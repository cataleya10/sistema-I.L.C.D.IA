import os
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from app.services.online_learning import learn_from_processed_document, get_online_learning_stats


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


if __name__ == "__main__":
    unittest.main()
