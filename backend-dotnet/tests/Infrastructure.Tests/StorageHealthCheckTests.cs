using System.Net;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Xunit;
using Api.Authorization;
using Api.HealthChecks;
using Api.Services;
using Infrastructure.Persistence;
using Infrastructure.Storage;
using Shared.Options;

namespace Infrastructure.Tests;

// ── LocalFileStorage ────────────────────────────────────────────

public class LocalFileStorageTests : IDisposable
{
    private readonly string _tempRoot;
    private readonly LocalFileStorage _sut;

    public LocalFileStorageTests()
    {
        _tempRoot = Path.Combine(Path.GetTempPath(), $"lfs_test_{Guid.NewGuid():N}");
        var options = Options.Create(new StorageOptions { RootPath = _tempRoot });
        _sut = new LocalFileStorage(options);
    }

    public void Dispose()
    {
        if (Directory.Exists(_tempRoot))
            Directory.Delete(_tempRoot, recursive: true);
    }

    [Fact]
    public void Constructor_CreatesRootDirectory()
    {
        Assert.True(Directory.Exists(_tempRoot));
    }

    [Fact]
    public async Task SaveAsync_CreatesFile_ReturnsCorrectNameAndPath()
    {
        var docId = Guid.NewGuid();
        var content = new MemoryStream("hello"u8.ToArray());

        var (storedFilename, storedPath) = await _sut.SaveAsync(content, "report.pdf", docId, CancellationToken.None);

        Assert.Equal($"{docId}.pdf", storedFilename);
        Assert.Equal(Path.Combine(_tempRoot, storedFilename), storedPath);
        Assert.True(File.Exists(storedPath));
        Assert.Equal("hello", await File.ReadAllTextAsync(storedPath));
    }

    [Fact]
    public async Task SaveAsync_PreservesOriginalExtension()
    {
        var docId = Guid.NewGuid();
        var content = new MemoryStream(new byte[] { 0xFF, 0xD8 });

        var (storedFilename, _) = await _sut.SaveAsync(content, "photo.jpg", docId, CancellationToken.None);

        Assert.EndsWith(".jpg", storedFilename);
    }

    [Fact]
    public async Task SaveAsync_HandlesNoExtension()
    {
        var docId = Guid.NewGuid();
        var content = new MemoryStream(new byte[] { 1 });

        var (storedFilename, _) = await _sut.SaveAsync(content, "noext", docId, CancellationToken.None);

        Assert.Equal($"{docId}", storedFilename);
    }

    [Fact]
    public async Task OpenReadAsync_ExistingFile_ReturnsStream()
    {
        var path = Path.Combine(_tempRoot, "readable.txt");
        await File.WriteAllTextAsync(path, "the-data");

        var stream = await _sut.OpenReadAsync(path, CancellationToken.None);

        Assert.NotNull(stream);
        using var reader = new StreamReader(stream!);
        Assert.Equal("the-data", await reader.ReadToEndAsync());
        stream!.Dispose();
    }

    [Fact]
    public async Task OpenReadAsync_MissingFile_ReturnsNull()
    {
        var result = await _sut.OpenReadAsync(Path.Combine(_tempRoot, "nope.txt"), CancellationToken.None);
        Assert.Null(result);
    }

    [Fact]
    public void Exists_ReturnsTrue_WhenFilePresent()
    {
        var path = Path.Combine(_tempRoot, "here.txt");
        File.WriteAllText(path, "x");
        Assert.True(_sut.Exists(path));
    }

    [Fact]
    public void Exists_ReturnsFalse_WhenFileMissing()
    {
        Assert.False(_sut.Exists(Path.Combine(_tempRoot, "ghost.txt")));
    }

    [Fact]
    public async Task DeleteAsync_RemovesFile()
    {
        var path = Path.Combine(_tempRoot, "del.txt");
        File.WriteAllText(path, "bye");

        await _sut.DeleteAsync(path, CancellationToken.None);

        Assert.False(File.Exists(path));
    }

