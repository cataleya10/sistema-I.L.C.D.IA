using Application.DTOs;
using Application.Interfaces;
using Domain.Enums;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Options;
using Shared.Options;
using Api.Authorization;
using System.Text.Json;

namespace Api.Controllers;

[ApiController]
[Route("api/documents")]
[Authorize]
public class DocumentsController : ControllerBase
{
    private readonly IDocumentService _documentService;
    private readonly IPythonAiClient _pythonAiClient;
    private readonly IDocumentExportService _exportService;
    private readonly UploadOptions _uploadOptions;
    private readonly ILogger<DocumentsController> _logger;

    public DocumentsController(
        IDocumentService documentService,
        IPythonAiClient pythonAiClient,
        IDocumentExportService exportService,
        IOptions<UploadOptions> uploadOptions,
        ILogger<DocumentsController> logger)
    {
        _documentService = documentService;
        _pythonAiClient = pythonAiClient;
        _exportService = exportService;
        _uploadOptions = uploadOptions.Value;
        _logger = logger;
    }

    [HttpPost("upload")]
    [Consumes("multipart/form-data")]
    [RequireRole("Admin,User")]
    public async Task<ActionResult<DocumentSummaryDto>> Upload([FromForm] IFormFile file, CancellationToken cancellationToken)
    {
        if (file is null || file.Length == 0)
            return BadRequest("Archivo invalido.");
        if (file.Length > _uploadOptions.MaxFileSizeBytes)
            return BadRequest($"El archivo excede el tamano permitido ({_uploadOptions.MaxFileSizeBytes} bytes).");
        if (!_uploadOptions.AllowedContentTypes.Contains(file.ContentType))
            return BadRequest("Tipo de archivo no permitido.");

        await using var stream = file.OpenReadStream();
        if (!HasValidFileSignature(stream, file.ContentType))
            return BadRequest("El archivo no coincide con el tipo declarado.");
        stream.Position = 0;
        var upload = new DocumentUpload(stream, file.FileName, file.ContentType, file.Length, User?.Identity?.Name);
        var result = await _documentService.UploadAsync(upload, cancellationToken);
        return Ok(result);
    }

    [HttpGet]
    [RequireRole("Admin,User")]
    public async Task<ActionResult<IReadOnlyList<DocumentSummaryDto>>> List(
        [FromQuery] string? status, [FromQuery] string? type, [FromQuery] string? q,
        [FromQuery] DateTime? from, [FromQuery] DateTime? to,
        [FromQuery] int page = 1, [FromQuery] int pageSize = 20,
        CancellationToken cancellationToken = default)
    {
        if (page < 1) page = 1;
        if (pageSize < 1) pageSize = 20;
        var query = new DocumentListQuery(status, type, q, from, to, page, pageSize);
        var result = await _documentService.ListAsync(query, cancellationToken);
        return Ok(result);
    }

    [HttpGet("online-learning/stats")]
    [RequireRole("Admin,User")]
    public async Task<ActionResult<OnlineLearningStatsDto>> GetOnlineLearningStats(
        [FromQuery] int recent = 10, CancellationToken cancellationToken = default)
    {
        var safeRecent = Math.Clamp(recent, 0, 100);
        try
        {
            var stats = await _pythonAiClient.GetOnlineLearningStatsAsync(safeRecent, cancellationToken);
            return Ok(stats);
        }
        catch (HttpRequestException)
        {
            return StatusCode(StatusCodes.Status503ServiceUnavailable, "No se pudo consultar el estado de entrenamiento del motor IA.");
        }
    }

