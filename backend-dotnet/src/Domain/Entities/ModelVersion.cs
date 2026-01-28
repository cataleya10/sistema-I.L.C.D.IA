using System.Text.Json;

namespace Domain.Entities;

public class ModelVersion
{
    public Guid Id { get; set; }
    public string ModelType { get; set; } = string.Empty;
    public string Version { get; set; } = string.Empty;
    public DateTime TrainedAt { get; set; }
    public JsonDocument? Metrics { get; set; }
    public string? Notes { get; set; }
}
