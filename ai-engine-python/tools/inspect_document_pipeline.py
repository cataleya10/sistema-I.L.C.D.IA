import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.pipelines.classify import classify_document
from app.pipelines.extract import extract_fields
from app.pipelines.ocr import run_ocr
from app.pipelines.preprocess import preprocess
from app.pipelines.validate import validate_fields
from app.services.document_processor import (
    _evaluate_payroll_strict,
    _extract_payroll_canonical_table,
    _normalize_fields,
    _postprocess_fields,
)


DEFAULT_STORAGE_DIR = (
    ROOT_DIR.parent / "backend-dotnet" / "src" / "Api" / "storage"
)


class LocalUploadFile:
    def __init__(self, path: Path, filename_hint: str | None = None):
        self.path = path
        self.filename = filename_hint or path.name
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            self.content_type = "application/pdf"
        elif suffix == ".png":
            self.content_type = "image/png"
        elif suffix in {".jpg", ".jpeg"}:
            self.content_type = "image/jpeg"
        else:
            self.content_type = "application/octet-stream"

    async def read(self) -> bytes:
        return self.path.read_bytes()


def _resolve_file_path(
    file_path: str | None,
    document_id: str | None,
    storage_dir: Path,
) -> Path:
    if file_path:
        resolved = Path(file_path).expanduser().resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"No existe el archivo: {resolved}")
        return resolved

    if not document_id:
        raise ValueError("Debes enviar --file o --document-id.")

    for ext in (".pdf", ".png", ".jpg", ".jpeg"):
        candidate = storage_dir / f"{document_id}{ext}"
        if candidate.exists():
            return candidate.resolve()

    raise FileNotFoundError(
        f"No se encontro un archivo para document_id={document_id} en {storage_dir}"
    )


def _safe_json_loads(raw_value: str | None):
    text = str(raw_value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _truncate(value, limit: int = 500) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _preview_rows(rows, limit: int = 3):
    if not isinstance(rows, list):
        return []
    return rows[:limit]


def _field_summary(field: dict) -> dict:
    return {
        "key": field.get("key"),
        "label": field.get("label"),
        "confidence": field.get("confidence"),
        "valid": field.get("valid"),
        "value_preview": _truncate(field.get("value"), 220),
    }


def _table_summary(payload: dict | None) -> dict | None:
    if not isinstance(payload, dict):
        return None

    table = payload.get("table") if isinstance(payload.get("table"), dict) else {}
    mapped_fields = payload.get("mapped_fields")
    if not isinstance(mapped_fields, dict) and isinstance(table, dict):
        mapped_fields = table.get("mapped_fields")

    return {
        "source": payload.get("source"),
        "bank": payload.get("bank") or table.get("bank"),
        "row_count": payload.get("row_count") or table.get("row_count"),
        "canonical_row_count": payload.get("canonical_row_count")
        or table.get("canonical_row_count"),
        "validation_warnings": payload.get("validation_warnings"),
        "mapped_fields": mapped_fields,
        "quality_report": payload.get("quality_report"),
        "rows_preview": _preview_rows(payload.get("rows") or table.get("rows")),
        "canonical_preview": _preview_rows(
            payload.get("canonical_rows") or table.get("canonical_rows")
        ),
        "metadata": payload.get("metadata") or table.get("metadata"),
    }


async def inspect_document(
    file_path: Path,
    filename_hint: str | None = None,
) -> dict:
    upload = LocalUploadFile(file_path, filename_hint=filename_hint)
    preprocess_result = await preprocess(upload)

    text_layer_boxes: list[dict] = []
    pdf_tables: list[list[list[str]]] = []
    table_cell_grids: list = []
    if isinstance(preprocess_result, tuple) and len(preprocess_result) >= 5:
        images, extracted_text, text_layer_boxes, pdf_tables, table_cell_grids = preprocess_result
    elif isinstance(preprocess_result, tuple) and len(preprocess_result) >= 4:
        images, extracted_text, text_layer_boxes, pdf_tables = preprocess_result
    else:
        images, extracted_text = preprocess_result

    ocr_text = ""
    ocr_boxes = []
    ocr_engine = "none"
    if images:
        ocr_text, ocr_boxes = await run_ocr(images)
        if extracted_text:
            ocr_text = f"{ocr_text}\n{extracted_text}".strip() if ocr_text else extracted_text
        ocr_engine = "ocr"
    else:
        ocr_text = extracted_text
        ocr_boxes = text_layer_boxes
        ocr_engine = "text-layer-fastpath"

    doc_type, doc_confidence = await classify_document(
        images[0] if images else None,
        ocr_text or extracted_text,
        upload.filename,
    )
    extraction_boxes = ocr_boxes if ocr_boxes else text_layer_boxes
    fields = await extract_fields(
        doc_type,
        ocr_text or extracted_text,
        extraction_boxes,
        extracted_text,
        upload.filename,
        pdf_tables,
    )
    fields = await validate_fields(fields)
    fields = _normalize_fields(doc_type, fields)
    fields = _postprocess_fields(doc_type, fields)

    field_map = {str(field.get("key", "")): field for field in fields}
    tabla_payload = _safe_json_loads(field_map.get("tabla_celdas", {}).get("value"))
    detail_payload = _safe_json_loads(field_map.get("pago_detalle", {}).get("value"))
    payroll_table = _extract_payroll_canonical_table(fields)
    strict_warnings, strict_hard_fail = _evaluate_payroll_strict(fields, doc_type)

    return {
        "file_path": str(file_path),
        "filename_used": upload.filename,
        "preprocess": {
            "images": len(images),
            "extracted_text_len": len(extracted_text or ""),
            "text_layer_boxes": len(text_layer_boxes or []),
            "pdf_tables": len(pdf_tables or []),
            "table_cell_grids": len(table_cell_grids or []),
            "text_preview": _truncate(extracted_text, 1200),
        },
        "pipeline": {
            "ocr_engine": ocr_engine,
            "doc_type": doc_type,
            "doc_confidence": doc_confidence,
            "field_count": len(fields),
            "field_keys": [field.get("key") for field in fields],
        },
        "fields": [_field_summary(field) for field in fields],
        "tabla_celdas": _table_summary(tabla_payload),
        "pago_detalle": _table_summary(detail_payload),
        "payroll_strict": {
            "has_canonical_table": bool(payroll_table),
            "warnings": strict_warnings,
            "hard_fail": strict_hard_fail,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspecciona el pipeline de extraccion para un PDF/imagen real."
    )
    parser.add_argument("--file", help="Ruta completa al archivo a inspeccionar.")
    parser.add_argument(
        "--document-id",
        help="GUID del documento guardado en storage; se buscara por extension conocida.",
    )
    parser.add_argument(
        "--storage-dir",
        default=str(DEFAULT_STORAGE_DIR),
        help="Directorio de storage donde buscar document_id.",
    )
    parser.add_argument(
        "--filename-hint",
        help="Nombre original opcional para clasificacion basada en nombre.",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Imprime solo JSON sin resumen adicional.",
    )
    return parser


async def _async_main(args: argparse.Namespace) -> int:
    file_path = _resolve_file_path(
        file_path=args.file,
        document_id=args.document_id,
        storage_dir=Path(args.storage_dir).expanduser().resolve(),
    )
    result = await inspect_document(file_path, filename_hint=args.filename_hint)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
