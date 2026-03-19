from pydantic import BaseModel, Field


class AuditFolderRequest(BaseModel):
    folder_path: str
    recurse: bool = True
    limit: int = Field(default=100, ge=1, le=500)
    issues_only: bool = False


class AuditDocumentSummary(BaseModel):
    name: str
    file_path: str
    status: str
    document_type: str | None = None
    confidence: float | None = None
    tabla_rows: int = 0
    detalle_rows: int = 0
    warning_count: int = 0
    warnings: list[str] = Field(default_factory=list)
    hard_fail: bool = False
    mapped_fields: dict[str, str] = Field(default_factory=dict)
    error: str | None = None


class AuditFolderResponse(BaseModel):
    folder_path: str
    recurse: bool
    limit: int
    issues_only: bool
    matched_files: int
    processed_files: int
    documents_returned: int
    clean_count: int
    issue_count: int
    error_count: int
    hard_fail_count: int
    non_factura_count: int
    document_type_counts: dict[str, int] = Field(default_factory=dict)
    documents: list[AuditDocumentSummary] = Field(default_factory=list)
