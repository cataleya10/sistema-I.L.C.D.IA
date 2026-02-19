from fastapi import UploadFile
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import io
import fitz
from app.core.config import settings


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


async def preprocess(file: UploadFile):
    content = await file.read()

    if file.content_type == "application/pdf" or file.filename.lower().endswith(".pdf"):
        extracted_parts: list[str] = []
        text_layer_boxes: list[dict] = []
        with fitz.open(stream=content, filetype="pdf") as doc:
            for index, page in enumerate(doc):
                if index >= settings.max_pages:
                    break
                extracted_parts.append(page.get_text("text") or "")
                for word in page.get_text("words") or []:
                    if len(word) < 5:
                        continue
                    x0, y0, x1, y1, text = word[:5]
                    text_str = str(text or "").strip()
                    if not text_str:
                        continue
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
        with fitz.open(stream=content, filetype="pdf") as doc:
            for index, page in enumerate(doc):
                if index >= settings.max_pages:
                    break
                pix = page.get_pixmap(dpi=settings.pdf_render_dpi)
                image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                image = ImageOps.autocontrast(image)
                image = ImageEnhance.Contrast(image.convert("L")).enhance(2.0)
                image = ImageEnhance.Sharpness(image).enhance(2.0)
                image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3)).convert("RGB")
                images.append(image)

        return images, extracted_text, text_layer_boxes

    image = Image.open(io.BytesIO(content)).convert("RGB")
    if image.width < 1200:
        scale = 1200 / image.width
        image = image.resize((int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS)
    image = ImageOps.autocontrast(image)
    image = ImageEnhance.Contrast(image.convert("L")).enhance(1.8)
    image = ImageEnhance.Sharpness(image).enhance(2.0)
    image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3)).convert("RGB")
    return [image], "", []
