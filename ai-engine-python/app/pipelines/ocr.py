import asyncio
import logging

try:
    from paddleocr import PaddleOCR
except Exception:  # pragma: no cover
    PaddleOCR = None

try:
    import numpy as np
except Exception:  # pragma: no cover
    np = None

try:
    from rapidocr_onnxruntime import RapidOCR
except Exception:  # pragma: no cover
    RapidOCR = None

from typing import Any

logger = logging.getLogger(__name__)

_ocr_instance = None
_rapid_instance = None


def _get_ocr() -> Any | None:
    global _ocr_instance
    if PaddleOCR is None:
        return None
    if _ocr_instance is None:
        try:
            _ocr_instance = PaddleOCR(use_angle_cls=True, lang="es")
        except Exception:  # pragma: no cover
            logger.warning("PaddleOCR initialization failed", exc_info=True)
            _ocr_instance = None
    return _ocr_instance


def _get_rapid() -> Any | None:
    global _rapid_instance
    if RapidOCR is None:
        return None
    if _rapid_instance is None:
        try:
            _rapid_instance = RapidOCR()
        except Exception:  # pragma: no cover
            logger.warning("RapidOCR initialization failed", exc_info=True)
            _rapid_instance = None
    return _rapid_instance


async def run_ocr(images: Any) -> tuple[str, list[dict[str, Any]]]:
    ocr = _get_ocr()
    if np is None:
        return "", []

    if not isinstance(images, list):
        images = [images]

    texts: list[str] = []
    boxes: list[dict[str, Any]] = []

    for page_index, image in enumerate(images, start=1):
        image_array = np.array(image)
        result: list[Any] = []
        if ocr is not None:
            try:
                result = await asyncio.to_thread(ocr.ocr, image_array, cls=True)
            except Exception:  # pragma: no cover
                logger.warning("PaddleOCR failed on page %d", page_index, exc_info=True)
                result = []
        if not result:
            rapid = _get_rapid()
            if rapid is None:
                continue
            try:
                rapid_result, _ = await asyncio.to_thread(rapid, image_array)
            except Exception:  # pragma: no cover
                logger.warning("RapidOCR failed on page %d", page_index, exc_info=True)
                continue
            for item in rapid_result or []:
                if not isinstance(item, (list, tuple)) or len(item) < 3:
                    continue
                box = item[0]
                text = item[1]
                confidence = item[2]
                text_str = str(text)
                texts.append(text_str.upper())
                boxes.append({"text": text_str, "confidence": confidence, "bbox": box, "page": page_index})
            continue

        for line in result:
            if not isinstance(line, (list, tuple)):
                continue
            for item in line:
                if not isinstance(item, (list, tuple)) or len(item) < 2:
                    continue
                box = item[0]
                text_payload = item[1]
                if not isinstance(text_payload, (list, tuple)) or len(text_payload) < 2:
                    continue
                text = str(text_payload[0] or "")
                confidence = text_payload[1]
                if not text:
                    continue
                texts.append(text.upper())
                boxes.append({"text": text, "confidence": confidence, "bbox": box, "page": page_index})

    return "\n".join(texts), boxes
