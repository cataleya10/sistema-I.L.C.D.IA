"""Shared utilities: text normalization, OCR, field building, validation."""

import re
import json
import os
import logging
import unicodedata
from datetime import datetime
from typing import Any

from .constants import *  # noqa: F403
from app.pipelines.legacy_adapter import legacy_extract_fields
from app.pipelines.table_postprocess import (
    postprocess_payment_table,
    postprocess_metadata,
    compute_table_quality_report,
)

logger = logging.getLogger(__name__)


def _export_all():
    import sys
    mod = sys.modules[__name__]
    return [n for n in dir(mod) if not n.startswith('__')]


CURP_PATTERN = re.compile(r"\b[A-Z][AEIOUX][A-Z]{2}\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[HM][A-Z]{5}[A-Z0-9]\d\b")

# Posiciones de letras y dígitos en un CURP de 18 caracteres (índice 0)
_CURP_LETTER_POS = frozenset({0, 1, 2, 3, 10, 11, 12, 13, 14, 15, 16})
_CURP_DIGIT_POS = frozenset({4, 5, 6, 7, 8, 9, 17})
_CURP_OCR_DIGIT_TO_LETTER = {"0": "O", "1": "I", "5": "S", "8": "B"}
_CURP_OCR_LETTER_TO_DIGIT = {"O": "0", "I": "1", "L": "1", "S": "5", "B": "8"}


def _try_fix_curp_ocr(candidate: str) -> str:
    """Corrige confusiones OCR comunes en un candidato de 18 chars que podría ser CURP."""
    if len(candidate) != 18:
        return candidate
    chars = list(candidate.upper())
    for i, ch in enumerate(chars):
        if i in _CURP_LETTER_POS and ch in _CURP_OCR_DIGIT_TO_LETTER:
            chars[i] = _CURP_OCR_DIGIT_TO_LETTER[ch]
        elif i in _CURP_DIGIT_POS and ch in _CURP_OCR_LETTER_TO_DIGIT:
            chars[i] = _CURP_OCR_LETTER_TO_DIGIT[ch]
    return "".join(chars)


def _search_curp(text: str) -> str | None:
    """Busca CURP en texto; si no encuentra match directo, intenta corrección OCR."""
    m = CURP_PATTERN.search(text.upper())
    if m:
        return m.group(0)
    for candidate in re.findall(r"[A-Z0-9]{18}", text.upper()):
        fixed = _try_fix_curp_ocr(candidate)
        if CURP_PATTERN.fullmatch(fixed):
            return fixed
    return None
RFC_PATTERN = re.compile(r"\b[A-Z&]{3,4}\d{6}[A-Z0-9]{3}\b")
NSS_PATTERN = re.compile(r"\b\d{11}\b")
CLABE_PATTERN = re.compile(r"\b\d{18}\b")
ACCOUNT_PATTERN = re.compile(r"\b\d{10,16}\b")
AMOUNT_PATTERN = re.compile(r"\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\b")
DATE_PATTERN = re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b")
DATE_FLEX_PATTERN = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}(?:\s+|[-/])[A-Z]{3,9}(?:\s+|[-/])\d{2,4})\b"
)
NAME_PATTERN = re.compile(r"\b[A-Z]{2,}(?:\s+[A-Z]{2,}){1,7}\b")
RFC_WITH_HOMOCLAVE = RFC_PATTERN  # alias — same regex, single compiled instance
CP_PATTERN = re.compile(r"\b\d{5}\b")

LABEL_MAP = {
    "CURP": "curp",
    "RFC": "rfc",
    "NSS": "nss",
    "CLABE": "clabe",
}

LABEL_ALIASES = {
    "NOMBRE": ["NOMBRE", "NOMBRES", "APELLIDO", "APELLIDOS", "APELLIDO PATERNO", "APELLIDO MATERNO", "NOMBRE(S)"],
    "CURP": ["CURP", "CLAVE UNICA DE REGISTRO DE POBLACION"],
    "RFC": ["RFC", "R.F.C.", "REGISTRO FEDERAL DE CONTRIBUYENTES"],
    "SEXO": ["SEXO", "GENERO", "GEN"],
    "DOMICILIO": ["DOMICILIO", "DIRECCION", "DIR"],
    "FECHA DE NACIMIENTO": ["FECHA DE NACIMIENTO", "FECHA NACIMIENTO", "F NACIMIENTO", "NACIMIENTO"],
    "LUGAR DE NACIMIENTO": ["LUGAR DE NACIMIENTO", "LUGAR NACIMIENTO"],
    "ENTIDAD DE REGISTRO": ["ENTIDAD DE REGISTRO", "ENTIDAD REGISTRO"],
    "MUNICIPIO DE REGISTRO": ["MUNICIPIO DE REGISTRO", "MUNICIPIO REGISTRO", "MUNICLPIO DE REGISTRO"],
    "FECHA DE REGISTRO": ["FECHA DE REGISTRO", "FECHA REGISTRO"],
    "NUMERO DE ACTA": ["NUMERO DE ACTA", "NUMERO ACTA", "NO ACTA", "NRO ACTA", "NUMERO DE ACTE", "NUMERO ACTE"],
    "NUMERO DE CERTIFICADO DE NACIMIENTO": [
        "NUMERO DE CERTIFICADO DE NACIMIENTO",
        "NUMERO CERTIFICADO",
        "NO CERTIFICADO",
        "CERTIFICADO NACIMIENTO",
    ],
    "NUMERO DE SERVICIO": ["NUMERO DE SERVICIO", "NUMERO SERVICIO", "NO SERVICIO", "NRO SERVICIO", "SERVICIO"],
    "NUMERO DE CLIENTE": ["NUMERO DE CLIENTE", "NO CLIENTE", "NRO CLIENTE", "CLIENTE"],
    "FECHA DE CORTE": ["FECHA DE CORTE", "FECHA CORTE"],
    "FECHA LIMITE": ["FECHA LIMITE", "F LIMITE", "VENCE"],
    "CLAVE DE ELECTOR": ["CLAVE DE ELECTOR", "CLAVE ELECTOR", "CLAVE ELECT"],
    "SECCION": ["SECCION", "SECC"],
}

LEGACY_LABELS = {
    "nombre": "Nombre",
    "nombres": "Nombres",
    "apellido_paterno": "Apellido paterno",
    "apellido_materno": "Apellido materno",
    "sexo": "Sexo",
    "domicilio": "Domicilio",
    "clave_elector": "Clave de elector",
    "curp": "CURP",
    "anio_registro": "Anio de registro",
    "fecha_nacimiento": "Fecha de nacimiento",
    "seccion": "Seccion",
    "vigencia": "Vigencia",
    "entidad_registro": "Entidad de registro",
    "municipio_registro": "Municipio de registro",
    "primer_apellido": "Primer apellido",
    "segundo_apellido": "Segundo apellido",
    "lugar_nacimiento": "Lugar de nacimiento",
    "fecha_emision": "Fecha de emision",
    "nss": "NSS",
    "fecha_documento": "Fecha documento",
    "folio_solicitud": "Folio solicitud",
    "rfc": "RFC",
    "cp": "CP",
    "id_cif": "Id CIF",
    "regimen": "Regimen",
    "banco": "Banco",
    "titular": "Titular",
    "clabe": "CLABE",
    "cuenta": "Cuenta",
    "proveedor": "Proveedor",
}

LEGACY_OVERRIDE_KEYS = {
    "seccion",
    "vigencia",
    "sexo",
    "clave_elector",
    "curp",
}


def _normalize_legacy_value(key: str, value: str) -> str:
    if value is None:
        return ""
    if key in {"curp", "rfc", "clave_elector", "folio_solicitud"}:
        return _normalize_alnum(value)
    if key in {"nss", "clabe", "cuenta", "cp", "seccion"}:
        return _normalize_numeric_field(value)
    if key in {"fecha_nacimiento", "fecha_emision", "fecha_documento"}:
        return _normalize_date_value(value)
    if key == "domicilio":
        return _clean_address_value(value)
    if key in {"lugar_nacimiento", "entidad_registro", "municipio_registro", "banco"}:
        return _normalize_address(value)
    if key in {"nombre", "nombres", "apellido_paterno", "apellido_materno", "primer_apellido", "segundo_apellido", "titular"}:
        return _normalize_name(value)
    if key == "sexo":
        return _normalize_sex(value)
    return _normalize_text(value)


def _name_quality_score(value: str, curp: str | None = None) -> int:
    normalized = _normalize_name(value).upper()
    if not normalized:
        return -1000

    tokens = [tok for tok in re.findall(r"[A-Z]+", normalized) if tok]
    if not tokens:
        return -1000

    particles = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "MC", "VAN", "VON"}
    short_noise = sum(1 for tok in tokens if len(tok) <= 2 and tok not in particles)

    score = len(tokens) * 10 + sum(min(len(tok), 8) for tok in tokens)
    if len(tokens) >= 3:
        score += 12
    if len(tokens) <= 2:
        score -= 15
    score -= short_noise * 10

    if any(ch.isdigit() for ch in normalized):
        score -= 30
    if ":" in normalized:
        score -= 20

    normalized_curp = _normalize_alnum(curp or "")
    if len(normalized_curp) >= 4:
        if _name_matches_curp(normalized, normalized_curp):
            score += 30
        else:
            score -= 25

    return score


def _merge_legacy_fields(fields: list[dict], legacy_values: dict[str, str], ocr_boxes):
    existing = {field.get("key"): field for field in fields if field.get("value")}
    existing_curp = str(existing.get("curp", {}).get("value", "") or "")
    for key, value in legacy_values.items():
        if not value:
            continue
        label = LEGACY_LABELS.get(key, key)
        normalized = _normalize_legacy_value(key, value)
        if not normalized:
            continue
        if key not in LEGACY_OVERRIDE_KEYS and key in existing:
            if key in {"nombre", "nombres"}:
                current_value = str(existing[key].get("value", "") or "")
                current_score = _name_quality_score(current_value, existing_curp)
                candidate_score = _name_quality_score(normalized, existing_curp)
                if candidate_score >= current_score + 6:
                    fields.append(_make_field(key, label, normalized, ocr_boxes, confidence=0.83))
            continue
        # Reject lugar_nacimiento values that contain section-header noise from ACTA
        if key == "lugar_nacimiento":
            upper_norm = normalized.upper()
            if any(noise in upper_norm for noise in ("PERSONA REGISTRADA", "DATOS DE LA", "REGISTRADA")):
                continue
        confidence = 0.9 if key in LEGACY_OVERRIDE_KEYS else 0.65
        fields.append(_make_field(key, label, normalized, ocr_boxes, confidence=confidence))

_ALIAS_MODEL_PATH = os.getenv(
    "FIELD_ALIAS_PATH",
    os.path.join(os.path.dirname(__file__), "..", "models", "field_aliases.json"),
)
_ALIAS_MODEL_MTIME = None
_ALIAS_MODEL_CACHE = {}


