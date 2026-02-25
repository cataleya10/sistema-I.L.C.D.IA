import json
import re
from pathlib import Path
import time
import logging
from app.schemas.process import ProcessResponse, DocumentField, ProcessMeta
from app.core.config import settings
from app.pipelines.preprocess import preprocess
from app.pipelines.ocr import run_ocr
from app.pipelines.classify import classify_document
from app.pipelines.extract import extract_fields
from app.pipelines.validate import validate_fields
from app.services.online_learning import learn_from_processed_document

logger = logging.getLogger(__name__)

SERVICE_TEXT_HINTS = {
    "TELMEX",
    "TELEFONOS DE MEXICO",
    "TELMEX-TEL",
    "RECIBO",
    "LINEA DE CAPTURA",
    "REFERENCIA UNICA",
    "NUMERO TELEFONICO",
    "PAGAR ANTES DE",
    "TOTAL A PAGAR",
    "NO. DE CUENTA",
    "NO DE CUENTA",
}

CSF_STRONG_HINTS = {
    "CONSTANCIA DE SITUACION FISCAL",
    "CEDULA DE IDENTIFICACION FISCAL",
    "ID CIF",
}

SERVICE_FILENAME_HINTS = {
    "TELMEX",
    "RECIBO",
    "COMPROBANTE",
    "DOMICILIO",
    "CFE",
    "TOTALPLAY",
    "IZZI",
    "MEGACABLE",
}


def _looks_like_service_document(text: str, filename: str | None) -> bool:
    upper_text = (text or "").upper()
    upper_name = (filename or "").upper()
    if any(token in upper_text for token in SERVICE_TEXT_HINTS):
        return True
    if any(token in upper_name for token in SERVICE_FILENAME_HINTS):
        return True
    return False


def _looks_like_csf_document(text: str) -> bool:
    upper_text = (text or "").upper()
    if any(token in upper_text for token in CSF_STRONG_HINTS):
        return True
    return False


def _maybe_override_doc_type(doc_type: str, text: str, filename: str | None) -> tuple[str, str | None]:
    if doc_type == "CONSTANCIA_SITUACION_FISCAL":
        if _looks_like_service_document(text, filename) and not _looks_like_csf_document(text):
            return "COMPROBANTE_DOMICILIO", "Clasificacion ajustada por huellas de recibo/servicio."
    return doc_type, None


ALLOWED_FORCED_DOC_TYPES = {"FACTURA"}


def _resolve_forced_document_type(options_data: dict) -> str | None:
    raw = options_data.get("force_document_type")
    if not isinstance(raw, str):
        return None
    normalized = raw.strip().upper().replace("-", "_").replace(" ", "_")
    if normalized in ALLOWED_FORCED_DOC_TYPES:
        return normalized
    return None


def _has_sufficient_text_layer(text: str) -> bool:
    compact = " ".join((text or "").split())
    if not compact:
        return False
    alnum_count = sum(1 for ch in compact if ch.isalnum())
    word_count = len(compact.split(" "))
    return (
        alnum_count >= settings.min_text_layer_chars
        and word_count >= settings.min_text_layer_words
    )


def _critical_coverage(doc_type: str, fields: list[dict]) -> tuple[int, int]:
    required = CRITICAL_FIELDS.get(doc_type, [])
    if not required:
        return 0, 0
    found_required = 0
    for key in required:
        if _select_required_field(doc_type, key, fields):
            found_required += 1
    return found_required, len(required)


CANONICAL_FIELD_KEYS: dict[str, str] = {
    "nss": "nss",
    "seguridad_social": "nss",
    "numero_seguridad_social": "nss",
    "numero_de_seguridad_social": "nss",
    "sistema_nacional_de_seguridad_social": "nss",
    "sistema": "nss",
    "nombre_beneficiario": "nombre",
    "nombre_asegurado": "nombre",
    "nombre_titular": "nombre",
    "nombre_del_beneficiario": "nombre",
    "nombre_del_asegurado": "nombre",
    "nombre_del_titular": "nombre",
    "beneficiario": "nombre",
    "asegurado": "nombre",
}

