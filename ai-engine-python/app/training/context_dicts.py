"""
Training B: Diccionarios de contexto para extraccion dirigida.

Cuando el extractor principal no encuentra un campo, este modulo puede
buscarlo por proximidad a palabras clave conocidas en el texto OCR.

"RFC" casi siempre aparece cerca del valor RFC.
"CLABE" casi siempre aparece cerca del numero CLABE.
etc.

Exports
-------
CONTEXT_KEYWORDS    : dict[str, list[str]]
    Mapea campo canonico -> lista de keywords que tipicamente aparecen cerca.

CONTEXT_BY_DOC_TYPE : dict[str, list[str]]
    Campos prioritarios por tipo de documento (en orden de importancia).

find_value_near_context(lines, field, doc_type, window) -> list[dict]
    Busca el valor de un campo escaneando ventanas alrededor de sus keywords.

extract_context_fields(lines, doc_type) -> list[dict]
    Extrae todos los campos posibles usando context_dicts (uno por clave).
"""
from __future__ import annotations

import re
import unicodedata
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Diccionarios de contexto — palabras que aparecen cerca de cada campo
# ------------------------------------------------------------------------------

CONTEXT_KEYWORDS: dict[str, list[str]] = {
    "rfc": [
        "RFC", "R.F.C.", "R.F.C",
        "REGISTRO FEDERAL DE CONTRIBUYENTES",
        "REGISTRO FEDERAL",
        "CLAVE DE RFC",
    ],
    "curp": [
        "CURP", "C.U.R.P.", "C.U.R.P",
        "CLAVE UNICA DE REGISTRO DE POBLACION",
        "CLAVE UNICA DE REGISTRO",
        "CLAVE UNICA",
    ],
    "nss": [
        "NSS", "N.S.S.", "N.S.S",
        "NUMERO DE SEGURIDAD SOCIAL",
        "NUMERO SEGURO SOCIAL",
        "SEGURIDAD SOCIAL",
        "NO. DE SEGURIDAD SOCIAL",
        "NUMERO DE AFILIACION",
        "IMSS",
    ],
    "clabe": [
        "CLABE", "CLAVE BANCARIA ESTANDARIZADA",
        "CLABE INTERBANCARIA", "CLAVE INTERBANCARIA",
        "TRANSFERENCIA INTERBANCARIA", "INTERBANCARIA",
    ],
    "cuenta": [
        "CUENTA", "NO. DE CUENTA", "NO DE CUENTA",
        "NUMERO DE CUENTA", "NUM. CUENTA", "NUM CUENTA",
        "NUMERO CUENTA", "CUENTA BANCARIA",
    ],
    "nombre": [
        "NOMBRE", "NOMBRES", "NOMBRE DEL TITULAR",
        "NOMBRE DEL TRABAJADOR", "NOMBRE DEL ASEGURADO",
        "NOMBRE DEL BENEFICIARIO", "NOMBRE Y APELLIDOS",
        "NOMBRE COMPLETO", "NOMBRE O RAZON SOCIAL",
    ],
    "titular": [
        "TITULAR", "NOMBRE DEL TITULAR", "RAZON SOCIAL",
        "NOMBRE O RAZON SOCIAL", "NOMBRE DEL PROVEEDOR",
    ],
    "banco": [
        "BANCO", "BANCO DESTINO", "BANCO ORIGEN",
        "INSTITUCION BANCARIA", "INSTITUCION",
        "ENTIDAD BANCARIA", "BANCO DE DEPOSITO",
    ],
    "domicilio": [
        "DOMICILIO", "DOMICILIO FISCAL",
        "DOMICILIO DE SUMINISTRO", "DOMICILIO DEL CONTRIBUYENTE",
        "DOMICILIO REGISTRADO", "DIRECCION",
    ],
    "cp": [
        "C.P.", "CP", "COD. POSTAL", "CODIGO POSTAL",
        "C.P", "CP.",
    ],
    "fecha_nacimiento": [
        "FECHA DE NACIMIENTO", "FECHA NACIMIENTO",
        "F. NACIMIENTO", "F.NACIMIENTO", "NACIMIENTO",
        "FECHA NAC.", "FEC. NAC.",
    ],
    "fecha_corte": [
        "FECHA DE CORTE", "FECHA CORTE",
        "PERIODO DE CORTE", "CORTE",
    ],
    "fecha_emision": [
        "FECHA DE EMISION", "FECHA EMISION",
        "FECHA DE EXPEDICION", "EXPEDICION",
        "FECHA DE IMPRESION",
    ],
    "vigencia": [
        "VIGENCIA", "VIGENTE HASTA", "VALIDO HASTA",
        "VENCE", "FECHA DE VENCIMIENTO",
    ],
    "seccion": [
        "SECCION", "SECC.", "SECCION ELECTORAL",
    ],
    "clave_elector": [
        "CLAVE DE ELECTOR", "CLAVE ELECTOR",
        "CLAVE ELECT.", "CREDENCIAL DE ELECTOR",
    ],
    "folio": [
        "FOLIO", "NO. DE FOLIO", "NUMERO DE FOLIO",
        "FOLIO DE ACTA", "FOLIO ACTA",
    ],
    "numero_acta": [
        "NUMERO DE ACTA", "NO. DE ACTA", "NUMERO ACTA",
        "NO ACTA", "NRO ACTA", "ACTA NUMERO",
    ],
    "monto": [
        "MONTO", "IMPORTE", "TOTAL", "IMPORTE TOTAL",
        "MONTO TOTAL", "SALDO", "CANTIDAD",
        "IMPORTE A PAGAR", "TOTAL A PAGAR",
        "VALOR TOTAL", "CARGO", "ABONO",
        "DEPOSITO", "MONTO DEPOSITADO",
    ],
    "regimen": [
        "REGIMEN", "REGIMEN FISCAL", "REGIMEN CAPITAL",
        "TIPO DE REGIMEN",
    ],
    "sexo": [
        "SEXO", "GENERO", "GEN.",
    ],
    "lugar_nacimiento": [
        "LUGAR DE NACIMIENTO", "LUGAR NACIMIENTO",
        "LUGAR NAC.", "MUNICIPIO NACIMIENTO",
    ],
    "entidad_registro": [
        "ENTIDAD DE REGISTRO", "ENTIDAD REGISTRO",
        "ESTADO DE REGISTRO", "ESTADO REGISTRO",
    ],
    "municipio_registro": [
        "MUNICIPIO DE REGISTRO", "MUNICIPIO REGISTRO",
        "MUNICIPIO", "DELEGACION",
    ],
}

