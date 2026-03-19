using Application.DTOs;
using Application.Interfaces;
using Domain.Enums;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Infrastructure.Clients;

public sealed class HybridAiClient : IPythonAiClient
{
    private static readonly Regex ThreeOrMoreDigitsRegex = new(@"\d{3,}", RegexOptions.Compiled);
    private static readonly Regex NameTokenRegex = new(@"[A-ZÑÁÉÍÓÚÜ]+", RegexOptions.Compiled);
    private static readonly HashSet<string> NameParticles = new(StringComparer.Ordinal)
    {
        "DE", "DEL", "LA", "LAS", "LOS", "Y", "MC", "VAN", "VON"
    };
    private static readonly string[] StructuredTableHeaderHints =
    [
        "CUENTA",
        "REFERENCIA",
        "IMPORTE",
        "NOMBRE",
        "APELLIDO",
        "ESTATUS",
        "CONCEPTO"
    ];
    private static readonly Dictionary<string, string> KeyAliases = new(StringComparer.OrdinalIgnoreCase)
    {
        ["direccion"] = "domicilio",
        ["numero_cuenta"] = "cuenta",
        ["codigo_postal"] = "cp"
    };

    private static readonly Dictionary<string, string> CanonicalLabels = new(StringComparer.OrdinalIgnoreCase)
    {
        ["domicilio"] = "Domicilio",
        ["cuenta"] = "Cuenta",
        ["cp"] = "CP"
    };

    private static readonly Dictionary<DocumentType, string[]> CriticalFieldsByType = new()
    {
        [DocumentType.Ine] = ["curp", "nombre", "fecha_nacimiento"],
        [DocumentType.Curp] = ["curp", "nombre"],
        [DocumentType.ActaNacimiento] = ["nombre", "fecha_nacimiento", "folio"],
        [DocumentType.ComprobanteDomicilio] = ["titular", "fecha_limite", "total"],
        [DocumentType.Nss] = ["nss", "nombre"],
        [DocumentType.DatosBancarios] = ["clabe", "titular"],
        [DocumentType.Factura] = ["tabla_celdas"],
        [DocumentType.ConstanciaSituacionFiscal] = ["rfc", "razon_social"]
    };

    private readonly PythonAiClient _pythonClient;
    private readonly CSharpAiClient _csharpClient;
    private readonly ILogger<HybridAiClient> _logger;
    private readonly bool _enablePythonFallback;
    private readonly decimal _fallbackMinConfidence;
    private readonly bool _alwaysMergePythonFields;

    public HybridAiClient(
        PythonAiClient pythonClient,
        CSharpAiClient csharpClient,
        IConfiguration configuration,
        ILogger<HybridAiClient> logger)
    {
        _pythonClient = pythonClient;
        _csharpClient = csharpClient;
        _logger = logger;
        _enablePythonFallback = configuration.GetValue<bool?>("AiEngine:Hybrid:EnablePythonFallback") ?? true;
        _fallbackMinConfidence = configuration.GetValue<decimal?>("AiEngine:Hybrid:FallbackMinConfidence") ?? 0.80m;
        _alwaysMergePythonFields = configuration.GetValue<bool?>("AiEngine:Hybrid:AlwaysMergePythonFields") ?? true;
    }

