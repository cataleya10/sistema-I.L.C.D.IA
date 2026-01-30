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

    images, extracted_text = await preprocess(file)
    ocr_text, ocr_boxes = await run_ocr(images)
    ocr_engine = "paddleocr" if ocr_text else "none"
    if extracted_text:
        if not ocr_text:
            ocr_text = extracted_text
            ocr_engine = "text-layer"
        else:
            ocr_text = f"{ocr_text}\n{extracted_text}"
            ocr_engine = "paddleocr+text-layer"

    if ocr_text:
        ocr_text = ocr_text.replace("\u00a0", " ").replace("\t", " ")
    first_image = images[0] if images else None
    doc_type, doc_confidence = await classify_document(first_image, ocr_text, file.filename)
    if (ocr_text or extracted_text) and doc_type != "UNKNOWN":
        doc_confidence = max(doc_confidence, 0.85)
    fields = await extract_fields(doc_type, ocr_text, ocr_boxes, extracted_text, file.filename)
    fields = await validate_fields(fields)

    critical_fields = {
        "INE": ["curp", "nombre", "fecha_nacimiento"],
        "CURP": ["curp", "nombre"],
        "ACTA_NACIMIENTO": ["fecha", "folio"],
        "COMPROBANTE_DOMICILIO": ["domicilio"],
        "NSS": ["nss"],
        "DATOS_BANCARIOS": ["clabe", "banco"],
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
    include_ocr_text = bool(options_data.get("return_ocr_text"))
    include_boxes = bool(options_data.get("return_boxes"))
    if not ocr_text:
        warnings.append("No se detectó texto. Verifica OCR o la calidad del documento.")

    status = "READY"
    required = critical_fields.get(doc_type, [])
    found_required = 0
    for key in required:
        if any(field.get("key") == key and field.get("value") for field in fields):
            found_required += 1

    if required:
        coverage = found_required / max(1, len(required))
        if coverage < 1:
            doc_confidence = min(doc_confidence, 0.75)
            missing = [key for key in required if not any(field.get("key") == key and field.get("value") for field in fields)]
            if missing:
                warnings.append(f"Campos críticos faltantes: {', '.join(missing)}")
            else:
                warnings.append("Campos críticos incompletos.")

    if doc_confidence < 0.8 or invalid_critical:
        status = "NEEDS_REVIEW"
        if invalid_critical:
            warnings.append(f"Campos críticos inválidos: {', '.join(invalid_critical)}")

    if len(fields) == 0:
        status = "NEEDS_REVIEW"
        warnings.append("No se detectaron campos extraídos.")

    response = ProcessResponse(
        document_id=document_id,
        status=status,
        document_type=doc_type,
        confidence=doc_confidence,
        fields=[
            DocumentField(**{
                **field,
                "source": {
                    **field.get("source", {}),
                    "bbox": [
                        min(int(round(point[0])) for point in field.get("source", {}).get("bbox", [])),
                        min(int(round(point[1])) for point in field.get("source", {}).get("bbox", [])),
                        max(int(round(point[0])) for point in field.get("source", {}).get("bbox", [])),
                        max(int(round(point[1])) for point in field.get("source", {}).get("bbox", [])),
                    ] if field.get("source", {}).get("bbox") else None
                } if field.get("source") else None
            }) for field in fields
        ],
        warnings=warnings,
        errors=[],
        meta=ProcessMeta(
            pages_processed=len(images),
            ocr_engine=ocr_engine,
            pipeline_version=settings.pipeline_version,
            model_version=settings.model_version,
            processing_ms=processing_ms,
        ),
        ocr_text=ocr_text if include_ocr_text else None,
        ocr_boxes=ocr_boxes if include_boxes else None,
    )

    return response