# Campos prioritarios por tipo de documento (los mas importantes primero)
CONTEXT_BY_DOC_TYPE: dict[str, list[str]] = {
    "INE": [
        "clave_elector", "curp", "nombre", "fecha_nacimiento",
        "seccion", "vigencia", "sexo", "domicilio",
    ],
    "CURP": [
        "curp", "nombre", "fecha_nacimiento", "sexo",
        "lugar_nacimiento", "entidad_registro",
    ],
    "NSS": [
        "nss", "nombre", "fecha_emision", "folio",
    ],
    "DATOS_BANCARIOS": [
        "clabe", "cuenta", "banco", "titular", "rfc", "fecha_corte", "monto",
    ],
    "COMPROBANTE_DOMICILIO": [
        "domicilio", "cp", "titular", "banco", "fecha_corte", "monto",
    ],
    "CONSTANCIA_SITUACION_FISCAL": [
        "rfc", "nombre", "cp", "domicilio", "regimen", "fecha_emision",
    ],
    "ACTA_NACIMIENTO": [
        "nombre", "fecha_nacimiento", "sexo", "lugar_nacimiento",
        "folio", "numero_acta", "entidad_registro", "municipio_registro",
    ],
    "FACTURA": [
        "titular", "rfc", "fecha_emision", "folio", "monto",
    ],
}

# ------------------------------------------------------------------------------
# Utilidades internas
# ------------------------------------------------------------------------------

def _normalize_line(line: str) -> str:
    t = unicodedata.normalize("NFKD", str(line or ""))
    try:
        t = t.encode("ascii", "ignore").decode("ascii")
    except Exception:
        pass
    return re.sub(r"\s+", " ", t).strip().upper()


def _extract_after_keyword(line: str, keyword: str) -> str:
    """Texto que sigue al keyword en la misma linea, sin el keyword."""
    idx = line.find(keyword)
    if idx < 0:
        return ""
    return line[idx + len(keyword):].strip(" :.-/")


