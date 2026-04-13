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

import difflib
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
    # ── cuenta / CLABE ───────────────────────────────────────────────────────
    "CUENTA CLABE": "clabe", "CUENTA BENEFICIARIO": "cuenta",
    "CUENTA DE RETIRO": "clabe", "CUENTA DEPOSITO": "cuenta",
    "NUM CUENTA": "cuenta", "NUMERO CUENTA": "cuenta",
    "NO CUENTA": "cuenta", "CONTRATO": "cuenta",
    "NUMERO DE CONTRATO": "cuenta", "NO CONTRATO": "cuenta",
    # ── importes (tablas de pago) ─────────────────────────────────────────────
    "IMPORTE": "importe", "MONTO": "importe",
    # CARGO y ABONO conservan su semántica propia (débito/crédito en edos. cta.)
    "CARGO": "cargo", "CARGOS": "cargo",
    "ABONO": "abono", "ABONOS": "abono",
    "DEBITO": "cargo", "DEBITOS": "cargo",
    "CREDITO": "abono", "CREDITOS": "abono",
    "DEPOSITOS": "abono", "DEPOSITO": "abono",
    "RETIROS": "cargo", "RETIRO": "cargo",
    # ── saldos (estados de cuenta) ────────────────────────────────────────────
    "SALDO": "saldo", "SALDO FINAL": "saldo_final",
    "SALDO ANTERIOR": "saldo_anterior", "SALDO ACTUAL": "saldo",
    "BALANCE": "saldo",
    # ── nombres ───────────────────────────────────────────────────────────────
    "NOMBRE": "nombre", "BENEFICIARIO": "nombre_beneficiario",
    "NOMBRE BENEFICIARIO": "nombre_beneficiario",
    "NOMBRE DEL BENEFICIARIO": "nombre_beneficiario",
    "APELLIDO PATERNO": "apellido_paterno",
    "APELLIDO MATERNO": "apellido_materno",
    "APELLIDOS": "apellido_paterno",
    # ── referencias ───────────────────────────────────────────────────────────
    "REFERENCIA": "referencia", "CLAVE RASTREO": "clave_rastreo",
    "FOLIO": "folio", "FOLIO INTERNET": "folio_internet",
    "FOLIO OPERACION": "folio", "NUM OPERACION": "folio",
    "NUM EMPLEADO": "numero_empleado", "NO EMPLEADO": "numero_empleado",
    "NUMERO EMPLEADO": "numero_empleado",
    # ── estatus ───────────────────────────────────────────────────────────────
    "ESTATUS": "estatus", "STATUS": "estatus", "ESTADO": "estatus",
    # ── concepto / descripción ────────────────────────────────────────────────
    "CONCEPTO": "concepto_pago", "DESCRIPCION": "concepto_pago",
    "MOTIVO": "concepto_pago", "DETALLE": "concepto_pago",
    # ── banco ─────────────────────────────────────────────────────────────────
    "BANCO": "banco", "INSTITUCION": "banco",
    "BANCO RECEPTOR": "banco_receptor", "BANCO DESTINO": "banco_receptor",
    "NO BANCO": "banco_receptor", "NUMERO BANCO": "banco_receptor",
    # ── rfc / curp / nss ──────────────────────────────────────────────────────
    "RFC": "rfc", "CURP": "curp", "NSS": "nss",
    # ── CFDI: conceptos de factura ────────────────────────────────────────────
    "CLAVE PROD SERV": "clave_prod_serv", "CLAVEPRODSERV": "clave_prod_serv",
    "CLAVE PRODUCTO": "clave_prod_serv", "CLAVE SAT": "clave_prod_serv",
    "NO IDENTIFICACION": "no_identificacion", "NO IDENT": "no_identificacion",
    "UNIDAD": "unidad", "CLAVE UNIDAD": "clave_unidad",
    "VALOR UNITARIO": "valor_unitario", "PRECIO UNITARIO": "valor_unitario",
    "PRECIO UNIT": "valor_unitario", "P UNITARIO": "valor_unitario",
    "PRECIO": "valor_unitario",
    "CANTIDAD": "cantidad",       # unidades (CFDI); se remap a importe en tablas de pago
    "DESCUENTO": "descuento",
    # ── nómina: desglose percepciones/deducciones ─────────────────────────────
    "PERCEPCION": "percepcion", "PERCEPCIONES": "percepcion",
    "DEDUCCION": "deduccion", "DEDUCCIONES": "deduccion",
    "IMPORTE GRAVADO": "importe_gravado", "IMP GRAVADO": "importe_gravado",
    "IMPORTE EXENTO": "importe_exento", "IMP EXENTO": "importe_exento",
    "TIPO PERCEPCION": "tipo", "TIPO DEDUCCION": "tipo", "TIPO": "tipo",
    "CLAVE PERCEPCION": "clave", "CLAVE DEDUCCION": "clave", "CLAVE": "clave",
    # ── fecha ─────────────────────────────────────────────────────────────────
    "FECHA": "fecha", "FECHA OPERACION": "fecha",
    "FECHA VALOR": "fecha", "FECHA MOVIMIENTO": "fecha",
    "FECHA APLICACION": "fecha", "FECHA LIQUIDACION": "fecha",
}

