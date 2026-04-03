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
from app.utils.table_utils import (
    to_canonical_rows,
    remap_to_target_payment_schema,
    table_quality_score,
)
from app.pipelines.table_postprocess import postprocess_payment_table

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


# Tipos de documento que usan el pipeline de pago (postprocess + remap a esquema bancario)
_PAYMENT_DOC_TYPES: frozenset[str] = frozenset({
    "DATOS_BANCARIOS",
    "COMPROBANTE_DE_PAGO",
    "NOMINA",
    "ESTADO_DE_CUENTA",
})

# Tipos bancarios donde aplica el geometric detector + extractor especializado
_BANK_REMAP_DOC_TYPES: frozenset[str] = frozenset({
    "DATOS_BANCARIOS",
    "COMPROBANTE_DE_PAGO",
    "ESTADO_DE_CUENTA",
})


def _detect_bank_from_fields(fields: list[dict]) -> str:
    """Extrae el nombre del banco desde los campos extraídos.

    Revisa múltiples claves en orden de precisión: banco > banco_receptor >
    titular (cuando contiene nombre de banco).  Devuelve string vacío si no
    se encuentra ninguno.
    """
    _BANK_KEY_PRIORITY = ("banco", "banco_receptor", "banco_destino", "institucion")
    field_map = {f.get("key"): f for f in fields if f.get("value")}
    for key in _BANK_KEY_PRIORITY:
        f = field_map.get(key)
        if f:
            return str(f["value"]).upper().strip()
    return ""


def _table_content_sig(cols: list[str], rows: list[dict]) -> str:
    """Firma de contenido para deduplicar tablas equivalentes.

    Combina encabezados + número de filas + contenido de la primera fila.
    """
    header = "|".join(cols[:10])
    row_count = len(rows)
    sample = ""
    if rows:
        sample = "|".join(str(v)[:25].upper() for v in list(rows[0].values())[:5])
    return f"{header}::{row_count}::{sample}"