_KEYWORDS_ALL: frozenset[str] = frozenset(
    kw.upper()
    for kws in CONTEXT_KEYWORDS.values()
    for kw in kws
)


def _looks_like_noise(value: str) -> bool:
    """Descarta valores que parecen ruido OCR, demasiado cortos, o solo keywords."""
    if not value or len(value) < 2:
        return True
    if not any(c.isalnum() for c in value):
        return True
    if len(value) > 120:
        return True
    # Es el propio keyword (no el valor)
    if value.upper() in _KEYWORDS_ALL:
        return True
    return False


# ------------------------------------------------------------------------------
# API publica
# ------------------------------------------------------------------------------

def find_value_near_context(
    lines: list[str],
    field: str,
    doc_type: str = "",
    window: int = 2,
) -> list[dict[str, Any]]:
    """Busca el valor de un campo buscando sus keywords en lineas adyacentes.

    Parameters
    ----------
    lines    : lineas del texto OCR (sin normalizar).
    field    : nombre canonico del campo (ej. 'rfc', 'curp').
    doc_type : tipo de documento (reservado para ajustes futuros).
    window   : lineas despues del keyword donde buscar el valor.

    Returns
    -------
    list[dict]  candidatos ordenados por confianza desc.
        Cada item: {key, label, value, confidence, source, context_keyword}
    """
    keywords = CONTEXT_KEYWORDS.get(field, [])
    if not keywords:
        return []

    label = field.replace("_", " ").title()
    keywords_upper = [kw.upper() for kw in keywords]
    normalized = [_normalize_line(ln) for ln in lines]

    candidates: list[dict] = []

    for idx, norm in enumerate(normalized):
        matched_kw: str | None = None
        for kw in keywords_upper:
            if kw in norm:
                matched_kw = kw
                break
        if matched_kw is None:
            continue

        # Valor en la misma linea despues del keyword
        tail = _extract_after_keyword(norm, matched_kw)
        if tail and not _looks_like_noise(tail):
            candidates.append({
                "key":             field,
                "label":           label,
                "value":           tail,
                "confidence":      0.62,
                "source":          "context",
                "context_keyword": matched_kw,
            })

        # Lineas siguientes (ventana)
        for offset in range(1, window + 1):
            next_idx = idx + offset
            if next_idx >= len(normalized):
                break
            next_norm = normalized[next_idx]
            if not next_norm:
                continue
            # Parar si la siguiente linea es otro keyword de cualquier campo
            if any(kw2 in next_norm for kw2 in keywords_upper if kw2 != matched_kw):
                break
            if not _looks_like_noise(next_norm):
                candidates.append({
                    "key":             field,
                    "label":           label,
                    "value":           next_norm,
                    "confidence":      max(0.52 - offset * 0.05, 0.35),
                    "source":          "context",
                    "context_keyword": matched_kw,
                })

    # Deduplicar por valor — conservar mayor confianza
    seen: dict[str, dict] = {}
    for c in candidates:
        v = c["value"]
        if v not in seen or c["confidence"] > seen[v]["confidence"]:
            seen[v] = c

    return sorted(seen.values(), key=lambda x: x["confidence"], reverse=True)


def extract_context_fields(
    lines: list[str],
    doc_type: str,
) -> list[dict[str, Any]]:
    """Extrae todos los campos posibles usando context_dicts.

    Llama a find_value_near_context() para cada campo relevante al doc_type
    y devuelve la mejor candidatura por campo.

    Parameters
    ----------
    lines    : lineas del texto OCR.
    doc_type : tipo de documento (determina que campos buscar primero).

    Returns
    -------
    list[dict]  un campo por clave, ordenados segun CONTEXT_BY_DOC_TYPE.
    """
    field_priority = CONTEXT_BY_DOC_TYPE.get(doc_type, list(CONTEXT_KEYWORDS.keys()))
    result: dict[str, dict] = {}

    for field in field_priority:
        candidates = find_value_near_context(lines, field, doc_type)
        if candidates:
            best = candidates[0]
            existing = result.get(field)
            if not existing or best["confidence"] > existing["confidence"]:
                result[field] = best

    return list(result.values())
