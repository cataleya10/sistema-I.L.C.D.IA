using System.Net.Http.Headers;
using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Application.DTOs;
using Application.Interfaces;
using Domain.Enums;
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
        var pyRaw = JsonSerializer.Deserialize<PythonRawResponse>(raw, _jsonOptions);
        if (pyRaw is null)
        {
            throw new InvalidOperationException("La respuesta del motor IA es invalida.");
        }

        var result = MapPythonResponse(documentId, pyRaw);

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

    // ── Python → C# mapping ─────────────────────────────────────────────────

    private static readonly Dictionary<string, DocumentType> DocTypeMap = new(StringComparer.OrdinalIgnoreCase)
    {
        ["INE"] = DocumentType.Ine,
        ["CURP"] = DocumentType.Curp,
        ["ACTA_NACIMIENTO"] = DocumentType.ActaNacimiento,
        ["COMPROBANTE_DOMICILIO"] = DocumentType.ComprobanteDomicilio,
        ["NSS"] = DocumentType.Nss,
        ["DATOS_BANCARIOS"] = DocumentType.DatosBancarios,
        ["CONSTANCIA_SITUACION_FISCAL"] = DocumentType.ConstanciaSituacionFiscal,
        ["FACTURA"] = DocumentType.Factura,
        ["NOMINA"] = DocumentType.Factura,           // Nómina se trata como Factura
        ["GENERICO"] = DocumentType.Generico,
        ["UNKNOWN"] = DocumentType.Unknown,
    };

    private static DocumentProcessResponse MapPythonResponse(Guid documentId, PythonRawResponse py)
    {
        var docType = DocTypeMap.GetValueOrDefault(py.TipoDocumento ?? "", DocumentType.Unknown);

        var requiresReview = py.ValidationSummary?.RequiresReview ?? false;
        var status = py.Success == true && !requiresReview
            ? DocumentStatus.Ready
            : DocumentStatus.NeedsReview;

        var fields = (py.Campos ?? []).Select(c => new DocumentFieldResultDto(
            c.Key ?? "",
            c.Label ?? "",
            c.Value is { } v ? (v.ValueKind == JsonValueKind.String ? v.GetString() : v.ToString()) : null,
            (decimal)(c.Confidence ?? 0),
            c.IsValid ?? true,
            Array.Empty<string>(),
            null
        )).ToArray();

        var tables = (py.Tablas ?? []).Select(t =>
        {
            var canonicalRows = t.CanonicalRows ?? [];
            var allKeys = canonicalRows
                .SelectMany(r => r.Keys)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToArray();
            var columns = allKeys.Length > 0 ? allKeys : (t.HeadersDetected ?? []).ToArray();
            var rows = canonicalRows.Select(r =>
                (IReadOnlyDictionary<string, string?>)columns.ToDictionary(
                    col => col,
                    col => r.TryGetValue(col, out var val) ? val.ToString() : null,
                    StringComparer.OrdinalIgnoreCase)
            ).ToArray();
            return new ExtractedTableDto(
                columns,
                rows,
                (float)(py.ValidationSummary?.TableQualityScore ?? 0),
                rows.Length,
                null);
        }).ToArray();

        var meta = new DocumentProcessMeta(
            py.Metadata?.Pages ?? 0,
            py.Metadata?.OcrEngine ?? "none",
            py.Metadata?.PipelineVersion ?? "",
            py.Metadata?.ModelVersion ?? "",
            py.Metadata?.ProcessingTimeMs ?? 0
        );

        return new DocumentProcessResponse(
            documentId,
            status,
            docType,
            (decimal)(py.ConfidenceGlobal ?? 0),
            fields,
            tables,
            (py.Warnings ?? []).ToArray(),
            (py.Errors ?? []).ToArray(),
            meta
        );
    }

    // ── Raw Python JSON DTOs (snake_case match) ─────────────────────────────

    private sealed record PythonRawResponse
    {
        [JsonPropertyName("document_id")]
        public string? DocumentId { get; init; }

        [JsonPropertyName("tipo_documento")]
        public string? TipoDocumento { get; init; }

        [JsonPropertyName("success")]
        public bool? Success { get; init; }

        [JsonPropertyName("message")]
        public string? Message { get; init; }

        [JsonPropertyName("confidence_global")]
        public double? ConfidenceGlobal { get; init; }

        [JsonPropertyName("campos")]
        public List<PythonCampo>? Campos { get; init; }

        [JsonPropertyName("tablas")]
        public List<PythonTabla>? Tablas { get; init; }

        [JsonPropertyName("metadata")]
        public PythonMetadata? Metadata { get; init; }

        [JsonPropertyName("validation_summary")]
        public PythonValidationSummary? ValidationSummary { get; init; }

        [JsonPropertyName("warnings")]
        public List<string>? Warnings { get; init; }

        [JsonPropertyName("errors")]
        public List<string>? Errors { get; init; }

        [JsonPropertyName("error_code")]
        public string? ErrorCode { get; init; }

        [JsonPropertyName("stage")]
        public string? Stage { get; init; }
    }

    private sealed record PythonCampo
    {
        [JsonPropertyName("key")]
        public string? Key { get; init; }

        [JsonPropertyName("label")]
        public string? Label { get; init; }

        [JsonPropertyName("value")]
        public JsonElement? Value { get; init; }

        [JsonPropertyName("confidence")]
        public double? Confidence { get; init; }

        [JsonPropertyName("is_critical")]
        public bool? IsCritical { get; init; }

        [JsonPropertyName("is_valid")]
        public bool? IsValid { get; init; }
    }

    private sealed record PythonTabla
    {
        [JsonPropertyName("name")]
        public string? Name { get; init; }

        [JsonPropertyName("headers_detected")]
        public List<string>? HeadersDetected { get; init; }

        [JsonPropertyName("rows")]
        public List<List<string>>? Rows { get; init; }

        [JsonPropertyName("canonical_rows")]
        public List<Dictionary<string, JsonElement>>? CanonicalRows { get; init; }
    }

    private sealed record PythonMetadata
    {
        [JsonPropertyName("filename")]
        public string? Filename { get; init; }

        [JsonPropertyName("pages")]
        public int? Pages { get; init; }

        [JsonPropertyName("source")]
        public string? Source { get; init; }

        [JsonPropertyName("processing_time_ms")]
        public long? ProcessingTimeMs { get; init; }

        [JsonPropertyName("ocr_engine")]
        public string? OcrEngine { get; init; }

        [JsonPropertyName("pipeline_version")]
        public string? PipelineVersion { get; init; }

        [JsonPropertyName("model_version")]
        public string? ModelVersion { get; init; }
    }

    private sealed record PythonValidationSummary
    {
        [JsonPropertyName("coverage")]
        public double? Coverage { get; init; }

        [JsonPropertyName("critical_coverage")]
        public double? CriticalCoverage { get; init; }

        [JsonPropertyName("requires_review")]
        public bool? RequiresReview { get; init; }

        [JsonPropertyName("score_decision")]
        public string? ScoreDecision { get; init; }

        [JsonPropertyName("table_quality_score")]
        public double? TableQualityScore { get; init; }
    }
}

public sealed record PythonOcrResult(
    string? OcrText,
    int PagesProcessed,
    long ProcessingMs,
    string OcrEngine,
    DocumentProcessResponse? PythonResponse = null);
