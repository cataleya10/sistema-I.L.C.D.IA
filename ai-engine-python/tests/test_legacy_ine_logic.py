"""Tests for app.legacy_motor.ine_logic – ProcesadorINE."""

from __future__ import annotations

from unittest.mock import patch
import pytest
from app.legacy_motor.ine_logic import ProcesadorINE


# ── init ────────────────────────────────────────────────────────────
class TestInit:
    def test_empty_list(self):
        p = ProcesadorINE([])
        assert p.lista_texto == []
        assert p.texto_completo == ""

    def test_strips_whitespace(self):
        p = ProcesadorINE(["  HOLA  ", "  ", "MUNDO"])
        assert p.lista_texto == ["HOLA", "MUNDO"]

    def test_texto_completo_upper(self):
        p = ProcesadorINE(["hola", "mundo"])
        assert p.texto_completo == "HOLA MUNDO"


# ── MRZ cleaning ───────────────────────────────────────────────────
class TestLimpiarMRZ:
    def test_double_chevron(self):
        p = ProcesadorINE([])
        # << → " ", then remaining < → " ", so "PEREZ JUAN CARLOS"
        assert p._limpiar_mrz_nombre("PEREZ<<JUAN<CARLOS") == "PEREZ JUAN CARLOS"

    def test_single_chevron(self):
        p = ProcesadorINE([])
        assert p._limpiar_mrz_nombre("LOPEZ<ANA") == "LOPEZ ANA"


# ── _buscar_indice_difuso ──────────────────────────────────────────
class TestBuscarIndiceDifuso:
    def test_exact_match(self):
        p = ProcesadorINE(["FOO", "NOMBRE", "BAR"])
        assert p._buscar_indice_difuso("NOMBRE") == 1

    def test_fuzzy_match(self):
        p = ProcesadorINE(["FOO", "NOMNRE", "BAR"])
        idx = p._buscar_indice_difuso("NOMBRE")
        # fuzzy token_set_ratio should match "NOMNRE" → NOMBRE
        assert idx == 1

    def test_not_found(self):
        p = ProcesadorINE(["ALGO", "DIFERENTE"])
        assert p._buscar_indice_difuso("ZZZZZZZ") == -1


# ── _es_basura_en_nombre ───────────────────────────────────────────
class TestEsBasuraEnNombre:
    def test_has_digit(self):
        p = ProcesadorINE([])
        assert p._es_basura_en_nombre("FOLIO 123") is True

    def test_has_keyword(self):
        p = ProcesadorINE([])
        assert p._es_basura_en_nombre("FECHA DE NACIMIENTO") is True
        assert p._es_basura_en_nombre("DOMICILIO") is True

    def test_clean_name(self):
        p = ProcesadorINE([])
        assert p._es_basura_en_nombre("JUAN PEREZ") is False


# ── _es_basura_en_domicilio ────────────────────────────────────────
class TestEsBasuraEnDomicilio:
    def test_has_keyword(self):
        p = ProcesadorINE([])
        assert p._es_basura_en_domicilio("DOMICILIO") is True
        assert p._es_basura_en_domicilio("CURP: ALGO") is True

    def test_clean_address(self):
        p = ProcesadorINE([])
        assert p._es_basura_en_domicilio("AV REFORMA 123") is False


# ── extraer_nombre ─────────────────────────────────────────────────
class TestExtraerNombre:
    def test_from_mrz(self):
        p = ProcesadorINE(["PEREZ<<JUAN<CARLOS"])
        nombre = p.extraer_nombre()
        assert nombre is not None
        assert "PEREZ" in nombre
        assert "JUAN" in nombre

    def test_mrz_skips_idmex(self):
        p = ProcesadorINE(["IDMEX<<ALGO<STUFF"])
        nombre = p.extraer_nombre()
        assert nombre is None

    def test_between_nombre_and_domicilio(self):
        p = ProcesadorINE([
            "INSTITUTO NACIONAL ELECTORAL",
            "NOMBRE",
            "GARCIA LOPEZ MARIA",
            "DOMICILIO",
            "AV REFORMA 123",
        ])
        nombre = p.extraer_nombre()
        assert nombre == "GARCIA LOPEZ MARIA"

    def test_nombre_only_no_domicilio(self):
        p = ProcesadorINE([
            "NOMBRE",
            "PEREZ GOMEZ JUAN",
            "FOLIO 12345",
        ])
        nombre = p.extraer_nombre()
        assert nombre == "PEREZ GOMEZ JUAN"

    def test_no_markers(self):
        p = ProcesadorINE(["ALGO", "SIN", "MARCADORES"])
        assert p.extraer_nombre() is None


