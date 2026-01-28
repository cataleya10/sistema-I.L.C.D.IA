namespace Application.DTOs;

public sealed record DocumentFieldUpdateDto(string Key, string Value);

public sealed record DocumentFieldsUpdateRequest(IReadOnlyList<DocumentFieldUpdateDto> Fields, string? ReviewedBy = null);
