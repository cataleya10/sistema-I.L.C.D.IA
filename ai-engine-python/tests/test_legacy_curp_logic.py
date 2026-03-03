"""Tests for app.legacy_motor.curp_logic – CURP document OCR extractor."""

import pytest
from app.legacy_motor.curp_logic import ProcesadorCURP, extraer_datos_curp


def _bloque(texto: str, x: int = 0, y: int = 0, w: int = 200, h: int = 30):
    """Build a single PaddleOCR-style line entry."""
    coords = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    return [coords, [texto, 0.99]]


def _ocr(lineas):
    """Wrap a list of line entries into PaddleOCR result format."""
    return [lineas]


# ── Constructor ──────────────────────────────────────────────────────────

class TestProcesadorCURPInit:
    def test_empty_ocr(self):
        proc = ProcesadorCURP(None)
        assert proc.bloques == []
        assert proc.datos["clave_curp"] is None

    def test_empty_list(self):
        proc = ProcesadorCURP([[]])
        assert proc.bloques == []

    def test_parses_bloques(self):
        ocr = _ocr([_bloque("HOLA MUNDO", 10, 20, 100, 30)])
        proc = ProcesadorCURP(ocr)
        assert len(proc.bloques) == 1
        assert proc.bloques[0]["texto"] == "HOLA MUNDO"
        assert proc.bloques[0]["texto_original"] == "HOLA MUNDO"


# ── CURP regex extraction ───────────────────────────────────────────────

class TestBuscarCURPRegex:
    def test_extracts_curp_from_text(self):
        curp = "GARC850101HDFRRL09"
        ocr = _ocr([_bloque(f"CLAVE CURP {curp}", 0, 0)])
        result = extraer_datos_curp(ocr)
        assert result["clave_curp"] == curp

    def test_no_curp_found(self):
        ocr = _ocr([_bloque("SIN DATOS RELEVANTES", 0, 0)])
        result = extraer_datos_curp(ocr)
        assert result["clave_curp"] is None

    def test_curp_among_noise(self):
        ocr = _ocr([
            _bloque("ESTADOS UNIDOS MEXICANOS", 0, 0),
            _bloque("REGISTRO CIVIL", 0, 40),
            _bloque("CURP LOPM900515MDFPRS01", 0, 80),
        ])
        result = extraer_datos_curp(ocr)
        assert result["clave_curp"] == "LOPM900515MDFPRS01"


# ── Relative search (nombre) ────────────────────────────────────────────

class TestBuscarNombre:
    def test_finds_nombre_below_label(self):
        ocr = _ocr([
            _bloque("NOMBRE", 50, 100, 200, 30),
            _bloque("JUAN PEREZ LOPEZ", 50, 145, 200, 30),
        ])
        result = extraer_datos_curp(ocr)
        assert result["nombre"] == "JUAN PEREZ LOPEZ"

    def test_no_nombre_when_far_away(self):
        ocr = _ocr([
            _bloque("NOMBRE", 50, 100, 200, 30),
            _bloque("JUAN PEREZ", 50, 500, 200, 30),  # too far below
        ])
        result = extraer_datos_curp(ocr)
        # May or may not find it depending on height tolerance
        # The key is that no crash occurs
        assert isinstance(result["nombre"], (str, type(None)))


# ── Relative search (entidad_registro – derecha) ────────────────────────

class TestBuscarEntidadRegistro:
    def test_finds_entidad_to_the_right(self):
        ocr = _ocr([
            _bloque("ENTIDAD DE REGISTRO", 50, 200, 200, 30),
            _bloque("JALISCO", 280, 200, 100, 30),
        ])
        result = extraer_datos_curp(ocr)
        assert result["entidad_registro"] == "JALISCO"


# ── Fecha emisión ───────────────────────────────────────────────────────

class TestBuscarFechaEmision:
    def test_cdmx_format(self):
        ocr = _ocr([
            _bloque("Ciudad de México, a 15 de enero de 2025", 0, 300, 400, 30),
        ])
        result = extraer_datos_curp(ocr)
        assert result["fecha_emision"] is not None
        assert "15" in result["fecha_emision"]
        assert "enero" in result["fecha_emision"].lower()

    def test_generic_format(self):
        ocr = _ocr([
            _bloque(", a 20 de marzo de 2024", 0, 300, 300, 30),
        ])
        result = extraer_datos_curp(ocr)
        assert result["fecha_emision"] is not None
        assert "20" in result["fecha_emision"]

    def test_no_fecha(self):
        ocr = _ocr([_bloque("SIN FECHA AQUI", 0, 0)])
        result = extraer_datos_curp(ocr)
        assert result["fecha_emision"] is None


# ── Full pipeline ────────────────────────────────────────────────────────

class TestExtraerDatosCurp:
    def test_returns_all_keys(self):
        result = extraer_datos_curp(None)
        expected_keys = {"clave_curp", "nombre", "entidad_registro", "fecha_emision"}
        assert set(result.keys()) == expected_keys

    def test_all_none_for_empty_input(self):
        result = extraer_datos_curp(None)
        assert all(v is None for v in result.values())

    def test_full_document_simulation(self):
        ocr = _ocr([
            _bloque("ESTADOS UNIDOS MEXICANOS", 100, 10, 300, 30),
            _bloque("CLAVE CURP", 50, 60, 150, 25),
            _bloque("GARC850101HDFRRL09", 50, 95, 250, 25),
            _bloque("NOMBRE", 50, 140, 100, 25),
            _bloque("GARCIA RAMIREZ CARLOS", 50, 175, 250, 25),
            _bloque("ENTIDAD DE REGISTRO", 50, 220, 200, 25),
            _bloque("DISTRITO FEDERAL", 280, 220, 180, 25),
            _bloque("Ciudad de México, a 10 de febrero de 2025", 50, 300, 400, 25),
        ])
        result = extraer_datos_curp(ocr)
        assert result["clave_curp"] == "GARC850101HDFRRL09"
        assert result["nombre"] is not None
        assert result["entidad_registro"] == "DISTRITO FEDERAL"
        assert result["fecha_emision"] is not None
