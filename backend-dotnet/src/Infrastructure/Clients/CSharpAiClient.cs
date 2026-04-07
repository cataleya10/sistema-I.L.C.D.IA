using System.Globalization;
using System.IO.Compression;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Application.DTOs;
using Application.Interfaces;
using Domain.Enums;

namespace Infrastructure.Clients;

public sealed class CSharpAiClient : IPythonAiClient
{
    private static readonly Regex CurpRegex = new(@"\b[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b", RegexOptions.Compiled | RegexOptions.IgnoreCase);
    private static readonly Regex RfcRegex = new(@"\b[A-Z&]{3,4}\d{6}[A-Z0-9]{3}\b", RegexOptions.Compiled | RegexOptions.IgnoreCase);
    private static readonly Regex DateRegex = new(
        @"\b\d{1,2}[/-](?:ENE|FEB|MAR|ABR|MAY|JUN|JUL|AGO|SEP|OCT|NOV|DIC|[A-Z]{3,4})[/-]\d{2,4}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        RegexOptions.Compiled | RegexOptions.IgnoreCase);
    private static readonly Regex AmountRegex = new(@"\b\d{1,3}(?:,\d{3})*(?:\.\d{2})\b", RegexOptions.Compiled);

    public async Task<DocumentProcessResponse> ProcessDocumentAsync(
        Guid documentId,
        string filePath,
        string? originalFilename,
        string? optionsJson,
        CancellationToken cancellationToken)
    {
        var started = DateTime.UtcNow;
        var rawText = await ReadDocumentTextAsync(filePath, cancellationToken);
        var forcedType = ResolveForcedDocumentType(optionsJson);
        return BuildResponseFromRawText(
            documentId,
            rawText,
            originalFilename ?? filePath,
            started,
            "csharp-local",
            "csharp-pipeline-v2",
            1,
            0,
            forcedType);
    }

    public Task<OnlineLearningStatsDto> GetOnlineLearningStatsAsync(
        int recent,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        _ = recent;
        return Task.FromResult(
            new OnlineLearningStatsDto(
                false,
                string.Empty,
                string.Empty,
                string.Empty,
                string.Empty,
                null,
                0,
                new OnlineLearningTotalsDto(0, 0, 0),
                new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
                {
                    ["not_supported_by_csharp_engine"] = 1
                },
                new Dictionary<string, OnlineLearningByTypeDto>(StringComparer.OrdinalIgnoreCase),
                null,
                Array.Empty<OnlineLearningEventDto>()));
    }

    public Task<AuditFolderResponseDto> AuditFolderAsync(
        AuditFolderRequestDto request,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        _ = request;
        throw new NotSupportedException("La auditoria de carpetas requiere el motor Python habilitado.");
    }

    public Task<DocumentProcessResponse> ProcessTextAsync(
        Guid documentId,
        string rawText,
        string? originalFilename,
        string ocrEngine,
        int pagesProcessed,
        long upstreamProcessingMs,
        string? optionsJson,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var started = DateTime.UtcNow;
        var forcedType = ResolveForcedDocumentType(optionsJson);
        var response = BuildResponseFromRawText(
            documentId,
            rawText,
            originalFilename ?? string.Empty,
            started,
            string.IsNullOrWhiteSpace(ocrEngine) ? "python-ocr" : ocrEngine,
            "csharp-hybrid-v1",
            pagesProcessed <= 0 ? 1 : pagesProcessed,
            upstreamProcessingMs < 0 ? 0 : upstreamProcessingMs,
            forcedType);
        return Task.FromResult(response);
    }

    private static DocumentProcessResponse BuildResponseFromRawText(
        Guid documentId,
        string rawText,
        string filenameOrPath,
        DateTime started,
        string ocrEngine,
        string pipelineVersion,
        int pagesProcessed,
        long upstreamProcessingMs,
        DocumentType? forcedType)
    {
        var normalizedText = Normalize(rawText);
        var filenameHint = Normalize(Path.GetFileNameWithoutExtension(filenameOrPath ?? string.Empty));

        var type = forcedType ?? DetectDocumentType(filenameHint, normalizedText);
        var fields = ExtractFields(type, normalizedText, filenameHint);
        var warnings = BuildWarnings(type, rawText, fields);
        var status = ResolveStatus(type, fields);
        var confidence = ResolveConfidence(fields, status);
        var elapsedMs = upstreamProcessingMs + (long)(DateTime.UtcNow - started).TotalMilliseconds;

        return new DocumentProcessResponse(
            documentId,
            status,
            type,
            confidence,
            fields,
            Array.Empty<ExtractedTableDto>(),
            warnings,
            Array.Empty<string>(),
            new DocumentProcessMeta(
                pagesProcessed <= 0 ? 1 : pagesProcessed,
                ocrEngine,
                pipelineVersion,
                "regex-v2",
                elapsedMs));
    }

    private static DocumentStatus ResolveStatus(DocumentType type, IReadOnlyList<DocumentFieldResultDto> fields)
    {
        if (type == DocumentType.Unknown || fields.Count == 0)
        {
            return DocumentStatus.NeedsReview;
        }

        static bool Has(IReadOnlyList<DocumentFieldResultDto> list, string key)
        {
            var field = list.FirstOrDefault(f => string.Equals(f.Key, key, StringComparison.OrdinalIgnoreCase));
            if (field is null)
            {
                return false;
            }

            return field.Valid && !string.IsNullOrWhiteSpace(field.Value);
        }

        var validCount = fields.Count(f => f.Valid && !string.IsNullOrWhiteSpace(f.Value));

        return type switch
        {
            DocumentType.Ine =>
                (Has(fields, "curp") && Has(fields, "clave_elector"))
                || (Has(fields, "nombre") && Has(fields, "curp") && Has(fields, "fecha_nacimiento"))
                    ? DocumentStatus.Ready
                    : DocumentStatus.NeedsReview,

            DocumentType.Curp =>
                (Has(fields, "curp") && Has(fields, "nombre"))
                    ? DocumentStatus.Ready
                    : DocumentStatus.NeedsReview,

            DocumentType.ActaNacimiento =>
                (Has(fields, "nombre") && Has(fields, "fecha_nacimiento") && (Has(fields, "folio") || Has(fields, "numero_acta")))
                    ? DocumentStatus.Ready
                    : DocumentStatus.NeedsReview,

            DocumentType.ComprobanteDomicilio =>
                (validCount >= 3 && (Has(fields, "proveedor") || Has(fields, "total") || Has(fields, "fecha_limite")))
                    ? DocumentStatus.Ready
                    : DocumentStatus.NeedsReview,

            DocumentType.Nss =>
                ((Has(fields, "nss") && Has(fields, "nombre")) || (Has(fields, "nss") && Has(fields, "curp")))
                    ? DocumentStatus.Ready
                    : DocumentStatus.NeedsReview,

            DocumentType.DatosBancarios =>
                (Has(fields, "clabe") && Has(fields, "titular"))
                    ? DocumentStatus.Ready
                    : DocumentStatus.NeedsReview,

            DocumentType.Factura =>
                Has(fields, "tabla_celdas")
                    ? DocumentStatus.Ready
                    : DocumentStatus.NeedsReview,

            DocumentType.ConstanciaSituacionFiscal =>
                (Has(fields, "rfc") && (Has(fields, "razon_social") || Has(fields, "regimen")))
                    ? DocumentStatus.Ready
                    : DocumentStatus.NeedsReview,

            _ => DocumentStatus.NeedsReview
        };
    }

    private static decimal ResolveConfidence(IReadOnlyList<DocumentFieldResultDto> fields, DocumentStatus status)
    {
        if (fields.Count == 0)
        {
            return 0.20m;
        }

        var avg = fields.Average(x => x.Confidence);
        var validRatio = fields.Count(f => f.Valid && !string.IsNullOrWhiteSpace(f.Value)) / (decimal)fields.Count;
        var weighted = (avg * 0.55m) + (validRatio * 0.45m);
        if (status == DocumentStatus.Ready)
        {
            weighted += 0.05m;
        }

        weighted = Math.Clamp(weighted, 0.15m, 0.99m);
        return Math.Round(weighted, 2, MidpointRounding.AwayFromZero);
    }

    private static IReadOnlyList<string> BuildWarnings(
        DocumentType documentType,
        string text,
        IReadOnlyList<DocumentFieldResultDto> fields)
    {
        var warnings = new List<string>();

        if (string.IsNullOrWhiteSpace(text))
        {
            warnings.Add("No se detecto texto util en el archivo; revisar OCR o escaneo.");
        }

        if (documentType == DocumentType.Unknown)
        {
            warnings.Add("No se pudo clasificar el tipo de documento con reglas locales C#.");
        }

        if (fields.Any(f => !f.Valid))
        {
            warnings.Add("Uno o mas campos requieren revision manual.");
        }

        return warnings;
    }

    private static DocumentType DetectDocumentType(string filename, string text)
    {
        var scores = new Dictionary<DocumentType, int>
        {
            [DocumentType.Ine] = 0,
            [DocumentType.Curp] = 0,
            [DocumentType.ActaNacimiento] = 0,
            [DocumentType.ComprobanteDomicilio] = 0,
            [DocumentType.Nss] = 0,
            [DocumentType.DatosBancarios] = 0,
            [DocumentType.Factura] = 0,
            [DocumentType.ConstanciaSituacionFiscal] = 0
        };

        // Strong filename hints
        AddScore(scores, DocumentType.Ine, filename, 14, "INE", "CREDENCIAL", "ELECTOR");
        AddScore(scores, DocumentType.Curp, filename, 16, "CURP");
        AddScore(scores, DocumentType.ActaNacimiento, filename, 12, "ACTA", "NACIMIENTO");
        AddScore(scores, DocumentType.ComprobanteDomicilio, filename, 12, "COMPROBANTE", "RECIBO", "DOMICILIO", "TELMEX", "CFE", "LUZ", "AGUA");
        AddScore(scores, DocumentType.Nss, filename, 16, "NSS", "IMSS", "SEGURO SOCIAL");
        AddScore(scores, DocumentType.DatosBancarios, filename, 14, "BANCO", "CLABE", "CUENTA");
        AddScore(scores, DocumentType.Factura, filename, 14, "FACTURA", "PAGO", "NOMINA", "DISPERSION", "BMPEI", "SPEI");
        AddScore(scores, DocumentType.ConstanciaSituacionFiscal, filename, 14, "CSF", "CONSTANCIA", "FISCAL", "SAT", "RFC");

        // Text hints
        AddScore(scores, DocumentType.Ine, text, 6, "INSTITUTO NACIONAL ELECTORAL", "CLAVE DE ELECTOR", "SECCION", "VIGENCIA", "CREDENCIAL PARA VOTAR");
        AddScore(scores, DocumentType.Curp, text, 6, "CLAVE UNICA DE REGISTRO DE POBLACION", "CURP");
        AddScore(scores, DocumentType.ActaNacimiento, text, 6, "ACTA DE NACIMIENTO", "REGISTRO CIVIL", "OFICIALIA");
        AddScore(scores, DocumentType.ComprobanteDomicilio, text, 5, "PAGAR ANTES DE", "COMPROBANTE DE DOMICILIO", "ESTADO DE CUENTA", "TOTAL A PAGAR", "TELMEX", "CFE");
        AddScore(scores, DocumentType.Nss, text, 6, "NUMERO DE SEGURIDAD SOCIAL", "IMSS", "NSS");
        AddScore(scores, DocumentType.DatosBancarios, text, 6, "CLABE", "ESTADO DE CUENTA", "BANCO", "NO. DE CUENTA");
        AddScore(scores, DocumentType.Factura, text, 7, "DISPERSION DE PAGO DE NOMINA", "PAGO DE NOMINA", "CLAVE RASTREO", "COMPROBANTE DE LA OPERACION", "DATOS DEL BENEFICIARIO", "REPORTE DE OPERACIONES");
        AddScore(scores, DocumentType.ConstanciaSituacionFiscal, text, 6, "CONSTANCIA DE SITUACION FISCAL", "CEDULA DE IDENTIFICACION FISCAL", "RFC", "SAT");

        if (CurpRegex.IsMatch(text))
        {
            scores[DocumentType.Curp] += 8;
            scores[DocumentType.Ine] += 3;
            scores[DocumentType.Nss] += 2;
        }

        if (RfcRegex.IsMatch(text))
        {
            scores[DocumentType.ConstanciaSituacionFiscal] += 7;
        }

        var ranked = scores
            .OrderByDescending(kv => kv.Value)
            .ThenBy(kv => kv.Key == DocumentType.Ine ? 1 : 0)
            .ToList();

        if (ranked.Count == 0 || ranked[0].Value < 8)
        {
            return DocumentType.Unknown;
        }

        if (ranked.Count > 1
            && ranked[0].Key == DocumentType.Ine
            && ranked[0].Value - ranked[1].Value <= 2)
        {
            return ranked[1].Key;
        }

        return ranked[0].Key;
    }

    private static DocumentType? ResolveForcedDocumentType(string? optionsJson)
    {
        if (string.IsNullOrWhiteSpace(optionsJson))
        {
            return null;
        }

        try
        {
            using var json = JsonDocument.Parse(optionsJson);
            if (!json.RootElement.TryGetProperty("force_document_type", out var typeElement))
            {
                return null;
            }
            if (typeElement.ValueKind != JsonValueKind.String)
            {
                return null;
            }

            var raw = typeElement.GetString();
            if (string.IsNullOrWhiteSpace(raw))
            {
                return null;
            }

            var normalized = raw.Trim();
            if (Enum.TryParse<DocumentType>(normalized, true, out var parsed))
            {
                return parsed;
            }

            normalized = normalized.Replace("_", string.Empty, StringComparison.OrdinalIgnoreCase);
            foreach (var item in Enum.GetValues<DocumentType>())
            {
                if (string.Equals(item.ToString(), normalized, StringComparison.OrdinalIgnoreCase))
                {
                    return item;
                }
            }
        }
        catch
        {
            return null;
        }

        return null;
    }

    private static IReadOnlyList<DocumentFieldResultDto> ExtractFields(DocumentType type, string text, string filename)
    {
        return type switch
        {
            DocumentType.Ine => ExtractIneFields(text),
            DocumentType.Curp => ExtractCurpFields(text),
            DocumentType.ActaNacimiento => ExtractActaFields(text),
            DocumentType.ComprobanteDomicilio => ExtractDomicilioFields(text, filename),
            DocumentType.Nss => ExtractNssFields(text),
            DocumentType.DatosBancarios => ExtractBankFields(text, filename),
            DocumentType.Factura => ExtractFacturaFields(text, filename),
            DocumentType.ConstanciaSituacionFiscal => ExtractFiscalFields(text),
            _ => Array.Empty<DocumentFieldResultDto>()
        };
    }

    private static IReadOnlyList<DocumentFieldResultDto> ExtractIneFields(string text)
    {
        var fields = new List<DocumentFieldResultDto>
        {
            Build("nombre", "Nombre completo", AfterAnyLabel(text, "NOMBRE", "NOMBRE(S)", "APELLIDOS Y NOMBRE")),
            Build("curp", "CURP", FirstRegex(text, CurpRegex), CurpRegex),
            Build("clave_elector", "Clave de elector", AfterAnyLabel(text, "CLAVE DE ELECTOR", "CLAVE ELECTOR")),
            Build("fecha_nacimiento", "Fecha de nacimiento", FirstRegex(text, DateRegex), DateRegex),
            Build("sexo", "Sexo", FirstAny(text, "HOMBRE", "MUJER", "H", "M")),
            Build("domicilio", "Domicilio", AfterAnyLabel(text, "DOMICILIO", "DIRECCION")),
            Build("seccion", "Seccion", AfterAnyLabel(text, "SECCION")),
            Build("vigencia", "Vigencia", AfterAnyLabel(text, "VIGENCIA"))
        };

        return fields;
    }

    private static IReadOnlyList<DocumentFieldResultDto> ExtractCurpFields(string text)
    {
        return
        [
            Build("nombre", "Nombre completo", AfterAnyLabel(text, "NOMBRE", "NOMBRE(S)")),
            Build("curp", "CURP", FirstRegex(text, CurpRegex), CurpRegex),
            Build("fecha_nacimiento", "Fecha de nacimiento", FirstRegex(text, DateRegex), DateRegex),
            Build("sexo", "Sexo", FirstAny(text, "HOMBRE", "MUJER", "H", "M")),
            Build("entidad_nacimiento", "Entidad de nacimiento", AfterAnyLabel(text, "ENTIDAD", "ENTIDAD DE NACIMIENTO"))
        ];
    }

    private static IReadOnlyList<DocumentFieldResultDto> ExtractActaFields(string text)
    {
        static string? NormalizeActaNumeric(string? raw)
        {
            if (string.IsNullOrWhiteSpace(raw))
            {
                return null;
            }

            var digits = raw
                .Trim()
                .ToUpperInvariant()
                .Replace("O", "0", StringComparison.Ordinal)
                .Replace("I", "1", StringComparison.Ordinal)
                .Replace("L", "1", StringComparison.Ordinal);
            digits = Regex.Replace(digits, @"\D", string.Empty);
            if (string.IsNullOrWhiteSpace(digits))
            {
                return null;
            }
            return digits;
        }

        static string? CleanActaName(string? raw)
        {
            if (string.IsNullOrWhiteSpace(raw))
            {
                return null;
            }

            var value = Regex.Replace(raw.Trim(), @"\s+", " ");
            if (value.Contains(':')
                || value.Contains("APELLIDO", StringComparison.OrdinalIgnoreCase)
                || value.Contains("SEXO", StringComparison.OrdinalIgnoreCase)
                || value.Contains("FECHA", StringComparison.OrdinalIgnoreCase)
                || value.Contains("LUGAR", StringComparison.OrdinalIgnoreCase)
                || value.Contains("NACIMIENTO", StringComparison.OrdinalIgnoreCase)
                || value.Contains("DATOS DE LA PERSONA REGISTRADA", StringComparison.OrdinalIgnoreCase))
            {
                return null;
            }

            return value;
        }

        static string? CleanActaPlace(string? raw)
        {
            if (string.IsNullOrWhiteSpace(raw))
            {
                return null;
            }

            var value = Regex.Replace(raw.Trim(), @"\s+", " ");
            value = Regex.Replace(value, @"[^A-Z ]", " ").Trim();
            value = Regex.Replace(value, @"\s+", " ");
            if (string.IsNullOrWhiteSpace(value))
            {
                return null;
            }
            if (value.Contains("LUGAR DE NACIMIENTO", StringComparison.OrdinalIgnoreCase)
                || value.Contains("DATOS DE LA PERSONA REGISTRADA", StringComparison.OrdinalIgnoreCase))
            {
                return null;
            }
            return value;
        }

        static string? FirstDateIn(string? raw)
        {
            if (string.IsNullOrWhiteSpace(raw))
            {
                return null;
            }

            var match = DateRegex.Match(raw);
            return match.Success ? match.Value : null;
        }

        static string? NormalizeSexo(string? raw)
        {
            if (string.IsNullOrWhiteSpace(raw))
            {
                return null;
            }

            var value = raw.Trim().ToUpperInvariant();
            if (value is "H" or "HOMBRE" or "MASCULINO")
            {
                return "HOMBRE";
            }
            if (value is "M" or "MUJER" or "FEMENINO")
            {
                return "MUJER";
            }
            return null;
        }

        var nombre = CleanActaName(AfterAnyLabel(text, "NOMBRE", "NOMBRE(S)"));
        if (string.IsNullOrWhiteSpace(nombre))
        {
            var namesRowMatch = Regex.Match(
                text,
                @"(?:^|\n)\s*([A-Z]{2,}(?:\s+[A-Z]{2,}){0,3})\s+([A-Z]{2,})\s+([A-Z]{2,})\s*\r?\n\s*NOMBRE(?:\(S\))?\s+PRIMER\s+APELLIDO\s+SEGUNDO\s+APELLIDO",
                RegexOptions.IgnoreCase | RegexOptions.Compiled);
            if (namesRowMatch.Success)
            {
                nombre = CleanActaName(
                    $"{namesRowMatch.Groups[1].Value} {namesRowMatch.Groups[2].Value} {namesRowMatch.Groups[3].Value}");
            }
        }
        if (string.IsNullOrWhiteSpace(nombre))
        {
            var sectionMatch = Regex.Match(
                text,
                @"DATOS\s+DE\s+LA\s+PERSONA\s+REGISTRADA(?<chunk>[\s\S]{0,260}?)(?:SEXO|FECHA\s+DE\s+NACIMIENTO|LUGAR\s+DE\s+NACIMIENTO)",
                RegexOptions.IgnoreCase | RegexOptions.Compiled);
            if (sectionMatch.Success)
            {
                var chunk = sectionMatch.Groups["chunk"].Value;
                var stopAt = Regex.Match(chunk, @"\b(?:HOMBRE|MUJER|MASCULINO|FEMENINO)\b|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", RegexOptions.IgnoreCase);
                if (stopAt.Success && stopAt.Index > 0)
                {
                    chunk = chunk[..stopAt.Index];
                }
                chunk = Regex.Replace(chunk, @"\b(?:NOMBRE(?:\(S\))?|PRIMER\s+APELLIDO|SEGUNDO\s+APELLIDO)\b", " ", RegexOptions.IgnoreCase);
                chunk = Regex.Replace(chunk, @"[^A-Z ]", " ", RegexOptions.IgnoreCase);
                chunk = Regex.Replace(chunk, @"\s+", " ").Trim();
                if (!string.IsNullOrWhiteSpace(chunk))
                {
                    var tokens = chunk
                        .Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                        .Where(t => t.Length >= 2)
                        .Take(8)
                        .ToArray();
                    if (tokens.Length >= 2)
                    {
                        nombre = CleanActaName(string.Join(' ', tokens));
                    }
                }
            }
        }
        if (!string.IsNullOrWhiteSpace(nombre))
        {
            nombre = Regex.Replace(
                nombre,
                @"\b(?:HOMBRE|MUJER|MASCULINO|FEMENINO)\b[\s\S]*$|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b[\s\S]*$",
                string.Empty,
                RegexOptions.IgnoreCase).Trim();
            nombre = CleanActaName(nombre);
        }

        var folio = NormalizeActaNumeric(FirstRegex(
            text,
            new Regex(@"\bFOLIO\s*[:\-]?\s*([0-9OIL]{1,8})\b", RegexOptions.IgnoreCase | RegexOptions.Compiled),
            1));
        var numeroActa = NormalizeActaNumeric(FirstRegex(
            text,
            new Regex(@"\bNUMERO\s+DE\s+ACTA\s*[:\-]?\s*([0-9OIL]{1,8})\b", RegexOptions.IgnoreCase | RegexOptions.Compiled),
            1));
        var sexoFilaMatch = Regex.Match(
            text,
            @"\b(?:HOMBRE|MUJER|MASCULINO|FEMENINO)\b\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+([A-Z ]{3,}?)\s+SEXO\s+FECHA\s+DE\s+NACIMIENTO\s+LUGAR\s+DE\s+NACIMIENTO",
            RegexOptions.IgnoreCase | RegexOptions.Compiled);
        var fechaNacimiento = FirstDateIn(AfterAnyLabel(text, "FECHA DE NACIMIENTO", "FECHA NACIMIENTO"));
        var lugarNacimiento = CleanActaPlace(AfterAnyLabel(text, "LUGAR DE NACIMIENTO", "LUGAR NACIMIENTO"));
        var fechaRegistro = FirstDateIn(AfterAnyLabel(text, "FECHA DE REGISTRO", "FECHA REGISTRO"));
        var municipioRegistro = CleanActaPlace(AfterAnyLabel(text, "MUNICIPIO DE REGISTRO", "MUNICIPIO REGISTRO"));
        var entidadRegistro = CleanActaPlace(AfterAnyLabel(text, "ENTIDAD DE REGISTRO", "ENTIDAD REGISTRO"));
        if (sexoFilaMatch.Success)
        {
            fechaNacimiento ??= sexoFilaMatch.Groups[1].Value;
            lugarNacimiento ??= CleanActaPlace(sexoFilaMatch.Groups[2].Value);
        }
        if (string.IsNullOrWhiteSpace(fechaNacimiento) || string.IsNullOrWhiteSpace(lugarNacimiento))
        {
            var simpleSexoRowMatch = Regex.Match(
                text,
                @"\b(?:HOMBRE|MUJER|MASCULINO|FEMENINO)\b\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+([A-Z ]{3,}?)(?:\r?\n|\s+)SEXO\b",
                RegexOptions.IgnoreCase | RegexOptions.Compiled);
            if (simpleSexoRowMatch.Success)
            {
                fechaNacimiento ??= simpleSexoRowMatch.Groups[1].Value;
                lugarNacimiento ??= CleanActaPlace(simpleSexoRowMatch.Groups[2].Value);
            }
        }

        // Table fallback: "OFICIALIA FECHA DE REGISTRO LIBRO NUMERO [DE ACTA] 0001 20/08/2001 3 45"
        var tableMatch = Regex.Match(
            text,
            @"OFICIALIA\s+FECHA\s+DE\s+REGISTRO\s+LIBRO\s+NUMERO(?:\s+DE\s+ACTA)?\s+([0-9OIL]{1,6})\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+([0-9OIL]{1,6})\s+([0-9OIL]{1,6})",
            RegexOptions.IgnoreCase | RegexOptions.Compiled);
        if (tableMatch.Success)
        {
            folio ??= NormalizeActaNumeric(tableMatch.Groups[1].Value);
            fechaRegistro ??= tableMatch.Groups[2].Value;
            numeroActa ??= NormalizeActaNumeric(tableMatch.Groups[4].Value);
        }

        // Registrar variant: "OFICIALIA NUMERO ANO 0001 45 2001"
        if (string.IsNullOrWhiteSpace(folio) || string.IsNullOrWhiteSpace(numeroActa))
        {
            var regMatch = Regex.Match(
                text,
                @"OFICIALIA\s+NUMERO\s+ANO\s+([0-9OIL]{1,6})\s+([0-9OIL]{1,6})\s+[0-9OIL]{2,4}",
                RegexOptions.IgnoreCase | RegexOptions.Compiled);
            if (regMatch.Success)
            {
                folio ??= NormalizeActaNumeric(regMatch.Groups[1].Value);
                numeroActa ??= NormalizeActaNumeric(regMatch.Groups[2].Value);
            }
        }

        if (string.IsNullOrWhiteSpace(fechaNacimiento))
        {
            var allDates = DateRegex.Matches(text)
                .Select(match => match.Value)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList();
            if (allDates.Count > 0)
            {
                var candidate = allDates.FirstOrDefault(date =>
                    string.IsNullOrWhiteSpace(fechaRegistro)
                    || !string.Equals(date, fechaRegistro, StringComparison.OrdinalIgnoreCase));
                fechaNacimiento = candidate ?? allDates[0];
            }
        }
        else if (!string.IsNullOrWhiteSpace(fechaRegistro)
            && string.Equals(fechaNacimiento, fechaRegistro, StringComparison.OrdinalIgnoreCase))
        {
            var allDates = DateRegex.Matches(text)
                .Select(match => match.Value)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList();
            var alternative = allDates.FirstOrDefault(date =>
                !string.Equals(date, fechaRegistro, StringComparison.OrdinalIgnoreCase));
            if (!string.IsNullOrWhiteSpace(alternative))
            {
                fechaNacimiento = alternative;
            }
        }

        return
        [
            Build("nombre", "Nombre completo", nombre),
            Build("sexo", "Sexo", NormalizeSexo(FirstAny(text, "HOMBRE", "MUJER", "MASCULINO", "FEMENINO"))),
            Build("fecha_nacimiento", "Fecha de nacimiento", fechaNacimiento, DateRegex),
            Build("lugar_nacimiento", "Lugar de nacimiento", lugarNacimiento),
            Build("folio", "Folio", folio, new Regex(@"^\d{1,8}$", RegexOptions.Compiled)),
            Build("numero_acta", "Numero de acta", numeroActa, new Regex(@"^\d{1,8}$", RegexOptions.Compiled)),
            Build("fecha_registro", "Fecha de registro", fechaRegistro, DateRegex),
            Build("municipio_registro", "Municipio de registro", municipioRegistro),
            Build("entidad_registro", "Entidad de registro", entidadRegistro)
        ];
    }

    private static IReadOnlyList<DocumentFieldResultDto> ExtractDomicilioFields(string text, string filename)
    {
        var dueDate = FirstRegex(
            text,
            new Regex(
                @"PAGAR\s+ANTES\s+DE[:\s-]*([0-9]{1,2}[/-][A-Z]{3}[/-][0-9]{2,4}|[0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})",
                RegexOptions.IgnoreCase | RegexOptions.Compiled),
            1);
        if (string.IsNullOrWhiteSpace(dueDate))
        {
            dueDate = FirstRegex(text, DateRegex);
        }

        var provider = FirstAny(text, "TELMEX", "CFE", "TOTALPLAY", "MEGACABLE", "IZZI");
        provider ??= FirstAny(filename, "TELMEX", "CFE", "TOTALPLAY", "MEGACABLE", "IZZI");

        return
        [
            Build("titular", "Titular", AfterAnyLabel(text, "TITULAR", "CLIENTE", "NOMBRE")),
            Build("domicilio", "Domicilio", AfterAnyLabel(text, "DIRECCION", "DOMICILIO")),
            Build("fecha_limite", "Fecha limite", dueDate, DateRegex),
            Build("total", "Total", FirstRegex(text, AmountRegex), AmountRegex),
            Build("proveedor", "Proveedor", provider),
            Build("ciudad", "Ciudad", AfterAnyLabel(text, "CIUDAD", "MUNICIPIO"))
        ];
    }

    private static IReadOnlyList<DocumentFieldResultDto> ExtractNssFields(string text)
    {
        var nssRegex = new Regex(@"\b\d{10,11}\b", RegexOptions.Compiled);
        return
        [
            Build("nombre", "Nombre completo", AfterAnyLabel(text, "NOMBRE", "ASEGURADO")),
            Build("nss", "NSS", FirstRegex(text, nssRegex), nssRegex),
            Build("curp", "CURP", FirstRegex(text, CurpRegex), CurpRegex)
        ];
    }

    private static IReadOnlyList<DocumentFieldResultDto> ExtractBankFields(string text, string filename)
    {
        var clabeRegex = new Regex(@"\b\d{18}\b", RegexOptions.Compiled);
        var bank = AfterAnyLabel(text, "BANCO", "INSTITUCION") ?? FirstAny(filename, "BBVA", "BANORTE", "SANTANDER", "BANAMEX", "HSBC");
        var account = AfterAnyLabel(text, "NO. CUENTA", "NO CUENTA", "NO DE CUENTA", "NUMERO DE CUENTA");
        if (string.IsNullOrWhiteSpace(account))
        {
            account = AfterAnyLabel(text, "CUENTA");
            if (!string.IsNullOrWhiteSpace(account))
            {
                // Avoid heading captures like "ESTADO DE CUENTA" -> "BANCO: ...".
                var hasEnoughDigits = Regex.IsMatch(account, @"\d{6,}");
                if (!hasEnoughDigits)
                {
                    var accountMatch = Regex.Match(
                        text,
                        @"(?:NO\.?\s*DE?\s*CUENTA|NUMERO\s+DE\s+CUENTA|CUENTA)\D{0,10}(\d{6,24})",
                        RegexOptions.IgnoreCase);
                    account = accountMatch.Success ? accountMatch.Groups[1].Value : null;
                }
            }
        }

        return
        [
            Build("banco", "Banco", bank),
            Build("titular", "Titular", AfterAnyLabel(text, "TITULAR", "NOMBRE")),
            Build("clabe", "CLABE", FirstRegex(text, clabeRegex), clabeRegex),
            Build("cuenta", "Cuenta", account)
        ];
    }

    private static IReadOnlyList<DocumentFieldResultDto> ExtractFacturaFields(string text, string filename)
    {
        var tableJson = BuildFacturaTableJson(text);
        if (!string.IsNullOrWhiteSpace(tableJson))
        {
            return
            [
                new DocumentFieldResultDto(
                "tabla_celdas",
                "Tabla celdas",
                tableJson,
                0.90m,
                true,
                Array.Empty<string>(),
                null)
            ];
        }
        return
        [
            Build("tabla_celdas", "Tabla celdas", null)
        ];
    }

    private static string? BuildFacturaTableJson(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return null;
        }

        var rows = new List<List<string>>();
        var lines = text
            .Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .Where(line => !string.IsNullOrWhiteSpace(line))
            .Take(300);

        foreach (var line in lines)
        {
            // Prefer fixed-width OCR spacing, but tolerate normalized text that keeps single spaces.
            var cells = Regex
                .Split(line.Trim(), @"\s{2,}")
                .Select(cell => cell.Trim())
                .Where(cell => !string.IsNullOrWhiteSpace(cell))
                .Take(10)
                .ToList();

            if (cells.Count < 3)
            {
                cells = Regex
                    .Split(line.Trim(), @"\s+")
                    .Select(cell => cell.Trim())
                    .Where(cell => !string.IsNullOrWhiteSpace(cell))
                    .Take(10)
                    .ToList();
            }

            if (cells.Count < 3)
            {
                continue;
            }

            var joined = string.Join(" ", cells).ToUpperInvariant();
            var headerLike = (joined.Contains("CUENTA") && (joined.Contains("REFERENCIA") || joined.Contains("IMPORTE")))
                || (joined.Contains("BENEFICIARIO") && joined.Contains("IMPORTE"))
                || (joined.Contains("CLAVE") && joined.Contains("RASTREO"));
            var dataLike = Regex.IsMatch(joined, @"\d{8,}")
                && (joined.Contains("$") || joined.Contains("PROCESADO") || joined.Contains("APLICADO")
                    || joined.Contains("ACEPTADO") || joined.Contains("TRANSMITIDO"));

            if (headerLike || dataLike)
            {
                rows.Add(cells);
            }

            if (rows.Count >= 20)
            {
                break;
            }
        }

        if (rows.Count < 2)
        {
            return null;
        }

        var payload = new
        {
            source = "text_lines_csharp",
            rows
        };
        return JsonSerializer.Serialize(payload);
    }

