"""
geometric_detector.py — Motor de detección de tablas estilo Amazon Textract.

Capacidades implementadas (paridad con Textract):
  1. Clustering Y/X  — filas y zonas de columna por densidad geométrica.
  2. Grid indexado   — cada celda con (row_idx, col_idx, confidence).
  3. Celdas fusionadas (merged cells) — detecta cuando un box abarca varias columnas.
  4. Multi-página    — une tablas que continúan en la siguiente página.
  5. Confianza de tabla — score global además de confianza por celda.
  6. Formularios clave-valor — extrae pares LABEL: VALOR fuera de tablas.

Uso
---
    from app.pipelines.extract.geometric_detector import (
        detect_table_grid,
        detect_all_table_grids,
        extract_key_value_pairs,
    )

    grids = detect_all_table_grids(ocr_boxes)
    kvs   = extract_key_value_pairs(ocr_boxes)
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ─── Estructuras de datos ─────────────────────────────────────────────────────

@dataclass
class GridCell:
    row_idx:   int
    col_idx:   int
    text:      str
    bbox:      tuple[float, float, float, float]   # x1, y1, x2, y2
    confidence: float = 1.0                        # 0..1
    col_span:  int   = 1                           # >1 = celda fusionada
    page:      int   = 0                           # página de origen (0-indexed)


@dataclass
class GridTable:
    """
    Resultado del detector geométrico: grilla (row, col) con textos y confianza.
    Compatible con Amazon Textract TABLE/CELL blocks.
    """
    cells:         list[GridCell]              = field(default_factory=list)
    n_rows:        int                         = 0
    n_cols:        int                         = 0
    column_zones:  list[tuple[float, float]]   = field(default_factory=list)
    column_labels: list[str]                   = field(default_factory=list)
    page_count:    int                         = 1   # número de páginas que abarca
    has_merged:    bool                        = False

    # ── Acceso conveniente ────────────────────────────────────────────────────

    def get_cell(self, row: int, col: int) -> GridCell | None:
        for c in self.cells:
            if c.row_idx == row and c.col_idx == col:
                return c
        return None

    def row_texts(self, row: int) -> list[str]:
        row_cells = sorted(
            [c for c in self.cells if c.row_idx == row],
            key=lambda c: c.col_idx,
        )
        result = [""] * self.n_cols
        for c in row_cells:
            if 0 <= c.col_idx < self.n_cols:
                result[c.col_idx] = c.text
                # Propagar texto en celdas fusionadas
                if c.col_span > 1:
                    for extra in range(1, c.col_span):
                        idx = c.col_idx + extra
                        if idx < self.n_cols and not result[idx]:
                            result[idx] = c.text
        return result

    def to_raw_table(self) -> list[list[str]]:
        """Formato list[list[str]] compatible con el pipeline existente."""
        return [self.row_texts(r) for r in range(self.n_rows)]

    def to_row_dicts(self) -> list[dict[str, str]]:
        labels = self.column_labels or [f"COL_{i+1}" for i in range(self.n_cols)]
        result = []
        for r in range(self.n_rows):
            texts = self.row_texts(r)
            result.append({labels[i]: texts[i] for i in range(len(labels))})
        return result

    @property
    def quality_score(self) -> float:
        """0-100: porcentaje de celdas no vacías en filas de datos."""
        if self.n_rows < 2 or self.n_cols == 0:
            return 0.0
        data_cells = [c for c in self.cells if c.row_idx > 0]
        if not data_cells:
            return 0.0
        filled = sum(1 for c in data_cells if c.text.strip())
        total  = (self.n_rows - 1) * self.n_cols
        return round(filled / total * 100, 1)

    @property
    def table_confidence(self) -> float:
        """Confianza global de la tabla: promedio de confianza de todas las celdas."""
        if not self.cells:
            return 0.0
        return round(sum(c.confidence for c in self.cells) / len(self.cells), 3)


# ─── Formulario clave-valor ───────────────────────────────────────────────────

@dataclass
class KeyValuePair:
    """Par clave-valor detectado fuera de una tabla (estilo Textract AnalyzeDocument)."""
    key:             str
    value:           str
    key_bbox:        tuple[float, float, float, float]
    value_bbox:      tuple[float, float, float, float] | None
    confidence:      float = 1.0
    page:            int   = 0


# ─── Utilidades internas ──────────────────────────────────────────────────────

def _safe_rect(box: dict) -> tuple[float, float, float, float] | None:
    rect = box.get("rect")
    if not isinstance(rect, (list, tuple)) or len(rect) < 4:
        return None
    try:
        x1, y1, x2, y2 = float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])
        if x2 < x1: x1, x2 = x2, x1
        if y2 < y1: y1, y2 = y2, y1
        return x1, y1, x2, y2
    except (TypeError, ValueError):
        return None


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _norm_text(text: str) -> str:
    t = unicodedata.normalize("NFD", text.upper())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", t).strip()


def _prepare_items(ocr_boxes: list[dict]) -> list[dict]:
    """Convierte OCR boxes crudos en items normalizados con geometría calculada."""
    items: list[dict] = []
    for box in ocr_boxes:
        text = str(box.get("text", "") or "").strip()
        if not text:
            continue
        rect = _safe_rect(box)
        if rect is None:
            continue
        x1, y1, x2, y2 = rect
        page = int(box.get("page", 0) or 0)
        items.append({
            "text":     text,
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "x_center": (x1 + x2) / 2,
            "y_center": (y1 + y2) / 2,
            "width":    max(1.0, x2 - x1),
            "height":   max(1.0, y2 - y1),
            "page":     page,
        })
    return items


# ─── Paso 1: clustering de filas por Y ───────────────────────────────────────

def _cluster_rows(
    items: list[dict],
    y_tol: float | None = None,
) -> list[list[dict]]:
    """
    Agrupa items en filas por proximidad en Y.
    Respeta saltos de página: items de páginas distintas nunca se fusionan en la misma fila.
    y_tol adaptativo: 60% de la altura mediana, en [5, 60].
    """
    if not items:
        return []

    heights = [it["height"] for it in items if it["height"] > 0]
    if y_tol is None:
        median_h = _median(heights) if heights else 14.0
        y_tol = max(5.0, min(median_h * 0.6, 60.0))

    # Ordenar por (página, y_center, x1)
    sorted_items = sorted(items, key=lambda it: (it["page"], it["y_center"], it["x1"]))

    rows: list[list[dict]] = []
    current: list[dict] = [sorted_items[0]]
    current_y    = sorted_items[0]["y_center"]
    current_page = sorted_items[0]["page"]

    for it in sorted_items[1:]:
        same_page = it["page"] == current_page
        close_y   = abs(it["y_center"] - current_y) <= y_tol

        if same_page and close_y:
            current.append(it)
            current_y = sum(i["y_center"] for i in current) / len(current)
        else:
            rows.append(sorted(current, key=lambda i: i["x1"]))
            current      = [it]
            current_y    = it["y_center"]
            current_page = it["page"]

    if current:
        rows.append(sorted(current, key=lambda i: i["x1"]))

    return rows


# ─── Paso 2: detección de zonas de columna por proyección X ──────────────────

def _detect_column_zones(
    all_items: list[dict],
    min_cols: int = 2,
    max_cols: int = 30,
) -> list[tuple[float, float]]:
    """
    Proyecta centros X en histograma 1-D y detecta zonas de columna como picos.
    Umbral relativo al pico máximo (sin floor fijo) para no filtrar columnas escasas.
    """
    if not all_items:
        return []

    x_centers  = [it["x_center"] for it in all_items]
    x_min, x_max = min(x_centers), max(x_centers)
    page_width = x_max - x_min
    if page_width < 10:
        return [(x_min - 5, x_max + 5)]

    bin_width = max(8.0, page_width / 40)
    n_bins    = max(1, int(math.ceil(page_width / bin_width)))
    bins: list[float] = [0.0] * n_bins

    for xc in x_centers:
        bi = min(int((xc - x_min) / bin_width), n_bins - 1)
        bins[bi] += 1.0

    # Suavizado ±1
    smoothed: list[float] = []
    for i in range(n_bins):
        nb = bins[max(0, i-1):i+2]
        smoothed.append(sum(nb) / len(nb))

    peak_max  = max(smoothed)
    threshold = max(0.25, peak_max * 0.15)

    peaks: list[int] = []
    for i in range(n_bins):
        left  = smoothed[i-1] if i > 0 else 0
        right = smoothed[i+1] if i < n_bins - 1 else 0
        if smoothed[i] >= threshold and smoothed[i] >= left and smoothed[i] >= right:
            peaks.append(i)

    if not peaks:
        return [(x_min - 5, x_max + 5)]

    # Fusionar picos adyacentes (≤ 2 bins)
    merged: list[int] = [peaks[0]]
    for p in peaks[1:]:
        if p - merged[-1] <= 2:
            merged[-1] = p if smoothed[p] >= smoothed[merged[-1]] else merged[-1]
        else:
            merged.append(p)

    merged = merged[:max_cols]
    if len(merged) < min_cols:
        return []

    margin = bin_width / 2
    zones: list[tuple[float, float]] = []
    for pi in merged:
        cx = x_min + pi * bin_width + bin_width / 2
        zones.append((cx - margin, cx + margin))

    logger.debug("[GEO] columnas=%d bin_width=%.1f page_width=%.1f", len(zones), bin_width, page_width)
    return zones


# ─── Paso 3: asignación a grid con detección de merged cells ─────────────────

def _assign_to_grid(
    rows:            list[list[dict]],
    zones:           list[tuple[float, float]],
    max_dist_factor: float = 1.5,
) -> list[GridCell]:
    """
    Asigna cada item a su (row_idx, col_idx).

    Detección de celdas fusionadas (merged cells):
      Si el ancho de un box supera 1.5× el ancho de la zona más cercana
      Y su extensión cubre ≥ 2 zonas contiguas → se marca como merged.
      El texto se coloca en la columna izquierda con col_span > 1.
    """
    if not zones:
        return []

    zone_centers = [(z[0] + z[1]) / 2 for z in zones]
    zone_widths  = [max(z[1] - z[0], 10.0) for z in zones]
    n_cols       = len(zones)
    cells: list[GridCell] = []

    for row_idx, row_items in enumerate(rows):
        col_buckets: dict[int, list[dict]] = {}

        for it in row_items:
            xc     = it["x_center"]
            bwidth = it["width"]
            page   = it["page"]

            # ── Detección de merged cell ──────────────────────────────────────
            # Un box es "merged" si su ancho cubre varias zonas de columna.
            covered = [
                ci for ci, (z1, z2) in enumerate(zones)
                if it["x1"] < z2 and it["x2"] > z1   # overlap
            ]

            if len(covered) >= 2:
                # Celda fusionada: asignar a la primera columna cubierta
                first_col = covered[0]
                col_span  = len(covered)
                col_buckets.setdefault(("merged", first_col, col_span), []).append(it)
                continue

            # ── Celda normal ──────────────────────────────────────────────────
            best_col  = min(range(n_cols), key=lambda ci: abs(xc - zone_centers[ci]))
            dist      = abs(xc - zone_centers[best_col])
            max_allow = zone_widths[best_col] * max_dist_factor

            if dist > max_allow:
                logger.debug("[GEO] box descartado dist=%.1f max=%.1f text=%s",
                             dist, max_allow, it["text"][:30])
                continue

            col_buckets.setdefault(best_col, []).append(it)

        # ── Construir GridCell por cada bucket ────────────────────────────────
        for key, bucket in col_buckets.items():
            bucket.sort(key=lambda i: i["x1"])
            text = " ".join(i["text"] for i in bucket).strip()
            if not text:
                continue

            x1 = min(i["x1"] for i in bucket)
            y1 = min(i["y1"] for i in bucket)
            x2 = max(i["x2"] for i in bucket)
            y2 = max(i["y2"] for i in bucket)
            pg = bucket[0]["page"]

            if isinstance(key, tuple) and key[0] == "merged":
                _, col_idx, col_span = key
                cells.append(GridCell(
                    row_idx=row_idx, col_idx=col_idx,
                    text=text, bbox=(x1, y1, x2, y2),
                    confidence=0.9, col_span=col_span, page=pg,
                ))
            else:
                col_idx = key
                total_conf = sum(
                    max(0.0, 1.0 - abs(i["x_center"] - zone_centers[col_idx])
                        / (zone_widths[col_idx] * max_dist_factor))
                    for i in bucket
                )
                conf = round(total_conf / len(bucket), 3)
                cells.append(GridCell(
                    row_idx=row_idx, col_idx=col_idx,
                    text=text, bbox=(x1, y1, x2, y2),
                    confidence=conf, col_span=1, page=pg,
                ))

    return cells


# ─── Multi-página: unir tablas que continúan en la siguiente página ───────────

def _columns_compatible(labels_a: list[str], labels_b: list[str]) -> bool:
    """
    True si dos listas de etiquetas de columna son suficientemente similares
    para considerar que la tabla continúa (misma estructura, diferente página).
    Usa Jaccard de tokens normalizados.
    """
    if not labels_a or not labels_b:
        return False
    if abs(len(labels_a) - len(labels_b)) > 2:
        return False

    set_a = {_norm_text(l) for l in labels_a if not l.startswith("COL_")}
    set_b = {_norm_text(l) for l in labels_b if not l.startswith("COL_")}

    if not set_a or not set_b:
        # Si ambas son genéricas (COL_N) comparar por cantidad
        return len(labels_a) == len(labels_b)

    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return (inter / union) >= 0.6 if union else False


def _merge_multipage_tables(grids: list[GridTable]) -> list[GridTable]:
    """
    Fusiona tablas consecutivas que comparten estructura de columnas.
    Comportamiento: si la página N termina con encabezado que coincide
    con el encabezado de página N+1, elimina el encabezado duplicado
    y une las filas en una sola tabla.

    Este proceso se repite hasta que no haya más fusiones posibles.
    """
    if len(grids) <= 1:
        return grids

    merged = True
    result = list(grids)

    while merged:
        merged = False
        new_result: list[GridTable] = []
        i = 0
        while i < len(result):
            if i + 1 >= len(result):
                new_result.append(result[i])
                i += 1
                continue

            a, b = result[i], result[i + 1]

            # Sólo fusionar si están en páginas distintas consecutivas
            pages_a = {c.page for c in a.cells}
            pages_b = {c.page for c in b.cells}
            if not pages_a or not pages_b:
                new_result.append(a)
                i += 1
                continue

            max_page_a = max(pages_a)
            min_page_b = min(pages_b)
            if min_page_b != max_page_a + 1:
                new_result.append(a)
                i += 1
                continue

            if not _columns_compatible(a.column_labels, b.column_labels):
                new_result.append(a)
                i += 1
                continue

            # ── Fusionar: b puede tener una fila de encabezado repetida ──────
            logger.info(
                "[GEO] fusionando tabla multi-página: pág %s + pág %s | cols=%s",
                sorted(pages_a), sorted(pages_b), a.column_labels,
            )

            b_header  = b.column_labels
            b_row0    = b.row_texts(0)
            skip_row0 = _columns_compatible(b_header, b_row0)  # encabezado repetido

            offset    = a.n_rows
            new_cells = list(a.cells)

            for cell in b.cells:
                if skip_row0 and cell.row_idx == 0:
                    continue
                adj_row = cell.row_idx - (1 if skip_row0 else 0) + offset
                new_cells.append(GridCell(
                    row_idx=adj_row, col_idx=cell.col_idx,
                    text=cell.text, bbox=cell.bbox,
                    confidence=cell.confidence, col_span=cell.col_span,
                    page=cell.page,
                ))

            n_rows_new = max(c.row_idx for c in new_cells) + 1
            fused = GridTable(
                cells=new_cells,
                n_rows=n_rows_new,
                n_cols=max(a.n_cols, b.n_cols),
                column_zones=a.column_zones,
                column_labels=a.column_labels,
                page_count=a.page_count + b.page_count,
                has_merged=a.has_merged or b.has_merged,
            )
            new_result.append(fused)
            merged = True
            i += 2  # saltar b, ya fue fusionada

        result = new_result

    return result


# ─── Formularios clave-valor (Textract AnalyzeDocument) ──────────────────────

_KV_SEPARATORS = re.compile(r"[:：\|]\s*")
_LABEL_MIN_LEN  = 2
_LABEL_MAX_LEN  = 60


def extract_key_value_pairs(
    ocr_boxes:     list[dict],
    min_gap_ratio: float = 0.15,
) -> list[KeyValuePair]:
    """
    Extrae pares clave-valor de OCR boxes (Textract AnalyzeDocument).

    Estrategia doble:
      A. Inline  — "RFC: XAXX010101000" en un solo box → split por separador
      B. Lateral — dos boxes en la misma fila, el de la izquierda es label,
                   el de la derecha es valor, con gap > min_gap_ratio × ancho_página

    Parámetros
    ----------
    ocr_boxes     : lista de OCR boxes con 'text' y 'rect'
    min_gap_ratio : gap mínimo entre label y valor como fracción del ancho de página

    Retorna lista de KeyValuePair ordenada por posición (página, Y, X).
    """
    items = _prepare_items(ocr_boxes)
    if not items:
        return []

    pairs: list[KeyValuePair] = []
    seen_keys: set[str] = set()

    # ── Estrategia A: Inline (separador en el mismo texto) ────────────────────
    for it in items:
        text = it["text"]
        parts = _KV_SEPARATORS.split(text, maxsplit=1)
        if len(parts) != 2:
            continue
        key_raw, val_raw = parts[0].strip(), parts[1].strip()
        if not key_raw or not val_raw:
            continue
        if len(key_raw) < _LABEL_MIN_LEN or len(key_raw) > _LABEL_MAX_LEN:
            continue
        norm_key = _norm_text(key_raw)
        if norm_key in seen_keys:
            continue
        seen_keys.add(norm_key)
        pairs.append(KeyValuePair(
            key=key_raw, value=val_raw,
            key_bbox=(it["x1"], it["y1"], it["x2"], it["y2"]),
            value_bbox=None,
            confidence=0.85, page=it["page"],
        ))

    # ── Estrategia B: Lateral (label izquierda, valor derecha en misma fila) ──
    all_x1 = [it["x1"] for it in items]
    all_x2 = [it["x2"] for it in items]
    if all_x1 and all_x2:
        page_width = max(all_x2) - min(all_x1)
        min_gap    = page_width * min_gap_ratio
    else:
        min_gap = 50.0

    # Agrupar items por fila (misma página, Y cercano)
    rows = _cluster_rows(items)

    for row_items in rows:
        if len(row_items) < 2:
            continue
        # Ordenar por X
        row_sorted = sorted(row_items, key=lambda i: i["x1"])

        for j in range(len(row_sorted) - 1):
            label_it = row_sorted[j]
            value_it = row_sorted[j + 1]

            gap = value_it["x1"] - label_it["x2"]
            if gap < min_gap:
                continue

            key_raw = label_it["text"].rstrip(": ")
            val_raw = value_it["text"]
            if not key_raw or not val_raw:
                continue
            if len(key_raw) < _LABEL_MIN_LEN or len(key_raw) > _LABEL_MAX_LEN:
                continue
            norm_key = _norm_text(key_raw)
            if norm_key in seen_keys:
                continue
            seen_keys.add(norm_key)

            # Confianza basada en longitud del label y magnitud del gap
            conf = min(0.95, 0.6 + gap / (page_width + 1) * 0.4) if page_width else 0.7
            pairs.append(KeyValuePair(
                key=key_raw, value=val_raw,
                key_bbox=(label_it["x1"], label_it["y1"],
                          label_it["x2"], label_it["y2"]),
                value_bbox=(value_it["x1"], value_it["y1"],
                            value_it["x2"], value_it["y2"]),
                confidence=round(conf, 3),
                page=label_it["page"],
            ))

    pairs.sort(key=lambda p: (p.page, p.key_bbox[1], p.key_bbox[0]))
    logger.info("[GEO] extract_key_value_pairs: %d pares detectados", len(pairs))
    return pairs


# ─── Constructor de GridTable desde rows+zones ────────────────────────────────

def _build_grid(
    block_rows: list[list[dict]],
    zones:      list[tuple[float, float]],
    min_data_rows: int = 1,
) -> GridTable | None:
    cells = _assign_to_grid(block_rows, zones)
    if not cells:
        return None

    data_cells = [c for c in cells if c.row_idx > 0]
    if len(data_cells) < min_data_rows * max(1, len(zones) // 2):
        return None

    n_rows   = max(c.row_idx for c in cells) + 1
    n_cols   = len(zones)
    has_merged = any(c.col_span > 1 for c in cells)

    col_labels = [f"COL_{i+1}" for i in range(n_cols)]
    for hc in [c for c in cells if c.row_idx == 0]:
        if 0 <= hc.col_idx < n_cols:
            col_labels[hc.col_idx] = hc.text.upper().strip()

    pages = {c.page for c in cells}

    return GridTable(
        cells=cells,
        n_rows=n_rows,
        n_cols=n_cols,
        column_zones=zones,
        column_labels=col_labels,
        page_count=len(pages),
        has_merged=has_merged,
    )


# ─── Punto de entrada: tabla única ────────────────────────────────────────────

def detect_table_grid(
    ocr_boxes:     list[dict],
    min_cols:      int   = 2,
    min_data_rows: int   = 1,
    max_cols:      int   = 30,
    y_tol:         float | None = None,
) -> GridTable | None:
    """
    Detecta UNA tabla en el conjunto de OCR boxes.
    Para PDFs con múltiples tablas usa detect_all_table_grids.
    """
    if not ocr_boxes:
        return None

    items = _prepare_items(ocr_boxes)
    if not items:
        return None

    rows = _cluster_rows(items, y_tol=y_tol)
    if len(rows) < min_data_rows + 1:
        return None

    zones = _detect_column_zones(items, min_cols=min_cols, max_cols=max_cols)
    if len(zones) < min_cols:
        return None

    grid = _build_grid(rows, zones, min_data_rows=min_data_rows)
    if grid is None:
        return None

    logger.info(
        "[GEO] GridTable: %d filas × %d cols | quality=%.1f | confidence=%.3f"
        " | merged=%s | pages=%d | labels=%s",
        grid.n_rows, grid.n_cols, grid.quality_score, grid.table_confidence,
        grid.has_merged, grid.page_count, grid.column_labels,
    )
    return grid


# ─── Punto de entrada: múltiples tablas + multi-página ───────────────────────

def detect_all_table_grids(
    ocr_boxes:         list[dict],
    min_cols:          int   = 2,
    min_data_rows:     int   = 1,
    max_cols:          int   = 30,
    block_gap_factor:  float = 2.5,
    merge_multipage:   bool  = True,
) -> list[GridTable]:
    """
    Detecta MÚLTIPLES tablas separando bloques verticales y,
    opcionalmente, fusiona tablas multi-página compatibles.

    Parámetros
    ----------
    ocr_boxes        : lista de OCR boxes (pueden tener campo 'page')
    min_cols         : columnas mínimas para tabla válida
    min_data_rows    : filas de datos mínimas
    max_cols         : columnas máximas a detectar
    block_gap_factor : salto vertical > factor × altura_mediana → nuevo bloque
    merge_multipage  : True = fusionar tablas compatibles de páginas consecutivas
    """
    if not ocr_boxes:
        return []

    items = _prepare_items(ocr_boxes)
    if not items:
        return []

    heights  = [it["height"] for it in items]
    median_h = _median(heights) if heights else 14.0
    y_tol    = max(5.0, min(median_h * 0.6, 60.0))
    block_gap = median_h * block_gap_factor

    rows = _cluster_rows(items, y_tol=y_tol)
    if not rows:
        return []

    # ── Separar en bloques por salto vertical O cambio de página ─────────────
    blocks: list[list[list[dict]]] = []
    current_block: list[list[dict]] = [rows[0]]
    prev_y    = sum(it["y_center"] for it in rows[0]) / len(rows[0])
    prev_page = rows[0][0]["page"]

    for row in rows[1:]:
        row_y    = sum(it["y_center"] for it in row) / len(row)
        row_page = row[0]["page"]

        page_break = row_page != prev_page
        gap_break  = (row_y - prev_y) > block_gap and not page_break

        if page_break or gap_break:
            blocks.append(current_block)
            current_block = [row]
        else:
            current_block.append(row)

        prev_y    = row_y
        prev_page = row_page

    if current_block:
        blocks.append(current_block)

    # ── Construir GridTable por bloque ────────────────────────────────────────
    grids: list[GridTable] = []
    for block_rows in blocks:
        block_items = [it for row in block_rows for it in row]
        if len(block_rows) < min_data_rows + 1:
            continue

        zones = _detect_column_zones(block_items, min_cols=min_cols, max_cols=max_cols)
        if len(zones) < min_cols:
            continue

        grid = _build_grid(block_rows, zones, min_data_rows=min_data_rows)
        if grid is None:
            continue

        if grid.quality_score >= 10.0:
            grids.append(grid)

    # ── Fusión multi-página ───────────────────────────────────────────────────
    if merge_multipage and len(grids) > 1:
        grids = _merge_multipage_tables(grids)

    logger.info(
        "[GEO] detect_all_table_grids: %d tabla(s) | merged_cells=%s | multipage=%s",
        len(grids),
        any(g.has_merged for g in grids),
        any(g.page_count > 1 for g in grids),
    )
    return grids
