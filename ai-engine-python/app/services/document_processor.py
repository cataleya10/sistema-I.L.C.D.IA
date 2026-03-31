import json
import pandas as pd
from collections import Counter
def export_table_to_csv_excel(columns, rows, csv_path=None, excel_path=None):
    """
    Exporta una tabla (columnas, filas) a CSV y/o Excel usando pandas.
    columns: lista de nombres de columna
    rows: lista de dicts (clave: columna)
    csv_path: ruta para guardar CSV (opcional)
    excel_path: ruta para guardar Excel (opcional)
    Devuelve: (csv_str, excel_bytes)
    """
    df = pd.DataFrame(rows, columns=columns)
    csv_str = df.to_csv(index=False, encoding="utf-8-sig")
    excel_bytes = None
    if excel_path or not csv_path:
        import io
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False)
        excel_bytes = output.getvalue()
        if excel_path:
            with open(excel_path, "wb") as f:
                f.write(excel_bytes)
    if csv_path:
        with open(csv_path, "w", encoding="utf-8-sig") as f:
            f.write(csv_str)
    return csv_str, excel_bytes
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


def _looks_like_xml(text: str) -> bool:
    """True si el texto parece ser contenido XML (CFDI)."""
    stripped = (text or "").lstrip()
    return stripped.startswith("<?xml") or stripped.startswith("<cfdi:")


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


ALLOWED_FORCED_DOC_TYPES = {"FACTURA", "GENERICO"}


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
    # Name variants: keep each as a distinct key so documents with
    # multiple people (beneficiario, titular, asegurado) preserve ALL names.
    "nombre_beneficiario": "nombre_beneficiario",
    "nombre_asegurado": "nombre_asegurado",
    "nombre_titular": "nombre_titular",
    "nombre_del_beneficiario": "nombre_beneficiario",
    "nombre_del_asegurado": "nombre_asegurado",
    "nombre_del_titular": "nombre_titular",
    "beneficiario": "nombre_beneficiario",
    "asegurado": "nombre_asegurado",
}

