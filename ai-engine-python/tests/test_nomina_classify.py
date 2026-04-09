"""
Tests para clasificación de NOMINA y helpers de document_processor.

  - Clasificación de nóminas (nuevo tipo, antes caía a FACTURA/GENERICO)
  - _correct_doc_type_from_fields
  - _detect_bank_from_fields
  - _table_content_sig
"""
import asyncio
import sys
import unittest
from unittest.mock import MagicMock

# ─── Mock de dependencias pesadas antes de importar document_processor ────────
# Save originals so we can restore them after this module's tests run
_MOCKED_MODULES = [
    "pandas", "fastapi", "app.pipelines.table_postprocess",
    "app.utils.table_utils", "app.pipelines.preprocess",
    "app.pipelines.ocr", "app.pipelines.validate",
    "app.services.online_learning", "app.services.llm_fallback",
]
_SAVED_MODULES: dict = {}
for mod in _MOCKED_MODULES:
    _SAVED_MODULES[mod] = sys.modules.get(mod)
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

# Hacer que pandas.DataFrame retorne algo serializable
pd_mock = sys.modules["pandas"]
if isinstance(pd_mock, MagicMock):
    pd_mock.DataFrame = MagicMock(return_value=MagicMock(
        to_csv=MagicMock(return_value=""),
        to_excel=MagicMock(),
    ))

from app.pipelines import classify


def teardown_module():
    """Restore original sys.modules entries to prevent cross-test contamination.

    After restoring, also evict modules that imported from the mocked versions
    so that subsequent test files get fresh, real imports.
    """
    for mod, original in _SAVED_MODULES.items():
        if original is None:
            sys.modules.pop(mod, None)
        else:
            sys.modules[mod] = original

    # Evict modules that may hold cached references to MagicMock objects so
    # subsequent test files reimport them cleanly.
    _DEPENDENTS_PREFIX = (
        "app.pipelines.extract",
        "app.pipelines.table_postprocess",
        "app.services.document_processor",
        "app.services.extractor_service",
        "app.utils.table_utils",
    )
    for key in list(sys.modules.keys()):
        if key.startswith(_DEPENDENTS_PREFIX):
            sys.modules.pop(key, None)


# ─── Clasificación de NOMINA ──────────────────────────────────────────────────

class TestClassifyNomina(unittest.TestCase):

    def setUp(self):
        classify.MODEL_PATH = "__missing_model_for_tests__.json"

    def test_nomina_from_total_percepciones(self):
        doc_type, conf = asyncio.run(
            classify.classify_document(None, "Total percepciones 12500 Total deducciones 2300 Neto a pagar 10200", None)
        )
        self.assertEqual(doc_type, "NOMINA")
        self.assertGreaterEqual(conf, 0.85)

    def test_nomina_from_recibo_nomina_text(self):
        doc_type, conf = asyncio.run(
            classify.classify_document(None, "Recibo de nomina periodo quincenal sueldo base INFONAVIT dias trabajados", None)
        )
        self.assertEqual(doc_type, "NOMINA")

    def test_nomina_from_filename(self):
        doc_type, conf = asyncio.run(
            classify.classify_document(None, "", "recibo_nomina_enero.pdf")
        )
        self.assertEqual(doc_type, "NOMINA")
        self.assertGreaterEqual(conf, 0.88)

    def test_nomina_before_factura_for_payroll(self):
        # Un comprobante de nómina NO debe clasificar como FACTURA
        texto = "Comprobante de nomina Total percepciones 15000 Neto a pagar 12500 IMSS INFONAVIT"
        doc_type, _ = asyncio.run(classify.classify_document(None, texto, None))
        self.assertEqual(doc_type, "NOMINA")
        self.assertNotEqual(doc_type, "FACTURA")

    def test_spei_still_classifies_as_factura(self):
        # Un SPEI no debe confundirse con NOMINA
        texto = "Transferencia SPEI enviado Clave rastreo folio unico datos del beneficiario"
        doc_type, _ = asyncio.run(classify.classify_document(None, texto, None))
        self.assertEqual(doc_type, "FACTURA")

    def test_banco_still_classifies_as_datos_bancarios(self):
        texto = "Estado de cuenta BBVA fecha de corte saldo anterior movimientos del periodo CLABE"
        doc_type, _ = asyncio.run(classify.classify_document(None, texto, None))
        self.assertEqual(doc_type, "DATOS_BANCARIOS")


# ─── Helpers de document_processor ───────────────────────────────────────────

