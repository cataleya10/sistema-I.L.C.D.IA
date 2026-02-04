namespace Shared.Options;

public sealed class StorageOptions
{
    public const string SectionName = "Storage";

    public string RootPath { get; set; } = "storage";
    public int RetentionDays { get; set; } = 0;
    public int CleanupIntervalMinutes { get; set; } = 60;
}
