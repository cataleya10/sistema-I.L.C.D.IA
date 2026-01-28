from fastapi import APIRouter, UploadFile, File, Form
from app.schemas.process import ProcessResponse
from app.services.document_processor import process_document

router = APIRouter()

@router.post("/process-document", response_model=ProcessResponse)
async def process_document_endpoint(
    file: UploadFile = File(...),
    document_id: str = Form(...),
    source: str = Form("web"),
    options: str | None = Form(None),
):
    payload = await process_document(file, document_id=document_id, source=source, options=options)
    return payload
