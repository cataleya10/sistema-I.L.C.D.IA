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
using System.Text.Json;

namespace Api.Controllers;

[ApiController]
[Route("api/documents")]
[Authorize]
public class DocumentsController : ControllerBase
{
    private readonly IDocumentService _documentService;
    private readonly IPythonAiClient _pythonAiClient;
    private readonly UploadOptions _uploadOptions;

    public DocumentsController(
        IDocumentService documentService,
        IPythonAiClient pythonAiClient,
        IOptions<UploadOptions> uploadOptions)
    {
        _documentService = documentService;
        _pythonAiClient = pythonAiClient;
        _uploadOptions = uploadOptions.Value;
    }

    [HttpPost("upload")]
    [Consumes("multipart/form-data")]
    [RequireRole("Admin,User")]
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

    [HttpGet("online-learning/stats")]
    [RequireRole("Admin,User")]
    public async Task<ActionResult<OnlineLearningStatsDto>> GetOnlineLearningStats(
        [FromQuery] int recent = 10,
        CancellationToken cancellationToken = default)
    {
        var safeRecent = Math.Clamp(recent, 0, 100);
        try
        {
            var stats = await _pythonAiClient.GetOnlineLearningStatsAsync(safeRecent, cancellationToken);
            return Ok(stats);
        }
        catch (HttpRequestException)
        {
            return StatusCode(StatusCodes.Status503ServiceUnavailable, "No se pudo consultar el estado de entrenamiento del motor IA.");
        }
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
    [RequireRole("Admin,User")]
    public async Task<ActionResult<DocumentProcessResponse>> Process(
        Guid id,
        [FromBody] DocumentProcessOptionsRequest? request,
        CancellationToken cancellationToken)
    {
        var result = await _documentService.ProcessAsync(id, BuildProcessOptionsJson(request), cancellationToken);
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
    [RequireRole("Admin,User")]
    public async Task<ActionResult<DocumentProcessResponse>> Reprocess(
        Guid id,
        [FromBody] DocumentProcessOptionsRequest? request,
        CancellationToken cancellationToken)
    {
        var result = await _documentService.ReprocessAsync(id, BuildProcessOptionsJson(request), cancellationToken);
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
    [RequireRole("Admin,User")]
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
    [RequireRole("Admin,User")]
    public async Task<IActionResult> Delete(Guid id, CancellationToken cancellationToken)
    {
        try
        {
            await _documentService.DeleteAsync(id, cancellationToken);
            return NoContent();
        }
        catch (IOException)
        {
            return Conflict("No se puede eliminar el documento mientras esta en procesamiento.");
        }
        catch (InvalidOperationException)
        {
            return NotFound("Documento no encontrado.");
        }
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
                    ("periodo", "Periodo"),
                    ("tabla_celdas", "Tabla celdas")
                },
                DocumentType.Factura => new List<(string, string)>
                {
                    ("banco", "Banco"),
                    ("clabe", "CLABE"),
                    ("cuenta", "Cuenta"),
                    ("titular", "Titular"),
                    ("rfc", "RFC"),
                    ("referencia", "Referencia"),
                    ("concepto", "Concepto"),
                    ("total", "Total"),
                    ("tabla_celdas", "Tabla celdas")
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
        var derivedValues = BuildDerivedExportValues(detail.Fields);
        var excludedKeys = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "texto_detectado" };
        var orderedTemplate = template
            .Where(item => !excludedKeys.Contains(item.Key))
            .ToList();
        var templateKeys = new HashSet<string>(orderedTemplate.Select(item => item.Key), StringComparer.OrdinalIgnoreCase);
        var extraFields = detail.Fields
            .Where(field => !excludedKeys.Contains(field.Key) && !templateKeys.Contains(field.Key))
            .Select(field => (Key: field.Key, Label: string.IsNullOrWhiteSpace(field.Label) ? field.Key : field.Label))
            .ToList();
        var derivedExtraFields = derivedValues.Keys
            .Where(key => !excludedKeys.Contains(key) && !templateKeys.Contains(key))
            .Select(key => (Key: key, Label: ResolveExportLabel(key)))
            .ToList();
        List<(string Key, string Label)> exportFields = orderedTemplate
            .Concat(extraFields)
            .Concat(derivedExtraFields)
            .GroupBy(item => item.Key, StringComparer.OrdinalIgnoreCase)
            .Select(group => group.First())
            .ToList();

        foreach (var exportField in exportFields)
        {
            var key = exportField.Key;
            var label = exportField.Label;
            if (fieldMap.TryGetValue(key, out var field))
            {
                var value = Escape(GetDisplayFieldValue(key, field.CorrectedValue ?? field.Value));
                sb.Append($"\\b {Escape(label)}: \\b0 {value}\\par\n");
            }
            else if (derivedValues.TryGetValue(key, out var derived))
            {
                var value = Escape(GetDisplayFieldValue(key, derived));
                sb.Append($"\\b {Escape(label)}: \\b0 {value}\\par\n");
            }
            else
            {
                sb.Append($"\\b {Escape(label)}: \\b0 -\\par\n");
            }
        }

        var structuredTables = BuildStructuredTablesForExport(detail.Fields);
        if (structuredTables.Count > 0)
        {
            sb.Append("\\par\\b Tablas extraidas \\b0\\par\n");
            foreach (var table in structuredTables)
            {
                var tableTitle = string.IsNullOrWhiteSpace(table.Source)
                    ? $"Tabla {table.Index}"
                    : $"Tabla {table.Index} ({table.Source})";
                sb.Append($"\\b {Escape(tableTitle)} \\b0\\par\n");
                AppendRtfTable(sb, table.Rows, Escape);
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
                    ("periodo", "Periodo"),
                    ("tabla_celdas", "Tabla celdas")
                },
                DocumentType.Factura => new List<(string, string)>
                {
                    ("banco", "Banco"),
                    ("clabe", "CLABE"),
                    ("cuenta", "Cuenta"),
                    ("titular", "Titular"),
                    ("rfc", "RFC"),
                    ("referencia", "Referencia"),
                    ("concepto", "Concepto"),
                    ("total", "Total"),
                    ("tabla_celdas", "Tabla celdas")
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
        var derivedValues = BuildDerivedExportValues(detail.Fields);
        var excludedKeys = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "texto_detectado" };
        var orderedTemplate = template
            .Where(item => !excludedKeys.Contains(item.Key))
            .ToList();
        var templateKeys = new HashSet<string>(orderedTemplate.Select(item => item.Key), StringComparer.OrdinalIgnoreCase);
        var extraFields = detail.Fields
            .Where(field => !excludedKeys.Contains(field.Key) && !templateKeys.Contains(field.Key))
            .Select(field => (Key: field.Key, Label: string.IsNullOrWhiteSpace(field.Label) ? field.Key : field.Label))
            .ToList();
        var derivedExtraFields = derivedValues.Keys
            .Where(key => !excludedKeys.Contains(key) && !templateKeys.Contains(key))
            .Select(key => (Key: key, Label: ResolveExportLabel(key)))
            .ToList();
        List<(string Key, string Label)> exportFields = orderedTemplate
            .Concat(extraFields)
            .Concat(derivedExtraFields)
            .GroupBy(item => item.Key, StringComparer.OrdinalIgnoreCase)
            .Select(group => group.First())
            .ToList();
        var structuredTables = BuildStructuredTablesForExport(detail.Fields);

        var rowNumber = 7u;
        var sheetData = new SheetData();
        sheetData.Append(BuildRow(1, "SISTEMA DE LECTURA INTELIGENTE"));
        sheetData.Append(BuildRow(2, "Documento", detail.OriginalFilename));
        sheetData.Append(BuildRow(3, "Tipo", detail.DocumentType.ToString()));
        sheetData.Append(BuildRow(4, "Fecha de carga", detail.UploadedAt.ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture)));
        sheetData.Append(BuildRow(6, "Campo", "Valor", "Validez", "Confianza"));

        foreach (var exportField in exportFields)
        {
            var key = exportField.Key;
            var label = exportField.Label;
            var hasField = fieldMap.TryGetValue(key, out var field);
            string? derivedValue = null;
            var hasDerived = !hasField && derivedValues.TryGetValue(key, out derivedValue);
            var value = hasField
                ? GetDisplayFieldValue(key, field!.CorrectedValue ?? field.Value)
                : hasDerived
                    ? GetDisplayFieldValue(key, derivedValue!)
                    : "-";
            var validity = hasField
                ? (field!.Valid ? "OK" : "Revisar")
                : hasDerived ? "Derivado" : "-";
            var confidence = hasField
                ? field!.Confidence.ToString("0.00", CultureInfo.InvariantCulture)
                : "-";
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

            if (structuredTables.Count > 0)
            {
                var tablesSheetData = new SheetData();
                var tableRowNumber = 1u;
                tablesSheetData.Append(BuildRow(tableRowNumber, "TABLAS EXTRAIDAS"));
                tableRowNumber += 2;
                foreach (var table in structuredTables)
                {
                    var tableTitle = string.IsNullOrWhiteSpace(table.Source)
                        ? $"Tabla {table.Index}"
                        : $"Tabla {table.Index} ({table.Source})";
                    tablesSheetData.Append(BuildRow(tableRowNumber, tableTitle));
                    tableRowNumber++;
                    foreach (var row in table.Rows)
                    {
                        tablesSheetData.Append(BuildRow(tableRowNumber, row.ToArray()));
                        tableRowNumber++;
                    }
                    tableRowNumber++;
                }

                var maxColumns = structuredTables
                    .SelectMany(table => table.Rows)
                    .Select(row => row.Count)
                    .DefaultIfEmpty(1)
                    .Max();
                var tablesWorksheetPart = workbookPart.AddNewPart<WorksheetPart>();
                tablesWorksheetPart.Worksheet = new Worksheet(
                    new Columns(
                        new Column { Min = 1U, Max = 1U, Width = 30D, CustomWidth = true },
                        new Column
                        {
                            Min = 2U,
                            Max = (uint)Math.Max(2, maxColumns),
                            Width = 30D,
                            CustomWidth = true
                        }),
                    tablesSheetData);
                sheets.Append(new Sheet
                {
                    Id = workbookPart.GetIdOfPart(tablesWorksheetPart),
                    SheetId = 2U,
                    Name = "Tablas"
                });
            }

            workbookPart.Workbook.Save();
        }

        return stream.ToArray();
    }

    private static IReadOnlyList<StructuredExportTable> BuildStructuredTablesForExport(IReadOnlyList<DocumentFieldDto> fields)
    {
        var tableField = fields.FirstOrDefault(field =>
            string.Equals(field.Key, "tabla_celdas", StringComparison.OrdinalIgnoreCase));
        if (tableField is null)
        {
            return Array.Empty<StructuredExportTable>();
        }

        var raw = tableField.CorrectedValue ?? tableField.Value;
        if (string.IsNullOrWhiteSpace(raw))
        {
            return Array.Empty<StructuredExportTable>();
        }

        try
        {
            using var document = JsonDocument.Parse(raw);
            var root = document.RootElement;
            var tables = new List<StructuredExportTable>();
            var canonicalTable = TryBuildCanonicalStructuredTable(root);
            if (canonicalTable is not null)
            {
                tables.Add(canonicalTable);
            }

            if (tables.Count == 0
                && root.ValueKind == JsonValueKind.Object
                && root.TryGetProperty("all_tables", out var allTablesElement)
                && allTablesElement.ValueKind == JsonValueKind.Array)
            {
                var fallbackIndex = 1;
                foreach (var tableElement in allTablesElement.EnumerateArray())
                {
                    if (tableElement.ValueKind != JsonValueKind.Object)
                    {
                        continue;
                    }

                    var rows = ReadStructuredRows(tableElement);
                    if (rows.Count == 0)
                    {
                        fallbackIndex++;
                        continue;
                    }

                    var tableIndex = ReadPositiveInt(tableElement, "table_index") ?? fallbackIndex;
                    var source = ReadStringValue(tableElement, "source");
                    tables.Add(new StructuredExportTable(tableIndex, source, rows));
                    fallbackIndex++;
                }
            }

            if (tables.Count == 0)
            {
                var rows = ReadStructuredRows(root);
                if (rows.Count > 0)
                {
                    var tableIndex = root.ValueKind == JsonValueKind.Object
                        ? ReadPositiveInt(root, "primary_table_index") ?? 1
                        : 1;
                    var source = root.ValueKind == JsonValueKind.Object
                        ? ReadStringValue(root, "source")
                        : null;
                    tables.Add(new StructuredExportTable(tableIndex, source, rows));
                }
            }

            return tables
                .OrderBy(table => table.Index)
                .ThenBy(table => table.Source, StringComparer.OrdinalIgnoreCase)
                .ToList();
        }
        catch
        {
            return Array.Empty<StructuredExportTable>();
        }
    }

    private static StructuredExportTable? TryBuildCanonicalStructuredTable(JsonElement root)
    {
        if (root.ValueKind != JsonValueKind.Object)
        {
            return null;
        }

        var columns = ReadCanonicalColumns(root);
        var rowMaps = ReadCanonicalRowMaps(root);
        if (rowMaps.Count == 0)
        {
            return null;
        }

        if (columns.Count == 0)
        {
            columns = rowMaps
                .SelectMany(item => item.Keys)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList();
        }

        var orderedColumns = OrderCanonicalColumns(columns);
        if (orderedColumns.Count == 0)
        {
            return null;
        }

        var tableRows = new List<List<string>>
        {
            orderedColumns.Select(ResolveCanonicalColumnLabel).ToList()
        };

        foreach (var rowMap in rowMaps)
        {
            var row = orderedColumns
                .Select(column => rowMap.TryGetValue(column, out var value) ? NormalizeStructuredCellText(value) : string.Empty)
                .ToList();
            if (row.Any(value => !string.IsNullOrWhiteSpace(value)))
            {
                tableRows.Add(row);
            }
        }

        if (tableRows.Count <= 1)
        {
            return null;
        }

        var normalizedRows = CleanStructuredRows(tableRows);
        if (normalizedRows.Count <= 1)
        {
            return null;
        }

        var tableIndex = ReadPositiveInt(root, "primary_table_index") ?? 1;
        var source = ReadStringValue(root, "source");
        var sourceLabel = string.IsNullOrWhiteSpace(source) ? "canonical_rows" : $"{source}_canonical";
        return new StructuredExportTable(tableIndex, sourceLabel, normalizedRows);
    }

    private static List<string> ReadCanonicalColumns(JsonElement root)
    {
        if (!TryReadArrayProperty(root, "canonical_columns", out var canonicalColumnsElement))
        {
            return new List<string>();
        }

        return canonicalColumnsElement.EnumerateArray()
            .Select(ReadStructuredCellText)
            .Select(NormalizeCanonicalColumnKey)
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static bool TryReadArrayProperty(JsonElement root, string propertyName, out JsonElement propertyValue)
    {
        propertyValue = default;
        if (root.ValueKind != JsonValueKind.Object
            || !root.TryGetProperty(propertyName, out propertyValue)
            || propertyValue.ValueKind != JsonValueKind.Array)
        {
            return false;
        }
        return true;
    }

    private static List<Dictionary<string, string>> ReadCanonicalRowMaps(JsonElement root)
    {
        if (!TryReadArrayProperty(root, "canonical_rows", out var canonicalRowsElement))
        {
            return new List<Dictionary<string, string>>();
        }

        var rows = new List<Dictionary<string, string>>();
        foreach (var rowElement in canonicalRowsElement.EnumerateArray())
        {
            if (rowElement.ValueKind != JsonValueKind.Object)
            {
                continue;
            }

            var rowMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var property in rowElement.EnumerateObject())
            {
                var key = NormalizeCanonicalColumnKey(property.Name);
                if (string.IsNullOrWhiteSpace(key))
                {
                    continue;
                }

                var value = NormalizeStructuredCellText(ReadStructuredCellText(property.Value));
                if (!string.IsNullOrWhiteSpace(value))
                {
                    rowMap[key] = value;
                }
            }

            if (rowMap.Count > 0)
            {
                rows.Add(rowMap);
            }
        }

        return rows;
    }

    private static string NormalizeCanonicalColumnKey(string? key)
    {
        var normalized = string.IsNullOrWhiteSpace(key)
            ? string.Empty
            : key.Trim().Replace("-", "_").Replace(" ", "_");

        if (string.IsNullOrWhiteSpace(normalized))
        {
            return string.Empty;
        }

        return normalized.ToLowerInvariant() switch
        {
            "cuentacuenta" => "cuenta",
            "referenciareferencia" => "referencia",
            "importeimporte" => "importe",
            "nombrenombre" => "nombre",
            "conceptoconcepto" => "concepto",
            "nombre_beneficiario" => "nombre",
            "concepto_pago" => "concepto",
            _ => normalized.ToLowerInvariant()
        };
    }

    private static IReadOnlyList<string> OrderCanonicalColumns(List<string> columns)
    {
        var preferredOrder = new[]
        {
            "cuenta",
            "referencia",
            "importe",
            "nombre",
            "apellido_paterno",
            "apellido_materno",
            "estatus",
            "concepto",
        };

        var ordered = new List<string>();
        foreach (var preferred in preferredOrder)
        {
            if (columns.Any(column => string.Equals(column, preferred, StringComparison.OrdinalIgnoreCase))
                && !ordered.Any(existing => string.Equals(existing, preferred, StringComparison.OrdinalIgnoreCase)))
            {
                ordered.Add(preferred);
            }
        }

        foreach (var column in columns)
        {
            if (!ordered.Any(existing => string.Equals(existing, column, StringComparison.OrdinalIgnoreCase)))
            {
                ordered.Add(column);
            }
        }

        return ordered;
    }

    private static string ResolveCanonicalColumnLabel(string key)
    {
        return key.ToLowerInvariant() switch
        {
            "cuenta" => "Cuenta",
            "referencia" => "Referencia",
            "importe" => "Importe",
            "nombre" => "Nombre",
            "apellido_paterno" => "Apellido paterno",
            "apellido_materno" => "Apellido materno",
            "estatus" => "Estatus",
            "concepto" => "Concepto",
            _ => ResolveExportLabel(key)
        };
    }

    private static IReadOnlyList<IReadOnlyList<string>> ReadStructuredRows(JsonElement element)
    {
        List<List<string>> rows;
        if (element.ValueKind == JsonValueKind.Array)
        {
            rows = ReadRowsMatrix(element);
        }
        else if (element.ValueKind == JsonValueKind.Object)
        {
            rows = element.TryGetProperty("rows", out var rowsElement)
                ? ReadRowsMatrix(rowsElement)
                : new List<List<string>>();
            if (rows.Count == 0
                && element.TryGetProperty("cells", out var cellsElement)
                && cellsElement.ValueKind == JsonValueKind.Array)
            {
                rows = ReadRowsFromCells(cellsElement);
            }
        }
        else
        {
            return Array.Empty<IReadOnlyList<string>>();
        }

        return CleanStructuredRows(rows);
    }

    private static IReadOnlyList<IReadOnlyList<string>> CleanStructuredRows(List<List<string>> rows)
    {
        var normalizedRows = rows
            .Select(row => row.Select(NormalizeStructuredCellText).ToList())
            .Where(row => row.Any(value => !string.IsNullOrWhiteSpace(value)))
            .ToList();
        if (normalizedRows.Count == 0)
        {
            return Array.Empty<IReadOnlyList<string>>();
        }

        var maxUsefulColumn = -1;
        foreach (var row in normalizedRows)
        {
            for (var col = row.Count - 1; col >= 0; col--)
            {
                if (!string.IsNullOrWhiteSpace(row[col]))
                {
                    maxUsefulColumn = Math.Max(maxUsefulColumn, col);
                    break;
                }
            }
        }

        if (maxUsefulColumn < 0)
        {
            return Array.Empty<IReadOnlyList<string>>();
        }

        var targetColumnCount = maxUsefulColumn + 1;
        foreach (var row in normalizedRows)
        {
            if (row.Count > targetColumnCount)
            {
                row.RemoveRange(targetColumnCount, row.Count - targetColumnCount);
            }
            while (row.Count < targetColumnCount)
            {
                row.Add(string.Empty);
            }
        }

        normalizedRows = normalizedRows
            .Where(row => !IsStructuredNoiseRow(row))
            .ToList();
        if (normalizedRows.Count == 0)
        {
            return Array.Empty<IReadOnlyList<string>>();
        }

        if (normalizedRows.Count > 1)
        {
            var header = normalizedRows[0];
            normalizedRows = normalizedRows
                .Where((row, index) => index == 0 || !RowsAreEquivalent(header, row))
                .ToList();
        }

        if (normalizedRows.Count == 0)
        {
            return Array.Empty<IReadOnlyList<string>>();
        }

        var maxColumns = normalizedRows.Max(row => row.Count);
        foreach (var row in normalizedRows)
        {
            while (row.Count < maxColumns)
            {
                row.Add(string.Empty);
            }
        }

        return normalizedRows;
    }

    private static List<List<string>> ReadRowsMatrix(JsonElement rowsElement)
    {
        if (rowsElement.ValueKind != JsonValueKind.Array)
        {
            return new List<List<string>>();
        }

        var rows = new List<List<string>>();
        foreach (var rowElement in rowsElement.EnumerateArray())
        {
            if (rowElement.ValueKind == JsonValueKind.Array)
            {
                rows.Add(rowElement.EnumerateArray()
                    .Select(ReadStructuredCellText)
                    .ToList());
                continue;
            }

            if (rowElement.ValueKind == JsonValueKind.Object)
            {
                rows.Add(rowElement.EnumerateObject()
                    .Select(property => ReadStructuredCellText(property.Value))
                    .ToList());
                continue;
            }

            rows.Add(new List<string> { ReadStructuredCellText(rowElement) });
        }

        return rows;
    }

    private static List<List<string>> ReadRowsFromCells(JsonElement cellsElement)
    {
        var rows = new List<List<string>>();
        foreach (var rowElement in cellsElement.EnumerateArray())
        {
            if (rowElement.ValueKind != JsonValueKind.Array)
            {
                continue;
            }

            var row = new List<string>();
            foreach (var cellElement in rowElement.EnumerateArray())
            {
                if (cellElement.ValueKind == JsonValueKind.Object
                    && cellElement.TryGetProperty("text", out var textElement))
                {
                    row.Add(ReadStructuredCellText(textElement));
                }
                else
                {
                    row.Add(ReadStructuredCellText(cellElement));
                }
            }
            rows.Add(row);
        }
        return rows;
    }

    private static string ReadStructuredCellText(JsonElement element)
    {
        return element.ValueKind switch
        {
            JsonValueKind.String => element.GetString() ?? string.Empty,
            JsonValueKind.Number => element.ToString(),
            JsonValueKind.True => bool.TrueString,
            JsonValueKind.False => bool.FalseString,
            JsonValueKind.Object when element.TryGetProperty("text", out var textElement) => ReadStructuredCellText(textElement),
            _ => string.Empty
        };
    }

    private static string NormalizeStructuredCellText(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return string.Empty;
        }

        return value
            .Replace("\r\n", " ")
            .Replace('\r', ' ')
            .Replace('\n', ' ')
            .Trim();
    }

    private static bool IsStructuredNoiseRow(IReadOnlyList<string> row)
    {
        var nonEmptyValues = row
            .Select(value => value.Trim())
            .Where(value => value.Length > 0)
            .ToList();
        if (nonEmptyValues.Count == 0)
        {
            return true;
        }

        if (nonEmptyValues.All(IsSeparatorToken))
        {
            return true;
        }

        return nonEmptyValues.Count == 1 && LooksLikeSerializedPayload(nonEmptyValues[0]);
    }

    private static bool IsSeparatorToken(string value)
    {
        if (value.Length < 3)
        {
            return false;
        }

        foreach (var ch in value)
        {
            if (ch == '-' || ch == '_' || ch == '=' || ch == '.' || ch == ':' || ch == '*' || ch == '/' || ch == '|')
            {
                continue;
            }

            if (!char.IsWhiteSpace(ch))
            {
                return false;
            }
        }

        return true;
    }

    private static bool LooksLikeSerializedPayload(string value)
    {
        if (value.Length < 40)
        {
            return false;
        }

        var trimmed = value.Trim();
        var looksJsonLike = (trimmed.StartsWith("{", StringComparison.Ordinal) && trimmed.Contains(":", StringComparison.Ordinal))
            || (trimmed.StartsWith("[", StringComparison.Ordinal) && trimmed.Contains(":", StringComparison.Ordinal));
        if (!looksJsonLike)
        {
            return false;
        }

        return trimmed.Contains("\"", StringComparison.Ordinal)
            || trimmed.Contains("{", StringComparison.Ordinal)
            || trimmed.Contains("[", StringComparison.Ordinal);
    }

    private static bool RowsAreEquivalent(IReadOnlyList<string> left, IReadOnlyList<string> right)
    {
        if (left.Count != right.Count)
        {
            return false;
        }

        for (var i = 0; i < left.Count; i++)
        {
            if (!string.Equals(left[i], right[i], StringComparison.OrdinalIgnoreCase))
            {
                return false;
            }
        }

        return true;
    }

    private static int? ReadPositiveInt(JsonElement element, string propertyName)
    {
        if (element.ValueKind != JsonValueKind.Object
            || !element.TryGetProperty(propertyName, out var propertyValue)
            || propertyValue.ValueKind != JsonValueKind.Number
            || !propertyValue.TryGetInt32(out var parsed)
            || parsed <= 0)
        {
            return null;
        }

        return parsed;
    }

    private static string? ReadStringValue(JsonElement element, string propertyName)
    {
        if (element.ValueKind != JsonValueKind.Object
            || !element.TryGetProperty(propertyName, out var propertyValue)
            || propertyValue.ValueKind != JsonValueKind.String)
        {
            return null;
        }

        var raw = propertyValue.GetString();
        return string.IsNullOrWhiteSpace(raw) ? null : raw.Trim();
    }

    private static void AppendRtfTable(
        global::System.Text.StringBuilder target,
        IReadOnlyList<IReadOnlyList<string>> rows,
        Func<string?, string> escape)
    {
        if (rows.Count == 0)
        {
            return;
        }

        var columnCount = rows.Max(row => row.Count);
        if (columnCount <= 0)
        {
            return;
        }

        const int tableWidth = 9000;
        var cellWidth = Math.Max(800, tableWidth / columnCount);
        for (var rowIndex = 0; rowIndex < rows.Count; rowIndex++)
        {
            target.Append("\\trowd\\trgaph108\\trleft0\\trftsWidth3\\trwWidth9000");
            if (rowIndex == 0)
            {
                target.Append("\\trhdr");
            }
            for (var colIndex = 0; colIndex < columnCount; colIndex++)
            {
                target.Append("\\clvertalc\\clpadl80\\clpadr80\\clpadfl3\\clpadfr3");
                target.Append("\\clbrdrt\\brdrs\\brdrw10\\clbrdrl\\brdrs\\brdrw10\\clbrdrb\\brdrs\\brdrw10\\clbrdrr\\brdrs\\brdrw10");
                target.Append("\\cellx").Append((colIndex + 1) * cellWidth);
            }

            var row = rows[rowIndex];
            for (var colIndex = 0; colIndex < columnCount; colIndex++)
            {
                var value = colIndex < row.Count ? row[colIndex] : string.Empty;
                if (rowIndex == 0)
                {
                    target.Append("\\intbl\\b ").Append(escape(value)).Append("\\b0\\cell");
                }
                else
                {
                    target.Append("\\intbl ").Append(escape(value)).Append("\\cell");
                }
            }
            target.Append("\\row\n");
        }
        target.Append("\\par\n");
    }

    private sealed record StructuredExportTable(int Index, string? Source, IReadOnlyList<IReadOnlyList<string>> Rows);

    private static readonly IReadOnlyDictionary<string, string> DerivedExportLabels =
        new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["banco"] = "Banco",
            ["banco_destino"] = "Banco destino",
            ["cuenta"] = "Cuenta",
            ["cuenta_retiro"] = "Cuenta retiro",
            ["cuenta_beneficiario"] = "Cuenta beneficiario",
            ["referencia"] = "Referencia",
            ["importe"] = "Importe",
            ["importe_detectado"] = "Importe detectado",
            ["total"] = "Total",
            ["concepto"] = "Concepto",
            ["concepto_pago"] = "Concepto de pago",
            ["clave_rastreo"] = "Clave de rastreo",
            ["nombre_beneficiario"] = "Nombre beneficiario",
            ["titular"] = "Titular",
            ["estatus"] = "Estatus",
            ["tipo_operacion"] = "Tipo de operacion",
            ["forma_deposito"] = "Forma de deposito",
            ["tipo_pago"] = "Tipo de pago",
            ["numero_lote"] = "Numero de lote",
            ["nombre_archivo"] = "Nombre de archivo",
            ["usuario_sistema_nombre"] = "Usuario del sistema",
            ["fecha_hora_proceso"] = "Fecha y hora de proceso",
            ["fecha_hora_captura"] = "Fecha y hora de captura",
            ["folio_internet"] = "Folio de internet",
        };

