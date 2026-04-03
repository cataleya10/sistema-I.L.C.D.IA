"""
bank_extractors.py — Extractores especializados por banco (Opción B).

Cada extractor conoce el schema exacto de columnas de su banco y usa el
GridTable del geometric_detector para mapear con confianza.

Jerarquía:
  BankExtractorBase          ← interfaz común
    ├── SantanderExtractor   ← FECHA / DESCRIPCION / CARGO / ABONO / SALDO
    ├── BBVAExtractor        ← FECHA / CONCEPTO / RETIROS / DEPOSITOS / SALDO
    ├── BanamexExtractor     ← FECHA / DESCRIPCION / CARGOS / ABONOS / SALDO
    ├── BanorteExtractor     ← FECHA / DESCRIPCION / CARGO / ABONO / SALDO
    ├── HSBCExtractor        ← FECHA / DESCRIPCION / CARGO / ABONO / SALDO
    └── GenericBankExtractor ← fallback: usa lo que encuentre el detector

Uso
---
    from app.pipelines.extract.bank_extractors import get_bank_extractor

    extractor = get_bank_extractor(bank_name)
    cols, rows = extractor.extract(grid_table)
"""

from __future__ import annotations

import logging
import re
import unicodedata
from abc import ABC, abstractmethod
from typing import Any

from .geometric_detector import GridTable

logger = logging.getLogger(__name__)


# ─── Normalización de texto ───────────────────────────────────────────────────

def _norm(text: str) -> str:
    """Normaliza texto: mayúsculas, sin acentos, sin caracteres extra."""
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text.upper())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _best_match(label: str, candidates: list[str], threshold: float = 0.6) -> str | None:
    """
    Retorna el candidato cuya similitud con label supera el umbral.
    Usa comparación de tokens para robustez ante OCR.
    """
    norm_label = _norm(label)
    label_tokens = set(norm_label.split())

    best_score = 0.0
    best_cand = None
    for cand in candidates:
        norm_cand = _norm(cand)
        cand_tokens = set(norm_cand.split())
        if not label_tokens or not cand_tokens:
            continue
        # Jaccard de tokens
        intersection = len(label_tokens & cand_tokens)
        union = len(label_tokens | cand_tokens)
        score = intersection / union if union else 0.0
        # Bonus si uno contiene al otro completamente
        if norm_label in norm_cand or norm_cand in norm_label:
            score = max(score, 0.8)
        if score > best_score:
            best_score = score
            best_cand = cand

    return best_cand if best_score >= threshold else None


# ─── Interfaz base ────────────────────────────────────────────────────────────

class BankExtractorBase(ABC):
    """Extractor base: mapea un GridTable a (column_names, row_dicts)."""

    # Schema esperado: (nombre_canónico, lista de sinónimos en el PDF)
    SCHEMA: list[tuple[str, list[str]]] = []
    BANK_NAME: str = "GENERICO"

    def extract(self, grid: GridTable) -> tuple[list[str], list[dict]]:
        """
        Mapea el GridTable al schema del banco.

        Retorna
        -------
        (cols, rows)
        cols : list[str] — nombres canónicos de columnas
        rows : list[dict] — filas como dicts {col_name: value}
        """
        if not grid or grid.n_rows < 2:
            return [], []

        col_map = self._build_col_map(grid.column_labels)
        logger.info(
            "[%s] col_map detectado: %s",
            self.BANK_NAME,
            {k: v for k, v in col_map.items() if v is not None},
        )

        # Columnas canónicas que sí se encontraron
        found_canonical = [can for can, _ in self.SCHEMA if col_map.get(can) is not None]
        if not found_canonical:
            logger.warning("[%s] no se mapeó ninguna columna del schema", self.BANK_NAME)
            return self._fallback_extract(grid)

        cols = found_canonical
        rows: list[dict] = []

        for row_idx in range(1, grid.n_rows):  # saltar encabezado
            raw = grid.row_texts(row_idx)
            if not any(t.strip() for t in raw):
                continue
            row_dict: dict[str, str] = {}
            for canonical in cols:
                grid_col_idx = col_map.get(canonical)
                if grid_col_idx is not None and grid_col_idx < len(raw):
                    row_dict[canonical] = raw[grid_col_idx].strip()
                else:
                    row_dict[canonical] = ""
            row_dict = self._postprocess_row(row_dict)
            rows.append(row_dict)

        rows = self._filter_rows(rows)
        logger.info("[%s] extraídas %d filas con cols=%s", self.BANK_NAME, len(rows), cols)
        return cols, rows

    def _build_col_map(self, grid_labels: list[str]) -> dict[str, int | None]:
        """
        Para cada columna canónica del schema, encuentra el índice en grid_labels.
        """
        col_map: dict[str, int | None] = {}
        used_indices: set[int] = set()

        for canonical, synonyms in self.SCHEMA:
            best_idx = None
            best_score = 0.0
            for gi, glabel in enumerate(grid_labels):
                if gi in used_indices:
                    continue
                for syn in synonyms:
                    norm_syn = _norm(syn)
                    norm_gl  = _norm(glabel)
                    if not norm_syn or not norm_gl:
                        continue
                    syn_tok = set(norm_syn.split())
                    gl_tok  = set(norm_gl.split())
                    inter = len(syn_tok & gl_tok)
                    union = len(syn_tok | gl_tok)
                    score = inter / union if union else 0.0
                    if norm_syn in norm_gl or norm_gl in norm_syn:
                        score = max(score, 0.85)
                    if score > best_score and score >= 0.5:
                        best_score = score
                        best_idx = gi

            col_map[canonical] = best_idx
            if best_idx is not None:
                used_indices.add(best_idx)

        return col_map

    def _fallback_extract(self, grid: GridTable) -> tuple[list[str], list[dict]]:
        """Extracción genérica cuando el schema no matchea."""
        cols = grid.column_labels
        rows = []
        for r in range(1, grid.n_rows):
            texts = grid.row_texts(r)
            if any(t.strip() for t in texts):
                rows.append({cols[i]: texts[i] for i in range(len(cols))})
        return cols, rows

    def _postprocess_row(self, row: dict) -> dict:
        """Hook para limpieza específica de banco. Overrideable."""
        return row

    def _filter_rows(self, rows: list[dict]) -> list[dict]:
        """Elimina filas totalmente vacías y filas de totales/resumen."""
        _TOTAL_KEYWORDS = {"TOTAL", "SUBTOTAL", "SUMA", "SALDO FINAL", "GRAN TOTAL"}
        result = []
        for row in rows:
            values = [v.strip() for v in row.values()]
            if not any(values):
                continue
            # Filtrar filas de totales
            first_val = _norm(values[0]) if values else ""
            if any(kw in first_val for kw in _TOTAL_KEYWORDS):
                continue
            result.append(row)
        return result


