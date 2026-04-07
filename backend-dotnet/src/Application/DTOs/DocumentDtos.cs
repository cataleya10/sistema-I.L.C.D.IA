using Domain.Enums;

namespace Application.DTOs;

public sealed record DocumentSummaryDto(
    Guid Id,
    string OriginalFilename,
    DocumentStatus Status,
    DocumentType DocumentType,
    decimal? Confidence,
    DateTime UploadedAt,
    DateTime? ProcessedAt
);

public sealed record DocumentDetailDto(
    Guid Id,
    string OriginalFilename,
    DocumentStatus Status,
    DocumentType DocumentType,
    decimal? Confidence,
    DateTime UploadedAt,
    DateTime? ProcessedAt,
    string FileUrl,
    string MimeType,
    bool NeedsReview,
    IReadOnlyList<DocumentFieldDto> Fields,
    IReadOnlyList<ExtractedTableDto> Tables
);

public sealed record DocumentFieldDto(
    string Key,
    string Label,
    string? Value,
    decimal Confidence,
    bool Valid,
    IReadOnlyList<string> ValidationErrors,
    FieldSourceDto? Source,
    bool Corrected,
    string? CorrectedValue
);

public sealed record FieldSourceDto(int Page, IReadOnlyList<int> Bbox);

public sealed record ProcessingLogDto(
    Guid Id,
    Guid DocumentId,
    string Stage,
    string Level,
    string Message,
    DateTime CreatedAt
);
