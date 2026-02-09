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


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.upper()).strip()


async def _run() -> int:
    sample_text = (
        "CFE COMISION FEDERAL DE ELECTRICIDAD RFC:CFE370814QI0 "
        "DAMIANHERNANDEZGABRIEL TOTALA PAGAR: $548 "
        "NO.DESERVICI0:795130504593 CUENTA:29DW05A012970875 "
        "LIMITE DE PAGO:05 FEB 26 C.P. 24180"
    )

    fields = await extract_fields(
        "COMPROBANTE_DOMICILIO",
        sample_text,
        [],
        sample_text,
        "cfe_regression.pdf",
    )
    fmap = _field_map(fields)

    titular = _normalize_name(fmap.get("titular", ""))
    total = fmap.get("total", "").replace("$", "").strip()

    errors: list[str] = []
    if titular != "DAMIAN HERNANDEZ GABRIEL":
        errors.append(f"titular inesperado: '{fmap.get('titular', '')}'")
    if not total.startswith("548"):
        errors.append(f"total inesperado: '{fmap.get('total', '')}'")

    if errors:
        print("FALLO regresion CFE:")
        for err in errors:
            print(f"- {err}")
        return 1

    print("OK regresion CFE: titular y total correctos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
