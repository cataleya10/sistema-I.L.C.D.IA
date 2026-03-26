"""
Extractor Service — wrapper sobre app/pipelines/extract/orchestrator.py

Expone:
  extract_document_fields()  -- extraccion pura (sin OCR, sin classify)
  extract_for_training()     -- extraccion + metadatos (para entrenamiento)
  process_document()         -- pipeline completo: archivo -> JSON estandar

Pipeline de process_document:
  archivo -> preprocess -> classify -> (fastpath o OCR) ->
  extract -> validate -> normalize -> postprocess -> JSON

Formato de retorno de process_document:
  {
    "tipo_documento": str,
    "fields": list[dict],           # {key, label, value, confidence, valid, ...}
    "table": {
      "rows": list[list[str]],      # tabla mas grande en bruto (pdf_tables[best])
      "canonical_rows": list[dict], # filas normalizadas por columna
    },
    "metadata": {
      "filename": str,
      "page_count": int,
      "ocr_used": bool,
      "ocr_engine": str,
      "confidence": float,
      "processing_time_ms": int,
    },
    "success": bool,
    "message": str,
  }
"""

from __future__ import annotations

import io
import logging
import mimetypes
import time
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from starlette.datastructures import Headers

from app.pipelines.classify import classify_document
from app.pipelines.extract import extract_fields as _extract_fields
from app.pipelines.ocr import run_ocr
from app.pipelines.preprocess import preprocess
from app.pipelines.validate import validate_fields
from app.utils.table_utils import to_canonical_rows

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import post-process helpers from document_processor (single source of truth)
# ---------------------------------------------------------------------------
try:
    from app.services.document_processor import (  # noqa: E402
        _has_sufficient_text_layer,
        _normalize_fields as _dp_normalize,
        _postprocess_fields as _dp_postprocess,
    )
    _HAS_DP = True
except Exception:
    _HAS_DP = False
    logger.warning("document_processor helpers unavailable; skipping normalize/postprocess")

try:
    from app.core.config import settings as _settings
    _FASTPATH_TYPES: frozenset[str] = frozenset(
        getattr(_settings, "text_layer_fastpath_types", [])
    )
except Exception:
    _FASTPATH_TYPES = frozenset()

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class _FileWrapper(UploadFile):
    """✅ FIX: hereda de UploadFile para ser 100% compatible con preprocess()."""

    def __init__(self, content: bytes, filename: str) -> None:
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        super().__init__(
            filename=filename,
            file=io.BytesIO(content),  # type: ignore[arg-type]
            headers=Headers({"content-type": content_type}),
        )
        self._content = content

    async def read(self, size: int = -1) -> bytes:
        return self._content


def _unpack_preprocess(result: Any) -> tuple[list, str, list, list, list]:
    if isinstance(result, tuple):
        n = len(result)
        if n >= 5:
            return result[0], result[1], result[2], result[3], result[4]
        if n >= 4:
            return result[0], result[1], result[2], result[3], []
        if n >= 3:
            return result[0], result[1], result[2], [], []
        if n >= 2:
            return result[0], result[1], [], [], []
    return [], "", [], [], []


def _best_table(pdf_tables: list[list[list[str]]]) -> list[list[str]]:
    """Devuelve la tabla con mas filas (dato util)."""
    if not pdf_tables:
        return []
    return max(pdf_tables, key=len)


def _make_error(message: str, filename: str = "") -> dict[str, Any]:
    return {
        "tipo_documento": "UNKNOWN",
        "fields": [],
        "table": {"rows": [], "canonical_rows": []},
        "metadata": {
            "filename": filename,
            "page_count": 0,
            "ocr_used": False,
            "ocr_engine": "none",
            "confidence": 0.0,
            "processing_time_ms": 0,
        },
        "success": False,
        "message": message,
    }


# ---------------------------------------------------------------------------
# Primary API: pipeline completo
# ---------------------------------------------------------------------------