    private static string ResolveExportLabel(string key)
    {
        if (DerivedExportLabels.TryGetValue(key, out var label))
        {
            return label;
        }

        var normalized = key.Replace('_', ' ').Trim();
        return string.IsNullOrWhiteSpace(normalized) ? key : normalized;
    }

    private static string GetDisplayFieldValue(string key, string? value)
    {
        var raw = string.IsNullOrWhiteSpace(value) ? string.Empty : value.Trim();
        if (string.IsNullOrEmpty(raw))
        {
            return "-";
        }

        if (string.Equals(key, "tabla_celdas", StringComparison.OrdinalIgnoreCase))
        {
            return SummarizeTableField(raw);
        }

        if (string.Equals(key, "pago_detalle", StringComparison.OrdinalIgnoreCase))
        {
            return SummarizePaymentDetailField(raw);
        }

        if (string.Equals(key, "replica_pdf_layout", StringComparison.OrdinalIgnoreCase))
        {
            return $"Layout estructurado ({raw.Length} caracteres)";
        }

        if (string.Equals(key, "replica_pdf_texto", StringComparison.OrdinalIgnoreCase))
        {
            var lineCount = raw.Split('\n', StringSplitOptions.None).Length;
            return $"Texto replica ({lineCount} lineas)";
        }

        return raw;
    }

