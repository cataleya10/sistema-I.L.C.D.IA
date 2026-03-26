"""
Construccion de datos de entrenamiento spaCy NER a partir del dataset etiquetado.
"""
from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

NER_LABELS: list[str] = [
    "PERSON_NAME", "RFC", "CURP", "NSS", "CLABE",
    "ACCOUNT_NUMBER", "BANK", "FOLIO", "DATE", "AMOUNT", "ADDRESS",
]

LABEL_FOR_FIELD: dict[str, str] = {
    "nombre":              "PERSON_NAME",
    "titular":             "PERSON_NAME",
    "nombre_beneficiario": "PERSON_NAME",
    "nombre_asegurado":    "PERSON_NAME",
    "nombre_titular":      "PERSON_NAME",
    "apellido_paterno":    "PERSON_NAME",
    "apellido_materno":    "PERSON_NAME",
    "curp":                "CURP",
    "rfc":                 "RFC",
    "nss":                 "NSS",
    "clabe":               "CLABE",
    "cuenta":              "ACCOUNT_NUMBER",
    "banco":               "BANK",
    "fecha_nacimiento":    "DATE",
    "fecha_corte":         "DATE",
    "fecha_emision":       "DATE",
    "fecha_registro":      "DATE",
    "monto":               "AMOUNT",
    "importe":             "AMOUNT",
    "total":               "AMOUNT",
    "saldo":               "AMOUNT",
    "folio":               "FOLIO",
    "numero_acta":         "FOLIO",
    "domicilio":           "ADDRESS",
}

CONTEXT_TEMPLATES: dict[str, list[str]] = {
    "clabe": ["CLABE: {value}", "CLABE interbancaria: {value}", "Cuenta de retiro: {value}", "Clave CLABE: {value}"],
    "cuenta": ["No. de Cuenta: {value}", "Numero de cuenta: {value}", "Cuenta: {value}"],
    "banco": ["Banco: {value}", "Banco Destino: {value}", "Institucion bancaria: {value}"],
    "titular": ["Titular de la cuenta: {value}", "Nombre del Cliente: {value}", "Titular: {value}"],
    "nombre": ["Nombre: {value}", "Nombre del trabajador: {value}", "Nombre completo: {value}"],
    "nombre_asegurado":    ["Nombre del asegurado: {value}", "Nombre: {value}"],
    "nombre_beneficiario": ["Nombre del beneficiario: {value}", "Nombre: {value}"],
    "nombre_titular":      ["Nombre del titular: {value}", "Titular: {value}"],
    "apellido_paterno":    ["Apellido Paterno: {value}"],
    "apellido_materno":    ["Apellido Materno: {value}"],
    "rfc":  ["RFC: {value}", "R.F.C.: {value}", "Registro Federal de Contribuyentes: {value}"],
    "curp": ["CURP: {value}", "C.U.R.P.: {value}", "Clave Unica de Registro de Poblacion: {value}"],
    "nss":  ["NSS: {value}", "Numero de Seguridad Social: {value}", "No. de Seguridad Social: {value}"],
    "fecha_nacimiento": ["Fecha de nacimiento: {value}", "Nacimiento: {value}"],
    "fecha_corte":      ["Fecha de corte: {value}", "Fecha de creacion: {value}"],
    "fecha_emision":    ["Fecha de emision: {value}", "Fecha de expedicion: {value}"],
    "fecha_registro":   ["Fecha de registro: {value}", "Fecha: {value}"],
    "monto":   ["Importe: {value}", "Monto: {value}", "Total: {value}"],
    "importe": ["Importe: {value}", "Importe total: {value}"],
    "total":   ["Total: {value}", "Total a pagar: {value}"],
    "saldo":   ["Saldo: {value}", "Saldo disponible: {value}"],
    "domicilio": ["Domicilio: {value}", "Domicilio fiscal: {value}", "Direccion: {value}"],
    "cp":          ["C.P.: {value}", "Codigo Postal: {value}"],
    "folio":       ["Folio: {value}", "No. de Folio: {value}"],
    "numero_acta": ["Numero de acta: {value}", "No. de Acta: {value}"],
}

WINDOW_RADIUS: int = 280


