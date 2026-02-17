import { DocumentField } from '../../../shared/models/document.models';

const TABLE_FIELD_KEYS = new Set(['tabla_celdas', 'tabla', 'celdas', 'table_cells']);
const HEADER_HINTS = ['TIPO', 'CUENTA', 'REFERENCIA', 'CLAVE', 'NOMBRE', 'BANCO', 'CONCEPTO', 'FECHA', 'MOVIMIENTO', 'IMPORTE'];

function normalizeToken(value: string | null | undefined): string {
  return String(value ?? '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

function extractRows(payload: unknown): unknown[] | null {
  if (Array.isArray(payload)) {
    return payload;
  }
  if (payload && typeof payload === 'object' && 'rows' in payload) {
    const rows = (payload as { rows?: unknown }).rows;
    return Array.isArray(rows) ? rows : null;
  }
  return null;
}

function tryParseJsonLike(text: string): unknown {
  const trimmed = text.trim();
  if (!trimmed) {
    return null;
  }

  try {
    return JSON.parse(trimmed);
  } catch {
    // Fallback for payloads serialized as Python-like strings with single quotes.
    const singleQuoted = trimmed.replace(/'([^'\\]*(?:\\.[^'\\]*)*)'/g, (_, raw: string) => {
      const unescaped = String(raw).replace(/\\"/g, '"');
      const escaped = unescaped.replace(/"/g, '\\"');
      return `"${escaped}"`;
    });
    return JSON.parse(singleQuoted);
  }
}

function tryParsePayload(rawValue: string): unknown {
  let candidate: unknown = rawValue.trim();
  for (let attempt = 0; attempt < 3; attempt += 1) {
    if (typeof candidate !== 'string') {
      return candidate;
    }

    const text = candidate.trim();
    if (!text) {
      return null;
    }

    try {
      candidate = tryParseJsonLike(text);
      continue;
    } catch {
      const start = text.indexOf('{');
      const end = text.lastIndexOf('}');
      if (start >= 0 && end > start) {
        const slice = text.slice(start, end + 1);
        try {
          candidate = tryParseJsonLike(slice);
          continue;
        } catch {
          return text;
        }
      }
      return text;
    }
  }
  return candidate;
}

export function isTableCellsField(field: Pick<DocumentField, 'key' | 'label'>): boolean {
  const key = normalizeToken(field.key);
  if (TABLE_FIELD_KEYS.has(key)) {
    return true;
  }

  const label = normalizeToken(field.label);
  return label.includes('tabla') && label.includes('celdas');
}

export function parseTableRows(rawValue: string | null | undefined): string[][] {
  const value = String(rawValue ?? '').trim();
  if (!value) {
    return [];
  }

  const parsed = tryParsePayload(value);
  const rows = extractRows(parsed);
  if (!rows || rows.length === 0) {
    return [];
  }

  const parsedRows = rows
    .map((row): unknown[] | null => {
      if (Array.isArray(row)) {
        return row;
      }
      if (typeof row !== 'string') {
        return null;
      }
      const parsedRow = tryParsePayload(row);
      return Array.isArray(parsedRow) ? parsedRow : null;
    })
    .filter((row): row is unknown[] => Array.isArray(row));

  const normalized = rows
    .filter((row): row is unknown[] => Array.isArray(row))
    .map((row) => row.map((cell) => String(cell ?? '').trim()))
    .filter((row) => row.some((cell) => cell.length > 0))
    .slice(0, 40);
  const sourceRows = parsedRows.length > 0 ? parsedRows : normalized;
  const normalizedRows = sourceRows
    .map((row) => row.map((cell) => String(cell ?? '').trim()))
    .filter((row) => row.some((cell) => cell.length > 0))
    .slice(0, 40);

  if (normalizedRows.length === 0) {
    return [];
  }

  const maxCols = normalizedRows.reduce((max, row) => Math.max(max, row.length), 0);
  return normalizedRows.map((row) => {
    if (row.length >= maxCols) {
      return row;
    }
    return [...row, ...new Array(maxCols - row.length).fill('')];
  });
}

function isDataLikeRow(row: string[]): boolean {
  const joined = row.join(' ').toUpperCase();
  const hasDate = /\b\d{2}\/\d{2}\/\d{4}\b/.test(joined) || /\b\d{2}-\d{2}-\d{4}\b/.test(joined);
  const hasAmount = /\$\s?\d/.test(joined) || /\b\d{1,3}(?:,\d{3})*(?:\.\d{2})\b/.test(joined);
  const hasLongDigits = /\b\d{10,}\b/.test(joined);
  return hasDate || hasAmount || hasLongDigits;
}

function isHeaderLikeRow(row: string[]): boolean {
  const joined = row.join(' ').toUpperCase();
  const hintHits = HEADER_HINTS.filter((hint) => joined.includes(hint)).length;
  if (hintHits >= 2 && !isDataLikeRow(row)) {
    return true;
  }
  return false;
}

export interface TableViewModel {
  headerRows: string[][];
  bodyRows: string[][];
}

export function buildTableView(rows: string[][]): TableViewModel {
  if (!rows.length) {
    return { headerRows: [], bodyRows: [] };
  }

  const headerRows: string[][] = [];
  let bodyStart = 0;
  for (let idx = 0; idx < rows.length; idx += 1) {
    if (idx > 1) {
      break;
    }
    const row = rows[idx];
    if (!isHeaderLikeRow(row)) {
      break;
    }
    headerRows.push(row);
    bodyStart = idx + 1;
  }

  const bodyRows = rows.slice(bodyStart);
  return {
    headerRows,
    bodyRows: bodyRows.length ? bodyRows : rows
  };
}
