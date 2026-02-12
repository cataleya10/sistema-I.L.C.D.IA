using Application.DTOs;
using Application.Interfaces;
using Application.Storage;
using Domain.Entities;
using Domain.Enums;
using Infrastructure.Persistence;
using Infrastructure.Services;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;
using Xunit;

namespace Infrastructure.Tests;

public class DocumentServiceTests
{
    [Fact]
    public async Task UploadAsync_PersistsDocument()
    {
        using var db = CreateDbContext();
        var fileStorage = new FakeFileStorage();
        var service = CreateService(db, fileStorage: fileStorage);

        await using var content = new MemoryStream(new byte[] { 1, 2, 3, 4 });
        var upload = new DocumentUpload(content, "ine.pdf", "application/pdf", content.Length, "admin");

        var result = await service.UploadAsync(upload, CancellationToken.None);

        var persisted = await db.Documents.SingleAsync(x => x.Id == result.Id);
        Assert.Equal(DocumentStatus.Uploaded, persisted.Status);
        Assert.Equal("ine.pdf", persisted.OriginalFilename);
        Assert.Equal("admin", persisted.UploadedBy);
        Assert.Equal("stored-ine.pdf", persisted.StoredFilename);
        Assert.Equal("/fake/stored-ine.pdf", persisted.FilePath);
    }

    [Fact]
    public async Task ProcessAsync_QueuesJobAndSetsProcessingStatus()
    {
        using var db = CreateDbContext();
        var queue = new FakeProcessingQueue();
        var service = CreateService(db, queue: queue);

        var documentId = Guid.NewGuid();
        db.Documents.Add(new Document
        {
            Id = documentId,
            OriginalFilename = "curp.pdf",
            StoredFilename = "stored-curp.pdf",
            FilePath = "/fake/stored-curp.pdf",
            MimeType = "application/pdf",
            FileSize = 128,
            Status = DocumentStatus.Uploaded
        });
        await db.SaveChangesAsync();

        var result = await service.ProcessAsync(documentId, CancellationToken.None);
        var persisted = await db.Documents.SingleAsync(x => x.Id == documentId);

        Assert.Equal(DocumentStatus.Processing, result.Status);
        Assert.Equal(DocumentStatus.Processing, persisted.Status);
        Assert.Single(queue.EnqueuedJobs);
        Assert.Equal(documentId, queue.EnqueuedJobs[0].DocumentId);
    }

    [Fact]
    public async Task ProcessNowAsync_WhenReadyResponse_PersistsFieldsAndMarksReady()
    {
        using var db = CreateDbContext();
        var pythonClient = new FakePythonAiClient((documentId, _, _) =>
            Task.FromResult(new DocumentProcessResponse(
                documentId,
                DocumentStatus.Ready,
                DocumentType.Ine,
                0.94m,
                new[]
                {
                    new DocumentFieldResultDto(
                        "curp",
                        "CURP",
                        "ABCD010101HDFRRS09",
                        0.96m,
                        true,
                        Array.Empty<string>(),
                        new FieldSourceDto(1, new[] { 10, 20, 30, 40 }))
                },
                Array.Empty<string>(),
                Array.Empty<string>(),
                new DocumentProcessMeta(1, "paddleocr", "1.0.0", "clf-v1.0.0", 1500))));
        var service = CreateService(db, pythonClient: pythonClient);

        var documentId = Guid.NewGuid();
        db.Documents.Add(new Document
        {
            Id = documentId,
            OriginalFilename = "ine.pdf",
            StoredFilename = "stored-ine.pdf",
            FilePath = "/fake/stored-ine.pdf",
            MimeType = "application/pdf",
            FileSize = 512,
            Status = DocumentStatus.Uploaded
        });
        await db.SaveChangesAsync();

        var response = await service.ProcessNowAsync(documentId, CancellationToken.None);
        var persisted = await db.Documents.Include(x => x.Fields).SingleAsync(x => x.Id == documentId);

        Assert.Equal(DocumentStatus.Ready, response.Status);
        Assert.Equal(DocumentStatus.Ready, persisted.Status);
        Assert.False(persisted.NeedsReview);
        Assert.Equal(DocumentType.Ine, persisted.DocumentType);
        Assert.Single(persisted.Fields);
        Assert.Equal("curp", persisted.Fields.First().FieldKey);
        Assert.Equal("ABCD010101HDFRRS09", persisted.Fields.First().FieldValue);
    }

    [Fact]
    public async Task UpdateFieldsAsync_MarksFieldAsCorrectedAndReady()
    {
        using var db = CreateDbContext();
        var service = CreateService(db);

        var documentId = Guid.NewGuid();
        db.Documents.Add(new Document
        {
            Id = documentId,
            OriginalFilename = "doc.pdf",
            StoredFilename = "stored-doc.pdf",
            FilePath = "/fake/stored-doc.pdf",
            MimeType = "application/pdf",
            FileSize = 256,
            Status = DocumentStatus.NeedsReview,
            NeedsReview = true,
            Fields =
            {
                new DocumentField
                {
                    Id = Guid.NewGuid(),
                    DocumentId = documentId,
                    FieldKey = "nombre",
                    FieldLabel = "Nombre",
                    FieldValue = "VALOR OCR",
                    Confidence = 0.70m,
                    IsValid = true
                }
            }
        });
        await db.SaveChangesAsync();

        var request = new DocumentFieldsUpdateRequest(
            new[] { new DocumentFieldUpdateDto("nombre", "VALOR CORREGIDO") },
            "reviewer");
        await service.UpdateFieldsAsync(documentId, request, CancellationToken.None);

        var persisted = await db.Documents.Include(x => x.Fields).SingleAsync(x => x.Id == documentId);
        var field = Assert.Single(persisted.Fields);
        Assert.True(field.Corrected);
        Assert.Equal("VALOR CORREGIDO", field.CorrectedValue);
        Assert.Equal("reviewer", field.CorrectedBy);
        Assert.Equal(DocumentStatus.Ready, persisted.Status);
        Assert.False(persisted.NeedsReview);
    }

