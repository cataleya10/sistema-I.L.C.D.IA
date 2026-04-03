"""
geometric_detector.py — Motor de detección de tablas estilo Amazon Textract.

En lugar de buscar "gaps grandes en X" (heurística frágil), este módulo:

  1. Agrupa OCR boxes en FILAS por proximidad en Y (clustering adaptativo).
  2. Proyecta los centros X de todos los boxes en un histograma 1-D y detecta
     ZONAS DE COLUMNA como picos de densidad (igual que Textract internamente).
  3. Asigna cada box a la celda (row_idx, col_idx) con score de confianza.
  4. Devuelve un GridTable con índices explícitos — sin depender de píxeles fijos.

Uso
---
    from app.pipelines.extract.geometric_detector import detect_table_grid

    grid = detect_table_grid(ocr_boxes)
    if grid:
        cols  = grid.column_labels   # lista de str (nombre de columna o "COL_N")
        rows  = grid.to_row_dicts()  # list[dict[col_label, text]]
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ─── Estructuras de datos ─────────────────────────────────────────────────────

@dataclass
class GridCell:
    row_idx: int
    col_idx: int
    text: str
    bbox: tuple[float, float, float, float]   # x1, y1, x2, y2
    confidence: float = 1.0                   # 0..1


@dataclass
class GridTable:
    """Resultado del detector geométrico: grilla (row, col) con textos y confianza."""
    cells: list[GridCell] = field(default_factory=list)
    n_rows: int = 0
    n_cols: int = 0
    column_zones: list[tuple[float, float]] = field(default_factory=list)  # (x1, x2) por col
    column_labels: list[str] = field(default_factory=list)

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
        total = (self.n_rows - 1) * self.n_cols
        return round(filled / total * 100, 1)


# ─── Utilidades internas ──────────────────────────────────────────────────────

def _safe_rect(box: dict) -> tuple[float, float, float, float] | None:
    rect = box.get("rect")
    if not isinstance(rect, (list, tuple)) or len(rect) < 4:
        return None
    try:
        x1, y1, x2, y2 = float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1
        return x1, y1, x2, y2
    except (TypeError, ValueError):
        return None


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


# ─── Paso 1: clustering de filas por Y ───────────────────────────────────────

def _cluster_rows(
    items: list[dict],
    y_tol: float | None = None,
) -> list[list[dict]]:
    """
    Agrupa items (cada uno con campo 'y_center') en filas por proximidad en Y.
    y_tol adaptativo: 60% de la altura mediana, en [5, 60].
    """
    if not items:
        return []

    heights = [it["height"] for it in items if it["height"] > 0]
    if y_tol is None:
        median_h = _median(heights) if heights else 14.0
        y_tol = max(5.0, min(median_h * 0.6, 60.0))

    sorted_items = sorted(items, key=lambda it: (it["y_center"], it["x1"]))

    rows: list[list[dict]] = []
    current: list[dict] = [sorted_items[0]]
    current_y = sorted_items[0]["y_center"]

    for it in sorted_items[1:]:
        if abs(it["y_center"] - current_y) <= y_tol:
            current.append(it)
            # Media acumulada para acomodar variación gradual dentro de la fila
            current_y = sum(i["y_center"] for i in current) / len(current)
        else:
            rows.append(sorted(current, key=lambda i: i["x1"]))
            current = [it]
            current_y = it["y_center"]

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
    Proyecta centros X en un histograma y encuentra picos de densidad.

    Algoritmo:
      - bin_width = 5% del ancho total de la página
      - suavizado gaussiano ligero (ventana ±2 bins)
      - picos = máximos locales con densidad > umbral
      - fusiona picos adyacentes < 1 bin

    Devuelve lista de (x_start, x_end) por zona de columna, ordenadas por X.
    """
    if not all_items:
        return []

    x_centers = [it["x_center"] for it in all_items]
    x_min = min(x_centers)
    x_max = max(x_centers)
    page_width = x_max - x_min
    if page_width < 10:
        return [(x_min - 5, x_max + 5)]

    # Ancho de bin: adaptar según número de items
    bin_width = max(8.0, page_width / 40)
    n_bins = max(1, int(math.ceil(page_width / bin_width)))
    bins: list[float] = [0.0] * n_bins

    for xc in x_centers:
        bi = min(int((xc - x_min) / bin_width), n_bins - 1)
        bins[bi] += 1.0

    # Suavizado: media de ventana ±1
    smoothed: list[float] = []
    for i in range(n_bins):
        neighbours = bins[max(0, i-1):i+2]
        smoothed.append(sum(neighbours) / len(neighbours))

    # Umbral: relativo al pico máximo, sin floor fijo para no filtrar columnas poco densas.
    # Con pocas filas (3-5) los bins tienen conteos 1-3 y después de suavizar quedan en
    # 0.3-1.0; un floor de 1.0 eliminaría columnas válidas.
    peak_max = max(smoothed)
    threshold = max(0.25, peak_max * 0.15)

    # Encontrar picos locales
    peaks: list[int] = []
    for i in range(n_bins):
        left  = smoothed[i-1] if i > 0 else 0
        right = smoothed[i+1] if i < n_bins - 1 else 0
        if smoothed[i] >= threshold and smoothed[i] >= left and smoothed[i] >= right:
            peaks.append(i)

    if not peaks:
        return [(x_min - 5, x_max + 5)]

    # Fusionar picos adyacentes (diferencia <= 1 bin)
    merged: list[int] = [peaks[0]]
    for p in peaks[1:]:
        if p - merged[-1] <= 2:
            # Tomar el de mayor densidad
            merged[-1] = p if smoothed[p] >= smoothed[merged[-1]] else merged[-1]
        else:
            merged.append(p)

    merged = merged[:max_cols]

    if len(merged) < min_cols:
        return []

    # Convertir picos a zonas (x1, x2) con margen = bin_width / 2
    margin = bin_width / 2
    zones: list[tuple[float, float]] = []
    for pi in merged:
        cx = x_min + pi * bin_width + bin_width / 2
        zones.append((cx - margin, cx + margin))

    logger.debug(
        "[GEO] columnas detectadas=%d bin_width=%.1f page_width=%.1f",
        len(zones), bin_width, page_width,
    )
    return zones


