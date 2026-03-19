using System.Net.Http.Headers;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Application.DTOs;
using Application.Interfaces;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Shared.Json;

namespace Infrastructure.Clients;

public class PythonAiClient : IPythonAiClient
{
    private const string OcrOnlyOptionsJson = "{\"return_ocr_text\": true}";

    private readonly HttpClient _httpClient;
    private readonly JsonSerializerOptions _jsonOptions;
    private readonly string? _apiKey;
    private readonly IHttpContextAccessor _httpContextAccessor;

    public PythonAiClient(
        HttpClient httpClient,
        IConfiguration configuration,
        IHttpContextAccessor httpContextAccessor)
    {
        _httpClient = httpClient;
        _httpContextAccessor = httpContextAccessor;
        var baseUrl = configuration["PythonAi:BaseUrl"] ?? "http://localhost:8000";
        _httpClient.BaseAddress = new Uri(baseUrl);
        var timeoutSeconds = configuration.GetValue<int?>("PythonAi:TimeoutSeconds");
        _httpClient.Timeout = TimeSpan.FromSeconds(
            timeoutSeconds.HasValue && timeoutSeconds.Value > 0
                ? timeoutSeconds.Value
                : 300);
        _apiKey = configuration["PythonAi:ApiKey"];
        _jsonOptions = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            PropertyNameCaseInsensitive = true
        };
        _jsonOptions.Converters.Add(new JsonStringEnumConverter(new UpperSnakeCaseNamingPolicy()));
    }

    private string? GetCorrelationId()
    {
        var headers = _httpContextAccessor.HttpContext?.Request.Headers;
        if (headers is null) return null;
        return headers.TryGetValue("X-Correlation-Id", out var val) ? val.ToString() : null;
    }

    public async Task<DocumentProcessResponse> ProcessDocumentAsync(
        Guid documentId,
        string filePath,
        string? originalFilename,
        string? optionsJson,
        CancellationToken cancellationToken)
    {
        var payload = await SendProcessRequestAsync(
            documentId,
            filePath,
            originalFilename,
            optionsJson,
            cancellationToken);

        return payload.Response;
    }

    public async Task<OnlineLearningStatsDto> GetOnlineLearningStatsAsync(
        int recent,
        CancellationToken cancellationToken)
    {
        var safeRecent = Math.Clamp(recent, 0, 100);
        using var request = new HttpRequestMessage(
            HttpMethod.Get,
            $"/online-learning/stats?recent={safeRecent}");

        AddSharedHeaders(request);

        using var response = await _httpClient.SendAsync(request, cancellationToken);
        response.EnsureSuccessStatusCode();

        var raw = await response.Content.ReadAsStringAsync(cancellationToken);
        var result = JsonSerializer.Deserialize<OnlineLearningStatsDto>(raw, _jsonOptions);
        if (result is null)
        {
            throw new InvalidOperationException("La respuesta de estadisticas de entrenamiento es invalida.");
        }

        return result with
        {
            StatsPath = result.StatsPath ?? string.Empty,
            DatasetPath = result.DatasetPath ?? string.Empty,
            ModelPath = result.ModelPath ?? string.Empty,
            AliasPath = result.AliasPath ?? string.Empty,
            Totals = result.Totals ?? new OnlineLearningTotalsDto(0, 0, 0),
            ByReason = result.ByReason ?? new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase),
            ByDocumentType = result.ByDocumentType ?? new Dictionary<string, OnlineLearningByTypeDto>(StringComparer.OrdinalIgnoreCase),
            RecentEvents = result.RecentEvents ?? Array.Empty<OnlineLearningEventDto>()
        };
    }

    public async Task<AuditFolderResponseDto> AuditFolderAsync(
        AuditFolderRequestDto requestPayload,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(requestPayload);

        var payloadJson = JsonSerializer.Serialize(requestPayload, _jsonOptions);
        using var request = new HttpRequestMessage(HttpMethod.Post, "/diagnostics/audit-folder")
        {
            Content = new StringContent(payloadJson, Encoding.UTF8, "application/json")
        };

        AddSharedHeaders(request);

        using var response = await _httpClient.SendAsync(request, cancellationToken);
        var raw = await response.Content.ReadAsStringAsync(cancellationToken);
        if (!response.IsSuccessStatusCode)
        {
            var detail = ExtractErrorDetail(raw);
            if (response.StatusCode == HttpStatusCode.BadRequest)
            {
                throw new InvalidOperationException(detail ?? "La solicitud de auditoria es invalida.");
            }

            throw new HttpRequestException(
                detail ?? $"La solicitud de auditoria al motor IA fallo con estado {(int)response.StatusCode}.",
                null,
                response.StatusCode);
        }

        var result = JsonSerializer.Deserialize<AuditFolderResponseDto>(raw, _jsonOptions);
        if (result is null)
        {
            throw new InvalidOperationException("La respuesta de auditoria del motor IA es invalida.");
        }

        return result with
        {
            FolderPath = result.FolderPath ?? string.Empty,
            DocumentTypeCounts = result.DocumentTypeCounts ?? new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase),
            Documents = (result.Documents ?? Array.Empty<AuditDocumentSummaryDto>())
                .Select(document => document with
                {
                    Name = document.Name ?? string.Empty,
                    FilePath = document.FilePath ?? string.Empty,
                    Status = document.Status ?? string.Empty,
                    Warnings = document.Warnings ?? Array.Empty<string>(),
                    MappedFields = document.MappedFields ?? new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
                })
                .ToArray()
        };
    }

    public async Task<PythonOcrResult> ExtractOcrAsync(
        Guid documentId,
        string filePath,
        string? originalFilename,
        string? optionsJson,
        CancellationToken cancellationToken)
    {
        var mergedOptions = MergeOptionsWithOcrFlag(optionsJson);
        var payload = await SendProcessRequestAsync(
            documentId,
            filePath,
            originalFilename,
            mergedOptions,
            cancellationToken);

        return new PythonOcrResult(
            payload.OcrText,
            payload.Response.Meta.PagesProcessed,
            payload.Response.Meta.ProcessingMs,
            payload.Response.Meta.OcrEngine,
            payload.Response);
    }

    private static string MergeOptionsWithOcrFlag(string? userOptionsJson)
    {
        if (string.IsNullOrWhiteSpace(userOptionsJson))
            return "{\"return_ocr_text\":true}";
        var trimmed = userOptionsJson.Trim();
        if (trimmed.StartsWith("{", StringComparison.Ordinal) && trimmed.EndsWith("}", StringComparison.Ordinal))
            return "{\"return_ocr_text\":true," + trimmed[1..];
        return "{\"return_ocr_text\":true}";
    }

    private async Task<PythonProcessPayload> SendProcessRequestAsync(
        Guid documentId,
        string filePath,
        string? originalFilename,
        string? optionsJson,
        CancellationToken cancellationToken)
    {
        await using var fileStream = File.OpenRead(filePath);
        using var content = new MultipartFormDataContent();
        var fileContent = new StreamContent(fileStream);
        fileContent.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
        content.Add(fileContent, "file", Path.GetFileName(filePath));
        content.Add(new StringContent(documentId.ToString()), "document_id");
        content.Add(new StringContent("web"), "source");
        if (!string.IsNullOrWhiteSpace(originalFilename))
        {
            content.Add(new StringContent(originalFilename), "original_filename");
        }

        if (!string.IsNullOrWhiteSpace(optionsJson))
        {
            content.Add(new StringContent(optionsJson, Encoding.UTF8, "application/json"), "options");
        }

        using var request = new HttpRequestMessage(HttpMethod.Post, "/process-document")
        {
            Content = content
        };

        AddSharedHeaders(request);

        using var response = await _httpClient.SendAsync(request, cancellationToken);
        response.EnsureSuccessStatusCode();

        var raw = await response.Content.ReadAsStringAsync(cancellationToken);
        var result = JsonSerializer.Deserialize<DocumentProcessResponse>(raw, _jsonOptions);
        if (result is null)
        {
            throw new InvalidOperationException("La respuesta del motor IA es invalida.");
        }

        string? ocrText = null;
        using var json = JsonDocument.Parse(raw);
        if (json.RootElement.TryGetProperty("ocr_text", out var ocrElement) && ocrElement.ValueKind == JsonValueKind.String)
        {
            ocrText = ocrElement.GetString();
        }

        return new PythonProcessPayload(result, ocrText);
    }

    private void AddSharedHeaders(HttpRequestMessage request)
    {
        if (!string.IsNullOrWhiteSpace(_apiKey))
        {
            request.Headers.Add("X-Api-Key", _apiKey);
        }

        var correlationId = GetCorrelationId();
        if (!string.IsNullOrWhiteSpace(correlationId))
        {
            request.Headers.Add("X-Correlation-Id", correlationId);
        }
    }

    private static string? ExtractErrorDetail(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
        {
            return null;
        }

        try
        {
            using var json = JsonDocument.Parse(raw);
            if (!json.RootElement.TryGetProperty("detail", out var detailElement))
            {
                return null;
            }

            return detailElement.ValueKind switch
            {
                JsonValueKind.String => detailElement.GetString(),
                JsonValueKind.Array => string.Join("; ", detailElement.EnumerateArray().Select(item => item.ToString())),
                _ => detailElement.ToString()
            };
        }
        catch
        {
            return null;
        }
    }

    private sealed record PythonProcessPayload(DocumentProcessResponse Response, string? OcrText);
}

public sealed record PythonOcrResult(
    string? OcrText,
    int PagesProcessed,
    long ProcessingMs,
    string OcrEngine,
    DocumentProcessResponse? PythonResponse = null);
