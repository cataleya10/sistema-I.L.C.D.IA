import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.services.document_audit import audit_folder


class DocumentAuditTests(unittest.TestCase):
    def test_audit_folder_summarizes_clean_issue_and_error_documents(self):
        folder = Path(__file__).resolve().parent
        files = [folder / "clean.pdf", folder / "issue.pdf", folder / "broken.pdf"]

        async def fake_inspect(file_path: Path):
            name = Path(file_path).name
            if name == "clean.pdf":
                return {
                    "file_path": str(file_path),
                    "pipeline": {"doc_type": "FACTURA", "doc_confidence": 0.95},
                    "tabla_celdas": {"canonical_row_count": 3, "mapped_fields": {"banco": "BBVA"}},
                    "pago_detalle": {"canonical_row_count": 3},
                    "payroll_strict": {"warnings": [], "hard_fail": False},
                }
            if name == "issue.pdf":
                return {
                    "file_path": str(file_path),
                    "pipeline": {"doc_type": "GENERICO", "doc_confidence": 0.5},
                    "tabla_celdas": {"canonical_row_count": 0, "validation_warnings": ["warning 1"]},
                    "pago_detalle": {"canonical_row_count": 0},
                    "payroll_strict": {"warnings": [], "hard_fail": True},
                }
            raise RuntimeError("boom")

        with patch("app.services.document_audit._iter_audit_files", return_value=files):
            with patch(
                "app.services.document_audit.inspect_document",
                new=AsyncMock(side_effect=fake_inspect),
            ):
                result = asyncio.run(audit_folder(folder, recurse=False, limit=10, issues_only=False))

        self.assertEqual(result["matched_files"], 3)
        self.assertEqual(result["processed_files"], 3)
        self.assertEqual(result["clean_count"], 1)
        self.assertEqual(result["issue_count"], 1)
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["hard_fail_count"], 1)
        self.assertEqual(result["non_factura_count"], 1)
        self.assertEqual(result["document_type_counts"], {"FACTURA": 1, "GENERICO": 1})
        self.assertEqual(len(result["documents"]), 3)

    def test_audit_folder_can_return_only_issues(self):
        folder = Path(__file__).resolve().parent
        files = [folder / "clean.pdf", folder / "issue.pdf"]

        async def fake_inspect(file_path: Path):
            name = Path(file_path).name
            if name == "clean.pdf":
                return {
                    "file_path": str(file_path),
                    "pipeline": {"doc_type": "FACTURA", "doc_confidence": 0.95},
                    "tabla_celdas": {"canonical_row_count": 1},
                    "pago_detalle": {"canonical_row_count": 1},
                    "payroll_strict": {"warnings": [], "hard_fail": False},
                }
            return {
                "file_path": str(file_path),
                "pipeline": {"doc_type": "FACTURA", "doc_confidence": 0.8},
                "tabla_celdas": {"canonical_row_count": 1, "validation_warnings": ["warning 1"]},
                "pago_detalle": {"canonical_row_count": 1},
                "payroll_strict": {"warnings": [], "hard_fail": False},
            }

        with patch("app.services.document_audit._iter_audit_files", return_value=files):
            with patch(
                "app.services.document_audit.inspect_document",
                new=AsyncMock(side_effect=fake_inspect),
            ):
                result = asyncio.run(audit_folder(folder, recurse=False, limit=10, issues_only=True))

        self.assertEqual(result["documents_returned"], 1)
        self.assertEqual(result["documents"][0]["name"], "issue.pdf")


if __name__ == "__main__":
    unittest.main()
