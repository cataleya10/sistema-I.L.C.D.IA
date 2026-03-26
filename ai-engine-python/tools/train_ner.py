#!/usr/bin/env python3
"""
tools/train_ner.py
==================
Entrena el modelo NER spaCy para detectar entidades en documentos mexicanos.

Flujo
-----
1. Carga el dataset etiquetado (dataset_index.json + labeled/*.json)
2. Extrae texto nativo de los PDFs con PyMuPDF (rapido, sin OCR completo)
3. Alinea valores de campos conocidos con sus posiciones en el texto
4. Divide en train/dev (80/20)
5. Entrena un modelo spaCy desde cero (blank "es" + NER personalizado)
6. Evalua en el conjunto dev cada 5 epocas
7. Guarda el mejor checkpoint + modelo final en app/models/ner/

Uso
---
    python tools/train_ner.py
    python tools/train_ner.py --epochs 30
    python tools/train_ner.py --dry-run     # solo estadisticas, no entrena
    python tools/train_ner.py --force-rebuild  # reconstruye cache del dataset
    python tools/train_ner.py --output app/models/ner_v2  # carpeta personalizada

Prerequisitos
-------------
    pip install spacy
    # Opcional: para fine-tune sobre modelo base en espanol:
    # python -m spacy download es_core_news_sm
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import time
from collections import Counter

# ---------------------------------------------------------------------------
# Bootstrap: agregar project root al path
# ---------------------------------------------------------------------------
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("train_ner")

# ✅ FIX: compounding viene de thinc.api en spaCy 3.x
from thinc.api import compounding

from app.training.ner_data_builder import (
    NER_LABELS,
    build_ner_dataset,
    load_ner_dataset,
    save_ner_dataset,
)

# ---------------------------------------------------------------------------
# Rutas por defecto
# ---------------------------------------------------------------------------
_DEFAULT_MANIFEST = os.path.join(_ROOT, "dataset", "manifests", "dataset_index.json")
_DEFAULT_OUTPUT   = os.path.join(_ROOT, "app", "models", "ner")
_DEFAULT_CACHE    = os.path.join(_ROOT, "dataset", "cache", "ner_training_data.json")
_DEFAULT_EPOCHS   = 20
_DEFAULT_DROP     = 0.3


def _check_spacy() -> bool:
    try:
        import spacy  # noqa: F401
        return True
    except ImportError:
        return False


def _build_or_load_dataset(
    manifest_path: str,
    cache_path: str,
    force_rebuild: bool,
) -> list[tuple]:
    if not force_rebuild and os.path.exists(cache_path):
        print(f"Cargando dataset desde cache: {cache_path}")
        examples = load_ner_dataset(cache_path)
        print(f"  {len(examples)} ejemplos en cache")
        return examples

    print(f"Construyendo dataset desde: {manifest_path}")
    examples = build_ner_dataset(manifest_path)
    if not examples:
        return []

    cache_dir = os.path.dirname(cache_path)
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
    save_ner_dataset(examples, cache_path)
    print(f"  {len(examples)} ejemplos guardados en cache: {cache_path}")
    return examples


def _split_dataset(
    examples: list[tuple],
    dev_ratio: float = 0.2,
    seed: int = 42,
) -> tuple[list[tuple], list[tuple]]:
    rng = random.Random(seed)
    shuffled = list(examples)
    rng.shuffle(shuffled)
    split = max(1, int(len(shuffled) * (1 - dev_ratio)))
    return shuffled[:split], shuffled[split:]


def _make_spacy_examples(nlp, data: list[tuple]) -> list:
    """Convierte (text, annotations) a objetos spaCy Example, descartando invalidos."""
    from spacy.training import Example
    valid = []
    for text, annotations in data:
        try:
            doc = nlp.make_doc(text)
            ex = Example.from_dict(doc, annotations)
            valid.append(ex)
        except Exception:
            pass  # span fuera de rango u otro error de alineacion
    return valid


def train(
    examples: list[tuple],
    output_dir: str,
    n_iter: int = _DEFAULT_EPOCHS,
    drop: float = _DEFAULT_DROP,
    base_model: str | None = None,
) -> None:
    """Entrena el modelo NER y guarda el resultado en output_dir."""
    import spacy

    train_data, dev_data = _split_dataset(examples)
    print(f"  Train: {len(train_data)} / Dev: {len(dev_data)} ejemplos")

    if not train_data:
        print("[ERROR] Sin datos de entrenamiento.")
        return

    # Crear o cargar modelo base
    if base_model:
        try:
            nlp = spacy.load(base_model)
            print(f"  Fine-tuning sobre: {base_model}")
            if "ner" not in nlp.pipe_names:
                nlp.add_pipe("ner", last=True)
        except Exception as exc:
            print(f"[AVISO] No se pudo cargar {base_model}: {exc}. Usando modelo blank.")
            nlp = spacy.blank("es")
            nlp.add_pipe("ner")
    else:
        nlp = spacy.blank("es")
        nlp.add_pipe("ner")

    # Registrar etiquetas
    ner = nlp.get_pipe("ner")
    for label in NER_LABELS:
        ner.add_label(label)

    # Ejemplos spaCy
    train_examples = _make_spacy_examples(nlp, train_data)
    dev_examples   = _make_spacy_examples(nlp, dev_data)
    print(f"  Ejemplos validos: train={len(train_examples)} dev={len(dev_examples)}")

    if not train_examples:
        print("[ERROR] Todos los ejemplos son invalidos (spans incorrectos).")
        return

    nlp.initialize(lambda: iter(train_examples))

    best_f = 0.0
    best_path = os.path.join(output_dir, "best")
    t0 = time.time()
    rng = random.Random(42)

    print(f"\nEntrenando {n_iter} epocas (drop={drop})...")
    for epoch in range(1, n_iter + 1):
        rng.shuffle(train_examples)
        losses: dict = {}
        batches = spacy.util.minibatch(
            train_examples,
            size=compounding(4.0, 32.0, 1.001),
        )
        for batch in batches:
            nlp.update(batch, drop=drop, losses=losses)

        # Evaluar cada 5 epocas
        if epoch % 5 == 0 or epoch == n_iter:
            if dev_examples:
                scores = nlp.evaluate(dev_examples)
                ner_f = scores.get("ents_f", 0.0)
                ner_p = scores.get("ents_p", 0.0)
                ner_r = scores.get("ents_r", 0.0)
            else:
                ner_f = ner_p = ner_r = 0.0

            elapsed = time.time() - t0
            print(
                f"  Epoca {epoch:3d}/{n_iter}"
                f" | loss={losses.get('ner', 0):.3f}"
                f" | P={ner_p:.3f} R={ner_r:.3f} F={ner_f:.3f}"
                f" | {elapsed:.0f}s"
            )

            if ner_f > best_f:
                best_f = ner_f
                os.makedirs(best_path, exist_ok=True)
                nlp.to_disk(best_path)

    # Guardar modelo final
    os.makedirs(output_dir, exist_ok=True)
    nlp.to_disk(output_dir)
    elapsed_total = time.time() - t0
    print(f"\n[OK] Modelo guardado en: {output_dir}")
    print(f"     Mejor F-score: {best_f:.4f} | Tiempo total: {elapsed_total:.0f}s")


def _print_stats(examples: list[tuple]) -> None:
    label_counts: Counter = Counter()
    for _, annotations in examples:
        for _, _, label in annotations.get("entities", []):
            label_counts[label] += 1
    print(f"\nDataset NER: {len(examples)} ejemplos")
    print("Distribucion de etiquetas:")
    for label, count in sorted(label_counts.items(), key=lambda x: -x[1]):
        print(f"  {label:<14}: {count:4d}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Entrenamiento NER spaCy — documentos mexicanos"
    )
    parser.add_argument(
        "--manifest", default=_DEFAULT_MANIFEST,
        help="Ruta al dataset_index.json",
    )
    parser.add_argument(
        "--output", default=_DEFAULT_OUTPUT,
        help="Directorio donde guardar el modelo entrenado",
    )
    parser.add_argument(
        "--epochs", type=int, default=_DEFAULT_EPOCHS,
        help=f"Numero de epocas de entrenamiento (default: {_DEFAULT_EPOCHS})",
    )
    parser.add_argument(
        "--drop", type=float, default=_DEFAULT_DROP,
        help=f"Tasa de dropout (default: {_DEFAULT_DROP})",
    )
    parser.add_argument(
        "--base-model", default=None,
        help="Modelo spaCy base para fine-tune (ej. es_core_news_sm). "
             "Si se omite se entrena desde cero.",
    )
    parser.add_argument(
        "--force-rebuild", action="store_true",
        help="Reconstruir el dataset aunque exista cache",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Solo muestra estadisticas del dataset, no entrena",
    )
    parser.add_argument(
        "--cache", default=_DEFAULT_CACHE,
        help="Ruta para el cache del dataset NER (JSON)",
    )
    args = parser.parse_args()

    # Verificar spaCy
    if not _check_spacy():
        print("[ERROR] spaCy no esta instalado.")
        print("  Instala con: pip install spacy")
        sys.exit(1)

    if not os.path.exists(args.manifest):
        print(f"[ERROR] Manifest no encontrado: {args.manifest}")
        sys.exit(1)

    # Cargar o construir dataset
    examples = _build_or_load_dataset(args.manifest, args.cache, args.force_rebuild)
    if not examples:
        print("[ERROR] Dataset vacio. "
              "Verifica que los docs esten etiquetados en dataset/labeled/")
        sys.exit(1)

    _print_stats(examples)

    if args.dry_run:
        print("\n[dry-run] Terminado sin entrenar.")
        return

    # Entrenar
    print(f"\nConfiguracion: epochs={args.epochs} drop={args.drop} base={args.base_model}")
    print(f"Salida: {args.output}")
    train(
        examples,
        args.output,
        n_iter=args.epochs,
        drop=args.drop,
        base_model=args.base_model,
    )


if __name__ == "__main__":
    main()