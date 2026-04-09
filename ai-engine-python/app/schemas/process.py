"""
Schemas del contrato público de la API de extracción.

Contrato v2 (formato uniforme)
───────────────────────────────
ProcessResponse   — respuesta del endpoint /process-document
CampoExtraido     — campo individual extraído
TablaExtraida     — tabla estructurada
MetadataDocumento — metadatos del procesamiento
ValidationSummary — resumen de calidad y cobertura

Modelos internos (para uso en document_processor.py)
──────────────────────────────────────────────────────
DocumentField, ExtractedTable, ProcessMeta  (sin cambio de interfaz)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# CONTRATO PÚBLICO v2
# ─────────────────────────────────────────────────────────────────────────────

class CampoExtraido(BaseModel):
    """Campo individual extraído del documento."""
    key: str
    label: str
    value: Optional[Any] = None
    confidence: float = 0.0
    is_critical: bool = False
    is_valid: bool = True


class TablaExtraida(BaseModel):
    """Tabla estructurada extraída del documento."""
    name: str = "tabla_principal"
    headers_detected: List[str] = Field(default_factory=list)
    rows: List[List[str]] = Field(default_factory=list)
    canonical_rows: List[Dict[str, Any]] = Field(default_factory=list)


class MetadataDocumento(BaseModel):
    """Metadatos del procesamiento del documento."""
    filename: str = ""
    pages: int = 0
    source: str = "web"
    processing_time_ms: int = 0
    ocr_engine: str = "none"
    pipeline_version: str = ""
    model_version: str = ""


class ValidationSummary(BaseModel):
    """Resumen de calidad y cobertura de campos críticos.

    score_decision:
        "accepted"  — critical_coverage >= 0.9, sin campos inválidos
        "review"    — critical_coverage entre 0.7 y 0.89, requiere revisión humana
        "reprocess" — critical_coverage < 0.7, se recomienda reprocesar
    """
    coverage: float = 0.0               # % de campos poblados vs total esperado
    critical_coverage: float = 0.0      # % de campos críticos encontrados
    requires_review: bool = False        # True si el doc necesita revisión humana
    score_decision: str = "accepted"     # "accepted" | "review" | "reprocess"
    table_quality_score: float = 0.0    # Calidad de la mejor tabla (escala 0-100)


class ProcessResponse(BaseModel):
    """Respuesta estándar del servicio de extracción.

    Formato uniforme consumible por C# y el frontend.

    Ejemplo (éxito):
        {
          "document_id": "doc-001",
          "tipo_documento": "FACTURA",
          "success": true,
          "message": "Documento procesado correctamente",
          "confidence_global": 0.91,
          "campos": [...],
          "tablas": [...],
          "metadata": {...},
          "validation_summary": {...}
        }

    Ejemplo (error):
        {
          "document_id": "doc-001",
          "tipo_documento": "UNKNOWN",
          "success": false,
          "message": "No se detectó texto en el documento",
          "error_code": "OCR_FAILED",
          "stage": "ocr",
          ...
        }
    """
    document_id: str
    tipo_documento: str
    success: bool = True
    message: str = ""
    confidence_global: float = 0.0
    campos: List[CampoExtraido] = Field(default_factory=list)
    tablas: List[TablaExtraida] = Field(default_factory=list)
    metadata: MetadataDocumento = Field(default_factory=MetadataDocumento)
    validation_summary: ValidationSummary = Field(default_factory=ValidationSummary)
    # Advertencias y errores (para auditoría / debug)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    # Presentes cuando hay cualquier condición notable (success=True o False)
    # None solo cuando el documento fue procesado sin problemas
    error_code: Optional[str] = None
    stage: Optional[str] = None
    # Opcionales: devueltos solo si el caller lo pide explícitamente
    ocr_text: Optional[str] = None
    ocr_boxes: Optional[List[dict]] = None


# ─────────────────────────────────────────────────────────────────────────────
# MODELOS INTERNOS (backward-compat, usados en document_processor.py)
# ─────────────────────────────────────────────────────────────────────────────

class FieldSource(BaseModel):
    page: int
    bbox: List[int]


class DocumentField(BaseModel):
    """Campo extraído — modelo interno antes de la conversión al contrato v2."""
    key: str
    label: str
    value: Optional[Any] = None
    confidence: float = 0.0
    valid: bool = True
    validation_errors: List[str] = Field(default_factory=list)
    source: Optional[FieldSource] = None


class ExtractedTable(BaseModel):
    """Tabla canónica — modelo interno antes de la conversión al contrato v2."""
    columns: List[str]
    rows: List[Dict[str, Any]]
    quality: float = 0.0
    row_count: int = 0
    doc_type_hint: Optional[str] = None


class ProcessMeta(BaseModel):
    """Metadatos de procesamiento — modelo interno."""
    pages_processed: int
    ocr_engine: str
    pipeline_version: str
    model_version: str
    processing_ms: int
    tables_found: int = 0