    private static IReadOnlyList<DocumentFieldResultDto> ExtractFiscalFields(string text)
    {
        return
        [
            Build("razon_social", "Razon social", AfterAnyLabel(text, "DENOMINACION", "RAZON SOCIAL", "NOMBRE")),
            Build("rfc", "RFC", FirstRegex(text, RfcRegex), RfcRegex),
            Build("regimen", "Regimen fiscal", AfterAnyLabel(text, "REGIMEN", "REGIMEN FISCAL")),
            Build("cp", "CP", AfterAnyLabel(text, "CODIGO POSTAL", "CP"))
        ];
    }

    private static DocumentFieldResultDto Build(string key, string label, string? rawValue, Regex? validator = null)
    {
        var value = SanitizeValue(rawValue);
        if (string.IsNullOrWhiteSpace(value))
        {
            return new DocumentFieldResultDto(key, label, null, 0.28m, false, new[] { "No detectado." }, null);
        }

        var isValid = validator is null || validator.IsMatch(value);
        var confidence = isValid ? 0.86m : 0.56m;
        var errors = isValid ? Array.Empty<string>() : new[] { "Formato no valido." };
        return new DocumentFieldResultDto(key, label, value, confidence, isValid, errors, null);
    }

    private static string? SanitizeValue(string? rawValue)
    {
        if (string.IsNullOrWhiteSpace(rawValue))
        {
            return null;
        }

        var value = rawValue.Trim();
        value = Regex.Replace(value, @"\s+", " ");
        if (value == "-" || value == ":")
        {
            return null;
        }

        return value;
    }

