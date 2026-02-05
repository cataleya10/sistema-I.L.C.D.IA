namespace Api.Services;

public class MetricsService
{
    private long _requests;
    private long _errors;
    private long _clientErrors;
    private long _totalDurationMs;
    private long _maxDurationMs;
    private readonly DateTime _startedAt = DateTime.UtcNow;

    public void Observe(long durationMs, int statusCode)
    {
        Interlocked.Increment(ref _requests);
        Interlocked.Add(ref _totalDurationMs, durationMs);

        while (true)
        {
            var current = Interlocked.Read(ref _maxDurationMs);
            if (durationMs <= current)
            {
                break;
            }
            if (Interlocked.CompareExchange(ref _maxDurationMs, durationMs, current) == current)
            {
                break;
            }
        }

        if (statusCode >= 500)
        {
            Interlocked.Increment(ref _errors);
        }
        else if (statusCode >= 400)
        {
            Interlocked.Increment(ref _clientErrors);
        }
    }

    public MetricsSnapshot Snapshot()
    {
        var requests = Interlocked.Read(ref _requests);
        var totalMs = Interlocked.Read(ref _totalDurationMs);
        var avgMs = requests > 0 ? (double)totalMs / requests : 0d;
        return new MetricsSnapshot(
            requests,
            Interlocked.Read(ref _errors),
            Interlocked.Read(ref _clientErrors),
            avgMs,
            Interlocked.Read(ref _maxDurationMs),
            _startedAt
        );
    }
}

public sealed record MetricsSnapshot(
    long Requests,
    long Errors,
    long ClientErrors,
    double AvgDurationMs,
    long MaxDurationMs,
    DateTime StartedAtUtc);
