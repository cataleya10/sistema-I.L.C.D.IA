"""
Nómina Extractor — extractor dedicado para Recibos de Nómina / Comprobantes de Pago

Campos que extrae:
  - nombre            (empleado)
  - rfc               (empleado)
  - nss               (Número de Seguro Social)
  - curp              (CURP del empleado)
  - periodo           (fechas inicio-fin del periodo de pago)
  - fecha_pago        (fecha en que se realizó el pago)
  - empresa           (razón social del empleador)
  - tabla_celdas      (desglose de percepciones y deducciones como tabla)
  - pago_detalle      (filas normalizadas del recibo)
  - total_percepciones
  - total_deducciones
  - neto_pagar

Estrategia:
  1. El pipeline FACTURA extrae la tabla de celdas (desglose percepciones/deducciones).
  2. El enriquecimiento post-pipeline añade los campos del empleado (NSS, CURP, RFC,
     nombre, empresa, periodo, fecha_pago, totales) que el pipeline FACTURA no extrae.
  3. Se usa raw_text (capa nativa del PDF) como fuente primaria cuando está disponible,
     ya que los CFDI son documentos XML cuyo PDF tiene texto seleccionable de calidad.
  4. Para cada campo se intentan varios patrones en orden de confianza decreciente.
"""

import logging
import re
from typing import Any

from app.pipelines.extract import extract_fields as _extract_fields

logger = logging.getLogger(__name__)

# Campos esperados en un recibo de nómina
EXPECTED_FIELDS = frozenset({
    "nombre", "rfc", "nss", "curp", "periodo", "fecha_pago",
    "empresa", "tabla_celdas", "pago_detalle",
    "total_percepciones", "total_deducciones", "neto_pagar",
})

# El orquestador usa FACTURA para extraer la tabla de celdas
DOCUMENT_TYPE = "FACTURA"

# ─── Patrones de extracción específicos de nómina ────────────────────────────

# NSS — múltiples formas de etiqueta
_NSS_PATTERNS: list[re.Pattern] = [
    re.compile(r"N[UÚ]MERO\s+DE\s+SEGURO\s+SOCIAL[:\s.]+(\d{11})", re.IGNORECASE),
    re.compile(r"N[UÚ]MERO\s+SEGURO\s+SOCIAL[:\s.]+(\d{11})", re.IGNORECASE),
    re.compile(r"\bNSS[:\s.]+(\d{11})\b", re.IGNORECASE),
    re.compile(r"SEGURO\s+SOCIAL[:\s.]+(\d{11})", re.IGNORECASE),
    re.compile(r"N\.\s*S\.\s*S[:\s.]+(\d{11})", re.IGNORECASE),
    re.compile(r"NO\.\s*SEGURO[:\s.]+(\d{11})", re.IGNORECASE),
]

# Periodo — múltiples formatos de fecha
_PERIODO_PATTERNS: list[tuple[re.Pattern, str]] = [
    # "PERIODO: 01/01/2024 AL 31/01/2024"
    (re.compile(
        r"PERIODO[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
        r"\s+(?:AL?|A)\s+"
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        re.IGNORECASE,
    ), "rango"),
    # "DEL 01/01/2024 AL 31/01/2024"
    (re.compile(
        r"(?:PERIODO[:\s]+)?DEL?\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
        r"\s+(?:AL?|A)\s+"
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        re.IGNORECASE,
    ), "rango"),
    # "01 DE ENERO DE 2024 AL 31 DE ENERO DE 2024"
    (re.compile(
        r"(\d{1,2}\s+DE\s+[A-ZÁÉÍÓÚÜÑ]+\s+DE\s+\d{4})"
        r"\s+(?:AL?|A)\s+"
        r"(\d{1,2}\s+DE\s+[A-ZÁÉÍÓÚÜÑ]+\s+DE\s+\d{4})",
        re.IGNORECASE,
    ), "rango"),
    # "PERIODO: ENERO 2024"  /  "PERIODO: 01/2024"
    (re.compile(
        r"PERIODO[:\s]+([A-ZÁÉÍÓÚÜÑ]{4,}\s+\d{4}|\d{1,2}/\d{4})",
        re.IGNORECASE,
    ), "simple"),
]

