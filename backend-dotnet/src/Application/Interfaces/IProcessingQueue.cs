namespace Application.Interfaces;

public interface IProcessingQueue
{
    ValueTask EnqueueAsync(DocumentProcessJob job, CancellationToken cancellationToken = default);
    ValueTask<DocumentProcessJob> DequeueAsync(CancellationToken cancellationToken);
}

public sealed record DocumentProcessJob(Guid DocumentId);
