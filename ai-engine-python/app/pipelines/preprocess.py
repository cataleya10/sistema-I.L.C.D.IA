from fastapi import UploadFile
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import io
import logging
import tempfile
import os
import fitz
from typing import Any, cast
from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

_IMAGE_MODULE = cast(Any, Image)
_RESAMPLING = getattr(_IMAGE_MODULE, "Resampling", _IMAGE_MODULE)
_LANCZOS = getattr(_RESAMPLING, "LANCZOS", getattr(_IMAGE_MODULE, "LANCZOS", 1))

# Lazy imports for optional heavy libraries
_pdfplumber = None
_img2table_PDF = None
_img2table_Img = None


def _get_pdfplumber():
    global _pdfplumber
    if _pdfplumber is None:
        try:
            import pdfplumber
            _pdfplumber = pdfplumber
        except ImportError:
            logger.debug("pdfplumber not installed, skipping")
    return _pdfplumber


def _get_img2table_pdf():
    global _img2table_PDF
    if _img2table_PDF is None:
        try:
            from img2table.document import PDF as Img2TablePDF
            _img2table_PDF = Img2TablePDF
        except ImportError:
            logger.debug("img2table not installed, skipping")
    return _img2table_PDF


def _get_img2table_img():
    global _img2table_Img
    if _img2table_Img is None:
        try:
            from img2table.document import Image as Img2TableImage
            _img2table_Img = Img2TableImage
        except ImportError:
            logger.debug("img2table not installed, skipping")
    return _img2table_Img


def _extract_tables_pdfplumber(content: bytes, max_pages: int) -> list[list[list[str]]]:
    """Extract tables from PDF bytes using pdfplumber (Stream + Lattice modes).

    Returns list of tables, each table = list of rows, each row = list of cells.
    Complements PyMuPDF find_tables() by using a different detection algorithm.
    """
    plumber = _get_pdfplumber()
    if plumber is None:
        return []
    tables: list[list[list[str]]] = []
    try:
        pdf = plumber.open(io.BytesIO(content))
        for page_idx, page in enumerate(pdf.pages[:max_pages]):
            try:
                page_tables = page.extract_tables(
                    table_settings={
                        "vertical_strategy": "lines_strict",
                        "horizontal_strategy": "lines_strict",
                    }
                )
                for raw_table in (page_tables or []):
                    if not raw_table or len(raw_table) < 2:
                        continue
                    cleaned = [
                        [str(cell or "").strip() for cell in row]
                        for row in raw_table
                        if isinstance(row, (list, tuple)) and any(str(c or "").strip() for c in row)
                    ]
                    if len(cleaned) >= 2:
                        tables.append(cleaned)
            except Exception:
                logger.debug("pdfplumber table extraction failed on page %d", page_idx + 1)
            # Also try "text" strategy for tables without visible lines
            try:
                page_tables_text = page.extract_tables(
                    table_settings={
                        "vertical_strategy": "text",
                        "horizontal_strategy": "text",
                    }
                )
                for raw_table in (page_tables_text or []):
                    if not raw_table or len(raw_table) < 2:
                        continue
                    cleaned = [
                        [str(cell or "").strip() for cell in row]
                        for row in raw_table
                        if isinstance(row, (list, tuple)) and any(str(c or "").strip() for c in row)
                    ]
                    if len(cleaned) >= 2:
                        tables.append(cleaned)
            except Exception:
                logger.debug("pdfplumber text-mode failed on page %d", page_idx + 1)
        pdf.close()
    except Exception:
        logger.debug("pdfplumber failed to open PDF")
    return tables


def _extract_tables_img2table_pdf(content: bytes, max_pages: int) -> list[list[list[str]]]:
    """Extract tables from PDF bytes using img2table (OpenCV-based structural detection).

    Best for scanned PDFs where text-layer-based extractors fail.
    """
    Img2TablePDF = _get_img2table_pdf()
    if Img2TablePDF is None:
        return []
    tables: list[list[list[str]]] = []
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        doc = Img2TablePDF(src=tmp_path, pages=list(range(max_pages)))
        extracted = doc.extract_tables()
        for page_tables in extracted.values():
            for table in page_tables:
                try:
                    df = table.df
                    if df is None or df.empty or len(df) < 1:
                        continue
                    rows: list[list[str]] = []
                    # Header from DataFrame columns
                    header = [str(c or "").strip() for c in df.columns]
                    rows.append(header)
                    for _, data_row in df.iterrows():
                        row_cells = [str(v or "").strip() for v in data_row]
                        if any(c for c in row_cells):
                            rows.append(row_cells)
                    if len(rows) >= 2:
                        tables.append(rows)
                except Exception:
                    continue
    except Exception:
        logger.debug("img2table PDF extraction failed")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return tables