def find_spans(text: str, value: str) -> list[tuple[int, int]]:
    if not text or not value or len(value.strip()) < 2:
        return []
    v = value.strip()
    pattern = re.compile(re.escape(v), re.IGNORECASE)
    spans = [(m.start(), m.end()) for m in pattern.finditer(text)]
    if not spans:
        v_compact = re.sub(r"\s+", " ", v)
        text_compact = re.sub(r"\s+", " ", text)
        for m in re.compile(re.escape(v_compact), re.IGNORECASE).finditer(text_compact):
            idx = text.upper().find(v_compact.upper())
            if idx >= 0:
                spans.append((idx, idx + len(v_compact)))
                break
    seen: set[tuple[int, int]] = set()
    result: list[tuple[int, int]] = []
    for sp in spans:
        if sp not in seen:
            seen.add(sp)
            result.append(sp)
    return result


def _overlaps(span: tuple[int, int], used: list[tuple[int, int]]) -> bool:
    s, e = span
    return any(not (e <= us or s >= ue) for us, ue in used)


def build_ner_example(text: str, fields: dict[str, str]) -> tuple | None:
    if not text or not fields:
        return None
    entities: list[tuple[int, int, str]] = []
    used_spans: list[tuple[int, int]] = []
    for field, value in fields.items():
        if not value or not isinstance(value, str):
            continue
        value = value.strip()
        if len(value) < 2:
            continue
        label = LABEL_FOR_FIELD.get(field)
        if not label:
            continue
        for span in find_spans(text, value):
            if not _overlaps(span, used_spans):
                entities.append((span[0], span[1], label))
                used_spans.append(span)
                break
    if not entities:
        return None
    return (text, {"entities": sorted(entities)})


def load_labeled_docs(
    manifest_path: str,
    labeled_base_dir: str | None = None,
) -> list[dict]:
    manifest_path = os.path.abspath(manifest_path)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(manifest_path)))
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            index = json.load(f)
    except Exception as exc:
        logger.error("No se pudo leer manifest %s: %s", manifest_path, exc)
        return []
    entries = index.get("entries", [])
    if not entries:
        logger.warning("dataset_index.json no tiene clave 'entries'")
        return []
    labeled_root = labeled_base_dir or os.path.join(project_root, "dataset", "labeled")
    docs: list[dict] = []
    for entry in entries:
        labeled_flag = entry.get("labeled", False)
        if isinstance(labeled_flag, str):
            labeled_flag = labeled_flag.lower() == "true"
        if not labeled_flag:
            continue
        label_path_rel = entry.get("label_path", "")
        label_path_full = ""
        if label_path_rel:
            candidate = os.path.join(project_root, label_path_rel)
            if os.path.exists(candidate):
                label_path_full = candidate
        if not label_path_full:
            doc_id = entry.get("document_id", "")
            tipo = entry.get("tipo_documento", "")
            candidate2 = os.path.join(labeled_root, tipo, f"{doc_id}.json")
            if os.path.exists(candidate2):
                label_path_full = candidate2
        if not label_path_full:
            logger.debug("Label file not found for %s", entry.get("document_id"))
            continue
        try:
            with open(label_path_full, "r", encoding="utf-8") as f:
                label_data = json.load(f)
        except Exception as exc:
            logger.warning("Error leyendo %s: %s", label_path_full, exc)
            continue
        expected = label_data.get("expected_fields", {})
        if not isinstance(expected, dict):
            continue
        filtered = {k: v for k, v in expected.items() if isinstance(v, str) and v.strip()}
        if not filtered:
            continue
        pdf_rel = entry.get("pdf_path", "")
        pdf_full = os.path.join(project_root, pdf_rel) if pdf_rel else ""
        docs.append({
            **entry,
            "expected_fields": filtered,
            "label_file":      label_path_full,
            "pdf_full_path":   pdf_full,
        })
    logger.info("Cargados %d docs etiquetados de %s", len(docs), manifest_path)
    return docs


def _clean_pdf_text(text: str) -> str:
    lines = text.split("\n")
    cleaned: list[str] = []
    blank_run = 0
    for line in lines:
        line = re.sub(r"[ \t]+", " ", line).strip()
        if not line:
            blank_run += 1
            if blank_run <= 1:
                cleaned.append("")
        else:
            blank_run = 0
            cleaned.append(line)
    return "\n".join(cleaned).strip()


def _extract_pdf_pages(pdf_path: str) -> list[str]:
    try:
        import fitz  # type: ignore[import]
        pages: list[str] = []
        with fitz.open(pdf_path) as pdf:
            for page in pdf:
                # ✅ FIX: str() garantiza que siempre sea str, compatible PyMuPDF 1.27.x
                raw = str(page.get_text() or "")  # type: ignore[attr-defined]
                cleaned = _clean_pdf_text(raw)
                if cleaned:
                    pages.append(cleaned)
        return pages
    except Exception as exc:
        logger.debug("PyMuPDF fallo para %s: %s", pdf_path, exc)
        return []


