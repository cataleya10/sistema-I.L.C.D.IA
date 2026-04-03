"""
Tests unitarios para app/utils/table_utils.py

Cubre:
  - canonicalize_column_name  (exacto, parcial, fuzzy, fallback)
  - normalize_amount           (formatos MX, OCR, negativos)
  - detect_header_row          (score correcto, sin encabezado)
  - merge_multirow_headers     (fusiona / no fusiona)
  - reconstruct_fragmented_rows
  - deduplicate_rows
  - to_canonical_rows          (pipeline completo)
  - table_quality_score        (dict con clave 'quality')
"""
import unittest

from app.utils.table_utils import (
    canonicalize_column_name,
    normalize_amount,
    detect_header_row,
    merge_multirow_headers,
    reconstruct_fragmented_rows,
    deduplicate_rows,
    to_canonical_rows,
    table_quality_score,
    unify_columns,
)


# ─── canonicalize_column_name ─────────────────────────────────────────────────

class TestCanonicalizeColumnName(unittest.TestCase):

    def test_exact_alias_clabe(self):
        self.assertEqual(canonicalize_column_name("CUENTA CLABE"), "clabe")

    def test_exact_alias_importe(self):
        self.assertEqual(canonicalize_column_name("IMPORTE"), "importe")

    def test_case_insensitive(self):
        self.assertEqual(canonicalize_column_name("importe"), "importe")
        self.assertEqual(canonicalize_column_name("Nombre Beneficiario"), "nombre_beneficiario")

    def test_partial_match(self):
        # "CUENTA CLABE" como substring inequívoco → "clabe"
        self.assertEqual(canonicalize_column_name("MI CUENTA CLABE BANCARIA"), "clabe")

    def test_numero_prefix_normalization(self):
        self.assertEqual(canonicalize_column_name("N° Empleado"), "numero_empleado")
        self.assertEqual(canonicalize_column_name("NUM EMPLEADO"), "numero_empleado")

    def test_cargo_abono_distinction(self):
        self.assertEqual(canonicalize_column_name("CARGO"), "cargo")
        self.assertEqual(canonicalize_column_name("ABONO"), "abono")
        self.assertEqual(canonicalize_column_name("DEBITO"), "cargo")
        self.assertEqual(canonicalize_column_name("CREDITO"), "abono")

    def test_nomina_columns(self):
        self.assertEqual(canonicalize_column_name("PERCEPCIONES"), "percepcion")
        self.assertEqual(canonicalize_column_name("DEDUCCIONES"), "deduccion")

    def test_fuzzy_abbreviated_header(self):
        # "VALOR UNITARIO" es alias exacto → debe mapearse correctamente
        self.assertEqual(canonicalize_column_name("VALOR UNITARIO"), "valor_unitario")
        # Fuzzy: "VLOR UNITRIO" (OCR corrupto) debería encontrar "VALOR UNITARIO"
        result = canonicalize_column_name("VLOR UNITRIO")
        self.assertEqual(result, "valor_unitario")

    def test_fallback_snake_case(self):
        result = canonicalize_column_name("MI COLUMNA RARA")
        self.assertEqual(result, "mi_columna_rara")

    def test_empty_string(self):
        result = canonicalize_column_name("")
        self.assertEqual(result, "")


# ─── normalize_amount ─────────────────────────────────────────────────────────

class TestNormalizeAmount(unittest.TestCase):

    def test_standard_with_dollar(self):
        self.assertEqual(normalize_amount("$1,234.56"), "1,234.56")

    def test_no_dollar_sign(self):
        self.assertEqual(normalize_amount("1234.56"), "1,234.56")

    def test_comma_as_decimal(self):
        self.assertEqual(normalize_amount("$1.234,56"), "1,234.56")

    def test_whole_number(self):
        self.assertEqual(normalize_amount("5000"), "5,000.00")

    def test_ocr_letter_o_in_number(self):
        result = normalize_amount("$5,OOO.OO")
        self.assertIn("5,000", result)

    def test_mxn_suffix_stripped(self):
        result = normalize_amount("3,500.00 MXN")
        self.assertEqual(result, "3,500.00")

    def test_negative_parentheses(self):
        # Importes negativos en estados de cuenta a veces van entre paréntesis
        result = normalize_amount("(1,500.00)")
        self.assertNotEqual(result, "")  # Algo extrae, no colapsa a vacío

    def test_empty_returns_empty(self):
        self.assertEqual(normalize_amount(""), "")
        self.assertEqual(normalize_amount(None), "")


# ─── detect_header_row ───────────────────────────────────────────────────────

