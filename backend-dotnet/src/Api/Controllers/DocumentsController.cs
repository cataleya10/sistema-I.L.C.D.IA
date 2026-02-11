using Application.DTOs;
using Application.Interfaces;
using Domain.Enums;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Options;
using Shared.Options;
using Api.Authorization;
using System.IO;
using System.IO.Compression;
using System.Globalization;

namespace Api.Controllers;

[ApiController]
[Route("api/documents")]
[Authorize]
public class DocumentsController : ControllerBase
{
    private readonly IDocumentService _documentService;
    private readonly UploadOptions _uploadOptions;

    public DocumentsController(IDocumentService documentService, IOptions<UploadOptions> uploadOptions)
    {
        _documentService = documentService;
        _uploadOptions = uploadOptions.Value;
    }

    [HttpPost("upload")]
    [Consumes("multipart/form-data")]
    [RequireRole("Admin")]
    public async Task<ActionResult<DocumentSummaryDto>> Upload([FromForm] IFormFile file, CancellationToken cancellationToken)
    {
        if (file is null || file.Length == 0)
        {
            return BadRequest("Archivo inválido.");
        }

        if (file.Length > _uploadOptions.MaxFileSizeBytes)
        {
            return BadRequest($"El archivo excede el tamaño permitido ({_uploadOptions.MaxFileSizeBytes} bytes).");
        }

        if (!_uploadOptions.AllowedContentTypes.Contains(file.ContentType))
        {
            return BadRequest("Tipo de archivo no permitido.");
        }

        await using var stream = file.OpenReadStream();
        if (!HasValidFileSignature(stream, file.ContentType))
        {
            return BadRequest("El archivo no coincide con el tipo declarado.");
        }
        stream.Position = 0;
        var upload = new DocumentUpload(
            stream,
            file.FileName,
            file.ContentType,
            file.Length,
            User?.Identity?.Name
        );

        var result = await _documentService.UploadAsync(upload, cancellationToken);
        return Ok(result);
    }

    [HttpGet]
    [RequireRole("Admin,User")]
    public async Task<ActionResult<IReadOnlyList<DocumentSummaryDto>>> List(
        [FromQuery] string? status,
        [FromQuery] string? type,
        [FromQuery] string? q,
        [FromQuery] DateTime? from,
        [FromQuery] DateTime? to,
        [FromQuery] int page = 1,
        [FromQuery] int pageSize = 20,
        CancellationToken cancellationToken = default)
    {
        if (page < 1)
        {
            page = 1;
        }

        if (pageSize < 1)
        {
            pageSize = 20;
        }

        var query = new DocumentListQuery(status, type, q, from, to, page, pageSize);
        var result = await _documentService.ListAsync(query, cancellationToken);
        return Ok(result);
    }

    [HttpGet("{id:guid}")]
    [RequireRole("Admin,User")]
    public async Task<ActionResult<DocumentDetailDto>> GetById(Guid id, CancellationToken cancellationToken)
    {
        var result = await _documentService.GetByIdAsync(id, cancellationToken);
        if (result is null)
        {
            return NotFound("Documento no encontrado.");
        }

        var fileUrl = Url.ActionLink(nameof(GetFile), values: new { id }) ?? string.Empty;
        var updated = result with { FileUrl = fileUrl };
        return Ok(updated);
    }

    [HttpGet("{id:guid}/file")]
    [RequireRole("Admin,User")]
    public async Task<IActionResult> GetFile(Guid id, CancellationToken cancellationToken)
    {
        var stream = await _documentService.GetFileStreamAsync(id, cancellationToken);
        if (stream is null)
        {
            return NotFound("Archivo no encontrado.");
        }

        var detail = await _documentService.GetByIdAsync(id, cancellationToken);
        var mimeType = detail?.MimeType ?? "application/octet-stream";
        return File(stream, mimeType, enableRangeProcessing: true);
    }

