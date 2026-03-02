using Application.DTOs;

namespace Application.Interfaces;

public interface IDocumentExportService
{
    string BuildRtf(DocumentDetailDto detail);
    byte[] BuildXlsx(DocumentDetailDto detail);
}
