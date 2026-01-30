using Application.DTOs;
using Application.Interfaces;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Options;
using Shared.Options;
using Api.Authorization;

namespace Api.Controllers;

[ApiController]
[Route("api/documents")]
[Authorize]
public class DocumentsController : ControllerBase
{
    private readonly IDocumentService _documentService;
    private readonly UploadOptions _uploadOptions;

    public DocumentsController(IDocumentService documentService, IOptions<UploadOptions> uploadOptions)
    {
        _documentService = documentService;
        _uploadOptions = uploadOptions.Value;
    }

    [HttpPost("upload")]
    [RequireRole("Admin")]
    public async Task<ActionResult<DocumentSummaryDto>> Upload([FromForm] IFormFile file, CancellationToken cancellationToken)
    {
        if (file is null || file.Length == 0)
        {
            return BadRequest("Archivo inválido.");
        }

        if (file.Length > _uploadOptions.MaxFileSizeBytes)
        {
            return BadRequest($"El archivo excede el tamaño permitido ({_uploadOptions.MaxFileSizeBytes} bytes).");
        }

        if (!_uploadOptions.AllowedContentTypes.Contains(file.ContentType))
        {
            return BadRequest("Tipo de archivo no permitido.");
        }

        await using var stream = file.OpenReadStream();
        var upload = new DocumentUpload(
            stream,
            file.FileName,
            file.ContentType,
            file.Length,
            User?.Identity?.Name
        );

        var result = await _documentService.UploadAsync(upload, cancellationToken);
        return Ok(result);
    }

    [HttpGet]
    [RequireRole("Admin,User")]
    public async Task<ActionResult<IReadOnlyList<DocumentSummaryDto>>> List(
        [FromQuery] string? status,
        [FromQuery] string? type,
        [FromQuery] string? q,
        [FromQuery] DateTime? from,
        [FromQuery] DateTime? to,
        [FromQuery] int page = 1,
        [FromQuery] int pageSize = 20,
        CancellationToken cancellationToken = default)
    {
        var query = new DocumentListQuery(status, type, q, from, to, page, pageSize);
        var result = await _documentService.ListAsync(query, cancellationToken);
        return Ok(result);
    }

    [HttpGet("{id:guid}")]
    [RequireRole("Admin,User")]
    public async Task<ActionResult<DocumentDetailDto>> GetById(Guid id, CancellationToken cancellationToken)
    {
        var result = await _documentService.GetByIdAsync(id, cancellationToken);
        if (result is null)
        {
            return NotFound();
        }

        var fileUrl = Url.ActionLink(nameof(GetFile), values: new { id }) ?? string.Empty;
        var updated = result with { FileUrl = fileUrl };
        return Ok(updated);
    }

    [HttpGet("{id:guid}/file")]
    [RequireRole("Admin,User")]
    public async Task<IActionResult> GetFile(Guid id, CancellationToken cancellationToken)
    {
        var stream = await _documentService.GetFileStreamAsync(id, cancellationToken);
        if (stream is null)
        {
            return NotFound();
        }

        var detail = await _documentService.GetByIdAsync(id, cancellationToken);
        var mimeType = detail?.MimeType ?? "application/octet-stream";
        return File(stream, mimeType, enableRangeProcessing: true);
    }

    [HttpPost("{id:guid}/process")]
    [RequireRole("Admin")]
    public async Task<ActionResult<DocumentProcessResponse>> Process(Guid id, CancellationToken cancellationToken)
    {
        var result = await _documentService.ProcessAsync(id, cancellationToken);
        return Ok(result);
    }

    [HttpPost("{id:guid}/reprocess")]
    [RequireRole("Admin")]
    public async Task<ActionResult<DocumentProcessResponse>> Reprocess(Guid id, CancellationToken cancellationToken)
    {
        var result = await _documentService.ProcessNowAsync(id, cancellationToken);
        return Ok(result);
    }

    [HttpPut("{id:guid}/fields")]
    [RequireRole("Admin")]
    public async Task<IActionResult> UpdateFields(Guid id, [FromBody] DocumentFieldsUpdateRequest request, CancellationToken cancellationToken)
    {
        var reviewedBy = User?.Identity?.Name;
        var updatedRequest = request with { ReviewedBy = reviewedBy };
        await _documentService.UpdateFieldsAsync(id, updatedRequest, cancellationToken);
        return NoContent();
    }

    [HttpGet("{id:guid}/logs")]
    [RequireRole("Admin,User")]
    public async Task<ActionResult<IReadOnlyList<ProcessingLogDto>>> GetLogs(Guid id, CancellationToken cancellationToken)
    {
        var logs = await _documentService.GetLogsAsync(id, cancellationToken);
        return Ok(logs);
    }

    [HttpPost("{id:guid}/mark-failed")]
    [RequireRole("Admin")]
    public async Task<IActionResult> MarkFailed(
        Guid id,
        [FromBody] DocumentFailRequest? request,
        [FromQuery] string? reason,
        CancellationToken cancellationToken)
    {
        var resolved = !string.IsNullOrWhiteSpace(reason) ? reason : request?.Reason;
        resolved = string.IsNullOrWhiteSpace(resolved) ? "Marcado manualmente." : resolved;
        await _documentService.MarkFailedAsync(id, resolved, cancellationToken);
        return NoContent();
    }
}

public sealed record DocumentFailRequest(string? Reason);