# Columnas financieras que deben recibir normalización de importes
_FINANCIAL_AMOUNT_COLS: frozenset[str] = frozenset({
    "importe", "monto", "cargo", "abono", "saldo", "saldo_anterior", "saldo_final",
    "total", "subtotal", "descuento", "valor_unitario", "precio_unitario",
    "importe_gravado", "importe_exento", "total_percepciones", "total_deducciones",
    "neto_pagar", "depositos", "retiros", "percepcion", "deduccion",
})


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


def _looks_like_generic_header(row: list[str]) -> bool:
    """Heurística para detectar encabezados en tablas no financieras.

    Una fila es encabezado genérico si:
      - Tiene al menos 2 celdas no vacías.
      - ≥ 70 % de las celdas son texto puro (sin números solos ni importes).
      - Ninguna celda es un número puro, fecha o importe monetario.
      - Las celdas tienen longitud razonable (2-60 chars) — evita ruido OCR.
    """
    _pure_numeric = re.compile(r"^\$?\s*\d[\d\s.,]*$")
    _date_like    = re.compile(r"^\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}$")

    non_empty = [str(c or "").strip() for c in row if str(c or "").strip()]
    if len(non_empty) < 2:
        return False
    numeric_count = sum(
        1 for c in non_empty
        if _pure_numeric.match(c) or _date_like.match(c)
    )
    text_count = len(non_empty) - numeric_count
    # Mayoría texto + longitud razonable en al menos la mitad de las celdas
    reasonable = sum(1 for c in non_empty if 2 <= len(c) <= 60)
    return text_count >= len(non_empty) * 0.7 and reasonable >= len(non_empty) * 0.5


