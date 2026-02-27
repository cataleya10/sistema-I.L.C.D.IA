"""Tests for multi-source table extraction helpers in preprocess.py."""

import unittest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# _deduplicate_tables (pure logic, no mocks needed)
# ---------------------------------------------------------------------------
class TestDeduplicateTables(unittest.TestCase):
    """Tests for the table deduplication utility."""

    def _dedup(self, tables):
        from app.pipelines.preprocess import _deduplicate_tables
        return _deduplicate_tables(tables)

    def test_empty_list(self):
        self.assertEqual(self._dedup([]), [])

    def test_single_table_unchanged(self):
        t = [["H1", "H2"], ["a", "b"]]
        result = self._dedup([t])
        self.assertEqual(result, [t])

    def test_identical_tables_deduped(self):
        t1 = [["CUENTA", "IMPORTE"], ["123", "$100.00"]]
        t2 = [["CUENTA", "IMPORTE"], ["123", "$100.00"]]
        result = self._dedup([t1, t2])
        self.assertEqual(len(result), 1)

    def test_same_header_keeps_richer_table(self):
        t_sparse = [["CUENTA", "IMPORTE"], ["", "$100.00"]]
        t_full = [["CUENTA", "IMPORTE"], ["123", "$100.00"]]
        result = self._dedup([t_sparse, t_full])
        self.assertEqual(len(result), 1)
        # The richer table should be kept
        self.assertEqual(result[0], t_full)

    def test_different_headers_both_kept(self):
        t1 = [["CUENTA", "IMPORTE"], ["123", "$100.00"]]
        t2 = [["NOMBRE", "RFC"], ["Ana", "ABC123"]]
        result = self._dedup([t1, t2])
        self.assertEqual(len(result), 2)

    def test_case_insensitive_header_match(self):
        t1 = [["cuenta", "importe"], ["123", "$100.00"]]
        t2 = [["CUENTA", "IMPORTE"], ["123", "$100.00"]]
        result = self._dedup([t1, t2])
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# _extract_tables_pdfplumber (mocked pdfplumber)
# ---------------------------------------------------------------------------
class TestExtractTablesPdfplumber(unittest.TestCase):
    """Tests for the pdfplumber extraction helper."""

    def test_returns_empty_when_pdfplumber_missing(self):
        """When pdfplumber is not installed, returns empty list."""
        import app.pipelines.preprocess as mod
        original = mod._pdfplumber
        try:
            mod._pdfplumber = None
            with patch.object(mod, "_get_pdfplumber", return_value=None):
                result = mod._extract_tables_pdfplumber(b"fake-pdf", 5)
            self.assertEqual(result, [])
        finally:
            mod._pdfplumber = original

    def test_extracts_tables_from_mock_pdf(self):
        """Verify tables are returned from a mocked pdfplumber page."""
        import app.pipelines.preprocess as mod

        mock_page = MagicMock()
        # lines_strict returns one table
        mock_page.extract_tables.side_effect = [
            # First call (lines_strict): one good table
            [[["CUENTA", "IMPORTE"], ["123", "$500.00"], ["456", "$300.00"]]],
            # Second call (text): empty
            [],
        ]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_plumber = MagicMock()
        mock_plumber.open.return_value = mock_pdf

        with patch.object(mod, "_get_pdfplumber", return_value=mock_plumber):
            result = mod._extract_tables_pdfplumber(b"fake-pdf", 5)

        self.assertGreaterEqual(len(result), 1)
        self.assertEqual(result[0][0], ["CUENTA", "IMPORTE"])
        self.assertEqual(result[0][1], ["123", "$500.00"])

    def test_skips_single_row_tables(self):
        """Tables with fewer than 2 rows are filtered out."""
        import app.pipelines.preprocess as mod

        mock_page = MagicMock()
        mock_page.extract_tables.side_effect = [
            [[["HEADER_ONLY"]]],  # lines_strict: 1-row table
            [],  # text: empty
        ]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]

        mock_plumber = MagicMock()
        mock_plumber.open.return_value = mock_pdf

        with patch.object(mod, "_get_pdfplumber", return_value=mock_plumber):
            result = mod._extract_tables_pdfplumber(b"fake-pdf", 5)

        self.assertEqual(result, [])

    def test_handles_none_cells(self):
        """None cells are converted to empty strings."""
        import app.pipelines.preprocess as mod

        mock_page = MagicMock()
        mock_page.extract_tables.side_effect = [
            [[[None, "IMPORTE"], ["123", None]]],
            [],
        ]

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]

        mock_plumber = MagicMock()
        mock_plumber.open.return_value = mock_pdf

        with patch.object(mod, "_get_pdfplumber", return_value=mock_plumber):
            result = mod._extract_tables_pdfplumber(b"fake-pdf", 5)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0][0], "")
        self.assertEqual(result[0][1][1], "")

    def test_respects_max_pages(self):
        """Only processes pages up to max_pages."""
        import app.pipelines.preprocess as mod

        page1 = MagicMock()
        page1.extract_tables.side_effect = [
            [[["H1", "H2"], ["a", "b"]]],
            [],
        ]
        page2 = MagicMock()
        page2.extract_tables.side_effect = [
            [[["H3", "H4"], ["c", "d"]]],
            [],
        ]

        mock_pdf = MagicMock()
        mock_pdf.pages = [page1, page2]

        mock_plumber = MagicMock()
        mock_plumber.open.return_value = mock_pdf

        with patch.object(mod, "_get_pdfplumber", return_value=mock_plumber):
            result = mod._extract_tables_pdfplumber(b"fake-pdf", max_pages=1)

        # Only tables from page1 should appear
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], ["H1", "H2"])


