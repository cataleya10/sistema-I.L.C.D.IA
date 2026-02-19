import { TableViewModel } from './table-cells';
import { ReplicaLayoutView } from './pdf-replica-layout';
import { PaymentDetailViewModel } from './payment-detail';

export interface ExtractionExportInput {
  title: string;
  tableView: TableViewModel;
  replicaLayout: ReplicaLayoutView | null;
  replicaText: string;
  paymentDetail: PaymentDetailViewModel | null;
}

function escapeHtml(value: string): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderTable(rows: string[][]): string {
  if (!rows.length) {
    return '<p class="muted">Sin filas disponibles.</p>';
  }
  const head = rows[0];
  const body = rows.slice(1);
  return `
    <table class="tbl">
      <thead>
        <tr>${head.map((cell) => `<th>${escapeHtml(cell)}</th>`).join('')}</tr>
      </thead>
      <tbody>
        ${body.map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`).join('')}
      </tbody>
    </table>
  `;
}

function renderReplicaLayout(layout: ReplicaLayoutView | null): string {
  if (!layout || !layout.pages.length) {
    return '<p class="muted">Sin layout de replica.</p>';
  }
  return layout.pages.map((page) => `
    <article class="page">
      <div class="canvas" style="padding-bottom:${page.aspectRatio}%;">
        ${page.lines.map((line) => `
          <span
            class="line"
            style="
              left:${line.leftPct}%;
              top:${line.topPct}%;
              width:${line.widthPct}%;
              height:${line.heightPx}px;
              font-size:${line.fontSizePx}px;
              line-height:${line.lineHeight};
            "
          >${escapeHtml(line.text)}</span>
        `).join('')}
      </div>
    </article>
  `).join('');
}

function renderPaymentDetail(paymentDetail: PaymentDetailViewModel | null): string {
  if (!paymentDetail) {
    return '<p class="muted">Sin pago_detalle estructurado.</p>';
  }
  const canonicalRows = paymentDetail.canonicalRows;
  const rows = paymentDetail.canonicalColumns.length
    ? [paymentDetail.canonicalColumns, ...canonicalRows]
    : canonicalRows;
  return `
    <p><strong>Banco:</strong> ${escapeHtml(paymentDetail.bank)}</p>
    <div class="meta">
      ${paymentDetail.metadataEntries.map((m) => `<p><strong>${escapeHtml(m.key)}:</strong> ${escapeHtml(m.value)}</p>`).join('')}
    </div>
    ${rows.length ? renderTable(rows) : '<p class="muted">Sin tabla canónica.</p>'}
    ${
      paymentDetail.summaryTables.length
        ? paymentDetail.summaryTables
            .map((table) => {
              const combined = table.columns.length ? [table.columns, ...table.rows] : table.rows;
              return `
                <h3>${escapeHtml(table.title)}</h3>
                ${combined.length ? renderTable(combined) : '<p class="muted">Sin filas.</p>'}
              `;
            })
            .join('')
        : ''
    }
  `;
}

export function buildExtractionHtmlDocument(input: ExtractionExportInput): string {
  const tableRows = [...input.tableView.headerRows, ...input.tableView.bodyRows];
  return `<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${escapeHtml(input.title)}</title>
    <style>
      body { font-family: Arial, sans-serif; margin: 20px; color: #111827; }
      h1, h2 { margin: 0 0 10px; }
      section { margin: 0 0 22px; }
      .muted { color: #6b7280; font-size: 12px; }
      .meta p { margin: 0 0 4px; font-size: 12px; }
      .tbl { width: 100%; border-collapse: collapse; font-size: 12px; }
      .tbl th, .tbl td { border: 1px solid #d1d5db; padding: 6px 8px; text-align: left; vertical-align: top; }
      .tbl th { background: #f3f4f6; }
      .page { border: 1px solid #d1d5db; border-radius: 8px; margin-bottom: 12px; overflow: hidden; }
      .canvas { position: relative; width: 100%; min-height: 420px; background: #fff; }
      .line { position: absolute; display: block; white-space: pre-wrap; overflow-wrap: anywhere; font-family: 'Times New Roman', serif; }
      pre { white-space: pre-wrap; background: #f8fafc; border: 1px solid #d1d5db; border-radius: 8px; padding: 10px; font-size: 11px; }
    </style>
  </head>
  <body>
    <h1>${escapeHtml(input.title)}</h1>
    <section>
      <h2>Pago estructurado</h2>
      ${renderPaymentDetail(input.paymentDetail)}
    </section>
    <section>
      <h2>Tabla detectada</h2>
      ${renderTable(tableRows)}
    </section>
    <section>
      <h2>Replica PDF (layout)</h2>
      ${renderReplicaLayout(input.replicaLayout)}
    </section>
    <section>
      <h2>Replica PDF (texto completo)</h2>
      <pre>${escapeHtml(input.replicaText || '')}</pre>
    </section>
  </body>
</html>`;
}
