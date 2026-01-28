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
        _ocr_instance = PaddleOCR(use_angle_cls=True, lang="es")
    return _ocr_instance


def _get_rapid():
    global _rapid_instance
    if RapidOCR is None:
        return None
    if _rapid_instance is None:
        _rapid_instance = RapidOCR()
    return _rapid_instance


async def run_ocr(image):
    ocr = _get_ocr()
    if np is None:
        return "", []

    image_array = np.array(image)
    texts = []
    boxes = []
    result = []
    if ocr is not None:
        result = ocr.ocr(image_array, cls=True)
    if not result:
        rapid = _get_rapid()
        if rapid is None:
            return "", []
        rapid_result, _ = rapid(image_array)
        for item in rapid_result or []:
            box, text, confidence = item
            texts.append(str(text).upper())
            boxes.append({"text": text, "confidence": confidence, "bbox": box})
        return "\n".join(texts), boxes

    for line in result:
        for item in line:
            box, (text, confidence) = item
            texts.append(text.upper())
            boxes.append({"text": text, "confidence": confidence, "bbox": box})

    return "\n".join(texts), boxes