    private static string? FirstRegex(string text, Regex regex, int group = 0)
    {
        var match = regex.Match(text);
        if (!match.Success)
        {
            return null;
        }

        return match.Groups.Count > group ? match.Groups[group].Value : match.Value;
    }

    private static string? AfterAnyLabel(string text, params string[] labels)
    {
        foreach (var label in labels)
        {
            var value = AfterLabel(text, label);
            if (!string.IsNullOrWhiteSpace(value))
            {
                return value;
            }
        }

        return null;
    }

    private static readonly HashSet<string> _knownLabelKeywords = new(StringComparer.OrdinalIgnoreCase)
    {
        "NOMBRE", "NOMBRE(S)", "CURP", "RFC", "NSS", "CLABE", "DOMICILIO", "DIRECCION",
        "FECHA DE NACIMIENTO", "SEXO", "VIGENCIA", "SECCION", "CLAVE DE ELECTOR",
        "APELLIDO PATERNO", "APELLIDO MATERNO", "LUGAR DE NACIMIENTO", "BANCO",
        "TITULAR", "FECHA LIMITE", "TOTAL", "TOTAL A PAGAR", "PAGAR ANTES DE",
        "NUMERO DE SEGURIDAD SOCIAL", "FOLIO", "NUMERO DE ACTA", "RAZON SOCIAL",
        "REGIMEN", "CODIGO POSTAL"
    };

