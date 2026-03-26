"""
Extractors package — punto de entrada para todos los extractores por tipo documental

Uso:
    from app.extractors import get_extractor
    extractor = get_extractor("INE")
    fields = await extractor.extract(ocr_text, ocr_boxes)

O directamente:
    from app.extractors import ine_extractor
    fields = await ine_extractor.extract(ocr_text, ocr_boxes)
"""

from app.extractors import (
    ine_extractor,
    curp_extractor,
    nomina_extractor,
    bancario_extractor,
    generic_extractor,
)

# Registro de extractores por tipo de documento
_EXTRACTOR_REGISTRY = {
    "INE":                       ine_extractor,
    "IFE":                       ine_extractor,      # alias
    "CURP":                      curp_extractor,
    "NOMINA":                    nomina_extractor,
    "RECIBO_NOMINA":             nomina_extractor,   # alias
    "DATOS_BANCARIOS":           bancario_extractor,
    "ESTADO_CUENTA":             bancario_extractor, # alias
    "GENERICO":                  generic_extractor,
    "UNKNOWN":                   generic_extractor,
}


def get_extractor(document_type: str):
    """
    Retorna el módulo extractor correspondiente al tipo de documento.

    Args:
        document_type: Tipo clasificado del documento (ej. "INE", "CURP").

    Returns:
        Módulo extractor con función `extract(ocr_text, ocr_boxes, ...)`.
        Si el tipo no tiene extractor dedicado, retorna generic_extractor.
    """
    return _EXTRACTOR_REGISTRY.get(document_type.upper(), generic_extractor)


def list_supported_types() -> list[str]:
    """Retorna la lista de tipos de documento con extractor dedicado."""
    return sorted(set(_EXTRACTOR_REGISTRY.keys()))


__all__ = [
    "ine_extractor",
    "curp_extractor",
    "nomina_extractor",
    "bancario_extractor",
    "generic_extractor",
    "get_extractor",
    "list_supported_types",
]