# ---------------------------------------------------------------------------
# _extract_tables_img2table_pdf (mocked img2table)
# ---------------------------------------------------------------------------
class TestExtractTablesImg2tablePdf(unittest.TestCase):
    """Tests for the img2table PDF extraction helper."""

    def test_returns_empty_when_img2table_missing(self):
        import app.pipelines.preprocess as mod
        original = mod._img2table_PDF
        try:
            mod._img2table_PDF = None
            with patch.object(mod, "_get_img2table_pdf", return_value=None):
                result = mod._extract_tables_img2table_pdf(b"fake-pdf", 5)
            self.assertEqual(result, [])
        finally:
            mod._img2table_PDF = original

    def test_extracts_tables_from_mock_pdf(self):
        """Verify conversion from img2table DataFrame output to list format."""
        import app.pipelines.preprocess as mod
        import pandas as pd

        mock_df = pd.DataFrame({"CUENTA": ["123"], "IMPORTE": ["$500"]})
        mock_table = MagicMock()
        mock_table.df = mock_df

        mock_doc = MagicMock()
        mock_doc.extract_tables.return_value = {0: [mock_table]}

        MockPDF = MagicMock(return_value=mock_doc)

        # Let real tempfile work for writing bytes, only mock img2table class
        with patch.object(mod, "_get_img2table_pdf", return_value=MockPDF):
            result = mod._extract_tables_img2table_pdf(b"fake-pdf", 5)

        self.assertGreaterEqual(len(result), 1)
        # Header row
        self.assertIn("CUENTA", result[0][0])
        self.assertIn("IMPORTE", result[0][0])
        # Data row
        self.assertEqual(result[0][1], ["123", "$500"])


# ---------------------------------------------------------------------------
# _extract_tables_img2table_image (mocked img2table)
# ---------------------------------------------------------------------------
class TestExtractTablesImg2tableImage(unittest.TestCase):
    """Tests for the img2table Image extraction helper."""

    def test_returns_empty_when_img2table_missing(self):
        from PIL import Image
        import app.pipelines.preprocess as mod
        original = mod._img2table_Img
        try:
            mod._img2table_Img = None
            with patch.object(mod, "_get_img2table_img", return_value=None):
                dummy = Image.new("RGB", (100, 100))
                result = mod._extract_tables_img2table_image(dummy)
            self.assertEqual(result, [])
        finally:
            mod._img2table_Img = original

    def test_extracts_tables_from_mock_image(self):
        """Verify conversion from img2table DataFrame output to list format."""
        from PIL import Image
        import app.pipelines.preprocess as mod
        import pandas as pd
        import tempfile as real_tempfile

        mock_df = pd.DataFrame({"NOMBRE": ["Ana"], "RFC": ["ABC123"]})
        mock_table = MagicMock()
        mock_table.df = mock_df

        mock_doc = MagicMock()
        mock_doc.extract_tables.return_value = [mock_table]

        MockImage = MagicMock(return_value=mock_doc)

        # Use a real temp file so pil_image.save() works, but mock img2table
        with patch.object(mod, "_get_img2table_img", return_value=MockImage):
            dummy = Image.new("RGB", (100, 100))
            result = mod._extract_tables_img2table_image(dummy)

        self.assertGreaterEqual(len(result), 1)
        self.assertIn("NOMBRE", result[0][0])
        self.assertIn("RFC", result[0][0])


