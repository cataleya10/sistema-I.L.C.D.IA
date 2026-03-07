using Domain.Enums;
using Infrastructure.Clients;
using Xunit;

namespace Infrastructure.Tests;

public class CSharpAiClientTests
{
    [Fact]
    public async Task ProcessDocumentAsync_ComprobanteTelmex_ExtractsDueDateAndTotal()
    {
        var tempFile = Path.Combine(Path.GetTempPath(), $"{Guid.NewGuid():N}-telmex.txt");
        await File.WriteAllTextAsync(
            tempFile,
            """
            TELMEX
            PAGAR ANTES DE: 23-ENE-2026
            TOTAL: 549.00
            CIUDAD: CONEXIA SUPERAMA
            """);

        try
        {
            var client = new CSharpAiClient();
            var response = await client.ProcessDocumentAsync(
                Guid.NewGuid(),
                tempFile,
                "Recibo-Ene.pdf",
                null,
                CancellationToken.None);

            Assert.Equal(DocumentType.ComprobanteDomicilio, response.DocumentType);
            Assert.Contains(response.Fields, f => f.Key == "fecha_limite" && f.Value is not null);
            Assert.Contains(response.Fields, f => f.Key == "total" && f.Value == "549.00");
        }
        finally
        {
            if (File.Exists(tempFile))
            {
                File.Delete(tempFile);
            }
        }
    }

    [Fact]
    public async Task ProcessTextAsync_UsesProvidedOcrText_ForTelmexDueDate()
    {
        var client = new CSharpAiClient();
        var response = await client.ProcessTextAsync(
            Guid.NewGuid(),
            """
            TELMEX
            PAGAR ANTES DE: 23-ENE-2026
            TOTAL A PAGAR: 549.00
            PUBLICO EN GENERAL
            """,
            "Recibo-Ene.pdf",
            "python-ocr",
            2,
            100,
            null,
            CancellationToken.None);

        Assert.Equal(DocumentType.ComprobanteDomicilio, response.DocumentType);
        Assert.Contains(response.Fields, f => f.Key == "fecha_limite" && f.Value is not null);
        Assert.Contains(response.Fields, f => f.Key == "total" && f.Value == "549.00");
    }

    [Fact]
    public async Task ProcessTextAsync_UsesCanonicalFieldKeys_ForDomicilioAndBank()
    {
        var client = new CSharpAiClient();

        var domicilioResponse = await client.ProcessTextAsync(
            Guid.NewGuid(),
            """
            COMPROBANTE DE DOMICILIO
            CFE
            DIRECCION: CALLE NORTE 123
            PAGAR ANTES DE: 02/02/2026
            TOTAL A PAGAR: 300.00
            """,
            "cfe.pdf",
            "python-ocr",
            1,
            0,
            null,
            CancellationToken.None);

        Assert.Contains(domicilioResponse.Fields, f => f.Key == "domicilio" && f.Value == "CALLE NORTE 123");
        Assert.DoesNotContain(domicilioResponse.Fields, f => f.Key == "direccion");

        var bankResponse = await client.ProcessTextAsync(
            Guid.NewGuid(),
            """
            ESTADO DE CUENTA
            BANCO: BBVA
            TITULAR: JUAN PEREZ
            CLABE: 012345678901234567
            NO. CUENTA: 1234567890
            """,
            "bbva.pdf",
            "python-ocr",
            1,
            0,
            null,
            CancellationToken.None);

        Assert.Contains(bankResponse.Fields, f => f.Key == "cuenta" && f.Value == "1234567890");
        Assert.DoesNotContain(bankResponse.Fields, f => f.Key == "numero_cuenta");
    }

    [Fact]
    public async Task GetOnlineLearningStatsAsync_ReturnsDisabledPayload()
    {
        var client = new CSharpAiClient();

        var stats = await client.GetOnlineLearningStatsAsync(10, CancellationToken.None);

        Assert.False(stats.Enabled);
        Assert.Equal(0, stats.DatasetSamples);
        Assert.Equal(0, stats.Totals.Attempted);
        Assert.Equal(1, stats.ByReason["not_supported_by_csharp_engine"]);
    }

