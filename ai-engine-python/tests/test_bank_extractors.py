"""
Tests para app/pipelines/extract/bank_extractors.py

Cubre:
  - _normalize_amount: montos > 999,999, símbolo de moneda, formato europeo, negativos
  - _norm: separadores / y - no fusionan tokens
  - BankExtractorBase._postprocess_row: normalización centralizada
  - InbursaExtractor: heredó normalización (antes no la tenía)
  - Bancos nuevos: Azteca, Afirme, BanBajío, Multiva, Invex
  - get_bank_extractor: matching exacto, parcial y fallback
  - get_doc_extractor: routing por doc_type y banco
"""

import unittest

from app.pipelines.extract.bank_extractors import (
    _norm,
    _normalize_amount,
    AztecaExtractor,
    AfirmeExtractor,
    BanBajioExtractor,
    BBVAExtractor,
    GenericBankExtractor,
    InbursaExtractor,
    InvexExtractor,
    MultivaBankExtractor,
    NominaExtractor,
    CFDIExtractor,
    SantanderExtractor,
    get_bank_extractor,
    get_doc_extractor,
)


# ─── _normalize_amount ────────────────────────────────────────────────────────

class NormalizeAmountTests(unittest.TestCase):
    def test_simple_amount(self):
        self.assertEqual(_normalize_amount("1234.56"), "1234.56")

    def test_single_thousands_comma(self):
        self.assertEqual(_normalize_amount("1,234.56"), "1234.56")

    def test_multiple_thousands_commas(self):
        """Bug original: "1,234,567.89" → "1234.567.89" con re.sub simple."""
        self.assertEqual(_normalize_amount("1,234,567.89"), "1234567.89")

    def test_very_large_amount(self):
        self.assertEqual(_normalize_amount("12,345,678,901.00"), "12345678901.00")

    def test_currency_symbol_stripped(self):
        self.assertEqual(_normalize_amount("$ 1,234.50"), "1234.50")

    def test_currency_symbol_no_space(self):
        self.assertEqual(_normalize_amount("$1234.50"), "1234.50")

    def test_european_format(self):
        """Formato europeo: puntos de miles, coma decimal."""
        self.assertEqual(_normalize_amount("1.234,56"), "1234.56")

    def test_european_format_large(self):
        self.assertEqual(_normalize_amount("1.234.567,89"), "1234567.89")

    def test_negative_amount(self):
        self.assertEqual(_normalize_amount("-1,234.56"), "-1234.56")

    def test_empty_string(self):
        self.assertEqual(_normalize_amount(""), "")

    def test_no_decimals(self):
        self.assertEqual(_normalize_amount("1,500"), "1500")

    def test_whitespace_removed(self):
        self.assertEqual(_normalize_amount("1 234.56"), "1234.56")

    def test_amount_with_mxn_prefix(self):
        """Algunos PDFs incluyen 'MXN' antes del monto."""
        self.assertEqual(_normalize_amount("MXN1,234.56"), "1234.56")


# ─── _norm ────────────────────────────────────────────────────────────────────

class NormTests(unittest.TestCase):
    def test_basic_uppercase(self):
        self.assertEqual(_norm("fecha"), "FECHA")

    def test_accents_removed(self):
        self.assertEqual(_norm("DEPÓSITO"), "DEPOSITO")

    def test_slash_separates_tokens(self):
        """FECHA/HORA no debe fusionarse en FECHAHORA."""
        result = _norm("FECHA/HORA")
        self.assertIn("FECHA", result)
        self.assertIn("HORA", result)
        self.assertNotEqual(result, "FECHAHORA")

    def test_hyphen_separates_tokens(self):
        result = _norm("NUM-OPERACION")
        self.assertIn("NUM", result)
        self.assertIn("OPERACION", result)

    def test_multiple_spaces_collapsed(self):
        self.assertEqual(_norm("FECHA   DE   PAGO"), "FECHA DE PAGO")

    def test_empty_string(self):
        self.assertEqual(_norm(""), "")

    def test_special_chars_removed(self):
        self.assertEqual(_norm("NO. REFERENCIA"), "NO REFERENCIA")


# ─── Normalización centralizada en base ───────────────────────────────────────

