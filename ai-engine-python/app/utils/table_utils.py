"""
Utilidades de tablas — fuente única de verdad para operaciones comunes.

Resuelve los problemas más frecuentes de tablas grandes mal extraídas:
  - filas y celdas vacías / basura
  - columnas duplicadas o desalineadas
  - encabezados no detectados
  - importes con formato inconsistente
  - conversión a canonical_rows (dict normalizado por columna)

Uso típico
----------
from app.utils.table_utils import (
    drop_empty_rows,
    unify_columns,
    detect_header_row,
    normalize_amount,
    to_canonical_rows,
)
"""

from __future__ import annotations

import re
import unicodedata
import logging
from typing import Any, cast

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Tokens que identifican columnas de tablas de pago mexicanas
# ──────────────────────────────────────────────────────────────────────────────

_HEADER_TOKENS: frozenset[str] = frozenset({
    "CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE", "APELLIDO",
    "ESTATUS", "CONCEPTO", "BENEFICIARIO", "CLAVE RASTREO",
    "EMPLEADO", "DESCRIPCION", "CLABE", "RFC", "NSS", "CURP",
    "NUMERO", "MONTO", "CANTIDAD", "CARGO", "ABONO", "SALDO",
    "FECHA", "BANCO", "FOLIO", "SECUENCIA", "LOTE", "SERIE",
    "PERIODO", "EMPRESA", "CONTRATO",
})

# Palabras que indican que una fila es de totales/resumen, no un dato
_SUMMARY_ROW_TOKENS: frozenset[str] = frozenset({
    "TOTAL", "SUBTOTAL", "SUMA", "GRAN TOTAL", "TOTAL GENERAL",
    "IMPORTE TOTAL", "TOTAL MOVIMIENTOS",
})

# Tokens de estatus válidos
_VALID_STATUSES: frozenset[str] = frozenset({
    "APLICADO", "ACEPTADO", "PROCESADO", "TRANSMITIDO",
    "RECHAZADO", "EN PROCESO", "DEVUELTO", "CANCELADO", "LIQUIDADO",
})

# Mapa de prefijos de estatus abreviados
_STATUS_PREFIX_MAP: dict[str, str] = {
    "APLIC": "APLICADO", "ACEPT": "ACEPTADO", "PROCE": "PROCESADO",
    "TRANS": "TRANSMITIDO", "RECHA": "RECHAZADO", "DEVUE": "DEVUELTO",
    "CANCE": "CANCELADO", "LIQUI": "LIQUIDADO",
}

# Sinónimos de columnas → nombre canónico
_COLUMN_ALIASES: dict[str, str] = {
    # cuenta/CLABE
    "CUENTA CLABE": "clabe", "CUENTA BENEFICIARIO": "cuenta",
    "CUENTA DE RETIRO": "clabe", "CUENTA DEPOSITO": "cuenta",
    "NUM CUENTA": "cuenta", "NUMERO CUENTA": "cuenta",
    "NO CUENTA": "cuenta", "CONTRATO": "cuenta",
    # importes
    "IMPORTE": "importe", "MONTO": "importe", "CANTIDAD": "importe",
    "CARGO": "importe", "ABONO": "importe",
    # nombres
    "NOMBRE": "nombre", "BENEFICIARIO": "nombre_beneficiario",
    "NOMBRE BENEFICIARIO": "nombre_beneficiario",
    "APELLIDO PATERNO": "apellido_paterno",
    "APELLIDO MATERNO": "apellido_materno",
    "APELLIDOS": "apellido_paterno",
    # referencias
    "REFERENCIA": "referencia", "CLAVE RASTREO": "clave_rastreo",
    "FOLIO": "folio", "FOLIO INTERNET": "folio_internet",
    "NUM EMPLEADO": "numero_empleado", "NO EMPLEADO": "numero_empleado",
    # estatus
    "ESTATUS": "estatus", "STATUS": "estatus", "ESTADO": "estatus",
    # concepto
    "CONCEPTO": "concepto_pago", "DESCRIPCION": "concepto_pago",
    # banco
    "BANCO": "banco", "INSTITUCION": "banco",
    # rfc/curp/nss
    "RFC": "rfc", "CURP": "curp", "NSS": "nss",
}


# ──────────────────────────────────────────────────────────────────────────────
# 1. LIMPIEZA DE TEXTO
# ──────────────────────────────────────────────────────────────────────────────

def normalize_cell(text: Any, upper: bool = False) -> str:
    """
    Limpia una celda individual: unicode NFC, colapsa espacios, trunca a 400 chars.

    Parameters
    ----------
    text   : valor de celda (cualquier tipo).
    upper  : True para devolver en mayúsculas.
    """
    if text is None:
        return ""
    s = unicodedata.normalize("NFC", str(text))
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > 400:
        s = s[:400].rstrip()
    return s.upper() if upper else s


