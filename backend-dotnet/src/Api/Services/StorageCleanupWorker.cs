using Microsoft.Extensions.Options;
using Shared.Options;

namespace Api.Services;

public sealed class StorageCleanupWorker : BackgroundService
{
    private readonly ILogger<StorageCleanupWorker> _logger;
    private readonly StorageOptions _options;

    public StorageCleanupWorker(ILogger<StorageCleanupWorker> logger, IOptions<StorageOptions> options)
    {
        _logger = logger;
        _options = options.Value;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        if (_options.RetentionDays <= 0)
        {
            _logger.LogInformation("Storage cleanup disabled (RetentionDays <= 0).");
            return;
        }

        var interval = TimeSpan.FromMinutes(Math.Max(5, _options.CleanupIntervalMinutes));
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                CleanupStorage();
            }
            catch (Exception ex) when (!stoppingToken.IsCancellationRequested)
            {
                _logger.LogWarning(ex, "Storage cleanup failed.");
            }

            try
            {
                await Task.Delay(interval, stoppingToken);
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }
    }

    private void CleanupStorage()
    {
        if (!Directory.Exists(_options.RootPath))
        {
            return;
        }

        var cutoff = DateTime.UtcNow.AddDays(-_options.RetentionDays);
        var files = Directory.EnumerateFiles(_options.RootPath, "*", SearchOption.AllDirectories);
        var deleted = 0;
        foreach (var file in files)
        {
            var info = new FileInfo(file);
            if (info.LastWriteTimeUtc < cutoff)
            {
                try
                {
                    info.Delete();
                    deleted++;
                }
                catch (Exception ex)
                {
                    _logger.LogDebug(ex, "Failed to delete {File}", file);
                }
            }
        }

        if (deleted > 0)
        {
            _logger.LogInformation("Storage cleanup deleted {Count} files older than {Days} days.", deleted, _options.RetentionDays);
        }
    }
}