CANONICAL_FIELD_LABELS: dict[str, str] = {
    "nss": "NSS",
    "nombre": "Nombre",
    "nombre_beneficiario": "Nombre Beneficiario",
    "nombre_asegurado": "Nombre Asegurado",
    "nombre_titular": "Nombre Titular",
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
    if document_type == "NSS" and resolved == "nombre_titular":
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
    "DATOS_BANCARIOS": ["clabe", "banco", "cuenta", "titular", "fecha_corte"],
    "FACTURA": ["tabla_celdas"],
    "CFDI": ["uuid", "rfc_emisor", "rfc_receptor", "total"],
    "CONSTANCIA_SITUACION_FISCAL": ["rfc", "nombre", "domicilio"],
    "GENERICO": [],
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
    "DATOS_BANCARIOS": ["clabe", "banco", "cuenta", "titular", "fecha_corte"],
    "FACTURA": ["tabla_celdas"],
    "CFDI": ["uuid", "rfc_emisor", "rfc_receptor", "total"],
    "CONSTANCIA_SITUACION_FISCAL": ["rfc"],
    "GENERICO": [],
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
        "nombre": ["nombre", "nombres", "nombre_completo", "nombre_beneficiario", "nombre_asegurado", "nombre_titular"],
    },
    "NSS": {
        "nombre": ["nombre", "nombres", "nombre_beneficiario", "nombre_asegurado", "nombre_titular", "titular"],
    },
    "DATOS_BANCARIOS": {
        "titular": ["titular", "nombre", "nombre_completo", "nombre_titular", "nombre_beneficiario"],
        "cuenta": ["cuenta", "numero_cuenta", "no_cuenta", "numero_de_cuenta"],
        "fecha_corte": ["fecha_corte", "fecha_de_corte", "corte", "fecha"],
        "tabla_celdas": ["tabla_celdas", "tabla", "celdas"],
    },
    "FACTURA": {
        "titular": ["titular", "nombre", "nombre_completo", "nombre_titular"],
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


_PAYROLL_REQUIRED_COLUMNS = (
    "cuenta",
    "referencia",
    "importe",
    "nombre",
    "apellido_paterno",
    "apellido_materno",
    "estatus",
    "concepto_pago",
)

_PAYROLL_STRICT_FILL_COLUMNS = (
    "cuenta",
    "referencia",
    "importe",
    "nombre",
    "apellido_paterno",
    "apellido_materno",
)


def _json_to_dict(raw_value) -> dict | None:
    if isinstance(raw_value, dict):
        return raw_value
    if not isinstance(raw_value, str):
        return None
    text = raw_value.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_payroll_canonical_table(fields: list[dict]) -> tuple[list[str], list[dict[str, str]]] | None:
    table_payload: dict | None = None
    for field in fields:
        normalized_key = _normalize_key_name(str(field.get("key", "") or ""))
        if normalized_key not in {"tabla_celdas", "pago_detalle"}:
            continue
        value = _field_value(field)
        payload = _json_to_dict(value)
        if not payload:
            continue
        if normalized_key == "tabla_celdas":
            table_payload = payload
            break
        table = payload.get("table")
        if isinstance(table, dict):
            table_payload = table

    if not isinstance(table_payload, dict):
        return None

    canonical_columns_raw = table_payload.get("canonical_columns")
    canonical_rows_raw = table_payload.get("canonical_rows")
    if not isinstance(canonical_columns_raw, list) or not isinstance(canonical_rows_raw, list):
        return None

    canonical_columns = [str(col or "").strip() for col in canonical_columns_raw if str(col or "").strip()]
    canonical_rows: list[dict[str, str]] = []
    for row in canonical_rows_raw:
        if not isinstance(row, dict):
            continue
        clean_row: dict[str, str] = {}
        for key, value in row.items():
            key_text = str(key or "").strip()
            if not key_text:
                continue
            value_text = str(value or "").strip()
            if value_text:
                clean_row[key_text] = value_text
        if clean_row:
            canonical_rows.append(clean_row)

    if not canonical_columns or not canonical_rows:
        return None
    return canonical_columns, canonical_rows


def _evaluate_payroll_strict(fields: list[dict], doc_type: str) -> tuple[list[str], bool]:
    if doc_type != "FACTURA" or not settings.payroll_strict_mode:
        return [], False

    extracted = _extract_payroll_canonical_table(fields)
    if not extracted:
        return [], False
    canonical_columns, canonical_rows = extracted
    canonical_set = set(canonical_columns)
    required_set = set(_PAYROLL_REQUIRED_COLUMNS)

    # Only enforce strict rules for advanced payroll tables.
    if not required_set.issubset(canonical_set):
        return [], False

    warnings: list[str] = []
    hard_fail = False
    total_rows = len(canonical_rows)
    if total_rows == 0:
        return ["[NOMINA_STRICT] tabla de nomina sin filas de datos."], True

    if "apellido_combo_estatus" in canonical_set:
        warnings.append("[NOMINA_STRICT] columna combinada 'apellido_combo_estatus' detectada en salida final.")
        hard_fail = True

    min_fill_rate = max(0.0, min(1.0, float(settings.payroll_strict_min_fill_rate)))
    min_rows_for_strict_fill = max(1, int(settings.payroll_strict_min_rows))
    if total_rows >= min_rows_for_strict_fill:
        for col in _PAYROLL_STRICT_FILL_COLUMNS:
            filled = sum(1 for row in canonical_rows if str(row.get(col, "") or "").strip())
            fill_rate = filled / max(1, total_rows)
            if fill_rate < min_fill_rate:
                warnings.append(
                    f"[NOMINA_STRICT] columna '{col}' con llenado bajo: {fill_rate:.1%} (< {min_fill_rate:.0%})."
                )
                hard_fail = True

    max_ratio = max(0.0, min(1.0, float(settings.payroll_strict_max_dominant_surname_ratio)))
    min_rows_for_ratio = max(10, int(settings.payroll_strict_min_rows))
    for surname_col in ("apellido_paterno", "apellido_materno"):
        values = [str(row.get(surname_col, "") or "").strip().upper() for row in canonical_rows]
        values = [value for value in values if value]
        if len(values) < min_rows_for_ratio:
            continue
        counts = Counter(values)
        dominant_value, dominant_count = counts.most_common(1)[0]
        dominant_ratio = dominant_count / len(values)
        if dominant_ratio > max_ratio:
            warnings.append(
                f"[NOMINA_STRICT] posible sobre-relleno en '{surname_col}': "
                f"'{dominant_value}' aparece en {dominant_ratio:.1%} de filas."
            )
            hard_fail = True

    dedupe_keys: list[tuple[str, str, str]] = []
    for row in canonical_rows:
        cuenta = str(row.get("cuenta", "") or "").strip()
        referencia = str(row.get("referencia", "") or "").strip()
        importe = str(row.get("importe", "") or "").strip()
        if cuenta and referencia and importe:
            dedupe_keys.append((cuenta, referencia, importe))
    if dedupe_keys:
        duplicate_count = len(dedupe_keys) - len(set(dedupe_keys))
        if duplicate_count > 0:
            duplicate_ratio = duplicate_count / len(dedupe_keys)
            warnings.append(
                f"[NOMINA_STRICT] filas duplicadas por (cuenta,referencia,importe): "
                f"{duplicate_count} ({duplicate_ratio:.1%})."
            )
            if duplicate_ratio > 0.10:
                hard_fail = True

    return warnings, hard_fail


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


_ACTA_NAME_NOISE_TOKENS = {
    "SEXO",
    "FECHA",
    "NACIMIENTO",
    "LUGAR",
    "REGISTRO",
    "ACTA",
    "PERSONA REGISTRADA",
    "DATOS DE LA",
}

_ACTA_LOCATION_NOISE_TOKENS = {
    "SEXO",
    "FECHA",
    "ACTA DE NACIMIENTO",
    "DATOS DE LA PERSONA",
    "PERSONA REGISTRADA",
}


def _mark_field_invalid(field: dict, error: str, confidence_cap: float = 0.55) -> None:
    field["valid"] = False
    current_conf = float(field.get("confidence", 0.0) or 0.0)
    field["confidence"] = min(current_conf, confidence_cap) if current_conf else confidence_cap
    errors = field.get("validation_errors")
    if not isinstance(errors, list):
        errors = []
    if error not in errors:
        errors.append(error)
    field["validation_errors"] = errors


def _is_plausible_ddmmyyyy(value: str) -> bool:
    match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", value)
    if not match:
        return False
    day = int(match.group(1))
    month = int(match.group(2))
    year = int(match.group(3))
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return False
    current_year = time.localtime().tm_year
    return 1900 <= year <= current_year + 1


def _apply_acta_sanity_guards(fields: list[dict]) -> tuple[list[dict], list[str]]:
    if not settings.acta_sanity_guards_enabled:
        return fields, []

    warnings: list[str] = []
    for field in fields:
        key = str(field.get("key", "") or "")
        value_raw = field.get("value")
        if value_raw in {None, ""}:
            continue
        value = str(value_raw).strip()
        upper = value.upper()

        if key == "nombre":
            cleaned = re.sub(r"\s+", " ", re.sub(r"[^A-Z ]", " ", upper)).strip()
            has_noise = any(token in cleaned for token in _ACTA_NAME_NOISE_TOKENS)
            has_digits = bool(re.search(r"\d", cleaned))
            if has_noise or has_digits or len(re.sub(r"[^A-Z]", "", cleaned)) < 4:
                _mark_field_invalid(field, "Nombre con ruido OCR de etiquetas (ACTA).", confidence_cap=0.45)
                warnings.append("Guardia ACTA: nombre invalido por ruido OCR.")
            else:
                field["value"] = cleaned

        elif key == "sexo":
            normalized = upper.replace("0", "O")
            if normalized in {"HOMBRE", "H"}:
                field["value"] = "H"
            elif normalized in {"MUJER", "M"}:
                field["value"] = "M"
            else:
                _mark_field_invalid(field, "Sexo invalido en ACTA (esperado H/M).", confidence_cap=0.45)
                warnings.append("Guardia ACTA: sexo invalido.")

        elif key in {"fecha_nacimiento", "fecha_registro"}:
            normalized = value.replace("-", "/")
            if not _is_plausible_ddmmyyyy(normalized):
                _mark_field_invalid(field, f"{key} invalida en ACTA.", confidence_cap=0.45)
                warnings.append(f"Guardia ACTA: {key} invalida.")
            else:
                field["value"] = normalized

        elif key in {"lugar_nacimiento", "municipio_registro", "entidad_registro"}:
            cleaned = re.sub(r"\s+", " ", upper).strip()
            if any(token in cleaned for token in _ACTA_LOCATION_NOISE_TOKENS):
                _mark_field_invalid(field, f"{key} contiene ruido de encabezados en ACTA.", confidence_cap=0.45)
                warnings.append(f"Guardia ACTA: {key} invalido por ruido OCR.")
            else:
                field["value"] = cleaned

        elif key in {"folio", "numero_acta"}:
            if not re.fullmatch(r"[A-Z0-9-]{1,12}", upper):
                _mark_field_invalid(field, f"{key} invalido en ACTA.", confidence_cap=0.45)
                warnings.append(f"Guardia ACTA: {key} invalido.")
            else:
                field["value"] = upper

    if warnings:
        deduped: list[str] = []
        seen: set[str] = set()
        for warning in warnings:
            if warning in seen:
                continue
            seen.add(warning)
            deduped.append(warning)
        warnings = deduped
    return fields, warnings


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

    t0 = time.time()
    preprocess_result = await preprocess(file)
    logger.info("[PERF] preprocess: %.1fms", (time.time() - t0) * 1000)
    text_layer_boxes: list[dict] = []
    pdf_tables: list[list[list[str]]] = []
    table_cell_grids: list = []
    if isinstance(preprocess_result, tuple) and len(preprocess_result) >= 5:
        images, extracted_text, text_layer_boxes, pdf_tables, table_cell_grids = preprocess_result
    elif isinstance(preprocess_result, tuple) and len(preprocess_result) >= 4:
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
    acta_guard_warnings: list[str] = []

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
                doc_confidence = max(fast_confidence, 0.85) if fast_type not in {"UNKNOWN", "GENERICO"} else fast_confidence
                doc_type_warning = fast_warning
                fields = candidate_fields

    if not fields:
        t1 = time.time()
        ocr_text, ocr_boxes = await run_ocr(images)
        logger.info("[PERF] OCR (%d pages): %.1fms", len(images), (time.time() - t1) * 1000)
        if ocr_boxes:
            ocr_engine = str(ocr_boxes[0].get("engine") or "paddleocr")
        elif ocr_text:
            ocr_engine = "ocr"
        else:
            ocr_engine = "none"
        if extracted_text:
            if not ocr_text:
                ocr_text = extracted_text
                ocr_engine = "text-layer"
            else:
                ocr_text = f"{ocr_text}\n{extracted_text}"
                ocr_engine = "paddleocr+text-layer"

        if ocr_text:
            ocr_text = ocr_text.replace("\u00a0", " ").replace("\t", " ")

        # ── Fill img2table grids with OCR box text ──────────────────
        # When preprocess detected table grid structure (cell bounding
        # boxes via img2table) but couldn't read cell contents (no OCR
        # engine configured in img2table), map the OCR boxes from
        # PaddleOCR to grid cells to produce filled tables.
        if table_cell_grids and ocr_boxes:
            from app.pipelines.preprocess import fill_grid_tables_from_ocr_boxes
            grid_tables = fill_grid_tables_from_ocr_boxes(table_cell_grids, ocr_boxes)
            if grid_tables:
                logger.info("Filled %d grid table(s) from OCR boxes", len(grid_tables))
                pdf_tables = pdf_tables + grid_tables
        # ────────────────────────────────────────────────────────────

        first_image = images[0] if images else None
        doc_type, doc_confidence = await classify_document(first_image, ocr_text, file.filename)
        doc_type, doc_type_warning = _maybe_override_doc_type(doc_type, ocr_text, file.filename)
        if forced_doc_type:
            doc_type = forced_doc_type
            doc_confidence = max(doc_confidence, 0.9)
            doc_type_warning = None
        if (ocr_text or extracted_text) and doc_type not in {"UNKNOWN", "GENERICO"}:
            doc_confidence = max(doc_confidence, 0.85)
        extraction_boxes = ocr_boxes if ocr_boxes else text_layer_boxes
        t2 = time.time()
        if doc_type == "CFDI":
            # CFDI: llamar directamente al extractor con el contenido XML
            from app.extractors.cfdi_extractor import extract as _cfdi_extract
            fields = await _cfdi_extract(
                ocr_text=ocr_text,
                ocr_boxes=extraction_boxes,
                raw_text=extracted_text,
                filename=file.filename,
                pdf_tables=pdf_tables,
                xml_content=extracted_text if extracted_text and _looks_like_xml(extracted_text) else None,
            )
        else:
            from app.extractors import get_extractor
            _extractor = get_extractor(doc_type)
            _kwargs: dict = {
                "ocr_text": ocr_text,
                "ocr_boxes": extraction_boxes,
                "raw_text": extracted_text,
                "filename": file.filename,
                "pdf_tables": pdf_tables,
            }
            if doc_type in {"GENERICO", "UNKNOWN"}:
                _kwargs["document_type"] = doc_type
            fields = await _extractor.extract(**_kwargs)
        logger.info("[PERF] extract_fields (%s): %.1fms", doc_type, (time.time() - t2) * 1000)
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

    # === LLM GENERIC (extracción abierta para documentos genéricos) ===
    if settings.llm_fallback_enabled and ocr_text and doc_type in {"GENERICO", "UNKNOWN"}:
        try:
            from app.services.llm_fallback import try_llm_generic_extraction, merge_llm_fields
            _generic_llm_fields = await try_llm_generic_extraction(
                ocr_text, fields,
                api_key=settings.anthropic_api_key,
                model=settings.llm_fallback_model,
            )
            if _generic_llm_fields:
                fields = merge_llm_fields(fields, _generic_llm_fields)
                logger.info(
                    "LLM generic añadió %d campos para doc_type=%s document_id=%s",
                    len(_generic_llm_fields), doc_type, document_id,
                )
        except Exception:
            logger.exception(
                "LLM generic falló, continuando sin él (doc_type=%s, document_id=%s)",
                doc_type, document_id,
            )

    if doc_type == "ACTA_NACIMIENTO":
        fields, acta_guard_warnings = _apply_acta_sanity_guards(fields)

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
    if acta_guard_warnings:
        warnings.extend(acta_guard_warnings)
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

    strict_warnings, strict_hard_fail = _evaluate_payroll_strict(fields, doc_type)
    if strict_warnings:
        warnings.extend(strict_warnings)
    if strict_hard_fail:
        status = "NEEDS_REVIEW"

    populated_fields = sum(1 for field in fields if _has_field_value(field))
    invalid_fields = sum(1 for field in fields if field.get("valid") is False)
    logger.info(
        "Extraction summary doc_id=%s type=%s status=%s populated=%d invalid=%d required=%d missing=%d ocr=%s",
        document_id,
        doc_type,
        status,
        populated_fields,
        invalid_fields,
        len(required),
        len(missing),
        ocr_engine,
    )

    if warnings:
        deduped_warnings: list[str] = []
        seen: set[str] = set()
        for warning in warnings:
            key = str(warning or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped_warnings.append(key)
        warnings = deduped_warnings

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
