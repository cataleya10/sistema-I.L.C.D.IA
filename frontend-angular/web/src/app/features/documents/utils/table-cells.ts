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

export function flattenTableView(tableView: TableViewModel): string[][] {
  return [...tableView.headerRows, ...tableView.bodyRows];
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

export interface CsvBuildOptions {
  delimiter?: string;
  includeUtf8Bom?: boolean;
}

export function buildCsv(rows: string[][], options: CsvBuildOptions = {}): string {
  const delimiter = options.delimiter ?? ',';
  const content = rows
    .map((row) => row.map((cell) => escapeCsvCell(cell, delimiter)).join(delimiter))
    .join('\n');
  if (options.includeUtf8Bom === false) {
    return content;
  }
  return `\uFEFF${content}`;
}

function escapeCsvCell(value: string, delimiter: string): string {
  const normalized = String(value ?? '');
  const escapeRegex = new RegExp(`[\"\\n\\r${escapeRegexToken(delimiter)}]`);
  if (escapeRegex.test(normalized)) {
    return `"${normalized.replace(/"/g, '""')}"`;
  }
  return normalized;
}

function escapeRegexToken(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function escapeHtml(value: string): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function buildReportHtmlDocument(title: string, tableView: TableViewModel): string {
  const header = tableView.headerRows ?? [];
  const body = tableView.bodyRows ?? [];
  const firstHeader = header[0] ?? [];
  const firstBody = body[0] ?? [];
  const colCount = Math.max(
    1,
    firstHeader.length || firstBody.length,
    ...header.map((row) => row.length),
    ...body.map((row) => row.length)
  );

  const thead = header.length
    ? `<thead>${header
        .map((row) => `<tr>${row.map((cell) => `<th>${escapeHtml(cell)}</th>`).join('')}</tr>`)
        .join('')}</thead>`
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

function escapePdfText(value: string): string {
  return String(value ?? '')
    .replace(/\\/g, '\\\\')
    .replace(/\(/g, '\\(')
    .replace(/\)/g, '\\)')
    .replace(/\r\n/g, ' ')
    .replace(/[\r\n\t]+/g, ' ')
    .trim();
}

function truncatePdfCell(value: string, width: number): string {
  const normalized = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (!normalized) {
    return '';
  }
  const maxChars = Math.max(4, Math.floor(width / 5.3));
  if (normalized.length <= maxChars) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(1, maxChars - 1))}…`;
}

function formatPdfDate(): string {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, '0');
  const dd = String(now.getDate()).padStart(2, '0');
  const hh = String(now.getHours()).padStart(2, '0');
  const mi = String(now.getMinutes()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
}

function toPdfDocumentBytes(objects: string[]): Uint8Array {
  let body = '%PDF-1.4\n';
  const offsets: number[] = [0];
  for (let index = 0; index < objects.length; index += 1) {
    offsets.push(body.length);
    body += `${index + 1} 0 obj\n${objects[index]}\nendobj\n`;
  }

  const xrefOffset = body.length;
  body += `xref\n0 ${objects.length + 1}\n`;
  body += '0000000000 65535 f \n';
  for (let index = 1; index <= objects.length; index += 1) {
    body += `${String(offsets[index]).padStart(10, '0')} 00000 n \n`;
  }
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`;

  return new TextEncoder().encode(body);
}

export function buildTablePdfBytes(title: string, tableView: TableViewModel): Uint8Array {
  const rows = flattenTableView(tableView);
  const headerCount = tableView.headerRows.length;
  const colCount = Math.max(1, ...rows.map((row) => row.length), 1);
  const normalizedRows = rows.map((row) => {
    if (row.length >= colCount) {
      return row;
    }
    return [...row, ...new Array(colCount - row.length).fill('')];
  });

  const pageWidth = 842;
  const pageHeight = 595;
  const marginLeft = 28;
  const marginTop = 32;
  const marginBottom = 28;
  const titleHeight = 20;
  const metaHeight = 14;
  const tableTop = pageHeight - marginTop - titleHeight - metaHeight;
  const rowHeight = 18;
  const tableWidth = pageWidth - marginLeft * 2;
  const colWidth = tableWidth / colCount;
  const maxRowsPerPage = Math.max(1, Math.floor((tableTop - marginBottom) / rowHeight));
  const pages: string[] = [];
  const headerRows = tableView.headerRows.length ? tableView.headerRows : normalizedRows.slice(0, 1);
  const bodyRows = tableView.headerRows.length ? tableView.bodyRows : normalizedRows.slice(1);

  for (let pageIndex = 0; ; pageIndex += 1) {
    const start = pageIndex * maxRowsPerPage;
    const chunk = bodyRows.slice(start, start + maxRowsPerPage);
    if (pageIndex > 0 && chunk.length === 0) {
      break;
    }
    const pageRows = pageIndex === 0 ? normalizedRows.slice(0, maxRowsPerPage) : [...headerRows, ...chunk];
    if (!pageRows.length) {
      break;
    }

    const commands: string[] = [];
    commands.push('BT /F1 13 Tf 28 560 Td');
    commands.push(`(${escapePdfText(title)}) Tj`);
    commands.push('ET');
    commands.push('BT /F1 9 Tf 28 544 Td');
    commands.push(`(Generado: ${escapePdfText(formatPdfDate())}) Tj`);
    commands.push('ET');

    const tableRowsOnPage = pageRows.length;
    const tableBottom = tableTop - tableRowsOnPage * rowHeight;

    commands.push('0.80 0.84 0.90 rg');
    const drawHeaderCount = Math.min(headerRows.length || 1, tableRowsOnPage);
    for (let headerRowIndex = 0; headerRowIndex < drawHeaderCount; headerRowIndex += 1) {
      const y = tableTop - (headerRowIndex + 1) * rowHeight;
      commands.push(`${marginLeft} ${y} ${tableWidth} ${rowHeight} re f`);
    }
    commands.push('0 g');

    for (let rowLine = 0; rowLine <= tableRowsOnPage; rowLine += 1) {
      const y = tableTop - rowLine * rowHeight;
      commands.push(`${marginLeft} ${y} m ${marginLeft + tableWidth} ${y} l S`);
    }
    for (let colLine = 0; colLine <= colCount; colLine += 1) {
      const x = marginLeft + colLine * colWidth;
      commands.push(`${x} ${tableTop} m ${x} ${tableBottom} l S`);
    }

    for (let rowIndex = 0; rowIndex < tableRowsOnPage; rowIndex += 1) {
      const row = pageRows[rowIndex];
      const textY = tableTop - rowIndex * rowHeight - 12;
      for (let colIndex = 0; colIndex < colCount; colIndex += 1) {
        const raw = truncatePdfCell(String(row[colIndex] ?? ''), colWidth - 6);
        if (!raw) {
          continue;
        }
        const textX = marginLeft + colIndex * colWidth + 3;
        commands.push(`BT /F1 8 Tf ${textX.toFixed(2)} ${textY.toFixed(2)} Td (${escapePdfText(raw)}) Tj ET`);
      }
    }

    const stream = commands.join('\n');
    pages.push(stream);
    if (chunk.length < maxRowsPerPage) {
      break;
    }
  }

  const objects: string[] = [];
  objects.push('<< /Type /Catalog /Pages 2 0 R >>');

  const pageObjectRefs: number[] = [];
  let nextObjectId = 3;
  const fontObjectId = 3 + pages.length * 2;
  for (let index = 0; index < pages.length; index += 1) {
    const pageObjectId = nextObjectId;
    const contentObjectId = nextObjectId + 1;
    pageObjectRefs.push(pageObjectId);
    objects.push(
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidth} ${pageHeight}] /Resources << /Font << /F1 ${fontObjectId} 0 R >> >> /Contents ${contentObjectId} 0 R >>`
    );
    const stream = pages[index];
    objects.push(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`);
    nextObjectId += 2;
  }

  objects.splice(
    1,
    0,
    `<< /Type /Pages /Kids [${pageObjectRefs.map((id) => `${id} 0 R`).join(' ')}] /Count ${pageObjectRefs.length} >>`
  );
  objects.push('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>');

  return toPdfDocumentBytes(objects);
}
