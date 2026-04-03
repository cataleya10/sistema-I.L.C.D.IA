"""
Normalization Service — fuente única de verdad para normalización de campos.

Garantiza que aunque el OCR lea sucio, el resultado final salga consistente:
  - Nombres en MAYÚSCULAS, sin espacios múltiples
  - Fechas a DD/MM/YYYY (interno) o YYYY-MM-DD (ISO 8601)
  - Importes con exactamente dos decimales y separador de miles
  - RFC / CURP sin espacios, en mayúsculas, longitud correcta
  - CLABE / NSS / CP solo dígitos, longitud validada
  - Folio / referencia alfanumérico limpio

API principal
-------------
normalize_field(key, value)   → aplica el normalizador correcto según el campo
normalize_fields(fields_list) → normaliza una lista de campos {key, value, ...}

Normalizadores individuales
---------------------------
normalize_name(str)       → str   JUAN JOSE GARCIA LOPEZ
normalize_date(str)       → str   25/03/2026  (DD/MM/YYYY)
normalize_date_iso(str)   → str   2026-03-25  (YYYY-MM-DD)
normalize_amount(str)     → str   1,234.56
normalize_rfc(str)        → str   GACE010425NW6
normalize_curp(str)       → str   GACE010425MDFMPL08
normalize_nss(str)        → str   12345678901
normalize_clabe(str)      → str   002010012345678901
normalize_cuenta(str)     → str   1234567890
normalize_cp(str)         → str   06600
normalize_sex(str)        → str   H | M
normalize_folio(str)      → str   limpio alfanumérico
normalize_text(str)       → str   texto unicode normalizado
"""

from __future__ import annotations

import re
import unicodedata
import logging
from typing import Any, Callable

from app.pipelines.validate import validate_fields as _validate_fields
from app.pipelines.extract.common import (
    _normalize_text,
    _normalize_name,
    _normalize_date_value,
    _normalize_alnum,
    _normalize_numeric_field,
    _normalize_sex,
    _normalize_cp_value,
    _normalize_folio_value,
    _postprocess_fields,
)
from app.utils.regex_patterns import (
    RFC_PATTERN,
    CURP_PATTERN,
    RFC_EXCLUIR,
    normalize_date as _normalize_date_from_patterns,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 1. NOMBRES
# ──────────────────────────────────────────────────────────────────────────────

def normalize_name(value: str) -> str:
    """
    Normaliza un nombre propio.

    - Unicode NFC
    - Colapsa espacios internos
    - MAYÚSCULAS

    >>> normalize_name("  juan   josé  garcía ")
    'JUAN JOSE GARCIA'
    """
    return _normalize_name(str(value or ""))


# ──────────────────────────────────────────────────────────────────────────────
# 2. FECHAS
# ──────────────────────────────────────────────────────────────────────────────

_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_ISO_DATE_SLASH_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})$")


def normalize_date(value: str) -> str:
    """
    Normaliza una fecha al formato interno DD/MM/YYYY.

    Acepta: '2026-03-25', '2026/03/25', '25/03/2026', '25-mar-2026', etc.

    >>> normalize_date('2026-03-25')
    '25/03/2026'
    >>> normalize_date('06/feb./2026')
    '06/02/2026'
    """
    raw = str(value or "").strip()
    # ISO 8601: YYYY-MM-DD o YYYY/MM/DD — convertir antes de pasar al parser
    m = _ISO_DATE_RE.match(raw) or _ISO_DATE_SLASH_RE.match(raw)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    return _normalize_date_value(raw)


def normalize_date_iso(value: str) -> str:
    """
    Normaliza una fecha a ISO 8601: YYYY-MM-DD.

    >>> normalize_date_iso('25/03/2026')
    '2026-03-25'
    >>> normalize_date_iso('06/feb./2026')
    '2026-02-06'
    """
    ddmmyyyy = normalize_date(value)
    # ddmmyyyy tiene forma DD/MM/YYYY si fue exitoso
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", ddmmyyyy)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return ddmmyyyy  # devuelve lo que había si no se pudo parsear


