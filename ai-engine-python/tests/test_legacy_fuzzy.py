"""Tests for app.legacy_motor.fuzzy – lightweight fuzzy-matching helpers."""

import pytest

from app.legacy_motor.fuzzy import _as_text, fuzz, process


# ── _as_text helper ──────────────────────────────────────────────────────

class TestAsText:
    def test_none_returns_empty(self):
        assert _as_text(None) == ""

    def test_empty_string(self):
        assert _as_text("") == ""

    def test_strips_and_uppercases(self):
        assert _as_text("  hello world  ") == "HELLO WORLD"

    def test_numeric_input(self):
        assert _as_text(123) == "123"


# ── fuzz.ratio ───────────────────────────────────────────────────────────

class TestFuzzRatio:
    def test_identical_strings(self):
        assert fuzz.ratio("hello", "hello") == 100

    def test_case_insensitive(self):
        assert fuzz.ratio("Hello", "HELLO") == 100

    def test_completely_different(self):
        assert fuzz.ratio("abc", "xyz") < 50

    def test_both_empty(self):
        assert fuzz.ratio("", "") == 100

    def test_one_empty(self):
        assert fuzz.ratio("abc", "") == 0
        assert fuzz.ratio("", "abc") == 0

    def test_none_values(self):
        assert fuzz.ratio(None, None) == 100
        assert fuzz.ratio(None, "abc") == 0

    def test_similar_strings(self):
        score = fuzz.ratio("ENTIDAD DE REGISTRO", "ENTIDAD DE REGISTRE")
        assert score > 85

    def test_returns_int(self):
        result = fuzz.ratio("abc", "abd")
        assert isinstance(result, int)


# ── fuzz.token_set_ratio ────────────────────────────────────────────────

class TestFuzzTokenSetRatio:
    def test_identical(self):
        assert fuzz.token_set_ratio("hello world", "hello world") == 100

    def test_reordered_tokens(self):
        assert fuzz.token_set_ratio("world hello", "hello world") == 100

    def test_duplicate_tokens_ignored(self):
        assert fuzz.token_set_ratio("hello hello world", "hello world") == 100

    def test_completely_different(self):
        assert fuzz.token_set_ratio("abc", "xyz") < 50


# ── fuzz.partial_ratio ──────────────────────────────────────────────────

class TestFuzzPartialRatio:
    def test_substring_match(self):
        assert fuzz.partial_ratio("abc", "xxabcxx") == 100

    def test_identical(self):
        assert fuzz.partial_ratio("hello", "hello") == 100

    def test_one_empty(self):
        assert fuzz.partial_ratio("", "abc") == 0
        assert fuzz.partial_ratio("abc", "") == 0

    def test_both_empty(self):
        assert fuzz.partial_ratio("", "") == 0

    def test_close_substring(self):
        score = fuzz.partial_ratio("NOMBRE", "NOMBRE(S)")
        assert score > 80

    def test_no_match(self):
        score = fuzz.partial_ratio("xyz", "abcdef")
        assert score < 60


# ── process.extractOne ──────────────────────────────────────────────────

class TestProcessExtractOne:
    def test_best_match(self):
        choices = ["AGUASCALIENTES", "BAJA CALIFORNIA", "CHIAPAS"]
        result = process.extractOne("AGUASCALIENTS", choices)
        assert result is not None
        best, score = result
        assert best == "AGUASCALIENTES"
        assert score > 80

    def test_exact_match_returns_100(self):
        choices = ["alpha", "beta", "gamma"]
        result = process.extractOne("ALPHA", choices)
        assert result is not None
        assert result[1] == 100

    def test_empty_choices(self):
        assert process.extractOne("abc", []) is None

    def test_none_choices(self):
        assert process.extractOne("abc", None) is None

    def test_custom_scorer(self):
        choices = ["xxhelloxx", "goodbye"]
        result = process.extractOne("hello", choices, scorer=fuzz.partial_ratio)
        assert result is not None
        assert result[0] == "xxhelloxx"
        assert result[1] == 100

    def test_single_choice(self):
        result = process.extractOne("abc", ["xyz"])
        assert result is not None
        assert result[0] == "xyz"
