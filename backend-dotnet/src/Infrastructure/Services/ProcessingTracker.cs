using System.Collections.Concurrent;
using Application.DTOs;
using Application.Interfaces;

namespace Infrastructure.Services;

public sealed class ProcessingTracker : IProcessingTracker
{
    private readonly ConcurrentDictionary<Guid, TaskCompletionSource<DocumentProcessResponse>> _inFlight = new();

    public (Task<DocumentProcessResponse> Task, bool Created) Register(Guid documentId)
    {
        var tcs = new TaskCompletionSource<DocumentProcessResponse>(TaskCreationOptions.RunContinuationsAsynchronously);
        var existing = _inFlight.GetOrAdd(documentId, tcs);
        var created = ReferenceEquals(existing, tcs);
        return (existing.Task, created);
    }

    public void Complete(Guid documentId, DocumentProcessResponse response)
    {
        if (_inFlight.TryRemove(documentId, out var tcs))
        {
            tcs.TrySetResult(response);
        }
    }

    public void Fail(Guid documentId, Exception exception)
    {
        if (_inFlight.TryRemove(documentId, out var tcs))
        {
            tcs.TrySetException(exception);
        }
    }

    public void Cancel(Guid documentId)
    {
        if (_inFlight.TryRemove(documentId, out var tcs))
        {
            tcs.TrySetCanceled();
        }
    }
}
