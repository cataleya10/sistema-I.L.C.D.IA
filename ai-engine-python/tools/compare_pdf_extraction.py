#!/usr/bin/env python3
"""Compare raw PDF data vs extracted table to verify extraction accuracy.

Usage:
    python tools/compare_pdf_extraction.py <path_to_pdf> [--json] [--out report.json]

Reads the PDF using the same pipeline as the AI engine, then compares:
  1) BBVA Advanced Text Extraction (regex-based, 8-column split)
  2) PyMuPDF Structural Extraction (find_tables())
  3) Merged Result (what the system actually outputs)

Generates a clear side-by-side comparison report.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz  # PyMuPDF  # noqa: E402

# Import extraction functions from the engine
from app.pipelines.extract import (  # noqa: E402
    _extract_bbva_nomina_advanced_rows_from_text,
    _extract_payment_table_rows_from_pdf_tables,
    _extract_payment_table_rows_from_text,
    _extract_payment_detail_payload,
    _extract_payment_table_payload,
    _merge_payment_rows_with_backup,
    _payment_rows_quality_score,
    _payment_to_canonical_rows,
    _payment_rows_to_objects,
    _build_display_columns_map,
    _payment_detect_bank,
    _normalize_text,
)


# ── Colours for terminal output ─────────────────────────────────────
class C:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    END = "\033[0m"


def _safe_cell(cell: object) -> str:
    """Same PyMuPDF NaN-safe cell cleaning as the engine."""
    if cell is None:
        return ""
    if isinstance(cell, float) and math.isnan(cell):
        return ""
    text = str(cell).strip()
    if text.upper() == "NAN":
        return ""
    return text


# ── PDF reading ──────────────────────────────────────────────────────
def read_pdf(pdf_path: str) -> tuple[str, list[list[list[str]]]]:
    """Read PDF text and structural tables, same as preprocess.py."""
    raw_text_parts: list[str] = []
    pdf_tables: list[list[list[str]]] = []

    with fitz.open(pdf_path) as doc:
        for page in doc:
            raw_text_parts.append(str(page.get_text("text") or ""))
            try:
                tab_finder = page.find_tables()  # type: ignore[attr-defined]
                for table in tab_finder.tables:
                    raw_rows = table.extract()
                    if raw_rows and len(raw_rows) >= 2:
                        clean_rows = [
                            [_safe_cell(cell) for cell in row]
                            for row in raw_rows
                            if isinstance(row, (list, tuple))
                        ]
                        if clean_rows:
                            pdf_tables.append(clean_rows)
            except Exception:
                pass

    raw_text = "\n\n".join(raw_text_parts)
    return raw_text, pdf_tables


# ── Table display helpers ────────────────────────────────────────────
def _truncate(text: str, max_len: int = 30) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def print_table(title: str, rows: list[list[str]], max_cols: int = 10) -> None:
    if not rows:
        print(f"\n{C.YELLOW}  {title}: (vacio -- sin datos){C.END}")
        return

    header = rows[0][:max_cols]
    data = rows[1:]

    # Compute column widths
    col_widths = [max(len(_truncate(str(h))), 6) for h in header]
    for row in data[:50]:
        for i, cell in enumerate(row[:max_cols]):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], min(len(_truncate(str(cell))), 35))

    print(f"\n{C.BOLD}{C.CYAN}  {title}{C.END}")
    print(f"  Filas: {len(data)}  |  Columnas: {len(header)}")

    # Header row
    header_line = " | ".join(
        f"{C.BOLD}{_truncate(str(h), col_widths[i]):>{col_widths[i]}}{C.END}"
        for i, h in enumerate(header)
    )
    print(f"  {header_line}")
    print(f"  {'-' * sum(col_widths + [3 * (len(header) - 1)])}")

    # Data rows
    for r_i, row in enumerate(data[:100]):
        cells = []
        for i, h in enumerate(header):
            val = str(row[i]) if i < len(row) else ""
            cells.append(f"{_truncate(val, col_widths[i]):>{col_widths[i]}}")
        line = " | ".join(cells)
        print(f"  {line}")

    if len(data) > 100:
        print(f"  ... y {len(data) - 100} filas mas")


def print_canonical_table(
    title: str,
    columns: list[str],
    rows: list[dict],
    display_map: dict[str, str] | None = None,
) -> None:
    """Print a canonical (list-of-dicts) table."""
    if not rows or not columns:
        print(f"\n{C.YELLOW}  {title}: (vacio -- sin datos){C.END}")
        return

    headers = [display_map.get(c, c) if display_map else c for c in columns]
    col_widths = [max(len(_truncate(str(h))), 6) for h in headers]
    for row in rows[:50]:
        for i, col in enumerate(columns):
            val = str(row.get(col, ""))
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], min(len(_truncate(val)), 35))

    print(f"\n{C.BOLD}{C.CYAN}  {title}{C.END}")
    print(f"  Filas: {len(rows)}  |  Columnas: {len(columns)}")

    header_line = " | ".join(
        f"{C.BOLD}{_truncate(str(h), col_widths[i]):>{col_widths[i]}}{C.END}"
        for i, h in enumerate(headers)
    )
    print(f"  {header_line}")
    print(f"  {'-' * sum(col_widths + [3 * (len(headers) - 1)])}")

    for row in rows[:100]:
        cells = []
        for i, col in enumerate(columns):
            val = str(row.get(col, ""))
            cells.append(f"{_truncate(val, col_widths[i]):>{col_widths[i]}}")
        print(f"  {' | '.join(cells)}")

    if len(rows) > 100:
        print(f"  ... y {len(rows) - 100} filas mas")


def compare_canonical(
    text_cols: list[str],
    text_rows: list[dict],
    final_cols: list[str],
    final_rows: list[dict],
) -> dict[str, Any]:
    """Compare text extraction (ground truth) vs final canonical output."""
    stats: dict[str, Any] = {
        "text_extraction": {
            "row_count": len(text_rows),
            "col_count": len(text_cols),
            "columns": text_cols,
        },
        "final_result": {
            "row_count": len(final_rows),
            "col_count": len(final_cols),
            "columns": final_cols,
        },
        "discrepancies": [],
    }

    # Find common columns
    common_cols = [c for c in text_cols if c in final_cols]
    only_text = [c for c in text_cols if c not in final_cols]
    only_final = [c for c in final_cols if c not in text_cols]

    stats["common_columns"] = common_cols
    stats["only_in_text"] = only_text
    stats["only_in_final"] = only_final

    max_rows = max(len(text_rows), len(final_rows))
    matched = 0
    cell_matches = 0
    cell_mismatches = 0
    cell_missing = 0

    for i in range(max_rows):
        if i >= len(text_rows):
            stats["discrepancies"].append({
                "type": "extra_row_in_final",
                "row": i + 1,
            })
            continue
        if i >= len(final_rows):
            stats["discrepancies"].append({
                "type": "missing_row_in_final",
                "row": i + 1,
            })
            continue

        matched += 1
        for col in common_cols:
            text_val = _normalize_text(str(text_rows[i].get(col, ""))).upper()
            final_val = _normalize_text(str(final_rows[i].get(col, ""))).upper()

            if not text_val:
                continue  # Skip empty source cells

            if not final_val:
                cell_missing += 1
                stats["discrepancies"].append({
                    "type": "missing_value",
                    "row": i + 1,
                    "column": col,
                    "expected": text_val,
                    "actual": "(vacio)",
                })
            elif text_val == final_val:
                cell_matches += 1
            else:
                cell_mismatches += 1
                stats["discrepancies"].append({
                    "type": "value_mismatch",
                    "row": i + 1,
                    "column": col,
                    "expected": text_val,
                    "actual": final_val,
                })

    stats["comparison"] = {
        "matched_rows": matched,
        "cell_matches": cell_matches,
        "cell_mismatches": cell_mismatches,
        "cell_missing": cell_missing,
        "total_discrepancies": len(stats["discrepancies"]),
        "accuracy_pct": round(
            cell_matches / max(cell_matches + cell_mismatches + cell_missing, 1) * 100,
            1,
        ),
    }

    return stats


def print_comparison_summary(stats: dict[str, Any]) -> None:
    """Print human-friendly comparison summary."""
    print(f"\n{'=' * 70}")
    print(f"{C.BOLD}{C.HEADER}  RESUMEN DE COMPARACION PDF vs EXTRACCION{C.END}")
    print(f"{'=' * 70}")

    for source_name, label in [
        ("text_extraction", "Extraccion por Texto (Referencia)"),
        ("final_result", "Resultado Final del Sistema"),
    ]:
        s = stats[source_name]
        print(f"\n  {C.BOLD}{label}:{C.END}")
        print(f"    Filas: {s['row_count']}  |  Columnas: {s['col_count']}")
        if s.get("columns"):
            print(f"    Columnas: {', '.join(str(c) for c in s['columns'])}")

    if stats.get("common_columns"):
        print(f"\n  {C.BOLD}Columnas comunes:{C.END} {', '.join(stats['common_columns'])}")
    if stats.get("only_in_text"):
        print(f"  {C.YELLOW}Solo en texto:{C.END} {', '.join(stats['only_in_text'])}")
    if stats.get("only_in_final"):
        print(f"  {C.YELLOW}Solo en final:{C.END} {', '.join(stats['only_in_final'])}")

    if "comparison" in stats:
        comp = stats["comparison"]
        print(f"\n  {C.BOLD}Comparacion Celda-a-Celda:{C.END}")
        accuracy = comp["accuracy_pct"]
        color = C.GREEN if accuracy >= 95 else C.YELLOW if accuracy >= 80 else C.RED
        print(f"    {color}Precision: {accuracy}%{C.END}")
        print(f"    {C.GREEN}Celdas correctas: {comp['cell_matches']}{C.END}")
        if comp["cell_mismatches"]:
            print(f"    {C.YELLOW}Celdas diferentes: {comp['cell_mismatches']}{C.END}")
        if comp["cell_missing"]:
            print(f"    {C.RED}Celdas faltantes: {comp['cell_missing']}{C.END}")

        disc = stats.get("discrepancies", [])
        if disc:
            print(f"\n  {C.RED}{C.BOLD}Discrepancias: {len(disc)}{C.END}")
            for d in disc[:30]:
                dtype = d["type"]
                if dtype == "missing_value":
                    print(f"    {C.RED}> Fila {d['row']}, '{d['column']}': esperado '{_truncate(d['expected'], 40)}' -> (vacio){C.END}")
                elif dtype == "value_mismatch":
                    print(f"    {C.YELLOW}> Fila {d['row']}, '{d['column']}': '{_truncate(d['expected'], 25)}' != '{_truncate(d['actual'], 25)}'{C.END}")
                elif dtype in ("missing_row_in_final", "extra_row_in_final"):
                    kind = "falta en resultado" if "missing" in dtype else "extra en resultado"
                    print(f"    {C.RED}> Fila {d['row']}: {kind}{C.END}")
            if len(disc) > 30:
                print(f"    ... y {len(disc) - 30} mas")
        else:
            print(f"\n  {C.GREEN}{C.BOLD}[OK] Sin discrepancias -- extraccion perfecta al 100%{C.END}")

    print(f"\n{'=' * 70}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Comparar datos PDF vs extraccion")
    parser.add_argument("pdf_path", help="Ruta al archivo PDF")
    parser.add_argument("--json", action="store_true", help="Salida en formato JSON")
    parser.add_argument("--out", help="Guardar reporte en archivo JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Mostrar tablas completas")
    args = parser.parse_args()

    pdf_path = args.pdf_path
    if not os.path.isfile(pdf_path):
        print(f"Error: archivo no encontrado: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    print(f"{C.BOLD}Leyendo PDF: {pdf_path}{C.END}")

    # 1) Read PDF
    raw_text, pdf_tables = read_pdf(pdf_path)
    bank = _payment_detect_bank(raw_text)
    print(f"  Banco detectado: {C.CYAN}{bank or '(no detectado)'}{C.END}")
    print(f"  Texto raw: {len(raw_text)} caracteres")
    print(f"  Tablas PyMuPDF: {len(pdf_tables)} tabla(s)")

    # 2) BBVA Advanced Text Extraction (regex ground truth)
    text_rows = _extract_bbva_nomina_advanced_rows_from_text(raw_text)
    if not text_rows:
        text_rows = _extract_payment_table_rows_from_text(raw_text)
    text_score = _payment_rows_quality_score(text_rows) if text_rows else -999

    # 3) PDF Structural Extraction
    pdf_rows = _extract_payment_table_rows_from_pdf_tables(pdf_tables)
    pdf_score = (_payment_rows_quality_score(pdf_rows) + 20) if pdf_rows else -999

    print(f"\n  Calidad texto: {text_score}  |  Calidad PDF+20: {pdf_score}")

    # 4) Determine primary and backup, then merge
    if pdf_score >= text_score and pdf_rows:
        primary, backup = pdf_rows, text_rows
        primary_label = "PDF Structural"
    else:
        primary, backup = text_rows, pdf_rows
        primary_label = "Text Extraction"

    print(f"  Fuente primaria: {C.BOLD}{primary_label}{C.END}")

    merged_rows = primary
    if primary and backup and len(backup) >= 2:
        merged_rows = _merge_payment_rows_with_backup(primary, backup)

    # 5) Show raw tables
    if args.verbose or not args.json:
        print_table("1. Extraccion por Texto (BBVA Advanced)", text_rows)
        print_table("2. Extraccion Estructural (PyMuPDF)", pdf_rows)
        print_table("3. Resultado Fusionado (Merge)", merged_rows)

    # 6) Convert to canonical through the real pipeline
    text_objects = _payment_rows_to_objects(text_rows) if text_rows else []
    text_canonical_cols, text_canonical_rows = _payment_to_canonical_rows(bank, text_objects)

    merged_objects = _payment_rows_to_objects(merged_rows) if merged_rows else []
    final_canonical_cols, final_canonical_rows = _payment_to_canonical_rows(bank, merged_objects)

    display_map = _build_display_columns_map(merged_rows, bank)

    # 7) Show canonical tables
    if args.verbose or not args.json:
        print_canonical_table(
            "4. Canonico -- Texto (Referencia)",
            text_canonical_cols,
            text_canonical_rows,
        )
        print_canonical_table(
            "5. Canonico -- Resultado Final",
            final_canonical_cols,
            final_canonical_rows,
            display_map,
        )

    # 8) Compare
    stats = compare_canonical(
        text_canonical_cols,
        text_canonical_rows,
        final_canonical_cols,
        final_canonical_rows,
    )
    stats["bank"] = bank
    stats["pdf_path"] = pdf_path
    stats["primary_source"] = primary_label
    stats["text_quality_score"] = text_score
    stats["pdf_quality_score"] = pdf_score
    stats["display_columns"] = display_map

    if not args.json:
        print_comparison_summary(stats)

    if args.json:
        print(json.dumps(stats, indent=2, ensure_ascii=False))

    if args.out:
        out_path = args.out
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
        print(f"\n  Reporte guardado en: {out_path}")


if __name__ == "__main__":
    main()
