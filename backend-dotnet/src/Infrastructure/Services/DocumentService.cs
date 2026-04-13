using Application.DTOs;
using Application.Interfaces;
using Application.Storage;
using Domain.Entities;
using Domain.Enums;
using Infrastructure.Persistence;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Infrastructure.Services;

public class DocumentService : IDocumentService
{
    private static readonly Regex ActaCodeRegex = new("^[A-Z0-9-]{1,12}$", RegexOptions.Compiled | RegexOptions.IgnoreCase);
    private readonly DocumentDbContext _dbContext;
    private readonly IPythonAiClient _pythonClient;
    private readonly IFileStorage _fileStorage;
    private readonly IProcessingQueue _queue;
    private readonly IProcessingTracker _tracker;
    private readonly ILogger<DocumentService> _logger;

    public DocumentService(
        DocumentDbContext dbContext,
        IPythonAiClient pythonClient,
        IFileStorage fileStorage,
        IProcessingQueue queue,
        IProcessingTracker tracker,
        ILogger<DocumentService> logger)
    {
        _dbContext = dbContext;
        _pythonClient = pythonClient;
        _fileStorage = fileStorage;
        _queue = queue;
        _tracker = tracker;
        _logger = logger;
    }

    public async Task<DocumentSummaryDto> UploadAsync(DocumentUpload upload, CancellationToken cancellationToken)
    {
        var documentId = Guid.NewGuid();
        var (storedFilename, storedPath) = await _fileStorage.SaveAsync(upload.Content, upload.FileName, documentId, cancellationToken);

        var document = new Document
        {
            Id = documentId,
            OriginalFilename = upload.FileName,
            StoredFilename = storedFilename,
            FilePath = storedPath,
            MimeType = upload.ContentType,
            FileSize = upload.Length,
            Status = DocumentStatus.Uploaded,
            UploadedBy = upload.UploadedBy
        };

        _dbContext.Documents.Add(document);
        await _dbContext.SaveChangesAsync(cancellationToken);

        return new DocumentSummaryDto(
            document.Id,
            document.OriginalFilename,
            document.Status,
            document.DocumentType,
            document.Confidence,
            document.UploadedAt,
            document.ProcessedAt
        );
    }

    public async Task<IReadOnlyList<DocumentSummaryDto>> ListAsync(DocumentListQuery query, CancellationToken cancellationToken)
    {
        IQueryable<Document> baseQuery = _dbContext.Documents.AsNoTracking();

        if (TryParseEnum(query.Status, out DocumentStatus status))
        {
            baseQuery = baseQuery.Where(x => x.Status == status);
        }

        if (TryParseEnum(query.Type, out DocumentType type))
        {
            baseQuery = baseQuery.Where(x => x.DocumentType == type);
        }

        if (!string.IsNullOrWhiteSpace(query.Q))
        {
            baseQuery = baseQuery.Where(x => x.OriginalFilename.Contains(query.Q));
        }

        if (query.From.HasValue)
        {
            baseQuery = baseQuery.Where(x => x.UploadedAt >= query.From);
        }

        if (query.To.HasValue)
        {
            baseQuery = baseQuery.Where(x => x.UploadedAt <= query.To);
        }

        var skip = Math.Max(0, (query.Page - 1) * query.PageSize);

        var documents = await baseQuery
            .OrderByDescending(x => x.UploadedAt)
            .Skip(skip)
            .Take(query.PageSize)
            .ToListAsync(cancellationToken);

        return documents
            .Select(document => new DocumentSummaryDto(
                document.Id,
                document.OriginalFilename,
                document.Status,
                document.DocumentType,
                document.Confidence,
                document.UploadedAt,
                document.ProcessedAt
            ))
            .ToList();
    }