class TestDetectHeaderRow(unittest.TestCase):

    def test_header_in_first_row(self):
        rows = [
            ["NOMBRE", "CUENTA", "IMPORTE"],
            ["Juan Garcia", "1234567890", "5000.00"],
        ]
        self.assertEqual(detect_header_row(rows), 0)

    def test_header_in_second_row(self):
        rows = [
            ["Logo empresa", "RFC: ABC123456ABC"],
            ["NOMBRE", "CLABE", "MONTO", "REFERENCIA"],
            ["Maria Lopez", "002180012345678901", "3500.00", "REF001"],
        ]
        self.assertEqual(detect_header_row(rows), 1)

    def test_no_header_returns_minus_one(self):
        rows = [
            ["12/01/2024", "Compra tienda", "150.00"],
            ["13/01/2024", "Deposito", "2000.00"],
        ]
        self.assertEqual(detect_header_row(rows), -1)

    def test_empty_table(self):
        self.assertEqual(detect_header_row([]), -1)


# ─── merge_multirow_headers ──────────────────────────────────────────────────

class TestMergeMultirowHeaders(unittest.TestCase):

    def test_merges_when_prev_has_header_tokens(self):
        rows = [
            ["", "IMPORTE", ""],          # fila 0 — tokens de encabezado
            ["NOMBRE", "BRUTO", "NETO"],  # fila 1 — encabezado detectado
            ["Juan", "3000", "2500"],
        ]
        result = merge_multirow_headers(rows, header_index=1)
        # Debe haber una fila menos (la fila 0 se absorbió)
        self.assertEqual(len(result), 2)
        merged_header = result[0]
        self.assertIn("IMPORTE", " ".join(merged_header).upper())
        self.assertIn("BRUTO", " ".join(merged_header).upper())

    def test_no_merge_when_prev_has_no_tokens(self):
        # Fila 0 sin tokens de encabezado conocidos → no debe fusionar
        rows = [
            ["Enero 2024", "Del 1 al 15"],    # score=0: ningún token conocido
            ["NOMBRE", "CUENTA", "IMPORTE"],
            ["Juan", "123456", "5000"],
        ]
        original_len = len(rows)
        result = merge_multirow_headers(rows, header_index=1)
        self.assertEqual(len(result), original_len)

    def test_header_index_zero_no_merge(self):
        rows = [["NOMBRE", "CUENTA"], ["Juan", "123"]]
        result = merge_multirow_headers(rows, header_index=0)
        self.assertEqual(len(result), 2)


# ─── reconstruct_fragmented_rows ─────────────────────────────────────────────

class TestReconstructFragmentedRows(unittest.TestCase):

    def test_merges_partial_row_into_previous(self):
        # Fila anterior tiene huecos, fila fragmento rellena exactamente esos huecos
        cols = ["nombre", "cuenta", "importe", "banco", "referencia", "estatus"]
        rows = [
            {c: v for c, v in zip(cols, ["Juan Garcia", "123456", "",     "",     "",      ""])},  # 2/6 completa
            {c: v for c, v in zip(cols, ["",            "",       "5000", "",     "",      ""])},  # 1/6 → fragmento
            {c: v for c, v in zip(cols, ["Maria Lopez", "987654", "3500", "HSBC", "REF02", "OK"])},
        ]
        result = reconstruct_fragmented_rows(rows)
        # Fila 2 (fragmento con importe) debe fusionarse en fila 1 → 2 filas totales
        self.assertLess(len(result), 3)

    def test_fragment_fills_empty_slots(self):
        # Fila completa primero, fragmento segundo — el fragmento rellena el hueco
        cols = ["nombre", "cuenta", "importe", "banco", "referencia", "estatus"]
        rows = [
            {c: v for c, v in zip(cols, ["",            "123456", "5000", "BBVA", "REF01", "OK"])},  # 5/6 completa
            {c: v for c, v in zip(cols, ["Juan Garcia", "",       "",     "",     "",      ""])},     # 1/6 → fragmento
        ]
        result = reconstruct_fragmented_rows(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["nombre"], "Juan Garcia")
        self.assertEqual(result[0]["cuenta"], "123456")

    def test_complete_rows_unchanged(self):
        rows = [
            {"nombre": "Juan",  "cuenta": "111111", "importe": "1000"},
            {"nombre": "Maria", "cuenta": "222222", "importe": "2000"},
        ]
        result = reconstruct_fragmented_rows(rows)
        self.assertEqual(len(result), 2)


# ─── deduplicate_rows ─────────────────────────────────────────────────────────

