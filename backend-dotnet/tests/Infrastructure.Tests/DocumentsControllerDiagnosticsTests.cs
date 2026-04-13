using Api.Controllers;
using Application.DTOs;
using Application.Interfaces;
using Infrastructure.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Shared.Options;
using Xunit;

namespace Infrastructure.Tests;

public class DocumentsControllerDiagnosticsTests
{
    [Fact]
    public async Task AuditFolder_ReturnsOk_WhenClientReturnsSummary()
    {
        var auditPath = OperatingSystem.IsWindows() ? @"C:\audits\nomina" : "/tmp/audits/nomina";
        var auditFilePath = OperatingSystem.IsWindows() ? @"C:\audits\nomina\nomina-01.pdf" : "/tmp/audits/nomina/nomina-01.pdf";
        var expected = new AuditFolderResponseDto(
            auditPath,
            true,
            25,
            false,
            2,
            2,
            1,
            1,
            1,
            0,
            0,
            0,
            new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
            {
                ["FACTURA"] = 2
            },
            new[]
            {
                new AuditDocumentSummaryDto(
                    "nomina-01.pdf",
                    auditFilePath,
                    "READY",
                    "FACTURA",
                    0.98m,
                    5,
                    4,
                    1,
                    new[] { "fila incompleta" },
                    false,
                    new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
                    {
                        ["referencia"] = "ABC123"
                    },
                    null)
            });

        var controller = CreateController(new FakePythonAiClient((request, cancellationToken) =>
        {
            cancellationToken.ThrowIfCancellationRequested();
            Assert.Equal(auditPath, request.FolderPath);
            Assert.Equal(25, request.Limit);
            return Task.FromResult(expected);
        }));

        var result = await controller.AuditFolder(
            new AuditFolderRequestDto(auditPath, true, 25, false),
            CancellationToken.None);

        var ok = Assert.IsType<OkObjectResult>(result.Result);
        var payload = Assert.IsType<AuditFolderResponseDto>(ok.Value);
        Assert.Equal(expected.FolderPath, payload.FolderPath);
        Assert.Single(payload.Documents);
        Assert.Equal("ABC123", payload.Documents[0].MappedFields["referencia"]);
    }

    [Fact]
    public async Task AuditFolder_ReturnsBadRequest_WhenFolderPathIsRelative()
    {
        var controller = CreateController(new FakePythonAiClient((_, cancellationToken) =>
        {
            cancellationToken.ThrowIfCancellationRequested();
            throw new Xunit.Sdk.XunitException("El cliente no debio ejecutarse.");
        }));

        var result = await controller.AuditFolder(
            new AuditFolderRequestDto("nomina\\enero", true, 10, false),
            CancellationToken.None);

        var badRequest = Assert.IsType<BadRequestObjectResult>(result.Result);
        Assert.Equal("La ruta de carpeta debe ser absoluta.", badRequest.Value);
    }

    [Fact]
    public async Task AuditFolder_ReturnsNotImplemented_WhenClientDoesNotSupportAudit()
    {
        var auditPath2 = OperatingSystem.IsWindows() ? @"C:\audits\nomina" : "/tmp/audits/nomina";
        var controller = CreateController(new FakePythonAiClient((_, cancellationToken) =>
        {
            cancellationToken.ThrowIfCancellationRequested();
            throw new NotSupportedException("No soportado.");
        }));

        var result = await controller.AuditFolder(
            new AuditFolderRequestDto(auditPath2, true, 10, false),
            CancellationToken.None);

        var notImplemented = Assert.IsType<ObjectResult>(result.Result);
        Assert.Equal(501, notImplemented.StatusCode);
    }

    private static DocumentsController CreateController(IPythonAiClient pythonAiClient)
    {
        return new DocumentsController(
            new FakeDocumentService(),
            pythonAiClient,
            new DocumentExportService(),
            Options.Create(new UploadOptions()),
            NullLogger<DocumentsController>.Instance);
    }

    private sealed class FakeDocumentService : IDocumentService
    {
        public Task<DocumentSummaryDto> UploadAsync(DocumentUpload upload, CancellationToken cancellationToken) => throw new NotImplementedException();
        public Task<IReadOnlyList<DocumentSummaryDto>> ListAsync(DocumentListQuery query, CancellationToken cancellationToken) => throw new NotImplementedException();
        public Task<DocumentDetailDto?> GetByIdAsync(Guid id, CancellationToken cancellationToken) => throw new NotImplementedException();
        public Task<Stream?> GetFileStreamAsync(Guid id, CancellationToken cancellationToken) => throw new NotImplementedException();
        public Task<DocumentProcessResponse> ProcessAsync(Guid id, string? optionsJson, CancellationToken cancellationToken) => throw new NotImplementedException();
        public Task<DocumentProcessResponse> GetProcessStatusAsync(Guid id, CancellationToken cancellationToken) => throw new NotImplementedException();
        public Task<DocumentProcessResponse> ReprocessAsync(Guid id, string? optionsJson, CancellationToken cancellationToken) => throw new NotImplementedException();
        public Task<DocumentProcessResponse> ProcessNowAsync(Guid id, string? optionsJson, CancellationToken cancellationToken) => throw new NotImplementedException();
        public Task UpdateFieldsAsync(Guid id, DocumentFieldsUpdateRequest request, CancellationToken cancellationToken) => throw new NotImplementedException();
        public Task MarkFailedAsync(Guid id, string reason, CancellationToken cancellationToken) => throw new NotImplementedException();
        public Task DeleteAsync(Guid id, CancellationToken cancellationToken) => throw new NotImplementedException();
        public Task<IReadOnlyList<ProcessingLogDto>> GetLogsAsync(Guid id, CancellationToken cancellationToken) => throw new NotImplementedException();
    }

    private sealed class FakePythonAiClient : IPythonAiClient
    {
        private readonly Func<AuditFolderRequestDto, CancellationToken, Task<AuditFolderResponseDto>> _auditHandler;

        public FakePythonAiClient(Func<AuditFolderRequestDto, CancellationToken, Task<AuditFolderResponseDto>> auditHandler)
        {
            _auditHandler = auditHandler;
        }

        public Task<DocumentProcessResponse> ProcessDocumentAsync(
            Guid documentId,
            string filePath,
            string? originalFilename,
            string? optionsJson,
            CancellationToken cancellationToken)
            => throw new NotImplementedException();

        public Task<AuditFolderResponseDto> AuditFolderAsync(
            AuditFolderRequestDto request,
            CancellationToken cancellationToken)
            => _auditHandler(request, cancellationToken);

        public Task<OnlineLearningStatsDto> GetOnlineLearningStatsAsync(
            int recent,
            CancellationToken cancellationToken)
            => throw new NotImplementedException();
    }
}
