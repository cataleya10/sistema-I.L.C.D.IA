import json
import os
import re
from typing import Any

STRUCTURED_FIELDS = {"tabla_celdas"}


def load_labels(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_value(value: str, key: str) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    if key in {"curp", "rfc", "nss", "clabe", "cuenta", "seccion"}:
        normalized = re.sub(r"[^A-Z0-9]", "", text)
        if key == "seccion":
            return normalized.lstrip("0") or "0"
        return normalized
    if key in {"cp"}:
        return re.sub(r"\D", "", text)
    if key in {"sexo"}:
        if "HOMBRE" in text or "MASCULINO" in text or text.startswith("H"):
            return "H"
        if "MUJER" in text or "FEMENINO" in text or text.startswith("M"):
            return "M"
        return text[:1]
    if key in {"fecha_nacimiento", "fecha_registro", "fecha_corte", "fecha_limite"}:
        text = text.replace("-", "/")
        return re.sub(r"\s+", " ", text)
    if key in {"total"}:
        numeric = re.sub(r"[^0-9.,]", "", text)
        numeric = numeric.replace(",", "")
        return numeric
    if key in {"nombre", "titular", "domicilio", "referencia"}:
        return re.sub(r"[^A-Z0-9]", "", text)
    if key in {"proveedor", "banco", "regimen", "entidad_nacimiento", "entidad_registro", "municipio_registro", "lugar_nacimiento"}:
        return re.sub(r"\s+", " ", text)
    return re.sub(r"\s+", " ", text)


def fields_to_map(fields: list[dict[str, Any]]) -> dict[str, str]:
    result = {}
    for field in fields or []:
        key = field.get("key")
        value = field.get("value")
        if key and value is not None:
            result[key] = str(value)
    return result


def _normalize_cell(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"\s+", " ", text)
    text = text.replace("\u00a0", " ")
    return text


def _parse_json_object(raw_value: str) -> dict[str, Any] | None:
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    if not text.startswith("{"):
        return None
    try:
        data = json.loads(text)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _extract_table_rows(payload: dict[str, Any] | None) -> list[list[str]]:
    if not payload:
        return []
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return []
    normalized: list[list[str]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        normalized.append([_normalize_cell(cell) for cell in row])
    return normalized


def _table_score(expected_rows: list[list[str]], predicted_rows: list[list[str]]) -> tuple[float, bool, dict[str, int]]:
    expected_cell_total = sum(len(row) for row in expected_rows)
    if expected_cell_total == 0:
        exact = len(predicted_rows) == 0
        return (1.0 if exact else 0.0), exact, {
            "expected_rows": len(expected_rows),
            "predicted_rows": len(predicted_rows),
            "expected_cells": 0,
            "matched_cells": 0,
        }

    matched_cells = 0
    for row_idx, expected_row in enumerate(expected_rows):
        predicted_row = predicted_rows[row_idx] if row_idx < len(predicted_rows) else []
        for col_idx, expected_cell in enumerate(expected_row):
            predicted_cell = predicted_row[col_idx] if col_idx < len(predicted_row) else ""
            if expected_cell == predicted_cell:
                matched_cells += 1

    score = matched_cells / expected_cell_total
    exact = expected_rows == predicted_rows
    return score, exact, {
        "expected_rows": len(expected_rows),
        "predicted_rows": len(predicted_rows),
        "expected_cells": expected_cell_total,
        "matched_cells": matched_cells,
    }


def compare_field(key: str, expected: Any, predicted: Any) -> tuple[bool, float, dict[str, Any]]:
    if key in STRUCTURED_FIELDS:
        expected_payload = _parse_json_object(str(expected or ""))
        predicted_payload = _parse_json_object(str(predicted or ""))
        expected_rows = _extract_table_rows(expected_payload)
        predicted_rows = _extract_table_rows(predicted_payload)
        if expected_rows:
            score, exact, metrics = _table_score(expected_rows, predicted_rows)
            return exact, score, metrics

    exp_norm = normalize_value(str(expected or ""), key)
    pred_norm = normalize_value(str(predicted or ""), key)
    ok = exp_norm == pred_norm and exp_norm != ""
    if not ok and key in {"banco", "proveedor"} and "," in exp_norm:
        options = [normalize_value(opt, key) for opt in exp_norm.split(",")]
        ok = pred_norm in options
    return ok, (1.0 if ok else 0.0), {}


def evaluate(labels_path: str, dataset_path: str) -> dict[str, Any]:
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = [json.loads(line) for line in f if line.strip()]

    label_docs = {doc["document_id"]: doc for doc in load_labels(labels_path)}

    totals = {}
    correct = {}
    score_totals = {}
    per_doc = []

    for item in dataset:
        doc_id = item["document_id"]
        label_doc = label_docs.get(doc_id)
        if not label_doc:
            continue
        label_fields = label_doc.get("fields", {})
        pred_fields = fields_to_map(item.get("prediction", {}).get("fields", []))

        doc_stats = {"document_id": doc_id, "filename": item.get("filename"), "fields": []}

        for key, expected in label_fields.items():
            if expected is None or str(expected).strip() == "":
                continue
            totals[key] = totals.get(key, 0) + 1
            pred = pred_fields.get(key, "")
            ok, score, metrics = compare_field(key, expected, pred)
            if ok:
                correct[key] = correct.get(key, 0) + 1
            score_totals[key] = score_totals.get(key, 0.0) + score
            doc_stats["fields"].append({
                "key": key,
                "expected": expected,
                "predicted": pred,
                "ok": ok,
                "score": round(score, 6),
                "metrics": metrics,
            })

        per_doc.append(doc_stats)

    summary = []
    for key in sorted(totals.keys()):
        total = totals[key]
        ok = correct.get(key, 0)
        avg_score = score_totals.get(key, 0.0) / total if total else 0.0
        acc = ok / total if total else 0
        summary.append(
            {
                "field": key,
                "accuracy": acc,
                "average_score": avg_score,
                "correct": ok,
                "total": total,
            }
        )

    return {"summary": summary, "per_doc": per_doc}


def main():
    labels_path = os.environ.get("LABELS_JSON", r"C:\Users\100156643\Documents\IA\labels_prefilled.json")
    dataset_path = os.environ.get("DATASET_JSONL", r"C:\Users\100156643\Documents\IA\training_dataset.jsonl")
    output_path = os.environ.get("REPORT_JSON", r"C:\Users\100156643\Documents\IA\evaluation_report.json")

    report = evaluate(labels_path, dataset_path)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"Report saved to {output_path}")


if __name__ == "__main__":
    main()