def _load_alias_model():
    global _ALIAS_MODEL_MTIME
    global _ALIAS_MODEL_CACHE

    try:
        if not os.path.exists(_ALIAS_MODEL_PATH):
            _ALIAS_MODEL_MTIME = None
            _ALIAS_MODEL_CACHE = {}
            return {}

        mtime = os.path.getmtime(_ALIAS_MODEL_PATH)
        if _ALIAS_MODEL_MTIME == mtime and isinstance(_ALIAS_MODEL_CACHE, dict):
            return _ALIAS_MODEL_CACHE

        with open(_ALIAS_MODEL_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            loaded = {}
        _ALIAS_MODEL_CACHE = loaded
        _ALIAS_MODEL_MTIME = mtime
        return _ALIAS_MODEL_CACHE
    except Exception:
        logger.exception("Failed to load alias model from %s", _ALIAS_MODEL_PATH)
        return _ALIAS_MODEL_CACHE if isinstance(_ALIAS_MODEL_CACHE, dict) else {}


def _is_reasonable_alias(alias: str) -> bool:
    if not alias:
        return False
    token = _normalize_keyword(alias)
    if len(token) < 4:
        return False
    letters = sum(1 for ch in token if ch.isalpha())
    if letters < 3:
        return False
    banned = {"ES", "PAGO", "P", "CP", "NSS"}
    return token not in banned


def _merge_aliases(label: str) -> list[str]:
    base = LABEL_ALIASES.get(label, [label])
    aliases_from_model = _load_alias_model()
    raw_extra = aliases_from_model.get(LABEL_MAP.get(label, label), [])
    extra = [alias for alias in raw_extra if _is_reasonable_alias(str(alias))]
    return list(dict.fromkeys([*base, *extra]))

STATE_CODE_TO_NAME = {
    "AS": "AGUASCALIENTES",
    "BC": "BAJA CALIFORNIA",
    "BS": "BAJA CALIFORNIA SUR",
    "CC": "CAMPECHE",
    "CL": "COAHUILA",
    "CM": "COLIMA",
    "CS": "CHIAPAS",
    "CH": "CHIHUAHUA",
    "DF": "CIUDAD DE MEXICO",
    "DG": "DURANGO",
    "GT": "GUANAJUATO",
    "GR": "GUERRERO",
    "HG": "HIDALGO",
    "JC": "JALISCO",
    "MC": "MEXICO",
    "MN": "MICHOACAN",
    "MS": "MORELOS",
    "NT": "NAYARIT",
    "NL": "NUEVO LEON",
    "OC": "OAXACA",
    "PL": "PUEBLA",
    "QT": "QUERETARO",
    "QR": "QUINTANA ROO",
    "SP": "SAN LUIS POTOSI",
    "SL": "SINALOA",
    "SR": "SONORA",
    "TC": "TABASCO",
    "TS": "TAMAULIPAS",
    "TL": "TLAXCALA",
    "VZ": "VERACRUZ",
    "YN": "YUCATAN",
    "ZS": "ZACATECAS",
    "NE": "NACIDO EN EL EXTRANJERO",
}


def _find_source(value: str, ocr_boxes):
    if not value or not ocr_boxes:
        return None
    for box in ocr_boxes:
        if value in box.get("text", "").upper():
            return {"page": box.get("page", 1), "bbox": box.get("bbox", []),
                    "ocr_confidence": box.get("confidence")}
    return None


def _ocr_confidence_for_value(value: str, ocr_boxes) -> float | None:
    """Return the OCR engine confidence for the box that contains *value*.

    Returns None when value cannot be located in ocr_boxes so callers can
    decide whether to adjust the extraction confidence.
    """
    if not value or not ocr_boxes:
        return None
    upper = value.upper()
    for box in ocr_boxes:
        if upper in box.get("text", "").upper():
            conf = box.get("confidence")
            if isinstance(conf, (int, float)):
                return float(conf)
    return None


def _make_field(key: str, label: str, value: str, ocr_boxes, confidence: float = 0.7):
    source = _find_source(value, ocr_boxes)
    # Propagate OCR box confidence: if OCR confidence is lower than the
    # requested extraction confidence, cap the field confidence down so
    # that downstream filters can discard unreliable extractions.
    ocr_conf = _ocr_confidence_for_value(value, ocr_boxes)
    effective_conf = confidence
    if ocr_conf is not None and ocr_conf < confidence:
        # Blend: keep some extractor confidence but weigh OCR quality
        effective_conf = round(min(confidence, 0.5 * confidence + 0.5 * ocr_conf), 4)
    return {
        "key": key,
        "label": label,
        "value": value,
        "confidence": effective_conf,
        "valid": True,
        "validation_errors": [],
        "source": source,
    }


def _pick_address(lines: list[str]):
    keywords = (
        "CALLE",
        "AV",
        "AV.",
        "AVENIDA",
        "COL",
        "COL.",
        "COLONIA",
        "FRACC",
        "FRACCIONAMIENTO",
        "CP",
        "C.P.",
        "CODIGO POSTAL",
        "CODIGO POSTAL",
        "NUM",
        "NUM",
        "NO.",
        "#",
        "MUNICIPIO",
        "ESTADO",
        "DEPTO",
    )
    noise_tokens = (
        "TELMEX",
        "TELCEL",
        "TELEFON",
        "NUMERO DE SERVICIO",
        "NO. DE SERVICIO",
        "NO DE SERVICIO",
        "RMU",
        "LINEA DE CAPTURA",
        "REFERENCIA",
        "CUENTA",
        "PAGAR",
        "TOTAL",
        "SALDO",
        "IMPORTE",
    )
    corporate_tokens = (
        "PASEO DE LA REFORMA",
        "ALCALDIA",
        "CUAUHTEMOC",
        "CIUDAD DE MEXICO",
        "RFC:CFE",
        "COMISION FEDERAL",
    )
    customer_tokens = ("DEPTO", "BENITO", "CARMEN", "S/N", "RIA", "SSL")
    stop_tokens = (
        "NO.DESERVICIO",
        "NO. DE SERVICIO",
        "RMU",
        "CUENTA",
        "TOTAL",
        "LIMITE",
        "CORTE",
        "TARIFA",
        "CONCEPTO",
        "LECTURA",
        "PERIODO",
    )

    best_candidate = None
    best_score = -10_000.0
    best_idx = -1

    def _line_score(text_line: str) -> float:
        score = 0.0
        score += sum(1.6 for k in keywords if k in text_line)
        if re.search(r"\bC\.?\s*P\.?\s*\d{5}\b", text_line) or re.search(r"\b\d{5}\b", text_line):
            score += 3.0
        if any(tok in text_line for tok in customer_tokens):
            score += 2.5
        if re.search(r"\b\d{1,2}DN\.?\d{1,4}\b|\b\d{1,2}DN\.?\b", text_line):
            score += 3.0
        if any(tok in text_line for tok in corporate_tokens):
            score -= 4.0
        if text_line.startswith("-"):
            score -= 0.6
        return score

    for idx, line in enumerate(lines):
        upper = _normalize_text(line).upper()
        if not upper:
            continue
        if not any(k in upper for k in keywords) and not any(tok in upper for tok in customer_tokens):
            continue
        if any(token in upper for token in noise_tokens):
            continue

        parts = [upper]
        score = _line_score(upper)
        if "DOMICILIO DE SUMINISTRO" in upper:
            score += 3.5

        for offset in (1, 2):
            next_idx = idx + offset
            if next_idx >= len(lines):
                break
            nxt = _normalize_text(lines[next_idx]).upper()
            if not nxt:
                continue
            if any(token in nxt for token in stop_tokens):
                break
            if any(token in nxt for token in noise_tokens):
                break
            if not (
                any(k in nxt for k in keywords)
                or re.search(r"\b\d{5}\b", nxt)
                or any(tok in nxt for tok in ("CIUDAD", "MUNICIPIO", "EDO", "TAB", "CAMP", "JONUTA"))
            ):
                break
            parts.append(nxt)
            score += _line_score(nxt) * 0.7

        candidate = " ".join(parts).strip()
        score += min(len(candidate), 140) * 0.02
        if score > best_score or (score == best_score and idx > best_idx):
            best_score = score
            best_candidate = candidate
            best_idx = idx

    return best_candidate


def _repair_mojibake(text: str) -> str:
    """Repair common UTF-8→Latin-1 mojibake (e.g. Ã± → ñ)."""
    if not text or "\u00c3" not in text:
        return text
    try:
        repaired = text.encode("latin-1").decode("utf-8")
        if len(repaired) < len(text):
            return repaired
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    return text


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _repair_mojibake(text)
    text = text.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _ascii_fold(text: str) -> str:
    value = str(text or "")
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")


def _normalize_keyword(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", _ascii_fold(text).upper())


def _is_junk_payment_header(header_cell: str) -> bool:
    """Detect column headers that are noise from PDF layout (footer, contact info).

    PyMuPDF sometimes captures text adjacent to tables (phone numbers, city
    names, addresses from footers) as extra table columns.  This identifies
    those junk headers so they can be stripped before they pollute the
    extraction pipeline.
    """
    text = str(header_cell or "").strip()
    if not text:
        return True  # empty header → junk

    # Strip to alphanumeric core
    alphanum = re.sub(r"[^A-Za-z0-9]", "", text)
    if not alphanum:
        return True  # only punctuation/symbols

    # Pure digits → phone numbers / codes (e.g. "9600", "3669 9000", "01 800 226 6783")
    if alphanum.isdigit():
        return True

    # Starts with dash/hyphen → formatting artifacts (e.g. "– GUADALAJARA (33)")
    first_non_space = text.lstrip()
    if first_non_space and first_non_space[0] in ("\u2013", "\u2014", "\u2212", "-"):
        return True

    # Known geographic / contact-info noise words that are never payment fields
    upper = text.upper()
    _NOISE_FRAGMENTS = (
        "GUADALAJARA", "MONTERREY", "RESTO DEL", "CIUDAD DE MEXICO",
        "CDMX", "01 800", "01800", "LADA SIN COSTO",
    )
    if any(nf in upper for nf in _NOISE_FRAGMENTS):
        return True

    return False


def _is_reasonable_acta_optional(value: str) -> bool:
    if not value:
        return False
    cleaned = _normalize_text(value).upper()
    if len(cleaned) > 30:
        return False
    if any(token in cleaned for token in ["FIRMA", "ELECTRON", "EXPEDICION", "CERTIF", "ANOTAC", "REGLAMENTO"]):
        return False
    letters = sum(1 for ch in cleaned if ch.isalpha())
    return letters >= 2


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

# Fields that should be dropped when marked invalid (valid=False) per doc type
_INVALID_DROP_BY_TYPE: dict[str, set[str]] = {
    "ACTA_NACIMIENTO": {"registro_civil", "juez"},
    "INE": {"curp", "clave_elector", "seccion"},
    "CURP": {"curp"},
    "NSS": {"nss"},
    "DATOS_BANCARIOS": {"clabe", "rfc"},
    "CONSTANCIA_SITUACION_FISCAL": {"rfc", "cp"},
    "COMPROBANTE_DOMICILIO": {"cp"},
}


# ── Value sanitizer: detects and rejects OCR garbage ──────────────────────
_GARBAGE_PATTERN = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f]"
    r"|[\x7f-\x9f]"
    r"|[#%&<>{}\\]{3,}"
)
_MIN_ALPHA_RATIO = 0.25  # At least 25% alphabetic chars for text fields
_PURE_TEXT_KEYS = {
    "nombre", "nombres", "apellido_paterno", "apellido_materno",
    "primer_apellido", "segundo_apellido", "titular", "nombre_empresa",
    "juez", "registro_civil", "domicilio", "cliente",
    "regimen", "denominacion",
}


def _is_garbage_value(key: str, value: str) -> bool:
    """Return True if the value looks like OCR garbage that should be dropped."""
    if not value or not value.strip():
        return True
    v = value.strip()
    # Control characters / binary junk
    if _GARBAGE_PATTERN.search(v):
        return True
    # Extremely short values for text fields (single char noise)
    if key in _PURE_TEXT_KEYS and len(v) < 2:
        return True
    # Text fields must have a minimum ratio of alphabetic characters
    if key in _PURE_TEXT_KEYS:
        alpha = sum(1 for ch in v if ch.isalpha())
        if len(v) > 3 and alpha / max(len(v), 1) < _MIN_ALPHA_RATIO:
            return True
    return False


def _postprocess_fields(document_type: str, fields: list[dict]) -> list[dict]:
    """Drop low-confidence, invalid, and garbage fields before output."""
    cleaned = []
    drop_low = _LOW_CONF_DROP_BY_TYPE.get(document_type, set())
    drop_invalid = _INVALID_DROP_BY_TYPE.get(document_type, set())
    for field in fields:
        key = str(field.get("key", ""))
        if key == "texto_detectado":
            cleaned.append(field)
            continue
        # Drop low-confidence fields per document type
        if key in drop_low and field.get("confidence", 1) < 0.7:
            continue
        # Drop structurally invalid fields per document type
        if key in drop_invalid and field.get("valid") is False:
            continue
        # Strip stray control characters from surviving values
        value = str(field.get("value", "") or "")
        sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', value).strip()
        if sanitized != value:
            field = {**field, "value": sanitized}
        # Drop OCR garbage values (control chars, nonsense text)
        if _is_garbage_value(key, sanitized):
            logger.debug("Dropping garbage field %s=%r", key, sanitized[:50])
            continue
        cleaned.append(field)
    # ── Cross-field coherence checks ────────────────────────────────────
    cleaned = _apply_cross_field_checks(cleaned)
    return cleaned


# ── Cross-field coherence validation ───────────────────────────────────────
def _extract_date_from_curp(curp: str) -> str | None:
    """Extract YYMMDD date fragment from a CURP string (positions 4-9)."""
    if not curp or len(curp) < 10:
        return None
    fragment = curp[4:10]
    if not fragment.isdigit():
        return None
    return fragment  # e.g. "850101" = 1985-01-01


def _extract_date_from_rfc(rfc: str) -> str | None:
    """Extract YYMMDD date fragment from an RFC string (positions 4-9 for personas físicas)."""
    if not rfc or len(rfc) < 10:
        return None
    fragment = rfc[4:10]
    if not fragment.isdigit():
        return None
    return fragment


def _normalize_date_to_yymmdd(date_str: str) -> str | None:
    """Convert common date formats (DD/MM/YYYY, YYYY-MM-DD, DD-MM-YY, etc.) to YYMMDD."""
    if not date_str:
        return None
    cleaned = re.sub(r"[^\d/\-]", "", date_str.strip())
    patterns = [
        (r"(\d{2})/(\d{2})/(\d{4})", lambda m: m.group(3)[2:] + m.group(2) + m.group(1)),
        (r"(\d{2})-(\d{2})-(\d{4})", lambda m: m.group(3)[2:] + m.group(2) + m.group(1)),
        (r"(\d{4})-(\d{2})-(\d{2})", lambda m: m.group(1)[2:] + m.group(2) + m.group(3)),
        (r"(\d{4})/(\d{2})/(\d{2})", lambda m: m.group(1)[2:] + m.group(2) + m.group(3)),
        (r"(\d{2})/(\d{2})/(\d{2})", lambda m: m.group(3) + m.group(2) + m.group(1)),
    ]
    for pattern, formatter in patterns:
        match = re.fullmatch(pattern, cleaned)
        if match:
            return formatter(match)
    return None