# ── extraer_domicilio ──────────────────────────────────────────────
class TestExtraerDomicilio:
    def test_between_domicilio_and_clave(self):
        p = ProcesadorINE([
            "NOMBRE",
            "PEREZ LOPEZ JUAN",
            "DOMICILIO",
            "AV REFORMA 123 COL CENTRO",
            "CP 06000",
            "CLAVE DE ELECTOR",
            "ABRCLP12345678AB01",
        ])
        dom = p.extraer_domicilio()
        assert dom is not None
        assert "REFORMA" in dom

    def test_no_markers(self):
        p = ProcesadorINE(["ALGO RANDOM"])
        assert p.extraer_domicilio() is None


# ── extraer_fecha_nacimiento ───────────────────────────────────────
class TestExtraerFechaNacimiento:
    def test_date_slash(self):
        p = ProcesadorINE(["15/03/1990"])
        assert p.extraer_fecha_nacimiento() == "15/03/1990"

    def test_date_dot(self):
        p = ProcesadorINE(["15.03.1990"])
        assert p.extraer_fecha_nacimiento() == "15/03/1990"

    def test_date_dash(self):
        p = ProcesadorINE(["15-03-1990"])
        assert p.extraer_fecha_nacimiento() == "15/03/1990"

    def test_date_pegado(self):
        """dd/mm followed directly by yyyy without separator."""
        p = ProcesadorINE(["15/032000"])
        assert p.extraer_fecha_nacimiento() == "15/03/2000"

    def test_not_found(self):
        p = ProcesadorINE(["SIN FECHA"])
        assert p.extraer_fecha_nacimiento() is None


# ── extraer_vigencia ───────────────────────────────────────────────
class TestExtraerVigencia:
    def test_range(self):
        p = ProcesadorINE(["VIGENCIA 2019 - 2029"])
        assert p.extraer_vigencia() == "2019-2029"

    def test_single_year(self):
        p = ProcesadorINE(["VIGENCIA 2025"])
        assert p.extraer_vigencia() == "2025"

    def test_not_found(self):
        p = ProcesadorINE(["SIN INFO"])
        assert p.extraer_vigencia() is None


# ── extraer_seccion ────────────────────────────────────────────────
class TestExtraerSeccion:
    def test_seccion_label(self):
        p = ProcesadorINE(["SECCION 1234"])
        assert p.extraer_seccion() == "1234"

    def test_seccion_with_zero(self):
        """SECCI0N (zero instead of O)."""
        p = ProcesadorINE(["SECCI0N 456"])
        assert p.extraer_seccion() == "456"

    def test_not_found(self):
        p = ProcesadorINE(["NADA"])
        assert p.extraer_seccion() is None


# ── extraer_curp ───────────────────────────────────────────────────
class TestExtraerCURP:
    def test_standard_curp(self):
        p = ProcesadorINE(["CURP VECJ880326HJCRZN09"])
        assert p.extraer_curp() == "VECJ880326HJCRZN09"

    def test_short_curp(self):
        p = ProcesadorINE(["ALGO VECJ880326HJCRZNA"])
        curp = p.extraer_curp()
        assert curp is not None
        assert curp.startswith("VECJ880326")

    def test_not_found(self):
        p = ProcesadorINE(["SIN CURP"])
        assert p.extraer_curp() is None


# ── extraer_clave_elector ──────────────────────────────────────────
class TestExtraerClaveElector:
    def test_found(self):
        p = ProcesadorINE(["CLAVE ABCDEF12345678XY01"])
        assert p.extraer_clave_elector() == "ABCDEF12345678XY01"

    def test_not_found(self):
        p = ProcesadorINE(["SIN CLAVE"])
        assert p.extraer_clave_elector() is None


# ── extraer_sexo ───────────────────────────────────────────────────
class TestExtraerSexo:
    def test_sexo_h(self):
        p = ProcesadorINE(["SEXO H"])
        assert p.extraer_sexo() == "H"

    def test_sexo_m(self):
        p = ProcesadorINE(["SEXO M"])
        assert p.extraer_sexo() == "M"

    def test_from_curp(self):
        p = ProcesadorINE(["VECJ880326HJCRZN09"])
        sexo = p.extraer_sexo()
        assert sexo == "H"

    def test_not_found(self):
        p = ProcesadorINE(["SIN DATOS"])
        assert p.extraer_sexo() is None


