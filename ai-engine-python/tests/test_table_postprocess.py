"""Tests for the Pandas-based table post-processing module."""

import unittest


class TestCleanAmount(unittest.TestCase):
    """Tests for _clean_amount cell cleaner."""

    def test_standard_format_unchanged(self):
        from app.pipelines.table_postprocess import _clean_amount
        self.assertEqual(_clean_amount("$3,240.73"), "$3,240.73")

    def test_no_dollar_sign_adds_it(self):
        from app.pipelines.table_postprocess import _clean_amount
        self.assertEqual(_clean_amount("3240.73"), "$3,240.73")

    def test_comma_decimal_mexico_format(self):
        from app.pipelines.table_postprocess import _clean_amount
        self.assertEqual(_clean_amount("$3.240,73"), "$3,240.73")

    def test_ocr_letter_o_replaced(self):
        from app.pipelines.table_postprocess import _clean_amount
        result = _clean_amount("$3,24O.73")
        self.assertEqual(result, "$3,240.73")

    def test_empty_returns_empty(self):
        from app.pipelines.table_postprocess import _clean_amount
        self.assertEqual(_clean_amount(""), "")
        self.assertEqual(_clean_amount(""), "")

    def test_whole_number(self):
        from app.pipelines.table_postprocess import _clean_amount
        self.assertEqual(_clean_amount("$5000"), "$5,000.00")

    def test_currency_suffix_stripped(self):
        from app.pipelines.table_postprocess import _clean_amount
        result = _clean_amount("$3,240.73 MXN")
        self.assertEqual(result, "$3,240.73")


class TestCleanAccount(unittest.TestCase):
    """Tests for _clean_account cell cleaner."""

    def test_clean_numeric_account(self):
        from app.pipelines.table_postprocess import _clean_account
        self.assertEqual(_clean_account("002180019912345678"), "002180019912345678")

    def test_strips_stray_chars(self):
        from app.pipelines.table_postprocess import _clean_account
        self.assertEqual(_clean_account("0021800199-12345678"), "002180019912345678")

    def test_short_text_kept(self):
        from app.pipelines.table_postprocess import _clean_account
        self.assertEqual(_clean_account("CLABE"), "CLABE")

    def test_empty_returns_empty(self):
        from app.pipelines.table_postprocess import _clean_account
        self.assertEqual(_clean_account(""), "")


class TestCleanName(unittest.TestCase):
    """Tests for _clean_name cell cleaner."""

    def test_uppercases(self):
        from app.pipelines.table_postprocess import _clean_name
        self.assertEqual(_clean_name("Juan Perez Lopez"), "JUAN PEREZ LOPEZ")

    def test_collapses_whitespace(self):
        from app.pipelines.table_postprocess import _clean_name
        self.assertEqual(_clean_name("MARIA   ELENA   GUTIERREZ"), "MARIA ELENA GUTIERREZ")

    def test_strips_noise(self):
        from app.pipelines.table_postprocess import _clean_name
        result = _clean_name("--MARIA ELENA--")
        self.assertEqual(result, "MARIA ELENA")

    def test_empty_returns_empty(self):
        from app.pipelines.table_postprocess import _clean_name
        self.assertEqual(_clean_name(""), "")


class TestCleanStatus(unittest.TestCase):
    """Tests for _clean_status cell cleaner."""

    def test_valid_status_unchanged(self):
        from app.pipelines.table_postprocess import _clean_status
        self.assertEqual(_clean_status("APLICADO"), "APLICADO")
        self.assertEqual(_clean_status("RECHAZADO"), "RECHAZADO")

    def test_lowercase_normalized(self):
        from app.pipelines.table_postprocess import _clean_status
        self.assertEqual(_clean_status("aplicado"), "APLICADO")

    def test_embedded_status_extracted(self):
        from app.pipelines.table_postprocess import _clean_status
        self.assertEqual(_clean_status("00 APLICADO OK"), "APLICADO")

    def test_truncated_status_recovered(self):
        from app.pipelines.table_postprocess import _clean_status
        self.assertEqual(_clean_status("PROCE"), "PROCESADO")
        self.assertEqual(_clean_status("APLIC"), "APLICADO")
        self.assertEqual(_clean_status("RECHA"), "RECHAZADO")

    def test_empty_returns_empty(self):
        from app.pipelines.table_postprocess import _clean_status
        self.assertEqual(_clean_status(""), "")


