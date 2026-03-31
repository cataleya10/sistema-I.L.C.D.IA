"""
INE Extractor — extractor dedicado para Credencial para Votar (INE/IFE)

Campos que extrae:
  - curp
  - nombre
  - fecha_nacimiento
  - sexo
  - domicilio
  - clave_elector
  - seccion
  - vigencia
  - entidad_nacimiento

Estrategia de enriquecimiento post-pipeline:
  1. El pipeline INE extrae campos desde bounding boxes y texto.
  2. _enrich_ine() añade fallbacks:
     - curp     → search_curp() con corrección OCR sobre el texto completo
     - sexo     → decodificado de la CURP (posición 10)
     - fecha_nacimiento → decodificado de la CURP (posiciones 4-9)
     - entidad_nacimiento → decodificado de la CURP (posiciones 11-12)
     - vigencia → regex de rango de años en el texto
"""

import logging
import re
import unicodedata
from datetime import datetime
from typing import Any

from app.pipelines.extract import extract_fields as _extract_fields
from app.pipelines.extract.extractors import _extract_ine_from_boxes
from app.utils.regex_patterns import search_curp

logger = logging.getLogger(__name__)

EXPECTED_FIELDS = frozenset({
    "curp", "nombre", "fecha_nacimiento", "sexo",
    "domicilio", "clave_elector", "seccion", "vigencia", "entidad_nacimiento",
})

DOCUMENT_TYPE = "INE"

# Mapa de códigos de entidad en la CURP → nombre completo de la entidad
_CURP_STATE_MAP: dict[str, str] = {
    "AS": "Aguascalientes",
    "BC": "Baja California",
    "BS": "Baja California Sur",
    "CC": "Campeche",
    "CL": "Coahuila",
    "CM": "Colima",
    "CS": "Chiapas",
    "CH": "Chihuahua",
    "DF": "Ciudad de México",
    "CD": "Ciudad de México",
    "DG": "Durango",
    "GT": "Guanajuato",
    "GR": "Guerrero",
    "HG": "Hidalgo",
    "JC": "Jalisco",
    "MC": "Estado de México",
    "MN": "Michoacán",
    "MS": "Morelos",
    "NT": "Nayarit",
    "NL": "Nuevo León",
    "OC": "Oaxaca",
    "PL": "Puebla",
    "QT": "Querétaro",
    "QR": "Quintana Roo",
    "SP": "San Luis Potosí",
    "SL": "Sinaloa",
    "SR": "Sonora",
    "TC": "Tabasco",
    "TS": "Tamaulipas",
    "TL": "Tlaxcala",
    "VZ": "Veracruz",
    "YN": "Yucatán",
    "ZS": "Zacatecas",
    "NE": "Nacido en el Extranjero",
}


def _decode_curp(curp: str) -> dict[str, str]:
    """
    Extrae fecha de nacimiento, sexo y entidad federativa de una CURP.

    La CURP tiene 18 caracteres:
      0-3  : iniciales del nombre/apellidos
      4-5  : año de nacimiento (YY)
      6-7  : mes de nacimiento (MM)
      8-9  : día de nacimiento (DD)
      10   : sexo (H=Hombre, M=Mujer)
      11-12: código de entidad federativa
      13-16: consonantes del nombre (+ dígito verificador)
      17   : homoclave alfanumérica

    Returns:
        Dict con los campos decodificados. Vacío si la CURP es inválida.
    """
    result: dict[str, str] = {}
    if not curp or len(curp) < 16:
        return result

    # Fecha de nacimiento (posiciones 4-9)
    try:
        yy = int(curp[4:6])
        mm = int(curp[6:8])
        dd = int(curp[8:10])
        current_yy = datetime.now().year % 100
        year = (2000 + yy) if yy <= current_yy else (1900 + yy)
        if 1 <= mm <= 12 and 1 <= dd <= 31:
            result["fecha_nacimiento"] = f"{dd:02d}/{mm:02d}/{year}"
    except ValueError:
        pass

    # Sexo (posición 10)
    sex = curp[10].upper() if len(curp) > 10 else ""
    if sex in {"H", "M"}:
        result["sexo"] = sex

    # Entidad federativa (posiciones 11-12)
    if len(curp) >= 13:
        state_code = curp[11:13].upper()
        if state_code in _CURP_STATE_MAP:
            result["entidad_nacimiento"] = _CURP_STATE_MAP[state_code]

    return result


# ─── Extractor principal ──────────────────────────────────────────────────────