    public async Task<DocumentProcessResponse> ProcessDocumentAsync(
        Guid documentId,
        string filePath,
        string? originalFilename,
        string? optionsJson,
        CancellationToken cancellationToken)
    {
        DocumentProcessResponse csharpResponse;
        PythonOcrResult? ocr = null;
        try
        {
            ocr = await _pythonClient.ExtractOcrAsync(
                documentId,
                filePath,
                originalFilename,
                optionsJson,
                cancellationToken);

            if (string.IsNullOrWhiteSpace(ocr.OcrText))
            {
                _logger.LogWarning(
                    "Hybrid OCR returned empty text for {DocumentId}. Falling back to local C# text extraction.",
                    documentId);
                csharpResponse = await _csharpClient.ProcessDocumentAsync(
                    documentId,
                    filePath,
                    originalFilename,
                    optionsJson,
                    cancellationToken);
            }
            else
            {
                csharpResponse = await _csharpClient.ProcessTextAsync(
                    documentId,
                    ocr.OcrText,
                    originalFilename,
                    ocr.OcrEngine,
                    ocr.PagesProcessed,
                    ocr.ProcessingMs,
                    optionsJson,
                    cancellationToken);
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(
                ex,
                "Hybrid OCR request failed for {DocumentId}. Falling back to local C# extraction.",
                documentId);
            csharpResponse = await _csharpClient.ProcessDocumentAsync(
                documentId,
                filePath,
                originalFilename,
                optionsJson,
                cancellationToken);
        }

        // Usar la respuesta Python ya obtenida en el primer call (si tiene campos extraídos)
        DocumentProcessResponse? pythonResponse =
            ocr?.PythonResponse?.Fields.Count > 0 ? ocr.PythonResponse : null;

        // Solo hacer una segunda llamada a Python si el primer call no retornó campos
        if (pythonResponse is null)
        {
            var shouldFetchPython = _alwaysMergePythonFields
                || (_enablePythonFallback && ShouldFallbackToPython(csharpResponse));
            if (shouldFetchPython)
            {
                try
                {
                    pythonResponse = await _pythonClient.ProcessDocumentAsync(
                        documentId,
                        filePath,
                        originalFilename,
                        optionsJson,
                        cancellationToken);
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(
                        ex,
                        "Hybrid fallback Python extraction failed for {DocumentId}. Keeping C# extraction.",
                        documentId);
                }
            }
        }

        if (pythonResponse is not null)
        {
            var shouldPreferPython = _enablePythonFallback && ShouldPreferPython(csharpResponse, pythonResponse);
            var preferred = shouldPreferPython ? pythonResponse : csharpResponse;
            var secondary = shouldPreferPython ? csharpResponse : pythonResponse;

            if (shouldPreferPython)
            {
                _logger.LogInformation(
                    "Hybrid fallback selected Python extraction for {DocumentId}. C#Status={CSharpStatus} PythonStatus={PythonStatus}",
                    documentId,
                    csharpResponse.Status,
                    pythonResponse.Status);
            }

            if (_alwaysMergePythonFields)
            {
                return ApplyDocumentTypeFieldPolicy(MergeResponses(preferred, secondary));
            }

            return ApplyDocumentTypeFieldPolicy(preferred);
        }

        return ApplyDocumentTypeFieldPolicy(csharpResponse);
    }

    public Task<OnlineLearningStatsDto> GetOnlineLearningStatsAsync(
        int recent,
        CancellationToken cancellationToken)
    {
        return _pythonClient.GetOnlineLearningStatsAsync(recent, cancellationToken);
    }

    public Task<AuditFolderResponseDto> AuditFolderAsync(
        AuditFolderRequestDto request,
        CancellationToken cancellationToken)
    {
        return _pythonClient.AuditFolderAsync(request, cancellationToken);
    }

    private static DocumentProcessResponse MergeResponses(
        DocumentProcessResponse preferred,
        DocumentProcessResponse secondary)
    {
        var mergedFields = MergeFields(preferred.Fields, secondary.Fields);
        var mergedWarnings = preferred.Warnings
            .Concat(secondary.Warnings)
            .Where(w => !string.IsNullOrWhiteSpace(w))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        var mergedErrors = preferred.Errors
            .Concat(secondary.Errors)
            .Where(e => !string.IsNullOrWhiteSpace(e))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
        var mergedPipeline = preferred.Meta.PipelineVersion.Contains("hybrid-merge-v1", StringComparison.OrdinalIgnoreCase)
            ? preferred.Meta.PipelineVersion
            : $"{preferred.Meta.PipelineVersion}+hybrid-merge-v1";
        var mergedMeta = preferred.Meta with { PipelineVersion = mergedPipeline };

        return new DocumentProcessResponse(
            preferred.DocumentId,
            preferred.Status,
            preferred.DocumentType,
            Math.Max(preferred.Confidence, secondary.Confidence),
            mergedFields,
            mergedWarnings,
            mergedErrors,
            mergedMeta);
    }

    private static IReadOnlyList<DocumentFieldResultDto> MergeFields(
        IReadOnlyList<DocumentFieldResultDto> preferred,
        IReadOnlyList<DocumentFieldResultDto> secondary)
    {
        var merged = new Dictionary<string, DocumentFieldResultDto>(StringComparer.OrdinalIgnoreCase);

        Absorb(merged, preferred, preferIncomingOnTie: true);
        Absorb(merged, secondary, preferIncomingOnTie: false);

        return merged.Values
            .OrderBy(f => f.Key, StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    private static void Absorb(
        Dictionary<string, DocumentFieldResultDto> merged,
        IEnumerable<DocumentFieldResultDto> incoming,
        bool preferIncomingOnTie)
    {
        foreach (var rawField in incoming)
        {
            var field = NormalizeFieldKey(rawField);
            if (!merged.TryGetValue(field.Key, out var existing))
            {
                merged[field.Key] = field;
                continue;
            }

            if (ShouldReplaceField(existing, field, preferIncomingOnTie))
            {
                merged[field.Key] = field;
            }
        }
    }

    private static DocumentFieldResultDto NormalizeFieldKey(DocumentFieldResultDto field)
    {
        if (string.IsNullOrWhiteSpace(field.Key))
        {
            return field;
        }

        var key = field.Key.Trim();
        if (!KeyAliases.TryGetValue(key, out var canonical))
        {
            return field with { Key = key };
        }

        var label = CanonicalLabels.TryGetValue(canonical, out var canonicalLabel)
            ? canonicalLabel
            : field.Label;

        return field with { Key = canonical, Label = label };
    }

    private static bool ShouldReplaceField(
        DocumentFieldResultDto current,
        DocumentFieldResultDto candidate,
        bool preferCandidateOnTie)
    {
        var currentHasValue = !string.IsNullOrWhiteSpace(current.Value);
        var candidateHasValue = !string.IsNullOrWhiteSpace(candidate.Value);
        if (currentHasValue != candidateHasValue)
        {
            return candidateHasValue;
        }

        if (current.Valid != candidate.Valid)
        {
            return candidate.Valid;
        }

        if (IsNameLikeFieldKey(current.Key) && string.Equals(current.Key, candidate.Key, StringComparison.OrdinalIgnoreCase))
        {
            var currentNameQuality = ScoreNameFieldValue(current.Value);
            var candidateNameQuality = ScoreNameFieldValue(candidate.Value);
            if (candidateNameQuality >= currentNameQuality + 12)
            {
                return true;
            }
            if (currentNameQuality >= candidateNameQuality + 12)
            {
                return false;
            }
        }

        if (candidate.Confidence != current.Confidence)
        {
            return candidate.Confidence > current.Confidence;
        }

        var currentErrors = current.ValidationErrors.Count;
        var candidateErrors = candidate.ValidationErrors.Count;
        if (currentErrors != candidateErrors)
        {
            return candidateErrors < currentErrors;
        }

        if (IsStructuredFieldKey(current.Key) && string.Equals(current.Key, candidate.Key, StringComparison.OrdinalIgnoreCase))
        {
            var currentQuality = ScoreStructuredFieldValue(current.Key, current.Value);
            var candidateQuality = ScoreStructuredFieldValue(candidate.Key, candidate.Value);
            if (candidateQuality != currentQuality)
            {
                return candidateQuality > currentQuality;
            }
        }

        return preferCandidateOnTie;
    }

    private static bool IsNameLikeFieldKey(string? key)
    {
        return string.Equals(key, "nombre", StringComparison.OrdinalIgnoreCase)
            || string.Equals(key, "titular", StringComparison.OrdinalIgnoreCase)
            || string.Equals(key, "razon_social", StringComparison.OrdinalIgnoreCase);
    }

    private static int ScoreNameFieldValue(string? rawValue)
    {
        if (string.IsNullOrWhiteSpace(rawValue))
        {
            return int.MinValue / 4;
        }

        var value = rawValue.Trim().ToUpperInvariant();
        var score = 0;

        if (value.Contains(':'))
        {
            score -= 40;
        }
        if (ThreeOrMoreDigitsRegex.IsMatch(value))
        {
            score -= 30;
        }

        var tokens = NameTokenRegex.Matches(value)
            .Select(match => match.Value)
            .Where(token => !string.IsNullOrWhiteSpace(token))
            .ToArray();
        if (tokens.Length == 0)
        {
            return -120;
        }

        score += tokens.Length * 12;
        if (tokens.Length >= 3)
        {
            score += 20;
        }
        if (tokens.Length <= 2)
        {
            score -= 15;
        }

        foreach (var token in tokens)
        {
            score += Math.Min(token.Length, 8);
            if (token.Length <= 2 && !NameParticles.Contains(token))
            {
                score -= 9;
            }
        }

        return score;
    }

    private bool ShouldFallbackToPython(DocumentProcessResponse csharpResponse)
    {
        if (csharpResponse.Status != DocumentStatus.Ready)
        {
            return true;
        }

        if (HasCriticalGapsOrSuspiciousValues(csharpResponse))
        {
            return true;
        }

        if (csharpResponse.Confidence < _fallbackMinConfidence)
        {
            return true;
        }

        return csharpResponse.Fields.Count == 0;
    }

    private bool ShouldPreferPython(
        DocumentProcessResponse csharpResponse,
        DocumentProcessResponse pythonResponse)
    {
        var csharpTableQuality = GetStructuredFieldQuality(csharpResponse, "tabla_celdas");
        var pythonTableQuality = GetStructuredFieldQuality(pythonResponse, "tabla_celdas");
        if (pythonTableQuality > csharpTableQuality + 25)
        {
            return true;
        }

        var csharpDetailQuality = GetStructuredFieldQuality(csharpResponse, "pago_detalle");
        var pythonDetailQuality = GetStructuredFieldQuality(pythonResponse, "pago_detalle");
        if (pythonDetailQuality > csharpDetailQuality + 20)
        {
            return true;
        }

        if (pythonResponse.Status == DocumentStatus.Ready
            && (csharpResponse.DocumentType == DocumentType.ActaNacimiento
                || pythonResponse.DocumentType == DocumentType.ActaNacimiento))
        {
            return true;
        }

        if (pythonResponse.Status == DocumentStatus.Ready && csharpResponse.Status != DocumentStatus.Ready)
        {
            return true;
        }

        if (pythonResponse.Status == csharpResponse.Status && pythonResponse.Confidence > csharpResponse.Confidence)
        {
            return true;
        }

        return pythonResponse.Status == DocumentStatus.Ready
            && pythonResponse.Confidence >= _fallbackMinConfidence
            && csharpResponse.Confidence < _fallbackMinConfidence;
    }

    private static bool IsStructuredFieldKey(string? key)
    {
        return string.Equals(key, "tabla_celdas", StringComparison.OrdinalIgnoreCase)
            || string.Equals(key, "pago_detalle", StringComparison.OrdinalIgnoreCase);
    }

    private static int GetStructuredFieldQuality(DocumentProcessResponse response, string key)
    {
        var field = response.Fields.FirstOrDefault(f => string.Equals(f.Key, key, StringComparison.OrdinalIgnoreCase));
        if (field is null)
        {
            return int.MinValue / 4;
        }

        return ScoreStructuredFieldValue(field.Key, field.Value);
    }

    private static int ScoreStructuredFieldValue(string key, string? rawValue)
    {
        if (string.IsNullOrWhiteSpace(rawValue))
        {
            return int.MinValue / 4;
        }

        if (string.Equals(key, "tabla_celdas", StringComparison.OrdinalIgnoreCase))
        {
            return ScoreTablaCeldasPayload(rawValue);
        }

        if (string.Equals(key, "pago_detalle", StringComparison.OrdinalIgnoreCase))
        {
            return ScorePagoDetallePayload(rawValue);
        }

        return 0;
    }

    private static int ScoreTablaCeldasPayload(string rawValue)
    {
        try
        {
            using var document = JsonDocument.Parse(rawValue);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                return -40;
            }

            var score = 0;
            var source = ReadString(root, "source");
            if (string.Equals(source, "text_lines_csharp", StringComparison.OrdinalIgnoreCase))
            {
                score -= 30;
            }

            var canonicalRows = CountArray(root, "canonical_rows");
            if (canonicalRows == 0 && TryGetProperty(root, "table", out var tableElement))
            {
                canonicalRows = CountArray(tableElement, "canonical_rows");
            }
            if (canonicalRows > 0)
            {
                score += 220 + (canonicalRows * 35);
            }

            var rowsCount = CountArray(root, "rows");
            JsonElement rowsElement;
            if (TryGetProperty(root, "rows", out rowsElement) && rowsElement.ValueKind == JsonValueKind.Array)
            {
                // no-op
            }
            else if (TryGetProperty(root, "table", out tableElement)
                     && TryGetProperty(tableElement, "rows", out rowsElement)
                     && rowsElement.ValueKind == JsonValueKind.Array)
            {
                rowsCount = rowsElement.GetArrayLength();
            }
            else
            {
                rowsElement = default;
            }

            if (rowsCount > 0)
            {
                var dataRows = Math.Max(0, rowsCount - 1);
                score += dataRows * 12;
            }

            if (rowsElement.ValueKind == JsonValueKind.Array
                && rowsElement.GetArrayLength() > 0
                && rowsElement[0].ValueKind == JsonValueKind.Array)
            {
                var headerCells = rowsElement[0]
                    .EnumerateArray()
                    .Select(cell => cell.ValueKind == JsonValueKind.String ? cell.GetString() ?? string.Empty : cell.ToString())
                    .Where(cell => !string.IsNullOrWhiteSpace(cell))
                    .Select(cell => cell.Trim().ToUpperInvariant())
                    .ToArray();

                var joined = string.Join(" ", headerCells);
                var hintHits = StructuredTableHeaderHints.Count(hint => joined.Contains(hint, StringComparison.Ordinal));
                score += hintHits * 8;

                var repeatedHeaderCells = headerCells.Count(IsRepeatedHeaderCell);
                score -= repeatedHeaderCells * 12;
            }

            return score;
        }
        catch
        {
            return -40;
        }
    }

    private static int ScorePagoDetallePayload(string rawValue)
    {
        try
        {
            using var document = JsonDocument.Parse(rawValue);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                return -40;
            }

            var score = 0;
            if (TryGetProperty(root, "metadata", out var metadataElement) && metadataElement.ValueKind == JsonValueKind.Object)
            {
                var metadataCount = metadataElement.EnumerateObject()
                    .Count(property => !string.IsNullOrWhiteSpace(property.Value.ToString()));
                score += Math.Min(40, metadataCount * 3);
            }

            if (TryGetProperty(root, "bank", out var bankElement) && bankElement.ValueKind == JsonValueKind.String)
            {
                var bank = bankElement.GetString();
                if (!string.IsNullOrWhiteSpace(bank) && !string.Equals(bank, "DESCONOCIDO", StringComparison.OrdinalIgnoreCase))
                {
                    score += 12;
                }
            }

            if (TryGetProperty(root, "table", out var tableElement) && tableElement.ValueKind == JsonValueKind.Object)
            {
                var canonicalRows = CountArray(tableElement, "canonical_rows");
                var rows = CountArray(tableElement, "rows");

                if (canonicalRows > 0)
                {
                    score += 180 + (canonicalRows * 30);
                }

                if (rows > 0)
                {
                    score += rows * 10;
                }
            }

            return score;
        }
        catch
        {
            return -40;
        }
    }

    private static int CountArray(JsonElement parent, string propertyName)
    {
        if (TryGetProperty(parent, propertyName, out var arrayElement) && arrayElement.ValueKind == JsonValueKind.Array)
        {
            return arrayElement.GetArrayLength();
        }

        return 0;
    }

    private static bool TryGetProperty(JsonElement parent, string propertyName, out JsonElement value)
    {
        value = default;
        return parent.ValueKind == JsonValueKind.Object
            && parent.TryGetProperty(propertyName, out value);
    }

    private static string ReadString(JsonElement parent, string propertyName)
    {
        if (TryGetProperty(parent, propertyName, out var value) && value.ValueKind == JsonValueKind.String)
        {
            return value.GetString() ?? string.Empty;
        }

        return string.Empty;
    }

    private static bool IsRepeatedHeaderCell(string value)
    {
        var tokens = value
            .Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Select(token => token.ToUpperInvariant())
            .ToArray();

        if (tokens.Length < 2)
        {
            return false;
        }

        if (tokens.All(token => token == tokens[0]))
        {
            return true;
        }

        if (tokens.Length % 2 == 0)
        {
            var half = tokens.Length / 2;
            return tokens.Take(half).SequenceEqual(tokens.Skip(half));
        }

        return false;
    }

    private static bool HasCriticalGapsOrSuspiciousValues(DocumentProcessResponse response)
    {
        if (response.DocumentType == DocumentType.Unknown)
        {
            return true;
        }

        if (CriticalFieldsByType.TryGetValue(response.DocumentType, out var required))
        {
            foreach (var key in required)
            {
                var field = response.Fields.FirstOrDefault(x => string.Equals(x.Key, key, StringComparison.OrdinalIgnoreCase));
                if (field is null || !field.Valid || string.IsNullOrWhiteSpace(field.Value))
                {
                    return true;
                }
            }
        }

        var nameLikeKeys = new[] { "titular", "nombre", "razon_social" };
        foreach (var key in nameLikeKeys)
        {
            var field = response.Fields.FirstOrDefault(x => string.Equals(x.Key, key, StringComparison.OrdinalIgnoreCase));
            if (field is null || string.IsNullOrWhiteSpace(field.Value))
            {
                continue;
            }

            var value = field.Value.Trim();
            if (value.Contains(':') || ThreeOrMoreDigitsRegex.IsMatch(value))
            {
                return true;
            }
        }

        return false;
    }

    private static DocumentProcessResponse ApplyDocumentTypeFieldPolicy(DocumentProcessResponse response)
    {
        if (response.DocumentType != DocumentType.Factura)
        {
            return response;
        }

        var filteredFields = response.Fields
            .Where(field => string.Equals(field.Key, "tabla_celdas", StringComparison.OrdinalIgnoreCase))
            .ToArray();

        var hasValidTable = filteredFields.Any(field => field.Valid && !string.IsNullOrWhiteSpace(field.Value));
        var status = hasValidTable ? response.Status : DocumentStatus.NeedsReview;

        return new DocumentProcessResponse(
            response.DocumentId,
            status,
            response.DocumentType,
            response.Confidence,
            filteredFields,
            response.Warnings,
            response.Errors,
            response.Meta);
    }
}