class TestPostprocessPaymentTable(unittest.TestCase):
    """Integration tests for the full Pandas post-processing pipeline."""

    def test_basic_cleaning(self):
        from app.pipelines.table_postprocess import postprocess_payment_table
        columns = ["cuenta", "importe", "nombre", "estatus"]
        rows = [
            {"cuenta": "002180019912345678", "importe": "3240.73", "nombre": "juan perez", "estatus": "APLICADO"},
        ]
        result_cols, result_rows = postprocess_payment_table(columns, rows, bank="BANORTE")
        self.assertEqual(len(result_rows), 1)
        row = result_rows[0]
        self.assertEqual(row["importe"], "$3,240.73")  # Amount normalized
        self.assertEqual(row["nombre"], "JUAN PEREZ")  # Name uppercased
        self.assertEqual(row["estatus"], "APLICADO")  # Status preserved

    def test_deduplication(self):
        from app.pipelines.table_postprocess import postprocess_payment_table
        columns = ["cuenta", "importe", "nombre"]
        rows = [
            {"cuenta": "123456789", "importe": "$610.44", "nombre": "MARLA GRISELDA"},
            {"cuenta": "123456789", "importe": "$610.44", "nombre": "MARLA GRISELDA"},
            {"cuenta": "987654321", "importe": "$1,537.35", "nombre": "ROLANDO ROGERIO"},
        ]
        result_cols, result_rows = postprocess_payment_table(columns, rows)
        self.assertEqual(len(result_rows), 2)  # Duplicate removed

    def test_status_inference_from_descripcion(self):
        from app.pipelines.table_postprocess import postprocess_payment_table
        columns = ["cuenta", "importe", "estatus", "descripcion"]
        rows = [
            {"cuenta": "123456789", "importe": "$610.44", "estatus": "", "descripcion": "ACEPTADO"},
        ]
        result_cols, result_rows = postprocess_payment_table(columns, rows)
        self.assertEqual(len(result_rows), 1)
        self.assertEqual(result_rows[0]["estatus"], "ACEPTADO")

    def test_empty_rows_removed(self):
        from app.pipelines.table_postprocess import postprocess_payment_table
        columns = ["cuenta", "importe"]
        rows = [
            {"cuenta": "123456789", "importe": "$610.44"},
            {"cuenta": "", "importe": ""},
        ]
        result_cols, result_rows = postprocess_payment_table(columns, rows)
        self.assertEqual(len(result_rows), 1)

    def test_empty_input_passthrough(self):
        from app.pipelines.table_postprocess import postprocess_payment_table
        cols, rows = postprocess_payment_table(["a", "b"], [])
        self.assertEqual(cols, ["a", "b"])
        self.assertEqual(rows, [])

    def test_multirow_banorte_table(self):
        """Simulate a 5-row Banorte table with various cleanings needed."""
        from app.pipelines.table_postprocess import postprocess_payment_table
        columns = ["numero_empleado", "nombre", "tipo_cuenta", "cuenta", "importe", "estatus", "codigo", "descripcion", "clave_rastreo"]
        rows = [
            {"numero_empleado": " 000123 ", "nombre": "juan perez lopez", "tipo_cuenta": "03",
             "cuenta": "0021800-19912345678", "importe": "3240.73", "estatus": "aplicado",
             "codigo": "00", "descripcion": "ACEPTADO", "clave_rastreo": "BANORTE 12345"},
            {"numero_empleado": "000456", "nombre": "  MARIA   ELENA  ", "tipo_cuenta": "03",
             "cuenta": "002180019987654321", "importe": "$1,537.35", "estatus": "PROCE",
             "codigo": "00", "descripcion": "PROCESADO", "clave_rastreo": "BANORTE67890"},
            {"numero_empleado": "000789", "nombre": "CARLOS RAMIREZ", "tipo_cuenta": "01",
             "cuenta": "002180019911111111", "importe": "$610.44", "estatus": "",
             "codigo": "00", "descripcion": "APLICADO", "clave_rastreo": "BANORTEABC"},
            {"numero_empleado": "000111", "nombre": "ANA GARCIA", "tipo_cuenta": "03",
             "cuenta": "002180019922222222", "importe": "$2,100.00 MXN", "estatus": "RECHAZADO",
             "codigo": "05", "descripcion": "RECHAZADO", "clave_rastreo": "BANORTEXYZ"},
            {"numero_empleado": "000222", "nombre": "--ROBERTO DIAZ GOMEZ--", "tipo_cuenta": "03",
             "cuenta": "002180019933333333", "importe": "45O.25", "estatus": "ACEPT",
             "codigo": "00", "descripcion": "ACEPTADO", "clave_rastreo": "BANORTE999"},
        ]
        result_cols, result_rows = postprocess_payment_table(columns, rows, bank="BANORTE")
        self.assertEqual(len(result_rows), 5)

        # Row 0: amount & name cleaned, account dash stripped
        self.assertEqual(result_rows[0]["importe"], "$3,240.73")
        self.assertEqual(result_rows[0]["nombre"], "JUAN PEREZ LOPEZ")
        self.assertEqual(result_rows[0]["cuenta"], "002180019912345678")
        self.assertEqual(result_rows[0]["estatus"], "APLICADO")
        self.assertEqual(result_rows[0]["numero_empleado"], "000123")

        # Row 1: truncated status recovered, whitespace in name collapsed
        self.assertEqual(result_rows[1]["estatus"], "PROCESADO")
        self.assertEqual(result_rows[1]["nombre"], "MARIA ELENA")

        # Row 2: empty status filled from descripcion
        self.assertEqual(result_rows[2]["estatus"], "APLICADO")

        # Row 3: MXN suffix stripped from amount
        self.assertEqual(result_rows[3]["importe"], "$2,100.00")

        # Row 4: OCR O→0 in amount, noise stripped from name, truncated status
        self.assertEqual(result_rows[4]["importe"], "$450.25")
        self.assertEqual(result_rows[4]["nombre"], "ROBERTO DIAZ GOMEZ")
        self.assertEqual(result_rows[4]["estatus"], "ACEPTADO")


