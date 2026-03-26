"""
Herramienta: rebuild_index.py
Reconstruye dataset/manifests/dataset_index.json escaneando todos los PDFs
y JSONs de etiquetas que existen en el dataset.

Uso:
    python tools/rebuild_index.py          # reconstruir índice completo
    python tools/rebuild_index.py --show   # solo mostrar estadísticas sin guardar

El índice resultante sigue el formato estándar:
{
  "document_id":    "bancario_001",
  "tipo_documento": "bancario",
  "document_type":  "DATOS_BANCARIOS",
  "pdf_path":       "dataset/raw/bancario/bancario_001.pdf",
  "label_path":     "dataset/labeled/bancario/bancario_001.json",
  "labeled":        true,
  "banco":          "BBVA BANCOMER",          # solo bancario
  "carpeta_origen": "bancomer",               # solo bancario
  "added_date":     "2026-03-25"
}
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
DATASET_DIR  = PROJECT_ROOT / "dataset"
MANIFEST     = DATASET_DIR / "manifests" / "dataset_index.json"

DOC_TYPE_MAP = {
    "ine":                   "INE",
    "curp":                  "CURP",
    "nomina":                "NOMINA",
    "bancario":              "DATOS_BANCARIOS",
    "acta_nacimiento":       "ACTA_NACIMIENTO",
    "nss":                   "NSS",
    "csf":                   "CONSTANCIA_SITUACION_FISCAL",
    "comprobante_domicilio": "COMPROBANTE_DOMICILIO",
}

TIPOS = ["bancario", "ine", "curp", "nomina",
         "acta_nacimiento", "nss", "csf", "comprobante_domicilio"]


def _read_label(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def rebuild(dry_run: bool = False) -> None:
    entries = []
    stats   = {}

    for tipo in TIPOS:
        raw_dir   = DATASET_DIR / "raw"     / tipo
        label_dir = DATASET_DIR / "labeled" / tipo

        if not raw_dir.exists():
            continue

        pdfs = sorted(raw_dir.glob("*.pdf"))
        tipo_count = {"total": 0, "labeled": 0, "sin_label_json": 0}

        for pdf in pdfs:
            stem       = pdf.stem                          # ej. bancario_001
            label_path = label_dir / f"{stem}.json"
            label_data = _read_label(label_path) if label_path.exists() else {}
            labeled    = bool(label_data.get("labeled", False))

            entry = {
                "document_id":    stem,
                "tipo_documento": tipo,
                "document_type":  DOC_TYPE_MAP.get(tipo, tipo.upper()),
                "pdf_path":       f"dataset/raw/{tipo}/{pdf.name}",
                "label_path":     f"dataset/labeled/{tipo}/{stem}.json",
                "labeled":        labeled,
                "added_date":     label_data.get("added_date",
                                                  datetime.now().strftime("%Y-%m-%d")),
            }

            # Campos extra por tipo
            if tipo == "bancario":
                entry["banco"]          = label_data.get("banco_origen", "")
                entry["carpeta_origen"] = label_data.get("carpeta_origen", "")

            entries.append(entry)
            tipo_count["total"] += 1
            if labeled:
                tipo_count["labeled"] += 1
            if not label_path.exists():
                tipo_count["sin_label_json"] += 1

        stats[tipo] = tipo_count

    # ── Imprimir estadísticas ─────────────────────────────────────────────────
    total      = len(entries)
    total_lab  = sum(1 for e in entries if e["labeled"])
    print()
    print(f"  {'TIPO':<12}  {'TOTAL':>7}  {'ETIQUETADOS':>12}  {'SIN JSON':>9}")
    print(f"  {'-'*12}  {'-'*7}  {'-'*12}  {'-'*9}")
    for tipo in TIPOS:
        if tipo in stats:
            s = stats[tipo]
            print(f"  {tipo:<12}  {s['total']:>7}  {s['labeled']:>12}  {s['sin_label_json']:>9}")
    print(f"  {'TOTAL':<12}  {total:>7}  {total_lab:>12}")
    print()

    if dry_run:
        print("  [--show] No se guardó ningún cambio.")
        return

    # ── Guardar índice ────────────────────────────────────────────────────────
    manifest = {
        "version":          "2.0",
        "updated":          datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_documents":  total,
        "total_labeled":    total_lab,
        "document_types":   {t: stats[t]["total"] for t in TIPOS if t in stats},
        "entries":          entries,
    }

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"  Índice guardado: {MANIFEST.relative_to(PROJECT_ROOT)}")
    print(f"  Total: {total} documentos  |  Etiquetados: {total_lab}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Reconstruye el índice del dataset")
    parser.add_argument("--show", action="store_true",
                        help="Solo mostrar estadísticas sin guardar")
    args = parser.parse_args()
    rebuild(dry_run=args.show)


if __name__ == "__main__":
    main()