# Fecha de pago
_FECHA_PAGO_PATTERNS: list[re.Pattern] = [
    re.compile(r"FECHA\s+DE\s+PAGO[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.IGNORECASE),
    re.compile(r"FECHA\s+PAGO[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.IGNORECASE),
    re.compile(r"F(?:\.|ECHA)?\s*PAGO[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.IGNORECASE),
    re.compile(r"PAGO[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.IGNORECASE),
]

# Empresa / razón social del empleador
_EMPRESA_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"(?:EMPRESA|RAZ[OÓ]N\s+SOCIAL|EMPLEADOR|NOMBRE\s+(?:DEL\s+)?PATR[OÓ]N)[:\s]+"
        r"([A-ZÁÉÍÓÚÜÑ&][A-ZÁÉÍÓÚÜÑ\s,\.&\-]{4,80}?)"
        r"(?:\n|\s{2,}|RFC|NSS|CURP|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"PATR[OÓ]N[:\s]+([A-ZÁÉÍÓÚÜÑ&][A-ZÁÉÍÓÚÜÑ\s,\.&\-]{4,80}?)"
        r"(?:\n|\s{2,}|RFC|$)",
        re.IGNORECASE,
    ),
]

# Nombre del empleado
_NOMBRE_EMPLEADO_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"(?:NOMBRE\s+(?:DEL\s+)?(?:EMPLEADO|TRABAJADOR)|TRABAJADOR)[:\s]+"
        r"([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ\s]{4,60}?)"
        r"(?:\n|\s{2,}|RFC|NSS|CURP|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"NOMBRE[:\s]+([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ\s]{4,60}?)"
        r"(?:\n|\s{2,}|RFC|NSS|CURP|PERIODO|$)",
        re.IGNORECASE,
    ),
]

# RFC del empleado (vs empresa — el empleado es persona física: 13 chars)
_RFC_EMPLEADO_PATTERNS: list[re.Pattern] = [
    re.compile(r"RFC\s+(?:DEL\s+)?(?:EMPLEADO|TRABAJADOR)[:\s]+([A-Z&]{4}\d{6}[A-Z0-9]{3})\b", re.IGNORECASE),
    re.compile(r"RFC\s+EMPLEADO[:\s]+([A-Z&]{4}\d{6}[A-Z0-9]{3})\b", re.IGNORECASE),
    # RFC de persona física suelto (4 letras iniciales = persona física)
    re.compile(r"\bRFC[:\s]+([A-Z&]{4}\d{6}[A-Z0-9]{3})\b", re.IGNORECASE),
]

# Totales
_TOTAL_PERCEPCIONES_PATTERNS: list[re.Pattern] = [
    re.compile(r"TOTAL\s+DE\s+PERCEPCIONES[:\s\$]+([\d,]+\.?\d*)", re.IGNORECASE),
    re.compile(r"TOTAL\s+PERCEPCIONES[:\s\$]+([\d,]+\.?\d*)", re.IGNORECASE),
    re.compile(r"PERCEPCIONES\s+TOTALES[:\s\$]+([\d,]+\.?\d*)", re.IGNORECASE),
    re.compile(r"TOTAL\s+GRAVADO[:\s\$]+([\d,]+\.?\d*)", re.IGNORECASE),
]

_TOTAL_DEDUCCIONES_PATTERNS: list[re.Pattern] = [
    re.compile(r"TOTAL\s+DE\s+DEDUCCIONES[:\s\$]+([\d,]+\.?\d*)", re.IGNORECASE),
    re.compile(r"TOTAL\s+DEDUCCIONES[:\s\$]+([\d,]+\.?\d*)", re.IGNORECASE),
    re.compile(r"DEDUCCIONES\s+TOTALES[:\s\$]+([\d,]+\.?\d*)", re.IGNORECASE),
]

_NETO_PAGAR_PATTERNS: list[re.Pattern] = [
    re.compile(r"NETO\s+A\s+PAGAR[:\s\$]+([\d,]+\.?\d*)", re.IGNORECASE),
    re.compile(r"TOTAL\s+NETO[:\s\$]+([\d,]+\.?\d*)", re.IGNORECASE),
    re.compile(r"IMPORTE\s+NETO[:\s\$]+([\d,]+\.?\d*)", re.IGNORECASE),
    re.compile(r"SALARIO\s+NETO[:\s\$]+([\d,]+\.?\d*)", re.IGNORECASE),
    re.compile(r"\bNETO[:\s\$]+([\d,]+\.?\d*)", re.IGNORECASE),
]


# ─── Extractor principal ─────────────────────────────────────────────────────

async def extract(
    ocr_text: str,
    ocr_boxes: list[dict[str, Any]] | None = None,
    raw_text: str = "",
    filename: str | None = None,
    pdf_tables: list[list[list[str]]] | None = None,
) -> list[dict[str, Any]]:
    """
    Extrae campos de un Recibo de Nómina / Comprobante de Pago CFDI.

    Args:
        ocr_text:   Texto completo del OCR (imagen/scan).
        ocr_boxes:  Bounding boxes del OCR con confianza y coordenadas.
        raw_text:   Texto del layer nativo del PDF — fuente primaria para CFDI.
        filename:   Nombre del archivo.
        pdf_tables: Tablas detectadas por pdfplumber/img2table.

    Returns:
        Lista de campos extraídos con el desglose completo de la nómina.
    """
    fields = await _extract_fields(
        document_type=DOCUMENT_TYPE,
        ocr_text=ocr_text,
        ocr_boxes=ocr_boxes,
        raw_text=raw_text,
        filename=filename,
        pdf_tables=pdf_tables,
    )

    _enrich_nomina_fields(fields, ocr_text=ocr_text, raw_text=raw_text, ocr_boxes=ocr_boxes or [])

    _log_coverage(fields, filename)
    return fields


