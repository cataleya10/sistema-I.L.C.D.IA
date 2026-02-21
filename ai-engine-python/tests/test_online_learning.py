import json
import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app.services.online_learning import (
    learn_from_processed_document,
    get_online_learning_stats,
    record_feedback_document,
    run_feedback_retraining,
)


class OnlineLearningTests(unittest.TestCase):
    def test_learn_from_processed_document_updates_dataset_and_models(self):
        temp_dir = Path("reports") / f"online_learning_{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            dataset_path = temp_dir / "dataset.jsonl"
            model_path = temp_dir / "doc_type_nb.json"
            alias_path = temp_dir / "field_aliases.json"
            stats_path = temp_dir / "online_training_stats.json"

            with patch.dict(
                os.environ,
                {
                    "ONLINE_TRAINING_ENABLED": "1",
                    "ONLINE_TRAINING_DATASET_PATH": str(dataset_path),
                    "DOC_MODEL_PATH": str(model_path),
                    "FIELD_ALIAS_PATH": str(alias_path),
                    "ONLINE_TRAINING_STATS_PATH": str(stats_path),
                    "ONLINE_TRAINING_MIN_DOC_CONFIDENCE": "0.8",
                    "ONLINE_TRAINING_MIN_FIELD_CONFIDENCE": "0.8",
                },
                clear=False,
            ):
                result = learn_from_processed_document(
                    document_id="doc-1",
                    document_type="CURP",
                    status="READY",
                    confidence=0.9,
                    ocr_text=(
                        "CONSTANCIA DE LA CLAVE UNICA DE REGISTRO DE POBLACION\n"
                        "CURP AACD900101HDFRRL09\n"
                        "NOMBRE JUAN PEREZ LOPEZ\n"
                        "FECHA DE NACIMIENTO 01/01/1990\n"
                        "LUGAR DE NACIMIENTO TABASCO\n"
                        "NACIONALIDAD MEXICANA"
                    ),
                    fields=[
                        {
                            "key": "curp",
                            "value": "AACD900101HDFRRL09",
                            "confidence": 0.95,
                            "valid": True,
                        },
                        {
                            "key": "nombre",
                            "value": "JUAN PEREZ LOPEZ",
                            "confidence": 0.9,
                            "valid": True,
                        },
                    ],
                )
                stats = get_online_learning_stats(recent=5)

            self.assertTrue(result.get("trained"))
            self.assertTrue(dataset_path.exists())
            self.assertTrue(model_path.exists())
            self.assertTrue(alias_path.exists())
            self.assertTrue(stats_path.exists())
            self.assertFalse(stats_path.with_suffix(stats_path.suffix + ".tmp").exists())
            self.assertEqual(int(stats.get("totals", {}).get("attempted", 0)), 1)
            self.assertEqual(int(stats.get("totals", {}).get("trained", 0)), 1)
            self.assertEqual(int(stats.get("totals", {}).get("skipped", 0)), 0)
            self.assertEqual(int(stats.get("dataset_samples", 0)), 1)
            self.assertEqual(len(stats.get("recent_events", [])), 1)

            model_data = model_path.read_text(encoding="utf-8")
            alias_data = alias_path.read_text(encoding="utf-8")
            self.assertIn('"CURP"', model_data)
            self.assertIn('"curp"', alias_data)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_learn_from_processed_document_skips_needs_review(self):
        temp_dir = Path("reports") / f"online_learning_{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            dataset_path = temp_dir / "dataset.jsonl"
            model_path = temp_dir / "doc_type_nb.json"
            alias_path = temp_dir / "field_aliases.json"
            stats_path = temp_dir / "online_training_stats.json"

            with patch.dict(
                os.environ,
                {
                    "ONLINE_TRAINING_ENABLED": "1",
                    "ONLINE_TRAINING_DATASET_PATH": str(dataset_path),
                    "DOC_MODEL_PATH": str(model_path),
                    "FIELD_ALIAS_PATH": str(alias_path),
                    "ONLINE_TRAINING_STATS_PATH": str(stats_path),
                },
                clear=False,
            ):
                result = learn_from_processed_document(
                    document_id="doc-2",
                    document_type="INE",
                    status="NEEDS_REVIEW",
                    confidence=0.95,
                    ocr_text="INSTITUTO NACIONAL ELECTORAL",
                    fields=[{"key": "curp", "value": "AAAA000101HDFRRL00", "confidence": 0.99, "valid": True}],
                )
                stats = get_online_learning_stats(recent=5)

            self.assertFalse(result.get("trained"))
            self.assertEqual(result.get("reason"), "status_not_ready")
            self.assertFalse(dataset_path.exists())
            self.assertTrue(stats_path.exists())
            self.assertEqual(int(stats.get("totals", {}).get("attempted", 0)), 1)
            self.assertEqual(int(stats.get("totals", {}).get("trained", 0)), 0)
            self.assertEqual(int(stats.get("totals", {}).get("skipped", 0)), 1)
            self.assertEqual(
                int(stats.get("by_reason", {}).get("status_not_ready", 0)),
                1,
            )
            self.assertEqual(len(stats.get("recent_events", [])), 1)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_record_feedback_document_persists_human_labels(self):
        temp_dir = Path("reports") / f"online_feedback_{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            feedback_path = temp_dir / "feedback.jsonl"
            with patch.dict(
                os.environ,
                {
                    "ONLINE_FEEDBACK_DATASET_PATH": str(feedback_path),
                },
                clear=False,
            ):
                result = record_feedback_document(
                    document_id="doc-fb-1",
                    document_type="ACTA_NACIMIENTO",
                    ocr_text=(
                        "ACTA DE NACIMIENTO\n"
                        "NOMBRE JUAN PEREZ LOPEZ\n"
                        "FECHA DE NACIMIENTO 01/01/1990\n"
                        "REGISTRO CIVIL MEXICO"
                    ),
                    corrected_labels={"nombre": "JUAN PEREZ LOPEZ", "fecha_nacimiento": "01/01/1990"},
                    extracted_fields=[],
                    reviewer="qa_user",
                )

            self.assertTrue(result.get("accepted"))
            self.assertTrue(feedback_path.exists())
            lines = feedback_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertIn("JUAN PEREZ LOPEZ", lines[0])
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_run_feedback_retraining_promotes_model_when_metrics_pass(self):
        temp_dir = Path("reports") / f"online_retrain_{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            feedback_path = temp_dir / "feedback.jsonl"
            dataset_path = temp_dir / "dataset.jsonl"
            model_path = temp_dir / "doc_type_nb.json"
            alias_path = temp_dir / "field_aliases.json"
            report_path = temp_dir / "promotion_report.json"

            samples = [
                (
                    "CURP",
                    "CONSTANCIA DE LA CLAVE UNICA DE REGISTRO DE POBLACION CURP AACD900101HDFRRL09 NOMBRE JUAN PEREZ LOPEZ NACIONALIDAD MEXICANA",
                    {"curp": "AACD900101HDFRRL09", "nombre": "JUAN PEREZ LOPEZ"},
                ),
                (
                    "NSS",
                    "NUMERO DE SEGURIDAD SOCIAL IMSS NSS 12345678901 NOMBRE MARIA GARCIA HERNANDEZ CLINICA FAMILIAR",
                    {"nss": "12345678901", "nombre": "MARIA GARCIA HERNANDEZ"},
                ),
            ]

            with patch.dict(
                os.environ,
                {
                    "ONLINE_FEEDBACK_DATASET_PATH": str(feedback_path),
                    "ONLINE_TRAINING_DATASET_PATH": str(dataset_path),
                    "DOC_MODEL_PATH": str(model_path),
                    "FIELD_ALIAS_PATH": str(alias_path),
                    "ONLINE_PROMOTION_REPORT_PATH": str(report_path),
                    "ONLINE_RETRAIN_INCLUDE_AUTO": "0",
                },
                clear=False,
            ):
                for idx in range(10):
                    doc_type, text, labels = samples[idx % 2]
                    recorded = record_feedback_document(
                        document_id=f"doc-{idx}",
                        document_type=doc_type,
                        ocr_text=text,
                        corrected_labels=labels,
                        extracted_fields=[],
                        reviewer="qa",
                    )
                    self.assertTrue(recorded.get("accepted"))

                result = run_feedback_retraining(
                    min_feedback_samples=4,
                    validation_ratio=0.3,
                    min_doc_accuracy=0.6,
                    min_validation_docs=1,
                    max_accuracy_drop=0.5,
                    promote=True,
                )

            self.assertTrue(result.get("promoted"))
            self.assertTrue(model_path.exists())
            self.assertTrue(alias_path.exists())
            self.assertTrue(report_path.exists())
            model_data = model_path.read_text(encoding="utf-8")
            self.assertIn('"CURP"', model_data)
            self.assertIn('"NSS"', model_data)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_stats_loader_recovers_legacy_tmp_file(self):
        temp_dir = Path("reports") / f"online_stats_recover_{uuid.uuid4().hex}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            stats_path = temp_dir / "online_training_stats.json"
            legacy_tmp = stats_path.with_suffix(stats_path.suffix + ".tmp")
            legacy_tmp.write_text(
                json.dumps(
                    {
                        "updated_at_utc": "2026-02-21T00:00:00+00:00",
                        "dataset_samples": 3,
                        "totals": {"attempted": 5, "trained": 3, "skipped": 2},
                        "by_reason": {"trained": 3},
                        "by_document_type": {"FACTURA": {"attempted": 5, "trained": 3, "skipped": 2}},
                        "last_event": {"document_id": "legacy-1"},
                        "recent_events": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "ONLINE_TRAINING_STATS_PATH": str(stats_path),
                },
                clear=False,
            ):
                stats = get_online_learning_stats(recent=0)

            self.assertTrue(stats_path.exists())
            if legacy_tmp.exists():
                self.assertEqual(legacy_tmp.read_text(encoding="utf-8"), "")
            self.assertEqual(int(stats.get("dataset_samples", 0)), 3)
            self.assertEqual(int(stats.get("totals", {}).get("attempted", 0)), 5)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