def _apply_cross_field_checks(fields: list[dict]) -> list[dict]:
    """Flag fields that are internally inconsistent with each other.

    Cross-checks implemented:
    1. CURP date ↔ fecha_nacimiento
    2. RFC date ↔ fecha_nacimiento
    3. CURP initials ↔ nombre (already done in INE extractor, now generalized)
    4. RFC initials ↔ nombre
    """
    field_map: dict[str, dict] = {}
    for f in fields:
        key = str(f.get("key", ""))
        if key and key not in field_map:
            field_map[key] = f

    curp_val = str(field_map.get("curp", {}).get("value", "") or "").upper()
    rfc_val = str(field_map.get("rfc", {}).get("value", "") or "").upper()
    fecha_val = str(field_map.get("fecha_nacimiento", {}).get("value", "") or "")
    nombre_val = str(field_map.get("nombre", {}).get("value", "") or "").upper()

    warnings_added: list[str] = []

    # 1. CURP date ↔ fecha_nacimiento
    if curp_val and fecha_val:
        curp_date = _extract_date_from_curp(curp_val)
        fecha_yymmdd = _normalize_date_to_yymmdd(fecha_val)
        if curp_date and fecha_yymmdd and curp_date != fecha_yymmdd:
            if "fecha_nacimiento" in field_map:
                f = field_map["fecha_nacimiento"]
                f["confidence"] = round(min(float(f.get("confidence", 0.7)), 0.55), 4)
                errors = f.get("validation_errors", [])
                errors.append(f"Fecha no coincide con CURP ({curp_date} vs {fecha_yymmdd})")
                f["validation_errors"] = errors
                warnings_added.append("curp_fecha")

    # 2. RFC date ↔ fecha_nacimiento
    if rfc_val and len(rfc_val) >= 12 and fecha_val:
        rfc_date = _extract_date_from_rfc(rfc_val)
        fecha_yymmdd = _normalize_date_to_yymmdd(fecha_val)
        if rfc_date and fecha_yymmdd and rfc_date != fecha_yymmdd:
            if "fecha_nacimiento" in field_map and "curp_fecha" not in warnings_added:
                f = field_map["fecha_nacimiento"]
                f["confidence"] = round(min(float(f.get("confidence", 0.7)), 0.55), 4)
                errors = f.get("validation_errors", [])
                errors.append(f"Fecha no coincide con RFC ({rfc_date} vs {fecha_yymmdd})")
                f["validation_errors"] = errors

    # 3. CURP initials ↔ nombre (generalized for all doc types)
    if curp_val and len(curp_val) >= 4 and nombre_val and len(nombre_val) >= 3:
        if not _name_matches_curp(nombre_val, curp_val):
            if "nombre" in field_map:
                f = field_map["nombre"]
                f["confidence"] = round(min(float(f.get("confidence", 0.7)), 0.6), 4)
                errors = f.get("validation_errors", [])
                errors.append("Nombre no coincide con iniciales de CURP")
                f["validation_errors"] = errors

    # 4. RFC initials ↔ nombre
    if rfc_val and len(rfc_val) >= 4 and nombre_val and len(nombre_val) >= 3:
        rfc_init_paterno = rfc_val[0]
        rfc_init_nombre = rfc_val[3] if len(rfc_val) >= 4 else ""
        tokens = [t for t in nombre_val.split() if t]
        if len(tokens) >= 2 and rfc_init_nombre:
            has_paterno = any(t[0] == rfc_init_paterno for t in tokens)
            has_nombre = any(t[0] == rfc_init_nombre for t in tokens)
            if not (has_paterno and has_nombre):
                if "nombre" in field_map:
                    f = field_map["nombre"]
                    current_conf = float(f.get("confidence", 0.7))
                    # Only penalize if not already penalized by CURP check
                    if current_conf > 0.55:
                        f["confidence"] = round(min(current_conf, 0.6), 4)
                        errors = f.get("validation_errors", [])
                        errors.append("Nombre no coincide con iniciales de RFC")
                        f["validation_errors"] = errors

    return fields


def _label_key(text: str) -> str:
    text = text.upper()
    text = text.replace("0", "O").replace("1", "I").replace("5", "S").replace("8", "B")
    return re.sub(r"[^A-Z0-9]", "", text)


def _label_key_no_vowels(text: str) -> str:
    return re.sub(r"[AEIOU]", "", _label_key(text))


def _expand_label_list(label):
    if isinstance(label, (list, tuple, set)):
        labels = []
        for item in label:
            labels.extend(_expand_label_list(item))
        return labels
    return _merge_aliases(label)


def _label_match(line_text: str, label: str) -> bool:
    label_key = _label_key(label)
    line_key = _label_key(line_text)
    if label_key and label_key in line_key:
        return True
    label_nv = _label_key_no_vowels(label)
    line_nv = _label_key_no_vowels(line_text)
    return bool(label_nv and label_nv in line_nv)


def _bbox_to_rect(bbox):
    if not bbox:
        return None
    xs = [point[0] for point in bbox]
    ys = [point[1] for point in bbox]
    return min(xs), min(ys), max(xs), max(ys)


def _boxes_with_rect(ocr_boxes):
    boxed = []
    for box in ocr_boxes or []:
        rect = _bbox_to_rect(box.get("bbox", []))
        if rect is None:
            continue
        boxed.append({**box, "rect": rect})
    return boxed


def _line_groups(boxes, y_tol=12):
    """Agrupa boxes en líneas por proximidad en Y.

    Cuando los boxes tienen el campo "page" (documentos multi-página),
    se respeta la frontera de página: celdas de páginas distintas nunca
    se mezclan en la misma línea, evitando que filas de tabla de diferentes
    páginas a la misma coordenada Y se fundan en un único grupo.
    """
    lines = []
    # Ordena por (página, Y, X) para procesar cada página en secuencia
    for box in sorted(boxes, key=lambda b: (b.get("page") or 0, b["rect"][1], b["rect"][0])):
        x1, y1, x2, y2 = box["rect"]
        page = box.get("page") or 0
        placed = False
        for line in lines:
            if (line.get("page") or 0) != page:
                continue
            ly = line["y"]
            if abs(y1 - ly) <= y_tol:
                line["boxes"].append(box)
                line["y"] = (ly + y1) / 2
                placed = True
                break
        if not placed:
            lines.append({"y": y1, "page": page, "boxes": [box]})
    for line in lines:
        line["boxes"].sort(key=lambda b: b["rect"][0])
        line["text"] = " ".join(b.get("text", "").strip() for b in line["boxes"] if b.get("text"))
        line["text_norm"] = _normalize_keyword(line["text"])
    return lines


def _lines_text_from_boxes(ocr_boxes, y_tol: int = 12):
    boxes = _boxes_with_rect(ocr_boxes)
    lines = _line_groups(boxes, y_tol=y_tol)
    return lines


def _normalize_table_cell(text: str) -> str:
    cell = _normalize_text(str(text or "")).upper()
    if not cell or cell == "NAN":
        return ""
    if len(cell) > 90:
        return cell[:90].rstrip() + "..."
    return cell


def _normalize_table_cell_exact(text: str) -> str:
    cell = _normalize_text(str(text or ""))
    if not cell:
        return ""
    if len(cell) > _GENERIC_TABLE_MAX_CELL_TEXT:
        return cell[:_GENERIC_TABLE_MAX_CELL_TEXT].rstrip()
    return cell


# ── Roman-numeral OCR correction ──────────────────────────────────────────────
# PaddleOCR frequently misreads the letter "I" as the digit "1", "l", or "|".
# This causes Roman numerals like III to appear as 111, I1, 1I, etc.
# These helpers detect and correct columns that contain Roman numerals.

_ROMAN_I_LIKE = frozenset("1IilL|")
_VALID_ROMAN_NUMERALS = {
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX",
}

# Column headers that strongly suggest Roman numeral content
_ROMAN_CONTEXT_KEYWORDS = {
    "semestre", "nivel", "grado", "periodo", "trimestre", "capitulo",
    "fase", "etapa", "ciclo", "modulo", "bloque", "unidad", "seccion",
    "volumen", "tomo", "parte",
}


def _fix_roman_numeral_cell(text: str) -> str:
    """Convert an OCR-misread Roman numeral back to proper form.

    Examples:
        "111" → "III", "11" → "II", "1" → "I", "I1" → "II", "1I" → "II"
        "1V" → "IV", "V1" → "VI", "V111" → "VIII"
    """
    s = text.strip()
    if not s:
        return text

    # Normalise each character: I-like → I, keep V/X as-is
    normalised = []
    for c in s:
        if c in _ROMAN_I_LIKE:
            normalised.append("I")
        elif c.upper() in ("V", "X"):
            normalised.append(c.upper())
        else:
            return text  # Contains non-Roman character → leave untouched
    roman = "".join(normalised)

    if roman in _VALID_ROMAN_NUMERALS:
        return roman
    return text


def _is_roman_numeral_column(values: list[str], header: str = "") -> bool:
    """Check if a column predominantly contains Roman numeral-like values.

    A column is considered Roman if:
    - The header matches a known context keyword (semestre, nivel, etc.), OR
    - At least 60% of non-empty data values look like misread Roman numerals
      (composed only of 1, I, l, |, V, X characters) and are 1-5 chars long.
    """
    header_lower = header.strip().lower()
    header_match = any(kw in header_lower for kw in _ROMAN_CONTEXT_KEYWORDS)

    non_empty = [v.strip() for v in values if v.strip()]
    if not non_empty:
        return header_match  # If header matches but no data, still apply

    roman_like = 0
    for v in non_empty:
        if len(v) > 5:
            continue  # Roman numerals up to XX are at most 5 chars
        if all(c in _ROMAN_I_LIKE or c.upper() in ("V", "X") for c in v):
            roman_like += 1

    # Require majority of values to look Roman, or header context match
    ratio = roman_like / len(non_empty) if non_empty else 0
    if header_match and roman_like >= 1:
        return True
    return ratio >= 0.6 and roman_like >= 2


def _apply_roman_numeral_correction(rows: list[list[str]]) -> list[list[str]]:
    """Apply column-level Roman numeral correction to table rows.

    For each column, if the data values look like misread Roman numerals,
    convert all matching cells to proper Roman form.

    Smart header detection: row[0] is only treated as a true header (and
    skipped) if it contains a recognised context keyword (SEMESTRE, NIVEL,
    etc.).  Otherwise row[0] is treated as data and corrected too.
    """
    if len(rows) < 2:
        return rows

    num_cols = max((len(r) for r in rows), default=0)
    if num_cols == 0:
        return rows

    # Check each column independently
    for col_idx in range(num_cols):
        # Gather header and data values
        header = rows[0][col_idx] if col_idx < len(rows[0]) else ""
        data_values = [
            r[col_idx] if col_idx < len(r) else ""
            for r in rows[1:]
        ]

        if not _is_roman_numeral_column(data_values, header):
            continue

        # Determine if row[0] is a real header or data.
        # A real header has a context keyword; otherwise row[0] is data too.
        header_lower = header.strip().lower()
        row0_is_header = any(kw in header_lower for kw in _ROMAN_CONTEXT_KEYWORDS)

        start_row = 1 if row0_is_header else 0
        for row_idx in range(start_row, len(rows)):
            if col_idx < len(rows[row_idx]):
                rows[row_idx][col_idx] = _fix_roman_numeral_cell(
                    rows[row_idx][col_idx]
                )

    return rows


def _table_rows_signature(rows: list[list[str]]) -> str:
    parts: list[str] = []
    for row in rows[:6]:
        if not isinstance(row, list):
            continue
        key = "|".join(_normalize_keyword(str(cell or "")) for cell in row[:8])
        if key:
            parts.append(key)
    return "||".join(parts)


def _looks_like_payment_table_header(cells: list[str]) -> bool:
    joined = " ".join(cells)
    hits = sum(1 for token in _PAYMENT_TABLE_HEADER_TOKENS if token in joined)
    return hits >= 2


def _looks_like_payment_table_data(cells: list[str]) -> bool:
    joined = " ".join(cells)
    has_amount = bool(re.search(r"\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\b", joined))
    long_numeric_cells = sum(1 for cell in cells if len(re.sub(r"\D", "", cell)) >= 8)
    has_status = any(token in joined for token in _PAYMENT_TABLE_STATUS_TOKENS)
    return (
        (has_amount and long_numeric_cells >= 1)
        or (has_status and long_numeric_cells >= 1)
        or (long_numeric_cells >= 2 and len(cells) >= 4)
    )


def _is_payment_table_footer(cells: list[str]) -> bool:
    joined = " ".join(cells)
    if "TOTAL" not in joined:
        return False
    return any(token in joined for token in ("MOVIMIENTO", "MOVIMIENTOS", "REGISTROS", "IMPORTE"))


def _normalize_payment_datetime(value: str) -> str:
    raw = _normalize_text(str(value or ""))
    if not raw:
        return ""
    upper = _ascii_fold(raw).upper()
    if "SIN FECHA" in upper:
        return "SIN FECHA Y HORA DE REGISTRO"
    date_match = re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", upper)
    time_match = re.search(r"\d{2}:\d{2}(?::\d{2})?", upper)
    if date_match and time_match:
        normalized_date = _normalize_date_value(date_match.group(0))
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", normalized_date):
            return f"{normalized_date} {time_match.group(0)}"
    if date_match:
        normalized_date = _normalize_date_value(date_match.group(0))
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", normalized_date):
            return normalized_date
    return raw


def _normalize_payment_amount(value: str) -> str:
    text = _normalize_text(str(value or "")).upper()
    if not text:
        return ""
    # Find the numeric token FIRST, then apply OCR corrections only within it
    match = re.search(r"\$?\s*([0-9OIL][0-9OIL.,]{1,24})", text)
    if not match:
        return ""
    token = match.group(1)
    token = token.replace("O", "0").replace("I", "1").replace("L", "1")
    match = re.search(r"(\d[\d.,]{1,24})", token)
    if not match:
        return ""
    token = match.group(1)
    token = re.sub(r"[^\d.,]", "", token)
    if not token:
        return ""
    decimal_sep = None
    if "." in token and "," in token:
        decimal_sep = "." if token.rfind(".") > token.rfind(",") else ","
    elif token.count(".") == 1 and len(token.split(".")[-1]) == 2:
        decimal_sep = "."
    elif token.count(",") == 1 and len(token.split(",")[-1]) == 2:
        decimal_sep = ","

    if decimal_sep:
        integer_raw, cents_raw = token.rsplit(decimal_sep, 1)
        integer_digits = re.sub(r"\D", "", integer_raw)
        cents_digits = re.sub(r"\D", "", cents_raw)
        if not integer_digits:
            return ""
        cents = (cents_digits + "00")[:2]
        return f"{int(integer_digits):,}.{cents}"

    integer_digits = re.sub(r"\D", "", token)
    if not integer_digits:
        return ""
    return f"{int(integer_digits):,}.00"


