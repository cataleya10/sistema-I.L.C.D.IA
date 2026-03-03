"""Tests for app.legacy_motor.csf_logic – ProcesadorCSF / extraer_datos_csf."""

from __future__ import annotations

import pytest
from app.legacy_motor.csf_logic import ProcesadorCSF, extraer_datos_csf


# ── helpers ─────────────────────────────────────────────────────────
def _bloque(texto: str, x: int = 0, y: int = 0, w: int = 200, h: int = 30):
    coords = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    return [coords, [texto, 0.99]]


def _ocr(lineas: list):
    return [lineas]


# ── init ────────────────────────────────────────────────────────────
class TestInit:
    def test_none_input(self):
        p = ProcesadorCSF(None)
        assert p.bloques == []

    def test_empty_list(self):
        p = ProcesadorCSF([[]])
        assert p.bloques == []

    def test_parses_bloques(self):
        ocr = _ocr([_bloque("HOLA MUNDO", x=10, y=20, w=100, h=25)])
        p = ProcesadorCSF(ocr)
        assert len(p.bloques) == 1
        b = p.bloques[0]
        assert b["texto"] == "HOLA MUNDO"
        assert b["x_min"] == 10
        assert b["y_min"] == 20

    def test_datos_keys(self):
        p = ProcesadorCSF(None)
        expected_keys = {
            "rfc", "curp", "nombre_completo",
            "codigo_postal", "id_cif", "fecha_emision", "regimen_fiscal",
        }
        assert set(p.datos.keys()) == expected_keys
        assert all(v is None for v in p.datos.values())


# ── RFC ─────────────────────────────────────────────────────────────
class TestRFC:
    def test_rfc_persona_moral(self):
        ocr = _ocr([_bloque("RFC: ABC123456XY9")])
        p = ProcesadorCSF(ocr)
        p._buscar_rfc()
        assert p.datos["rfc"] == "ABC123456XY9"

    def test_rfc_persona_fisica(self):
        ocr = _ocr([_bloque("VECJ880326AB1")])
        p = ProcesadorCSF(ocr)
        p._buscar_rfc()
        assert p.datos["rfc"] == "VECJ880326AB1"

    def test_rfc_not_found(self):
        ocr = _ocr([_bloque("NO HAY RFC AQUI")])
        p = ProcesadorCSF(ocr)
        p._buscar_rfc()
        assert p.datos["rfc"] is None


# ── CURP ────────────────────────────────────────────────────────────
class TestCURP:
    def test_curp_found(self):
        ocr = _ocr([_bloque("CURP VECJ880326HJCRZN09")])
        p = ProcesadorCSF(ocr)
        p._buscar_curp()
        assert p.datos["curp"] == "VECJ880326HJCRZN09"

    def test_curp_not_found(self):
        ocr = _ocr([_bloque("SIN DATOS")])
        p = ProcesadorCSF(ocr)
        p._buscar_curp()
        assert p.datos["curp"] is None


# ── Nombre (CIF method) ────────────────────────────────────────────
class TestNombreCIF:
    def test_nombre_between_rfc_and_denominacion(self):
        """Name should be extracted between 'REGISTRO FEDERAL' and 'DENOMINACION'."""
        ocr = _ocr([
            _bloque("REGISTRO FEDERAL DE CONTRIBUYENTES", x=0, y=0, w=400, h=30),
            _bloque("VECJ880326AB1", x=0, y=35, w=200, h=30),
            _bloque("JUAN PEREZ LOPEZ", x=0, y=80, w=300, h=30),
            _bloque("DENOMINACION O RAZON SOCIAL", x=0, y=140, w=400, h=30),
        ])
        p = ProcesadorCSF(ocr)
        # Pre-populate rfc so the techo algorithm can also use it
        p.datos["rfc"] = "VECJ880326AB1"
        p._buscar_nombre_en_cif()
        assert p.datos["nombre_completo"] == "JUAN PEREZ LOPEZ"

    def test_nombre_skips_rfc_block(self):
        """The block containing the RFC itself should be skipped."""
        ocr = _ocr([
            _bloque("REGISTRO FEDERAL DE CONTRIBUYENTES", x=0, y=0, w=400, h=30),
            _bloque("VECJ880326AB1", x=0, y=40, w=200, h=30),
            _bloque("MARIA GONZALEZ", x=0, y=80, w=300, h=30),
            _bloque("DENOMINACION O RAZON SOCIAL", x=0, y=130, w=400, h=30),
        ])
        p = ProcesadorCSF(ocr)
        p.datos["rfc"] = "VECJ880326AB1"
        p._buscar_nombre_en_cif()
        assert p.datos["nombre_completo"] == "MARIA GONZALEZ"

    def test_nombre_not_found_no_landmarks(self):
        ocr = _ocr([_bloque("ALGO RANDOM")])
        p = ProcesadorCSF(ocr)
        p._buscar_nombre_en_cif()
        assert p.datos["nombre_completo"] is None