def is_garbage_cell(value: Any) -> bool:
    """
    Detecta celdas basura: caracteres de control, base64, ruido puro.

    Returns True si la celda debe descartarse.
    """
    text = str(value or "").strip()
    if not text:
        return False
    # Caracteres de control
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", text):
        return True
    # Cadena larga sin espacios que parece base64/binario
    if len(text) > 30 and not re.search(r"\s", text) and re.fullmatch(r"[A-Za-z0-9+/=_\-]{30,}", text):
        return True
    # Más del 65% de caracteres no alfanuméricos
    alpha = sum(1 for c in text if c.isalnum() or c.isspace())
    if len(text) >= 4 and alpha / len(text) < 0.35:
        return True
    # Carácter repetido (ej. "||||||||", "========")
    stripped = text.replace(" ", "")
    if len(stripped) >= 4 and len(set(stripped)) <= 1:
        return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# 2. LIMPIEZA DE FILAS
# ──────────────────────────────────────────────────────────────────────────────

def drop_empty_rows(
    rows: list[Any],
    min_filled: int = 1,
) -> list[Any]:
    """
    Elimina filas vacías o con solo celdas basura.

    Parameters
    ----------
    rows       : lista de listas (raw) o lista de dicts (canonical).
    min_filled : mínimo de celdas no vacías para conservar la fila.

    Returns el mismo tipo que recibe.
    """
    result: list[Any] = []
    for row in rows:
        cells = row.values() if isinstance(row, dict) else row
        filled = sum(
            1 for c in cells
            if str(c or "").strip() and not is_garbage_cell(c)
        )
        if filled >= min_filled:
            result.append(row)
    dropped = len(rows) - len(result)
    if dropped:
        logger.debug("drop_empty_rows: eliminadas %d filas vacías/basura", dropped)
    return result


def drop_summary_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """
    Elimina filas de totales/resumen (TOTAL, SUBTOTAL, SUMA, etc.)
    basándose en la primera celda no vacía de cada fila.
    """
    result = []
    for row in rows:
        first_val = next((str(v).upper().strip() for v in row.values() if str(v or "").strip()), "")
        is_summary = any(tok in first_val for tok in _SUMMARY_ROW_TOKENS)
        if not is_summary:
            result.append(row)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# 3. DETECCIÓN DE ENCABEZADOS
# ──────────────────────────────────────────────────────────────────────────────

def _row_header_score(row: list[str] | dict[str, str]) -> int:
    """Calcula cuántos tokens de encabezado conocidos contiene una fila."""
    cells = list(row.values()) if isinstance(row, dict) else row
    score = 0
    for cell in cells:
        token = str(cell or "").upper().strip()
        if token in _HEADER_TOKENS:
            score += 2
        elif any(tok in token for tok in _HEADER_TOKENS):
            score += 1
    return score


def detect_header_row(rows: list[list[str]]) -> int:
    """
    Detecta el índice de la fila de encabezados en una tabla raw (lista de listas).

    Busca entre las primeras 5 filas la que tenga más tokens conocidos como
    CUENTA, NOMBRE, IMPORTE, REFERENCIA, etc.

    Returns
    -------
    int
        Índice de la fila de encabezados (0-based). -1 si no se detecta ninguna.
    """
    best_idx = -1
    best_score = 0
    for i, row in enumerate(rows[:5]):
        score = _row_header_score(row)
        if score > best_score:
            best_score = score
            best_idx = i
    if best_score == 0:
        return -1
    logger.debug("detect_header_row: encabezado en fila %d (score=%d)", best_idx, best_score)
    return best_idx


# ──────────────────────────────────────────────────────────────────────────────
# 4. UNIFICACIÓN DE COLUMNAS
# ──────────────────────────────────────────────────────────────────────────────

def canonicalize_column_name(raw: str) -> str:
    """
    Convierte un encabezado de columna raw a su nombre canónico en snake_case.

    Ejemplos:
        "CUENTA CLABE"  ->  "clabe"
        "Nombre"        ->  "nombre"
        "N° empleado"   ->  "numero_empleado"
    """
    normalized = re.sub(r"\s+", " ", str(raw or "").upper().strip())
    normalized = re.sub(r"[^\w\s]", "", normalized)
    normalized = re.sub(r"\bN[UÚO°]?[MR]?[EOO]?\b\.?\s*", "NUMERO ", normalized).strip()

    # Búsqueda directa en alias
    if normalized in _COLUMN_ALIASES:
        return _COLUMN_ALIASES[normalized]

    # Búsqueda parcial (el token más largo que coincida)
    best_match = ""
    for alias_key, canon in _COLUMN_ALIASES.items():
        if alias_key in normalized and len(alias_key) > len(best_match):
            best_match = alias_key

    if best_match:
        return _COLUMN_ALIASES[best_match]

    # Fallback: snake_case del texto normalizado
    return normalized.lower().replace(" ", "_")