# ---------------------------------------------------------------------------
# Lazy import resilience
# ---------------------------------------------------------------------------
class TestLazyImports(unittest.TestCase):
    """Test that lazy import functions handle missing packages gracefully."""

    def test_pdfplumber_import_failure(self):
        import app.pipelines.preprocess as mod
        original = mod._pdfplumber
        try:
            mod._pdfplumber = None
            with patch("builtins.__import__", side_effect=ImportError("No module")):
                result = mod._get_pdfplumber()
            self.assertIsNone(result)
        finally:
            mod._pdfplumber = original

    def test_img2table_pdf_import_failure(self):
        import app.pipelines.preprocess as mod
        original = mod._img2table_PDF
        try:
            mod._img2table_PDF = None
            with patch("builtins.__import__", side_effect=ImportError("No module")):
                result = mod._get_img2table_pdf()
            self.assertIsNone(result)
        finally:
            mod._img2table_PDF = original

    def test_img2table_img_import_failure(self):
        import app.pipelines.preprocess as mod
        original = mod._img2table_Img
        try:
            mod._img2table_Img = None
            with patch("builtins.__import__", side_effect=ImportError("No module")):
                result = mod._get_img2table_img()
            self.assertIsNone(result)
        finally:
            mod._img2table_Img = original


# ---------------------------------------------------------------------------
# Integration: multi-source table merge in preprocess
# ---------------------------------------------------------------------------
class TestMultiSourceMerge(unittest.TestCase):
    """Tests verifying the multi-source merge produces deduplicated tables."""

    def test_pymupdf_plus_pdfplumber_deduped(self):
        """When both extractors return the same table, only one copy survives."""
        from app.pipelines.preprocess import _deduplicate_tables

        pymupdf_table = [["CUENTA", "IMPORTE"], ["111", "$100.00"]]
        plumber_table = [["CUENTA", "IMPORTE"], ["111", "$100.00"]]

        all_tables = [pymupdf_table, plumber_table]
        result = _deduplicate_tables(all_tables)
        self.assertEqual(len(result), 1)

    def test_complementary_tables_both_kept(self):
        """When extractors find different tables, all are kept."""
        from app.pipelines.preprocess import _deduplicate_tables

        pymupdf_table = [["CUENTA", "IMPORTE"], ["111", "$100.00"]]
        plumber_table = [["NOMBRE", "RFC"], ["Ana", "ABC123"]]
        img2t_table = [["FECHA", "CONCEPTO"], ["2024-01-01", "Pago"]]

        result = _deduplicate_tables([pymupdf_table, plumber_table, img2t_table])
        self.assertEqual(len(result), 3)

    def test_three_sources_same_table_one_survives(self):
        """Three extractors returning the same table → single result."""
        from app.pipelines.preprocess import _deduplicate_tables

        t1 = [["A", "B"], ["1", "2"]]
        t2 = [["A", "B"], ["1", "2"]]
        t3 = [["A", "B"], ["1", "2"]]
        result = _deduplicate_tables([t1, t2, t3])
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# _image_to_pdf_bytes (image → PDF conversion)
# ---------------------------------------------------------------------------
class TestImageToPdfBytes(unittest.TestCase):
    """Tests for the image-to-PDF conversion utility."""

    def test_produces_valid_pdf_bytes(self):
        """Converted bytes should be a valid PDF openable by PyMuPDF."""
        from PIL import Image
        import fitz
        from app.pipelines.preprocess import _image_to_pdf_bytes

        img = Image.new("RGB", (200, 100), color=(255, 0, 0))
        pdf_bytes = _image_to_pdf_bytes(img)

        self.assertTrue(len(pdf_bytes) > 0)
        # Should start with PDF magic bytes
        self.assertTrue(pdf_bytes[:5] == b"%PDF-")

        # Should be openable as a single-page PDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        self.assertEqual(len(doc), 1)
        page = doc.load_page(0)
        self.assertAlmostEqual(page.rect.width, 200, delta=1)
        self.assertAlmostEqual(page.rect.height, 100, delta=1)
        doc.close()

    def test_preserves_image_dimensions(self):
        """PDF page dimensions should match the source image."""
        from PIL import Image
        import fitz
        from app.pipelines.preprocess import _image_to_pdf_bytes

        img = Image.new("RGB", (800, 600))
        pdf_bytes = _image_to_pdf_bytes(img)
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page = doc.load_page(0)
        self.assertAlmostEqual(page.rect.width, 800, delta=1)
        self.assertAlmostEqual(page.rect.height, 600, delta=1)
        doc.close()


