namespace Shared.Options;

public sealed class ProcessingOptions
{
    public const string SectionName = "Processing";

    public int MaxAttempts { get; set; } = 3;
    public int RetryDelaySeconds { get; set; } = 5;
}