    public async Task<DocumentDetailDto?> GetByIdAsync(Guid id, CancellationToken cancellationToken)
    {
        var document = await _dbContext.Documents
            .AsNoTracking()
            .Include(x => x.Fields)
            .Include(x => x.Tables)
            .FirstOrDefaultAsync(x => x.Id == id, cancellationToken);

        if (document is null)
        {
            return null;
        }

        var tables = (document.Tables ?? [])
            .OrderBy(t => t.TableIndex)
            .Select(MapTable)
            .ToList();

        return new DocumentDetailDto(
            document.Id,
            document.OriginalFilename,
            document.Status,
            document.DocumentType,
            document.Confidence,
            document.UploadedAt,
            document.ProcessedAt,
            string.Empty,
            document.MimeType,
            document.NeedsReview,
            (document.Fields ?? []).Select(MapField).ToList(),
            tables
        );
    }

    public async Task<Stream?> GetFileStreamAsync(Guid id, CancellationToken cancellationToken)
    {
        var document = await _dbContext.Documents.AsNoTracking().FirstOrDefaultAsync(x => x.Id == id, cancellationToken);
        if (document is null || !_fileStorage.Exists(document.FilePath))
        {
            return null;
        }

        return await _fileStorage.OpenReadAsync(document.FilePath, cancellationToken);
    }

    public async Task<DocumentProcessResponse> ProcessAsync(Guid id, string? optionsJson, CancellationToken cancellationToken)
    {
        var document = await _dbContext.Documents
            .Include(x => x.Fields)
            .FirstOrDefaultAsync(x => x.Id == id, cancellationToken);

        if (document is null)
        {
            throw new InvalidOperationException("Documento no encontrado.");
        }

        if (document.Status == DocumentStatus.Processing)
        {
            var existing = _tracker.Register(document.Id);
            if (existing.Created)
            {
                await _queue.EnqueueAsync(new DocumentProcessJob(document.Id, SanitizeProcessOptions(optionsJson)), cancellationToken);
            }

            return BuildQueuedResponse(document.Id);
        }

        var wasProcessed = document.Status is DocumentStatus.Ready or DocumentStatus.NeedsReview;
        document.Status = DocumentStatus.Processing;
        document.ErrorMessage = null;
        _dbContext.ProcessingLogs.Add(new ProcessingLog
        {
            Id = Guid.NewGuid(),
            DocumentId = document.Id,
            Stage = "PROCESS",
            Level = "INFO",
            Message = wasProcessed
                ? "Documento encolado para reprocesamiento."
                : "Documento encolado para procesamiento."
        });
        await _dbContext.SaveChangesAsync(cancellationToken);

        var registration = _tracker.Register(document.Id);
        if (registration.Created)
        {
            await _queue.EnqueueAsync(new DocumentProcessJob(document.Id, SanitizeProcessOptions(optionsJson)), cancellationToken);
        }

        return BuildQueuedResponse(document.Id);
    }

    public async Task<DocumentProcessResponse> ReprocessAsync(Guid id, string? optionsJson, CancellationToken cancellationToken)
    {
        var document = await _dbContext.Documents
            .Include(x => x.Fields)
            .FirstOrDefaultAsync(x => x.Id == id, cancellationToken);

        if (document is null)
        {
            throw new InvalidOperationException("Documento no encontrado.");
        }

        document.Status = DocumentStatus.Processing;
        document.ErrorMessage = null;
        _dbContext.ProcessingLogs.Add(new ProcessingLog
        {
            Id = Guid.NewGuid(),
            DocumentId = document.Id,
            Stage = "PROCESS",
            Level = "INFO",
            Message = "Documento encolado para reprocesamiento."
        });
        await _dbContext.SaveChangesAsync(cancellationToken);

        var registration = _tracker.Register(document.Id);
        if (registration.Created)
        {
            await _queue.EnqueueAsync(new DocumentProcessJob(document.Id, SanitizeProcessOptions(optionsJson)), cancellationToken);
        }

        return BuildQueuedResponse(document.Id);
    }

