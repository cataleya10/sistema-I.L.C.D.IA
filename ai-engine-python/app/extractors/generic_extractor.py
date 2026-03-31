"""
Generic Extractor — extractor para documentos no clasificados o de tipo desconocido

Campos que extrae (los que encuentre):
  - texto_detectado     (snippet del OCR para revisión manual)
  - tipo_sugerido       (tipo de documento inferido de los identificadores encontrados)
  - CURP, RFC, NSS, CLABE, email, teléfono, montos, fechas
  - Pares KV detectados por layout espacial o texto
  - Tablas (tabla_celdas_1, tabla_celdas_2, ...)

Cuándo se usa:
  - Documentos clasificados como GENERICO o UNKNOWN
  - Como fallback cuando el clasificador no tiene suficiente confianza
  - Para documentos nuevos aún no cubiertos por un extractor dedicado

Estrategia:
  1. El pipeline GENERICO extrae KV por layout, identifiers y tablas.
  2. El enriquecimiento post-pipeline añade:
     - texto_detectado: primeros ~300 caracteres del texto para inspección rápida
     - tipo_sugerido: inferencia ligera basada en los campos encontrados
  3. suggest_document_type() puede usarse externamente para clasificación ligera.
"""

import logging
import re
from typing import Any

from app.pipelines.extract import extract_fields as _extract_fields
from app.pipelines.extract.extractors import (
    _extract_generic_kv_from_text,
    _extract_generic_kv_from_boxes,
    _extract_generic_identifiers,
)
from app.utils.regex_patterns import (
    CURP_PATTERN,
    RFC_PATTERN,
    NSS_PATTERN,
    CLABE_PATTERN,
    search_curp,
)

logger = logging.getLogger(__name__)

DOCUMENT_TYPE_GENERIC = "GENERICO"
DOCUMENT_TYPE_UNKNOWN = "UNKNOWN"

# Longitud máxima del snippet de texto para texto_detectado
_SNIPPET_MAX_CHARS = 300

# Umbral mínimo de confianza para incluir tipo_sugerido
_SUGGESTION_MIN_CONFIDENCE = 0.6

# Señales de texto que apuntan a un tipo de documento específico
_TYPE_SIGNALS: list[tuple[str, str, float]] = [
    # (patron_regex, tipo_sugerido, confianza)
    (r"INSTITUTO NACIONAL ELECTORAL|CREDENCIAL PARA VOTAR|CLAVE DE ELECTOR",      "INE",                       0.85),
    (r"CONSTANCIA.*CLAVE UNICA|CLAVE UNICA DE REGISTRO DE POBLACION|CURP CERTIF", "CURP",                      0.85),
    (r"ACTA DE NACIMIENTO|REGISTRO CIVIL",                                         "ACTA_NACIMIENTO",           0.80),
    (r"NUMERO DE SEGURIDAD SOCIAL|IMSS.*NSS|NSS.*IMSS",                            "NSS",                       0.80),
    (r"ESTADO DE CUENTA|FECHA DE CORTE|SALDO ANTERIOR|SALDO INICIAL",              "DATOS_BANCARIOS",           0.80),
    (r"CONSTANCIA DE SITUACION FISCAL|CEDULA DE IDENTIFICACION FISCAL",            "CONSTANCIA_SITUACION_FISCAL", 0.85),
    (r"RECIBO DE NOMINA|COMPROBANTE DE PAGO.*NOMINA|TOTAL PERCEPCIONES|NSS.*CURP", "NOMINA",                    0.78),
    (r"COMPROBANTE.*CFE|TELMEX|TOTALPLAY|LINEA DE CAPTURA|BIMESTRE",               "COMPROBANTE_DOMICILIO",     0.80),
    (r"UUID|FOLIO FISCAL|TIMBRE FISCAL DIGITAL|COMPROBANTE FISCAL DIGITAL",        "CFDI",                      0.88),
    (r"TRANSFERENCIA SPEI|CLAVE RASTREO|COMPROBANTE.*TRANSFERENCIA|ABONO NOMINA",  "FACTURA",                   0.75),
]


# ─── Extractor principal ─────────────────────────────────────────────────────

async def extract(
    ocr_text: str,
    ocr_boxes: list[dict[str, Any]] | None = None,
    raw_text: str = "",
    filename: str | None = None,
    pdf_tables: list[list[list[str]]] | None = None,
    document_type: str = DOCUMENT_TYPE_GENERIC,
) -> list[dict[str, Any]]:
    """
    Extrae campos de un documento de tipo desconocido o genérico.

    Args:
        ocr_text:      Texto OCR completo.
        ocr_boxes:     Bounding boxes del OCR.
        raw_text:      Texto nativo del PDF.
        filename:      Nombre del archivo.
        pdf_tables:    Tablas detectadas.
        document_type: "GENERICO" o "UNKNOWN".

    Returns:
        Lista de campos encontrados. Incluye:
        - texto_detectado (snippet del contenido para revisión)
        - tipo_sugerido (tipo inferido, si hay señales suficientes)
        - Pares KV por layout / patrones
        - Identificadores estándar (CURP, RFC, NSS, CLABE)
        - tabla_celdas_N (tablas encontradas)
    """
    fields = await _extract_fields(
        document_type=document_type,
        ocr_text=ocr_text,
        ocr_boxes=ocr_boxes,
        raw_text=raw_text,
        filename=filename,
        pdf_tables=pdf_tables,
    )

    _enrich_generic(fields, ocr_text=ocr_text, raw_text=raw_text, filename=filename)
    return fields


# ─── Enriquecimiento post-pipeline ───────────────────────────────────────────

