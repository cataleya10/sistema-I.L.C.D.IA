"""Tests for app.legacy_motor.nss_logic – NSS (IMSS) document OCR extractor."""

import pytest
from app.legacy_motor.nss_logic import ProcesadorNSS, extraer_datos_nss


def _bloque(texto, x=0, y=0, w=200, h=30):
    coords = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    return [coords, [texto, 0.99]]


def _ocr(lineas):
    return [lineas]


# ── Constructor ──────────────────────────────────────────────────────────

class TestProcesadorNSSInit:
    def test_empty_ocr(self):
        proc = ProcesadorNSS(None)
        assert proc.bloques == []
        assert proc.datos["nss"] is None

    def test_parses_bloques(self):
        ocr = _ocr([_bloque("IMSS SEGURO SOCIAL")])
        proc = ProcesadorNSS(ocr)
        assert len(proc.bloques) == 1
        assert proc.bloques[0]["texto_upper"] == "IMSS SEGURO SOCIAL"


# ── NSS extraction ──────────────────────────────────────────────────────

class TestExtraerNSS:
    def test_nss_from_social_label(self):
        ocr = _ocr([_bloque("Numero de Seguridad Social: 12345678901")])
        result = extraer_datos_nss(ocr)
        assert result["nss"] == "12345678901"

    def test_nss_visual_fallback_11_digits(self):
        ocr = _ocr([
            _bloque("Datos del asegurado"),
            _bloque("98765432100"),
        ])
        result = extraer_datos_nss(ocr)
        assert result["nss"] == "98765432100"

    def test_no_nss(self):
        ocr = _ocr([_bloque("DOCUMENTO SIN NSS")])
        result = extraer_datos_nss(ocr)
        assert result["nss"] is None


# ── CURP extraction ─────────────────────────────────────────────────────

class TestExtraerCURP:
    def test_curp_from_text(self):
        ocr = _ocr([_bloque("CURP GARC850101HDFRRL09")])
        result = extraer_datos_nss(ocr)
        assert result["curp"] == "GARC850101HDFRRL09"

    def test_curp_fallback_visual(self):
        ocr = _ocr([
            _bloque("Asegurado"),
            _bloque("LOPM900515MDFPRS01"),
        ])
        result = extraer_datos_nss(ocr)
        assert result["curp"] == "LOPM900515MDFPRS01"


# ── Nombre extraction ───────────────────────────────────────────────────

class TestExtraerNombre:
    def test_nombre_asegurado(self):
        ocr = _ocr([_bloque("Nombre del Asegurado: GARCIA PEREZ JUAN CARLOS")])
        result = extraer_datos_nss(ocr)
        assert result["nombre"] is not None
        assert "GARCIA" in result["nombre"]

    def test_nombre_titular(self):
        ocr = _ocr([_bloque("Nombre del Titular: LOPEZ MARTINEZ ANA")])
        result = extraer_datos_nss(ocr)
        assert result["nombre"] is not None
        assert "LOPEZ" in result["nombre"]


# ── Fecha / folio ────────────────────────────────────────────────────────

class TestExtraerFechaFolio:
    def test_fecha_documento(self):
        ocr = _ocr([_bloque("Fecha: 15 de marzo de 2025")])
        result = extraer_datos_nss(ocr)
        assert result["fecha_documento"] is not None
        assert "2025" in result["fecha_documento"]

    def test_folio_solicitud(self):
        ocr = _ocr([_bloque("Folio: 12345678")])
        result = extraer_datos_nss(ocr)
        assert result["folio_solicitud"] == "12345678"

    def test_no_fecha_no_folio(self):
        ocr = _ocr([_bloque("SIN DATOS RELEVANTES")])
        result = extraer_datos_nss(ocr)
        assert result["fecha_documento"] is None
        assert result["folio_solicitud"] is None


# ── Full pipeline ────────────────────────────────────────────────────────

class TestExtraerDatosNSS:
    def test_returns_all_keys(self):
        result = extraer_datos_nss(None)
        expected = {"nss", "nombre", "curp", "fecha_documento", "folio_solicitud"}
        assert set(result.keys()) == expected

    def test_all_none_for_empty(self):
        result = extraer_datos_nss(None)
        assert all(v is None for v in result.values())

    def test_full_document_simulation(self):
        ocr = _ocr([
            _bloque("INSTITUTO MEXICANO DEL SEGURO SOCIAL"),
            _bloque("Nombre del Asegurado: RAMIREZ GONZALEZ PEDRO"),
            _bloque("Numero de Seguridad Social: 12345678901"),
            _bloque("CURP RAGP800101HDFRRL09"),
            _bloque("Fecha: 10 de enero de 2026"),
            _bloque("Folio: 99887766"),
        ])
        result = extraer_datos_nss(ocr)
        assert result["nss"] == "12345678901"
        assert result["curp"] == "RAGP800101HDFRRL09"
        assert result["nombre"] is not None
        assert result["fecha_documento"] is not None
        assert result["folio_solicitud"] == "99887766"
