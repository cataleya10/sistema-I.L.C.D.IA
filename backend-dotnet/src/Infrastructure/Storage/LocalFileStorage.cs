using Application.Storage;
using Microsoft.Extensions.Options;
using Shared.Options;

namespace Infrastructure.Storage;

public class LocalFileStorage : IFileStorage
{
    private readonly StorageOptions _options;

    public LocalFileStorage(IOptions<StorageOptions> options)
    {
        _options = options.Value;
        Directory.CreateDirectory(_options.RootPath);
    }

    public async Task<(string StoredFilename, string StoredPath)> SaveAsync(Stream content, string originalFilename, Guid documentId, CancellationToken cancellationToken)
    {
        var extension = Path.GetExtension(originalFilename);
        var storedFilename = $"{documentId}{extension}";
        var storedPath = Path.Combine(_options.RootPath, storedFilename);

        await using var fileStream = new FileStream(storedPath, FileMode.Create, FileAccess.Write, FileShare.None);
        await content.CopyToAsync(fileStream, cancellationToken);

        return (storedFilename, storedPath);
    }

    public Task<Stream?> OpenReadAsync(string storedPath, CancellationToken cancellationToken)
    {
        if (!File.Exists(storedPath))
        {
            return Task.FromResult<Stream?>(null);
        }

        Stream stream = new FileStream(storedPath, FileMode.Open, FileAccess.Read, FileShare.Read);
        return Task.FromResult<Stream?>(stream);
    }

    public bool Exists(string storedPath) => File.Exists(storedPath);
}
