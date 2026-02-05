using Application.DTOs;

namespace Application.Interfaces;

public interface IDocumentService
{
    Task<DocumentSummaryDto> UploadAsync(DocumentUpload upload, CancellationToken cancellationToken);
    Task<IReadOnlyList<DocumentSummaryDto>> ListAsync(DocumentListQuery query, CancellationToken cancellationToken);
    Task<DocumentDetailDto?> GetByIdAsync(Guid id, CancellationToken cancellationToken);
    Task<Stream?> GetFileStreamAsync(Guid id, CancellationToken cancellationToken);
    Task<DocumentProcessResponse> ProcessAsync(Guid id, CancellationToken cancellationToken);
    Task<DocumentProcessResponse> ProcessNowAsync(Guid id, CancellationToken cancellationToken);
    Task UpdateFieldsAsync(Guid id, DocumentFieldsUpdateRequest request, CancellationToken cancellationToken);
    Task MarkFailedAsync(Guid id, string reason, CancellationToken cancellationToken);
    Task DeleteAsync(Guid id, CancellationToken cancellationToken);
    Task<IReadOnlyList<ProcessingLogDto>> GetLogsAsync(Guid id, CancellationToken cancellationToken);
}

public sealed record DocumentUpload(
    Stream Content,
    string FileName,
    string ContentType,
    long Length,
    string? UploadedBy
);

public sealed record DocumentListQuery(
    string? Status,
    string? Type,
    string? Q,
    DateTime? From,
    DateTime? To,
    int Page = 1,
    int PageSize = 20
);
