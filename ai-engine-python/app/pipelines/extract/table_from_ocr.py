"""
Extracción de tablas desde OCR — fallback para PDFs escaneados.

Cuando pdfplumber / img2table / PyMuPDF no encuentran estructura de tabla
(PDFs 100% imagen), este módulo intenta reconstruir tablas a partir de:

  1. OCR boxes  — clustering espacial por coordenadas (X, Y).
                  Agrupa cajas en filas por proximidad en Y,
                  alinea columnas por centroide X del encabezado.

  2. Texto OCR  — detección de bloques con alineación de columnas.
                  Busca una línea encabezado (≥ 2 tokens conocidos)
                  seguida de líneas con estructura columnar similar.

Uso principal:
    from app.pipelines.extract.table_from_ocr import extract_fallback_tables
    raw_tables = extract_fallback_tables(ocr_text, ocr_boxes)
    # raw_tables → list[list[list[str]]] (igual que pdf_tables de preprocess)
"""

from __future__ import annotations

import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Tokens de encabezado conocidos para detectar filas de cabecera
_HEADER_KEYWORDS: frozenset[str] = frozenset({
    "NOMBRE", "CUENTA", "CLABE", "IMPORTE", "MONTO", "REFERENCIA",
    "BENEFICIARIO", "BANCO", "ESTATUS", "CONCEPTO", "RFC", "NSS",
    "CURP", "FECHA", "FOLIO", "CLAVE", "EMPLEADO", "DESCRIPCION",
    "PERCEPCION", "DEDUCCION", "CANTIDAD", "TOTAL", "SALDO",
    "CARGO", "ABONO", "SERIE", "SECUENCIA", "LOTE", "NUMERO",
    "PERIODO", "EMPRESA", "CONTRATO", "APELLIDO",
})

# Separador de columnas en texto OCR (2+ espacios o tabulación)
_COL_SEP = re.compile(r"  +|\t")


# ─── Utilidades bbox ──────────────────────────────────────────────────────────

def _bbox_to_rect(bbox: Any) -> tuple[float, float, float, float] | None:
    """Convierte cualquier formato de bbox a (x_min, y_min, x_max, y_max)."""
    if not bbox:
        return None
    try:
        if isinstance(bbox[0], (list, tuple)):
            xs = [float(p[0]) for p in bbox]
            ys = [float(p[1]) for p in bbox]
            return min(xs), min(ys), max(xs), max(ys)
        if len(bbox) >= 4:
            return float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
    except (TypeError, ValueError, IndexError):
        pass
    return None


def _header_score(tokens: list[str]) -> int:
    """Cuenta cuántos tokens de la fila coinciden con keywords de encabezado."""
    score = 0
    for t in tokens:
        upper = t.upper().strip()
        if upper in _HEADER_KEYWORDS:
            score += 2
        elif any(kw in upper for kw in _HEADER_KEYWORDS):
            score += 1
    return score


# ─── Estrategia 1: clustering espacial de OCR boxes ─────────────────────────