    [HttpGet("{id:guid}/export/word")]
    [RequireRole("Admin,User")]
    public async Task<IActionResult> ExportWord(Guid id, CancellationToken cancellationToken)
    {
        var detail = await _documentService.GetByIdAsync(id, cancellationToken);
        if (detail is null)
        {
            return NotFound("Documento no encontrado.");
        }

        var rtf = BuildRtf(detail);
        var filename = Path.GetFileNameWithoutExtension(detail.OriginalFilename);
        var outputName = string.IsNullOrWhiteSpace(filename) ? "documento" : filename;
        return File(global::System.Text.Encoding.UTF8.GetBytes(rtf), "application/rtf", $"{outputName}.doc");
    }

    [HttpGet("{id:guid}/export/excel")]
    [RequireRole("Admin,User")]
    public async Task<IActionResult> ExportExcel(Guid id, CancellationToken cancellationToken)
    {
        var detail = await _documentService.GetByIdAsync(id, cancellationToken);
        if (detail is null)
        {
            return NotFound("Documento no encontrado.");
        }

        var bytes = BuildXlsx(detail);
        var filename = Path.GetFileNameWithoutExtension(detail.OriginalFilename);
        var outputName = string.IsNullOrWhiteSpace(filename) ? "documento" : filename;
        return File(
            bytes,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            $"{outputName}.xlsx");
    }

    [HttpPost("{id:guid}/process")]
    [RequireRole("Admin")]
    public async Task<ActionResult<DocumentProcessResponse>> Process(Guid id, CancellationToken cancellationToken)
    {
        var result = await _documentService.ProcessAsync(id, cancellationToken);
        if (result.Status == DocumentStatus.Processing)
        {
            return Accepted(result);
        }

        return Ok(result);
    }

    [HttpGet("{id:guid}/process/status")]
    [RequireRole("Admin,User")]
    public async Task<ActionResult<DocumentProcessResponse>> ProcessStatus(Guid id, CancellationToken cancellationToken)
    {
        var detail = await _documentService.GetByIdAsync(id, cancellationToken);
        if (detail is null)
        {
            return NotFound("Documento no encontrado.");
        }

        var result = await _documentService.GetProcessStatusAsync(id, cancellationToken);
        return Ok(result);
    }

    [HttpPost("{id:guid}/reprocess")]
    [RequireRole("Admin")]
    public async Task<ActionResult<DocumentProcessResponse>> Reprocess(Guid id, CancellationToken cancellationToken)
    {
        var result = await _documentService.ReprocessAsync(id, cancellationToken);
        return Accepted(result);
    }

    [HttpPut("{id:guid}/fields")]
    [RequireRole("Admin,User")]
    public async Task<IActionResult> UpdateFields(Guid id, [FromBody] DocumentFieldsUpdateRequest request, CancellationToken cancellationToken)
    {
        if (request is null)
        {
            return BadRequest("Solicitud inválida.");
        }

        var reviewedBy = User?.Identity?.Name;
        var updatedRequest = request with { ReviewedBy = reviewedBy };
        await _documentService.UpdateFieldsAsync(id, updatedRequest, cancellationToken);
        return NoContent();
    }

    [HttpGet("{id:guid}/logs")]
    [RequireRole("Admin,User")]
    public async Task<ActionResult<IReadOnlyList<ProcessingLogDto>>> GetLogs(Guid id, CancellationToken cancellationToken)
    {
        var logs = await _documentService.GetLogsAsync(id, cancellationToken);
        return Ok(logs);
    }

    [HttpPost("{id:guid}/mark-failed")]
    [RequireRole("Admin")]
    public async Task<IActionResult> MarkFailed(
        Guid id,
        [FromBody] DocumentFailRequest? request,
        [FromQuery] string? reason,
        CancellationToken cancellationToken)
    {
        var resolved = !string.IsNullOrWhiteSpace(reason) ? reason : request?.Reason;
        resolved = string.IsNullOrWhiteSpace(resolved) ? "Marcado manualmente." : resolved;
        await _documentService.MarkFailedAsync(id, resolved, cancellationToken);
        return NoContent();
    }

