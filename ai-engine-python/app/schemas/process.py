from pydantic import BaseModel, Field
from typing import List, Optional

class FieldSource(BaseModel):
    page: int
    bbox: List[int]

class DocumentField(BaseModel):
    key: str
    label: str
    value: Optional[str]
    confidence: float
    valid: bool
    validation_errors: List[str] = Field(default_factory=list)
    source: Optional[FieldSource] = None

class ProcessMeta(BaseModel):
    pages_processed: int
    ocr_engine: str
    pipeline_version: str
    model_version: str
    processing_ms: int

class ProcessResponse(BaseModel):
    document_id: str
    status: str
    document_type: str
    confidence: float
    fields: List[DocumentField]
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    meta: ProcessMeta
    ocr_text: Optional[str] = None
    ocr_boxes: Optional[List[dict]] = None
