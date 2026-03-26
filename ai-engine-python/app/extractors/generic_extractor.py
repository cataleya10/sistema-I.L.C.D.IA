"""
Generic Extractor — extractor para documentos no clasificados o de tipo desconocido

Campos que extrae (los que encuentre):
  - Cualquier par clave-valor detectado por layout espacial
  - Identificadores estándar: CURP, RFC, NSS, CLABE si aparecen
  - Todas las tablas detectadas en el documento
  - texto_detectado (snippet del contenido OCR)

Cuándo se usa:
  - Documentos de tipo GENERICO o UNKNOWN
  - Como fallback cuando el clasificador no tiene suficiente confianza
  - Para documentos nuevos aún no entrenados (primer paso antes de crear extractor dedicado)

Reglas:
  - No asume estructura fija: extrae KV por posición espacial y por patrones
  - Los campos tienen confianza más baja que extractores dedicados
  - Útil para inspección manual y para alimentar el pipeline de entrenamiento
"""

from typing import Any

from app.pipelines.extract import extract_fields as _extract_fields
from app.pipelines.extract.extractors import (
    _extract_generic_kv_from_text,
    _extract_generic_kv_from_boxes,
)

DOCUMENT_TYPE_GENERIC  = "GENERICO"
DOCUMENT_TYPE_UNKNOWN  = "UNKNOWN"


async def extract(
    ocr_text: str,
    ocr_boxes: list[dict[str, Any]] | None = None,
    raw_text: str = "",
    filename: str | None = None,
    pdf_tables: list[list[list[str]]] | None = None,
    document_type: str = DOCUMENT_TYPE_GENERIC,
) -> list[dict[str, Any]]:
    """
    Extrae campos de un documento de tipo desconocido o genérico.

    Args:
        ocr_text:      Texto OCR completo.
        ocr_boxes:     Bounding boxes del OCR.
        raw_text:      Texto nativo del PDF.
        filename:      Nombre del archivo.
        pdf_tables:    Tablas detectadas.
        document_type: "GENERICO" o "UNKNOWN" (default: "GENERICO").

    Returns:
        Lista de campos encontrados. Puede incluir:
        - texto_detectado
        - Pares KV detectados por layout
        - Identificadores estándar (CURP, RFC, NSS, CLABE) si aparecen
        - tabla_celdas, tabla_celdas_2... si hay tablas
    """
    return await _extract_fields(
        document_type=document_type,
        ocr_text=ocr_text,
        ocr_boxes=ocr_boxes,
        raw_text=raw_text,
        filename=filename,
        pdf_tables=pdf_tables,
    )


def extract_kv_from_text(text: str) -> list[dict[str, Any]]:
    """
    Extrae pares clave-valor directamente del texto plano usando patrones.
    No requiere boxes. Útil para pre-análisis rápido.

    Returns:
        Lista de {key, label, value, confidence}.
    """
    return _extract_generic_kv_from_text(text)


def extract_kv_from_boxes(ocr_boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Extrae pares clave-valor usando la posición espacial de los bounding boxes.
    Más preciso que extract_kv_from_text para documentos con layout estructurado.

    Returns:
        Lista de {key, label, value, confidence}.
    """
    return _extract_generic_kv_from_boxes(ocr_boxes)


def extract_identifiers(
    ocr_text: str,
    ocr_boxes: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """
    Busca identificadores estándar en el texto: CURP, RFC, NSS, CLABE.
    Útil para pre-clasificación o enriquecimiento de documentos desconocidos.

    Returns:
        Dict {tipo_identificador: valor} con los encontrados.
    """
    import re
    from app.pipelines.extract.common import (
        CURP_PATTERN, RFC_PATTERN, NSS_PATTERN, CLABE_PATTERN, _normalize_text,
    )

    text = _normalize_text(ocr_text)
    result: dict[str, str] = {}

    curp_m = CURP_PATTERN.search(text)
    if curp_m:
        result["curp"] = curp_m.group(0)

    rfc_m = RFC_PATTERN.search(text)
    if rfc_m:
        result["rfc"] = rfc_m.group(0)

    clabe_m = CLABE_PATTERN.search(text)
    if clabe_m:
        result["clabe"] = clabe_m.group(0)
    else:
        nss_m = NSS_PATTERN.search(text)
        if nss_m:
            result["nss"] = nss_m.group(0)

    return result
