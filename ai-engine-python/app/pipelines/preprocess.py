from fastapi import UploadFile
from PIL import Image, ImageEnhance
import io
import fitz

async def preprocess(file: UploadFile):
    content = await file.read()

    if file.content_type == "application/pdf" or file.filename.lower().endswith(".pdf"):
        with fitz.open(stream=content, filetype="pdf") as doc:
            page = doc.load_page(0)
            extracted_text = page.get_text("text") or ""
            pix = page.get_pixmap(dpi=300)
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            image = ImageEnhance.Contrast(image.convert("L")).enhance(2.0)
            image = ImageEnhance.Sharpness(image).enhance(2.0).convert("RGB")
            return image, extracted_text

    image = Image.open(io.BytesIO(content)).convert("RGB")
    image = ImageEnhance.Contrast(image.convert("L")).enhance(1.6)
    image = ImageEnhance.Sharpness(image).enhance(1.8).convert("RGB")
    return image, ""
