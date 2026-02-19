import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.pipelines.extract import extract_fields  # noqa: E402


def _load_jsonl(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _pick_doc_type(item: dict[str, Any]) -> str:
    prediction = item.get("prediction") if isinstance(item.get("prediction"), dict) else {}
    pred_type = str(prediction.get("document_type") or "").strip().upper()
    if pred_type:
        return pred_type
    base_type = str(item.get("document_type") or "").strip().upper()
    return base_type or "UNKNOWN"


async def _replay_item(item: dict[str, Any]) -> dict[str, Any]:
    ocr = item.get("ocr") if isinstance(item.get("ocr"), dict) else {}
    ocr_text = str(ocr.get("text") or "")
    ocr_boxes = ocr.get("boxes")
    if not isinstance(ocr_boxes, list):
        ocr_boxes = []

    doc_type = _pick_doc_type(item)
    filename = str(item.get("filename") or "")
    fields = await extract_fields(doc_type, ocr_text, ocr_boxes, raw_text=ocr_text, filename=filename)
    prediction = item.get("prediction") if isinstance(item.get("prediction"), dict) else {}

    out = dict(item)
    out["prediction"] = {
        "document_type": doc_type,
        "confidence": prediction.get("confidence", 0.0),
        "fields": fields,
        "warnings": prediction.get("warnings", []),
    }
    return out


async def _run(dataset_path: str, output_path: str) -> None:
    rows = _load_jsonl(dataset_path)
    replayed: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        replayed.append(await _replay_item(row))
        if idx % 25 == 0:
            print(f"Processed {idx}/{len(rows)}")

    with open(output_path, "w", encoding="utf-8") as f:
        for row in replayed:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Replay dataset saved to {output_path}")


def main() -> None:
    dataset_path = os.environ.get("DATASET_JSONL", r"C:\Users\100156643\Documents\IA\training_dataset.jsonl")
    output_path = os.environ.get(
        "OUTPUT_JSONL",
        str(ROOT / "training_dataset_replayed.jsonl"),
    )
    asyncio.run(_run(dataset_path, output_path))


if __name__ == "__main__":
    main()
