using Domain.Enums;

namespace Domain.Entities;

public class Document
{
    public Guid Id { get; set; }
    public string OriginalFilename { get; set; } = string.Empty;
    public string StoredFilename { get; set; } = string.Empty;
    public string FilePath { get; set; } = string.Empty;
    public string MimeType { get; set; } = string.Empty;
    public long FileSize { get; set; }
    public DocumentStatus Status { get; set; } = DocumentStatus.Uploaded;
    public DocumentType DocumentType { get; set; } = DocumentType.Unknown;
    public decimal? Confidence { get; set; }
    public string? UploadedBy { get; set; }
    public DateTime UploadedAt { get; set; } = DateTime.UtcNow;
    public DateTime? ProcessedAt { get; set; }
    public string? ModelVersion { get; set; }
    public string? PipelineVersion { get; set; }
    public bool NeedsReview { get; set; }
    public string? ErrorMessage { get; set; }

    public ICollection<DocumentField> Fields { get; set; } = new List<DocumentField>();
    public ICollection<ProcessingLog> ProcessingLogs { get; set; } = new List<ProcessingLog>();
    public ICollection<DocumentTable> Tables { get; set; } = new List<DocumentTable>();
}
