from fastapi import UploadFile
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import io
import fitz
from app.core.config import settings

async def preprocess(file: UploadFile):
    content = await file.read()

    if file.content_type == "application/pdf" or file.filename.lower().endswith(".pdf"):
        images: list[Image.Image] = []
        extracted_parts: list[str] = []
        with fitz.open(stream=content, filetype="pdf") as doc:
            for index, page in enumerate(doc):
                if index >= settings.max_pages:
                    break
                extracted_parts.append(page.get_text("text") or "")
                pix = page.get_pixmap(dpi=300)
                image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                image = ImageOps.autocontrast(image)
                image = ImageEnhance.Contrast(image.convert("L")).enhance(2.0)
                image = ImageEnhance.Sharpness(image).enhance(2.0)
                image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3)).convert("RGB")
                images.append(image)
        extracted_text = "\n\n".join(part for part in extracted_parts if part)
        return images, extracted_text

    image = Image.open(io.BytesIO(content)).convert("RGB")
    if image.width < 1200:
        scale = 1200 / image.width
        image = image.resize((int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS)
    image = ImageOps.autocontrast(image)
    image = ImageEnhance.Contrast(image.convert("L")).enhance(1.8)
    image = ImageEnhance.Sharpness(image).enhance(2.0)
    image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3)).convert("RGB")
    return [image], ""