def _process_all_tables(
    pdf_tables: list[list[list[str]]],
    doc_type: str,
    bank: str = "",
    ocr_boxes: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """Procesa TODAS las tablas detectadas en el documento.

    Para cada tabla raw de pdf_tables:
      1. to_canonical_rows  — encabezado + columnas canónicas + limpieza básica
      2. postprocess_payment_table (solo docs de pago) — pandas cleaning + split merged rows
      3. remap_to_target_payment_schema (solo docs de pago) — esquema por banco
      4. table_quality_score — puntaje de calidad

    Returns lista de dicts ordenada por calidad descendente. Cada dict:
      {index, columns, display_columns, rows, canonical_rows, row_count, quality, avg_fill_rate}
    """
    is_payment = doc_type in _PAYMENT_DOC_TYPES
    is_bank = doc_type in _BANK_REMAP_DOC_TYPES
    results: list[dict[str, Any]] = []
    seen_sigs: set[str] = set()

    # ── Ruta 1: Geometric detector + extractor por banco ─────────────────────
    if is_bank and ocr_boxes:
        try:
            from app.pipelines.extract.geometric_detector import detect_all_table_grids
            from app.pipelines.extract.bank_extractors import get_bank_extractor

            grids = detect_all_table_grids(ocr_boxes)
            extractor = get_bank_extractor(bank)

            for grid in grids:
                if grid.n_rows < 2:
                    continue
                try:
                    geo_cols, geo_rows = extractor.extract(grid)
                except Exception:
                    logger.debug("bank_extractor.extract falló (extractor_service)", exc_info=True)
                    geo_cols, geo_rows = [], []

                if not geo_cols or not geo_rows:
                    continue

                quality_info = table_quality_score(geo_cols, geo_rows)
                quality = quality_info.get("quality", 0)
                sig = _table_content_sig(geo_cols, geo_rows)
                if sig in seen_sigs:
                    continue
                seen_sigs.add(sig)

                display = {c: c.replace("_", " ").upper() for c in geo_cols}
                results.append({
                    "index": len(results),
                    "columns": geo_cols,
                    "display_columns": display,
                    "rows": grid.to_raw_table(),
                    "canonical_rows": geo_rows,
                    "row_count": len(geo_rows),
                    "quality": quality,
                    "avg_fill_rate": quality_info.get("avg_fill_rate", 0.0),
                })

            if results:
                results.sort(key=lambda t: (t["quality"], t["row_count"]), reverse=True)
                logger.info(
                    "_process_all_tables [%s] via geometric+bank: %d tablas",
                    doc_type, len(results),
                )
                return results
        except Exception:
            logger.debug("Pipeline geométrico-bancario falló (extractor_service)", exc_info=True)

    # ── Ruta 2: Canonicalización genérica ────────────────────────────────────
    if not pdf_tables:
        return []

    for i, raw_table in enumerate(pdf_tables):
        # Tabla mínimamente válida: al menos encabezado + 1 fila de datos
        if not raw_table or len(raw_table) < 2:
            continue
        try:
            # ── Paso 1: canonicalizar ────────────────────────────────────────
            # to_canonical_rows ya incluye: detección de encabezado,
            # unificación de columnas, reconstrucción de filas fragmentadas,
            # drop de vacías/totales, deduplicación y normalización de importes.
            canon_cols, canon_rows = to_canonical_rows(raw_table)
            if not canon_rows:
                continue

            # ── Paso 2: postprocess de pago (pandas + split merged rows) ─────
            if is_payment:
                try:
                    canon_cols, canon_rows = postprocess_payment_table(
                        canon_cols, canon_rows, bank=bank
                    )
                except Exception:
                    logger.debug(
                        "_process_all_tables: postprocess_payment_table fallo tabla %d", i,
                        exc_info=True,
                    )

            # ── Paso 3: remap a esquema bancario destino ─────────────────────
            if is_payment:
                try:
                    target_cols, final_rows, display = remap_to_target_payment_schema(
                        canon_cols, canon_rows, bank=bank
                    )
                except Exception:
                    logger.debug(
                        "_process_all_tables: remap_to_target_payment_schema fallo tabla %d", i,
                        exc_info=True,
                    )
                    target_cols, final_rows = canon_cols, canon_rows
                    display = {c: c.replace("_", " ").upper() for c in canon_cols}
            else:
                target_cols, final_rows = canon_cols, canon_rows
                display = {c: c.replace("_", " ").upper() for c in canon_cols}

            # ── Paso 4: gate de calidad ──────────────────────────────────────
            quality_info = table_quality_score(target_cols, final_rows)
            quality = quality_info.get("quality", 0)

            # Descartar tablas con muy baja calidad (casi vacías o basura OCR)
            if quality < 15 and len(final_rows) < 2:
                logger.debug(
                    "_process_all_tables: tabla %d descartada quality=%d rows=%d",
                    i, quality, len(final_rows),
                )
                continue

            # ── Paso 5: deduplicación por contenido ──────────────────────────
            sig = _table_content_sig(target_cols, final_rows)
            if sig in seen_sigs:
                logger.debug(
                    "_process_all_tables: tabla %d descartada (duplicado de contenido)", i
                )
                continue
            seen_sigs.add(sig)

            results.append({
                "index": i,
                "columns": target_cols,
                "display_columns": display,
                "rows": raw_table,
                "canonical_rows": final_rows,
                "row_count": len(final_rows),
                "quality": quality,
                "avg_fill_rate": quality_info.get("avg_fill_rate", 0.0),
            })

        except Exception:
            logger.debug(
                "_process_all_tables: fallo procesando tabla %d", i, exc_info=True
            )

    # Ordenar por calidad descendente; empate: más filas primero
    results.sort(key=lambda t: (t["quality"], t["row_count"]), reverse=True)
    logger.info(
        "_process_all_tables [%s]: %d tablas raw → %d procesadas (quality gate + dedup aplicados)",
        doc_type, len(pdf_tables), len(results),
    )
    return results


def _make_error(message: str, filename: str = "") -> dict[str, Any]:
    return {
        "tipo_documento": "UNKNOWN",
        "fields": [],
        "table": {"rows": [], "canonical_rows": [], "columns": [], "display_columns": {}, "row_count": 0, "quality": 0},
        "tables": [],
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
    extraction_boxes: list[dict] = []  # disponible para _process_all_tables independientemente del path

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

    # ── 4. Tablas: procesar TODAS las tablas detectadas ──────────────────────
    bank = _detect_bank_from_fields(fields)
    all_tables = _process_all_tables(pdf_tables, doc_type, bank=bank, ocr_boxes=extraction_boxes)

    # Tabla principal = la de mayor calidad (backward compat con backend C#)
    best = all_tables[0] if all_tables else None

    elapsed_ms = int((time.time() - start) * 1000)
    return {
        "tipo_documento": doc_type,
        "fields": fields,
        # tabla principal — estructura compatible con versión anterior
        "table": {
            "rows": best["rows"] if best else [],
            "canonical_rows": best["canonical_rows"] if best else [],
            "columns": best["columns"] if best else [],
            "display_columns": best["display_columns"] if best else {},
            "row_count": best["row_count"] if best else 0,
            "quality": best["quality"] if best else 0,
        },
        # todas las tablas — nueva clave para el backend
        "tables": [
            {
                "index": t["index"],
                "columns": t["columns"],
                "display_columns": t["display_columns"],
                "canonical_rows": t["canonical_rows"],
                "row_count": t["row_count"],
                "quality": t["quality"],
                "avg_fill_rate": t["avg_fill_rate"],
            }
            for t in all_tables
        ],
        "metadata": {
            "filename": fname,
            "page_count": len(images),
            "ocr_used": ocr_engine not in {"none", "text-layer-fastpath"},
            "ocr_engine": ocr_engine,
            "confidence": round(doc_confidence, 4),
            "processing_time_ms": elapsed_ms,
            "tables_found": len(all_tables),
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
