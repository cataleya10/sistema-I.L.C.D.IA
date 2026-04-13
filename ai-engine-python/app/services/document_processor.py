import json
import pandas as pd
from collections import Counter
def export_table_to_csv_excel(columns, rows, csv_path=None, excel_path=None):
    """
    Exporta una tabla (columnas, filas) a CSV y/o Excel usando pandas.
    columns: lista de nombres de columna
    rows: lista de dicts (clave: columna)
    csv_path: ruta para guardar CSV (opcional)
    excel_path: ruta para guardar Excel (opcional)
    Devuelve: (csv_str, excel_bytes)
    """
    df = pd.DataFrame(rows, columns=columns)
    csv_str = df.to_csv(index=False, encoding="utf-8-sig")
    excel_bytes = None
    if excel_path or not csv_path:
        import io
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False)
        excel_bytes = output.getvalue()
        if excel_path:
            with open(excel_path, "wb") as f:
                f.write(excel_bytes)
    if csv_path:
        with open(csv_path, "w", encoding="utf-8-sig") as f:
            f.write(csv_str)
    return csv_str, excel_bytes
import re
import unicodedata
from pathlib import Path
import time
import logging
from app.schemas.process import (
    ProcessResponse, DocumentField, ProcessMeta, ExtractedTable,
    CampoExtraido, TablaExtraida, MetadataDocumento, ValidationSummary,
)
from app.core.config import settings
from app.pipelines.preprocess import preprocess
from app.pipelines.ocr import run_ocr
from app.pipelines.classify import classify_document
from app.pipelines.extract import extract_fields
from app.pipelines.validate import validate_fields
from app.services.online_learning import learn_from_processed_document
from app.utils.table_utils import to_canonical_rows, table_quality_score, remap_to_target_payment_schema
from app.pipelines.table_postprocess import postprocess_payment_table

logger = logging.getLogger(__name__)

# Tipos donde se aplica normalización de importes en tablas
_PAYMENT_DOC_TYPES = frozenset({
    "DATOS_BANCARIOS", "COMPROBANTE_DE_PAGO", "NOMINA",
    "ESTADO_DE_CUENTA", "FACTURA",
})

# Tipos donde la tabla es el contenido principal (su ausencia es un error)
_TABLE_REQUIRED_DOC_TYPES = frozenset({
    "DATOS_BANCARIOS", "COMPROBANTE_DE_PAGO", "NOMINA", "FACTURA",
})

# Tipos que usan el motor geométrico + extractor especializado (get_doc_extractor).
# Incluye bancarios, nómina y CFDI/factura.
_GEO_EXTRACT_DOC_TYPES = frozenset({
    "DATOS_BANCARIOS", "COMPROBANTE_DE_PAGO", "ESTADO_DE_CUENTA",
    "NOMINA", "CFDI", "FACTURA",
})

# Tipos bancarios que además aplican remapeo de esquema (alias por compatibilidad)
_BANK_REMAP_DOC_TYPES = frozenset({
    "DATOS_BANCARIOS", "COMPROBANTE_DE_PAGO", "ESTADO_DE_CUENTA", "FACTURA",
})


def _detect_bank_from_fields(fields: list[dict]) -> str | None:
    """Detecta el banco a partir de los campos extraídos."""
    for key in ("banco", "banco_receptor", "banco_destino", "institucion"):
        for f in fields:
            if f.get("key") == key and f.get("value"):
                return str(f["value"]).upper()
    return None


def _table_content_sig(cols: list[str], rows: list[dict]) -> str:
    """Huella de contenido para deduplicar tablas equivalentes."""
    col_sig = "|".join(sorted(cols))
    row_sigs = sorted(
        "|".join(f"{k}={v}" for k, v in sorted(r.items()) if v)
        for r in rows[:5]
    )
    return col_sig + "##" + "||".join(row_sigs)


def _process_all_tables(
    pdf_tables: list[list[list[str]]],
    doc_type: str,
    bank: str | None,
    fields: list[dict],
    ocr_boxes: list[dict] | None = None,
) -> list[ExtractedTable]:
    """
    Procesa todas las tablas crudas del PDF y devuelve tablas canónicas limpias.

    Pipeline:
      1. Si es doc bancario Y hay ocr_boxes → geometric detector (Textract-like)
         + extractor especializado por banco (Opción B).
      2. Para el resto → canonicalización genérica + post-proceso + remapeo.
    """
    is_payment = doc_type in _PAYMENT_DOC_TYPES
    results: list[ExtractedTable] = []
    seen_sigs: set[str] = set()

    # ── Ruta 1: Geometric detector + extractor especializado por doc_type/banco ─
    if doc_type in _GEO_EXTRACT_DOC_TYPES and ocr_boxes:
        try:
            from app.pipelines.extract.geometric_detector import detect_all_table_grids
            from app.pipelines.extract.bank_extractors import get_doc_extractor

            grids = detect_all_table_grids(ocr_boxes)
            extractor = get_doc_extractor(doc_type, bank)

            for grid in grids:
                if grid.n_rows < 2:
                    continue
                try:
                    geo_cols, geo_rows = extractor.extract(grid)
                except Exception:
                    logger.debug("bank_extractor.extract falló", exc_info=True)
                    geo_cols, geo_rows = [], []

                if not geo_cols or not geo_rows:
                    continue

                quality_report = table_quality_score(geo_cols, geo_rows)
                quality = float(
                    quality_report.get("quality", 0)
                    if isinstance(quality_report, dict) else quality_report
                )
                sig = _table_content_sig(geo_cols, geo_rows)
                if sig in seen_sigs:
                    continue
                seen_sigs.add(sig)

                results.append(ExtractedTable(
                    columns=geo_cols,
                    rows=geo_rows,
                    quality=round(quality, 1),
                    row_count=len(geo_rows),
                    doc_type_hint=doc_type,
                ))
                logger.info(
                    "[GEO+DOC] tabla extraída: doc_type=%s banco=%s cols=%s filas=%d quality=%.1f",
                    doc_type, bank or "N/A", geo_cols, len(geo_rows), quality,
                )

            if results:
                return results
            logger.info("[GEO+DOC] sin resultados del detector geométrico, usando ruta genérica")
        except Exception:
            logger.debug("Pipeline geométrico falló, usando ruta genérica", exc_info=True)

    # ── Ruta 2: Canonicalización genérica (documentos no bancarios o fallback) ─
    if not pdf_tables:
        return results

    for raw_table in pdf_tables:
        if not raw_table or len(raw_table) < 2:
            continue
        try:
            canon_cols, canon_rows = to_canonical_rows(raw_table)
        except Exception:
            logger.debug("to_canonical_rows falló para tabla", exc_info=True)
            continue

        if not canon_cols or not canon_rows:
            continue

        # Post-proceso para documentos de pago (normalización de importes)
        if is_payment:
            try:
                canon_cols, canon_rows = postprocess_payment_table(canon_cols, canon_rows, bank=bank or "")
            except Exception:
                logger.debug("postprocess_payment_table falló", exc_info=True)

        # Remapeo al esquema bancario solo para dispersiones/transferencias, NO nómina
        if doc_type in _BANK_REMAP_DOC_TYPES:
            try:
                # remap devuelve (cols, rows, display_labels) — ignorar display_labels
                canon_cols, canon_rows, _ = remap_to_target_payment_schema(canon_cols, canon_rows, bank=bank or "")
            except Exception:
                logger.debug("remap_to_target_payment_schema falló", exc_info=True)

        # Quality gate
        quality_report = table_quality_score(canon_cols, canon_rows)
        quality = float(quality_report.get("quality", 0) if isinstance(quality_report, dict) else quality_report)
        if quality < 15 and len(canon_rows) < 2:
            logger.debug("Tabla descartada: quality=%.1f rows=%d", quality, len(canon_rows))
            continue

        # Dedup por contenido
        sig = _table_content_sig(canon_cols, canon_rows)
        if sig in seen_sigs:
            continue
        seen_sigs.add(sig)

        results.append(ExtractedTable(
            columns=canon_cols,
            rows=canon_rows,
            quality=round(quality, 1),
            row_count=len(canon_rows),
            doc_type_hint=doc_type,
        ))

    return results

SERVICE_TEXT_HINTS = {
    "TELMEX",
    "TELEFONOS DE MEXICO",
    "TELMEX-TEL",
    "RECIBO",
    "LINEA DE CAPTURA",
    "REFERENCIA UNICA",
    "NUMERO TELEFONICO",
    "PAGAR ANTES DE",
    "TOTAL A PAGAR",
    "NO. DE CUENTA",
    "NO DE CUENTA",
}

