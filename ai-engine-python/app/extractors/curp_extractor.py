"""
CURP Extractor — extractor dedicado para Cédula de CURP

Campos que extrae:
  - curp
  - nombre
  - fecha_nacimiento
  - sexo
  - entidad_nacimiento

Estrategia de enriquecimiento post-pipeline:
  1. El pipeline CURP extrae campos desde bounding boxes y texto.
  2. _enrich_curp() añade fallbacks:
     - curp     → search_curp() con corrección OCR sobre el texto completo
     - sexo     → decodificado de la CURP (posición 10)
     - fecha_nacimiento → decodificado de la CURP (posiciones 4-9)
     - entidad_nacimiento → decodificado de la CURP (posiciones 11-12)
                         o búsqueda por etiqueta en el texto
     - nombre   → ensambla desde "1er Apellido / 2do Apellido / Nombre(s)"
                  si el pipeline no produjo un nombre

Notas:
  - La cédula RENAPO muestra apellidos y nombre en campos separados;
    _extract_name_from_text() los une en un nombre completo.
  - La CURP codifica fecha (YYMMDD), sexo (H/M) y entidad (2 letras),
    por lo que esos campos se pueden recuperar con alta confianza (0.95)
    incluso sin OCR de los campos del documento.
"""

import logging
import re
import unicodedata
from datetime import datetime
from typing import Any

from app.pipelines.extract import extract_fields as _extract_fields
from app.pipelines.extract.extractors import _extract_curp_from_boxes
from app.utils.regex_patterns import search_curp

logger = logging.getLogger(__name__)

EXPECTED_FIELDS = frozenset({
    "curp", "nombre", "fecha_nacimiento", "sexo", "entidad_nacimiento",
})

DOCUMENT_TYPE = "CURP"

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

# Etiquetas de entidad en la cédula RENAPO (orden: más específico primero)
_ENTITY_LABELS = (
    "ENTIDAD DE NACIMIENTO",
    "ENTIDAD FEDERATIVA DE NACIMIENTO",
    "ENTIDAD FEDERATIVA",
    "ESTADO DE NACIMIENTO",
    "ENTIDAD",
    "ESTADO",
)


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


def _extract_name_from_text(normalized: str) -> str | None:
    """
    Intenta ensamblar el nombre completo buscando las etiquetas
    'Primer Apellido', 'Segundo Apellido' y 'Nombre(s)' en el texto.

    Args:
        normalized: Texto sin acentos, en mayúsculas.

    Returns:
        Nombre completo si se encontraron al menos 2 partes, o None.
    """
    def _after(pattern: str) -> str | None:
        m = re.search(pattern + r"\s*[:\-]?\s*([A-Z][A-Z\s]{1,50})", normalized)
        if not m:
            return None
        val = m.group(1).strip()
        # Cortar en la siguiente etiqueta o doble espacio
        val = re.split(r"\s{2,}|\n|(?:CURP|FECHA|SEXO|ENTIDAD|ESTADO|REGISTRO|FOLIO|CLAVE)", val)[0]
        return val.strip() if len(val.strip()) >= 2 else None

    apellido1 = _after(r"(?:1ER?\s+APELLIDO|PRIMER\s+APELLIDO|APELLIDO\s+PATERNO)")
    apellido2 = _after(r"(?:2DO?\s+APELLIDO|SEGUNDO\s+APELLIDO|APELLIDO\s+MATERNO)")
    nombres   = _after(r"NOMBRE[S]?(?:\(?S?\)?)?")

    parts = [p for p in [apellido1, apellido2, nombres] if p]
    return " ".join(parts) if len(parts) >= 2 else None


# ─── Extractor principal ──────────────────────────────────────────────────────

