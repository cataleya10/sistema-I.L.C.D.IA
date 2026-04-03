"""
tools/evaluate.py
==================
CLI para evaluar la calidad de extraccion contra el dataset etiquetado.

Uso
---
    python tools/evaluate.py [opciones]

Opciones
--------
    --manifest  PATH     Ruta al dataset_index.json
                         (default: app/training/dataset/dataset_index.json)
    --base-dir  PATH     Directorio base del dataset etiquetado
                         (default: junto al manifest)
    --output    PATH     Donde guardar el informe JSON
                         (default: reports/evaluation_report.json)
    --max-docs  N        Limitar a los primeros N documentos
    --dry-run            Carga el manifest y muestra cuantos docs habria
    --field     CAMPO    Mostrar solo el campo especificado en el detalle

Ejemplo
-------
    python tools/evaluate.py --max-docs 5
    python tools/evaluate.py --field clabe --field rfc
    python tools/evaluate.py --output reports/eval_v2.json
"""
import argparse
import json
import os
import sys

# Asegurar que el paquete app sea importable desde la raiz del ai-engine
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import logging
logging.basicConfig(
    level=logging.WARNING,     # silenciar logs internos para output limpio
    format="%(levelname)s  %(name)s  %(message)s",
)

# Defaults
DEFAULT_MANIFEST = os.path.join(
    _ROOT, "dataset", "manifests", "dataset_index.json"
)
DEFAULT_OUTPUT = os.path.join(_ROOT, "reports", "evaluation_report.json")


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Evaluacion de calidad de extraccion NER/campo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--manifest", default=DEFAULT_MANIFEST,
        help=f"dataset_index.json (default: {DEFAULT_MANIFEST})",
    )
    p.add_argument(
        "--base-dir", default=None,
        help="Directorio base del dataset etiquetado",
    )
    p.add_argument(
        "--output", default=DEFAULT_OUTPUT,
        help=f"Ruta de salida del informe JSON (default: {DEFAULT_OUTPUT})",
    )
    p.add_argument(
        "--max-docs", type=int, default=None,
        help="Evaluar solo los primeros N documentos",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Solo muestra cuantos docs se evaluarian, sin procesarlos",
    )
    p.add_argument(
        "--field", action="append", dest="fields", metavar="CAMPO",
        help="Mostrar solo estos campos en el detalle (puede repetirse)",
    )
    p.add_argument(
        "--force-type", action="store_true", dest="force_type",
        help="Forzar el tipo de documento del label al extractor (mide calidad de campos aislada)",
    )
    p.add_argument(
        "--no-save", action="store_true",
        help="No guardar el informe en disco",
    )
    return p.parse_args(argv)


def dry_run(manifest_path: str, base_dir=None) -> None:
    from app.training.ner_data_builder import load_labeled_docs
    docs = load_labeled_docs(manifest_path, base_dir)
    print(f"\nManifest: {manifest_path}")
    print(f"Docs en el dataset: {len(docs)}")
    has_pdf = 0
    for d in docs:
        pdf = d.get("pdf_full_path", "")
        if pdf and os.path.exists(pdf):
            has_pdf += 1
    print(f"Docs con PDF accesible: {has_pdf}")
    print(f"Docs sin PDF (se omitian): {len(docs) - has_pdf}")
    print()


def _print_field_detail(report_dict: dict, fields_filter: list[str] | None = None) -> None:
    """Muestra detalle de campos filtrados para depuracion."""
    per_doc = report_dict.get("per_doc", [])
    fields_filter_set = set(fields_filter) if fields_filter else None
    for doc in per_doc:
        fname = doc.get("filename", doc.get("document_id", "?"))
        relevant = [
            fr for fr in doc.get("fields", [])
            if not fields_filter_set or fr.get("key") in fields_filter_set
        ]
        if not relevant:
            continue
        print(f"\n  Doc: {fname}  ({doc.get('document_type', '')})")
        for fr in relevant:
            key = fr["key"]
            exp = fr["expected"] or "(vacio)"
            pred = fr["predicted"] or "(vacio)"
            status = "OK" if fr.get("exact_match") else \
                     "PARCIAL" if fr.get("partial_match") else \
                     "FP" if fr.get("false_positive") else \
                     "FN" if fr.get("false_negative") else \
                     "WRONG" if fr.get("wrong_value") else "--"
            conf = fr.get("confidence", 0)
            print(f"    {key:<18}  [{status:<6}] conf={conf:.2f}")
            print(f"      expected : {exp[:60]}")
            print(f"      predicted: {pred[:60]}")


def main(argv=None) -> int:
    args = parse_args(argv)

    if not os.path.exists(args.manifest):
        print(f"ERROR: manifest no encontrado: {args.manifest}")
        return 1

    if args.dry_run:
        dry_run(args.manifest, args.base_dir)
        return 0

    print(f"\nEvaluando dataset: {args.manifest}")
    if args.max_docs:
        print(f"  (limitado a {args.max_docs} documentos)")

    from app.services.evaluation_service import (
        evaluate_dataset_sync,
        save_report,
        print_summary,
    )

    report = evaluate_dataset_sync(
        manifest_path=args.manifest,
        labeled_base_dir=args.base_dir,
        max_docs=args.max_docs,
        force_type=args.force_type,
    )

    # Imprimir resumen
    print_summary(report)

    # Detalle por campo si se pidio
    if args.fields:
        print("\nDETALLE POR CAMPO")
        report_dict = report.to_dict()
        _print_field_detail(report_dict, args.fields)
        print()

    # Guardar
    if not args.no_save:
        save_report(report, args.output)
        print(f"  Informe guardado: {args.output}")
    
    if report.docs_evaluated == 0:
        print("\nADVERTENCIA: No se evaluo ningun documento.")
        print("  Verifica que los PDF existan en las rutas del manifest.")
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
