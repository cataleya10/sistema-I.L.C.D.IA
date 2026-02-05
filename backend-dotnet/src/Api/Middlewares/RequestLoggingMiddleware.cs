using System.Diagnostics;

namespace Api.Middlewares;

public class RequestLoggingMiddleware
{
    private readonly RequestDelegate _next;
    private readonly ILogger<RequestLoggingMiddleware> _logger;
    private readonly Services.MetricsService _metrics;

    public RequestLoggingMiddleware(RequestDelegate next, ILogger<RequestLoggingMiddleware> logger, Services.MetricsService metrics)
    {
        _next = next;
        _logger = logger;
        _metrics = metrics;
    }

    public async Task InvokeAsync(HttpContext context)
    {
        var stopwatch = Stopwatch.StartNew();
        context.Response.OnStarting(() =>
        {
            context.Response.Headers["X-Request-Duration-ms"] = stopwatch.ElapsedMilliseconds.ToString();
            return Task.CompletedTask;
        });
        await _next(context);
        stopwatch.Stop();
        _metrics.Observe(stopwatch.ElapsedMilliseconds, context.Response.StatusCode);

        var correlationId = context.Response.Headers["X-Correlation-Id"].ToString();
        var user = context.User?.Identity?.Name ?? "anonymous";
        _logger.LogInformation(
            "{Method} {Path} responded {StatusCode} in {Elapsed}ms User={User} CorrelationId={CorrelationId}",
            context.Request.Method,
            context.Request.Path,
            context.Response.StatusCode,
            stopwatch.ElapsedMilliseconds,
            user,
            correlationId
        );

    }
}
