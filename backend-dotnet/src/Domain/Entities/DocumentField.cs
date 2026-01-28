namespace Domain.Entities;

public class DocumentField
{
    public Guid Id { get; set; }
    public Guid DocumentId { get; set; }
    public string FieldKey { get; set; } = string.Empty;
    public string FieldLabel { get; set; } = string.Empty;
    public string? FieldValue { get; set; }
    public decimal Confidence { get; set; }
    public bool IsValid { get; set; }
    public string[] ValidationErrors { get; set; } = Array.Empty<string>();
    public int? SourcePage { get; set; }
    public int[]? SourceBbox { get; set; }
    public bool Corrected { get; set; }
    public string? CorrectedValue { get; set; }
    public string? CorrectedBy { get; set; }
    public DateTime? CorrectedAt { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    public Document? Document { get; set; }
}