# ── Nombre (table reconstruct) ─────────────────────────────────────
class TestNombreTabla:
    def test_reconstruir_from_labels(self):
        """When NOMBRE (S), PRIMER APELLIDO, SEGUNDO APELLIDO labels exist with values."""
        ocr = _ocr([
            _bloque("NOMBRE (S)", x=0, y=0, w=120, h=25),
            _bloque("JUAN", x=130, y=0, w=100, h=25),
            _bloque("PRIMER APELLIDO", x=0, y=40, w=160, h=25),
            _bloque("PEREZ", x=170, y=40, w=100, h=25),
            _bloque("SEGUNDO APELLIDO", x=0, y=80, w=180, h=25),
            _bloque("LOPEZ", x=190, y=80, w=100, h=25),
        ])
        p = ProcesadorCSF(ocr)
        p._reconstruir_nombre_tabla()
        assert p.datos["nombre_completo"] == "JUAN PEREZ LOPEZ"


# ── Código Postal ──────────────────────────────────────────────────
class TestCP:
    def test_cp_from_label(self):
        ocr = _ocr([_bloque("CODIGO POSTAL: 01234")])
        p = ProcesadorCSF(ocr)
        p._buscar_cp()
        assert p.datos["codigo_postal"] == "01234"

    def test_cp_with_cp_prefix(self):
        ocr = _ocr([_bloque("CP 44100")])
        p = ProcesadorCSF(ocr)
        p._buscar_cp()
        assert p.datos["codigo_postal"] == "44100"

    def test_cp_fallback_five_digits(self):
        """When no CP/CODIGO/POSTAL label, first standalone 5-digit number is used."""
        ocr = _ocr([_bloque("EN DOMICILIO 45678 MEXICO")])
        p = ProcesadorCSF(ocr)
        p._buscar_cp()
        assert p.datos["codigo_postal"] == "45678"

    def test_cp_not_found(self):
        ocr = _ocr([_bloque("NADA AQUI")])
        p = ProcesadorCSF(ocr)
        p._buscar_cp()
        assert p.datos["codigo_postal"] is None


# ── idCIF ───────────────────────────────────────────────────────────
class TestIdCIF:
    def test_id_cif_found(self):
        ocr = _ocr([_bloque("idCIF: 12345678")])
        p = ProcesadorCSF(ocr)
        p._buscar_id_cif()
        assert p.datos["id_cif"] == "12345678"

    def test_id_cif_no_space(self):
        ocr = _ocr([_bloque("idCIF:99887766")])
        p = ProcesadorCSF(ocr)
        p._buscar_id_cif()
        assert p.datos["id_cif"] == "99887766"

    def test_id_cif_not_found(self):
        ocr = _ocr([_bloque("SIN ID")])
        p = ProcesadorCSF(ocr)
        p._buscar_id_cif()
        assert p.datos["id_cif"] is None


# ── Fecha Emisión ───────────────────────────────────────────────────
class TestFechaEmision:
    def test_fecha_flexible(self):
        ocr = _ocr([_bloque("A 15 DE MARZO DE 2024")])
        p = ProcesadorCSF(ocr)
        p._buscar_fecha_emision()
        assert p.datos["fecha_emision"] == "15 DE MARZO DE 2024"

    def test_fecha_compact(self):
        """Regex [DE]* character class consumes leading chars from month name."""
        ocr = _ocr([_bloque("A 1 MARZO 2023")])
        p = ProcesadorCSF(ocr)
        p._buscar_fecha_emision()
        assert p.datos["fecha_emision"] == "1 DE MARZO DE 2023"

    def test_fecha_not_found(self):
        ocr = _ocr([_bloque("SIN FECHA")])
        p = ProcesadorCSF(ocr)
        p._buscar_fecha_emision()
        assert p.datos["fecha_emision"] is None


# ── Régimen Fiscal ──────────────────────────────────────────────────
class TestRegimenFiscal:
    def test_regimen_from_table(self):
        ocr = _ocr([
            _bloque("REGIMEN FISCAL", x=0, y=0, w=180, h=25),
            _bloque("GENERAL DE LEY PERSONAS MORALES", x=190, y=0, w=350, h=25),
        ])
        p = ProcesadorCSF(ocr)
        p._buscar_regimen()
        assert p.datos["regimen_fiscal"] is not None
        assert "GENERAL" in p.datos["regimen_fiscal"]

    def test_regimen_truncated_at_domicilio(self):
        """Regimen text should be cut off when DOMICILIO keyword appears."""
        ocr = _ocr([
            _bloque("REGIMEN FISCAL: SUELDOS Y SALARIOS DOMICILIO FISCAL CALLE 5"),
        ])
        p = ProcesadorCSF(ocr)
        p._buscar_regimen()
        assert p.datos["regimen_fiscal"] is not None
        assert "DOMICILIO" not in p.datos["regimen_fiscal"]
        assert "SUELDOS" in p.datos["regimen_fiscal"]

    def test_regimen_not_found(self):
        ocr = _ocr([_bloque("NADA")])
        p = ProcesadorCSF(ocr)
        p._buscar_regimen()
        assert p.datos["regimen_fiscal"] is None