# ---------------------------------------------------------------------------
# _extract_tables_from_image_via_pdf (multi-source for images)
# ---------------------------------------------------------------------------
class TestExtractTablesFromImageViaPdf(unittest.TestCase):
    """Tests for the image-via-PDF multi-source table extraction."""

    def test_returns_empty_on_plain_image(self):
        """A blank image should produce no tables."""
        from PIL import Image
        from app.pipelines.preprocess import _extract_tables_from_image_via_pdf

        blank = Image.new("RGB", (200, 100), color=(255, 255, 255))
        result = _extract_tables_from_image_via_pdf(blank)
        # Blank image has no tables — should be empty list
        self.assertIsInstance(result, list)

    def test_gracefully_handles_conversion_failure(self):
        """If image-to-PDF conversion fails, returns empty list."""
        from PIL import Image
        import app.pipelines.preprocess as mod

        with patch.object(mod, "_image_to_pdf_bytes", side_effect=Exception("conversion failed")):
            blank = Image.new("RGB", (100, 100))
            result = mod._extract_tables_from_image_via_pdf(blank)
        self.assertEqual(result, [])

    def test_merges_results_from_multiple_extractors(self):
        """When PyMuPDF and pdfplumber both return tables, all are included."""
        from PIL import Image
        import app.pipelines.preprocess as mod

        fake_pdf_bytes = b"%PDF-fake"

        plumber_table = [["NOMBRE", "RFC"], ["Ana", "ABC123"]]

        with patch.object(mod, "_image_to_pdf_bytes", return_value=fake_pdf_bytes):
            # Mock fitz.open for PyMuPDF find_tables — return empty
            with patch("fitz.open") as mock_fitz_open:
                mock_doc = MagicMock()
                mock_page = MagicMock()
                mock_page.find_tables.return_value = MagicMock(tables=[])
                mock_doc.load_page.return_value = mock_page
                mock_doc.__enter__ = MagicMock(return_value=mock_doc)
                mock_doc.__exit__ = MagicMock(return_value=False)
                mock_fitz_open.return_value = mock_doc

                with patch.object(mod, "_extract_tables_pdfplumber", return_value=[plumber_table]):
                    with patch.object(mod, "_extract_tables_img2table_pdf", return_value=[]):
                        blank = Image.new("RGB", (100, 100))
                        result = mod._extract_tables_from_image_via_pdf(blank)

        self.assertGreaterEqual(len(result), 1)
        self.assertEqual(result[0], plumber_table)

    def test_pymupdf_tables_captured(self):
        """PyMuPDF find_tables results should appear in the output."""
        from PIL import Image
        import app.pipelines.preprocess as mod

        fake_pdf_bytes = b"%PDF-fake"
        pymupdf_raw = [["CUENTA", "IMPORTE"], ["123", "$500"]]

        mock_table = MagicMock()
        mock_table.extract.return_value = pymupdf_raw

        with patch.object(mod, "_image_to_pdf_bytes", return_value=fake_pdf_bytes):
            with patch("fitz.open") as mock_fitz_open:
                mock_doc = MagicMock()
                mock_page = MagicMock()
                mock_page.find_tables.return_value = MagicMock(tables=[mock_table])
                mock_doc.load_page.return_value = mock_page
                mock_doc.__enter__ = MagicMock(return_value=mock_doc)
                mock_doc.__exit__ = MagicMock(return_value=False)
                mock_fitz_open.return_value = mock_doc

                with patch.object(mod, "_extract_tables_pdfplumber", return_value=[]):
                    with patch.object(mod, "_extract_tables_img2table_pdf", return_value=[]):
                        blank = Image.new("RGB", (100, 100))
                        result = mod._extract_tables_from_image_via_pdf(blank)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], ["CUENTA", "IMPORTE"])
        self.assertEqual(result[0][1], ["123", "$500"])