    private static DocumentDbContext CreateDbContext()
    {
        var options = new DbContextOptionsBuilder<DocumentDbContext>()
            .UseInMemoryDatabase(Guid.NewGuid().ToString("N"))
            .Options;
        return new DocumentDbContext(options);
    }

    private static DocumentService CreateService(
        DocumentDbContext dbContext,
        IPythonAiClient? pythonClient = null,
        IFileStorage? fileStorage = null,
        IProcessingQueue? queue = null,
        IProcessingTracker? tracker = null)
    {
        return new DocumentService(
            dbContext,
            pythonClient ?? new FakePythonAiClient((_, _, _) => throw new NotImplementedException()),
            fileStorage ?? new FakeFileStorage(),
            queue ?? new FakeProcessingQueue(),
            tracker ?? new FakeProcessingTracker(),
            NullLogger<DocumentService>.Instance);
    }

    private sealed class FakePythonAiClient : IPythonAiClient
    {
        private readonly Func<Guid, string, CancellationToken, Task<DocumentProcessResponse>> _handler;

        public FakePythonAiClient(Func<Guid, string, CancellationToken, Task<DocumentProcessResponse>> handler)
        {
            _handler = handler;
        }

        public Task<DocumentProcessResponse> ProcessDocumentAsync(Guid documentId, string filePath, CancellationToken cancellationToken)
            => _handler(documentId, filePath, cancellationToken);
    }

    private sealed class FakeProcessingQueue : IProcessingQueue
    {
        public List<DocumentProcessJob> EnqueuedJobs { get; } = new();

        public ValueTask EnqueueAsync(DocumentProcessJob job, CancellationToken cancellationToken = default)
        {
            EnqueuedJobs.Add(job);
            return ValueTask.CompletedTask;
        }

        public ValueTask<DocumentProcessJob> DequeueAsync(CancellationToken cancellationToken)
            => throw new NotImplementedException();
    }

    private sealed class FakeProcessingTracker : IProcessingTracker
    {
        private readonly Dictionary<Guid, TaskCompletionSource<DocumentProcessResponse>> _map = new();

        public (Task<DocumentProcessResponse> Task, bool Created) Register(Guid documentId)
        {
            if (_map.TryGetValue(documentId, out var existing))
            {
                return (existing.Task, false);
            }

            var tcs = new TaskCompletionSource<DocumentProcessResponse>(TaskCreationOptions.RunContinuationsAsynchronously);
            _map[documentId] = tcs;
            return (tcs.Task, true);
        }

        public bool TryGet(Guid documentId, out Task<DocumentProcessResponse> task)
        {
            if (_map.TryGetValue(documentId, out var tcs))
            {
                task = tcs.Task;
                return true;
            }

            task = Task.FromException<DocumentProcessResponse>(new KeyNotFoundException(documentId.ToString()));
            return false;
        }

        public void Complete(Guid documentId, DocumentProcessResponse response)
        {
            if (_map.TryGetValue(documentId, out var tcs))
            {
                tcs.TrySetResult(response);
            }
        }

        public void Fail(Guid documentId, Exception exception)
        {
            if (_map.TryGetValue(documentId, out var tcs))
            {
                tcs.TrySetException(exception);
            }
        }

        public void Cancel(Guid documentId)
        {
            if (_map.TryGetValue(documentId, out var tcs))
            {
                tcs.TrySetCanceled();
            }
        }
    }

    private sealed class FakeFileStorage : IFileStorage
    {
        private readonly Dictionary<string, byte[]> _files = new();

        public async Task<(string StoredFilename, string StoredPath)> SaveAsync(
            Stream content,
            string originalFilename,
            Guid documentId,
            CancellationToken cancellationToken)
        {
            await using var ms = new MemoryStream();
            await content.CopyToAsync(ms, cancellationToken);
            var storedFilename = $"stored-{originalFilename}";
            var storedPath = $"/fake/{storedFilename}";
            _files[storedPath] = ms.ToArray();
            return (storedFilename, storedPath);
        }

        public Task<Stream?> OpenReadAsync(string storedPath, CancellationToken cancellationToken)
        {
            if (!_files.TryGetValue(storedPath, out var data))
            {
                return Task.FromResult<Stream?>(null);
            }

            return Task.FromResult<Stream?>(new MemoryStream(data, writable: false));
        }

        public bool Exists(string storedPath) => _files.ContainsKey(storedPath);

        public Task DeleteAsync(string storedPath, CancellationToken cancellationToken)
        {
            _files.Remove(storedPath);
            return Task.CompletedTask;
        }
    }
}
