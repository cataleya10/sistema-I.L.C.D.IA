import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

from app.services.document_processor import process_document


@dataclass
class LocalUploadFile:
    filename: str
    content_type: str
    _data: bytes

    async def read(self) -> bytes:
        return self._data


def guess_content_type(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return "application/pdf"
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    return "application/octet-stream"


def load_labels(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


async def process_one(doc: dict[str, Any], docs_path: str) -> dict[str, Any] | None:
    filename = doc["filename"]
    file_path = os.path.join(docs_path, filename)
    if not os.path.exists(file_path):
        print(f"Missing file: {file_path}")
        return None

    with open(file_path, "rb") as f:
        data = f.read()

    upload = LocalUploadFile(
        filename=filename,
        content_type=guess_content_type(filename),
        _data=data,
    )

    response = await process_document(
        upload,
        document_id=str(doc["document_id"]),
        source="local",
        options=json.dumps({"return_ocr_text": True, "return_boxes": True}),
    )

    return {
        "document_id": doc["document_id"],
        "filename": filename,
        "document_type": doc["document_type"],
        "labels": doc.get("fields", {}),
        "prediction": {
            "document_type": response.document_type,
            "confidence": response.confidence,
            "fields": [field.model_dump() for field in response.fields],
            "warnings": response.warnings,
        },
        "ocr": {
            "text": response.ocr_text,
            "boxes": response.ocr_boxes,
        },
    }


async def main():
    labels_path = os.environ.get("LABELS_JSON", r"C:\Users\100156643\Documents\IA\labels_prefilled.json")
    docs_path = os.environ.get("DOCS_PATH", r"C:\Users\100156643\Documents\IA")
    output_path = os.environ.get("OUTPUT_JSONL", r"C:\Users\100156643\Documents\IA\training_dataset.jsonl")

    labels = load_labels(labels_path)

    results = []
    for doc in labels:
        print(f"Processing {doc['filename']}...")
        result = await process_one(doc, docs_path)
        if result:
            results.append(result)

    with open(output_path, "w", encoding="utf-8") as f:
        for item in results:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"Dataset saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
