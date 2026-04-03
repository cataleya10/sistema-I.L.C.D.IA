"""
Tests unitarios para app/pipelines/extract/table_from_ocr.py

Cubre:
  - extract_tables_from_text      (tabla válida, sin tabla, 1 fila)
  - extract_tables_from_ocr_boxes (grid válido, sin encabezado, pocas filas)
  - extract_fallback_tables       (boxes primero, texto como fallback)
"""
import sys
import unittest
from unittest.mock import MagicMock

# Mock pandas antes de que el __init__.py del paquete lo importe
if "pandas" not in sys.modules:
    sys.modules["pandas"] = MagicMock()

from app.pipelines.extract.table_from_ocr import (
    extract_fallback_tables,
    extract_tables_from_ocr_boxes,
    extract_tables_from_text,
)

# ─── Fixtures ─────────────────────────────────────────────────────────────────

_TEXTO_TABLA = (
    "NOMBRE           CUENTA          IMPORTE\n"
    "Juan Garcia      1234567890      5,000.00\n"
    "Maria Lopez      9876543210      3,500.00\n"
    "Pedro Martinez   5555555555      4,200.00\n"
)

_BOXES_TABLA = [
    # Encabezado
    {"text": "NOMBRE",       "bbox": [[10, 10], [120, 10], [120, 25], [10, 25]]},
    {"text": "CUENTA",       "bbox": [[130, 10], [240, 10], [240, 25], [130, 25]]},
    {"text": "IMPORTE",      "bbox": [[250, 10], [360, 10], [360, 25], [250, 25]]},
    # Fila 1
    {"text": "Juan Garcia",  "bbox": [[10, 35], [120, 35], [120, 50], [10, 50]]},
    {"text": "1234567890",   "bbox": [[130, 35], [240, 35], [240, 50], [130, 50]]},
    {"text": "5,000.00",     "bbox": [[250, 35], [360, 35], [360, 50], [250, 50]]},
    # Fila 2
    {"text": "Maria Lopez",  "bbox": [[10, 55], [120, 55], [120, 70], [10, 70]]},
    {"text": "9876543210",   "bbox": [[130, 55], [240, 55], [240, 70], [130, 55]]},
    {"text": "3,500.00",     "bbox": [[250, 55], [360, 55], [360, 70], [250, 55]]},
]


# ─── extract_tables_from_text ─────────────────────────────────────────────────

class TestExtractTablesFromText(unittest.TestCase):

    def test_detects_basic_table(self):
        tables = extract_tables_from_text(_TEXTO_TABLA)
        self.assertEqual(len(tables), 1)

    def test_header_columns_correct(self):
        tables = extract_tables_from_text(_TEXTO_TABLA)
        header = tables[0][0]
        # Debe incluir los 3 encabezados
        header_joined = " ".join(header).upper()
        self.assertIn("NOMBRE", header_joined)
        self.assertIn("CUENTA", header_joined)
        self.assertIn("IMPORTE", header_joined)

    def test_data_rows_count(self):
        tables = extract_tables_from_text(_TEXTO_TABLA)
        # 1 header + 3 filas de datos
        self.assertGreaterEqual(len(tables[0]), 4)

    def test_first_data_row_content(self):
        tables = extract_tables_from_text(_TEXTO_TABLA)
        first_data = tables[0][1]
        self.assertIn("Juan Garcia", first_data)

    def test_no_table_returns_empty(self):
        texto = "Este es un texto de párrafo sin estructura tabular.\nSegunda línea sin patrón."
        tables = extract_tables_from_text(texto)
        self.assertEqual(tables, [])

    def test_only_one_data_row_returns_empty(self):
        texto = "NOMBRE  CUENTA  IMPORTE\nJuan    12345   1000\n"
        tables = extract_tables_from_text(texto, min_data_rows=2)
        self.assertEqual(tables, [])

    def test_empty_text_returns_empty(self):
        self.assertEqual(extract_tables_from_text(""), [])

    def test_dispersión_spei_pattern(self):
        texto = (
            "BENEFICIARIO          CLABE                 IMPORTE   REFERENCIA\n"
            "Juan Perez            002180700000000001    10000.00  REF001\n"
            "Ana Rodriguez         012345678901234567    25000.00  REF002\n"
            "Carlos Mendez         072123456789012345    8500.00   REF003\n"
        )
        tables = extract_tables_from_text(texto)
        self.assertEqual(len(tables), 1)
        self.assertGreaterEqual(len(tables[0]), 4)


# ─── extract_tables_from_ocr_boxes ──────────────────────────────────────────

