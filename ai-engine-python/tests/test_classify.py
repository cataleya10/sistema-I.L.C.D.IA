import asyncio
import unittest

from app.pipelines import classify


class ClassifyPipelineTests(unittest.TestCase):
    def setUp(self):
        # Force keyword-path classification for deterministic unit tests.
        classify.MODEL_PATH = "__missing_model_for_tests__.json"

    def test_normalize_text_removes_accents_and_symbols(self):
        text = "  Cedula   de\tidentificacion!!  fiscal  "
        normalized = classify._normalize_text(text)
        self.assertEqual(normalized, "CEDULA DE IDENTIFICACION FISCAL")

    def test_classify_ine_from_text(self):
        doc_type, confidence = asyncio.run(
            classify.classify_document(None, "Instituto Nacional Electoral Credencial para votar", None)
        )
        self.assertEqual(doc_type, "INE")
        self.assertGreaterEqual(confidence, 0.88)

    def test_classify_comprobante_from_service_markers(self):
        doc_type, confidence = asyncio.run(
            classify.classify_document(None, "Recibo CFE total a pagar", None)
        )
        self.assertEqual(doc_type, "COMPROBANTE_DOMICILIO")
        self.assertGreaterEqual(confidence, 0.8)

    def test_classify_bancarios_from_filename(self):
        doc_type, confidence = asyncio.run(
            classify.classify_document(None, "", "estado_cuenta_bbva.pdf")
        )
        self.assertEqual(doc_type, "DATOS_BANCARIOS")
        self.assertGreaterEqual(confidence, 0.8)

    def test_classify_unknown_when_no_markers(self):
        doc_type, confidence = asyncio.run(
            classify.classify_document(None, "texto generico sin pistas", "archivo.pdf")
        )
        self.assertEqual(doc_type, "UNKNOWN")
        self.assertEqual(confidence, 0.5)

    def test_classify_constancia_with_accents(self):
        doc_type, confidence = asyncio.run(
            classify.classify_document(None, "Constancia de situación fiscal del SAT", None)
        )
        self.assertEqual(doc_type, "CONSTANCIA_SITUACION_FISCAL")
        self.assertGreaterEqual(confidence, 0.86)

    def test_classify_comprobante_att_marker(self):
        doc_type, confidence = asyncio.run(
            classify.classify_document(None, "Factura de AT&T total a pagar", None)
        )
        self.assertEqual(doc_type, "COMPROBANTE_DOMICILIO")
        self.assertGreaterEqual(confidence, 0.8)

    def test_classify_constancia_compact_ocr_text(self):
        doc_type, confidence = asyncio.run(
            classify.classify_document(None, "CONSTANCIADESITUACIONFISCALRFCSAT", None)
        )
        self.assertEqual(doc_type, "CONSTANCIA_SITUACION_FISCAL")
        self.assertGreaterEqual(confidence, 0.86)

    def test_classify_comprobante_compact_service_marker(self):
        doc_type, confidence = asyncio.run(
            classify.classify_document(None, "TELMEXTOTALAPAGAR", None)
        )
        self.assertEqual(doc_type, "COMPROBANTE_DOMICILIO")
        self.assertGreaterEqual(confidence, 0.86)

    def test_classify_factura_pago_nomina_markers(self):
        doc_type, confidence = asyncio.run(
            classify.classify_document(
                None,
                "Reporte de operaciones Dispersion de Pago de Nomina Cuenta Referencia Importe",
                "PAGO FIS BMPEI.pdf",
            )
        )
        self.assertEqual(doc_type, "FACTURA")
        self.assertGreaterEqual(confidence, 0.85)


if __name__ == "__main__":
    unittest.main()
