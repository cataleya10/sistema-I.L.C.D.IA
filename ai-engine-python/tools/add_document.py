"""
Herramienta: add_document.py
Agrega un documento nuevo al dataset de entrenamiento.

Uso:
    python tools/add_document.py <ruta_archivo> <tipo>

Ejemplos:
    python tools/add_document.py C:/Descargas/mi_ine.pdf ine
    python tools/add_document.py C:/Descargas/estado_bbva.pdf bancario
    python tools/add_document.py C:/Descargas/recibo_marzo.pdf nomina
    python tools/add_document.py C:/Descargas/mi_curp.pdf curp

Lo que hace:
    1. Copia el archivo a dataset/raw/<tipo>/<tipo>_NNN.<ext>
    2. Crea un archivo de etiquetas vacío en dataset/labeled/<tipo>/<tipo>_NNN.json
    3. Registra el documento en dataset/manifests/dataset_index.json
"""

import sys
import os
import json
import shutil
from datetime import datetime
from pathlib import Path

# ─── Configuración ────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATASET_DIR  = PROJECT_ROOT / "dataset"
MANIFEST     = DATASET_DIR / "manifests" / "dataset_index.json"

TIPOS_VALIDOS = {"ine", "curp", "nomina", "bancario"}

CAMPOS_POR_TIPO = {
    "ine": {
        "curp":               "",
        "nombre":             "",
        "fecha_nacimiento":   "",
        "sexo":               "",
        "domicilio":          "",
        "clave_elector":      "",
        "seccion":            "",
        "vigencia":           "",
        "entidad_nacimiento": "",
    },
    "curp": {
        "curp":               "",
        "nombre":             "",
        "fecha_nacimiento":   "",
        "sexo":               "",
        "entidad_nacimiento": "",
    },
    "nomina": {
        "nombre":             "",
        "rfc":                "",
        "nss":                "",
        "curp":               "",
        "empresa":            "",
        "periodo":            "",
        "fecha_pago":         "",
        "total_percepciones": "",
        "total_deducciones":  "",
        "neto_pagar":         "",
    },
    "bancario": {
        "clabe":       "",
        "cuenta":      "",
        "banco":       "",
        "titular":     "",
        "rfc":         "",
        "fecha_corte": "",
        "periodo":     "",
    },
}

DOC_TYPE_MAP = {
    "ine":      "INE",
    "curp":     "CURP",
    "nomina":   "NOMINA",
    "bancario": "DATOS_BANCARIOS",
}

# ─── Funciones ────────────────────────────────────────────────────────────────

def _next_id(tipo: str) -> int:
    """Obtiene el siguiente número de secuencia para el tipo dado."""
    raw_dir = DATASET_DIR / "raw" / tipo
    existing = list(raw_dir.glob(f"{tipo}_*.pdf")) + \
               list(raw_dir.glob(f"{tipo}_*.jpg")) + \
               list(raw_dir.glob(f"{tipo}_*.jpeg")) + \
               list(raw_dir.glob(f"{tipo}_*.png"))
    if not existing:
        return 1
    nums = []
    for f in existing:
        stem = f.stem  # ej. "ine_003"
        parts = stem.split("_")
        if len(parts) >= 2 and parts[-1].isdigit():
            nums.append(int(parts[-1]))
    return max(nums, default=0) + 1


def _load_manifest() -> dict:
    if MANIFEST.exists():
        with open(MANIFEST, encoding="utf-8-sig") as fh:
            return json.load(fh)
    return {
        "version": "1.0",
        "created": datetime.now().strftime("%Y-%m-%d"),
        "document_types": list(TIPOS_VALIDOS),
        "splits": ["raw", "labeled", "corrected"],
        "entries": [],
    }


def _save_manifest(data: dict) -> None:
    with open(MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def add_document(source_path: str, tipo: str) -> None:
    tipo = tipo.lower().strip()

    # ── Validaciones ──────────────────────────────────────────────────────────
    if tipo not in TIPOS_VALIDOS:
        print(f"ERROR: tipo '{tipo}' no válido. Usa: {', '.join(sorted(TIPOS_VALIDOS))}")
        sys.exit(1)

    src = Path(source_path)
    if not src.exists():
        print(f"ERROR: archivo no encontrado: {source_path}")
        sys.exit(1)

    ext = src.suffix.lower()
    if ext not in {".pdf", ".jpg", ".jpeg", ".png"}:
        print(f"ERROR: formato no soportado '{ext}'. Usa: .pdf .jpg .jpeg .png")
        sys.exit(1)

    # ── Destino ───────────────────────────────────────────────────────────────
    seq_id   = _next_id(tipo)
    new_name = f"{tipo}_{seq_id:03d}{ext}"

    raw_dest     = DATASET_DIR / "raw"     / tipo / new_name
    label_dest   = DATASET_DIR / "labeled" / tipo / f"{tipo}_{seq_id:03d}.json"

    # ── Copiar archivo ────────────────────────────────────────────────────────
    raw_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, raw_dest)
    print(f"  Copiado  → {raw_dest.relative_to(PROJECT_ROOT)}")

    # ── Crear JSON de etiquetas ───────────────────────────────────────────────
    label_dest.parent.mkdir(parents=True, exist_ok=True)
    label_data = {
        "filename":        new_name,
        "document_type":   DOC_TYPE_MAP[tipo],
        "source_original": str(src),
        "added_date":      datetime.now().strftime("%Y-%m-%d"),
        "labeled":         False,
        "notes":           "",
        "expected_fields": CAMPOS_POR_TIPO[tipo],
    }
    with open(label_dest, "w", encoding="utf-8") as fh:
        json.dump(label_data, fh, ensure_ascii=False, indent=2)
    print(f"  Etiqueta → {label_dest.relative_to(PROJECT_ROOT)}")

    # ── Actualizar índice ─────────────────────────────────────────────────────
    manifest = _load_manifest()
    manifest["entries"].append({
        "id":            f"{tipo}_{seq_id:03d}",
        "tipo":          tipo,
        "document_type": DOC_TYPE_MAP[tipo],
        "filename":      new_name,
        "raw_path":      f"dataset/raw/{tipo}/{new_name}",
        "label_path":    f"dataset/labeled/{tipo}/{tipo}_{seq_id:03d}.json",
        "added_date":    datetime.now().strftime("%Y-%m-%d"),
        "labeled":       False,
    })
    _save_manifest(manifest)
    print(f"  Índice   → dataset/manifests/dataset_index.json  (total: {len(manifest['entries'])} docs)")

    # ── Resumen ───────────────────────────────────────────────────────────────
    print()
    print(f"Documento agregado: {new_name}")
    print(f"Siguiente paso: abre '{label_dest.relative_to(PROJECT_ROOT)}' y rellena los campos esperados.")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)

    source = sys.argv[1]
    tipo   = sys.argv[2]
    add_document(source, tipo)


if __name__ == "__main__":
    main()