CSF_STRONG_HINTS = {
    "CONSTANCIA DE SITUACION FISCAL",
    "CEDULA DE IDENTIFICACION FISCAL",
    "ID CIF",
}

SERVICE_FILENAME_HINTS = {
    "TELMEX",
    "RECIBO",
    "COMPROBANTE",
    "DOMICILIO",
    "CFE",
    "TOTALPLAY",
    "IZZI",
    "MEGACABLE",
}


def _looks_like_xml(text: str) -> bool:
    """True si el texto parece ser contenido XML (CFDI)."""
    stripped = (text or "").lstrip()
    return stripped.startswith("<?xml") or stripped.startswith("<cfdi:")


def _looks_like_service_document(text: str, filename: str | None) -> bool:
    upper_text = (text or "").upper()
    upper_name = (filename or "").upper()
    if any(token in upper_text for token in SERVICE_TEXT_HINTS):
        return True
    if any(token in upper_name for token in SERVICE_FILENAME_HINTS):
        return True
    return False


def _looks_like_csf_document(text: str) -> bool:
    upper_text = (text or "").upper()
    if any(token in upper_text for token in CSF_STRONG_HINTS):
        return True
    return False


# Campos clave que señalan fuertemente un tipo de documento
_TYPE_SIGNAL_FIELDS: dict[str, frozenset[str]] = {
    "DATOS_BANCARIOS":  frozenset({"clabe", "cuenta", "banco", "titular", "fecha_corte"}),
    "NOMINA":           frozenset({"nss", "curp", "total_percepciones", "total_deducciones", "neto_pagar"}),
    "INE":              frozenset({"clave_elector", "curp", "seccion", "folio_credencial"}),
    "CURP":             frozenset({"curp", "entidad_registro", "anio_registro"}),
    "NSS":              frozenset({"nss", "fecha_inicio_cotizacion"}),
    "CONSTANCIA_SITUACION_FISCAL": frozenset({"rfc", "id_cif", "cp", "regimen"}),
    "ACTA_NACIMIENTO":  frozenset({"numero_acta", "libro", "tomo", "registro_civil"}),
    "COMPROBANTE_DOMICILIO": frozenset({"linea_captura", "periodo", "referencia_unica"}),
}

_MIN_SIGNAL_MATCH = 2  # mínimo de campos señal para reclasificar

_PAYMENT_TABLE_SIGNAL_COLUMNS = frozenset({
    "cuenta",
    "cuenta_beneficiario",
    "referencia",
    "importe",
    "nombre",
    "nombre_beneficiario",
    "banco_receptor",
    "concepto_pago",
    "clave_beneficiario",
    "dias_vigencia",
    "fecha_aplicacion",
})

_PAYMENT_TABLE_REQUIRED_CORE = frozenset({
    "cuenta",
    "referencia",
    "importe",
})


def _read_field_value(field: dict):
    value = field.get("corrected_value")
    if value in {None, ""}:
        value = field.get("value")
    return value


def _parse_structured_table_payload(field: dict) -> dict | None:
    raw_value = _read_field_value(field)
    payload: dict | None = None
    if isinstance(raw_value, dict):
        payload = raw_value
    elif isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        if isinstance(parsed, dict):
            payload = parsed

    if not isinstance(payload, dict):
        return None

    normalized_key = _normalize_key_name(str(field.get("key", "") or ""))
    if normalized_key == "pago_detalle" and isinstance(payload.get("table"), dict):
        return payload["table"]
    return payload


def _extract_structured_table_profile(fields: list[dict]) -> tuple[set[str], int]:
    best_columns: set[str] = set()
    best_rows = 0

    for field in fields:
        normalized_key = _normalize_key_name(str(field.get("key", "") or ""))
        if normalized_key not in {"tabla_celdas", "pago_detalle"}:
            continue

        payload = _parse_structured_table_payload(field)
        if not isinstance(payload, dict):
            continue

        columns_raw = payload.get("canonical_columns")
        rows_raw = payload.get("canonical_rows")
        if not isinstance(columns_raw, list) or not isinstance(rows_raw, list):
            continue

        columns = {
            _normalize_key_name(str(col or ""))
            for col in columns_raw
            if str(col or "").strip()
        }
        row_count = sum(1 for row in rows_raw if isinstance(row, dict) and row)
        if row_count <= 0 or not columns:
            continue

        if row_count > best_rows or (row_count == best_rows and len(columns) > len(best_columns)):
            best_columns = columns
            best_rows = row_count

    return best_columns, best_rows


def _looks_like_payment_table(fields: list[dict]) -> bool:
    columns, row_count = _extract_structured_table_profile(fields)
    if row_count <= 0 or not columns:
        return False

    core_hits = len(columns & _PAYMENT_TABLE_REQUIRED_CORE)
    signal_hits = len(columns & _PAYMENT_TABLE_SIGNAL_COLUMNS)
    return core_hits >= 2 and signal_hits >= 4


def _correct_doc_type_from_fields(
    doc_type: str,
    fields: list[dict],
    confidence: float,
) -> tuple[str, float, str | None]:
    """
    Corrige el tipo de documento si los campos extraídos señalan claramente
    un tipo distinto al clasificado.

    Solo actúa sobre GENERICO, UNKNOWN y tipos de baja confianza (< 0.75).
    Retorna (nuevo_tipo, nueva_confianza, warning_or_None).
    """
    extracted_keys = {f.get("key") for f in fields if f.get("value")}

    if doc_type == "DATOS_BANCARIOS" and _looks_like_payment_table(fields):
        # Don't reclassify synthetic single-transaction tables (SPEI receipts)
        _is_synthetic = any(
            '"synthetic_single_transaction"' in (f.get("value") or "")
            for f in fields
            if f.get("key") in ("tabla_celdas", "pago_detalle")
        )
        # Don't reclassify multi-row dispersions (canonical_rows > 1)
        _, row_count = _extract_structured_table_profile(fields)
        _is_multi_row_dispersion = row_count > 1
        bank_signals = len(extracted_keys & _TYPE_SIGNAL_FIELDS["DATOS_BANCARIOS"])
        if bank_signals < 5 and not _is_synthetic and not _is_multi_row_dispersion:
            new_conf = max(confidence, 0.82)
            warning = (
                "Tipo corregido DATOS_BANCARIOS→FACTURA por tabla estructurada "
                "de pago/dispersión."
            )
            logger.info("%s señales_bancarias=%d", warning, bank_signals)
            return "FACTURA", new_conf, warning

    if doc_type not in {"GENERICO", "UNKNOWN"} and confidence >= 0.75:
        return doc_type, confidence, None

    best_type = doc_type
    best_score = 0

    for candidate_type, signal_keys in _TYPE_SIGNAL_FIELDS.items():
        score = len(extracted_keys & signal_keys)
        if score > best_score and score >= _MIN_SIGNAL_MATCH:
            best_score = score
            best_type = candidate_type

    if best_type != doc_type:
        new_conf = min(0.82, 0.60 + best_score * 0.07)
        warning = f"Tipo corregido {doc_type}→{best_type} por campos extraídos (señales={best_score})."
        logger.info(warning)
        return best_type, new_conf, warning

    return doc_type, confidence, None


def _maybe_override_doc_type(doc_type: str, text: str, filename: str | None) -> tuple[str, str | None]:
    if doc_type == "CONSTANCIA_SITUACION_FISCAL":
        if _looks_like_service_document(text, filename) and not _looks_like_csf_document(text):
            return "COMPROBANTE_DOMICILIO", "Clasificacion ajustada por huellas de recibo/servicio."
    return doc_type, None


ALLOWED_FORCED_DOC_TYPES = {
    "CFDI", "FACTURA", "DATOS_BANCARIOS", "COMPROBANTE_DE_PAGO",
    "NOMINA", "INE", "CURP", "NSS", "ACTA_NACIMIENTO",
    "COMPROBANTE_DOMICILIO", "CONSTANCIA_SITUACION_FISCAL", "GENERICO",
}


def _resolve_forced_document_type(options_data: dict) -> str | None:
    raw = options_data.get("force_document_type")
    if not isinstance(raw, str):
        return None
    normalized = raw.strip().upper().replace("-", "_").replace(" ", "_")
    if normalized in ALLOWED_FORCED_DOC_TYPES:
        return normalized
    return None


def _has_sufficient_text_layer(text: str) -> bool:
    compact = " ".join((text or "").split())
    if not compact:
        return False
    alnum_count = sum(1 for ch in compact if ch.isalnum())
    word_count = len(compact.split(" "))
    return (
        alnum_count >= settings.min_text_layer_chars
        and word_count >= settings.min_text_layer_words
    )


