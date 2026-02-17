import json
import os
import re
import threading
import unicodedata
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

_LOCK = threading.Lock()

_STOPWORDS = {
    "DE",
    "DEL",
    "LA",
    "EL",
    "LOS",
    "LAS",
    "Y",
    "EN",
    "A",
    "PARA",
    "POR",
    "NO",
    "N",
    "NUM",
    "NUMERO",
    "NRO",
    "NO.",
    "SR",
    "SRA",
    "C.",
    "C",
}


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _models_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "models"


def _dataset_path() -> Path:
    return Path(
        os.getenv(
            "ONLINE_TRAINING_DATASET_PATH",
            str(_models_dir() / "online_training_dataset.jsonl"),
        )
    )


def _doc_model_path() -> Path:
    return Path(
        os.getenv(
            "DOC_MODEL_PATH",
            str(_models_dir() / "doc_type_nb.json"),
        )
    )


def _alias_model_path() -> Path:
    return Path(
        os.getenv(
            "FIELD_ALIAS_PATH",
            str(_models_dir() / "field_aliases.json"),
        )
    )


def _stats_path() -> Path:
    return Path(
        os.getenv(
            "ONLINE_TRAINING_STATS_PATH",
            str(_models_dir() / "online_training_stats.json"),
        )
    )


