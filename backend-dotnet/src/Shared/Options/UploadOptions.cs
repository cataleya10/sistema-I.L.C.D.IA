namespace Shared.Options;

public sealed class UploadOptions
{
    public const string SectionName = "Upload";

    public long MaxFileSizeBytes { get; set; } = 15 * 1024 * 1024;
    public string[] AllowedContentTypes { get; set; } = [
        "application/pdf",
        "image/png",
        "image/jpeg"
    ];
}
