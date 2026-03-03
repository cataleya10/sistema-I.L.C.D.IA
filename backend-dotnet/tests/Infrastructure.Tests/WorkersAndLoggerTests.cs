using System.Collections.Concurrent;
using Application.DTOs;
using Application.Interfaces;
using Domain.Enums;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;
using Api.Logging;
using Api.Services;
using Shared.Options;

namespace Infrastructure.Tests;

// ── DocumentProcessingWorker ────────────────────────────────────

public class DocumentProcessingWorkerTests
{
    private static DocumentProcessResponse MakeResponse(Guid id) =>
        new(id, DocumentStatus.Ready, DocumentType.Ine, 0.95m,
            Array.Empty<DocumentFieldResultDto>(),
            Array.Empty<string>(), Array.Empty<string>(),
            new DocumentProcessMeta(1, "PaddleOCR", "v1", "v1", 200));

    // ── Fakes ────

    private sealed class FakeQueue : IProcessingQueue
    {
        private readonly ConcurrentQueue<DocumentProcessJob> _items = new();
        private readonly SemaphoreSlim _signal = new(0);

        public void Push(DocumentProcessJob job) { _items.Enqueue(job); _signal.Release(); }

        public ValueTask EnqueueAsync(DocumentProcessJob job, CancellationToken ct = default)
        {
            _items.Enqueue(job);
            _signal.Release();
            return ValueTask.CompletedTask;
        }

        public async ValueTask<DocumentProcessJob> DequeueAsync(CancellationToken ct)
        {
            await _signal.WaitAsync(ct);
            _items.TryDequeue(out var job);
            return job!;
        }
    }

    private sealed class FakeTracker : IProcessingTracker
    {
        public readonly ConcurrentDictionary<Guid, DocumentProcessResponse> Completed = new();
        public readonly ConcurrentDictionary<Guid, Exception> Failed = new();

        public (Task<DocumentProcessResponse> Task, bool Created) Register(Guid documentId)
        {
            var tcs = new TaskCompletionSource<DocumentProcessResponse>();
            return (tcs.Task, true);
        }

        public bool TryGet(Guid documentId, out Task<DocumentProcessResponse> task)
        {
            task = Task.FromResult(MakeResponse(documentId));
            return Completed.ContainsKey(documentId);
        }

        public void Complete(Guid documentId, DocumentProcessResponse response)
            => Completed[documentId] = response;

        public void Fail(Guid documentId, Exception exception)
            => Failed[documentId] = exception;

        public void Cancel(Guid documentId) { }
    }

    private sealed class FakeDocumentService : IDocumentService
    {
        public Func<Guid, string?, CancellationToken, Task<DocumentProcessResponse>>? OnProcessNow { get; set; }
        public readonly ConcurrentBag<(Guid Id, string Reason)> MarkFailedCalls = new();

        public Task<DocumentProcessResponse> ProcessNowAsync(Guid id, string? optionsJson, CancellationToken ct)
            => OnProcessNow?.Invoke(id, optionsJson, ct) ?? Task.FromResult(MakeResponse(id));

        public Task MarkFailedAsync(Guid id, string reason, CancellationToken ct)
        {
            MarkFailedCalls.Add((id, reason));
            return Task.CompletedTask;
        }

        // ── Not used by worker ──
        public Task<DocumentSummaryDto> UploadAsync(DocumentUpload u, CancellationToken ct) => throw new NotSupportedException();
        public Task<IReadOnlyList<DocumentSummaryDto>> ListAsync(DocumentListQuery q, CancellationToken ct) => throw new NotSupportedException();
        public Task<DocumentDetailDto?> GetByIdAsync(Guid id, CancellationToken ct) => throw new NotSupportedException();
        public Task<Stream?> GetFileStreamAsync(Guid id, CancellationToken ct) => throw new NotSupportedException();
        public Task<DocumentProcessResponse> ProcessAsync(Guid id, string? json, CancellationToken ct) => throw new NotSupportedException();
        public Task<DocumentProcessResponse> GetProcessStatusAsync(Guid id, CancellationToken ct) => throw new NotSupportedException();
        public Task<DocumentProcessResponse> ReprocessAsync(Guid id, string? json, CancellationToken ct) => throw new NotSupportedException();
        public Task UpdateFieldsAsync(Guid id, DocumentFieldsUpdateRequest r, CancellationToken ct) => throw new NotSupportedException();
        public Task DeleteAsync(Guid id, CancellationToken ct) => throw new NotSupportedException();
        public Task<IReadOnlyList<ProcessingLogDto>> GetLogsAsync(Guid id, CancellationToken ct) => throw new NotSupportedException();
    }