async def extract(
    ocr_text: str,
    ocr_boxes: list[dict[str, Any]] | None = None,
    raw_text: str = "",
    filename: str | None = None,
    pdf_tables: list[list[list[str]]] | None = None,
) -> list[dict[str, Any]]:
    """
    Extrae campos de una Cédula de CURP (RENAPO).

    Args:
        ocr_text:   Texto completo resultado del OCR.
        ocr_boxes:  Lista de bounding boxes del OCR.
        raw_text:   Texto del layer nativo del PDF.
        filename:   Nombre del archivo.
        pdf_tables: Tablas detectadas (no usadas en CURP, por compatibilidad).

    Returns:
        Lista de campos extraídos. Campos esperados:
        curp, nombre, fecha_nacimiento, sexo, entidad_nacimiento.
    """
    fields = await _extract_fields(
        document_type=DOCUMENT_TYPE,
        ocr_text=ocr_text,
        ocr_boxes=ocr_boxes,
        raw_text=raw_text,
        filename=filename,
    )
    _enrich_curp(fields, ocr_text=ocr_text, raw_text=raw_text, filename=filename)
    return fields


# ─── Enriquecimiento post-pipeline ───────────────────────────────────────────

def _enrich_curp(
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
                "value": curp_val, "confidence": 0.90, "valid": True, "source": "ocr_fallback",
            })
            existing["curp"] = {"value": curp_val}

    # 2. Decodificar sexo, fecha_nacimiento y entidad_nacimiento desde la CURP
    if curp_val:
        decoded = _decode_curp(curp_val)
        _field_pairs = [
            ("fecha_nacimiento",  "Fecha de nacimiento"),
            ("sexo",              "Sexo"),
            ("entidad_nacimiento","Entidad de nacimiento"),
        ]
        for key, label in _field_pairs:
            if key not in existing and key in decoded:
                fields.append({
                    "key": key, "label": label,
                    "value": decoded[key], "confidence": 0.95,
                    "valid": True, "source": "curp",
                })
                existing[key] = {"value": decoded[key]}

    # 3. Nombre — ensamblar desde etiquetas de apellido/nombre en el texto
    if "nombre" not in existing and normalized:
        nombre = _extract_name_from_text(normalized)
        if nombre and len(nombre) >= 4:
            fields.append({
                "key": "nombre", "label": "Nombre",
                "value": nombre, "confidence": 0.80, "valid": True, "source": None,
            })
            existing["nombre"] = {"value": nombre}

    # 4. entidad_nacimiento — búsqueda por etiqueta si no vino de la CURP
    if "entidad_nacimiento" not in existing and normalized:
        for label in _ENTITY_LABELS:
            escaped = re.escape(unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii"))
            m = re.search(rf"{escaped}\s*[:\-]?\s*([A-Z][A-Z\s]{{2,50}})", normalized)
            if m:
                val = m.group(1).strip()
                # Eliminar ruido de fin de línea o doble espacio
                val = re.split(r"\s{2,}|\n|\d", val)[0].strip().rstrip(".,;")
                if len(val) >= 3 and not re.search(r"\d", val):
                    fields.append({
                        "key": "entidad_nacimiento", "label": "Entidad de nacimiento",
                        "value": val.title(), "confidence": 0.80,
                        "valid": True, "source": None,
                    })
                    break

    _log_coverage(fields, filename)


def _log_coverage(fields: list[dict[str, Any]], filename: str | None) -> None:
    """Log de cobertura: qué campos se encontraron y cuáles faltan."""
    found = {f["key"] for f in fields if f.get("value")}
    hit = found & EXPECTED_FIELDS
    missing = EXPECTED_FIELDS - found
    pct = int(100 * len(hit) / len(EXPECTED_FIELDS))
    logger.info(
        "curp [%s]: %d%% cobertura | encontrados=%s | faltantes=%s",
        filename or "?", pct,
        sorted(hit),
        sorted(missing) or "ninguno",
    )


# ─── API pública ──────────────────────────────────────────────────────────────

def extract_from_boxes(ocr_boxes: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Extracción directa desde bounding boxes.
    Útil para evaluación rápida y pruebas unitarias.
    """
    return _extract_curp_from_boxes(ocr_boxes)


def get_expected_fields() -> frozenset[str]:
    """Devuelve el conjunto de campos que este extractor debe producir."""
    return EXPECTED_FIELDS
