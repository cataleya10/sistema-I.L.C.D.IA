namespace Shared.Options;

public sealed class RefreshTokenOptions
{
    public const string SectionName = "RefreshTokens";

    public string StoragePath { get; set; } = "storage/refresh_tokens.json";
    public int CleanupIntervalMinutes { get; set; } = 30;
}

