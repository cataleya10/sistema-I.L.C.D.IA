import asyncio
import json
import os
import re
import sys
from typing import Any

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from app.pipelines.extract import extract_fields  # noqa: E402


def _build_boxes(lines: list[str]) -> list[dict[str, Any]]:
    boxes: list[dict[str, Any]] = []
    for idx, line in enumerate(lines):
        y = 100 + (idx * 30)
        boxes.append(
            {
                "text": line,
                "page": 1,
                "bbox": [[100, y], [1100, y], [1100, y + 24], [100, y + 24]],
                "confidence": 0.99,
            }
        )
    return boxes


def _fields_to_map(fields: list[dict[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in fields:
        key = str(field.get("key", "")).strip()
        value = str(field.get("value", "")).strip()
        if key and value:
            result[key] = value
    return result


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip().upper())


def _check_rule(actual: str, rule: dict[str, str]) -> tuple[bool, str]:
    val = _norm(actual)
    if "equals" in rule:
        exp = _norm(rule["equals"])
        return (val == exp, f"equals '{rule['equals']}'")
    if "contains" in rule:
        exp = _norm(rule["contains"])
        return (exp in val, f"contains '{rule['contains']}'")
    if "starts_with" in rule:
        exp = _norm(rule["starts_with"])
        return (val.startswith(exp), f"starts_with '{rule['starts_with']}'")
    if "regex" in rule:
        pattern = rule["regex"]
        return (re.search(pattern, actual or "") is not None, f"regex '{pattern}'")
    return (False, "invalid rule")


async def _run_case(case: dict[str, Any]) -> tuple[bool, list[str]]:
    ocr_lines = case.get("ocr_lines") or []
    ocr_boxes = _build_boxes(ocr_lines) if ocr_lines else []
    fields = await extract_fields(
        case["document_type"],
        case.get("ocr_text", ""),
        ocr_boxes,
        case.get("raw_text", ""),
        case.get("filename"),
    )
    fmap = _fields_to_map(fields)

    errors: list[str] = []
    expected = case.get("expected", {})
    for key, rule in expected.items():
        actual = fmap.get(key, "")
        ok, desc = _check_rule(actual, rule)
        if not ok:
            errors.append(f"{key}: expected {desc}, got '{actual}'")
    return (len(errors) == 0, errors)


async def main() -> int:
    dataset_path = os.environ.get(
        "GOLDEN_DATASET_PATH",
        os.path.join(os.path.dirname(__file__), "golden_dataset.json"),
    )
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    failures = 0
    for case in dataset:
        ok, errors = await _run_case(case)
        case_id = case.get("id", "unknown_case")
        if ok:
            print(f"OK {case_id}")
            continue
        failures += 1
        print(f"FAIL {case_id}")
        for err in errors:
            print(f"- {err}")

    if failures:
        print(f"Regression suite failed: {failures} case(s).")
        return 1
    print(f"Regression suite passed: {len(dataset)} case(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
