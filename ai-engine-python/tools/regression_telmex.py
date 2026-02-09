import asyncio
import os
import re
import sys

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

from app.pipelines.extract import extract_fields  # noqa: E402


def _field_map(fields: list[dict]) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in fields:
        key = str(field.get("key", "")).strip()
        value = str(field.get("value", "")).strip()
        if key and value:
            result[key] = value
    return result


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.upper()).strip()


async def _run() -> int:
    sample_lines = [
        "TELMEX",
        "CALDERON CORDOVA JOSE ALEJANDRO",
        "PUBLICO EN GENERAL",
        "CLL DEL GOLFO SN",
        "MZ SN LT SN",
        "ATASTA",
        "ATASTA, CARMEN, CA",
        "C.P. 24326",
        "NUMERO: 9386883644",
        "CUENTA: 00001000000711443734",
        "REFERENCIA: 93868836440000549001",
        "PAGAR ANTES DE: 23-ENE-2026",
        "TOTAL A PAGAR 549.00",
    ]
    sample_text = " ".join(sample_lines)
    sample_ocr_boxes = []
    for idx, line in enumerate(sample_lines):
        y = 100 + (idx * 30)
        sample_ocr_boxes.append(
            {
                "text": line,
                "page": 1,
                "bbox": [[100, y], [1100, y], [1100, y + 24], [100, y + 24]],
                "confidence": 0.99,
            }
        )

    fields = await extract_fields(
        "COMPROBANTE_DOMICILIO",
        sample_text,
        sample_ocr_boxes,
        sample_text,
        "telmex_regression.pdf",
    )
    fmap = _field_map(fields)

    titular = _norm_text(fmap.get("titular", ""))
    domicilio = _norm_text(fmap.get("domicilio", ""))
    cp = fmap.get("cp", "")
    total = fmap.get("total", "").replace("$", "").strip()

    errors: list[str] = []
    if titular != "CALDERON CORDOVA JOSE ALEJANDRO":
        errors.append(f"titular inesperado: '{fmap.get('titular', '')}'")
    if "CLL DEL GOLFO SN" not in domicilio:
        errors.append(f"domicilio inesperado: '{fmap.get('domicilio', '')}'")
    if cp != "24326":
        errors.append(f"cp inesperado: '{cp}'")
    if not total.startswith("549"):
        errors.append(f"total inesperado: '{fmap.get('total', '')}'")

    if errors:
        print("FALLO regresion TELMEX:")
        for err in errors:
            print(f"- {err}")
        return 1

    print("OK regresion TELMEX: titular, domicilio, cp y total correctos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