# ──────────────────────────────────────────────────────────────────────────────
# 3. IMPORTES
# ──────────────────────────────────────────────────────────────────────────────

_CURRENCY_NOISE = re.compile(r"(?i)\s*(?:MXN|MXP|PESOS?)\s*")
_DOLLAR_RE       = re.compile(r"\$\s*([0-9OIl][0-9OIl.,]{0,24})")
_AMOUNT_NUM_RE   = re.compile(r"(?<![A-Za-z])(\d[\d.,]{0,24})")


def normalize_amount(value: str) -> str:
    """
    Normaliza un importe monetario a «1,234.56».

    - Elimina prefijo $ y sufijo MXN/MXP
    - Corrige OCR: O→0, l→1, I→1
    - Determina separador decimal automáticamente
    - Garantiza exactamente 2 decimales

    >>> normalize_amount('$ 1,234.56 MXN')
    '1,234.56'
    >>> normalize_amount('15000')
    '15,000.00'
    >>> normalize_amount('1.234,56')   # separador europeo
    '1,234.56'
    """
    text = _CURRENCY_NOISE.sub("", str(value or "")).strip()
    if not text:
        return ""

    m = _DOLLAR_RE.search(text) or _AMOUNT_NUM_RE.search(text)
    if not m:
        return text

    token = m.group(1)
    token = token.replace("O", "0").replace("l", "1").replace("I", "1")
    token = re.sub(r"[^\d.,]", "", token)
    if not token:
        return text

    decimal_sep: str | None = None
    if "." in token and "," in token:
        decimal_sep = "." if token.rfind(".") > token.rfind(",") else ","
    elif token.count(".") == 1 and len(token.split(".")[-1]) == 2:
        decimal_sep = "."
    elif token.count(",") == 1 and len(token.split(",")[-1]) == 2:
        decimal_sep = ","

    if decimal_sep:
        integer_raw, cents_raw = token.rsplit(decimal_sep, 1)
        integer_digits = re.sub(r"\D", "", integer_raw)
        cents_digits   = re.sub(r"\D", "", cents_raw)
        if not integer_digits:
            return text
        cents = (cents_digits + "00")[:2]
        return f"{int(integer_digits):,}.{cents}"

    digits = re.sub(r"\D", "", token)
    return f"{int(digits):,}.00" if digits else text


# ──────────────────────────────────────────────────────────────────────────────
# 4. IDENTIFICADORES PERSONALES
# ──────────────────────────────────────────────────────────────────────────────

def normalize_rfc(value: str) -> str:
    """
    Normaliza un RFC: elimina espacios/guiones, mayúsculas.
    Devuelve '' si el resultado no tiene la longitud esperada (12-13 chars).

    >>> normalize_rfc('GACE 010425 NW6')
    'GACE010425NW6'
    """
    cleaned = re.sub(r"[\s\-\.]", "", str(value or "")).upper()
    # Quitar solo caracteres que no sean alfanuméricos ni &
    cleaned = re.sub(r"[^A-Z0-9&]", "", cleaned)
    if 12 <= len(cleaned) <= 13:
        return cleaned
    # Intentar extraer un RFC válido del texto original
    m = RFC_PATTERN.search(str(value or "").upper())
    return re.sub(r"\s", "", m.group(0)) if m else ""


def normalize_curp(value: str) -> str:
    """
    Normaliza un CURP: elimina espacios, mayúsculas, 18 chars.

    >>> normalize_curp('GACE 010425 MDFMPL 08')
    'GACE010425MDFMPL08'
    """
    cleaned = re.sub(r"\s+", "", str(value or "")).upper()
    cleaned = re.sub(r"[^A-Z0-9]", "", cleaned)
    if len(cleaned) == 18 and CURP_PATTERN.fullmatch(cleaned):
        return cleaned
    # Intentar extraer del texto original
    m = CURP_PATTERN.search(str(value or "").upper())
    return m.group(0) if m else ""


