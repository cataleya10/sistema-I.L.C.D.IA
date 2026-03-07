"""Table extraction pipeline: generic + payment table processing."""

import re
import json
import os
import logging
import unicodedata
from datetime import datetime
from typing import Any

from .constants import *  # noqa: F403
from .common import *  # noqa: F403

logger = logging.getLogger(__name__)


def _export_all():
    import sys
    mod = sys.modules[__name__]
    return [n for n in dir(mod) if not n.startswith('__')]



def _table_line_gap_stats(line: dict) -> dict[str, float]:
    boxes = [
        box for box in line.get("boxes", [])
        if _normalize_table_cell_exact(box.get("text", ""))
    ]
    if len(boxes) < 2:
        return {"box_count": float(len(boxes)), "max_gap": 0.0, "large_gap_count": 0.0}

    sorted_boxes = sorted(boxes, key=lambda item: item["rect"][0])
    gaps: list[float] = []
    for idx in range(len(sorted_boxes) - 1):
        left = sorted_boxes[idx]
        right = sorted_boxes[idx + 1]
        gaps.append(float(right["rect"][0] - left["rect"][2]))

    max_gap = max(gaps) if gaps else 0.0
    large_gap_count = sum(1 for gap in gaps if gap >= _GENERIC_TABLE_LARGE_GAP_X)
    return {
        "box_count": float(len(sorted_boxes)),
        "max_gap": float(max_gap),
        "large_gap_count": float(large_gap_count),
    }


def _looks_like_generic_table_line(line: dict, min_large_gap: float = _GENERIC_TABLE_LARGE_GAP_X) -> bool:
    stats = _table_line_gap_stats(line)
    box_count = int(stats.get("box_count", 0))
    max_gap = float(stats.get("max_gap", 0.0))
    large_gap_count = int(stats.get("large_gap_count", 0))
    return (
        (box_count >= 2 and large_gap_count >= 1)          # standard: 2+ boxes, gap >= min_large_gap
        or (box_count >= 4 and max_gap >= 20.0)             # standard: 4+ boxes, gap >= 20px
        or (box_count >= 3 and max_gap >= 8.0)              # compact tables: 3+ boxes, any gap >= 8px
        or (box_count >= 2 and max_gap >= min_large_gap * 0.3)  # small images: 2+ boxes, 30% of threshold
    )


def _generic_column_anchors_from_line(line_boxes: list[dict]) -> list[dict]:
    if not line_boxes:
        return []

    # Defensive: filter boxes that have valid rect coordinates
    valid_boxes = [
        box for box in line_boxes
        if isinstance(box.get("rect"), (list, tuple))
        and len(box["rect"]) >= 4
        and all(isinstance(v, (int, float)) for v in box["rect"][:4])
    ]
    if not valid_boxes:
        return []

    sorted_boxes = sorted(valid_boxes, key=lambda box: box["rect"][0])
    grouped: list[list[dict]] = []
    cluster = [sorted_boxes[0]]
    for box in sorted_boxes[1:]:
        prev = cluster[-1]
        gap = box["rect"][0] - prev["rect"][2]
        if gap <= _GENERIC_TABLE_JOIN_GAP_X:
            cluster.append(box)
            continue
        grouped.append(cluster)
        cluster = [box]
    grouped.append(cluster)

    anchors: list[dict] = []
    for idx, group in enumerate(grouped[:_GENERIC_TABLE_MAX_COLS]):
        x1 = min(item["rect"][0] for item in group)
        x2 = max(item["rect"][2] for item in group)
        label = _normalize_table_cell_exact(" ".join(item.get("text", "") for item in group))
        anchors.append(
            {
                "x": (x1 + x2) / 2,
                "x1": x1,
                "x2": x2,
                "label": label if label else f"COLUMN_{idx + 1}",
            }
        )
    return anchors


# Maximum horizontal pixel distance a box can be from its nearest anchor
# before it is discarded as orphan noise.  Prevents far-off OCR boxes
# (footer fragments, page margins) from being force-assigned to columns.
_GENERIC_TABLE_ANCHOR_MAX_DIST = 120.0


def _generic_row_with_cells_by_anchors(
    row_boxes: list[dict],
    anchors: list[dict],
) -> tuple[list[str], list[dict]]:
    if not row_boxes or not anchors:
        return [], []

    columns: list[list[tuple[float, str, tuple[float, float, float, float]]]] = [[] for _ in anchors]
    for box in row_boxes:
        text = _normalize_table_cell_exact(box.get("text", ""))
        if not text:
            continue
        rect = box.get("rect")
        if not isinstance(rect, (list, tuple)) or len(rect) < 4:
            continue
        x1, y1, x2, y2 = rect[:4]
        center = (x1 + x2) / 2
        best_idx = min(
            range(len(anchors)),
            key=lambda idx: abs(center - anchors[idx]["x"]),
        )
        # Guard: skip boxes too far from any anchor (orphan noise)
        best_dist = abs(center - anchors[best_idx]["x"])
        if best_dist > _GENERIC_TABLE_ANCHOR_MAX_DIST:
            continue
        columns[best_idx].append((x1, text, (x1, y1, x2, y2)))

    row: list[str] = []
    cells: list[dict] = []
    for col in columns:
        if not col:
            row.append("")
            cells.append({"text": "", "bbox": None})
            continue
        col.sort(key=lambda item: item[0])
        text = _normalize_table_cell_exact(" ".join(item[1] for item in col))
        rects = [item[2] for item in col]
        bbox = [
            int(round(min(rect[0] for rect in rects))),
            int(round(min(rect[1] for rect in rects))),
            int(round(max(rect[2] for rect in rects))),
            int(round(max(rect[3] for rect in rects))),
        ]
        row.append(text)
        cells.append({"text": text, "bbox": bbox})
    return row, cells


def _extract_generic_tables_from_boxes(ocr_boxes) -> list[dict]:
    try:
        return _extract_generic_tables_from_boxes_impl(ocr_boxes)
    except Exception:
        logger.debug("_extract_generic_tables_from_boxes: error", exc_info=True)
        return []