    private static string? AfterLabel(string text, string label)
    {
        // 1. Intento en la misma línea: LABEL: valor
        var sameLine = new Regex($@"{Regex.Escape(label)}\s*[:\-]?\s*(.+)", RegexOptions.IgnoreCase);
        var match = sameLine.Match(text);
        if (match.Success)
        {
            var value = match.Groups[1].Value.Trim();
            var stop = value.IndexOfAny(['\r', '\n']);
            if (stop >= 0)
            {
                value = value[..stop];
            }

            if (!string.IsNullOrWhiteSpace(value))
            {
                return value.Trim();
            }
        }

        // 2. Intento en la línea siguiente: label en su propia línea, valor en la siguiente
        var nextLine = new Regex(
            $@"(?:^|\n)\s*{Regex.Escape(label)}\s*[:\-]?\s*\r?\n\s*(.+)",
            RegexOptions.IgnoreCase);
        match = nextLine.Match(text);
        if (match.Success)
        {
            var value = match.Groups[1].Value.Trim();
            var stop = value.IndexOfAny(['\r', '\n']);
            if (stop >= 0)
            {
                value = value[..stop];
            }

            if (!string.IsNullOrWhiteSpace(value) && !_knownLabelKeywords.Contains(value))
            {
                return value.Trim();
            }
        }

        return null;
    }