def detect_header_row(rows: list[list[str]]) -> int:
    """
    Detecta el índice de la fila de encabezados en una tabla raw (lista de listas).

    Estrategia en dos pasos:
      1. Busca entre las primeras 5 filas la que tenga más tokens financieros
         conocidos (CUENTA, NOMBRE, IMPORTE, REFERENCIA, etc.).
      2. Si ninguna fila tiene tokens conocidos (tabla genérica), aplica la
         heurística ``_looks_like_generic_header``: primera fila con mayoría de
         celdas de texto puro y sin números/fechas se toma como encabezado.
         Esto permite extraer tablas de productos, empleados, etc. con sus
         columnas reales en lugar de col_0, col_1, col_2.

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

    if best_score > 0:
        logger.debug("detect_header_row: encabezado financiero en fila %d (score=%d)", best_idx, best_score)
        return best_idx

    # Fallback genérico: buscar la primera fila que parezca encabezado
    for i, row in enumerate(rows[:3]):
        if _looks_like_generic_header(row):
            logger.debug("detect_header_row: encabezado genérico detectado en fila %d", i)
            return i

    return -1


# ──────────────────────────────────────────────────────────────────────────────
# 3b. FUSIÓN DE ENCABEZADOS MULTI-FILA
# ──────────────────────────────────────────────────────────────────────────────

def merge_multirow_headers(
    rows: list[list[str]],
    header_index: int,
) -> list[list[str]]:
    """
    Fusiona encabezados distribuidos en dos filas consecutivas.

    Algunos PDFs generan tablas donde la primera fila tiene títulos de grupo
    (p. ej. «IMPORTE») y la segunda tiene sub-columnas («BRUTO», «NETO»).
    Esta función detecta si la fila anterior al encabezado detectado también
    contiene tokens de encabezado conocidos y, de ser así, concatena ambas
    filas en una sola para que ``unify_columns`` las reconozca correctamente.

    Parameters
    ----------
    rows         : tabla raw completa (lista de listas).
    header_index : índice de la fila de encabezado ya detectada.

    Returns
    -------
    rows con la fila de encabezado fusionada (misma longitud de lista).
    """
    if header_index <= 0 or header_index >= len(rows):
        return rows

    prev_row = rows[header_index - 1]
    header_row = rows[header_index]

    # Score de la fila anterior
    prev_score = _row_header_score(prev_row)
    if prev_score == 0:
        return rows  # sin tokens de encabezado → no fusionar

    n_cols = max(len(prev_row), len(header_row))
    merged: list[str] = []
    for i in range(n_cols):
        p = str(prev_row[i] if i < len(prev_row) else "").strip()
        h = str(header_row[i] if i < len(header_row) else "").strip()
        if p and h:
            merged.append(f"{p} {h}")
        else:
            merged.append(p or h)

    new_rows = list(rows)
    new_rows[header_index] = merged
    # Eliminar la fila anterior al encabezado (ya absorbida)
    del new_rows[header_index - 1]
    logger.debug("merge_multirow_headers: fusionados encabezados fila %d+%d", header_index - 1, header_index)
    return new_rows


# ──────────────────────────────────────────────────────────────────────────────
# 4. UNIFICACIÓN DE COLUMNAS
# ──────────────────────────────────────────────────────────────────────────────

def _fuzzy_alias_match(normalized: str) -> str | None:
    """
    Busca la clave de alias más similar usando SequenceMatcher.
    Solo aplica si la similitud supera 0.72 y el normalized tiene al menos 4 chars.
    Evita falsos positivos en tokens cortos (p. ej. "RFC" no debe fuzzy-matchear).
    """
    if len(normalized) < 4:
        return None
    best_ratio = 0.0
    best_canon: str | None = None
    for alias_key, canon in _COLUMN_ALIASES.items():
        if abs(len(alias_key) - len(normalized)) > max(len(normalized) // 2, 4):
            continue  # diferencia de longitud muy grande → skip rápido
        ratio = difflib.SequenceMatcher(None, normalized, alias_key, autojunk=False).ratio()
        if ratio > best_ratio and ratio >= 0.72:
            best_ratio = ratio
            best_canon = canon
    return best_canon


def canonicalize_column_name(raw: str) -> str:
    """
    Convierte un encabezado de columna raw a su nombre canónico en snake_case.

    Estrategia:
      1. Búsqueda exacta en _COLUMN_ALIASES.
      2. Búsqueda parcial (substrings).
      3. Similitud fuzzy (difflib ≥ 0.72) — captura abreviaciones y OCR.
      4. Fallback snake_case del texto normalizado.

    Ejemplos:
        "CUENTA CLABE"      ->  "clabe"
        "IMPT UNIT"         ->  "valor_unitario"  (fuzzy)
        "NOMB BENEF"        ->  "nombre_beneficiario" (fuzzy)
        "N° empleado"       ->  "numero_empleado"
    """
    normalized = re.sub(r"\s+", " ", str(raw or "").upper().strip())
    normalized = re.sub(r"[^\w\s]", "", normalized)
    normalized = re.sub(r"\bN[UÚO°]?[MR]?[EOO]?\b\.?\s*", "NUMERO ", normalized).strip()

    # 1. Búsqueda exacta
    if normalized in _COLUMN_ALIASES:
        return _COLUMN_ALIASES[normalized]

    # 2. Búsqueda parcial (el token más largo que coincida)
    best_match = ""
    for alias_key in _COLUMN_ALIASES:
        if alias_key in normalized and len(alias_key) > len(best_match):
            best_match = alias_key
    if best_match:
        return _COLUMN_ALIASES[best_match]

    # 3. Fuzzy match (abreviaciones, OCR roto)
    fuzzy_canon = _fuzzy_alias_match(normalized)
    if fuzzy_canon:
        logger.debug("canonicalize fuzzy: '%s' → '%s'", raw, fuzzy_canon)
        return fuzzy_canon

    # 4. Fallback: snake_case del texto normalizado
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
        # Detectar automáticamente: columnas financieras conocidas + cualquiera
        # que contenga "importe" o "monto" en su nombre (cubre variantes futuras)
        all_cols = {k for row in rows for k in row}
        amount_columns = {
            c for c in all_cols
            if c in _FINANCIAL_AMOUNT_COLS
            or "importe" in c
            or "monto" in c
            or "saldo" in c
        }

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
# 5b. RECONSTRUCCIÓN DE FILAS FRAGMENTADAS
# ──────────────────────────────────────────────────────────────────────────────

def reconstruct_fragmented_rows(
    rows: list[dict[str, str]],
    min_fill_ratio: float = 0.35,
) -> list[dict[str, str]]:
    """Fusiona filas parciales que el OCR fragmentó en múltiples líneas.

    Cuando el OCR divide una fila lógica en dos líneas (p.ej. el nombre en
    una y el importe en la siguiente), la fila resultante tiene muy pocas
    celdas llenas.  Si esa fila parcial rellena huecos de la fila anterior
    se fusiona con ella en lugar de quedar como fila independiente.

    Parameters
    ----------
    rows          : lista de dicts canonical ya con columnas unificadas.
    min_fill_ratio: ratio mínimo de celdas llenas para considerar una fila
                    completa.  Filas con menos se tratan como fragmentos.
    """
    if not rows:
        return rows

    n_cols = max(len(r) for r in rows) if rows else 1
    min_filled = max(1, int(n_cols * min_fill_ratio))

    result: list[dict[str, str]] = []
    merged_count = 0

    for row in rows:
        filled = sum(1 for v in row.values() if str(v or "").strip())
        # Fila completa o primera fila → añadir directamente
        if filled >= min_filled or not result:
            result.append(row)
            continue

        # Fila fragmentada: intentar fusionar con la anterior
        prev = result[-1]
        prev_empty_keys = {k for k, v in prev.items() if not str(v or "").strip()}
        row_filled_keys = {k for k, v in row.items() if str(v or "").strip()}

        # Fusionar solo si esta fila rellena huecos de la anterior
        # y no sobreescribe valores ya presentes (evita mezclar filas distintas)
        if row_filled_keys & prev_empty_keys:
            merged = dict(prev)
            for k in row_filled_keys:
                if not str(merged.get(k, "")).strip():
                    merged[k] = row[k]
            result[-1] = merged
            merged_count += 1
        else:
            result.append(row)

    if merged_count:
        logger.debug(
            "reconstruct_fragmented_rows: fusionadas %d filas fragmentadas", merged_count
        )
    return result


# ──────────────────────────────────────────────────────────────────────────────
# 5c. DEDUPLICACIÓN DE FILAS
# ──────────────────────────────────────────────────────────────────────────────

def deduplicate_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Elimina filas duplicadas (contenido idéntico normalizado).

    Ocurre cuando pdfplumber y img2table detectan la misma tabla y los
    mismos contenidos pasan por el pipeline dos veces, o cuando el OCR
    repite una línea con ligeras diferencias de espaciado.

    Conserva la primera aparición de cada fila única.
    """
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    dupes = 0

    for row in rows:
        # Firma: pares clave-valor no vacíos, normalizados y ordenados
        sig = "|".join(
            f"{k}:{str(v).strip().upper()[:40]}"
            for k, v in sorted(row.items())
            if str(v or "").strip()
        )
        if not sig:
            result.append(row)
            continue
        if sig in seen:
            dupes += 1
            continue
        seen.add(sig)
        result.append(row)

    if dupes:
        logger.debug("deduplicate_rows: eliminadas %d filas duplicadas", dupes)
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

    # 1. Detectar encabezado y fusionar encabezados multi-fila
    if header_row_index is None:
        header_row_index = detect_header_row(raw_rows)

    if header_row_index >= 0:
        # Intentar fusionar con fila anterior si también contiene tokens de encabezado
        orig_len = len(raw_rows)
        raw_rows = merge_multirow_headers(raw_rows, header_row_index)
        # Solo ajustar el índice si la fusión realmente eliminó una fila
        if len(raw_rows) < orig_len:
            header_row_index = header_row_index - 1
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

    # 3.5 Reconstruir filas fragmentadas por OCR
    canon_rows = reconstruct_fragmented_rows(cast(list[dict[str, str]], canon_rows))

    # 4. Eliminar filas de totales
    if drop_summaries:
        canon_rows = drop_summary_rows(canon_rows)

    # 4.5 Eliminar duplicados (mismo contenido detectado por múltiples extractores)
    canon_rows = deduplicate_rows(cast(list[dict[str, str]], canon_rows))

    # 5. Normalizar importes en todas las columnas financieras conocidas
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