def _normalize_payment_count(value: str) -> str:
    raw = _normalize_numeric_field(str(value or ""))
    if not raw:
        return ""
    if len(raw) > 6:
        return raw[:6]
    return str(int(raw))


# ── Level 3: OCR quality assessment ────────────────────────────────────────

def _assess_ocr_quality(ocr_text: str, ocr_boxes: list[dict] | None = None) -> dict[str, Any]:
    """Assess the quality of the OCR output.

    Returns a dict with:
      - score: float 0.0–1.0 (1.0 = perfect)
      - warnings: list[str] of quality issues detected
      - metrics: dict with detailed quality metrics
    """
    result: dict[str, Any] = {
        "score": 1.0,
        "warnings": [],
        "metrics": {},
    }

    text = str(ocr_text or "")
    if not text.strip():
        result["score"] = 0.0
        result["warnings"].append("Texto OCR vacío — documento posiblemente en blanco o ilegible")
        return result

    total_chars = len(text)
    penalties: list[float] = []

    # ── Metric 1: Character composition ──────────────────────────────────
    alpha_count = sum(1 for ch in text if ch.isalpha())
    digit_count = sum(1 for ch in text if ch.isdigit())
    space_count = sum(1 for ch in text if ch.isspace())
    printable_count = alpha_count + digit_count + space_count
    # Punctuation and common symbols are acceptable
    common_punct = sum(1 for ch in text if ch in ".,;:!?/$%-()[]{}\"'@#&*+=<>_|~\\^`")
    clean_count = printable_count + common_punct
    noise_count = total_chars - clean_count
    noise_ratio = noise_count / max(total_chars, 1)

    result["metrics"]["total_chars"] = total_chars
    result["metrics"]["alpha_ratio"] = round(alpha_count / max(total_chars, 1), 3)
    result["metrics"]["noise_ratio"] = round(noise_ratio, 3)

    if noise_ratio > 0.15:
        penalties.append(0.3)
        result["warnings"].append(
            f"Alto nivel de ruido OCR: {noise_ratio:.0%} caracteres no reconocibles"
        )
    elif noise_ratio > 0.08:
        penalties.append(0.15)
        result["warnings"].append(
            f"Nivel moderado de ruido OCR: {noise_ratio:.0%} caracteres no reconocibles"
        )

    # ── Metric 2: Line quality — very short lines often indicate garbled OCR
    lines = [line for line in text.splitlines() if line.strip()]
    if lines:
        avg_line_len = sum(len(line) for line in lines) / len(lines)
        very_short = sum(1 for line in lines if len(line.strip()) < 3)
        short_ratio = very_short / max(len(lines), 1)
        result["metrics"]["avg_line_length"] = round(avg_line_len, 1)
        result["metrics"]["very_short_line_ratio"] = round(short_ratio, 3)

        if short_ratio > 0.4 and len(lines) > 5:
            penalties.append(0.2)
            result["warnings"].append(
                f"Muchas líneas muy cortas ({short_ratio:.0%}): posible OCR fragmentado"
            )

    # ── Metric 3: Repeated character sequences (OCR stutter) ─────────────
    stutter_matches = re.findall(r"(.)\1{4,}", text)
    if len(stutter_matches) > 2:
        penalties.append(0.15)
        result["warnings"].append(
            f"Repeticiones excesivas de caracteres detectadas ({len(stutter_matches)} ocurrencias)"
        )
    result["metrics"]["stutter_sequences"] = len(stutter_matches)

    # ── Metric 4: Confidence from OCR boxes ──────────────────────────────
    if ocr_boxes:
        confidences = []
        for box in ocr_boxes:
            conf = box.get("confidence")
            if conf is not None:
                try:
                    confidences.append(float(conf))
                except (ValueError, TypeError):
                    pass
        if confidences:
            avg_conf = sum(confidences) / len(confidences)
            low_conf_count = sum(1 for c in confidences if c < 0.6)
            low_conf_ratio = low_conf_count / len(confidences)
            result["metrics"]["avg_box_confidence"] = round(avg_conf, 3)
            result["metrics"]["low_conf_box_ratio"] = round(low_conf_ratio, 3)

            if avg_conf < 0.5:
                penalties.append(0.3)
                result["warnings"].append(
                    f"Confianza OCR promedio muy baja: {avg_conf:.2f}"
                )
            elif avg_conf < 0.7:
                penalties.append(0.15)
                result["warnings"].append(
                    f"Confianza OCR promedio baja: {avg_conf:.2f}"
                )

            if low_conf_ratio > 0.3:
                penalties.append(0.1)
                result["warnings"].append(
                    f"{low_conf_ratio:.0%} de cajas con confianza < 0.6"
                )

    # ── Metric 5: Recognizable structure (dates, amounts, IDs) ───────────
    structure_hits = 0
    if re.search(r"\d{2}/\d{2}/\d{4}", text):
        structure_hits += 1
    if re.search(r"\$[\d,]+\.\d{2}", text):
        structure_hits += 1
    if CURP_PATTERN.search(text.upper()):
        structure_hits += 1
    if RFC_WITH_HOMOCLAVE.search(text.upper()):
        structure_hits += 1
    if re.search(r"\b\d{10,18}\b", text):
        structure_hits += 1

    result["metrics"]["structure_hits"] = structure_hits
    if structure_hits == 0 and total_chars > 200:
        penalties.append(0.1)
        result["warnings"].append(
            "No se detectaron patrones estructurados (fechas, montos, IDs) en el texto"
        )

    # ── Final score ──────────────────────────────────────────────────────
    total_penalty = min(sum(penalties), 0.95)  # never go below 0.05
    result["score"] = round(1.0 - total_penalty, 3)

    return result


def _extract_label_value(
    lines: list[dict],
    label: str,
    stop_labels: list[str] | None = None,
    value_regex: re.Pattern[str] | None = None,
) -> str | None:
    line = _find_label_line(lines, label)
    if not line:
        return None
    right = _value_right_of_label(line, label)
    if right:
        candidate = right.get("text", "").strip()
        if value_regex is None or value_regex.search(candidate):
            return candidate
    labels = _expand_label_list(label)
    line_text = line.get("text", "")
    for alias in labels:
        tokens = [tok for tok in alias.strip().split() if tok]
        if not tokens:
            continue
        pattern = r"(?i)" + r"\\s*".join(re.escape(tok) for tok in tokens) + r"\\s*[:\\-]?\\s*(.+)$"
        match = re.search(pattern, line_text)
        if match:
            candidate = match.group(1).strip()
            if candidate and (value_regex is None or value_regex.search(candidate)):
                return candidate
    if stop_labels is None:
        stop_labels = []
    below = _collect_below(lines, line, stop_labels, max_lines=1)
    if below:
        candidate = below[0]["text"].strip()
        if value_regex is None or value_regex.search(candidate):
            return candidate
    return None


def _find_label_line(lines, label):
    labels = _expand_label_list(label)
    for line in lines:
        for alias in labels:
            if _label_match(line["text"], alias):
                return line
    return None


def _value_right_of_label(line, label, min_gap=5):
    labels = _expand_label_list(label)
    for box in line["boxes"]:
        box_text = box.get("text", "")
        if any(_label_match(box_text, alias) for alias in labels):
            label_rect = box["rect"]
            candidates = []
            for other in line["boxes"]:
                if other is box:
                    continue
                ox1, oy1, ox2, oy2 = other["rect"]
                if ox1 >= label_rect[2] + min_gap:
                    candidates.append(other)
            if not candidates:
                return None
            best = sorted(candidates, key=lambda b: b["rect"][0])[0]
            return best
    return None


def _collect_below(lines, start_line, stop_labels, max_lines=3):
    expanded = []
    for label in stop_labels:
        expanded.extend(_expand_label_list(label))
    stop_norm = {_label_key(lbl) for lbl in expanded}
    collected = []
    started = False
    for line in lines:
        if line is start_line:
            started = True
            continue
        if not started:
            continue
        line_key = _label_key(line["text"])
        if line_key in stop_norm or any(lbl in line_key for lbl in stop_norm):
            break
        collected.append(line)
        if len(collected) >= max_lines:
            break
    return collected


def _normalize_sex(value: str) -> str:
    value = value.strip().upper()
    if value in {"H", "HOMBRE", "MASCULINO"}:
        return "H"
    if value in {"M", "MUJER", "FEMENINO"}:
        return "M"
    return value


def _normalize_date_value(value: str) -> str:
    raw = _normalize_text(str(value or ""))
    if not raw:
        return ""
    upper = (
        raw.upper()
        .replace(".", " ")
        .replace(",", " ")
        .replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
    )

    def _fix_ocr_digits(token: str) -> str:
        return token.upper().replace("O", "0").replace("I", "1").replace("L", "1")

    numeric = re.search(
        r"([0-9OIL]{1,2})\s*(?:[/-]|[^0-9A-Z]+)\s*([0-9OIL]{1,2})\s*(?:[/-]|[^0-9A-Z]+)\s*([0-9OIL]{2,4})",
        upper,
    )
    if numeric:
        day, month, year = numeric.groups()
        day_i = int(_fix_ocr_digits(day))
        month_i = int(_fix_ocr_digits(month))
        year_i = int(_fix_ocr_digits(year))
        if len(year) == 2:
            year_i = 2000 + year_i
        if 1 <= day_i <= 31 and 1 <= month_i <= 12:
            return f"{day_i:02d}/{month_i:02d}/{year_i:04d}"

    month_map = {
        "ENE": "01",
        "FEB": "02",
        "MAR": "03",
        "ABR": "04",
        "MAY": "05",
        "JUN": "06",
        "JUL": "07",
        "AGO": "08",
        "SEP": "09",
        "SET": "09",
        "OCT": "10",
        "NOV": "11",
        "DIC": "12",
        "JAN": "01",
        "APR": "04",
        "AUG": "08",
        "DEC": "12",
    }
    textual = re.search(
        r"([0-9OIL]{1,2})\s*(?:[-/]|[^0-9A-Z]+)\s*([A-Z]{3,9})\s*(?:[-/]|[^0-9A-Z]+)\s*([0-9OIL]{2,4})",
        upper,
    )
    if textual:
        day, month_token, year = textual.groups()
        month = month_map.get(month_token[:3])
        if month:
            day_i = int(_fix_ocr_digits(day))
            year_i = int(_fix_ocr_digits(year))
            if len(year) == 2:
                year_i = 2000 + year_i
            if 1 <= day_i <= 31:
                return f"{day_i:02d}/{month}/{year_i:04d}"

    return raw


