"""
NER Service — deteccion de entidades en texto con spaCy.

Carga de forma perezosa el modelo spaCy entrenado en app/models/ner/ y
expone funciones de extraccion compatibles con el formato de campos del pipeline.

Si spaCy no esta instalado o el modelo no existe, is_ner_available() devuelve
False y extract_entities() devuelve lista vacia sin lanzar error.

Uso tipico
----------
from app.services.ner_service import is_ner_available, extract_entities, entities_to_fields

if is_ner_available():
    ents = extract_entities(ocr_text)
    extra_fields = entities_to_fields(ents)

Exports
-------
is_ner_available() -> bool
extract_entities(text) -> list[dict]
extract_entities_from_boxes(boxes) -> list[dict]
entities_to_fields(entities) -> list[dict]
reload_model() -> bool
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Rutas candidatas en orden de prioridad.
# 1. Variable de entorno NER_MODEL_PATH (override explícito)
# 2. app/models/trained/spacy_model/  (producción — generado por training_service)
# 3. app/models/ner/                  (legacy / copia manual)
_MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "models")


def _resolve_model_path() -> str:
    """Devuelve la primera ruta valida donde exista un modelo spaCy."""
    env_path = os.environ.get("NER_MODEL_PATH", "").strip()
    candidates = [
        env_path,
        os.path.join(_MODELS_DIR, "trained", "spacy_model"),
        os.path.join(_MODELS_DIR, "ner"),
    ]
    for c in candidates:
        if c and os.path.isdir(os.path.abspath(c)):
            return os.path.abspath(c)
    # Devolver la ruta de producción aunque no exista (para el mensaje de log)
    return os.path.abspath(os.path.join(_MODELS_DIR, "trained", "spacy_model"))


_NER_MODEL_PATH: str = _resolve_model_path()

_nlp = None            # modelo spaCy (carga perezosa)
_nlp_load_tried = False  # evita reintentar si ya fallo

# Mapeo etiqueta NER -> campo canonico del pipeline
_ENTITY_TO_FIELD: dict[str, str] = {
    "PERSON_NAME":    "nombre",
    "RFC":            "rfc",
    "CURP":           "curp",
    "NSS":            "nss",
    "CLABE":          "clabe",
    "ACCOUNT_NUMBER": "cuenta",
    "BANK":           "banco",
    "FOLIO":          "folio",
    "DATE":           "fecha",
    "AMOUNT":         "monto",
    "ADDRESS":        "domicilio",
}

_LABEL_DISPLAY: dict[str, str] = {
    "PERSON_NAME":    "Nombre",
    "RFC":            "RFC",
    "CURP":           "CURP",
    "NSS":            "NSS",
    "CLABE":          "CLABE",
    "ACCOUNT_NUMBER": "Cuenta",
    "BANK":           "Banco",
    "FOLIO":          "Folio",
    "DATE":           "Fecha",
    "AMOUNT":         "Monto",
    "ADDRESS":        "Domicilio",
}


def _load_nlp():
    global _nlp, _nlp_load_tried
    if _nlp_load_tried:
        return _nlp
    _nlp_load_tried = True

    # Verificar que spaCy este instalado
    try:
        import spacy  # noqa: F401
    except ImportError:
        logger.info(
            "spaCy no esta instalado. Para NER ejecuta: pip install spacy"
        )
        return None

    model_path = os.path.abspath(_NER_MODEL_PATH)
    if not os.path.isdir(model_path):
        logger.info(
            "Modelo NER no encontrado en %s. "
            "Ejecuta tools/train_ner.py para entrenarlo.",
            model_path,
        )
        return None

    try:
        import spacy
        _nlp = spacy.load(model_path)
        logger.info("Modelo NER cargado desde %s", model_path)
    except Exception as exc:
        logger.warning("No se pudo cargar el modelo NER: %s", exc)
        _nlp = None

    return _nlp


def is_ner_available() -> bool:
    """True si spaCy esta instalado y el modelo NER esta listo."""
    return _load_nlp() is not None


def extract_entities(text: str) -> list[dict[str, Any]]:
    """Extrae entidades del texto usando el modelo NER spaCy.

    Parameters
    ----------
    text : texto OCR o nativo del documento.

    Returns
    -------
    list[dict]  cada entidad tiene: {text, label, start, end, confidence}
    Lista vacia si NER no esta disponible o el texto es vacio.
    """
    nlp = _load_nlp()
    if nlp is None or not text:
        return []

    try:
        # Limitar a 50k chars para evitar documentos enormes
        doc = nlp(text[:50_000])
        return [
            {
                "text":       ent.text,
                "label":      ent.label_,
                "start":      ent.start_char,
                "end":        ent.end_char,
                "confidence": round(float(getattr(ent, "score_", 0.75) or 0.75), 4),
            }
            for ent in doc.ents
        ]
    except Exception as exc:
        logger.warning("extract_entities() fallo: %s", exc)
        return []


def extract_entities_from_boxes(boxes: list[dict]) -> list[dict[str, Any]]:
    """Extrae entidades concatenando el texto de los bounding boxes.

    Parameters
    ----------
    boxes : lista de boxes del OCR — cada uno con al menos {"text": str}.

    Returns
    -------
    list[dict]  misma estructura que extract_entities().
    """
    if not boxes:
        return []
    text = " ".join(str(box.get("text", "") or "") for box in boxes if box.get("text"))
    return extract_entities(text)


def entities_to_fields(entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convierte entidades NER al formato de campos del pipeline.

    Returns
    -------
    list[dict]  lista de campos:
        {key, label, value, confidence, valid, validation_errors, source}
    """
    fields: list[dict] = []
    for ent in entities:
        ner_label = str(ent.get("label", "") or "")
        field_key = _ENTITY_TO_FIELD.get(ner_label)
        if not field_key:
            continue
        value = str(ent.get("text", "") or "").strip()
        if not value:
            continue
        fields.append({
            "key":               field_key,
            "label":             _LABEL_DISPLAY.get(ner_label, field_key),
            "value":             value,
            "confidence":        round(float(ent.get("confidence", 0.70)), 4),
            "valid":             True,
            "validation_errors": [],
            "source":            "ner",
        })
    return fields


def reload_model() -> bool:
    """Fuerza la recarga del modelo (util despues de un re-entrenamiento).

    Vuelve a resolver la ruta del modelo por si fue actualizado.
    Returns True si el modelo se cargo correctamente.
    """
    global _nlp, _nlp_load_tried, _NER_MODEL_PATH
    _nlp = None
    _nlp_load_tried = False
    _NER_MODEL_PATH = _resolve_model_path()
    return is_ner_available()


def preload_model() -> bool:
    """Precarga el modelo NER en startup.

    Llama a is_ner_available() para forzar la carga perezosa y registrar
    el resultado en los logs de arranque.  Devuelve True si el modelo
    quedo listo para usar.
    """
    available = is_ner_available()
    if available:
        logger.info(
            "Modelo NER listo en: %s",
            _NER_MODEL_PATH,
        )
    else:
        logger.info(
            "Modelo NER no disponible en startup (%s). "
            "Entrena con training_service.train_ner_model() para activarlo.",
            _NER_MODEL_PATH,
        )
    return available