def _extract_tables_img2table_image(pil_image: Image.Image) -> list[list[list[str]]]:
    """Extract tables from a PIL Image using img2table (OpenCV-based).

    Best for scanned documents where no text layer exists.
    Returns tables with cell text when available (requires OCR in img2table),
    or tables with empty strings when only grid structure is detected.
    """
    Img2TableImage = _get_img2table_img()
    if Img2TableImage is None:
        return []
    tables: list[list[list[str]]] = []
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            pil_image.save(tmp, format="PNG")
            tmp_path = tmp.name
        doc = Img2TableImage(src=tmp_path)
        extracted = doc.extract_tables(borderless_tables=True, implicit_rows=True)
        for table in extracted:
            try:
                df = table.df
                if df is None or df.empty or len(df) < 1:
                    continue
                rows: list[list[str]] = []
                header = [str(c or "").strip() for c in df.columns]
                rows.append(header)
                for _, data_row in df.iterrows():
                    row_cells = [str(v or "").strip() for v in data_row]
                    if any(c for c in row_cells):
                        rows.append(row_cells)
                if len(rows) >= 2:
                    tables.append(rows)
            except Exception:
                continue
    except Exception:
        logger.debug("img2table image extraction failed")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return tables


# ── img2table grid extraction + OCR-box cell filling ──────────────────
_TableCellGrid = list[list[dict]]  # row → col → {"bbox": (x1,y1,x2,y2)}


def _extract_img2table_grid(pil_image: Image.Image) -> list[_TableCellGrid]:
    """Detect table grid structure (cell bounding boxes) from an image.

    Returns a list of grids, each grid = list of rows, each row = list of
    cell dicts with 'bbox' key holding (x1, y1, x2, y2).
    """
    Img2TableImage = _get_img2table_img()
    if Img2TableImage is None:
        return []
    grids: list[_TableCellGrid] = []
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            pil_image.save(tmp, format="PNG")
            tmp_path = tmp.name
        doc = Img2TableImage(src=tmp_path)
        extracted = doc.extract_tables(borderless_tables=True, implicit_rows=True)
        for table in extracted:
            try:
                content = table.content
                if not content:
                    continue
                grid: _TableCellGrid = []
                for row_idx in sorted(content.keys()):
                    row_cells = content[row_idx]
                    row: list[dict] = []
                    for cell in row_cells:
                        bb = cell.bbox
                        row.append({"bbox": (int(bb.x1), int(bb.y1), int(bb.x2), int(bb.y2))})
                    grid.append(row)
                if len(grid) >= 2 and all(len(r) >= 2 for r in grid):
                    grids.append(grid)
            except Exception:
                continue
    except Exception:
        logger.debug("img2table grid extraction failed", exc_info=True)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return grids


def fill_grid_tables_from_ocr_boxes(
    grids: list[_TableCellGrid],
    ocr_boxes: list[dict],
) -> list[list[list[str]]]:
    """Map OCR boxes to img2table cell grids to produce filled table data.

    For each cell in the grid, find all OCR boxes whose center falls inside
    that cell's bounding box.  Concatenate their text to produce the cell
    value.
    """
    if not grids or not ocr_boxes:
        return []

    # Pre-compute OCR box centers and text
    box_data: list[tuple[float, float, str]] = []
    for box in ocr_boxes:
        bbox = box.get("bbox")
        text = str(box.get("text", "")).strip()
        if not text or not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            continue
        # bbox can be polygon [[x1,y1],[x2,y2],...] or flat [x1,y1,x2,y2]
        if isinstance(bbox[0], (list, tuple)):
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
        else:
            xs = [bbox[0], bbox[2]]
            ys = [bbox[1], bbox[3]]
        cx = sum(xs) / len(xs)
        cy = sum(ys) / len(ys)
        box_data.append((cx, cy, text))

    tables: list[list[list[str]]] = []
    for grid in grids:
        rows: list[list[str]] = []
        for row in grid:
            row_cells: list[str] = []
            for cell in row:
                x1, y1, x2, y2 = cell["bbox"]
                # Find OCR boxes whose center falls inside this cell
                parts: list[tuple[float, str]] = []
                for cx, cy, text in box_data:
                    if x1 <= cx <= x2 and y1 <= cy <= y2:
                        parts.append((cx, text))
                # Sort by X to maintain reading order
                parts.sort(key=lambda t: t[0])
                row_cells.append(" ".join(p[1] for p in parts).strip())
            rows.append(row_cells)
        # Only keep tables with at least 2 rows with non-empty content
        non_empty_rows = sum(1 for r in rows if any(c.strip() for c in r))
        if non_empty_rows >= 2:
            tables.append(rows)
    return tables


