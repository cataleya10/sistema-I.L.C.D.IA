using Microsoft.Extensions.Diagnostics.HealthChecks;

namespace Api.HealthChecks;

/// <summary>
/// Verifies the Python AI engine is reachable by hitting its /health endpoint.
/// </summary>
public sealed class AiEngineHealthCheck : IHealthCheck
{
    private readonly IHttpClientFactory _httpClientFactory;
    private readonly IConfiguration _configuration;

    public AiEngineHealthCheck(IHttpClientFactory httpClientFactory, IConfiguration configuration)
    {
        _httpClientFactory = httpClientFactory;
        _configuration = configuration;
    }

    public async Task<HealthCheckResult> CheckHealthAsync(
        HealthCheckContext context, CancellationToken cancellationToken = default)
    {
        var baseUrl = _configuration["PythonAi:BaseUrl"] ?? "http://localhost:8000";
        try
        {
            var client = _httpClientFactory.CreateClient();
            client.Timeout = TimeSpan.FromSeconds(5);
            var response = await client.GetAsync($"{baseUrl.TrimEnd('/')}/health", cancellationToken);
            if (response.IsSuccessStatusCode)
            {
                return HealthCheckResult.Healthy($"AI Engine at {baseUrl} is healthy.");
            }
            return HealthCheckResult.Degraded($"AI Engine returned {(int)response.StatusCode}.");
        }
        catch (Exception ex)
        {
            return HealthCheckResult.Unhealthy($"AI Engine at {baseUrl} is unreachable.", ex);
        }
    }
}
