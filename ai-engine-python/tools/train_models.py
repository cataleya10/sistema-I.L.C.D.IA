import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from typing import Any


def load_jsonl(path: str) -> list[dict[str, Any]]:
    items = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def normalize_text(text: str) -> str:
    if text is None:
        return ""
    text = unicodedata.normalize("NFKD", str(text))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.upper()
    text = re.sub(r"[^A-Z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokenize(text: str) -> list[str]:
    text = normalize_text(text)
    return [tok for tok in text.split() if len(tok) > 1]


def train_nb(docs: list[dict[str, Any]]) -> dict[str, Any]:
    class_counts = Counter()
    token_counts = defaultdict(Counter)
    vocab = set()

    for item in docs:
        doc_type = item.get("document_type") or item.get("prediction", {}).get("document_type")
        if not doc_type:
            continue
        text = item.get("ocr", {}).get("text") or ""
        tokens = tokenize(text)
        if not tokens:
            continue
        class_counts[doc_type] += 1
        for tok in tokens:
            token_counts[doc_type][tok] += 1
            vocab.add(tok)

    model = {
        "classes": list(class_counts.keys()),
        "class_counts": dict(class_counts),
        "token_counts": {cls: dict(cnts) for cls, cnts in token_counts.items()},
        "vocab": sorted(vocab),
        "total_docs": sum(class_counts.values()),
    }
    return model


def find_aliases(docs: list[dict[str, Any]]) -> dict[str, list[str]]:
    alias_counts = defaultdict(Counter)
    stopwords = {
        "DE", "DEL", "LA", "EL", "LOS", "LAS", "Y", "EN", "A", "PARA", "POR",
        "NO", "N", "NUM", "NUMERO", "NRO", "NO.", "SR", "SRA", "C.", "C",
    }

    for item in docs:
        labels = item.get("labels", {})
        ocr_text = item.get("ocr", {}).get("text") or ""
        lines = [normalize_text(line) for line in ocr_text.splitlines() if line.strip()]
        for key, value in labels.items():
            if not value:
                continue
            value_norm = normalize_text(value)
            if not value_norm:
                continue
            for idx, line in enumerate(lines):
                if value_norm in line:
                    prefix = line.split(value_norm, 1)[0].strip()
                    if not prefix and idx > 0:
                        prefix = lines[idx - 1].strip()
                    if not prefix:
                        continue
                    words = [w for w in prefix.split() if w not in stopwords]
                    if not words:
                        continue
                    # Take last 4 words as candidate label phrase
                    for size in range(1, min(4, len(words)) + 1):
                        phrase = " ".join(words[-size:])
                        if phrase:
                            alias_counts[key][phrase] += 1
                    break

    aliases = {}
    for key, counts in alias_counts.items():
        top = [phrase for phrase, _ in counts.most_common(6)]
        if top:
            aliases[key] = top
    return aliases


def main():
    dataset_path = os.environ.get("DATASET_JSONL", r"C:\Users\100156643\Documents\IA\training_dataset.jsonl")
    model_path = os.environ.get("DOC_MODEL", r"C:\xampp\htdocs\Sistema I.L.C.D.IA\ai-engine-python\app\models\doc_type_nb.json")
    alias_path = os.environ.get("ALIAS_MODEL", r"C:\xampp\htdocs\Sistema I.L.C.D.IA\ai-engine-python\app\models\field_aliases.json")

    docs = load_jsonl(dataset_path)
    if not docs:
        raise SystemExit("Empty dataset")

    model = train_nb(docs)
    with open(model_path, "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, indent=2)

    aliases = find_aliases(docs)
    with open(alias_path, "w", encoding="utf-8") as f:
        json.dump(aliases, f, ensure_ascii=False, indent=2)

    print(f"Saved model to {model_path}")
    print(f"Saved aliases to {alias_path}")


if __name__ == "__main__":
    main()
