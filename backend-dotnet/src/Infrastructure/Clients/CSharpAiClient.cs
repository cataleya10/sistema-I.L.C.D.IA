using System.Globalization;
using System.IO.Compression;
using System.Text;
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
        CancellationToken cancellationToken)
    {
        var started = DateTime.UtcNow;
        var rawText = await ReadDocumentTextAsync(filePath, cancellationToken);
        return BuildResponseFromRawText(
            documentId,
            rawText,
            originalFilename ?? filePath,
            started,
            "csharp-local",
            "csharp-pipeline-v2",
            1,
            0);
    }

    public Task<DocumentProcessResponse> ProcessTextAsync(
        Guid documentId,
        string rawText,
        string? originalFilename,
        string ocrEngine,
        int pagesProcessed,
        long upstreamProcessingMs,
        CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var started = DateTime.UtcNow;
        var response = BuildResponseFromRawText(
            documentId,
            rawText,
            originalFilename ?? string.Empty,
            started,
            string.IsNullOrWhiteSpace(ocrEngine) ? "python-ocr" : ocrEngine,
            "csharp-hybrid-v1",
            pagesProcessed <= 0 ? 1 : pagesProcessed,
            upstreamProcessingMs < 0 ? 0 : upstreamProcessingMs);
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
        long upstreamProcessingMs)
    {
        var normalizedText = Normalize(rawText);
        var filenameHint = Normalize(Path.GetFileNameWithoutExtension(filenameOrPath ?? string.Empty));

        var type = DetectDocumentType(filenameHint, normalizedText);
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
            [DocumentType.ConstanciaSituacionFiscal] = 0
        };

        // Strong filename hints
        AddScore(scores, DocumentType.Ine, filename, 14, "INE", "CREDENCIAL", "ELECTOR");
        AddScore(scores, DocumentType.Curp, filename, 16, "CURP");
        AddScore(scores, DocumentType.ActaNacimiento, filename, 12, "ACTA", "NACIMIENTO");
        AddScore(scores, DocumentType.ComprobanteDomicilio, filename, 12, "COMPROBANTE", "RECIBO", "DOMICILIO", "TELMEX", "CFE", "LUZ", "AGUA");
        AddScore(scores, DocumentType.Nss, filename, 16, "NSS", "IMSS", "SEGURO SOCIAL");
        AddScore(scores, DocumentType.DatosBancarios, filename, 14, "BANCO", "CLABE", "CUENTA");
        AddScore(scores, DocumentType.ConstanciaSituacionFiscal, filename, 14, "CSF", "CONSTANCIA", "FISCAL", "SAT", "RFC");

        // Text hints
        AddScore(scores, DocumentType.Ine, text, 6, "INSTITUTO NACIONAL ELECTORAL", "CLAVE DE ELECTOR", "SECCION", "VIGENCIA", "CREDENCIAL PARA VOTAR");
        AddScore(scores, DocumentType.Curp, text, 6, "CLAVE UNICA DE REGISTRO DE POBLACION", "CURP");
        AddScore(scores, DocumentType.ActaNacimiento, text, 6, "ACTA DE NACIMIENTO", "REGISTRO CIVIL", "OFICIALIA");
        AddScore(scores, DocumentType.ComprobanteDomicilio, text, 5, "PAGAR ANTES DE", "COMPROBANTE DE DOMICILIO", "ESTADO DE CUENTA", "TOTAL A PAGAR", "TELMEX", "CFE");
        AddScore(scores, DocumentType.Nss, text, 6, "NUMERO DE SEGURIDAD SOCIAL", "IMSS", "NSS");
        AddScore(scores, DocumentType.DatosBancarios, text, 6, "CLABE", "ESTADO DE CUENTA", "BANCO", "NO. DE CUENTA");
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
        return
        [
            Build("nombre", "Nombre completo", AfterAnyLabel(text, "NOMBRE", "NOMBRE(S)")),
            Build("sexo", "Sexo", FirstAny(text, "HOMBRE", "MUJER", "MASCULINO", "FEMENINO")),
            Build("fecha_nacimiento", "Fecha de nacimiento", FirstRegex(text, DateRegex), DateRegex),
            Build("lugar_nacimiento", "Lugar de nacimiento", AfterAnyLabel(text, "LUGAR DE NACIMIENTO", "LUGAR NACIMIENTO")),
            Build("folio", "Folio", AfterAnyLabel(text, "FOLIO", "NO. DE FOLIO")),
            Build("numero_acta", "Numero de acta", AfterAnyLabel(text, "NUMERO DE ACTA", "ACTA"))
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
            Build("direccion", "Direccion", AfterAnyLabel(text, "DIRECCION", "DOMICILIO")),
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

        return
        [
            Build("banco", "Banco", bank),
            Build("titular", "Titular", AfterAnyLabel(text, "TITULAR", "NOMBRE")),
            Build("clabe", "CLABE", FirstRegex(text, clabeRegex), clabeRegex),
            Build("numero_cuenta", "Numero de cuenta", AfterAnyLabel(text, "CUENTA", "NO. CUENTA", "NUMERO DE CUENTA"))
        ];
    }

    private static IReadOnlyList<DocumentFieldResultDto> ExtractFiscalFields(string text)
    {
        return
        [
            Build("razon_social", "Razon social", AfterAnyLabel(text, "DENOMINACION", "RAZON SOCIAL", "NOMBRE")),
            Build("rfc", "RFC", FirstRegex(text, RfcRegex), RfcRegex),
            Build("regimen", "Regimen fiscal", AfterAnyLabel(text, "REGIMEN", "REGIMEN FISCAL")),
            Build("codigo_postal", "Codigo postal", AfterAnyLabel(text, "CODIGO POSTAL", "CP"))
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

    private static string? AfterLabel(string text, string label)
    {
        var pattern = new Regex($@"{Regex.Escape(label)}\s*[:\-]?\s*(.+)", RegexOptions.IgnoreCase);
        var match = pattern.Match(text);
        if (!match.Success)
        {
            return null;
        }

        var value = match.Groups[1].Value.Trim();
        var stop = value.IndexOfAny(['\r', '\n']);
        if (stop >= 0)
        {
            value = value[..stop];
        }

        return value.Trim();
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