def normalize_sex(value: str) -> str:
    """
    Normaliza el valor de sexo a 'H' o 'M'.

    >>> normalize_sex('Masculino')
    'H'
    >>> normalize_sex('femenino')
    'M'
    """
    return _normalize_sex(str(value or ""))


# ──────────────────────────────────────────────────────────────────────────────
# 5. CLAVES NUMÉRICAS
# ──────────────────────────────────────────────────────────────────────────────

def normalize_nss(value: str) -> str:
    """
    Normaliza un NSS a 11 dígitos exactos.
    Corrige OCR: O→0, I→1, L→1.

    >>> normalize_nss('123 456 78 901')
    '12345678901'
    """
    digits = _normalize_numeric_field(str(value or ""))
    return digits if len(digits) == 11 else ""


def normalize_clabe(value: str) -> str:
    """
    Normaliza una CLABE interbancaria a 18 dígitos exactos.
    Corrige OCR: O→0, I→1, L→1.

    >>> normalize_clabe('002 010 01234567 89 01')
    '002010012345678901'
    """
    digits = _normalize_numeric_field(str(value or ""))
    return digits if len(digits) == 18 else ""


def normalize_cuenta(value: str) -> str:
    """
    Normaliza un número de cuenta bancaria (10-16 dígitos).

    >>> normalize_cuenta('1234-5678-90')
    '1234567890'
    """
    digits = _normalize_numeric_field(str(value or ""))
    return digits if 10 <= len(digits) <= 16 else digits  # devuelve lo que hay aunque no sea exacto


def normalize_cp(value: str) -> str:
    """
    Normaliza un código postal mexicano a 5 dígitos.

    >>> normalize_cp('0 6600')
    '06600'
    """
    return _normalize_cp_value(str(value or ""))


def normalize_folio(value: str) -> str:
    """
    Normaliza un folio o número de referencia: alfanumérico limpio.

    >>> normalize_folio('Folio: AB-12345')
    'AB12345'
    """
    return _normalize_alnum(str(value or ""))


# ──────────────────────────────────────────────────────────────────────────────
# 6. TEXTO GENÉRICO
# ──────────────────────────────────────────────────────────────────────────────

def normalize_text(text: str) -> str:
    """Normaliza texto OCR: unicode NFC, colapsa espacios, sin mojibake."""
    return _normalize_text(str(text or ""))


# ──────────────────────────────────────────────────────────────────────────────
# 7. DISPATCHER POR NOMBRE DE CAMPO
# ──────────────────────────────────────────────────────────────────────────────

# Mapa campo → normalizador.
# El dispatcher busca coincidencia exacta primero, luego por substring.
_FIELD_NORMALIZERS: dict[str, Callable[[str], str]] = {
    # Nombres
    "nombre":                normalize_name,
    "nombre_beneficiario":   normalize_name,
    "titular":               normalize_name,
    "apellido_paterno":      normalize_name,
    "apellido_materno":      normalize_name,
    "primer_apellido":       normalize_name,
    "segundo_apellido":      normalize_name,
    # Fechas (formato interno DD/MM/YYYY)
    "fecha_nacimiento":      normalize_date,
    "fecha_corte":           normalize_date,
    "fecha_registro":        normalize_date,
    "fecha_pago":            normalize_date,
    "fecha_limite":          normalize_date,
    "fecha_documento":       normalize_date,
    "fecha_emision":         normalize_date,
    # Importes
    "importe":               normalize_amount,
    "total":                 normalize_amount,
    "total_percepciones":    normalize_amount,
    "total_deducciones":     normalize_amount,
    "neto_pagar":            normalize_amount,
    "monto":                 normalize_amount,
    # Identificadores personales
    "rfc":                   normalize_rfc,
    "curp":                  normalize_curp,
    "nss":                   normalize_nss,
    "sexo":                  normalize_sex,
    # Bancarios
    "clabe":                 normalize_clabe,
    "cuenta":                normalize_cuenta,
    # Direcciones / códigos
    "cp":                    normalize_cp,
    "folio":                 normalize_folio,
    "referencia":            normalize_folio,
    "clave_elector":         normalize_folio,
    "clave_rastreo":         normalize_folio,
    "numero_servicio":       normalize_folio,
    "numero_acta":           normalize_folio,
}

