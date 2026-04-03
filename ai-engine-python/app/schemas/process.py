from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

class FieldSource(BaseModel):
    page: int
    bbox: List[int]

class DocumentField(BaseModel):
    key: str
    label: str
    value: Optional[Any] = None
    confidence: float
    valid: bool
    validation_errors: List[str] = Field(default_factory=list)
    source: Optional[FieldSource] = None

class ExtractedTable(BaseModel):
    """Tabla estructurada extraída del documento."""
    columns: List[str]
    rows: List[Dict[str, Any]]
    quality: float = 0.0
    row_count: int = 0
    doc_type_hint: Optional[str] = None

class ProcessMeta(BaseModel):
    pages_processed: int
    ocr_engine: str
    pipeline_version: str
    model_version: str
    processing_ms: int
    tables_found: int = 0

class ProcessResponse(BaseModel):
    document_id: str
    status: str
    document_type: str
    confidence: float
    fields: List[DocumentField]
    tables: List[ExtractedTable] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    meta: ProcessMeta
    ocr_text: Optional[str] = None
    ocr_boxes: Optional[List[dict]] = None
