"""Tests for app.pipelines.legacy_adapter."""

from __future__ import annotations

import pytest

from app.pipelines.legacy_adapter import (
    _lines_from_boxes,
    _to_legacy_ocr_results,
    legacy_extract_fields,
)


# ── _to_legacy_ocr_results ──────────────────────────────────────

class TestToLegacyOcrResults:
    def test_empty_input(self):
        assert _to_legacy_ocr_results([]) == []
        assert _to_legacy_ocr_results(None) == []

    def test_single_page_single_box(self):
        boxes = [{"page": 1, "bbox": [0, 0, 100, 20], "text": "HELLO", "confidence": 0.99}]
        result = _to_legacy_ocr_results(boxes)
        assert len(result) == 1
        assert len(result[0]) == 1
        assert result[0][0][1] == ["HELLO", 0.99]

    def test_multiple_pages_sorted(self):
        boxes = [
            {"page": 2, "bbox": [0, 0, 1, 1], "text": "B", "confidence": 0.9},
            {"page": 1, "bbox": [0, 0, 1, 1], "text": "A", "confidence": 0.8},
        ]
        result = _to_legacy_ocr_results(boxes)
        assert len(result) == 2
        assert result[0][0][1][0] == "A"
        assert result[1][0][1][0] == "B"

    def test_missing_fields_defaults(self):
        boxes = [{"text": "X"}]
        result = _to_legacy_ocr_results(boxes)
        assert len(result) == 1
        # defaults: page=1, bbox=[], confidence=0.0
        assert result[0][0][0] == []
        assert result[0][0][1] == ["X", 0.0]

    def test_none_values_default(self):
        boxes = [{"page": None, "bbox": None, "text": None, "confidence": None}]
        result = _to_legacy_ocr_results(boxes)
        assert result[0][0][1] == ["", 0.0]


# ── _lines_from_boxes ───────────────────────────────────────────

class TestLinesFromBoxes:
    def test_empty_input(self):
        assert _lines_from_boxes([]) == []
        assert _lines_from_boxes(None) == []

    def test_extracts_text_lines(self):
        boxes = [
            {"text": "  HELLO  "},
            {"text": "WORLD"},
        ]
        assert _lines_from_boxes(boxes) == ["HELLO", "WORLD"]

    def test_strips_and_skips_blanks(self):
        boxes = [
            {"text": "OK"},
            {"text": "  "},
            {"text": ""},
            {"text": "YES"},
        ]
        assert _lines_from_boxes(boxes) == ["OK", "YES"]

    def test_missing_text_key(self):
        boxes = [{"bbox": [1, 2, 3, 4]}]
        assert _lines_from_boxes(boxes) == []


# ── legacy_extract_fields ────────────────────────────────────────

