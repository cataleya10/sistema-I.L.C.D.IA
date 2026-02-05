namespace Application.Storage;

public interface IFileStorage
{
    Task<(string StoredFilename, string StoredPath)> SaveAsync(Stream content, string originalFilename, Guid documentId, CancellationToken cancellationToken);
    Task<Stream?> OpenReadAsync(string storedPath, CancellationToken cancellationToken);
    bool Exists(string storedPath);
    Task DeleteAsync(string storedPath, CancellationToken cancellationToken);
}