# ── extraer_anio_registro ──────────────────────────────────────────
class TestExtraerAnioRegistro:
    def test_six_digit_year_prefix(self):
        """Matches 6-digit block where first 4 are a year."""
        p = ProcesadorINE(["REGISTRO 202301"])
        assert p.extraer_anio_registro() == "2023"

    def test_from_registro_label(self):
        p = ProcesadorINE(["REGISTRO 2019"])
        assert p.extraer_anio_registro() == "2019"

    def test_not_found(self):
        p = ProcesadorINE(["SIN AÑO"])
        assert p.extraer_anio_registro() is None


# ── _estructurar_nombre_completo ───────────────────────────────────
class TestEstructurarNombre:
    def test_three_parts(self):
        p = ProcesadorINE([])
        result = p._estructurar_nombre_completo("PEREZ LOPEZ JUAN CARLOS")
        assert result["apellido_paterno"] == "PEREZ"
        assert result["apellido_materno"] == "LOPEZ"
        assert result["nombres"] == "JUAN CARLOS"

    def test_two_parts(self):
        p = ProcesadorINE([])
        result = p._estructurar_nombre_completo("PEREZ JUAN")
        assert result["apellido_paterno"] == "PEREZ"
        assert result["apellido_materno"] is None
        assert result["nombres"] == "JUAN"

    def test_single_part(self):
        p = ProcesadorINE([])
        result = p._estructurar_nombre_completo("JUAN")
        assert result["nombres"] == "JUAN"
        assert result["apellido_paterno"] is None

    def test_none(self):
        p = ProcesadorINE([])
        result = p._estructurar_nombre_completo(None)
        assert result["nombres"] is None
        assert result["apellido_paterno"] is None
        assert result["apellido_materno"] is None


# ── _limpiar_direccion_inteligente (without SEPOMEX) ───────────────
class TestLimpiarDireccion:
    def test_none_returns_none(self):
        p = ProcesadorINE([])
        assert p._limpiar_direccion_inteligente(None) is None

    def test_splits_letter_digit(self):
        p = ProcesadorINE([])
        result = p._limpiar_direccion_inteligente("AV5 CALLE3")
        assert result is not None
        assert "AV 5" in result
        assert "CALLE 3" in result

    def test_removes_duplicate_last_word(self):
        p = ProcesadorINE([])
        result = p._limpiar_direccion_inteligente("CALLE NORTE NORTE")
        assert result == "CALLE NORTE"


# ── obtener_json (integration) ─────────────────────────────────────
class TestObtenerJson:
    def test_all_keys_present(self):
        p = ProcesadorINE(["ALGO"])
        result = p.obtener_json()
        expected_keys = {
            "nombre_completo", "nombres", "apellido_paterno", "apellido_materno",
            "sexo", "domicilio", "clave_elector", "curp",
            "anio_registro", "fecha_nacimiento", "seccion", "vigencia",
        }
        assert set(result.keys()) == expected_keys

    def test_full_ine_document(self):
        lines = [
            "INSTITUTO NACIONAL ELECTORAL",
            "NOMBRE",
            "PEREZ LOPEZ JUAN CARLOS",
            "DOMICILIO",
            "AV REFORMA 123 COL CENTRO",
            "SEXO H",
            "FECHA DE NACIMIENTO 15/03/1990",
            "CLAVE DE ELECTOR ABCDEF12345678XY01",
            "CURP VECJ880326HJCRZN09",
            "SECCION 1234",
            "VIGENCIA 2019 - 2029",
            "REGISTRO 202301",
        ]
        p = ProcesadorINE(lines)
        result = p.obtener_json()
        assert result["nombre_completo"] is not None
        assert result["sexo"] == "H"
        assert result["fecha_nacimiento"] == "15/03/1990"
        assert result["clave_elector"] == "ABCDEF12345678XY01"
        assert result["curp"] == "VECJ880326HJCRZN09"
        assert result["seccion"] == "1234"
        assert result["vigencia"] == "2019-2029"

    def test_empty_input(self):
        p = ProcesadorINE([])
        result = p.obtener_json()
        assert result["nombre_completo"] is None
        assert result["curp"] is None
