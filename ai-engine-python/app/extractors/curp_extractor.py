"""
CURP Extractor — extractor dedicado para Cédula de CURP

Campos que extrae:
  - curp
  - nombre
  - fecha_nacimiento
  - sexo
  - entidad_nacimiento

La CURP tiene reglas distintas a la INE:
  - No hay domicilio ni clave_elector
  - El nombre puede aparecer en campos separados (1er_apellido, 2do_apellido, nombres)
  - La entidad de nacimiento se valida contra los 32 códigos de estado
  - La CURP misma contiene metadatos (fecha, sexo, entidad) que se usan para validación cruzada

Delega al motor interno _extract_curp_from_boxes.
"""

from typing import Any

from app.pipelines.extract import extract_fields as _extract_fields
from app.pipelines.extract.extractors import _extract_curp_from_boxes

# Campos que este extractor debe devolver
EXPECTED_FIELDS = frozenset({
    "curp", "nombre", "fecha_nacimiento", "sexo", "entidad_nacimiento",
})

DOCUMENT_TYPE = "CURP"


async def extract(
    ocr_text: str,
    ocr_boxes: list[dict[str, Any]] | None = None,
    raw_text: str = "",
    filename: str | None = None,
) -> list[dict[str, Any]]:
    """
    Extrae campos de una Cédula de CURP.

    Args:
        ocr_text:  Texto completo resultado del OCR.
        ocr_boxes: Lista de bounding boxes del OCR.
        raw_text:  Texto del layer nativo del PDF.
        filename:  Nombre del archivo.

    Returns:
        Lista de campos extraídos. Campos esperados:
        curp, nombre, fecha_nacimiento, sexo, entidad_nacimiento.
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
    Extracción directa desde bounding boxes.
    Útil para evaluación rápida y pruebas unitarias.

    Returns:
        Dict con los valores encontrados {campo: valor}.
    """
    return _extract_curp_from_boxes(ocr_boxes)


def get_expected_fields() -> frozenset[str]:
    """Devuelve el conjunto de campos que este extractor debe producir."""
    return EXPECTED_FIELDS