def _extract_pdf_text(pdf_path: str) -> str:
    return "\n\n".join(_extract_pdf_pages(pdf_path))


def _extract_context_window(text: str, value: str) -> str:
    spans = find_spans(text, value)
    if not spans:
        return ""
    start, end = spans[0]
    win_s = max(0, start - WINDOW_RADIUS)
    win_e = min(len(text), end + WINDOW_RADIUS)
    while win_s > 0 and text[win_s - 1] != "\n":
        win_s -= 1
    while win_e < len(text) and text[win_e] != "\n":
        win_e += 1
    return text[win_s:win_e].strip()


def _build_synthetic_text(fields: dict[str, str]) -> tuple | None:
    lines: list[str] = []
    line_meta: list[tuple[str, str]] = []
    for field, value in fields.items():
        if not value or not isinstance(value, str):
            continue
        value = value.strip()
        if len(value) < 2:
            continue
        label = LABEL_FOR_FIELD.get(field)
        if not label:
            continue
        templates = CONTEXT_TEMPLATES.get(field)
        if not templates:
            keyword = field.replace("_", " ").upper()
            templates = [f"{keyword}: {{value}}"]
        line = templates[0].format(value=value)
        lines.append(line)
        line_meta.append((value, label))
    if not lines:
        return None
    text = "\n".join(lines)
    entities: list[tuple[int, int, str]] = []
    used: list[tuple[int, int]] = []
    for value, label in line_meta:
        for sp in find_spans(text, value):
            if not _overlaps(sp, used):
                entities.append((sp[0], sp[1], label))
                used.append(sp)
                break
    if not entities:
        return None
    return (text, {"entities": sorted(entities)})


def build_ner_dataset(
    manifest_path: str,
    labeled_base_dir: str | None = None,
    ocr_texts: dict[str, str] | None = None,
) -> list[tuple]:
    docs = load_labeled_docs(manifest_path, labeled_base_dir)
    if not docs:
        logger.warning("No se cargaron docs etiquetados; dataset NER vacio")
        return []
    examples: list[tuple] = []
    seen_texts: set[str] = set()
    skipped = 0

    def _add(ex: tuple | None) -> None:
        if ex is None:
            return
        text, _ = ex
        key = text[:200]
        if key not in seen_texts:
            seen_texts.add(key)
            examples.append(ex)

    for doc in docs:
        doc_id = doc.get("document_id", "")
        fields: dict[str, str] = doc.get("expected_fields", {})
        synth = _build_synthetic_text(fields)
        if synth:
            _add(synth)
        else:
            skipped += 1
        pages: list[str] = []
        if ocr_texts and doc_id in ocr_texts:
            pages = [_clean_pdf_text(ocr_texts[doc_id])]
        else:
            pdf_path = doc.get("pdf_full_path", "")
            if pdf_path and os.path.exists(pdf_path):
                pages = _extract_pdf_pages(pdf_path)
        if not pages:
            continue
        for page_text in pages:
            if len(page_text.strip()) < 20:
                continue
            ex = build_ner_example(page_text, fields)
            if ex:
                _add(ex)
        full_text = "\n\n".join(pages)
        windows_seen: set[str] = set()
        for field, value in fields.items():
            if not value or not isinstance(value, str) or len(value.strip()) < 3:
                continue
            if not LABEL_FOR_FIELD.get(field):
                continue
            window = _extract_context_window(full_text, value.strip())
            if not window or len(window) < 10 or window in windows_seen:
                continue
            windows_seen.add(window)
            ex = build_ner_example(window, fields)
            if ex:
                _add(ex)

    logger.info("Dataset NER: %d ejemplos construidos, %d sin entidades utiles", len(examples), skipped)
    return examples


def save_ner_dataset(examples: list[tuple], output_path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    serializable = [
        {"text": ex[0], "entities": list(ex[1]["entities"])}
        for ex in examples
    ]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    logger.info("Guardados %d ejemplos NER en %s", len(serializable), output_path)


def load_ner_dataset(input_path: str) -> list[tuple]:
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [
            (item["text"], {"entities": [tuple(e) for e in item["entities"]]})
            for item in data
            if item.get("text") and item.get("entities") is not None
        ]
    except Exception as exc:
        logger.error("Error cargando NER dataset desde %s: %s", input_path, exc)
        return []
