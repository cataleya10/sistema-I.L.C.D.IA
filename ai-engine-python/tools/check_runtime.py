import importlib.util
import os
import sys


def _parse_version(raw: str) -> tuple[int, int]:
    parts = (raw or "").strip().split(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Invalid version format: {raw!r}")
    return int(parts[0]), int(parts[1])


def _fmt(version: tuple[int, int]) -> str:
    return f"{version[0]}.{version[1]}"


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def main() -> int:
    min_ver = _parse_version(os.getenv("REQUIRED_PYTHON_MIN", "3.12"))
    max_exclusive = _parse_version(os.getenv("REQUIRED_PYTHON_MAX_EXCLUSIVE", "3.13"))
    current = (sys.version_info.major, sys.version_info.minor)

    print(f"[runtime] python={_fmt(current)} expected>={_fmt(min_ver)} and <{_fmt(max_exclusive)}")
    if not (min_ver <= current < max_exclusive):
        print("[runtime] ERROR: unsupported Python runtime.")
        return 1

    paddle_available = _has_module("paddleocr")
    rapid_available = _has_module("rapidocr_onnxruntime")
    print(f"[runtime] ocr_backends paddle={paddle_available} rapid={rapid_available}")
    if not (paddle_available or rapid_available):
        print("[runtime] ERROR: no OCR backend installed (paddleocr/rapidocr_onnxruntime).")
        return 1

    print("[runtime] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
