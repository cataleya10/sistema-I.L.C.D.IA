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
            CancellationToken.None);

        Assert.Equal(DocumentType.ComprobanteDomicilio, response.DocumentType);
        Assert.Contains(response.Fields, f => f.Key == "fecha_limite" && f.Value is not null);
        Assert.Contains(response.Fields, f => f.Key == "total" && f.Value == "549.00");
    }
}
