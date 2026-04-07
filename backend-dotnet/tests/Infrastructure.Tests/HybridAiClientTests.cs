using System.Net;
using System.Text;
using Domain.Enums;
using Infrastructure.Clients;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace Infrastructure.Tests;

public class HybridAiClientTests
{
    private sealed class NullHttpContextAccessor : IHttpContextAccessor
    {
        public HttpContext? HttpContext { get => null; set { } }
    }

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

            var pythonClient = new PythonAiClient(httpClient, config, new NullHttpContextAccessor());
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

        var pythonClient = new PythonAiClient(httpClient, config, new NullHttpContextAccessor());
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

            var pythonClient = new PythonAiClient(httpClient, config, new NullHttpContextAccessor());
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

    [Fact]
    public async Task ProcessDocumentAsync_FacturaMerge_PrefersStructuredPythonTableWhenCSharpTableIsNoisy()
    {
        var tempFile = Path.Combine(Path.GetTempPath(), $"{Guid.NewGuid():N}-factura-structured.txt");
        await File.WriteAllTextAsync(
            tempFile,
            """
            REPORTE DE OPERACIONES
            PAGO DE NOMINA
            CUENTA REFERENCIA IMPORTE NOMBRE
            56783223195 1620260115134340581263 $610.44 MARLA GRISELDA MENDEZ FLORES PROCESADO
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

            using var httpClient = new HttpClient(new FacturaStructuredTableHandler())
            {
                BaseAddress = new Uri("http://unit-test.local")
            };

            var pythonClient = new PythonAiClient(httpClient, config, new NullHttpContextAccessor());
            var csharpClient = new CSharpAiClient();
            var hybridClient = new HybridAiClient(
                pythonClient,
                csharpClient,
                config,
                NullLogger<HybridAiClient>.Instance);

            var response = await hybridClient.ProcessDocumentAsync(
                Guid.NewGuid(),
                tempFile,
                "pago-nomina-bbva.pdf",
                null,
                CancellationToken.None);

            var tableField = Assert.Single(response.Fields);
            Assert.Equal("tabla_celdas", tableField.Key, ignoreCase: true);
            Assert.NotNull(tableField.Value);
            Assert.Contains("\"canonical_rows\":", tableField.Value!, StringComparison.Ordinal);
            Assert.Contains("1620260115134348451388", tableField.Value!, StringComparison.Ordinal);
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
    public async Task ProcessDocumentAsync_DatosBancariosStructuredPayment_ReclassifiesToFactura()
    {
        var tempFile = Path.Combine(Path.GetTempPath(), $"{Guid.NewGuid():N}-datos-bancarios-payment.txt");
        await File.WriteAllTextAsync(
            tempFile,
            """
            REPORTE DE OPERACIONES
            SCOTIABANK
            TIPO REGISTRO CUENTA REFERENCIA IMPORTE
            DA ALTA 0007425010945541678 A246 $700.00
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

            using var httpClient = new HttpClient(new DatosBancariosStructuredPaymentHandler())
            {
                BaseAddress = new Uri("http://unit-test.local")
            };

            var pythonClient = new PythonAiClient(httpClient, config, new NullHttpContextAccessor());
            var csharpClient = new CSharpAiClient();
            var hybridClient = new HybridAiClient(
                pythonClient,
                csharpClient,
                config,
                NullLogger<HybridAiClient>.Instance);

            var response = await hybridClient.ProcessDocumentAsync(
                Guid.NewGuid(),
                tempFile,
                "pago-dispersion-scotiabank.pdf",
                null,
                CancellationToken.None);

            Assert.Equal(DocumentType.Factura, response.DocumentType);
            Assert.Contains(response.Warnings, warning => warning.Contains("DATOS_BANCARIOS", StringComparison.OrdinalIgnoreCase));

            var tableField = Assert.Single(response.Fields);
            Assert.Equal("tabla_celdas", tableField.Key, ignoreCase: true);
            Assert.NotNull(tableField.Value);
            Assert.Contains("\"canonical_rows\":", tableField.Value!, StringComparison.Ordinal);
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
    public async Task ProcessDocumentAsync_Acta_PrefersPythonWhenReady()
    {
        var tempFile = Path.Combine(Path.GetTempPath(), $"{Guid.NewGuid():N}-acta.txt");
        await File.WriteAllTextAsync(
            tempFile,
            """
            ACTA DE NACIMIENTO
            NOMBRE(S):
            SEXO H
            FECHA DE NACIMIENTO 20/08/2001
            LUGAR DE NACIMIENTO JONUTA TABASCO
            FOLIO JSP,CAPTURANCO EL LDENTIFICADORELECTRONICO
            NUMERO DE ACTA DE NACIMIENTO
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

            using var httpClient = new HttpClient(new ActaPreferPythonHandler())
            {
                BaseAddress = new Uri("http://unit-test.local")
            };

            var pythonClient = new PythonAiClient(httpClient, config, new NullHttpContextAccessor());
            var csharpClient = new CSharpAiClient();
            var hybridClient = new HybridAiClient(
                pythonClient,
                csharpClient,
                config,
                NullLogger<HybridAiClient>.Instance);

            var response = await hybridClient.ProcessDocumentAsync(
                Guid.NewGuid(),
                tempFile,
                "acta-nacimiento.pdf",
                null,
                CancellationToken.None);

            Assert.Equal(DocumentType.ActaNacimiento, response.DocumentType);
            Assert.Equal(DocumentStatus.Ready, response.Status);
            Assert.Contains(response.Fields, f => f.Key == "nombre" && f.Value == "ERWIN GUSTAVO GARCIA CAMPOS");
            Assert.Contains(response.Fields, f => f.Key == "folio" && f.Value == "0001");
            Assert.Contains(response.Fields, f => f.Key == "numero_acta" && f.Value == "437");
            Assert.DoesNotContain(response.Fields, f => f.Key == "folio" && (f.Value?.Contains("JSP", StringComparison.OrdinalIgnoreCase) ?? false));
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
    public async Task ProcessDocumentAsync_IneMerge_PrefersHigherQualityPythonName()
    {
        var tempFile = Path.Combine(Path.GetTempPath(), $"{Guid.NewGuid():N}-ine.txt");
        await File.WriteAllTextAsync(
            tempFile,
            """
            INSTITUTO NACIONAL ELECTORAL
            NOMBRE
            IA CAMPOS
            CURP GACE010425HTCRMRA8
            FECHA DE NACIMIENTO 25/04/2001
            CLAVE DE ELECTOR GRCMER01042527H100
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

            using var httpClient = new HttpClient(new IneNameMergeHandler())
            {
                BaseAddress = new Uri("http://unit-test.local")
            };

            var pythonClient = new PythonAiClient(httpClient, config, new NullHttpContextAccessor());
            var csharpClient = new CSharpAiClient();
            var hybridClient = new HybridAiClient(
                pythonClient,
                csharpClient,
                config,
                NullLogger<HybridAiClient>.Instance);

            var response = await hybridClient.ProcessDocumentAsync(
                Guid.NewGuid(),
                tempFile,
                "ine.pdf",
                null,
                CancellationToken.None);

            Assert.Equal(DocumentType.Ine, response.DocumentType);
            Assert.Contains(response.Fields, f => f.Key == "nombre" && f.Value == "ERWIN GUSTAVO GARCIA CAMPOS");
            Assert.DoesNotContain(response.Fields, f => f.Key == "nombre" && f.Value == "IA CAMPOS");
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

    private sealed class FacturaStructuredTableHandler : HttpMessageHandler
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
              "status":"READY",
              "document_type":"FACTURA",
              "confidence":0.70,
              "fields":[
                {
                  "key":"tabla_celdas",
                  "label":"Tabla celdas",
                  "value":"{\"source\":\"text_lines\",\"rows\":[[\"CUENTA\",\"REFERENCIA\",\"IMPORTE\",\"NOMBRE\",\"APELLIDO PATERNO\",\"APELLIDO MATERNO\",\"ESTATUS\",\"CONCEPTO\"],[\"56783223195\",\"1620260115134340581263\",\"$610.44\",\"MARLA GRISELDA\",\"MENDEZ\",\"FLORES\",\"PROCESADO\",\"PAGO DE NOMINA\"],[\"56936397470\",\"1620260115134348451388\",\"$1,537.35\",\"ROLANDO ROGERIO\",\"CONTRERAS\",\"CAMARGO\",\"PROCESADO\",\"PAGO DE NOMINA\"]],\"canonical_rows\":[{\"cuenta\":\"56783223195\",\"referencia\":\"1620260115134340581263\",\"importe\":\"$610.44\",\"nombre\":\"MARLA GRISELDA\",\"apellido_paterno\":\"MENDEZ\",\"apellido_materno\":\"FLORES\",\"estatus\":\"PROCESADO\",\"concepto_pago\":\"PAGO DE NOMINA\"},{\"cuenta\":\"56936397470\",\"referencia\":\"1620260115134348451388\",\"importe\":\"$1,537.35\",\"nombre\":\"ROLANDO ROGERIO\",\"apellido_paterno\":\"CONTRERAS\",\"apellido_materno\":\"CAMARGO\",\"estatus\":\"PROCESADO\",\"concepto_pago\":\"PAGO DE NOMINA\"}]}",
                  "confidence":0.70,
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
              },
              "ocr_text":"REPORTE DE OPERACIONES PAGO DE NOMINA CUENTA REFERENCIA IMPORTE NOMBRE 56783223195 1620260115134340581263 $610.44 MARLA GRISELDA MENDEZ FLORES PROCESADO"
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
              "confidence":0.70,
              "fields":[
                {
                  "key":"tabla_celdas",
                  "label":"Tabla celdas",
                  "value":"{\"source\":\"text_lines\",\"rows\":[[\"CUENTA\",\"REFERENCIA\",\"IMPORTE\",\"NOMBRE\",\"APELLIDO PATERNO\",\"APELLIDO MATERNO\",\"ESTATUS\",\"CONCEPTO\"],[\"56783223195\",\"1620260115134340581263\",\"$610.44\",\"MARLA GRISELDA\",\"MENDEZ\",\"FLORES\",\"PROCESADO\",\"PAGO DE NOMINA\"],[\"56936397470\",\"1620260115134348451388\",\"$1,537.35\",\"ROLANDO ROGERIO\",\"CONTRERAS\",\"CAMARGO\",\"PROCESADO\",\"PAGO DE NOMINA\"]],\"canonical_rows\":[{\"cuenta\":\"56783223195\",\"referencia\":\"1620260115134340581263\",\"importe\":\"$610.44\",\"nombre\":\"MARLA GRISELDA\",\"apellido_paterno\":\"MENDEZ\",\"apellido_materno\":\"FLORES\",\"estatus\":\"PROCESADO\",\"concepto_pago\":\"PAGO DE NOMINA\"},{\"cuenta\":\"56936397470\",\"referencia\":\"1620260115134348451388\",\"importe\":\"$1,537.35\",\"nombre\":\"ROLANDO ROGERIO\",\"apellido_paterno\":\"CONTRERAS\",\"apellido_materno\":\"CAMARGO\",\"estatus\":\"PROCESADO\",\"concepto_pago\":\"PAGO DE NOMINA\"}]}",
                  "confidence":0.70,
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
    }

    private sealed class DatosBancariosStructuredPaymentHandler : HttpMessageHandler
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
              "status":"READY",
              "document_type":"DATOS_BANCARIOS",
              "confidence":0.75,
              "fields":[
                {
                  "key":"tabla_celdas",
                  "label":"Tabla celdas",
                  "value":"{\"source\":\"python\",\"rows\":[[\"TIPO REGISTRO\",\"CUENTA\",\"REFERENCIA\",\"IMPORTE\",\"CLAVE DEL BENEFICIARIO\",\"NOMBRE DEL BENEFICIARIO\",\"NO. CUENTA\",\"NO. BANCO\",\"CONCEPTO\"],[\"DA ALTA\",\"04 CLIENTE ABONO EN\",\"$700.00\",\"15/01/2026\",\"A246\",\"PEREZ CORNEJO\",\"RUBEN\",\"0007425010945541678\",\"72 1\",\"PAGOS246\"]],\"canonical_rows\":[{\"tipo\":\"DA ALTA\",\"cuenta\":\"04 CLIENTE ABONO EN\",\"importe\":\"$700.00\",\"fecha\":\"15/01/2026\",\"referencia\":\"A246\",\"apellido_paterno\":\"PEREZ CORNEJO\",\"nombre\":\"RUBEN\",\"no_cuenta\":\"0007425010945541678\",\"no_banco\":\"72 1\",\"concepto_pago\":\"PAGOS246\"}]}",
                  "confidence":0.89,
                  "valid":true,
                  "validation_errors":[],
                  "source":null
                },
                {
                  "key":"folio",
                  "label":"Folio",
                  "value":"62016189548",
                  "confidence":0.93,
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
              },
              "ocr_text":"REPORTE DE OPERACIONES SCOTIABANK TIPO REGISTRO CUENTA REFERENCIA IMPORTE DA ALTA 0007425010945541678 A246 $700.00"
            }
            """;
        }

        private static string BuildExtractionPayload()
        {
            return """
            {
              "document_id":"00000000-0000-0000-0000-000000000000",
              "status":"READY",
              "document_type":"DATOS_BANCARIOS",
              "confidence":0.75,
              "fields":[
                {
                  "key":"tabla_celdas",
                  "label":"Tabla celdas",
                  "value":"{\"source\":\"python\",\"rows\":[[\"TIPO REGISTRO\",\"CUENTA\",\"REFERENCIA\",\"IMPORTE\",\"CLAVE DEL BENEFICIARIO\",\"NOMBRE DEL BENEFICIARIO\",\"NO. CUENTA\",\"NO. BANCO\",\"CONCEPTO\"],[\"DA ALTA\",\"04 CLIENTE ABONO EN\",\"$700.00\",\"15/01/2026\",\"A246\",\"PEREZ CORNEJO\",\"RUBEN\",\"0007425010945541678\",\"72 1\",\"PAGOS246\"]],\"canonical_rows\":[{\"tipo\":\"DA ALTA\",\"cuenta\":\"04 CLIENTE ABONO EN\",\"importe\":\"$700.00\",\"fecha\":\"15/01/2026\",\"referencia\":\"A246\",\"apellido_paterno\":\"PEREZ CORNEJO\",\"nombre\":\"RUBEN\",\"no_cuenta\":\"0007425010945541678\",\"no_banco\":\"72 1\",\"concepto_pago\":\"PAGOS246\"}]}",
                  "confidence":0.89,
                  "valid":true,
                  "validation_errors":[],
                  "source":null
                },
                {
                  "key":"folio",
                  "label":"Folio",
                  "value":"62016189548",
                  "confidence":0.93,
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
    }

    private sealed class IneNameMergeHandler : HttpMessageHandler
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
              "status":"READY",
              "document_type":"INE",
              "confidence":0.95,
              "fields":[],
              "warnings":[],
              "errors":[],
              "meta":{
                "pages_processed":1,
                "ocr_engine":"paddleocr",
                "pipeline_version":"python-extract-v1",
                "model_version":"clf-v1",
                "processing_ms":180
              },
              "ocr_text":"INSTITUTO NACIONAL ELECTORAL NOMBRE IA CAMPOS CURP GACE010425HTCRMRA8 FECHA DE NACIMIENTO 25/04/2001 CLAVE DE ELECTOR GRCMER01042527H100"
            }
            """;
        }

        private static string BuildExtractionPayload()
        {
            return """
            {
              "document_id":"00000000-0000-0000-0000-000000000000",
              "status":"READY",
              "document_type":"INE",
              "confidence":0.90,
              "fields":[
                {
                  "key":"nombre",
                  "label":"Nombre",
                  "value":"ERWIN GUSTAVO GARCIA CAMPOS",
                  "confidence":0.80,
                  "valid":true,
                  "validation_errors":[],
                  "source":null
                },
                {
                  "key":"curp",
                  "label":"CURP",
                  "value":"GACE010425HTCRMRA8",
                  "confidence":0.92,
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
    }

    private sealed class ActaPreferPythonHandler : HttpMessageHandler
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
              "status":"READY",
              "document_type":"ACTA_NACIMIENTO",
              "confidence":0.95,
              "fields":[
                {
                  "key":"nombre",
                  "label":"Nombre",
                  "value":"ERWIN GUSTAVO GARCIA CAMPOS",
                  "confidence":0.95,
                  "valid":true,
                  "validation_errors":[],
                  "source":null
                },
                {
                  "key":"folio",
                  "label":"Folio",
                  "value":"0001",
                  "confidence":0.95,
                  "valid":true,
                  "validation_errors":[],
                  "source":null
                },
                {
                  "key":"numero_acta",
                  "label":"Numero de acta",
                  "value":"437",
                  "confidence":0.95,
                  "valid":true,
                  "validation_errors":[],
                  "source":null
                },
                {
                  "key":"fecha_nacimiento",
                  "label":"Fecha de nacimiento",
                  "value":"20/08/2001",
                  "confidence":0.95,
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
              },
              "ocr_text":"ACTA DE NACIMIENTO NOMBRE(S): FOLIO JSP,CAPTURANCO EL LDENTIFICADORELECTRONICO NUMERO DE ACTA DE NACIMIENTO"
            }
            """;
        }

        private static string BuildExtractionPayload()
        {
            return """
            {
              "document_id":"00000000-0000-0000-0000-000000000000",
              "status":"READY",
              "document_type":"ACTA_NACIMIENTO",
              "confidence":0.95,
              "fields":[
                {
                  "key":"nombre",
                  "label":"Nombre",
                  "value":"ERWIN GUSTAVO GARCIA CAMPOS",
                  "confidence":0.95,
                  "valid":true,
                  "validation_errors":[],
                  "source":null
                },
                {
                  "key":"folio",
                  "label":"Folio",
                  "value":"0001",
                  "confidence":0.95,
                  "valid":true,
                  "validation_errors":[],
                  "source":null
                },
                {
                  "key":"numero_acta",
                  "label":"Numero de acta",
                  "value":"437",
                  "confidence":0.95,
                  "valid":true,
                  "validation_errors":[],
                  "source":null
                },
                {
                  "key":"fecha_nacimiento",
                  "label":"Fecha de nacimiento",
                  "value":"20/08/2001",
                  "confidence":0.95,
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
    }
}