# ---------------------------------------------------------------------------
# Integration: image multi-source table extraction in preprocess
# ---------------------------------------------------------------------------
class TestImageMultiSourceMerge(unittest.TestCase):
    """Tests verifying that image path uses the same multi-source strategy as PDFs."""

    def test_image_tables_from_all_sources_merged_and_deduped(self):
        """Both img2table image and PDF-based extractors contribute tables."""
        from app.pipelines.preprocess import _deduplicate_tables

        # Simulate img2table image finding one table
        img2t_table = [["CUENTA", "IMPORTE"], ["111", "$100.00"]]
        # Simulate PDF-based extractor finding a different table
        pdf_based_table = [["NOMBRE", "RFC"], ["Ana", "ABC123"]]
        # And a duplicate of the img2table result
        duplicate_table = [["CUENTA", "IMPORTE"], ["111", "$100.00"]]

        all_tables = [img2t_table, pdf_based_table, duplicate_table]
        result = _deduplicate_tables(all_tables)
        # Should keep 2 unique tables (img2t + pdf_based), dedupe the duplicate
        self.assertEqual(len(result), 2)

    def test_empty_image_extractors_return_empty(self):
        """When no extractors find tables, result is empty."""
        from app.pipelines.preprocess import _deduplicate_tables

        result = _deduplicate_tables([])
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# fill_grid_tables_from_ocr_boxes
# ---------------------------------------------------------------------------
class TestFillGridTablesFromOcrBoxes(unittest.TestCase):
    """Tests for mapping OCR boxes to img2table cell grids."""

    def _make_box(self, x1, y1, x2, y2, text, conf=0.9):
        return {
            "text": text,
            "confidence": conf,
            "bbox": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
        }

    def test_basic_cell_filling(self):
        from app.pipelines.preprocess import fill_grid_tables_from_ocr_boxes

        # 2x2 grid
        grids = [[
            [{"bbox": (0, 0, 100, 50)}, {"bbox": (100, 0, 200, 50)}],
            [{"bbox": (0, 50, 100, 100)}, {"bbox": (100, 50, 200, 100)}],
        ]]
        # OCR boxes centered in each cell
        ocr_boxes = [
            self._make_box(20, 10, 80, 40, "Header A"),  # cell (0,0)
            self._make_box(120, 10, 180, 40, "Header B"),  # cell (0,1)
            self._make_box(20, 60, 80, 90, "Value 1"),  # cell (1,0)
            self._make_box(120, 60, 180, 90, "Value 2"),  # cell (1,1)
        ]
        result = fill_grid_tables_from_ocr_boxes(grids, ocr_boxes)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], ["Header A", "Header B"])
        self.assertEqual(result[0][1], ["Value 1", "Value 2"])

    def test_empty_grids_return_empty(self):
        from app.pipelines.preprocess import fill_grid_tables_from_ocr_boxes

        result = fill_grid_tables_from_ocr_boxes([], [self._make_box(0, 0, 100, 50, "text")])
        self.assertEqual(result, [])

    def test_empty_ocr_boxes_return_empty(self):
        from app.pipelines.preprocess import fill_grid_tables_from_ocr_boxes

        grids = [[
            [{"bbox": (0, 0, 100, 50)}, {"bbox": (100, 0, 200, 50)}],
            [{"bbox": (0, 50, 100, 100)}, {"bbox": (100, 50, 200, 100)}],
        ]]
        result = fill_grid_tables_from_ocr_boxes(grids, [])
        self.assertEqual(result, [])

    def test_multiple_boxes_in_one_cell(self):
        from app.pipelines.preprocess import fill_grid_tables_from_ocr_boxes

        grids = [[
            [{"bbox": (0, 0, 200, 50)}],
            [{"bbox": (0, 50, 200, 100)}],
        ]]
        ocr_boxes = [
            self._make_box(10, 10, 50, 40, "Hello"),
            self._make_box(60, 10, 120, 40, "World"),
            self._make_box(10, 60, 80, 90, "Test"),
        ]
        result = fill_grid_tables_from_ocr_boxes(grids, ocr_boxes)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], ["Hello World"])
        self.assertEqual(result[0][1], ["Test"])

    def test_box_outside_grid_ignored(self):
        from app.pipelines.preprocess import fill_grid_tables_from_ocr_boxes

        grids = [[
            [{"bbox": (0, 0, 100, 50)}, {"bbox": (100, 0, 200, 50)}],
            [{"bbox": (0, 50, 100, 100)}, {"bbox": (100, 50, 200, 100)}],
        ]]
        ocr_boxes = [
            self._make_box(50, 25, 80, 35, "Inside"),  # Inside cell (0,0)
            self._make_box(300, 300, 400, 400, "Outside"),  # Outside any cell
        ]
        result = fill_grid_tables_from_ocr_boxes(grids, ocr_boxes)
        self.assertEqual(len(result), 0)  # Only 1 non-empty row, need 2