class TestExtractTablesFromOcrBoxes(unittest.TestCase):

    def test_detects_table_from_boxes(self):
        tables = extract_tables_from_ocr_boxes(_BOXES_TABLA)
        self.assertEqual(len(tables), 1)

    def test_header_row_present(self):
        tables = extract_tables_from_ocr_boxes(_BOXES_TABLA)
        # La primera fila debe contener NOMBRE, CUENTA, IMPORTE
        header_text = " ".join(tables[0][0]).upper()
        self.assertIn("NOMBRE", header_text)
        self.assertIn("CUENTA", header_text)
        self.assertIn("IMPORTE", header_text)

    def test_data_rows_count(self):
        tables = extract_tables_from_ocr_boxes(_BOXES_TABLA)
        self.assertGreaterEqual(len(tables[0]), 3)  # header + 2 filas

    def test_amount_preserved(self):
        tables = extract_tables_from_ocr_boxes(_BOXES_TABLA)
        all_values = " ".join(c for row in tables[0] for c in row)
        self.assertIn("5,000.00", all_values)

    def test_no_header_returns_empty(self):
        boxes = [
            {"text": "12345",    "bbox": [[10, 10], [60, 10], [60, 25], [10, 25]]},
            {"text": "67890",    "bbox": [[70, 10], [120, 10], [120, 25], [70, 25]]},
            {"text": "abc",      "bbox": [[10, 35], [60, 35], [60, 50], [10, 50]]},
            {"text": "def",      "bbox": [[70, 35], [120, 35], [120, 50], [70, 50]]},
        ]
        tables = extract_tables_from_ocr_boxes(boxes)
        self.assertEqual(tables, [])

    def test_only_one_data_row_returns_empty(self):
        boxes = [
            {"text": "NOMBRE",  "bbox": [[10, 10], [120, 10], [120, 25], [10, 25]]},
            {"text": "IMPORTE", "bbox": [[130, 10], [240, 10], [240, 25], [130, 25]]},
            {"text": "Juan",    "bbox": [[10, 35], [120, 35], [120, 50], [10, 50]]},
            {"text": "5000",    "bbox": [[130, 35], [240, 35], [240, 50], [130, 50]]},
        ]
        tables = extract_tables_from_ocr_boxes(boxes, min_data_rows=2)
        self.assertEqual(tables, [])

    def test_empty_boxes_returns_empty(self):
        self.assertEqual(extract_tables_from_ocr_boxes([]), [])

    def test_boxes_with_flat_bbox(self):
        # Formato alternativo: [x1, y1, x2, y2] en lugar de polígono
        boxes = [
            {"text": "NOMBRE",      "bbox": [10, 10, 120, 25]},
            {"text": "CUENTA",      "bbox": [130, 10, 240, 25]},
            {"text": "IMPORTE",     "bbox": [250, 10, 360, 25]},
            {"text": "Juan Garcia", "bbox": [10, 35, 120, 50]},
            {"text": "1234567890",  "bbox": [130, 35, 240, 50]},
            {"text": "5000.00",     "bbox": [250, 35, 360, 50]},
            {"text": "Maria Lopez", "bbox": [10, 55, 120, 70]},
            {"text": "9876543210",  "bbox": [130, 55, 240, 70]},
            {"text": "3500.00",     "bbox": [250, 55, 360, 70]},
        ]
        tables = extract_tables_from_ocr_boxes(boxes)
        self.assertEqual(len(tables), 1)


# ─── extract_fallback_tables ─────────────────────────────────────────────────

class TestExtractFallbackTables(unittest.TestCase):

    def test_boxes_take_priority_over_text(self):
        # Con boxes válidos debe devolver resultado sin llegar al texto
        tables = extract_fallback_tables(_TEXTO_TABLA, _BOXES_TABLA)
        self.assertGreater(len(tables), 0)

    def test_falls_back_to_text_when_no_boxes(self):
        tables = extract_fallback_tables(_TEXTO_TABLA, None)
        self.assertGreater(len(tables), 0)

    def test_falls_back_to_text_when_boxes_empty(self):
        tables = extract_fallback_tables(_TEXTO_TABLA, [])
        self.assertGreater(len(tables), 0)

    def test_returns_empty_when_nothing_works(self):
        tables = extract_fallback_tables("texto sin tabla", [])
        self.assertEqual(tables, [])

    def test_returns_list_of_list_of_list(self):
        tables = extract_fallback_tables(_TEXTO_TABLA, None)
        self.assertIsInstance(tables, list)
        if tables:
            self.assertIsInstance(tables[0], list)
            if tables[0]:
                self.assertIsInstance(tables[0][0], list)

    def test_result_compatible_with_to_canonical_rows(self):
        from app.utils.table_utils import to_canonical_rows
        tables = extract_fallback_tables(_TEXTO_TABLA, None)
        self.assertTrue(len(tables) > 0)
        cols, rows = to_canonical_rows(tables[0])
        self.assertTrue(len(cols) >= 2)
        self.assertTrue(len(rows) >= 2)


if __name__ == "__main__":
    unittest.main()
