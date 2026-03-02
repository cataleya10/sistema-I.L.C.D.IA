"""
LLM Fallback Service — usa Claude API para rescatar campos críticos
que el pipeline de OCR/regex no pudo extraer.

Se activa únicamente cuando:
  1. LLM_FALLBACK_ENABLED=true (env var)
  2. Hay campos críticos faltantes tras el pipeline principal
  3. ocr_text tiene contenido suficiente

El resultado se fusiona con los campos existentes sin sobreescribir
campos de alta confianza (>= 0.75).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Etiquetas legibles por tipo de campo para el prompt
_FIELD_LABELS: dict[str, str] = {
    "curp": "CURP (18 caracteres alfanuméricos)",
    "nombre": "Nombre completo",
    "nombre_completo": "Nombre completo",
    "fecha_nacimiento": "Fecha de nacimiento (DD/MM/AAAA)",
    "rfc": "RFC (12-13 caracteres)",
    "nss": "Número de Seguridad Social (11 dígitos)",
    "clabe": "CLABE interbancaria (18 dígitos)",
    "banco": "Nombre del banco",
    "titular": "Nombre del titular de la cuenta",
    "domicilio": "Domicilio completo",
    "cp": "Código postal (5 dígitos)",
    "folio": "Número de folio",
    "numero_acta": "Número de acta",
    "seccion": "Sección electoral",
    "vigencia": "Fecha de vigencia",
    "razon_social": "Razón social",
    "denominacion_razon_social": "Denominación o razón social",
    "tabla_celdas": "Tabla de conceptos/productos",
    "importe": "Importe o monto",
    "referencia": "Número de referencia",
    "clave_rastreo": "Clave de rastreo",
    "fecha_operacion": "Fecha de operación",
}

_DOC_TYPE_LABELS: dict[str, str] = {
    "INE": "Credencial para Votar (INE/IFE)",
    "CURP": "Cédula CURP",
    "ACTA_NACIMIENTO": "Acta de Nacimiento",
    "COMPROBANTE_DOMICILIO": "Comprobante de Domicilio",
    "NSS": "Número de Seguridad Social (IMSS)",
    "DATOS_BANCARIOS": "Estado de Cuenta / Datos Bancarios",
    "FACTURA": "Factura / Comprobante Fiscal (CFDI)",
    "CONSTANCIA_SITUACION_FISCAL": "Constancia de Situación Fiscal (SAT)",
    "PAYMENT": "Comprobante de Pago / Transferencia Bancaria",
    "GENERICO": "Documento genérico / imagen",
}

_OCR_TEXT_MAX_CHARS = 4000


def _field_label(key: str) -> str:
    return _FIELD_LABELS.get(key, key.replace("_", " ").title())


def _build_prompt(
    doc_type: str,
    ocr_text: str,
    missing_keys: list[str],
    existing_fields: list[dict],
) -> str:
    doc_label = _DOC_TYPE_LABELS.get(doc_type, doc_type)

    # Resumen de campos ya encontrados (contexto para Claude)
    found_summary_parts = []
    for f in existing_fields:
        key = f.get("key", "")
        value = f.get("value") or f.get("corrected_value")
        if key and value:
            found_summary_parts.append(f"  - {key}: {value}")
    found_summary = "\n".join(found_summary_parts) if found_summary_parts else "  (ninguno aún)"

    # Lista de campos faltantes con etiqueta legible
    missing_parts = [f"  - {key} ({_field_label(key)})" for key in missing_keys]
    missing_summary = "\n".join(missing_parts)

    # Truncar texto OCR para no exceder el contexto
    ocr_snippet = ocr_text[:_OCR_TEXT_MAX_CHARS]
    if len(ocr_text) > _OCR_TEXT_MAX_CHARS:
        ocr_snippet += "\n[... texto truncado ...]"

    return f"""Eres un extractor especializado en documentos oficiales mexicanos. \
Se te proporciona el texto extraído por OCR de un documento y debes encontrar \
los campos que el sistema de extracción automática no pudo identificar.

TIPO DE DOCUMENTO: {doc_label}

CAMPOS YA ENCONTRADOS (NO repetir estos):
{found_summary}

CAMPOS QUE DEBES BUSCAR:
{missing_summary}

TEXTO OCR DEL DOCUMENTO:
---
{ocr_snippet}
---

Instrucciones:
1. Busca ÚNICAMENTE los campos listados en "CAMPOS QUE DEBES BUSCAR".
2. Si no encuentras un campo con certeza razonable, NO lo incluyas.
3. Para la confianza (0.0 a 1.0): usa 0.9 si el valor es explícito y claro, \
0.75 si requirió inferencia, 0.6 si es incierto.
4. Responde SOLO con JSON válido, sin texto adicional ni markdown.

Formato de respuesta:
{{"fields": [{{"key": "nombre_del_campo", "value": "valor_extraido", "confidence": 0.85}}]}}