CANONICAL_FIELD_LABELS: dict[str, str] = {
    "nss": "NSS",
    "nombre": "Nombre",
    "titular": "Titular",
}


def _normalize_key_name(value: str) -> str:
    normalized = (value or "").strip().lower()
    normalized = normalized.replace("-", "_").replace(" ", "_")
    return normalized


def _resolve_canonical_key(key: str, label: str, document_type: str) -> str:
    normalized_key = _normalize_key_name(key)
    if normalized_key in CANONICAL_FIELD_KEYS:
        resolved = CANONICAL_FIELD_KEYS[normalized_key]
    else:
        normalized_label = _normalize_key_name(label)
        if "seguridad" in normalized_label or "nss" in normalized_label:
            resolved = "nss"
        elif normalized_label in CANONICAL_FIELD_KEYS:
            resolved = CANONICAL_FIELD_KEYS[normalized_label]
        else:
            resolved = normalized_key

    if document_type == "NSS" and resolved == "titular":
        return "nombre"
    if document_type in {"COMPROBANTE_DOMICILIO", "FACTURA"} and resolved == "nombre":
        return "titular"
    return resolved


def _normalize_fields(document_type: str, fields: list[dict]) -> list[dict]:
    normalized: dict[str, dict] = {}
    for field in fields:
        raw_key = str(field.get("key", "") or "")
        raw_label = str(field.get("label", "") or "")
        canonical_key = _resolve_canonical_key(raw_key, raw_label, document_type)
        if not canonical_key:
            continue

        value = field.get("value")
        if isinstance(value, str):
            value = value.strip()
        if value in {"", None}:
            continue

        candidate = {
            **field,
            "key": canonical_key,
            "label": CANONICAL_FIELD_LABELS.get(canonical_key, raw_label or canonical_key),
            "value": value,
        }

        existing = normalized.get(canonical_key)
        if not existing:
            normalized[canonical_key] = candidate
            continue

        current_score = float(existing.get("confidence", 0) or 0)
        new_score = float(candidate.get("confidence", 0) or 0)
        current_valid = bool(existing.get("valid", True))
        new_valid = bool(candidate.get("valid", True))
        if (new_valid and not current_valid) or (new_valid == current_valid and new_score >= current_score):
            normalized[canonical_key] = candidate

    return list(normalized.values())


FASTPATH_REQUIRED_FIELDS: dict[str, list[str]] = {
    "INE": ["curp", "nombre", "fecha_nacimiento", "seccion", "vigencia"],
    "CURP": ["curp", "nombre", "fecha_nacimiento"],
    "ACTA_NACIMIENTO": ["nombre", "fecha_nacimiento", "folio", "numero_acta"],
    "COMPROBANTE_DOMICILIO": ["domicilio", "cp"],
    "NSS": ["nss", "nombre"],
    "DATOS_BANCARIOS": ["clabe", "banco", "titular"],
    "FACTURA": ["tabla_celdas"],
    "CONSTANCIA_SITUACION_FISCAL": ["rfc", "nombre", "domicilio"],
    "UNKNOWN": [],
}


def _has_required_fields(fields: list[dict], required_keys: list[str]) -> bool:
    for key in required_keys:
        if not any(field.get("key") == key and field.get("value") for field in fields):
            return False
    return True


