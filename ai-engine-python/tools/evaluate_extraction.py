import json
import os
import re
from typing import Any


def load_labels(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_value(value: str, key: str) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    if key in {"curp", "rfc", "nss", "clabe", "cuenta", "seccion"}:
        return re.sub(r"[^A-Z0-9]", "", text)
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
        if key and value:
            result[key] = str(value)
    return result


def evaluate(labels_path: str, dataset_path: str) -> dict[str, Any]:
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = [json.loads(line) for line in f if line.strip()]

    label_docs = {doc["document_id"]: doc for doc in load_labels(labels_path)}

    totals = {}
    correct = {}
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
            exp_norm = normalize_value(expected, key)
            pred_norm = normalize_value(pred, key)
            ok = exp_norm == pred_norm and exp_norm != ""
            if not ok and key in {"banco", "proveedor"} and "," in exp_norm:
                options = [normalize_value(opt, key) for opt in exp_norm.split(",")]
                ok = pred_norm in options
            if ok:
                correct[key] = correct.get(key, 0) + 1
            doc_stats["fields"].append({
                "key": key,
                "expected": expected,
                "predicted": pred,
                "ok": ok
            })

        per_doc.append(doc_stats)

    summary = []
    for key in sorted(totals.keys()):
        total = totals[key]
        ok = correct.get(key, 0)
        acc = ok / total if total else 0
        summary.append({"field": key, "accuracy": acc, "correct": ok, "total": total})

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