    private static string? FirstAny(string text, params string[] options)
    {
        foreach (var option in options)
        {
            if (ContainsToken(text, option))
            {
                return option;
            }
        }

        return null;
    }

    private static void AddScore(Dictionary<DocumentType, int> scores, DocumentType type, string source, int weight, params string[] tokens)
    {
        var hits = 0;
        foreach (var token in tokens)
        {
            if (ContainsToken(source, token))
            {
                hits++;
            }
        }

        if (hits > 0)
        {
            scores[type] += hits * weight;
        }
    }

    private static bool ContainsToken(string source, string token)
    {
        if (string.IsNullOrWhiteSpace(source) || string.IsNullOrWhiteSpace(token))
        {
            return false;
        }

        if (token.Contains(' '))
        {
            return source.Contains(token, StringComparison.OrdinalIgnoreCase);
        }

        return Regex.IsMatch(source, $@"\b{Regex.Escape(token)}\b", RegexOptions.IgnoreCase);
    }

    private static string Normalize(string raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
        {
            return string.Empty;
        }

        var withoutMarks = RemoveDiacritics(raw);
        var compact = Regex.Replace(withoutMarks, @"[ \t]+", " ");
        return compact.ToUpperInvariant();
    }

    private static string RemoveDiacritics(string value)
    {
        var normalized = value.Normalize(NormalizationForm.FormD);
        var sb = new StringBuilder(normalized.Length);
        foreach (var c in normalized)
        {
            var category = CharUnicodeInfo.GetUnicodeCategory(c);
            if (category != UnicodeCategory.NonSpacingMark)
            {
                sb.Append(c);
            }
        }

        return sb.ToString().Normalize(NormalizationForm.FormC);
    }

