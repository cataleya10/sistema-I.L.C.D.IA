using Domain.Enums;

namespace Application.DTOs;

public sealed record DocumentProcessRequest(Guid DocumentId, string Source, string? Options);

public sealed record DocumentProcessResponse(
    Guid DocumentId,
    DocumentStatus Status,
    DocumentType DocumentType,
    decimal Confidence,
    IReadOnlyList<DocumentFieldResultDto> Fields,
    IReadOnlyList<ExtractedTableDto> Tables,
    IReadOnlyList<string> Warnings,
    IReadOnlyList<string> Errors,
    DocumentProcessMeta Meta
);

/// <summary>
/// Tabla canónica extraída del documento por el motor Python.
/// Rows: lista de filas como diccionario columna→valor (strings).
/// </summary>
public sealed record ExtractedTableDto(
    IReadOnlyList<string> Columns,
    IReadOnlyList<IReadOnlyDictionary<string, string?>> Rows,
    float Quality,
    int RowCount,
    string? DocTypeHint
);

public sealed record DocumentFieldResultDto(
    string Key,
    string Label,
    string? Value,
    decimal Confidence,
    bool Valid,
    IReadOnlyList<string> ValidationErrors,
    FieldSourceDto? Source
);

public sealed record DocumentProcessMeta(
    int PagesProcessed,
    string OcrEngine,
    string PipelineVersion,
    string ModelVersion,
    long ProcessingMs
);