def _critical_coverage(doc_type: str, fields: list[dict]) -> tuple[int, int]:
    required = CRITICAL_FIELDS.get(doc_type, [])
    if not required:
        return 0, 0
    found_required = 0
    for key in required:
        if _select_required_field(doc_type, key, fields):
            found_required += 1
    return found_required, len(required)


CANONICAL_FIELD_KEYS: dict[str, str] = {
    "nss": "nss",
    "seguridad_social": "nss",
    "numero_seguridad_social": "nss",
    "numero_de_seguridad_social": "nss",
    "sistema_nacional_de_seguridad_social": "nss",
    "sistema": "nss",
    # Name variants: keep each as a distinct key so documents with
    # multiple people (beneficiario, titular, asegurado) preserve ALL names.
    "nombre_beneficiario": "nombre_beneficiario",
    "nombre_asegurado": "nombre_asegurado",
    "nombre_titular": "nombre_titular",
    "nombre_del_beneficiario": "nombre_beneficiario",
    "nombre_del_asegurado": "nombre_asegurado",
    "nombre_del_titular": "nombre_titular",
    "beneficiario": "nombre_beneficiario",
    "asegurado": "nombre_asegurado",
}

CANONICAL_FIELD_LABELS: dict[str, str] = {
    "nss": "NSS",
    "nombre": "Nombre",
    "nombre_beneficiario": "Nombre Beneficiario",
    "nombre_asegurado": "Nombre Asegurado",
    "nombre_titular": "Nombre Titular",
    "titular": "Titular",
}


def _normalize_key_name(value: str) -> str:
    normalized = (value or "").strip().lower()
    normalized = normalized.replace("-", "_").replace(" ", "_")
    return normalized


def _resolve_canonical_key(key: str, label: str, document_type: str) -> str:
    normalized_key = _normalize_key_name(key)
    if normalized_key in CANONICAL_FIELD_KEYS:
        resolved = CANONICAL_FIELD_KEYS[normalized_key]
    else:
        normalized_label = _normalize_key_name(label)
        if "seguridad" in normalized_label or "nss" in normalized_label:
            resolved = "nss"
        elif normalized_label in CANONICAL_FIELD_KEYS:
            resolved = CANONICAL_FIELD_KEYS[normalized_label]
        else:
            resolved = normalized_key

    if document_type == "NSS" and resolved == "titular":
        return "nombre"
    if document_type == "NSS" and resolved == "nombre_titular":
        return "nombre"
    if document_type in {"COMPROBANTE_DOMICILIO", "FACTURA"} and resolved == "nombre":
        return "titular"
    return resolved


def _normalize_fields(document_type: str, fields: list[dict]) -> list[dict]:
    normalized: dict[str, dict] = {}
    for field in fields:
        raw_key = str(field.get("key", "") or "")
        raw_label = str(field.get("label", "") or "")
        canonical_key = _resolve_canonical_key(raw_key, raw_label, document_type)
        if not canonical_key:
            continue

        value = field.get("value")
        if isinstance(value, str):
            value = value.strip()
        if value in {"", None}:
            continue

        candidate = {
            **field,
            "key": canonical_key,
            "label": CANONICAL_FIELD_LABELS.get(canonical_key, raw_label or canonical_key),
            "value": value,
        }

        existing = normalized.get(canonical_key)
        if not existing:
            normalized[canonical_key] = candidate
            continue

        current_score = float(existing.get("confidence", 0) or 0)
        new_score = float(candidate.get("confidence", 0) or 0)
        current_valid = bool(existing.get("valid", True))
        new_valid = bool(candidate.get("valid", True))
        if (new_valid and not current_valid) or (new_valid == current_valid and new_score >= current_score):
            normalized[canonical_key] = candidate

    return list(normalized.values())


FASTPATH_REQUIRED_FIELDS: dict[str, list[str]] = {
    "INE": ["curp", "nombre", "fecha_nacimiento", "seccion", "vigencia"],
    "CURP": ["curp", "nombre", "fecha_nacimiento"],
    "ACTA_NACIMIENTO": ["nombre", "fecha_nacimiento", "folio", "numero_acta"],
    "COMPROBANTE_DOMICILIO": ["domicilio", "cp"],
    "NSS": ["nss", "nombre"],
    "DATOS_BANCARIOS": ["clabe", "banco", "cuenta", "titular", "fecha_corte"],
    "FACTURA": ["tabla_celdas"],
    "NOMINA": ["nombre", "periodo", "neto_pagar"],
    "CFDI": ["uuid", "rfc_emisor", "rfc_receptor", "total"],
    "CONSTANCIA_SITUACION_FISCAL": ["rfc", "nombre", "domicilio"],
    "GENERICO": [],
    "UNKNOWN": [],
}


def _has_required_fields(fields: list[dict], required_keys: list[str]) -> bool:
    for key in required_keys:
        if not any(field.get("key") == key and field.get("value") for field in fields):
            return False
    return True


