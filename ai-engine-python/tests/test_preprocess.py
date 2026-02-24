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


if __name__ == "__main__":
    unittest.main()
