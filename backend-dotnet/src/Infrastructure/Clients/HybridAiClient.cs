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
    private static readonly Dictionary<DocumentType, string[]> CriticalFieldsByType = new()
    {
        [DocumentType.Ine] = ["curp", "nombre", "fecha_nacimiento"],
        [DocumentType.Curp] = ["curp", "nombre"],
        [DocumentType.ActaNacimiento] = ["nombre", "fecha_nacimiento", "folio"],
        [DocumentType.ComprobanteDomicilio] = ["titular", "fecha_limite", "total"],
        [DocumentType.Nss] = ["nss", "nombre"],
        [DocumentType.DatosBancarios] = ["clabe", "titular"],
        [DocumentType.ConstanciaSituacionFiscal] = ["rfc", "razon_social"]
    };

    private readonly PythonAiClient _pythonClient;
    private readonly CSharpAiClient _csharpClient;
    private readonly ILogger<HybridAiClient> _logger;
    private readonly bool _enablePythonFallback;
    private readonly decimal _fallbackMinConfidence;

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
    }

    public async Task<DocumentProcessResponse> ProcessDocumentAsync(
        Guid documentId,
        string filePath,
        string? originalFilename,
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
                cancellationToken);
        }

        if (!_enablePythonFallback || !ShouldFallbackToPython(csharpResponse))
        {
            return csharpResponse;
        }

        try
        {
            var pythonResponse = await _pythonClient.ProcessDocumentAsync(
                documentId,
                filePath,
                originalFilename,
                cancellationToken);
            if (ShouldPreferPython(csharpResponse, pythonResponse))
            {
                _logger.LogInformation(
                    "Hybrid fallback selected Python extraction for {DocumentId}. C#Status={CSharpStatus} PythonStatus={PythonStatus}",
                    documentId,
                    csharpResponse.Status,
                    pythonResponse.Status);
                return pythonResponse;
            }
        }
        catch (Exception ex)
        {
            _logger.LogWarning(
                ex,
                "Hybrid fallback Python extraction failed for {DocumentId}. Keeping C# extraction.",
                documentId);
        }

        return csharpResponse;
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
}