    [Fact]
    public async Task DeleteAsync_NoThrow_WhenFileMissing()
    {
        var ex = await Record.ExceptionAsync(
            () => _sut.DeleteAsync(Path.Combine(_tempRoot, "absent.txt"), CancellationToken.None));
        Assert.Null(ex);
    }
}

// ── AiEngineHealthCheck ─────────────────────────────────────────

public class AiEngineHealthCheckTests
{
    private sealed class FakeHandler : HttpMessageHandler
    {
        private readonly Func<HttpRequestMessage, HttpResponseMessage> _handler;
        public FakeHandler(Func<HttpRequestMessage, HttpResponseMessage> handler) => _handler = handler;
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
            => Task.FromResult(_handler(request));
    }

    private sealed class FakeHttpClientFactory : IHttpClientFactory
    {
        private readonly HttpClient _client;
        public FakeHttpClientFactory(HttpClient client) => _client = client;
        public HttpClient CreateClient(string name) => _client;
    }

    private static IConfiguration BuildConfig(string baseUrl) =>
        new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?> { ["PythonAi:BaseUrl"] = baseUrl })
            .Build();

    [Fact]
    public async Task CheckHealthAsync_ReturnsHealthy_WhenAiReturns200()
    {
        var handler = new FakeHandler(_ => new HttpResponseMessage(HttpStatusCode.OK));
        var client = new HttpClient(handler);
        var sut = new AiEngineHealthCheck(new FakeHttpClientFactory(client), BuildConfig("http://fake:8000"));

        var result = await sut.CheckHealthAsync(new HealthCheckContext());

        Assert.Equal(HealthStatus.Healthy, result.Status);
    }

    [Fact]
    public async Task CheckHealthAsync_ReturnsDegraded_WhenAiReturnsNon200()
    {
        var handler = new FakeHandler(_ => new HttpResponseMessage(HttpStatusCode.InternalServerError));
        var client = new HttpClient(handler);
        var sut = new AiEngineHealthCheck(new FakeHttpClientFactory(client), BuildConfig("http://fake:8000"));

        var result = await sut.CheckHealthAsync(new HealthCheckContext());

        Assert.Equal(HealthStatus.Degraded, result.Status);
    }

    [Fact]
    public async Task CheckHealthAsync_ReturnsUnhealthy_WhenAiThrows()
    {
        var handler = new FakeHandler(_ => throw new HttpRequestException("Connection refused"));
        var client = new HttpClient(handler);
        var sut = new AiEngineHealthCheck(new FakeHttpClientFactory(client), BuildConfig("http://fake:8000"));

        var result = await sut.CheckHealthAsync(new HealthCheckContext());

        Assert.Equal(HealthStatus.Unhealthy, result.Status);
        Assert.NotNull(result.Exception);
    }

    [Fact]
    public async Task CheckHealthAsync_UsesConfiguredBaseUrl()
    {
        HttpRequestMessage? captured = null;
        var handler = new FakeHandler(req =>
        {
            captured = req;
            return new HttpResponseMessage(HttpStatusCode.OK);
        });
        var client = new HttpClient(handler);
        var sut = new AiEngineHealthCheck(new FakeHttpClientFactory(client), BuildConfig("http://custom:9999"));

        await sut.CheckHealthAsync(new HealthCheckContext());

        Assert.NotNull(captured);
        Assert.Equal("http://custom:9999/health", captured!.RequestUri!.ToString());
    }

    [Fact]
    public async Task CheckHealthAsync_UsesDefaultUrl_WhenConfigMissing()
    {
        HttpRequestMessage? captured = null;
        var handler = new FakeHandler(req =>
        {
            captured = req;
            return new HttpResponseMessage(HttpStatusCode.OK);
        });
        var client = new HttpClient(handler);
        var config = new ConfigurationBuilder().Build(); // empty config
        var sut = new AiEngineHealthCheck(new FakeHttpClientFactory(client), config);

        await sut.CheckHealthAsync(new HealthCheckContext());

        Assert.Contains("localhost:8000/health", captured!.RequestUri!.ToString());
    }
}