# ── _es_stop_word ───────────────────────────────────────────────────
class TestEsStopWord:
    def test_stop_word_detected(self):
        p = ProcesadorCSF(None)
        assert p._es_stop_word("RFC") is True
        assert p._es_stop_word("CURP") is True
        assert p._es_stop_word("NOMBRE") is True

    def test_not_stop_word(self):
        p = ProcesadorCSF(None)
        assert p._es_stop_word("JUAN PEREZ") is False

    def test_stop_word_partial(self):
        """Partial ratio > 90 for 'SAT' inside longer text."""
        p = ProcesadorCSF(None)
        assert p._es_stop_word("SAT") is True


# ── _encontrar_etiqueta_fuzzy ──────────────────────────────────────
class TestEncontrarEtiquetaFuzzy:
    def test_exact_match(self):
        ocr = _ocr([
            _bloque("NOMBRE (S)", x=0, y=0),
            _bloque("VALOR", x=200, y=0),
        ])
        p = ProcesadorCSF(ocr)
        result = p._encontrar_etiqueta_fuzzy("NOMBRE (S)")
        assert result is not None
        assert "NOMBRE" in result["texto_upper"]

    def test_no_match(self):
        ocr = _ocr([_bloque("HOLA")])
        p = ProcesadorCSF(ocr)
        result = p._encontrar_etiqueta_fuzzy("ZZZZZZZZZ")
        assert result is None

    def test_empty_keyword(self):
        ocr = _ocr([_bloque("HOLA")])
        p = ProcesadorCSF(ocr)
        assert p._encontrar_etiqueta_fuzzy("") is None
        assert p._encontrar_etiqueta_fuzzy(None) is None  # type: ignore[arg-type]


# ── _buscar_valor_tabla ─────────────────────────────────────────────
class TestBuscarValorTabla:
    def test_value_to_right(self):
        ocr = _ocr([
            _bloque("NOMBRE (S)", x=0, y=0, w=120, h=25),
            _bloque("MARIA", x=130, y=0, w=80, h=25),
        ])
        p = ProcesadorCSF(ocr)
        val = p._buscar_valor_tabla("NOMBRE (S)")
        assert val == "MARIA"

    def test_value_below(self):
        ocr = _ocr([
            _bloque("PRIMER APELLIDO", x=0, y=0, w=180, h=25),
            _bloque("GONZALEZ", x=0, y=30, w=180, h=25),
        ])
        p = ProcesadorCSF(ocr)
        val = p._buscar_valor_tabla("PRIMER APELLIDO")
        assert val == "GONZALEZ"

    def test_no_label_returns_none(self):
        ocr = _ocr([_bloque("NADA")])
        p = ProcesadorCSF(ocr)
        val = p._buscar_valor_tabla("INEXISTENTE")
        assert val is None

    def test_string_etiqueta(self):
        """Accept a single string (not list)."""
        ocr = _ocr([
            _bloque("PRIMER APELLIDO", x=0, y=0, w=180, h=25),
            _bloque("LOPEZ", x=0, y=30, w=180, h=25),
        ])
        p = ProcesadorCSF(ocr)
        val = p._buscar_valor_tabla("PRIMER APELLIDO")
        assert val == "LOPEZ"


# ── extraer_datos_csf (facade) ─────────────────────────────────────
class TestExtraerDatosCSF:
    def test_empty_returns_all_none(self):
        result = extraer_datos_csf(None)
        assert result["rfc"] is None
        assert result["nombre_completo"] is None

    def test_full_document(self):
        ocr = _ocr([
            _bloque("REGISTRO FEDERAL DE CONTRIBUYENTES", x=0, y=0, w=500, h=30),
            _bloque("RFC: VECJ880326AB1", x=0, y=40, w=300, h=30),
            _bloque("CURP: VECJ880326HJCRZN09", x=0, y=80, w=350, h=30),
            _bloque("JUAN PEREZ LOPEZ", x=0, y=120, w=300, h=30),
            _bloque("DENOMINACION O RAZON SOCIAL", x=0, y=170, w=400, h=30),
            _bloque("CODIGO POSTAL: 44100", x=0, y=210, w=250, h=30),
            _bloque("idCIF: 55667788", x=0, y=250, w=200, h=30),
            _bloque("A 15 DE MARZO DE 2024", x=0, y=290, w=300, h=30),
            _bloque("REGIMEN FISCAL", x=0, y=330, w=180, h=25),
            _bloque("GENERAL DE LEY PERSONAS MORALES", x=190, y=330, w=350, h=25),
        ])
        result = extraer_datos_csf(ocr)
        assert result["rfc"] == "VECJ880326AB1"
        assert result["curp"] == "VECJ880326HJCRZN09"
        assert result["nombre_completo"] == "JUAN PEREZ LOPEZ"
        assert result["codigo_postal"] == "44100"
        assert result["id_cif"] == "55667788"
        assert result["fecha_emision"] == "15 DE MARZO DE 2024"
        assert result["regimen_fiscal"] is not None