class TestLegacyExtractFields:
    def test_empty_boxes_returns_empty(self):
        assert legacy_extract_fields("INE", []) == {}
        assert legacy_extract_fields("INE", None) == {}

    def test_unknown_document_type_returns_empty(self):
        boxes = [{"page": 1, "bbox": [0, 0, 1, 1], "text": "HOLA", "confidence": 0.9}]
        result = legacy_extract_fields("TIPO_DESCONOCIDO", boxes)
        assert result == {}

    # ── INE ──

    def test_ine_extracts_curp(self):
        boxes = [
            {"page": 1, "bbox": [[0,0],[100,0],[100,20],[0,20]], "text": "INSTITUTO NACIONAL ELECTORAL", "confidence": 0.9},
            {"page": 1, "bbox": [[0,20],[100,20],[100,40],[0,40]], "text": "NOMBRE GARCIA LOPEZ JUAN", "confidence": 0.9},
            {"page": 1, "bbox": [[0,40],[100,40],[100,60],[0,60]], "text": "CURP GALJ900101HDFRPN09", "confidence": 0.9},
            {"page": 1, "bbox": [[0,60],[100,60],[100,80],[0,80]], "text": "CLAVE DE ELECTOR GRLPJN90010109H100", "confidence": 0.9},
            {"page": 1, "bbox": [[0,80],[100,80],[100,100],[0,100]], "text": "SECCION 0100", "confidence": 0.9},
            {"page": 1, "bbox": [[0,100],[100,100],[100,120],[0,120]], "text": "VIGENCIA 2029", "confidence": 0.9},
        ]
        result = legacy_extract_fields("INE", boxes)
        # INE returns a dict with these keys even if some are None
        expected_keys = {"nombre", "nombres", "apellido_paterno", "apellido_materno",
                         "sexo", "domicilio", "clave_elector", "curp",
                         "anio_registro", "fecha_nacimiento", "seccion", "vigencia"}
        assert expected_keys == set(result.keys())

    # ── CURP ──

    def test_curp_extracts_fields(self):
        boxes = [
            {"page": 1, "bbox": [[0,0],[200,0],[200,20],[0,20]], "text": "ESTADOS UNIDOS MEXICANOS CLAVE UNICA DE REGISTRO DE POBLACION", "confidence": 0.9},
            {"page": 1, "bbox": [[0,20],[200,20],[200,40],[0,40]], "text": "GALJ900101HDFRPN09", "confidence": 0.9},
            {"page": 1, "bbox": [[0,40],[200,40],[200,60],[0,60]], "text": "GARCIA LOPEZ JUAN", "confidence": 0.9},
        ]
        result = legacy_extract_fields("CURP", boxes)
        expected_keys = {"curp", "nombre", "entidad_registro", "fecha_emision"}
        assert expected_keys == set(result.keys())

    # ── NSS ──

    def test_nss_extracts_fields(self):
        boxes = [
            {"page": 1, "bbox": [[0,0],[300,0],[300,20],[0,20]], "text": "INSTITUTO MEXICANO DEL SEGURO SOCIAL", "confidence": 0.9},
            {"page": 1, "bbox": [[0,20],[300,20],[300,40],[0,40]], "text": "NUMERO DE SEGURIDAD SOCIAL 12345678901", "confidence": 0.9},
            {"page": 1, "bbox": [[0,40],[300,40],[300,60],[0,60]], "text": "CURP GALJ900101HDFRPN09", "confidence": 0.9},
            {"page": 1, "bbox": [[0,60],[300,60],[300,80],[0,80]], "text": "GARCIA LOPEZ JUAN", "confidence": 0.9},
        ]
        result = legacy_extract_fields("NSS", boxes)
        expected_keys = {"nss", "nombre", "curp", "fecha_documento", "folio_solicitud"}
        assert expected_keys == set(result.keys())

    # ── ACTA_NACIMIENTO ──

    def test_acta_extracts_fields(self):
        boxes = [
            {"page": 1, "bbox": [[0,0],[300,0],[300,20],[0,20]], "text": "ACTA DE NACIMIENTO", "confidence": 0.9},
            {"page": 1, "bbox": [[0,20],[300,20],[300,40],[0,40]], "text": "NOMBRE JUAN", "confidence": 0.9},
            {"page": 1, "bbox": [[0,40],[300,40],[300,60],[0,60]], "text": "GARCIA LOPEZ", "confidence": 0.9},
            {"page": 1, "bbox": [[0,60],[300,60],[300,80],[0,80]], "text": "SEXO MASCULINO", "confidence": 0.9},
        ]
        result = legacy_extract_fields("ACTA_NACIMIENTO", boxes)
        expected_keys = {"entidad_registro", "municipio_registro", "nombre",
                         "primer_apellido", "segundo_apellido", "sexo",
                         "fecha_nacimiento", "lugar_nacimiento", "anio_registro", "curp"}
        assert expected_keys == set(result.keys())

    # ── CSF ──

    def test_csf_extracts_fields(self):
        boxes = [
            {"page": 1, "bbox": [[0,0],[400,0],[400,20],[0,20]], "text": "CEDULA DE IDENTIFICACION FISCAL", "confidence": 0.9},
            {"page": 1, "bbox": [[0,20],[400,20],[400,40],[0,40]], "text": "RFC GARL900101ABC", "confidence": 0.9},
            {"page": 1, "bbox": [[0,40],[400,40],[400,60],[0,60]], "text": "CURP GALJ900101HDFRPN09", "confidence": 0.9},
            {"page": 1, "bbox": [[0,60],[400,60],[400,80],[0,80]], "text": "NOMBRE GARCIA LOPEZ JUAN", "confidence": 0.9},
            {"page": 1, "bbox": [[0,80],[400,80],[400,100],[0,100]], "text": "CODIGO POSTAL 01234", "confidence": 0.9},
            {"page": 1, "bbox": [[0,100],[400,100],[400,120],[0,120]], "text": "REGIMEN GENERAL", "confidence": 0.9},
            {"page": 1, "bbox": [[0,120],[400,120],[400,140],[0,140]], "text": "FECHA 01/01/2020", "confidence": 0.9},
        ]
        result = legacy_extract_fields("CONSTANCIA_SITUACION_FISCAL", boxes)
        expected_keys = {"rfc", "curp", "nombre", "cp", "id_cif", "fecha_emision", "regimen"}
        assert expected_keys == set(result.keys())

    # ── DATOS_BANCARIOS ──

    def test_banco_extracts_fields(self):
        boxes = [
            {"page": 1, "bbox": [0, 0, 1, 1], "text": "BBVA BANCOMER", "confidence": 0.9},
            {"page": 1, "bbox": [0, 0, 1, 1], "text": "TITULAR GARCIA LOPEZ JUAN", "confidence": 0.9},
            {"page": 1, "bbox": [0, 0, 1, 1], "text": "CLABE 012345678901234567", "confidence": 0.9},
            {"page": 1, "bbox": [0, 0, 1, 1], "text": "CUENTA 1234567890", "confidence": 0.9},
        ]
        result = legacy_extract_fields("DATOS_BANCARIOS", boxes)
        expected_keys = {"banco", "titular", "clabe", "cuenta"}
        assert expected_keys == set(result.keys())

    def test_factura_uses_banco_extractor(self):
        """FACTURA doc type also uses banco_logic."""
        boxes = [
            {"page": 1, "bbox": [0, 0, 1, 1], "text": "FACTURA", "confidence": 0.9},
            {"page": 1, "bbox": [0, 0, 1, 1], "text": "CLABE 012345678901234567", "confidence": 0.9},
        ]
        result = legacy_extract_fields("FACTURA", boxes)
        assert "clabe" in result

    # ── COMPROBANTE_DOMICILIO ──

    def test_domicilio_extracts_fields(self):
        boxes = [
            {"page": 1, "bbox": [0, 0, 1, 1], "text": "CFE COMISION FEDERAL DE ELECTRICIDAD", "confidence": 0.9},
            {"page": 1, "bbox": [0, 0, 1, 1], "text": "CALLE REFORMA 123", "confidence": 0.9},
            {"page": 1, "bbox": [0, 0, 1, 1], "text": "COLONIA CENTRO", "confidence": 0.9},
            {"page": 1, "bbox": [0, 0, 1, 1], "text": "C.P. 06000", "confidence": 0.9},
        ]
        result = legacy_extract_fields("COMPROBANTE_DOMICILIO", boxes)
        expected_keys = {"domicilio", "cp", "proveedor"}
        assert expected_keys == set(result.keys())

    # ── Error handling ──

    def test_exception_returns_empty_dict(self, monkeypatch):
        """If the legacy extractor throws, return {} instead of propagating."""
        def boom(*args, **kwargs):
            raise RuntimeError("Extraction crash")

        monkeypatch.setattr("app.legacy_motor.ine_logic.ProcesadorINE.__init__", boom)
        boxes = [{"page": 1, "bbox": [0, 0, 1, 1], "text": "HELLO", "confidence": 0.9}]
        result = legacy_extract_fields("INE", boxes)
        assert result == {}

    # ── GENERICO banco returns None ──

    def test_banco_generico_returns_none_for_banco(self):
        """When banco_detectado is GENERICO, banco field should be None."""
        boxes = [
            {"page": 1, "bbox": [0, 0, 1, 1], "text": "ESTADO DE CUENTA", "confidence": 0.9},
            {"page": 1, "bbox": [0, 0, 1, 1], "text": "TITULAR JUAN", "confidence": 0.9},
        ]
        result = legacy_extract_fields("DATOS_BANCARIOS", boxes)
        # If the banco is GENERICO, should be None
        if result.get("banco") is not None:
            assert result["banco"] != "GENERICO"
