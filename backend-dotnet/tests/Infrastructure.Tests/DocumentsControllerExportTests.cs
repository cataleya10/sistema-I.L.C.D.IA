using Application.DTOs;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Spreadsheet;
using Domain.Enums;
using Infrastructure.Services;
using Xunit;

namespace Infrastructure.Tests;

public class DocumentsControllerExportTests
{
    [Fact]
    public void BuildRtf_UsesMappedFieldsFromTablaCeldas()
    {
        var detail = CreateFacturaDetailWithTablaCeldas();

        var rtf = InvokeBuildRtf(detail);

        Assert.Contains("Banco", rtf);
        Assert.Contains("BBVA", rtf);
        Assert.Contains("Cuenta", rtf);
        Assert.Contains("123456789012", rtf);
        Assert.Contains("Referencia", rtf);
        Assert.Contains("REF-7788", rtf);
        Assert.Contains("Concepto", rtf);
        Assert.Contains("Pago de nomina", rtf);
        Assert.Contains("Total", rtf);
        Assert.Contains("1500.25", rtf);
        Assert.Contains("Titular", rtf);
        Assert.Contains("JUAN PEREZ", rtf);
        Assert.Contains("Tipo de pago", rtf);
        Assert.Contains("SPEI", rtf);
        Assert.Contains("Tabla estructurada, fuente=bbva_pdf_table, banco=BBVA, columnas=4, filas=1", rtf);
        Assert.Contains("Tablas extraidas", rtf);
        Assert.Contains("Tabla 2 (bbva_pdf_table)", rtf);
        Assert.Contains("REF-9900", rtf);
        Assert.DoesNotContain("mapped_fields", rtf, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void BuildXlsx_UsesMappedFieldsFromTablaCeldas()
    {
        var detail = CreateFacturaDetailWithTablaCeldas();

        var bytes = InvokeBuildXlsx(detail);

        using var stream = new MemoryStream(bytes);
        using var spreadsheet = SpreadsheetDocument.Open(stream, false);
        var worksheetPart = GetWorksheetPartByName(spreadsheet, "Extraccion");
        var sheetData = worksheetPart.Worksheet.GetFirstChild<SheetData>()!;
        var rows = sheetData.Elements<Row>();
        var extractionRows = rows
            .Select(row => row.Elements<Cell>().Select(ReadCellText).ToArray())
            .Where(values =>
                values.Length >= 4
                && !string.IsNullOrWhiteSpace(values[0])
                && !string.Equals(values[0], "Campo", StringComparison.OrdinalIgnoreCase))
            .ToDictionary(values => values[0], values => values, StringComparer.OrdinalIgnoreCase);

        Assert.Equal("BBVA", extractionRows["Banco"][1]);
        Assert.Equal("Derivado", extractionRows["Banco"][2]);
        Assert.Equal("123456789012", extractionRows["Cuenta"][1]);
        Assert.Equal("Derivado", extractionRows["Cuenta"][2]);
        Assert.Equal("REF-7788", extractionRows["Referencia"][1]);
        Assert.Equal("Pago de nomina", extractionRows["Concepto"][1]);
        Assert.Equal("1500.25", extractionRows["Total"][1]);
        Assert.Equal("JUAN PEREZ", extractionRows["Titular"][1]);
        Assert.Equal("SPEI", extractionRows["Tipo de pago"][1]);
        Assert.StartsWith("Tabla estructurada", extractionRows["Tabla celdas"][1], StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("mapped_fields", extractionRows["Tabla celdas"][1], StringComparison.OrdinalIgnoreCase);

        var tablesWorksheetPart = GetWorksheetPartByName(spreadsheet, "Tablas");
        var tableRows = tablesWorksheetPart.Worksheet.GetFirstChild<SheetData>()!
            .Elements<Row>()
            .Select(row => row.Elements<Cell>().Select(ReadCellText).ToArray())
            .ToList();
        Assert.Contains(tableRows, values => values.Length > 0 && values[0] == "TABLAS EXTRAIDAS");
        Assert.Contains(tableRows, values => values.Length > 0 && values[0].StartsWith("Tabla 1", StringComparison.OrdinalIgnoreCase));
        Assert.Contains(tableRows, values => values.Length > 0 && values[0].StartsWith("Tabla 2", StringComparison.OrdinalIgnoreCase));
        Assert.Contains(tableRows, values =>
            values.Length >= 4
            && values[0] == "555111222333"
            && values[1] == "REF-9900"
            && values[2] == "780.00"
            && values[3] == "Pago extra");
    }

    [Fact]
    public void BuildRtf_RemovesNoiseRowsFromStructuredTables()
    {
        var detail = CreateFacturaDetailWithNoisyTablaCeldas();

        var rtf = InvokeBuildRtf(detail);

        Assert.Contains("Tabla 1 (bbva_pdf_table)", rtf);
        Assert.Contains("123456789012", rtf);
        Assert.Contains("555111222333", rtf);
        Assert.DoesNotContain("----------", rtf, StringComparison.OrdinalIgnoreCase);
        Assert.DoesNotContain("raw_payload", rtf, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void BuildXlsx_RemovesNoiseRowsFromStructuredTables()
    {
        var detail = CreateFacturaDetailWithNoisyTablaCeldas();

        var bytes = InvokeBuildXlsx(detail);

        using var stream = new MemoryStream(bytes);
        using var spreadsheet = SpreadsheetDocument.Open(stream, false);
        var tablesWorksheetPart = GetWorksheetPartByName(spreadsheet, "Tablas");
        var tableRows = tablesWorksheetPart.Worksheet.GetFirstChild<SheetData>()!
            .Elements<Row>()
            .Select(row => row.Elements<Cell>().Select(ReadCellText).ToArray())
            .ToList();

        Assert.Contains(tableRows, values =>
            values.Length >= 4
            && values[0] == "123456789012"
            && values[1] == "REF-7788"
            && values[2] == "1500.25"
            && values[3] == "Pago de nomina");
        Assert.Contains(tableRows, values =>
            values.Length >= 4
            && values[0] == "555111222333"
            && values[1] == "REF-9900"
            && values[2] == "780.00"
            && values[3] == "Pago extra");
        Assert.DoesNotContain(tableRows, values =>
            values.Any(value => value.Contains("raw_payload", StringComparison.OrdinalIgnoreCase)));
        Assert.DoesNotContain(tableRows, values =>
            values.Any(value => value.Contains("----------", StringComparison.OrdinalIgnoreCase)));
        Assert.Equal(1, tableRows.Count(values =>
            values.Length >= 4
            && values[0] == "Cuenta"
            && values[1] == "Referencia"
            && values[2] == "Importe"
            && values[3] == "Concepto"));
    }

    [Fact]
    public void BuildXlsx_PrefersCanonicalRowsWhenAvailable()
    {
        var detail = CreateFacturaDetailWithCanonicalRowsAndNoisyRawTable();

        var bytes = InvokeBuildXlsx(detail);

        using var stream = new MemoryStream(bytes);
        using var spreadsheet = SpreadsheetDocument.Open(stream, false);
        var tablesWorksheetPart = GetWorksheetPartByName(spreadsheet, "Tablas");
        var tableRows = tablesWorksheetPart.Worksheet.GetFirstChild<SheetData>()!
            .Elements<Row>()
            .Select(row => row.Elements<Cell>().Select(ReadCellText).ToArray())
            .ToList();

        Assert.Contains(tableRows, values =>
            values.Length >= 8
            && values[0] == "Cuenta"
            && values[1] == "Referencia"
            && values[2] == "Importe"
            && values[3] == "Nombre"
            && values[4] == "Apellido paterno"
            && values[5] == "Apellido materno"
            && values[6] == "Estatus"
            && values[7] == "Concepto");
        Assert.Contains(tableRows, values =>
            values.Length >= 8
            && values[0] == "56783223195"
            && values[1] == "1620260115134340581263"
            && values[2] == "$610.44"
            && values[3] == "MARLA GRISELDA"
            && values[4] == "MENDEZ"
            && values[5] == "FLORES"
            && values[6] == "PROCESADO"
            && values[7] == "PAGO DE NOMINA");
        Assert.DoesNotContain(tableRows, values =>
            values.Any(value => value.Contains("CUENTA CUENTA", StringComparison.OrdinalIgnoreCase)));
        Assert.DoesNotContain(tableRows, values =>
            values.Any(value => value.Contains("raw_payload", StringComparison.OrdinalIgnoreCase)));
    }

    private static string InvokeBuildRtf(DocumentDetailDto detail)
    {
        var service = new DocumentExportService();
        return service.BuildRtf(detail);
    }

    private static byte[] InvokeBuildXlsx(DocumentDetailDto detail)
    {
        var service = new DocumentExportService();
        return service.BuildXlsx(detail);
    }

    private static string ReadCellText(Cell cell)
    {
        if (cell.DataType?.Value == CellValues.InlineString)
        {
            return cell.InlineString?.Text?.Text ?? cell.InlineString?.InnerText ?? string.Empty;
        }

        return cell.CellValue?.Text ?? cell.InnerText ?? string.Empty;
    }

    private static WorksheetPart GetWorksheetPartByName(SpreadsheetDocument spreadsheet, string sheetName)
    {
        var workbookPart = spreadsheet.WorkbookPart!;
        var sheet = workbookPart.Workbook.Sheets!
            .Elements<Sheet>()
            .FirstOrDefault(item => string.Equals(item.Name?.Value, sheetName, StringComparison.OrdinalIgnoreCase));
        Assert.NotNull(sheet);
        return (WorksheetPart)workbookPart.GetPartById(sheet!.Id!);
    }

    private static DocumentDetailDto CreateFacturaDetailWithTablaCeldas()
    {
        var tablaCeldas = """
        {
          "source": "bbva_pdf_table",
          "bank": "BBVA",
          "rows": [
            ["Cuenta", "Referencia", "Importe", "Concepto"],
            ["123456789012", "REF-7788", "1500.25", "Pago de nomina"]
          ],
          "all_tables": [
            {
              "table_index": 1,
              "source": "bbva_pdf_table",
              "rows": [
                ["Cuenta", "Referencia", "Importe", "Concepto"],
                ["123456789012", "REF-7788", "1500.25", "Pago de nomina"]
              ]
            },
            {
              "table_index": 2,
              "source": "bbva_pdf_table",
              "rows": [
                ["Cuenta", "Referencia", "Importe", "Concepto"],
                ["555111222333", "REF-9900", "780.00", "Pago extra"]
              ]
            }
          ],
          "mapped_fields": {
            "banco": "BBVA",
            "cuenta_beneficiario": "123456789012",
            "referencia": "REF-7788",
            "concepto_pago": "Pago de nomina",
            "importe": "1500.25",
            "nombre_beneficiario": "JUAN PEREZ",
            "tipo_pago": "SPEI"
          }
        }
        """;

        return new DocumentDetailDto(
            Guid.NewGuid(),
            "bbva_transferencia.pdf",
            DocumentStatus.Ready,
            DocumentType.Factura,
            0.95m,
            new DateTime(2026, 2, 21, 10, 30, 0, DateTimeKind.Utc),
            DateTime.UtcNow,
            "/api/documents/fake/file",
            "application/pdf",
            false,
            new[]
            {
                new DocumentFieldDto(
                    "tabla_celdas",
                    "Tabla celdas",
                    tablaCeldas,
                    0.99m,
                    true,
                    Array.Empty<string>(),
                    null,
                    false,
                    null)
            },
            Array.Empty<ExtractedTableDto>());
    }

    private static DocumentDetailDto CreateFacturaDetailWithNoisyTablaCeldas()
    {
        var tablaCeldas = """
        {
          "source": "bbva_pdf_table",
          "bank": "BBVA",
          "all_tables": [
            {
              "table_index": 1,
              "source": "bbva_pdf_table",
              "rows": [
                ["Cuenta", "Referencia", "Importe", "Concepto", "", ""],
                ["----------", "----------", "----------", "----------", "", ""],
                ["123456789012", "REF-7788", "1500.25", "Pago de nomina", "", ""],
                ["Cuenta", "Referencia", "Importe", "Concepto", "", ""],
                ["{\"raw_payload\":\"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\"}", "", "", "", "", ""],
                ["555111222333", "REF-9900", "780.00", "Pago extra", "", ""]
              ]
            }
          ],
          "mapped_fields": {
            "banco": "BBVA",
            "cuenta_beneficiario": "123456789012",
            "referencia": "REF-7788",
            "concepto_pago": "Pago de nomina",
            "importe": "1500.25",
            "nombre_beneficiario": "JUAN PEREZ"
          }
        }
        """;

        return new DocumentDetailDto(
            Guid.NewGuid(),
            "bbva_transferencia.pdf",
            DocumentStatus.Ready,
            DocumentType.Factura,
            0.95m,
            new DateTime(2026, 2, 21, 10, 30, 0, DateTimeKind.Utc),
            DateTime.UtcNow,
            "/api/documents/fake/file",
            "application/pdf",
            false,
            new[]
            {
                new DocumentFieldDto(
                    "tabla_celdas",
                    "Tabla celdas",
                    tablaCeldas,
                    0.99m,
                    true,
                    Array.Empty<string>(),
                    null,
                    false,
                    null)
            },
            Array.Empty<ExtractedTableDto>());
    }

    private static DocumentDetailDto CreateFacturaDetailWithCanonicalRowsAndNoisyRawTable()
    {
        var tablaCeldas = """
        {
          "source": "bbva_pdf_table",
          "all_tables": [
            {
              "table_index": 1,
              "source": "bbva_pdf_table",
              "rows": [
                ["CUENTA CUENTA", "REFERENCIA REFERENCIA", "IMPORTE IMPORTE", "NOMBRE NOMBRE", "APELLIDO PATERNO APELLIDO MATERNO ESTATUS", "CONCEPTO CONCEPTO"],
                ["56783223195 1620260115134340581263", "$610.44 MARLA GRISELDA", "MENDEZ FLORES PROCESADO", "PAGO DE NOMINA", "{\"raw_payload\":\"zzzzzz\"}", ""]
              ]
            }
          ],
          "canonical_columns": ["cuenta", "referencia", "importe", "nombre", "apellido_paterno", "apellido_materno", "estatus", "concepto_pago"],
          "canonical_rows": [
            {
              "cuenta": "56783223195",
              "referencia": "1620260115134340581263",
              "importe": "$610.44",
              "nombre": "MARLA GRISELDA",
              "apellido_paterno": "MENDEZ",
              "apellido_materno": "FLORES",
              "estatus": "PROCESADO",
              "concepto_pago": "PAGO DE NOMINA"
            }
          ],
          "mapped_fields": {
            "banco": "BBVA",
            "cuenta_beneficiario": "56783223195",
            "referencia": "1620260115134340581263",
            "concepto_pago": "PAGO DE NOMINA",
            "importe": "$610.44",
            "nombre_beneficiario": "MARLA GRISELDA MENDEZ FLORES"
          }
        }
        """;

        return new DocumentDetailDto(
            Guid.NewGuid(),
            "bbva_nomina.pdf",
            DocumentStatus.Ready,
            DocumentType.Factura,
            0.95m,
            new DateTime(2026, 2, 21, 10, 30, 0, DateTimeKind.Utc),
            DateTime.UtcNow,
            "/api/documents/fake/file",
            "application/pdf",
            false,
            new[]
            {
                new DocumentFieldDto(
                    "tabla_celdas",
                    "Tabla celdas",
                    tablaCeldas,
                    0.99m,
                    true,
                    Array.Empty<string>(),
                    null,
                    false,
                    null)
            },
            Array.Empty<ExtractedTableDto>());
    }
}
