using System.Net;
using System.Text;
using Domain.Enums;
using Infrastructure.Clients;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace Infrastructure.Tests;

public class HybridAiClientTests
{
    [Fact]
    public async Task ProcessDocumentAsync_MergesPythonFieldsIntoPreferredResponse()
    {
        var tempFile = Path.Combine(Path.GetTempPath(), $"{Guid.NewGuid():N}-hybrid.txt");
        await File.WriteAllTextAsync(
            tempFile,
            """
            TELMEX
            PAGAR ANTES DE: 23-ENE-2026
            TOTAL A PAGAR: 549.00
            """);

        try
        {
            var config = new ConfigurationBuilder()
                .AddInMemoryCollection(new Dictionary<string, string?>
                {
                    ["PythonAi:BaseUrl"] = "http://unit-test.local",
                    ["AiEngine:Hybrid:EnablePythonFallback"] = "true",
                    ["AiEngine:Hybrid:FallbackMinConfidence"] = "0.8",
                    ["AiEngine:Hybrid:AlwaysMergePythonFields"] = "true"
                })
                .Build();

            using var httpClient = new HttpClient(new StubPythonHandler())
            {
                BaseAddress = new Uri("http://unit-test.local")
            };

            var pythonClient = new PythonAiClient(httpClient, config);
            var csharpClient = new CSharpAiClient();
            var hybridClient = new HybridAiClient(
                pythonClient,
                csharpClient,
                config,
                NullLogger<HybridAiClient>.Instance);

            var response = await hybridClient.ProcessDocumentAsync(
                Guid.NewGuid(),
                tempFile,
                "recibo-telmex.pdf",
                null,
                CancellationToken.None);

            Assert.Equal(DocumentType.ComprobanteDomicilio, response.DocumentType);
            Assert.Equal(DocumentStatus.Ready, response.Status);
            Assert.Contains(response.Fields, f => f.Key == "fecha_limite" && f.Value == "23-ENE-2026");
            Assert.Contains(response.Fields, f => f.Key == "medidor" && f.Value == "A1B2C3D4");
            Assert.Contains(response.Fields, f => f.Key == "cp" && f.Value == "12345");
            Assert.Contains("hybrid-merge-v1", response.Meta.PipelineVersion, StringComparison.OrdinalIgnoreCase);
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
    public async Task GetOnlineLearningStatsAsync_ForwardsPythonStats()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["PythonAi:BaseUrl"] = "http://unit-test.local"
            })
            .Build();

        using var httpClient = new HttpClient(new StubPythonHandler())
        {
            BaseAddress = new Uri("http://unit-test.local")
        };

        var pythonClient = new PythonAiClient(httpClient, config);
        var csharpClient = new CSharpAiClient();
        var hybridClient = new HybridAiClient(
            pythonClient,
            csharpClient,
            config,
            NullLogger<HybridAiClient>.Instance);

        var stats = await hybridClient.GetOnlineLearningStatsAsync(5, CancellationToken.None);

