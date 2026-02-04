using Microsoft.Extensions.Options;
using Shared.Options;

namespace Api.Services;

public sealed class RefreshTokenCleanupWorker : BackgroundService
{
    private readonly ILogger<RefreshTokenCleanupWorker> _logger;
    private readonly RefreshTokenOptions _options;
    private readonly RefreshTokenStore _store;

    public RefreshTokenCleanupWorker(
        ILogger<RefreshTokenCleanupWorker> logger,
        IOptions<RefreshTokenOptions> options,
        RefreshTokenStore store)
    {
        _logger = logger;
        _options = options.Value;
        _store = store;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var interval = TimeSpan.FromMinutes(Math.Max(5, _options.CleanupIntervalMinutes));
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                _store.RevokeExpired();
            }
            catch (Exception ex) when (!stoppingToken.IsCancellationRequested)
            {
                _logger.LogWarning(ex, "Refresh token cleanup failed.");
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
}

