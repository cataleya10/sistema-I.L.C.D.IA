import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

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
_ocr_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ocr")


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


def warm_up() -> None:
    """Pre-load OCR models so the first request doesn't pay the startup cost."""
    logger.info("OCR warm-up: pre-loading models...")
    paddle = _get_ocr()
    rapid = _get_rapid()
    if paddle is None and rapid is None:
        logger.warning("OCR warm-up: no OCR backend available (PaddleOCR/RapidOCR unavailable)")
    elif paddle is None:
        logger.info("OCR warm-up: using RapidOCR backend")
    elif rapid is None:
        logger.info("OCR warm-up: using PaddleOCR backend")
    else:
        logger.info("OCR warm-up: using PaddleOCR + RapidOCR backends")
    logger.info("OCR warm-up: done")


def _ocr_single_page(ocr: Any, rapid: Any, image_array: Any, page_index: int) -> tuple[list[str], list[dict[str, Any]]]:
    """OCR a single page (runs in thread pool). Returns (texts, boxes)."""
    texts: list[str] = []
    boxes: list[dict[str, Any]] = []
    result: list[Any] = []
    if ocr is not None:
        try:
            result = ocr.ocr(image_array, cls=True)
        except Exception:  # pragma: no cover
            logger.warning("PaddleOCR failed on page %d", page_index, exc_info=True)
            result = []
    if not result:
        if rapid is None:
            return texts, boxes
        try:
            rapid_result, _ = rapid(image_array)
        except Exception:  # pragma: no cover
            logger.warning("RapidOCR failed on page %d", page_index, exc_info=True)
            return texts, boxes
        for item in rapid_result or []:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            box = item[0]
            text = item[1]
            confidence = item[2]
            text_str = str(text)
            texts.append(text_str.upper())
            boxes.append(
                {
                    "text": text_str,
                    "confidence": confidence,
                    "bbox": box,
                    "page": page_index,
                    "engine": "rapidocr",
                }
            )
        return texts, boxes

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
            boxes.append(
                {
                    "text": text,
                    "confidence": confidence,
                    "bbox": box,
                    "page": page_index,
                    "engine": "paddleocr",
                }
            )
    return texts, boxes


async def run_ocr(images: Any) -> tuple[str, list[dict[str, Any]]]:
    ocr = _get_ocr()
    if np is None:
        return "", []

    if not isinstance(images, list):
        images = [images]

    if not images:
        return "", []

    rapid = _get_rapid()
    loop = asyncio.get_event_loop()

    # Process pages in parallel using the OCR thread pool
    futures = []
    for page_index, image in enumerate(images, start=1):
        image_array = np.array(image)
        futures.append(
            loop.run_in_executor(
                _ocr_pool,
                _ocr_single_page,
                ocr, rapid, image_array, page_index,
            )
        )

    results = await asyncio.gather(*futures, return_exceptions=True)

    all_texts: list[str] = []
    all_boxes: list[dict[str, Any]] = []
    for res in results:
        if isinstance(res, Exception):
            logger.warning("OCR page failed: %s", res)
            continue
        page_texts, page_boxes = res
        all_texts.extend(page_texts)
        all_boxes.extend(page_boxes)

    return "\n".join(all_texts), all_boxes
