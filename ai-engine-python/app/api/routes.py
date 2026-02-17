from fastapi import APIRouter, UploadFile, File, Form, Header, HTTPException, Depends, Query
from app.schemas.process import ProcessResponse
from app.services.document_processor import process_document
from app.services.online_learning import get_online_learning_stats
from app.core.config import settings

router = APIRouter()


async def verify_api_key(x_api_key: str | None = Header(None, alias="X-Api-Key")):
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")

@router.post("/process-document", dependencies=[Depends(verify_api_key)])
async def process_document_endpoint(
    file: UploadFile = File(...),
    document_id: str = Form(...),
    source: str = Form("web"),
    options: str | None = Form(None),
) -> ProcessResponse:
    payload = await process_document(file, document_id=document_id, source=source, options=options)
    return payload


@router.get("/online-learning/stats", dependencies=[Depends(verify_api_key)])
async def online_learning_stats_endpoint(
    recent: int = Query(default=10, ge=0, le=100),
):
    return get_online_learning_stats(recent=recent)
