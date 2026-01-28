import json
import time
from app.schemas.process import ProcessResponse, DocumentField, ProcessMeta
from app.core.config import settings
from app.pipelines.preprocess import preprocess
from app.pipelines.ocr import run_ocr
from app.pipelines.classify import classify_document
from app.pipelines.extract import extract_fields
from app.pipelines.validate import validate_fields

async def process_document(file, document_id: str, source: str, options: str | None):
    start = time.time()
    options_data = {}
    if options:
        try:
            options_data = json.loads(options)
        except json.JSONDecodeError:
            options_data = {}
    image, extracted_text = await preprocess(file)
    ocr_text, ocr_boxes = await run_ocr(image)
    ocr_engine = "paddleocr" if ocr_text else "none"
    if not ocr_text and extracted_text:
        ocr_text = extracted_text
        ocr_engine = "text-layer"
    doc_type, doc_confidence = await classify_document(image, ocr_text, file.filename)
    if (ocr_text or extracted_text) and doc_type != "UNKNOWN":
        doc_confidence = 1.0
    fields = await extract_fields(doc_type, ocr_text, ocr_boxes, extracted_text, file.filename)
    fields = await validate_fields(fields)

    critical_fields = {
        "INE": ["curp"],
        "CURP": ["curp"],
        "ACTA_NACIMIENTO": ["fecha"],
        "COMPROBANTE_DOMICILIO": ["domicilio"],
        "NSS": ["nss"],
        "DATOS_BANCARIOS": ["clabe"],
        "CONSTANCIA_SITUACION_FISCAL": ["rfc"]
    }

    required = critical_fields.get(doc_type, [])
    invalid_critical = []
    for key in required:
        field = next((f for f in fields if f["key"] == key), None)
        if not field or not field.get("valid", True):
            invalid_critical.append(key)

    processing_ms = int((time.time() - start) * 1000)

    warnings: list[str] = []
    if options_data.get("return_ocr_text"):
        warnings.append("return_ocr_text no está habilitado en esta versión.")
    if options_data.get("return_boxes"):
        warnings.append("return_boxes no está habilitado en esta versión.")
    if not ocr_text:
        warnings.append("No se detectó texto. Verifica OCR o la calidad del documento.")

    status = "READY"
    if doc_confidence < 0.8 or invalid_critical:
        status = "NEEDS_REVIEW"
        if invalid_critical:
            warnings.append(f"Campos críticos inválidos: {', '.join(invalid_critical)}")

    response = ProcessResponse(
        document_id=document_id,
        status=status,
        document_type=doc_type,
        confidence=doc_confidence,
        fields=[DocumentField(**field) for field in fields],
        warnings=warnings,
        errors=[],
        meta=ProcessMeta(
            pages_processed=1,
            ocr_engine=ocr_engine,
            pipeline_version=settings.pipeline_version,
            model_version=settings.model_version,
            processing_ms=processing_ms,
        ),
    )

    return response
