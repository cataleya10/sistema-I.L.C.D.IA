import json
import tempfile
import unittest
from pathlib import Path

from tools.evaluate_extraction import evaluate


def _write_temp_json(content) -> str:
    tmp = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".json")
    with tmp as handle:
        json.dump(content, handle, ensure_ascii=False)
    return tmp.name


def _write_temp_jsonl(rows: list[dict]) -> str:
    tmp = tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".jsonl")
    with tmp as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return tmp.name


class EvaluateExtractionTests(unittest.TestCase):
    def tearDown(self) -> None:
        for path in getattr(self, "_temp_paths", []):
            Path(path).unlink(missing_ok=True)

    def _track(self, *paths: str) -> None:
        if not hasattr(self, "_temp_paths"):
            self._temp_paths = []
        self._temp_paths.extend(paths)

    def test_evaluate_tablaceldas_exact_match_counts_as_full_score(self):
        expected_table = {"rows": [["CUENTA", "IMPORTE"], ["123", "$100.00"]]}
        predicted_table = {"rows": [["cuenta", "importe"], ["123", "$100.00"]]}

        labels_path = _write_temp_json(
            [{"document_id": "doc-1", "fields": {"tabla_celdas": json.dumps(expected_table, ensure_ascii=False)}}]
        )
        dataset_path = _write_temp_jsonl(
            [
                {
                    "document_id": "doc-1",
                    "prediction": {"fields": [{"key": "tabla_celdas", "value": json.dumps(predicted_table, ensure_ascii=False)}]},
                }
            ]
        )
        self._track(labels_path, dataset_path)

        report = evaluate(labels_path, dataset_path)
        summary = {item["field"]: item for item in report["summary"]}
        self.assertEqual(summary["tabla_celdas"]["accuracy"], 1.0)
        self.assertEqual(summary["tabla_celdas"]["average_score"], 1.0)

    def test_evaluate_tablaceldas_partial_match_sets_partial_score(self):
        expected_table = {"rows": [["CUENTA", "IMPORTE"], ["123", "$100.00"]]}
        predicted_table = {"rows": [["CUENTA", "IMPORTE"], ["123", "$999.00"]]}

        labels_path = _write_temp_json(
            [{"document_id": "doc-2", "fields": {"tabla_celdas": json.dumps(expected_table, ensure_ascii=False)}}]
        )
        dataset_path = _write_temp_jsonl(
            [
                {
                    "document_id": "doc-2",
                    "prediction": {"fields": [{"key": "tabla_celdas", "value": json.dumps(predicted_table, ensure_ascii=False)}]},
                }
            ]
        )
        self._track(labels_path, dataset_path)

        report = evaluate(labels_path, dataset_path)
        summary = {item["field"]: item for item in report["summary"]}
        per_doc = report["per_doc"][0]["fields"][0]

        self.assertEqual(summary["tabla_celdas"]["accuracy"], 0.0)
        self.assertEqual(summary["tabla_celdas"]["average_score"], 0.75)
        self.assertEqual(per_doc["ok"], False)
        self.assertEqual(per_doc["metrics"]["matched_cells"], 3)
        self.assertEqual(per_doc["metrics"]["expected_cells"], 4)


if __name__ == "__main__":
    unittest.main()
