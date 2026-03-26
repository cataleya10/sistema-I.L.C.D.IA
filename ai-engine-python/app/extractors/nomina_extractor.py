"""
Nómina Extractor — extractor dedicado para Recibos de Nómina / Comprobantes de Pago

Campos que extrae:
  - nombre (empleado)
  - rfc (empleado y/o empresa)
  - nss
  - curp
  - periodo (fecha inicio y fin del pago)
  - fecha_pago
  - empresa (razón social del empleador)
  - tabla_celdas (desglose de percepciones y deducciones)
  - pago_detalle (filas normalizadas del recibo)
  - total_percepciones
  - total_deducciones
  - neto_pagar

Nota: La nómina comparte estructura con FACTURA (tabla CFDI) pero tiene
campos propios como NSS, CURP del empleado y desglose de conceptos.
El pipeline usa FACTURA como base y aplica reglas adicionales de nómina.
"""

from typing import Any

from app.pipelines.extract import extract_fields as _extract_fields

# Campos esperados en un recibo de nómina
EXPECTED_FIELDS = frozenset({
    "nombre", "rfc", "nss", "curp", "periodo", "fecha_pago",
    "empresa", "tabla_celdas", "pago_detalle",
    "total_percepciones", "total_deducciones", "neto_pagar",
})

# El tipo de documento que reconoce el orquestador actual para nóminas
# (usa el pipeline FACTURA con detección de estructura CFDI de nómina)
DOCUMENT_TYPE = "FACTURA"


async def extract(
    ocr_text: str,
    ocr_boxes: list[dict[str, Any]] | None = None,
    raw_text: str = "",
    filename: str | None = None,
    pdf_tables: list[list[list[str]]] | None = None,
) -> list[dict[str, Any]]:
    """
    Extrae campos de un Recibo de Nómina / Comprobante de Pago.

    El recibo de nómina es un CFDI tipo Nómina (complemento 1.2 o 1.1).
    Se extrae la tabla de percepciones/deducciones y los datos del empleado.

    Args:
        ocr_text:   Texto completo resultado del OCR.
        ocr_boxes:  Lista de bounding boxes del OCR.
        raw_text:   Texto del layer nativo del PDF (preferido para CFDI).
        filename:   Nombre del archivo.
        pdf_tables: Tablas detectadas por pdfplumber/img2table.

    Returns:
        Lista de campos extraídos con el desglose de la nómina.
    """
    fields = await _extract_fields(
        document_type=DOCUMENT_TYPE,
        ocr_text=ocr_text,
        ocr_boxes=ocr_boxes,
        raw_text=raw_text,
        filename=filename,
        pdf_tables=pdf_tables,
    )

    # Enriquecimiento específico de nómina: extrae NSS y CURP del empleado
    # si el orquestador FACTURA no los detectó (son campos exclusivos de nómina)
    _enrich_nomina_fields(fields, ocr_text, ocr_boxes or [])

    return fields


def _enrich_nomina_fields(
    fields: list[dict[str, Any]],
    ocr_text: str,
    ocr_boxes: list[dict[str, Any]],
) -> None:
    """
    Agrega campos específicos de nómina que el pipeline FACTURA no extrae:
    NSS, CURP del empleado, periodo de nómina, totales.
    Modifica la lista in-place.
    """
    import re
    from app.pipelines.extract.common import (
        CURP_PATTERN, NSS_PATTERN, _make_field, _normalize_text,
    )

    existing_keys = {f.get("key") for f in fields}
    text_upper = _normalize_text(ocr_text)

    # NSS del empleado
    if "nss" not in existing_keys:
        # Busca NSS precedido por etiqueta
        nss_match = re.search(
            r"(?:N(?:UMERO\s+DE\s+)?SEGURO\s+SOCIAL|NSS)[:\s]+(\d{11})",
            text_upper
        )
        if nss_match:
            fields.append(_make_field("nss", "NSS", nss_match.group(1), ocr_boxes))

    # CURP del empleado
    if "curp" not in existing_keys:
        curp_match = CURP_PATTERN.search(text_upper)
        if curp_match:
            fields.append(_make_field("curp", "CURP", curp_match.group(0), ocr_boxes))

    # Periodo de nómina
    if "periodo" not in existing_keys:
        periodo_match = re.search(
            r"PERIODO[:\s]+(\d{2}[/-]\d{2}[/-]\d{4})\s+(?:AL?|A)\s+(\d{2}[/-]\d{2}[/-]\d{4})",
            text_upper
        )
        if periodo_match:
            periodo_val = f"{periodo_match.group(1)} al {periodo_match.group(2)}"
            fields.append(_make_field("periodo", "Periodo", periodo_val, ocr_boxes))


def get_expected_fields() -> frozenset[str]:
    """Devuelve el conjunto de campos que este extractor debe producir."""
    return EXPECTED_FIELDS
