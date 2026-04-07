namespace Domain.Entities;

public class DocumentTable
{
    public Guid Id { get; set; }
    public Guid DocumentId { get; set; }
    public int TableIndex { get; set; }
    public string[] Columns { get; set; } = Array.Empty<string>();
    /// <summary>JSON array of row objects (canonical key→value string pairs).</summary>
    public string RowsJson { get; set; } = "[]";
    public float Quality { get; set; }
    public int RowCount { get; set; }
    public string? DocTypeHint { get; set; }
    public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

    public Document? Document { get; set; }
}