def _extract_generic_tables_from_boxes_impl(ocr_boxes) -> list[dict]:
    # ── Adaptive y_tol: scale with median OCR box height ──────────────────
    # Fixed 20px works for bank-statement images but is too coarse for
    # small/compact tables (e.g. screenshots of Word docs).  Use 60% of the
    # median box height, clamped to [6, 50].
    _all_boxes_pre = _boxes_with_rect(ocr_boxes) or []
    _heights = [
        abs(b["rect"][3] - b["rect"][1])
        for b in _all_boxes_pre
        if isinstance(b.get("rect"), (list, tuple)) and len(b["rect"]) >= 4
        and abs(b["rect"][3] - b["rect"][1]) > 0
    ]
    if _heights:
        _median_h = sorted(_heights)[len(_heights) // 2]
        _y_tol = max(6, min(int(_median_h * 0.6), 50))
    else:
        _y_tol = 20

    # ── Adaptive large-gap threshold: 30% of median inter-word gap ─────────
    # _GENERIC_TABLE_LARGE_GAP_X=34 is calibrated for A4 bank docs (~300 DPI).
    # For compact / screenshot images use a smaller threshold so column gaps
    # inside small tables are still recognised.
    _all_widths = [
        abs(b["rect"][2] - b["rect"][0])
        for b in _all_boxes_pre
        if isinstance(b.get("rect"), (list, tuple)) and len(b["rect"]) >= 4
        and abs(b["rect"][2] - b["rect"][0]) > 0
    ]
    if _all_widths:
        _median_w = sorted(_all_widths)[len(_all_widths) // 2]
        _adaptive_gap = max(8.0, min(_median_w * 0.5, float(_GENERIC_TABLE_LARGE_GAP_X)))
    else:
        _adaptive_gap = float(_GENERIC_TABLE_LARGE_GAP_X)

    logger.info("[DIAG-BOX] boxes=%d y_tol=%d adaptive_gap=%.1f", len(_all_boxes_pre), _y_tol, _adaptive_gap)
    lines = _lines_text_from_boxes(ocr_boxes, y_tol=_y_tol)
    logger.info("[DIAG-BOX] lines_grouped=%d", len(lines))
    if not lines:
        return []

    table_lines: list[dict] = []
    all_multi_box_lines: list[dict] = []  # ALL lines with ≥2 boxes (for header recovery)
    all_any_box_lines: list[dict] = []    # ALL lines with ≥1 box (for header recovery from single-box lines)
    for idx, line in enumerate(lines):
        boxes = [
            box for box in line.get("boxes", [])
            if _normalize_table_cell_exact(box.get("text", ""))
        ]
        if not boxes:
            continue
        line_entry = {
            "index": idx,
            "y": float(line.get("y", 0.0) or 0.0),
            "boxes": boxes,
        }
        all_any_box_lines.append(line_entry)
        if len(boxes) < 2:
            # Single-box lines: log them for diagnostics, keep for header recovery
            preview = boxes[0].get("text", "")[:100]
            logger.info("[DIAG-BOX] single-box line idx=%d y=%.0f text=%s",
                        idx, line_entry["y"], preview)
            continue
        line_entry["is_table_like"] = _looks_like_generic_table_line({"boxes": boxes}, min_large_gap=_adaptive_gap)
        all_multi_box_lines.append(line_entry)
        if line_entry["is_table_like"]:
            table_lines.append(line_entry)
        else:
            preview = " | ".join(b.get("text", "") for b in boxes)[:100]
            stats = _table_line_gap_stats({"boxes": boxes})
            logger.info("[DIAG-BOX] skipped line idx=%d y=%.0f boxes=%d max_gap=%.1f preview=%s",
                        idx, line_entry["y"], len(boxes), stats.get("max_gap", 0), preview)

    logger.info("[DIAG-BOX] table_lines=%d all_multi_box=%d all_any_box=%d", len(table_lines), len(all_multi_box_lines), len(all_any_box_lines))
    if len(table_lines) < 2:
        return []

    # ── Adaptive block-gap: compute from median spacing between table lines ──
    # The fixed _GENERIC_TABLE_BLOCK_GAP_Y (36px) works for high-DPI bank
    # statements but is too small for screenshots of Word docs / educational
    # materials where row spacing can be 40-80px.  Use 2.5× median inter-line
    # gap (clamped) so rows within the same table stay grouped.
    _tl_gaps = [
        table_lines[i]["y"] - table_lines[i - 1]["y"]
        for i in range(1, len(table_lines))
        if table_lines[i]["y"] - table_lines[i - 1]["y"] > 0
    ]
    if _tl_gaps:
        _median_tl_gap = sorted(_tl_gaps)[len(_tl_gaps) // 2]
        _adaptive_block_gap = max(
            float(_GENERIC_TABLE_BLOCK_GAP_Y),
            min(_median_tl_gap * 2.5, 200.0),
        )
    else:
        _adaptive_block_gap = float(_GENERIC_TABLE_BLOCK_GAP_Y)

    logger.info("[DIAG-BOX] adaptive_block_gap=%.1f median_tl_gap=%.1f",
                _adaptive_block_gap, sorted(_tl_gaps)[len(_tl_gaps) // 2] if _tl_gaps else 0.0)

    # Log all inter-line gaps for diagnostics
    if _tl_gaps:
        logger.info("[DIAG-BOX] all_tl_gaps=%s", [round(g, 1) for g in _tl_gaps])

    blocks: list[list[dict]] = []
    current: list[dict] = []
    for line in table_lines:
        if not current:
            current = [line]
            continue
        gap = line["y"] - current[-1]["y"]
        if gap > _adaptive_block_gap:
            blocks.append(current)
            current = [line]
            continue
        current.append(line)
    if current:
        blocks.append(current)

    # ── Header recovery: prepend nearby non-table-like lines as headers ─────
    # Table header rows (e.g. "CÉDULA | NOMBRE | APELLIDOS | SEMESTRE | MATERIA")
    # may not pass the table-like gap heuristic because OCR boxes in header
    # rows are sometimes closer together, or all words may be merged into
    # a single OCR box.  For each block, look for any line just above the
    # block start that could be a column header row.
    _block_set_indices = {l["index"] for blk in blocks for l in blk}
    for blk in blocks:
        first_y = blk[0]["y"]
        block_col_count = max((len(l["boxes"]) for l in blk), default=0)
        if block_col_count < 2:
            continue
        # Find candidate header lines: not already in a block,
        # just above the block start (within adaptive_block_gap).
        # Check both multi-box AND single-box lines.
        best_header = None
        best_dist = float("inf")
        for cand in all_any_box_lines:
            if cand["index"] in _block_set_indices:
                continue
            dist = first_y - cand["y"]
            if dist < 0 or dist > _adaptive_block_gap:
                continue
            if dist >= best_dist:
                continue

            cand_boxes = cand["boxes"]
            if len(cand_boxes) >= 3:
                # Multi-box header candidate (e.g. each column name is its own box)
                best_header = cand
                best_dist = dist
            elif len(cand_boxes) >= 1:
                # Single (or two) box line: check if the text contains multiple
                # space-separated words that could be column headers.
                # E.g. "CEDULA NOMBRE APELLIDOS SEMESTRE MATERIA" as one box.
                all_text = " ".join(b.get("text", "") for b in cand_boxes).strip()
                words = [w for w in all_text.split() if len(w) >= 2]
                if len(words) >= block_col_count and len(words) >= 3:
                    # Synthesise individual boxes from words, reusing the rect
                    # from the original box for approximate positioning.
                    orig_rect = cand_boxes[0].get("rect", [0, 0, 0, 0])
                    x1 = orig_rect[0] if isinstance(orig_rect, (list, tuple)) and len(orig_rect) >= 4 else 0
                    x2 = orig_rect[2] if isinstance(orig_rect, (list, tuple)) and len(orig_rect) >= 4 else 100
                    total_w = x2 - x1 if x2 > x1 else 100
                    col_w = total_w / len(words)
                    synth_boxes = []
                    for wi, word in enumerate(words[:_GENERIC_TABLE_MAX_COLS]):
                        bx1 = x1 + wi * col_w
                        bx2 = bx1 + col_w
                        by1 = orig_rect[1] if isinstance(orig_rect, (list, tuple)) and len(orig_rect) >= 4 else 0
                        by2 = orig_rect[3] if isinstance(orig_rect, (list, tuple)) and len(orig_rect) >= 4 else 20
                        synth_boxes.append({
                            "text": word,
                            "rect": [bx1, by1, bx2, by2],
                        })
                    cand = {**cand, "boxes": synth_boxes}
                    best_header = cand
                    best_dist = dist

        if best_header is not None:
            blk.insert(0, best_header)
            _block_set_indices.add(best_header["index"])
            preview = " | ".join(b.get("text", "") for b in best_header["boxes"])[:100]
            logger.info("[DIAG-BOX] recovered header for block y=%.0f: idx=%d boxes=%d preview=%s",
                        first_y, best_header["index"], len(best_header["boxes"]), preview)

    # Log block structure
    for bi, blk in enumerate(blocks):
        ys = [l["y"] for l in blk]
        first_texts = [" | ".join(b.get("text", "") for b in blk[0]["boxes"])[:120]] if blk else []
        logger.info("[DIAG-BOX] block[%d] lines=%d y_range=[%.0f..%.0f] first_row_preview=%s",
                    bi, len(blk), min(ys), max(ys), first_texts[0] if first_texts else "?")

    logger.info("[DIAG-BOX] blocks_count=%d", len(blocks))

    tables: list[dict] = []
    seen_signatures: set[str] = set()
    for block in blocks:
        if len(block) < 2:
            continue

        # Prefer the first line of the block as column-anchor reference.
        # Table headers are virtually always the first row.  The previous
        # "widest line" heuristic picked data rows whose multi-word values
        # (e.g. "VELAZQUEZ CHABLE MAURO FRANCISCO") created phantom column
        # anchors.  Use the first line when it produces ≥ 3 anchors; fall
        # back to the widest line only when the first line is too narrow.
        first_line = block[0]
        first_anchors = _generic_column_anchors_from_line(first_line["boxes"])

        if len(first_anchors) >= 3:
            anchors = first_anchors
        else:
            ref_line = max(
                block,
                key=lambda item: (
                    int(_table_line_gap_stats({"boxes": item["boxes"]}).get("large_gap_count", 0)),
                    len(item["boxes"]),
                ),
            )
            anchors = _generic_column_anchors_from_line(ref_line["boxes"])
        if len(anchors) < 2:
            continue

        rows: list[list[str]] = []
        row_cells: list[list[dict]] = []
        for line in block[:_GENERIC_TABLE_MAX_ROWS]:
            row, cells = _generic_row_with_cells_by_anchors(line["boxes"], anchors)
            non_empty = sum(1 for cell in row if _normalize_table_cell_exact(cell))
            if non_empty < 2:
                continue
            rows.append(row[:_GENERIC_TABLE_MAX_COLS])
            row_cells.append(cells[:_GENERIC_TABLE_MAX_COLS])

        if len(rows) < 2:
            continue

        # Column-consistency check: if most data rows fill far fewer columns
        # than the header, the anchors likely came from a noisy line.
        # Strip trailing all-empty columns that no data row uses.
        header_len = len(rows[0]) if rows else 0
        if header_len > 3 and len(rows) > 2:
            data_rows = rows[1:]
            data_cells_list = row_cells[1:] if len(row_cells) > 1 else []
            # Find rightmost column that has data in any row
            max_used_col = 0
            for dr in data_rows:
                for ci in range(len(dr) - 1, -1, -1):
                    if _normalize_table_cell_exact(dr[ci]):
                        max_used_col = max(max_used_col, ci)
                        break
            # Trim phantom trailing columns that no data row uses
            trim_to = max_used_col + 1
            if trim_to < header_len:
                rows = [r[:trim_to] for r in rows]
                row_cells = [c[:trim_to] for c in row_cells]

        # Column-level Roman numeral correction: fix OCR misreads like
        # 111→III, 11→II, 1→I, I1→II in columns that contain Roman numerals.
        rows = _apply_roman_numeral_correction(rows)  # noqa: F405

        signature = _table_rows_signature(rows)
        if not signature or signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        rects = [
            box["rect"]
            for line in block
            for box in line["boxes"]
            if box.get("rect")
        ]
        if not rects:
            continue
        bbox = [
            int(round(min(rect[0] for rect in rects))),
            int(round(min(rect[1] for rect in rects))),
            int(round(max(rect[2] for rect in rects))),
            int(round(max(rect[3] for rect in rects))),
        ]

        tables.append(
            {
                "table_index": len(tables) + 1,
                "source": "ocr_boxes",
                "row_count": len(rows),
                "column_count": max((len(row) for row in rows), default=0),
                "bbox": bbox,
                "rows": rows,
                "cells": row_cells,
            }
        )
        if len(tables) >= _GENERIC_TABLE_MAX_TABLES:
            break

    return tables


def _extract_generic_tables_from_text(raw_text: str) -> list[dict]:
    try:
        return _extract_generic_tables_from_text_impl(raw_text)
    except Exception:
        logger.debug("_extract_generic_tables_from_text: error", exc_info=True)
        return []


def _extract_generic_tables_from_text_impl(raw_text: str) -> list[dict]:
    text = str(raw_text or "")
    if not text.strip():
        return []

    tables: list[dict] = []
    current_rows: list[list[str]] = []
    seen_signatures: set[str] = set()

    def flush_current():
        nonlocal current_rows
        if len(current_rows) < 2:
            current_rows = []
            return
        # Roman numeral correction before signature
        current_rows = _apply_roman_numeral_correction(current_rows)  # noqa: F405
        signature = _table_rows_signature(current_rows)
        if not signature or signature in seen_signatures:
            current_rows = []
            return
        seen_signatures.add(signature)
        rows = [row[:_GENERIC_TABLE_MAX_COLS] for row in current_rows[:_GENERIC_TABLE_MAX_ROWS]]
        cells = [
            [{"text": _normalize_table_cell_exact(cell), "bbox": None} for cell in row]
            for row in rows
        ]
        tables.append(
            {
                "table_index": len(tables) + 1,
                "source": "text_lines",
                "row_count": len(rows),
                "column_count": max((len(row) for row in rows), default=0),
                "bbox": None,
                "rows": rows,
                "cells": cells,
            }
        )
        current_rows = []

    for raw_line in text.splitlines():
        # Use light normalization (preserve multi-space gaps for column detection)
        line = re.sub(r"[ \t][ \t]+", lambda m: " " * len(m.group()), raw_line.strip())
        line_norm = _normalize_text(raw_line)
        if not line_norm:
            flush_current()
            if len(tables) >= _GENERIC_TABLE_MAX_TABLES:
                break
            continue

        if "\t" in line:
            parts = [part.strip() for part in line.split("\t") if part.strip()]
        else:
            parts = [part.strip() for part in re.split(r"\s{2,}", line) if part.strip()]

        if len(parts) < 2:
            flush_current()
            if len(tables) >= _GENERIC_TABLE_MAX_TABLES:
                break
            continue

        row = [_normalize_table_cell_exact(part) for part in parts[:_GENERIC_TABLE_MAX_COLS]]
        current_rows.append(row)
        if len(current_rows) >= _GENERIC_TABLE_MAX_ROWS:
            flush_current()
            if len(tables) >= _GENERIC_TABLE_MAX_TABLES:
                break

    flush_current()

    # ── Fallback: pattern-based column detection for single-space text ──
    # OCR output (PaddleOCR, Tesseract) often uses single spaces between
    # columns.  The above logic requires \t or \s{2,}.  This fallback
    # detects columns by recognising data-type transitions within each line:
    # text → number, number → percentage, etc.
    if not tables:
        pattern_tables = _extract_generic_tables_from_text_pattern_split(text)
        if pattern_tables:
            for pt in pattern_tables:
                sig = _table_rows_signature(pt.get("rows", []))
                if sig and sig not in seen_signatures:
                    seen_signatures.add(sig)
                    tables.append(pt)

    return tables[:_GENERIC_TABLE_MAX_TABLES]


# Pattern tokens that likely represent "data columns" in table text.
# Order matters: more specific patterns first to prevent greedy matching.
_DATA_TOKEN_PAT = re.compile(
    r"""
    \$[\d,.]+              # currency  ($89, $1,234.56)
    | [\d,.]+\s*%          # percentage (123%, 12.5 %)
    | \bYES\b              # boolean-like
    | \bNO\b
    | \bN/A\b
    | \bSI\b
    | \bNA\b
    | \b\d{1,3}(?:\s\d{3})+\b(?!\s*[%$])  # space-separated thousands (8 288) — not before %/$
    | \b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b    # comma-separated thousands (1,005)
    | \b\d+(?:\.\d+)?\b                    # plain numbers (123, 56.78)
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _extract_generic_tables_from_text_pattern_split(raw_text: str) -> list[dict]:
    """Detect tables in OCR text using data-type pattern boundaries.

    For lines like ``Lorem dolor siamet 8 288 123% YES $89``, finds
    transitions from words → data tokens and splits accordingly.
    """
    try:
        return _extract_generic_tables_from_text_pattern_split_impl(raw_text)
    except Exception:
        logger.debug("_extract_generic_tables_from_text_pattern_split: error", exc_info=True)
        return []


def _split_line_by_data_patterns(line: str) -> list[str] | None:
    """Split a line into label + data columns using pattern matching.

    Returns None if the line doesn't look like a table row.
    """
    matches = list(_DATA_TOKEN_PAT.finditer(line))
    if len(matches) < 2:
        return None

    parts: list[str] = []
    # Leading text before first data token = row label
    label = line[:matches[0].start()].strip()
    if label:
        parts.append(label)

    for m in matches:
        parts.append(m.group(0).strip())

    # Trailing text after last data token
    tail = line[matches[-1].end():].strip()
    if tail:
        parts.append(tail)

    if len(parts) < 3:
        return None
    return parts


def _extract_generic_tables_from_text_pattern_split_impl(raw_text: str) -> list[dict]:
    if not raw_text or not raw_text.strip():
        return []

    lines = [_normalize_text(line) for line in raw_text.splitlines() if _normalize_text(line)]
    if len(lines) < 3:
        return []

    # Detect header-like lines: lines with multiple words (potential column headers)
    # then consecutive lines with data patterns
    tables: list[dict] = []
    seen_signatures: set[str] = set()
    current_rows: list[list[str]] = []
    header_cols = 0

    def flush():
        nonlocal current_rows, header_cols
        if len(current_rows) < 2:
            current_rows = []
            header_cols = 0
            return
        # Normalize column count: pad or trim to max column count
        max_cols = max(len(r) for r in current_rows)
        norm_rows = []
        for r in current_rows[:_GENERIC_TABLE_MAX_ROWS]:
            while len(r) < max_cols:
                r.append("")
            norm_rows.append([_normalize_table_cell_exact(c) for c in r[:_GENERIC_TABLE_MAX_COLS]])
        sig = _table_rows_signature(norm_rows)
        if sig and sig not in seen_signatures:
            seen_signatures.add(sig)
            cells = [
                [{"text": _normalize_table_cell_exact(c), "bbox": None} for c in row]
                for row in norm_rows
            ]
            tables.append({
                "table_index": len(tables) + 1,
                "source": "text_pattern_split",
                "row_count": len(norm_rows),
                "column_count": max((len(r) for r in norm_rows), default=0),
                "bbox": None,
                "rows": norm_rows,
                "cells": cells,
            })
        current_rows = []
        header_cols = 0

    for line in lines:
        parts = _split_line_by_data_patterns(line)
        if parts and len(parts) >= 3:
            if not current_rows:
                # Check if the previous line could be a header
                # (handled below after loop)
                pass
            current_rows.append(parts)
            if len(current_rows) >= _GENERIC_TABLE_MAX_ROWS:
                flush()
        else:
            # Check if this could be a header for upcoming data rows
            if current_rows:
                flush()
            # Try to use this line as a header
            header_parts = [p.strip() for p in re.split(r"\s{2,}", line) if p.strip()]
            if len(header_parts) < 2:
                # Try single-space split for short-word headers
                words = line.split()
                if len(words) >= 3:
                    header_parts = words
            if len(header_parts) >= 2:
                # Tentatively store as potential header
                current_rows = [header_parts]
                header_cols = len(header_parts)
            else:
                flush()

    flush()

    return tables[:_GENERIC_TABLE_MAX_TABLES]



def _extract_all_table_payloads(base_text_raw: str, ocr_boxes) -> list[dict]:
    tables = _extract_generic_tables_from_boxes(ocr_boxes)
    if tables:
        return tables
    return _extract_generic_tables_from_text(base_text_raw)


def _pick_primary_table_from_payloads(tables: list[dict]) -> dict | None:
    if not tables:
        return None
    ranked = sorted(
        (
            table for table in tables
            if isinstance(table, dict)
            and isinstance(table.get("rows"), list)
            and len(table.get("rows", [])) >= 2
        ),
        key=lambda item: (
            int(item.get("row_count", 0)),
            int(item.get("column_count", 0)),
            int(item.get("row_count", 0)) * int(item.get("column_count", 0)),
        ),
        reverse=True,
    )
    return ranked[0] if ranked else None


def _payment_rows_plain_from_lines(lines: list[dict]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in lines:
        cells = [_normalize_table_cell(box.get("text", "")) for box in line.get("boxes", [])]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 3:
            rows.append(cells[:10])
    return rows


def _payment_table_column_anchors(header_boxes: list[dict]) -> list[dict]:
    if not header_boxes:
        return []
    # Defensive: filter boxes with valid rect coordinates
    valid_boxes = [
        b for b in header_boxes
        if isinstance(b.get("rect"), (list, tuple))
        and len(b["rect"]) >= 4
        and all(isinstance(v, (int, float)) for v in b["rect"][:4])
    ]
    if not valid_boxes:
        return []
    sorted_boxes = sorted(valid_boxes, key=lambda b: b["rect"][0])
    anchors: list[list[dict]] = []
    cluster = [sorted_boxes[0]]
    for box in sorted_boxes[1:]:
        prev = cluster[-1]
        prev_right = prev["rect"][2]
        curr_left = box["rect"][0]
        if curr_left - prev_right <= 12:
            cluster.append(box)
            continue
        anchors.append(cluster)
        cluster = [box]
    anchors.append(cluster)

    result: list[dict] = []
    for col_idx, group in enumerate(anchors):
        x1 = min(item["rect"][0] for item in group)
        x2 = max(item["rect"][2] for item in group)
        label = _normalize_table_cell(" ".join(item.get("text", "") for item in group))
        if not label:
            label = f"COLUMN_{col_idx + 1}"
        result.append({"x": (x1 + x2) / 2, "label": label})
    return result


def _payment_table_row_by_anchors(row_boxes: list[dict], anchors: list[dict]) -> list[str]:
    if not row_boxes or not anchors:
        return []
    columns: list[list[tuple[float, str]]] = [[] for _ in anchors]
    for box in row_boxes:
        text = _normalize_table_cell(box.get("text", ""))
        if not text:
            continue
        rect = box.get("rect")
        if not isinstance(rect, (list, tuple)) or len(rect) < 4:
            continue
        x1, _, x2, _ = rect[:4]
        center = (x1 + x2) / 2
        best_idx = min(
            range(len(anchors)),
            key=lambda idx: abs(center - anchors[idx]["x"]),
        )
        # Guard: skip boxes too far from any anchor (orphan noise)
        best_dist = abs(center - anchors[best_idx]["x"])
        if best_dist > _GENERIC_TABLE_ANCHOR_MAX_DIST:
            continue
        columns[best_idx].append((x1, text))

    row: list[str] = []
    for col in columns:
        if not col:
            row.append("")
            continue
        col.sort(key=lambda item: item[0])
        row.append(_normalize_table_cell(" ".join(text for _, text in col)))
    return row


_AMOUNT_IN_CELL_PAT = re.compile(r"^\$?\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))\b")

# Unified status vocabulary — used by all payment functions and shared with table_postprocess.py
_ALL_PAYMENT_STATUSES = (
    "EN PROCESO",  # multi-word first for regex alternation priority
    "PROCESADO", "APLICADO", "ACEPTADO", "TRANSMITIDO", "RECHAZADO",
    "DEVUELTO", "CANCELADO", "LIQUIDADO", "OPERADO",
    "PAGADO", "PENDIENTE", "DEPOSITADO", "AUTORIZADO",
)
_STATUS_WORDS_RE = "|".join(_ALL_PAYMENT_STATUSES)
_STATUS_PREFIX_PAT = re.compile(rf"^({_STATUS_WORDS_RE})\b\s*")
_STATUS_SEARCH_PAT = re.compile(rf"(?<!\w)({_STATUS_WORDS_RE})(?!\w)")


def _fix_payment_ocr_column_errors(structured_rows: list[list[str]]) -> list[list[str]]:
    """Post-proceso para el path de OCR boxes.

    Corrige cuatro errores comunes de alineación de columnas en PDFs BBVA:
    1. Monto en columna NOMBRE: extrae a IMPORTE si está vacío y limpia NOMBRE.
    2. Fila con NOMBRE inválido (solo monto): descarta la fila.
    3. ESTATUS embebido en CONCEPTO ("PROCESADO PAGO DE NOMINA"): separa estatus.
       Si el header OCR no tiene columna ESTATUS, se inyecta automáticamente.
    4. Nombres en mixed-case: uniforma a MAYÚSCULAS.
    5. Dedup headers de multi-página OCR ("CUENTA CUENTA" → "CUENTA").
    """
    if len(structured_rows) < 2:
        return structured_rows

    header = _dedup_header_row(list(structured_rows[0]))
    keys = [_normalize_keyword(h).lower() for h in header]

    def _ci(name: str) -> int:
        for i, k in enumerate(keys):
            if name in k:
                return i
        return -1

    importe_idx = _ci("importe")
    nombre_idx = _ci("nombre")
    estatus_idx = _ci("estatus") if _ci("estatus") != -1 else _ci("estado")
    concepto_idx = _ci("concepto")

    _has_apellido = any("apellido" in k for k in keys)

    # Fix pre-loop A: detectar columna merged "ESTATUS CONCEPTO" donde ambos índices
    # apuntan al mismo lugar. Normalizamos: renombramos la columna a solo CONCEPTO y
    # forzamos inyección de ESTATUS para que el path de inyección la maneje bien.
    if estatus_idx >= 0 and estatus_idx == concepto_idx and concepto_idx >= 0:
        header[concepto_idx] = "CONCEPTO"
        keys[concepto_idx] = "concepto"
        estatus_idx = -1

    # Fix pre-loop B: inyectar columna ESTATUS si el header OCR no la incluye.
    # Solo aplica a tablas de nómina BBVA (tienen columna APELLIDO); tablas tipo
    # Scotia/Scotiabank tienen estructura diferente y no deben modificarse.
    col_injected = False
    if estatus_idx < 0 and concepto_idx >= 0 and _has_apellido:
        insert_pos = concepto_idx
        header.insert(insert_pos, "ESTATUS")
        keys.insert(insert_pos, "estatus")
        estatus_idx = insert_pos
        concepto_idx += 1
        if importe_idx >= insert_pos:
            importe_idx += 1
        if nombre_idx >= insert_pos:
            nombre_idx += 1
        col_injected = True

    fixed: list[list[str]] = [header]
    for orig_row in structured_rows[1:]:
        # Expandir fila con ESTATUS vacío cuando la columna fue inyectada
        if col_injected:
            ins = estatus_idx
            row = list(orig_row[:ins]) + [""] + list(orig_row[ins:])
        else:
            row = list(orig_row)

        # Fix 1: monto en columna nombre
        if 0 <= nombre_idx < len(row):
            nombre_val = row[nombre_idx].strip()
            m = _AMOUNT_IN_CELL_PAT.match(nombre_val)
            if m:
                amount_str = m.group(0).strip()
                name_after = nombre_val[m.end():].strip()
                if 0 <= importe_idx < len(row) and not row[importe_idx].strip():
                    row[importe_idx] = amount_str
                row[nombre_idx] = name_after

        # Fix 2: validar nombre — si tiene un valor inválido no-vacío, limpiar
        # pero NUNCA descartar la fila completa (los demás campos son valiosos).
        if 0 <= nombre_idx < len(row):
            nombre_after_fix = row[nombre_idx].strip()
            if nombre_after_fix and not _looks_like_person_name(nombre_after_fix):
                # Solo limpiar el nombre si parece basura (números, símbolos);
                # NO descartar la fila — cuenta, referencia, importe siguen siendo válidos.
                if sum(1 for ch in nombre_after_fix if ch.isdigit()) > len(nombre_after_fix) * 0.5:
                    row[nombre_idx] = ""

        # Fix 3: estatus embebido en concepto.
        # Siempre limpiar concepto cuando empieza con palabra de estatus.
        # Si estatus está vacío, también se extrae de ahí.
        if 0 <= concepto_idx < len(row) and estatus_idx >= 0 and concepto_idx != estatus_idx:
            concepto_val = row[concepto_idx].strip()
            sm = _STATUS_PREFIX_PAT.match(concepto_val)
            if sm:
                while len(row) <= max(estatus_idx, concepto_idx):
                    row.append("")
                if not row[estatus_idx].strip():
                    row[estatus_idx] = sm.group(1)
                # Siempre limpiar el prefijo de estatus del concepto
                row[concepto_idx] = concepto_val[sm.end():].strip() or "PAGO DE NOMINA"

        # Fix 3b: fallback — si estatus sigue vacío, buscar palabra de estatus en la fila
        if 0 <= estatus_idx < len(row) and not row[estatus_idx].strip() and _has_apellido:
            row_joined = " ".join(str(c or "") for c in row)
            m_st = _STATUS_SEARCH_PAT.search(row_joined)
            if m_st:
                row[estatus_idx] = m_st.group(1)

        # Fix 4: uniformar nombres a MAYÚSCULAS (OCR puede devolver mixed-case)
        for col_idx in [nombre_idx, _ci("apellido")]:
            if 0 <= col_idx < len(row) and row[col_idx]:
                row[col_idx] = row[col_idx].upper()

        fixed.append(row)
    return fixed


def _extract_payment_table_rows_from_boxes(ocr_boxes) -> list[list[str]]:
    try:
        return _extract_payment_table_rows_from_boxes_impl(ocr_boxes)
    except Exception:
        logger.debug("_extract_payment_table_rows_from_boxes: error", exc_info=True)
        return []


def _extract_payment_table_rows_from_boxes_impl(ocr_boxes) -> list[list[str]]:
    lines = _lines_text_from_boxes(ocr_boxes)
    rows = _payment_rows_plain_from_lines(lines)

    if not rows:
        return []

    header_idx = next((idx for idx, row in enumerate(rows) if _looks_like_payment_table_header(row)), None)
    if header_idx is None:
        return [row for row in rows if _looks_like_payment_table_data(row)][:500]

    header_boxes = [
        box for box in lines[header_idx].get("boxes", [])
        if _normalize_table_cell(box.get("text", ""))
    ]
    anchors = _payment_table_column_anchors(header_boxes)
    if len(anchors) >= 3:
        structured_rows: list[list[str]] = []
        header_row = [_normalize_table_cell(anchor.get("label", "")) for anchor in anchors]
        if _looks_like_payment_table_header(header_row):
            structured_rows.append(header_row[:10])

        for line in lines[header_idx + 1:]:
            if len(structured_rows) >= 500:
                break
            row_boxes = [
                box for box in line.get("boxes", [])
                if _normalize_table_cell(box.get("text", ""))
            ]
            if len(row_boxes) < 2:
                continue
            row = _payment_table_row_by_anchors(row_boxes, anchors)[:10]
            if _is_payment_table_footer(row) and len(structured_rows) > 1:
                break
            if _looks_like_payment_table_header(row):
                # Solo incluir el header una vez; headers repetidos (páginas 2-N) se saltan
                if not structured_rows:
                    structured_rows.append(row)
                continue
            if _looks_like_payment_table_data(row):
                structured_rows.append(row)

        if len(structured_rows) > 1:
            return _fix_payment_ocr_column_errors(structured_rows)

    selected = [rows[header_idx]]
    for row in rows[header_idx + 1:]:
        if len(selected) >= 500:
            break
        if _is_payment_table_footer(row) and len(selected) > 1:
            break
        if _looks_like_payment_table_header(row):
            # Headers repetidos de páginas siguientes: saltar silenciosamente
            continue
        if _looks_like_payment_table_data(row):
            selected.append(row)

    if len(selected) > 1:
        return _fix_payment_ocr_column_errors(selected)
    # Refuerzo: si solo hay una fila, intentar heurísticamente separar encabezado y datos
    if len(selected) == 1:
        row = selected[0]
        # Si la fila tiene muchas columnas, partir en dos: encabezado y datos
        if len(row) >= 6:
            mid = len(row) // 2
            header = row[:mid]
            data = row[mid:]
            if len(header) == len(data):
                return [header, data]
    return []


_ADVANCED_NOMINA_TABLE_HEADER = [
    "CUENTA",
    "REFERENCIA",
    "IMPORTE",
    "NOMBRE",
    "APELLIDO PATERNO",
    "APELLIDO MATERNO",
    "ESTATUS",
    "CONCEPTO",
]


def _split_payment_name_parts(full_name: str) -> tuple[str, str, str]:
    normalized = _normalize_name(full_name)
    if not normalized:
        return "", "", ""
    tokens = [token for token in normalized.split() if token]
    if len(tokens) <= 2:
        return normalized, "", ""
    if len(tokens) == 3:
        return tokens[0], tokens[1], tokens[2]
    return " ".join(tokens[:-2]), tokens[-2], tokens[-1]


def _extract_bbva_nomina_advanced_rows_from_text(raw_text: str) -> list[list[str]]:
    try:
        return _extract_bbva_nomina_advanced_rows_impl(raw_text)
    except Exception:
        logger.debug("_extract_bbva_nomina_advanced_rows: error", exc_info=True)
        return []


def _extract_bbva_nomina_advanced_rows_impl(raw_text: str) -> list[list[str]]:
    folded = _ascii_fold(str(raw_text or "")).upper()
    if "NOMINA" not in folded:
        return []

    lines = [_ascii_fold(_normalize_text(line)).upper() for line in str(raw_text or "").splitlines() if _normalize_text(line)]
    if not lines:
        return []

    # La referencia puede venir con un espacio OCR intermedio (ej: "16202601151343405812 63")
    # _REF_PAT acepta dígitos con un espacio interno opcional para tolerar ese artefacto
    _REF_PAT = r"\d{10,28}(?:\s+\d{1,6})?"
    row_pattern = re.compile(
        r"\b(?P<cuenta>\d{10,24})\s+"
        r"(?P<referencia>" + _REF_PAT + r")\s+"
        r"(?P<importe>\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))\s+"
        r"(?P<nombre>[A-ZÑÁÉÍÓÚÜ .'\'\-]{4,120}?)"
        r"(?=\s+\d{10,24}\s+" + _REF_PAT + r"\s+\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})"
        rf"|\s+(?:{_STATUS_WORDS_RE})\b"
        r"|\s*$)"
    )
    status_pattern = _STATUS_SEARCH_PAT
    concept_pattern = re.compile(r"\b(PAGO(?:\s+DE)?\s+NOMINA|ABONO\s+NOMINA)\b")

    global_status_match = status_pattern.search(folded)
    global_status = _normalize_table_cell(global_status_match.group(1)) if global_status_match else ""
    global_concept_match = concept_pattern.search(folded)
    global_concept = _normalize_table_cell(global_concept_match.group(1)) if global_concept_match else ""

    rows: list[list[str]] = []
    seen: set[tuple[str, str, str]] = set()
    for line in lines:
        if "CUENTA" in line and "REFERENCIA" in line and "IMPORTE" in line and "NOMBRE" in line:
            continue
        line_status_match = status_pattern.search(line)
        line_status = _normalize_table_cell(line_status_match.group(1)) if line_status_match else global_status
        line_concept_match = concept_pattern.search(line)
        line_concept = _normalize_table_cell(line_concept_match.group(1)) if line_concept_match else global_concept

        for match in row_pattern.finditer(line):
            cuenta = _normalize_numeric_field(match.group("cuenta"))
            # Elimina espacio OCR interno en la referencia (ej: "16202601...812 63" → "...81263")
            ref_raw = re.sub(r"\s+", "", match.group("referencia"))
            referencia = _normalize_value_for_key("referencia", ref_raw)
            importe = _normalize_payment_amount(match.group("importe"))
            full_name = _normalize_name(match.group("nombre"))
            if not _looks_like_person_name(full_name):
                continue

            tail = line[match.end():]
            tail_status_match = status_pattern.search(tail)
            estatus = _normalize_table_cell(tail_status_match.group(1)) if tail_status_match else line_status

            tail_concept_match = concept_pattern.search(tail)
            concepto = _normalize_table_cell(tail_concept_match.group(1)) if tail_concept_match else line_concept

            if not cuenta or not referencia or not importe:
                continue

            nombre, apellido_paterno, apellido_materno = _split_payment_name_parts(full_name)
            if not nombre:
                continue

            dedupe_key = (cuenta, referencia, importe)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            rows.append(
                [
                    cuenta,
                    referencia,
                    importe,
                    nombre,
                    apellido_paterno,
                    apellido_materno,
                    estatus,
                    concepto or line_concept or global_concept or "PAGO DE NOMINA",
                ]
            )

    if len(rows) < 1:
        return []

    return [_ADVANCED_NOMINA_TABLE_HEADER, *rows[:500]]


# ---------------------------------------------------------------------------
# BBVA "Dispersión de Pago de Nómina" – comprobante KV pages extractor
# ---------------------------------------------------------------------------

def _extract_bbva_nomina_comprobante_rows(raw_text: str) -> list[list[str]]:
    """Extract rows from individual comprobante KV pages in BBVA nomina documents.

    These documents have a summary table on the first page (handled by
    ``_extract_bbva_nomina_advanced_rows``) followed by one comprobante page
    per beneficiary with key-value pairs like::

        DATOS DEL BENEFICIARIO
        Número de cuenta de Abono:56775171706
        Referencia:1620260115134903934215
        Importe:$3,000.00 MXN
        Estatus:Procesado
        Concepto:Pago de Nómina
        Nombre:PATRICIA
        Apellido paterno:CRUZ
        Apellido materno:TEJERO
    """
    try:
        return _extract_bbva_nomina_comprobante_rows_impl(raw_text)
    except Exception:
        logger.debug("_extract_bbva_nomina_comprobante_rows: error", exc_info=True)
        return []


_NOMINA_KV_LABEL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("cuenta",    re.compile(r"(?:N[Uú]MERO\s+DE\s+CUENTA\s+DE\s+ABONO|CUENTA\s+DE\s+ABONO|CUENTA\s+ABONO)\s*:\s*(.+)", re.IGNORECASE)),
    ("referencia", re.compile(r"REFERENCIA\s*:\s*(.+)", re.IGNORECASE)),
    ("importe",   re.compile(r"IMPORTE\s*:\s*(.+)", re.IGNORECASE)),
    ("estatus",   re.compile(r"ESTATUS\s*:\s*(.+)", re.IGNORECASE)),
    ("concepto",  re.compile(r"CONCEPTO\s*:\s*([^:]+?)(?:\s*$)", re.IGNORECASE)),
    ("nombre",    re.compile(r"NOMBRE\s*:\s*(.+)", re.IGNORECASE)),
    ("apellido_paterno", re.compile(r"APELLIDO\s+PATERNO\s*:\s*(.+)", re.IGNORECASE)),
    ("apellido_materno", re.compile(r"APELLIDO\s+MATERNO\s*:\s*(.+)", re.IGNORECASE)),
]


def _extract_bbva_nomina_comprobante_rows_impl(raw_text: str) -> list[list[str]]:
    if not raw_text:
        return []
    folded = _ascii_fold(raw_text).upper()
    # Guard: must look like a BBVA "Dispersión de Nómina" document with comprobante pages
    if "NOMINA" not in folded:
        return []
    if "DISPERSION" not in folded and "DISPERSI" not in folded:
        return []
    if "DATOS DEL BENEFICIARIO" not in _ascii_fold(raw_text).upper():
        return []

    # Split text on "DATOS DEL BENEFICIARIO" to get one segment per employee
    segments = re.split(r"DATOS\s+DEL\s+BENEFICIARIO", raw_text, flags=re.IGNORECASE)
    if len(segments) < 2:
        return []  # No beneficiary sections found

    rows: list[list[str]] = []
    seen: set[tuple[str, str, str]] = set()

    for seg in segments[1:]:  # Skip preamble before first DATOS DEL BENEFICIARIO
        lines = [line.strip() for line in seg.splitlines() if line.strip()]
        # Only parse lines up to the next "Comprobante" / "DATOS DEL CLIENTE" marker
        kv: dict[str, str] = {}
        for line in lines:
            # Stop if we hit a new section marker
            line_upper = _ascii_fold(line).upper()
            if "COMPROBANTE" in line_upper and "OPERACION" in line_upper:
                break
            if "DATOS DEL CLIENTE" in line_upper:
                break
            for field_name, pattern in _NOMINA_KV_LABEL_PATTERNS:
                m = pattern.search(line)
                if m and field_name not in kv:
                    kv[field_name] = m.group(1).strip()
                    break

        cuenta = _normalize_numeric_field(kv.get("cuenta", ""))
        referencia = _normalize_value_for_key("referencia", kv.get("referencia", ""))
        importe = _normalize_payment_amount(kv.get("importe", ""))
        estatus = _normalize_table_cell(kv.get("estatus", ""))
        concepto = _normalize_table_cell(kv.get("concepto", ""))
        nombre = _normalize_name(kv.get("nombre", ""))
        apellido_paterno = _normalize_name(kv.get("apellido_paterno", ""))
        apellido_materno = _normalize_name(kv.get("apellido_materno", ""))

        # Quality gate: at least cuenta + importe + nombre
        if not cuenta or not importe or not nombre:
            continue

        dedupe_key = (cuenta, referencia, importe)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        rows.append([
            cuenta,
            referencia,
            importe,
            nombre,
            apellido_paterno,
            apellido_materno,
            estatus,
            concepto or "PAGO DE NOMINA",
        ])

    if not rows:
        return []

    logger.info("[BBVA_NOMINA_COMPROBANTE] extracted %d rows from comprobante KV pages", len(rows))
    return [_ADVANCED_NOMINA_TABLE_HEADER, *rows[:500]]


_ALL_STATUSES_SET = frozenset(_ALL_PAYMENT_STATUSES)


def _smart_split_narrow_line(line: str) -> list[str]:
    """Pattern-aware split for lines where columns are separated by single spaces.

    Splits on token-type transitions: numeric ↔ alpha ↔ status keyword.
    """
    tokens = line.split()
    if len(tokens) < 3:
        return [line]
    cells: list[str] = []
    buf: list[str] = []
    prev_type: str | None = None
    for tok in tokens:
        upper = tok.upper().strip(".,;:-")
        if upper in _ALL_STATUSES_SET:
            cur_type = "status"
        elif re.match(r"^\$?\d[\d,OIL]*\.?\d*$", tok, re.IGNORECASE):
            cur_type = "num"
        else:
            cur_type = "alpha"
        if prev_type is not None and cur_type != prev_type:
            cells.append(" ".join(buf))
            buf = [tok]
        else:
            buf.append(tok)
        prev_type = cur_type
    if buf:
        cells.append(" ".join(buf))
    return cells if len(cells) >= 3 else [line]


def _extract_payment_table_rows_from_text(raw_text: str) -> list[list[str]]:
    if not raw_text:
        return []
    try:
        advanced_rows = _extract_bbva_nomina_advanced_rows_from_text(raw_text)
        if advanced_rows:
            # Also try extracting from comprobante KV pages and merge unique rows
            comprobante_rows = _extract_bbva_nomina_comprobante_rows(raw_text)
            if comprobante_rows and len(comprobante_rows) > 1:
                # Build set of existing (cuenta, referencia, importe) from advanced rows
                existing = set()
                for row in advanced_rows[1:]:  # skip header
                    if len(row) >= 3:
                        existing.add((row[0], row[1], row[2]))
                for row in comprobante_rows[1:]:  # skip header
                    if len(row) >= 3:
                        key = (row[0], row[1], row[2])
                        if key not in existing:
                            advanced_rows.append(row)
                            existing.add(key)
            return advanced_rows
    except Exception:
        logger.debug("_extract_payment_table_rows_from_text: bbva advanced failed", exc_info=True)

    # Try BBVA nomina comprobante KV pages as standalone (no summary table found)
    try:
        comprobante_rows = _extract_bbva_nomina_comprobante_rows(raw_text)
        if comprobante_rows:
            return comprobante_rows
    except Exception:
        logger.debug("_extract_payment_table_rows_from_text: bbva nomina comprobante failed", exc_info=True)

    # Try BBVA vertical key-value receipt BEFORE generic text splitting so
    # that "Grupo Pago Mismo Banco" / comprobante documents are not polluted
    # by the generic splitter picking up footer fragments as table rows.
    try:
        _normalized_lines_early = [
            _ascii_fold(_normalize_text(line)).upper()
            for line in raw_text.splitlines()
            if _normalize_text(line)
        ]
        bbva_receipt_rows = _extract_bbva_transfer_receipt_rows(_normalized_lines_early, raw_text)
        if bbva_receipt_rows:
            return bbva_receipt_rows
    except Exception:
        logger.debug("_extract_payment_table_rows_from_text: bbva receipt failed", exc_info=True)

    rows: list[list[str]] = []
    narrow_candidates: list[list[str]] = []
    for raw_line in raw_text.splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        if "\t" in line:
            parts = [part.strip() for part in line.split("\t") if part.strip()]
        else:
            parts = [part.strip() for part in re.split(r"\s{2,}", line) if part.strip()]
        # Fallback: pattern-aware split for narrow columns separated by single space
        used_narrow = False
        if len(parts) < 3:
            narrow_parts = _smart_split_narrow_line(line)
            if len(narrow_parts) >= 3:
                parts = narrow_parts
                used_narrow = True
        cells = [_normalize_table_cell(part) for part in parts if part.strip()]
        if len(cells) < 3:
            continue
        if _looks_like_payment_table_header(cells) or _looks_like_payment_table_data(cells):
            if used_narrow:
                narrow_candidates.append(cells[:10])
            else:
                rows.append(cells[:10])
        if len(rows) >= 500:
            break
    # Only use narrow-split rows when 2+ found (real narrow-column table, not a one-off)
    if len(narrow_candidates) >= 2:
        rows.extend(narrow_candidates)
    # Dedup rows to avoid multi-page OCR duplicates
    if rows:
        seen_sigs: set[str] = set()
        deduped: list[list[str]] = []
        for r in rows:
            sig = "|".join(str(c or "").strip() for c in r)
            if sig not in seen_sigs:
                seen_sigs.add(sig)
                deduped.append(r)
        rows = deduped
    # A useful payment table needs at least 2 rows (header + data).
    # Fall through to compact-text extractor if we don't have enough.
    if len(rows) >= 2:
        return rows
    # Refuerzo: si solo hay una fila, intentar heurísticamente separar encabezado y datos
    if len(rows) == 1:
        row = rows[0]
        if len(row) >= 6:
            mid = len(row) // 2
            header = row[:mid]
            data = row[mid:]
            if len(header) == len(data):
                return [header, data]
    return _extract_payment_table_rows_from_compact_text(raw_text)


def _extract_scotia_transfer_rows(lines: list[str]) -> list[list[str]]:
    try:
        return _extract_scotia_transfer_rows_impl(lines)
    except Exception:
        logger.debug("_extract_scotia_transfer_rows: error", exc_info=True)
        return []


def _extract_scotia_transfer_rows_impl(lines: list[str]) -> list[list[str]]:
    if not lines:
        return []
    full = " ".join(lines)
    if "SCOTIABANK" not in full and "TRANSFERENCIA DE ARCHIVOS" not in full:
        return []
    if "DA ALTA" not in full and "DAALTA" not in full:
        return []

    header = [
        "TIPO DE REGISTRO",
        "TIPO DE MOVIMIENTO (PAGO)",
        "IMPORTE",
        "FECHA DE APLICACION",
        "CLAVE DEL BENEFICIARIO",
        "NOMBRE DEL BENEFICIARIO",
        "REFERENCIA",
        "NO. CUENTA BENEFICIARIO",
        "NO. BANCO RECEPTOR",
        "DIAS DE VIGENCIA",
        "CONCEPTO PAGO",
    ]

    rows: list[list[str]] = []
    seen_keys: set[tuple[str, ...]] = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        key = _normalize_keyword(line)
        if "DAALTA" not in key and "DA ALTA" not in line:
            i += 1
            continue

        block: list[str] = []
        j = i
        while j < len(lines) and len(block) < 25:
            curr = lines[j]
            curr_key = _normalize_keyword(curr)
            if j > i and "DAALTA" in curr_key:
                break
            if any(token in curr for token in ("TOTAL DE MOVIMIENTOS", "CANTIDAD DE MOVIMIENTOS", "IMPORTE DE MOVIMIENTOS")):
                break
            block.append(curr)
            j += 1

        joined = " ".join(block)
        amount_match = re.search(r"\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})", joined)
        date_match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", joined)
        clave_match = re.search(r"\b[A-Z]\d{2,6}\b", joined)
        cuenta_match = re.search(r"\b\d{18,24}\b", joined)
        concepto_match = re.search(r"\bPAG[O0]\s*0?\d{1,4}\b", joined)
        movimiento_match = re.search(r"\b\d{2}\s+ABONO\s+EN\s+CUENTA\b", joined)
        referencia_match = re.search(r"\b([0-9OIL]{1,8})\b(?=\s+\d{18,24})", joined)

        cuenta = cuenta_match.group(0) if cuenta_match else ""
        banco = ""
        vigencia = ""
        if cuenta:
            try:
                post = joined.split(cuenta, 1)[1]
                trailing = re.search(r"\b(\d{1,2})\b(?:\s+\b(\d)\b)?", post)
                if trailing:
                    banco = trailing.group(1) or ""
                    vigencia = trailing.group(2) or ""
            except (ValueError, IndexError):
                pass

        beneficiary_parts: list[str] = []
        for raw in block:
            candidate = _normalize_text(raw).upper()
            if not candidate:
                continue
            if any(
                token in candidate
                for token in (
                    "DA ALTA",
                    "ABONO EN",
                    "TIPO DE",
                    "MOVIMIENTO",
                    "IMPORTE",
                    "FECHA DE",
                    "CLAVE DEL",
                    "REFERENCIA",
                    "CUENTA",
                    "NO. CUENTA",
                    "NO.BANCO",
                    "DIAS DE",
                    "CONCEPTO",
                )
            ):
                continue
            if re.fullmatch(r"\d{1,3}", candidate):
                continue
            if re.fullmatch(r"\d{18,24}(?:\s+\d{1,2})?(?:\s+\d)?", candidate):
                continue
            if re.search(r"\$", candidate) or re.search(r"\d{2}/\d{2}/\d{4}", candidate):
                continue
            if re.fullmatch(r"[A-Z]\d{2,6}", candidate):
                continue
            if re.fullmatch(r"PAG[O0]\d{1,4}", candidate):
                continue
            normalized_name = _normalize_name(candidate)
            if not normalized_name:
                continue
            if normalized_name not in beneficiary_parts:
                beneficiary_parts.append(normalized_name)

        beneficiary = " ".join(beneficiary_parts[:4]).strip()
        beneficiary = re.sub(r"^CUENTA\s+", "", beneficiary)
        beneficiary = re.sub(r"\s+\b1\b$", "", beneficiary)
        row = [
            "DA ALTA",
            _normalize_table_cell(movimiento_match.group(0) if movimiento_match else "04 ABONO EN CUENTA"),
            _normalize_table_cell(amount_match.group(0) if amount_match else ""),
            date_match.group(0) if date_match else "",
            clave_match.group(0) if clave_match else "",
            beneficiary,
            _normalize_numeric_field(referencia_match.group(1)) if referencia_match else "",
            cuenta,
            banco,
            vigencia,
            _normalize_table_cell(concepto_match.group(0) if concepto_match else ""),
        ]
        # Dedup key includes importe + clave + cuenta + concepto for precision
        dedup_key = (row[2], row[4], row[7], row[10])
        if row[7] and (row[2] or row[3] or row[10]) and dedup_key not in seen_keys:
            seen_keys.add(dedup_key)
            rows.append(row)
        i = j

    if not rows:
        return []
    if len(rows) > 500:
        logger.warning("_extract_scotia_transfer_rows: truncating %d rows to 500", len(rows))
    summary_rows = _extract_scotia_summary_rows(lines)
    return [header, *rows[:500], *summary_rows]


def _extract_scotia_summary_rows(lines: list[str]) -> list[list[str]]:
    if not lines:
        return []
    extracted: list[list[str]] = []

    normal_values = _extract_scotia_summary_block_values(lines, total=False)
    if normal_values:
        extracted.append(
            [
                "CANTIDAD DE MOVIMIENTOS ALTAS",
                "IMPORTE DE MOVIMIENTO ALTAS",
                "CANTIDAD DE MOVIMIENTOS BAJAS",
                "IMPORTE DE MOVIMIENTOS BAJAS",
            ]
        )
        extracted.append(normal_values)

    total_values = _extract_scotia_summary_block_values(lines, total=True)
    if total_values:
        extracted.append(
            [
                "TOTAL CANTIDAD DE MOVIMIENTOS ALTAS",
                "TOTAL IMPORTE DE MOVIMIENTO ALTAS",
                "TOTAL CANTIDAD DE MOVIMIENTOS BAJAS",
                "TOTAL IMPORTE DE MOVIMIENTOS BAJAS",
            ]
        )
        extracted.append(total_values)

    return extracted


def _extract_scotia_summary_block_values(lines: list[str], total: bool) -> list[str]:
    if not lines:
        return []
    full = " ".join(lines)
    if total:
        pattern = re.search(
            r"TOTAL\s+CANTIDAD\s+DE\s+MOVIMIENTO[S]?\s+ALTAS\s+"
            r"TOTAL\s+IMPORTE\s+DE\s+MOVIMIENTO[S]?\s+ALTAS\s+"
            r"TOTAL\s+CANTIDAD\s+DE\s+MOVIMIENTO[S]?\s+BAJAS\s+"
            r"TOTAL\s+IMPORTE\s+DE\s+MOVIMIENTO[S]?\s+BAJAS(?:\s+[A-Z]+){0,3}\s+"
            r"([0-9OIL]{1,6})\s+(\$?\s*[0-9OIL.,]{1,24})\s+([0-9OIL]{1,6})\s+(\$?\s*[0-9OIL.,]{1,24})",
            full,
        )
    else:
        pattern = re.search(
            r"CANTIDAD\s+DE\s+MOVIMIENTO[S]?\s+ALTAS\s+"
            r"IMPORTE\s+DE\s+MOVIMIENTO[S]?\s+ALTAS\s+"
            r"CANTIDAD\s+DE\s+MOVIMIENTO[S]?\s+BAJAS\s+"
            r"IMPORTE\s+DE\s+MOVIMIENTO[S]?\s+BAJAS(?:\s+[A-Z]+){0,3}\s+"
            r"([0-9OIL]{1,6})\s+(\$?\s*[0-9OIL.,]{1,24})\s+([0-9OIL]{1,6})\s+(\$?\s*[0-9OIL.,]{1,24})",
            full,
        )
    if pattern:
        return [
            _normalize_payment_count(pattern.group(1)),
            _normalize_payment_amount(pattern.group(2)),
            _normalize_payment_count(pattern.group(3)),
            _normalize_payment_amount(pattern.group(4)),
        ]

    anchor = "TOTAL CANTIDAD DE MOVIMIENTOS ALTAS" if total else "CANTIDAD DE MOVIMIENTOS ALTAS"
    start_idx = -1
    for idx, line in enumerate(lines):
        if anchor in line:
            start_idx = idx
            break
    if start_idx < 0:
        return []

    amount_values: list[str] = []
    count_values: list[str] = []
    amount_re = re.compile(r"\$?\s*[0-9OIL]{1,3}(?:[.,][0-9OIL]{3})*(?:[.,][0-9OIL]{2})")
    for raw_line in lines[start_idx : min(len(lines), start_idx + 30)]:
        line = raw_line.strip()
        if not line:
            continue
        if any(token in line for token in ("CANTIDAD", "IMPORTE", "MOVIMIENTO", "BAJAS", "ALTAS", "TOTAL")):
            continue
        for amount in amount_re.findall(line):
            normalized_amount = _normalize_payment_amount(amount)
            if normalized_amount:
                amount_values.append(normalized_amount)
        compact = re.sub(r"\s+", "", line)
        if re.fullmatch(r"[0-9OIL]{1,6}", compact or ""):
            normalized_count = _normalize_payment_count(compact)
            if normalized_count:
                count_values.append(normalized_count)
        if len(count_values) >= 2 and len(amount_values) >= 2:
            break

    if len(count_values) < 2 or len(amount_values) < 2:
        return []
    return [count_values[0], amount_values[0], count_values[1], amount_values[1]]


def _extract_payment_table_rows_from_compact_text(raw_text: str) -> list[list[str]]:
    if not raw_text:
        return []
    try:
        return _extract_payment_table_rows_from_compact_text_impl(raw_text)
    except Exception:
        logger.debug("_extract_payment_table_rows_from_compact_text: error", exc_info=True)
        return []


def _extract_payment_table_rows_from_compact_text_impl(raw_text: str) -> list[list[str]]:
    lines = [_ascii_fold(_normalize_text(line)).upper() for line in raw_text.splitlines() if _normalize_text(line)]
    if not lines:
        return []

    scotia_rows = _extract_scotia_transfer_rows(lines)
    if scotia_rows:
        return scotia_rows
    detail_rows = _extract_banorte_bbva_detail_rows(lines, raw_text)
    if detail_rows:
        return detail_rows
    bbva_transfer_rows = _extract_bbva_transfer_receipt_rows(lines, raw_text)
    if bbva_transfer_rows:
        return bbva_transfer_rows

    full = " ".join(lines)
    values: dict[str, str] = {}

    def pick(pattern: str) -> str:
        match = re.search(pattern, full)
        if not match:
            return ""
        return _normalize_table_cell(match.group(1))

    def pick_labeled_value(labels: list[str]) -> str:
        for line in lines:
            candidate = line
            for label in labels:
                if candidate.startswith(label + ":"):
                    return _normalize_table_cell(candidate.split(":", 1)[1])
                tag = f"{label}:"
                if tag in candidate:
                    return _normalize_table_cell(candidate.split(tag, 1)[1])
        return ""

    nombre_directo = pick_labeled_value(["NOMBRE"])
    apellido_paterno = pick_labeled_value(["APELLIDO PATERNO", "APELLIDOPATERNO"])
    apellido_materno = pick_labeled_value(["APELLIDO MATERNO", "APELLIDOMATERNO"])

    values["cuenta"] = _normalize_numeric_field(
        pick_labeled_value(
            [
                "NUMERO DE CUENTA DE ABONO",
                "NUMERO DE CUENTA",
                "NO. DE CUENTA",
                "CUENTA CARGO",
            ]
        )
    ) or _normalize_numeric_field(
        pick(r"(?:NUMERO DE CUENTA DE ABONO|CUENTA(?: DE ABONO)?|NO\.?\s*DE\s*CUENTA)\s*:?\s*([0-9OIL.-]{8,26})")
    )
    values["referencia"] = _normalize_value_for_key(
        "referencia",
        pick_labeled_value(["REFERENCIA", "REFERENCIA DE CARGO", "LINEA DE CAPTURA"])
        or pick(r"(?:REFERENCIA(?: DE CARGO)?|LINEA DE CAPTURA)\s*:?\s*([0-9OIL.-]{10,36})"),
    )
    values["importe"] = _normalize_table_cell(
        pick_labeled_value(["IMPORTE", "IMPORTE TOTAL", "TOTAL A PAGAR"])
        or pick(r"(?:IMPORTE(?: TOTAL)?|TOTAL A PAGAR)\s*:?\s*(\$?\s*[0-9OIL]{1,3}(?:[.,][0-9OIL]{3})*(?:[.,][0-9OIL]{2}))")
    )
    name_labeled = nombre_directo
    if not name_labeled:
        name_labeled = pick(r"(?:NOMBRE)\s*:\s*([A-ZÑÁÉÍÓÚÜ ]{4,80})")
    if not name_labeled:
        name_labeled = pick(r"(?:NOMBRE)\s*:?\s*([A-ZÑÁÉÍÓÚÜ ]{4,80}?)(?=\s+(?:ESTATUS|CONCEPTO|REFERENCIA|CUENTA|IMPORTE)\b|$)")
    full_name = _normalize_name(
        " ".join(part for part in [name_labeled, apellido_paterno, apellido_materno] if part).strip()
    ) or _normalize_name(name_labeled)
    if full_name and not _looks_like_person_name(full_name):
        full_name = ""
    values["nombre"] = full_name
    values["estatus"] = _normalize_table_cell(
        pick_labeled_value(["ESTATUS"])
        or pick(r"(?:ESTATUS)\s*:?\s*([A-ZÑÁÉÍÓÚÜ]{4,30})")
    )
    concept_labeled = pick_labeled_value(["CONCEPTO"])
    if not concept_labeled:
        concept_labeled = pick(r"(?:TIPO DE PAGO)\s*:?\s*([A-ZÑÁÉÍÓÚÜ ]{4,80})")
    if not concept_labeled:
        concept_labeled = pick(r"(?:CONCEPTO)\s*:?\s*([A-ZÑÁÉÍÓÚÜ ]{4,80}?)(?=\s+(?:ESTATUS|NOMBRE|REFERENCIA|CUENTA|IMPORTE)\b|$)")
    values["concepto"] = _normalize_table_cell(concept_labeled)
    if values["concepto"]:
        values["concepto"] = re.sub(
            r"\s+\b(?:ESTATUS|NOMBRE|REFERENCIA|CUENTA|IMPORTE)\b.*$",
            "",
            values["concepto"],
        ).strip()

    if not values["cuenta"] or not values["referencia"]:
        for line in lines:
            nums = re.findall(r"\d{10,24}", line)
            if len(nums) >= 2:
                if not values["cuenta"]:
                    values["cuenta"] = nums[0]
                if not values["referencia"]:
                    values["referencia"] = nums[1]
                break

    if not values["importe"] or not values["nombre"]:
        for line in lines:
            amt = re.search(r"(\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))", line)
            if not amt:
                continue
            if not values["importe"]:
                values["importe"] = _normalize_table_cell(amt.group(1))
            if not values["nombre"]:
                tail = line[amt.end():].strip()
                if tail:
                    tail_name = _normalize_name(tail)
                    if tail_name and _looks_like_person_name(tail_name):
                        values["nombre"] = tail_name
            break

    if not values["cuenta"] or not values["importe"] or not values["estatus"]:
        movement_match = re.search(
            r"\b(\d{12,24})\s*\$?\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))\s*(APLICADO|PROCESADO|ACEPTADO|RECHAZADO)\b",
            full,
        )
        if movement_match:
            if not values["cuenta"]:
                values["cuenta"] = movement_match.group(1)
            if not values["importe"]:
                values["importe"] = "$" + movement_match.group(2) if not movement_match.group(2).startswith("$") else movement_match.group(2)
            if not values["estatus"]:
                values["estatus"] = movement_match.group(3)

    if not values["nombre"]:
        for line in lines:
            cleaned = _normalize_name(line)
            if not cleaned:
                continue
            token_count = len(cleaned.split())
            if token_count < 3:
                continue
            if any(
                marker in line
                for marker in (
                    "REPORTE",
                    "ARCHIVO",
                    "EMPRESA",
                    "CONTRATO",
                    "FOLIO",
                    "TRANSFERENCIA",
                    "CANTIDAD",
                    "MOVIMIENTOS",
                    "TIPO DE",
                    "CUENTA",
                    "REFERENCIA",
                    "IMPORTE",
                    "ESTATUS",
                    "CONCEPTO",
                )
            ):
                continue
            values["nombre"] = cleaned
            break

    filled = sum(1 for key in _PAYMENT_TABLE_TEXT_LABELS if values.get(key))
    if filled < 3:
        return []

    header = ["CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE", "ESTATUS", "CONCEPTO"]
    row = [
        values.get("cuenta", ""),
        values.get("referencia", ""),
        values.get("importe", ""),
        values.get("nombre", ""),
        values.get("estatus", ""),
        values.get("concepto", ""),
    ]

    if not any(cell for cell in row):
        return []

    return [header, row]


_BANORTE_STATUS_RE = r"(?:APLICADO|ACEPTADO|PROCESADO|TRANSMITIDO|RECHAZADO)"
# Patrón para fila de nómina multi-empleado (una fila por línea):
# "0000000001  ARLY ERNESTO ESPINOZA JOB  01  00000001290307408  $3,201.73  APLICADO  00  ACEPTADO"
_BANORTE_ROW_PAT = re.compile(
    r"^\s*(?P<employee>\d{6,12})\s+"
    r"(?P<nombre>[A-ZÑÁÉÍÓÚÜ][A-ZÑÁÉÍÓÚÜ .'\'\-]{3,79}?)\s+"
    r"(?P<tipo>\d{2})\s+"
    r"(?P<cuenta>\d{12,24})\s+"
    r"(?P<importe>\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))\s+"
    r"(?P<estatus>" + _BANORTE_STATUS_RE + r")\s+"
    r"(?P<codigo>\d{2})\s+"
    r"(?P<descripcion>" + _BANORTE_STATUS_RE + r")"
    r"(?:\s+(?P<clave>[A-Z0-9]{8,50}))?\s*$"
)


def _extract_banorte_bbva_detail_rows(lines: list[str], raw_text: str) -> list[list[str]]:
    try:
        return _extract_banorte_bbva_detail_rows_impl(lines, raw_text)
    except Exception:
        logger.debug("_extract_banorte_bbva_detail_rows: error", exc_info=True)
        return []


def _extract_banorte_bbva_detail_rows_impl(lines: list[str], raw_text: str) -> list[list[str]]:
    full = " ".join(lines)
    if "REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS" not in full:
        return []
    if not any(token in full for token in ("NO. EMPLEADO", "NOEMPLEADO", "DETALLE")):
        return []

    header = [
        "NO. EMPLEADO",
        "NOMBRE",
        "TIPO CUENTA",
        "NO. DE CUENTA",
        "IMPORTE",
        "ESTATUS",
        "CODIGO",
        "DESCRIPCION",
        "CLAVE RASTREO",
    ]

    detail_idx = next(
        (
            i
            for i, line in enumerate(lines)
            if any(marker in line for marker in ("NO. EMPLEADO", "NOEMPLEADO", "DETALLE"))
        ),
        None,
    )

    # --- Path A: extracción multi-fila (una línea por empleado) ---
    # Aplica cuando el documento es una tabla con múltiples empleados donde cada fila
    # contiene todos los campos en una sola línea separados por espacios.
    table_rows: list[list[str]] = []
    start_idx = (detail_idx + 1) if detail_idx is not None else 0
    for line in lines[start_idx:]:
        folded_line = _ascii_fold(_normalize_text(line)).upper()
        m = _BANORTE_ROW_PAT.match(folded_line)
        if m:
            table_rows.append([
                m.group("employee"),
                _normalize_name(m.group("nombre")),
                m.group("tipo"),
                _normalize_numeric_field(m.group("cuenta")),
                _normalize_payment_amount(m.group("importe")),
                _normalize_table_cell(m.group("estatus")),
                m.group("codigo"),
                _normalize_table_cell(m.group("descripcion")),
                m.group("clave") or "",
            ])
        elif table_rows and _is_payment_table_footer([folded_line]):
            break

    if len(table_rows) >= 1:
        return [header, *table_rows[:500]]

    # --- Path B (fallback): extracción single-record para comprobantes individuales ---
    # Aplica cuando el documento es un comprobante de un solo empleado con cada campo
    # en su propia línea.
    employee = ""
    name = ""
    tipo_cuenta = ""
    cuenta = ""
    importe = ""
    estatus = ""
    codigo = ""
    descripcion = ""
    clave_rastreo = ""

    if detail_idx is not None:
        scope = lines[detail_idx : min(len(lines), detail_idx + 20)]
        for idx, line in enumerate(scope):
            if not employee and re.fullmatch(r"\d{6,12}", line):
                employee = line
                for nxt in scope[idx + 1 : idx + 5]:
                    words = [w for w in nxt.split() if w.isalpha() and len(w) >= 2]
                    if len(words) >= 3:
                        name = _normalize_name(nxt)
                        break
                continue
            if not tipo_cuenta and re.fullmatch(r"\d{2}", line):
                tipo_cuenta = line
                continue
            if not codigo and re.fullmatch(r"\d{2}", line) and tipo_cuenta and line != tipo_cuenta:
                codigo = line
                continue
            if (
                not descripcion
                and any(token in line for token in ("ACEPTADO", "RECHAZADO", "APLICADO", "TRANSMITIDO"))
                and "$" not in line
                and len(re.sub(r"\D", "", line)) < 4
            ):
                descripcion = _normalize_table_cell(line)

    if detail_idx is not None:
        chunk = " ".join(lines[detail_idx : min(len(lines), detail_idx + 24)])
    else:
        chunk = full
    account_match = re.search(r"\b\d{12,24}\b", chunk)
    if account_match:
        cuenta = _normalize_numeric_field(account_match.group(0))
    amount_match = re.search(r"\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})", chunk)
    if amount_match:
        importe = _normalize_payment_amount(amount_match.group(0))
    status_match = re.search(r"\b(TRANSMITIDO|APLICADO|ACEPTADO|RECHAZADO|PROCESADO)\b", chunk)
    if status_match:
        estatus = _normalize_table_cell(status_match.group(1))

    if not descripcion:
        status_values = re.findall(r"\b(ACEPTADO|RECHAZADO|APLICADO|TRANSMITIDO|PROCESADO)\b", chunk)
        if status_values:
            descripcion = _normalize_table_cell(status_values[-1])
    if not descripcion and estatus:
        descripcion = estatus

    trace_match = re.search(r"FOLIO\s+ELECTRONICO\s*:?\s*([A-Z0-9]{8,50})", full)
    if trace_match:
        clave_rastreo = _normalize_table_cell(trace_match.group(1))
    elif cuenta:
        ref_match = re.search(r"\b\d{7,12}\b", chunk)
        if ref_match:
            clave_rastreo = _normalize_table_cell(ref_match.group(0))

    if not name:
        candidate_name = re.search(r"\b([A-Z\u00d1\u00c1\u00c9\u00cd\u00d3\u00da\u00dc]{2,}(?:\s+[A-Z\u00d1\u00c1\u00c9\u00cd\u00d3\u00da\u00dc]{2,}){2,6})\b", chunk)
        if candidate_name:
            guessed = _normalize_name(candidate_name.group(1))
            if _looks_like_person_name(guessed):
                name = guessed

    populated = sum(1 for value in [cuenta, importe, name, estatus, employee] if value)
    if populated < 3:
        return []

    row = [employee, name, tipo_cuenta, cuenta, importe, estatus, codigo, descripcion, clave_rastreo]
    return [header, row]


def _extract_bbva_transfer_receipt_rows(lines: list[str], raw_text: str) -> list[list[str]]:
    try:
        return _extract_bbva_transfer_receipt_rows_impl(lines, raw_text)
    except Exception:
        logger.debug("_extract_bbva_transfer_receipt_rows: error", exc_info=True)
        return []


def _extract_bbva_transfer_receipt_rows_impl(lines: list[str], raw_text: str) -> list[list[str]]:
    """Extract BBVA vertical key-value transfer receipts.

    Handles two document types:
    A) Comprobante de traspaso: has COMPROBANTE + RESULTADO DEL TRASPASO
    B) Grupo Pago Mismo Banco / Operación Autorizada: has
       PAGO MISMO BANCO / OPERACION AUTORIZADA + CUENTA DE RETIRO + CUENTA DE DEPOSITO

    Both may contain multiple payments (one per page).  Each payment becomes
    one row in the returned table.
    """
    if not lines:
        return []
    normalized_lines = [str(line or "").strip() for line in lines if str(line or "").strip()]
    normalized_keys = [_normalize_keyword(_ascii_fold(line).upper()) for line in normalized_lines]
    full = " ".join(normalized_lines)
    full_key = " ".join(normalized_keys)

    logger.info("[BBVA_RECEIPT] full_key[:300] = %s", full_key[:300])
    logger.info("[BBVA_RECEIPT] num_lines = %d", len(normalized_lines))

    # --- Type A: original comprobante guard ---
    is_comprobante = (
        "COMPROBANTE" in full_key
        and any(
            token in full_key
            for token in (
                "RESULTADODELTRASPASO",
                "TRASPASOSAOTROSBANCOS",
                "TRASPASOAOTROSBANCOS",
            )
        )
    )

    # --- Type B: "Grupo Pago Mismo Banco" / "Operacion Autorizada" ---
    is_grupo_pago = any(
        token in full_key
        for token in (
            "PAGOMISMOBANCO",
            "GRUPOPAGOMISMOBANCO",
            "OPERACIONAUTORIZADA",
        )
    )

    has_deposit_label = any(
        key.startswith("CUENTADEDEPOSITO")
        or key.startswith("CUENTADEDEPSITO")
        or key.startswith("CUENTADESTINO")
        or key.startswith("CUENTADEPOSITO")
        for key in normalized_keys
    )

    has_retiro_label = any(
        key.startswith("CUENTADERETIRO") for key in normalized_keys
    )

    if not is_comprobante and not (is_grupo_pago and has_deposit_label and has_retiro_label):
        return []

    def keyword_close(left: str, right: str) -> bool:
        if left == right:
            return True
        if abs(len(left) - len(right)) > 1:
            return False
        i = 0
        j = 0
        mismatches = 0
        while i < len(left) and j < len(right):
            if left[i] == right[j]:
                i += 1
                j += 1
                continue
            mismatches += 1
            if mismatches > 1:
                return False
            if len(left) > len(right):
                i += 1
            elif len(right) > len(left):
                j += 1
            else:
                i += 1
                j += 1
        if i < len(left) or j < len(right):
            mismatches += 1
        return mismatches <= 1

    def _pick_value_from_segment(
        seg_lines: list[str],
        seg_keys: list[str],
        labels: list[str],
        seg_text: str,
        lookahead: int = 4,
        max_len: int = 120,
    ) -> str:
        """Pick a value from a specific text segment (one payment block)."""
        label_pairs = []
        for label in labels:
            key = _normalize_keyword(_ascii_fold(_normalize_text(label)).upper())
            if key:
                label_pairs.append((label, key))
        for idx, line in enumerate(seg_lines):
            line_key = seg_keys[idx]
            for label, label_key in label_pairs:
                if keyword_close(line_key, label_key):
                    for next_idx in range(idx + 1, min(len(seg_lines), idx + 1 + lookahead)):
                        next_line = seg_lines[next_idx]
                        next_key = seg_keys[next_idx]
                        if not next_line:
                            continue
                        if any(keyword_close(next_key, candidate_key) for _, candidate_key in label_pairs):
                            continue
                        return _normalize_text(next_line)[:max_len]
                if line_key.startswith(label_key):
                    remainder = _normalize_text(line).strip(" :")
                    prefix = _normalize_text(label)
                    if remainder.startswith(prefix):
                        remainder = remainder[len(prefix):].strip(" :")
                    if remainder:
                        return remainder[:max_len]
        fallback = _payment_pick_labeled_value(seg_text, labels, max_len=max_len)
        if fallback:
            return fallback
        return ""

    # --- Split text into payment segments ---
    # Multi-payment documents repeat the structure per page / per section.
    # For "Grupo Pago" (Type B) we split on "TIPO DE OPERACION" — it marks
    # the very first field of each payment block and is far less likely to
    # appear spuriously in footers / summaries than "CUENTA DE RETIRO".
    # For Type A (comprobante) we keep the original "CUENTA DE RETIRO" split.
    segment_starts: list[int] = []
    if is_grupo_pago:
        for idx, key in enumerate(normalized_keys):
            if key.startswith("TIPODEOPERACION"):
                segment_starts.append(idx)
    if not segment_starts:
        # Fallback (Type A, or Type B where TIPO DE OPERACION was not found)
        for idx, key in enumerate(normalized_keys):
            if key.startswith("CUENTADERETIRO"):
                segment_starts.append(idx)

    if not segment_starts:
        # Last resort: treat everything as one segment
        segment_starts = [0]

    # Build segments
    segments: list[tuple[list[str], list[str], str]] = []
    for seg_i, start in enumerate(segment_starts):
        end = segment_starts[seg_i + 1] if seg_i + 1 < len(segment_starts) else len(normalized_lines)
        seg_lines = normalized_lines[start:end]
        seg_keys = normalized_keys[start:end]
        seg_text = "\n".join(seg_lines)
        segments.append((seg_lines, seg_keys, seg_text))

    logger.info("[BBVA_RECEIPT] is_comprobante=%s, is_grupo_pago=%s, segments=%d, segment_starts=%s",
                is_comprobante, is_grupo_pago, len(segments), segment_starts)

    # --- Extract one row per segment ---
    def _extract_one_payment(
        seg_lines: list[str], seg_keys: list[str], seg_text: str,
    ) -> list[str] | None:
        def pick(labels: list[str], lookahead: int = 4, max_len: int = 120) -> str:
            return _pick_value_from_segment(seg_lines, seg_keys, labels, seg_text, lookahead, max_len)

        cuenta_retiro = _normalize_numeric_field(
            pick(["CUENTA DE RETIRO"], max_len=30)
        )
        cuenta_destino = _normalize_numeric_field(
            pick(
                ["CUENTA DE DEPOSITO", "CUENTA DESTINO", "CUENTA DE ABONO", "CUENTA DEPOSITO",
                 "CUENTA DE DEPSITO"],
                max_len=40,
            )
        )
        importe = _normalize_payment_amount(
            pick(["IMPORTE"], max_len=40)
        )

        if is_grupo_pago:
            # --- Type B: Grupo Pago Mismo Banco ---
            # Fields match the PDF exactly
            tipo_operacion = _normalize_text(
                pick(["TIPO DE OPERACION"], max_len=90)
            )
            descripcion = _normalize_text(
                pick(["DESCRIPCION"], max_len=100)
            )
            divisa = _normalize_text(
                pick(["DIVISA DE LA CUENTA", "DIVISA"], max_len=20)
            )
            # Titular = account holder name
            titular = _normalize_text(
                pick(["TITULAR DE LA CUENTA", "TITULAR"], max_len=120)
            )
            # If pick returned nothing, try regex as fallback
            if not titular:
                titular_match = re.search(
                    r"TITULAR\s+(?:DE\s+LA\s+CUENTA)?\s*:?\s*([A-Z .'\-]{4,120})",
                    _ascii_fold(seg_text).upper(),
                )
                if titular_match:
                    titular = _normalize_text(titular_match.group(1))
            if not titular:
                candidate_short = _normalize_text(pick(["NOMBRE CORTO"]))
                if candidate_short:
                    titular = candidate_short

            fecha_creacion = _normalize_text(
                pick(["FECHA DE CREACION"], max_len=40)
            )
            fecha_aplicacion = _normalize_text(
                pick(["FECHA DE APLICACION"], max_len=40)
            )
            hora_captura = _normalize_text(
                pick(["HORA DE CAPTURA EN EL CANAL", "HORA DE CAPTURA"], max_len=20)
            )
            motivo_pago = _normalize_text(
                pick(["MOTIVO DE PAGO"], max_len=80)
            )
            folio_firma = _normalize_text(
                pick(["FOLIO DE FIRMA"], max_len=30)
            )
            folio_unico = _normalize_text(
                pick(["FOLIO UNICO"], max_len=50)
            )
            # Estado
            estado = ""
            seg_full = " ".join(seg_lines)
            estado_match = re.search(
                r"ESTADO\s*:?\s*(OPERADO|APLICADO|ACEPTADO|TRANSMITIDO|RECHAZADO|PROCESADO|EN\s+PROCESO)",
                _ascii_fold(seg_full).upper(),
            )
            if estado_match:
                estado = _normalize_text(estado_match.group(1))
            if not estado:
                status_match = re.search(
                    r"\b(APLICADO|ACEPTADO|TRANSMITIDO|RECHAZADO|PROCESADO|OPERADO)\b",
                    seg_full,
                )
                if status_match:
                    estado = _normalize_text(status_match.group(1))

            # Quality gate
            populated = sum(
                1 for v in [cuenta_retiro, cuenta_destino, importe, folio_firma, estado]
                if v
            )
            if populated < 3:
                return None

            return [
                tipo_operacion,
                descripcion,
                importe,
                cuenta_retiro,
                cuenta_destino,
                divisa,
                titular,
                fecha_creacion,
                fecha_aplicacion,
                hora_captura,
                motivo_pago,
                folio_firma,
                folio_unico,
                estado,
            ]
        else:
            # --- Type A: Comprobante de traspaso ---
            tipo_operacion = _normalize_text(
                pick(["TIPO DE OPERACION"], max_len=90)
            )
            banco_destino = _normalize_text(
                pick(["BANCO DESTINO"], max_len=80)
            )
            forma_deposito = _normalize_text(
                pick(["FORMA DE DEPOSITO"], max_len=80)
            )
            concepto_raw = pick(["CONCEPTO DE PAGO", "CONCEPTO"], max_len=100)
            concepto = _normalize_text(concepto_raw)
            if not concepto:
                desc_raw = pick(["DESCRIPCION"], max_len=100)
                concepto = _normalize_text(desc_raw)
            raw_referencia = pick(["REFERENCIA NUMERICA", "REFERENCIA"], max_len=40)
            referencia = _normalize_value_for_key("referencia", raw_referencia)
            if not referencia:
                short_reference = _normalize_numeric_field(raw_referencia)
                if re.fullmatch(r"\d{1,3}", short_reference or ""):
                    referencia = short_reference
            if not referencia:
                for idx, line_key in enumerate(seg_keys):
                    if "REFERENCIA" not in line_key:
                        continue
                    for next_idx in range(idx + 1, min(len(seg_lines), idx + 3)):
                        candidate_line = seg_lines[next_idx]
                        candidate_key = seg_keys[next_idx]
                        if any(
                            token in candidate_key
                            for token in ("CLAVE", "NOMBRE", "IMPORTE", "CONCEPTO", "BANCO", "CUENTA", "FORMA")
                        ):
                            continue
                        candidate = _normalize_value_for_key("referencia", candidate_line)
                        if not candidate:
                            short_candidate = _normalize_numeric_field(candidate_line)
                            if re.fullmatch(r"\d{1,3}", short_candidate or ""):
                                candidate = short_candidate
                        if candidate:
                            referencia = candidate
                            break
                    if referencia:
                        break
            clave_rastreo = _normalize_text(
                pick(["CLAVE DE RASTREO", "CLAVE RASTREO"], max_len=80)
            )
            nombre = ""
            beneficiary_match = re.search(
                r"DATOS\s+DEL\s+BENEFICIARIO\s+NOMBRE\s*:?\s*([^\n\r]{4,120})",
                seg_text,
                flags=re.IGNORECASE,
            )
            if beneficiary_match:
                candidate = _normalize_name(beneficiary_match.group(1))
                if candidate and _looks_like_person_name(candidate):
                    nombre = candidate
            if not nombre:
                candidate_short = _normalize_name(pick(["NOMBRE CORTO"]))
                if candidate_short and _looks_like_person_name(candidate_short):
                    nombre = candidate_short
            if not nombre:
                titular_match = re.search(
                    r"TITULAR\s+DE\s+LA\s+CUENTA\s*:?\s*([A-Z .']{4,120})",
                    _ascii_fold(seg_text).upper(),
                )
                if titular_match:
                    candidate_tit = _normalize_name(titular_match.group(1))
                    if candidate_tit and _looks_like_person_name(candidate_tit):
                        nombre = candidate_tit
            estatus = ""
            seg_full = " ".join(seg_lines)
            seg_full_key = " ".join(seg_keys)
            estado_match = re.search(
                r"ESTADO\s*:?\s*(OPERADO|APLICADO|ACEPTADO|TRANSMITIDO|RECHAZADO|PROCESADO|EN\s+PROCESO)",
                _ascii_fold(seg_full).upper(),
            )
            if estado_match:
                estatus = _normalize_text(estado_match.group(1))
            if not estatus:
                status_match = re.search(r"\b(APLICADO|ACEPTADO|TRANSMITIDO|RECHAZADO|PROCESADO|OPERADO)\b", seg_full)
                if status_match:
                    estatus = _normalize_text(status_match.group(1))
            if not estatus and "ENPROCESODEVALIDACION" in seg_full_key:
                estatus = "EN PROCESO"

            folio_firma = _normalize_text(pick(["FOLIO DE FIRMA"], max_len=30))
            folio_unico = _normalize_text(pick(["FOLIO UNICO"], max_len=50))
            fecha_aplicacion = _normalize_text(pick(["FECHA DE APLICACION"], max_len=40))
            motivo_pago = _normalize_text(pick(["MOTIVO DE PAGO"], max_len=80))

            populated = sum(
                1
                for value in [
                    cuenta_retiro, cuenta_destino, importe,
                    banco_destino or folio_firma,
                    referencia or clave_rastreo,
                    nombre, estatus,
                ]
                if value
            )
            if populated < 3:
                return None

            return [
                cuenta_retiro,
                tipo_operacion,
                banco_destino,
                cuenta_destino,
                importe,
                forma_deposito,
                concepto,
                referencia,
                clave_rastreo,
                nombre,
                estatus,
                folio_firma,
                folio_unico,
                fecha_aplicacion,
                motivo_pago,
            ]

    # --- Header depends on document type ---
    if is_grupo_pago:
        header = [
            "TIPO DE OPERACION",
            "DESCRIPCION",
            "IMPORTE",
            "CUENTA DE RETIRO",
            "CUENTA DE DEPOSITO",
            "DIVISA",
            "TITULAR",
            "FECHA DE CREACION",
            "FECHA DE APLICACION",
            "HORA DE CAPTURA",
            "MOTIVO DE PAGO",
            "FOLIO DE FIRMA",
            "FOLIO UNICO",
            "ESTADO",
        ]
    else:
        header = [
            "CUENTA DE RETIRO",
            "TIPO DE OPERACION",
            "BANCO DESTINO",
            "CUENTA DE DEPOSITO",
            "IMPORTE",
            "FORMA DE DEPOSITO",
            "CONCEPTO DE PAGO",
            "REFERENCIA NUMERICA",
            "CLAVE DE RASTREO",
            "NOMBRE",
            "ESTATUS",
            "FOLIO DE FIRMA",
            "FOLIO UNICO",
            "FECHA DE APLICACION",
            "MOTIVO DE PAGO",
        ]

    result_rows: list[list[str]] = []
    seen_folios: set[str] = set()
    # Determine folio column index from header for accurate dedup
    folio_idx = -1
    for _fi, _fh in enumerate(header):
        if _normalize_keyword(_fh).lower() in ("foliounico", "folio_unico"):
            folio_idx = _fi
            break
    for seg_idx, (seg_lines, seg_keys, seg_text) in enumerate(segments):
        logger.info("[BBVA_RECEIPT] Segment %d: %d lines, first_key=%s",
                    seg_idx, len(seg_lines), seg_keys[0] if seg_keys else "EMPTY")
        try:
            row = _extract_one_payment(seg_lines, seg_keys, seg_text)
        except Exception:
            logger.debug("[BBVA_RECEIPT] Segment %d FAILED (exception)", seg_idx, exc_info=True)
            row = None
        if row:
            logger.info("[BBVA_RECEIPT] Segment %d produced row with %d cols: %s",
                        seg_idx, len(row), row)
            # Deduplicate by folio_unico using header-derived index.
            folio_val = row[folio_idx] if 0 <= folio_idx < len(row) else ""
            if folio_val:
                if folio_val in seen_folios:
                    logger.info("[BBVA_RECEIPT] Segment %d SKIPPED (dup folio=%s)", seg_idx, folio_val)
                    continue  # skip duplicate payment
                seen_folios.add(folio_val)
            result_rows.append(row)
        else:
            logger.info("[BBVA_RECEIPT] Segment %d returned None (quality gate)", seg_idx)

    if not result_rows:
        return []

    # Remove columns that are entirely empty across all rows
    non_empty_cols: list[int] = []
    for col_i in range(len(header)):
        if any(row[col_i] for row in result_rows if col_i < len(row)):
            non_empty_cols.append(col_i)
    header = [header[i] for i in non_empty_cols]
    result_rows = [[row[i] if i < len(row) else "" for i in non_empty_cols] for row in result_rows]

    return [header] + result_rows


def _normalize_payment_table_rows(rows: list[list[str]]) -> list[list[str]]:
    """Normalización final aplicada a las filas ya fusionadas (OCR + texto).

    0. Deduplica headers de multi-página OCR ("CUENTA CUENTA" → "CUENTA").
    1. Si CONCEPTO empieza con palabra de estatus → siempre limpia el prefijo.
       Si ESTATUS también está vacío, lo extrae de ahí.
       Si el header no tiene columna ESTATUS, se inyecta antes de CONCEPTO.
    2. Fallback: si ESTATUS sigue vacío, busca la palabra de estatus en toda la fila.
    3. Uniforma NOMBRE y APELLIDO* a MAYÚSCULAS.
    """
    try:
        return _normalize_payment_table_rows_impl(rows)
    except Exception:
        logger.debug("_normalize_payment_table_rows: error, returning original", exc_info=True)
        return rows


def _normalize_payment_table_rows_impl(rows: list[list[str]]) -> list[list[str]]:
    if len(rows) < 2:
        return rows

    # Fix 0: Dedup multi-page OCR header tokens y normaliza a claves canónicas
    header = _dedup_header_row(list(rows[0]))
    canonical_map = {
        "tipo de registro": "tipoderegistro",
        "tipo de movimiento (pago)": "tipomovimiento",
        "importe": "importe",
        "fecha de aplicacion": "fechaaplicacion",
        "clave del beneficiario": "clavedebeneficiario",
        "nombre del beneficiario": "nombrebeneficiario",
        "referencia": "referencia",
        "no. cuenta beneficiario": "cuentabeneficiario",
        "no. banco receptor": "bancoreceptor",
        "dias de vigencia": "diasvigencia",
        "concepto pago": "conceptopago",
        # Agrega más mapeos según los tests
    }
    def canon(h):
        h_norm = str(h or "").strip().lower().replace(" ", "").replace(".", "")
        for k, v in canonical_map.items():
            if h_norm == k.replace(" ", "").replace(".", ""):
                return v
        return h_norm
    # Normaliza header a canónico
    canon_header = [canon(h) for h in header]
    keys = canon_header

    # Detectar si es tabla avanzada (nómina/pago/factura) o simple (comprobante, datos bancarios)
    advanced_keys = {"tipoderegistro", "tipomovimiento", "importe", "fechaaplicacion", "clavedebeneficiario", "nombrebeneficiario", "referencia", "cuentabeneficiario", "bancoreceptor", "diasvigencia", "conceptopago"}
    is_advanced = any(k in canon_header for k in advanced_keys)

    def _ci(name: str) -> int:
        for i, k in enumerate(keys):
            if name in k:
                return i
        return -1

    estatus_idx = _ci("estatus") if _ci("estatus") != -1 else _ci("estado")
    concepto_idx = _ci("concepto")
    nombre_idx = _ci("nombre")
    apellido_idxs = [i for i, k in enumerate(keys) if "apellido" in k]

    _has_apellido = bool(apellido_idxs)

    # Fix pre-loop A: detectar columna merged "ESTATUS CONCEPTO" donde ambos índices
    # apuntan al mismo lugar. Renombramos a CONCEPTO y forzamos inyección de ESTATUS.
    if estatus_idx >= 0 and estatus_idx == concepto_idx and concepto_idx >= 0:
        header[concepto_idx] = "CONCEPTO"
        keys[concepto_idx] = "concepto"
        estatus_idx = -1

    # Fix pre-loop B: inyectar ESTATUS si el header no lo tiene pero sí CONCEPTO.
    # Solo aplica a tablas BBVA nomina (tienen columna APELLIDO); tablas tipo Scotia
    # tienen estructura diferente y su CONCEPTO no lleva prefijo de estatus.
    col_injected = False
    if estatus_idx < 0 and concepto_idx >= 0 and _has_apellido:
        insert_pos = concepto_idx
        header.insert(insert_pos, "ESTATUS")
        keys.insert(insert_pos, "estatus")
        estatus_idx = insert_pos
        concepto_idx += 1
        if nombre_idx >= insert_pos:
            nombre_idx += 1
        apellido_idxs = [i + 1 if i >= insert_pos else i for i in apellido_idxs]
        col_injected = True

    result: list[list[str]]
    if is_advanced:
        norm_rows: list[dict[str, str]] = []
        for orig_row in rows[1:]:
            if col_injected:
                ins = estatus_idx
                raw_row: list[str] = list(orig_row[:ins]) + [""] + list(orig_row[ins:])
            else:
                raw_row = list(orig_row)
            # Mapear a dict usando header canónico
            row_map: dict[str, str] = {k: (raw_row[i] if i < len(raw_row) else "") for i, k in enumerate(canon_header)}

            # Fix 3: extraer/limpiar estatus embebido en concepto (aplica a cualquier source).
            if (
                0 <= concepto_idx < len(canon_header)
                and 0 <= estatus_idx < len(canon_header)
                and concepto_idx != estatus_idx
            ):
                concepto_val = row_map.get(canon_header[concepto_idx], "").strip()
                sm = _STATUS_PREFIX_PAT.match(concepto_val)
                if sm:
                    if not row_map.get(canon_header[estatus_idx], "").strip():
                        row_map[canon_header[estatus_idx]] = sm.group(1)
                    row_map[canon_header[concepto_idx]] = concepto_val[sm.end():].strip() or "PAGO DE NOMINA"

            # Fix 3b: fallback — si estatus sigue vacío, buscar palabra de estatus en la fila
            if 0 <= estatus_idx < len(canon_header) and not row_map.get(canon_header[estatus_idx], "").strip() and _has_apellido:
                row_joined = " ".join(str(row_map.get(k, "")) for k in canon_header)
                m_st = _STATUS_SEARCH_PAT.search(row_joined)
                if m_st:
                    row_map[canon_header[estatus_idx]] = m_st.group(1)

            # Uniformar nombre y apellidos a MAYÚSCULAS
            for col_idx in ([nombre_idx] + apellido_idxs):
                k = canon_header[col_idx] if 0 <= col_idx < len(canon_header) else None
                if k and row_map.get(k):
                    row_map[k] = row_map[k].upper()

            # Asegurar que la fila tenga todas las claves del header
            for k in canon_header:
                if k not in row_map:
                    row_map[k] = ""

            norm_rows.append(row_map)

        # Siempre devolver lista de listas: [header_list, data_row_list, ...]
        result = [header]
        for row_dict in norm_rows:
            result.append([row_dict.get(k, "") for k in canon_header])
        result = _prune_redundant_payment_columns(result)
        return _reorder_nomina_payment_columns(result)
    else:
        # Tabla simple: mantener como listas
        result = [header]
        for orig_row in rows[1:]:
            if col_injected:
                ins = estatus_idx
                row_values = list(orig_row[:ins]) + [""] + list(orig_row[ins:])
            else:
                row_values = list(orig_row)
            # Padding para igualar columnas
            while len(row_values) < len(header):
                row_values.append("")
            result.append(row_values)
        result = _prune_redundant_payment_columns(result)
        return _reorder_nomina_payment_columns(result)


def _prune_redundant_payment_columns(rows: list[list[str]]) -> list[list[str]]:
    """Drop redundant/ghost columns from wide payment tables.

    Some bank PDFs include duplicated composite headers (e.g. "REFERENCIA IMPORTE")
    along with the real split columns ("REFERENCIA", "IMPORTE"), or trailing
    blank columns produced by table detectors. Keeping them hurts row alignment.
    """
    if len(rows) < 2:
        return rows

    header = list(rows[0])
    norm_header = [_normalize_keyword(str(cell or "")).upper() for cell in header]
    header_set = {token for token in norm_header if token}
    drop_idx: set[int] = set()

    # If split columns exist, drop composite duplicates.
    if {"REFERENCIA", "IMPORTE"}.issubset(header_set):
        for idx, token in enumerate(norm_header):
            if token in {"REFERENCIAIMPORTE", "IMPORTEREFERENCIA"}:
                drop_idx.add(idx)

    # Remove near-empty ghost columns with no meaningful header.
    sparse_threshold = max(2, len(rows) // 25)
    for idx, token in enumerate(norm_header):
        if token:
            continue
        non_empty = 0
        amount_like = 0
        for row in rows[1:]:
            if idx >= len(row):
                continue
            cell_text = _normalize_text(str(row[idx] or ""))
            if not cell_text:
                continue
            non_empty += 1
            if re.search(r"\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})", cell_text):
                amount_like += 1
        if non_empty <= sparse_threshold:
            drop_idx.add(idx)
            continue
        # Empty header columns that are mostly amount duplicates are redundant
        # when a real IMPORTE column already exists.
        if "IMPORTE" in header_set and non_empty > 0 and (amount_like / non_empty) >= 0.75:
            drop_idx.add(idx)

    if not drop_idx:
        return rows

    cleaned_rows: list[list[str]] = []
    for row in rows:
        cleaned_rows.append([str(cell or "") for i, cell in enumerate(row) if i not in drop_idx])
    return cleaned_rows


def _reorder_nomina_payment_columns(rows: list[list[str]]) -> list[list[str]]:
    """Reorder advanced payroll table columns to match the PDF reading order."""
    if len(rows) < 2:
        return rows

    header = [str(cell or "") for cell in rows[0]]
    norm_header = [_normalize_keyword(cell).upper() for cell in header]
    if not norm_header:
        return rows

    def _pick_idx(candidates: tuple[str, ...]) -> int:
        for idx, token in enumerate(norm_header):
            if token in candidates:
                return idx
        return -1

    idx_cuenta = _pick_idx((
        "CUENTA",
        "NOCUENTA",
        "NODECUENTA",
        "NUMERODECUENTA",
        "CUENTABENEFICIARIO",
        "NUMERODECUENTABENEFICIARIO",
    ))
    idx_ref = _pick_idx(("REFERENCIA", "REFERENCIANUMERICA", "REFERENCIAREFERENCIA"))
    idx_imp = _pick_idx(("IMPORTE", "IMPORTETOTAL", "MONTO", "IMPORTEIMPORTE"))
    idx_nombre = _pick_idx(("NOMBRE", "NOMBREBENEFICIARIO", "NOMBRENOMBRE", "BENEFICIARIO"))
    idx_ap_pat = _pick_idx(("APELLIDOPATERNO",))
    idx_ap_mat = _pick_idx(("APELLIDOMATERNO",))
    idx_estatus = _pick_idx(("ESTATUS", "ESTADO", "RESULTADODELTRASPASO"))
    idx_concepto = _pick_idx(("CONCEPTO", "CONCEPTOPAGO", "CONCEPTODEPAGO", "CONCEPTOCONCEPTO"))

    # Only reorder when the row clearly contains the full payroll schema.
    if min(idx_cuenta, idx_ref, idx_imp, idx_nombre, idx_estatus, idx_concepto) < 0:
        return rows

    preferred = [idx_cuenta, idx_ref, idx_imp, idx_nombre, idx_ap_pat, idx_ap_mat, idx_estatus, idx_concepto]
    ordered_idx: list[int] = []
    for idx in preferred:
        if idx >= 0 and idx not in ordered_idx:
            ordered_idx.append(idx)
    for idx in range(len(header)):
        if idx not in ordered_idx:
            ordered_idx.append(idx)

    reordered: list[list[str]] = []
    for row in rows:
        row_vals = [str(cell or "") for cell in row]
        if len(row_vals) < len(header):
            row_vals.extend([""] * (len(header) - len(row_vals)))
        reordered.append([row_vals[idx] if idx < len(row_vals) else "" for idx in ordered_idx])
    return reordered


def _extract_payment_table_rows_from_pdf_tables(pdf_tables: list[list[list[str]]] | None) -> tuple[list[list[str]], list[list[list[str]]]]:
    try:
        return _extract_payment_table_rows_from_pdf_tables_impl(pdf_tables)
    except Exception:
        logger.debug("_extract_payment_table_rows_from_pdf_tables: error", exc_info=True)
        return [], []


def _extract_payment_table_rows_from_pdf_tables_impl(pdf_tables: list[list[list[str]]] | None) -> tuple[list[list[str]], list[list[list[str]]]]:
    """Convert PyMuPDF find_tables() output into payment table rows.

    Tables from multiple pages with matching headers are merged into a single
    result so that multi-page Banorte/BBVA tables are fully captured.
    Returns a tuple of (best_rows, secondary_tables) where:
      - best_rows: rows in the standard ``[header_row, data_row, ...]`` format
      - secondary_tables: list of additional tables (different header structure)
    """
    if not pdf_tables:
        return [], []

    # Step 1: clean each table
    def _safe_cell(cell: object) -> str:
        """Convert a PyMuPDF cell to string, treating None/NaN as empty."""
        if cell is None:
            return ""
        if isinstance(cell, float):
            import math
            if math.isnan(cell):
                return ""
        text = str(cell).strip()
        if text.upper() == "NAN":
            return ""
        return text

    cleaned_tables: list[list[list[str]]] = []
    for table_rows in pdf_tables:
        if not table_rows or len(table_rows) < 1:
            continue
        cleaned: list[list[str]] = []
        for row in table_rows:
            cleaned_row = [_safe_cell(cell) for cell in row]
            # Solo agrega filas con al menos un dato real
            if any(c for c in cleaned_row):
                cleaned.append(cleaned_row)
        if len(cleaned) >= 1:
            cleaned_tables.append(cleaned)

    if not cleaned_tables:
        return [], []

    # Step 2: group tables with identical header structure (multi-page merge)
    def _header_sig(header: list[str]) -> str:
        return "|".join(_normalize_keyword(h).lower() for h in header)

    groups: dict[str, list[list[list[str]]]] = {}
    for tbl in cleaned_tables:
        sig = _header_sig(tbl[0])
        groups.setdefault(sig, []).append(tbl)

    # Step 3: for each group, merge data rows under a single header
    merged_candidates: list[list[list[str]]] = []
    for sig, tables_in_group in groups.items():
        if len(tables_in_group) == 1:
            merged_candidates.append(tables_in_group[0])
        else:
            # Multi-page: take header from first table, append data rows from all
            header = tables_in_group[0][0]
            col_count = len(header)
            seen_rows: set[str] = set()
            data_rows: list[list[str]] = []
            for tbl in tables_in_group:
                for row in tbl[1:]:
                    # Pad/trim row to match header column count
                    padded = list(row[:col_count])
                    while len(padded) < col_count:
                        padded.append("")
                    row_key = "|".join(padded)
                    if row_key not in seen_rows:
                        seen_rows.add(row_key)
                        data_rows.append(padded)
            if data_rows:
                merged_candidates.append([header] + data_rows)

    # Step 4: pick the best merged candidate
    best_rows: list[list[str]] = []
    best_score = -999
    best_idx = -1
    for i, candidate in enumerate(merged_candidates):
        score = _payment_rows_quality_score(candidate)
        # No inner bonus — the outer _extract_payment_table_payload adds +20 for PDF source
        if score > best_score:
            best_score = score
            best_rows = candidate
            best_idx = i

    # Step 5: strip trailing junk columns (footer/contact noise from PyMuPDF)
    if best_rows and len(best_rows) >= 2:
        header = best_rows[0]
        last_valid = len(header) - 1
        while last_valid >= 0 and _is_junk_payment_header(header[last_valid]):
            last_valid -= 1
        if 0 <= last_valid < len(header) - 1:
            best_rows = [row[:last_valid + 1] for row in best_rows]

    # Step 6: collect ALL secondary tables (non-best candidates, even deformed ones)
    secondary_tables: list[list[list[str]]] = []
    for i, candidate in enumerate(merged_candidates):
        if i == best_idx:
            continue
        # No filtro: agrega todas las tablas con al menos 1 fila y 1 columna
        if len(candidate) >= 1 and len(candidate[0]) >= 1:
            # Strip trailing junk columns from secondary tables too
            hdr = candidate[0]
            last_v = len(hdr) - 1
            while last_v >= 0 and _is_junk_payment_header(hdr[last_v]):
                last_v -= 1
            if 0 <= last_v < len(hdr) - 1:
                candidate = [row[:last_v + 1] for row in candidate]
            secondary_tables.append(candidate)

    return best_rows, secondary_tables


def _pdf_tables_to_generic_payloads(pdf_tables: list[list[list[str]]] | None) -> list[dict]:
    """Convert PyMuPDF find_tables() output into generic table payloads."""
    if not pdf_tables:
        return []
    payloads: list[dict] = []
    for idx, table_rows in enumerate(pdf_tables):
        if not table_rows or len(table_rows) < 2:
            continue
        cleaned = [
            [str(cell or "").strip() for cell in row]
            for row in table_rows
            if any(str(c or "").strip() for c in row)
        ]
        if len(cleaned) < 2:
            continue
        # Filter metadata/noise rows from generic tables too
        _exp_cols = len(cleaned[0]) if cleaned else 0
        filtered = [cleaned[0]]  # keep header
        for r in cleaned[1:]:
            if not _is_metadata_row(r, expected_cols=_exp_cols):
                filtered.append(r)
        # Permitir tablas con encabezado + al menos 1 fila de datos
        if len(filtered) < 2:
            continue
        payloads.append({
            "rows": filtered,
            "row_count": len(filtered),
            "column_count": _exp_cols,
            "table_index": idx,
            "source": "pdf_structure",
        })
    return payloads


def _extract_payment_table_payload(base_text_raw: str, ocr_boxes, pdf_tables: list[list[list[str]]] | None = None) -> dict | None:
    try:
        return _extract_payment_table_payload_impl(base_text_raw, ocr_boxes, pdf_tables)
    except Exception:
        logger.warning("_extract_payment_table_payload: unexpected error, returning None", exc_info=True)
        return None


def _extract_payment_table_payload_impl(base_text_raw: str, ocr_boxes, pdf_tables: list[list[list[str]]] | None = None) -> dict | None:
    all_tables = _extract_all_table_payloads(base_text_raw, ocr_boxes)
    # Merge structurally-detected PDF tables into the generic pool
    pdf_generic = _pdf_tables_to_generic_payloads(pdf_tables)
    if pdf_generic:
        all_tables = pdf_generic + all_tables

    rows_ocr = _extract_payment_table_rows_from_boxes(ocr_boxes)
    rows_text = _extract_payment_table_rows_from_text(base_text_raw)
    rows_pdf, secondary_pdf_tables = _extract_payment_table_rows_from_pdf_tables(pdf_tables)

    score_ocr = _payment_rows_quality_score(rows_ocr) if len(rows_ocr) >= 2 else -999
    score_text = _payment_rows_quality_score(rows_text) if len(rows_text) >= 2 else -999
    score_pdf = (_payment_rows_quality_score(rows_pdf) + 20) if len(rows_pdf) >= 2 else -999

    # Pick the best source among all three
    candidates = [
        (score_pdf, rows_pdf, "pdf_structure"),
        (score_ocr, rows_ocr, "ocr_boxes"),
        (score_text, rows_text, "text_lines"),
    ]
    candidates.sort(key=lambda c: c[0], reverse=True)
    best_score, best_rows, best_source = candidates[0]

    selected_table_index = None
    if best_score >= 0:
        rows = best_rows
        source = best_source
    else:
        fallback_table = _pick_primary_table_from_payloads(all_tables)
        if not isinstance(fallback_table, dict):
            return None
        fallback_rows = fallback_table.get("rows")
        if not isinstance(fallback_rows, list) or len(fallback_rows) < 2:
            return None
        rows = [
            [str(cell or "") for cell in row]
            for row in fallback_rows
            if isinstance(row, list)
        ]
        if len(rows) < 2:
            return None
        source = "generic_table_payload"
        selected_table_index = int(fallback_table.get("table_index", 0) or 0)

    # Detect if the winning rows come from a BBVA vertical key-value receipt.
    # These are self-contained and must NOT be merged with generic text/pdf
    # sources, which would add junk columns and duplicate rows.
    # Type A (comprobante) header starts with "CUENTA DE RETIRO".
    # Type B (grupo pago)  header starts with "TIPO DE OPERACION".
    _first_header_key = (
        _normalize_keyword(str(rows[0][0] or "")) if (rows and rows[0]) else ""
    )
    _is_bbva_receipt_rows = (
        len(rows) >= 2
        and _first_header_key.startswith(("CUENTADERETIRO", "TIPODEOPERACION"))
    )

    if not _is_bbva_receipt_rows:
        if source == "ocr_boxes":
            rows = _merge_payment_rows_with_backup(rows, rows_text)
        elif source == "text_lines":
            rows = _merge_payment_rows_with_backup(rows, rows_ocr)
        elif source == "pdf_structure":
            # PDF structural tables are authoritative; only merge backup when
            # column count matches to avoid corrupting table structure.
            backup = rows_ocr if len(rows_ocr) >= 2 else rows_text
            pdf_cols = len(rows[0]) if rows else 0
            backup_cols = len(backup[0]) if backup else 0
            if len(backup) >= 2 and pdf_cols > 0 and backup_cols == pdf_cols:
                rows = _merge_payment_rows_with_backup(rows, backup)
            elif len(backup) >= 2 and pdf_cols > 0 and backup_cols != pdf_cols:
                logger.debug(
                    "Skipping backup merge: pdf_cols=%d backup_cols=%d (incompatible)",
                    pdf_cols, backup_cols,
                )
        else:
            rows = _merge_payment_rows_with_backup(rows, rows_ocr)

    rows = _append_scotia_summary_rows_to_table(rows, base_text_raw)
    rows = _normalize_payment_table_rows(rows)

    # ── Filter metadata/noise rows from raw data ────────────────────────
    # Keep the header (row 0) and only data rows that are not metadata noise.
    if len(rows) >= 2:
        _expected_cols = len(rows[0])
        clean = [rows[0]]
        for data_row in rows[1:]:
            if not _is_metadata_row(data_row, expected_cols=_expected_cols):
                clean.append(data_row)
        rows = clean

    # ── L1 + L2: Validate cells and cross-coherence ─────────────────────
    validation_warnings: list[str] = []
    try:
        validation_warnings.extend(_validate_payment_table_cells(rows))
    except Exception:
        logger.debug("L1 cell validation failed", exc_info=True)
    try:
        validation_warnings.extend(_validate_payment_table_coherence(rows))
    except Exception:
        logger.debug("L2 coherence validation failed", exc_info=True)

    payload: dict[str, Any] = {
        "source": source,
        "rows": rows,
    }
    # Refuerzo: si se detecta banco en encabezado, ese valor prevalece y se fuerza en todo el payload y filas dict
    _text_upper = (base_text_raw or "").upper()
    bancos_prioridad = ["BBVA", "SANTANDER", "SCOTIA", "BANORTE", "HSBC", "INBURSA", "BANAMEX", "STP"]
    banco_detectado = None
    primeras_lineas = [line.strip().upper() for line in (base_text_raw or "").splitlines()[:10] if line.strip()]
    for banco in bancos_prioridad:
        if any(banco in linea for linea in primeras_lineas):
            banco_detectado = banco
            break
    if not banco_detectado:
        for banco in bancos_prioridad:
            if banco in _text_upper:
                banco_detectado = banco
                break
    # BBVA receipt rows: the source bank is always BBVA regardless of destination bank in text
    if _is_bbva_receipt_rows:
        banco_detectado = "BBVA"
    if banco_detectado:
        payload["bank"] = banco_detectado
        # Si hay filas, forzar el campo 'bank' en cada fila dict
        if "rows" in payload and isinstance(payload["rows"], list):
            for i, row in enumerate(payload["rows"]):
                if isinstance(row, dict):
                    row["bank"] = banco_detectado
                # Si la fila es lista, pero tiene un campo banco, también forzar
                elif isinstance(row, list):
                    for idx, cell in enumerate(row):
                        if isinstance(cell, dict) and "bank" in cell:
                            cell["bank"] = banco_detectado
        # Si las filas son listas de listas (tablas tipo SCOTIA), fuerza el banco en la metadata si aplica
        if "metadata" in payload and isinstance(payload["metadata"], dict):
            payload["metadata"]["bank"] = banco_detectado
    # Para SCOTIA: si existen summary_tables, inclúyelos en el payload
    if "rows" in payload and isinstance(payload["rows"], list):
        for row in payload["rows"]:
            if isinstance(row, dict) and "summary_tables" in row:
                payload["summary_tables"] = row["summary_tables"]
    if banco_detectado and payload.get("bank") != banco_detectado:
        payload["bank"] = banco_detectado
    if validation_warnings:
        payload["validation_warnings"] = validation_warnings
    # Attach secondary PDF tables (different header structure than the primary)
    if secondary_pdf_tables:
        payload["secondary_pdf_tables"] = secondary_pdf_tables
    if all_tables:
        payload["all_tables"] = all_tables
        payload["all_table_count"] = len(all_tables)
        row_signature = _table_rows_signature(rows)
        matched = next(
            (
                int(table.get("table_index", 0) or 0)
                for table in all_tables
                if isinstance(table, dict)
                and _table_rows_signature(table.get("rows", [])) == row_signature
            ),
            0,
        )
        if matched > 0:
            payload["primary_table_index"] = matched
        elif selected_table_index and selected_table_index > 0:
            payload["primary_table_index"] = selected_table_index
    # Refuerzo global: forzar el banco detectado en encabezado en el payload final
    _text_upper = (base_text_raw or "").upper()
    bancos_prioridad = ["BBVA", "SANTANDER", "SCOTIA", "BANORTE", "HSBC", "INBURSA", "BANAMEX", "STP"]
    banco_detectado = None
    primeras_lineas = [line.strip().upper() for line in (base_text_raw or "").splitlines()[:10] if line.strip()]
    for banco in bancos_prioridad:
        if any(banco in linea for linea in primeras_lineas):
            banco_detectado = banco
            break
    if not banco_detectado:
        for banco in bancos_prioridad:
            if banco in _text_upper:
                banco_detectado = banco
                break
    # BBVA receipt rows: source bank is always BBVA regardless of destination bank in text
    if _is_bbva_receipt_rows:
        banco_detectado = "BBVA"
    if banco_detectado:
        payload["bank"] = banco_detectado
        # Refuerzo: fuerza el banco en cada fila si es dict
        if "rows" in payload and isinstance(payload["rows"], list):
            for row in payload["rows"]:
                if isinstance(row, dict):
                    row["bank"] = banco_detectado
    return payload


def _build_payment_mapped_fields(payment_detail: dict) -> dict[str, str]:
    if not isinstance(payment_detail, dict):
        return {}

    mapped: dict[str, str] = {}
    # Refuerzo: si el payload ya tiene 'bank', ese valor prevalece SIEMPRE
    bank = _normalize_text(str(payment_detail.get("bank") or ""))
    if bank:
        mapped["banco"] = bank
    banco_emisor = mapped.get("banco")

    metadata = payment_detail.get("metadata")
    if isinstance(metadata, dict):
        for key in (
            "tipo_pago",
            "fecha_hora_proceso",
            "fecha_hora_captura",
            "folio_internet",
            "numero_lote",
            "nombre_archivo",
            "usuario_sistema_nombre",
            "importe_detectado",
            "titular",
            "contrato",
            "divisa",
            "folio_firma",
            "folio_unico",
            "folio_operacion",
            "fecha_creacion",
            "fecha_aplicacion",
            "hora_captura",
            "motivo_pago",
            "solicitud_comentarios",
            "fecha_corte",
            "periodo",
            "descripcion_servicio",
            "resultado_traspaso",
            "estatus_detectados",
            "reporte_tipo",
        ):
            value = _normalize_text(str(metadata.get(key) or ""))
            if value:
                mapped[key] = value

    table = payment_detail.get("table")
    if not isinstance(table, dict):
        return mapped

    canonical_rows = table.get("canonical_rows")
    if not isinstance(canonical_rows, list):
        return mapped

    first_row = next(
        (
            row
            for row in canonical_rows
            if isinstance(row, dict)
            and any(_normalize_text(str(cell or "")) for cell in row.values())
        ),
        None,
    )
    if not isinstance(first_row, dict):
        return mapped

    key_map = {
        "cuenta": "cuenta",
        "cuenta_beneficiario": "cuenta_beneficiario",
        "cuenta_retiro": "cuenta_retiro",
        "banco_destino": "banco_destino",
        "referencia": "referencia",
        "importe": "importe",
        "concepto_pago": "concepto_pago",
        "clave_rastreo": "clave_rastreo",
        "nombre_beneficiario": "nombre_beneficiario",
        "nombre": "nombre",
        "apellido_paterno": "apellido_paterno",
        "apellido_materno": "apellido_materno",
        "estatus": "estatus",
        "tipo_operacion": "tipo_operacion",
        "forma_deposito": "forma_deposito",
        "tipo_registro": "tipo_registro",
        "tipo_movimiento": "tipo_movimiento",
        "numero_empleado": "numero_empleado",
        "tipo_cuenta": "tipo_cuenta",
        "codigo": "codigo",
        "descripcion": "descripcion",
        "divisa": "divisa",
        "titular": "titular",
        "contrato": "contrato",
        "folio_firma": "folio_firma",
        "folio_unico": "folio_unico",
        "folio_operacion": "folio_operacion",
        "motivo_pago": "motivo_pago",
    }
    for source_key, target_key in key_map.items():
        value = _normalize_text(str(first_row.get(source_key) or ""))
        if value:
            mapped[target_key] = value

    # Reconstruct nombre_beneficiario from available parts if not already present
    if "nombre_beneficiario" not in mapped:
        if "apellido_paterno" in mapped or "apellido_materno" in mapped:
            # Document had separate columns — combine them
            parts = [
                mapped.get("nombre", ""),
                mapped.get("apellido_paterno", ""),
                mapped.get("apellido_materno", ""),
            ]
            full_name = " ".join(p for p in parts if p).strip()
        else:
            # Document had a single name column — nombre contains full name
            full_name = mapped.get("nombre", "")
        if full_name:
            mapped["nombre_beneficiario"] = full_name

    return mapped


def _enrich_payment_table_payload(
    table_payload: dict | None,
    payment_detail: dict | None,
) -> dict | None:
    try:
        return _enrich_payment_table_payload_impl(table_payload, payment_detail)
    except Exception:
        logger.debug("_enrich_payment_table_payload: error during enrichment, returning original", exc_info=True)
        return table_payload


def _enrich_payment_table_payload_impl(
    table_payload: dict | None,
    payment_detail: dict | None,
) -> dict | None:
    if not isinstance(table_payload, dict):
        return table_payload
    if not isinstance(payment_detail, dict):
        return table_payload

    enriched = dict(table_payload)

    bank = _normalize_text(str(payment_detail.get("bank") or ""))
    if bank:
        enriched["bank"] = bank

    metadata = payment_detail.get("metadata")
    if isinstance(metadata, dict):
        metadata_clean: dict[str, str] = {}
        for key, value in metadata.items():
            text = _normalize_text(str(value or ""))
            if text:
                metadata_clean[str(key)] = text
        if metadata_clean:
            enriched["metadata"] = metadata_clean

    detail_table = payment_detail.get("table")
    if isinstance(detail_table, dict):
        canonical_columns_clean: list[str] = []
        canonical_rows_clean: list[dict[str, str]] = []
        display_columns_map: dict[str, str] = {}

        canonical_columns = detail_table.get("canonical_columns")
        if isinstance(canonical_columns, list):
            columns = [_normalize_text(str(column or "")) for column in canonical_columns if _normalize_text(str(column or ""))]
            if columns:
                canonical_columns_clean = columns
                enriched["canonical_columns"] = columns

        canonical_rows = detail_table.get("canonical_rows")
        if isinstance(canonical_rows, list):
            rows: list[dict[str, str]] = []
            for row in canonical_rows:
                if not isinstance(row, dict):
                    continue
                normalized_row: dict[str, str] = {}
                for key, value in row.items():
                    text = _normalize_text(str(value or ""))
                    if text:
                        normalized_row[str(key)] = text
                if normalized_row:
                    rows.append(normalized_row)
            if rows:
                canonical_rows_clean = rows
                enriched["canonical_rows"] = rows
                enriched["canonical_row_count"] = len(rows)

        # Propagate display_columns (original PDF header labels) to table payload
        display_columns = detail_table.get("display_columns")
        if isinstance(display_columns, dict) and display_columns:
            display_columns_map = {str(k): str(v) for k, v in display_columns.items() if str(v).strip()}
            enriched["display_columns"] = display_columns_map

        # Build a clean table view for advanced payroll exports so column order
        # matches the source PDF and ghost/composite headers are hidden.
        nomina_required = {
            "cuenta", "referencia", "importe", "nombre",
            "apellido_paterno", "apellido_materno", "estatus", "concepto_pago",
        }
        if canonical_columns_clean and canonical_rows_clean and nomina_required.issubset(set(canonical_columns_clean)):
            preferred_order = [
                "cuenta",
                "referencia",
                "importe",
                "nombre",
                "apellido_paterno",
                "apellido_materno",
                "estatus",
                "concepto_pago",
            ]
            ordered_cols = [col for col in preferred_order if col in canonical_columns_clean]
            ordered_cols.extend([col for col in canonical_columns_clean if col not in ordered_cols])

            label_fallback = {
                "cuenta": "Cuenta",
                "referencia": "REFERENCIA",
                "importe": "IMPORTE",
                "nombre": "Nombre",
                "apellido_paterno": "Apellido paterno",
                "apellido_materno": "Apellido materno",
                "estatus": "Estatus",
                "concepto_pago": "Concepto",
            }
            header_labels = [
                display_columns_map.get(col) or label_fallback.get(col, col.replace("_", " ").title())
                for col in ordered_cols
            ]
            clean_rows: list[list[str]] = [header_labels]
            for crow in canonical_rows_clean:
                clean_rows.append([_normalize_text(str(crow.get(col, "") or "")) for col in ordered_cols])
            if len(clean_rows) >= 2:
                enriched["rows"] = clean_rows
                enriched["row_count"] = len(clean_rows) - 1
                enriched["column_count"] = len(ordered_cols)
                enriched["canonical_columns"] = ordered_cols

        # When summary_tables exist (BBVA Grupo Pago multi-payment), replace
        # the raw structural rows with clean canonical data so the "Tabla
        # detectada" panel does not show junk footer fragments.
        # Only for BBVA grupo-pago — Scotiabank summary tables are additive
        # and should not replace the main table.
        summary_tables = detail_table.get("summary_tables")
        if isinstance(summary_tables, list) and summary_tables:
            enriched["summary_tables"] = summary_tables
            if bank.upper() == "BBVA" and not enriched.get("canonical_rows"):
                # canonical_rows is empty → grupo pago split is active
                first_st = summary_tables[0]
                if isinstance(first_st, dict) and first_st.get("columns"):
                    clean_header = [str(c) for c in first_st["columns"]]
                    clean_rows: list[list[str]] = [clean_header]
                    for st in summary_tables:
                        if isinstance(st, dict) and isinstance(st.get("rows"), list):
                            for r in st["rows"]:
                                if isinstance(r, list):
                                    clean_rows.append([str(c or "") for c in r])
                    enriched["rows"] = clean_rows
                    enriched["source"] = "payment_detail_summary"

    mapped_fields = _build_payment_mapped_fields(payment_detail)
    if mapped_fields:
        enriched["mapped_fields"] = mapped_fields

    return enriched


def _append_scotia_summary_rows_to_table(rows: list[list[str]], raw_text: str) -> list[list[str]]:
    if len(rows) < 2:
        return rows
    if _payment_detect_bank(raw_text) != "SCOTIABANK":
        return rows
    lines = [_ascii_fold(_normalize_text(line)).upper() for line in str(raw_text or "").splitlines() if _normalize_text(line)]
    if not lines:
        return rows
    summary_rows = _extract_scotia_summary_rows(lines)
    if not summary_rows:
        return rows

    existing = {"|".join(_normalize_table_cell(cell) for cell in row) for row in rows}
    appended = list(rows)
    for row in summary_rows:
        signature = "|".join(_normalize_table_cell(cell) for cell in row)
        if signature in existing:
            continue
        appended.append(row)
        existing.add(signature)
    return appended


def _payment_rows_look_low_quality(rows: list[list[str]]) -> bool:
    return _payment_rows_quality_score(rows) < 0


def _header_cell_has_repeated_tokens(cell: str) -> bool:
    tokens = [token for token in str(cell or "").strip().split() if token]
    if len(tokens) < 2:
        return False
    upper_tokens = [token.upper() for token in tokens]
    if all(token == upper_tokens[0] for token in upper_tokens):
        return True
    if len(upper_tokens) % 2 == 0:
        half = len(upper_tokens) // 2
        if upper_tokens[:half] == upper_tokens[half:]:
            return True
    return False


def _dedup_header_cell(cell: str) -> str:
    """Strip repeated token halves from multi-page OCR headers.

    Multi-page PDFs often produce concatenated headers when OCR merges pages:
    - "CUENTA CUENTA" → "CUENTA"
    - "REFERENCIA REFERENCIA" → "REFERENCIA"
    - "APELLIDO PATERNO APELLIDO MATERNO ESTATUS APELLIDO PATERNO APELLIDO MATERNO ESTATUS"
      → "APELLIDO PATERNO APELLIDO MATERNO ESTATUS"
    """
    tokens = str(cell or "").strip().split()
    if len(tokens) < 2:
        return str(cell or "").strip()
    upper_tokens = [t.upper() for t in tokens]
    # All same token: "CUENTA CUENTA" → "CUENTA"
    if all(t == upper_tokens[0] for t in upper_tokens):
        return tokens[0]
    # Even count, repeated halves
    if len(upper_tokens) % 2 == 0:
        half = len(upper_tokens) // 2
        if upper_tokens[:half] == upper_tokens[half:]:
            return " ".join(tokens[:half])
    # Try all possible repeat-unit lengths (smallest first)
    n = len(upper_tokens)
    for unit_len in range(2, n // 2 + 1):
        if n % unit_len == 0:
            unit = upper_tokens[:unit_len]
            if all(upper_tokens[i:i + unit_len] == unit for i in range(unit_len, n, unit_len)):
                return " ".join(tokens[:unit_len])
    # Fallback: check if the second half is a fuzzy repeat (handles OCR typos)
    if n >= 4:
        for half in range(n // 3, (n + 1) // 2 + 1):
            first_part = " ".join(upper_tokens[:half])
            second_part = " ".join(upper_tokens[half:])
            if first_part == second_part:
                return " ".join(tokens[:half])
    return str(cell or "").strip()


def _dedup_header_row(header: list[str]) -> list[str]:
    """Apply header cell deduplication to an entire header row."""
    return [_dedup_header_cell(cell) for cell in header]


def _payment_rows_quality_score(rows: list[list[str]]) -> int:
    if len(rows) < 2:
        return -100
    header = [str(cell or "").strip().upper() for cell in rows[0]]
    data = [str(cell or "").strip().upper() for cell in rows[1]]
    if len(header) < 3:
        return -80

    header_joined = " ".join(header)
    header_hits = sum(1 for token in _PAYMENT_TABLE_HEADER_TOKENS if token in header_joined)
    score = header_hits * 15
    score += min(10, len(rows) - 1) * 4
    score -= sum(max(0, len(cell) - 60) for cell in header) // 4
    score -= sum(max(0, len(cell) - 120) for cell in data) // 6

    # Penalizar headers con tokens duplicados (multi-página OCR)
    repeated_header_cells = sum(1 for cell in header if _header_cell_has_repeated_tokens(cell))
    score -= repeated_header_cells * 25

    data_joined = " ".join(data)
    noisy_fragments = (
        "UNIDAD ESPECIALIZADA",
        "ACLARACION",
        "TELEFONOS",
        "INSTITUCION",
        "COMPROBANTE",
        "LAPSO",
    )
    score -= sum(18 for fragment in noisy_fragments if fragment in data_joined)

    # Penalizar celdas con múltiples montos (multi-record-per-line)
    amount_hits = len(re.findall(r"\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\b", data_joined))
    if amount_hits >= 3:
        score -= 60
    elif amount_hits >= 2:
        score -= 35

    # Penalizar celdas con múltiples secuencias numéricas largas empaquetadas
    compact_number_hits = sum(1 for cell in data if len(re.findall(r"\b\d{10,24}\b", cell)) >= 2)
    if compact_number_hits >= 2:
        score -= 35
    elif compact_number_hits >= 1:
        score -= 18

    # Penalizar celdas de datos con metadatos del documento mezclados
    metadata_noise = (
        "NUMERODECONTRATO",
        "NUMERODESECUENCIA",
        "REPORTE DE OPERACIONES",
        "DISPERSION DE PAGO",
        "DATOSDELCLIENTE",
        "COMPROBANTE DE LA OPERACION",
    )
    for fragment in metadata_noise:
        if fragment in data_joined:
            score -= 22

    if "CUENTA" in header_joined and data:
        account_cell = data[0] if len(data) >= 1 else ""
        if account_cell and re.search(r"[A-Z]", account_cell):
            if any(token in account_cell for token in ("DATOS", "CLIENTE", "PAGADOR")):
                score -= 25
            if sum(ch.isdigit() for ch in account_cell) < 8:
                score -= 15
    if "REFERENCIA" in header_joined and len(data) >= 2:
        ref_cell = data[1]
        if ref_cell and re.search(r"[A-Z]", ref_cell):
            if any(token in ref_cell for token in ("DATOS", "CLIENTE", "PAGADOR", "REPORTE", "DISPERSION")):
                score -= 25
            if sum(ch.isdigit() for ch in ref_cell) < 8:
                score -= 15
    if re.search(r"\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})", data_joined):
        score += 12
    else:
        score -= 20
    return score


def _payment_header_token_index(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, cell in enumerate(header):
        normalized = _normalize_keyword(cell).lower()
        if normalized and normalized not in mapping:
            mapping[normalized] = idx
    return mapping


def _payment_header_alias(token: str) -> str:
    aliases = {
        "nocuentabeneficiario": "cuenta",
        "numerodecuenta": "cuenta",
        "numerodecuentadeabono": "cuenta",
        "cuentadedeposito": "cuenta",
        "cuentadeposito": "cuenta",
        "referenciadecarga": "referencia",
        "referencianumerica": "referencia",
        "clavebeneficiario": "referencia",
        "nombredelbeneficiario": "nombre",
        "nombrebeneficiario": "nombre",
        "conceptodepago": "concepto",
        "tipodemovimientopago": "concepto",
        "tipodemovimiento": "concepto",
    }
    return aliases.get(token, token)


def _merge_row_similarity(
    primary_row: list[str],
    backup_row: list[str],
    primary_idx: dict[str, int],
    backup_idx: dict[str, int],
) -> float:
    """Score how well a backup row matches a primary row (0..1).

    Compares overlapping non-empty cells from common columns; higher is better.
    Used for content-based row matching instead of positional offset.
    """
    matches = 0
    comparisons = 0
    for token, p_idx in primary_idx.items():
        if p_idx >= len(primary_row):
            continue
        p_val = _normalize_text(primary_row[p_idx]).upper()
        if not p_val:
            continue
        alias = _payment_header_alias(token)
        b_idx = backup_idx.get(alias)
        if b_idx is None or b_idx >= len(backup_row):
            continue
        b_val = _normalize_text(str(backup_row[b_idx] or "")).upper()
        if not b_val:
            continue
        comparisons += 1
        # Account/reference numbers: exact digit match
        p_digits = re.sub(r"\D", "", p_val)
        b_digits = re.sub(r"\D", "", b_val)
        if len(p_digits) >= 6 and len(b_digits) >= 6:
            if p_digits == b_digits:
                matches += 1
            continue
        if p_val == b_val or p_val in b_val or b_val in p_val:
            matches += 1
    if comparisons == 0:
        return 0.0
    return matches / comparisons


def _merge_payment_rows_with_backup(primary_rows: list[list[str]], backup_rows: list[list[str]]) -> list[list[str]]:
    """Merge backup rows into primary rows using content-based matching.

    Instead of purely positional offset merge (which breaks when one source
    misses a row), this uses a two-pass approach:
    1. If row counts match, use positional merge (fast path, order preserved).
    2. If row counts differ, find the best-matching backup row for each
       primary row using cell similarity, preventing cross-contamination.
    """
    try:
        return _merge_payment_rows_with_backup_impl(primary_rows, backup_rows)
    except Exception:
        logger.debug("_merge_payment_rows_with_backup: error, returning primary", exc_info=True)
        return primary_rows


def _merge_payment_rows_with_backup_impl(primary_rows: list[list[str]], backup_rows: list[list[str]]) -> list[list[str]]:
    if len(primary_rows) < 2 or len(backup_rows) < 2:
        return primary_rows

    primary_header = [str(cell or "") for cell in primary_rows[0]]
    backup_header = [str(cell or "") for cell in backup_rows[0]]
    if not primary_header or not backup_header:
        return primary_rows

    primary_idx = _payment_header_token_index(primary_header)
    backup_idx_raw = _payment_header_token_index(backup_header)
    backup_idx: dict[str, int] = {}
    for token, idx in backup_idx_raw.items():
        alias = _payment_header_alias(token)
        if alias and alias not in backup_idx:
            backup_idx[alias] = idx

    if not primary_idx or not backup_idx:
        return primary_rows

    def _fill_empty_cells(p_row: list[str], b_row: list[str]) -> list[str]:
        """Fill empty cells in primary row from backup row."""
        row = list(p_row)
        if len(row) < len(primary_header):
            row.extend([""] * (len(primary_header) - len(row)))
        for token, p_idx in primary_idx.items():
            if p_idx >= len(row):
                continue
            cell_val = _normalize_text(row[p_idx])
            if cell_val and cell_val.upper() != "NAN":
                continue
            alias = _payment_header_alias(token)
            b_idx = backup_idx.get(alias)
            if b_idx is None or b_idx >= len(b_row):
                continue
            backup_value = _normalize_text(str(b_row[b_idx] or ""))
            if backup_value:
                row[p_idx] = backup_value
        return row

    primary_data = primary_rows[1:]
    backup_data = backup_rows[1:]

    # Fast path: same row count → positional merge (order preserved)
    if len(primary_data) == len(backup_data):
        merged = []
        for p_row, b_row in zip(primary_data, backup_data):
            merged.append(_fill_empty_cells(list(p_row), b_row))

        # Supplement missing columns from backup
        primary_aliases = {_payment_header_alias(t) for t in primary_idx if _payment_header_alias(t)}
        missing_cols: list[tuple[str, int]] = []
        for token, b_idx in backup_idx_raw.items():
            alias = _payment_header_alias(token)
            if alias and alias not in primary_aliases:
                raw_label = str(backup_header[b_idx] if b_idx < len(backup_header) else token)
                if _is_junk_payment_header(raw_label):
                    continue  # skip footer/contact noise columns
                missing_cols.append((raw_label, b_idx))

        if missing_cols:
            result_header = list(primary_header)
            for col_label, _ in missing_cols:
                result_header.append(col_label)
            for row_i, row in enumerate(merged):
                b_row = backup_data[row_i] if row_i < len(backup_data) else []
                for _, b_col_idx in missing_cols:
                    if b_col_idx < len(b_row):
                        val = str(b_row[b_col_idx] or "")
                        row.append(val if val and val.upper() != "NAN" else "")
                    else:
                        row.append("")
            return [result_header] + merged

        return [primary_header] + merged

    # Content-based matching: for each primary row find best backup match
    # Track which backup index matched each primary position for ordering
    merged_data: list[list[str]] = []
    # Backup source index per merged row (None means no reliable match).
    merged_backup_indices: list[int | None] = []
    used_backup: set[int] = set()
    primary_to_backup: dict[int, int] = {}  # primary_idx → backup_idx
    for p_i, p_row in enumerate(primary_data):
        best_b_idx = -1
        best_sim = 0.3  # minimum similarity threshold
        for b_i, b_row in enumerate(backup_data):
            if b_i in used_backup:
                continue
            sim = _merge_row_similarity(list(p_row), b_row, primary_idx, backup_idx)
            if sim > best_sim:
                best_sim = sim
                best_b_idx = b_i
        if best_b_idx >= 0:
            used_backup.add(best_b_idx)
            primary_to_backup[p_i] = best_b_idx
            merged_data.append(_fill_empty_cells(list(p_row), backup_data[best_b_idx]))
            merged_backup_indices.append(best_b_idx)
        else:
            row = list(p_row)
            if len(row) < len(primary_header):
                row.extend([""] * (len(primary_header) - len(row)))
            merged_data.append(row)
            merged_backup_indices.append(None)

    # Insert unmatched backup rows at estimated positions (ordered by original
    # backup index, placed after the last matched primary row that maps to a
    # backup row before the unmatched one).
    unmatched_backups: list[tuple[int, list[str], int]] = []
    for b_i, b_row in enumerate(backup_data):
        if b_i in used_backup:
            continue
        new_row = [""] * len(primary_header)
        filled = 0
        for token, p_idx in primary_idx.items():
            if p_idx >= len(new_row):
                continue
            alias = _payment_header_alias(token)
            b_idx_val = backup_idx.get(alias)
            if b_idx_val is None or b_idx_val >= len(b_row):
                continue
            val = _normalize_text(str(b_row[b_idx_val] or ""))
            if val:
                new_row[p_idx] = val
                filled += 1
        if filled >= 2:
            # Find insertion point: after the last primary row whose matched
            # backup index is < b_i (preserves document order)
            insert_after = -1
            for p_i, mb_i in primary_to_backup.items():
                if mb_i < b_i and p_i > insert_after:
                    insert_after = p_i
            unmatched_backups.append((insert_after, new_row, b_i))

    # Insert in reverse order so indices remain valid
    unmatched_backups.sort(key=lambda x: x[0], reverse=True)
    for insert_after, new_row, source_b_idx in unmatched_backups:
        merged_data.insert(insert_after + 1, new_row)
        merged_backup_indices.insert(insert_after + 1, source_b_idx)

    # --- Supplement missing columns from backup ---
    # If the backup has columns that the primary doesn't (e.g., ESTATUS,
    # CONCEPTO), add them so no data is lost.
    primary_aliases = {_payment_header_alias(t) for t in primary_idx if _payment_header_alias(t)}
    missing_cols: list[tuple[str, int]] = []  # (backup_header_cell, backup_col_index)
    for token, b_idx in backup_idx_raw.items():
        alias = _payment_header_alias(token)
        if alias and alias not in primary_aliases:
            raw_label = str(backup_header[b_idx] if b_idx < len(backup_header) else token)
            if _is_junk_payment_header(raw_label):
                continue  # skip footer/contact noise columns
            missing_cols.append((raw_label, b_idx))

    if missing_cols:
        # Find matched backup rows for each merged_data row
        matched_backup_for_row: list[list[str] | None] = []
        for row_i in range(len(merged_data)):
            b_i = merged_backup_indices[row_i] if row_i < len(merged_backup_indices) else None
            if b_i is not None and b_i < len(backup_data):
                matched_backup_for_row.append(list(backup_data[b_i]))
            else:
                matched_backup_for_row.append(None)

        # Extend header and all data rows with the missing columns
        result_header = list(primary_header if len(primary_data) == len(backup_data) else primary_header)
        for col_label, _ in missing_cols:
            result_header.append(col_label)

        for row_i, row in enumerate(merged_data):
            backup_row = matched_backup_for_row[row_i] if row_i < len(matched_backup_for_row) else None
            for _, b_col_idx in missing_cols:
                if backup_row and b_col_idx < len(backup_row):
                    val = str(backup_row[b_col_idx] or "")
                    row.append(val if val and val.upper() != "NAN" else "")
                else:
                    # No matched backup row: keep empty to avoid synthetic values.
                    row.append("")

        return [result_header] + merged_data

    return [primary_header] + merged_data


def _payment_detect_bank(raw_text: str) -> str:
    text = _ascii_fold(str(raw_text or "")).upper()
    if "SCOTIABANK" in text or "SCOTIA BANK" in text:
        return "SCOTIABANK"
    if "BBVA" in text or "BANCOMER" in text or "REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS" in text:
        return "BBVA"
    if (
        any(token in text for token in ("BNET", "FOLIO DE INTERNET", "RESULTADO DEL TRASPASO"))
        and "CUENTA DE RETIRO" in text
        and ("CUENTA DE DEPOSITO" in text or "CUENTA DESTINO" in text)
    ):
        return "BBVA"
    if "SANTANDER" in text or "CONTRATO ENLACE" in text:
        return "SANTANDER"
    if "BANORTE" in text or "IXE" in text:
        return "BANORTE"
    if "BANAMEX" in text or "CITIBANAMEX" in text:
        return "BANAMEX"
    if "HSBC" in text:
        return "HSBC"
    if "INBURSA" in text:
        return "INBURSA"
    # Fallback: try to detect bank from CLABE prefix (first 3 digits)
    clabe_match = re.search(r"\b(\d{18})\b", text)
    if clabe_match:
        prefix = clabe_match.group(1)[:3]
        _CLABE_BANK = {
            "002": "BANAMEX", "012": "BBVA", "014": "SANTANDER",
            "021": "HSBC", "030": "BAJIO", "036": "INBURSA",
            "044": "SCOTIABANK", "072": "BANORTE", "058": "BANREGIO",
        }
        bank = _CLABE_BANK.get(prefix)
        if bank:
            return bank
    return "DESCONOCIDO"


def _payment_pick_labeled_value(raw_text: str, labels: list[str], max_len: int = 120) -> str:
    lines = [_ascii_fold(_normalize_text(line)).upper() for line in str(raw_text or "").splitlines() if _normalize_text(line)]
    for line in lines:
        for label in labels:
            key = _ascii_fold(_normalize_text(label)).upper()
            if line.startswith(key + ":"):
                return _normalize_text(line.split(":", 1)[1])[:max_len]
            if key + ":" in line:
                return _normalize_text(line.split(key + ":", 1)[1])[:max_len]
            if line.startswith(key + " "):
                remainder = _normalize_text(line[len(key):])
                if len(remainder) >= 2:
                    return remainder[:max_len]
    full = " ".join(lines)
    for label in labels:
        key = _ascii_fold(_normalize_text(label)).upper()
        match = re.search(rf"{re.escape(key)}\s*:?\s*(.+?)(?=\s+[A-Z0-9][A-Z0-9 .:/-]{{2,}}:\s*|$)", full)
        if match:
            return _normalize_text(match.group(1))[:max_len]
    return ""


# ── Level 1: Field-level data validation for payment table cells ───────────

_VALID_AMOUNT_FMT_RE = re.compile(r"^\$[\d,]+\.\d{2}$")
_VALID_DATE_FMT_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_VALID_ACCOUNT_FMT_RE = re.compile(r"^\d{6,20}$")
_VALID_CLABE_FMT_RE = re.compile(r"^\d{18}$")

_AMOUNT_HEADER_TOKENS = frozenset({
    "IMPORTE", "MONTO", "IMPORTEDETECTADO", "IMPORTETOTALMOVIMIENTOS",
    "IMPORTEMOVIMIENTOALTAS", "IMPORTEMOVIMIENTOSBAJAS",
    "TOTALIMPORTEDEMOVIMIENTOALTAS", "TOTALIMPORTEDEMOVIMIENTOSBAJAS",
})

_ACCOUNT_HEADER_TOKENS = frozenset({
    "CUENTA", "CUENTARETIRO", "CUENTABENEFICIARIO", "CUENTADEPOSITO",
    "CONTRATO", "NUMEROCONTRATO", "CLABE",
})

_DATE_HEADER_TOKENS = frozenset({
    "FECHA", "FECHAPAGO", "FECHAOPERACION", "FECHAAPLICACION",
    "FECHAHORAPROCESO", "FECHAHORACAPTURA",
})

_STATUS_HEADER_TOKENS = frozenset({"ESTATUS", "STATUS"})

_COUNT_HEADER_TOKENS = frozenset({
    "CANTIDADDEMOVIMIENTOSALTAS", "CANTIDADDEMOVIMIENTOSBAJAS",
    "TOTALCANTIDADDEMOVIMIENTOSALTAS", "TOTALCANTIDADDEMOVIMIENTOSBAJAS",
})


def _classify_table_columns(header: list[str]) -> dict[int, str]:
    """Classify each header column into a semantic type for validation."""
    classification: dict[int, str] = {}
    for idx, cell in enumerate(header):
        key = _normalize_keyword(str(cell or ""))
        if not key:
            continue
        if key in _COUNT_HEADER_TOKENS:
            classification[idx] = "count"
        elif key in _AMOUNT_HEADER_TOKENS or "IMPORTE" in key or "MONTO" in key:
            classification[idx] = "amount"
        elif key in _ACCOUNT_HEADER_TOKENS or "CUENTA" in key or "CLABE" in key:
            classification[idx] = "account"
        elif key in _DATE_HEADER_TOKENS or "FECHA" in key:
            classification[idx] = "date"
        elif key in _STATUS_HEADER_TOKENS:
            classification[idx] = "status"
    return classification


def _validate_payment_table_cells(rows: list[list[str]]) -> list[str]:
    """Level 1: Validate individual cell values against expected formats.

    Returns a list of human-readable warning strings for cells that don't
    match the expected format for their column type.  Does NOT modify rows.
    """
    if not rows or len(rows) < 2:
        return []

    header = rows[0]
    col_types = _classify_table_columns(header)
    if not col_types:
        return []

    warnings: list[str] = []

    for row_idx, row in enumerate(rows[1:], start=2):
        for col_idx, col_type in col_types.items():
            if col_idx >= len(row):
                continue
            cell = str(row[col_idx] or "").strip()
            if not cell:
                continue

            if col_type == "amount":
                if not _VALID_AMOUNT_FMT_RE.fullmatch(cell):
                    warnings.append(
                        f"Fila {row_idx}, col '{header[col_idx]}': "
                        f"formato de importe inválido '{cell[:40]}'"
                    )
                else:
                    # Check for impossible zero amounts in data rows
                    digits = re.sub(r"\D", "", cell)
                    if digits and int(digits) == 0:
                        warnings.append(
                            f"Fila {row_idx}, col '{header[col_idx]}': "
                            f"importe es $0.00"
                        )

            elif col_type == "account":
                digits = re.sub(r"\D", "", cell)
                if not _VALID_ACCOUNT_FMT_RE.fullmatch(digits):
                    warnings.append(
                        f"Fila {row_idx}, col '{header[col_idx]}': "
                        f"cuenta con longitud inválida ({len(digits)} dígitos) '{cell[:30]}'"
                    )

            elif col_type == "date":
                # Strip time portion if present
                date_part = cell.split(" ")[0] if " " in cell else cell
                if _VALID_DATE_FMT_RE.fullmatch(date_part):
                    try:
                        dd, mm, yyyy = date_part.split("/")
                        d, m, y = int(dd), int(mm), int(yyyy)
                        if m < 1 or m > 12:
                            warnings.append(
                                f"Fila {row_idx}, col '{header[col_idx]}': "
                                f"mes fuera de rango ({m}) en '{date_part}'"
                            )
                        elif d < 1 or d > 31:
                            warnings.append(
                                f"Fila {row_idx}, col '{header[col_idx]}': "
                                f"día fuera de rango ({d}) en '{date_part}'"
                            )
                        elif y < 1990 or y > 2099:
                            warnings.append(
                                f"Fila {row_idx}, col '{header[col_idx]}': "
                                f"año fuera de rango ({y}) en '{date_part}'"
                            )
                    except (ValueError, IndexError):
                        warnings.append(
                            f"Fila {row_idx}, col '{header[col_idx]}': "
                            f"fecha no parseable '{date_part}'"
                        )

            elif col_type == "status":
                upper_cell = cell.upper().strip()
                if upper_cell and upper_cell not in _ALL_PAYMENT_STATUSES:
                    # Try substring match before flagging
                    found = any(s in upper_cell for s in _ALL_PAYMENT_STATUSES)
                    if not found:
                        warnings.append(
                            f"Fila {row_idx}, col '{header[col_idx]}': "
                            f"estatus no reconocido '{cell[:30]}'"
                        )

            elif col_type == "count":
                digits = re.sub(r"\D", "", cell)
                if not digits:
                    warnings.append(
                        f"Fila {row_idx}, col '{header[col_idx]}': "
                        f"cantidad no numérica '{cell[:30]}'"
                    )

    return warnings


# ── Level 2: Cross-coherence validation ────────────────────────────────────

def _parse_amount_to_cents(amount_str: str) -> int | None:
    """Parse a $X,XXX.XX formatted amount into integer cents for safe arithmetic."""
    if not amount_str:
        return None
    m = re.search(r"\$?([\d,]+)\.(\d{2})", str(amount_str))
    if not m:
        return None
    try:
        integer_part = int(m.group(1).replace(",", ""))
        cents_part = int(m.group(2))
        return integer_part * 100 + cents_part
    except (ValueError, OverflowError):
        return None


def _format_cents_as_amount(cents: int) -> str:
    """Format integer cents back to $X,XXX.XX string."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    integer_part = cents // 100
    cents_part = cents % 100
    return f"{sign}${integer_part:,}.{cents_part:02d}"


def _validate_payment_table_coherence(rows: list[list[str]]) -> list[str]:
    """Level 2: Validate cross-row coherence in the payment table.

    Checks:
    1. Sum of individual IMPORTE values vs summary IMPORTE row (Scotiabank)
    2. Count of data rows vs CANTIDAD DE MOVIMIENTOS summary (Scotiabank)
    Returns a list of warning strings.  Does NOT modify rows.
    """
    if not rows or len(rows) < 3:
        return []

    header = rows[0]
    col_types = _classify_table_columns(header)
    if not col_types:
        return []

    # Find the primary importe and count columns
    importe_col: int | None = None
    count_col: int | None = None
    for idx, ctype in col_types.items():
        if ctype == "amount" and importe_col is None:
            importe_col = idx
        if ctype == "count" and count_col is None:
            count_col = idx

    warnings: list[str] = []

    # Identify summary rows vs data rows.
    # Summary rows have header-like labels (e.g. "CANTIDAD DE MOVIMIENTOS ALTAS")
    # in the first cell.  These are appended by _append_scotia_summary_rows_to_table.
    _SUMMARY_MARKERS = frozenset({
        "CANTIDADDEMOVIMIENTOSALTAS",
        "IMPORTEDEMOVIMIENTOALTAS",
        "CANTIDADDEMOVIMIENTOSBAJAS",
        "IMPORTEDEMOVIMIENTOSBAJAS",
        "TOTALCANTIDADDEMOVIMIENTOSALTAS",
        "TOTALIMPORTEDEMOVIMIENTOALTAS",
        "TOTALCANTIDADDEMOVIMIENTOSBAJAS",
        "TOTALIMPORTEDEMOVIMIENTOSBAJAS",
    })

    def _is_summary_row(row: list[str]) -> bool:
        """Return True if *any* cell in the row looks like a summary header."""
        for cell in row:
            key = _normalize_keyword(str(cell or ""))
            if key in _SUMMARY_MARKERS:
                return True
            # Also detect standalone summary header rows
            if any(marker in key for marker in ("CANTIDADDEMOVIMIENTO", "IMPORTEDEMOVIMIENTO")):
                return True
        return False

    # Separate data rows from summary rows
    data_rows: list[list[str]] = []
    summary_header_row: list[str] | None = None
    summary_value_row: list[str] | None = None

    i = 1  # skip header
    while i < len(rows):
        row = rows[i]
        if _is_summary_row(row):
            summary_header_row = row
            # The next row should be the values
            if i + 1 < len(rows):
                summary_value_row = rows[i + 1]
            break  # Stop at first summary block
        data_rows.append(row)
        i += 1

    if not data_rows:
        return []

    # ── Check 1: Sum of importes vs summary importe ─────────────────────
    if importe_col is not None and summary_header_row and summary_value_row:
        # Find the summary importe value
        summary_importe_idx: int | None = None
        for s_idx, s_cell in enumerate(summary_header_row):
            key = _normalize_keyword(str(s_cell or ""))
            if "IMPORTE" in key and "TOTAL" not in key and "BAJAS" not in key:
                summary_importe_idx = s_idx
                break

        if summary_importe_idx is not None and summary_importe_idx < len(summary_value_row):
            summary_amount_str = _normalize_payment_amount(
                str(summary_value_row[summary_importe_idx] or "")
            )
            summary_cents = _parse_amount_to_cents(summary_amount_str)

            if summary_cents is not None and summary_cents > 0:
                total_cents = 0
                parsed_count = 0
                for d_row in data_rows:
                    if importe_col < len(d_row):
                        cell_cents = _parse_amount_to_cents(str(d_row[importe_col] or ""))
                        if cell_cents is not None:
                            total_cents += cell_cents
                            parsed_count += 1

                if parsed_count > 0 and total_cents != summary_cents:
                    diff_cents = abs(total_cents - summary_cents)
                    # Only warn if difference exceeds 1% of the summary amount
                    # to tolerate minor OCR rounding errors
                    threshold = max(summary_cents * 0.01, 100)  # at least $1.00
                    if diff_cents > threshold:
                        warnings.append(
                            f"Suma de importes individuales "
                            f"({_format_cents_as_amount(total_cents)}) "
                            f"no coincide con resumen "
                            f"({_format_cents_as_amount(summary_cents)}), "
                            f"diferencia: {_format_cents_as_amount(diff_cents)}"
                        )

    # ── Check 2: Row count vs CANTIDAD DE MOVIMIENTOS ───────────────────
    if summary_header_row and summary_value_row:
        summary_count_idx: int | None = None
        for s_idx, s_cell in enumerate(summary_header_row):
            key = _normalize_keyword(str(s_cell or ""))
            if "CANTIDAD" in key and "TOTAL" not in key and "BAJAS" not in key:
                summary_count_idx = s_idx
                break

        if summary_count_idx is not None and summary_count_idx < len(summary_value_row):
            expected_count_str = _normalize_payment_count(
                str(summary_value_row[summary_count_idx] or "")
            )
            if expected_count_str:
                try:
                    expected_count = int(expected_count_str)
                    actual_count = len(data_rows)
                    if expected_count > 0 and actual_count != expected_count:
                        warnings.append(
                            f"Cantidad de filas de datos ({actual_count}) "
                            f"no coincide con resumen "
                            f"CANTIDAD DE MOVIMIENTOS ({expected_count})"
                        )
                except ValueError:
                    pass

    return warnings


def _extract_scotia_payment_metadata(raw_text: str) -> dict[str, str]:
    text = _ascii_fold(str(raw_text or "")).upper()
    out: dict[str, str] = {}
    date_match = re.search(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b", text)
    if date_match:
        normalized_date = _normalize_date_value(date_match.group(1))
        if normalized_date:
            out["fecha_archivo"] = normalized_date
    time_match = re.search(r"\b(\d{2}:\d{2}(?::\d{2})?)\b", text)
    if time_match:
        out["hora_archivo"] = time_match.group(1)
    contract_match = re.search(r"NUMERO DE CONTRATO SCOTIA EN LINEA\s*:?\s*([0-9OIL]{4,12})", text)
    if contract_match:
        out["numero_contrato_scotia_linea"] = _normalize_numeric_field(contract_match.group(1))
    folio_match = re.search(r"\bFOLIO\s*:?\s*([0-9OIL]{4,18})\b", text)
    if folio_match:
        out["folio"] = _normalize_numeric_field(folio_match.group(1))
    archivo_match = re.search(r"NOMBRE DEL ARCHIVO\s*:?\s*([A-Z0-9._ -]{6,80})", text)
    if archivo_match:
        out["nombre_archivo"] = _normalize_text(archivo_match.group(1))
    usuario_match = re.search(r"NOMBRE DE USUARIO DEL SISTEMA Y NOMBRE\s*:?\s*([A-Z0-9._ -]{6,120})", text)
    if usuario_match:
        out["usuario_sistema_nombre"] = _normalize_text(usuario_match.group(1))
    validacion_match = re.search(
        r"FECHA Y HORA DE VALIDACION DEL ARCHIVO\s*:?\s*([A-Z0-9:/ .-]{6,80})",
        text,
    )
    if validacion_match:
        out["fecha_hora_validacion_archivo"] = _normalize_text(validacion_match.group(1))
    registro_match = re.search(
        r"(SIN FECHA Y HORA DE REGISTRO|FECHA Y HORA DE REGISTRO\s*:?\s*[A-Z0-9:/ .-]{6,80})",
        text,
    )
    if registro_match:
        out["fecha_hora_registro"] = _normalize_text(registro_match.group(1))
    carga_match = re.search(
        r"TIPO DE REGISTRO\s+CUENTA DE CARGA\s+REFERENCIA DE CARGA\s+([A-Z]+)\s+([0-9OIL]{6,20})\s+([0-9OIL]{1,4})",
        text,
    )
    if carga_match:
        out["tipo_registro_carga"] = _normalize_text(carga_match.group(1))
        out["cuenta_carga"] = _normalize_numeric_field(carga_match.group(2))
        out["referencia_carga"] = _normalize_numeric_field(carga_match.group(3))
    for key, pattern in {
        "cantidad_total_movimientos": r"CANTIDAD TOTAL DE MOVIMIENTOS\s*:?\s*([0-9OIL]{1,6})",
        "cantidad_movimientos_altas": r"CANTIDAD DE MOVIMIENT(?:O|OS) ALTAS\s*:?\s*([0-9OIL]{1,6})",
        "cantidad_movimientos_bajas": r"CANTIDAD DE MOVIMIENT(?:O|OS) BAJAS\s*:?\s*([0-9OIL]{1,6})",
        "total_registros_leidos": r"TOTAL DE REGISTROS LEIDOS\s*:?\s*([0-9OIL]{1,6})",
    }.items():
        match = re.search(pattern, text)
        if match:
            normalized = _normalize_payment_count(match.group(1))
            if normalized:
                out[key] = normalized
    for key, pattern in {
        "importe_total_movimientos": r"IMPORTE TOTAL DE MOVIMIENTOS\s*:?\s*(\$?\s*[0-9OIL.,]{4,20})",
        "importe_movimiento_altas": r"IMPORTE DE MOVIMIENT(?:O|OS) ALTAS\s*:?\s*(\$?\s*[0-9OIL.,]{4,20})",
        "importe_movimientos_bajas": r"IMPORTE DE MOVIMIENT(?:O|OS) BAJAS\s*:?\s*(\$?\s*[0-9OIL.,]{4,20})",
    }.items():
        match = re.search(pattern, text)
        if match:
            normalized = _normalize_payment_amount(match.group(1))
            if normalized:
                out[key] = normalized
    return out


def _extract_bbva_payment_metadata(raw_text: str) -> dict[str, str]:
    text = _ascii_fold(str(raw_text or "")).upper()
    out: dict[str, str] = {}
    if "REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS" in text:
        out["reporte_tipo"] = "REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS"
    payment_type = re.search(r"TIPO DE PAGO\s*:?\s*([A-Z ]{4,80})", text)
    if payment_type:
        out["tipo_pago"] = _normalize_text(payment_type.group(1)).upper()
    accepted = re.findall(r"\b(APLICADO|ACEPTADO|TRANSMITIDO|RECHAZADO)\b", text)
    if accepted:
        out["estatus_detectados"] = ",".join(sorted(set(accepted)))
    amount_matches = re.findall(
        r"\$?\s*([0-9OIL]{1,3}(?:[.,][0-9OIL]{3})*(?:[.,][0-9OIL]{2}))", text,
    )
    if amount_matches:
        best_amount = ""
        best_value = 0.0
        for raw_amt in amount_matches:
            normalized = _normalize_payment_amount("$" + raw_amt)
            if normalized:
                try:
                    val = float(normalized.replace("$", "").replace(",", ""))
                    if val > best_value:
                        best_value = val
                        best_amount = normalized
                except ValueError:
                    if not best_amount:
                        best_amount = normalized
        if best_amount:
            out["importe_detectado"] = best_amount
    process_dt = re.search(
        r"(?:FECHA(?:\s+Y\s+HORA)?\s+DE\s+PROCESO|FECHA(?:\s+DE)?\s+TRANSMISION)\s*:?\s*([A-Z0-9:/ .-]{8,80})",
        text,
    )
    if process_dt:
        out["fecha_hora_proceso"] = _normalize_text(process_dt.group(1))
    capture_dt = re.search(
        r"FECHA\s+Y\s+HORA\s+DE\s+CAPTURA\s*:?\s*([A-Z0-9:/ .-]{8,80})",
        text,
    )
    if capture_dt:
        out["fecha_hora_captura"] = _normalize_text(capture_dt.group(1))
    folio_internet = re.search(r"FOLIO\s+DE\s+INTERNET\s*:?\s*([0-9OIL]{4,20})", text)
    if folio_internet:
        normalized_folio = _normalize_numeric_field(folio_internet.group(1))
        if re.fullmatch(r"\d{4,20}", normalized_folio):
            out["folio_internet"] = normalized_folio
    archivo_value = _payment_pick_labeled_value(raw_text, ["NOMBRE DE ARCHIVO", "ARCHIVO"], max_len=120)
    if archivo_value and ("." in archivo_value or "_" in archivo_value or re.search(r"\d", archivo_value)):
        out["nombre_archivo"] = _normalize_text(archivo_value)
    else:
        archivo_match = re.search(r"(?:NOMBRE\s+DE\s+ARCHIVO|ARCHIVO)\s*:\s*([A-Z0-9._ -]{6,120})", text)
        if archivo_match:
            out["nombre_archivo"] = _normalize_text(archivo_match.group(1))
    usuario_match = re.search(r"(?:USUARIO|OPERADOR)\s*:?\s*([A-Z0-9._ -]{4,80})", text)
    if usuario_match:
        out["usuario_sistema_nombre"] = _normalize_text(usuario_match.group(1))
    lote_match = re.search(r"(?:LOTE|LOTE\s+ID|NO\.?\s+DE\s+LOTE)\s*:?\s*([0-9OIL]{1,12})", text)
    if lote_match:
        out["numero_lote"] = _normalize_numeric_field(lote_match.group(1))
    archivo_num_match = re.search(r"(?:NO\.?\s+DE\s+ARCHIVO|ARCHIVO\s+NO)\s*:?\s*([0-9OIL]{1,12})", text)
    if archivo_num_match:
        out["numero_archivo_en_dia"] = _normalize_numeric_field(archivo_num_match.group(1))

    # --- BBVA transfer receipt / comprobante de traspaso fields ---
    is_transfer = any(
        token in text
        for token in (
            "COMPROBANTE",
            "RESULTADO DEL TRASPASO",
            "PAGO MISMO BANCO",
            "OPERACION AUTORIZADA",
            "DATOS DE CONFIRMACION",
            "FOLIO DE FIRMA",
        )
    )
    if is_transfer:
        # Titular
        titular_match = re.search(
            r"(?:TITULAR(?:\s+DE\s+LA\s+CUENTA)?)\s*:?\s*([A-Z .']{4,120})",
            text,
        )
        if titular_match:
            out["titular"] = _normalize_name(titular_match.group(1))
        # Contrato
        contrato_match = re.search(r"(?:NUM\.?\s*CONTRATO|CONTRATO)\s*:?\s*(\d{4,20})", text)
        if contrato_match:
            out["contrato"] = contrato_match.group(1)
        # Divisa
        divisa_match = re.search(r"DIVISA\s*:?\s*([A-Z]{2,10})", text)
        if divisa_match:
            out["divisa"] = _normalize_text(divisa_match.group(1))
        # Folio de firma
        folio_firma_match = re.search(r"FOLIO\s+DE\s+FIRMA\s*:?\s*([A-Z0-9 -]{4,30})", text)
        if folio_firma_match:
            out["folio_firma"] = _normalize_text(folio_firma_match.group(1))
        # Folio unico
        folio_unico_match = re.search(r"FOLIO\s+UNICO\s*:?\s*([A-Z0-9 -]{4,30})", text)
        if folio_unico_match:
            out["folio_unico"] = _normalize_text(folio_unico_match.group(1))
        # Folio de operacion
        folio_op_match = re.search(r"FOLIO\s+(?:DE\s+)?OPERACION\s*:?\s*([A-Z0-9 -]{4,30})", text)
        if folio_op_match and "folio_internet" not in out:
            out["folio_operacion"] = _normalize_text(folio_op_match.group(1))
        # Fecha de creacion
        fecha_creacion_match = re.search(
            r"FECHA\s+DE\s+CREACION\s*:?\s*([0-9A-Z:/ .-]{8,40})", text
        )
        if fecha_creacion_match:
            out["fecha_creacion"] = _normalize_text(fecha_creacion_match.group(1))
        # Fecha de aplicacion
        fecha_aplicacion_match = re.search(
            r"FECHA\s+DE\s+APLICACION\s*:?\s*([0-9A-Z:/ .-]{8,40})", text
        )
        if fecha_aplicacion_match:
            out["fecha_aplicacion"] = _normalize_text(fecha_aplicacion_match.group(1))
        # Hora de captura
        hora_captura_match = re.search(
            r"HORA\s+DE\s+CAPTURA\s*:?\s*([0-9:. -]{4,20})", text
        )
        if hora_captura_match and "fecha_hora_captura" not in out:
            out["hora_captura"] = _normalize_text(hora_captura_match.group(1))
        # Motivo de pago
        motivo_match = re.search(
            r"MOTIVO\s+DE\s+PAGO\s*:?\s*([A-Z0-9 ._/-]{2,80})", text
        )
        if motivo_match:
            out["motivo_pago"] = _normalize_text(motivo_match.group(1))
        # Solicitud de comentarios
        solicitud_match = re.search(
            r"SOLICITUD\s+DE\s+COMENTARIOS\s*:?\s*([A-Z0-9 ._/-]{2,120})", text
        )
        if solicitud_match:
            out["solicitud_comentarios"] = _normalize_text(solicitud_match.group(1))
        # Fecha de corte
        fecha_corte_match = re.search(
            r"FECHA\s+DE\s+CORTE\s*:?\s*([0-9A-Z:/ .-]{6,40})", text
        )
        if fecha_corte_match:
            out["fecha_corte"] = _normalize_text(fecha_corte_match.group(1))
        # Periodo
        periodo_match = re.search(
            r"PERIODO\s*:?\s*([A-Z0-9 /_.-]{4,60})", text
        )
        if periodo_match:
            out["periodo"] = _normalize_text(periodo_match.group(1))
        # Descripcion del servicio
        desc_match = re.search(
            r"DESCRIPCION(?:\s+DEL\s+SERVICIO)?\s*:?\s*([A-Z0-9 ._/-]{2,120})", text
        )
        if desc_match:
            out["descripcion_servicio"] = _normalize_text(desc_match.group(1))
        # Resultado del traspaso
        resultado_match = re.search(
            r"RESULTADO\s+DEL\s+TRASPASO\s*:?\s*([A-Z ]{4,60})", text
        )
        if resultado_match:
            out["resultado_traspaso"] = _normalize_text(resultado_match.group(1))
        # Tipo de operacion (BBVA transfer)
        tipo_op_match = re.search(
            r"TIPO\s+DE\s+OPERACION\s*:?\s*([A-Z ]{4,80}?)(?=\s+(?:FOLIO|CUENTA|BANCO|IMPORTE|FECHA)\b|$)",
            text,
        )
        if tipo_op_match and "tipo_pago" not in out:
            out["tipo_pago"] = _normalize_text(tipo_op_match.group(1)).upper()

    return out


def _extract_santander_payment_metadata(raw_text: str) -> dict[str, str]:
    """Extract Santander-specific metadata from nómina payment documents."""
    text = _ascii_fold(str(raw_text or "")).upper()
    out: dict[str, str] = {}

    # Tipo de operación
    op_type = re.search(r"TIPO\s+DE\s+OPERACION\s*:?\s*([A-Z ]{4,80}?)(?=\s+(?:FECHA|CUENTA|NUMERO|ESTATUS)\b|$)", text)
    if op_type:
        out["tipo_operacion"] = _normalize_text(op_type.group(1)).upper()

    # Número de contrato ENLACE
    contrato = re.search(r"(?:NUMERO\s+DE\s+)?CONTRATO\s*(?:ENLACE)?\s*:?\s*(\d{8,20})", text)
    if contrato:
        out["numero_contrato"] = contrato.group(1)

    # Cuenta cargo
    cuenta_cargo = re.search(r"CUENTA\s+CARGO\s*:?\s*(\d{8,20})", text)
    if cuenta_cargo:
        out["cuenta_cargo"] = cuenta_cargo.group(1)

    # Fecha de envío de pago
    fecha_envio = re.search(r"FECHA\s+DE\s+ENVIO\s+DE\s+PAGO\s*:?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})", text)
    if fecha_envio:
        out["fecha_hora_proceso"] = _normalize_date_value(fecha_envio.group(1))

    # Número de secuencia del archivo
    secuencia = re.search(r"(?:NUMERO\s+DE\s+)?SECUENCIA\s+DEL?\s+ARCHIVO\s*:?\s*([A-Z0-9]{10,40})", text)
    if secuencia:
        out["numero_secuencia_archivo"] = secuencia.group(1)

    # Importe total
    importe_total = re.search(r"IMPORTE\s+TOTAL\s*:?\s*(\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))", text)
    if importe_total:
        normalized = _normalize_payment_amount(importe_total.group(1))
        if normalized:
            out["importe_detectado"] = normalized

    # Total de registros
    total_regs = re.search(r"TOTAL\s+DE\s+REGISTROS\s*:?\s*(\d{1,6})", text)
    if total_regs:
        out["total_registros"] = total_regs.group(1)

    # Dispersión marker
    if "DISPERSION" in text and "NOMINA" in text:
        out["tipo_pago"] = "DISPERSION DE PAGO DE NOMINA"

    return out


def _extract_generic_bank_payment_metadata(raw_text: str, bank: str) -> dict[str, str]:
    """Extract metadata for banks without a dedicated handler (HSBC, BANAMEX, INBURSA, BANREGIO, BAJIO).

    Uses broad label patterns that cover common Mexican bank payment document formats.
    """
    text = _ascii_fold(str(raw_text or "")).upper()
    out: dict[str, str] = {}

    # Common labels across multiple Mexican banks
    _GENERIC_LABELS: list[tuple[str, list[str]]] = [
        ("folio_operacion", ["FOLIO DE CONFIRMACION", "FOLIO DE OPERACION", "FOLIO OPERACION", "NO. DE OPERACION", "NUMERO DE OPERACION"]),
        ("tipo_pago", ["TIPO DE PAGO", "TIPO DE OPERACION", "TIPO OPERACION", "CONCEPTO DE PAGO"]),
        ("cuenta_cargo", ["CUENTA CARGO", "CUENTA ORIGEN", "CUENTA DE CARGO", "CUENTA ORDENANTE"]),
        ("cuenta_beneficiario", ["CUENTA DESTINO", "CUENTA BENEFICIARIO", "CUENTA DE ABONO", "CUENTA CLABE"]),
        ("nombre_beneficiario", ["BENEFICIARIO", "NOMBRE DEL BENEFICIARIO", "NOMBRE BENEFICIARIO"]),
        ("titular", ["TITULAR", "NOMBRE DEL TITULAR", "CLIENTE"]),
        ("importe_detectado", ["MONTO TOTAL", "MONTO", "IMPORTE TOTAL", "TOTAL A PAGAR", "IMPORTE"]),
        ("referencia_carga", ["REFERENCIA", "REFERENCIA NUMERICA", "NUMERO DE REFERENCIA"]),
        ("fecha_hora_proceso", ["FECHA DE OPERACION", "FECHA OPERACION", "FECHA DE PAGO", "FECHA PAGO", "FECHA VALOR"]),
        ("banco_destino", ["BANCO DESTINO", "BANCO BENEFICIARIO", "BANCO RECEPTOR", "INSTITUCION DESTINO"]),
        ("numero_contrato", ["CONTRATO", "NUMERO DE CONTRATO", "NO. DE CONTRATO"]),
    ]

    for key, labels in _GENERIC_LABELS:
        if key in out:
            continue
        value = _payment_pick_labeled_value(raw_text, labels, max_len=180)
        if value:
            out[key] = value

    # Amount detection — look for labeled amount first, then any standalone amount
    if "importe_detectado" not in out:
        amount_match = re.search(
            r"(?:MONTO|IMPORTE|TOTAL)\s*:?\s*(\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))",
            text,
        )
        if amount_match:
            normalized = _normalize_payment_amount(amount_match.group(1))
            if normalized:
                out["importe_detectado"] = normalized

    # Bank brand detection for logging/metadata
    if bank and bank != "DESCONOCIDO":
        out.setdefault("banco_detectado", bank)

    return out


def _extract_scotia_summary_tables(raw_text: str) -> list[dict]:
    text = str(raw_text or "")
    if not text.strip():
        return []
    lines = [_ascii_fold(_normalize_text(line)).upper() for line in text.splitlines() if _normalize_text(line)]
    if not lines:
        return []

    tables: list[dict] = []
    normal_values = _extract_scotia_summary_block_values(lines, total=False)
    if normal_values:
        tables.append(
            {
                "title": "RESUMEN MOVIMIENTOS",
                "columns": [
                    "CANTIDAD DE MOVIMIENTOS ALTAS",
                    "IMPORTE DE MOVIMIENTO ALTAS",
                    "CANTIDAD DE MOVIMIENTOS BAJAS",
                    "IMPORTE DE MOVIMIENTOS BAJAS",
                ],
                "rows": [normal_values],
            }
        )

    total_values = _extract_scotia_summary_block_values(lines, total=True)
    if total_values:
        tables.append(
            {
                "title": "RESUMEN TOTAL",
                "columns": [
                    "TOTAL CANTIDAD DE MOVIMIENTOS ALTAS",
                    "TOTAL IMPORTE DE MOVIMIENTO ALTAS",
                    "TOTAL CANTIDAD DE MOVIMIENTOS BAJAS",
                    "TOTAL IMPORTE DE MOVIMIENTOS BAJAS",
                ],
                "rows": [total_values],
            }
        )

    return tables


def _sanitize_payment_metadata(metadata: dict[str, str]) -> dict[str, str]:
    if not metadata:
        return {}
    cleaned: dict[str, str] = {}
    date_keys = {"fecha_archivo"}
    datetime_keys = {"fecha_hora_validacion_archivo", "fecha_hora_registro", "fecha_hora_proceso", "fecha_hora_captura"}
    time_keys = {"hora_archivo"}
    amount_keys = {"importe_total_movimientos", "importe_movimiento_altas", "importe_movimientos_bajas", "importe_detectado"}
    count_keys = {"cantidad_total_movimientos", "cantidad_movimientos_altas", "cantidad_movimientos_bajas", "total_registros_leidos"}
    numeric_keys = {
        "numero_contrato_scotia_linea",
        "folio",
        "folio_internet",
        "numero_archivo_en_dia",
        "numero_contrato_servicio",
        "numero_lote",
        "cuenta_carga",
        "referencia_carga",
    }
    for key, value in metadata.items():
        raw = _normalize_text(str(value or ""))
        if not raw:
            continue
        if key in date_keys:
            normalized = _normalize_date_value(raw)
            if re.fullmatch(r"\d{2}/\d{2}/\d{4}", normalized):
                cleaned[key] = normalized
            continue
        if key in datetime_keys:
            normalized = _normalize_payment_datetime(raw)
            if normalized:
                cleaned[key] = normalized
            continue
        if key in time_keys:
            time_match = re.search(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", raw)
            if time_match:
                cleaned[key] = time_match.group(0)
            continue
        if key in amount_keys:
            normalized = _normalize_payment_amount(raw)
            if normalized:
                cleaned[key] = normalized
            continue
        if key in count_keys:
            normalized = _normalize_payment_count(raw)
            if normalized:
                cleaned[key] = normalized
            continue
        if key in numeric_keys:
            normalized = _normalize_numeric_field(raw)
            if key in {"folio", "folio_internet"} and len(normalized) < 4:
                continue
            if normalized:
                cleaned[key] = normalized
            continue
        if key in {
            "nombre_archivo",
            "usuario_sistema_nombre",
            "nombre_contrato_scotia_linea",
            "nombre_empresa",
            "reporte_tipo",
            "tipo_pago",
            "tipo_registro_carga",
        }:
            cleaned[key] = _normalize_text(raw).upper()
            continue
        cleaned[key] = raw
    return cleaned


def _payment_header_keys_from_cells(cells: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: dict[str, int] = {}
    for idx, cell in enumerate(cells):
        base = _normalize_keyword(cell).lower()
        if not base:
            base = f"columna_{idx + 1}"
        count = seen.get(base, 0) + 1
        seen[base] = count
        normalized.append(base if count == 1 else f"{base}_{count}")
    return normalized


def _build_display_columns_map(raw_rows: list[list[str]], bank: str) -> dict[str, str]:
    """Map canonical column keys → original PDF header labels.

    Enables the frontend to show column headers exactly as they appear
    in the source PDF rather than generic canonical names.
    """
    if not raw_rows:
        return {}
    raw_headers = raw_rows[0]
    if not raw_headers:
        return {}

    normalized_keys = _payment_header_keys_from_cells(raw_headers)
    display_map: dict[str, str] = {}
    for raw_header, norm_key in zip(raw_headers, normalized_keys):
        canonical_key = _canonical_payment_key(bank, norm_key)
        if not canonical_key:
            continue
        label = _dedup_header_cell(str(raw_header or "").strip())
        if label:
            display_map[canonical_key] = label

    # If nombre_beneficiario was mapped but we keep full name as "nombre",
    # carry the original label forward.
    if "nombre_beneficiario" in display_map and "nombre" not in display_map:
        display_map["nombre"] = display_map["nombre_beneficiario"]
    display_map.pop("nombre_beneficiario", None)

    return display_map


_SUMMARY_ROW_MARKERS = frozenset({
    "CANTIDAD DE MOVIMIENTOS ALTAS",
    "IMPORTE DE MOVIMIENTO ALTAS",
    "CANTIDAD DE MOVIMIENTOS BAJAS",
    "IMPORTE DE MOVIMIENTOS BAJAS",
    "TOTAL CANTIDAD DE MOVIMIENTOS ALTAS",
    "TOTAL IMPORTE DE MOVIMIENTO ALTAS",
    "TOTAL CANTIDAD DE MOVIMIENTOS BAJAS",
    "TOTAL IMPORTE DE MOVIMIENTOS BAJAS",
})


def _is_summary_row(row: list[str]) -> bool:
    """Detect Scotia-style summary rows that should NOT be in the main table.

    Summary rows have sub-header cells like 'CANTIDAD DE MOVIMIENTOS ALTAS'
    or are the data row immediately following such a sub-header.
    """
    for cell in row:
        upper = str(cell or "").strip().upper()
        if upper in _SUMMARY_ROW_MARKERS:
            return True
        if "CANTIDAD DE MOVIMIENTO" in upper or "IMPORTE DE MOVIMIENTO" in upper:
            return True
        if "TOTAL CANTIDAD" in upper or "TOTAL IMPORTE" in upper:
            return True
    return False


_METADATA_NOISE_PATTERNS = (
    "NUMERODECONTRATO",
    "NUMERO DE CONTRATO",
    "NUMERODESECUENCIA",
    "NUMERO DE SECUENCIA",
    "COMPROBANTE DE LA OPERACION",
    "DATOS DEL CLIENTE PAGAD",
    "DATOSDELCLIENTE",
)

# Short metadata labels that appear in BBVA/bank header sections.
# When a row has very few non-empty cells and those cells match these
# prefixes, the row is metadata noise — not payment data.
_METADATA_LABEL_PREFIXES = (
    "FECHA Y HO", "FECHA DE", "BBVA NET", "BBVA ME", "DATOS D",
    "ESTADO", "ESTATUS",
    "REPORTE DE", "COMPROBANTE", "DISPERSION",
    "NUMERO DE CON", "NUMERO DE SEC", "TIPO DE PAGO",
    "FECHA DE ENV", "FECHA DE TRANS",
    "DATOS DEL C", "OPERACION RE",
    "TRANSF", "TRA ", "PAGO", "PA ",
    "CONCEPTO", "IMPORTE", "MONEDA", "DIVISA",
    "TITULAR", "CUENTA DE", "FOLIO",
    "HORA DE", "MOTIVO",
)


def _is_metadata_row(row: list[str], expected_cols: int = 0) -> bool:
    """Detect metadata label rows that leaked into the table.

    Rows containing document metadata labels (contract numbers, sequence IDs,
    etc.) should NOT be data rows in the payment table.

    *expected_cols*: when provided (>0), the number of columns the header row
    has.  In wide tables (≥5 cols), rows with very few non-empty cells are
    almost certainly metadata noise, not real data.
    """
    row_joined = " ".join(str(cell or "").strip().upper() for cell in row)
    noise_count = sum(1 for pat in _METADATA_NOISE_PATTERNS if pat in row_joined)
    if noise_count >= 2:
        return True

    non_empty = [str(c or "").strip() for c in row if str(c or "").strip()]

    # ── Wide-table heuristic ───────────────────────────────────────────
    # In tables with many columns (≥5), real data rows always populate
    # several cells.  A row with only 1 non-empty cell is metadata noise
    # (e.g. "Fecha y ho", "Tra", "D", "Es" from BBVA headers).
    if expected_cols >= 5:
        if len(non_empty) <= 1:
            return True
        # 2 non-empty cells that are short text → still metadata labels
        if len(non_empty) == 2:
            combined_len = sum(len(c) for c in non_empty)
            if combined_len <= 25:
                combined = " ".join(non_empty).upper()
                if any(combined.startswith(prefix) for prefix in _METADATA_LABEL_PREFIXES):
                    return True
                # Very short orphan text (e.g. "PA", "D", "Es") not matching
                # a prefix is still noise if each cell is ≤ 4 chars.
                if all(len(c) <= 4 for c in non_empty):
                    return True

    # Rows with very few non-empty cells that are metadata labels (not data)
    if len(non_empty) <= 2 and non_empty:
        combined = " ".join(non_empty).upper()
        if any(combined.startswith(prefix) for prefix in _METADATA_LABEL_PREFIXES):
            return True

    # If a cell IS a known metadata label (not data), skip the row
    for cell in row:
        upper = str(cell or "").strip().upper()
        if not upper:
            continue
        # Pure metadata labels (short text with colon-like patterns)
        if upper in ("TIPO DE OPERACION:", "FECHA DE ENVIO DE PAGO:", "CUENTA", "IMPORTE", "NOMBRE"):
            # Check if this looks like a re-emitted header instead of data
            if upper in ("CUENTA", "IMPORTE", "NOMBRE"):
                non_empty_cells = [c for c in row if str(c or "").strip()]
                # If most cells are header-like tokens, this is a re-emitted header
                header_like = sum(1 for c in non_empty_cells if _normalize_keyword(c).upper() in
                    ("CUENTA", "IMPORTE", "NOMBRE", "REFERENCIA", "ESTATUS", "CONCEPTO",
                     "APELLIDOPATERNO", "APELLIDOMATERNO"))
                if header_like >= 3:
                    return True
    return False


def _clean_metadata_from_cell(value: str) -> str:
    """Remove metadata fragments from a data cell value."""
    text = str(value or "").strip()
    if not text:
        return ""
    # Remove patterns like "NUMERODECONTRATOENLACE:80122978989"
    text = re.sub(r"NUMERO\s*DE\s*CONTRATO\s*(?:ENLACE)?[:\s]*\d+", "", text, flags=re.IGNORECASE)
    # Remove patterns like "NUMERODESECUENCIADELARCHIVO:992026011513432707Z426"
    text = re.sub(r"NUMERO\s*DE\s*SECUENCIA\s*DEL?\s*ARCHIVO[:\s]*[\w]+", "", text, flags=re.IGNORECASE)
    # Remove "COMPROBANTE DE LA OPERACION" repeated noise
    text = re.sub(r"(?:COMPROBANTE\s+DE\s+LA\s+OPERACION\s*)+", "", text, flags=re.IGNORECASE)
    # Remove "DISPERSION DE PAGO DE NOMINA" repeated noise (when it's noise, not data)
    text = re.sub(r"(?:DISPERSION\s+DE\s+PAGO\s+DE\s+NOMINA\s*){2,}", "", text, flags=re.IGNORECASE)
    # Remove "REPORTE DE OPERACIONES" noise
    text = re.sub(r"REPORTE\s+DE\s+OPERACIONES\s*", "", text, flags=re.IGNORECASE)
    # Remove "DATOSDELCLIENTEPAGAD..." noise
    text = re.sub(r"DATOS\s*DEL?\s*CLIENTE\s*PAGAD\w*", "", text, flags=re.IGNORECASE)
    # Remove "Estatus:Procesado" repeated noise
    text = re.sub(r"(?:Estatus\s*:\s*\w+\s*){2,}", "", text, flags=re.IGNORECASE)
    # Remove "Concepto:Pago de Nomina" repeated noise
    text = re.sub(r"(?:Concepto\s*:\s*(?:Pago\s+de\s+(?:N[oó]mina|Nomina))\s*){2,}", "", text, flags=re.IGNORECASE)
    # Remove "Concepto 2:" repeated noise
    text = re.sub(r"(?:Concepto\s+\d+\s*:\s*){2,}", "", text, flags=re.IGNORECASE)
    # Remove "Importe:$NNN.NN MXN" repeated noise
    text = re.sub(r"(?:Importe\s*:\s*\$[\d,.]+\s*MXN\s*){2,}", "", text, flags=re.IGNORECASE)
    # Remove "Apellido paterno:XXXX" / "Apellido materno:XXXX" labels
    text = re.sub(r"Apellido\s+(?:paterno|materno)\s*:", "", text, flags=re.IGNORECASE)
    # Collapse whitespace
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def _payment_rows_to_objects(rows: list[list[str]]) -> list[dict]:
    if not rows or len(rows) < 2:
        return []
    try:
        header = rows[0]
        keys = _payment_header_keys_from_cells(header)
        if not keys:
            return []
        _expected_cols = len(header)
        objects: list[dict] = []
        for row in rows[1:]:
            try:
                # Skip summary sub-header/data rows (extracted separately)
                if _is_summary_row(row):
                    continue
                # Skip metadata label rows that leaked into the table
                if _is_metadata_row(row, expected_cols=_expected_cols):
                    continue
                item: dict[str, str] = {}
                for idx, key in enumerate(keys):
                    if idx >= len(row):
                        item[key] = ""
                    else:
                        cleaned = _clean_metadata_from_cell(str(row[idx] or ""))
                        item[key] = _normalize_text(cleaned)
                if any(str(v).strip() for v in item.values()):
                    objects.append(item)
            except Exception:
                continue
        return objects[:500]
    except Exception:
        logger.debug("_payment_rows_to_objects: error converting rows", exc_info=True)
        return []


def _canonical_payment_key(bank: str, raw_key: str) -> str:
    key = _normalize_keyword(raw_key).lower()
    if not key:
        return ""

    base_map = {
        "cuenta": "cuenta",
        "cuentaderetiro": "cuenta_retiro",
        "cuentacargo": "cuenta_retiro",
        "cuentabeneficiario": "cuenta_beneficiario",
        "numerodecuentabeneficiario": "cuenta_beneficiario",
        "numerodecuentadelbeneficiario": "cuenta_beneficiario",
        "numerodecuenta": "cuenta",
        "nocuenta": "cuenta",
        "nodecuenta": "cuenta",
        "cuentadedeposito": "cuenta",
        "cuentadeposito": "cuenta",
        "cuentadestino": "cuenta",
        "cuentadeabono": "cuenta",
        "cuentacuenta": "cuenta",
        "referencia": "referencia",
        "referencianumerica": "referencia",
        "referenciareferencia": "referencia",
        "importe": "importe",
        "importeimporte": "importe",
        "nombre": "nombre_beneficiario",
        "nombrebeneficiario": "nombre_beneficiario",
        "nombrenombre": "nombre_beneficiario",
        "beneficiario": "nombre_beneficiario",
        "nombrecorto": "nombre_beneficiario",
        "apellidopaterno": "apellido_paterno",
        "apellidomaterno": "apellido_materno",
        "apellidopaternoapellidomaternoestatus": "apellido_combo_estatus",
        "estatus": "estatus",
        "estado": "estado",
        "concepto": "concepto_pago",
        "conceptopago": "concepto_pago",
        "conceptodepago": "concepto_pago",
        "conceptoconcepto": "concepto_pago",
        "tipodeoperacion": "tipo_operacion",
        "bancodestino": "banco_destino",
        "bancoreceptor": "banco_destino",
        "formadedeposito": "forma_deposito",
        "clavederastreo": "clave_rastreo",
        "claverastreo": "clave_rastreo",
        "codigo": "codigo",
        "descripcion": "descripcion",
        "tipocuenta": "tipo_cuenta",
        "tipodecuenta": "tipo_cuenta",
        "noempleado": "numero_empleado",
        "numeroempleado": "numero_empleado",
        "numerodeempleado": "numero_empleado",
        "motivodepago": "motivo_pago",
        "motivopago": "motivo_pago",
        "divisa": "divisa",
        "titular": "titular",
        "titulardelacuenta": "titular",
        "contrato": "contrato",
        "numcontrato": "contrato",
        "numerocontrato": "contrato",
        "numerodecontrato": "contrato",
        "foliodefirma": "folio_firma",
        "foliounico": "folio_unico",
        "foliooperacion": "folio_operacion",
    }
    scotia_map = {
        "tipoderegistro": "tipo_registro",
        "tipodemovimiento": "tipo_movimiento",
        "tipodemovimientopago": "tipo_movimiento",
        "fechadeaplicacion": "fecha_aplicacion",
        "clavedelbeneficiario": "clave_beneficiario",
        "referencia": "referencia",
        "referenciadecarga": "referencia",
        "nocuentabeneficiario": "cuenta_beneficiario",
        "numerobancoreceptor": "banco_receptor",
        "nobancoreceptor": "banco_receptor",
        "diasdevigencia": "dias_vigencia",
        "nombredelbeneficiario": "nombre_beneficiario",
    }
    bbva_map = {
        "cuentaderetiroclabe": "cuenta_retiro",
        "cuentadedepsitoclabe": "cuenta",
        "cuentadedepositoclabe": "cuenta",
        "resultadodeltraspaso": "estatus",
        "foliodefirma": "folio_firma",
        "foliounico": "folio_unico",
        "fechadecreacion": "fecha_creacion",
        "fechadeaplicacion": "fecha_aplicacion",
        "horadecaptura": "hora_captura",
    }
    banorte_map = {
        "noempleado": "numero_empleado",
        "tipocuenta": "tipo_cuenta",
        "nodecuenta": "cuenta",
        "claverastreo": "clave_rastreo",
    }

    bank_upper = (bank or "").upper()
    if "SCOTIA" in bank_upper and key in scotia_map:
        return scotia_map[key]
    if "BBVA" in bank_upper and key in bbva_map:
        return bbva_map[key]
    if "BANORTE" in bank_upper and key in banorte_map:
        return banorte_map[key]

    mapped = base_map.get(key)
    if mapped:
        return mapped

    # Fallback: fuzzy match for unmapped keys from unsupported banks
    # (HSBC, INBURSA, BANAMEX, BANREGIO, etc.)
    _FUZZY_ALIASES: dict[str, str] = {
        "monto": "importe",
        "montototal": "importe",
        "montopago": "importe",
        "cantidad": "importe",
        "importepago": "importe",
        "importado": "importe",
        "saldo": "importe",
        "cuentacargo": "cuenta_retiro",
        "cuentaorigen": "cuenta_retiro",
        "cuentaabono": "cuenta",
        "cuentadestino": "cuenta",
        "rfcbeneficiario": "rfc_beneficiario",
        "rfc": "rfc_beneficiario",
        "curp": "curp_beneficiario",
        "curpbeneficiario": "curp_beneficiario",
        "fechaoperacion": "fecha_aplicacion",
        "fechapago": "fecha_aplicacion",
        "fechavalor": "fecha_aplicacion",
        "bancobeneficiario": "banco_destino",
        "bancoordenante": "banco_origen",
        "bancoemisor": "banco_origen",
        "folioconfirmacion": "folio_operacion",
        "foliodeconfirmacion": "folio_operacion",
        "clavedebeneficiario": "clave_beneficiario",
        "tipopago": "tipo_operacion",
        "mediopago": "forma_deposito",
        "formapago": "forma_deposito",
    }
    fuzzy = _FUZZY_ALIASES.get(key)
    if fuzzy:
        return fuzzy

    # Try to detect doubled canonical keys (e.g. "referenciareferencia" → "referencia")
    # This happens when header dedup fails to strip multi-page OCR repeats.
    if len(key) >= 10:
        for split_pos in range(4, len(key) // 2 + 1):
            prefix = key[:split_pos]
            remainder = key[split_pos:]
            if prefix == remainder:
                deduped = base_map.get(prefix)
                if deduped:
                    return deduped
                deduped_fuzzy = _FUZZY_ALIASES.get(prefix)
                if deduped_fuzzy:
                    return deduped_fuzzy

    # Pure numeric keys are never valid column names (phone numbers, codes)
    if key.isdigit():
        return ""

    # Drop unrecognized keys that look like OCR noise (contain digits mixed with letters)
    if re.search(r"\d", key) and re.search(r"[a-z]", key):
        return ""

    # Drop excessively long unrecognized keys (likely OCR concatenation noise)
    if len(key) > 40:
        return ""

    # Drop very short keys (≤ 3 chars) that are never valid column headers.
    # These are phantom columns from data values like "DA", "ES", "MXN".
    if len(key) <= 3:
        return ""

    key_upper = key.upper()

    # Reject single common Spanish words that are data values, NOT column
    # headers.  These leak through when a data row is mistakenly used as
    # the column-anchor reference (e.g. "ALTA", "ABONO", person surnames).
    _DATA_VALUE_WORDS = frozenset({
        "ALTA", "BAJA", "ABONO", "CARGO", "RETIRO", "DEPOSITO",
        "PAGO", "PAGOS", "TRANSFERENCIA", "TRASPASO",
        "PROCESADO", "APLICADO", "ACEPTADO", "TRANSMITIDO",
        "RECHAZADO", "DEVUELTO", "CANCELADO", "LIQUIDADO",
        "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
        "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
        "LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO",
    })
    if key_upper in _DATA_VALUE_WORDS:
        return ""

    # Reject leftover geographic / contact-info noise that survived normalization
    _NOISE_STEMS = ("GUADALAJARA", "MONTERREY", "RESTODEL", "CIUDADDEMEXICO", "LADASINCOSTO")
    if any(ns in key_upper for ns in _NOISE_STEMS):
        return ""

    # Reject keys that look like person names or surnames (single uppercase
    # words that don't match any known column vocabulary).  Valid column
    # keys always contain at least one of these substrings.
    _COLUMN_SUBSTRINGS = (
        "CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE", "APELLIDO",
        "ESTATUS", "ESTADO", "CONCEPTO", "TIPO", "BANCO", "CLAVE",
        "FOLIO", "NUMERO", "FECHA", "DIVISA", "TITULAR", "CONTRATO",
        "CODIGO", "DESCRIPCION", "MOTIVO", "DEPOSITO", "FORMA",
        "RASTREO", "OPERACION", "MOVIMIENTO", "EMPLEADO", "LOTE",
        "VIGENCIA", "RECEPTOR", "BENEFICIARIO", "REGISTRO",
    )
    if not any(sub in key_upper for sub in _COLUMN_SUBSTRINGS):
        return ""

    return key


_PAYMENT_PERSON_TOKEN_OCR_FIXES: dict[str, str] = {
    # Common OCR vowel drift in surnames from bank payment tables.
    "HERNENDEZ": "HERNANDEZ",
}


def _normalize_payment_person_value(value: str) -> str:
    normalized = _normalize_name(str(value or ""))
    if not normalized:
        return ""
    fixed_tokens: list[str] = []
    for token in normalized.split():
        if token in _PAYMENT_PERSON_TOKEN_OCR_FIXES:
            fixed_tokens.append(_PAYMENT_PERSON_TOKEN_OCR_FIXES[token])
        else:
            fixed_tokens.append(token)
    return " ".join(fixed_tokens).strip()


def _split_payment_apellidos_combo(value: str) -> tuple[str, str, str]:
    """Split 'APELLIDO PATERNO APELLIDO MATERNO ESTATUS' composite values."""
    combo = _normalize_name(str(value or ""))
    if not combo:
        return "", "", ""

    status = ""
    # Prefer longest statuses first (e.g. "EN PROCESO" before "PROCESADO").
    for st in sorted(_ALL_PAYMENT_STATUSES, key=len, reverse=True):
        if not st:
            continue
        pattern = rf"\b{re.escape(st)}\b"
        if re.search(pattern, combo):
            status = st
            combo = re.sub(pattern, " ", combo).strip()
            break

    parts = [part for part in combo.split() if part]
    if not parts:
        return "", "", status
    if len(parts) == 1:
        return parts[0], "", status
    if len(parts) == 2:
        return parts[0], parts[1], status
    # Conservative heuristic for compound surnames:
    # keep the last token as maternal and the rest as paternal.
    return " ".join(parts[:-1]).strip(), parts[-1], status


def _payment_to_canonical_rows(bank: str, rows: list[dict]) -> tuple[list[str], list[dict]]:
    if not rows:
        return [], []
    canonical_rows: list[dict] = []
    canonical_keys: list[str] = []
    for row in rows:
        try:
            canonical_row: dict[str, str] = {}
            source_canonical_keys: set[str] = set()
            for raw_key, raw_value in row.items():
                canon_key = _canonical_payment_key(bank, str(raw_key or ""))
                if not canon_key:
                    continue
                source_canonical_keys.add(canon_key)
                value = _normalize_text(str(raw_value or ""))
                if not value:
                    continue
                if canon_key in canonical_row:
                    # Avoid merging duplicate amounts (would produce garbage like "$1,234 $1,234")
                    if canon_key == "importe":
                        pass  # keep first value
                    else:
                        merged = f"{canonical_row[canon_key]} {value}".strip()
                        canonical_row[canon_key] = _normalize_text(merged)
                else:
                    canonical_row[canon_key] = value
                if canon_key not in canonical_keys:
                    canonical_keys.append(canon_key)

            combo = _normalize_text(str(canonical_row.get("apellido_combo_estatus") or ""))
            if combo:
                combo_ap_pat, combo_ap_mat, combo_status = _split_payment_apellidos_combo(combo)

                if combo_status and not canonical_row.get("estatus"):
                    canonical_row["estatus"] = _normalize_text(combo_status)
                    if "estatus" not in canonical_keys:
                        canonical_keys.append("estatus")

                # When combo has both surnames, prioritize it as the canonical
                # source (it is usually the most complete field in noisy PDFs).
                if combo_ap_pat and combo_ap_mat:
                    canonical_row["apellido_paterno"] = combo_ap_pat
                    canonical_row["apellido_materno"] = combo_ap_mat
                else:
                    if combo_ap_pat and not canonical_row.get("apellido_paterno"):
                        canonical_row["apellido_paterno"] = combo_ap_pat
                    if combo_ap_mat and not canonical_row.get("apellido_materno"):
                        canonical_row["apellido_materno"] = combo_ap_mat

                if canonical_row.get("apellido_paterno") and "apellido_paterno" not in canonical_keys:
                    canonical_keys.append("apellido_paterno")
                if canonical_row.get("apellido_materno") and "apellido_materno" not in canonical_keys:
                    canonical_keys.append("apellido_materno")

                # Drop composite key from output columns once split.
                canonical_row.pop("apellido_combo_estatus", None)
                if "apellido_combo_estatus" in canonical_keys:
                    canonical_keys.remove("apellido_combo_estatus")

            # Composite headers in some Santander/BBVA exports can produce a
            # synthetic "referenciaimporte" column. Keep it only if it adds
            # unique information not already captured by split columns.
            source_has_explicit_referencia = "referencia" in source_canonical_keys
            referencia_importe = _normalize_text(str(canonical_row.get("referenciaimporte") or ""))
            if referencia_importe:
                has_referencia = bool(_normalize_text(str(canonical_row.get("referencia") or "")))
                has_importe = bool(_normalize_text(str(canonical_row.get("importe") or "")))
                if has_referencia and has_importe:
                    canonical_row.pop("referenciaimporte", None)
                    if "referenciaimporte" in canonical_keys:
                        canonical_keys.remove("referenciaimporte")
                elif not has_referencia and not source_has_explicit_referencia:
                    ref_digits = _normalize_numeric_field(referencia_importe)
                    if len(ref_digits) >= 10:
                        canonical_row["referencia"] = ref_digits
                        if "referencia" not in canonical_keys:
                            canonical_keys.append("referencia")

            concepto = _normalize_text(str(canonical_row.get("concepto_pago") or "")).upper()
            if concepto and (concepto.startswith("PAGO DE N") or concepto.startswith("PAGO NOM")):
                canonical_row["concepto_pago"] = "PAGO DE NOMINA"

            full_name = _normalize_text(str(canonical_row.get("nombre_beneficiario") or ""))
            if full_name:
                # Only split into nombre/apellido parts if the document already
                # has separate apellido columns (from original headers or combo handler).
                # Otherwise, keep the full name intact — faithful to the PDF.
                has_separate_apellidos = bool(
                    canonical_row.get("apellido_paterno")
                    or canonical_row.get("apellido_materno")
                )
                if has_separate_apellidos:
                    nombre, apellido_paterno, apellido_materno = _split_payment_name_parts(full_name)
                    if nombre and not canonical_row.get("nombre"):
                        canonical_row["nombre"] = nombre
                        if "nombre" not in canonical_keys:
                            # Insert at the position of nombre_beneficiario to preserve PDF column order
                            if "nombre_beneficiario" in canonical_keys:
                                canonical_keys[canonical_keys.index("nombre_beneficiario")] = "nombre"
                            else:
                                canonical_keys.append("nombre")
                    if apellido_paterno and not canonical_row.get("apellido_paterno"):
                        canonical_row["apellido_paterno"] = apellido_paterno
                        if "apellido_paterno" not in canonical_keys:
                            canonical_keys.append("apellido_paterno")
                    if apellido_materno and not canonical_row.get("apellido_materno"):
                        canonical_row["apellido_materno"] = apellido_materno
                        if "apellido_materno" not in canonical_keys:
                            canonical_keys.append("apellido_materno")
                else:
                    # Document has only a single name column — keep the full name
                    canonical_row["nombre"] = full_name
                    if "nombre" not in canonical_keys:
                        # Insert at the position of nombre_beneficiario to preserve PDF column order
                        if "nombre_beneficiario" in canonical_keys:
                            canonical_keys[canonical_keys.index("nombre_beneficiario")] = "nombre"
                        else:
                            canonical_keys.append("nombre")

                # Remove the original nombre_beneficiario to avoid duplicate Nombre columns
                canonical_row.pop("nombre_beneficiario", None)
                # Only remove from canonical_keys if it wasn't already replaced in-place above
                if "nombre_beneficiario" in canonical_keys:
                    canonical_keys.remove("nombre_beneficiario")

            for person_key in ("nombre", "nombre_beneficiario", "apellido_paterno", "apellido_materno", "titular"):
                current_val = _normalize_text(str(canonical_row.get(person_key) or ""))
                if not current_val:
                    continue
                fixed_val = _normalize_payment_person_value(current_val)
                if fixed_val:
                    canonical_row[person_key] = fixed_val

            if canonical_row:
                canonical_rows.append(canonical_row)
        except Exception:
            logger.debug("_payment_to_canonical_rows: skipping row due to error", exc_info=True)
            continue

    # If the table has a dominant status (e.g. "Procesado"), propagate it to
    # rows where OCR missed only that specific cell.
    if canonical_rows and "estatus" in canonical_keys:
        status_pairs: list[tuple[str, str]] = []
        for row in canonical_rows:
            raw_status = _normalize_text(str(row.get("estatus") or ""))
            if not raw_status:
                continue
            status_pairs.append((_normalize_keyword(raw_status), raw_status))
        if status_pairs:
            from collections import Counter

            counts = Counter(norm for norm, _ in status_pairs if norm)
            if counts:
                dominant_norm, dominant_count = counts.most_common(1)[0]
                dominant_status = next(
                    (raw for norm, raw in status_pairs if norm == dominant_norm),
                    "",
                )
                if dominant_status and dominant_count >= 8 and (dominant_count / max(1, len(status_pairs))) >= 0.75:
                    for row in canonical_rows:
                        if not _normalize_text(str(row.get("estatus") or "")):
                            row["estatus"] = dominant_status
    return canonical_keys, canonical_rows


def _extract_payment_detail_payload(base_text_raw: str, table_payload: dict | None) -> dict | None:
    try:
        return _extract_payment_detail_payload_impl(base_text_raw, table_payload)
    except Exception:
        logger.debug("_extract_payment_detail_payload: error, returning None", exc_info=True)
        return None


def _extract_payment_detail_payload_impl(base_text_raw: str, table_payload: dict | None) -> dict | None:
    text = str(base_text_raw or "")
    if not text.strip():
        return None

    # Refuerzo: si hay table_payload y tiene filas, devolver dict con bank, table y metadata extraída
    if isinstance(table_payload, dict) and table_payload.get("rows"):
        bank_header = _payment_detect_bank(text)
        table_bank = table_payload.get("bank")
        bank = _normalize_text(str(bank_header or table_bank or "")).upper()
        # Extraer metadata aunque solo haya tabla
        metadata: dict[str, Any] = {}
        # Siempre poblar primero los campos genéricos por label_map
        label_map = {
            "fecha_archivo": ["FECHA", "FECHA DE ARCHIVO"],
            "hora_archivo": ["HORA"],
            "nombre_empresa": ["NOMBRE DE EMPRESA", "EMPRESA", "RAZON SOCIAL"],
            "nombre_archivo": ["NOMBRE DEL ARCHIVO"],
            "folio": ["FOLIO", "FOLIO DE INTERNET"],
            "nombre_contrato_scotia_linea": ["NOMBRE DE CONTRATO SCOTIA EN LINEA"],
            "numero_contrato_scotia_linea": ["NUMERO DE CONTRATO SCOTIA EN LINEA"],
            "numero_contrato_servicio": ["NUMERO DE CONTRATO DEL SERVICIO"],
            "numero_lote": ["LOTE", "LOTE ID", "NO DE LOTE", "NUMERO DE LOTE"],
            "numero_archivo_en_dia": ["NUMERO DE ARCHIVO EN EL DIA"],
            "usuario_sistema_nombre": ["NOMBRE DE USUARIO DEL SISTEMA Y NOMBRE", "USUARIO"],
            "fecha_hora_validacion_archivo": ["FECHA Y HORA DE VALIDACION DEL ARCHIVO"],
            "fecha_hora_registro": ["FECHA Y HORA DE REGISTRO"],
            "fecha_hora_proceso": ["FECHA Y HORA DE PROCESO", "FECHA DE TRANSMISION"],
            "cantidad_total_movimientos": ["CANTIDAD TOTAL DE MOVIMIENTOS"],
            "importe_total_movimientos": ["IMPORTE TOTAL DE MOVIMIENTOS"],
            "cantidad_movimientos_altas": ["CANTIDAD DE MOVIMIENTO ALTAS", "CANTIDAD DE MOVIMIENTOS ALTAS"],
            "importe_movimiento_altas": ["IMPORTE DE MOVIMIENTO ALTAS", "IMPORTE DE MOVIMIENTOS ALTAS"],
            "cantidad_movimientos_bajas": ["CANTIDAD DE MOVIMIENTO BAJAS", "CANTIDAD DE MOVIMIENTOS BAJAS"],
            "importe_movimientos_bajas": ["IMPORTE DE MOVIMIENTOS BAJAS"],
            "total_registros_leidos": ["TOTAL DE REGISTROS LEIDOS"],
        }
        for key, labels in label_map.items():
            value = _payment_pick_labeled_value(text, labels, max_len=180)
            if value:
                metadata[key] = value
        if bank == "SCOTIABANK":
            metadata.update(_extract_scotia_payment_metadata(text))
        elif bank == "BBVA":
            metadata.update(_extract_bbva_payment_metadata(text))
        elif bank == "SANTANDER":
            metadata.update(_extract_santander_payment_metadata(text))
        else:
            metadata.update(_extract_generic_bank_payment_metadata(text, bank))
        metadata = _sanitize_payment_metadata(metadata)

        # Poblar canonical_columns y canonical_rows igual que el pipeline general
        rows: list[list[str]] = []
        raw_rows = table_payload.get("rows")
        if isinstance(raw_rows, list):
            for raw_row in raw_rows:
                if not isinstance(raw_row, list):
                    continue
                rows.append([str(cell or "") for cell in raw_row])
        row_objects = _payment_rows_to_objects(rows) if rows else []
        canonical_columns, canonical_rows = _payment_to_canonical_rows(bank, row_objects)
        # Uppercase name columns in canonical rows
        _name_cols = {"nombre", "nombre_beneficiario", "apellido_paterno", "apellido_materno", "titular"}
        for crow in canonical_rows:
            for col in _name_cols:
                if crow.get(col):
                    crow[col] = crow[col].upper()
        display_columns = _build_display_columns_map(rows, bank)

        # Use canonical keys for rows in table_out (matches what callers expect)
        _header_keys = _payment_header_keys_from_cells(rows[0]) if rows else []
        table_rows_with_canonical_keys = (
            [dict(zip(_header_keys, row)) for row in rows[1:]] if len(rows) > 1 else []
        )

        summary_tables_early = _extract_scotia_summary_tables(text) if bank == "SCOTIABANK" else []

        table_out = {
            "columns": rows[0] if rows else [],
            "row_count": len(rows) - 1 if len(rows) > 1 else 0,
            "rows": table_rows_with_canonical_keys,
            "canonical_columns": canonical_columns,
            "canonical_row_count": len(canonical_rows),
            "canonical_rows": canonical_rows,
            "display_columns": display_columns,
            "summary_tables": summary_tables_early,
        }
        table_out["bank"] = bank

        quality_report_early: dict[str, Any] | None = None
        try:
            from app.pipelines.table_postprocess import compute_table_quality_report as _compute_qr
            quality_report_early = _compute_qr(canonical_columns, canonical_rows)
        except Exception:
            logger.debug("compute_table_quality_report failed for table_only payload", exc_info=True)

        result: dict[str, Any] = {
            "source": "table_only",
            "bank": bank,
            "metadata": metadata,
            "table": table_out,
        }
        if quality_report_early:
            result["quality_report"] = quality_report_early
        return result

    metadata: dict[str, Any] = {}
    bank = _normalize_text(str(_payment_detect_bank(text) or "")).upper()
    label_map = {
        "fecha_archivo": ["FECHA", "FECHA DE ARCHIVO"],
        "hora_archivo": ["HORA"],
        "nombre_empresa": ["NOMBRE DE EMPRESA", "EMPRESA", "RAZON SOCIAL"],
        "nombre_archivo": ["NOMBRE DEL ARCHIVO"],
        "folio": ["FOLIO", "FOLIO DE INTERNET"],
        "nombre_contrato_scotia_linea": ["NOMBRE DE CONTRATO SCOTIA EN LINEA"],
        "numero_contrato_scotia_linea": ["NUMERO DE CONTRATO SCOTIA EN LINEA"],
        "numero_contrato_servicio": ["NUMERO DE CONTRATO DEL SERVICIO"],
        "numero_lote": ["LOTE", "LOTE ID", "NO DE LOTE", "NUMERO DE LOTE"],
        "numero_archivo_en_dia": ["NUMERO DE ARCHIVO EN EL DIA"],
        "usuario_sistema_nombre": ["NOMBRE DE USUARIO DEL SISTEMA Y NOMBRE", "USUARIO"],
        "fecha_hora_validacion_archivo": ["FECHA Y HORA DE VALIDACION DEL ARCHIVO"],
        "fecha_hora_registro": ["FECHA Y HORA DE REGISTRO"],
        "fecha_hora_proceso": ["FECHA Y HORA DE PROCESO", "FECHA DE TRANSMISION"],
        "cantidad_total_movimientos": ["CANTIDAD TOTAL DE MOVIMIENTOS"],
        "importe_total_movimientos": ["IMPORTE TOTAL DE MOVIMIENTOS"],
        "cantidad_movimientos_altas": ["CANTIDAD DE MOVIMIENTO ALTAS", "CANTIDAD DE MOVIMIENTOS ALTAS"],
        "importe_movimiento_altas": ["IMPORTE DE MOVIMIENTO ALTAS", "IMPORTE DE MOVIMIENTOS ALTAS"],
        "cantidad_movimientos_bajas": ["CANTIDAD DE MOVIMIENTO BAJAS", "CANTIDAD DE MOVIMIENTOS BAJAS"],
        "importe_movimientos_bajas": ["IMPORTE DE MOVIMIENTOS BAJAS"],
        "total_registros_leidos": ["TOTAL DE REGISTROS LEIDOS"],
    }
    for key, labels in label_map.items():
        value = _payment_pick_labeled_value(text, labels, max_len=180)
        if value:
            metadata[key] = value

    if bank == "SCOTIABANK":
        metadata.update(_extract_scotia_payment_metadata(text))
    elif bank == "BBVA":
        metadata.update(_extract_bbva_payment_metadata(text))
    elif bank == "SANTANDER":
        metadata.update(_extract_santander_payment_metadata(text))
    else:
        # Generic metadata extraction for HSBC, BANAMEX, INBURSA, BANREGIO, etc.
        metadata.update(_extract_generic_bank_payment_metadata(text, bank))

    metadata = _sanitize_payment_metadata(metadata)

    rows: list[list[str]] = []
    if isinstance(table_payload, dict):
        raw_rows = table_payload.get("rows")
        if isinstance(raw_rows, list):
            for raw_row in raw_rows:
                if not isinstance(raw_row, list):
                    continue
                rows.append([str(cell or "") for cell in raw_row])
    row_objects = _payment_rows_to_objects(rows) if rows else []
    canonical_columns, canonical_rows = _payment_to_canonical_rows(bank, row_objects)
    summary_tables = _extract_scotia_summary_tables(text) if bank == "SCOTIABANK" else []

    # Convert secondary PDF tables (different header structures) into summary_tables
    secondary_pdf_tables: list[list[list[str]]] = []
    if isinstance(table_payload, dict):
        secondary_pdf_tables = table_payload.get("secondary_pdf_tables") or []
    for sec_idx, sec_table in enumerate(secondary_pdf_tables):
        try:
            if not sec_table or len(sec_table) < 2:
                continue
            sec_objects = _payment_rows_to_objects(sec_table)
            sec_cols, sec_rows = _payment_to_canonical_rows(bank, sec_objects)
            if not sec_rows:
                # Fall back to raw header/data if canonical conversion yields nothing
                sec_header = [str(c or "") for c in sec_table[0]]
                sec_data_rows = [
                    [str(c or "") for c in row]
                    for row in sec_table[1:]
                    if any(str(c or "").strip() for c in row)
                ]
                if sec_data_rows:
                    summary_tables.append({
                        "title": f"Tabla {sec_idx + 2}",
                        "columns": sec_header,
                        "rows": sec_data_rows,
                    })
            else:
                # Build display labels for summary columns
                sec_display = _build_display_columns_map(sec_table, bank)
                sec_labels = [
                    sec_display.get(col) or col.replace("_", " ").title()
                    for col in sec_cols
                ]
                sec_formatted_rows = [
                    [str(crow.get(col, "") or "") for col in sec_cols]
                    for crow in sec_rows
                ]
                if sec_formatted_rows:
                    summary_tables.append({
                        "title": f"Tabla {sec_idx + 2}",
                        "columns": sec_labels,
                        "rows": sec_formatted_rows,
                    })
        except Exception:
            logger.debug("Failed to convert secondary PDF table %d", sec_idx, exc_info=True)

    # Build display_columns: map canonical keys → original PDF header labels
    display_columns = _build_display_columns_map(rows, bank)

    # Reorder canonical_columns to match original PDF header order.
    # The in-place replacement in _payment_to_canonical_rows handles most cases,
    # but derived columns (from combo handlers) may still shift. This ensures
    # the final order mirrors the PDF.
    if rows and len(rows) >= 1:
        header_keys = _payment_header_keys_from_cells(rows[0])
        header_canonical_order: list[str] = []
        for hk in header_keys:
            ck = _canonical_payment_key(bank, hk)
            if not ck:
                continue
            # Handle nombre_beneficiario → nombre replacement
            if ck == "nombre_beneficiario":
                ck = "nombre"
            # Handle apellido_combo_estatus decomposition
            if ck == "apellido_combo_estatus":
                for derived in ("apellido_paterno", "apellido_materno", "estatus"):
                    if derived in canonical_columns and derived not in header_canonical_order:
                        header_canonical_order.append(derived)
                continue
            if ck not in header_canonical_order:
                header_canonical_order.append(ck)
        # Append any canonical_columns not derived from header (e.g., inferred columns)
        for cc in canonical_columns:
            if cc not in header_canonical_order:
                header_canonical_order.append(cc)
        # Filter to only include columns that exist in canonical_columns
        canonical_columns = [c for c in header_canonical_order if c in canonical_columns]

    # --- Pandas-based precision post-processing ---
    try:
        metadata = postprocess_metadata(metadata, bank=bank)
    except Exception:
        logger.warning("postprocess_metadata failed, using raw metadata", exc_info=True)

    try:
        canonical_columns, canonical_rows = postprocess_payment_table(
            canonical_columns, canonical_rows, bank=bank,
        )
    except Exception:
        logger.warning("postprocess_payment_table failed, using raw table data", exc_info=True)

    # --- BBVA "Grupo Pago Mismo Banco": split multi-payment into separate tables ---
    text_upper = _ascii_fold(text).upper() if text else ""
    is_bbva_grupo_pago = (
        bank == "BBVA"
        and len(canonical_rows) > 1
        and any(
            token in text_upper
            for token in ("PAGO MISMO BANCO", "OPERACION AUTORIZADA", "GRUPO PAGO")
        )
    )
    if is_bbva_grupo_pago:
        # Build display labels for summary_table columns
        summary_col_labels: list[str] = []
        for col in canonical_columns:
            label = display_columns.get(col) or col.replace("_", " ").title()
            summary_col_labels.append(label)

        for i, crow in enumerate(canonical_rows, 1):
            cell_values = [str(crow.get(col, "") or "") for col in canonical_columns]
            summary_tables.append({
                "title": f"Pago {i}",
                "columns": list(summary_col_labels),
                "rows": [cell_values],
            })
        # Clear main table so payments appear only as separate summary tables
        canonical_rows = []
        row_objects = []

    if not metadata and not row_objects and not canonical_rows and not summary_tables:
        return None

    # Quality report for diagnostics / online-learning
    quality_report: dict = {}
    try:
        quality_report = compute_table_quality_report(canonical_columns, canonical_rows)
    except Exception:
        pass

    result: dict[str, Any] = {
        "source": "table_and_text" if row_objects else "text_only",
        "bank": bank,
        "metadata": metadata,
        "table": {
            "columns": canonical_columns if canonical_columns else (
                rows[0] if len(rows) >= 1 else []
            ),
            "row_count": len(row_objects),
            "rows": row_objects,
            "canonical_columns": canonical_columns,
            "canonical_row_count": len(canonical_rows),
            "canonical_rows": canonical_rows,
            "display_columns": display_columns,
            "summary_tables": summary_tables,
        },
    }
    # Refuerzo: forzar el banco detectado en encabezado en el payload final
    bank_header = _payment_detect_bank(text)
    if bank_header:
        result["bank"] = bank_header
        if "table" in result and isinstance(result["table"], dict):
            result["table"]["bank"] = bank_header
        # Refuerzo: si hay mapped_fields, fuerza el banco también
        if "mapped_fields" in result and isinstance(result["mapped_fields"], dict):
            result["mapped_fields"]["banco"] = bank_header
    if quality_report:
        result["quality_report"] = quality_report
    # Refuerzo final: fuerza el banco detectado en encabezado en todos los niveles antes de devolver
    bank_header = _payment_detect_bank(text)
    if bank_header:
        result["bank"] = bank_header
        if "table" in result and isinstance(result["table"], dict):
            result["table"]["bank"] = bank_header
        if "mapped_fields" in result and isinstance(result["mapped_fields"], dict):
            result["mapped_fields"]["banco"] = bank_header
    return result


def _build_replica_layout_payload(ocr_boxes, raw_text: str) -> dict | None:
    boxes = _boxes_with_rect(ocr_boxes)
    if boxes:
        pages: dict[int, list[dict]] = {}
        for box in boxes:
            page = int(box.get("page", 1) or 1)
            pages.setdefault(page, []).append(box)

        payload_pages: list[dict] = []
        for page_num in sorted(pages.keys()):
            page_boxes = pages[page_num]
            lines = _line_groups(page_boxes, y_tol=10)
            if not lines:
                continue
            max_x = max(box["rect"][2] for box in page_boxes)
            max_y = max(box["rect"][3] for box in page_boxes)
            line_items: list[dict] = []
            for line in lines[:700]:
                text = _normalize_text(line.get("text", ""))
                if not text:
                    continue
                rects = [item["rect"] for item in line.get("boxes", []) if item.get("rect")]
                if not rects:
                    continue
                x1 = min(r[0] for r in rects)
                y1 = min(r[1] for r in rects)
                x2 = max(r[2] for r in rects)
                y2 = max(r[3] for r in rects)
                line_items.append(
                    {
                        "text": text,
                        "x": int(round(x1)),
                        "y": int(round(y1)),
                        "w": int(round(max(1, x2 - x1))),
                        "h": int(round(max(1, y2 - y1))),
                    }
                )
            if line_items:
                payload_pages.append(
                    {
                        "page": page_num,
                        "width": int(round(max_x)),
                        "height": int(round(max_y)),
                        "lines": line_items,
                    }
                )

        if payload_pages:
            return {"source": "layout_boxes", "pages": payload_pages}

    text_lines = [line.rstrip() for line in str(raw_text or "").replace("\r\n", "\n").split("\n")]
    text_lines = [line for line in text_lines if line.strip()]
    if len(text_lines) < 2:
        return None
    fallback_lines: list[dict] = []
    y = 24
    for line in text_lines[:700]:
        fallback_lines.append({"text": line, "x": 24, "y": y, "w": 1020, "h": 14})
        y += 16
    return {
        "source": "text_lines",
        "pages": [{"page": 1, "width": 1100, "height": max(600, y + 24), "lines": fallback_lines}],
    }


__all__ = _export_all()  # pyright: ignore[reportUnsupportedDunderAll]

