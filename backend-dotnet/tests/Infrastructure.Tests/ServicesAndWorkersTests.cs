using System.Text.Json;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;
using Api.Services;
using Shared.Json;
using Shared.Options;
using Application.DTOs;
using Application.Interfaces;
using Infrastructure.Services;
using Api.Controllers.System;

namespace Infrastructure.Tests;

// ── MetricsService ─────────────────────────────────────────────────
public class MetricsServiceTests
{
    [Fact]
    public void Snapshot_InitialState_AllZeros()
    {
        var svc = new MetricsService();
        var snap = svc.Snapshot();

        Assert.Equal(0, snap.Requests);
        Assert.Equal(0, snap.Errors);
        Assert.Equal(0, snap.ClientErrors);
        Assert.Equal(0d, snap.AvgDurationMs);
        Assert.Equal(0, snap.MaxDurationMs);
    }

    [Fact]
    public void Observe_200_IncrementsRequests()
    {
        var svc = new MetricsService();
        svc.Observe(50, 200);
        var snap = svc.Snapshot();

        Assert.Equal(1, snap.Requests);
        Assert.Equal(0, snap.Errors);
        Assert.Equal(0, snap.ClientErrors);
    }

    [Fact]
    public void Observe_500_IncrementsErrors()
    {
        var svc = new MetricsService();
        svc.Observe(100, 500);
        var snap = svc.Snapshot();

        Assert.Equal(1, snap.Requests);
        Assert.Equal(1, snap.Errors);
        Assert.Equal(0, snap.ClientErrors);
    }

    [Fact]
    public void Observe_400_IncrementsClientErrors()
    {
        var svc = new MetricsService();
        svc.Observe(30, 404);
        var snap = svc.Snapshot();

        Assert.Equal(1, snap.Requests);
        Assert.Equal(0, snap.Errors);
        Assert.Equal(1, snap.ClientErrors);
    }

    [Fact]
    public void Observe_MultipleCalls_CalculatesAvgAndMax()
    {
        var svc = new MetricsService();
        svc.Observe(100, 200);
        svc.Observe(200, 200);
        svc.Observe(300, 500);
        var snap = svc.Snapshot();

        Assert.Equal(3, snap.Requests);
        Assert.Equal(200d, snap.AvgDurationMs);
        Assert.Equal(300, snap.MaxDurationMs);
        Assert.Equal(1, snap.Errors);
    }

    [Fact]
    public void Snapshot_StartedAtUtc_IsReasonable()
    {
        var before = DateTime.UtcNow;
        var svc = new MetricsService();
        var after = DateTime.UtcNow;
        var snap = svc.Snapshot();

        Assert.InRange(snap.StartedAtUtc, before, after);
    }
}

// ── ProcessingTracker ──────────────────────────────────────────────
public class ProcessingTrackerTests
{
    [Fact]
    public void Register_NewId_CreatesTaskAndReturnsCreatedTrue()
    {
        var tracker = new ProcessingTracker();
        var id = Guid.NewGuid();
        var (task, created) = tracker.Register(id);

        Assert.True(created);
        Assert.NotNull(task);
        Assert.False(task.IsCompleted);
    }

    [Fact]
    public void Register_SameIdTwice_ReturnsSameTaskAndCreatedFalse()
    {
        var tracker = new ProcessingTracker();
        var id = Guid.NewGuid();
        var (task1, created1) = tracker.Register(id);
        var (task2, created2) = tracker.Register(id);

        Assert.True(created1);
        Assert.False(created2);
        Assert.Same(task1, task2);
    }

    [Fact]
    public void TryGet_RegisteredId_ReturnsTrue()
    {
        var tracker = new ProcessingTracker();
        var id = Guid.NewGuid();
        tracker.Register(id);

        Assert.True(tracker.TryGet(id, out var task));
        Assert.NotNull(task);
    }

    [Fact]
    public void TryGet_UnknownId_ReturnsFalse()
    {
        var tracker = new ProcessingTracker();
        Assert.False(tracker.TryGet(Guid.NewGuid(), out _));
    }

    [Fact]
    public async Task Complete_SetsResult()
    {
        var tracker = new ProcessingTracker();
        var id = Guid.NewGuid();
        var (task, _) = tracker.Register(id);

        var response = CreateDummyResponse(id);
        tracker.Complete(id, response);

        var result = await task;
        Assert.Equal(id, result.DocumentId);
    }

    [Fact]
    public async Task Fail_SetsException()
    {
        var tracker = new ProcessingTracker();
        var id = Guid.NewGuid();
        var (task, _) = tracker.Register(id);

        tracker.Fail(id, new InvalidOperationException("boom"));

        await Assert.ThrowsAsync<InvalidOperationException>(() => task);
    }

    [Fact]
    public async Task Cancel_SetsCancellation()
    {
        var tracker = new ProcessingTracker();
        var id = Guid.NewGuid();
        var (task, _) = tracker.Register(id);

        tracker.Cancel(id);

        await Assert.ThrowsAsync<TaskCanceledException>(() => task);
    }