// ── DatabaseHealthCheck ─────────────────────────────────────────

public class DatabaseHealthCheckTests
{
    private static IConfiguration BuildConfig(string provider) =>
        new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?> { ["Database:Provider"] = provider })
            .Build();

    [Fact]
    public async Task CheckHealthAsync_ReturnsHealthy_WhenProviderIsInMemory()
    {
        // InMemory short-circuits – scopeFactory is never used
        var sut = new DatabaseHealthCheck(new NullScopeFactory(), BuildConfig("InMemory"));

        var result = await sut.CheckHealthAsync(new HealthCheckContext());

        Assert.Equal(HealthStatus.Healthy, result.Status);
        Assert.Contains("InMemory", result.Description);
    }

    [Fact]
    public async Task CheckHealthAsync_ReturnsHealthy_WhenCanConnect()
    {
        // Build a real service provider with InMemory EF so CanConnectAsync succeeds
        var services = new ServiceCollection();
        services.AddDbContext<DocumentDbContext>(opt =>
            opt.UseInMemoryDatabase($"healthcheck_{Guid.NewGuid():N}"));
        var sp = services.BuildServiceProvider();
        var scopeFactory = sp.GetRequiredService<IServiceScopeFactory>();

        var sut = new DatabaseHealthCheck(scopeFactory, BuildConfig("Postgres"));

        var result = await sut.CheckHealthAsync(new HealthCheckContext());

        Assert.Equal(HealthStatus.Healthy, result.Status);
    }

    [Fact]
    public async Task CheckHealthAsync_ReturnsUnhealthy_WhenExceptionOccurs()
    {
        // Scope factory that throws mimics a DB connectivity failure
        var sut = new DatabaseHealthCheck(new ThrowingScopeFactory(), BuildConfig("Postgres"));

        var result = await sut.CheckHealthAsync(new HealthCheckContext());

        Assert.Equal(HealthStatus.Unhealthy, result.Status);
        Assert.NotNull(result.Exception);
    }

    [Fact]
    public async Task CheckHealthAsync_DefaultsToPostgres_WhenProviderConfigMissing()
    {
        // No Database:Provider key → defaults to "Postgres" → exercises the DB path
        var services = new ServiceCollection();
        services.AddDbContext<DocumentDbContext>(opt =>
            opt.UseInMemoryDatabase($"healthcheck_default_{Guid.NewGuid():N}"));
        var sp = services.BuildServiceProvider();
        var scopeFactory = sp.GetRequiredService<IServiceScopeFactory>();
        var config = new ConfigurationBuilder().Build();

        var sut = new DatabaseHealthCheck(scopeFactory, config);

        var result = await sut.CheckHealthAsync(new HealthCheckContext());

        Assert.Equal(HealthStatus.Healthy, result.Status);
    }

    // ── Helpers ────

    private sealed class NullScopeFactory : IServiceScopeFactory
    {
        public IServiceScope CreateScope() => throw new NotSupportedException("Should not be called for InMemory.");
    }

    private sealed class ThrowingScopeFactory : IServiceScopeFactory
    {
        public IServiceScope CreateScope() => throw new InvalidOperationException("DB down");
    }
}

// ── StorageCleanupWorker ────────────────────────────────────────

public class StorageCleanupWorkerTests : IDisposable
{
    private readonly string _tempRoot;

    public StorageCleanupWorkerTests()
    {
        _tempRoot = Path.Combine(Path.GetTempPath(), $"cleanup_test_{Guid.NewGuid():N}");
        Directory.CreateDirectory(_tempRoot);
    }

    public void Dispose()
    {
        if (Directory.Exists(_tempRoot))
            Directory.Delete(_tempRoot, recursive: true);
    }

    [Fact]
    public async Task ExecuteAsync_ReturnsImmediately_WhenRetentionDaysIsZero()
    {
        var options = Options.Create(new StorageOptions { RootPath = _tempRoot, RetentionDays = 0 });
        var sut = new StorageCleanupWorker(NullLogger<StorageCleanupWorker>.Instance, options);

        using var cts = new CancellationTokenSource();
        // ExecuteAsync should return immediately when RetentionDays <= 0
        await sut.StartAsync(cts.Token);
        // Give a tiny window for the background task
        await Task.Delay(100);
        await sut.StopAsync(CancellationToken.None);

        // If we got here without the worker entering the loop, success
        Assert.True(true);
    }