def _normalize_alnum(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _normalize_name(value: str) -> str:
    value = _normalize_text(value)
    return value.upper()


def _split_compact_given_names(value: str) -> str:
    compact = _normalize_alnum(value)
    if not compact:
        return ""
    known_pairs = {
        "JOSEALEJANDRO": "JOSE ALEJANDRO",
        "MARIAJOSE": "MARIA JOSE",
        "JOSELUIS": "JOSE LUIS",
        "JUANCARLOS": "JUAN CARLOS",
        "MIGUELANGEL": "MIGUEL ANGEL",
        "LUISFERNANDO": "LUIS FERNANDO",
        "ERWINGUSTAVO": "ERWIN GUSTAVO",
    }
    for key, spaced in known_pairs.items():
        if compact == key:
            return spaced
    return compact


def _split_compact_surnames(value: str) -> str:
    token = _normalize_alnum(value)
    if len(token) < 8:
        return token

    def _vowel_ratio(part: str) -> float:
        letters = [ch for ch in part if ch.isalpha()]
        if not letters:
            return 0.0
        vowels = sum(1 for ch in letters if ch in "AEIOU")
        return vowels / len(letters)

    best_split = None
    best_score = None
    for i in range(4, len(token) - 3):
        left = token[:i]
        right = token[i:]
        score = abs(len(left) - len(right)) * 0.1
        score += abs(_vowel_ratio(left) - 0.4)
        score += abs(_vowel_ratio(right) - 0.4)
        common_endings = ("EZ", "ES", "ON", "OS", "AS", "IA", "VA", "RA", "DO", "ZA", "GA", "NA")
        if left.endswith(common_endings):
            score -= 0.15
        if right.startswith("N") and left.endswith(("A", "E", "I", "O", "U")):
            score += 0.12
        if best_score is None or score < best_score:
            best_score = score
            best_split = (left, right)

    if not best_split:
        return token
    return f"{best_split[0]} {best_split[1]}"


def _normalize_address(value: str) -> str:
    value = _normalize_text(value)
    replacements = {
        "AV.": "AV ",
        "AVENIDA": "AV ",
        "C.P.": "CP ",
        "CODIGO POSTAL": "CP ",
        "COL.": "COL ",
        "COLONIA": "COL ",
        "FRACC.": "FRACC ",
        "FRACCIONAMIENTO": "FRACC ",
        "MUNICIPIO": "MUN ",
        "ESTADO": "EDO ",
    }
    upper = value.upper()
    for key, repl in replacements.items():
        upper = upper.replace(key, repl)
    return upper


def _clean_address_value(value: str) -> str:
    if not value:
        return value
    upper = _normalize_address(value)
    upper = re.sub(r"\bCFE\s+COMISION\s+FEDERAL\s+DE\s+ELECTRICIDAD\b", " ", upper)
    upper = re.sub(r"\bCOMISION\s+FEDERAL\s+DE\s+ELECTRICIDAD\b", " ", upper)
    upper = re.sub(r"\bRMU[:\s-].*$", " ", upper)
    upper = re.sub(r"\$\s*\d{1,5}(?:[.,]\d{2})?(?:\s+\d{1,3})*", " ", upper)
    upper = re.sub(r"\([^)]{0,200}\)", " ", upper)
    upper = re.sub(r"\bDESCARGA\s+NUESTRA\b.*$", " ", upper)
    # Remove leading payment/amount fragments that OCR sometimes merges into CFE address lines.
    upper = re.sub(r"^\s*\$\s*\d{1,5}(?:[.,]\d{2})?(?:\s+\d{1,3})*\s+", "", upper)
    upper = re.sub(
        r"^\s*\d{3,5}\s+\d{1,3}\s+(?=(?:DN\.?|DEPTO|DEPARTAMENTO|CALLE|CLL|AV|COL|BENITO|MZ|LT|NO\.?|NUM|KM)\b)",
        "",
        upper,
    )
    upper = upper.replace("DOMICILIO", " ")
    upper = re.sub(r"^\s*DE\s+SUMINISTRO\b", " ", upper)
    # Strip leading dashes/hyphens that OCR sometimes prepends
    upper = re.sub(r"^[\s\-]+", "", upper)
    upper = re.sub(r"\bAV(?=[A-Z])", "AV ", upper)
    upper = re.sub(r"\bFCP\b", "CP", upper)
    upper = re.sub(r"([A-Z])S/N\b", r"\1 S/N", upper)
    upper = re.sub(r"\bLOC([A-Z]{3,})\b", r"LOC \1", upper)
    upper = re.sub(r"\bLOC([A-Z]{2,})\b", r"LOC \1", upper)
    upper = re.sub(r"\bLOC([A-Z]{2,})(\d{5})\b", r"LOC \1 \2", upper)
    upper = re.sub(r"\bLOC\s*([A-Z]+)(\d{5})\b", r"LOC \1 \2", upper)
    # Fix OCR-merged ordinal+SECCION: "2DASECCION" or "2 DASECCION" → "2DA SECCION"
    upper = re.sub(r"\b(\d+)\s*DASECCION\b", r"\1DA SECCION", upper)
    upper = re.sub(r"\bDASECCION\b", "DA SECCION", upper)
    # Fix OCR-merged tokens with RIA prefix (e.g. "RIAZAPOTAL" → "RIA ZAPOTAL")
    upper = re.sub(r"\bRIA([A-Z]{4,})\b", r"RIA \1", upper)
    # Fix BENITO merges (e.g. "BENITOJUAR" → "BENITO JUAR", "BENITOJUAREZ" → "BENITO JUAREZ")
    upper = re.sub(r"\bBENITO([A-Z]{3,})\b", r"BENITO \1", upper)
    # Fix SSL prefix merges (e.g. "SSLBENITOJUAREZ" → "SSL BENITO JUAREZ")
    upper = re.sub(r"\bSSL\.?([A-Z]{3,})\b", r"SSL \1", upper)
    upper = re.sub(r"(?<=\D)(?=\d)", " ", upper)
    upper = re.sub(r"(?<=\d)(?=\D)", " ", upper)
    # Normalize common OCR merges for address tokens
    upper = re.sub(r"\bCOL([A-Z]{3,})\b", r"COL \1", upper)
    upper = re.sub(r"\bCARRDE\b", "CARR DE", upper)
    upper = re.sub(r"\bCARRDEL\b", "CARR DEL", upper)
    upper = re.sub(r"\bCARRDEL([A-Z]{2,})\b", r"CARR DEL \1", upper)
    upper = re.sub(r"\bCARRDEL([A-Z]{2,})S/N\b", r"CARR DEL \1 S/N", upper)
    upper = re.sub(r"\bCARR DE L([A-Z]{2,})\b", r"CARR DEL \1", upper)
    upper = re.sub(r"\bAVENIDA\b", "AV", upper)
    upper = re.sub(r"\bCARRETERA\b", "CARR", upper)
    upper = re.sub(r"\bCAMP\.\b", "CAMP", upper)
    upper = upper.replace(",", " ")
    upper = re.sub(r"\bGOLFOS/N\b", "GOLFO S/N", upper)
    noise = {
        "INSTITUTO",
        "NACIONAL",
        "ELECTORAL",
        "CREDENCIAL",
        "PARA",
        "VOTAR",
        "NOMBRE",
        "SEXO",
        "CURP",
        "FECHA",
        "CLAVE",
        "ELECTOR",
    }
    allowed_keywords = {
        "CALLE", "CARR", "AV", "COL", "FRACC", "CP", "MUN", "EDO", "KM",
        "S/N", "NUM", "NO.", "LOC", "SECCION",
    }
    vowels = set("AEIOU")
    tokens = []
    for tok in upper.split():
        if tok in {"$", "MXN", "M.N.", "M.N", "MN"}:
            continue
        if not re.search(r"[A-Z0-9/]", tok):
            continue
        if tok in noise:
            continue
        if any(fragment in tok for fragment in ("INSTI", "ELECT", "CREDEN", "VOTAR")):
            continue
        if tok in allowed_keywords:
            tokens.append(tok)
            continue
        if any(ch.isdigit() for ch in tok) or "/" in tok:
            tokens.append(tok)
            continue
        letters = [ch for ch in tok if ch.isalpha()]
        if letters:
            vowel_count = sum(1 for ch in letters if ch in vowels)
            vowel_ratio = vowel_count / len(letters)
            consonant_ratio = (len(letters) - vowel_count) / len(letters)
            # Drop OCR garbage tokens with very low vowel ratio
            if vowel_ratio < 0.2 and len(letters) >= 6:
                continue
            if vowel_ratio < 0.3 and len(letters) >= 10:
                continue
            if vowel_count <= 2 and len(letters) >= 12:
                continue
            if re.search(r"[BCDFGHJKLMNPQRSTVWXYZ]{4,}", tok) and len(letters) >= 7:
                continue
            if vowel_count == 0 and len(letters) >= 5:
                continue
            if consonant_ratio >= 0.75 and len(letters) >= 8:
                continue
        tokens.append(tok)
    cleaned = " ".join(tokens)
    cleaned = cleaned.replace(" ,", ",").replace("  ", " ").strip()
    # Remove trailing junk tokens that are unlikely in address
    cleaned = re.sub(r"\b(ONKEECTDRA|EDUNGSJACGSOACLNA|STTUTON)\b", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _normalize_vigencia(value: str) -> str:
    value = value.strip().upper().replace("-", "/")
    year_range = re.search(r"(\d{4}\s*/\s*\d{4})", value)
    if year_range:
        return year_range.group(1).replace(" ", "")
    years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", value)]
    if years:
        _max_vig_year = datetime.now().year + 30
        plausible = [year for year in years if 2020 <= year <= _max_vig_year]
        selected = max(plausible) if plausible else max(years)
        return str(selected)
    date_match = re.search(r"(\d{2}/\d{2}/(\d{4}))", value)
    if date_match:
        year = date_match.group(2)
        return _normalize_vigencia(year)
    return value


def _normalize_numeric_field(value: str) -> str:
    value = value.upper()
    value = value.replace("O", "0").replace("I", "1").replace("L", "1")
    return re.sub(r"\D", "", value)


def _normalize_cp_value(value: str) -> str:
    raw = _normalize_numeric_field(value)
    if len(raw) == 5:
        return raw
    if len(raw) > 5:
        return raw[:5]
    return ""


def _normalize_folio_value(value: str) -> str:
    text = str(value or "").upper()
    candidates = re.findall(r"[0-9OIL]{1,6}", text)
    # Avoid false positives from words that only contribute I/O noise.
    candidates = [c for c in candidates if re.search(r"\d", c)]
    if not candidates:
        return ""
    candidate = max(candidates, key=len)
    raw = _normalize_numeric_field(candidate)
    return raw if re.fullmatch(r"\d{1,6}", raw) else ""


def _normalize_numero_acta_value(value: str) -> str:
    text = str(value or "").upper().strip()
    if not text:
        return ""
    # Ignore label-like OCR noise such as "DE NACIMIENTO".
    if not re.search(r"\d", text):
        return ""
    if re.search(r"\d", text) or re.fullmatch(r"[0-9OIL\s-]+", text):
        raw = _normalize_numeric_field(text)
        if re.fullmatch(r"\d{1,12}", raw):
            return raw
    normalized = _normalize_alnum(text)
    digit_count = sum(1 for ch in normalized if ch.isdigit())
    return normalized if len(normalized) >= 3 and digit_count >= 3 else ""


def _normalize_numero_certificado_value(value: str) -> str:
    text = str(value or "").upper().strip()
    if not text:
        return ""
    numeric = _normalize_numeric_field(text)
    if len(numeric) >= 6:
        return numeric
    alnum = _normalize_alnum(text)
    return alnum if len(alnum) >= 6 else ""


def _normalize_identificador_electronico_value(value: str) -> str:
    text = str(value or "").upper().strip()
    if not text:
        return ""
    alnum = _normalize_alnum(text)
    return alnum if len(alnum) >= 6 else ""


def _normalize_reference_value(value: str) -> str:
    text = str(value or "").upper().strip()
    if not text:
        return ""
    text_norm = _normalize_text(text).upper()
    if len(text_norm) >= 12 and any(marker in text_norm for marker in ("CALLE", "CLL", "AV", "COL", "DEPTO", "CIUDAD", "CP", "C.P.", "BENITO", "CARMEN")):
        return text_norm
    numeric = _normalize_numeric_field(text)
    if 10 <= len(numeric) <= 30:
        return numeric
    alnum = _normalize_alnum(text)
    digits = sum(1 for ch in alnum if ch.isdigit())
    if 10 <= len(alnum) <= 120 and digits >= 8:
        return alnum
    return ""


def _normalize_seccion_value(value: str) -> str:
    text = str(value or "").upper().replace("O", "0")
    raw = re.sub(r"\D", "", text)
    if not raw:
        return ""
    if re.fullmatch(r"\d{3,4}", raw):
        return raw
    trimmed = raw.lstrip("0")
    if re.fullmatch(r"\d{3,4}", trimmed):
        return trimmed
    return raw


FIELD_VALUE_NORMALIZERS = {
    "cp": _normalize_cp_value,
    "folio": _normalize_folio_value,
    "seccion": _normalize_seccion_value,
    "numero_acta": _normalize_numero_acta_value,
    "numero_certificado": _normalize_numero_certificado_value,
    "identificador_electronico": _normalize_identificador_electronico_value,
    "referencia": _normalize_reference_value,
}


def _normalize_value_for_key(key: str, value: str) -> str:
    normalizer = FIELD_VALUE_NORMALIZERS.get(str(key or ""))
    if normalizer is None:
        return str(value or "")
    return normalizer(str(value or ""))


def _is_curp_header_noise_name(value: str) -> bool:
    text = _normalize_name(value).upper()
    if not text:
        return False

    header_phrases = (
        "ESTADOS UNIDOS MEXICANOS",
        "CONSTANCIA DE LA CLAVE UNICA",
        "CLAVE UNICA DE REGISTRO DE POBLACION",
        "REGISTRO DE POBLACION",
        "GOBIERNO DE MEXICO",
        "RENAPO",
    )
    if any(phrase in text for phrase in header_phrases):
        return True

    tokens = [tok for tok in text.split() if tok]
    header_tokens = {
        "ESTADOS",
        "UNIDOS",
        "MEXICANOS",
        "CONSTANCIA",
        "CLAVE",
        "UNICA",
        "REGISTRO",
        "POBLACION",
        "RENAPO",
        "GOBIERNO",
        "MEXICO",
    }
    hits = sum(1 for tok in tokens if tok in header_tokens)
    return hits >= 4


def _clean_curp_name(value: str) -> str | None:
    if not value:
        return None
    cleaned = _normalize_text(value).upper()
    if not cleaned:
        return None

    cleaned = re.sub(r"^(?:NOMBRE(?:\(S\))?|NOMBRES)\s*[:\-]?\s*", "", cleaned)
    cleaned = re.sub(
        r"^(?:ESTADOS\s+UNIDOS\s+MEXICANOS\s+)?CONSTANCIA\s+DE\s+LA\s+CLAVE\s+UNICA(?:\s+DE\s+REGISTRO\s+DE\s+POBLACION)?\s*",
        "",
        cleaned,
    )
    cleaned = re.sub(r"^CLAVE\s+UNICA\s+DE\s+REGISTRO\s+DE\s+POBLACION\s*", "", cleaned)
    cleaned = re.split(r"\b(?:CURP|CLAVE|FECHA|SEXO|ENTIDAD|NACIMIENTO|REGISTRO)\b", cleaned)[0].strip(" :.-,")

    cleaned = re.sub(r"[^A-ZÑÁÉÍÓÚÜ ]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    if _is_curp_header_noise_name(cleaned):
        return None
    if not _looks_like_person_name(cleaned):
        return None
    return cleaned


def _normalize_field_value_for_contract(document_type: str, key: str, value: str) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    if key == "tabla_celdas":
        return raw.strip()
    if key == "pago_detalle":
        return raw.strip()
    if key == "replica_pdf_layout":
        return raw.strip()
    if key == "replica_pdf_texto":
        lines = [line.rstrip() for line in raw.replace("\r\n", "\n").split("\n")]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(lines).strip()
    if key in FIELD_VALUE_NORMALIZERS:
        return _normalize_value_for_key(key, raw)
    if key in {"curp", "rfc", "clave_elector", "id_cif"}:
        return _normalize_alnum(raw)
    if key in {"nss", "clabe", "cp", "seccion", "numero_servicio"}:
        return _normalize_numeric_field(raw)
    if key == "cuenta":
        return _normalize_alnum(raw)
    if key in {"fecha", "fecha_nacimiento", "fecha_registro", "fecha_limite", "fecha_corte", "fecha_emision", "fecha_documento"}:
        return _normalize_date_value(raw)
    if key in {"nombre", "titular", "nombres", "apellido_paterno", "apellido_materno", "primer_apellido", "segundo_apellido"}:
        if document_type == "NSS" and key == "nombre":
            cleaned_nss = _clean_nss_name(raw)
            if cleaned_nss:
                return _normalize_name(cleaned_nss)
            compact = _normalize_alnum(_normalize_text(raw))
            if re.fullmatch(r"[A-Z]{10,40}", compact):
                return _normalize_name(_split_compact_nss_token(compact))
        if document_type == "CURP" and key == "nombre":
            cleaned_curp = _clean_curp_name(raw)
            if cleaned_curp:
                return _normalize_name(cleaned_curp)
            return ""
        return _normalize_name(raw)
    if key == "sexo":
        return _normalize_sex(raw)
    if key == "lugar_nacimiento":
        return _clean_acta_lugar_nacimiento(raw)
    if key == "domicilio":
        return _clean_address_value(raw)
    if key in {"entidad_registro", "municipio_registro", "banco", "estado", "ciudad", "proveedor"}:
        return _normalize_address(raw)
    return _normalize_text(raw)


def _is_valid_table_cells_payload(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        payload = json.loads(text)
    except Exception:
        return False

    if not isinstance(payload, dict):
        return False

    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) < 2:
        return False

    non_empty_rows = 0
    for row in rows:
        if not isinstance(row, list):
            continue
        cells = [_normalize_text(str(cell or "")) for cell in row]
        if any(cells):
            non_empty_rows += 1

    return non_empty_rows >= 2


def _is_valid_replica_layout_payload(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        payload = json.loads(text)
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    pages = payload.get("pages")
    if not isinstance(pages, list) or not pages:
        return False
    line_count = 0
    for page in pages:
        if not isinstance(page, dict):
            continue
        lines = page.get("lines")
        if not isinstance(lines, list):
            continue
        for line in lines:
            if not isinstance(line, dict):
                continue
            if str(line.get("text", "")).strip():
                line_count += 1
    return line_count >= 2


def _is_valid_payment_detail_payload(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        payload = json.loads(text)
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    metadata = payload.get("metadata")
    table = payload.get("table")
    has_metadata = isinstance(metadata, dict) and any(str(v or "").strip() for v in metadata.values())
    has_rows = False
    if isinstance(table, dict):
        rows = table.get("rows")
        has_rows = isinstance(rows, list) and any(isinstance(item, dict) and item for item in rows)
    return has_metadata or has_rows


def _looks_like_person_name(value: str) -> bool:
    text = _normalize_name(value).upper()
    if not text:
        return False
    if len(text) < 2 or len(text) > 120:
        return False
    tokens = [t for t in text.split() if t]
    if not tokens:
        return False
    banned = {
        "PRESTACIONES",
        "ESPECIE",
        "DINERO",
        "REQUISITOS",
        "OTORGARAN",
        "CUMPLIDO",
    }
    banned_fragments = (
        "SUBTOTAL",
        "MULTIPLICADOR",
        "KWH",
        "TARIFA",
    )
    if any(tok in banned for tok in tokens):
        return False
    if _is_curp_header_noise_name(text):
        return False
    if any(fragment in text for fragment in banned_fragments):
        return False
    if sum(1 for ch in text if ch.isdigit()) >= len(text) * 0.5:
        return False
    return True


def _is_allowed_field_for_type(document_type: str, key: str) -> bool:
    if key == "texto_detectado":
        return True
    # Always allow additional table fields (tabla_celdas_2, tabla_celdas_3, ...)
    if key.startswith("tabla_celdas_"):
        return True
    # Always allow name variant fields
    if key in {"nombre_beneficiario", "nombre_asegurado", "nombre_titular"}:
        return True
    allowed = _ALLOWED_FIELDS_BY_TYPE.get(document_type)
    if not allowed:
        return True
    return key in allowed


def _is_valid_by_contract(document_type: str, key: str, value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    upper = text.upper()

    if key == "tabla_celdas" or key.startswith("tabla_celdas_"):
        return _is_valid_table_cells_payload(text)
    if key == "pago_detalle":
        return _is_valid_payment_detail_payload(text)
    if key == "replica_pdf_layout":
        return _is_valid_replica_layout_payload(text)
    if key == "replica_pdf_texto":
        return len(text) >= 80

    if key == "curp":
        return bool(CURP_PATTERN.fullmatch(_normalize_alnum(upper)))
    if key == "rfc":
        return bool(RFC_WITH_HOMOCLAVE.fullmatch(_normalize_alnum(upper)))
    if key == "nss":
        return bool(re.fullmatch(r"\d{11}", _normalize_numeric_field(upper)))
    if key == "clabe":
        return bool(re.fullmatch(r"\d{18}", _normalize_numeric_field(upper)))
    if key == "cp":
        return bool(re.fullmatch(r"\d{5}", _normalize_numeric_field(upper)))
    if key == "seccion":
        return bool(re.fullmatch(r"\d{3,6}", _normalize_numeric_field(upper)))
    if key == "numero_servicio":
        return bool(re.fullmatch(r"\d{10,13}", _normalize_numeric_field(upper)))
    if key == "cuenta":
        if document_type in {"DATOS_BANCARIOS", "FACTURA"}:
            return bool(re.fullmatch(r"\d{8,22}", _normalize_numeric_field(upper)))
        normalized_account = _normalize_alnum(upper)
        digit_count = sum(1 for ch in normalized_account if ch.isdigit())
        return bool(normalized_account) and 8 <= len(normalized_account) <= 24 and digit_count >= 6
    if key == "referencia":
        normalized = _normalize_value_for_key("referencia", upper)
        if any(ch.isalpha() for ch in normalized):
            return len(normalized) >= 12
        digits = sum(1 for ch in normalized if ch.isdigit())
        return bool(normalized) and 10 <= len(normalized) <= 30 and digits >= 8
    if key == "sexo":
        return upper in {"H", "M"}
    if key in {"fecha", "fecha_nacimiento", "fecha_registro", "fecha_limite", "fecha_corte", "fecha_emision", "fecha_documento"}:
        return bool(re.fullmatch(r"\d{2}[/-]\d{2}[/-]\d{4}", text))
    if key == "vigencia":
        return bool(re.fullmatch(r"\d{4}(?:/\d{4})?", text))
    if key in {"folio", "numero_acta"}:
        return bool(re.fullmatch(r"[A-Z0-9]{1,12}", _normalize_alnum(upper)))
    if key == "numero_certificado":
        return bool(re.fullmatch(r"[A-Z0-9]{6,24}", _normalize_alnum(upper)))
    if key == "identificador_electronico":
        return bool(re.fullmatch(r"[A-Z0-9]{6,30}", _normalize_alnum(upper)))
    if key in {"nombre", "titular"}:
        if key == "titular" and document_type == "COMPROBANTE_DOMICILIO" and upper == "PUBLICO EN GENERAL":
            return True
        if document_type == "NSS" and key == "nombre":
            cleaned_nss = _clean_nss_name(text)
            return bool(cleaned_nss and _is_nss_person_name(cleaned_nss))
        return _looks_like_person_name(text)
    if key == "lugar_nacimiento":
        if any(token in upper for token in {"ACTA DE NACIMIENTO", "SEXO", "FECHA DE NACIMIENTO", "LUGAR DE NACIMIENTO"}):
            return False
        return 2 <= len(upper) <= 80
    if key == "domicilio":
        if any(token in upper for token in {"LINEA DE CAPTURA", "TOTAL A PAGAR", "REFERENCIA"}):
            return False
        return len(upper) >= 10
    if key in {"entidad_registro", "municipio_registro", "banco", "estado", "ciudad", "proveedor"}:
        return len(upper) >= 3

    return len(text) >= 2


def _apply_field_contracts(document_type: str, fields: list[dict]) -> list[dict]:
    contracted: list[dict] = []
    for field in fields:
        key = str(field.get("key", "") or "")
        if not key:
            continue
        if not _is_allowed_field_for_type(document_type, key):
            continue
        if key == "texto_detectado":
            contracted.append(field)
            continue

        normalized_value = _normalize_field_value_for_contract(
            document_type,
            key,
            str(field.get("value", "") or ""),
        )
        if not normalized_value:
            continue
        if not _is_valid_by_contract(document_type, key, normalized_value):
            continue

        updated = dict(field)
        updated["value"] = normalized_value
        contracted.append(updated)
    return contracted


def _extract_city_state(lines: list[str]) -> tuple[str | None, str | None]:
    city = None
    state = None
    for line in lines:
        if "MUNICIPIO" in line or "MUN" in line:
            city = line.split("MUNICIPIO")[-1].split("MUN")[-1].strip(" :.-")
        if "ESTADO" in line or "EDO" in line:
            state = line.split("ESTADO")[-1].split("EDO")[-1].strip(" :.-")
    return city, state


def _extract_postal_code(text: str) -> str | None:
    upper = str(text or "").upper()
    match = re.search(r"\b([0-9OIL]{5})\b", upper)
    if not match:
        return None
    normalized = _normalize_value_for_key("cp", match.group(1))
    return normalized or None


def _extract_curp_state(curps: list[str]) -> str | None:
    if not curps:
        return None
    curp = _normalize_alnum(curps[0])
    if len(curp) < 13:
        return None
    return curp[11:13]


def _extract_curp_birth_date(curps: list[str]) -> str | None:
    if not curps:
        return None
    curp = _normalize_alnum(curps[0])
    if len(curp) < 10:
        return None
    yy = curp[4:6]
    mm = curp[6:8]
    dd = curp[8:10]
    if not (yy.isdigit() and mm.isdigit() and dd.isdigit()):
        return None
    pivot = (datetime.now().year % 100) + 5
    return f"{dd}/{mm}/19{yy}" if int(yy) >= pivot else f"{dd}/{mm}/20{yy}"


def _extract_curp_sex(curps: list[str]) -> str | None:
    if not curps:
        return None
    curp = _normalize_alnum(curps[0])
    if len(curp) < 11:
        return None
    sex = curp[10]
    return sex if sex in {"H", "M"} else None


def _guess_name(text: str) -> str | None:
    candidates = NAME_PATTERN.findall(text)
    if not candidates:
        return None
    blacklist = {"CURP", "RFC", "ACTA", "NACIMIENTO", "INSTITUTO", "ELECTOR", "DOMICILIO"}
    for name in candidates:
        if any(word in blacklist for word in name.split()):
            continue
        return name
    return None


def _extract_ine_name_from_lines(lines: list[str], curp: str | None = None) -> str | None:
    if not lines:
        return None

    norm_lines = [_normalize_text(str(line or "")).upper() for line in lines if _normalize_text(str(line or ""))]
    if not norm_lines:
        return None

    stop_labels = ["DOMICILIO", "SEXO", "CLAVE", "CURP", "FECHA", "SECCION", "VIGENCIA", "EMISION", "REGISTRO"]
    stop_keys = {_label_key(lbl) for lbl in stop_labels}
    label_key = _label_key("NOMBRE")

    start_idx = -1
    for idx, line in enumerate(norm_lines):
        if label_key in _label_key(line):
            start_idx = idx
            break

    if start_idx < 0:
        return None

    candidate_pieces: list[str] = []
    if start_idx >= 0:
        line = norm_lines[start_idx]
        if "NOMBRE" in line:
            tail = line.split("NOMBRE", 1)[-1].strip(" :.-")
            if tail:
                candidate_pieces.append(tail)
        else:
            compact = _label_key(line)
            if label_key in compact:
                compact_tail = compact.split(label_key, 1)[-1].strip(" :.-")
                if compact_tail:
                    candidate_pieces.append(compact_tail)

        for idx in range(start_idx + 1, min(len(norm_lines), start_idx + 9)):
            line = norm_lines[idx]
            line_key = _label_key(line)
            if any(stop in line_key for stop in stop_keys):
                break
            candidate_pieces.append(line)
    tokens: list[str] = []
    particles = {"DE", "DEL", "LA", "LAS", "LOS", "Y"}
    for piece in candidate_pieces:
        for tok in re.findall(r"[A-ZÑÁÉÍÓÚÜ]+", piece):
            if tok == "NOMBRE":
                continue
            if len(tok) <= 1:
                continue
            if (
                tokens
                and len(tok) <= 2
                and tok not in particles
                and len(tokens[-1]) >= 3
            ):
                tokens[-1] = f"{tokens[-1]}{tok}"
                continue
            if curp and len(tok) >= 10 and tok.startswith(curp[3].upper()):
                split = _split_compact_given_names(tok)
                parts = [p for p in split.split() if p]
                if len(parts) > 1:
                    tokens.extend(parts)
                    continue
            tokens.append(tok)

    if not tokens:
        return None

    normalized_curp = _normalize_alnum(curp or "")
    if len(normalized_curp) >= 4:
        paterno_init = normalized_curp[0]
        paterno_vowel = normalized_curp[1]
        materno_init = normalized_curp[2]
        nombre_init = normalized_curp[3]

        given_idx = next((i for i, tok in enumerate(tokens) if tok and tok[0] == nombre_init), -1)
        given_tokens = tokens[given_idx:] if given_idx >= 0 else []

        def _matches_paterno(tok: str) -> bool:
            if not tok or tok[0] != paterno_init:
                return False
            vowels = set("AEIOU")
            first_vowel = next((c for c in tok[1:] if c in vowels), "")
            return first_vowel == paterno_vowel

        paterno = next((tok for tok in tokens if _matches_paterno(tok)), "")
        materno = next((tok for tok in tokens if tok and tok[0] == materno_init and tok != paterno), "")

        if given_tokens and paterno:
            ordered = [*given_tokens, paterno]
            if materno:
                ordered.append(materno)
            deduped: list[str] = []
            for tok in ordered:
                if tok not in deduped:
                    deduped.append(tok)
            candidate = " ".join(deduped).strip()
            if candidate and _name_matches_curp(candidate, normalized_curp):
                return candidate

    fallback_tokens = list(tokens)
    if len(normalized_curp) >= 4:
        nombre_init = normalized_curp[3]
        given_idx = next((i for i, tok in enumerate(fallback_tokens) if tok and tok[0] == nombre_init), -1)
        if given_idx > 0:
            fallback_tokens = [*fallback_tokens[given_idx:], *fallback_tokens[:given_idx]]
    fallback = " ".join(fallback_tokens).strip()
    if fallback and _looks_like_person_name(fallback):
        return fallback
    return None


def _find_labeled_value(lines: list[str], label: str) -> str | None:
    labels = _expand_label_list(label)
    label_upper = label.upper()
    for line in lines:
        for alias in labels:
            alias_upper = alias.upper()
            if alias_upper in line:
                parts = line.split(alias_upper, 1)
                if len(parts) > 1:
                    candidate = parts[1].strip(" :.-")
                    if candidate:
                        return candidate
            compact_line = _label_key(line)
            compact_label = _label_key(alias_upper)
            if compact_label in compact_line:
                # If label is present but value isn't inline, fallback to next line in caller
                continue
    return None


def _find_value_after_keyword(lines: list[str], keywords: list[str]) -> str | None:
    expanded = []
    for keyword in keywords:
        expanded.extend(_expand_label_list(keyword))
    normalized_keywords = [_label_key(keyword) for keyword in expanded]
    for idx, line in enumerate(lines):
        compact_line = _label_key(line)
        if any(keyword in line for keyword in expanded) or any(keyword in compact_line for keyword in normalized_keywords):
            for keyword in expanded:
                if keyword in line:
                    tail = line.split(keyword, 1)[-1].strip(" :.-")
                    if tail:
                        return tail
            if idx + 1 < len(lines):
                return lines[idx + 1].strip(" :.-")
    return None


def _clean_nss_name(value: str) -> str | None:
    if not value:
        return None
    cleaned = _normalize_text(value).upper()
    cleaned = re.sub(
        r"^(?:(?:N[O0]MBRE\s*O?\s*RAZ[O0]N\s*SOCIAL|N[O0]MBRE[O0]?RAZ[O0]NSOCIAL)|"
        r"N[O0]MBRE(?:\s+DEL|\s+DE LA)?(?:\s+ASEGURADO|\s+BENEFICIARIO|\s+TRABAJADOR|\s+TITULAR)?|"
        r"ASEGURADO|BENEFICIARIO|TITULAR|"
        # OCR garbles "RAZÓN SOCIAL" as "0RAZ0NSOCIAL" or "RAZ0N SOCIAL" (0↔O confusion)
        r"[O0]?RAZ[O0]N\s*SOCIAL|RAZON\s+SOCIAL)\s*[:\-]?\s*",
        "",
        cleaned,
    )
    cleaned = re.split(r"\b(?:CURP|RFC|NSS|IMSS|FOLIO|FECHA|VIGENCIA|UNIDAD|CLINICA)\b", cleaned)[0].strip(" :.-,")
    cleaned = re.sub(r"[^A-ZÑÁÉÍÓÚÜ ]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    tokens = [tok for tok in cleaned.split() if tok]
    if len(tokens) <= 2 and any(len(tok) >= 12 for tok in tokens):
        expanded: list[str] = []
        for tok in tokens:
            if len(tok) >= 12:
                expanded.extend([part for part in _split_compact_nss_token(tok).split() if part])
            else:
                expanded.append(tok)
        tokens = expanded
        cleaned = " ".join(tokens).strip()
    if len(cleaned) < 5:
        return None
    if len(tokens) < 2:
        return None
    return cleaned


def _is_nss_person_name(value: str) -> bool:
    cleaned = _normalize_text(value).upper()
    if not cleaned:
        return False
    if len(cleaned) > 70:
        return False

    non_name_tokens = {
        "PRESTACIONES", "ESPECIE", "DINERO", "OTORGARAN", "CUMPLIDO", "REQUISITOS", "PREVISTOS",
        "LEY", "ARTICULO", "VIGENCIA", "FOLIO", "CLINICA", "UNIDAD", "SEGURO", "SOCIAL",
        "IMSS", "NSS", "RFC", "CURP", "SISTEMA", "NACIONAL", "SEGURIDAD",
    }
    non_name_fragments = (
        "PRESTACION",
        "REQUISIT",
        "OTORGAR",
        "CUMPLID",
        "DINERO",
        "ESPECIE",
        "BENEFICIARIOS",
        "TRABAJADORES",
        "ASEGURAMIENTO",
        "SOCIAL",   # captura "NSOCIAL", "RAZONSOCIAL" y variantes OCR
        "RAZON",    # captura "RAZ " suelto y variantes de RAZÓN SOCIAL mal limpiadas
    )
    particles = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "MC", "VON", "DA", "DO", "DI"}

    tokens = [tok for tok in re.findall(r"[A-ZÑÁÉÍÓÚÜ]+", cleaned) if tok]
    if len(tokens) < 2 or len(tokens) > 6:
        return False
    if any(tok in non_name_tokens for tok in tokens):
        return False
    if any(fragment in cleaned for fragment in non_name_fragments):
        return False

    core_tokens = [tok for tok in tokens if tok not in particles]
    if len(core_tokens) < 2:
        return False
    if any(len(tok) > 18 for tok in core_tokens):
        return False
    if any(len(tok) < 2 for tok in core_tokens):
        return False
    if sum(1 for tok in core_tokens if len(tok) >= 3) < 2:
        return False
    return True


def _split_compact_nss_token(token: str) -> str:
    compact = _normalize_alnum(token)
    if len(compact) <= 12:
        return compact

    common_surnames = (
        "HERNANDEZ",
        "GONZALEZ",
        "MARTINEZ",
        "RODRIGUEZ",
        "LOPEZ",
        "PEREZ",
        "SANCHEZ",
        "RAMIREZ",
        "CRUZ",
        "FLORES",
        "GOMEZ",
        "DIAZ",
        "REYES",
        "MORALES",
        "ORTIZ",
        "RUIZ",
        "MEDINA",
        "TORRES",
        "ROMERO",
        "VARGAS",
        "CASTILLO",
        "MENDOZA",
        "RIVERA",
        "VASQUEZ",
        "GARZA",
        "AGUILAR",
        "SILVA",
        "NAVARRO",
        "CASTRO",
        "GARCIA",
        "CAMPOS",
    )
    for surname in common_surnames:
        if compact.endswith(surname) and len(compact) > len(surname) + 3:
            left = compact[: -len(surname)]
            left_named = _split_compact_given_names(left)
            return f"{left_named} {surname}".strip()

    best = None
    best_score = None
    for cut in range(max(4, len(compact) - 10), min(len(compact) - 3, len(compact) - 4) + 1):
        left = compact[:cut]
        right = compact[cut:]
        if len(right) < 4 or len(right) > 10:
            continue
        if len(left) < 4:
            continue
        vowels_r = sum(1 for ch in right if ch in "AEIOU")
        ratio_r = vowels_r / max(1, len(right))
        if ratio_r < 0.2 or ratio_r > 0.8:
            continue
        score = abs(len(left) - len(right) * 1.7)
        if right.endswith(("EZ", "ES", "OS", "AS", "ON", "AN", "IA", "ZA", "GA")):
            score -= 0.4
        if best_score is None or score < best_score:
            best_score = score
            best = (left, right)

    if not best:
        return compact

    left, right = best
    left_named = _split_compact_given_names(left)
    return f"{left_named} {right}".strip()


def _append_nss_surname_hint(lines: list[str], start_idx: int, base_name: str) -> str:
    candidate = _normalize_name(base_name)
    compact_candidate = candidate.replace(" ", "")
    stop_words = {
        "IMSS",
        "NSS",
        "RFC",
        "CURP",
        "FOLIO",
        "FECHA",
        "VIGENCIA",
        "UNIDAD",
        "CLINICA",
        "BENEFICIARIO",
        "ASEGURADO",
        "TITULAR",
    }
    for offset in (1, 2):
        idx = start_idx + offset
        if idx >= len(lines):
            break
        raw_line = _normalize_text(lines[idx]).upper()
        if not raw_line:
            continue
        if re.search(r"\d", raw_line):
            continue
        if " " in raw_line.strip():
            continue
        token = _normalize_alnum(raw_line)
        if not token:
            continue
        if token in stop_words:
            continue
        if len(token) < 4 or len(token) > 18:
            continue
        if token in compact_candidate:
            continue
        merged = _clean_nss_name(f"{candidate} {token}")
        if merged and _is_nss_person_name(merged):
            return merged
    return candidate


def _extract_nss_name_from_text(lines: list[str], full_text: str) -> str | None:
    strict_keywords = [
        "NOMBRE DEL ASEGURADO",
        "NOMBRE DEL BENEFICIARIO",
        "NOMBRE DEL TRABAJADOR",
        "NOMBRE DEL TITULAR",
        "NOMBRE O RAZON SOCIAL",
    ]
    for idx, line in enumerate(lines):
        upper_line = line.upper()
        compact_line = _label_key(upper_line)
        for keyword in strict_keywords:
            compact_keyword = _label_key(keyword)
            if keyword not in upper_line and compact_keyword not in compact_line:
                continue
            if keyword in upper_line:
                tail = upper_line.split(keyword, 1)[-1].strip(" :.-")
            else:
                tail = ""
                if compact_keyword in compact_line:
                    compact_tail = compact_line.split(compact_keyword, 1)[-1].strip(" :.-")
                    if compact_tail:
                        tail = compact_tail
            if tail:
                normalized = _clean_nss_name(tail)
                if normalized and _is_nss_person_name(normalized):
                    return _append_nss_surname_hint(lines, idx, normalized)
            for offset in (1, 2, 3):
                if idx + offset >= len(lines):
                    break
                normalized = _clean_nss_name(lines[idx + offset])
                if normalized and _is_nss_person_name(normalized):
                    return _append_nss_surname_hint(lines, idx + offset, normalized)

    for pattern in [
        r"(?:NOMBRE\s+DEL\s+ASEGURADO|NOMBRE\s+DEL\s+BENEFICIARIO|NOMBRE\s+DEL\s+TRABAJADOR|NOMBRE\s+DEL\s+TITULAR|NOMBRE\s+O\s+RAZON\s+SOCIAL)\s*[:\-]?\s*([A-ZÑÁÉÍÓÚÜ ]{8,70})",
        r"(?:ASEGURADO|BENEFICIARIO|TITULAR)\s*[:\-]?\s*([A-ZÑÁÉÍÓÚÜ ]{8,70})",
    ]:
        match = re.search(pattern, full_text)
        if not match:
            continue
        normalized = _clean_nss_name(match.group(1))
        if normalized and _is_nss_person_name(normalized):
            return normalized

    compact_name_match = re.search(r"\b([A-ZÑ]{3,})!\s*([A-ZÑ]{8,24})\b", full_text)
    if compact_name_match:
        last_name = _normalize_alnum(compact_name_match.group(1))
        compact = _split_compact_nss_token(compact_name_match.group(2))
        candidate = _clean_nss_name(f"{compact} {last_name}")
        if candidate and _is_nss_person_name(candidate):
            return candidate

    return None


def _extract_acta_folio_numero_from_text(full_text: str) -> tuple[str | None, str | None]:
    text = _normalize_text(full_text).upper()
    ascii_text = _ascii_fold(text).upper()

    # Common compact table layout:
    # "FECHA DE REGISTRO LIBRO NUMERO DE ACTA 0001 20/08/2001 3 437"
    table_match = re.search(
        r"FECHA\s+DE\s+REGISTRO\s+LIBR[OA]\s+NUMER[OA]\s+DE\s+ACT[AE]\s+"
        r"([0-9OIL]{1,6})\s+\d{2}[/-]\d{2}[/-]\d{4}\s+([0-9OIL]{1,6})\s+([0-9OIL]{1,6})",
        text,
    )
    if table_match:
        first_value = _normalize_value_for_key("folio", table_match.group(1))
        middle_value = _normalize_value_for_key("numero_acta", table_match.group(2))
        last_value = _normalize_value_for_key("folio", table_match.group(3))

        # Prefer common pattern where first number behaves as folio and the last as numero_acta.
        if first_value and last_value:
            return (first_value, _normalize_value_for_key("numero_acta", table_match.group(3)) or last_value)
        if middle_value and last_value:
            return (last_value, middle_value)

        fallback_folio = _normalize_value_for_key("folio", table_match.group(3))
        fallback_numero = middle_value or _normalize_value_for_key("numero_acta", table_match.group(3))
        if not fallback_folio and first_value and middle_value:
            fallback_folio = first_value
        return (fallback_folio or None, fallback_numero or None)

    numero_acta = None
    folio = None

    numero_match = re.search(r"NUMER[OA]\s+DE\s+ACT[AE]\s*[:\-]?\s*([0-9OIL]{1,8})", text)
    if numero_match:
        normalized = _normalize_value_for_key("numero_acta", numero_match.group(1))
        if normalized:
            numero_acta = normalized

    folio_match = re.search(r"FOLI[O0]\s*[:\-]?\s*([0-9OIL]{1,8})", text)
    if folio_match:
        normalized = _normalize_value_for_key("folio", folio_match.group(1))
        if normalized:
            folio = normalized

    # Fallback: compact registrar header "OFICIALIA NUMERO ANO <folio> <numero> <anio>"
    if not folio or not numero_acta:
        header_match = re.search(
            r"OFICIALIA\s+NUMERO\s+ANO\s+([0-9OIL]{1,6})\s+([0-9OIL]{1,6})\s+[0-9OIL]{2,4}",
            ascii_text,
        )
        if header_match:
            if not folio:
                normalized = _normalize_value_for_key("folio", header_match.group(1))
                if normalized:
                    folio = normalized
            if not numero_acta:
                normalized = _normalize_value_for_key("numero_acta", header_match.group(2))
                if normalized:
                    numero_acta = normalized

    # Fallback: "OFICIALÍA <N>" style (some state registrar formats use this instead of FOLIO)
    if not folio:
        ofic_match = re.search(r"OFICIALIA\s+([0-9OIL]{1,6})", ascii_text)
        if ofic_match:
            normalized = _normalize_value_for_key("folio", ofic_match.group(1))
            if normalized:
                folio = normalized

    # Fallback: bare "NÚMERO <N>" as numero_acta (when no "NUMERO DE ACTA" keyword)
    if not numero_acta:
        num_match = re.search(r"\bNUMERO\s+([0-9OIL]{1,6})\b", ascii_text)
        if num_match:
            normalized = _normalize_value_for_key("numero_acta", num_match.group(1))
            if normalized:
                numero_acta = normalized

    return folio, numero_acta


def _extract_acta_name_from_text(raw_text: str) -> str | None:
    def fix_ocr_letters(value: str) -> str:
        text = str(value or "").upper()
        text = re.sub(r"(?<=[A-Z])0(?=[A-Z])", "O", text)
        text = re.sub(r"(?<=[A-Z])0(?=\b|[^0-9])", "O", text)
        text = re.sub(r"(?<=[A-Z])1(?=[A-Z])", "I", text)
        text = re.sub(r"(?<=[A-Z])5(?=[A-Z])", "S", text)
        return text

    lines = [fix_ocr_letters(_normalize_text(line)) for line in str(raw_text or "").splitlines() if _normalize_text(line)]
    if not lines:
        return None
    full = " ".join(lines)

    stop_words = (
        "SEXO",
        "FECHA",
        "LUGAR",
        "NACIMIENTO",
        "PRIMER",
        "SEGUNDO",
        "APELLIDO",
        "CURP",
        "FOLIO",
        "LIBRO",
        "TOMO",
        "OFICIALIA",
        "REGISTRO",
        "ACTA",
    )

    def clean_piece(value: str) -> str:
        piece = re.sub(r"[^A-ZÑÁÉÍÓÚÜ ]", " ", str(value or "").upper())
        piece = re.sub(r"\s+", " ", piece).strip()
        if not piece:
            return ""
        if len(piece) <= 1:
            return ""
        if any(token in piece for token in ("DATOS", "PERSONA", "REGISTRADA", "IDENTIFICADOR", "ELECTRONICO")):
            return ""
        if any(token in piece for token in ("APELLIDO", "NOMBRE(S)")):
            return ""
        return piece

    def cut_at_stop(text_value: str) -> str:
        cut = text_value
        for token in stop_words:
            idx = cut.find(token)
            if idx > 0:
                cut = cut[:idx].strip()
        return cut

    def label_equals(line_value: str, target: str) -> bool:
        return _label_key(line_value) == _label_key(target)

    inline_candidate = ""

    # Pattern 1: full label in one line.
    inline = re.search(r"\bNOMBRE(?:\(S\))?\s*[:\-]?\s*([A-ZÑÁÉÍÓÚÜ ]{4,120})", full)
    if inline:
        candidate = clean_piece(cut_at_stop(inline.group(1)))
        if candidate and _looks_like_person_name(candidate):
            inline_candidate = _normalize_name(candidate)

    # Pattern 1b: label in one line, value in next line (with OCR-noisy labels).
    for idx, line in enumerate(lines):
        if not (label_equals(line, "NOMBRE") or label_equals(line, "NOMBRES") or label_equals(line, "NOMBRE(S)")):
            continue
        if idx + 1 >= len(lines):
            continue
        candidate = clean_piece(cut_at_stop(lines[idx + 1]))
        if candidate and _looks_like_person_name(candidate):
            if not inline_candidate:
                inline_candidate = _normalize_name(candidate)
            break

    # Pattern 2: labeled parts.
    nombre = ""
    apellido1 = ""
    apellido2 = ""
    for line in lines:
        if not nombre:
            match = re.search(r"\bNOMBRE(?:\(S\))?\s*[:\-]?\s*(.+)$", line)
            if match:
                nombre = clean_piece(cut_at_stop(match.group(1)))
                continue
            if label_equals(line, "NOMBRE") or label_equals(line, "NOMBRES") or label_equals(line, "NOMBRE(S)"):
                continue
        if not apellido1:
            match = re.search(r"\bPRIMER\s+APELLID[O0]\s*[:\-]?\s*(.+)$", line)
            if match:
                apellido1 = clean_piece(cut_at_stop(match.group(1)))
                continue
            if label_equals(line, "PRIMER APELLIDO") or label_equals(line, "1ER APELLIDO"):
                continue
        if not apellido2:
            match = re.search(r"\bSEGUND[O0]\s+APELLID[O0]\s*[:\-]?\s*(.+)$", line)
            if match:
                apellido2 = clean_piece(cut_at_stop(match.group(1)))
                continue
            if label_equals(line, "SEGUNDO APELLIDO") or label_equals(line, "2DO APELLIDO"):
                continue

    # Pattern 2b: OCR noisy labels with values in following lines.
    if not (nombre and apellido1 and apellido2):
        for idx, line in enumerate(lines):
            if not nombre and (label_equals(line, "NOMBRE") or label_equals(line, "NOMBRES") or label_equals(line, "NOMBRE(S)")):
                if idx + 1 < len(lines):
                    nombre = clean_piece(cut_at_stop(lines[idx + 1])) or nombre
            if not apellido1 and (label_equals(line, "PRIMER APELLIDO") or label_equals(line, "1ER APELLIDO")):
                if idx + 1 < len(lines):
                    apellido1 = clean_piece(cut_at_stop(lines[idx + 1])) or apellido1
            if not apellido2 and (label_equals(line, "SEGUNDO APELLIDO") or label_equals(line, "2DO APELLIDO")):
                if idx + 1 < len(lines):
                    apellido2 = clean_piece(cut_at_stop(lines[idx + 1])) or apellido2
    composed = " ".join(part for part in [nombre, apellido1, apellido2] if part).strip()
    if composed and _looks_like_person_name(composed):
        return _normalize_name(composed)

    # Pattern 3: section "DATOS DE LA PERSONA REGISTRADA".
    section_idx = next((i for i, line in enumerate(lines) if "DATOS DE LA PERSONA REGISTRADA" in line), -1)
    if section_idx >= 0:
        collected: list[str] = []
        for line in lines[section_idx + 1 : section_idx + 6]:
            if any(token in line for token in ("NOMBRE", "APELLIDO", "SEXO", "FECHA", "LUGAR", "NACIMIENTO")):
                break
            cleaned = clean_piece(line)
            if cleaned:
                collected.append(cleaned)
        candidate = " ".join(collected).strip()
        if candidate and _looks_like_person_name(candidate):
            return _normalize_name(candidate)

    return inline_candidate or None


def _clean_acta_lugar_nacimiento(value: str) -> str:
    text = _normalize_text(str(value or "")).upper()
    if not text:
        return ""

    text = re.sub(r"^\s*ACTA\s+DE\s+NACIMIENTO\b", " ", text)
    text = re.split(
        r"\b(?:SEXO|FECHA\s+DE\s+NACIMIENTO|LUGAR\s+DE\s+NACIMIENTO|NOMBRE(?:\(S\))?|PRIMER\s+APELLIDO|SEGUNDO\s+APELLIDO)\b",
        text,
    )[0]
    text = re.sub(r"[^A-ZÑÁÉÍÓÚÜ ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text in {"ACTA", "ACTA DE", "ACTA DE NACIMIENTO"}:
        return ""
    return text


def _dedupe_fields(fields: list[dict]) -> list[dict]:
    def _parse_amount_for_rank(value: str | None) -> float | None:
        if not value:
            return None
        raw = str(value).replace("$", "").replace(" ", "").replace(",", "")
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _address_quality(value: str | None) -> float:
        text = _normalize_address(str(value or ""))
        if not text:
            return 0.0
        score = float(min(len(text), 140))
        if re.search(r"\b\d{5}\b", text):
            score += 12
        marker_hits = sum(
            1
            for marker in ("CALLE", "CLL", "AV", "COL", "CP", "C.P.", "MUN", "EDO", "S/N", "NUM", "NO.", "LOC", "RIA", "DEPTO")
            if marker in text
        )
        score += marker_hits * 10
        if "SSL" in text or "BENITOJUAREZ" in text:
            score += 18
        if re.search(r"\b\d{5}\s*$", text):
            score -= 16
        if text.startswith("-"):
            score -= 12
        if any(noise in text for noise in ("NO. DE SERVICIO", "NUMERO DE SERVICIO", "CUENTA", "RMU")):
            score -= 35
        if any(noise in text for noise in ("INSTITUTO NACIONAL ELECTORAL", "CREDENCIAL PARA VOTAR", "TELMEX TOTAL A PAGAR")):
            score -= 20
        return score

    def _rank(field: dict) -> tuple[float, float, float]:
        key = str(field.get("key", ""))
        confidence = float(field.get("confidence", 0) or 0)
        if key == "total":
            amount = _parse_amount_for_rank(field.get("value"))
            return (1 if amount is not None and amount > 0 else 0, 0, confidence)
        if key == "domicilio":
            return (1, _address_quality(field.get("value")), confidence)
        return (1, 0, confidence)

    best: dict[str, dict] = {}
    for field in fields:
        key = field.get("key")
        if not key:
            continue
        if key not in best:
            best[key] = field
            continue
        if _rank(field) > _rank(best[key]):
            best[key] = field
    return list(best.values())


def _name_matches_curp(name: str, curp: str) -> bool:
    """Check if name tokens are consistent with CURP letter positions.

    CURP structure:
    - pos 0: first letter of paternal surname
    - pos 1: first internal vowel of paternal surname
    - pos 2: first letter of maternal surname
    - pos 3: first letter of given name (primer nombre)
    Returns True if a token matching the paterno initial + vowel AND the nombre
    initial are found in the name tokens.
    """
    if not name or not curp or len(curp) < 4:
        return True  # Cannot validate, assume OK
    tokens = [t for t in name.upper().split() if t]
    if len(tokens) < 2:
        return True
    paterno_init = curp[0].upper()
    paterno_vowel = curp[1].upper()
    nombre_init = curp[3].upper()
    vowels = set("AEIOU")

    has_nombre = any(t[0] == nombre_init for t in tokens)
    # Validate paterno: token must start with paterno_init AND its first
    # internal vowel (any vowel after the initial) must match paterno_vowel.
    has_paterno = False
    for t in tokens:
        if t[0] != paterno_init:
            continue
        # Find the first vowel after the initial letter
        first_vowel = next((c for c in t[1:] if c in vowels), "")
        if first_vowel == paterno_vowel:
            has_paterno = True
            break
    return has_nombre and has_paterno


def _try_repair_name_with_curp(name: str, curp: str) -> str:
    """Try to split OCR-merged tokens in a name using CURP initials.

    When OCR merges adjacent name tokens (e.g. 'GUSTAVOIA' from 'GUSTAVO' + 'GARCIA'),
    use the CURP paterno/materno initials to find a plausible split point.
    """
    if not name or not curp or len(curp) < 4:
        return name
    tokens = name.upper().split()
    if not tokens:
        return name
    paterno_init = curp[0].upper()
    materno_init = curp[2].upper()
    nombre_init = curp[3].upper()
    firsts = {t[0] for t in tokens}

    # Identify which initial is missing
    missing_init = None
    if nombre_init not in firsts:
        missing_init = nombre_init
    elif paterno_init not in firsts:
        missing_init = paterno_init
    elif materno_init not in firsts:
        missing_init = materno_init
    else:
        return name  # All initials present

    # Try to split a long token that may contain the missing initial
    for i, token in enumerate(tokens):
        if len(token) < 7:
            continue
        if token[0] == missing_init:
            continue  # This token already starts with missing initial
        for pos in range(3, len(token) - 2):
            if token[pos] == missing_init:
                left = token[:pos]
                right = token[pos:]
                # Both parts should look like name fragments (>= 3 chars, has vowels)
                vowels = set("AEIOU")
                if (
                    len(left) >= 3
                    and len(right) >= 3
                    and any(c in vowels for c in left)
                    and any(c in vowels for c in right)
                ):
                    tokens[i:i + 1] = [left, right]
                    return " ".join(tokens)
    return name


__all__ = _export_all()