class TestPostprocessMetadata(unittest.TestCase):
    """Tests for metadata precision cleaning."""

    def test_amount_fields_normalized(self):
        from app.pipelines.table_postprocess import postprocess_metadata
        meta = {"importe_detectado": "3240.73", "importe_total_movimientos": "$15,000.50 MXN"}
        result = postprocess_metadata(meta, bank="BBVA")
        self.assertEqual(result["importe_detectado"], "$3,240.73")
        self.assertEqual(result["importe_total_movimientos"], "$15,000.50")

    def test_name_fields_uppercased(self):
        from app.pipelines.table_postprocess import postprocess_metadata
        meta = {"titular": "maria elena gutierrez", "nombre_empresa": "acme corp"}
        result = postprocess_metadata(meta)
        self.assertEqual(result["titular"], "MARIA ELENA GUTIERREZ")
        self.assertEqual(result["nombre_empresa"], "ACME CORP")

    def test_folio_fields_cleaned(self):
        from app.pipelines.table_postprocess import postprocess_metadata
        meta = {"folio_firma": " 7748 662779 ", "numero_lote": " 123 "}
        result = postprocess_metadata(meta)
        self.assertEqual(result["folio_firma"], "7748662779")
        self.assertEqual(result["numero_lote"], "123")

    def test_count_fields_numeric(self):
        from app.pipelines.table_postprocess import postprocess_metadata
        meta = {"cantidad_total_movimientos": "23 REGISTROS"}
        result = postprocess_metadata(meta)
        self.assertEqual(result["cantidad_total_movimientos"], "23")

    def test_empty_passthrough(self):
        from app.pipelines.table_postprocess import postprocess_metadata
        self.assertEqual(postprocess_metadata({}), {})


