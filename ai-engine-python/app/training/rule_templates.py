"""
Training A: Reglas mejoradas por tipo de documento.

Complementa app/utils/regex_patterns.py con:
  - Validadores estructurales por campo (CLABE checksum, CURP estado, etc.)
  - Conjuntos de valores conocidos (bancos, estados CURP, codigos CLABE)
  - Ajuste de confianza cruzado entre campos del mismo documento

Exports
-------
VALID_BANK_NAMES      : frozenset[str]
CURP_STATE_CODES      : frozenset[str]
CLABE_BANK_CODES      : frozenset[str]
validate_curp_structure(value) -> tuple[bool, str]
validate_clabe_checksum(value) -> tuple[bool, str]
validate_nss_structure(value)  -> tuple[bool, str]
validate_rfc_structure(value)  -> tuple[bool, str]
rule_confidence_delta(doc_type, key, value, all_fields) -> float
apply_rule_boosts(doc_type, fields) -> list[dict]
"""
from __future__ import annotations

import re
import logging
from typing import Callable

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Conjuntos de valores conocidos
# ------------------------------------------------------------------------------

VALID_BANK_NAMES: frozenset[str] = frozenset({
    "BBVA", "BBVA BANCOMER", "BANAMEX", "CITIBANAMEX", "CITI",
    "SANTANDER", "HSBC", "BANORTE", "SCOTIABANK", "INBURSA",
    "AZTECA", "BANREGIO", "INVEX", "AFIRME", "MIFEL", "BANSI",
    "BANJERCITO", "BANCOPPEL", "ACTINVER", "MULTIVA", "ABC CAPITAL",
    "BANCREA", "CIBANCO", "CONSUBANCO", "JP MORGAN", "AMERICAN EXPRESS",
    "AMEX", "SABADELL", "INTERCAM", "BANKAOOL", "INMOBILIARIO",
    "COMPARTAMOS", "PAGATODO", "STP",
})

# Codigos de estado en CURP (posiciones 11-12)
CURP_STATE_CODES: frozenset[str] = frozenset({
    "AS", "BC", "BS", "CC", "CL", "CM", "CS", "CH", "DF", "DG",
    "GT", "GR", "HG", "JC", "MC", "MN", "MS", "NT", "NL", "OC",
    "PL", "QT", "QR", "SP", "SL", "SR", "TC", "TS", "TL", "VZ",
    "YN", "ZS", "NE",
})

# Primeros 3 digitos de CLABE = codigo de banco (muestra representativa SAT)
CLABE_BANK_CODES: frozenset[str] = frozenset({
    "002", "006", "009", "012", "014", "021", "030", "032", "036",
    "042", "044", "058", "059", "060", "062", "072", "102", "103",
    "106", "108", "110", "112", "113", "116", "124", "126", "127",
    "128", "129", "130", "132", "133", "134", "135", "136", "137",
    "138", "139", "140", "141", "143", "145", "147", "148", "149",
    "155", "156", "160", "163", "166", "168", "600", "601", "602",
    "605", "616", "617", "627", "628", "629", "630", "631", "632",
    "633", "634", "636", "637", "638", "640", "642", "646", "648",
    "649", "651", "652", "653", "655", "656", "659", "670", "674",
    "679", "684", "685", "686", "687", "689", "699", "706", "710",
    "722", "723", "728", "730", "732", "733", "734", "736", "740",
    "741", "742", "743", "744", "745", "746", "748", "749",
})

# ------------------------------------------------------------------------------
# Validadores estructurales
# ------------------------------------------------------------------------------

_CURP_RE = re.compile(
    r"^[A-Z]{4}\d{6}[HM]{1}[A-Z]{2}[B-DF-HJ-NP-TV-Z]{3}[A-Z0-9]{2}$"
)


def validate_curp_structure(value: str) -> tuple[bool, str]:
    """Valida estructura CURP: 18 chars, fecha valida, estado valido."""
    v = (value or "").strip().upper()
    if len(v) != 18:
        return False, f"Longitud incorrecta: {len(v)} (esperado 18)"
    if not _CURP_RE.match(v):
        return False, "Formato CURP invalido"
    state = v[11:13]
    if state not in CURP_STATE_CODES:
        return False, f"Codigo de estado CURP desconocido: {state}"
    try:
        mm, dd = int(v[6:8]), int(v[8:10])
        if not (1 <= mm <= 12 and 1 <= dd <= 31):
            return False, f"Fecha CURP invalida: {v[4:10]}"
    except ValueError:
        return False, "Fecha CURP no numerica"
    return True, ""


def validate_clabe_checksum(value: str) -> tuple[bool, str]:
    """Valida CLABE 18 digitos + digito verificador (ponderacion 3-7-1)."""
    v = re.sub(r"\D", "", (value or ""))
    if len(v) != 18:
        return False, f"CLABE: {len(v)} digitos (esperado 18)"
    weights = [3, 7, 1, 3, 7, 1, 3, 7, 1, 3, 7, 1, 3, 7, 1, 3, 7]
    total = sum(int(v[i]) * weights[i] for i in range(17))
    check = (10 - (total % 10)) % 10
    if check != int(v[17]):
        return False, f"Digito verificador CLABE incorrecto (esperado {check})"
    return True, ""


def validate_nss_structure(value: str) -> tuple[bool, str]:
    """Valida NSS: exactamente 11 digitos."""
    v = re.sub(r"\D", "", (value or ""))
    if len(v) != 11:
        return False, f"NSS: {len(v)} digitos (esperado 11)"
    return True, ""