    private static string SummarizeTableField(string raw)
    {
        try
        {
            using var document = JsonDocument.Parse(raw);
            if (document.RootElement.ValueKind != JsonValueKind.Object)
            {
                return "Tabla estructurada";
            }

            var source = document.RootElement.TryGetProperty("source", out var sourceElement)
                ? sourceElement.GetString()
                : null;
            var bank = document.RootElement.TryGetProperty("bank", out var bankElement)
                ? bankElement.GetString()
                : null;
            var rowCount = 0;
            var columnCount = 0;
            if (document.RootElement.TryGetProperty("rows", out var rowsElement)
                && rowsElement.ValueKind == JsonValueKind.Array)
            {
                rowCount = rowsElement.GetArrayLength();
                if (rowCount > 0)
                {
                    var header = rowsElement[0];
                    if (header.ValueKind == JsonValueKind.Array)
                    {
                        columnCount = header.GetArrayLength();
                    }
                }
            }

            var dataRows = rowCount > 0 ? rowCount - 1 : 0;
            var parts = new List<string> { "Tabla estructurada" };
            if (!string.IsNullOrWhiteSpace(source))
            {
                parts.Add($"fuente={source}");
            }
            if (!string.IsNullOrWhiteSpace(bank))
            {
                parts.Add($"banco={bank}");
            }
            if (columnCount > 0)
            {
                parts.Add($"columnas={columnCount}");
            }
            if (dataRows > 0)
            {
                parts.Add($"filas={dataRows}");
            }
            return string.Join(", ", parts);
        }
        catch
        {
            return "Tabla estructurada";
        }
    }

