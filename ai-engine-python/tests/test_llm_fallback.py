"""
Tests unitarios para app/services/llm_fallback.py
Los tests mockean el cliente Anthropic para no requerir API key real.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm_fallback import (
    _build_prompt,
    _parse_llm_response,
    merge_llm_fields,
    try_llm_fallback,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_existing_field(key: str, value: str, confidence: float = 0.9) -> dict:
    return {
        "key": key,
        "label": key,
        "value": value,
        "confidence": confidence,
        "valid": True,
        "validation_errors": [],
        "source": None,
    }


def _make_anthropic_response(text: str) -> MagicMock:
    """Simula un objeto anthropic.types.Message con un TextBlock."""
    block = MagicMock()
    block.text = text
    message = MagicMock()
    message.content = [block]
    return message


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------

def test_build_prompt_includes_doc_type():
    prompt = _build_prompt("INE", "TEXTO OCR", ["curp", "nombre"], [])
    assert "INE" in prompt or "Credencial" in prompt


def test_build_prompt_includes_missing_keys():
    prompt = _build_prompt("CURP", "TEXTO OCR", ["curp", "fecha_nacimiento"], [])
    assert "curp" in prompt
    assert "fecha_nacimiento" in prompt


def test_build_prompt_includes_existing_fields():
    existing = [_make_existing_field("rfc", "ABCD123456XYZ")]
    prompt = _build_prompt("CONSTANCIA_SITUACION_FISCAL", "TEXTO", ["nombre"], existing)
    assert "ABCD123456XYZ" in prompt


def test_build_prompt_truncates_long_ocr():
    long_text = "A" * 10_000
    prompt = _build_prompt("INE", long_text, ["curp"], [])
    # Prompt should not contain 10 000 As — truncated to _OCR_TEXT_MAX_CHARS
    assert prompt.count("A") < 10_000


# ---------------------------------------------------------------------------
# _parse_llm_response
# ---------------------------------------------------------------------------

def test_parse_valid_json_response():
    raw = json.dumps({"fields": [{"key": "curp", "value": "BADD840901HDFNNN09", "confidence": 0.9}]})
    result = _parse_llm_response(raw, ["curp", "nombre"])
    assert len(result) == 1
    assert result[0]["key"] == "curp"
    assert result[0]["value"] == "BADD840901HDFNNN09"
    assert result[0]["confidence"] <= 0.85  # capped at 0.85


def test_parse_response_skips_unknown_keys():
    raw = json.dumps({"fields": [{"key": "campo_inexistente", "value": "algo", "confidence": 0.8}]})
    result = _parse_llm_response(raw, ["curp"])
    assert result == []


def test_parse_response_skips_empty_values():
    raw = json.dumps({"fields": [{"key": "curp", "value": "", "confidence": 0.9}]})
    result = _parse_llm_response(raw, ["curp"])
    assert result == []


def test_parse_response_with_invalid_json_returns_empty():
    result = _parse_llm_response("esto no es json", ["curp"])
    assert result == []


def test_parse_response_with_json_embedded_in_text():
    raw = 'Aquí está la respuesta: {"fields": [{"key": "nombre", "value": "Juan Pérez", "confidence": 0.8}]} fin.'
    result = _parse_llm_response(raw, ["nombre"])
    assert len(result) == 1
    assert result[0]["value"] == "Juan Pérez"


def test_parse_response_caps_confidence_at_085():
    raw = json.dumps({"fields": [{"key": "curp", "value": "BADD840901HDFNNN09", "confidence": 0.99}]})
    result = _parse_llm_response(raw, ["curp"])
    assert result[0]["confidence"] == 0.85


def test_parse_response_empty_fields_list():
    raw = json.dumps({"fields": []})
    result = _parse_llm_response(raw, ["curp"])
    assert result == []


# ---------------------------------------------------------------------------
# merge_llm_fields
# ---------------------------------------------------------------------------

def test_merge_adds_new_field():
    existing = [_make_existing_field("nombre", "Juan Pérez")]
    llm = [{"key": "curp", "label": "CURP", "value": "BADD840901HDFNNN09",
            "confidence": 0.8, "valid": True, "validation_errors": [], "source": None}]
    result = merge_llm_fields(existing, llm)
    keys = [f["key"] for f in result]
    assert "curp" in keys
    assert "nombre" in keys


def test_merge_does_not_overwrite_high_confidence():
    existing = [_make_existing_field("curp", "ORIGINAL_CURP_VALUE", confidence=0.9)]
    llm = [{"key": "curp", "label": "CURP", "value": "LLM_CURP_VALUE",
            "confidence": 0.8, "valid": True, "validation_errors": [], "source": None}]
    result = merge_llm_fields(existing, llm)
    curp_field = next(f for f in result if f["key"] == "curp")
    assert curp_field["value"] == "ORIGINAL_CURP_VALUE"


def test_merge_replaces_low_confidence_field():
    existing = [_make_existing_field("curp", "LOW_CONF_CURP", confidence=0.5)]
    llm = [{"key": "curp", "label": "CURP", "value": "LLM_CURP_BETTER",
            "confidence": 0.8, "valid": True, "validation_errors": [], "source": None}]
    result = merge_llm_fields(existing, llm)
    curp_field = next(f for f in result if f["key"] == "curp")
    assert curp_field["value"] == "LLM_CURP_BETTER"


def test_merge_empty_llm_fields_returns_existing():
    existing = [_make_existing_field("nombre", "Juan")]
    result = merge_llm_fields(existing, [])
    assert result == existing


def test_merge_preserves_field_at_exactly_075_threshold():
    existing = [_make_existing_field("rfc", "RFC_EXACTO", confidence=0.75)]
    llm = [{"key": "rfc", "label": "RFC", "value": "RFC_LLM",
            "confidence": 0.8, "valid": True, "validation_errors": [], "source": None}]
    result = merge_llm_fields(existing, llm)
    rfc_field = next(f for f in result if f["key"] == "rfc")
    assert rfc_field["value"] == "RFC_EXACTO"


# ---------------------------------------------------------------------------
# try_llm_fallback (async)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_fills_missing_field():
    llm_response = json.dumps({
        "fields": [{"key": "curp", "value": "BADD840901HDFNNN09", "confidence": 0.88}]
    })
    mock_message = _make_anthropic_response(llm_response)

    with patch("anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_message)
        mock_cls.return_value = mock_client

        result = await try_llm_fallback(
            doc_type="INE",
            ocr_text="NOMBRE JOSE GARCIA CURP BADD840901HDFNNN09",
            missing_keys=["curp"],
            existing_fields=[],
            api_key="test-key",
            model="claude-haiku-4-5-20251001",
        )

    assert len(result) == 1
    assert result[0]["key"] == "curp"
    assert result[0]["value"] == "BADD840901HDFNNN09"
    assert result[0]["confidence"] <= 0.85


@pytest.mark.asyncio
async def test_fallback_returns_empty_on_api_error():
    with patch("anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("Connection error"))
        mock_cls.return_value = mock_client

        result = await try_llm_fallback(
            doc_type="INE",
            ocr_text="TEXTO OCR DE PRUEBA CON CONTENIDO SUFICIENTE",
            missing_keys=["curp"],
            existing_fields=[],
            api_key="test-key",
        )

    assert result == []


@pytest.mark.asyncio
async def test_fallback_returns_empty_on_invalid_json():
    mock_message = _make_anthropic_response("Lo siento, no pude encontrar los datos.")

    with patch("anthropic.AsyncAnthropic") as mock_cls:
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_message)
        mock_cls.return_value = mock_client

        result = await try_llm_fallback(
            doc_type="INE",
            ocr_text="TEXTO OCR",
            missing_keys=["curp"],
            existing_fields=[],
            api_key="test-key",
        )

    assert result == []


@pytest.mark.asyncio
async def test_fallback_returns_empty_without_api_key():
    result = await try_llm_fallback(
        doc_type="INE",
        ocr_text="TEXTO OCR SUFICIENTE PARA PROCESAR",
        missing_keys=["curp"],
        existing_fields=[],
        api_key=None,
    )
    assert result == []


@pytest.mark.asyncio
async def test_fallback_returns_empty_when_missing_keys_empty():
    result = await try_llm_fallback(
        doc_type="INE",
        ocr_text="TEXTO OCR",
        missing_keys=[],
        existing_fields=[],
        api_key="test-key",
    )
    assert result == []


@pytest.mark.asyncio
async def test_fallback_returns_empty_on_short_ocr_text():
    result = await try_llm_fallback(
        doc_type="INE",
        ocr_text="OK",
        missing_keys=["curp"],
        existing_fields=[],
        api_key="test-key",
    )
    assert result == []
