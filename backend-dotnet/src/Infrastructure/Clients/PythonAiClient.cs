using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Application.DTOs;
using Application.Interfaces;
using Microsoft.Extensions.Configuration;
using Shared.Json;

namespace Infrastructure.Clients;

public class PythonAiClient : IPythonAiClient
{
    private const string OcrOnlyOptionsJson = "{\"return_ocr_text\": true}";

    private readonly HttpClient _httpClient;
    private readonly JsonSerializerOptions _jsonOptions;
    private readonly string? _apiKey;

    public PythonAiClient(HttpClient httpClient, IConfiguration configuration)
    {
        _httpClient = httpClient;
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

        if (!string.IsNullOrWhiteSpace(_apiKey))
        {
            request.Headers.Add("X-Api-Key", _apiKey);
        }

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

    public async Task<PythonOcrResult> ExtractOcrAsync(
        Guid documentId,
        string filePath,
        string? originalFilename,
        CancellationToken cancellationToken)
    {
        var payload = await SendProcessRequestAsync(
            documentId,
            filePath,
            originalFilename,
            OcrOnlyOptionsJson,
            cancellationToken);

        return new PythonOcrResult(
            payload.OcrText,
            payload.Response.Meta.PagesProcessed,
            payload.Response.Meta.ProcessingMs,
            payload.Response.Meta.OcrEngine);
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

        if (!string.IsNullOrWhiteSpace(_apiKey))
        {
            request.Headers.Add("X-Api-Key", _apiKey);
        }

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

    private sealed record PythonProcessPayload(DocumentProcessResponse Response, string? OcrText);
}

public sealed record PythonOcrResult(
    string? OcrText,
    int PagesProcessed,
    long ProcessingMs,
    string OcrEngine);