    [HttpPost("diagnostics/audit-folder")]
    [RequireRole("Admin")]
    public async Task<ActionResult<AuditFolderResponseDto>> AuditFolder(
        [FromBody] AuditFolderRequestDto? request,
        CancellationToken cancellationToken = default)
    {
        if (request is null || string.IsNullOrWhiteSpace(request.FolderPath))
        {
            return BadRequest("La ruta de carpeta es obligatoria.");
        }

        var folderPath = request.FolderPath.Trim();
        if (!Path.IsPathRooted(folderPath))
        {
            return BadRequest("La ruta de carpeta debe ser absoluta.");
        }

        if (request.Limit is < 1 or > 500)
        {
            return BadRequest("El limite debe estar entre 1 y 500.");
        }

        try
        {
            var result = await _pythonAiClient.AuditFolderAsync(
                request with { FolderPath = folderPath },
                cancellationToken);
            return Ok(result);
        }
        catch (NotSupportedException)
        {
            return StatusCode(StatusCodes.Status501NotImplemented, "La auditoria de carpetas requiere el motor Python habilitado.");
        }
        catch (InvalidOperationException ex)
        {
            _logger.LogWarning(ex, "AuditFolder: solicitud invalida");
            return BadRequest("La solicitud de auditoria es invalida.");
        }
        catch (HttpRequestException)
        {
            return StatusCode(StatusCodes.Status503ServiceUnavailable, "No se pudo consultar la auditoria del motor IA.");
        }
    }

    [HttpGet("{id:guid}")]
    [RequireRole("Admin,User")]
    public async Task<ActionResult<DocumentDetailDto>> GetById(Guid id, CancellationToken cancellationToken)
    {
        var result = await _documentService.GetByIdAsync(id, cancellationToken);
        if (result is null) return NotFound("Documento no encontrado.");
        var fileUrl = Url.ActionLink(nameof(GetFile), values: new { id }) ?? string.Empty;
        return Ok(result with { FileUrl = fileUrl });
    }

    [HttpGet("{id:guid}/file")]
    [RequireRole("Admin,User")]
    public async Task<IActionResult> GetFile(Guid id, CancellationToken cancellationToken)
    {
        var stream = await _documentService.GetFileStreamAsync(id, cancellationToken);
        if (stream is null) return NotFound("Archivo no encontrado.");
        var detail = await _documentService.GetByIdAsync(id, cancellationToken);
        return File(stream, detail?.MimeType ?? "application/octet-stream", enableRangeProcessing: true);
    }

    [HttpGet("{id:guid}/export/word")]
    [RequireRole("Admin,User")]
    public async Task<IActionResult> ExportWord(Guid id, CancellationToken cancellationToken)
    {
        var detail = await _documentService.GetByIdAsync(id, cancellationToken);
        if (detail is null) return NotFound("Documento no encontrado.");
        var rtf = _exportService.BuildRtf(detail);
        var filename = Path.GetFileNameWithoutExtension(detail.OriginalFilename);
        var outputName = string.IsNullOrWhiteSpace(filename) ? "documento" : filename;
        return File(global::System.Text.Encoding.UTF8.GetBytes(rtf), "application/rtf", $"{outputName}.doc");
    }

