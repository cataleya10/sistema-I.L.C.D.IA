import json
import secrets

from fastapi import APIRouter, UploadFile, File, Form, Header, HTTPException, Depends, Query, Response
from app.schemas.process import ProcessResponse
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

@router.post("/process-document", dependencies=[Depends(verify_api_key)])
async def process_document_endpoint(
    file: UploadFile = File(...),
    document_id: str = Form(...),
    source: str = Form("web"),
    options: str | None = Form(None),
    original_filename: str | None = Form(None),
) -> ProcessResponse:
    # Use original filename from .NET so filename-based classification works
    # (file.filename arrives as a temp path like a GUID otherwise)
    if original_filename:
        file.filename = original_filename
    payload = await process_document(file, document_id=document_id, source=source, options=options)
    return payload


@router.post("/diagnostics/audit-folder", dependencies=[Depends(verify_api_key)], response_model=AuditFolderResponse)
async def audit_folder_endpoint(payload: AuditFolderRequest):
    try:
        return await run_audit_folder(
            payload.folder_path,
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