        Assert.True(stats.Enabled);
        Assert.Equal(12, stats.DatasetSamples);
        Assert.Equal(15, stats.Totals.Attempted);
        Assert.Equal(10, stats.Totals.Trained);
        Assert.Equal(5, stats.Totals.Skipped);
    }

    [Fact]
    public async Task ProcessDocumentAsync_FacturaPolicy_OnlyKeepsTablaCeldas()
    {
        var tempFile = Path.Combine(Path.GetTempPath(), $"{Guid.NewGuid():N}-factura.txt");
        await File.WriteAllTextAsync(
            tempFile,
            """
            REPORTE DE OPERACIONES
            PAGO DE NOMINA
            CUENTA   REFERENCIA   IMPORTE   ESTATUS
            56551346133   1620260115132703271255   $1,462.58   PROCESADO
            """);

        try
        {
            var config = new ConfigurationBuilder()
                .AddInMemoryCollection(new Dictionary<string, string?>
                {
                    ["PythonAi:BaseUrl"] = "http://unit-test.local",
                    ["AiEngine:Hybrid:EnablePythonFallback"] = "true",
                    ["AiEngine:Hybrid:FallbackMinConfidence"] = "0.8",
                    ["AiEngine:Hybrid:AlwaysMergePythonFields"] = "true"
                })
                .Build();

            using var httpClient = new HttpClient(new FacturaPolicyHandler())
            {
                BaseAddress = new Uri("http://unit-test.local")
            };

            var pythonClient = new PythonAiClient(httpClient, config);
            var csharpClient = new CSharpAiClient();
            var hybridClient = new HybridAiClient(
                pythonClient,
                csharpClient,
                config,
                NullLogger<HybridAiClient>.Instance);

            var response = await hybridClient.ProcessDocumentAsync(
                Guid.NewGuid(),
                tempFile,
                "pago-nomina.pdf",
                null,
                CancellationToken.None);

            Assert.Equal(DocumentType.Factura, response.DocumentType);
            Assert.Contains(response.Fields, f => f.Key == "tabla_celdas" && !string.IsNullOrWhiteSpace(f.Value));
            Assert.DoesNotContain(response.Fields, f => !string.Equals(f.Key, "tabla_celdas", StringComparison.OrdinalIgnoreCase));
        }
        finally
        {
            if (File.Exists(tempFile))
            {
                File.Delete(tempFile);
            }
        }
    }

    private sealed class StubPythonHandler : HttpMessageHandler
    {
        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            if (request.Method == HttpMethod.Get
                && request.RequestUri is not null
                && request.RequestUri.AbsolutePath.Contains("/online-learning/stats", StringComparison.OrdinalIgnoreCase))
            {
                return new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(BuildOnlineLearningStatsPayload(), Encoding.UTF8, "application/json")
                };
            }

            var body = request.Content is null
                ? string.Empty
                : await request.Content.ReadAsStringAsync(cancellationToken);

            var isOcrOnly = body.Contains("return_ocr_text", StringComparison.OrdinalIgnoreCase);
            var payload = isOcrOnly ? BuildOcrPayload() : BuildExtractionPayload();

            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(payload, Encoding.UTF8, "application/json")
            };
        }

        private static string BuildOcrPayload()
        {
            return """
            {
              "document_id":"00000000-0000-0000-0000-000000000000",
              "status":"NEEDS_REVIEW",
              "document_type":"COMPROBANTE_DOMICILIO",
              "confidence":0.62,
              "fields":[],
              "warnings":[],
              "errors":[],
              "meta":{
                "pages_processed":1,
                "ocr_engine":"paddleocr",
                "pipeline_version":"python-ocr-only-v1",
                "model_version":"clf-v1",
                "processing_ms":90
              },
              "ocr_text":"TELMEX PAGAR ANTES DE: 23-ENE-2026 TOTAL A PAGAR: 549.00"
            }
            """;
        }

        private static string BuildExtractionPayload()
        {
            return """
            {
              "document_id":"00000000-0000-0000-0000-000000000000",
              "status":"READY",
              "document_type":"COMPROBANTE_DOMICILIO",
              "confidence":0.95,
              "fields":[
                {
                  "key":"medidor",
                  "label":"Medidor",
                  "value":"A1B2C3D4",
                  "confidence":0.93,
                  "valid":true,
                  "validation_errors":[],
                  "source":null
                },
                {
                  "key":"cp",
                  "label":"CP",
                  "value":"12345",
                  "confidence":0.91,
                  "valid":true,
                  "validation_errors":[],
                  "source":null
                }
              ],
              "warnings":[],
              "errors":[],
              "meta":{
                "pages_processed":1,
                "ocr_engine":"paddleocr",
                "pipeline_version":"python-extract-v1",
                "model_version":"clf-v1",
                "processing_ms":180
              }
            }
            """;
        }

        private static string BuildOnlineLearningStatsPayload()
        {
            return """
            {
              "enabled": true,
              "stats_path": "/tmp/online_training_stats.json",
              "dataset_path": "/tmp/online_training_dataset.jsonl",
              "model_path": "/tmp/doc_type_nb.json",
              "alias_path": "/tmp/field_aliases.json",
              "updated_at_utc": "2026-02-17T16:30:00+00:00",
              "dataset_samples": 12,
              "totals": {
                "attempted": 15,
                "trained": 10,
                "skipped": 5
              },
              "by_reason": {
                "trained": 10,
                "status_not_ready": 5
              },
              "by_document_type": {
                "INE": {
                  "attempted": 8,
                  "trained": 6,
                  "skipped": 2
                }
              },
              "last_event": {
                "timestamp_utc": "2026-02-17T16:29:58+00:00",
                "document_id": "00000000-0000-0000-0000-000000000001",
                "document_type": "INE",
                "status": "READY",
                "confidence": 0.93,
                "trained": true,
                "reason": "trained",
                "labels": 7
              },
              "recent_events": []
            }
            """;
        }
    }

    private sealed class FacturaPolicyHandler : HttpMessageHandler
    {
        protected override async Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            var body = request.Content is null
                ? string.Empty
                : await request.Content.ReadAsStringAsync(cancellationToken);

            var isOcrOnly = body.Contains("return_ocr_text", StringComparison.OrdinalIgnoreCase);
            var payload = isOcrOnly ? BuildOcrPayload() : BuildExtractionPayload();

            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(payload, Encoding.UTF8, "application/json")
            };
        }

        private static string BuildOcrPayload()
        {
            return """
            {
              "document_id":"00000000-0000-0000-0000-000000000000",
              "status":"NEEDS_REVIEW",
              "document_type":"FACTURA",
              "confidence":0.62,
              "fields":[],
              "warnings":[],
              "errors":[],
              "meta":{
                "pages_processed":1,
                "ocr_engine":"paddleocr",
                "pipeline_version":"python-ocr-only-v1",
                "model_version":"clf-v1",
                "processing_ms":90
              },
              "ocr_text":"PAGO DE NOMINA CUENTA REFERENCIA IMPORTE ESTATUS 56551346133 1620260115132703271255 $1,462.58 PROCESADO"
            }
            """;
        }

        private static string BuildExtractionPayload()
        {
            return """
            {
              "document_id":"00000000-0000-0000-0000-000000000000",
              "status":"READY",
              "document_type":"FACTURA",
              "confidence":0.95,
              "fields":[
                {
                  "key":"tabla_celdas",
                  "label":"Tabla celdas",
                  "value":"{\"source\":\"python\",\"rows\":[[\"CUENTA\",\"REFERENCIA\",\"IMPORTE\"],[\"56551346133\",\"1620260115132703271255\",\"$1,462.58\"]]}",
                  "confidence":0.93,
                  "valid":true,
                  "validation_errors":[],
                  "source":null
                },
                {
                  "key":"banco",
                  "label":"Banco",
                  "value":"TEXTO NO DESEADO",
                  "confidence":0.55,
                  "valid":false,
                  "validation_errors":["Banco invalido."],
                  "source":null
                }
              ],
              "warnings":[],
              "errors":[],
              "meta":{
                "pages_processed":1,
                "ocr_engine":"paddleocr",
                "pipeline_version":"python-extract-v1",
                "model_version":"clf-v1",
                "processing_ms":180
              }
            }
            """;
        }
    }
}
