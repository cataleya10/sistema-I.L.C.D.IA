"""Tests for app.legacy_motor.acta_logic – Acta de Nacimiento OCR extractor."""

import pytest
from app.legacy_motor.acta_logic import ProcesadorActa, extraer_datos_acta


def _bloque(texto, x=0, y=0, w=200, h=30):
    coords = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    return [coords, [texto, 0.99]]


def _ocr(lineas):
    return [lineas]


# ── Constructor ──────────────────────────────────────────────────────────

class TestProcesadorActaInit:
    def test_empty_ocr(self):
        proc = ProcesadorActa(None)
        assert proc.bloques == []

    def test_parses_bloques(self):
        ocr = _ocr([_bloque("ACTA DE NACIMIENTO")])
        proc = ProcesadorActa(ocr)
        assert len(proc.bloques) == 1
        assert proc.bloques[0]["texto"] == "ACTA DE NACIMIENTO"


# ── Sexo detection ──────────────────────────────────────────────────────

class TestBuscarSexo:
    def test_hombre(self):
        ocr = _ocr([_bloque("HOMBRE", 50, 200)])
        result = extraer_datos_acta(ocr)
        assert result["sexo"] == "HOMBRE"

    def test_mujer(self):
        ocr = _ocr([_bloque("MUJER", 50, 200)])
        result = extraer_datos_acta(ocr)
        assert result["sexo"] == "MUJER"

    def test_no_sexo(self):
        ocr = _ocr([_bloque("SIN DATOS")])
        result = extraer_datos_acta(ocr)
        assert result["sexo"] is None


# ── Fecha nacimiento ────────────────────────────────────────────────────

class TestBuscarFechaNacimiento:
    def test_date_format_dd_mm_yyyy(self):
        ocr = _ocr([_bloque("FECHA 15/03/1990")])
        result = extraer_datos_acta(ocr)
        assert result["fecha_nacimiento"] == "15/03/1990"

    def test_no_date(self):
        ocr = _ocr([_bloque("SIN FECHA")])
        result = extraer_datos_acta(ocr)
        assert result["fecha_nacimiento"] is None


# ── Año de registro ─────────────────────────────────────────────────────

class TestBuscarAnioRegistro:
    def test_extracts_year(self):
        ocr = _ocr([_bloque("REGISTRADA DE 2015")])
        result = extraer_datos_acta(ocr)
        assert result["anio_registro"] == "2015"

    def test_year_1900s(self):
        ocr = _ocr([_bloque("ACTA DE 1987 EMITIDA")])
        result = extraer_datos_acta(ocr)
        assert result["anio_registro"] == "1987"


# ── CURP detection & inference ──────────────────────────────────────────

class TestProcesarCURP:
    def test_curp_detected(self):
        ocr = _ocr([_bloque("CURP GARC850101HDFRRL091")])
        result = extraer_datos_acta(ocr)
        assert result["curp_detectada"] == "GARC850101HDFRRL091"

    def test_sexo_from_curp_h(self):
        # CURP with H at position 10 → HOMBRE
        ocr = _ocr([_bloque("GARC850101HDFRRL091")])
        result = extraer_datos_acta(ocr)
        assert result["sexo"] == "HOMBRE"

    def test_sexo_from_curp_m(self):
        ocr = _ocr([_bloque("GARC850101MDFRRL091")])
        result = extraer_datos_acta(ocr)
        assert result["sexo"] == "MUJER"

    def test_fecha_from_curp(self):
        # CURP digits 4-10 encode YYMMDD → 850101 → 01/01/1985
        ocr = _ocr([_bloque("GARC850101HDFRRL091")])
        result = extraer_datos_acta(ocr)
        assert result["fecha_nacimiento"] == "01/01/1985"

    def test_entidad_from_curp(self):
        # Position 11-12 = "DF" → CIUDAD DE MEXICO
        ocr = _ocr([_bloque("GARC850101HDFRRL091")])
        result = extraer_datos_acta(ocr)
        assert result["entidad_registro"] == "CIUDAD DE MEXICO"

    def test_entidad_jalisco_from_curp(self):
        # "JC" → JALISCO
        ocr = _ocr([_bloque("GARC850101HJCRRL091")])
        result = extraer_datos_acta(ocr)
        assert result["entidad_registro"] == "JALISCO"


# ── Relative search (entidad, municipio, nombre, apellidos) ─────────────

class TestBuscarRelativo:
    def test_entidad_below_label(self):
        ocr = _ocr([
            _bloque("ENTIDAD DE REGISTRO", 50, 100, 200, 30),
            _bloque("JALISCO", 50, 145, 150, 30),
        ])
        result = extraer_datos_acta(ocr)
        assert result["entidad_registro"] == "JALISCO"

    def test_nombre_above_label(self):
        ocr = _ocr([
            _bloque("CARLOS", 50, 80, 100, 25),
            _bloque("NOMBRE", 50, 115, 100, 25),
        ])
        result = extraer_datos_acta(ocr)
        assert result["nombre"] == "CARLOS"


# ── Full pipeline ────────────────────────────────────────────────────────

class TestExtraerDatosActa:
    def test_returns_all_keys(self):
        result = extraer_datos_acta(None)
        expected = {
            "entidad_registro", "municipio_registro", "nombre",
            "primer_apellido", "segundo_apellido", "sexo",
            "fecha_nacimiento", "lugar_nacimiento", "anio_registro",
            "curp_detectada",
        }
        assert set(result.keys()) == expected

    def test_all_none_for_empty(self):
        result = extraer_datos_acta(None)
        assert all(v is None for v in result.values())

    def test_full_document(self):
        ocr = _ocr([
            _bloque("ACTA DE NACIMIENTO", 100, 10, 300, 30),
            _bloque("HOMBRE", 300, 200, 100, 25),
            _bloque("15/03/1990", 50, 250, 150, 25),
            _bloque("DE 2015", 50, 300, 100, 25),
            _bloque("GARC900315HDFRRL091", 50, 350, 250, 25),
        ])
        result = extraer_datos_acta(ocr)
        assert result["sexo"] == "HOMBRE"
        assert result["fecha_nacimiento"] == "15/03/1990"
        assert result["anio_registro"] == "2015"
        assert result["curp_detectada"] == "GARC900315HDFRRL091"
