"""
app/services/training_service.py
=================================
Servicio de entrenamiento NER spaCy — llamable desde la API Python.

Encapsula la logica de entrenamiento del modelo NER, expone funciones
async compatibles con FastAPI y devuelve resultados estructurados.

Flujo
-----
1. load_or_build_dataset(config)  -> carga/construye dataset NER
2. train_ner_model(config)        -> async, corre _train_sync en executor
3. _train_sync(config, examples)  -> loop de entrenamiento spaCy (CPU-bound)
4. reload_ner_service()           -> recarga ner_service con el modelo nuevo

Rutas por defecto
-----------------
Dataset cache  : dataset/cache/ner_training_data.json
Modelo output  : app/models/trained/spacy_model/
Mejor checkpoint: app/models/trained/spacy_model/best/
Espejo ner_svc  : app/models/ner/  (para que ner_service.reload_model() funcione)

Exports
-------
TrainingConfig
TrainingResult
train_ner_model(config)  -> TrainingResult        (async)
load_or_build_dataset(config) -> list             (sync)
get_training_status()    -> dict                  (sync)
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# ✅ FIX: compounding viene de thinc.api en spaCy 3.x
from thinc.api import compounding

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rutas base
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_APP_DIR = os.path.abspath(os.path.join(_HERE, ".."))
_ROOT = os.path.abspath(os.path.join(_APP_DIR, ".."))

_DEFAULT_OUTPUT = os.path.join(_APP_DIR, "models", "trained", "spacy_model")
_DEFAULT_MANIFEST = os.path.join(_ROOT, "dataset", "manifests", "dataset_index.json")
_DEFAULT_CACHE = os.path.join(_ROOT, "dataset", "cache", "ner_training_data.json")

# ---------------------------------------------------------------------------
# Estado global del servicio (simple, sin locks de hilo)
# ---------------------------------------------------------------------------
_state: dict[str, Any] = {
    "in_progress": False,
    "last_result": None,
    "started_at": None,
}


# ---------------------------------------------------------------------------
# Configuracion y resultado
# ---------------------------------------------------------------------------

@dataclass
class TrainingConfig:
    """Parametros de entrenamiento NER."""
    manifest_path: str = _DEFAULT_MANIFEST
    output_dir: str = _DEFAULT_OUTPUT
    cache_path: str = _DEFAULT_CACHE
    epochs: int = 20
    drop: float = 0.3
    dev_ratio: float = 0.2
    base_model: str | None = None
    force_rebuild: bool = False
    seed: int = 42
    # Si True, copia el modelo a app/models/ner/ y recarga ner_service
    reload_ner_service: bool = True


@dataclass
class TrainingResult:
    """Resultado del entrenamiento NER."""
    success: bool
    message: str
    model_path: str = ""
    examples_total: int = 0
    examples_train: int = 0
    examples_dev: int = 0
    best_f: float = 0.0
    best_precision: float = 0.0
    best_recall: float = 0.0
    duration_seconds: float = 0.0
    epoch_scores: list[dict] = field(default_factory=list)
    label_distribution: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "message": self.message,
            "model_path": self.model_path,
            "examples_total": self.examples_total,
            "examples_train": self.examples_train,
            "examples_dev": self.examples_dev,
            "metrics": {
                "best_f": round(self.best_f, 4),
                "best_precision": round(self.best_precision, 4),
                "best_recall": round(self.best_recall, 4),
            },
            "duration_seconds": round(self.duration_seconds, 1),
            "epoch_scores": self.epoch_scores,
            "label_distribution": self.label_distribution,
        }


# ---------------------------------------------------------------------------
# Dataset helpers
# ---------------------------------------------------------------------------

def load_or_build_dataset(config: TrainingConfig) -> list[tuple]:
    """
    Devuelve la lista de ejemplos NER (text, annotations).

    Carga desde cache si existe, o construye desde el dataset etiquetado.
    Con force_rebuild=True siempre reconstruye.
    """
    from app.training.ner_data_builder import (
        build_ner_dataset,
        load_ner_dataset,
        save_ner_dataset,
    )

    cache_path = config.cache_path
    if not config.force_rebuild and os.path.exists(cache_path):
        logger.info("Cargando dataset NER desde cache: %s", cache_path)
        examples = load_ner_dataset(cache_path)
        logger.info("  %d ejemplos cargados desde cache", len(examples))
        return examples

    logger.info("Construyendo dataset NER desde: %s", config.manifest_path)
    examples = build_ner_dataset(config.manifest_path)
    if not examples:
        logger.warning("No se construyeron ejemplos NER — verifica el dataset.")
        return []

    cache_dir = os.path.dirname(cache_path)
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
    save_ner_dataset(examples, cache_path)
    logger.info("  %d ejemplos guardados en cache: %s", len(examples), cache_path)
    return examples


def _label_distribution(examples: list[tuple]) -> dict[str, int]:
    counts: Counter = Counter()
    for _, annotations in examples:
        for _, _, label in annotations.get("entities", []):
            counts[label] += 1
    return dict(counts)


def _split_dataset(
    examples: list[tuple],
    dev_ratio: float,
    seed: int,
) -> tuple[list[tuple], list[tuple]]:
    rng = random.Random(seed)
    shuffled = list(examples)
    rng.shuffle(shuffled)
    split = max(1, int(len(shuffled) * (1 - dev_ratio)))
    return shuffled[:split], shuffled[split:]


def _make_spacy_examples(nlp: Any, data: list[tuple]) -> list:
    from spacy.training import Example
    valid = []
    for text, annotations in data:
        try:
            doc = nlp.make_doc(text)
            ex = Example.from_dict(doc, annotations)
            valid.append(ex)
        except Exception:
            pass
    return valid


# ---------------------------------------------------------------------------
# Entrenamiento (CPU-bound, bloqueante)
# ---------------------------------------------------------------------------

def _train_sync(config: TrainingConfig, examples: list[tuple]) -> TrainingResult:
    """
    Ejecuta el entrenamiento spaCy de forma sincrona.
    Diseñado para correr en un thread executor desde train_ner_model().
    """
    import spacy

    t0 = time.time()
    label_dist = _label_distribution(examples)

    if not examples:
        return TrainingResult(
            success=False,
            message="Sin ejemplos de entrenamiento. Verifica el dataset.",
            label_distribution=label_dist,
        )

    train_data, dev_data = _split_dataset(examples, config.dev_ratio, config.seed)
    logger.info("Split — train: %d / dev: %d", len(train_data), len(dev_data))

    # -----------------------------------------------------------------------
    # Construir modelo
    # -----------------------------------------------------------------------
    if config.base_model:
        try:
            nlp = spacy.load(config.base_model)
            logger.info("Fine-tuning sobre: %s", config.base_model)
            if "ner" not in nlp.pipe_names:
                nlp.add_pipe("ner", last=True)
        except Exception as exc:
            logger.warning(
                "No se pudo cargar %s: %s. Usando modelo blank.",
                config.base_model, exc,
            )
            nlp = spacy.blank("es")
            nlp.add_pipe("ner")
    else:
        nlp = spacy.blank("es")
        nlp.add_pipe("ner")

    # Registrar etiquetas NER
    from app.training.ner_data_builder import NER_LABELS
    ner = nlp.get_pipe("ner")
    for label in NER_LABELS:
        ner.add_label(label)

    train_examples = _make_spacy_examples(nlp, train_data)
    dev_examples = _make_spacy_examples(nlp, dev_data)
    logger.info(
        "Ejemplos validos: train=%d dev=%d",
        len(train_examples), len(dev_examples)
    )

    if not train_examples:
        return TrainingResult(
            success=False,
            message="Todos los ejemplos son invalidos (spans mal alineados).",
            examples_total=len(examples),
            examples_train=len(train_data),
            examples_dev=len(dev_data),
            label_distribution=label_dist,
        )

    nlp.initialize(lambda: iter(train_examples))

    # -----------------------------------------------------------------------
    # Loop de entrenamiento
    # -----------------------------------------------------------------------
    best_f = 0.0
    best_p = 0.0
    best_r = 0.0
    epoch_scores: list[dict] = []
    best_path = os.path.join(config.output_dir, "best")
    rng = random.Random(config.seed)

    logger.info("Entrenando %d epocas (drop=%.2f)...", config.epochs, config.drop)

    for epoch in range(1, config.epochs + 1):
        rng.shuffle(train_examples)
        losses: dict = {}
        # ✅ FIX: compounding importado desde thinc.api al inicio del archivo
        batches = spacy.util.minibatch(
            train_examples,
            size=compounding(4.0, 32.0, 1.001),
        )
        for batch in batches:
            nlp.update(batch, drop=config.drop, losses=losses)

        # Evaluar cada 5 epocas y en la ultima
        if epoch % 5 == 0 or epoch == config.epochs:
            if dev_examples:
                scores = nlp.evaluate(dev_examples)
                ner_f = scores.get("ents_f", 0.0)
                ner_p = scores.get("ents_p", 0.0)
                ner_r = scores.get("ents_r", 0.0)
            else:
                ner_f = ner_p = ner_r = 0.0

            elapsed = time.time() - t0
            entry = {
                "epoch": epoch,
                "loss": round(losses.get("ner", 0.0), 4),
                "precision": round(ner_p, 4),
                "recall": round(ner_r, 4),
                "f1": round(ner_f, 4),
                "elapsed_s": round(elapsed, 1),
            }
            epoch_scores.append(entry)
            logger.info(
                "  Epoca %3d/%d | loss=%.3f | P=%.3f R=%.3f F=%.3f | %.0fs",
                epoch, config.epochs,
                entry["loss"], ner_p, ner_r, ner_f, elapsed,
            )

            if ner_f > best_f:
                best_f = ner_f
                best_p = ner_p
                best_r = ner_r
                os.makedirs(best_path, exist_ok=True)
                nlp.to_disk(best_path)

    # -----------------------------------------------------------------------
    # Guardar modelo final
    # -----------------------------------------------------------------------
    os.makedirs(config.output_dir, exist_ok=True)
    nlp.to_disk(config.output_dir)
    elapsed_total = time.time() - t0
    logger.info("Modelo guardado en: %s | F=%.4f | %.0fs", config.output_dir, best_f, elapsed_total)

    return TrainingResult(
        success=True,
        message="Entrenamiento completado correctamente.",
        model_path=config.output_dir,
        examples_total=len(examples),
        examples_train=len(train_examples),
        examples_dev=len(dev_examples),
        best_f=best_f,
        best_precision=best_p,
        best_recall=best_r,
        duration_seconds=round(elapsed_total, 1),
        epoch_scores=epoch_scores,
        label_distribution=label_dist,
    )


# ---------------------------------------------------------------------------
# Reload ner_service tras entrenar
# ---------------------------------------------------------------------------

def reload_ner_service() -> bool:
    """
    Indica a ner_service que descargue y recargue el modelo NER.
    Devuelve True si el reload fue exitoso.
    """
    try:
        from app.services import ner_service
        return ner_service.reload_model()
    except Exception as exc:
        logger.warning("No se pudo recargar ner_service: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Punto de entrada async (para la API)
# ---------------------------------------------------------------------------

async def train_ner_model(config: TrainingConfig | None = None) -> TrainingResult:
    """
    Entrena el modelo NER de forma async-compatible.

    El entrenamiento real corre en un executor de threads para no bloquear
    el event loop de FastAPI.

    Parameters
    ----------
    config : TrainingConfig, opcional.
        Si se omite se usan los valores por defecto.

    Returns
    -------
    TrainingResult
    """
    if config is None:
        config = TrainingConfig()

    if _state["in_progress"]:
        return TrainingResult(
            success=False,
            message="Ya hay un entrenamiento en progreso. Intenta despues.",
        )

    # Cargar dataset en el hilo actual (es rapido si usa cache)
    examples = load_or_build_dataset(config)
    if not examples:
        return TrainingResult(
            success=False,
            message="No se encontraron ejemplos para entrenar.",
        )

    # Marcar como en progreso
    _state["in_progress"] = True
    _state["started_at"] = time.time()
    _state["last_result"] = None

    result = TrainingResult(success=False, message="Entrenamiento no iniciado.")
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            _train_sync,
            config,
            examples,
        )
    except Exception as exc:
        logger.exception("Error durante el entrenamiento NER")
        result = TrainingResult(
            success=False,
            message=f"Error inesperado: {exc}",
        )
    finally:
        _state["in_progress"] = False
        _state["last_result"] = result

    # Recargar ner_service si el entrenamiento fue exitoso
    if result.success and config.reload_ner_service:
        reload_ner_service()

    return result


# ---------------------------------------------------------------------------
# Estado del servicio (para endpoint de estado)
# ---------------------------------------------------------------------------

def get_training_status() -> dict:
    """Devuelve el estado actual del servicio de entrenamiento."""
    result = _state.get("last_result")
    started_at = _state.get("started_at")
    return {
        "in_progress": _state["in_progress"],
        "elapsed_seconds": round(time.time() - started_at, 1) if started_at and _state["in_progress"] else None,
        "last_result": result.to_dict() if result is not None else None,
    }