# ──────────────────────────────────────────────────────────────────────────────
# 8. ESQUEMAS DE PAGOS POR BANCO
# ──────────────────────────────────────────────────────────────────────────────

# Etiquetas de visualización para cada columna canónica
_PAYMENT_DISPLAY_LABELS: dict[str, str] = {
    "clave_beneficiario":  "Clave",
    "nombre_beneficiario": "Nombre",
    "importe":             "Importe",
    "fecha_aplicacion":    "Fecha",
    "referencia":          "Referencia",
    "cuenta_beneficiario": "Cuenta",
    "banco_receptor":      "Banco",
    "dias_vigencia":       "Dias",
    "concepto_pago":       "Concepto",
    "estatus":             "Estatus",
}

# Esquema de 9 columnas completo (Scotiabank y fallback universal)
TARGET_PAYMENT_SCHEMA: list[str] = list(_PAYMENT_DISPLAY_LABELS.keys())
TARGET_PAYMENT_DISPLAY: dict[str, str] = dict(_PAYMENT_DISPLAY_LABELS)

# Esquemas específicos por banco — solo las columnas que ese banco realmente provee
# Orden refleja el orden natural del documento de cada banco
_BANK_SCHEMAS: dict[str, list[str]] = {
    "SCOTIABANK": [
        "clave_beneficiario",
        "nombre_beneficiario",
        "importe",
        "fecha_aplicacion",
        "referencia",
        "cuenta_beneficiario",
        "banco_receptor",
        "dias_vigencia",
        "concepto_pago",
    ],
    "BBVA": [
        "nombre_beneficiario",
        "cuenta_beneficiario",
        "importe",
        "concepto_pago",
    ],
    "BANORTE": [
        "clave_beneficiario",
        "nombre_beneficiario",
        "cuenta_beneficiario",
        "importe",
        "fecha_aplicacion",
        "referencia",
        "banco_receptor",
        "concepto_pago",
    ],
    "SANTANDER": [
        "nombre_beneficiario",
        "cuenta_beneficiario",
        "banco_receptor",
        "referencia",
        "importe",
        "estatus",
        "concepto_pago",
    ],
    "BANAMEX": [
        "nombre_beneficiario",
        "cuenta_beneficiario",
        "banco_receptor",
        "importe",
        "fecha_aplicacion",
        "referencia",
        "concepto_pago",
    ],
    "HSBC": [
        "nombre_beneficiario",
        "cuenta_beneficiario",
        "banco_receptor",
        "importe",
        "fecha_aplicacion",
        "referencia",
        "concepto_pago",
    ],
}

