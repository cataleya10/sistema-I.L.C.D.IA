"""Tests for app.legacy_motor.domicilio_logic – extraer_datos_domicilio."""

from __future__ import annotations

import pytest
from app.legacy_motor.domicilio_logic import extraer_datos_domicilio


# ── helpers ─────────────────────────────────────────────────────────
def _bloque(texto: str, x: int = 0, y: int = 0, w: int = 200, h: int = 30):
    coords = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    return [coords, [texto, 0.99]]


def _ocr(lineas: list):
    return [lineas]


# ── empty / None input ──────────────────────────────────────────────
class TestEmptyInput:
    def test_none_input(self):
        result = extraer_datos_domicilio(None)
        assert result["tipo_documento"] == "COMPROBANTE_DOMICILIO"
        assert result["servicio_detectado"] == "OTRO"
        assert result["cp_detectado"] is None
        assert result["direccion_presunta"] == ""

    def test_empty_list(self):
        result = extraer_datos_domicilio([[]])
        assert result["cp_detectado"] is None


# ── service detection ───────────────────────────────────────────────
class TestServiceDetection:
    def test_cfe_detected(self):
        ocr = _ocr([_bloque("CFE RECIBO"), _bloque("AV REFORMA 123 44100")])
        result = extraer_datos_domicilio(ocr)
        assert result["servicio_detectado"] == "CFE"

    def test_suministro_electrico_detected(self):
        ocr = _ocr([_bloque("SUMINISTRO ELECTRICO"), _bloque("CALLE 5 44200")])
        result = extraer_datos_domicilio(ocr)
        assert result["servicio_detectado"] == "CFE"

    def test_agua_detected(self):
        ocr = _ocr([
            _bloque("AGUA POTABLE"),
            _bloque("DOMICILIO: REFORMA 100"),
            _bloque("COLONIA: CENTRO"),
            _bloque("C.P. 44100"),
        ])
        result = extraer_datos_domicilio(ocr)
        assert result["servicio_detectado"] == "AGUA"

    def test_smapac_detected(self):
        ocr = _ocr([_bloque("SMAPAC"), _bloque("CALLE NORTE 44300")])
        result = extraer_datos_domicilio(ocr)
        assert result["servicio_detectado"] == "AGUA"

    def test_otro_service(self):
        ocr = _ocr([_bloque("RECIBO GENERICO"), _bloque("ALGO 44100")])
        result = extraer_datos_domicilio(ocr)
        assert result["servicio_detectado"] == "OTRO"


# ── AGUA extraction ────────────────────────────────────────────────
class TestAgua:
    def test_full_agua_document(self):
        ocr = _ocr([
            _bloque("AGUA POTABLE"),
            _bloque("DOMICILIO: AV REFORMA 123 ENTRE CALLE 1 Y 2"),
            _bloque("COLONIA: CENTRO C.P. 44100"),
            _bloque("MUNICIPIO GUADALAJARA"),
        ])
        result = extraer_datos_domicilio(ocr)
        assert result["servicio_detectado"] == "AGUA"
        assert result["cp_detectado"] == "44100"
        assert "REFORMA" in result["direccion_presunta"]

    def test_agua_no_domicilio_label(self):
        ocr = _ocr([
            _bloque("AGUA POTABLE"),
            _bloque("COLONIA: INDEPENDENCIA"),
            _bloque("C.P. 44340"),
        ])
        result = extraer_datos_domicilio(ocr)
        assert result["cp_detectado"] == "44340"


# ── CFE extraction ─────────────────────────────────────────────────
class TestCFE:
    def test_cfe_with_cp(self):
        ocr = _ocr([
            _bloque("CFE"),
            _bloque("AV CHAPULTEPEC 100"),
            _bloque("COL AMERICANA 44160"),
        ])
        result = extraer_datos_domicilio(ocr)
        assert result["servicio_detectado"] == "CFE"
        assert result["cp_detectado"] == "44160"
        assert "CHAPULTEPEC" in result["direccion_presunta"] or "AMERICANA" in result["direccion_presunta"]

    def test_cfe_blacklisted_cp_skipped(self):
        """CPs in the blacklist (06600, 06500, 01210) should be ignored."""
        ocr = _ocr([
            _bloque("CFE"),
            _bloque("EMPRESA 06600"),
            _bloque("CALLE REAL 44100"),
        ])
        result = extraer_datos_domicilio(ocr)
        assert result["cp_detectado"] == "44100"

    def test_cfe_filters_servicio_line(self):
        """Lines with 'NO. DE SERVICIO' or 'RMU' should be filtered."""
        ocr = _ocr([
            _bloque("CFE"),
            _bloque("NO. DE SERVICIO 12345"),
            _bloque("AV JUAREZ 200"),
            _bloque("COL CENTRO 44100"),
        ])
        result = extraer_datos_domicilio(ocr)
        assert "SERVICIO" not in result["direccion_presunta"]

    def test_cfe_no_valid_cp(self):
        """If all CPs are blacklisted, fallback to OTRO generic."""
        ocr = _ocr([
            _bloque("CFE RECIBO"),
            _bloque("CALLE SIN CP"),
        ])
        result = extraer_datos_domicilio(ocr)
        assert result["cp_detectado"] is None


# ── generic fallback ───────────────────────────────────────────────
class TestGenericFallback:
    def test_generic_cp_found(self):
        ocr = _ocr([
            _bloque("RECIBO TELEFONICO"),
            _bloque("CP 45678"),
        ])
        result = extraer_datos_domicilio(ocr)
        assert result["servicio_detectado"] == "OTRO"
        assert result["cp_detectado"] == "45678"
        assert "45678" in result["direccion_presunta"]

    def test_generic_blacklisted_cp(self):
        ocr = _ocr([
            _bloque("RECIBO GENERICO"),
            _bloque("CENTRO 06600"),
        ])
        result = extraer_datos_domicilio(ocr)
        assert result["cp_detectado"] is None


# ── output shape ────────────────────────────────────────────────────
class TestOutputShape:
    def test_all_keys_present(self):
        result = extraer_datos_domicilio(None)
        expected = {"tipo_documento", "servicio_detectado", "cp_detectado", "direccion_presunta"}
        assert set(result.keys()) == expected

    def test_tipo_always_comprobante(self):
        result = extraer_datos_domicilio(None)
        assert result["tipo_documento"] == "COMPROBANTE_DOMICILIO"