def validate_rfc_structure(value: str) -> tuple[bool, str]:
    """Valida RFC: 12 chars (moral) o 13 chars (fisica)."""
    v = re.sub(r"[\s.\-]", "", (value or "")).upper()
    if len(v) == 12:
        pattern = re.compile(r"^[A-Z&]{3}\d{6}[A-Z0-9]{3}$")
    elif len(v) == 13:
        pattern = re.compile(r"^[A-Z&]{4}\d{6}[A-Z0-9]{3}$")
    else:
        return False, f"RFC: {len(v)} chars (esperado 12-13)"
    if not pattern.match(v):
        return False, "Formato RFC invalido"
    return True, ""


# ✅ FIX: usar Callable en lugar de object para que Pylance sepa que es invocable
_VALIDATORS: dict[str, Callable[[str], tuple[bool, str]]] = {
    "curp":  validate_curp_structure,
    "clabe": validate_clabe_checksum,
    "nss":   validate_nss_structure,
    "rfc":   validate_rfc_structure,
}

# Campos prohibidos por tipo de documento (indican clasificacion erronea)
_FORBIDDEN_FIELDS: dict[str, frozenset[str]] = {
    "INE":    frozenset({"nss", "clabe", "tabla_celdas"}),
    "NSS":    frozenset({"clabe", "clave_elector"}),
    "CURP":   frozenset({"clabe", "nss"}),
    "FACTURA": frozenset({"clave_elector", "nss"}),
}

# ------------------------------------------------------------------------------
# Motor de reglas
# ------------------------------------------------------------------------------


def rule_confidence_delta(
    doc_type: str,
    key: str,
    value: str,
    all_fields: dict[str, str],
) -> float:
    """Calcula ajuste de confianza para un campo segun reglas del tipo de doc.

    Retorna un float: positivo = boost, negativo = penalizacion, 0 = sin cambio.
    """
    delta = 0.0
    v = str(value or "").strip()
    if not v:
        return 0.0

    # 1. Validacion estructural del campo
    validator = _VALIDATORS.get(key)
    if validator:
        valid, reason = validator(v)
        if valid:
            delta += 0.08
        else:
            delta -= 0.15
            logger.debug("[rule_templates] %s.%s fallo validacion: %s", doc_type, key, reason)

    # 2. Banco conocido para DATOS_BANCARIOS
    if key == "banco" and doc_type == "DATOS_BANCARIOS":
        banco_upper = v.upper()
        if any(b in banco_upper for b in VALID_BANK_NAMES):
            delta += 0.05
        else:
            delta -= 0.05

    # 3. Coherencia CURP <-> nombre/apellidos
    if key == "curp" and len(v) == 18 and doc_type in {"INE", "CURP"}:
        ap = (all_fields.get("apellido_paterno") or "").strip().upper()
        am = (all_fields.get("apellido_materno") or "").strip().upper()
        nm = (all_fields.get("nombre") or "").strip().upper()
        expected = []
        if ap:
            expected.append(ap[0])
        if am:
            expected.append(am[0])
        if nm:
            expected.append(nm[0])
        if expected:
            curp_letters = v[:4]
            matches = sum(1 for letter in expected if letter in curp_letters)
            if matches >= 2:
                delta += 0.10
            elif matches == 0:
                delta -= 0.10

    # 4. Coherencia CURP <-> fecha_nacimiento (YYMMDD en posiciones 4-9)
    if key == "fecha_nacimiento" and doc_type in {"INE", "CURP", "NSS"}:
        curp = (all_fields.get("curp") or "")
        if len(curp) >= 10:
            curp_date = curp[4:10]
            parts = re.split(r"[/\-]", v)
            if len(parts) == 3:
                try:
                    dd_s, mm_s, yyyy_s = parts[0], parts[1], parts[2]
                    dd, mm = int(dd_s), int(mm_s)
                    yy = yyyy_s[-2:]
                    expected_date = f"{yy}{mm:02d}{dd:02d}"
                    if curp_date == expected_date:
                        delta += 0.15
                except (ValueError, IndexError):
                    pass

    # 5. CLABE bank code conocido
    if key == "clabe":
        digits = re.sub(r"\D", "", v)
        if len(digits) == 18:
            bank_code = digits[:3]
            if bank_code not in CLABE_BANK_CODES:
                delta -= 0.05  # soft penalty, puede ser banco nuevo

    return round(delta, 3)


def apply_rule_boosts(doc_type: str, fields: list[dict]) -> list[dict]:
    """Aplica reglas mejoradas a una lista de campos y ajusta su confianza.

    No modifica el campo si la confianza resultante saldria de [0.0, 1.0].
    Compatible con el formato de campos del pipeline (dict con key, value, confidence).
    """
    if not fields:
        return fields

    value_map: dict[str, str] = {
        str(f.get("key", "") or ""): str(f.get("value", "") or "")
        for f in fields
        if f.get("value")
    }

    forbidden = _FORBIDDEN_FIELDS.get(doc_type, frozenset())
    result: list[dict] = []

    for field in fields:
        key = str(field.get("key", "") or "")
        value = str(field.get("value", "") or "")

        if key in forbidden:
            new_field = dict(field)
            new_field["confidence"] = min(float(new_field.get("confidence") or 0.5), 0.35)
            errors = list(new_field.get("validation_errors") or [])
            errors.append(f"Campo '{key}' atipico para {doc_type}")
            new_field["validation_errors"] = errors
            result.append(new_field)
            continue

        delta = rule_confidence_delta(doc_type, key, value, value_map)
        if delta != 0.0:
            new_field = dict(field)
            current = float(new_field.get("confidence") or 0.5)
            new_field["confidence"] = round(max(0.0, min(1.0, current + delta)), 4)
            result.append(new_field)
        else:
            result.append(field)

    return result