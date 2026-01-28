namespace Api.Services;

public class MetricsService
{
    private long _requests;
    private long _errors;

    public void IncrementRequest() => Interlocked.Increment(ref _requests);
    public void IncrementError() => Interlocked.Increment(ref _errors);

    public (long Requests, long Errors) Snapshot() => (Interlocked.Read(ref _requests), Interlocked.Read(ref _errors));
}
