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
    ├── ScotiabankExtractor  ← FECHA / DESCRIPCION / CARGO / ABONO / SALDO
    ├── InbursaExtractor     ← FECHA / DESCRIPCION / CARGO / ABONO / SALDO
    ├── AztecaExtractor      ← FECHA / CONCEPTO / DEPOSITO / RETIRO / SALDO
    ├── AfirmeExtractor      ← FECHA / DESCRIPCION / CARGO / ABONO / SALDO
    ├── BanBajioExtractor    ← FECHA / DESCRIPCION / CARGO / ABONO / SALDO
    ├── MultivaBankExtractor ← FECHA / DESCRIPCION / CARGO / ABONO / SALDO
    ├── InvexExtractor       ← FECHA / DESCRIPCION / CARGO / ABONO / SALDO
    ├── NominaExtractor      ← CLAVE / CONCEPTO / IMP GRAVADO / IMP EXENTO / IMPORTE
    ├── CFDIExtractor        ← CANTIDAD / UNIDAD / DESCRIPCION / V.UNITARIO / IMPORTE
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
    """Normaliza texto: mayúsculas, sin acentos, sin caracteres especiales.

    Reemplaza '/' y '-' por espacio antes de quitar puntuación para evitar
    que tokens como "FECHA/HORA" se fusionen en "FECHAHORA".
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text.upper())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # Separadores comunes que deben dividir tokens, no fusionarlos
    text = re.sub(r"[/\-]", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_amount(val: str) -> str:
    """Normaliza un monto monetario a string numérico limpio.

    Maneja correctamente montos > 999,999:
      "1,234,567.89" → "1234567.89"
      "$ 1,234.50"   → "1234.50"
      "1.234.567,89" → "1234567.89"  (formato europeo)
      "-1,234.56"    → "-1234.56"
    """
    if not val:
        return val
    val = re.sub(r"\s", "", val)
    # Quitar símbolo de moneda y signo negativo (lo conservamos aparte)
    negative = val.startswith("-")
    val = re.sub(r"^[-$€£¥MXN]+", "", val).strip()
    # Detectar formato europeo: puntos de miles y coma decimal ("1.234,56")
    if re.search(r"\d\.\d{3},\d{1,2}$", val):
        val = val.replace(".", "").replace(",", ".")
    else:
        # Formato MX/US: comas como separador de miles
        # Usa lookahead para sólo remover comas seguidas de exactamente 3 dígitos
        val = re.sub(r",(?=\d{3}(?:[,.]|$))", "", val)
    return f"-{val}" if negative else val


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

    # Columnas que contienen montos monetarios y deben normalizarse.
    # Las subclases pueden sobreescribir esto.
    _MONEY_KEYS: tuple[str, ...] = ("cargo", "abono", "saldo")

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
            logger.warning(
                "[%s] no se mapeó ninguna columna del schema — grid_cols=%s, schema_keys=%s",
                self.BANK_NAME,
                grid.column_labels[:10],
                [k for k, _ in self.SCHEMA],
            )
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
        # Normalizar a minúsculas para garantizar consistencia entre cols y row keys.
        # C# aplica DictionaryKeyPolicy=SnakeCaseLower a los keys al serializar; si los
        # columns son uppercase ("FECHA") pero los keys quedan lowercase ("fecha") el
        # template Angular row[col] falla. Ambos deben ser la misma cadena.
        cols = [c.lower() for c in grid.column_labels]
        rows = []
        for r in range(1, grid.n_rows):
            texts = grid.row_texts(r)
            if any(t.strip() for t in texts):
                rows.append({cols[i]: texts[i] for i in range(len(cols))})
        return cols, rows

    def _postprocess_row(self, row: dict) -> dict:
        """Normaliza montos en las columnas declaradas en _MONEY_KEYS."""
        for key in self._MONEY_KEYS:
            val = row.get(key, "")
            if val:
                row[key] = _normalize_amount(val)
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
    # Hereda _postprocess_row de BankExtractorBase (normaliza cargo/abono/saldo)


# ─── Azteca ───────────────────────────────────────────────────────────────────

class AztecaExtractor(BankExtractorBase):
    """
    Estado de cuenta Banco Azteca.

    Columnas típicas:
      FECHA | CONCEPTO | DEPOSITO | RETIRO | SALDO
    Nota: Azteca invierte el orden DEPOSITO/RETIRO vs el estándar CARGO/ABONO.
    """
    BANK_NAME = "AZTECA"
    SCHEMA = [
        ("fecha",       ["FECHA", "DATE", "DIA"]),
        ("descripcion", ["CONCEPTO", "DESCRIPCION", "DETALLE", "MOVIMIENTO"]),
        ("referencia",  ["REFERENCIA", "REF", "FOLIO", "NUM OPERACION"]),
        ("abono",       ["DEPOSITO", "DEPOSITOS", "ABONO", "ABONOS", "CREDITO"]),
        ("cargo",       ["RETIRO", "RETIROS", "CARGO", "CARGOS", "DEBITO"]),
        ("saldo",       ["SALDO", "SALDO ACTUAL", "BALANCE"]),
    ]


# ─── Afirme ───────────────────────────────────────────────────────────────────

class AfirmeExtractor(BankExtractorBase):
    """
    Estado de cuenta Banco Afirme.

    Columnas típicas:
      FECHA | DESCRIPCION | REFERENCIA | CARGO | ABONO | SALDO
    """
    BANK_NAME = "AFIRME"
    SCHEMA = [
        ("fecha",       ["FECHA", "DATE", "FEC"]),
        ("descripcion", ["DESCRIPCION", "CONCEPTO", "DETALLE", "MOVIMIENTO"]),
        ("referencia",  ["REFERENCIA", "REF", "FOLIO", "NUM OPERACION", "NO OPER"]),
        ("cargo",       ["CARGO", "CARGOS", "DEBITO", "RETIRO"]),
        ("abono",       ["ABONO", "ABONOS", "CREDITO", "DEPOSITO"]),
        ("saldo",       ["SALDO", "SALDO ACTUAL", "BALANCE"]),
    ]


# ─── BanBajío ─────────────────────────────────────────────────────────────────

class BanBajioExtractor(BankExtractorBase):
    """
    Estado de cuenta Banco del Bajío (BanBajío).

    Columnas típicas:
      FECHA | DESCRIPCION | REFERENCIA | CARGO | ABONO | SALDO
    """
    BANK_NAME = "BANBAJIO"
    SCHEMA = [
        ("fecha",       ["FECHA", "DATE", "DIA"]),
        ("descripcion", ["DESCRIPCION", "CONCEPTO", "DETALLE", "MOVIMIENTO"]),
        ("referencia",  ["REFERENCIA", "REF", "FOLIO", "NUM OPERACION"]),
        ("cargo",       ["CARGO", "CARGOS", "DEBITO", "RETIRO"]),
        ("abono",       ["ABONO", "ABONOS", "CREDITO", "DEPOSITO"]),
        ("saldo",       ["SALDO", "SALDO FINAL", "BALANCE"]),
    ]


# ─── Multiva ──────────────────────────────────────────────────────────────────

class MultivaBankExtractor(BankExtractorBase):
    """
    Estado de cuenta Multiva / Grupo Financiero Multiva.

    Columnas típicas:
      FECHA | DESCRIPCION | REFERENCIA | CARGO | ABONO | SALDO
    """
    BANK_NAME = "MULTIVA"
    SCHEMA = [
        ("fecha",       ["FECHA", "DATE"]),
        ("descripcion", ["DESCRIPCION", "CONCEPTO", "DETALLE", "MOVIMIENTO"]),
        ("referencia",  ["REFERENCIA", "REF", "FOLIO", "OPERACION"]),
        ("cargo",       ["CARGO", "CARGOS", "DEBITO", "RETIRO"]),
        ("abono",       ["ABONO", "ABONOS", "CREDITO", "DEPOSITO"]),
        ("saldo",       ["SALDO", "BALANCE"]),
    ]


# ─── Invex ────────────────────────────────────────────────────────────────────

class InvexExtractor(BankExtractorBase):
    """
    Estado de cuenta Invex Banco.

    Columnas típicas:
      FECHA | CONCEPTO | REFERENCIA | CARGO | ABONO | SALDO
    """
    BANK_NAME = "INVEX"
    SCHEMA = [
        ("fecha",       ["FECHA", "DATE"]),
        ("descripcion", ["CONCEPTO", "DESCRIPCION", "DETALLE"]),
        ("referencia",  ["REFERENCIA", "REF", "FOLIO", "NUM CHEQUE"]),
        ("cargo",       ["CARGO", "CARGOS", "DEBITO", "RETIRO"]),
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
                    row[col] = _normalize_amount(val)
        return row


# ─── Nómina ───────────────────────────────────────────────────────────────────

class NominaExtractor(BankExtractorBase):
    """
    Extractor especializado para recibos de nómina mexicanos.

    Los PDFs de nómina tienen dos secciones típicas:
      PERCEPCIONES: CLAVE | CONCEPTO | IMPORTE GRAVADO | IMPORTE EXENTO | IMPORTE
      DEDUCCIONES:  CLAVE | CONCEPTO | IMPORTE

    El detector geométrico unifica ambas secciones en una grilla.
    Este extractor mapea las columnas correctamente y normaliza importes.
    """
    BANK_NAME = "NOMINA"
    SCHEMA = [
        ("clave",           ["CLAVE", "CVE", "NUM", "NUMERO", "NO", "ID"]),
        ("concepto",        ["CONCEPTO", "DESCRIPCION", "DETALLE", "PERCEPCION",
                             "DEDUCCION", "PERCEPCIONES", "DEDUCCIONES", "MOTIVO"]),
        ("importe_gravado", ["IMPORTE GRAVADO", "IMP GRAVADO", "GRAVADO", "GRAVABLE"]),
        ("importe_exento",  ["IMPORTE EXENTO", "IMP EXENTO", "EXENTO"]),
        ("importe",         ["IMPORTE", "MONTO", "CANTIDAD", "TOTAL", "IMPORTE TOTAL"]),
    ]

    _MONEY_KEYS = ("importe_gravado", "importe_exento", "importe")

    def _filter_rows(self, rows: list[dict]) -> list[dict]:
        """En nómina excluimos filas de totales pero mantenemos conceptos clave."""
        _TOTAL_KEYWORDS = {"TOTAL", "SUBTOTAL", "NETO", "GRAN TOTAL"}
        result = []
        for row in rows:
            values = [v.strip() for v in row.values()]
            if not any(values):
                continue
            concepto = _norm(row.get("concepto", ""))
            # Mantener filas de total de percepciones/deducciones como referencia
            if any(kw in concepto for kw in {"TOTAL PERCEPCIONES", "TOTAL DEDUCCIONES", "NETO A PAGAR"}):
                result.append(row)
                continue
            # Descartar filas de totales genéricos sin concepto específico
            first_val = _norm(values[0]) if values else ""
            if any(kw == first_val for kw in _TOTAL_KEYWORDS):
                continue
            result.append(row)
        return result


# ─── CFDI / Factura ───────────────────────────────────────────────────────────

class CFDIExtractor(BankExtractorBase):
    """
    Extractor especializado para facturas CFDI mexicanas (SAT).

    Tabla de conceptos típica:
      CANTIDAD | UNIDAD | CLAVE PROD/SERV | NO IDENTIFICACION |
      DESCRIPCION | VALOR UNITARIO | DESCUENTO | IMPORTE

    También maneja facturas simplificadas (sin clave SAT):
      CANT | DESCRIPCION | PRECIO UNIT | IMPORTE
    """
    BANK_NAME = "CFDI"
    SCHEMA = [
        ("cantidad",        ["CANTIDAD", "CANT", "UNIDADES", "PZA", "PIEZAS", "QTY"]),
        ("clave_unidad",    ["CLAVE UNIDAD", "UNIDAD", "UM", "U/M", "UNID"]),
        ("clave_prod_serv", ["CLAVE PROD SERV", "CLAVEPRODSERV", "CLAVE SAT",
                             "CLAVE PRODUCTO", "CLAVE"]),
        ("no_identificacion",["NO IDENTIFICACION", "NO IDENT", "NO PARTE",
                              "CODIGO", "SKU", "CLAVE INTERNA"]),
        ("descripcion",     ["DESCRIPCION", "CONCEPTO", "DETALLE", "PRODUCTO",
                             "SERVICIO", "BIEN O SERVICIO"]),
        ("valor_unitario",  ["VALOR UNITARIO", "PRECIO UNITARIO", "PRECIO UNIT",
                             "P UNITARIO", "PRECIO", "P.U.", "V.U."]),
        ("descuento",       ["DESCUENTO", "DESC", "DSCTO"]),
        ("importe",         ["IMPORTE", "TOTAL", "MONTO", "SUBTOTAL", "IMPORTE TOTAL"]),
    ]

    _MONEY_KEYS = ("valor_unitario", "descuento", "importe")

    def _filter_rows(self, rows: list[dict]) -> list[dict]:
        """En CFDI eliminamos filas de subtotal/IVA/total que no son conceptos."""
        _SUMMARY_KEYWORDS = {"SUBTOTAL", "IVA", "TOTAL", "DESCUENTO TOTAL", "ISR"}
        result = []
        for row in rows:
            values = [v.strip() for v in row.values()]
            if not any(values):
                continue
            desc = _norm(row.get("descripcion", ""))
            # Filas de resumen fiscal → descartar
            if any(kw == desc for kw in _SUMMARY_KEYWORDS):
                continue
            result.append(row)
        return result


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
    # Bancos adicionales
    "AZTECA": AztecaExtractor,
    "BANCO AZTECA": AztecaExtractor,
    "AFIRME": AfirmeExtractor,
    "BANCO AFIRME": AfirmeExtractor,
    "BANBAJIO": BanBajioExtractor,
    "BANCO DEL BAJIO": BanBajioExtractor,
    "BAJIO": BanBajioExtractor,
    "MULTIVA": MultivaBankExtractor,
    "GRUPO FINANCIERO MULTIVA": MultivaBankExtractor,
    "INVEX": InvexExtractor,
    "BANCO INVEX": InvexExtractor,
}

# Mapa por tipo de documento (independiente del banco)
_DOC_TYPE_EXTRACTOR_MAP: dict[str, type[BankExtractorBase]] = {
    "NOMINA":   NominaExtractor,
    "CFDI":     CFDIExtractor,
    "FACTURA":  CFDIExtractor,
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


def get_doc_extractor(doc_type: str, bank_name: str | None = None) -> BankExtractorBase:
    """
    Router principal — devuelve el extractor correcto según tipo de documento y banco.

    Prioridad:
      1. Si el doc_type tiene extractor propio (NOMINA, CFDI, FACTURA) → úsalo
      2. Si es doc bancario → enrutar por banco (get_bank_extractor)
      3. Fallback → GenericBankExtractor

    Ejemplos:
      get_doc_extractor("NOMINA")              → NominaExtractor
      get_doc_extractor("CFDI")                → CFDIExtractor
      get_doc_extractor("FACTURA")             → CFDIExtractor
      get_doc_extractor("DATOS_BANCARIOS", "SANTANDER") → SantanderExtractor
      get_doc_extractor("ESTADO_DE_CUENTA", "BBVA")     → BBVAExtractor
      get_doc_extractor("DATOS_BANCARIOS", None)        → GenericBankExtractor
    """
    norm_type = (doc_type or "").upper().strip()

    # 1. Extractor por tipo de documento
    if norm_type in _DOC_TYPE_EXTRACTOR_MAP:
        cls = _DOC_TYPE_EXTRACTOR_MAP[norm_type]
        logger.info("[DOC_EXTRACTOR] doc_type='%s' → %s", doc_type, cls.__name__)
        return cls()

    # 2. Extractor por banco para documentos bancarios
    bank_doc_types = {"DATOS_BANCARIOS", "COMPROBANTE_DE_PAGO", "ESTADO_DE_CUENTA"}
    if norm_type in bank_doc_types:
        return get_bank_extractor(bank_name)

    # 3. Fallback genérico
    logger.info("[DOC_EXTRACTOR] doc_type='%s' sin extractor especializado → GenericBankExtractor", doc_type)
    return GenericBankExtractor()