# ─── Paso 3: asignación de items a celdas (row, col) ─────────────────────────

def _assign_to_grid(
    rows: list[list[dict]],
    zones: list[tuple[float, float]],
    max_dist_factor: float = 1.5,
) -> list[GridCell]:
    """
    Asigna cada item a su (row_idx, col_idx) basándose en el centro X
    más cercano a las zonas detectadas.

    Confianza = 1 - distancia_normalizada (0..1).
    Items demasiado lejos de cualquier zona → descartados.
    """
    if not zones:
        return []

    zone_centers = [(z[0] + z[1]) / 2 for z in zones]
    zone_widths  = [max(z[1] - z[0], 10.0) for z in zones]
    n_cols = len(zones)
    cells: list[GridCell] = []

    for row_idx, row_items in enumerate(rows):
        # Acumular texto cuando múltiples boxes caen en la misma celda
        col_buckets: dict[int, list[dict]] = {}

        for it in row_items:
            xc = it["x_center"]
            best_col = min(range(n_cols), key=lambda ci: abs(xc - zone_centers[ci]))
            dist = abs(xc - zone_centers[best_col])
            max_allowed = zone_widths[best_col] * max_dist_factor

            if dist > max_allowed:
                logger.debug("[GEO] item descartado: dist=%.1f max=%.1f text=%s", dist, max_allowed, it["text"][:30])
                continue

            col_buckets.setdefault(best_col, []).append(it)

        for col_idx, bucket in col_buckets.items():
            # Ordenar por X y concatenar texto
            bucket.sort(key=lambda i: i["x1"])
            text = " ".join(i["text"] for i in bucket).strip()
            if not text:
                continue

            # Confianza: promedio basado en distancia al centroide de columna
            total_conf = 0.0
            for it in bucket:
                dist = abs(it["x_center"] - zone_centers[col_idx])
                half_w = zone_widths[col_idx] * max_dist_factor
                total_conf += max(0.0, 1.0 - dist / half_w)
            conf = total_conf / len(bucket)

            # Bbox de la celda
            x1 = min(i["x1"] for i in bucket)
            y1 = min(i["y1"] for i in bucket)
            x2 = max(i["x2"] for i in bucket)
            y2 = max(i["y2"] for i in bucket)

            cells.append(GridCell(
                row_idx=row_idx,
                col_idx=col_idx,
                text=text,
                bbox=(x1, y1, x2, y2),
                confidence=round(conf, 3),
            ))

    return cells


# ─── Punto de entrada principal ───────────────────────────────────────────────