class TestComputeTableQualityReport(unittest.TestCase):
    """Tests for quality report generation."""

    def test_full_table_quality(self):
        from app.pipelines.table_postprocess import compute_table_quality_report
        columns = ["cuenta", "importe", "nombre", "estatus"]
        rows = [
            {"cuenta": "123", "importe": "$100.00", "nombre": "JUAN", "estatus": "APLICADO"},
            {"cuenta": "456", "importe": "$200.00", "nombre": "MARIA", "estatus": "PROCESADO"},
        ]
        report = compute_table_quality_report(columns, rows)
        self.assertEqual(report["row_count"], 2)
        self.assertEqual(report["overall_quality"], 100.0)

    def test_partial_fill_quality(self):
        from app.pipelines.table_postprocess import compute_table_quality_report
        columns = ["cuenta", "importe", "nombre", "estatus"]
        rows = [
            {"cuenta": "123", "importe": "$100.00", "nombre": "JUAN", "estatus": ""},
            {"cuenta": "", "importe": "$200.00", "nombre": "", "estatus": ""},
        ]
        report = compute_table_quality_report(columns, rows)
        self.assertEqual(report["row_count"], 2)
        self.assertLess(report["overall_quality"], 100.0)
        self.assertIn("cuenta", report["fill_rates"])

    def test_empty_rows_zero_quality(self):
        from app.pipelines.table_postprocess import compute_table_quality_report
        report = compute_table_quality_report(["a", "b"], [])
        self.assertEqual(report["row_count"], 0)
        self.assertEqual(report["overall_quality"], 0.0)


class TestIntegrationWithExtract(unittest.TestCase):
    """Test that postprocessor integrates correctly with extract.py pipeline."""

    def test_payment_detail_has_quality_report(self):
        from app.pipelines.extract import _extract_payment_detail_payload
        table_payload = {
            "rows": [
                ["CUENTA", "IMPORTE", "NOMBRE", "ESTATUS"],
                ["56783223195", "$610.44", "MARLA GRISELDA", "APLICADO"],
                ["56936397470", "$1,537.35", "ROLANDO", "PROCESADO"],
            ],
        }
        result = _extract_payment_detail_payload("BANORTE REPORTE DE TRANSMISION", table_payload)
        self.assertIsNotNone(result)
        assert result is not None  # narrow type for Pyright
        self.assertIn("quality_report", result)
        qr = result["quality_report"]
        self.assertGreater(qr["row_count"], 0)
        self.assertGreater(qr["overall_quality"], 0)

    def test_payment_detail_canonical_rows_cleaned(self):
        from app.pipelines.extract import _extract_payment_detail_payload
        table_payload = {
            "rows": [
                ["CUENTA", "IMPORTE", "NOMBRE", "ESTATUS", "DESCRIPCION"],
                ["002180019912345678", "3240.73", "juan perez lopez", "", "APLICADO"],
            ],
        }
        result = _extract_payment_detail_payload("BANORTE DISPERSIONES", table_payload)
        self.assertIsNotNone(result)
        assert result is not None  # narrow type for Pyright
        canonical = result["table"]["canonical_rows"]
        self.assertGreater(len(canonical), 0)
        row = canonical[0]
        # Amount should be normalized by Pandas post-processor
        if "importe" in row:
            self.assertTrue(row["importe"].startswith("$"))
        # Name should be uppercased
        name_val = row.get("nombre") or row.get("nombre_beneficiario") or ""
        if name_val:
            self.assertEqual(name_val, name_val.upper())


# ==========================================================================
# Cell garbage filter tests
# ==========================================================================