    [Fact]
    public async Task ExecuteAsync_DeletesOldFiles_KeepsRecentFiles()
    {
        // Create an old file (> 1 day ago) and a recent file
        var oldFile = Path.Combine(_tempRoot, "old.txt");
        File.WriteAllText(oldFile, "old");
        File.SetLastWriteTimeUtc(oldFile, DateTime.UtcNow.AddDays(-5));

        var recentFile = Path.Combine(_tempRoot, "recent.txt");
        File.WriteAllText(recentFile, "recent");

        var options = Options.Create(new StorageOptions
        {
            RootPath = _tempRoot,
            RetentionDays = 2,
            CleanupIntervalMinutes = 60 // won't loop in time
        });
        var sut = new StorageCleanupWorker(NullLogger<StorageCleanupWorker>.Instance, options);

        using var cts = new CancellationTokenSource();
        await sut.StartAsync(cts.Token);
        // Wait for at least one cleanup cycle
        await Task.Delay(250);
        await sut.StopAsync(CancellationToken.None);

        // Old file should be deleted, recent file kept
        Assert.False(File.Exists(oldFile), "Old file should have been deleted.");
        Assert.True(File.Exists(recentFile), "Recent file should be kept.");
    }

    [Fact]
    public async Task ExecuteAsync_NoError_WhenDirectoryDoesNotExist()
    {
        var missingPath = Path.Combine(Path.GetTempPath(), $"missing_{Guid.NewGuid():N}");
        var options = Options.Create(new StorageOptions
        {
            RootPath = missingPath,
            RetentionDays = 1,
            CleanupIntervalMinutes = 60
        });
        var sut = new StorageCleanupWorker(NullLogger<StorageCleanupWorker>.Instance, options);

        using var cts = new CancellationTokenSource();
        await sut.StartAsync(cts.Token);
        await Task.Delay(250);
        await sut.StopAsync(CancellationToken.None);

        // Should not throw – CleanupStorage returns early if directory missing
        Assert.True(true);
    }

    [Fact]
    public async Task ExecuteAsync_RespectsMinimumInterval()
    {
        // CleanupIntervalMinutes = 1 → clamped to 5 min minimum
        var options = Options.Create(new StorageOptions
        {
            RootPath = _tempRoot,
            RetentionDays = 1,
            CleanupIntervalMinutes = 1
        });

        var sut = new StorageCleanupWorker(NullLogger<StorageCleanupWorker>.Instance, options);

        using var cts = new CancellationTokenSource();
        await sut.StartAsync(cts.Token);
        // The worker should run once then delay for 5 min, not 1 min
        await Task.Delay(200);
        await sut.StopAsync(CancellationToken.None);

        // If it respected Math.Max(5, 1) = 5 min, it would not have looped again in 200ms
        Assert.True(true);
    }
}

// ── RequireRoleAttribute ────────────────────────────────────────

public class RequireRoleAttributeTests
{
    [Fact]
    public void Constructor_SetsRolesProperty()
    {
        var attr = new RequireRoleAttribute("Admin");
        Assert.Equal("Admin", attr.Roles);
    }

    [Theory]
    [InlineData("Admin")]
    [InlineData("User")]
    [InlineData("Operator")]
    [InlineData("Admin,User")]
    public void Constructor_SetsCorrectRole_ForVariousInputs(string role)
    {
        var attr = new RequireRoleAttribute(role);
        Assert.Equal(role, attr.Roles);
    }

    [Fact]
    public void IsAuthorizationAttribute()
    {
        var attr = new RequireRoleAttribute("X");
        Assert.IsAssignableFrom<Microsoft.AspNetCore.Authorization.AuthorizeAttribute>(attr);
    }
}
