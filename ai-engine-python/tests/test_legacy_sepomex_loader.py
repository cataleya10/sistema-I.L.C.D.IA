"""Tests for app.legacy_motor.sepomex_loader – SepomexLoader."""

from __future__ import annotations

import json
import os
import pytest
from app.legacy_motor.sepomex_loader import SepomexLoader


# ── helper: create a temporary JSON cache ───────────────────────────
@pytest.fixture()
def sepomex_json(tmp_path):
    """Write a minimal sepomex.json into tmp_path and return a SepomexLoader."""
    data = {
        "44100": {
            "colonias": ["CENTRO", "LA PAZ"],
            "municipio": "GUADALAJARA",
            "estado": "JALISCO",
        },
        "06600": {
            "colonias": ["JUAREZ", "CUAUHTEMOC"],
            "municipio": "CUAUHTEMOC",
            "estado": "CIUDAD DE MEXICO",
        },
    }
    json_file = tmp_path / "sepomex.json"
    json_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return SepomexLoader(base_path=str(tmp_path))


# ── init ────────────────────────────────────────────────────────────
class TestInit:
    def test_loads_from_json(self, sepomex_json):
        assert len(sepomex_json.db) == 2
        assert "44100" in sepomex_json.db

    def test_no_files_empty_db(self, tmp_path):
        loader = SepomexLoader(base_path=str(tmp_path))
        assert loader.db == {}


# ── buscar_cp ───────────────────────────────────────────────────────
class TestBuscarCP:
    def test_found(self, sepomex_json):
        result = sepomex_json.buscar_cp("44100")
        assert result is not None
        assert result["municipio"] == "GUADALAJARA"
        assert "CENTRO" in result["colonias"]

    def test_not_found(self, sepomex_json):
        assert sepomex_json.buscar_cp("99999") is None

    def test_none_input(self, sepomex_json):
        assert sepomex_json.buscar_cp(None) is None

    def test_strips_non_digits(self, sepomex_json):
        """Passing 'CP 44100' should still find the entry."""
        result = sepomex_json.buscar_cp("CP 44100")
        assert result is not None
        assert result["estado"] == "JALISCO"

    def test_integer_input(self, sepomex_json):
        result = sepomex_json.buscar_cp(44100)
        assert result is not None

    def test_zero_padded(self, sepomex_json):
        """'06600' should be found."""
        result = sepomex_json.buscar_cp("06600")
        assert result is not None
        assert result["estado"] == "CIUDAD DE MEXICO"

    def test_empty_string(self, sepomex_json):
        result = sepomex_json.buscar_cp("")
        assert result is None


# ── _resolve_data_dir ───────────────────────────────────────────────
class TestResolveDataDir:
    def test_explicit_base_path(self, tmp_path):
        loader = SepomexLoader(base_path=str(tmp_path))
        # Should use the explicit path
        assert str(tmp_path) in loader.json_path


# ── cargar_desde_json (error handling) ──────────────────────────────
class TestCargarDesdeJson:
    def test_corrupt_json_falls_back(self, tmp_path):
        """If JSON is corrupt, db should remain empty (XML also missing)."""
        json_file = tmp_path / "sepomex.json"
        json_file.write_text("{invalid json!!", encoding="utf-8")
        loader = SepomexLoader(base_path=str(tmp_path))
        assert loader.db == {}