    public async Task<DocumentProcessResponse> GetProcessStatusAsync(Guid id, CancellationToken cancellationToken)
    {
        var document = await _dbContext.Documents
            .AsNoTracking()
            .Include(x => x.Fields)
            .Include(x => x.Tables)
            .FirstOrDefaultAsync(x => x.Id == id, cancellationToken);

        if (document is null)
        {
            throw new InvalidOperationException("Documento no encontrado.");
        }

        if (document.Status is DocumentStatus.Ready or DocumentStatus.NeedsReview)
        {
            return BuildResponseFromDocument(document);
        }

        if (document.Status == DocumentStatus.Failed)
        {
            var errors = string.IsNullOrWhiteSpace(document.ErrorMessage)
                ? Array.Empty<string>()
                : new[] { document.ErrorMessage };

            return new DocumentProcessResponse(
                document.Id,
                DocumentStatus.Failed,
                document.DocumentType,
                document.Confidence ?? 0m,
                Array.Empty<DocumentFieldResultDto>(),
                Array.Empty<ExtractedTableDto>(),
                Array.Empty<string>(),
                errors,
                new DocumentProcessMeta(0, "pending", "", "", 0)
            );
        }

        return BuildQueuedResponse(document.Id);
    }

    public async Task<DocumentProcessResponse> ProcessNowAsync(Guid id, string? optionsJson, CancellationToken cancellationToken)
    {
        var document = await _dbContext.Documents
            .Include(x => x.Fields)
            .FirstOrDefaultAsync(x => x.Id == id, cancellationToken);

        if (document is null)
        {
            throw new InvalidOperationException("Documento no encontrado.");
        }

        document.Status = DocumentStatus.Processing;
        document.ErrorMessage = null;
        _dbContext.ProcessingLogs.Add(new ProcessingLog
        {
            Id = Guid.NewGuid(),
            DocumentId = document.Id,
            Stage = "PROCESS",
            Level = "INFO",
            Message = "Procesamiento iniciado."
        });
        await _dbContext.SaveChangesAsync(cancellationToken);

        DocumentProcessResponse response;
        try
        {
            _dbContext.ProcessingLogs.Add(new ProcessingLog
            {
                Id = Guid.NewGuid(),
                DocumentId = document.Id,
                Stage = "ENGINE",
                Level = "INFO",
                Message = "Enviando a motor de extraccion."
            });
            await _dbContext.SaveChangesAsync(cancellationToken);
            response = await _pythonClient.ProcessDocumentAsync(
                document.Id,
                document.FilePath,
                document.OriginalFilename,
                SanitizeProcessOptions(optionsJson),
                cancellationToken);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error al procesar documento {DocumentId}", document.Id);
            _dbContext.ProcessingLogs.Add(new ProcessingLog
            {
                Id = Guid.NewGuid(),
                DocumentId = document.Id,
                Stage = "ENGINE",
                Level = "ERROR",
                Message = ex.Message
            });
            await _dbContext.SaveChangesAsync(cancellationToken);
            throw;
        }

        document.DocumentType = response.DocumentType;
        document.Confidence = response.Confidence;
        document.ProcessedAt = DateTime.UtcNow;
        document.ModelVersion = response.Meta.ModelVersion;
        document.PipelineVersion = response.Meta.PipelineVersion;
        document.ErrorMessage = null;

        if (response.Warnings is { Count: > 0 })
        {
            foreach (var warning in response.Warnings)
            {
                _dbContext.ProcessingLogs.Add(new ProcessingLog
                {
                    Id = Guid.NewGuid(),
                    DocumentId = document.Id,
                    Stage = "ENGINE",
                    Level = "WARN",
                    Message = warning
                });
            }
        }

        var existingFields = await _dbContext.DocumentFields
            .Where(x => x.DocumentId == document.Id)
            .ToListAsync(cancellationToken);
        if (existingFields.Count > 0)
        {
            _dbContext.DocumentFields.RemoveRange(existingFields);
        }

        document.Fields = (response.Fields ?? []).Select(field => new DocumentField
        {
            Id = Guid.NewGuid(),
            DocumentId = document.Id,
            FieldKey = field.Key,
            FieldLabel = field.Label,
            FieldValue = field.Value,
            Confidence = field.Confidence,
            IsValid = field.Valid,
            ValidationErrors = (field.ValidationErrors ?? []).ToArray(),
            SourcePage = field.Source?.Page,
            SourceBbox = field.Source?.Bbox?.ToArray()
        }).ToList();

        if (document.Fields.Count > 0)
        {
            _dbContext.DocumentFields.AddRange(document.Fields);
        }

        var existingTables = await _dbContext.DocumentTables
            .Where(x => x.DocumentId == document.Id)
            .ToListAsync(cancellationToken);
        if (existingTables.Count > 0)
        {
            _dbContext.DocumentTables.RemoveRange(existingTables);
        }

        if (response.Tables is { Count: > 0 })
        {
            var newTables = response.Tables.Select((table, index) => new DocumentTable
            {
                Id = Guid.NewGuid(),
                DocumentId = document.Id,
                TableIndex = index,
                Columns = (table.Columns ?? []).ToArray(),
                RowsJson = JsonSerializer.Serialize(table.Rows),
                Quality = table.Quality,
                RowCount = table.RowCount,
                DocTypeHint = table.DocTypeHint
            }).ToList();
            _dbContext.DocumentTables.AddRange(newTables);
        }

        var needsReview = response.Status == DocumentStatus.NeedsReview;
        if (needsReview && ShouldForceReadyForActa(document.DocumentType, (document.Fields ?? []).ToList()))
        {
            NormalizeActaCriticalFlags((document.Fields ?? []).ToList());
            needsReview = false;
        }
        if (!needsReview && (response.Fields is null || response.Fields.Count == 0))
        {
            needsReview = true;
        }

        document.NeedsReview = needsReview;
        document.Status = needsReview ? DocumentStatus.NeedsReview : DocumentStatus.Ready;

        _dbContext.ProcessingLogs.Add(new ProcessingLog
        {
            Id = Guid.NewGuid(),
            DocumentId = document.Id,
            Stage = "PROCESS",
            Level = "INFO",
            Message = document.NeedsReview ? "Documento requiere revisión." : "Documento procesado correctamente."
        });

        await _dbContext.SaveChangesAsync(cancellationToken);

        return response;
    }

