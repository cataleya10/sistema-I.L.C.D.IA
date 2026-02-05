using Application.DTOs;

namespace Application.Interfaces;

public interface IProcessingQueue
{
    ValueTask EnqueueAsync(DocumentProcessJob job, CancellationToken cancellationToken = default);
    ValueTask<DocumentProcessJob> DequeueAsync(CancellationToken cancellationToken);
}

public interface IProcessingTracker
{
    (Task<DocumentProcessResponse> Task, bool Created) Register(Guid documentId);
    bool TryGet(Guid documentId, out Task<DocumentProcessResponse> task);
    void Complete(Guid documentId, DocumentProcessResponse response);
    void Fail(Guid documentId, Exception exception);
    void Cancel(Guid documentId);
}

public sealed record DocumentProcessJob(Guid DocumentId);
