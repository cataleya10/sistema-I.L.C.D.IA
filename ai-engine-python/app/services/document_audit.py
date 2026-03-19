from __future__ import annotations

from collections import Counter
from pathlib import Path

from tools.inspect_document_pipeline import inspect_document


_AUDIT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


def _iter_audit_files(folder_path: Path, recurse: bool) -> list[Path]:
    iterator = folder_path.rglob("*") if recurse else folder_path.glob("*")
    files = [
        path.resolve()
        for path in iterator
        if path.is_file() and path.suffix.lower() in _AUDIT_EXTENSIONS
    ]
    files.sort(key=lambda item: str(item).lower())
    return files


def _gather_warnings(result: dict) -> list[str]:
    tabla = result.get("tabla_celdas") or {}
    detalle = result.get("pago_detalle") or {}
    strict = result.get("payroll_strict") or {}
    warnings: list[str] = []
    warnings.extend(str(strict_warning) for strict_warning in (strict.get("warnings") or []))
    warnings.extend(str(tabla_warning) for tabla_warning in (tabla.get("validation_warnings") or []))
    warnings.extend(str(detalle_warning) for detalle_warning in (detalle.get("validation_warnings") or []))
    return warnings


def _pick_mapped_fields(result: dict) -> dict[str, str]:
    tabla = result.get("tabla_celdas") or {}
    detalle = result.get("pago_detalle") or {}
    mapped = tabla.get("mapped_fields") or detalle.get("mapped_fields") or {}
    if not isinstance(mapped, dict):
        return {}
    return {str(key): str(value) for key, value in mapped.items() if value not in {"", None}}


def _summarize_document_result(result: dict) -> dict:
    pipeline = result.get("pipeline") or {}
    tabla = result.get("tabla_celdas") or {}
    detalle = result.get("pago_detalle") or {}
    strict = result.get("payroll_strict") or {}
    warnings = _gather_warnings(result)
    document_type = str(pipeline.get("doc_type") or "")
    hard_fail = bool(strict.get("hard_fail"))
    has_issue = bool(warnings or hard_fail or document_type != "FACTURA")
    return {
        "name": Path(str(result.get("file_path") or "")).name,
        "file_path": str(result.get("file_path") or ""),
        "status": "issue" if has_issue else "clean",
        "document_type": document_type or None,
        "confidence": float(pipeline.get("doc_confidence") or 0),
        "tabla_rows": int(tabla.get("canonical_row_count") or 0),
        "detalle_rows": int(detalle.get("canonical_row_count") or 0),
        "warning_count": len(warnings),
        "warnings": warnings,
        "hard_fail": hard_fail,
        "mapped_fields": _pick_mapped_fields(result),
        "error": None,
    }


async def audit_folder(
    folder_path: str | Path,
    *,
    recurse: bool = True,
    limit: int = 100,
    issues_only: bool = False,
) -> dict:
    resolved_folder = Path(folder_path).expanduser().resolve()
    if not resolved_folder.exists():
        raise FileNotFoundError(f"No existe la carpeta: {resolved_folder}")
    if not resolved_folder.is_dir():
        raise NotADirectoryError(f"La ruta no es una carpeta: {resolved_folder}")

    matched_files = _iter_audit_files(resolved_folder, recurse=recurse)
    selected_files = matched_files[:limit]
    type_counts: Counter[str] = Counter()
    clean_count = 0
    issue_count = 0
    error_count = 0
    hard_fail_count = 0
    non_factura_count = 0
    documents: list[dict] = []

    for file_path in selected_files:
        try:
            inspection = await inspect_document(file_path)
            summary = _summarize_document_result(inspection)
        except Exception as exc:
            summary = {
                "name": file_path.name,
                "file_path": str(file_path),
                "status": "error",
                "document_type": None,
                "confidence": None,
                "tabla_rows": 0,
                "detalle_rows": 0,
                "warning_count": 0,
                "warnings": [],
                "hard_fail": False,
                "mapped_fields": {},
                "error": f"{type(exc).__name__}: {exc}",
            }

        document_type = str(summary.get("document_type") or "")
        if document_type:
            type_counts[document_type] += 1

        if summary["status"] == "error":
            error_count += 1
        elif summary["status"] == "clean":
            clean_count += 1
        else:
            issue_count += 1

        if summary.get("hard_fail"):
            hard_fail_count += 1
        if document_type and document_type != "FACTURA":
            non_factura_count += 1

        if not issues_only or summary["status"] != "clean":
            documents.append(summary)

    return {
        "folder_path": str(resolved_folder),
        "recurse": recurse,
        "limit": limit,
        "issues_only": issues_only,
        "matched_files": len(matched_files),
        "processed_files": len(selected_files),
        "documents_returned": len(documents),
        "clean_count": clean_count,
        "issue_count": issue_count,
        "error_count": error_count,
        "hard_fail_count": hard_fail_count,
        "non_factura_count": non_factura_count,
        "document_type_counts": dict(sorted(type_counts.items())),
        "documents": documents,
    }