DEFAULT_CRITICAL_FIELDS: dict[str, list[str]] = {
    "INE": ["curp", "nombre", "fecha_nacimiento"],
    "CURP": ["curp", "nombre"],
    "ACTA_NACIMIENTO": ["nombre", "fecha_nacimiento", "folio", "numero_acta"],
    "COMPROBANTE_DOMICILIO": ["domicilio"],
    "NSS": ["nss"],
    "DATOS_BANCARIOS": ["clabe", "banco", "cuenta", "titular", "fecha_corte"],
    "FACTURA": ["tabla_celdas"],
    "NOMINA": ["nombre", "periodo", "neto_pagar", "total_percepciones", "total_deducciones"],
    "CFDI": ["uuid", "rfc_emisor", "rfc_receptor", "total"],
    "CONSTANCIA_SITUACION_FISCAL": ["rfc"],
    "GENERICO": [],
}
CRITICAL_FIELDS: dict[str, list[str]] = DEFAULT_CRITICAL_FIELDS.copy()
_critical_path = Path(__file__).resolve().parent.parent / "models" / "critical_fields.json"
if _critical_path.exists():
    try:
        loaded = json.loads(_critical_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and loaded:
            CRITICAL_FIELDS = loaded
    except Exception:
        logger.warning("Failed to load critical_fields.json, using defaults", exc_info=True)
        CRITICAL_FIELDS = DEFAULT_CRITICAL_FIELDS.copy()

CRITICAL_KEY_ALIASES: dict[str, dict[str, list[str]]] = {
    "ACTA_NACIMIENTO": {
        "fecha_nacimiento": ["fecha_nacimiento", "fecha"],
    },
    "CURP": {
        "nombre": ["nombre", "nombres", "nombre_completo", "nombre_beneficiario", "nombre_asegurado", "nombre_titular"],
    },
    "NSS": {
        "nombre": ["nombre", "nombres", "nombre_beneficiario", "nombre_asegurado", "nombre_titular", "titular"],
    },
    "DATOS_BANCARIOS": {
        "titular": ["titular", "nombre", "nombre_completo", "nombre_titular", "nombre_beneficiario"],
        "cuenta": ["cuenta", "numero_cuenta", "no_cuenta", "numero_de_cuenta"],
        "fecha_corte": ["fecha_corte", "fecha_de_corte", "corte", "fecha"],
        "tabla_celdas": ["tabla_celdas", "tabla", "celdas"],
    },
    "FACTURA": {
        "titular": ["titular", "nombre", "nombre_completo", "nombre_titular"],
        "tabla_celdas": ["tabla_celdas", "tabla", "celdas"],
    },
    "CONSTANCIA_SITUACION_FISCAL": {
        "nombre": ["nombre", "nombre_completo", "razon_social", "denominacion_razon_social"],
    },
}


def _critical_aliases(doc_type: str, key: str) -> list[str]:
    aliases_by_type = CRITICAL_KEY_ALIASES.get(doc_type, {})
    aliases = aliases_by_type.get(key, [key])
    return [_normalize_key_name(alias) for alias in aliases if alias]


def _has_field_value(field: dict) -> bool:
    value = field.get("corrected_value")
    if value in {None, ""}:
        value = field.get("value")
    if isinstance(value, str):
        value = value.strip()
    return value not in {None, ""}


def _field_value(field: dict):
    value = field.get("corrected_value")
    if value in {None, ""}:
        value = field.get("value")
    if isinstance(value, str):
        return value.strip()
    return value


_PAYROLL_REQUIRED_COLUMNS = (
    "cuenta",
    "referencia",
    "importe",
    "nombre",
    "apellido_paterno",
    "apellido_materno",
    "estatus",
    "concepto_pago",
)

_PAYROLL_STRICT_FILL_COLUMNS = (
    "cuenta",
    "referencia",
    "importe",
    "nombre",
    "apellido_paterno",
    "apellido_materno",
)

_PAYMENT_REQUIRED_COLUMNS_BY_BANK: dict[str, tuple[str, ...]] = {
    "SCOTIABANK": ("nombre_beneficiario", "importe", "referencia", "cuenta_beneficiario"),
    "BBVA": ("nombre_beneficiario", "importe", "cuenta_beneficiario", "concepto_pago"),
    "BANORTE": ("nombre_beneficiario", "importe", "cuenta_beneficiario", "clave_beneficiario"),
    "SANTANDER": ("nombre_beneficiario", "importe", "cuenta_beneficiario", "referencia"),
    "BANAMEX": ("nombre_beneficiario", "importe", "cuenta_beneficiario"),
    "HSBC": ("nombre_beneficiario", "importe", "cuenta_beneficiario"),
}

_PAYMENT_DEFAULT_REQUIRED_COLUMNS: tuple[str, ...] = (
    "nombre_beneficiario",
    "importe",
    "cuenta_beneficiario",
)

_PAYMENT_TOTAL_METADATA_KEYS: tuple[str, ...] = (
    "importe_total_movimientos",
    "importe_movimiento_altas",
    "importe_detectado",
    "importe_total",
)


def _json_to_dict(raw_value) -> dict | None:
    if isinstance(raw_value, dict):
        return raw_value
    if not isinstance(raw_value, str):
        return None
    text = raw_value.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_payroll_canonical_table(fields: list[dict]) -> tuple[list[str], list[dict[str, str]]] | None:
    table_payload: dict | None = None
    for field in fields:
        normalized_key = _normalize_key_name(str(field.get("key", "") or ""))
        if normalized_key not in {"tabla_celdas", "pago_detalle"}:
            continue
        value = _field_value(field)
        payload = _json_to_dict(value)
        if not payload:
            continue
        if normalized_key == "tabla_celdas":
            table_payload = payload
            break
        table = payload.get("table")
        if isinstance(table, dict):
            table_payload = table

    if not isinstance(table_payload, dict):
        return None

    canonical_columns_raw = table_payload.get("canonical_columns")
    canonical_rows_raw = table_payload.get("canonical_rows")
    if not isinstance(canonical_columns_raw, list) or not isinstance(canonical_rows_raw, list):
        return None

    canonical_columns = [str(col or "").strip() for col in canonical_columns_raw if str(col or "").strip()]
    canonical_rows: list[dict[str, str]] = []
    for row in canonical_rows_raw:
        if not isinstance(row, dict):
            continue
        clean_row: dict[str, str] = {}
        for key, value in row.items():
            key_text = str(key or "").strip()
            if not key_text:
                continue
            value_text = str(value or "").strip()
            if value_text:
                clean_row[key_text] = value_text
        if clean_row:
            canonical_rows.append(clean_row)

    if not canonical_columns or not canonical_rows:
        return None
    return canonical_columns, canonical_rows


def _normalize_bank_name(value) -> str:
    return str(value or "").strip().upper()


def _parse_amount_number(value) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None

    text = (
        text.upper()
        .replace("$", "")
        .replace("MXN", "")
        .replace("PESOS", "")
        .replace(" ", "")
        .replace("O", "0")
        .replace("I", "1")
        .replace("L", "1")
    )
    text = re.sub(r"[^0-9,.\-]", "", text)
    if not text:
        return None

    if "," in text and "." in text:
        decimal_sep = "." if text.rfind(".") > text.rfind(",") else ","
        if decimal_sep == ".":
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    elif text.count(",") == 1 and len(text.split(",")[-1]) in {1, 2}:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")

    try:
        return float(text)
    except ValueError:
        return None


def _extract_payment_table_context(fields: list[dict]) -> dict | None:
    fallback_bank = _normalize_bank_name(_detect_bank_from_fields(fields))
    best_context: dict | None = None
    best_score = -1

    for field in fields:
        normalized_key = _normalize_key_name(str(field.get("key", "") or ""))
        if normalized_key not in {"tabla_celdas", "pago_detalle"}:
            continue

        payload = _json_to_dict(_field_value(field))
        if not payload:
            continue

        table_payload = payload
        if normalized_key == "pago_detalle" and isinstance(payload.get("table"), dict):
            table_payload = payload["table"]

        if not isinstance(table_payload, dict):
            continue

        canonical_columns_raw = table_payload.get("canonical_columns")
        canonical_rows_raw = table_payload.get("canonical_rows")
        if not isinstance(canonical_rows_raw, list) or not canonical_rows_raw:
            continue

        canonical_rows: list[dict[str, str]] = []
        derived_columns: set[str] = set()
        for row in canonical_rows_raw:
            if not isinstance(row, dict):
                continue
            clean_row: dict[str, str] = {}
            for key, value in row.items():
                key_text = str(key or "").strip()
                if not key_text:
                    continue
                value_text = str(value or "").strip()
                if value_text:
                    clean_row[key_text] = value_text
                    derived_columns.add(key_text)
            if clean_row:
                canonical_rows.append(clean_row)

        if not canonical_rows:
            continue

        if isinstance(canonical_columns_raw, list):
            canonical_columns = [str(col or "").strip() for col in canonical_columns_raw if str(col or "").strip()]
        else:
            canonical_columns = sorted(derived_columns)

        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        bank = _normalize_bank_name(
            payload.get("bank")
            or table_payload.get("bank")
            or metadata.get("bank")
            or fallback_bank
        )

        remapped_columns, remapped_rows, display_columns = remap_to_target_payment_schema(
            canonical_columns,
            canonical_rows,
            bank=bank,
        )
        populated_remapped_columns = {
            column
            for column in remapped_columns
            if any(str(row.get(column, "") or "").strip() for row in remapped_rows)
        }

        score = (
            len(canonical_rows) * 50
            + len(populated_remapped_columns) * 10
            + (20 if metadata else 0)
            + (10 if bank else 0)
            + (5 if normalized_key == "pago_detalle" else 0)
        )

        if score > best_score:
            best_score = score
            best_context = {
                "field_key": normalized_key,
                "bank": bank,
                "metadata": metadata,
                "canonical_columns": canonical_columns,
                "canonical_rows": canonical_rows,
                "remapped_columns": remapped_columns,
                "remapped_rows": remapped_rows,
                "display_columns": display_columns,
                "populated_remapped_columns": populated_remapped_columns,
            }

    return best_context


def _payment_metadata_amount(metadata: dict) -> tuple[str | None, float | None]:
    if not isinstance(metadata, dict):
        return None, None

    for key in _PAYMENT_TOTAL_METADATA_KEYS:
        amount = _parse_amount_number(metadata.get(key))
        if amount is not None:
            return key, amount

    return None, None


def _should_skip_item_level_total_validation(
    *,
    bank: str,
    metadata: dict,
    total_key: str | None,
    row_count: int,
) -> bool:
    if total_key != "importe_detectado" or row_count <= 1:
        return False

    bank_name = _normalize_bank_name(bank)
    payment_type = str(metadata.get("tipo_pago") or "").strip().upper()
    if bank_name == "BBVA" and "GRUPO PAGO" in payment_type:
        return True

    return False


def _build_duplicate_payment_keys(rows: list[dict[str, str]]) -> list[tuple[str, ...]]:
    candidate_sets = (
        ("cuenta_beneficiario", "referencia", "importe"),
        ("cuenta_beneficiario", "importe", "nombre_beneficiario"),
        ("referencia", "importe", "nombre_beneficiario"),
    )

    for candidate in candidate_sets:
        keys: list[tuple[str, ...]] = []
        for row in rows:
            values = tuple(str(row.get(column, "") or "").strip() for column in candidate)
            if all(values):
                keys.append(values)
        if keys:
            return keys

    return []


def _evaluate_payroll_strict(fields: list[dict], doc_type: str) -> tuple[list[str], bool]:
    if doc_type not in {"FACTURA", "NOMINA"} or not settings.payroll_strict_mode:
        return [], False

    table_context = _extract_payment_table_context(fields)
    if not table_context:
        return [], False
    canonical_columns = table_context["canonical_columns"]
    canonical_rows = table_context["canonical_rows"]
    canonical_set = set(canonical_columns)
    required_set = set(_PAYROLL_REQUIRED_COLUMNS)

    remapped_rows: list[dict[str, str]] = table_context["remapped_rows"]
    remapped_columns = set(table_context["populated_remapped_columns"])
    bank = _normalize_bank_name(table_context["bank"])
    metadata: dict = table_context["metadata"]
    bank_required = _PAYMENT_REQUIRED_COLUMNS_BY_BANK.get(bank, _PAYMENT_DEFAULT_REQUIRED_COLUMNS)

    warnings: list[str] = []
    hard_fail = False
    total_rows = len(canonical_rows)
    if total_rows == 0:
        return ["[NOMINA_STRICT] tabla de nomina sin filas de datos."], True

    if bank:
        missing_bank_columns = [column for column in bank_required if column not in remapped_columns]
        if missing_bank_columns and total_rows >= max(1, int(settings.payroll_strict_min_rows)):
            warnings.append(
                f"[NOMINA_STRICT] {bank}: columnas canónicas esperadas ausentes: {', '.join(missing_bank_columns)}."
            )
            if len(bank_required) - len(missing_bank_columns) < 2:
                hard_fail = True

    enforce_advanced_payroll = required_set.issubset(canonical_set)

    if enforce_advanced_payroll and "apellido_combo_estatus" in canonical_set:
        warnings.append("[NOMINA_STRICT] columna combinada 'apellido_combo_estatus' detectada en salida final.")
        hard_fail = True

    min_fill_rate = max(0.0, min(1.0, float(settings.payroll_strict_min_fill_rate)))
    min_rows_for_strict_fill = max(1, int(settings.payroll_strict_min_rows))
    if total_rows >= min_rows_for_strict_fill:
        fill_columns = [column for column in bank_required if column in remapped_columns]
        if enforce_advanced_payroll:
            for column in _PAYROLL_STRICT_FILL_COLUMNS:
                if column not in fill_columns and column in canonical_set:
                    fill_columns.append(column)

        for col in fill_columns:
            row_source = canonical_rows if col in canonical_set and col not in remapped_columns else remapped_rows
            filled = sum(1 for row in row_source if str(row.get(col, "") or "").strip())
            fill_rate = filled / max(1, total_rows)
            if fill_rate < min_fill_rate:
                warnings.append(
                    f"[NOMINA_STRICT] columna '{col}' con llenado bajo: {fill_rate:.1%} (< {min_fill_rate:.0%})."
                )
                hard_fail = True

    max_ratio = max(0.0, min(1.0, float(settings.payroll_strict_max_dominant_surname_ratio)))
    min_rows_for_ratio = max(10, int(settings.payroll_strict_min_rows))
    if enforce_advanced_payroll:
        for surname_col in ("apellido_paterno", "apellido_materno"):
            values = [str(row.get(surname_col, "") or "").strip().upper() for row in canonical_rows]
            values = [value for value in values if value]
            if len(values) < min_rows_for_ratio:
                continue
            counts = Counter(values)
            dominant_value, dominant_count = counts.most_common(1)[0]
            dominant_ratio = dominant_count / len(values)
            if dominant_ratio > max_ratio:
                warnings.append(
                    f"[NOMINA_STRICT] posible sobre-relleno en '{surname_col}': "
                    f"'{dominant_value}' aparece en {dominant_ratio:.1%} de filas."
                )
                hard_fail = True

    total_key, expected_total = _payment_metadata_amount(metadata)
    if expected_total is not None and remapped_rows:
        row_amounts = [
            amount
            for amount in (_parse_amount_number(row.get("importe")) for row in remapped_rows)
            if amount is not None
        ]
        if row_amounts and not _should_skip_item_level_total_validation(
            bank=bank,
            metadata=metadata,
            total_key=total_key,
            row_count=len(remapped_rows),
        ):
            extracted_total = sum(row_amounts)
            tolerance = max(0.05, round(expected_total * 0.005, 2))
            if abs(extracted_total - expected_total) > tolerance:
                warnings.append(
                    f"[NOMINA_STRICT] total por filas ({extracted_total:.2f}) no coincide con "
                    f"{total_key} ({expected_total:.2f})."
                )
                hard_fail = True

    dedupe_keys = _build_duplicate_payment_keys(remapped_rows)
    if dedupe_keys:
        duplicate_count = len(dedupe_keys) - len(set(dedupe_keys))
        if duplicate_count > 0:
            duplicate_ratio = duplicate_count / len(dedupe_keys)
            warnings.append(
                f"[NOMINA_STRICT] filas duplicadas por clave de pago: "
                f"{duplicate_count} ({duplicate_ratio:.1%})."
            )
            if duplicate_ratio > 0.10:
                hard_fail = True

    return warnings, hard_fail


def _is_effectively_valid(doc_type: str, required_key: str, field: dict) -> bool:
    if bool(field.get("valid", True)):
        return True

    value = _field_value(field)
    if value in {None, ""}:
        return False

    text = str(value).upper()
    if doc_type == "ACTA_NACIMIENTO" and required_key in {"folio", "numero_acta"}:
        return bool(re.fullmatch(r"[A-Z0-9-]{1,12}", text))

    return False


def _select_required_field(doc_type: str, required_key: str, fields: list[dict]) -> dict | None:
    aliases = set(_critical_aliases(doc_type, required_key))
    candidates = []
    for field in fields:
        normalized = _normalize_key_name(str(field.get("key", "") or ""))
        if normalized not in aliases:
            continue
        if not _has_field_value(field):
            continue
        confidence = float(field.get("confidence", 0) or 0)
        candidates.append((_is_effectively_valid(doc_type, required_key, field), confidence, field))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]