    [HttpGet("{id:guid}/export/excel")]
    [RequireRole("Admin,User")]
    public async Task<IActionResult> ExportExcel(Guid id, CancellationToken cancellationToken)
    {
        var detail = await _documentService.GetByIdAsync(id, cancellationToken);
        if (detail is null) return NotFound("Documento no encontrado.");
        var bytes = _exportService.BuildXlsx(detail);
        var filename = Path.GetFileNameWithoutExtension(detail.OriginalFilename);
        var outputName = string.IsNullOrWhiteSpace(filename) ? "documento" : filename;
        return File(bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", $"{outputName}.xlsx");
    }

    [HttpPost("{id:guid}/process")]
    [RequireRole("Admin,User")]
    public async Task<ActionResult<DocumentProcessResponse>> Process(
        Guid id, [FromBody] DocumentProcessOptionsRequest? request, CancellationToken cancellationToken)
    {
        var result = await _documentService.ProcessAsync(id, BuildProcessOptionsJson(request), cancellationToken);
        return result.Status == DocumentStatus.Processing ? Accepted(result) : Ok(result);
    }

    [HttpGet("{id:guid}/process/status")]
    [RequireRole("Admin,User")]
    public async Task<ActionResult<DocumentProcessResponse>> ProcessStatus(Guid id, CancellationToken cancellationToken)
    {
        var detail = await _documentService.GetByIdAsync(id, cancellationToken);
        if (detail is null) return NotFound("Documento no encontrado.");
        return Ok(await _documentService.GetProcessStatusAsync(id, cancellationToken));
    }

    [HttpPost("{id:guid}/reprocess")]
    [RequireRole("Admin,User")]
    public async Task<ActionResult<DocumentProcessResponse>> Reprocess(
        Guid id, [FromBody] DocumentProcessOptionsRequest? request, CancellationToken cancellationToken)
    {
        var result = await _documentService.ReprocessAsync(id, BuildProcessOptionsJson(request), cancellationToken);
        return Accepted(result);
    }

    [HttpPut("{id:guid}/fields")]
    [RequireRole("Admin,User")]
    public async Task<IActionResult> UpdateFields(Guid id, [FromBody] DocumentFieldsUpdateRequest request, CancellationToken cancellationToken)
    {
        if (request is null) return BadRequest("Solicitud invalida.");
        var reviewedBy = User?.Identity?.Name;
        await _documentService.UpdateFieldsAsync(id, request with { ReviewedBy = reviewedBy }, cancellationToken);
        return NoContent();
    }

    [HttpGet("{id:guid}/logs")]
    [RequireRole("Admin,User")]
    public async Task<ActionResult<IReadOnlyList<ProcessingLogDto>>> GetLogs(Guid id, CancellationToken cancellationToken)
    {
        return Ok(await _documentService.GetLogsAsync(id, cancellationToken));
    }

    [HttpPost("{id:guid}/mark-failed")]
    [RequireRole("Admin,User")]
    public async Task<IActionResult> MarkFailed(
        Guid id, [FromBody] DocumentFailRequest? request, [FromQuery] string? reason, CancellationToken cancellationToken)
    {
        var resolved = !string.IsNullOrWhiteSpace(reason) ? reason : request?.Reason;
        resolved = string.IsNullOrWhiteSpace(resolved) ? "Marcado manualmente." : resolved;
        await _documentService.MarkFailedAsync(id, resolved, cancellationToken);
        return NoContent();
    }

    [HttpDelete("{id:guid}")]
    [RequireRole("Admin,User")]
    public async Task<IActionResult> Delete(Guid id, CancellationToken cancellationToken)
    {
        try { await _documentService.DeleteAsync(id, cancellationToken); return NoContent(); }
        catch (IOException) { return Conflict("No se puede eliminar el documento mientras esta en procesamiento."); }
        catch (InvalidOperationException) { return NotFound("Documento no encontrado."); }
    }

    private static bool HasValidFileSignature(Stream stream, string contentType)
    {
        Span<byte> header = stackalloc byte[8];
        var read = stream.Read(header);
        if (read < 4) return false;
        return contentType switch
        {
            "application/pdf" => header[0] == (byte)'%' && header[1] == (byte)'P' && header[2] == (byte)'D' && header[3] == (byte)'F',
            "image/png" => read >= 8 && header[0] == 0x89 && header[1] == 0x50 && header[2] == 0x4E && header[3] == 0x47
                && header[4] == 0x0D && header[5] == 0x0A && header[6] == 0x1A && header[7] == 0x0A,
            "image/jpeg" => header[0] == 0xFF && header[1] == 0xD8 && header[2] == 0xFF,
            _ => true
        };
    }

    private static string? BuildProcessOptionsJson(DocumentProcessOptionsRequest? request)
    {
        var forced = (request?.ForceDocumentType ?? string.Empty).Trim().ToUpperInvariant();
        return forced != "FACTURA" ? null : JsonSerializer.Serialize(new { force_document_type = "FACTURA" });
    }
}

public sealed record DocumentFailRequest(string? Reason);
public sealed record DocumentProcessOptionsRequest(string? ForceDocumentType);
