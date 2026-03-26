"""
Herramienta: prelabel_document.py
Pre-etiqueta un documento ejecutando el extractor y guardando los campos detectados.

Uso:
    python tools/prelabel_document.py <ruta_pdf> <tipo>

Ejemplos:
    python tools/prelabel_document.py dataset/raw/ine/ine_001.pdf ine
    python tools/prelabel_document.py dataset/raw/nomina/nomina_001.pdf nomina
    python tools/prelabel_document.py dataset/raw/bancario/bancario_001.pdf bancario
    python tools/prelabel_document.py dataset/raw/curp/curp_001.pdf curp
"""

import sys
import os
import json
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Any

SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATASET_DIR  = PROJECT_ROOT / "dataset"

sys.path.insert(0, str(PROJECT_ROOT))

TIPOS_VALIDOS = {"ine", "curp", "nomina", "bancario"}

DOC_TYPE_MAP = {
    "ine":      "INE",
    "curp":     "CURP",
    "nomina":   "NOMINA",
    "bancario": "DATOS_BANCARIOS",
}

CAMPOS_ESPERADOS = {
    "ine":      {"curp", "nombre", "fecha_nacimiento", "sexo", "domicilio", "clave_elector", "seccion", "vigencia", "entidad_nacimiento"},
    "curp":     {"curp", "nombre", "fecha_nacimiento", "sexo", "entidad_nacimiento"},
    "nomina":   {"nombre", "rfc", "nss", "curp", "empresa", "periodo", "fecha_pago", "total_percepciones", "total_deducciones", "neto_pagar"},
    "bancario": {"clabe", "cuenta", "banco", "titular", "rfc", "fecha_corte", "periodo"},
}


# ✅ FIX: tipo de retorno correcto list[dict[str, Any]]
async def _run_extraction(pdf_path: Path, tipo: str) -> list[dict[str, Any]]:
    """Ejecuta el pipeline completo sobre el PDF y devuelve los campos detectados."""
    from fastapi import UploadFile
    import io

    from app.pipelines.preprocess import preprocess
    from app.services.extractor_service import extract_document_fields
    from app.services.normalization_service import validate_extracted_fields

    pdf_bytes = pdf_path.read_bytes()
    file_obj  = io.BytesIO(pdf_bytes)
    upload    = UploadFile(filename=pdf_path.name, file=file_obj)  # type: ignore[arg-type]

    print(f"  [1/4] Preprocesando {pdf_path.name}...")
    images, extracted_text, text_layer_boxes, pdf_tables, _ = await preprocess(upload)

    print(f"  [2/4] Ejecutando OCR...")
    from app.pipelines.ocr import run_ocr
    if images:
        ocr_text, ocr_boxes = await run_ocr(images)
    else:
        ocr_text   = extracted_text
        ocr_boxes  = text_layer_boxes

    full_text = ocr_text or extracted_text

    print(f"  [3/4] Clasificando documento...")
    doc_type = DOC_TYPE_MAP.get(tipo, "GENERICO")

    print(f"  [4/4] Extrayendo campos (tipo: {doc_type})...")
    # ✅ FIX: extract_document_fields devuelve list[dict], asignamos correctamente
    fields: list[dict[str, Any]] = await extract_document_fields(
        document_type=doc_type,
        ocr_text=full_text,
        ocr_boxes=ocr_boxes,
        raw_text=extracted_text,
        filename=pdf_path.name,
        pdf_tables=pdf_tables,
    )
    # ✅ FIX: validate_extracted_fields también devuelve list[dict]
    validated: list[dict[str, Any]] = await validate_extracted_fields(fields)
    return validated


def _fields_to_dict(fields: list[dict[str, Any]], tipo: str) -> dict[str, str]:
    """
    Convierte la lista de campos extraídos a un dict plano {key: value}.
    Incluye todos los campos esperados para el tipo, con "" si no se detectaron.
    """
    detected: dict[str, str] = {}
    for f in fields:
        key = str(f.get("key", "") or "")
        val = str(f.get("value", "") or "")
        if key in {"texto_detectado", "tabla_celdas", "pago_detalle",
                   "replica_pdf_layout", "replica_pdf_texto"}:
            continue
        if key and val:
            detected[key] = val.strip()

    result: dict[str, str] = {}
    for campo in sorted(CAMPOS_ESPERADOS.get(tipo, set())):
        result[campo] = detected.get(campo, "")

    for k, v in detected.items():
        if k not in result:
            result[f"_extra_{k}"] = v

    return result


def prelabel(pdf_path_str: str, tipo: str) -> None:
    tipo = tipo.lower().strip()

    if tipo not in TIPOS_VALIDOS:
        print(f"ERROR: tipo '{tipo}' no válido. Usa: {', '.join(sorted(TIPOS_VALIDOS))}")
        sys.exit(1)

    pdf_path = Path(pdf_path_str)
    if not pdf_path.exists():
        print(f"ERROR: archivo no encontrado: {pdf_path_str}")
        sys.exit(1)

    stem       = pdf_path.stem
    label_path = DATASET_DIR / "labeled" / tipo / f"{stem}.json"
    label_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\nPre-etiquetando: {pdf_path.name}  ->  tipo={tipo.upper()}")
    print("-" * 60)

    try:
        fields = asyncio.run(_run_extraction(pdf_path, tipo))
    except Exception as e:
        print(f"\nERROR durante la extracción: {e}")
        print("Creando JSON vacío para etiquetado manual...")
        fields = []

    fields_dict = _fields_to_dict(fields, tipo)

    label_data = {
        "filename":        pdf_path.name,
        "document_type":   DOC_TYPE_MAP[tipo],
        "prelabeled_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "labeled":         False,
        "notes":           "REVISAR: corrige los campos incorrectos y cambia 'labeled' a true",
        "expected_fields": fields_dict,
    }

    with open(label_path, "w", encoding="utf-8") as fh:
        json.dump(label_data, fh, ensure_ascii=False, indent=2)

    print()
    print("Campos detectados:")
    print("-" * 60)
    detectados = 0
    vacios     = 0
    for campo, valor in fields_dict.items():
        if campo.startswith("_extra_"):
            continue
        if valor:
            print(f"  [OK]  {campo:<25} {valor}")
            detectados += 1
        else:
            print(f"  [--]  {campo:<25} (no detectado)")
            vacios += 1

    print("-" * 60)
    print(f"  Detectados: {detectados} / {detectados + vacios}   Faltantes: {vacios}")
    print()
    print(f"Archivo guardado: {label_path.relative_to(PROJECT_ROOT)}")
    print()
    print("SIGUIENTE PASO:")
    print(f"  1. Abre el archivo: {label_path}")
    print(f"  2. Corrige cualquier campo incorrecto")
    print(f"  3. Rellena los campos vacíos (marcados con '')")
    print(f"  4. Cambia  \"labeled\": false  ->  \"labeled\": true")
    print()


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    prelabel(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()