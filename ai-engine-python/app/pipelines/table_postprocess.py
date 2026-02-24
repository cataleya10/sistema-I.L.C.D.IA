"""Pandas-based table post-processing for precision data cleaning.

Takes canonical payment table rows (list[dict]) produced by extract.py and
applies column-aware cleaning, type inference, deduplication, and quality
enrichment using Pandas DataFrames.

Designed to run as the last step before the API returns table data — after
all extraction, normalization, and canonical mapping are complete.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column classification
# ---------------------------------------------------------------------------

_AMOUNT_COLUMNS = frozenset({
    "importe", "importe_detectado", "importe_total_movimientos",
    "importe_movimiento_altas", "importe_movimientos_bajas",
})

_ACCOUNT_COLUMNS = frozenset({
    "cuenta", "cuenta_retiro", "cuenta_beneficiario", "cuenta_deposito",
    "numero_contrato", "contrato",
})

_NAME_COLUMNS = frozenset({
    "nombre", "nombre_beneficiario", "apellido_paterno", "apellido_materno",
    "titular",
})

_STATUS_COLUMNS = frozenset({
    "estatus",
})

_NUMERIC_ID_COLUMNS = frozenset({
    "referencia", "numero_empleado", "folio_internet", "folio_firma",
    "folio_unico", "folio_operacion", "numero_lote", "codigo",
    "clave_rastreo",
})

_VALID_STATUSES = frozenset({
    "APLICADO", "ACEPTADO", "PROCESADO", "TRANSMITIDO", "RECHAZADO",
    "EN PROCESO", "EN PROCESO DE VALIDACION", "DEVUELTO", "CANCELADO",
    "LIQUIDADO",
})

# ---------------------------------------------------------------------------
# Cell-level cleaners
# ---------------------------------------------------------------------------


def _clean_amount(value: str) -> str:
    """Normalize monetary amounts to consistent $X,XXX.XX format."""
    text = str(value or "").strip()
    if not text:
        return ""
    # Fix common OCR errors
    text = text.replace("O", "0").replace("l", "1").replace("I", "1")
    # Strip currency prefix/suffix
    text = re.sub(r"(?i)\s*(?:MXN|MXP|PESOS?)\s*", "", text)
    match = re.search(r"\$?\s*(\d[\d.,]{0,24})", text)
    if not match:
        return text  # return original if no number found
    token = match.group(1)
    token = re.sub(r"[^\d.,]", "", token)
    if not token:
        return text

    # Determine decimal separator
    decimal_sep = None
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
        return f"${int(integer_digits):,}.{cents}"

    integer_digits = re.sub(r"\D", "", token)
    if not integer_digits:
        return text
    return f"${int(integer_digits):,}.00"


def _clean_account(value: str) -> str:
    """Normalize account/contract numbers — strip stray non-digits."""
    text = str(value or "").strip()
    if not text:
        return ""
    # If it looks mostly numeric with stray chars, clean it
    digits = re.sub(r"\D", "", text)
    non_digits = len(text) - len(digits)
    if digits and non_digits <= 3 and len(digits) >= 6:
        return digits
    return text


def _clean_name(value: str) -> str:
    """Normalize person names — uppercase, collapse whitespace, strip noise."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.upper()
    # Remove common OCR artifacts in names
    text = re.sub(r"[_\-]{2,}", " ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    # Remove trailing/leading punctuation that isn't part of names
    text = text.strip(".,;:-_/\\|")
    return text


def _clean_status(value: str) -> str:
    """Normalize status values to standard vocabulary."""
    text = str(value or "").strip().upper()
    if not text:
        return ""
    # Direct match
    if text in _VALID_STATUSES:
        return text
    # Fuzzy match: find first valid status contained in the text
    for status in _VALID_STATUSES:
        if status in text:
            return status
    # Abbreviated/OCR-damaged status recovery
    status_map = {
        "APLIC": "APLICADO",
        "ACEPT": "ACEPTADO",
        "PROCE": "PROCESADO",
        "TRANS": "TRANSMITIDO",
        "RECHA": "RECHAZADO",
        "DEVUE": "DEVUELTO",
        "CANCE": "CANCELADO",
        "LIQUI": "LIQUIDADO",
    }
    for prefix, full in status_map.items():
        if text.startswith(prefix):
            return full
    return text


def _clean_numeric_id(value: str) -> str:
    """Clean numeric ID fields — strip stray whitespace/separators."""
    text = str(value or "").strip()
    if not text:
        return ""
    # If purely numeric with spaces, collapse
    collapsed = re.sub(r"\s+", "", text)
    if re.fullmatch(r"[A-Za-z0-9]+", collapsed):
        return collapsed
    return text


# ---------------------------------------------------------------------------
# DataFrame post-processing engine
# ---------------------------------------------------------------------------


def postprocess_payment_table(
    canonical_columns: list[str],
    canonical_rows: list[dict[str, str]],
    bank: str = "",
) -> tuple[list[str], list[dict[str, str]]]:
    """Apply Pandas-based precision cleaning to canonical payment table data.

    Parameters
    ----------
    canonical_columns : list[str]
        Column names in canonical form (e.g., "cuenta", "importe", "nombre").
    canonical_rows : list[dict[str, str]]
        Row data as list of dicts (canonical key → string value).
    bank : str
        Detected bank name (e.g., "BBVA", "BANORTE").

    Returns
    -------
    tuple[list[str], list[dict[str, str]]]
        Cleaned (columns, rows) in the same format as input.
    """
    if not canonical_rows:
        return canonical_columns, canonical_rows

    try:
        df = pd.DataFrame(canonical_rows)
    except Exception:
        logger.debug("postprocess_payment_table: failed to create DataFrame")
        return canonical_columns, canonical_rows

    if df.empty:
        return canonical_columns, canonical_rows

    # --- Step 1: Column-wise type-aware cleaning ---
    for col in df.columns:
        col_lower = str(col).lower()
        if col_lower in _AMOUNT_COLUMNS:
            df[col] = df[col].apply(_clean_amount)
        elif col_lower in _ACCOUNT_COLUMNS:
            df[col] = df[col].apply(_clean_account)
        elif col_lower in _NAME_COLUMNS:
            df[col] = df[col].apply(_clean_name)
        elif col_lower in _STATUS_COLUMNS:
            df[col] = df[col].apply(_clean_status)
        elif col_lower in _NUMERIC_ID_COLUMNS:
            df[col] = df[col].apply(_clean_numeric_id)
        else:
            # Generic: strip whitespace
            df[col] = df[col].apply(lambda v: str(v or "").strip())

    # --- Step 2: Cross-column status inference ---
    # If estatus is empty but descripcion contains a valid status, fill it
    if "estatus" in df.columns and "descripcion" in df.columns:
        mask = df["estatus"].apply(lambda v: not str(v or "").strip())
        for idx in df.index[mask]:
            desc = str(df.at[idx, "descripcion"] or "").upper()
            for status in _VALID_STATUSES:
                if status in desc:
                    df.at[idx, "estatus"] = status
                    break

    # --- Step 3: Cross-column amount validation ---
    # If importe looks like an account number (too many digits, no decimal),
    # flag it — but don't destructively modify
    if "importe" in df.columns:
        for idx in df.index:
            val = str(df.at[idx, "importe"] or "")
            digits_only = re.sub(r"\D", "", val)
            if len(digits_only) > 14 and "." not in val and "," not in val:
                # This looks like an account number, not an amount
                logger.debug(
                    "postprocess: suspicious importe '%s' at row %d (looks like account)",
                    val, idx,
                )

    # --- Step 4: Duplicate row detection ---
    # Build a dedup key from (cuenta or nombre) + importe
    dedup_cols = []
    for col in ("cuenta", "cuenta_beneficiario"):
        if col in df.columns:
            dedup_cols.append(col)
            break
    if "importe" in df.columns:
        dedup_cols.append("importe")
    if "nombre" in df.columns or "nombre_beneficiario" in df.columns:
        name_col = "nombre" if "nombre" in df.columns else "nombre_beneficiario"
        dedup_cols.append(name_col)

    if len(dedup_cols) >= 2:
        before_count = len(df)
        df = df.drop_duplicates(subset=dedup_cols, keep="first")
        dropped = before_count - len(df)
        if dropped > 0:
            logger.info("postprocess: removed %d duplicate rows", dropped)

    # --- Step 5: Empty row removal ---
    # Drop rows where all value columns are empty
    value_cols = [c for c in df.columns if c not in ("columna_1", "columna_2")]
    if value_cols:
        mask = df[value_cols].apply(
            lambda row: any(str(v or "").strip() for v in row), axis=1
        )
        df = df[mask]

    # --- Step 6: Column completeness stats (for diagnostics) ---
    # Not returned to client, but useful for logging
    total_rows = len(df)
    if total_rows > 0:
        fill_rates = {}
        for col in df.columns:
            filled = df[col].apply(lambda v: bool(str(v or "").strip())).sum()
            fill_rates[col] = round(filled / total_rows * 100, 1)
        logger.debug("postprocess: column fill rates: %s", fill_rates)

    # --- Step 7: Convert back to canonical format ---
    # Replace NaN/None with empty string
    df = df.fillna("")

    # Rebuild columns list preserving original order + any new columns
    result_columns = list(canonical_columns)
    for col in df.columns:
        if col not in result_columns:
            result_columns.append(col)
    # Only keep columns that actually exist in the DataFrame
    result_columns = [c for c in result_columns if c in df.columns]

    result_rows = df.to_dict(orient="records")
    # Ensure all values are strings
    clean_rows: list[dict[str, str]] = []
    for row in result_rows:
        clean_row: dict[str, str] = {}
        for key, value in row.items():
            text = str(value or "").strip()
            if text:
                clean_row[str(key)] = text
        if clean_row:
            clean_rows.append(clean_row)

    return result_columns, clean_rows


def postprocess_metadata(
    metadata: dict[str, str],
    bank: str = "",
) -> dict[str, str]:
    """Apply precision cleaning to payment metadata fields.

    Parameters
    ----------
    metadata : dict[str, str]
        Raw metadata extracted from document text.
    bank : str
        Detected bank name.

    Returns
    -------
    dict[str, str]
        Cleaned metadata.
    """
    if not metadata:
        return metadata

    cleaned: dict[str, str] = {}
    for key, value in metadata.items():
        text = str(value or "").strip()
        if not text:
            continue
        key_lower = key.lower()

        # Count fields — ensure purely numeric (check BEFORE amounts since
        # "cantidad_total_movimientos" contains "total" but is a count)
        if any(token in key_lower for token in ("cantidad", "registros")) and "importe" not in key_lower:
            digits = re.sub(r"\D", "", text)
            if digits:
                text = str(int(digits))
        # Amount fields
        elif any(token in key_lower for token in ("importe", "monto")) or (key_lower.endswith("_total") and "cantidad" not in key_lower):
            text = _clean_amount(text)
        # Account/contract fields
        elif any(token in key_lower for token in ("cuenta", "contrato")):
            text = _clean_account(text)
        # Name fields
        elif any(token in key_lower for token in ("nombre", "titular", "usuario", "empresa")):
            text = _clean_name(text)
        # Folio/reference fields
        elif any(token in key_lower for token in ("folio", "lote", "referencia")):
            text = _clean_numeric_id(text)

        if text:
            cleaned[key] = text

    return cleaned


def compute_table_quality_report(
    canonical_columns: list[str],
    canonical_rows: list[dict[str, str]],
) -> dict[str, Any]:
    """Compute a quality report for the extracted table data.

    Returns a dict with column fill rates, row count, and overall quality score.
    Useful for diagnostics and online learning feedback.
    """
    if not canonical_rows:
        return {
            "row_count": 0,
            "column_count": len(canonical_columns),
            "columns": canonical_columns,
            "fill_rates": {},
            "overall_quality": 0.0,
        }

    try:
        df = pd.DataFrame(canonical_rows)
    except Exception:
        return {
            "row_count": len(canonical_rows),
            "column_count": len(canonical_columns),
            "columns": canonical_columns,
            "fill_rates": {},
            "overall_quality": 0.0,
        }

    total_rows = len(df)
    fill_rates: dict[str, float] = {}
    for col in df.columns:
        filled = df[col].apply(lambda v: bool(str(v or "").strip())).sum()
        fill_rates[col] = round(filled / total_rows * 100, 1)

    # Overall quality: average fill rate across important columns
    important_cols = [
        c for c in df.columns
        if c in _AMOUNT_COLUMNS | _ACCOUNT_COLUMNS | _NAME_COLUMNS | _STATUS_COLUMNS
    ]
    if important_cols:
        avg_fill = sum(fill_rates.get(c, 0) for c in important_cols) / len(important_cols)
    else:
        avg_fill = sum(fill_rates.values()) / max(len(fill_rates), 1)

    return {
        "row_count": total_rows,
        "column_count": len(df.columns),
        "columns": list(df.columns),
        "fill_rates": fill_rates,
        "overall_quality": round(avg_fill, 1),
    }