    [Fact]
    public async Task ProcessTextAsync_Factura_ReturnsOnlyTablaCeldasField()
    {
        var client = new CSharpAiClient();
        var response = await client.ProcessTextAsync(
            Guid.NewGuid(),
            """
            REPORTE DE OPERACIONES
            PAGO DE NOMINA
            CUENTA   REFERENCIA   IMPORTE   ESTATUS
            56551346133   1620260115132703271255   $1,462.58   PROCESADO
            """,
            "pago-nomina.pdf",
            "python-ocr",
            1,
            0,
            null,
            CancellationToken.None);

        Assert.Equal(DocumentType.Factura, response.DocumentType);
        Assert.Contains(response.Fields, f => f.Key == "tabla_celdas" && !string.IsNullOrWhiteSpace(f.Value));
        Assert.DoesNotContain(response.Fields, f => f.Key == "banco");
        Assert.DoesNotContain(response.Fields, f => f.Key == "cuenta");
        Assert.DoesNotContain(response.Fields, f => f.Key == "referencia");
        Assert.DoesNotContain(response.Fields, f => f.Key == "concepto");
        Assert.DoesNotContain(response.Fields, f => f.Key == "total");
    }

    [Fact]
    public async Task ProcessTextAsync_Acta_DoesNotCaptureLabelNoiseInCriticalFields()
    {
        var client = new CSharpAiClient();
        var response = await client.ProcessTextAsync(
            Guid.NewGuid(),
            """
            ACTA DE NACIMIENTO
            NOMBRE(S):
            SEXO H
            FECHA DE NACIMIENTO 20/08/2001
            LUGAR DE NACIMIENTO JONUTA TABASCO
            FOLIO JSP,CAPTURANCO EL LDENTIFICADORELECTRONICO
            NUMERO DE ACTA DE NACIMIENTO
            """,
            "acta-nacimiento.pdf",
            "python-ocr",
            1,
            0,
            null,
            CancellationToken.None);

        var nombre = response.Fields.FirstOrDefault(f => f.Key == "nombre");
        var folio = response.Fields.FirstOrDefault(f => f.Key == "folio");
        var numeroActa = response.Fields.FirstOrDefault(f => f.Key == "numero_acta");

        Assert.True(nombre is null || string.IsNullOrWhiteSpace(nombre.Value));
        Assert.True(folio is null || string.IsNullOrWhiteSpace(folio.Value));
        Assert.True(numeroActa is null || string.IsNullOrWhiteSpace(numeroActa.Value));
    }

    [Fact]
    public async Task ProcessTextAsync_Acta_ExtractsStructuredTableAndPersonFields()
    {
        var client = new CSharpAiClient();
        var response = await client.ProcessTextAsync(
            Guid.NewGuid(),
            """
            ESTADOS UNIDOS MEXICANOS
            ACTA DE NACIMIENTO
            ENTIDAD DE REGISTRO TABASCO
            MUNICIPIO DE REGISTRO JONUTA
            OFICIALIA FECHA DE REGISTRO LIBRO NUMERO
            0001 20/08/2001 3 45
            DATOS DE LA PERSONA REGISTRADA
            ERWIN GUSTAVO GARCIA CAMPOS
            NOMBRE(S) PRIMER APELLIDO SEGUNDO APELLIDO
            HOMBRE 25/04/2001 JONUTA TABASCO
            SEXO FECHA DE NACIMIENTO LUGAR DE NACIMIENTO
            """,
            "acta-nacimiento.pdf",
            "python-ocr",
            1,
            0,
            null,
            CancellationToken.None);

        Assert.Equal(DocumentType.ActaNacimiento, response.DocumentType);
        Assert.Contains(response.Fields, f => f.Key == "nombre" && f.Value == "ERWIN GUSTAVO GARCIA CAMPOS");
        Assert.Contains(response.Fields, f => f.Key == "sexo" && f.Value == "HOMBRE");
        Assert.Contains(response.Fields, f => f.Key == "fecha_nacimiento" && f.Value == "25/04/2001");
        Assert.Contains(response.Fields, f => f.Key == "lugar_nacimiento" && f.Value == "JONUTA TABASCO");
        Assert.Contains(response.Fields, f => f.Key == "folio" && f.Value == "0001");
        Assert.Contains(response.Fields, f => f.Key == "numero_acta" && f.Value == "45");
        Assert.Contains(response.Fields, f => f.Key == "fecha_registro" && f.Value == "20/08/2001");
        Assert.Contains(response.Fields, f => f.Key == "municipio_registro" && f.Value == "JONUTA");
        Assert.Contains(response.Fields, f => f.Key == "entidad_registro" && f.Value == "TABASCO");
    }
}