    private static async Task<string> ReadDocumentTextAsync(string filePath, CancellationToken cancellationToken)
    {
        var extension = Path.GetExtension(filePath).ToLowerInvariant();
        return extension switch
        {
            ".txt" or ".json" or ".csv" or ".xml" => await File.ReadAllTextAsync(filePath, cancellationToken),
            ".pdf" => await ReadPdfAsTextAsync(filePath, cancellationToken),
            _ => string.Empty
        };
    }

    private static async Task<string> ReadPdfAsTextAsync(string filePath, CancellationToken cancellationToken)
    {
        var bytes = await File.ReadAllBytesAsync(filePath, cancellationToken);
        if (bytes.Length == 0)
        {
            return string.Empty;
        }

        // First attempt: parse PDF content streams and decode Flate data.
        var streamText = ExtractTextFromPdfStreams(bytes);
        if (!string.IsNullOrWhiteSpace(streamText))
        {
            return streamText;
        }

        // Fallback for PDFs with uncompressed text operators.
        var latin = Encoding.GetEncoding("ISO-8859-1").GetString(bytes);
        var chunks = new List<string>();
        foreach (Match match in Regex.Matches(latin, @"\((?<txt>(?:\\.|[^\\\)])*)\)\s*T[Jj]", RegexOptions.Singleline))
        {
            var encoded = match.Groups["txt"].Value;
            var decoded = DecodePdfEscapes(encoded);
            if (IsLikelyTextSegment(decoded))
            {
                chunks.Add(decoded);
            }
        }

        if (chunks.Count == 0)
        {
            return string.Empty;
        }

        return string.Join(Environment.NewLine, chunks);
    }