def _image_to_pdf_bytes(pil_image: Image.Image) -> bytes:
    """Convert a PIL Image to a single-page PDF in memory using PyMuPDF.

    This allows reusing PDF-specific table extractors (PyMuPDF find_tables,
    pdfplumber) on uploaded images, giving images the same multi-source
    table extraction pipeline that PDFs enjoy.
    """
    img_bytes = io.BytesIO()
    pil_image.save(img_bytes, format="PNG")
    img_bytes.seek(0)
    pdf_doc = fitz.open()  # type: ignore[attr-defined]
    try:
        page = pdf_doc.new_page(width=pil_image.width, height=pil_image.height)
        page.insert_image(fitz.Rect(0, 0, pil_image.width, pil_image.height), stream=img_bytes.read())
        pdf_bytes = pdf_doc.tobytes()
    finally:
        pdf_doc.close()
    return pdf_bytes


def _extract_tables_from_image_via_pdf(pil_image: Image.Image) -> list[list[list[str]]]:
    """Extract tables from a PIL Image by converting it to PDF first.

    Applies the same PyMuPDF find_tables() and pdfplumber extraction that
    PDFs receive, so images get the same multi-source table detection.
    """
    tables: list[list[list[str]]] = []
    try:
        pdf_bytes = _image_to_pdf_bytes(pil_image)
    except Exception:
        logger.debug("Image-to-PDF conversion failed, skipping PDF-based table extraction")
        return []

    # 1) PyMuPDF find_tables()
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:  # type: ignore[attr-defined]
            page = doc.load_page(0)
            tab_finder = page.find_tables()
            for table in tab_finder.tables:
                raw_rows = table.extract()
                if raw_rows and len(raw_rows) >= 2:
                    clean_rows = [
                        [str(cell or "").strip() for cell in row]
                        for row in raw_rows
                        if isinstance(row, (list, tuple))
                    ]
                    if len(clean_rows) >= 2:
                        tables.append(clean_rows)
    except Exception:
        logger.debug("PyMuPDF find_tables() failed on image-converted PDF")

    # 2) pdfplumber
    plumber_tables = _extract_tables_pdfplumber(pdf_bytes, max_pages=1)
    if plumber_tables:
        logger.debug("pdfplumber found %d table(s) from image-converted PDF", len(plumber_tables))
        tables.extend(plumber_tables)

    # 3) img2table PDF mode
    img2t_tables = _extract_tables_img2table_pdf(pdf_bytes, max_pages=1)
    if img2t_tables:
        logger.debug("img2table PDF found %d table(s) from image-converted PDF", len(img2t_tables))
        tables.extend(img2t_tables)

    return tables


def _deduplicate_tables(all_tables: list[list[list[str]]]) -> list[list[list[str]]]:
    """Remove duplicate tables that appear from multiple extractors.

    Two tables are considered duplicates if they have identical header
    signatures and overlapping data rows.
    """
    if len(all_tables) <= 1:
        return all_tables

    def _table_sig(table: list[list[str]]) -> str:
        if not table:
            return ""
        header = "|".join(str(c or "").strip().upper() for c in table[0])
        row_count = len(table) - 1
        return f"{header}::{row_count}"

    seen: dict[str, list[list[str]]] = {}
    result: list[list[list[str]]] = []

    for table in all_tables:
        sig = _table_sig(table)
        if sig in seen:
            # Keep the one with more non-empty cells
            existing = seen[sig]
            new_cells = sum(1 for row in table[1:] for c in row if str(c or "").strip())
            old_cells = sum(1 for row in existing[1:] for c in row if str(c or "").strip())
            if new_cells > old_cells:
                # Replace with better table
                result = [t for t in result if _table_sig(t) != sig]
                result.append(table)
                seen[sig] = table
        else:
            seen[sig] = table
            result.append(table)

    return result


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