class BasePostprocessRowTests(unittest.TestCase):
    def _make_grid_stub(self, labels, rows_data):
        """Stub mínimo de GridTable para probar extract()."""
        class FakeGrid:
            column_labels = labels
            n_rows = len(rows_data) + 1  # +1 por header
            def row_texts(self, idx):
                return rows_data[idx - 1]
        return FakeGrid()

    def test_santander_normalizes_large_amounts(self):
        grid = self._make_grid_stub(
            ["FECHA", "DESCRIPCION", "CARGO", "ABONO", "SALDO"],
            [["01/01/2026", "TRASPASO", "1,500,000.00", "", "2,500,000.00"]],
        )
        ext = SantanderExtractor()
        cols, rows = ext.extract(grid)
        self.assertEqual(rows[0]["cargo"], "1500000.00")
        self.assertEqual(rows[0]["saldo"], "2500000.00")

    def test_bbva_normalizes_symbol(self):
        grid = self._make_grid_stub(
            ["FECHA", "CONCEPTO", "RETIROS", "DEPOSITOS", "SALDO"],
            [["02/01/2026", "PAGO", "$ 2,345.67", "", "$ 10,000.00"]],
        )
        ext = BBVAExtractor()
        cols, rows = ext.extract(grid)
        self.assertEqual(rows[0]["cargo"], "2345.67")
        self.assertEqual(rows[0]["saldo"], "10000.00")

    def test_inbursa_normalizes_amounts(self):
        """Inbursa antes no tenía _postprocess_row; ahora hereda de la base."""
        grid = self._make_grid_stub(
            ["FECHA", "DESCRIPCION", "CARGO", "ABONO", "SALDO"],
            [["03/01/2026", "DEPOSITO", "", "$ 45,678.90", "$ 100,000.00"]],
        )
        ext = InbursaExtractor()
        cols, rows = ext.extract(grid)
        self.assertEqual(rows[0]["abono"], "45678.90")
        self.assertEqual(rows[0]["saldo"], "100000.00")

    def test_nomina_uses_correct_money_keys(self):
        grid = self._make_grid_stub(
            ["CLAVE", "CONCEPTO", "IMPORTE GRAVADO", "IMPORTE EXENTO", "IMPORTE"],
            [["001", "SUELDO BASE", "15,500.00", "0.00", "15,500.00"]],
        )
        ext = NominaExtractor()
        cols, rows = ext.extract(grid)
        self.assertEqual(rows[0]["importe_gravado"], "15500.00")
        self.assertEqual(rows[0]["importe"], "15500.00")

    def test_cfdi_uses_correct_money_keys(self):
        grid = self._make_grid_stub(
            ["CANTIDAD", "DESCRIPCION", "VALOR UNITARIO", "IMPORTE"],
            [["2", "LAPTOP", "25,000.00", "50,000.00"]],
        )
        ext = CFDIExtractor()
        cols, rows = ext.extract(grid)
        self.assertEqual(rows[0]["valor_unitario"], "25000.00")
        self.assertEqual(rows[0]["importe"], "50000.00")


# ─── Bancos nuevos ────────────────────────────────────────────────────────────