def extract_tables_from_ocr_boxes(
    ocr_boxes: list[dict],
    min_columns: int = 2,
    min_data_rows: int = 2,
) -> list[list[list[str]]]:
    """
    Reconstruye tablas agrupando OCR boxes por posición espacial.

    Algoritmo:
      1. Calcula (x_min, y_center, height) de cada box.
      2. Ordena por y_center; agrupa en filas cuando Δy ≤ tolerancia.
         Tolerancia = 60 % de la altura mediana de los boxes.
      3. Dentro de cada fila, ordena por x_min.
      4. Toma la fila con más celdas como referencia de columnas.
      5. Asigna cada celda al centroide de columna más cercano.
      6. Filtra segmentos sin encabezado detectado o con < min_data_rows.

    Returns
    -------
    list[list[list[str]]]
        Lista de tablas (cada tabla = lista de filas, cada fila = lista de celdas).
    """
    if not ocr_boxes:
        return []

    # 1. Extraer geometría
    items: list[dict] = []
    for box in ocr_boxes:
        text = str(box.get("text", "") or "").strip()
        if not text:
            continue
        rect = _bbox_to_rect(box.get("bbox") or box.get("rect") or [])
        if rect is None:
            continue
        x1, y1, x2, y2 = rect
        items.append({
            "text": text,
            "x_min": x1, "y_min": y1,
            "x_max": x2, "y_max": y2,
            "x_center": (x1 + x2) / 2,
            "y_center": (y1 + y2) / 2,
            "height": max(1.0, y2 - y1),
        })

    if not items:
        return []

    # Tolerancia adaptativa basada en la altura mediana de los boxes
    heights = sorted(it["height"] for it in items)
    median_h = heights[len(heights) // 2]
    row_tolerance = max(6.0, median_h * 0.65)

    # 2. Ordenar por y_center y agrupar en filas
    items.sort(key=lambda b: (b["y_center"], b["x_min"]))
    raw_rows: list[list[dict]] = []
    current: list[dict] = [items[0]]
    current_y = items[0]["y_center"]

    for it in items[1:]:
        if abs(it["y_center"] - current_y) <= row_tolerance:
            current.append(it)
            # Media corrida para acumular variación gradual en filas largas
            current_y = (current_y * (len(current) - 1) + it["y_center"]) / len(current)
        else:
            raw_rows.append(sorted(current, key=lambda b: b["x_min"]))
            current = [it]
            current_y = it["y_center"]
    if current:
        raw_rows.append(sorted(current, key=lambda b: b["x_min"]))

    if len(raw_rows) < min_data_rows + 1:
        return []

    # 3. Referencia de columnas: la fila con más celdas
    ref_row = max(raw_rows, key=len)
    n_cols = len(ref_row)
    if n_cols < min_columns:
        return []
    col_centers = [it["x_center"] for it in ref_row]

    # 4. Asignar celdas a columnas
    table: list[list[str]] = []
    for row in raw_rows:
        cells = [""] * n_cols
        for it in row:
            nearest = min(range(n_cols), key=lambda i: abs(col_centers[i] - it["x_center"]))
            cells[nearest] = (cells[nearest] + " " + it["text"]).strip() if cells[nearest] else it["text"]
        table.append(cells)

    # 5. Verificar: necesitamos al menos una fila de encabezado detectada
    header_found = any(_header_score(row) >= 3 for row in table)
    if not header_found:
        logger.debug("table_from_ocr boxes: sin encabezado detectado, descartando tabla")
        return []

    data_count = sum(1 for row in table if _header_score(row) < 2 and any(c.strip() for c in row))
    if data_count < min_data_rows:
        logger.debug("table_from_ocr boxes: solo %d filas de datos (mínimo %d)", data_count, min_data_rows)
        return []

    logger.info("table_from_ocr boxes: tabla reconstruida %d cols × %d filas", n_cols, len(table))
    return [table]


# ─── Estrategia 2: detección en texto OCR ────────────────────────────────────

def extract_tables_from_text(
    text: str,
    min_columns: int = 2,
    min_data_rows: int = 2,
) -> list[list[list[str]]]:
    """
    Detecta tablas en el texto OCR buscando bloques con estructura columnar.

    Algoritmo:
      1. Divide el texto en bloques separados por línea en blanco.
      2. En cada bloque, busca una línea encabezado (score ≥ 4).
      3. Usa 2+ espacios como separador de columnas.
      4. Filtra bloques con < min_columns columnas o < min_data_rows filas de datos.

    Returns
    -------
    list[list[list[str]]]
    """
    if not text:
        return []

    # Dividir en bloques por líneas en blanco
    blocks: list[list[str]] = []
    current_block: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            current_block.append(line)
        elif current_block:
            blocks.append(current_block)
            current_block = []
    if current_block:
        blocks.append(current_block)

    tables: list[list[list[str]]] = []

    for block in blocks:
        if len(block) < min_data_rows + 1:
            continue

        # Buscar la línea con el header score más alto dentro del bloque
        best_header_idx = -1
        best_score = 0
        for idx, line in enumerate(block[:5]):  # solo primeras 5 líneas
            tokens = _COL_SEP.split(line.strip())
            tokens = [t.strip() for t in tokens if t.strip()]
            score = _header_score(tokens)
            if score > best_score:
                best_score = score
                best_header_idx = idx

        if best_score < 4 or best_header_idx < 0:
            continue

        header_line = block[best_header_idx]
        header_cells = [c.strip() for c in _COL_SEP.split(header_line) if c.strip()]
        if len(header_cells) < min_columns:
            continue

        # Recopilar filas de datos
        data_rows: list[list[str]] = []
        for line in block[best_header_idx + 1:]:
            cells = [c.strip() for c in _COL_SEP.split(line) if c.strip()]
            if not cells:
                continue
            # Descartar si parece otra cabecera
            if _header_score(cells) >= 4:
                continue
            # Aceptar si tiene un número razonable de columnas
            if len(cells) >= min_columns:
                # Padear/truncar al número de columnas del encabezado
                padded = (cells + [""] * len(header_cells))[:len(header_cells)]
                data_rows.append(padded)

        if len(data_rows) < min_data_rows:
            continue

        table = [header_cells] + data_rows
        tables.append(table)
        logger.info(
            "table_from_ocr text: tabla detectada %d cols × %d filas",
            len(header_cells), len(data_rows),
        )

    return tables


# ─── Punto de entrada principal ──────────────────────────────────────────────

def extract_fallback_tables(
    ocr_text: str,
    ocr_boxes: list[dict] | None,
) -> list[list[list[str]]]:
    """
    Intenta extraer tablas cuando pdf_tables está vacío (PDF escaneado).

    Estrategia (en orden de prioridad):
      1. Geometric detector (Textract-like): clustering Y/X con grid indexado.
      2. Spatial clustering clásico: fallback si el detector geométrico falla.
      3. Texto OCR: detección por bloques (fallback universal).

    Returns
    -------
    list[list[list[str]]]
        Tablas en el mismo formato que pdf_tables de preprocess.
        Lista vacía si no se detecta ninguna tabla válida.
    """
    # 1. Geometric detector — más robusto, imita Amazon Textract
    if ocr_boxes:
        try:
            from .geometric_detector import detect_all_table_grids
            grids = detect_all_table_grids(ocr_boxes)
            if grids:
                tables = [g.to_raw_table() for g in grids if g.n_rows >= 2]
                if tables:
                    logger.info(
                        "table_from_ocr: %d tabla(s) via geometric_detector (Textract-like)",
                        len(tables),
                    )
                    return tables
        except Exception:
            logger.debug("geometric_detector falló, continuando con fallback", exc_info=True)

    # 2. Spatial clustering clásico
    if ocr_boxes:
        tables = extract_tables_from_ocr_boxes(ocr_boxes)
        if tables:
            logger.info("table_from_ocr: %d tabla(s) via spatial clustering", len(tables))
            return tables

    # 3. Texto OCR
    if ocr_text:
        tables = extract_tables_from_text(ocr_text)
        if tables:
            logger.info("table_from_ocr: %d tabla(s) via text detection", len(tables))
            return tables

    return []
