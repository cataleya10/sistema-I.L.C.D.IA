import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services import document_processor as dp


def _field(key: str, value: str, valid: bool = True, confidence: float = 0.95) -> dict:
     return {
        "key": key,
        "label": key,
        "value": value,
        "confidence": confidence,
        "valid": valid,
        "validation_errors": [],
    }


class DocumentProcessorTests(unittest.TestCase):
    def _run_case(
        self,
        fields: list[dict],
        *,
        doc_type: str = "INE",
        critical_fields: dict[str, list[str]] | None = None,
        ocr_text: str = "texto ocr",
        options: str | None = None,
    ):
        fake_file = SimpleNamespace(filename="doc.png")
        with patch.object(dp, "CRITICAL_FIELDS", critical_fields or {"INE": ["curp", "nombre"]}):
            with patch("app.services.document_processor.preprocess", AsyncMock(return_value=([object()], ""))):
                with patch("app.services.document_processor.run_ocr", AsyncMock(return_value=(ocr_text, []))):
                    with patch("app.services.document_processor.classify_document", AsyncMock(return_value=(doc_type, 0.9))):
                        with patch("app.services.document_processor.extract_fields", AsyncMock(return_value=fields)):
                            with patch("app.services.document_processor.validate_fields", AsyncMock(side_effect=lambda x: x)):
                                with patch("app.services.document_processor.learn_from_processed_document") as learn_mock:
                                    response = asyncio.run(
                                        dp.process_document(fake_file, "doc-1", "upload", options)
                                    )
                                    return response, learn_mock

    def test_process_document_ready_when_all_critical_fields_are_valid(self):
        response, learn_mock = self._run_case(
            [
                _field("curp", "AACD900101HDFRRL09"),
                _field("nombre", "JUAN PEREZ"),
            ]
        )

        self.assertEqual(response.status, "READY")
        self.assertEqual(learn_mock.call_count, 1)
        self.assertNotIn("Campos críticos faltantes", " ".join(response.warnings))
        self.assertNotIn("Campos críticos inválidos", " ".join(response.warnings))

    def test_process_document_needs_review_when_critical_field_is_missing(self):
        response, learn_mock = self._run_case([_field("curp", "AACD900101HDFRRL09")])

        self.assertEqual(response.status, "NEEDS_REVIEW")
        self.assertEqual(learn_mock.call_count, 1)
        self.assertIn("Campos críticos faltantes: nombre", response.warnings)

    def test_process_document_needs_review_when_critical_field_is_invalid(self):
        response, learn_mock = self._run_case(
            [
                _field("curp", "AACD900101HDFRRL09"),
                _field("nombre", "XX", valid=False),
            ]
        )

        self.assertEqual(response.status, "NEEDS_REVIEW")
        self.assertEqual(learn_mock.call_count, 1)
        self.assertIn("Campos críticos inválidos: nombre", response.warnings)

    def test_process_document_warns_when_ocr_text_is_empty(self):
        response, learn_mock = self._run_case([], ocr_text="")

        self.assertEqual(response.status, "NEEDS_REVIEW")
        self.assertEqual(learn_mock.call_count, 1)
        self.assertIn("No se detectó texto. Verifica OCR o la calidad del documento.", response.warnings)
        self.assertIn("No se detectaron campos extraídos.", response.warnings)

    def test_process_document_ready_when_acta_uses_fecha_alias(self):
        response, learn_mock = self._run_case(
            [
                _field("nombre", "JUAN PEREZ"),
                _field("fecha", "01/01/2000"),
                _field("folio", "1234"),
                _field("numero_acta", "5678"),
            ],
            doc_type="ACTA_NACIMIENTO",
            critical_fields={"ACTA_NACIMIENTO": ["nombre", "fecha_nacimiento", "folio", "numero_acta"]},
        )

        self.assertEqual(response.status, "READY")
        self.assertEqual(learn_mock.call_count, 1)
        self.assertNotIn("Campos críticos faltantes", " ".join(response.warnings))

    def test_process_document_ready_when_nss_uses_titular_alias(self):
        response, learn_mock = self._run_case(
            [
                _field("nss", "12345678901"),
                _field("titular", "JUAN PEREZ"),
            ],
            doc_type="NSS",
            critical_fields={"NSS": ["nss", "nombre"]},
        )

        self.assertEqual(response.status, "READY")
        self.assertEqual(learn_mock.call_count, 1)
        self.assertNotIn("Campos críticos faltantes", " ".join(response.warnings))

    def test_process_document_ready_when_acta_folio_is_semantically_valid(self):
        response, learn_mock = self._run_case(
            [
                _field("nombre", "JUAN PEREZ"),
                _field("fecha_nacimiento", "01/01/2000"),
                _field("folio", "437", valid=False),
                _field("numero_acta", "3"),
            ],
            doc_type="ACTA_NACIMIENTO",
            critical_fields={"ACTA_NACIMIENTO": ["nombre", "fecha_nacimiento", "folio", "numero_acta"]},
        )

        self.assertEqual(response.status, "READY")
        self.assertEqual(learn_mock.call_count, 1)
        self.assertNotIn("Campos críticos inválidos", " ".join(response.warnings))

    def test_process_document_uses_forced_document_type(self):
        response, learn_mock = self._run_case(
            [_field("tabla_celdas", '{"rows":[["cuenta","importe"],["123","100.00"]]}')],
            doc_type="INE",
            critical_fields={"FACTURA": ["tabla_celdas"]},
            options='{"force_document_type":"FACTURA"}',
        )

        self.assertEqual(response.document_type, "FACTURA")
        self.assertEqual(response.status, "READY")
        self.assertEqual(learn_mock.call_count, 1)
        self.assertIn("Tipo forzado manualmente: FACTURA.", response.warnings)


if __name__ == "__main__":
    unittest.main()
