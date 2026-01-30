namespace Shared.Options;

public sealed class RateLimitOptions
{
    public const string SectionName = "RateLimiting";

    public int WindowSeconds { get; set; } = 60;
    public int AdminPermitLimit { get; set; } = 200;
    public int UserPermitLimit { get; set; } = 60;
    public int AnonymousPermitLimit { get; set; } = 20;
    public int QueueLimit { get; set; } = 20;
}
