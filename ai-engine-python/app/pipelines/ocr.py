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

_ocr_instance = None
_rapid_instance = None


def _get_ocr():
    global _ocr_instance
    if PaddleOCR is None:
        return None
    if _ocr_instance is None:
        try:
            _ocr_instance = PaddleOCR(use_angle_cls=True, lang="es")
        except Exception:  # pragma: no cover
            _ocr_instance = None
    return _ocr_instance


def _get_rapid():
    global _rapid_instance
    if RapidOCR is None:
        return None
    if _rapid_instance is None:
        try:
            _rapid_instance = RapidOCR()
        except Exception:  # pragma: no cover
            _rapid_instance = None
    return _rapid_instance


async def run_ocr(images):
    ocr = _get_ocr()
    if np is None:
        return "", []

    if not isinstance(images, list):
        images = [images]

    texts: list[str] = []
    boxes: list[dict] = []

    for page_index, image in enumerate(images, start=1):
        image_array = np.array(image)
        result = []
        if ocr is not None:
            try:
                result = ocr.ocr(image_array, cls=True)
            except Exception:  # pragma: no cover
                result = []
        if not result:
            rapid = _get_rapid()
            if rapid is None:
                continue
            try:
                rapid_result, _ = rapid(image_array)
            except Exception:  # pragma: no cover
                continue
            for item in rapid_result or []:
                box, text, confidence = item
                text_str = str(text)
                texts.append(text_str.upper())
                boxes.append({"text": text_str, "confidence": confidence, "bbox": box, "page": page_index})
            continue

        for line in result:
            for item in line:
                box, (text, confidence) = item
                texts.append(text.upper())
                boxes.append({"text": text, "confidence": confidence, "bbox": box, "page": page_index})

    return "\n".join(texts), boxes