def _enrich_generic(
    fields: list[dict[str, Any]],
    ocr_text: str,
    raw_text: str,
    filename: str | None,
) -> None:
    """
    Añade campos de utilidad para documentos desconocidos:
    - texto_detectado: snippet del texto para inspección rápida
    - tipo_sugerido: tipo inferido si hay señales claras

    Modifica la lista in-place.
    """
    existing_keys = {f.get("key") for f in fields if f.get("value")}
    combined = (ocr_text or "") or (raw_text or "")

    # ── texto_detectado ───────────────────────────────────────────────────────
    if "texto_detectado" not in existing_keys and combined.strip():
        snippet = " ".join(combined.split())[:_SNIPPET_MAX_CHARS]
        fields.append({
            "key": "texto_detectado",
            "label": "Texto detectado",
            "value": snippet,
            "confidence": 1.0,
            "valid": True,
            "source": None,
        })

    # ── tipo_sugerido ─────────────────────────────────────────────────────────
    if "tipo_sugerido" not in existing_keys and combined.strip():
        suggestion, conf = suggest_document_type(combined)
        if suggestion and conf >= _SUGGESTION_MIN_CONFIDENCE:
            fields.append({
                "key": "tipo_sugerido",
                "label": "Tipo sugerido",
                "value": suggestion,
                "confidence": conf,
                "valid": True,
                "source": None,
            })

    _log_summary(fields, filename)


def _log_summary(fields: list[dict[str, Any]], filename: str | None) -> None:
    """Log de resumen: qué campos y qué tipo sugerido se encontraron."""
    identifiers = [
        f.get("key") for f in fields
        if f.get("key") in {"curp", "rfc", "nss", "clabe", "email", "telefono"} and f.get("value")
    ]
    tables = sum(1 for f in fields if str(f.get("key", "")).startswith("tabla_celdas"))
    tipo = next((f.get("value") for f in fields if f.get("key") == "tipo_sugerido"), None)

    logger.info(
        "generic [%s]: %d campos, identifiers=%s, tablas=%d, tipo_sugerido=%s",
        filename or "?",
        len(fields),
        identifiers or "ninguno",
        tables,
        tipo or "indeterminado",
    )


# ─── API pública ─────────────────────────────────────────────────────────────

def suggest_document_type(text: str) -> tuple[str | None, float]:
    """
    Infiere un tipo de documento probable basado en señales de texto.

    Usa patrones ligeros — no reemplaza al clasificador principal pero
    es útil para enriquecer documentos GENERICO con una pista de tipo.

    Args:
        text: Texto OCR o texto nativo del documento.

    Returns:
        Tupla (tipo_sugerido, confianza). Retorna (None, 0.0) si no hay señal clara.
    """
    upper = (text or "").upper()

    best_type: str | None = None
    best_conf: float = 0.0

    for pattern_str, doc_type, confidence in _TYPE_SIGNALS:
        if re.search(pattern_str, upper):
            if confidence > best_conf:
                best_type = doc_type
                best_conf = confidence

    # Refuerzo por identificadores encontrados
    if best_type is None:
        if search_curp(upper):
            best_type, best_conf = "CURP", 0.65
        elif CLABE_PATTERN.search(upper):
            best_type, best_conf = "DATOS_BANCARIOS", 0.62

    return best_type, best_conf


def extract_identifiers(
    ocr_text: str,
    ocr_boxes: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """
    Busca identificadores estándar en el texto: CURP, RFC, NSS, CLABE.

    Nota: CLABE (18 dígitos) y NSS (11 dígitos) se buscan de forma
    independiente — si aparecen ambos, se retornan ambos.

    Args:
        ocr_text:  Texto OCR o texto nativo.
        ocr_boxes: Bounding boxes (no utilizados actualmente, reservado).

    Returns:
        Dict {tipo_identificador: valor} con los encontrados.
    """
    upper = (ocr_text or "").upper()
    result: dict[str, str] = {}

    # CURP — con corrección OCR
    curp_val = search_curp(upper)
    if curp_val:
        result["curp"] = curp_val

    # RFC
    rfc_m = RFC_PATTERN.search(upper)
    if rfc_m:
        result["rfc"] = rfc_m.group(0)

    # CLABE (18 dígitos) — independiente de NSS
    clabe_m = CLABE_PATTERN.search(upper)
    if clabe_m:
        result["clabe"] = clabe_m.group(0)

    # NSS (11 dígitos) — independiente de CLABE
    # Solo si hay contexto de seguridad social para evitar falsos positivos
    if re.search(r"NSS|SEGURIDAD\s*SOCIAL|IMSS|NUMERO\s*DE\s*SEGURO", upper):
        nss_m = NSS_PATTERN.search(upper)
        if nss_m:
            result["nss"] = nss_m.group(0)

    return result


def extract_kv_from_text(text: str) -> list[dict[str, Any]]:
    """
    Extrae pares clave-valor directamente del texto plano usando patrones.
    No requiere boxes. Útil para pre-análisis rápido.

    Returns:
        Lista de {key, label, value, confidence}.
    """
    return _extract_generic_kv_from_text(text)


def extract_kv_from_boxes(ocr_boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Extrae pares clave-valor usando la posición espacial de los bounding boxes.
    Más preciso que extract_kv_from_text para documentos con layout estructurado.

    Returns:
        Lista de {key, label, value, confidence}.
    """
    return _extract_generic_kv_from_boxes(ocr_boxes)


def extract_all_identifiers(
    ocr_text: str,
    ocr_boxes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Versión extendida de extract_identifiers que retorna campos completos
    (con confianza, label, source) en lugar de un dict simple.

    Incluye: CURP, RFC, NSS, CLABE, email, teléfono, montos, fechas.

    Returns:
        Lista de campos en formato estándar del sistema.
    """
    return _extract_generic_identifiers(ocr_text, ocr_boxes)