# ---------------------------------------------------------------------------
# _extract_img2table_grid
# ---------------------------------------------------------------------------
class TestExtractImg2tableGrid(unittest.TestCase):
    """Tests for img2table grid extraction."""

    def test_returns_empty_when_img2table_missing(self):
        from app.pipelines.preprocess import _extract_img2table_grid
        from PIL import Image

        img = Image.new("RGB", (100, 100), "white")
        with patch("app.pipelines.preprocess._get_img2table_img", return_value=None):
            result = _extract_img2table_grid(img)
        self.assertEqual(result, [])

    def test_extracts_grid_from_mock_table(self):
        from app.pipelines.preprocess import _extract_img2table_grid
        from PIL import Image

        img = Image.new("RGB", (400, 200), "white")

        # Mock img2table response with cell bounding boxes
        mock_bbox = MagicMock()
        mock_bbox.x1 = 10
        mock_bbox.y1 = 10
        mock_bbox.x2 = 100
        mock_bbox.y2 = 50

        mock_bbox2 = MagicMock()
        mock_bbox2.x1 = 100
        mock_bbox2.y1 = 10
        mock_bbox2.x2 = 200
        mock_bbox2.y2 = 50

        mock_bbox3 = MagicMock()
        mock_bbox3.x1 = 10
        mock_bbox3.y1 = 50
        mock_bbox3.x2 = 100
        mock_bbox3.y2 = 90

        mock_bbox4 = MagicMock()
        mock_bbox4.x1 = 100
        mock_bbox4.y1 = 50
        mock_bbox4.x2 = 200
        mock_bbox4.y2 = 90

        mock_cell1 = MagicMock()
        mock_cell1.bbox = mock_bbox
        mock_cell2 = MagicMock()
        mock_cell2.bbox = mock_bbox2
        mock_cell3 = MagicMock()
        mock_cell3.bbox = mock_bbox3
        mock_cell4 = MagicMock()
        mock_cell4.bbox = mock_bbox4

        mock_table = MagicMock()
        mock_table.content = {0: [mock_cell1, mock_cell2], 1: [mock_cell3, mock_cell4]}

        mock_doc = MagicMock()
        mock_doc.extract_tables.return_value = [mock_table]

        mock_img2table_cls = MagicMock(return_value=mock_doc)

        with patch("app.pipelines.preprocess._get_img2table_img", return_value=mock_img2table_cls):
            result = _extract_img2table_grid(img)

        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]), 2)  # 2 rows
        self.assertEqual(len(result[0][0]), 2)  # 2 cols per row
        self.assertEqual(result[0][0][0]["bbox"], (10, 10, 100, 50))
        self.assertEqual(result[0][1][1]["bbox"], (100, 50, 200, 90))


if __name__ == "__main__":
    unittest.main()
