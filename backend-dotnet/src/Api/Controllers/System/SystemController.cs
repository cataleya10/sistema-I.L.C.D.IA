using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Options;
using Shared.Options;
using Api.Authorization;

namespace Api.Controllers.System;

[ApiController]
[Route("api/system")]
public class SystemController : ControllerBase
{
    private readonly SystemInfoOptions _options;
    private readonly Api.Services.MetricsService _metrics;

    public SystemController(IOptions<SystemInfoOptions> options, Api.Services.MetricsService metrics)
    {
        _options = options.Value;
        _metrics = metrics;
    }

    [HttpGet("info")]
    [AllowAnonymous]
    public IActionResult Info()
    {
        return Ok(new
        {
            service_name = _options.ServiceName,
            pipeline_version = _options.PipelineVersion,
            model_version = _options.ModelVersion,
            timestamp = DateTime.UtcNow
        });
    }

    [HttpGet("metrics")]
    [RequireRole("Admin,User")]
    public IActionResult Metrics()
    {
        var snapshot = _metrics.Snapshot();
        return Ok(new
        {
            requests = snapshot.Requests,
            errors = snapshot.Errors,
            client_errors = snapshot.ClientErrors,
            avg_duration_ms = snapshot.AvgDurationMs,
            max_duration_ms = snapshot.MaxDurationMs,
            started_at_utc = snapshot.StartedAtUtc,
            uptime_seconds = (long)(DateTime.UtcNow - snapshot.StartedAtUtc).TotalSeconds,
            timestamp = DateTime.UtcNow
        });
    }
}