async def preprocess(file: UploadFile) -> tuple[list[Image.Image], str, list[dict[str, Any]], list[list[list[str]]], list]:
    """Preprocess an uploaded document file.

    Returns (images, extracted_text, text_layer_boxes, pdf_tables, table_cell_grids).
    ``table_cell_grids`` is a list of img2table cell grids (for images) that
    can later be filled with OCR box text via :func:`fill_grid_tables_from_ocr_boxes`.
    """
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError(f"File too large ({len(content)} bytes, max {MAX_UPLOAD_BYTES})")
    filename = str(file.filename or "")
    content_type = str(file.content_type or "")

    if content_type == "application/pdf" or filename.lower().endswith(".pdf"):
        extracted_parts: list[str] = []
        text_layer_boxes: list[dict[str, Any]] = []
        pdf_tables: list[list[list[str]]] = []
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
                # Extract structured tables via PyMuPDF find_tables()
                try:
                    tab_finder = page.find_tables()
                    for table in tab_finder.tables:
                        raw_rows = table.extract()
                        if raw_rows and len(raw_rows) >= 2:
                            clean_rows = [
                                [str(cell or "").strip() for cell in row]
                                for row in raw_rows
                                if isinstance(row, (list, tuple))
                            ]
                            if clean_rows:
                                pdf_tables.append(clean_rows)
                except Exception:
                    logger.debug("find_tables() failed on page %d, skipping", index + 1)

        extracted_text = "\n\n".join(part for part in extracted_parts if part)

        # ── Multi-source table extraction ───────────────────────────
        # 2) pdfplumber: different algorithm, catches tables PyMuPDF misses
        plumber_tables = _extract_tables_pdfplumber(content, max_pages)
        if plumber_tables:
            logger.debug("pdfplumber found %d table(s)", len(plumber_tables))
            pdf_tables.extend(plumber_tables)

        # 3) img2table (PDF mode): OpenCV structural detection for scanned pages
        img2t_tables = _extract_tables_img2table_pdf(content, max_pages)
        if img2t_tables:
            logger.debug("img2table PDF found %d table(s)", len(img2t_tables))
            pdf_tables.extend(img2t_tables)

        # Remove duplicates across extractors
        pdf_tables = _deduplicate_tables(pdf_tables)
        logger.debug("Total unique tables after multi-source merge: %d", len(pdf_tables))
        # ────────────────────────────────────────────────────────────

        if settings.enable_text_layer_short_circuit and _has_sufficient_text_layer(extracted_text):
            return [], extracted_text, text_layer_boxes, pdf_tables, []

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

        return images, extracted_text, text_layer_boxes, pdf_tables, []

    image = Image.open(io.BytesIO(content)).convert("RGB")
    # Upscale small images so img2table and the OCR-box table reconstructor
    # see pixel gaps large enough to distinguish table columns reliably.
    # 2000 px minimum gives enough resolution for compact (Word-doc) tables.
    if image.width < 2000:
        width = max(image.width, 1)
        scale = 2000 / width
        image = image.resize((int(image.width * scale), int(image.height * scale)), _LANCZOS)
    image = ImageOps.autocontrast(image)
    image = ImageEnhance.Contrast(image.convert("L")).enhance(1.8)
    image = ImageEnhance.Sharpness(image).enhance(2.0)
    image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3)).convert("RGB")

    # ── Multi-source table extraction for images ────────────────────
    # Apply the same multi-extractor strategy that PDFs receive so that
    # images with tables get identical extraction quality.
    img_tables: list[list[list[str]]] = []

    # 1) img2table image-mode: OpenCV-based structural detection
    img2t_image_tables = _extract_tables_img2table_image(image)
    if img2t_image_tables:
        logger.debug("img2table image found %d table(s)", len(img2t_image_tables))
        img_tables.extend(img2t_image_tables)

    # 2) Convert image → PDF, then run PyMuPDF + pdfplumber + img2table PDF
    pdf_based_tables = _extract_tables_from_image_via_pdf(image)
    if pdf_based_tables:
        logger.debug("PDF-based extractors found %d table(s) from image", len(pdf_based_tables))
        img_tables.extend(pdf_based_tables)

    # Remove duplicates across extractors (same logic as PDF path)
    img_tables = _deduplicate_tables(img_tables)
    logger.debug("Total unique tables from image after multi-source merge: %d", len(img_tables))

    # 3) Extract img2table grid structure (cell bounding boxes)
    #    This is used later to fill cell text from OCR boxes when img2table
    #    didn't have an OCR engine to read cell contents.
    img_cell_grids = _extract_img2table_grid(image)
    if img_cell_grids:
        logger.debug("img2table detected %d grid(s) with cell bounding boxes", len(img_cell_grids))
    # ────────────────────────────────────────────────────────────────

    return [image], "", [], img_tables, img_cell_grids