    public async Task UpdateFieldsAsync(Guid id, DocumentFieldsUpdateRequest request, CancellationToken cancellationToken)
    {
        var document = await _dbContext.Documents
            .Include(x => x.Fields)
            .FirstOrDefaultAsync(x => x.Id == id, cancellationToken);

        if (document is null)
        {
            throw new InvalidOperationException("Documento no encontrado.");
        }

        foreach (var update in request.Fields)
        {
            var field = (document.Fields ?? []).FirstOrDefault(x => x.FieldKey == update.Key);
            if (field is null)
            {
                continue;
            }

            var sanitized = (update.Value ?? string.Empty).Trim();
            if (string.IsNullOrWhiteSpace(sanitized))
            {
                continue;
            }

            field.Corrected = true;
            field.CorrectedValue = sanitized;
            // Keep the base value aligned so every consumer (UI/export/integration) sees the corrected data.
            field.FieldValue = sanitized;
            field.CorrectedBy = request.ReviewedBy;
            field.CorrectedAt = DateTime.UtcNow;
        }

        document.NeedsReview = false;
        document.Status = DocumentStatus.Ready;
        await _dbContext.SaveChangesAsync(cancellationToken);
    }

    public async Task MarkFailedAsync(Guid id, string reason, CancellationToken cancellationToken)
    {
        var document = await _dbContext.Documents.FirstOrDefaultAsync(x => x.Id == id, cancellationToken);
        if (document is null)
        {
            throw new InvalidOperationException("Documento no encontrado.");
        }

        document.Status = DocumentStatus.Failed;
        document.ErrorMessage = reason;
        _dbContext.ProcessingLogs.Add(new ProcessingLog
        {
            Id = Guid.NewGuid(),
            DocumentId = document.Id,
            Stage = "PROCESS",
            Level = "WARN",
            Message = $"Marcado como fallido manualmente: {reason}"
        });

        await _dbContext.SaveChangesAsync(cancellationToken);
    }

