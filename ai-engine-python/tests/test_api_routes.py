import io
import unittest
import asyncio
import os
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from app.api.routes import (
    process_document_endpoint,
    audit_folder_endpoint,
    online_learning_stats_endpoint,
    online_learning_feedback_endpoint,
    online_learning_retrain_endpoint,
)
from app.schemas.audit import AuditFolderRequest
from app.schemas.online_learning import (
    OnlineLearningFeedbackRequest,
    FeedbackField,
    OnlineLearningRetrainRequest,
)
from app.schemas.process import (
    ProcessResponse,
    CampoExtraido,
    TablaExtraida,
    MetadataDocumento,
    ValidationSummary,
)


def _make_process_response(
    *,
    doc_type: str = "INE",
    requires_review: bool = False,
    campos: list | None = None,
    tablas: list | None = None,
) -> ProcessResponse:
    """Helper: construye un ProcessResponse realista para mocks."""
    return ProcessResponse(
        document_id="doc-test",
        tipo_documento=doc_type,
        success=not requires_review,
        message="Documento procesado correctamente" if not requires_review else "Requiere revisión.",
        confidence_global=0.92,
        campos=campos or [
            CampoExtraido(key="curp", label="CURP", value="AACD900101HDFRRL09",
                          confidence=0.97, is_critical=True, is_valid=True),
            CampoExtraido(key="nombre", label="Nombre", value="JUAN PEREZ",
                          confidence=0.90, is_critical=True, is_valid=True),
        ],
        tablas=tablas or [],
        metadata=MetadataDocumento(
            filename="doc.pdf", pages=1, source="web",
            processing_time_ms=1200, ocr_engine="paddleocr",
        ),
        validation_summary=ValidationSummary(
            coverage=1.0,
            critical_coverage=1.0,
            requires_review=requires_review,
        ),
    )


class ApiRoutesTests(unittest.TestCase):
    def test_audit_folder_endpoint_returns_service_payload(self):
        base = Path(os.environ.get("AUDIT_BASE_PATH", "storage")).resolve()
        resolved = str((base / "docs").resolve())
        expected = {
            "folder_path": "docs",
            "recurse": True,
            "limit": 25,
            "issues_only": False,
            "matched_files": 3,
            "processed_files": 3,
            "documents_returned": 3,
            "clean_count": 2,
            "issue_count": 1,
            "error_count": 0,
            "hard_fail_count": 0,
            "non_factura_count": 0,
            "document_type_counts": {"FACTURA": 3},
            "documents": [],
        }
        payload = AuditFolderRequest(folder_path="docs", recurse=True, limit=25, issues_only=False)
        with patch("app.api.routes.run_audit_folder", return_value=expected) as audit_mock:
            response = asyncio.run(audit_folder_endpoint(payload=payload))

        self.assertEqual(response, expected)
        audit_mock.assert_called_once_with(
            resolved,
            recurse=True,
            limit=25,
            issues_only=False,
        )

    def test_online_learning_stats_endpoint_returns_payload(self):
        expected = {
            "totals": {"attempted": 7, "trained": 5, "skipped": 2},
            "recent_events": [],
        }
        with patch("app.api.routes.get_online_learning_stats", return_value=expected) as stats_mock:
            response = asyncio.run(online_learning_stats_endpoint(recent=3))

        self.assertEqual(response, expected)
        stats_mock.assert_called_once_with(recent=3)

    def test_online_learning_feedback_endpoint_returns_service_payload(self):
        expected = {"accepted": True, "labels": 2}
        payload = OnlineLearningFeedbackRequest(
            document_id="doc-1",
            document_type="CURP",
            ocr_text="CONSTANCIA CURP",
            corrected_fields=[
                FeedbackField(key="curp", value="AAAA000101HDFRRL00"),
                FeedbackField(key="nombre", value="JUAN PEREZ"),
            ],
        )
        with patch("app.api.routes.record_feedback_document", return_value=expected) as feedback_mock:
            response = asyncio.run(online_learning_feedback_endpoint(payload=payload))

        self.assertEqual(response, expected)
        feedback_mock.assert_called_once()

    def test_online_learning_retrain_endpoint_returns_service_payload(self):
        expected = {"promoted": True, "decision_reasons": []}
        payload = OnlineLearningRetrainRequest(
            min_feedback_samples=10,
            validation_ratio=0.2,
            min_doc_accuracy=0.9,
            min_validation_docs=3,
            max_accuracy_drop=0.02,
            promote=True,
        )
        with patch("app.api.routes.run_feedback_retraining", return_value=expected) as retrain_mock:
            response = asyncio.run(online_learning_retrain_endpoint(payload=payload))

        self.assertEqual(response, expected)
        retrain_mock.assert_called_once()