DEFAULT_CRITICAL_FIELDS: dict[str, list[str]] = {
    "INE": ["curp", "nombre", "fecha_nacimiento"],
    "CURP": ["curp", "nombre"],
    "ACTA_NACIMIENTO": ["nombre", "fecha_nacimiento", "folio", "numero_acta"],
    "COMPROBANTE_DOMICILIO": ["domicilio"],
    "NSS": ["nss"],
    "DATOS_BANCARIOS": ["clabe", "banco"],
    "FACTURA": ["tabla_celdas"],
    "CONSTANCIA_SITUACION_FISCAL": ["rfc"]
}
CRITICAL_FIELDS: dict[str, list[str]] = DEFAULT_CRITICAL_FIELDS.copy()
_critical_path = Path(__file__).resolve().parent.parent / "models" / "critical_fields.json"
if _critical_path.exists():
    try:
        loaded = json.loads(_critical_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and loaded:
            CRITICAL_FIELDS = loaded
    except Exception:
        logger.warning("Failed to load critical_fields.json, using defaults", exc_info=True)
        CRITICAL_FIELDS = DEFAULT_CRITICAL_FIELDS.copy()

CRITICAL_KEY_ALIASES: dict[str, dict[str, list[str]]] = {
    "ACTA_NACIMIENTO": {
        "fecha_nacimiento": ["fecha_nacimiento", "fecha"],
    },
    "CURP": {
        "nombre": ["nombre", "nombres", "nombre_completo"],
    },
    "NSS": {
        "nombre": ["nombre", "nombres", "nombre_beneficiario", "nombre_asegurado", "titular"],
    },
    "DATOS_BANCARIOS": {
        "titular": ["titular", "nombre", "nombre_completo"],
    },
    "FACTURA": {
        "titular": ["titular", "nombre", "nombre_completo"],
        "tabla_celdas": ["tabla_celdas", "tabla", "celdas"],
    },
    "CONSTANCIA_SITUACION_FISCAL": {
        "nombre": ["nombre", "nombre_completo", "razon_social", "denominacion_razon_social"],
    },
}


def _critical_aliases(doc_type: str, key: str) -> list[str]:
    aliases_by_type = CRITICAL_KEY_ALIASES.get(doc_type, {})
    aliases = aliases_by_type.get(key, [key])
    return [_normalize_key_name(alias) for alias in aliases if alias]


def _has_field_value(field: dict) -> bool:
    value = field.get("corrected_value")
    if value in {None, ""}:
        value = field.get("value")
    if isinstance(value, str):
        value = value.strip()
    return value not in {None, ""}


def _field_value(field: dict):
    value = field.get("corrected_value")
    if value in {None, ""}:
        value = field.get("value")
    if isinstance(value, str):
        return value.strip()
    return value


def _is_effectively_valid(doc_type: str, required_key: str, field: dict) -> bool:
    if bool(field.get("valid", True)):
        return True

    value = _field_value(field)
    if value in {None, ""}:
        return False

    text = str(value).upper()
    if doc_type == "ACTA_NACIMIENTO" and required_key in {"folio", "numero_acta"}:
        return bool(re.fullmatch(r"[A-Z0-9-]{1,12}", text))

    return False


def _select_required_field(doc_type: str, required_key: str, fields: list[dict]) -> dict | None:
    aliases = set(_critical_aliases(doc_type, required_key))
    candidates = []
    for field in fields:
        normalized = _normalize_key_name(str(field.get("key", "") or ""))
        if normalized not in aliases:
            continue
        if not _has_field_value(field):
            continue
        confidence = float(field.get("confidence", 0) or 0)
        candidates.append((_is_effectively_valid(doc_type, required_key, field), confidence, field))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]

_LOW_CONF_DROP_BY_TYPE = {
    "INE": {
        "nombres",
        "apellido_paterno",
        "apellido_materno",
        "fecha",
        "entidad_nacimiento",
        "anio_registro",
    },
    "ACTA_NACIMIENTO": {
        "libro",
        "tomo",
        "oficialia",
        "registro_civil",
        "juez",
        "primer_apellido",
        "segundo_apellido",
        "anio_registro",
    },
    "COMPROBANTE_DOMICILIO": {
        "periodo",
        "titular",
        "referencia",
    },
    "CONSTANCIA_SITUACION_FISCAL": {
        "cp",
        "id_cif",
        "fecha_emision",
    },
    "CURP": {
        "entidad_registro",
    },
    "NSS": {
        "fecha_documento",
        "folio_solicitud",
    },
    "FACTURA": {
        "titular",
        "referencia",
        "fecha_corte",
    },
    "DATOS_BANCARIOS": {
        "titular",
        "fecha_corte",
        "periodo",
    },
}

