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
    def _run_case(self, fields: list[dict], *, ocr_text: str = "texto ocr"):
        fake_file = SimpleNamespace(filename="doc.png")
        with patch.object(dp, "CRITICAL_FIELDS", {"INE": ["curp", "nombre"]}):
            with patch("app.services.document_processor.preprocess", AsyncMock(return_value=([object()], ""))):
                with patch("app.services.document_processor.run_ocr", AsyncMock(return_value=(ocr_text, []))):
                    with patch("app.services.document_processor.classify_document", AsyncMock(return_value=("INE", 0.9))):
                        with patch("app.services.document_processor.extract_fields", AsyncMock(return_value=fields)):
                            with patch("app.services.document_processor.validate_fields", AsyncMock(side_effect=lambda x: x)):
                                return asyncio.run(
                                    dp.process_document(fake_file, "doc-1", "upload", None)
                                )

    def test_process_document_ready_when_all_critical_fields_are_valid(self):
        response = self._run_case(
            [
                _field("curp", "AACD900101HDFRRL09"),
                _field("nombre", "JUAN PEREZ"),
            ]
        )

        self.assertEqual(response.status, "READY")
        self.assertNotIn("Campos críticos faltantes", " ".join(response.warnings))
        self.assertNotIn("Campos críticos inválidos", " ".join(response.warnings))

    def test_process_document_needs_review_when_critical_field_is_missing(self):
        response = self._run_case([_field("curp", "AACD900101HDFRRL09")])

        self.assertEqual(response.status, "NEEDS_REVIEW")
        self.assertIn("Campos críticos faltantes: nombre", response.warnings)

    def test_process_document_needs_review_when_critical_field_is_invalid(self):
        response = self._run_case(
            [
                _field("curp", "AACD900101HDFRRL09"),
                _field("nombre", "XX", valid=False),
            ]
        )

        self.assertEqual(response.status, "NEEDS_REVIEW")
        self.assertIn("Campos críticos inválidos: nombre", response.warnings)

    def test_process_document_warns_when_ocr_text_is_empty(self):
        response = self._run_case([], ocr_text="")

        self.assertEqual(response.status, "NEEDS_REVIEW")
        self.assertIn("No se detectó texto. Verifica OCR o la calidad del documento.", response.warnings)
        self.assertIn("No se detectaron campos extraídos.", response.warnings)


if __name__ == "__main__":
    unittest.main()