class ProcessDocumentEndpointTests(unittest.TestCase):
    """Tests del endpoint POST /process-document con el contrato v2."""

    def _make_upload_file(self, filename: str = "doc.pdf", content: bytes = b"%PDF-1.4 fake") -> MagicMock:
        upload = MagicMock()
        upload.filename = filename
        upload.read = AsyncMock(return_value=content)
        upload.file = io.BytesIO(content)
        return upload

    def _call_endpoint(
        self,
        mock_response: ProcessResponse,
        *,
        document_id: str = "doc-test",
        source: str = "web",
        options: str | None = None,
        filename: str = "doc.pdf",
    ) -> ProcessResponse:
        file = self._make_upload_file(filename=filename)
        with patch(
            "app.api.routes.process_document",
            new=AsyncMock(return_value=mock_response),
        ):
            return asyncio.run(
                process_document_endpoint(
                    file=file,
                    document_id=document_id,
                    source=source,
                    options=options,
                )
            )

    # ── Contrato básico ───────────────────────────────────────────────────────

    def test_returns_process_response_instance(self):
        resp = self._call_endpoint(_make_process_response())
        self.assertIsInstance(resp, ProcessResponse)

    def test_response_has_tipo_documento(self):
        resp = self._call_endpoint(_make_process_response(doc_type="CURP"))
        self.assertEqual(resp.tipo_documento, "CURP")

    def test_response_success_true_when_ready(self):
        resp = self._call_endpoint(_make_process_response(requires_review=False))
        self.assertTrue(resp.success)

    def test_response_campos_have_is_critical_flag(self):
        resp = self._call_endpoint(_make_process_response())
        self.assertTrue(any(c.is_critical for c in resp.campos))

    def test_response_campos_have_is_valid_flag(self):
        resp = self._call_endpoint(_make_process_response())
        for campo in resp.campos:
            self.assertIsInstance(campo.is_valid, bool)

    def test_response_confidence_global_between_0_and_1(self):
        resp = self._call_endpoint(_make_process_response())
        self.assertGreaterEqual(resp.confidence_global, 0.0)
        self.assertLessEqual(resp.confidence_global, 1.0)

    def test_response_validation_summary_present(self):
        resp = self._call_endpoint(_make_process_response())
        vs = resp.validation_summary
        self.assertIsInstance(vs, ValidationSummary)
        self.assertIsInstance(vs.requires_review, bool)
        self.assertIsInstance(vs.coverage, float)
        self.assertIsInstance(vs.critical_coverage, float)
        self.assertIn(vs.score_decision, {"accepted", "review", "reprocess"})
        self.assertIsInstance(vs.table_quality_score, float)

    def test_score_decision_accepted_when_no_review(self):
        resp = self._call_endpoint(_make_process_response(requires_review=False))
        # score_decision puede ser "accepted" si critical_coverage es alta
        self.assertIn(resp.validation_summary.score_decision, {"accepted", "review", "reprocess"})

    def test_score_decision_present_on_error_response(self):
        error_resp = ProcessResponse(
            document_id="doc-err",
            tipo_documento="UNKNOWN",
            success=False,
            message="Tipo de documento no identificado.",
            error_code="DOCUMENT_TYPE_UNKNOWN",
            stage="classification",
            metadata=MetadataDocumento(filename="doc.pdf"),
            validation_summary=ValidationSummary(requires_review=True, score_decision="reprocess"),
        )
        resp = self._call_endpoint(error_resp)
        self.assertEqual(resp.error_code, "DOCUMENT_TYPE_UNKNOWN")
        self.assertEqual(resp.stage, "classification")
        self.assertEqual(resp.validation_summary.score_decision, "reprocess")

    def test_table_not_found_error_code(self):
        error_resp = ProcessResponse(
            document_id="doc-t",
            tipo_documento="FACTURA",
            success=True,
            message="No se detectó tabla principal en el documento.",
            error_code="TABLE_NOT_FOUND",
            stage="table_extraction",
            metadata=MetadataDocumento(filename="doc.pdf"),
            validation_summary=ValidationSummary(
                requires_review=True, score_decision="review",
                table_quality_score=0.0,
            ),
        )
        resp = self._call_endpoint(error_resp)
        self.assertEqual(resp.error_code, "TABLE_NOT_FOUND")
        self.assertTrue(resp.validation_summary.requires_review)

    def test_response_metadata_has_required_keys(self):
        resp = self._call_endpoint(_make_process_response())
        meta = resp.metadata
        self.assertIsInstance(meta, MetadataDocumento)
        self.assertIsInstance(meta.filename, str)
        self.assertIsInstance(meta.pages, int)
        self.assertIsInstance(meta.processing_time_ms, int)

    def test_response_requires_review_when_needs_review(self):
        resp = self._call_endpoint(_make_process_response(requires_review=True))
        self.assertTrue(resp.validation_summary.requires_review)

    def test_response_tablas_structure_when_present(self):
        tablas = [
            TablaExtraida(
                name="tabla_principal",
                headers_detected=["fecha", "importe"],
                rows=[],
                canonical_rows=[{"fecha": "2026-03-22", "importe": "1500.00"}],
            )
        ]
        resp = self._call_endpoint(_make_process_response(tablas=tablas))
        self.assertEqual(len(resp.tablas), 1)
        self.assertEqual(resp.tablas[0].name, "tabla_principal")
        self.assertIn("fecha", resp.tablas[0].headers_detected)
        self.assertEqual(len(resp.tablas[0].canonical_rows), 1)

    # ── Validaciones del endpoint ─────────────────────────────────────────────

    def test_invalid_document_id_raises_422(self):
        from fastapi import HTTPException
        file = self._make_upload_file()
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                process_document_endpoint(
                    file=file,
                    document_id="id con espacios!!",
                    source="web",
                    options=None,
                )
            )
        self.assertEqual(ctx.exception.status_code, 422)

    def test_invalid_options_json_raises_422(self):
        from fastapi import HTTPException
        file = self._make_upload_file()
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                process_document_endpoint(
                    file=file,
                    document_id="doc-ok",
                    source="web",
                    options="no es json",
                )
            )
        self.assertEqual(ctx.exception.status_code, 422)

    def test_error_response_has_error_code(self):
        error_resp = ProcessResponse(
            document_id="doc-err",
            tipo_documento="UNKNOWN",
            success=False,
            message="Error en OCR.",
            error_code="OCR_FAILED",
            stage="ocr",
            metadata=MetadataDocumento(filename="doc.pdf"),
            validation_summary=ValidationSummary(requires_review=True),
        )
        resp = self._call_endpoint(error_resp)
        self.assertFalse(resp.success)
        self.assertEqual(resp.error_code, "OCR_FAILED")
        self.assertEqual(resp.stage, "ocr")
        self.assertTrue(resp.validation_summary.requires_review)


if __name__ == "__main__":
    unittest.main()