async def process_document(
    file_path: str | Path,
    filename: str | None = None,
    force_type: str | None = None,
) -> dict[str, Any]:
    """Pipeline completo: archivo -> OCR -> classify -> extract -> normalize -> JSON.

    Args:
        file_path:   Ruta absoluta o relativa al archivo (PDF o imagen).
        filename:    Nombre de archivo a usar en metadatos (por defecto: nombre de la ruta).
        force_type:  Forzar tipo de documento (ej. "FACTURA").  None = auto-detectar.

    Returns:
        Dict estandarizado con tipo_documento, fields, table, metadata, success, message.
    """
    start = time.time()
    path = Path(file_path)
    fname = filename or path.name

    try:
        content = path.read_bytes()
    except OSError as exc:
        return _make_error(f"No se pudo leer el archivo: {exc}", fname)

    wrapper = _FileWrapper(content, fname)

    # ── 1. Preprocesar (extrae texto, imagenes, tablas) ──────────────────────
    try:
        raw = await preprocess(wrapper)
    except Exception as exc:
        logger.exception("preprocess() fallo para '%s'", fname)
        return _make_error(f"Error en preprocesamiento: {exc}", fname)

    images, extracted_text, text_boxes, pdf_tables, table_cell_grids = _unpack_preprocess(raw)

    ocr_text: str = ""
    ocr_boxes: list[dict] = []
    ocr_engine: str = "none"
    doc_type: str = "UNKNOWN"
    doc_confidence: float = 0.0
    fields: list[dict] = []

    forced = force_type.strip().upper().replace("-", "_").replace(" ", "_") if force_type else None

    # ── 2. Fastpath: si existe capa de texto suficiente ──────────────────────
    if extracted_text and _HAS_DP and _has_sufficient_text_layer(extracted_text):
        ft, fc = await classify_document(None, extracted_text, fname)
        if forced:
            ft, fc = forced, max(fc, 0.9)
        if ft in _FASTPATH_TYPES:
            cands = await _extract_fields(ft, extracted_text, text_boxes, extracted_text, fname, pdf_tables)
            cands = await validate_fields(cands)
            cands = _dp_normalize(ft, cands)
            cands = _dp_postprocess(ft, cands)
            if cands:
                ocr_text = extracted_text
                ocr_engine = "text-layer-fastpath"
                doc_type = ft
                doc_confidence = max(fc, 0.85) if ft not in {"UNKNOWN", "GENERICO"} else fc
                fields = cands

    # ── 3. OCR completo si fastpath no fue suficiente ────────────────────────
    if not fields:
        try:
            ocr_text, ocr_boxes = await run_ocr(images)
        except Exception as exc:
            logger.exception("run_ocr() fallo para '%s'", fname)
            return _make_error(f"Error en OCR: {exc}", fname)

        if ocr_boxes:
            ocr_engine = str(ocr_boxes[0].get("engine") or "paddleocr")
        elif ocr_text:
            ocr_engine = "ocr"

        if extracted_text:
            ocr_text = (ocr_text + "\n" + extracted_text).strip() if ocr_text else extracted_text
            ocr_engine = ("paddleocr+text-layer" if ocr_engine not in {"ocr", "none"} else "text-layer")

        ocr_text = (ocr_text or "").replace("\u00a0", " ").replace("\t", " ")

        # Rellenar grillas img2table con boxes de OCR
        if table_cell_grids and ocr_boxes:
            try:
                from app.pipelines.preprocess import fill_grid_tables_from_ocr_boxes
                extra = fill_grid_tables_from_ocr_boxes(table_cell_grids, ocr_boxes)
                if extra:
                    pdf_tables = pdf_tables + extra
            except Exception:
                logger.debug("fill_grid_tables_from_ocr_boxes no disponible", exc_info=True)

        first_img = images[0] if images else None
        doc_type, doc_confidence = await classify_document(first_img, ocr_text, fname)
        if forced:
            doc_type, doc_confidence = forced, max(doc_confidence, 0.9)
        elif ocr_text and doc_type not in {"UNKNOWN", "GENERICO"}:
            doc_confidence = max(doc_confidence, 0.85)

        extraction_boxes = ocr_boxes if ocr_boxes else text_boxes
        try:
            fields = await _extract_fields(doc_type, ocr_text, extraction_boxes, extracted_text, fname, pdf_tables)
            fields = await validate_fields(fields)
        except Exception as exc:
            logger.exception("extract/validate fallo para '%s'", fname)
            return _make_error(f"Error en extraccion: {exc}", fname)

        if _HAS_DP:
            fields = _dp_normalize(doc_type, fields)
            fields = _dp_postprocess(doc_type, fields)

    # ── 4. Tabla: tomar la mejor tabla de pdf_tables ─────────────────────────
    best_rows = _best_table(pdf_tables)
    try:
        canonical_rows = to_canonical_rows(best_rows) if best_rows else []
    except Exception:
        logger.debug("to_canonical_rows fallo", exc_info=True)
        canonical_rows = []

    elapsed_ms = int((time.time() - start) * 1000)
    return {
        "tipo_documento": doc_type,
        "fields": fields,
        "table": {
            "rows": best_rows,
            "canonical_rows": canonical_rows,
        },
        "metadata": {
            "filename": fname,
            "page_count": len(images),
            "ocr_used": ocr_engine not in {"none", "text-layer-fastpath"},
            "ocr_engine": ocr_engine,
            "confidence": round(doc_confidence, 4),
            "processing_time_ms": elapsed_ms,
        },
        "success": True,
        "message": "",
    }


# ---------------------------------------------------------------------------
# Lower-level helpers (backward-compatible)
# ---------------------------------------------------------------------------

async def extract_document_fields(
    document_type: str,
    ocr_text: str,
    ocr_boxes: list[dict] | None = None,
    raw_text: str = "",
    filename: str | None = None,
    pdf_tables: list[list[list[str]]] | None = None,
) -> list[dict[str, Any]]:
    """Extrae campos estructurados de un documento segun su tipo.

    Recibe texto+boxes ya procesados (sin OCR interno).  Para el pipeline
    completo desde un archivo usa process_document().

    Returns:
        Lista de campos extraidos: [{key, label, value, confidence, valid, ...}]
    """
    return await _extract_fields(
        document_type=document_type,
        ocr_text=ocr_text,
        ocr_boxes=ocr_boxes,
        raw_text=raw_text,
        filename=filename,
        pdf_tables=pdf_tables,
    )


async def extract_for_training(
    document_type: str,
    ocr_text: str,
    ocr_boxes: list[dict] | None = None,
    raw_text: str = "",
    filename: str | None = None,
    pdf_tables: list[list[list[str]]] | None = None,
) -> dict[str, Any]:
    """Variante de extraccion para el pipeline de entrenamiento.

    Returns:
        {
          "document_type": str,
          "filename": str | None,
          "fields": list[dict],
          "field_count": int,
          "extracted_keys": list[str],
        }
    """
    fields = await _extract_fields(
        document_type=document_type,
        ocr_text=ocr_text,
        ocr_boxes=ocr_boxes,
        raw_text=raw_text,
        filename=filename,
        pdf_tables=pdf_tables,
    )
    return {
        "document_type": document_type,
        "filename": filename,
        "fields": fields,
        "field_count": len(fields),
        "extracted_keys": [f.get("key") for f in fields if f.get("key")],
    }
