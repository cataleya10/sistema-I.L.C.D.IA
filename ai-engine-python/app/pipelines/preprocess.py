from fastapi import UploadFile
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import io
import logging
import fitz
from typing import Any, cast
from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

_IMAGE_MODULE = cast(Any, Image)
_RESAMPLING = getattr(_IMAGE_MODULE, "Resampling", _IMAGE_MODULE)
_LANCZOS = getattr(_RESAMPLING, "LANCZOS", getattr(_IMAGE_MODULE, "LANCZOS", 1))


def _word_payload(raw_word: Any) -> tuple[float, float, float, float, str] | None:
    if not isinstance(raw_word, (list, tuple)) or len(raw_word) < 5:
        return None
    x0, y0, x1, y1, text = raw_word[:5]
    try:
        x0_val = float(x0)
        y0_val = float(y0)
        x1_val = float(x1)
        y1_val = float(y1)
    except (TypeError, ValueError):
        return None
    text_val = str(text or "").strip()
    if not text_val:
        return None
    return x0_val, y0_val, x1_val, y1_val, text_val


def _has_sufficient_text_layer(text: str) -> bool:
    compact = " ".join((text or "").split())
    if not compact:
        return False

    alnum_count = sum(1 for ch in compact if ch.isalnum())
    word_count = len(compact.split(" "))
    return (
        alnum_count >= settings.min_text_layer_chars
        and word_count >= settings.min_text_layer_words
    )


async def preprocess(file: UploadFile) -> tuple[list[Image.Image], str, list[dict[str, Any]]]:
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError(f"File too large ({len(content)} bytes, max {MAX_UPLOAD_BYTES})")
    filename = str(file.filename or "")
    content_type = str(file.content_type or "")

    if content_type == "application/pdf" or filename.lower().endswith(".pdf"):
        extracted_parts: list[str] = []
        text_layer_boxes: list[dict[str, Any]] = []
        with fitz.open(stream=content, filetype="pdf") as doc:  # type: ignore[attr-defined]
            max_pages = min(len(doc), settings.max_pages)
            for index in range(max_pages):
                page = doc.load_page(index)
                extracted_parts.append(str(page.get_text("text") or ""))
                words: Any = page.get_text("words")
                if not isinstance(words, list):
                    continue
                for raw_word in words:
                    payload = _word_payload(raw_word)
                    if payload is None:
                        continue
                    x0, y0, x1, y1, text_str = payload
                    text_layer_boxes.append(
                        {
                            "text": text_str,
                            "confidence": 1.0,
                            "bbox": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
                            "page": index + 1,
                        }
                    )

        extracted_text = "\n\n".join(part for part in extracted_parts if part)
        if settings.enable_text_layer_short_circuit and _has_sufficient_text_layer(extracted_text):
            return [], extracted_text, text_layer_boxes

        images: list[Image.Image] = []
        with fitz.open(stream=content, filetype="pdf") as doc:  # type: ignore[attr-defined]
            max_pages = min(len(doc), settings.max_pages)
            for index in range(max_pages):
                page = doc.load_page(index)
                pix = page.get_pixmap(dpi=settings.pdf_render_dpi)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                image = ImageOps.autocontrast(image)
                image = ImageEnhance.Contrast(image.convert("L")).enhance(2.0)
                image = ImageEnhance.Sharpness(image).enhance(2.0)
                image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3)).convert("RGB")
                images.append(image)

        return images, extracted_text, text_layer_boxes

    image = Image.open(io.BytesIO(content)).convert("RGB")
    if image.width < 1200:
        width = max(image.width, 1)
        scale = 1200 / width
        image = image.resize((int(image.width * scale), int(image.height * scale)), _LANCZOS)
    image = ImageOps.autocontrast(image)
    image = ImageEnhance.Contrast(image.convert("L")).enhance(1.8)
    image = ImageEnhance.Sharpness(image).enhance(2.0)
    image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3)).convert("RGB")
    return [image], "", []