    public async Task DeleteAsync(Guid id, CancellationToken cancellationToken)
    {
        var document = await _dbContext.Documents
            .Include(x => x.Fields)
            .Include(x => x.ProcessingLogs)
            .FirstOrDefaultAsync(x => x.Id == id, cancellationToken);

        if (document is null)
        {
            throw new InvalidOperationException("Documento no encontrado.");
        }

        if (_fileStorage.Exists(document.FilePath))
        {
            await _fileStorage.DeleteAsync(document.FilePath, cancellationToken);
        }

        if (document.Fields.Count > 0)
        {
            _dbContext.DocumentFields.RemoveRange(document.Fields);
        }

        if (document.ProcessingLogs.Count > 0)
        {
            _dbContext.ProcessingLogs.RemoveRange(document.ProcessingLogs);
        }

        _dbContext.Documents.Remove(document);
        await _dbContext.SaveChangesAsync(cancellationToken);
    }

    public async Task<IReadOnlyList<ProcessingLogDto>> GetLogsAsync(Guid id, CancellationToken cancellationToken)
    {
        var logs = await _dbContext.ProcessingLogs
            .AsNoTracking()
            .Where(x => x.DocumentId == id)
            .OrderByDescending(x => x.CreatedAt)
            .ToListAsync(cancellationToken);

        return logs.Select(log => new ProcessingLogDto(
            log.Id,
            log.DocumentId,
            log.Stage,
            log.Level,
            log.Message,
            log.CreatedAt
        )).ToList();
    }

    private static DocumentFieldDto MapField(DocumentField field)
    {
        FieldSourceDto? source = null;
        if (field.SourcePage.HasValue && field.SourceBbox is not null)
        {
            source = new FieldSourceDto(field.SourcePage.Value, field.SourceBbox);
        }

        return new DocumentFieldDto(
            field.FieldKey,
            field.FieldLabel,
            field.FieldValue,
            field.Confidence,
            field.IsValid,
            field.ValidationErrors,
            source,
            field.Corrected,
            field.CorrectedValue
        );
    }

    private static ExtractedTableDto MapTable(DocumentTable table)
    {
        List<IReadOnlyDictionary<string, string?>> rows;
        try
        {
            rows = JsonSerializer.Deserialize<List<Dictionary<string, string?>>>(table.RowsJson)
                       ?.Cast<IReadOnlyDictionary<string, string?>>()
                       .ToList()
                   ?? [];
        }
        catch
        {
            rows = [];
        }

        return new ExtractedTableDto(
            table.Columns,
            rows,
            table.Quality,
            table.RowCount,
            table.DocTypeHint
        );
    }

    private static DocumentProcessResponse BuildResponseFromDocument(Document document)
    {
        var fields = (document.Fields ?? [])
            .Select(field =>
            {
                FieldSourceDto? source = null;
                if (field.SourcePage.HasValue && field.SourceBbox is not null)
                {
                    source = new FieldSourceDto(field.SourcePage.Value, field.SourceBbox);
                }

                return new DocumentFieldResultDto(
                    field.FieldKey,
                    field.FieldLabel,
                    field.CorrectedValue ?? field.FieldValue,
                    field.Confidence,
                    field.IsValid,
                    field.ValidationErrors ?? [],
                    source
                );
            })
            .ToList();

        var tables = (document.Tables ?? [])
            .OrderBy(t => t.TableIndex)
            .Select(MapTable)
            .ToList();

        return new DocumentProcessResponse(
            document.Id,
            document.Status,
            document.DocumentType,
            document.Confidence ?? 0m,
            fields,
            tables,
            Array.Empty<string>(),
            Array.Empty<string>(),
            new DocumentProcessMeta(
                0,
                "stored",
                document.PipelineVersion ?? string.Empty,
                document.ModelVersion ?? string.Empty,
                0
            )
        );
    }

