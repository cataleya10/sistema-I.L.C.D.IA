namespace Shared.Options;

public sealed class SystemInfoOptions
{
    public const string SectionName = "SystemInfo";

    public string ServiceName { get; set; } = "ILCDIA API";
    public string PipelineVersion { get; set; } = "1.0.0";
    public string ModelVersion { get; set; } = "clf-v1.0.0";
}