class TestDeduplicateRows(unittest.TestCase):

    def test_removes_exact_duplicate(self):
        rows = [
            {"nombre": "Juan", "importe": "5000"},
            {"nombre": "Maria", "importe": "3000"},
            {"nombre": "Juan", "importe": "5000"},  # duplicado
        ]
        result = deduplicate_rows(rows)
        self.assertEqual(len(result), 2)

    def test_keeps_different_rows(self):
        rows = [
            {"nombre": "Juan",  "importe": "5000"},
            {"nombre": "Juan",  "importe": "6000"},  # mismo nombre, diferente importe
        ]
        result = deduplicate_rows(rows)
        self.assertEqual(len(result), 2)

    def test_empty_list(self):
        self.assertEqual(deduplicate_rows([]), [])

    def test_preserves_first_occurrence(self):
        rows = [
            {"nombre": "Juan", "importe": "5000"},
            {"nombre": "Juan", "importe": "5000"},
        ]
        result = deduplicate_rows(rows)
        self.assertEqual(result[0]["nombre"], "Juan")


# ─── to_canonical_rows ───────────────────────────────────────────────────────

class TestToCanonicalRows(unittest.TestCase):

    def test_basic_pipeline(self):
        raw = [
            ["NOMBRE", "CUENTA", "IMPORTE"],
            ["Juan Garcia", "1234567890", "$5,000.00"],
            ["Maria Lopez", "9876543210", "$3,500.00"],
        ]
        cols, rows = to_canonical_rows(raw)
        self.assertEqual(cols, ["nombre", "cuenta", "importe"])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["nombre"], "Juan Garcia")
        self.assertIn("5,000", rows[0]["importe"])

    def test_drops_empty_rows(self):
        raw = [
            ["NOMBRE", "IMPORTE"],
            ["Juan", "5000"],
            ["", ""],
            ["Maria", "3000"],
        ]
        cols, rows = to_canonical_rows(raw)
        self.assertEqual(len(rows), 2)

    def test_drops_summary_row(self):
        raw = [
            ["NOMBRE", "IMPORTE"],
            ["Juan", "5000"],
            ["TOTAL", "8000"],
        ]
        cols, rows = to_canonical_rows(raw)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["nombre"], "Juan")

    def test_no_header_uses_col_names(self):
        raw = [
            ["01/01/2024", "Deposito", "5000"],
            ["02/01/2024", "Retiro",   "200"],
        ]
        cols, rows = to_canonical_rows(raw)
        self.assertTrue(all(c.startswith("col_") for c in cols))
        self.assertEqual(len(rows), 2)

    def test_returns_tuple(self):
        raw = [["NOMBRE", "IMPORTE"], ["Juan", "100"]]
        result = to_canonical_rows(raw)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_alias_mapping_clabe(self):
        raw = [
            ["CUENTA CLABE", "NOMBRE BENEFICIARIO", "MONTO"],
            ["002180012345678901", "Juan Garcia", "5000"],
        ]
        cols, rows = to_canonical_rows(raw)
        self.assertIn("clabe", cols)
        self.assertIn("nombre_beneficiario", cols)
        self.assertIn("importe", cols)


# ─── table_quality_score ─────────────────────────────────────────────────────

class TestTableQualityScore(unittest.TestCase):

    def test_returns_dict_with_quality_key(self):
        cols = ["nombre", "importe"]
        rows = [{"nombre": "Juan", "importe": "5000"}]
        result = table_quality_score(cols, rows)
        self.assertIsInstance(result, dict)
        self.assertIn("quality", result)

    def test_full_table_quality_100(self):
        cols = ["nombre", "importe"]
        rows = [
            {"nombre": "Juan",  "importe": "5000"},
            {"nombre": "Maria", "importe": "3000"},
        ]
        result = table_quality_score(cols, rows)
        self.assertEqual(result["quality"], 100)

    def test_half_filled_quality_50(self):
        cols = ["nombre", "importe"]
        rows = [
            {"nombre": "Juan", "importe": ""},
            {"nombre": "Maria", "importe": ""},
        ]
        result = table_quality_score(cols, rows)
        self.assertEqual(result["quality"], 50)

    def test_empty_rows_quality_zero(self):
        result = table_quality_score(["nombre", "importe"], [])
        self.assertEqual(result["quality"], 0)

    def test_quality_is_numeric(self):
        cols = ["a", "b"]
        rows = [{"a": "1", "b": "2"}]
        q = table_quality_score(cols, rows)["quality"]
        self.assertIsInstance(q, (int, float))
        # Debe ser comparable con número (no fallar en document_processor)
        self.assertGreater(float(q), 0)


if __name__ == "__main__":
    unittest.main()