    private static bool TryParseEnum<TEnum>(string? value, out TEnum result) where TEnum : struct, Enum
    {
        result = default;
        if (string.IsNullOrWhiteSpace(value))
        {
            return false;
        }

        if (Enum.TryParse(value, true, out result))
        {
            return true;
        }

        var normalized = value.Replace("_", string.Empty, StringComparison.OrdinalIgnoreCase);
        foreach (var enumValue in Enum.GetValues<TEnum>())
        {
            if (string.Equals(normalized, enumValue.ToString(), StringComparison.OrdinalIgnoreCase))
            {
                result = enumValue;
                return true;
            }
        }

        return false;
    }

    private static DocumentProcessResponse BuildQueuedResponse(Guid documentId)
    {
        return new DocumentProcessResponse(
            documentId,
            DocumentStatus.Processing,
            DocumentType.Unknown,
            0m,
            Array.Empty<DocumentFieldResultDto>(),
            Array.Empty<ExtractedTableDto>(),
            Array.Empty<string>(),
            Array.Empty<string>(),
            new DocumentProcessMeta(0, "pending", "", "", 0)
        );
    }

    private static bool ShouldForceReadyForActa(DocumentType documentType, IReadOnlyList<DocumentField> fields)
    {
        if (documentType != DocumentType.ActaNacimiento)
        {
            return false;
        }

        var hasNombre = HasEffectivelyValidField(fields, "nombre", null);
        var hasFechaNac = HasEffectivelyValidField(fields, "fecha_nacimiento", static value =>
            Regex.IsMatch(value, @"^\d{2}[/-]\d{2}[/-]\d{4}$"));
        var hasFolio = HasEffectivelyValidField(fields, "folio", static value =>
            ActaCodeRegex.IsMatch(value));
        var hasNumeroActa = HasEffectivelyValidField(fields, "numero_acta", static value =>
            ActaCodeRegex.IsMatch(value));

        return hasNombre && hasFechaNac && hasFolio && hasNumeroActa;
    }

    private static bool HasEffectivelyValidField(
        IReadOnlyList<DocumentField> fields,
        string key,
        Func<string, bool>? semanticValidator)
    {
        foreach (var field in fields)
        {
            if (!string.Equals(field.FieldKey, key, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            var value = string.IsNullOrWhiteSpace(field.CorrectedValue)
                ? field.FieldValue
                : field.CorrectedValue;
            if (string.IsNullOrWhiteSpace(value))
            {
                continue;
            }

            if (field.IsValid)
            {
                return true;
            }

            if (semanticValidator is not null && semanticValidator(value.Trim()))
            {
                return true;
            }
        }

        return false;
    }

    private static string? SanitizeProcessOptions(string? rawOptionsJson)
    {
        if (string.IsNullOrWhiteSpace(rawOptionsJson))
        {
            return null;
        }

        try
        {
            using var document = JsonDocument.Parse(rawOptionsJson);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                return null;
            }

            if (!root.TryGetProperty("force_document_type", out var forcedTypeElement))
            {
                return null;
            }
            if (forcedTypeElement.ValueKind != JsonValueKind.String)
            {
                return null;
            }

            var forcedType = (forcedTypeElement.GetString() ?? string.Empty).Trim().ToUpperInvariant();
            if (forcedType != "FACTURA")
            {
                return null;
            }

            return "{\"force_document_type\":\"FACTURA\"}";
        }
        catch
        {
            return null;
        }
    }

    private static void NormalizeActaCriticalFlags(IReadOnlyList<DocumentField> fields)
    {
        foreach (var field in fields)
        {
            if (!string.Equals(field.FieldKey, "folio", StringComparison.OrdinalIgnoreCase)
                && !string.Equals(field.FieldKey, "numero_acta", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            var value = string.IsNullOrWhiteSpace(field.CorrectedValue)
                ? field.FieldValue
                : field.CorrectedValue;
            if (string.IsNullOrWhiteSpace(value))
            {
                continue;
            }

            if (!ActaCodeRegex.IsMatch(value.Trim()))
            {
                continue;
            }

            field.IsValid = true;
            field.ValidationErrors = Array.Empty<string>();
        }
    }
}
