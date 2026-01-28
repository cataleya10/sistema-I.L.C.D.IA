using Application.DTOs;

namespace Application.Interfaces;

public interface IPythonAiClient
{
    Task<DocumentProcessResponse> ProcessDocumentAsync(Guid documentId, string filePath, CancellationToken cancellationToken);
}