Si no encuentras ningún campo, responde: {{"fields": []}}"""


def _parse_llm_response(
    response_text: str,
    allowed_keys: list[str],
) -> list[dict[str, Any]]:
    """Parsea la respuesta JSON de Claude y valida los campos."""
    # Extraer bloque JSON si viene con texto alrededor
    text = response_text.strip()
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if not json_match:
        logger.warning("LLM fallback: respuesta no contiene JSON válido: %.200s", text)
        return []

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError as exc:
        logger.warning("LLM fallback: JSON malformado — %s. Texto: %.200s", exc, text)
        return []

    raw_fields = data.get("fields")
    if not isinstance(raw_fields, list):
        logger.warning("LLM fallback: 'fields' no es lista en respuesta JSON")
        return []

    allowed_set = set(allowed_keys)
    result: list[dict[str, Any]] = []

    for item in raw_fields:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        value = item.get("value")
        confidence = item.get("confidence", 0.75)

        if not key or not isinstance(key, str):
            continue
        if key not in allowed_set:
            logger.debug("LLM fallback: clave '%s' no está en allowed_keys, descartada", key)
            continue
        if value is None or str(value).strip() == "":
            continue
        if not isinstance(confidence, (int, float)):
            confidence = 0.75
        confidence = float(max(0.0, min(1.0, confidence)))

        result.append({
            "key": key,
            "label": _field_label(key),
            "value": str(value).strip(),
            "confidence": round(min(confidence, 0.85), 4),
            "valid": True,
            "validation_errors": [],
            "source": None,
        })

    return result


def merge_llm_fields(
    existing: list[dict],
    llm_fields: list[dict],
) -> list[dict]:
    """
    Fusiona campos LLM con los existentes.
    - Si el campo no existe en existing → se añade.
    - Si existe con confidence < 0.75 → se reemplaza con el valor LLM.
    - Si existe con confidence >= 0.75 → se preserva el original.
    """
    if not llm_fields:
        return existing

    # Índice por key para búsqueda rápida
    existing_by_key: dict[str, int] = {}
    for i, f in enumerate(existing):
        k = f.get("key")
        if k:
            existing_by_key[k] = i

    result = list(existing)

    for llm_field in llm_fields:
        key = llm_field.get("key")
        if not key:
            continue

        idx = existing_by_key.get(key)
        if idx is not None:
            existing_conf = float(result[idx].get("confidence", 0) or 0)
            if existing_conf >= 0.75:
                # Campo existente de alta confianza — preservar
                logger.debug(
                    "LLM fallback: campo '%s' preservado (conf=%.2f >= 0.75)",
                    key, existing_conf,
                )
                continue
            else:
                # Reemplazar campo de baja confianza
                result[idx] = llm_field
                logger.debug(
                    "LLM fallback: campo '%s' reemplazado (conf %.2f → %.2f)",
                    key, existing_conf, llm_field.get("confidence", 0),
                )
        else:
            # Campo nuevo — añadir
            result.append(llm_field)
            existing_by_key[key] = len(result) - 1
            logger.debug("LLM fallback: campo '%s' añadido (valor='%s')", key, llm_field.get("value"))

    return result


async def try_llm_fallback(
    doc_type: str,
    ocr_text: str,
    missing_keys: list[str],
    existing_fields: list[dict],
    api_key: str | None = None,
    model: str = "claude-haiku-4-5-20251001",
) -> list[dict]:
    """
    Llama a Claude API para extraer campos faltantes del texto OCR.

    Returns:
        Lista de dicts con campos extraídos (puede ser vacía si falla o no encuentra nada).
    """
    if not missing_keys:
        return []

    if not api_key:
        logger.warning(
            "LLM fallback: ANTHROPIC_API_KEY no configurada, omitiendo fallback"
        )
        return []

    if not ocr_text or len(ocr_text.strip()) < 20:
        logger.debug("LLM fallback: ocr_text muy corto, omitiendo")
        return []

    try:
        import anthropic
    except ImportError:
        logger.error(
            "LLM fallback: paquete 'anthropic' no instalado. "
            "Ejecuta: pip install 'anthropic>=0.40.0'"
        )
        return []

    prompt = _build_prompt(doc_type, ocr_text, missing_keys, existing_fields)

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        message = await client.messages.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError:
        logger.error("LLM fallback: ANTHROPIC_API_KEY inválida")
        return []
    except anthropic.RateLimitError:
        logger.warning("LLM fallback: rate limit alcanzado, omitiendo fallback")
        return []
    except Exception as exc:
        logger.warning("LLM fallback: error de API — %s", exc)
        return []

    response_text = ""
    if message.content and len(message.content) > 0:
        block = message.content[0]
        if hasattr(block, "text"):
            response_text = block.text

    if not response_text:
        logger.debug("LLM fallback: respuesta vacía del modelo")
        return []

    fields = _parse_llm_response(response_text, missing_keys)
    logger.info(
        "LLM fallback: doc_type=%s, buscados=%s, encontrados=%d",
        doc_type, missing_keys, len(fields),
    )
    return fields


# ═══════════════════════════════════════════════════════════════════════════════
# Generic / open-ended LLM extraction for GENERICO documents
# ═══════════════════════════════════════════════════════════════════════════════

def _build_generic_prompt(ocr_text: str, existing_fields: list[dict]) -> str:
    """Build a prompt for open-ended extraction from any document."""
    found_summary_parts = []
    for f in existing_fields:
        key = f.get("key", "")
        value = f.get("value") or f.get("corrected_value")
        if key and value and key != "texto_detectado":
            found_summary_parts.append(f"  - {key}: {value}")
    found_summary = "\n".join(found_summary_parts) if found_summary_parts else "  (ninguno)"

    ocr_snippet = ocr_text[:_OCR_TEXT_MAX_CHARS]
    if len(ocr_text) > _OCR_TEXT_MAX_CHARS:
        ocr_snippet += "\n[... texto truncado ...]"

    return f"""Eres un extractor de datos inteligente. Se te proporciona texto extraído \
