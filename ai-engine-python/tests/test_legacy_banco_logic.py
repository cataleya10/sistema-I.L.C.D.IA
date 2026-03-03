"""Tests for app.legacy_motor.banco_logic – Bank statement OCR extractor."""

import pytest
from app.legacy_motor.banco_logic import extraer_datos_bancarios


def _bloque(texto, x=0, y=0, w=200, h=30):
    coords = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    return [coords, [texto, 0.99]]


def _ocr(lineas):
    return [lineas]


# ── Empty / missing input ───────────────────────────────────────────────

class TestEmptyInput:
    def test_none_returns_defaults(self):
        result = extraer_datos_bancarios(None)
        assert result["banco_detectado"] == "GENERICO"
        assert result["titular"] is None
        assert result["clabe"] is None
        assert result["cuenta"] is None

    def test_empty_ocr(self):
        result = extraer_datos_bancarios([[]])
        assert result["banco_detectado"] == "GENERICO"

    def test_returns_all_keys(self):
        result = extraer_datos_bancarios(None)
        expected = {"banco_detectado", "titular", "clabe", "cuenta"}
        assert set(result.keys()) == expected


# ── CLABE extraction ────────────────────────────────────────────────────

class TestCLABE:
    def test_clabe_18_digits_in_text(self):
        ocr = _ocr([_bloque("Su CLABE es 012345678901234567")])
        result = extraer_datos_bancarios(ocr)
        assert result["clabe"] == "012345678901234567"

    def test_clabe_standalone_18_digits(self):
        ocr = _ocr([_bloque("012345678901234567")])
        result = extraer_datos_bancarios(ocr)
        assert result["clabe"] == "012345678901234567"

    def test_clabe_label_next_line(self):
        ocr = _ocr([
            _bloque("CLABE INTERBANCARIA"),
            _bloque("098765432109876543"),
        ])
        result = extraer_datos_bancarios(ocr)
        assert result["clabe"] == "098765432109876543"

    def test_no_clabe(self):
        ocr = _ocr([_bloque("SIN DATOS BANCARIOS")])
        result = extraer_datos_bancarios(ocr)
        assert result["clabe"] is None


# ── Cuenta extraction ───────────────────────────────────────────────────

class TestCuenta:
    def test_cuenta_from_label(self):
        ocr = _ocr([
            _bloque("Cuenta: 1234567890"),
        ])
        result = extraer_datos_bancarios(ocr)
        assert result["cuenta"] == "1234567890"

    def test_contrato_label(self):
        ocr = _ocr([
            _bloque("Contrato: 9876543210"),
        ])
        result = extraer_datos_bancarios(ocr)
        assert result["cuenta"] == "9876543210"

    def test_cuenta_excludes_clabe(self):
        """Account number should not repeat the CLABE."""
        ocr = _ocr([
            _bloque("CLABE 012345678901234567"),
            _bloque("Cuenta: 9876543210"),
        ])
        result = extraer_datos_bancarios(ocr)
        assert result["clabe"] == "012345678901234567"
        assert result["cuenta"] == "9876543210"
        assert result["cuenta"] != result["clabe"]

    def test_estado_de_cuenta_ignored(self):
        """Lines with 'ESTADO' should not trigger account number extraction."""
        ocr = _ocr([
            _bloque("ESTADO DE CUENTA"),
            _bloque("1234567890"),
        ])
        result = extraer_datos_bancarios(ocr)
        # "ESTADO DE CUENTA" contains "CUENTA" but also "ESTADO", so it's filtered
        assert result["cuenta"] is None


# ── Titular extraction ──────────────────────────────────────────────────

class TestTitular:
    def test_nombre_short_label_next_line(self):
        ocr = _ocr([
            _bloque("NOMBRE:"),
            _bloque("JUAN PEREZ GARCIA"),
        ])
        result = extraer_datos_bancarios(ocr)
        assert result["titular"] == "JUAN PEREZ GARCIA"

    def test_titular_inline(self):
        ocr = _ocr([
            _bloque("TITULAR: MARIA LOPEZ SANCHEZ"),
        ])
        result = extraer_datos_bancarios(ocr)
        assert result["titular"] is not None
        assert "MARIA" in result["titular"]

    def test_cliente_label(self):
        ocr = _ocr([
            _bloque("CLIENTE: ANA MARTINEZ"),
        ])
        result = extraer_datos_bancarios(ocr)
        assert result["titular"] is not None
        assert "ANA" in result["titular"]


# ── Full pipeline ────────────────────────────────────────────────────────

class TestFullPipeline:
    def test_full_bank_document(self):
        ocr = _ocr([
            _bloque("BBVA MEXICO"),
            _bloque("ESTADO DE CUENTA"),
            _bloque("NOMBRE:"),
            _bloque("GARCIA RAMIREZ CARLOS"),
            _bloque("CLABE INTERBANCARIA"),
            _bloque("012345678901234567"),
            _bloque("Cuenta: 1234567890"),
        ])
        result = extraer_datos_bancarios(ocr)
        assert result["titular"] == "GARCIA RAMIREZ CARLOS"
        assert result["clabe"] == "012345678901234567"
        assert result["cuenta"] == "1234567890"