# ─── Enriquecimiento ─────────────────────────────────────────────────────────

def _enrich_nomina_fields(
    fields: list[dict[str, Any]],
    ocr_text: str,
    raw_text: str,
    ocr_boxes: list[dict[str, Any]],
) -> None:
    """
    Añade/mejora campos específicos de nómina que el pipeline FACTURA no extrae.
    Opera sobre la lista in-place.

    Usa raw_text como fuente primaria (mayor calidad en CFDI con capa PDF nativa);
    cae a ocr_text cuando raw_text está vacío o no produce resultados.
    """
    from app.pipelines.extract.common import _make_field, _normalize_text
    from app.utils.regex_patterns import RFC_PATTERN, search_curp

    existing_keys = {f.get("key") for f in fields if f.get("value")}

    # Fuente primaria: raw_text (capa nativa PDF) > ocr_text
    primary = raw_text.strip() if raw_text and raw_text.strip() else ocr_text
    secondary = ocr_text if primary is raw_text else ""

    def _try_patterns(
        patterns: list[re.Pattern],
        key: str,
        label: str,
        confidence: float = 0.82,
        group: int = 1,
    ) -> bool:
        """Intenta los patrones contra primary y luego secondary. Retorna True si agrega."""
        if key in existing_keys:
            return False
        for src in (primary, secondary):
            if not src:
                continue
            for pat in patterns:
                m = pat.search(src)
                if m:
                    val = m.group(group).strip()
                    if val:
                        fields.append(_make_field(key, label, val, ocr_boxes, confidence=confidence))
                        existing_keys.add(key)
                        logger.debug("nomina enrich: %s='%s'", key, val)
                        return True
        return False

    # ── NSS ──────────────────────────────────────────────────────────────────
    _try_patterns(_NSS_PATTERNS, "nss", "NSS", confidence=0.85)

    # ── CURP del empleado ─────────────────────────────────────────────────────
    if "curp" not in existing_keys:
        for src in (primary, secondary):
            if not src:
                continue
            curp_val = search_curp(src)
            if curp_val:
                fields.append(_make_field("curp", "CURP", curp_val, ocr_boxes, confidence=0.88))
                existing_keys.add("curp")
                logger.debug("nomina enrich: curp='%s'", curp_val)
                break

    # ── RFC del empleado ──────────────────────────────────────────────────────
    _try_patterns(_RFC_EMPLEADO_PATTERNS, "rfc", "RFC", confidence=0.83)

    # ── Nombre del empleado ───────────────────────────────────────────────────
    _try_patterns(_NOMBRE_EMPLEADO_PATTERNS, "nombre", "Nombre", confidence=0.75)

    # ── Empresa / razón social ────────────────────────────────────────────────
    _try_patterns(_EMPRESA_PATTERNS, "empresa", "Empresa", confidence=0.78)

    # ── Periodo ───────────────────────────────────────────────────────────────
    if "periodo" not in existing_keys:
        for src in (primary, secondary):
            if not src:
                continue
            for pat, tipo in _PERIODO_PATTERNS:
                m = pat.search(src)
                if m:
                    if tipo == "rango":
                        val = f"{m.group(1).strip()} al {m.group(2).strip()}"
                    else:
                        val = m.group(1).strip()
                    fields.append(_make_field("periodo", "Periodo", val, ocr_boxes, confidence=0.80))
                    existing_keys.add("periodo")
                    logger.debug("nomina enrich: periodo='%s'", val)
                    break
            if "periodo" in existing_keys:
                break

    # ── Fecha de pago ─────────────────────────────────────────────────────────
    _try_patterns(_FECHA_PAGO_PATTERNS, "fecha_pago", "Fecha de pago", confidence=0.82)

    # ── Totales ───────────────────────────────────────────────────────────────
    _try_patterns(_TOTAL_PERCEPCIONES_PATTERNS, "total_percepciones", "Total percepciones", confidence=0.80)
    _try_patterns(_TOTAL_DEDUCCIONES_PATTERNS, "total_deducciones", "Total deducciones", confidence=0.80)
    _try_patterns(_NETO_PAGAR_PATTERNS, "neto_pagar", "Neto a pagar", confidence=0.82)


def _log_coverage(fields: list[dict[str, Any]], filename: str | None) -> None:
    """Emite un log INFO con qué campos se encontraron y cuáles faltan."""
    found = {f.get("key") for f in fields if f.get("value")}
    missing = EXPECTED_FIELDS - found
    pct = int(100 * len(found & EXPECTED_FIELDS) / len(EXPECTED_FIELDS))
    if missing:
        logger.info(
            "nomina [%s] cobertura %d%% — faltan: %s",
            filename or "?",
            pct,
            ", ".join(sorted(missing)),
        )
    else:
        logger.info("nomina [%s] cobertura 100%%", filename or "?")


def get_expected_fields() -> frozenset[str]:
    """Devuelve el conjunto de campos que este extractor debe producir."""
    return EXPECTED_FIELDS
