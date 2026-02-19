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

export type TableLayoutMode = 'standard' | 'advanced_nomina';

const ADVANCED_NOMINA_TOKENS = [
  'TIPO_MOVIMIENTO',
  'CLAVE_BENEFICIARIO',
  'CUENTA_BENEFICIARIO',
  'BANCO_RECEPTOR',
  'DIAS_VIGENCIA',
  'CONCEPTO_PAGO'
];

function normalizeHeaderToken(value: string): string {
  return String(value ?? '')
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
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

export function detectTableLayoutMode(tableView: TableViewModel): TableLayoutMode {
  const header = tableView.headerRows[0] ?? tableView.bodyRows[0] ?? [];
  if (!header.length) {
    return 'standard';
  }
  const normalized = header.map((cell) => normalizeHeaderToken(cell));
  const tokenHits = ADVANCED_NOMINA_TOKENS.filter((token) => normalized.includes(token)).length;
  if (tokenHits >= 3 || normalized.length >= 8) {
    return 'advanced_nomina';
  }
  return 'standard';
}

function escapeXml(value: string): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

export interface ExcelXmlOptions {
  reportMode?: boolean;
}

function columnWidths(rows: string[][], reportMode: boolean): number[] {
  const maxCols = rows.reduce((max, row) => Math.max(max, row.length), 0);
  const widths = new Array(maxCols).fill(reportMode ? 90 : 120);
  for (let col = 0; col < maxCols; col += 1) {
    let longest = 0;
    for (const row of rows) {
      const value = String(row[col] ?? '');
      longest = Math.max(longest, value.length);
    }
    const calculated = reportMode ? longest * 5.4 : longest * 6.6;
    const min = reportMode ? 70 : 90;
    const max = reportMode ? 170 : 260;
    widths[col] = Math.max(min, Math.min(max, Math.round(calculated)));
  }
  return widths;
}

export function buildExcelXml(rows: string[][], options: ExcelXmlOptions = {}): string {
  const reportMode = Boolean(options.reportMode);
  const widths = columnWidths(rows, reportMode);
  const columnsXml = widths.map((width) => `<Column ss:AutoFitWidth="0" ss:Width="${width}"/>`).join('');
  const body = rows
    .map((row, rowIndex) => {
      const isHeader = rowIndex === 0;
      const style = isHeader ? 'HeaderCell' : reportMode ? 'ReportCell' : 'BodyCell';
      const cells = row
        .map((cell) => `<Cell ss:StyleID="${style}"><Data ss:Type="String">${escapeXml(cell)}</Data></Cell>`)
        .join('');
      return `<Row>${cells}</Row>`;
    })
    .join('');

  return [
    '<?xml version="1.0"?>',
    '<?mso-application progid="Excel.Sheet"?>',
    '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"',
    ' xmlns:o="urn:schemas-microsoft-com:office:office"',
    ' xmlns:x="urn:schemas-microsoft-com:office:excel"',
    ' xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"',
    ' xmlns:html="http://www.w3.org/TR/REC-html40">',
    '<Styles>',
    '<Style ss:ID="HeaderCell">',
    '<Font ss:Bold="1"/>',
    '<Alignment ss:Horizontal="Center" ss:Vertical="Center" ss:WrapText="1"/>',
    '<Interior ss:Color="#EAF0FF" ss:Pattern="Solid"/>',
    '<Borders>',
    '<Border ss:Position="Bottom" ss:LineStyle="Continuous" ss:Weight="1"/>',
    '<Border ss:Position="Left" ss:LineStyle="Continuous" ss:Weight="1"/>',
    '<Border ss:Position="Right" ss:LineStyle="Continuous" ss:Weight="1"/>',
    '<Border ss:Position="Top" ss:LineStyle="Continuous" ss:Weight="1"/>',
    '</Borders>',
    '</Style>',
    '<Style ss:ID="BodyCell">',
    '<Alignment ss:Horizontal="Left" ss:Vertical="Center" ss:WrapText="1"/>',
    '<Borders>',
    '<Border ss:Position="Bottom" ss:LineStyle="Continuous" ss:Weight="1"/>',
    '<Border ss:Position="Left" ss:LineStyle="Continuous" ss:Weight="1"/>',
    '<Border ss:Position="Right" ss:LineStyle="Continuous" ss:Weight="1"/>',
    '<Border ss:Position="Top" ss:LineStyle="Continuous" ss:Weight="1"/>',
    '</Borders>',
    '</Style>',
    '<Style ss:ID="ReportCell">',
    '<Alignment ss:Horizontal="Center" ss:Vertical="Center" ss:WrapText="1"/>',
    '<Borders>',
    '<Border ss:Position="Bottom" ss:LineStyle="Continuous" ss:Weight="1"/>',
    '<Border ss:Position="Left" ss:LineStyle="Continuous" ss:Weight="1"/>',
    '<Border ss:Position="Right" ss:LineStyle="Continuous" ss:Weight="1"/>',
    '<Border ss:Position="Top" ss:LineStyle="Continuous" ss:Weight="1"/>',
    '</Borders>',
    '</Style>',
    '</Styles>',
    '<Worksheet ss:Name="Tabla">',
    '<Table>',
    columnsXml,
    body,
    '</Table>',
    '</Worksheet>',
    '</Workbook>'
  ].join('');
}

function escapeHtml(value: string): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function buildReportHtmlDocument(title: string, rows: string[][]): string {
  const header = rows[0] ?? [];
  const body = rows.slice(1);
  const colCount = Math.max(1, header.length || (body[0]?.length ?? 1));

  const thead = header.length
    ? `<thead><tr>${header.map((cell) => `<th>${escapeHtml(cell)}</th>`).join('')}</tr></thead>`
    : '';
  const tbody = body.length
    ? `<tbody>${body
        .map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`)
        .join('')}</tbody>`
    : `<tbody><tr><td colspan="${colCount}">Sin datos</td></tr></tbody>`;

  return [
    '<!doctype html>',
    '<html lang="es">',
    '<head>',
    '<meta charset="utf-8" />',
    `<title>${escapeHtml(title)}</title>`,
    '<style>',
    'body{font-family:"Times New Roman",Georgia,serif;margin:22px;color:#111;}',
    'h1{font-size:18px;text-align:center;margin:0 0 14px;}',
    'table{width:100%;border-collapse:collapse;table-layout:fixed;}',
    'th,td{border:1px solid #374151;padding:4px 6px;font-size:11px;line-height:1.1;text-align:center;vertical-align:middle;word-wrap:break-word;}',
    'th{background:#e5e7eb;font-weight:700;}',
    'tbody tr:nth-child(even) td{background:#f9fafb;}',
    '.meta{font-size:11px;color:#374151;margin:0 0 10px;}',
    '@page{size:A4 landscape;margin:10mm;}',
    '</style>',
    '</head>',
    '<body>',
    `<h1>${escapeHtml(title)}</h1>`,
    `<p class="meta">Generado: ${new Date().toLocaleString('es-MX')}</p>`,
    `<table>${thead}${tbody}</table>`,
    '<script>window.onload=function(){setTimeout(function(){window.print();},120);}</script>',
    '</body>',
    '</html>'
  ].join('');
}