_LOW_CONF_DROP_BY_TYPE = {
    "INE": {
        "nombres",
        "apellido_paterno",
        "apellido_materno",
        "fecha",
        "entidad_nacimiento",
        "anio_registro",
    },
    "ACTA_NACIMIENTO": {
        "libro",
        "tomo",
        "oficialia",
        "registro_civil",
        "juez",
        "primer_apellido",
        "segundo_apellido",
        "anio_registro",
    },
    "COMPROBANTE_DOMICILIO": {
        "periodo",
        "titular",
        "referencia",
    },
    "CONSTANCIA_SITUACION_FISCAL": {
        "cp",
        "id_cif",
        "fecha_emision",
    },
    "CURP": {
        "entidad_registro",
    },
    "NSS": {
        "fecha_documento",
        "folio_solicitud",
    },
    "FACTURA": {
        "titular",
        "referencia",
        "fecha_corte",
    },
    "DATOS_BANCARIOS": {
        "titular",
        "fecha_corte",
        "periodo",
    },
}

_INVALID_DROP_BY_TYPE = {
    "ACTA_NACIMIENTO": {"registro_civil", "juez"},
    "INE": {"curp", "clave_elector", "seccion"},
    "CURP": {"curp"},
    "NSS": {"nss"},
    "DATOS_BANCARIOS": {"rfc"},
    "CONSTANCIA_SITUACION_FISCAL": {"rfc", "cp"},
    "COMPROBANTE_DOMICILIO": {"cp"},
}


def _postprocess_fields(doc_type: str, fields: list[dict]) -> list[dict]:
    drop_low = _LOW_CONF_DROP_BY_TYPE.get(doc_type, set())
    drop_invalid = _INVALID_DROP_BY_TYPE.get(doc_type, set())
    cleaned: list[dict] = []
    for field in fields:
        key = field.get("key")
        if key == "texto_detectado":
            cleaned.append(field)
            continue
        if key in drop_low and field.get("confidence", 1) < 0.7:
            continue
        if key in drop_invalid and field.get("valid") is False:
            continue
        # Strip control characters from values
        value = str(field.get("value", "") or "")
        import re as _re
        sanitized = _re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', value).strip()
        if sanitized != value:
            field = {**field, "value": sanitized}
        if not sanitized:
            continue
        cleaned.append(field)
    return cleaned


_ACTA_NAME_NOISE_TOKENS = {
    "SEXO",
    "FECHA",
    "NACIMIENTO",
    "LUGAR",
    "REGISTRO",
    "ACTA",
    "PERSONA REGISTRADA",
    "DATOS DE LA",
}

_ACTA_LOCATION_NOISE_TOKENS = {
    "SEXO",
    "FECHA",
    "ACTA DE NACIMIENTO",
    "DATOS DE LA PERSONA",
    "PERSONA REGISTRADA",
}