class TestDocumentProcessorHelpers(unittest.TestCase):
    """
    Prueba funciones puras de document_processor sin levantar FastAPI ni pandas.
    Las importamos después de mockear las dependencias pesadas.
    """

    @classmethod
    def setUpClass(cls):
        # Importar solo las funciones puras, esquivando el import de pandas
        # que ocurre al nivel de módulo
        import importlib, types

        # Crear módulo ficticio para app.schemas.process
        schema_mod = types.ModuleType("app.schemas.process")
        schema_mod.ProcessResponse = MagicMock
        schema_mod.DocumentField = MagicMock
        schema_mod.ProcessMeta = MagicMock
        schema_mod.ExtractedTable = MagicMock
        sys.modules["app.schemas.process"] = schema_mod

        # Mockear todo lo que document_processor importa a nivel de módulo
        for mod in [
            "app.core.config", "app.pipelines.extract",
            "app.pipelines.classify", "app.pipelines.validate",
        ]:
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()

        # Mockear settings
        cfg = sys.modules["app.core.config"]
        cfg.settings = MagicMock()
        cfg.settings.payroll_strict_mode = True
        cfg.settings.payroll_strict_min_rows = 5
        cfg.settings.payroll_strict_min_fill_rate = 0.9
        cfg.settings.payroll_strict_max_dominant_surname_ratio = 0.55
        cfg.settings.pipeline_version = "test"
        cfg.settings.model_version = "test"
        cfg.settings.llm_fallback_enabled = False
        cfg.settings.text_layer_fastpath_types = []
        cfg.settings.acta_sanity_guards_enabled = False

        # Importar el módulo con los mocks en su lugar
        if "app.services.document_processor" in sys.modules:
            del sys.modules["app.services.document_processor"]

        try:
            import app.services.document_processor as dp
            cls.dp = dp
        except Exception as e:
            cls.dp = None
            cls.skip_reason = str(e)

    def _skip_if_unavailable(self):
        if self.dp is None:
            self.skipTest(f"document_processor no importable: {getattr(self, 'skip_reason', '')}")

    # ── _detect_bank_from_fields ─────────────────────────────────────────────

    def test_detect_bank_bbva(self):
        self._skip_if_unavailable()
        fields = [
            {"key": "banco", "value": "BBVA BANCOMER"},
            {"key": "clabe", "value": "002180700000000001"},
        ]
        result = self.dp._detect_bank_from_fields(fields)
        self.assertIn("BBVA", result)

    def test_detect_bank_from_banco_receptor(self):
        self._skip_if_unavailable()
        fields = [{"key": "banco_receptor", "value": "Santander"}]
        result = self.dp._detect_bank_from_fields(fields)
        self.assertIn("SANTANDER", result)

    def test_detect_bank_no_bank_field(self):
        self._skip_if_unavailable()
        fields = [{"key": "nombre", "value": "Juan Garcia"}]
        result = self.dp._detect_bank_from_fields(fields)
        self.assertIsNone(result)

    # ── _correct_doc_type_from_fields ────────────────────────────────────────

    def test_corrects_generico_to_datos_bancarios(self):
        self._skip_if_unavailable()
        fields = [
            {"key": "clabe",        "value": "002180700000000001"},
            {"key": "cuenta",       "value": "1234567890"},
            {"key": "banco",        "value": "BBVA"},
            {"key": "titular",      "value": "Juan Garcia"},
            {"key": "fecha_corte",  "value": "31/01/2024"},
        ]
        new_type, new_conf, warning = self.dp._correct_doc_type_from_fields(
            "GENERICO", fields, 0.5
        )
        self.assertEqual(new_type, "DATOS_BANCARIOS")
        self.assertIsNotNone(warning)

    def test_does_not_correct_high_confidence(self):
        self._skip_if_unavailable()
        fields = [
            {"key": "clabe",   "value": "002180700000000001"},
            {"key": "cuenta",  "value": "1234567890"},
        ]
        # Confianza alta → no corrige
        new_type, new_conf, warning = self.dp._correct_doc_type_from_fields(
            "INE", fields, 0.90
        )
        self.assertEqual(new_type, "INE")
        self.assertIsNone(warning)

    def test_corrects_generico_to_nomina(self):
        self._skip_if_unavailable()
        fields = [
            {"key": "nss",                 "value": "12345678901"},
            {"key": "curp",                "value": "GACJ900101HDFXXX01"},
            {"key": "total_percepciones",  "value": "15000"},
            {"key": "total_deducciones",   "value": "3000"},
            {"key": "neto_pagar",          "value": "12000"},
        ]
        new_type, _, warning = self.dp._correct_doc_type_from_fields(
            "GENERICO", fields, 0.5
        )
        self.assertEqual(new_type, "NOMINA")

    def test_no_correction_when_insufficient_signals(self):
        self._skip_if_unavailable()
        fields = [{"key": "clabe", "value": "002180700000000001"}]
        new_type, _, warning = self.dp._correct_doc_type_from_fields(
            "GENERICO", fields, 0.5
        )
        # Solo 1 señal → sin corrección (mínimo es 2)
        self.assertEqual(new_type, "GENERICO")
        self.assertIsNone(warning)

    # ── _table_content_sig ───────────────────────────────────────────────────

    def test_same_content_same_sig(self):
        self._skip_if_unavailable()
        cols = ["nombre", "importe"]
        rows = [{"nombre": "Juan", "importe": "5000"}]
        sig1 = self.dp._table_content_sig(cols, rows)
        sig2 = self.dp._table_content_sig(cols, rows)
        self.assertEqual(sig1, sig2)

    def test_different_content_different_sig(self):
        self._skip_if_unavailable()
        cols = ["nombre", "importe"]
        rows1 = [{"nombre": "Juan",  "importe": "5000"}]
        rows2 = [{"nombre": "Maria", "importe": "3000"}]
        self.assertNotEqual(
            self.dp._table_content_sig(cols, rows1),
            self.dp._table_content_sig(cols, rows2),
        )


if __name__ == "__main__":
    unittest.main()