_INVALID_DROP_BY_TYPE = {
    "ACTA_NACIMIENTO": {"registro_civil", "juez"},
    "INE": {"curp", "clave_elector", "seccion"},
    "CURP": {"curp"},
    "NSS": {"nss"},
    "DATOS_BANCARIOS": {"clabe", "rfc"},
    "CONSTANCIA_SITUACION_FISCAL": {"rfc", "cp"},
    "COMPROBANTE_DOMICILIO": {"cp"},
}


def _postprocess_fields(doc_type: str, fields: list[dict]) -> list[dict]:
    drop_low = _LOW_CONF_DROP_BY_TYPE.get(doc_type, set())
    drop_invalid = _INVALID_DROP_BY_TYPE.get(doc_type, set())
    cleaned: list[dict] = []
    for field in fields:
        key = field.get("key")
        if key == "texto_detectado":
            cleaned.append(field)
            continue
        if key in drop_low and field.get("confidence", 1) < 0.7:
            continue
        if key in drop_invalid and field.get("valid") is False:
            continue
        # Strip control characters from values
        value = str(field.get("value", "") or "")
        import re as _re
        sanitized = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', value).strip()
        if sanitized != value:
            field = {**field, "value": sanitized}
        if not sanitized:
            continue
        cleaned.append(field)
    return cleaned