    [HttpDelete("{id:guid}")]
    [RequireRole("Admin")]
    public async Task<IActionResult> Delete(Guid id, CancellationToken cancellationToken)
    {
        await _documentService.DeleteAsync(id, cancellationToken);
        return NoContent();
    }

    private static string BuildRtf(DocumentDetailDto detail)
    {
        static string Escape(string? value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return "-";
            }
            var normalized = value
                .Replace("\\", "\\\\")
                .Replace("{", "\\{")
                .Replace("}", "\\}")
                .Replace("\r\n", "\n")
                .Replace("\r", "\n");

            var sb = new global::System.Text.StringBuilder();
            foreach (var ch in normalized)
            {
                if (ch == '\n')
                {
                    sb.Append("\\par ");
                    continue;
                }
                if (ch <= 0x7f)
                {
                    sb.Append(ch);
                    continue;
                }
                var code = (int)ch;
                if (code > 32767)
                {
                    code -= 65536;
                }
                sb.Append("\\u").Append(code).Append("?");
            }
            return sb.ToString();
        }

        static IReadOnlyList<(string Key, string Label)> GetTemplate(DocumentType documentType)
        {
            return documentType switch
            {
                DocumentType.Ine => new List<(string, string)>
                {
                    ("nombre", "Nombre completo"),
                    ("curp", "CURP"),
                    ("clave_elector", "Clave de elector"),
                    ("fecha_nacimiento", "Fecha de nacimiento"),
                    ("sexo", "Sexo"),
                    ("domicilio", "Domicilio"),
                    ("seccion", "Sección"),
                    ("vigencia", "Vigencia")
                },
                DocumentType.Curp => new List<(string, string)>
                {
                    ("nombre", "Nombre completo"),
                    ("curp", "CURP"),
                    ("fecha_nacimiento", "Fecha de nacimiento"),
                    ("sexo", "Sexo"),
                    ("entidad_nacimiento", "Entidad de nacimiento")
                },
                DocumentType.ActaNacimiento => new List<(string, string)>
                {
                    ("nombre", "Nombre completo"),
                    ("sexo", "Sexo"),
                    ("fecha_nacimiento", "Fecha de nacimiento"),
                    ("lugar_nacimiento", "Lugar de nacimiento"),
                    ("folio", "Folio"),
                    ("numero_acta", "Número de acta"),
                    ("fecha_registro", "Fecha de registro"),
                    ("municipio_registro", "Municipio de registro"),
                    ("entidad_registro", "Entidad de registro")
                },
                DocumentType.Nss => new List<(string, string)>
                {
                    ("nombre", "Nombre completo"),
                    ("nss", "NSS")
                },
                DocumentType.ComprobanteDomicilio => new List<(string, string)>
                {
                    ("proveedor", "Proveedor"),
                    ("numero_servicio", "Número de servicio"),
                    ("cuenta", "Cuenta"),
                    ("referencia", "Referencia"),
                    ("titular", "Titular"),
                    ("domicilio", "Domicilio"),
                    ("cp", "Código postal"),
                    ("fecha_limite", "Fecha límite"),
                    ("total", "Total")
                },
                DocumentType.DatosBancarios => new List<(string, string)>
                {
                    ("banco", "Banco"),
                    ("clabe", "CLABE"),
                    ("cuenta", "Cuenta"),
                    ("titular", "Titular"),
                    ("rfc", "RFC"),
                    ("fecha_corte", "Fecha de corte"),
                    ("periodo", "Periodo")
                },
                DocumentType.ConstanciaSituacionFiscal => new List<(string, string)>
                {
                    ("rfc", "RFC"),
                    ("nombre", "Nombre completo"),
                    ("regimen", "Régimen"),
                    ("domicilio", "Domicilio"),
                },
                _ => new List<(string, string)>()
            };
        }