    private static string ExtractTextFromPdfStreams(byte[] pdfBytes)
    {
        var allChunks = new List<string>();
        var streamToken = Encoding.ASCII.GetBytes("stream");
        var endStreamToken = Encoding.ASCII.GetBytes("endstream");
        var position = 0;

        while (position < pdfBytes.Length)
        {
            var streamIndex = IndexOfBytes(pdfBytes, streamToken, position);
            if (streamIndex < 0)
            {
                break;
            }

            var contentStart = streamIndex + streamToken.Length;
            if (contentStart < pdfBytes.Length && pdfBytes[contentStart] == '\r')
            {
                contentStart++;
            }

            if (contentStart < pdfBytes.Length && pdfBytes[contentStart] == '\n')
            {
                contentStart++;
            }

            var endIndex = IndexOfBytes(pdfBytes, endStreamToken, contentStart);
            if (endIndex < 0)
            {
                break;
            }

            var length = endIndex - contentStart;
            if (length <= 0)
            {
                position = endIndex + endStreamToken.Length;
                continue;
            }

            var streamBytes = new byte[length];
            Buffer.BlockCopy(pdfBytes, contentStart, streamBytes, 0, length);

            var dictStart = LastIndexOfAscii(pdfBytes, "<<", streamIndex, 2048);
            var dictEnd = LastIndexOfAscii(pdfBytes, ">>", streamIndex, 2048);
            var hasFlate = false;
            if (dictStart >= 0 && dictEnd >= dictStart)
            {
                var dictLength = dictEnd + 2 - dictStart;
                var dictBytes = new byte[dictLength];
                Buffer.BlockCopy(pdfBytes, dictStart, dictBytes, 0, dictLength);
                var dictText = Encoding.ASCII.GetString(dictBytes);
                hasFlate = dictText.Contains("/FlateDecode", StringComparison.OrdinalIgnoreCase);
            }

            var contentBytes = hasFlate ? TryInflateStream(streamBytes) : streamBytes;
            if (contentBytes.Length > 0)
            {
                var text = ExtractTextOperators(Encoding.GetEncoding("ISO-8859-1").GetString(contentBytes));
                if (!string.IsNullOrWhiteSpace(text))
                {
                    allChunks.Add(text);
                }
            }

            position = endIndex + endStreamToken.Length;
        }

        if (allChunks.Count == 0)
        {
            return string.Empty;
        }

        return string.Join(Environment.NewLine, allChunks);
    }