def unify_columns(
    headers: list[str],
    rows: list[list[str]],
) -> tuple[list[str], list[dict[str, str]]]:
    """
    Normaliza los encabezados y convierte filas raw (list[str]) a
    list[dict[str, str]] con nombres canónicos.

    Duplicados de columna se sufijan con _2, _3, etc.
    Columnas sin encabezado reciben el nombre 'col_N'.

    Parameters
    ----------
    headers : primera fila del CSV/tabla como lista de strings.
    rows    : filas de datos (sin la fila de encabezados).

    Returns
    -------
    (canonical_columns, canonical_rows)
    """
    # Construir columnas canónicas, resolviendo duplicados
    canonical_cols: list[str] = []
    seen: dict[str, int] = {}
    for i, h in enumerate(headers):
        col = canonicalize_column_name(h) if str(h or "").strip() else f"col_{i}"
        if col in seen:
            seen[col] += 1
            col = f"{col}_{seen[col]}"
        else:
            seen[col] = 1
        canonical_cols.append(col)

    # Convertir filas a dicts
    canonical_rows: list[dict[str, str]] = []
    for row in rows:
        d: dict[str, str] = {}
        for j, col in enumerate(canonical_cols):
            raw_val = row[j] if j < len(row) else ""
            cell = normalize_cell(raw_val)
            if cell and not is_garbage_cell(cell):
                d[col] = cell
            else:
                d[col] = ""
        canonical_rows.append(d)

    return canonical_cols, canonical_rows


# ──────────────────────────────────────────────────────────────────────────────
# 5. NORMALIZACIÓN DE IMPORTES
# ──────────────────────────────────────────────────────────────────────────────

_AMOUNT_RE = re.compile(r"(?<![A-Za-z])(\d[\d.,]{0,24})")
_DOLLAR_RE = re.compile(r"\$\s*([0-9OIl][0-9OIl.,]{0,24})")
_CURRENCY_NOISE = re.compile(r"(?i)\s*(?:MXN|MXP|PESOS?)\s*")


def normalize_amount(value: Any) -> str:
    """
    Normaliza un importe monetario a formato «1,234.56».

    Maneja:
    - Prefijo $ y sufijo MXN/MXP
    - Separadores de miles con coma o punto
    - Confusiones OCR: O→0, l→1, I→1

    Returns '' si no se puede parsear ningún importe válido.
    """
    text = _CURRENCY_NOISE.sub("", str(value or "")).strip()
    if not text:
        return ""

    # Intentar con prefijo $
    m = _DOLLAR_RE.search(text)
    if not m:
        m = _AMOUNT_RE.search(text)
    if not m:
        return text

    token = m.group(1)
    # Correcciones OCR dentro del número
    token = token.replace("O", "0").replace("l", "1").replace("I", "1")
    # Conservar solo dígitos y separadores
    token = re.sub(r"[^\d.,]", "", token)
    if not token:
        return text

    # Determinar separador decimal
    decimal_sep: str | None = None
    if "." in token and "," in token:
        decimal_sep = "." if token.rfind(".") > token.rfind(",") else ","
    elif token.count(".") == 1 and len(token.split(".")[-1]) == 2:
        decimal_sep = "."
    elif token.count(",") == 1 and len(token.split(",")[-1]) == 2:
        decimal_sep = ","

    if decimal_sep:
        integer_raw, cents_raw = token.rsplit(decimal_sep, 1)
        integer_digits = re.sub(r"\D", "", integer_raw)
        cents_digits = re.sub(r"\D", "", cents_raw)
        if not integer_digits:
            return text
        cents = (cents_digits + "00")[:2]
        return f"{int(integer_digits):,}.{cents}"

    digits = re.sub(r"\D", "", token)
    if not digits:
        return text
    return f"{int(digits):,}.00"


def normalize_amounts_in_rows(
    rows: list[dict[str, str]],
    amount_columns: set[str] | None = None,
) -> list[dict[str, str]]:
    """
    Aplica ``normalize_amount`` a todas las columnas de importe de la tabla.

    Parameters
    ----------
    rows           : lista de dicts canonical.
    amount_columns : conjunto de nombres de columna a normalizar.
                     Por defecto usa columnas que contengan 'importe' o 'monto'.
    """
    if amount_columns is None:
        # Detectar automáticamente
        all_cols = {k for row in rows for k in row}
        amount_columns = {c for c in all_cols if "importe" in c or "monto" in c}

    if not amount_columns:
        return rows

    result = []
    for row in rows:
        new_row = dict(row)
        for col in amount_columns:
            if col in new_row and new_row[col]:
                new_row[col] = normalize_amount(new_row[col])
        result.append(new_row)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# 6. CONVERSIÓN COMPLETA A canonical_rows