# ─── Santander ────────────────────────────────────────────────────────────────

class SantanderExtractor(BankExtractorBase):
    """
    Estado de cuenta / dispersión Santander.

    Columnas típicas en PDFs Santander:
      FECHA | DESCRIPCION | REFERENCIA | CARGO | ABONO | SALDO
    """
    BANK_NAME = "SANTANDER"
    SCHEMA = [
        ("fecha",       ["FECHA", "DATE", "FEC", "DIA"]),
        ("descripcion", ["DESCRIPCION", "CONCEPTO", "DETALLE", "MOVIMIENTO", "DESC"]),
        ("referencia",  ["REFERENCIA", "REF", "FOLIO", "NUM OPERACION", "NUMERO"]),
        ("cargo",       ["CARGO", "CARGOS", "DEBITO", "RETIRO", "RETIROS", "DEBITOS"]),
        ("abono",       ["ABONO", "ABONOS", "CREDITO", "DEPOSITO", "DEPOSITOS", "CREDITOS"]),
        ("saldo",       ["SALDO", "SALDO ACTUAL", "BALANCE"]),
    ]

    def _postprocess_row(self, row: dict) -> dict:
        # Normalizar montos: quitar comas de miles, unificar puntos decimales
        for key in ("cargo", "abono", "saldo"):
            val = row.get(key, "")
            if val:
                # Quitar espacios, reemplazar coma-miles
                val = re.sub(r"\s", "", val)
                val = re.sub(r"(\d),(\d{3})", r"\1\2", val)
                val = val.replace(",", ".")
                row[key] = val
        return row


# ─── BBVA ─────────────────────────────────────────────────────────────────────

class BBVAExtractor(BankExtractorBase):
    """
    Estado de cuenta / dispersión BBVA Bancomer.

    Columnas típicas:
      FECHA | CONCEPTO | NUM REFERENCIA | RETIROS | DEPOSITOS | SALDO
    También en tablas de beneficiarios:
      NO CUENTA | NOMBRE | CLABE | IMPORTE | ESTATUS
    """
    BANK_NAME = "BBVA"
    SCHEMA = [
        ("fecha",       ["FECHA", "DATE", "DIA"]),
        ("concepto",    ["CONCEPTO", "DESCRIPCION", "DETALLE", "MOVIMIENTO"]),
        ("referencia",  ["NUM REFERENCIA", "REFERENCIA", "REF", "FOLIO", "NUM OPERACION"]),
        ("cargo",       ["RETIROS", "CARGO", "CARGOS", "DEBITO"]),
        ("abono",       ["DEPOSITOS", "ABONO", "ABONOS", "CREDITO", "DEPOSITO"]),
        ("saldo",       ["SALDO", "SALDO FINAL", "BALANCE"]),
    ]

    def _postprocess_row(self, row: dict) -> dict:
        for key in ("cargo", "abono", "saldo"):
            val = row.get(key, "")
            if val:
                val = re.sub(r"\s", "", val)
                val = re.sub(r"(\d),(\d{3})", r"\1\2", val)
                val = val.replace(",", ".")
                row[key] = val
        return row