def _mark_field_invalid(field: dict, error: str, confidence_cap: float = 0.55) -> None:
    field["valid"] = False
    current_conf = float(field.get("confidence", 0.0) or 0.0)
    field["confidence"] = min(current_conf, confidence_cap) if current_conf else confidence_cap
    errors = field.get("validation_errors")
    if not isinstance(errors, list):
        errors = []
    if error not in errors:
        errors.append(error)
    field["validation_errors"] = errors


def _is_plausible_ddmmyyyy(value: str) -> bool:
    match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", value)
    if not match:
        return False
    day = int(match.group(1))
    month = int(match.group(2))
    year = int(match.group(3))
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return False
    current_year = time.localtime().tm_year
    return 1900 <= year <= current_year + 1


def _apply_acta_sanity_guards(fields: list[dict]) -> tuple[list[dict], list[str]]:
    if not settings.acta_sanity_guards_enabled:
        return fields, []

    warnings: list[str] = []
    for field in fields:
        key = str(field.get("key", "") or "")
        value_raw = field.get("value")
        if value_raw in {None, ""}:
            continue
        value = str(value_raw).strip()
        upper = value.upper()

        if key == "nombre":
            cleaned = re.sub(r"\s+", " ", re.sub(r"[^A-Z ]", " ", upper)).strip()
            has_noise = any(token in cleaned for token in _ACTA_NAME_NOISE_TOKENS)
            has_digits = bool(re.search(r"\d", cleaned))
            if has_noise or has_digits or len(re.sub(r"[^A-Z]", "", cleaned)) < 4:
                _mark_field_invalid(field, "Nombre con ruido OCR de etiquetas (ACTA).", confidence_cap=0.45)
                warnings.append("Guardia ACTA: nombre invalido por ruido OCR.")
            else:
                field["value"] = cleaned

        elif key == "sexo":
            normalized = upper.replace("0", "O")
            if normalized in {"HOMBRE", "H"}:
                field["value"] = "H"
            elif normalized in {"MUJER", "M"}:
                field["value"] = "M"
            else:
                _mark_field_invalid(field, "Sexo invalido en ACTA (esperado H/M).", confidence_cap=0.45)
                warnings.append("Guardia ACTA: sexo invalido.")

        elif key in {"fecha_nacimiento", "fecha_registro"}:
            normalized = value.replace("-", "/")
            if not _is_plausible_ddmmyyyy(normalized):
                _mark_field_invalid(field, f"{key} invalida en ACTA.", confidence_cap=0.45)
                warnings.append(f"Guardia ACTA: {key} invalida.")
            else:
                field["value"] = normalized

        elif key in {"lugar_nacimiento", "municipio_registro", "entidad_registro"}:
            cleaned = re.sub(r"\s+", " ", upper).strip()
            if any(token in cleaned for token in _ACTA_LOCATION_NOISE_TOKENS):
                _mark_field_invalid(field, f"{key} contiene ruido de encabezados en ACTA.", confidence_cap=0.45)
                warnings.append(f"Guardia ACTA: {key} invalido por ruido OCR.")
            else:
                field["value"] = cleaned

        elif key in {"folio", "numero_acta"}:
            if not re.fullmatch(r"[A-Z0-9-]{1,12}", upper):
                _mark_field_invalid(field, f"{key} invalido en ACTA.", confidence_cap=0.45)
                warnings.append(f"Guardia ACTA: {key} invalido.")
            else:
                field["value"] = upper

    if warnings:
        deduped: list[str] = []
        seen: set[str] = set()
        for warning in warnings:
            if warning in seen:
                continue
            seen.add(warning)
            deduped.append(warning)
        warnings = deduped
    return fields, warnings


def _make_error_response(
    document_id: str,
    message: str,
    error_code: str,
    stage: str,
    filename: str = "",
    source: str = "web",
    processing_time_ms: int = 0,
) -> ProcessResponse:
    """Construye una respuesta de error estructurada con error_code y stage."""
    return ProcessResponse(
        document_id=document_id,
        tipo_documento="UNKNOWN",
        success=False,
        message=message,
        error_code=error_code,
        stage=stage,
        metadata=MetadataDocumento(
            filename=filename,
            source=source,
            processing_time_ms=processing_time_ms,
        ),
        validation_summary=ValidationSummary(
            requires_review=True,
            score_decision="reprocess",
        ),
    )


