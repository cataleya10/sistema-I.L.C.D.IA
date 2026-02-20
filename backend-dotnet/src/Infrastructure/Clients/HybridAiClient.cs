using Application.DTOs;
using Application.Interfaces;
using Domain.Enums;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using System.Text.RegularExpressions;

namespace Infrastructure.Clients;

public sealed class HybridAiClient : IPythonAiClient
{
    private static readonly Regex ThreeOrMoreDigitsRegex = new(@"\d{3,}", RegexOptions.Compiled);
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
        try
        {
            var ocr = await _pythonClient.ExtractOcrAsync(
                documentId,
                filePath,
                originalFilename,
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

        var shouldFetchPython = _alwaysMergePythonFields
            || (_enablePythonFallback && ShouldFallbackToPython(csharpResponse));
        if (!shouldFetchPython)
        {
            return ApplyDocumentTypeFieldPolicy(csharpResponse);
        }

        try
        {
            var pythonResponse = await _pythonClient.ProcessDocumentAsync(
                documentId,
                filePath,
                originalFilename,
                optionsJson,
                cancellationToken);
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
        catch (Exception ex)
        {
            _logger.LogWarning(
                ex,
                "Hybrid fallback Python extraction failed for {DocumentId}. Keeping C# extraction.",
                documentId);
        }

        return ApplyDocumentTypeFieldPolicy(csharpResponse);
    }

    public Task<OnlineLearningStatsDto> GetOnlineLearningStatsAsync(
        int recent,
        CancellationToken cancellationToken)
    {
        return _pythonClient.GetOnlineLearningStatsAsync(recent, cancellationToken);
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

        return preferCandidateOnTie;
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
