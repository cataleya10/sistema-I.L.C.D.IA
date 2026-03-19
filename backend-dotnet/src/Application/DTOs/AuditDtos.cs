namespace Application.DTOs;

public sealed record AuditFolderRequestDto(
    string FolderPath,
    bool Recurse = true,
    int Limit = 100,
    bool IssuesOnly = false
);

public sealed record AuditDocumentSummaryDto(
    string Name,
    string FilePath,
    string Status,
    string? DocumentType,
    decimal? Confidence,
    int TablaRows,
    int DetalleRows,
    int WarningCount,
    IReadOnlyList<string> Warnings,
    bool HardFail,
    IReadOnlyDictionary<string, string> MappedFields,
    string? Error
);

public sealed record AuditFolderResponseDto(
    string FolderPath,
    bool Recurse,
    int Limit,
    bool IssuesOnly,
    int MatchedFiles,
    int ProcessedFiles,
    int DocumentsReturned,
    int CleanCount,
    int IssueCount,
    int ErrorCount,
    int HardFailCount,
    int NonFacturaCount,
    IReadOnlyDictionary<string, int> DocumentTypeCounts,
    IReadOnlyList<AuditDocumentSummaryDto> Documents
);