    private static ServiceProvider BuildSp(FakeDocumentService svc)
    {
        var sc = new ServiceCollection();
        sc.AddSingleton<IDocumentService>(svc);
        return sc.BuildServiceProvider();
    }

    [Fact]
    public async Task Worker_ProcessesJob_AndCompletesTracker()
    {
        var docId = Guid.NewGuid();
        var queue = new FakeQueue();
        var tracker = new FakeTracker();
        var svc = new FakeDocumentService();
        var sp = BuildSp(svc);
        var options = Options.Create(new ProcessingOptions { MaxConcurrentWorkers = 1, MaxAttempts = 1 });
        var worker = new DocumentProcessingWorker(
            NullLogger<DocumentProcessingWorker>.Instance,
            sp.GetRequiredService<IServiceScopeFactory>(),
            queue, tracker, options);

        using var cts = new CancellationTokenSource();
        await worker.StartAsync(cts.Token);

        queue.Push(new DocumentProcessJob(docId));
        await Task.Delay(300);
        await cts.CancelAsync();
        await worker.StopAsync(CancellationToken.None);

        Assert.True(tracker.Completed.ContainsKey(docId));
    }

    [Fact]
    public async Task Worker_RetriesOnFailure_ThenCompletesOnSuccess()
    {
        var docId = Guid.NewGuid();
        var queue = new FakeQueue();
        var tracker = new FakeTracker();
        var attemptCount = 0;
        var svc = new FakeDocumentService
        {
            OnProcessNow = (id, _, ct) =>
            {
                attemptCount++;
                if (attemptCount < 2)
                    throw new InvalidOperationException("Transient error");
                return Task.FromResult(MakeResponse(id));
            }
        };
        var sp = BuildSp(svc);
        var options = Options.Create(new ProcessingOptions
        {
            MaxConcurrentWorkers = 1,
            MaxAttempts = 3,
            RetryDelaySeconds = 1
        });
        var worker = new DocumentProcessingWorker(
            NullLogger<DocumentProcessingWorker>.Instance,
            sp.GetRequiredService<IServiceScopeFactory>(),
            queue, tracker, options);

        using var cts = new CancellationTokenSource();
        await worker.StartAsync(cts.Token);

        queue.Push(new DocumentProcessJob(docId));
        await Task.Delay(3000);
        await cts.CancelAsync();
        await worker.StopAsync(CancellationToken.None);

        Assert.True(tracker.Completed.ContainsKey(docId));
        Assert.Equal(2, attemptCount);
    }

    [Fact]
    public async Task Worker_FailsAndMarks_AfterMaxAttempts()
    {
        var docId = Guid.NewGuid();
        var queue = new FakeQueue();
        var tracker = new FakeTracker();
        var svc = new FakeDocumentService
        {
            OnProcessNow = (_, _, _) => throw new InvalidOperationException("Permanent error")
        };
        var sp = BuildSp(svc);
        var options = Options.Create(new ProcessingOptions
        {
            MaxConcurrentWorkers = 1,
            MaxAttempts = 2,
            RetryDelaySeconds = 1
        });
        var worker = new DocumentProcessingWorker(
            NullLogger<DocumentProcessingWorker>.Instance,
            sp.GetRequiredService<IServiceScopeFactory>(),
            queue, tracker, options);

        using var cts = new CancellationTokenSource();
        await worker.StartAsync(cts.Token);

        queue.Push(new DocumentProcessJob(docId));
        await Task.Delay(3500);
        await cts.CancelAsync();
        await worker.StopAsync(CancellationToken.None);

        Assert.True(tracker.Failed.ContainsKey(docId));
        Assert.Single(svc.MarkFailedCalls);
    }

