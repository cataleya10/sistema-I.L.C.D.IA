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

Delega al motor interno _extract_ine_from_boxes y al orquestador
con document_type="INE", sin mezclarse con la lógica de otros documentos.
"""

from typing import Any

from app.pipelines.extract import extract_fields as _extract_fields
from app.pipelines.extract.extractors import _extract_ine_from_boxes

# Campos que este extractor debe devolver (para filtrado y validación)
EXPECTED_FIELDS = frozenset({
    "curp", "nombre", "fecha_nacimiento", "sexo",
    "domicilio", "clave_elector", "seccion", "vigencia", "entidad_nacimiento",
})

DOCUMENT_TYPE = "INE"


async def extract(
    ocr_text: str,
    ocr_boxes: list[dict[str, Any]] | None = None,
    raw_text: str = "",
    filename: str | None = None,
) -> list[dict[str, Any]]:
    """
    Extrae campos de una Credencial para Votar (INE/IFE).

    Args:
        ocr_text:  Texto completo resultado del OCR.
        ocr_boxes: Lista de bounding boxes del OCR (mejora precisión de campos).
        raw_text:  Texto del layer nativo del PDF (si aplica).
        filename:  Nombre del archivo (ayuda al clasificador).

    Returns:
        Lista de campos extraídos. Campos esperados:
        curp, nombre, fecha_nacimiento, sexo, domicilio,
        clave_elector, seccion, vigencia, entidad_nacimiento.
    """
    return await _extract_fields(
        document_type=DOCUMENT_TYPE,
        ocr_text=ocr_text,
        ocr_boxes=ocr_boxes,
        raw_text=raw_text,
        filename=filename,
    )


def extract_from_boxes(ocr_boxes: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Extracción directa desde bounding boxes (sin pasar por el orquestador).
    Útil para evaluación rápida y pruebas unitarias.

    Returns:
        Dict con los valores encontrados {campo: valor}.
    """
    return _extract_ine_from_boxes(ocr_boxes)


def get_expected_fields() -> frozenset[str]:
    """Devuelve el conjunto de campos que este extractor debe producir."""
    return EXPECTED_FIELDS
