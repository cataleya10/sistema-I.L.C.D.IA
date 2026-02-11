using Application.DTOs;
using Application.Interfaces;
using Domain.Enums;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Options;
using Shared.Options;
using Api.Authorization;
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Spreadsheet;
using System.IO;
using System.Globalization;
using System.Xml;

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

        static string SanitizeText(string? value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return string.Empty;
            }

            var normalized = value
                .Replace("\r\n", "\n")
                .Replace("\r", "\n");
            var sb = new global::System.Text.StringBuilder(normalized.Length);
            foreach (var ch in normalized)
            {
                if (XmlConvert.IsXmlChar(ch))
                {
                    sb.Append(ch);
                }
            }
            return sb.ToString();
        }

        static Cell TextCell(string cellRef, string? value)
        {
            return new Cell
            {
                CellReference = cellRef,
                DataType = CellValues.InlineString,
                InlineString = new InlineString(
                    new Text(SanitizeText(value))
                    {
                        Space = SpaceProcessingModeValues.Preserve
                    })
            };
        }

        static string Col(int index)
        {
            const string letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
            if (index <= 26)
            {
                return letters[index - 1].ToString();
            }

            var first = (index - 1) / 26;
            var second = (index - 1) % 26;
            return $"{letters[first - 1]}{letters[second]}";
        }

        static Row BuildRow(uint rowIndex, params string[] values)
        {
            var row = new Row { RowIndex = rowIndex };
            for (var i = 0; i < values.Length; i++)
            {
                var cellRef = $"{Col(i + 1)}{rowIndex}";
                row.Append(TextCell(cellRef, values[i]));
            }
            return row;
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

        var rowNumber = 7u;
        var sheetData = new SheetData();
        sheetData.Append(BuildRow(1, "SISTEMA DE LECTURA INTELIGENTE"));
        sheetData.Append(BuildRow(2, "Documento", detail.OriginalFilename));
        sheetData.Append(BuildRow(3, "Tipo", detail.DocumentType.ToString()));
        sheetData.Append(BuildRow(4, "Fecha de carga", detail.UploadedAt.ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture)));
        sheetData.Append(BuildRow(6, "Campo", "Valor", "Validez", "Confianza"));

        foreach (var (key, label) in template)
        {
            var hasField = fieldMap.TryGetValue(key, out var field);
            var value = hasField ? (field!.CorrectedValue ?? field.Value ?? "-") : "-";
            var validity = hasField ? (field!.Valid ? "OK" : "Revisar") : "-";
            var confidence = hasField ? field!.Confidence.ToString("0.00", CultureInfo.InvariantCulture) : "-";
            sheetData.Append(BuildRow(rowNumber, label, value, validity, confidence));
            rowNumber++;
        }

        using var stream = new MemoryStream();
        using (var spreadsheet = SpreadsheetDocument.Create(stream, SpreadsheetDocumentType.Workbook, true))
        {
            var workbookPart = spreadsheet.AddWorkbookPart();
            workbookPart.Workbook = new Workbook();

            var worksheetPart = workbookPart.AddNewPart<WorksheetPart>();
            var lastDataRow = Math.Max(7u, rowNumber - 1);
            worksheetPart.Worksheet = new Worksheet(
                new SheetViews(
                    new SheetView
                    {
                        WorkbookViewId = 0U,
                        Pane = new Pane
                        {
                            VerticalSplit = 6D,
                            TopLeftCell = "A7",
                            ActivePane = PaneValues.BottomLeft,
                            State = PaneStateValues.Frozen
                        }
                    }),
                new Columns(
                    new Column { Min = 1U, Max = 1U, Width = 28D, CustomWidth = true },
                    new Column { Min = 2U, Max = 2U, Width = 58D, CustomWidth = true },
                    new Column { Min = 3U, Max = 3U, Width = 14D, CustomWidth = true },
                    new Column { Min = 4U, Max = 4U, Width = 14D, CustomWidth = true }),
                sheetData,
                new AutoFilter { Reference = $"A6:D{lastDataRow}" });

            var sheets = workbookPart.Workbook.AppendChild(new Sheets());
            sheets.Append(new Sheet
            {
                Id = workbookPart.GetIdOfPart(worksheetPart),
                SheetId = 1U,
                Name = "Extraccion"
            });

            workbookPart.Workbook.Save();
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