    [Fact]
    public async Task Worker_SpawnsMultipleConcurrentWorkers()
    {
        var queue = new FakeQueue();
        var tracker = new FakeTracker();
        var concurrentCount = 0;
        var maxConcurrent = 0;
        var lockObj = new object();
        var svc = new FakeDocumentService
        {
            OnProcessNow = async (id, _, ct) =>
            {
                lock (lockObj) { concurrentCount++; maxConcurrent = Math.Max(maxConcurrent, concurrentCount); }
                await Task.Delay(200, ct);
                lock (lockObj) { concurrentCount--; }
                return MakeResponse(id);
            }
        };
        var sp = BuildSp(svc);
        var options = Options.Create(new ProcessingOptions { MaxConcurrentWorkers = 3, MaxAttempts = 1 });
        var worker = new DocumentProcessingWorker(
            NullLogger<DocumentProcessingWorker>.Instance,
            sp.GetRequiredService<IServiceScopeFactory>(),
            queue, tracker, options);

        using var cts = new CancellationTokenSource();
        await worker.StartAsync(cts.Token);

        for (var i = 0; i < 6; i++)
            queue.Push(new DocumentProcessJob(Guid.NewGuid()));

        await Task.Delay(1500);
        await cts.CancelAsync();
        await worker.StopAsync(CancellationToken.None);

        Assert.True(maxConcurrent >= 2, $"Expected concurrency >= 2, got {maxConcurrent}");
    }
}

// ── RefreshTokenCleanupWorker ───────────────────────────────────

public class RefreshTokenCleanupWorkerTests
{
    [Fact]
    public async Task ExecuteAsync_CallsRevokeExpired()
    {
        // Build a real RefreshTokenStore with temp storage so RevokeExpired is exercised
        var tempDir = Path.Combine(Path.GetTempPath(), $"rt_test_{Guid.NewGuid():N}");
        Directory.CreateDirectory(tempDir);
        try
        {
            var tokenOptions = Options.Create(new RefreshTokenOptions
            {
                StoragePath = Path.Combine(tempDir, "tokens.json"),
                CleanupIntervalMinutes = 5
            });

            var sc = new ServiceCollection();
            sc.AddDataProtection();
            sc.AddSingleton(Microsoft.Extensions.Hosting.Environments.Development);
            var sp = sc.BuildServiceProvider();

            var env = new FakeHostEnvironment(tempDir);
            var store = new RefreshTokenStore(
                tokenOptions,
                NullLogger<RefreshTokenStore>.Instance,
                env,
                sp.GetRequiredService<Microsoft.AspNetCore.DataProtection.IDataProtectionProvider>());

            // Issue a token that's already expired
            var entry = store.IssueToken("test", "Admin", TimeSpan.FromMilliseconds(-1));

            var worker = new RefreshTokenCleanupWorker(
                NullLogger<RefreshTokenCleanupWorker>.Instance,
                tokenOptions,
                store);

            using var cts = new CancellationTokenSource();
            await worker.StartAsync(cts.Token);
            await Task.Delay(300);
            await cts.CancelAsync();
            await worker.StopAsync(CancellationToken.None);

            // After cleanup, the expired token should be gone
            Assert.False(store.TryUseToken(entry.Token, out _));
        }
        finally
        {
            if (Directory.Exists(tempDir))
                Directory.Delete(tempDir, recursive: true);
        }
    }

    private sealed class FakeHostEnvironment : Microsoft.Extensions.Hosting.IHostEnvironment
    {
        public string EnvironmentName { get; set; } = "Development";
        public string ApplicationName { get; set; } = "Tests";
        public string ContentRootPath { get; set; }
        public Microsoft.Extensions.FileProviders.IFileProvider ContentRootFileProvider { get; set; } = null!;
        public FakeHostEnvironment(string root) => ContentRootPath = root;
    }
}

// ── SimpleFileLogger ────────────────────────────────────────────

public class SimpleFileLoggerTests : IDisposable
{
    private readonly string _tempDir;

    public SimpleFileLoggerTests()
    {
        _tempDir = Path.Combine(Path.GetTempPath(), $"logger_test_{Guid.NewGuid():N}");
        Directory.CreateDirectory(_tempDir);
    }

    public void Dispose()
    {
        // Allow background writer to release the file
        Thread.Sleep(200);
        try
        {
            if (Directory.Exists(_tempDir))
                Directory.Delete(_tempDir, recursive: true);
        }
        catch { /* best-effort cleanup */ }
    }

    /// <summary>Reads file with FileShare.ReadWrite to avoid locking conflicts with the background writer.</summary>
    private static string ReadFileShared(string path)
    {
        using var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        using var reader = new StreamReader(fs);
        return reader.ReadToEnd();
    }

    private static string[] ReadLinesShared(string path)
        => ReadFileShared(path).Split('\n', StringSplitOptions.RemoveEmptyEntries)
            .Select(l => l.TrimEnd('\r')).ToArray();

    [Fact]
    public void CreateLogger_ReturnsNonNull()
    {
        var path = Path.Combine(_tempDir, "test.log");
        using var provider = new SimpleFileLoggerProvider(path);
        var logger = provider.CreateLogger("TestCategory");
        Assert.NotNull(logger);
    }