async def extract(
    ocr_text: str,
    ocr_boxes: list[dict[str, Any]] | None = None,
    raw_text: str = "",
    filename: str | None = None,
    pdf_tables: list[list[list[str]]] | None = None,
) -> list[dict[str, Any]]:
    """
    Extrae campos de una Credencial para Votar (INE/IFE).

    Args:
        ocr_text:   Texto completo resultado del OCR.
        ocr_boxes:  Lista de bounding boxes del OCR (mejora precisión de campos).
        raw_text:   Texto del layer nativo del PDF (si aplica).
        filename:   Nombre del archivo.
        pdf_tables: Tablas detectadas (no usadas en INE, por compatibilidad).

    Returns:
        Lista de campos extraídos. Campos esperados:
        curp, nombre, fecha_nacimiento, sexo, domicilio,
        clave_elector, seccion, vigencia, entidad_nacimiento.
    """
    fields = await _extract_fields(
        document_type=DOCUMENT_TYPE,
        ocr_text=ocr_text,
        ocr_boxes=ocr_boxes,
        raw_text=raw_text,
        filename=filename,
    )
    _enrich_ine(fields, ocr_text=ocr_text, raw_text=raw_text, filename=filename)
    return fields


# ─── Enriquecimiento post-pipeline ───────────────────────────────────────────

def _enrich_ine(
    fields: list[dict[str, Any]],
    ocr_text: str,
    raw_text: str,
    filename: str | None,
) -> None:
    """
    Añade fallbacks para campos que el pipeline no pudo extraer directamente.
    Modifica la lista in-place.
    """
    existing = {f["key"]: f for f in fields if f.get("value")}
    combined = (raw_text or "") or (ocr_text or "")
    upper = combined.upper()
    normalized = unicodedata.normalize("NFKD", upper).encode("ascii", "ignore").decode("ascii")

    # 1. CURP — fallback con corrección OCR (O↔0, I↔1)
    curp_val = existing.get("curp", {}).get("value") if "curp" in existing else None
    if not curp_val:
        curp_val = search_curp(normalized)
        if curp_val:
            fields.append({
                "key": "curp", "label": "CURP",
                "value": curp_val, "confidence": 0.85, "valid": True, "source": "ocr_fallback",
            })
            existing["curp"] = {"value": curp_val}

    # 2. Decodificar sexo, fecha_nacimiento y entidad_nacimiento desde la CURP
    if curp_val:
        decoded = _decode_curp(curp_val)
        _field_pairs = [
            ("fecha_nacimiento", "Fecha de nacimiento"),
            ("sexo",             "Sexo"),
            ("entidad_nacimiento", "Entidad de nacimiento"),
        ]
        for key, label in _field_pairs:
            if key not in existing and key in decoded:
                fields.append({
                    "key": key, "label": label,
                    "value": decoded[key], "confidence": 0.95,
                    "valid": True, "source": "curp",
                })
                existing[key] = {"value": decoded[key]}

    # 3. Vigencia — fallback por rango de años en el texto
    if "vigencia" not in existing and combined:
        m = re.search(r"\b(20\d{2})\s*[-–]\s*(20\d{2})\b", combined)
        if m:
            fields.append({
                "key": "vigencia", "label": "Vigencia",
                "value": f"{m.group(1)}-{m.group(2)}",
                "confidence": 0.85, "valid": True, "source": None,
            })
        else:
            # Solo año de expiración junto a la etiqueta VIGENCIA
            m2 = re.search(r"VIGENCIA\D{0,10}(20\d{2})", normalized)
            if m2:
                fields.append({
                    "key": "vigencia", "label": "Vigencia",
                    "value": m2.group(1),
                    "confidence": 0.75, "valid": True, "source": None,
                })

    _log_coverage(fields, filename)


def _log_coverage(fields: list[dict[str, Any]], filename: str | None) -> None:
    """Log de cobertura: qué campos se encontraron y cuáles faltan."""
    found = {f["key"] for f in fields if f.get("value")}
    hit = found & EXPECTED_FIELDS
    missing = EXPECTED_FIELDS - found
    pct = int(100 * len(hit) / len(EXPECTED_FIELDS))
    logger.info(
        "ine [%s]: %d%% cobertura | encontrados=%s | faltantes=%s",
        filename or "?", pct,
        sorted(hit),
        sorted(missing) or "ninguno",
    )


# ─── API pública ──────────────────────────────────────────────────────────────

def extract_from_boxes(ocr_boxes: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Extracción directa desde bounding boxes (sin pasar por el orquestador).
    Útil para evaluación rápida y pruebas unitarias.
    """
    return _extract_ine_from_boxes(ocr_boxes)


def get_expected_fields() -> frozenset[str]:
    """Devuelve el conjunto de campos que este extractor debe producir."""
    return EXPECTED_FIELDS