# ─── Banamex / Citibanamex ────────────────────────────────────────────────────

class BanamexExtractor(BankExtractorBase):
    """
    Estado de cuenta Citibanamex / Banamex.

    Columnas típicas:
      FECHA | DESCRIPCION | NUMERO DE REFERENCIA | CARGOS | ABONOS | SALDO
    """
    BANK_NAME = "BANAMEX"
    SCHEMA = [
        ("fecha",       ["FECHA", "DATE"]),
        ("descripcion", ["DESCRIPCION", "CONCEPTO", "DETALLE"]),
        ("referencia",  ["NUMERO DE REFERENCIA", "REFERENCIA", "NUM REF", "FOLIO"]),
        ("cargo",       ["CARGOS", "CARGO", "DEBITO", "RETIROS"]),
        ("abono",       ["ABONOS", "ABONO", "CREDITO", "DEPOSITOS"]),
        ("saldo",       ["SALDO", "SALDO FINAL", "BALANCE"]),
    ]

    def _postprocess_row(self, row: dict) -> dict:
        for key in ("cargo", "abono", "saldo"):
            val = row.get(key, "")
            if val:
                val = re.sub(r"\s", "", val)
                val = re.sub(r"(\d),(\d{3})", r"\1\2", val)
                val = val.replace(",", ".")
                row[key] = val
        return row


# ─── Banorte ──────────────────────────────────────────────────────────────────

class BanorteExtractor(BankExtractorBase):
    """
    Estado de cuenta Banorte / IXE.

    Columnas típicas:
      FECHA | DESCRIPCION | REFERENCIA | CARGO | ABONO | SALDO
    """
    BANK_NAME = "BANORTE"
    SCHEMA = [
        ("fecha",       ["FECHA", "DATE", "DIA"]),
        ("descripcion", ["DESCRIPCION", "CONCEPTO", "DETALLE", "MOVIMIENTO"]),
        ("referencia",  ["REFERENCIA", "REF", "FOLIO", "NUM OPERACION"]),
        ("cargo",       ["CARGO", "CARGOS", "DEBITO", "RETIRO"]),
        ("abono",       ["ABONO", "ABONOS", "CREDITO", "DEPOSITO"]),
        ("saldo",       ["SALDO", "SALDO ACTUAL", "BALANCE"]),
    ]

    def _postprocess_row(self, row: dict) -> dict:
        for key in ("cargo", "abono", "saldo"):
            val = row.get(key, "")
            if val:
                val = re.sub(r"\s", "", val)
                val = re.sub(r"(\d),(\d{3})", r"\1\2", val)
                val = val.replace(",", ".")
                row[key] = val
        return row


# ─── HSBC ─────────────────────────────────────────────────────────────────────

class HSBCExtractor(BankExtractorBase):
    """
    Estado de cuenta HSBC México.

    Columnas típicas:
      FECHA | DESCRIPCION | CARGO | ABONO | SALDO
    """
    BANK_NAME = "HSBC"
    SCHEMA = [
        ("fecha",       ["FECHA", "DATE"]),
        ("descripcion", ["DESCRIPCION", "CONCEPTO", "DETALLE"]),
        ("referencia",  ["REFERENCIA", "REF", "FOLIO"]),
        ("cargo",       ["CARGO", "CARGOS", "DEBITO", "RETIRO"]),
        ("abono",       ["ABONO", "ABONOS", "CREDITO", "DEPOSITO"]),
        ("saldo",       ["SALDO", "BALANCE"]),
    ]

    def _postprocess_row(self, row: dict) -> dict:
        for key in ("cargo", "abono", "saldo"):
            val = row.get(key, "")
            if val:
                val = re.sub(r"\s", "", val)
                val = re.sub(r"(\d),(\d{3})", r"\1\2", val)
                val = val.replace(",", ".")
                row[key] = val
        return row


# ─── Scotiabank ───────────────────────────────────────────────────────────────