    [Fact]
    public void IsEnabled_ReturnsFalse_ForNone()
    {
        var path = Path.Combine(_tempDir, "test.log");
        using var provider = new SimpleFileLoggerProvider(path);
        var logger = provider.CreateLogger("Cat");
        Assert.False(logger.IsEnabled(LogLevel.None));
    }

    [Theory]
    [InlineData(LogLevel.Trace)]
    [InlineData(LogLevel.Debug)]
    [InlineData(LogLevel.Information)]
    [InlineData(LogLevel.Warning)]
    [InlineData(LogLevel.Error)]
    [InlineData(LogLevel.Critical)]
    public void IsEnabled_ReturnsTrue_ForAllExceptNone(LogLevel level)
    {
        var path = Path.Combine(_tempDir, "test.log");
        using var provider = new SimpleFileLoggerProvider(path);
        var logger = provider.CreateLogger("Cat");
        Assert.True(logger.IsEnabled(level));
    }

    [Fact]
    public void Log_WritesToFile()
    {
        var path = Path.Combine(_tempDir, "test.log");
        using (var provider = new SimpleFileLoggerProvider(path))
        {
            var logger = provider.CreateLogger("MyCategory");
            logger.LogInformation("Hello World");
            // Allow background writer to flush
            Thread.Sleep(300);
        }

        Assert.True(File.Exists(path));
        var content = ReadFileShared(path);
        Assert.Contains("[Information]", content);
        Assert.Contains("MyCategory", content);
        Assert.Contains("Hello World", content);
    }

    [Fact]
    public void Log_IncludesExceptionInfo()
    {
        var path = Path.Combine(_tempDir, "test.log");
        using (var provider = new SimpleFileLoggerProvider(path))
        {
            var logger = provider.CreateLogger("Cat");
            logger.LogError(new InvalidOperationException("oops"), "Something failed");
            Thread.Sleep(300);
        }

        var content = ReadFileShared(path);
        Assert.Contains("InvalidOperationException", content);
        Assert.Contains("oops", content);
        Assert.Contains("Something failed", content);
    }

    [Fact]
    public void Log_IncludesTimestamp()
    {
        var path = Path.Combine(_tempDir, "test.log");
        using (var provider = new SimpleFileLoggerProvider(path))
        {
            var logger = provider.CreateLogger("Cat");
            logger.LogInformation("tick");
            Thread.Sleep(300);
        }

        var content = ReadFileShared(path);
        // ISO 8601 timestamp starts with year
        Assert.Matches(@"^\d{4}-\d{2}-\d{2}T", content);
    }

    [Fact]
    public void Log_SkipsEmptyMessages()
    {
        var path = Path.Combine(_tempDir, "test.log");
        using (var provider = new SimpleFileLoggerProvider(path))
        {
            var logger = provider.CreateLogger("Cat");
            logger.Log(LogLevel.Information, 0, "  ", null, (s, _) => "   ");
            Thread.Sleep(300);
        }

        // File might not exist or be empty since message is whitespace-only
        if (File.Exists(path))
        {
            Assert.Equal("", ReadFileShared(path).Trim());
        }
    }

    [Fact]
    public void BeginScope_ReturnsNull()
    {
        var path = Path.Combine(_tempDir, "test.log");
        using var provider = new SimpleFileLoggerProvider(path);
        var logger = provider.CreateLogger("Cat");
        Assert.Null(logger.BeginScope("scope"));
    }

    [Fact]
    public void Provider_CreatesDirectoryIfMissing()
    {
        var nested = Path.Combine(_tempDir, "sub", "deep", "test.log");
        using var provider = new SimpleFileLoggerProvider(nested);
        Assert.True(Directory.Exists(Path.GetDirectoryName(nested)));
    }

    [Fact]
    public void MultipleLogMessages_WrittenInOrder()
    {
        var path = Path.Combine(_tempDir, "test.log");
        using (var provider = new SimpleFileLoggerProvider(path))
        {
            var logger = provider.CreateLogger("Cat");
            logger.LogInformation("Line1");
            logger.LogInformation("Line2");
            logger.LogInformation("Line3");
            Thread.Sleep(500);
        }

        var lines = ReadLinesShared(path).Where(l => !string.IsNullOrWhiteSpace(l)).ToArray();
        Assert.Equal(3, lines.Length);
        Assert.Contains("Line1", lines[0]);
        Assert.Contains("Line2", lines[1]);
        Assert.Contains("Line3", lines[2]);
    }
}
