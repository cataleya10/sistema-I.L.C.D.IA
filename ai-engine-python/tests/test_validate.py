"""Tests for app.pipelines.validate."""

from __future__ import annotations

import pytest

from app.pipelines.validate import validate_fields, VALIDATORS


# ── VALIDATORS map ───────────────────────────────────────────────

class TestValidatorsMap:
    def test_expected_keys_present(self):
        expected = {"curp", "rfc", "nss", "clabe", "fecha", "fecha_nacimiento",
                    "sexo", "banco", "folio", "cp", "entidad_nacimiento",
                    "clave_elector", "seccion", "vigencia"}
        assert expected.issubset(set(VALIDATORS.keys()))

    def test_each_validator_is_callable(self):
        for key, fn in VALIDATORS.items():
            assert callable(fn), f"VALIDATORS['{key}'] is not callable"


# ── Digit normalization ──────────────────────────────────────────

class TestDigitNormalization:
    """Fields nss, clabe, cp, seccion get O→0, I→1, L→1 replacement + digit-only filter."""

    @pytest.mark.asyncio
    async def test_nss_normalizes_letters_to_digits(self):
        fields = [{"key": "nss", "value": "1234O67890I"}]
        result = await validate_fields(fields)
        assert result[0]["value"] == "12340678901"

    @pytest.mark.asyncio
    async def test_clabe_normalizes_letters_to_digits(self):
        fields = [{"key": "clabe", "value": "OI234567890L234567"}]
        result = await validate_fields(fields)
        assert result[0]["value"] == "012345678901234567"

    @pytest.mark.asyncio
    async def test_cp_normalizes_letters(self):
        fields = [{"key": "cp", "value": "O6O0O"}]
        result = await validate_fields(fields)
        assert result[0]["value"] == "06000"

    @pytest.mark.asyncio
    async def test_seccion_normalizes_letters(self):
        fields = [{"key": "seccion", "value": "OI0L"}]
        result = await validate_fields(fields)
        assert result[0]["value"] == "0101"

    @pytest.mark.asyncio
    async def test_strips_non_digit_chars(self):
        fields = [{"key": "nss", "value": "123-456-7890X"}]
        result = await validate_fields(fields)
        # X is not in O/I/L mapping, - stripped, only digits remain
        assert result[0]["value"] == "1234567890"


# ── Validation logic ─────────────────────────────────────────────

class TestValidation:
    @pytest.mark.asyncio
    async def test_valid_curp_sets_valid_true(self):
        fields = [{"key": "curp", "value": "GALJ900101HDFRPN09"}]
        result = await validate_fields(fields)
        assert result[0].get("valid") is True
        assert result[0].get("validation_errors") == []

    @pytest.mark.asyncio
    async def test_invalid_curp_sets_valid_false(self):
        fields = [{"key": "curp", "value": "INVALID"}]
        result = await validate_fields(fields)
        assert result[0].get("valid") is False
        assert len(result[0].get("validation_errors", [])) > 0

    @pytest.mark.asyncio
    async def test_valid_nss_after_normalization(self):
        fields = [{"key": "nss", "value": "12345678901"}]
        result = await validate_fields(fields)
        assert result[0].get("valid") is True

    @pytest.mark.asyncio
    async def test_invalid_nss_wrong_length(self):
        fields = [{"key": "nss", "value": "1234"}]
        result = await validate_fields(fields)
        assert result[0].get("valid") is False

    @pytest.mark.asyncio
    async def test_clabe_validated(self):
        """CLABE gets validated; an arbitrary 18-digit string may fail check digit."""
        fields = [{"key": "clabe", "value": "012345678901234567"}]
        result = await validate_fields(fields)
        # Validation runs and sets 'valid' key (might be True or False depending on check digit)
        assert "valid" in result[0]
        assert "validation_errors" in result[0]

    @pytest.mark.asyncio
    async def test_valid_cp(self):
        fields = [{"key": "cp", "value": "06000"}]
        result = await validate_fields(fields)
        assert result[0].get("valid") is True

    @pytest.mark.asyncio
    async def test_valid_sexo(self):
        fields = [{"key": "sexo", "value": "H"}]
        result = await validate_fields(fields)
        assert result[0].get("valid") is True

    @pytest.mark.asyncio
    async def test_invalid_sexo(self):
        fields = [{"key": "sexo", "value": "X"}]
        result = await validate_fields(fields)
        assert result[0].get("valid") is False


# ── Edge cases ───────────────────────────────────────────────────

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_none_value_skipped(self):
        fields = [{"key": "curp", "value": None}]
        result = await validate_fields(fields)
        assert "valid" not in result[0]

    @pytest.mark.asyncio
    async def test_unknown_key_skipped(self):
        """Fields with keys not in VALIDATORS remain untouched."""
        fields = [{"key": "random_field", "value": "anything"}]
        result = await validate_fields(fields)
        assert "valid" not in result[0]
        assert "validation_errors" not in result[0]

    @pytest.mark.asyncio
    async def test_multiple_fields_processed(self):
        fields = [
            {"key": "curp", "value": "GALJ900101HDFRPN09"},
            {"key": "nss", "value": "12345678901"},
            {"key": "sexo", "value": "M"},
        ]
        result = await validate_fields(fields)
        assert len(result) == 3
        assert all(f.get("valid") is True for f in result)

    @pytest.mark.asyncio
    async def test_empty_list(self):
        result = await validate_fields([])
        assert result == []

    @pytest.mark.asyncio
    async def test_normalization_does_not_affect_non_numeric_fields(self):
        """curp field should NOT get digit normalization."""
        fields = [{"key": "curp", "value": "GALJ900101HDFRPN09"}]
        result = await validate_fields(fields)
        # Value should remain unchanged (no O→0 replacement)
        assert result[0]["value"] == "GALJ900101HDFRPN09"

    @pytest.mark.asyncio
    async def test_returns_same_list_reference(self):
        fields = [{"key": "curp", "value": "GALJ900101HDFRPN09"}]
        result = await validate_fields(fields)
        assert result is fields