def _normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKD", str(text or ""))
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.upper()
    value = re.sub(r"[^A-Z0-9\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokenize(text: str) -> list[str]:
    return [token for token in _normalize_text(text).split() if len(token) > 1]


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", str(value or "").strip().lower().replace("-", "_").replace(" ", "_"))


def _safe_load_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def _safe_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(payload_text, encoding="utf-8")
    try:
        os.replace(temp, path)
    except PermissionError:
        path.write_text(payload_text, encoding="utf-8")
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_stats() -> dict[str, Any]:
    return {
        "updated_at_utc": None,
        "dataset_samples": 0,
        "totals": {
            "attempted": 0,
            "trained": 0,
            "skipped": 0,
        },
        "by_reason": {},
        "by_document_type": {},
        "last_event": None,
        "recent_events": [],
    }


def _load_stats(path: Path) -> dict[str, Any]:
    stats = _safe_load_json(path)
    if not stats:
        return _default_stats()

    merged = _default_stats()
    merged.update({k: v for k, v in stats.items() if k in merged})
    if not isinstance(merged.get("totals"), dict):
        merged["totals"] = _default_stats()["totals"]
    if not isinstance(merged.get("by_reason"), dict):
        merged["by_reason"] = {}
    if not isinstance(merged.get("by_document_type"), dict):
        merged["by_document_type"] = {}
    if not isinstance(merged.get("recent_events"), list):
        merged["recent_events"] = []
    return merged


def _update_stats_unlocked(
    path: Path,
    *,
    document_id: str,
    document_type: str,
    status: str,
    confidence: float,
    trained: bool,
    reason: str,
    labels: int,
) -> None:
    stats = _load_stats(path)
    totals = stats["totals"]
    totals["attempted"] = int(totals.get("attempted", 0)) + 1
    if trained:
        totals["trained"] = int(totals.get("trained", 0)) + 1
        stats["dataset_samples"] = int(stats.get("dataset_samples", 0)) + 1
    else:
        totals["skipped"] = int(totals.get("skipped", 0)) + 1

    by_reason = stats["by_reason"]
    by_reason[reason] = int(by_reason.get(reason, 0)) + 1

    by_type = stats["by_document_type"]
    bucket = by_type.get(document_type)
    if not isinstance(bucket, dict):
        bucket = {"attempted": 0, "trained": 0, "skipped": 0}
    bucket["attempted"] = int(bucket.get("attempted", 0)) + 1
    if trained:
        bucket["trained"] = int(bucket.get("trained", 0)) + 1
    else:
        bucket["skipped"] = int(bucket.get("skipped", 0)) + 1
    by_type[document_type] = bucket

    event = {
        "timestamp_utc": _utc_now_iso(),
        "document_id": str(document_id),
        "document_type": str(document_type),
        "status": str(status),
        "confidence": float(confidence or 0),
        "trained": bool(trained),
        "reason": str(reason),
        "labels": int(labels),
    }
    stats["updated_at_utc"] = event["timestamp_utc"]
    stats["last_event"] = event

    max_recent = max(1, int(os.getenv("ONLINE_TRAINING_STATS_RECENT_LIMIT", "50")))
    recent = list(stats.get("recent_events") or [])
    recent.append(event)
    if len(recent) > max_recent:
        recent = recent[-max_recent:]
    stats["recent_events"] = recent
    _safe_write_json(path, stats)


def _is_reasonable_alias(alias: str) -> bool:
    token = _normalize_text(alias)
    if len(token) < 4:
        return False
    letters = sum(1 for char in token if char.isalpha())
    if letters < 3:
        return False
    return token not in {"ES", "PAGO", "CP", "NSS"}


def _best_labels(fields: list[dict[str, Any]]) -> dict[str, str]:
    min_conf = float(os.getenv("ONLINE_TRAINING_MIN_FIELD_CONFIDENCE", "0.9"))
    best: dict[str, tuple[float, str]] = {}
    for field in fields or []:
        if not bool(field.get("valid", True)):
            continue
        key = _normalize_key(str(field.get("key", "")))
        if not key or key == "texto_detectado":
            continue
        value = field.get("value")
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
        if not value:
            continue
        if len(str(value)) > 200:
            continue
        confidence = float(field.get("confidence", 0) or 0)
        if confidence < min_conf:
            continue
        current = best.get(key)
        if current is None or confidence >= current[0]:
            best[key] = (confidence, str(value))
    return {key: value for key, (_, value) in best.items()}


def _empty_model() -> dict[str, Any]:
    return {
        "classes": [],
        "class_counts": {},
        "token_counts": {},
        "vocab": [],
        "total_docs": 0,
    }


def _update_doc_type_model(path: Path, doc_type: str, text: str) -> None:
    tokens = _tokenize(text)
    if not tokens:
        return

    model = _safe_load_json(path)
    if not model:
        model = _empty_model()

    classes = list(model.get("classes") or [])
    class_counts = dict(model.get("class_counts") or {})
    token_counts = dict(model.get("token_counts") or {})
    vocab = set(model.get("vocab") or [])
    total_docs = int(model.get("total_docs") or 0)

    if doc_type not in classes:
        classes.append(doc_type)
    class_counts[doc_type] = int(class_counts.get(doc_type) or 0) + 1
    cls_counts = dict(token_counts.get(doc_type) or {})
    for token in tokens:
        cls_counts[token] = int(cls_counts.get(token) or 0) + 1
        vocab.add(token)
    token_counts[doc_type] = cls_counts
    total_docs += 1

    model["classes"] = classes
    model["class_counts"] = class_counts
    model["token_counts"] = token_counts
    model["vocab"] = sorted(vocab)
    model["total_docs"] = total_docs
    _safe_write_json(path, model)


def _candidate_aliases(ocr_text: str, value: str) -> list[str]:
    normalized_value = _normalize_text(value)
    if not normalized_value:
        return []

    lines = [_normalize_text(line) for line in str(ocr_text or "").splitlines() if line.strip()]
    candidates: list[str] = []
    for idx, line in enumerate(lines):
        if normalized_value not in line:
            continue
        prefix = line.split(normalized_value, 1)[0].strip()
        if not prefix and idx > 0:
            prefix = lines[idx - 1].strip()
        if not prefix:
            continue
        words = [word for word in prefix.split() if word and word not in _STOPWORDS]
        if not words:
            continue
        for size in range(1, min(4, len(words)) + 1):
            phrase = " ".join(words[-size:])
            if phrase and _is_reasonable_alias(phrase):
                candidates.append(phrase)
        break
    return candidates


def _update_alias_model(path: Path, labels: dict[str, str], ocr_text: str) -> None:
    if not labels:
        return

    max_aliases = int(os.getenv("ONLINE_TRAINING_MAX_ALIASES_PER_FIELD", "12"))
    alias_model = _safe_load_json(path)

    changed = False
    for key, value in labels.items():
        if not value:
            continue
        existing = [str(item) for item in alias_model.get(key, []) if str(item).strip()]
        for phrase in _candidate_aliases(ocr_text, value):
            if phrase not in existing:
                existing.append(phrase)
                changed = True
        if len(existing) > max_aliases:
            existing = existing[:max_aliases]
        if existing:
            alias_model[key] = existing

    if changed:
        _safe_write_json(path, alias_model)


def learn_from_processed_document(
    *,
    document_id: str,
    document_type: str,
    status: str,
    confidence: float,
    ocr_text: str,
    fields: list[dict[str, Any]],
) -> dict[str, Any]:
    stats_path = _stats_path()

    if not _env_bool("ONLINE_TRAINING_ENABLED", True):
        with _LOCK:
            _update_stats_unlocked(
                stats_path,
                document_id=document_id,
                document_type=str(document_type or "").upper(),
                status=status,
                confidence=confidence,
                trained=False,
                reason="disabled",
                labels=0,
            )
        return {"trained": False, "reason": "disabled"}

    doc_type = str(document_type or "").upper()
    if doc_type in {"", "UNKNOWN"}:
        with _LOCK:
            _update_stats_unlocked(
                stats_path,
                document_id=document_id,
                document_type=doc_type or "UNKNOWN",
                status=status,
                confidence=confidence,
                trained=False,
                reason="unknown_document_type",
                labels=0,
            )
        return {"trained": False, "reason": "unknown_document_type"}
    if str(status or "").upper() != "READY":
        with _LOCK:
            _update_stats_unlocked(
                stats_path,
                document_id=document_id,
                document_type=doc_type,
                status=status,
                confidence=confidence,
                trained=False,
                reason="status_not_ready",
                labels=0,
            )
        return {"trained": False, "reason": "status_not_ready"}

    min_doc_conf = float(os.getenv("ONLINE_TRAINING_MIN_DOC_CONFIDENCE", "0.85"))
    if float(confidence or 0) < min_doc_conf:
        with _LOCK:
            _update_stats_unlocked(
                stats_path,
                document_id=document_id,
                document_type=doc_type,
                status=status,
                confidence=confidence,
                trained=False,
                reason="low_document_confidence",
                labels=0,
            )
        return {"trained": False, "reason": "low_document_confidence"}

    clean_text = str(ocr_text or "").strip()
    if len(_tokenize(clean_text)) < 15:
        with _LOCK:
            _update_stats_unlocked(
                stats_path,
                document_id=document_id,
                document_type=doc_type,
                status=status,
                confidence=confidence,
                trained=False,
                reason="insufficient_text",
                labels=0,
            )
        return {"trained": False, "reason": "insufficient_text"}

    labels = _best_labels(fields)
    if not labels:
        with _LOCK:
            _update_stats_unlocked(
                stats_path,
                document_id=document_id,
                document_type=doc_type,
                status=status,
                confidence=confidence,
                trained=False,
                reason="no_reliable_labels",
                labels=0,
            )
        return {"trained": False, "reason": "no_reliable_labels"}

    sample = {
        "document_id": str(document_id),
        "document_type": doc_type,
        "source": "online_auto",
        "ocr": {"text": clean_text},
        "labels": labels,
    }

    with _LOCK:
        _append_jsonl(_dataset_path(), sample)
        _update_doc_type_model(_doc_model_path(), doc_type, clean_text)
        _update_alias_model(_alias_model_path(), labels, clean_text)
        _update_stats_unlocked(
            stats_path,
            document_id=document_id,
            document_type=doc_type,
            status=status,
            confidence=confidence,
            trained=True,
            reason="trained",
            labels=len(labels),
        )

    return {"trained": True, "labels": len(labels)}


def get_online_learning_stats(recent: int = 10) -> dict[str, Any]:
    requested_recent = max(0, min(100, int(recent)))
    path = _stats_path()
    with _LOCK:
        stats = _load_stats(path)

    events = list(stats.get("recent_events") or [])
    if requested_recent == 0:
        events = []
    elif len(events) > requested_recent:
        events = events[-requested_recent:]
    events.reverse()

    return {
        "enabled": _env_bool("ONLINE_TRAINING_ENABLED", True),
        "stats_path": str(path),
        "dataset_path": str(_dataset_path()),
        "model_path": str(_doc_model_path()),
        "alias_path": str(_alias_model_path()),
        "updated_at_utc": stats.get("updated_at_utc"),
        "dataset_samples": int(stats.get("dataset_samples", 0) or 0),
        "totals": stats.get("totals", {}),
        "by_reason": stats.get("by_reason", {}),
        "by_document_type": stats.get("by_document_type", {}),
        "last_event": stats.get("last_event"),
        "recent_events": events,
    }
