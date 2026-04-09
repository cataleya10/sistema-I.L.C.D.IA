import unittest
import asyncio
import os
from pathlib import Path
from unittest.mock import patch

from app.api.routes import (
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


if __name__ == "__main__":
    unittest.main()