class TestIsGarbageCell(unittest.TestCase):
    """Tests for _is_garbage_cell detector."""

    def test_normal_text_not_garbage(self):
        from app.pipelines.table_postprocess import _is_garbage_cell
        self.assertFalse(_is_garbage_cell("JUAN PEREZ LOPEZ"))
        self.assertFalse(_is_garbage_cell("$1,500.00"))
        self.assertFalse(_is_garbage_cell("1234567890"))

    def test_control_chars_garbage(self):
        from app.pipelines.table_postprocess import _is_garbage_cell
        self.assertTrue(_is_garbage_cell("HOLA\x00MUNDO"))
        self.assertTrue(_is_garbage_cell("\x01\x02\x03"))

    def test_excessive_special_chars(self):
        from app.pipelines.table_postprocess import _is_garbage_cell
        self.assertTrue(_is_garbage_cell("|||///===\\\\"))
        self.assertTrue(_is_garbage_cell("@@##$$%%^^"))

    def test_repeated_char_garbage(self):
        from app.pipelines.table_postprocess import _is_garbage_cell
        self.assertTrue(_is_garbage_cell("========"))
        self.assertTrue(_is_garbage_cell("||||||||"))

    def test_empty_not_garbage(self):
        from app.pipelines.table_postprocess import _is_garbage_cell
        self.assertFalse(_is_garbage_cell(""))

    def test_short_normal_text(self):
        from app.pipelines.table_postprocess import _is_garbage_cell
        self.assertFalse(_is_garbage_cell("OK"))
        self.assertFalse(_is_garbage_cell("$50.00"))


# ==========================================================================
# Row quality threshold tests
# ==========================================================================

class TestRowQualityThreshold(unittest.TestCase):
    """Tests for minimum row quality enforcement in postprocess_payment_table."""

    def test_low_quality_row_dropped(self):
        from app.pipelines.table_postprocess import postprocess_payment_table
        columns = ["cuenta", "referencia", "importe", "nombre_beneficiario", "estatus"]
        rows = [
            # Good row
            {"cuenta": "1234567890", "referencia": "REF001", "importe": "$1,500.00", "nombre_beneficiario": "JUAN PEREZ", "estatus": "APLICADO"},
            # Bad row — only 1 important column filled
            {"cuenta": "", "referencia": "", "importe": "", "nombre_beneficiario": "", "estatus": "APLICADO"},
        ]
        result_cols, result_rows = postprocess_payment_table(columns, rows, bank="BBVA")
        # Good row should survive, bad row should be dropped
        self.assertEqual(len(result_rows), 1)
        self.assertIn("1234567890", result_rows[0].get("cuenta", ""))

    def test_good_rows_preserved(self):
        from app.pipelines.table_postprocess import postprocess_payment_table
        columns = ["cuenta", "importe", "nombre_beneficiario"]
        rows = [
            {"cuenta": "1234567890", "importe": "$1,500.00", "nombre_beneficiario": "JUAN PEREZ"},
            {"cuenta": "9876543210", "importe": "$2,000.00", "nombre_beneficiario": "ANA LOPEZ"},
        ]
        result_cols, result_rows = postprocess_payment_table(columns, rows, bank="BBVA")
        self.assertEqual(len(result_rows), 2)

    def test_garbage_cells_cleaned_before_processing(self):
        from app.pipelines.table_postprocess import postprocess_payment_table
        columns = ["cuenta", "referencia", "importe", "nombre_beneficiario"]
        rows = [
            {"cuenta": "1234567890", "referencia": "REF001", "importe": "$1,500.00", "nombre_beneficiario": "||||===="},
        ]
        result_cols, result_rows = postprocess_payment_table(columns, rows, bank="BBVA")
        if result_rows:
            name_val = result_rows[0].get("nombre_beneficiario", "")
            # Garbage should have been cleaned out
            self.assertNotIn("||||", name_val)


if __name__ == "__main__":
    unittest.main()
