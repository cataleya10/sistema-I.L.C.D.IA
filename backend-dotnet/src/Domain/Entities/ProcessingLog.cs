namespace Domain.Entities;

public class ProcessingLog
{
    public Guid Id { get; set; }
    public Guid DocumentId { get; set; }
    public string Stage { get; set; } = string.Empty;
    public string Level { get; set; } = string.Empty;
    public string Message { get; set; } = string.Empty;
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    public Document? Document { get; set; }
}