# Reglas de fallback: si el nombre del campo contiene una de estas palabras clave
_FIELD_KEYWORD_RULES: list[tuple[str, Callable[[str], str]]] = [
    ("nombre",   normalize_name),
    ("apellido", normalize_name),
    ("titular",  normalize_name),
    ("fecha",    normalize_date),
    ("importe",  normalize_amount),
    ("monto",    normalize_amount),
    ("total",    normalize_amount),
    ("rfc",      normalize_rfc),
    ("curp",     normalize_curp),
    ("nss",      normalize_nss),
    ("clabe",    normalize_clabe),
    ("cuenta",   normalize_cuenta),
    ("cp",       normalize_cp),
    ("folio",    normalize_folio),
    ("referencia", normalize_folio),
]


def normalize_field(key: str, value: str) -> str:
    """
    Aplica el normalizador correcto al valor según el nombre del campo.

    Primero busca coincidencia exacta en ``_FIELD_NORMALIZERS``.
    Si no encuentra, busca por substring en ``_FIELD_KEYWORD_RULES``.
    Si tampoco, aplica ``normalize_text`` como fallback.

    Parameters
    ----------
    key   : nombre canónico del campo (ej. 'rfc', 'fecha_nacimiento').
    value : valor crudo del campo.

    Returns
    -------
    str
        Valor normalizado.

    Examples
    --------
    >>> normalize_field('rfc', 'GACE 010425 NW6')
    'GACE010425NW6'
    >>> normalize_field('fecha_nacimiento', '25-mar-2026')
    '25/03/2026'
    >>> normalize_field('importe', '$ 15,000.00 MXN')
    '15,000.00'
    """
    key_lower = str(key or "").lower().strip()
    raw = str(value or "")

    # 1. Coincidencia exacta
    fn = _FIELD_NORMALIZERS.get(key_lower)
    if fn:
        return fn(raw)

    # 2. Substring
    for keyword, fn in _FIELD_KEYWORD_RULES:
        if keyword in key_lower:
            return fn(raw)

    # 3. Fallback genérico
    return normalize_text(raw)


def normalize_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Normaliza una lista de campos en el formato estándar del sistema.

    Cada campo es un dict con al menos ``{"key": ..., "value": ...}``.
    Aplica ``normalize_field`` al valor de cada uno y devuelve la lista
    con los valores actualizados *sin* modificar el resto de las claves.

    Parameters
    ----------
    fields : lista de dicts de campos extraídos.

    Returns
    -------
    list[dict]
        Misma lista con ``value`` normalizado en cada campo.
    """
    result = []
    for field in fields:
        field_copy = dict(field)
        key   = str(field_copy.get("key") or "")
        value = str(field_copy.get("value") or "")
        if key and value:
            field_copy["value"] = normalize_field(key, value)
        result.append(field_copy)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# 8. VALIDACIÓN (wrappers sobre el pipeline existente)
# ──────────────────────────────────────────────────────────────────────────────

async def validate_extracted_fields(
    fields: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Aplica validadores de formato a cada campo extraído.
    (CURP, RFC, NSS, CLABE, fechas, sexo, etc.)
    """
    return await _validate_fields(fields)


def postprocess_fields(
    document_type: str,
    fields: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Filtra campos con baja confianza, inválidos o garbage y aplica
    verificaciones cruzadas (CURP ↔ fecha_nacimiento, RFC ↔ nombre).
    """
    return _postprocess_fields(document_type, fields)