# Sinónimos de columnas extraídas → columna objetivo
# Incluye tanto formas con guión_bajo como formas concatenadas (sin guión)
# que usa el pipeline interno de tables.py
_TO_TARGET_COL: dict[str, str] = {
    # ── clave_beneficiario ────────────────────────────────────────────────
    "clave_beneficiario":       "clave_beneficiario",
    "clave_de_beneficiario":    "clave_beneficiario",
    "clavedebeneficiario":      "clave_beneficiario",   # pipeline interno
    "clavebeneficiario":        "clave_beneficiario",
    "clavedelbeneficiario":     "clave_beneficiario",
    "clave":                    "clave_beneficiario",
    "numero_empleado":          "clave_beneficiario",   # Banorte: No. Empleado
    "numeroempleado":           "clave_beneficiario",
    "no_empleado":              "clave_beneficiario",
    # ── nombre_beneficiario ───────────────────────────────────────────────
    "nombre_beneficiario":      "nombre_beneficiario",
    "nombrebeneficiario":       "nombre_beneficiario",  # pipeline interno
    "nombredelbeneficiario":    "nombre_beneficiario",
    "nombre":                   "nombre_beneficiario",
    "beneficiario":             "nombre_beneficiario",
    "nombrecorto":              "nombre_beneficiario",
    "nombrenombre":             "nombre_beneficiario",
    "nombre_corto":             "nombre_beneficiario",
    "titular":                  "nombre_beneficiario",
    # ── importe ───────────────────────────────────────────────────────────
    "importe":                  "importe",
    "importe_detectado":        "importe",
    "monto":                    "importe",
    "cantidad":                 "importe",
    "cargo":                    "importe",
    "abono":                    "importe",
    # ── fecha_aplicacion ──────────────────────────────────────────────────
    "fecha_aplicacion":         "fecha_aplicacion",
    "fechaaplicacion":          "fecha_aplicacion",     # pipeline interno
    "fecha_de_aplicacion":      "fecha_aplicacion",
    "fechadeaplicacion":        "fecha_aplicacion",
    "fecha":                    "fecha_aplicacion",
    "fecha_operacion":          "fecha_aplicacion",
    "fechaoperacion":           "fecha_aplicacion",
    "fecha_valor":              "fecha_aplicacion",
    "fecha_movimiento":         "fecha_aplicacion",
    "fecha_liquidacion":        "fecha_aplicacion",
    "fechaliquidacion":         "fecha_aplicacion",
    # ── referencia ────────────────────────────────────────────────────────
    "referencia":               "referencia",
    "clave_rastreo":            "referencia",
    "claverastreo":             "referencia",           # pipeline interno
    "folio":                    "referencia",
    "folio_internet":           "referencia",
    "folio_operacion":          "referencia",
    "foliointernet":            "referencia",
    "folio_unico":              "referencia",
    "foliounico":               "referencia",
    "referencia_numerica":      "referencia",
    "referenciaemisor":         "referencia",
    # ── cuenta_beneficiario ───────────────────────────────────────────────
    "cuenta_beneficiario":      "cuenta_beneficiario",
    "cuentabeneficiario":       "cuenta_beneficiario",  # pipeline interno
    "nocuentabeneficiario":     "cuenta_beneficiario",
    "numerodecuentabeneficiario": "cuenta_beneficiario",
    "cuenta_abono":             "cuenta_beneficiario",
    "cuentaabono":              "cuenta_beneficiario",
    "cuenta":                   "cuenta_beneficiario",
    "clabe":                    "cuenta_beneficiario",
    "cuenta_clabe":             "cuenta_beneficiario",
    "cuentaclabe":              "cuenta_beneficiario",
    "cuenta_deposito":          "cuenta_beneficiario",
    "cuentadeposito":           "cuenta_beneficiario",
    "cuenta_retiro":            "cuenta_beneficiario",
    "cuentaretiro":             "cuenta_beneficiario",
    "numero_cuenta":            "cuenta_beneficiario",
    "no_de_cuenta":             "cuenta_beneficiario",
    "nodecuenta":               "cuenta_beneficiario",
    # ── banco_receptor ────────────────────────────────────────────────────
    "banco_receptor":           "banco_receptor",
    "bancoreceptor":            "banco_receptor",       # pipeline interno
    "no_banco_receptor":        "banco_receptor",
    "nobancoreceptor":          "banco_receptor",
    "banco_destino":            "banco_receptor",
    "bancodestino":             "banco_receptor",
    "banco":                    "banco_receptor",
    "institucion":              "banco_receptor",
    "banco_beneficiario":       "banco_receptor",
    # ── dias_vigencia ─────────────────────────────────────────────────────
    "dias_vigencia":            "dias_vigencia",
    "diasvigencia":             "dias_vigencia",        # pipeline interno
    "dias":                     "dias_vigencia",
    "vigencia":                 "dias_vigencia",
    # ── concepto_pago ─────────────────────────────────────────────────────
    "concepto_pago":            "concepto_pago",
    "conceptopago":             "concepto_pago",        # pipeline interno
    "concepto_pago2":           "concepto_pago",
    "concepto":                 "concepto_pago",
    "descripcion":              "concepto_pago",
    "motivo_pago":              "concepto_pago",
    "motivopago":               "concepto_pago",
    "proposito":                "concepto_pago",
    "proposito_de_la_transferencia": "concepto_pago",
    # ── estatus ───────────────────────────────────────────────────────────────
    "estatus":                  "estatus",
    "estado":                   "estatus",
    "estatus_operacion":        "estatus",
    "resultado":                "estatus",
}


