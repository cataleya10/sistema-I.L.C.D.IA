using System.Net;
using System.Text.Json;
using Application.DTOs;
using Domain.Enums;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Xunit;
using Infrastructure.Clients;

namespace Infrastructure.Tests;

// ── PythonAiClient ──────────────────────────────────────────────

public class PythonAiClientTests
{
    private static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
    };

    private sealed class FakeHandler : HttpMessageHandler
    {
        private readonly Func<HttpRequestMessage, Task<HttpResponseMessage>> _handler;
        public FakeHandler(Func<HttpRequestMessage, Task<HttpResponseMessage>> handler) => _handler = handler;
        public FakeHandler(Func<HttpRequestMessage, HttpResponseMessage> handler)
            : this(req => Task.FromResult(handler(req))) { }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
            => _handler(request);
    }

    private static IConfiguration BuildConfig(string baseUrl = "http://localhost:8000", string? apiKey = null, int? timeout = null)
    {
        var dict = new Dictionary<string, string?> { ["PythonAi:BaseUrl"] = baseUrl };
        if (apiKey != null) dict["PythonAi:ApiKey"] = apiKey;
        if (timeout.HasValue) dict["PythonAi:TimeoutSeconds"] = timeout.Value.ToString();
        return new ConfigurationBuilder().AddInMemoryCollection(dict).Build();
    }

    private static string MakeResponseJson(Guid docId)
    {
        var resp = new
        {
            document_id = docId,
            status = "READY",
            document_type = "INE",
            confidence = 0.95,
            fields = Array.Empty<object>(),
            warnings = Array.Empty<string>(),
            errors = Array.Empty<string>(),
            meta = new
            {
                pages_processed = 1,
                ocr_engine = "PaddleOCR",
                pipeline_version = "v1",
                model_version = "v1",
                processing_ms = 200
            }
        };
        return JsonSerializer.Serialize(resp, JsonOpts);
    }

    private static string MakeResponseJsonWithOcr(Guid docId, string ocrText)
    {
        var resp = new
        {
            document_id = docId,
            status = "READY",
            document_type = "INE",
            confidence = 0.95,
            fields = Array.Empty<object>(),
            warnings = Array.Empty<string>(),
            errors = Array.Empty<string>(),
            meta = new
            {
                pages_processed = 1,
                ocr_engine = "PaddleOCR",
                pipeline_version = "v1",
                model_version = "v1",
                processing_ms = 200
            },
            ocr_text = ocrText
        };
        return JsonSerializer.Serialize(resp, JsonOpts);
    }

    private static PythonAiClient CreateClient(FakeHandler handler, IConfiguration? config = null)
    {
        var httpClient = new HttpClient(handler);
        var accessor = new FakeHttpContextAccessor();
        return new PythonAiClient(httpClient, config ?? BuildConfig(), accessor);
    }

    private sealed class FakeHttpContextAccessor : IHttpContextAccessor
    {
        public HttpContext? HttpContext { get; set; }
    }

    // ── ProcessDocumentAsync ────

    [Fact]
    public async Task ProcessDocumentAsync_ReturnsResponse_WhenAiReturns200()
    {
        var docId = Guid.NewGuid();
        // Create a temp file to process
        var tempFile = Path.GetTempFileName();
        await File.WriteAllTextAsync(tempFile, "dummy content");
        try
        {
            var handler = new FakeHandler(_ =>
                new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(MakeResponseJson(docId), System.Text.Encoding.UTF8, "application/json")
                });

            var client = CreateClient(handler);
            var result = await client.ProcessDocumentAsync(docId, tempFile, "test.pdf", null, CancellationToken.None);

            Assert.Equal(docId, result.DocumentId);
            Assert.Equal(DocumentStatus.Ready, result.Status);
            Assert.Equal(DocumentType.Ine, result.DocumentType);
        }
        finally
        {
            File.Delete(tempFile);
        }
    }

    [Fact]
    public async Task ProcessDocumentAsync_SendsMultipartForm_WithDocumentId()
    {
        var docId = Guid.NewGuid();
        var tempFile = Path.GetTempFileName();
        await File.WriteAllTextAsync(tempFile, "test");
        HttpRequestMessage? captured = null;

        try
        {
            var handler = new FakeHandler(req =>
            {
                captured = req;
                return new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(MakeResponseJson(docId), System.Text.Encoding.UTF8, "application/json")
                };
            });

            var client = CreateClient(handler);
            await client.ProcessDocumentAsync(docId, tempFile, "test.pdf", null, CancellationToken.None);

            Assert.NotNull(captured);
            Assert.Equal(HttpMethod.Post, captured!.Method);
            Assert.Contains("/process-document", captured.RequestUri!.ToString());
        }
        finally
        {
            File.Delete(tempFile);
        }
    }

    [Fact]
    public async Task ProcessDocumentAsync_Throws_WhenAiReturns500()
    {
        var tempFile = Path.GetTempFileName();
        await File.WriteAllTextAsync(tempFile, "test");

        try
        {
            var handler = new FakeHandler(_ =>
                new HttpResponseMessage(HttpStatusCode.InternalServerError));

            var client = CreateClient(handler);
            await Assert.ThrowsAsync<HttpRequestException>(
                () => client.ProcessDocumentAsync(Guid.NewGuid(), tempFile, "test.pdf", null, CancellationToken.None));
        }
        finally
        {
            File.Delete(tempFile);
        }
    }

    [Fact]
    public async Task ProcessDocumentAsync_IncludesApiKey_WhenConfigured()
    {
        var docId = Guid.NewGuid();
        var tempFile = Path.GetTempFileName();
        await File.WriteAllTextAsync(tempFile, "test");
        HttpRequestMessage? captured = null;

        try
        {
            var handler = new FakeHandler(req =>
            {
                captured = req;
                return new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(MakeResponseJson(docId), System.Text.Encoding.UTF8, "application/json")
                };
            });

            var config = BuildConfig(apiKey: "secret-key-123");
            var client = CreateClient(handler, config);
            await client.ProcessDocumentAsync(docId, tempFile, "test.pdf", null, CancellationToken.None);

            Assert.True(captured!.Headers.Contains("X-Api-Key"));
            Assert.Equal("secret-key-123", captured.Headers.GetValues("X-Api-Key").First());
        }
        finally
        {
            File.Delete(tempFile);
        }
    }

    // ── GetOnlineLearningStatsAsync ────

    [Fact]
    public async Task GetOnlineLearningStatsAsync_ReturnsStats()
    {
        var statsJson = JsonSerializer.Serialize(new
        {
            enabled = true,
            stats_path = "/stats",
            dataset_path = "/data",
            model_path = "/model",
            alias_path = "/alias",
            updated_at_utc = (string?)null,
            dataset_samples = 10,
            totals = new { total = 5, accepted = 3, rejected = 2 },
            by_reason = new Dictionary<string, int> { ["correction"] = 3 },
            by_document_type = new Dictionary<string, object>(),
            last_event = (object?)null,
            recent_events = Array.Empty<object>()
        }, JsonOpts);

        var handler = new FakeHandler(_ =>
            new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(statsJson, System.Text.Encoding.UTF8, "application/json")
            });

        var client = CreateClient(handler);
        var result = await client.GetOnlineLearningStatsAsync(10, CancellationToken.None);

        Assert.True(result.Enabled);
        Assert.Equal(10, result.DatasetSamples);
        Assert.Equal("/stats", result.StatsPath);
    }

    [Fact]
    public async Task GetOnlineLearningStatsAsync_ClampsRecentTo100()
    {
        HttpRequestMessage? captured = null;
        var statsJson = JsonSerializer.Serialize(new
        {
            enabled = false,
            stats_path = "",
            dataset_path = "",
            model_path = "",
            alias_path = "",
            updated_at_utc = (string?)null,
            dataset_samples = 0,
            totals = new { total = 0, accepted = 0, rejected = 0 },
            by_reason = new Dictionary<string, int>(),
            by_document_type = new Dictionary<string, object>(),
            last_event = (object?)null,
            recent_events = Array.Empty<object>()
        }, JsonOpts);

        var handler = new FakeHandler(req =>
        {
            captured = req;
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(statsJson, System.Text.Encoding.UTF8, "application/json")
            };
        });

        var client = CreateClient(handler);
        await client.GetOnlineLearningStatsAsync(999, CancellationToken.None);

        Assert.Contains("recent=100", captured!.RequestUri!.ToString());
    }

    // ── MergeOptionsWithOcrFlag (via ExtractOcrAsync) ────

    [Fact]
    public async Task ExtractOcrAsync_IncludesReturnOcrTextFlag()
    {
        var docId = Guid.NewGuid();
        var tempFile = Path.GetTempFileName();
        await File.WriteAllTextAsync(tempFile, "test image");
        string? capturedOptions = null;

        try
        {
            var handler = new FakeHandler(async req =>
            {
                if (req.Content is MultipartFormDataContent multipart)
                {
                    foreach (var part in multipart)
                    {
                        if (part.Headers.ContentDisposition?.Name?.Trim('"') == "options")
                        {
                            capturedOptions = await part.ReadAsStringAsync();
                        }
                    }
                }
                var json = MakeResponseJsonWithOcr(docId, "Hello OCR");
                return new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(json, System.Text.Encoding.UTF8, "application/json")
                };
            });

            var client = CreateClient(handler);
            var result = await client.ExtractOcrAsync(docId, tempFile, "test.pdf", null, CancellationToken.None);

            Assert.NotNull(capturedOptions);
            Assert.Contains("return_ocr_text", capturedOptions!);
            Assert.Equal("Hello OCR", result.OcrText);
        }
        finally
        {
            File.Delete(tempFile);
        }
    }

    // ── Correlation ID forwarding ────

    [Fact]
    public async Task ProcessDocumentAsync_ForwardsCorrelationId_WhenPresent()
    {
        var docId = Guid.NewGuid();
        var tempFile = Path.GetTempFileName();
        await File.WriteAllTextAsync(tempFile, "test");
        HttpRequestMessage? captured = null;

        try
        {
            var handler = new FakeHandler(req =>
            {
                captured = req;
                return new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(MakeResponseJson(docId), System.Text.Encoding.UTF8, "application/json")
                };
            });

            // Set up an HttpContext with correlation ID
            var httpContext = new DefaultHttpContext();
            httpContext.Request.Headers["X-Correlation-Id"] = "corr-123";
            var accessor = new FakeHttpContextAccessor { HttpContext = httpContext };

            var config = BuildConfig();
            var client = new PythonAiClient(new HttpClient(handler), config, accessor);
            await client.ProcessDocumentAsync(docId, tempFile, "test.pdf", null, CancellationToken.None);

            Assert.True(captured!.Headers.Contains("X-Correlation-Id"));
            Assert.Equal("corr-123", captured.Headers.GetValues("X-Correlation-Id").First());
        }
        finally
        {
            File.Delete(tempFile);
        }
    }

    // ── Timeout config ────

    [Fact]
    public void Constructor_SetsTimeoutFromConfig()
    {
        var handler = new FakeHandler(_ => new HttpResponseMessage(HttpStatusCode.OK));
        var httpClient = new HttpClient(handler);
        var config = BuildConfig(timeout: 60);
        var accessor = new FakeHttpContextAccessor();

        _ = new PythonAiClient(httpClient, config, accessor);

        Assert.Equal(TimeSpan.FromSeconds(60), httpClient.Timeout);
    }

    [Fact]
    public void Constructor_DefaultsTimeout_WhenNotConfigured()
    {
        var handler = new FakeHandler(_ => new HttpResponseMessage(HttpStatusCode.OK));
        var httpClient = new HttpClient(handler);
        var config = BuildConfig();
        var accessor = new FakeHttpContextAccessor();

        _ = new PythonAiClient(httpClient, config, accessor);

        Assert.Equal(TimeSpan.FromSeconds(300), httpClient.Timeout);
    }
}
