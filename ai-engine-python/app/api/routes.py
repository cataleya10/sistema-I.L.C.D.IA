import json
import os
import secrets
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, Header, HTTPException, Depends, Query, Response
from app.schemas.process import ProcessResponse  # contrato v2 unificado
from app.schemas.audit import AuditFolderRequest, AuditFolderResponse
from app.schemas.online_learning import OnlineLearningFeedbackRequest, OnlineLearningRetrainRequest
from app.services.document_processor import process_document, export_table_to_csv_excel
from app.services.document_audit import audit_folder as run_audit_folder
from app.services.online_learning import (
    get_online_learning_stats,
    get_precision_metrics,
    record_feedback_document,
    run_feedback_retraining,
)
from app.core.config import settings

router = APIRouter()


async def verify_api_key(x_api_key: str | None = Header(None, alias="X-Api-Key")):
    if settings.api_key:
        if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
            raise HTTPException(status_code=401, detail="Invalid API key")

_DOCUMENT_ID_RE = __import__("re").compile(r"^[a-zA-Z0-9_\-]{1,64}$")

@router.post("/process-document", dependencies=[Depends(verify_api_key)])
async def process_document_endpoint(
    file: UploadFile = File(...),
    document_id: str = Form(...),
    source: str = Form("web"),
    options: str | None = Form(None),
    original_filename: str | None = Form(None),
) -> ProcessResponse:
    # Validar document_id: solo alfanumérico + guiones, máx 64 chars
    if not _DOCUMENT_ID_RE.match(document_id):
        raise HTTPException(status_code=422, detail="document_id inválido: solo letras, números, guiones y guiones bajos (máx 64 chars)")
    # Validar options: debe ser JSON válido si se proporciona
    if options is not None:
        if len(options) > 2048:
            raise HTTPException(status_code=422, detail="options excede el tamaño permitido (máx 2048 chars)")
        try:
            json.loads(options)
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="options debe ser JSON válido")
    # Use original filename from .NET so filename-based classification works
    if original_filename:
        file.filename = original_filename
    payload = await process_document(file, document_id=document_id, source=source, options=options)
    return payload


@router.post("/diagnostics/audit-folder", dependencies=[Depends(verify_api_key)], response_model=AuditFolderResponse)
async def audit_folder_endpoint(payload: AuditFolderRequest):
    # Path traversal guard: folder_path must stay inside AUDIT_BASE_PATH.
    base = Path(settings.audit_base_path).resolve()
    req = Path(payload.folder_path)
    target = req if req.is_absolute() else (base / req)
    try:
        target = target.resolve()
        target.relative_to(base)  # raises ValueError if outside base
    except ValueError:
        raise HTTPException(status_code=403, detail="Acceso denegado: ruta fuera del directorio permitido")
    except Exception:
        raise HTTPException(status_code=400, detail="Ruta inválida")
    try:
        return await run_audit_folder(
            str(target),
            recurse=payload.recurse,
            limit=payload.limit,
            issues_only=payload.issues_only,
        )
    except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/online-learning/stats", dependencies=[Depends(verify_api_key)])
async def online_learning_stats_endpoint(
    recent: int = Query(default=10, ge=0, le=100),
):
    return get_online_learning_stats(recent=recent)


@router.post("/online-learning/feedback", dependencies=[Depends(verify_api_key)])
async def online_learning_feedback_endpoint(payload: OnlineLearningFeedbackRequest):
    corrected = {item.key: item.value for item in payload.corrected_fields}
    return record_feedback_document(
        document_id=payload.document_id,
        document_type=payload.document_type,
        ocr_text=payload.ocr_text,
        corrected_labels=corrected,
        extracted_fields=payload.extracted_fields,
        reviewer=payload.reviewer,
        source=payload.source,
    )


@router.post("/online-learning/retrain", dependencies=[Depends(verify_api_key)])
async def online_learning_retrain_endpoint(payload: OnlineLearningRetrainRequest):
    return run_feedback_retraining(
        min_feedback_samples=payload.min_feedback_samples,
        validation_ratio=payload.validation_ratio,
        min_doc_accuracy=payload.min_doc_accuracy,
        min_validation_docs=payload.min_validation_docs,
        max_accuracy_drop=payload.max_accuracy_drop,
        promote=payload.promote,
    )


@router.get("/health")
async def health_endpoint():
    return {
        "status": "ok",
        "version": settings.pipeline_version,
    }


@router.get("/metrics", dependencies=[Depends(verify_api_key)])
async def metrics_endpoint():
    return get_precision_metrics()


@router.post("/export-table", dependencies=[Depends(verify_api_key)])
async def export_table_endpoint(
    columns: list[str] = Form(...),
    rows: str = Form(...),  # JSON stringified list of dicts
    format: str = Form("csv"),
):
    try:
        rows_data = json.loads(rows)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid rows format")
    csv_str, excel_bytes = export_table_to_csv_excel(columns, rows_data)
    if format == "csv":
        return Response(content=csv_str, media_type="text/csv")
    elif format == "excel":
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        raise HTTPException(status_code=400, detail="Invalid format")
