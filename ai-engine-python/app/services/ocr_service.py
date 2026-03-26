"""
OCR Service — wrapper sobre app/pipelines/ocr.py

Centraliza el acceso al motor de OCR para que:
- El endpoint no importe pipelines directamente
- Los tests y el entrenamiento puedan llamar OCR de forma aislada
"""

from typing import Any

from app.pipelines.ocr import run_ocr, warm_up


async def extract_text_from_images(
    images: Any,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Ejecuta OCR sobre una lista de imágenes PIL.

    Args:
        images: Lista de imágenes PIL.Image (una por página).

    Returns:
        Tupla (texto_completo, lista_de_boxes).
        - texto_completo: todo el texto concatenado con saltos de línea.
        - lista_de_boxes: cada box tiene {text, confidence, bbox, page, engine}.
    """
    return await run_ocr(images)


def warm_up_ocr() -> None:
    """Pre-carga los modelos OCR para que la primera petición no pague el costo de inicio."""
    warm_up()