        var sb = new global::System.Text.StringBuilder();
        sb.Append("{\\rtf1\\ansi\\ansicpg1252\\uc1\\deff0\n");
        sb.Append("\\b SISTEMA DE LECTURA INTELIGENTE \\b0\\par\n");
        sb.Append($"Documento: {Escape(detail.OriginalFilename)}\\par\n");
        sb.Append($"Tipo: {Escape(detail.DocumentType.ToString())}\\par\n");
        sb.Append($"Fecha de carga: {detail.UploadedAt:yyyy-MM-dd HH:mm}\\par\n");
        sb.Append("\\par\\b Campos extraidos \\b0\\par\n");
        var template = GetTemplate(detail.DocumentType);
        if (template.Count == 0 && detail.Fields.Count > 0)
        {
            template = detail.Fields
                .Select(field => (field.Key, field.Label))
                .ToList();
        }
        var fieldMap = detail.Fields
            .GroupBy(field => field.Key, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(group => group.Key, group => group.First(), StringComparer.OrdinalIgnoreCase);

        foreach (var (key, label) in template)
        {
            if (fieldMap.TryGetValue(key, out var field))
            {
                var value = Escape(field.CorrectedValue ?? field.Value);
                sb.Append($"\\b {Escape(label)}: \\b0 {value}\\par\n");
            }
            else
            {
                sb.Append($"\\b {Escape(label)}: \\b0 -\\par\n");
            }
        }

        sb.Append("}");
        return sb.ToString();
    }

    private static byte[] BuildXlsx(DocumentDetailDto detail)
    {
        static string EscapeXml(string? value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return string.Empty;
            }

            return value
                .Replace("&", "&amp;")
                .Replace("<", "&lt;")
                .Replace(">", "&gt;")
                .Replace("\"", "&quot;")
                .Replace("'", "&apos;");
        }

        static string InlineCell(string cellRef, string value, int styleId)
        {
            return $"<c r=\"{cellRef}\" t=\"inlineStr\" s=\"{styleId}\"><is><t xml:space=\"preserve\">{EscapeXml(value)}</t></is></c>";
        }

        static IReadOnlyList<(string Key, string Label)> GetTemplate(DocumentType documentType)
        {
            return documentType switch
            {
                DocumentType.Ine => new List<(string, string)>
                {
                    ("nombre", "Nombre completo"),
                    ("curp", "CURP"),
                    ("clave_elector", "Clave de elector"),
                    ("fecha_nacimiento", "Fecha de nacimiento"),
                    ("sexo", "Sexo"),
                    ("domicilio", "Domicilio"),
                    ("seccion", "Seccion"),
                    ("vigencia", "Vigencia")
                },
                DocumentType.Curp => new List<(string, string)>
                {
                    ("nombre", "Nombre completo"),
                    ("curp", "CURP"),
                    ("fecha_nacimiento", "Fecha de nacimiento"),
                    ("sexo", "Sexo"),
                    ("entidad_nacimiento", "Entidad de nacimiento")
                },
                DocumentType.ActaNacimiento => new List<(string, string)>
                {
                    ("nombre", "Nombre completo"),
                    ("sexo", "Sexo"),
                    ("fecha_nacimiento", "Fecha de nacimiento"),
                    ("lugar_nacimiento", "Lugar de nacimiento"),
                    ("folio", "Folio"),
                    ("numero_acta", "Numero de acta"),
                    ("fecha_registro", "Fecha de registro"),
                    ("municipio_registro", "Municipio de registro"),
                    ("entidad_registro", "Entidad de registro")
                },
                DocumentType.Nss => new List<(string, string)>
                {
                    ("nombre", "Nombre completo"),
                    ("nss", "NSS")
                },
                DocumentType.ComprobanteDomicilio => new List<(string, string)>
                {
                    ("proveedor", "Proveedor"),
                    ("numero_servicio", "Numero de servicio"),
                    ("cuenta", "Cuenta"),
                    ("referencia", "Referencia"),
                    ("titular", "Titular"),
                    ("domicilio", "Domicilio"),
                    ("cp", "Codigo postal"),
                    ("fecha_limite", "Fecha limite"),
                    ("total", "Total")
                },
                DocumentType.DatosBancarios => new List<(string, string)>
                {
                    ("banco", "Banco"),
                    ("clabe", "CLABE"),
                    ("cuenta", "Cuenta"),
                    ("titular", "Titular"),
                    ("rfc", "RFC"),
                    ("fecha_corte", "Fecha de corte"),
                    ("periodo", "Periodo")
                },
                DocumentType.ConstanciaSituacionFiscal => new List<(string, string)>
                {
                    ("rfc", "RFC"),
                    ("nombre", "Nombre completo"),
                    ("regimen", "Regimen"),
                    ("domicilio", "Domicilio")
                },
                _ => new List<(string, string)>()
            };
        }

