using Application.Interfaces;
using Microsoft.Extensions.Options;
using Shared.Options;

namespace Api.Services;

public sealed class DocumentProcessingWorker : BackgroundService
{
    private readonly ILogger<DocumentProcessingWorker> _logger;
    private readonly IServiceScopeFactory _scopeFactory;
    private readonly IProcessingQueue _queue;
    private readonly IProcessingTracker _tracker;
    private readonly ProcessingOptions _options;

    public DocumentProcessingWorker(
        ILogger<DocumentProcessingWorker> logger,
        IServiceScopeFactory scopeFactory,
        IProcessingQueue queue,
        IProcessingTracker tracker,
        IOptions<ProcessingOptions> options)
    {
        _logger = logger;
        _scopeFactory = scopeFactory;
        _queue = queue;
        _tracker = tracker;
        _options = options.Value;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            DocumentProcessJob job;
            try
            {
                job = await _queue.DequeueAsync(stoppingToken);
            }
            catch (OperationCanceledException)
            {
                break;
            }

            await ProcessWithRetriesAsync(job, stoppingToken);
        }
    }

    private async Task ProcessWithRetriesAsync(DocumentProcessJob job, CancellationToken stoppingToken)
    {
        var attempt = 0;
        while (attempt < Math.Max(1, _options.MaxAttempts))
        {
            attempt++;
            try
            {
                using var scope = _scopeFactory.CreateScope();
                var service = scope.ServiceProvider.GetRequiredService<IDocumentService>();
                var response = await service.ProcessNowAsync(job.DocumentId, stoppingToken);
                _tracker.Complete(job.DocumentId, response);
                return;
            }
            catch (Exception ex) when (!stoppingToken.IsCancellationRequested)
            {
                _logger.LogWarning(ex, "Error processing document {DocumentId} attempt {Attempt}", job.DocumentId, attempt);
                if (attempt >= _options.MaxAttempts)
                {
                    _logger.LogError(ex, "Document {DocumentId} failed after {Attempts} attempts", job.DocumentId, attempt);
                    try
                    {
                        using var failureScope = _scopeFactory.CreateScope();
                        var failureService = failureScope.ServiceProvider.GetRequiredService<IDocumentService>();
                        await failureService.MarkFailedAsync(job.DocumentId, ex.Message, stoppingToken);
                    }
                    catch (Exception markEx)
                    {
                        _logger.LogError(markEx, "Unable to mark document {DocumentId} as failed", job.DocumentId);
                    }
                    _tracker.Fail(job.DocumentId, ex);
                    return;
                }

                var delay = TimeSpan.FromSeconds(Math.Max(1, _options.RetryDelaySeconds));
                try
                {
                    await Task.Delay(delay, stoppingToken);
                }
                catch (OperationCanceledException)
                {
                    return;
                }
            }
        }
    }
}