    [Fact]
    public void Complete_UnregisteredId_DoesNotThrow()
    {
        var tracker = new ProcessingTracker();
        tracker.Complete(Guid.NewGuid(), CreateDummyResponse(Guid.NewGuid()));
    }

    private static DocumentProcessResponse CreateDummyResponse(Guid id) =>
        new(id, Domain.Enums.DocumentStatus.Ready, Domain.Enums.DocumentType.Ine,
            0.95m, Array.Empty<DocumentFieldResultDto>(),
            Array.Empty<ExtractedTableDto>(),
            Array.Empty<string>(), Array.Empty<string>(),
            new DocumentProcessMeta(1, "paddle", "1.0", "v1", 100));
}

// ── DocumentProcessingQueue ────────────────────────────────────────
public class DocumentProcessingQueueTests
{
    [Fact]
    public async Task Enqueue_Dequeue_ReturnsJob()
    {
        var queue = new DocumentProcessingQueue();
        var id = Guid.NewGuid();
        var job = new DocumentProcessJob(id, "{\"mode\":\"fast\"}");

        await queue.EnqueueAsync(job);
        var dequeued = await queue.DequeueAsync(CancellationToken.None);

        Assert.Equal(id, dequeued.DocumentId);
        Assert.Equal("{\"mode\":\"fast\"}", dequeued.OptionsJson);
    }

    [Fact]
    public async Task Dequeue_FIFO_Order()
    {
        var queue = new DocumentProcessingQueue();
        var id1 = Guid.NewGuid();
        var id2 = Guid.NewGuid();

        await queue.EnqueueAsync(new DocumentProcessJob(id1));
        await queue.EnqueueAsync(new DocumentProcessJob(id2));

        var first = await queue.DequeueAsync(CancellationToken.None);
        var second = await queue.DequeueAsync(CancellationToken.None);

        Assert.Equal(id1, first.DocumentId);
        Assert.Equal(id2, second.DocumentId);
    }

    [Fact]
    public async Task Dequeue_EmptyQueue_HonorsCancellation()
    {
        var queue = new DocumentProcessingQueue();
        using var cts = new CancellationTokenSource(50);

        await Assert.ThrowsAsync<OperationCanceledException>(() =>
            queue.DequeueAsync(cts.Token).AsTask());
    }
}

// ── UpperSnakeCaseNamingPolicy ─────────────────────────────────────
public class UpperSnakeCaseNamingPolicyTests
{
    private readonly UpperSnakeCaseNamingPolicy _policy = new();

    [Theory]
    [InlineData("ServiceName", "SERVICE_NAME")]
    [InlineData("PipelineVersion", "PIPELINE_VERSION")]
    [InlineData("AvgDurationMs", "AVG_DURATION_MS")]
    [InlineData("id", "ID")]
    [InlineData("A", "A")]
    public void ConvertName_ProducesExpectedOutput(string input, string expected)
    {
        Assert.Equal(expected, _policy.ConvertName(input));
    }

    [Theory]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(null)]
    public void ConvertName_NullOrWhitespace_ReturnsSame(string? input)
    {
        Assert.Equal(input, _policy.ConvertName(input!));
    }

    [Fact]
    public void ConvertName_AllCaps_InsertsUnderscores()
    {
        Assert.Equal("X_M_L", _policy.ConvertName("XML"));
    }
}

// ── SystemController ───────────────────────────────────────────────
public class SystemControllerTests
{
    private static SystemController CreateController(
        SystemInfoOptions? opts = null, MetricsService? metrics = null)
    {
        opts ??= new SystemInfoOptions();
        metrics ??= new MetricsService();
        var optionsWrapper = Options.Create(opts);
        return new SystemController(optionsWrapper, metrics)
        {
            ControllerContext = new ControllerContext { HttpContext = new DefaultHttpContext() }
        };
    }

    [Fact]
    public void Info_ReturnsOkWithServiceInfo()
    {
        var opts = new SystemInfoOptions
        {
            ServiceName = "TestService",
            PipelineVersion = "2.0",
            ModelVersion = "v2"
        };
        var ctrl = CreateController(opts);

        var result = ctrl.Info();

        var ok = Assert.IsType<OkObjectResult>(result);
        Assert.NotNull(ok.Value);
        var json = JsonSerializer.Serialize(ok.Value);
        Assert.Contains("TestService", json);
        Assert.Contains("2.0", json);
    }

    [Fact]
    public void Metrics_ReturnsOkWithMetricsSnapshot()
    {
        var metrics = new MetricsService();
        metrics.Observe(100, 200);
        metrics.Observe(50, 404);

        var ctrl = CreateController(metrics: metrics);
        var result = ctrl.Metrics();

        var ok = Assert.IsType<OkObjectResult>(result);
        Assert.NotNull(ok.Value);
        var json = JsonSerializer.Serialize(ok.Value);
        Assert.Contains("\"requests\"", json);
        Assert.Contains("\"errors\"", json);
    }

    [Fact]
    public void Info_DefaultOptions_UsesDefaults()
    {
        var ctrl = CreateController();
        var result = ctrl.Info();
        var ok = Assert.IsType<OkObjectResult>(result);
        var json = JsonSerializer.Serialize(ok.Value);
        Assert.Contains("ILCDIA API", json);
    }
}