        var template = GetTemplate(detail.DocumentType);
        if (template.Count == 0 && detail.Fields.Count > 0)
        {
            template = detail.Fields
                .Select(field => (field.Key, field.Label))
                .ToList();
        }

        var fieldMap = detail.Fields
            .GroupBy(field => field.Key, StringComparer.OrdinalIgnoreCase)
            .ToDictionary(group => group.Key, group => group.First(), StringComparer.OrdinalIgnoreCase);

        var rows = new List<string>
        {
            "<row r=\"1\">" + InlineCell("A1", "SISTEMA DE LECTURA INTELIGENTE", 1) + "</row>",
            "<row r=\"2\">" + InlineCell("A2", "Documento", 2) + InlineCell("B2", detail.OriginalFilename, 3) + "</row>",
            "<row r=\"3\">" + InlineCell("A3", "Tipo", 2) + InlineCell("B3", detail.DocumentType.ToString(), 3) + "</row>",
            "<row r=\"4\">" + InlineCell("A4", "Fecha de carga", 2) + InlineCell("B4", detail.UploadedAt.ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture), 3) + "</row>",
            "<row r=\"6\">" + InlineCell("A6", "Campo", 2) + InlineCell("B6", "Valor", 2) + InlineCell("C6", "Validez", 2) + InlineCell("D6", "Confianza", 2) + "</row>"
        };

        var rowNumber = 7;
        foreach (var (key, label) in template)
        {
            var hasField = fieldMap.TryGetValue(key, out var field);
            var value = hasField ? (field!.CorrectedValue ?? field.Value ?? "-") : "-";
            var validity = hasField ? (field!.Valid ? "OK" : "Revisar") : "-";
            var confidence = hasField ? field!.Confidence.ToString("0.00", CultureInfo.InvariantCulture) : "-";
            rows.Add(
                $"<row r=\"{rowNumber}\">" +
                InlineCell($"A{rowNumber}", label, 3) +
                InlineCell($"B{rowNumber}", value, 3) +
                InlineCell($"C{rowNumber}", validity, 3) +
                InlineCell($"D{rowNumber}", confidence, 3) +
                "</row>");
            rowNumber++;
        }

        var lastDataRow = Math.Max(7, rowNumber - 1);

        var sheetXml = $"""
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheetViews>
    <sheetView workbookViewId="0">
      <pane ySplit="6" topLeftCell="A7" activePane="bottomLeft" state="frozen"/>
    </sheetView>
  </sheetViews>
  <dimension ref="A1:D{lastDataRow}"/>
  <cols>
    <col min="1" max="1" width="28" customWidth="1"/>
    <col min="2" max="2" width="58" customWidth="1"/>
    <col min="3" max="3" width="14" customWidth="1"/>
    <col min="4" max="4" width="14" customWidth="1"/>
  </cols>
  <sheetData>
    {string.Join(string.Empty, rows)}
  </sheetData>
  <autoFilter ref="A6:D{lastDataRow}"/>
</worksheet>
""";

        const string contentTypesXml = """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
""";

        const string rootRelsXml = """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
""";

        const string workbookXml = """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Extraccion" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
""";

        const string workbookRelsXml = """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>
""";

        const string stylesXml = """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="3">
    <font><sz val="11"/><name val="Calibri"/><family val="2"/></font>
    <font><b/><sz val="12"/><name val="Calibri"/><family val="2"/></font>
    <font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/><family val="2"/></font>
  </fonts>
  <fills count="4">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFDCE6F1"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left style="thin"/><right style="thin"/><top style="thin"/><bottom style="thin"/><diagonal/></border>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="4">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
    <xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>
    <xf numFmtId="0" fontId="0" fillId="2" borderId="1" xfId="0" applyFill="1" applyBorder="1"/>
  </cellXfs>
  <cellStyles count="1">
    <cellStyle name="Normal" xfId="0" builtinId="0"/>
  </cellStyles>
</styleSheet>
""";

        var now = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture);
        var coreXml = $"""
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Extraccion de documento</dc:title>
  <dc:creator>Sistema I.L.C.D.IA</dc:creator>
  <cp:lastModifiedBy>Sistema I.L.C.D.IA</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>
</cp:coreProperties>
""";

        const string appXml = """
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Sistema I.L.C.D.IA</Application>
  <DocSecurity>0</DocSecurity>
  <ScaleCrop>false</ScaleCrop>
  <HeadingPairs>
    <vt:vector size="2" baseType="variant">
      <vt:variant><vt:lpstr>Worksheets</vt:lpstr></vt:variant>
      <vt:variant><vt:i4>1</vt:i4></vt:variant>
    </vt:vector>
  </HeadingPairs>
  <TitlesOfParts>
    <vt:vector size="1" baseType="lpstr">
      <vt:lpstr>Extraccion</vt:lpstr>
    </vt:vector>
  </TitlesOfParts>
</Properties>
""";

        using var stream = new MemoryStream();
        using (var archive = new ZipArchive(stream, ZipArchiveMode.Create, true))
        {
            static void AddEntry(ZipArchive archive, string name, string content)
            {
                var entry = archive.CreateEntry(name, CompressionLevel.Fastest);
                using var writer = new StreamWriter(entry.Open(), new global::System.Text.UTF8Encoding(false));
                writer.Write(content);
            }

            AddEntry(archive, "[Content_Types].xml", contentTypesXml);
            AddEntry(archive, "_rels/.rels", rootRelsXml);
            AddEntry(archive, "xl/workbook.xml", workbookXml);
            AddEntry(archive, "xl/_rels/workbook.xml.rels", workbookRelsXml);
            AddEntry(archive, "xl/worksheets/sheet1.xml", sheetXml);
            AddEntry(archive, "xl/styles.xml", stylesXml);
            AddEntry(archive, "docProps/core.xml", coreXml);
            AddEntry(archive, "docProps/app.xml", appXml);
        }

        return stream.ToArray();
    }

    private static bool HasValidFileSignature(Stream stream, string contentType)
    {
        Span<byte> header = stackalloc byte[8];
        var read = stream.Read(header);
        if (read < 4)
        {
            return false;
        }

        return contentType switch
        {
            "application/pdf" => header[0] == (byte)'%' && header[1] == (byte)'P' && header[2] == (byte)'D' && header[3] == (byte)'F',
            "image/png" => read >= 8 && header[0] == 0x89 && header[1] == 0x50 && header[2] == 0x4E && header[3] == 0x47
                && header[4] == 0x0D && header[5] == 0x0A && header[6] == 0x1A && header[7] == 0x0A,
            "image/jpeg" => header[0] == 0xFF && header[1] == 0xD8 && header[2] == 0xFF,
            _ => true
        };
    }
}

public sealed record DocumentFailRequest(string? Reason);