async def process_document(file, document_id: str, source: str, options: str | None):
    start = time.time()
    options_data = {}
    if options:
        try:
            options_data = json.loads(options)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in options parameter: %s", options)
            options_data = {}
    forced_doc_type = _resolve_forced_document_type(options_data)

    preprocess_result = await preprocess(file)
    text_layer_boxes: list[dict] = []
    pdf_tables: list[list[list[str]]] = []
    if isinstance(preprocess_result, tuple) and len(preprocess_result) >= 4:
        images, extracted_text, text_layer_boxes, pdf_tables = preprocess_result
    elif isinstance(preprocess_result, tuple) and len(preprocess_result) >= 3:
        images, extracted_text, text_layer_boxes = preprocess_result
    else:
        images, extracted_text = preprocess_result
    ocr_text = ""
    ocr_boxes = []
    ocr_engine = "none"
    doc_type_warning = None
    fields: list[dict] = []

    use_fastpath = bool(
        extracted_text
        and _has_sufficient_text_layer(extracted_text)
    )
    if use_fastpath:
        fast_type, fast_confidence = await classify_document(None, extracted_text, file.filename)
        fast_type, fast_warning = _maybe_override_doc_type(fast_type, extracted_text, file.filename)
        if forced_doc_type:
            fast_type = forced_doc_type
            fast_confidence = max(fast_confidence, 0.9)
            fast_warning = None
        if fast_type in settings.text_layer_fastpath_types:
            candidate_fields = await extract_fields(
                fast_type,
                extracted_text,
                text_layer_boxes,
                extracted_text,
                file.filename,
                pdf_tables,
            )
            candidate_fields = await validate_fields(candidate_fields)
            candidate_fields = _normalize_fields(fast_type, candidate_fields)
            candidate_fields = _postprocess_fields(fast_type, candidate_fields)
            found_required, required_total = _critical_coverage(fast_type, candidate_fields)
            fastpath_complete = required_total == 0 or found_required == required_total
            extra_required = FASTPATH_REQUIRED_FIELDS.get(fast_type, [])
            if extra_required and not _has_required_fields(candidate_fields, extra_required):
                fastpath_complete = False
            if fastpath_complete and candidate_fields:
                ocr_text = extracted_text
                ocr_engine = "text-layer-fastpath"
                doc_type = fast_type
                doc_confidence = max(fast_confidence, 0.85) if fast_type != "UNKNOWN" else fast_confidence
                doc_type_warning = fast_warning
                fields = candidate_fields

    if not fields:
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
        doc_type, doc_type_warning = _maybe_override_doc_type(doc_type, ocr_text, file.filename)
        if forced_doc_type:
            doc_type = forced_doc_type
            doc_confidence = max(doc_confidence, 0.9)
            doc_type_warning = None
        if (ocr_text or extracted_text) and doc_type != "UNKNOWN":
            doc_confidence = max(doc_confidence, 0.85)
        extraction_boxes = ocr_boxes if ocr_boxes else text_layer_boxes
        fields = await extract_fields(doc_type, ocr_text, extraction_boxes, extracted_text, file.filename, pdf_tables)
        fields = await validate_fields(fields)
        fields = _normalize_fields(doc_type, fields)
        fields = _postprocess_fields(doc_type, fields)

    # === LLM FALLBACK (solo si hay campos críticos faltantes) ===
    if settings.llm_fallback_enabled and ocr_text:
        _tentative_required = CRITICAL_FIELDS.get(doc_type, [])
        _tentative_missing = [
            k for k in _tentative_required
            if not _select_required_field(doc_type, k, fields)
        ]
        if _tentative_missing:
            try:
                from app.services.llm_fallback import try_llm_fallback, merge_llm_fields
                _llm_fields = await try_llm_fallback(
                    doc_type, ocr_text, _tentative_missing, fields,
                    api_key=settings.anthropic_api_key,
                    model=settings.llm_fallback_model,
                )
                if _llm_fields:
                    fields = merge_llm_fields(fields, _llm_fields)
                    logger.info(
                        "LLM fallback añadió %d campos para doc_type=%s document_id=%s",
                        len(_llm_fields), doc_type, document_id,
                    )
            except Exception:
                logger.exception(
                    "LLM fallback falló, continuando sin él (doc_type=%s, document_id=%s)",
                    doc_type, document_id,
                )

    critical_keys = set(CRITICAL_FIELDS.get(doc_type, []))
    for field in fields:
        if field.get("key") in critical_keys and field.get("valid") and field.get("confidence", 0) < 0.8:
            field["confidence"] = 0.8

    required = CRITICAL_FIELDS.get(doc_type, [])
    invalid_critical = []
    for key in required:
        field = _select_required_field(doc_type, key, fields)
        if not field or not _is_effectively_valid(doc_type, key, field):
            invalid_critical.append(key)

    processing_ms = int((time.time() - start) * 1000)

    warnings: list[str] = []
    if forced_doc_type:
        warnings.append(f"Tipo forzado manualmente: {forced_doc_type}.")
    if doc_type_warning:
        warnings.append(doc_type_warning)
    include_ocr_text = bool(options_data.get("return_ocr_text"))
    include_boxes = bool(options_data.get("return_boxes"))
    if not ocr_text:
        warnings.append("No se detectó texto. Verifica OCR o la calidad del documento.")

    status = "READY"
    required = CRITICAL_FIELDS.get(doc_type, [])
    found_required = 0
    for key in required:
        if _select_required_field(doc_type, key, fields):
            found_required += 1

    missing: list[str] = []
    if required:
        coverage = found_required / max(1, len(required))
        if coverage < 1:
            doc_confidence = min(doc_confidence, 0.75)
            missing = [key for key in required if not _select_required_field(doc_type, key, fields)]
            if missing:
                warnings.append(f"Campos críticos faltantes: {', '.join(missing)}")
            else:
                warnings.append("Campos críticos incompletos.")

    if missing:
        status = "NEEDS_REVIEW"

    if invalid_critical:
        status = "NEEDS_REVIEW"
        warnings.append(f"Campos críticos inválidos: {', '.join(invalid_critical)}")
    elif doc_confidence < 0.8 and not required:
        status = "NEEDS_REVIEW"

    if len(fields) == 0:
        status = "NEEDS_REVIEW"
        warnings.append("No se detectaron campos extraídos.")

    try:
        learn_from_processed_document(
            document_id=document_id,
            document_type=doc_type,
            status=status,
            confidence=doc_confidence,
            ocr_text=ocr_text,
            fields=fields,
            processing_ms=(time.time() - start) * 1000,
            critical_keys=list(CRITICAL_FIELDS.get(doc_type, [])),
        )
    except Exception:
        logger.exception("Online learning failed for document_id=%s", document_id)

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
        ocr_boxes=(ocr_boxes if ocr_boxes else text_layer_boxes) if include_boxes else None,
    )

    return response