    private static string SummarizePaymentDetailField(string raw)
    {
        try
        {
            using var document = JsonDocument.Parse(raw);
            if (document.RootElement.ValueKind != JsonValueKind.Object)
            {
                return "Detalle de pago estructurado";
            }

            var bank = document.RootElement.TryGetProperty("bank", out var bankElement)
                ? bankElement.GetString()
                : null;
            var rowCount = 0;
            if (document.RootElement.TryGetProperty("table", out var tableElement)
                && tableElement.ValueKind == JsonValueKind.Object
                && tableElement.TryGetProperty("row_count", out var rowCountElement)
                && rowCountElement.ValueKind == JsonValueKind.Number)
            {
                rowCount = rowCountElement.GetInt32();
            }

            var parts = new List<string> { "Detalle de pago estructurado" };
            if (!string.IsNullOrWhiteSpace(bank))
            {
                parts.Add($"banco={bank}");
            }
            if (rowCount > 0)
            {
                parts.Add($"filas={rowCount}");
            }
            return string.Join(", ", parts);
        }
        catch
        {
            return "Detalle de pago estructurado";
        }
    }

    private static IReadOnlyDictionary<string, string> BuildDerivedExportValues(IReadOnlyList<DocumentFieldDto> fields)
    {
        var derived = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var tableField = fields.FirstOrDefault(field =>
            string.Equals(field.Key, "tabla_celdas", StringComparison.OrdinalIgnoreCase));
        if (tableField is null)
        {
            return derived;
        }

        var raw = tableField.CorrectedValue ?? tableField.Value;
        if (string.IsNullOrWhiteSpace(raw))
        {
            return derived;
        }

        try
        {
            using var document = JsonDocument.Parse(raw);
            if (document.RootElement.ValueKind != JsonValueKind.Object)
            {
                return derived;
            }

            if (document.RootElement.TryGetProperty("mapped_fields", out var mappedElement)
                && mappedElement.ValueKind == JsonValueKind.Object)
            {
                foreach (var property in mappedElement.EnumerateObject())
                {
                    AddDerivedValue(derived, property.Name, property.Value);
                }
            }

            if (derived.Count == 0)
            {
                if (document.RootElement.TryGetProperty("bank", out var bankElement))
                {
                    AddDerivedValue(derived, "banco", bankElement);
                }

                if (document.RootElement.TryGetProperty("metadata", out var metadataElement)
                    && metadataElement.ValueKind == JsonValueKind.Object)
                {
                    foreach (var key in new[]
                    {
                        "tipo_pago",
                        "fecha_hora_proceso",
                        "fecha_hora_captura",
                        "folio_internet",
                        "numero_lote",
                        "nombre_archivo",
                        "usuario_sistema_nombre",
                        "importe_detectado",
                    })
                    {
                        if (metadataElement.TryGetProperty(key, out var valueElement))
                        {
                            AddDerivedValue(derived, key, valueElement);
                        }
                    }
                }

                if (document.RootElement.TryGetProperty("canonical_rows", out var canonicalRowsElement)
                    && canonicalRowsElement.ValueKind == JsonValueKind.Array)
                {
                    foreach (var rowElement in canonicalRowsElement.EnumerateArray())
                    {
                        if (rowElement.ValueKind != JsonValueKind.Object)
                        {
                            continue;
                        }

                        foreach (var key in new[]
                        {
                            "cuenta",
                            "cuenta_beneficiario",
                            "cuenta_retiro",
                            "banco_destino",
                            "referencia",
                            "importe",
                            "concepto_pago",
                            "clave_rastreo",
                            "nombre_beneficiario",
                            "estatus",
                            "tipo_operacion",
                            "forma_deposito",
                            "tipo_movimiento",
                            "tipo_registro",
                        })
                        {
                            if (rowElement.TryGetProperty(key, out var valueElement))
                            {
                                AddDerivedValue(derived, key, valueElement);
                            }
                        }
                        break;
                    }
                }
            }

            if (!derived.ContainsKey("concepto") && derived.TryGetValue("concepto_pago", out var concept))
            {
                derived["concepto"] = concept;
            }
            if (!derived.ContainsKey("titular") && derived.TryGetValue("nombre_beneficiario", out var beneficiary))
            {
                derived["titular"] = beneficiary;
            }
            if (!derived.ContainsKey("total") && derived.TryGetValue("importe", out var amount))
            {
                derived["total"] = amount;
            }
            if (!derived.ContainsKey("total") && derived.TryGetValue("importe_detectado", out var detectedAmount))
            {
                derived["total"] = detectedAmount;
            }
            if (!derived.ContainsKey("cuenta") && derived.TryGetValue("cuenta_beneficiario", out var beneficiaryAccount))
            {
                derived["cuenta"] = beneficiaryAccount;
            }
        }
        catch
        {
            return derived;
        }

        return derived;
    }

    private static void AddDerivedValue(Dictionary<string, string> target, string key, JsonElement valueElement)
    {
        if (string.IsNullOrWhiteSpace(key))
        {
            return;
        }

        string? value = valueElement.ValueKind switch
        {
            JsonValueKind.String => valueElement.GetString(),
            JsonValueKind.Number => valueElement.ToString(),
            JsonValueKind.True => bool.TrueString,
            JsonValueKind.False => bool.FalseString,
            _ => null
        };

        if (string.IsNullOrWhiteSpace(value))
        {
            return;
        }

        var normalized = value.Trim();
        if (string.IsNullOrWhiteSpace(normalized))
        {
            return;
        }

        if (!target.ContainsKey(key))
        {
            target[key] = normalized;
        }
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

    private static string? BuildProcessOptionsJson(DocumentProcessOptionsRequest? request)
    {
        var forced = (request?.ForceDocumentType ?? string.Empty).Trim().ToUpperInvariant();
        if (forced != "FACTURA")
        {
            return null;
        }

        return JsonSerializer.Serialize(new
        {
            force_document_type = "FACTURA"
        });
    }
}

public sealed record DocumentFailRequest(string? Reason);
public sealed record DocumentProcessOptionsRequest(string? ForceDocumentType);