def remap_to_target_payment_schema(
    canonical_columns: list[str],
    canonical_rows: list[dict[str, Any]],
    bank: str = "",
) -> tuple[list[str], list[dict[str, str]], dict[str, str]]:
    """
    Remapea canonical_columns y canonical_rows al esquema del banco detectado.

    Estrategia:
      1. Si el banco tiene esquema definido → usa esas columnas exactas (sin blancos).
      2. Si no se detectó el banco → tabla adaptativa: solo columnas con datos.
      3. Fallback: esquema universal de 9 columnas.

    Returns:
        (target_columns, remapped_rows, display_columns)
    """
    bank_key = str(bank or "").upper().strip()

    # Construir mapa columna_fuente → columna_objetivo
    col_map: dict[str, str] = {}
    for src in canonical_columns:
        normalized = re.sub(r"[^a-z0-9]+", "_", src.lower()).strip("_")
        target = _TO_TARGET_COL.get(normalized) or _TO_TARGET_COL.get(src.lower())
        if target:
            col_map[src] = target

    # Remap todas las filas usando el mapa completo de 9 columnas
    all_remapped: list[dict[str, str]] = []
    for row in canonical_rows:
        new_row: dict[str, str] = {col: "" for col in TARGET_PAYMENT_SCHEMA}
        for src_col, value in row.items():
            tgt = col_map.get(src_col)
            if tgt and str(value or "").strip():
                new_row[tgt] = str(value).strip()
        # Combinar apellido_paterno + apellido_materno con nombre_beneficiario
        # (tablas Santander y otras que separan nombre y apellidos en columnas distintas)
        ap = str(row.get("apellido_paterno") or "").strip()
        am = str(row.get("apellido_materno") or "").strip()
        if ap or am:
            nombre_base = new_row.get("nombre_beneficiario", "")
            partes = [p for p in [nombre_base, ap, am] if p]
            new_row["nombre_beneficiario"] = " ".join(partes)
        if any(v for v in new_row.values()):
            all_remapped.append(new_row)

    # ── Seleccionar esquema de columnas ──────────────────────────────────────
    if bank_key in _BANK_SCHEMAS:
        # Esquema fijo del banco — columnas definidas por tipo de banco
        schema = _BANK_SCHEMAS[bank_key]
        final_rows = [
            {col: row.get(col, "") for col in schema}
            for row in all_remapped
        ]
    elif all_remapped:
        # Tabla adaptativa — solo columnas que tienen al menos un valor
        cols_with_data = [
            col for col in TARGET_PAYMENT_SCHEMA
            if any(str(row.get(col, "") or "").strip() for row in all_remapped)
        ]
        schema = cols_with_data if cols_with_data else TARGET_PAYMENT_SCHEMA
        final_rows = [
            {col: row.get(col, "") for col in schema}
            for row in all_remapped
        ]
    else:
        schema = TARGET_PAYMENT_SCHEMA
        final_rows = all_remapped

    display = {col: _PAYMENT_DISPLAY_LABELS.get(col, col.replace("_", " ").upper()) for col in schema}
    return list(schema), final_rows, display