async def process_document(file, document_id: str, source: str, options: str | None):
    start = time.time()
    options_data = {}
    if options:
        try:
            options_data = json.loads(options)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in options parameter: %s", options)
            options_data = {}
    forced_doc_type = _resolve_forced_document_type(options_data)

    t0 = time.time()
    try:
        preprocess_result = await preprocess(file)
    except Exception as exc:
        logger.exception("preprocess() falló para doc_id=%s", document_id)
        return _make_error_response(
            document_id=document_id,
            message=f"Error en preprocesamiento: {exc}",
            error_code="PREPROCESSING_FAILED",
            stage="preprocess",
            filename=str(getattr(file, "filename", "") or ""),
            source=source or "web",
            processing_time_ms=int((time.time() - start) * 1000),
        )
    logger.info("[PERF] preprocess: %.1fms", (time.time() - t0) * 1000)
    text_layer_boxes: list[dict] = []
    pdf_tables: list[list[list[str]]] = []
    table_cell_grids: list = []
    extraction_boxes: list[dict] = []  # se actualiza tras OCR; disponible para _process_all_tables
    if isinstance(preprocess_result, tuple) and len(preprocess_result) >= 5:
        images, extracted_text, text_layer_boxes, pdf_tables, table_cell_grids = preprocess_result
    elif isinstance(preprocess_result, tuple) and len(preprocess_result) >= 4:
        images, extracted_text, text_layer_boxes, pdf_tables = preprocess_result
    elif isinstance(preprocess_result, tuple) and len(preprocess_result) >= 3:
        images, extracted_text, text_layer_boxes = preprocess_result
    else:
        images, extracted_text = preprocess_result
    ocr_text = ""
    ocr_boxes = []
    ocr_engine = "none"
    doc_type_warning = None
    fields: list[dict] = []
    acta_guard_warnings: list[str] = []
    t_ocr_ms: float = 0.0
    t_extract_ms: float = 0.0

    # Detectar PDF corrupto / vacío: sin imágenes ni texto extraíble
    if not images and not extracted_text:
        logger.warning("PDF sin imágenes ni texto para doc_id=%s filename=%s",
                       document_id, getattr(file, "filename", ""))
        return _make_error_response(
            document_id=document_id,
            message="El documento no contiene páginas procesables.",
            error_code="PDF_CORRUPTED",
            stage="preprocess",
            filename=str(getattr(file, "filename", "") or ""),
            source=source or "web",
            processing_time_ms=int((time.time() - start) * 1000),
        )

    use_fastpath = bool(
        extracted_text
        and _has_sufficient_text_layer(extracted_text)
    )
    if use_fastpath:
        fast_type, fast_confidence = await classify_document(None, extracted_text, file.filename)
        fast_type, fast_warning = _maybe_override_doc_type(fast_type, extracted_text, file.filename)
        if forced_doc_type:
            fast_type = forced_doc_type
            fast_confidence = max(fast_confidence, 0.9)
            fast_warning = None
        if fast_type in settings.text_layer_fastpath_types:
            candidate_fields = await extract_fields(
                fast_type,
                extracted_text,
                text_layer_boxes,
                extracted_text,
                file.filename,
                pdf_tables,
            )
            candidate_fields = await validate_fields(candidate_fields)
            candidate_fields = _normalize_fields(fast_type, candidate_fields)
            candidate_fields = _postprocess_fields(fast_type, candidate_fields)
            found_required, required_total = _critical_coverage(fast_type, candidate_fields)
            fastpath_complete = required_total == 0 or found_required == required_total
            extra_required = FASTPATH_REQUIRED_FIELDS.get(fast_type, [])
            if extra_required and not _has_required_fields(candidate_fields, extra_required):
                fastpath_complete = False
            if fastpath_complete and candidate_fields:
                ocr_text = extracted_text
                ocr_engine = "text-layer-fastpath"
                doc_type = fast_type
                doc_confidence = max(fast_confidence, 0.85) if fast_type not in {"UNKNOWN", "GENERICO"} else fast_confidence
                doc_type_warning = fast_warning
                fields = candidate_fields

    if not fields:
        t1 = time.time()
        try:
            ocr_text, ocr_boxes = await run_ocr(images)
        except Exception as exc:
            logger.exception("run_ocr() falló para doc_id=%s", document_id)
            return _make_error_response(
                document_id=document_id,
                message=f"Error en OCR: {exc}",
                error_code="OCR_FAILED",
                stage="ocr",
                filename=str(getattr(file, "filename", "") or ""),
                source=source or "web",
                processing_time_ms=int((time.time() - start) * 1000),
            )
        t_ocr_ms = (time.time() - t1) * 1000
        logger.info("[PERF] OCR (%d pages): %.1fms", len(images), t_ocr_ms)
        if ocr_boxes:
            ocr_engine = str(ocr_boxes[0].get("engine") or "paddleocr")
        elif ocr_text:
            ocr_engine = "ocr"
        else:
            ocr_engine = "none"
        if extracted_text:
            if not ocr_text:
                ocr_text = extracted_text
                ocr_engine = "text-layer"
            else:
                ocr_text = f"{ocr_text}\n{extracted_text}"
                ocr_engine = "paddleocr+text-layer"

        if ocr_text:
            # Normalización de texto OCR: unicode NFC, espacios, control chars
            ocr_text = ocr_text.replace("\u00a0", " ").replace("\t", " ")
            ocr_text = unicodedata.normalize("NFC", ocr_text)
            ocr_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', ocr_text)

        # ── Fill img2table grids with OCR box text ──────────────────
        # When preprocess detected table grid structure (cell bounding
        # boxes via img2table) but couldn't read cell contents (no OCR
        # engine configured in img2table), map the OCR boxes from
        # PaddleOCR to grid cells to produce filled tables.
        if table_cell_grids and ocr_boxes:
            from app.pipelines.preprocess import fill_grid_tables_from_ocr_boxes
            grid_tables = fill_grid_tables_from_ocr_boxes(table_cell_grids, ocr_boxes)
            if grid_tables:
                logger.info("Filled %d grid table(s) from OCR boxes", len(grid_tables))
                pdf_tables = pdf_tables + grid_tables
        # ────────────────────────────────────────────────────────────

        # ── Fallback: reconstruir tablas desde OCR (PDF escaneado) ──
        # Cuando preprocess no encontró estructura de tabla (PDF imagen
        # puro), intentar reconstruir tablas desde los bounding boxes
        # del OCR o desde el texto con detección de columnas.
        if not pdf_tables and (ocr_boxes or ocr_text):
            from app.pipelines.extract.table_from_ocr import extract_fallback_tables
            _fallback = extract_fallback_tables(ocr_text or "", ocr_boxes or [])
            if _fallback:
                pdf_tables = _fallback
                logger.info(
                    "OCR table fallback: %d tabla(s) reconstruida(s) para doc_id=%s",
                    len(_fallback), document_id,
                )
        # ────────────────────────────────────────────────────────────

        first_image = images[0] if images else None
        doc_type, doc_confidence = await classify_document(first_image, ocr_text, file.filename)
        doc_type, doc_type_warning = _maybe_override_doc_type(doc_type, ocr_text, file.filename)
        if forced_doc_type:
            doc_type = forced_doc_type
            doc_confidence = max(doc_confidence, 0.9)
            doc_type_warning = None
        if (ocr_text or extracted_text) and doc_type not in {"UNKNOWN", "GENERICO"}:
            doc_confidence = max(doc_confidence, 0.85)
        extraction_boxes = ocr_boxes if ocr_boxes else text_layer_boxes
        t2 = time.time()
        if doc_type == "CFDI":
            # CFDI: llamar directamente al extractor con el contenido XML
            from app.extractors.cfdi_extractor import extract as _cfdi_extract
            fields = await _cfdi_extract(
                ocr_text=ocr_text,
                ocr_boxes=extraction_boxes,
                raw_text=extracted_text,
                filename=file.filename,
                pdf_tables=pdf_tables,
                xml_content=extracted_text if extracted_text and _looks_like_xml(extracted_text) else None,
            )
        else:
            from app.extractors import get_extractor
            _extractor = get_extractor(doc_type)
            _kwargs: dict = {
                "ocr_text": ocr_text,
                "ocr_boxes": extraction_boxes,
                "raw_text": extracted_text,
                "filename": file.filename,
                "pdf_tables": pdf_tables,
            }
            if doc_type in {"GENERICO", "UNKNOWN"}:
                _kwargs["document_type"] = doc_type
            fields = await _extractor.extract(**_kwargs)
        t_extract_ms = (time.time() - t2) * 1000
        logger.info("[PERF] extract_fields (%s): %.1fms", doc_type, t_extract_ms)
        fields = await validate_fields(fields)
        fields = _normalize_fields(doc_type, fields)
        fields = _postprocess_fields(doc_type, fields)

    # === LLM FALLBACK (solo si hay campos críticos faltantes) ===
    if settings.llm_fallback_enabled and ocr_text:
        _tentative_required = CRITICAL_FIELDS.get(doc_type, [])
        _tentative_missing = [
            k for k in _tentative_required
            if not _select_required_field(doc_type, k, fields)
        ]
        if _tentative_missing:
            try:
                from app.services.llm_fallback import try_llm_fallback, merge_llm_fields
                _llm_fields = await try_llm_fallback(
                    doc_type, ocr_text, _tentative_missing, fields,
                    api_key=settings.anthropic_api_key,
                    model=settings.llm_fallback_model,
                )
                if _llm_fields:
                    fields = merge_llm_fields(fields, _llm_fields)
                    logger.info(
                        "LLM fallback añadió %d campos para doc_type=%s document_id=%s",
                        len(_llm_fields), doc_type, document_id,
                    )
            except Exception:
                logger.exception(
                    "LLM fallback falló, continuando sin él (doc_type=%s, document_id=%s)",
                    doc_type, document_id,
                )

    # === LLM GENERIC (extracción abierta para documentos genéricos) ===
    if settings.llm_fallback_enabled and ocr_text and doc_type in {"GENERICO", "UNKNOWN"}:
        try:
            from app.services.llm_fallback import try_llm_generic_extraction, merge_llm_fields
            _generic_llm_fields = await try_llm_generic_extraction(
                ocr_text, fields,
                api_key=settings.anthropic_api_key,
                model=settings.llm_fallback_model,
            )
            if _generic_llm_fields:
                fields = merge_llm_fields(fields, _generic_llm_fields)
                logger.info(
                    "LLM generic añadió %d campos para doc_type=%s document_id=%s",
                    len(_generic_llm_fields), doc_type, document_id,
                )
        except Exception:
            logger.exception(
                "LLM generic falló, continuando sin él (doc_type=%s, document_id=%s)",
                doc_type, document_id,
            )

    # === CORRECCIÓN DE TIPO POR CAMPOS EXTRAÍDOS ============================
    doc_type, doc_confidence, type_correction_warning = _correct_doc_type_from_fields(
        doc_type, fields, doc_confidence
    )
    if type_correction_warning:
        # Re-run postprocessing con el tipo corregido
        fields = _postprocess_fields(doc_type, fields)

    # === EXTRACCIÓN Y POST-PROCESO DE TABLAS ================================
    detected_bank = _detect_bank_from_fields(fields)
    extracted_tables = _process_all_tables(
        pdf_tables, doc_type, detected_bank, fields,
        ocr_boxes=extraction_boxes,
    )
    # TABLE_NOT_FOUND no aplica cuando la tabla viene embebida en tabla_celdas / pago_detalle
    _table_embedded = any(
        f.get("key") in {"tabla_celdas", "pago_detalle"} and f.get("value")
        for f in fields
    )
    table_not_found = (
        doc_type in _TABLE_REQUIRED_DOC_TYPES
        and not extracted_tables
        and not _table_embedded
    )
    # ========================================================================

    if doc_type == "ACTA_NACIMIENTO":
        fields, acta_guard_warnings = _apply_acta_sanity_guards(fields)

    critical_keys = set(CRITICAL_FIELDS.get(doc_type, []))
    for field in fields:
        if field.get("key") in critical_keys and field.get("valid") and field.get("confidence", 0) < 0.8:
            field["confidence"] = 0.8

    required = CRITICAL_FIELDS.get(doc_type, [])
    invalid_critical = []
    for key in required:
        field = _select_required_field(doc_type, key, fields)
        if not field or not _is_effectively_valid(doc_type, key, field):
            invalid_critical.append(key)

    processing_ms = int((time.time() - start) * 1000)

    warnings: list[str] = []
    if forced_doc_type:
        warnings.append(f"Tipo forzado manualmente: {forced_doc_type}.")
    if doc_type_warning:
        warnings.append(doc_type_warning)
    if type_correction_warning:
        warnings.append(type_correction_warning)
    if acta_guard_warnings:
        warnings.extend(acta_guard_warnings)
    include_ocr_text = bool(options_data.get("return_ocr_text"))
    include_boxes = bool(options_data.get("return_boxes"))
    if not ocr_text:
        warnings.append("No se detectó texto. Verifica OCR o la calidad del documento.")

    status = "READY"
    required = CRITICAL_FIELDS.get(doc_type, [])
    found_required = 0
    for key in required:
        if _select_required_field(doc_type, key, fields):
            found_required += 1

    missing: list[str] = []
    if required:
        coverage = found_required / max(1, len(required))
        if coverage < 1:
            doc_confidence = min(doc_confidence, 0.75)
            missing = [key for key in required if not _select_required_field(doc_type, key, fields)]
            if missing:
                warnings.append(f"Campos críticos faltantes: {', '.join(missing)}")
            else:
                warnings.append("Campos críticos incompletos.")

    if missing:
        status = "NEEDS_REVIEW"

    if invalid_critical:
        status = "NEEDS_REVIEW"
        warnings.append(f"Campos críticos inválidos: {', '.join(invalid_critical)}")
    elif doc_confidence < 0.8 and not required:
        status = "NEEDS_REVIEW"

    if len(fields) == 0:
        status = "NEEDS_REVIEW"
        warnings.append("No se detectaron campos extraídos.")

    if table_not_found:
        status = "NEEDS_REVIEW"
        warnings.append("No se detectó tabla principal en el documento.")

    strict_warnings, strict_hard_fail = _evaluate_payroll_strict(fields, doc_type)
    if strict_warnings:
        warnings.extend(strict_warnings)
    if strict_hard_fail:
        status = "NEEDS_REVIEW"

    if warnings:
        deduped_warnings: list[str] = []
        seen: set[str] = set()
        for warning in warnings:
            key = str(warning or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped_warnings.append(key)
        warnings = deduped_warnings

    try:
        learn_from_processed_document(
            document_id=document_id,
            document_type=doc_type,
            status=status,
            confidence=doc_confidence,
            ocr_text=ocr_text,
            fields=fields,
            processing_ms=(time.time() - start) * 1000,
            critical_keys=list(CRITICAL_FIELDS.get(doc_type, [])),
        )
    except Exception:
        logger.exception("Online learning failed for document_id=%s", document_id)

    # ── Construir campos con flag is_critical ─────────────────────────────────
    critical_keys_set: set[str] = set()
    for k in CRITICAL_FIELDS.get(doc_type, []):
        critical_keys_set.update(_critical_aliases(doc_type, k))

    campos_out: list[CampoExtraido] = []
    for f in fields:
        field_key = str(f.get("key", "") or "")
        campos_out.append(CampoExtraido(
            key=field_key,
            label=str(f.get("label", field_key) or field_key),
            value=f.get("value"),
            confidence=round(float(f.get("confidence", 0.0) or 0.0), 4),
            is_critical=bool(field_key in critical_keys_set),
            is_valid=bool(f.get("valid", True)),
        ))

    # ── Construir tablas en el nuevo formato ──────────────────────────────────
    tablas_out: list[TablaExtraida] = []
    for i, t in enumerate(extracted_tables):
        nombre_tabla = "tabla_principal" if i == 0 else f"tabla_secundaria_{i}"
        tablas_out.append(TablaExtraida(
            name=nombre_tabla,
            headers_detected=list(t.columns),
            rows=[],  # raw rows no se preservan en este path; usar canonical_rows
            canonical_rows=list(t.rows),
        ))

    # ── Calcular confidence_global ────────────────────────────────────────────
    # Campos críticos pesan 70%, el resto 30%; se blendea con la confianza del
    # clasificador para que un tipo muy seguro suba el score global.
    critical_campos = [c for c in campos_out if c.is_critical]
    non_critical_campos = [c for c in campos_out if not c.is_critical]
    if critical_campos:
        crit_avg = sum(c.confidence for c in critical_campos) / len(critical_campos)
        if non_critical_campos:
            other_avg = sum(c.confidence for c in non_critical_campos) / len(non_critical_campos)
            fields_confidence = crit_avg * 0.7 + other_avg * 0.3
        else:
            fields_confidence = crit_avg
    elif campos_out:
        fields_confidence = sum(c.confidence for c in campos_out) / len(campos_out)
    else:
        fields_confidence = 0.0
    confidence_global = round((fields_confidence + doc_confidence) / 2, 4)

    # ── Calcular validation_summary ───────────────────────────────────────────
    required_count = len(required)
    critical_coverage_val = round(found_required / max(1, required_count), 4) if required_count else 1.0
    populated_count = sum(1 for c in campos_out if c.value not in {None, ""})
    coverage_val = round(populated_count / max(1, len(campos_out)), 4) if campos_out else 1.0
    requires_review = status == "NEEDS_REVIEW"

    # Calidad de la mejor tabla (escala 0-100 interna)
    table_quality_score_val = round(float(extracted_tables[0].quality), 2) if extracted_tables else 0.0

    # score_decision por umbrales formales
    # "accepted" requiere además que no haya ninguna bandera de revisión activa
    if (
        critical_coverage_val >= 0.9
        and not invalid_critical
        and not table_not_found
        and not requires_review
    ):
        score_decision = "accepted"
    elif critical_coverage_val >= 0.7:
        score_decision = "review"
    else:
        score_decision = "reprocess"

    # ── Construir mensaje y error_code ────────────────────────────────────────
    # Orden de prioridad: OCR → tipo desconocido → tabla faltante →
    #   campos críticos faltantes → campos inválidos → baja confianza → ok
    if not ocr_text:
        main_message = "No se detectó texto en el documento."
        error_code_out: str | None = "OCR_FAILED"
        stage_out: str | None = "ocr"
        success_out = False
    elif doc_type in {"UNKNOWN"} and not forced_doc_type:
        main_message = "Tipo de documento no identificado."
        error_code_out = "DOCUMENT_TYPE_UNKNOWN"
        stage_out = "classification"
        success_out = True
    elif table_not_found:
        main_message = "No se detectó tabla principal en el documento."
        error_code_out = "TABLE_NOT_FOUND"
        stage_out = "table_extraction"
        success_out = True
    elif requires_review and missing:
        main_message = f"Campos críticos faltantes: {', '.join(missing)}."
        error_code_out = "CRITICAL_FIELDS_MISSING"
        stage_out = "validation"
        success_out = True
    elif requires_review and invalid_critical:
        main_message = f"Campos críticos inválidos: {', '.join(invalid_critical)}."
        error_code_out = "CRITICAL_FIELDS_INVALID"
        stage_out = "validation"
        success_out = True
    elif requires_review:
        main_message = "Documento requiere revisión manual."
        error_code_out = "LOW_CONFIDENCE_RESULT"
        stage_out = "validation"
        success_out = True
    else:
        main_message = "Documento procesado correctamente."
        error_code_out = None
        stage_out = None
        success_out = True

    # ── Log estructurado final ────────────────────────────────────────────────
    logger.info(
        "doc_id=%s tipo=%s score=%s success=%s confidence=%.3f "
        "critical=%.2f/%d campos=%d tablas=%d tabla_quality=%.1f "
        "ocr=%s ms=%d ms_ocr=%.0f ms_extract=%.0f | %s",
        document_id, doc_type, score_decision, success_out,
        confidence_global,
        critical_coverage_val, required_count,
        len(campos_out), len(tablas_out), table_quality_score_val,
        ocr_engine, processing_ms, t_ocr_ms, t_extract_ms,
        error_code_out or "OK",
    )

    return ProcessResponse(
        document_id=document_id,
        tipo_documento=doc_type,
        success=success_out,
        message=main_message,
        confidence_global=confidence_global,
        campos=campos_out,
        tablas=tablas_out,
        metadata=MetadataDocumento(
            filename=str(getattr(file, "filename", "") or ""),
            pages=len(images),
            source=source or "web",
            processing_time_ms=processing_ms,
            ocr_engine=ocr_engine,
            pipeline_version=settings.pipeline_version,
            model_version=settings.model_version,
        ),
        validation_summary=ValidationSummary(
            coverage=coverage_val,
            critical_coverage=critical_coverage_val,
            requires_review=requires_review,
            score_decision=score_decision,
            table_quality_score=table_quality_score_val,
        ),
        warnings=warnings,
        errors=[],
        error_code=error_code_out,  # None solo cuando todo está OK
        stage=stage_out,            # None solo cuando todo está OK
        ocr_text=ocr_text if include_ocr_text else None,
        ocr_boxes=(ocr_boxes if ocr_boxes else text_layer_boxes) if include_boxes else None,
    )