# ──────────────────────────────────────────────────────────────────────────────

def to_canonical_rows(
    raw_rows: list[list[str]],
    *,
    header_row_index: int | None = None,
    amount_cols: set[str] | None = None,
    drop_empty: bool = True,
    drop_summaries: bool = True,
) -> tuple[list[str], list[dict[str, str]]]:
    """
    Pipeline completo: raw_rows → canonical_rows limpias.

    Pasos:
        1. Detectar (o usar) la fila de encabezados.
        2. ``unify_columns``: nombres canónicos + conversión a dicts.
        3. ``drop_empty_rows``: eliminar filas vacías/basura.
        4. ``drop_summary_rows``: eliminar totales/resúmenes (opcional).
        5. ``normalize_amounts_in_rows``: normalizar importes.

    Parameters
    ----------
    raw_rows         : tabla completa como lista de listas de strings.
    header_row_index : índice de la fila encabezado.
                       None → se detecta automáticamente con detect_header_row.
    amount_cols      : columnas a normalizar como importe.
                       None → detección automática.
    drop_empty       : si True, elimina filas vacías.
    drop_summaries   : si True, elimina filas de totales.

    Returns
    -------
    (canonical_columns, canonical_rows)
    """
    if not raw_rows:
        return [], []

    # 1. Detectar encabezado
    if header_row_index is None:
        header_row_index = detect_header_row(raw_rows)

    if header_row_index >= 0:
        headers = [str(c or "") for c in raw_rows[header_row_index]]
        data_rows = raw_rows[header_row_index + 1:]
    else:
        # Sin encabezado: columnas ficticias col_0, col_1, ...
        n_cols = max((len(r) for r in raw_rows), default=0)
        headers = [f"col_{i}" for i in range(n_cols)]
        data_rows = raw_rows

    # 2. Unificar columnas
    canon_cols, canon_rows = unify_columns(headers, data_rows)

    # 3. Eliminar filas vacías
    if drop_empty:
        canon_rows = drop_empty_rows(canon_rows, min_filled=1)

    # 4. Eliminar filas de totales
    if drop_summaries:
        canon_rows = drop_summary_rows(canon_rows)

    # 5. Normalizar importes
    canon_rows = normalize_amounts_in_rows(
        cast(list[dict[str, str]], canon_rows),
        amount_columns=amount_cols,
    )

    logger.debug(
        "to_canonical_rows: %d cols, %d filas finales",
        len(canon_cols), len(canon_rows),
    )
    return canon_cols, canon_rows


# ──────────────────────────────────────────────────────────────────────────────
# 7. UTILIDADES ADICIONALES
# ──────────────────────────────────────────────────────────────────────────────

def normalize_status(value: Any) -> str:
    """Normaliza un valor de estatus al vocabulario estándar."""
    text = str(value or "").strip().upper()
    if not text:
        return ""
    if text in _VALID_STATUSES:
        return text
    for status in _VALID_STATUSES:
        if status in text:
            return status
    for prefix, full in _STATUS_PREFIX_MAP.items():
        if text.startswith(prefix):
            return full
    return text


def count_filled_columns(row: dict[str, str]) -> int:
    """Cuenta cuántas columnas tienen valor no vacío en un canonical_row."""
    return sum(1 for v in row.values() if str(v or "").strip())


def table_quality_score(
    canonical_cols: list[str],
    canonical_rows: list[dict[str, str]],
) -> dict[str, Any]:
    """
    Calcula un reporte de calidad básico para una tabla canonicalizada.

    Returns
    -------
    dict con claves:
        total_rows, total_cols, avg_fill_rate, empty_rows, quality (0-100)
    """
    if not canonical_rows:
        return {"total_rows": 0, "total_cols": len(canonical_cols),
                "avg_fill_rate": 0.0, "empty_rows": 0, "quality": 0}

    n_cols = len(canonical_cols) or 1
    fill_rates = [count_filled_columns(row) / n_cols for row in canonical_rows]
    avg_fill = sum(fill_rates) / len(fill_rates)
    empty = sum(1 for r in fill_rates if r == 0.0)

    quality = int(avg_fill * 100)

    return {
        "total_rows": len(canonical_rows),
        "total_cols": len(canonical_cols),
        "avg_fill_rate": round(avg_fill, 3),
        "empty_rows": empty,
        "quality": quality,
    }