def detect_table_grid(
    ocr_boxes: list[dict],
    min_cols: int = 2,
    min_data_rows: int = 1,
    max_cols: int = 30,
    y_tol: float | None = None,
) -> GridTable | None:
    """
    Analiza OCR boxes y devuelve un GridTable estilo Textract.

    Parámetros
    ----------
    ocr_boxes     : lista de dicts con campos 'text' y 'rect' (x1,y1,x2,y2)
    min_cols      : columnas mínimas para que la tabla sea válida
    min_data_rows : filas de datos mínimas (excluyendo encabezado)
    max_cols      : columnas máximas a detectar
    y_tol         : tolerancia Y en píxeles (None = adaptativo)

    Devuelve None si no se detecta ninguna tabla válida.
    """
    if not ocr_boxes:
        return None

    # ── Preparar items ────────────────────────────────────────────────────────
    items: list[dict] = []
    for box in ocr_boxes:
        text = str(box.get("text", "") or "").strip()
        if not text:
            continue
        rect = _safe_rect(box)
        if rect is None:
            continue
        x1, y1, x2, y2 = rect
        items.append({
            "text": text,
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "x_center": (x1 + x2) / 2,
            "y_center": (y1 + y2) / 2,
            "height": max(1.0, y2 - y1),
        })

    if not items:
        return None

    # ── Paso 1: clustering de filas ───────────────────────────────────────────
    rows = _cluster_rows(items, y_tol=y_tol)
    logger.debug("[GEO] filas detectadas=%d total_items=%d", len(rows), len(items))

    if len(rows) < min_data_rows + 1:
        return None

    # ── Paso 2: zonas de columna ──────────────────────────────────────────────
    zones = _detect_column_zones(items, min_cols=min_cols, max_cols=max_cols)
    if len(zones) < min_cols:
        logger.debug("[GEO] zonas insuficientes: %d (mínimo %d)", len(zones), min_cols)
        return None

    # ── Paso 3: asignación a grid ─────────────────────────────────────────────
    cells = _assign_to_grid(rows, zones)
    if not cells:
        return None

    # Verificar que hay filas de datos con contenido
    data_cells = [c for c in cells if c.row_idx > 0]
    if len(data_cells) < min_data_rows * min_cols:
        logger.debug("[GEO] pocas celdas de datos: %d", len(data_cells))
        return None

    # ── Construir GridTable ───────────────────────────────────────────────────
    n_rows = max(c.row_idx for c in cells) + 1
    n_cols = len(zones)

    # Etiquetas de columna: textos de la primera fila
    col_labels: list[str] = [f"COL_{i+1}" for i in range(n_cols)]
    header_cells = [c for c in cells if c.row_idx == 0]
    for hc in header_cells:
        if 0 <= hc.col_idx < n_cols:
            col_labels[hc.col_idx] = hc.text.upper().strip()

    grid = GridTable(
        cells=cells,
        n_rows=n_rows,
        n_cols=n_cols,
        column_zones=zones,
        column_labels=col_labels,
    )

    logger.info(
        "[GEO] GridTable: %d filas × %d cols | quality=%.1f | labels=%s",
        n_rows, n_cols, grid.quality_score, col_labels,
    )
    return grid


# ─── Detección multi-bloque ───────────────────────────────────────────────────

def detect_all_table_grids(
    ocr_boxes: list[dict],
    min_cols: int = 2,
    min_data_rows: int = 1,
    max_cols: int = 30,
    block_gap_factor: float = 2.5,
) -> list[GridTable]:
    """
    Detecta MÚLTIPLES tablas en un mismo conjunto de OCR boxes separando
    bloques verticales (cuando hay un salto Y > block_gap_factor × altura_mediana).

    Útil para PDFs con varias tablas en distintas secciones.
    """
    if not ocr_boxes:
        return []

    items: list[dict] = []
    for box in ocr_boxes:
        text = str(box.get("text", "") or "").strip()
        if not text:
            continue
        rect = _safe_rect(box)
        if rect is None:
            continue
        x1, y1, x2, y2 = rect
        items.append({
            "text": text,
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "x_center": (x1 + x2) / 2,
            "y_center": (y1 + y2) / 2,
            "height": max(1.0, y2 - y1),
        })

    if not items:
        return []

    heights = [it["height"] for it in items]
    median_h = _median(heights) if heights else 14.0
    y_tol = max(5.0, min(median_h * 0.6, 60.0))
    block_gap = median_h * block_gap_factor

    rows = _cluster_rows(items, y_tol=y_tol)
    if not rows:
        return []

    # Separar en bloques por salto vertical grande
    blocks: list[list[list[dict]]] = []
    current_block: list[list[dict]] = [rows[0]]
    prev_y = sum(it["y_center"] for it in rows[0]) / len(rows[0])

    for row in rows[1:]:
        row_y = sum(it["y_center"] for it in row) / len(row)
        if row_y - prev_y > block_gap:
            blocks.append(current_block)
            current_block = [row]
        else:
            current_block.append(row)
        prev_y = row_y

    if current_block:
        blocks.append(current_block)

    grids: list[GridTable] = []
    for block_rows in blocks:
        block_items = [it for row in block_rows for it in row]
        if len(block_rows) < min_data_rows + 1:
            continue
        zones = _detect_column_zones(block_items, min_cols=min_cols, max_cols=max_cols)
        if len(zones) < min_cols:
            continue
        cells = _assign_to_grid(block_rows, zones)
        if not cells:
            continue

        n_rows = max(c.row_idx for c in cells) + 1
        n_cols = len(zones)
        col_labels = [f"COL_{i+1}" for i in range(n_cols)]
        for hc in [c for c in cells if c.row_idx == 0]:
            if 0 <= hc.col_idx < n_cols:
                col_labels[hc.col_idx] = hc.text.upper().strip()

        grid = GridTable(
            cells=cells,
            n_rows=n_rows,
            n_cols=n_cols,
            column_zones=zones,
            column_labels=col_labels,
        )
        if grid.quality_score >= 10.0:
            grids.append(grid)

    logger.info("[GEO] detect_all_table_grids: %d tabla(s) detectada(s)", len(grids))
    return grids