    private static byte[] TryInflateStream(byte[] data)
    {
        static byte[] InflateWith(Func<Stream, Stream> factory, byte[] source)
        {
            using var input = new MemoryStream(source, writable: false);
            using var decoder = factory(input);
            using var output = new MemoryStream();
            decoder.CopyTo(output);
            return output.ToArray();
        }

        try
        {
            return InflateWith(stream => new ZLibStream(stream, CompressionMode.Decompress, leaveOpen: false), data);
        }
        catch
        {
            try
            {
                return InflateWith(stream => new DeflateStream(stream, CompressionMode.Decompress, leaveOpen: false), data);
            }
            catch
            {
                return Array.Empty<byte>();
            }
        }
    }

    private static string ExtractTextOperators(string content)
    {
        var chunks = new List<string>();

        foreach (Match match in Regex.Matches(content, @"\((?<txt>(?:\\.|[^\\\)])*)\)\s*T[Jj]", RegexOptions.Singleline))
        {
            var decoded = DecodePdfEscapes(match.Groups["txt"].Value);
            if (IsLikelyTextSegment(decoded))
            {
                chunks.Add(decoded);
            }
        }

        foreach (Match match in Regex.Matches(content, @"\[(?<arr>.*?)\]\s*TJ", RegexOptions.Singleline))
        {
            var arr = match.Groups["arr"].Value;
            foreach (Match item in Regex.Matches(arr, @"\((?<txt>(?:\\.|[^\\\)])*)\)"))
            {
                var decoded = DecodePdfEscapes(item.Groups["txt"].Value);
                if (IsLikelyTextSegment(decoded))
                {
                    chunks.Add(decoded);
                }
            }
        }

        if (chunks.Count == 0)
        {
            return string.Empty;
        }

        return string.Join(Environment.NewLine, chunks);
    }

    private static int IndexOfBytes(byte[] source, byte[] pattern, int start)
    {
        for (var i = Math.Max(0, start); i <= source.Length - pattern.Length; i++)
        {
            var ok = true;
            for (var j = 0; j < pattern.Length; j++)
            {
                if (source[i + j] != pattern[j])
                {
                    ok = false;
                    break;
                }
            }

            if (ok)
            {
                return i;
            }
        }

        return -1;
    }

    private static int LastIndexOfAscii(byte[] source, string ascii, int beforeIndex, int maxBacktrack)
    {
        var token = Encoding.ASCII.GetBytes(ascii);
        var start = Math.Max(0, beforeIndex - Math.Max(0, maxBacktrack));
        for (var i = beforeIndex - token.Length; i >= start; i--)
        {
            var ok = true;
            for (var j = 0; j < token.Length; j++)
            {
                if (source[i + j] != token[j])
                {
                    ok = false;
                    break;
                }
            }

            if (ok)
            {
                return i;
            }
        }

        return -1;
    }

    private static bool IsLikelyTextSegment(string segment)
    {
        if (string.IsNullOrWhiteSpace(segment))
        {
            return false;
        }

        var cleaned = segment.Trim();
        if (cleaned.Length < 3)
        {
            return false;
        }

        var letters = cleaned.Count(char.IsLetter);
        var digits = cleaned.Count(char.IsDigit);
        var printable = cleaned.Count(c => !char.IsControl(c));
        var ratio = printable / (decimal)cleaned.Length;

        return ratio >= 0.85m && (letters + digits) >= 2;
    }

    private static string DecodePdfEscapes(string value)
    {
        var sb = new StringBuilder(value.Length);
        for (var i = 0; i < value.Length; i++)
        {
            var ch = value[i];
            if (ch != '\\')
            {
                sb.Append(ch);
                continue;
            }

            if (i + 1 >= value.Length)
            {
                break;
            }

            var next = value[++i];
            switch (next)
            {
                case 'n': sb.Append('\n'); break;
                case 'r': sb.Append('\r'); break;
                case 't': sb.Append('\t'); break;
                case '\\': sb.Append('\\'); break;
                case '(' : sb.Append('('); break;
                case ')' : sb.Append(')'); break;
                default:
                    if (next is >= '0' and <= '7')
                    {
                        var oct = new StringBuilder().Append(next);
                        for (var j = 0; j < 2 && i + 1 < value.Length && value[i + 1] is >= '0' and <= '7'; j++)
                        {
                            oct.Append(value[++i]);
                        }

                        if (int.TryParse(oct.ToString(), NumberStyles.None, CultureInfo.InvariantCulture, out var num))
                        {
                            sb.Append((char)num);
                        }
                    }
                    else
                    {
                        sb.Append(next);
                    }
                    break;
            }
        }

        return sb.ToString();
    }
}