por OCR de una imagen o documento. Tu tarea es identificar y extraer TODOS los datos \
estructurados que encuentres.

DATOS YA EXTRAÍDOS POR EL SISTEMA (NO repetir):
{found_summary}

TEXTO OCR DEL DOCUMENTO:
---
{ocr_snippet}
---

Instrucciones:
1. Extrae TODOS los pares clave-valor que identifiques en el texto.
2. Busca especialmente: nombres, fechas, números de referencia, montos, \
direcciones, teléfonos, correos, identificadores, estados, conceptos.
3. Usa claves en snake_case descriptivas (ej: "nombre_completo", "fecha_emision", \
"numero_referencia", "monto_total").
4. NO incluyas datos que ya fueron extraídos por el sistema.
5. Para la confianza: 0.9 si explícito, 0.75 si inferido, 0.6 si incierto.
6. Si hay tablas, describe brevemente su contenido.
7. Responde SOLO con JSON válido.

Formato de respuesta:
{{"fields": [{{"key": "clave_descriptiva", "label": "Etiqueta legible", "value": "valor_extraido", "confidence": 0.85}}]}}

Si no encuentras datos adicionales, responde: {{"fields": []}}"""


def _parse_generic_llm_response(response_text: str) -> list[dict[str, Any]]:
    """Parse LLM response for generic extraction (no key whitelist)."""
    text = response_text.strip()
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if not json_match:
        logger.warning("LLM generic: respuesta no contiene JSON válido: %.200s", text)
        return []

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError as exc:
        logger.warning("LLM generic: JSON malformado — %s. Texto: %.200s", exc, text)
        return []

    raw_fields = data.get("fields")
    if not isinstance(raw_fields, list):
        logger.warning("LLM generic: 'fields' no es lista en respuesta JSON")
        return []

    result: list[dict[str, Any]] = []
    for item in raw_fields:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        value = item.get("value")
        label = item.get("label", "")
        confidence = item.get("confidence", 0.75)

        if not key or not isinstance(key, str):
            continue
        if value is None or str(value).strip() == "":
            continue
        if not isinstance(confidence, (int, float)):
            confidence = 0.75
        confidence = float(max(0.0, min(1.0, confidence)))

        # Sanitize key to snake_case
        clean_key = re.sub(r"[^a-z0-9_]", "_", key.lower().strip())
        clean_key = re.sub(r"_+", "_", clean_key).strip("_")[:50]
        if not clean_key:
            continue

        result.append({
            "key": clean_key,
            "label": str(label or key.replace("_", " ").title()).strip(),
            "value": str(value).strip(),
            "confidence": round(min(confidence, 0.85), 4),
            "valid": True,
            "validation_errors": [],
            "source": None,
        })

    return result


async def try_llm_generic_extraction(
    ocr_text: str,
    existing_fields: list[dict],
    api_key: str | None = None,
    model: str = "claude-haiku-4-5-20251001",
) -> list[dict]:
    """
    Use LLM to extract ALL structured data from an arbitrary document.
    Unlike try_llm_fallback, this doesn't need a list of expected fields.
    """
    if not api_key:
        logger.warning("LLM generic: ANTHROPIC_API_KEY no configurada, omitiendo")
        return []

    if not ocr_text or len(ocr_text.strip()) < 20:
        logger.debug("LLM generic: ocr_text muy corto, omitiendo")
        return []

    try:
        import anthropic
    except ImportError:
        logger.error(
            "LLM generic: paquete 'anthropic' no instalado. "
            "Ejecuta: pip install 'anthropic>=0.40.0'"
        )
        return []

    prompt = _build_generic_prompt(ocr_text, existing_fields)

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        message = await client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError:
        logger.error("LLM generic: ANTHROPIC_API_KEY inválida")
        return []
    except anthropic.RateLimitError:
        logger.warning("LLM generic: rate limit alcanzado, omitiendo")
        return []
    except Exception as exc:
        logger.warning("LLM generic: error de API — %s", exc)
        return []

    response_text = ""
    if message.content and len(message.content) > 0:
        block = message.content[0]
        if hasattr(block, "text"):
            response_text = block.text

    if not response_text:
        logger.debug("LLM generic: respuesta vacía del modelo")
        return []

    fields = _parse_generic_llm_response(response_text)
    logger.info("LLM generic: encontrados=%d campos", len(fields))
    return fields
