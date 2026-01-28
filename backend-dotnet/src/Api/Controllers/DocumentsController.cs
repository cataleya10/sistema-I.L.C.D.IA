using Application.DTOs;
using Application.Interfaces;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Options;
using Shared.Options;

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
    public async Task<ActionResult<DocumentProcessResponse>> Process(Guid id, CancellationToken cancellationToken)
    {
        var result = await _documentService.ProcessAsync(id, cancellationToken);
        return Ok(result);
    }

    [HttpPut("{id:guid}/fields")]
    public async Task<IActionResult> UpdateFields(Guid id, [FromBody] DocumentFieldsUpdateRequest request, CancellationToken cancellationToken)
    {
        var reviewedBy = User?.Identity?.Name;
        var updatedRequest = request with { ReviewedBy = reviewedBy };
        await _documentService.UpdateFieldsAsync(id, updatedRequest, cancellationToken);
        return NoContent();
    }

    [HttpGet("{id:guid}/logs")]
    public async Task<ActionResult<IReadOnlyList<ProcessingLogDto>>> GetLogs(Guid id, CancellationToken cancellationToken)
    {
        var logs = await _documentService.GetLogsAsync(id, cancellationToken);
        return Ok(logs);
    }
}