class NewBankExtractorsTests(unittest.TestCase):
    def _make_grid_stub(self, labels, rows_data):
        class FakeGrid:
            column_labels = labels
            n_rows = len(rows_data) + 1
            def row_texts(self, idx):
                return rows_data[idx - 1]
        return FakeGrid()

    def test_azteca_inverted_column_order(self):
        """Azteca usa DEPOSITO/RETIRO en lugar de ABONO/CARGO."""
        grid = self._make_grid_stub(
            ["FECHA", "CONCEPTO", "DEPOSITO", "RETIRO", "SALDO"],
            [["05/01/2026", "PAGO NOMINA", "3,000.00", "", "13,000.00"]],
        )
        ext = AztecaExtractor()
        cols, rows = ext.extract(grid)
        self.assertIn("abono", cols)
        self.assertEqual(rows[0]["abono"], "3000.00")

    def test_afirme_basic_extraction(self):
        grid = self._make_grid_stub(
            ["FECHA", "DESCRIPCION", "CARGO", "ABONO", "SALDO"],
            [["06/01/2026", "COMPRA", "500.00", "", "9,500.00"]],
        )
        ext = AfirmeExtractor()
        cols, rows = ext.extract(grid)
        self.assertEqual(rows[0]["cargo"], "500.00")
        self.assertEqual(rows[0]["saldo"], "9500.00")

    def test_banbajio_basic_extraction(self):
        grid = self._make_grid_stub(
            ["FECHA", "DESCRIPCION", "CARGO", "ABONO", "SALDO"],
            [["07/01/2026", "TRANSFERENCIA", "1,000.00", "", "4,000.00"]],
        )
        ext = BanBajioExtractor()
        cols, rows = ext.extract(grid)
        self.assertEqual(rows[0]["cargo"], "1000.00")

    def test_multiva_basic_extraction(self):
        grid = self._make_grid_stub(
            ["FECHA", "DESCRIPCION", "CARGO", "ABONO", "SALDO"],
            [["08/01/2026", "CHEQUE", "2,000.00", "", "8,000.00"]],
        )
        ext = MultivaBankExtractor()
        cols, rows = ext.extract(grid)
        self.assertEqual(rows[0]["cargo"], "2000.00")

    def test_invex_basic_extraction(self):
        grid = self._make_grid_stub(
            ["FECHA", "CONCEPTO", "CARGO", "ABONO", "SALDO"],
            [["09/01/2026", "DEPOSITO", "", "5,000.00", "15,000.00"]],
        )
        ext = InvexExtractor()
        cols, rows = ext.extract(grid)
        self.assertEqual(rows[0]["abono"], "5000.00")


# ─── get_bank_extractor ───────────────────────────────────────────────────────

class GetBankExtractorTests(unittest.TestCase):
    def test_exact_match_santander(self):
        self.assertIsInstance(get_bank_extractor("SANTANDER"), SantanderExtractor)

    def test_exact_match_bbva(self):
        self.assertIsInstance(get_bank_extractor("BBVA"), BBVAExtractor)

    def test_partial_match_bbva_bancomer(self):
        self.assertIsInstance(get_bank_extractor("BBVA BANCOMER MEXICO"), BBVAExtractor)

    def test_new_bank_azteca(self):
        self.assertIsInstance(get_bank_extractor("BANCO AZTECA"), AztecaExtractor)

    def test_new_bank_afirme(self):
        self.assertIsInstance(get_bank_extractor("AFIRME"), AfirmeExtractor)

    def test_new_bank_banbajio(self):
        self.assertIsInstance(get_bank_extractor("BANCO DEL BAJIO"), BanBajioExtractor)

    def test_new_bank_multiva(self):
        self.assertIsInstance(get_bank_extractor("MULTIVA"), MultivaBankExtractor)

    def test_new_bank_invex(self):
        self.assertIsInstance(get_bank_extractor("INVEX"), InvexExtractor)

    def test_unknown_bank_returns_generic(self):
        self.assertIsInstance(get_bank_extractor("BANCO DESCONOCIDO XYZ"), GenericBankExtractor)

    def test_none_returns_generic(self):
        self.assertIsInstance(get_bank_extractor(None), GenericBankExtractor)

    def test_empty_string_returns_generic(self):
        self.assertIsInstance(get_bank_extractor(""), GenericBankExtractor)

    def test_case_insensitive(self):
        self.assertIsInstance(get_bank_extractor("santander"), SantanderExtractor)


# ─── get_doc_extractor ────────────────────────────────────────────────────────

class GetDocExtractorTests(unittest.TestCase):
    def test_nomina_doc_type(self):
        self.assertIsInstance(get_doc_extractor("NOMINA"), NominaExtractor)

    def test_cfdi_doc_type(self):
        self.assertIsInstance(get_doc_extractor("CFDI"), CFDIExtractor)

    def test_factura_doc_type(self):
        self.assertIsInstance(get_doc_extractor("FACTURA"), CFDIExtractor)

    def test_datos_bancarios_with_bank(self):
        self.assertIsInstance(get_doc_extractor("DATOS_BANCARIOS", "SANTANDER"), SantanderExtractor)

    def test_datos_bancarios_without_bank_returns_generic(self):
        self.assertIsInstance(get_doc_extractor("DATOS_BANCARIOS", None), GenericBankExtractor)

    def test_unknown_doc_type_returns_generic(self):
        self.assertIsInstance(get_doc_extractor("TIPO_DESCONOCIDO"), GenericBankExtractor)


if __name__ == "__main__":
    unittest.main()
