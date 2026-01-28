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
        _metrics.IncrementRequest();
        await _next(context);
        stopwatch.Stop();

        var correlationId = context.Response.Headers["X-Correlation-Id"].ToString();
        _logger.LogInformation(
            "{Method} {Path} responded {StatusCode} in {Elapsed}ms CorrelationId={CorrelationId}",
            context.Request.Method,
            context.Request.Path,
            context.Response.StatusCode,
            stopwatch.ElapsedMilliseconds,
            correlationId
        );

        if (context.Response.StatusCode >= 500)
        {
            _metrics.IncrementError();
        }
    }
}