class ScotiabankExtractor(BankExtractorBase):
    """
    Estado de cuenta Scotiabank México.

    Columnas típicas:
      FECHA | DESCRIPCION | REFERENCIA | CARGO | ABONO | SALDO
    """
    BANK_NAME = "SCOTIABANK"
    SCHEMA = [
        ("fecha",       ["FECHA", "DATE"]),
        ("descripcion", ["DESCRIPCION", "CONCEPTO", "DETALLE"]),
        ("referencia",  ["REFERENCIA", "REF", "FOLIO"]),
        ("cargo",       ["CARGO", "CARGOS", "DEBITO", "RETIRO"]),
        ("abono",       ["ABONO", "ABONOS", "CREDITO", "DEPOSITO"]),
        ("saldo",       ["SALDO", "BALANCE"]),
    ]

    def _postprocess_row(self, row: dict) -> dict:
        for key in ("cargo", "abono", "saldo"):
            val = row.get(key, "")
            if val:
                val = re.sub(r"\s", "", val)
                val = re.sub(r"(\d),(\d{3})", r"\1\2", val)
                val = val.replace(",", ".")
                row[key] = val
        return row


# ─── Inbursa ──────────────────────────────────────────────────────────────────

class InbursaExtractor(BankExtractorBase):
    """
    Estado de cuenta Inbursa / GFInbursa.
    """
    BANK_NAME = "INBURSA"
    SCHEMA = [
        ("fecha",       ["FECHA", "DATE"]),
        ("descripcion", ["DESCRIPCION", "CONCEPTO", "DETALLE"]),
        ("referencia",  ["REFERENCIA", "REF", "FOLIO"]),
        ("cargo",       ["CARGO", "CARGOS", "DEBITO"]),
        ("abono",       ["ABONO", "ABONOS", "CREDITO", "DEPOSITO"]),
        ("saldo",       ["SALDO", "BALANCE"]),
    ]


# ─── Extractor genérico (fallback) ────────────────────────────────────────────

class GenericBankExtractor(BankExtractorBase):
    """
    Fallback: no conoce el banco, usa las columnas que haya detectado el grid.
    Intenta al menos normalizar montos en columnas que parezcan numéricas.
    """
    BANK_NAME = "GENERICO"
    SCHEMA = []  # vacío: usa _fallback_extract directamente

    _AMOUNT_COL_HINTS = frozenset({
        "CARGO", "ABONO", "SALDO", "IMPORTE", "MONTO",
        "DEPOSITO", "RETIRO", "CREDITO", "DEBITO",
    })

    def extract(self, grid: GridTable) -> tuple[list[str], list[dict]]:
        cols, rows = self._fallback_extract(grid)
        rows = [self._normalize_amounts(row, cols) for row in rows]
        rows = self._filter_rows(rows)
        return cols, rows

    def _normalize_amounts(self, row: dict, cols: list[str]) -> dict:
        for col in cols:
            if any(hint in _norm(col) for hint in self._AMOUNT_COL_HINTS):
                val = row.get(col, "")
                if val:
                    val = re.sub(r"\s", "", val)
                    val = re.sub(r"(\d),(\d{3})", r"\1\2", val)
                    val = val.replace(",", ".")
                    row[col] = val
        return row


# ─── Router ───────────────────────────────────────────────────────────────────

_EXTRACTOR_MAP: dict[str, type[BankExtractorBase]] = {
    "SANTANDER": SantanderExtractor,
    "BBVA": BBVAExtractor,
    "BANCOMER": BBVAExtractor,
    "BBVA BANCOMER": BBVAExtractor,
    "BANAMEX": BanamexExtractor,
    "CITIBANAMEX": BanamexExtractor,
    "CITI": BanamexExtractor,
    "BANORTE": BanorteExtractor,
    "IXE": BanorteExtractor,
    "HSBC": HSBCExtractor,
    "SCOTIABANK": ScotiabankExtractor,
    "INBURSA": InbursaExtractor,
    "GFINBURSA": InbursaExtractor,
}


def get_bank_extractor(bank_name: str | None) -> BankExtractorBase:
    """
    Devuelve el extractor especializado para el banco dado.
    Si el banco no se reconoce o es None, devuelve GenericBankExtractor.

    El matching es fuzzy: "BBVA BANCOMER MEXICO" → BBVAExtractor.
    """
    if not bank_name:
        return GenericBankExtractor()

    norm_bank = _norm(bank_name)

    # Match exacto primero
    for key, cls in _EXTRACTOR_MAP.items():
        if _norm(key) == norm_bank:
            logger.info("[BANK_EXTRACTOR] banco='%s' → %s (exacto)", bank_name, cls.__name__)
            return cls()

    # Match por contenido
    for key, cls in _EXTRACTOR_MAP.items():
        if _norm(key) in norm_bank or norm_bank in _norm(key):
            logger.info("[BANK_EXTRACTOR] banco='%s' → %s (parcial)", bank_name, cls.__name__)
            return cls()

    logger.info("[BANK_EXTRACTOR] banco='%s' no reconocido → GenericBankExtractor", bank_name)
    return GenericBankExtractor()
