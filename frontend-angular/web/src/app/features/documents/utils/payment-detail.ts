export interface PaymentDetailViewModel {
  bank: string;
  metadataEntries: Array<{ key: string; value: string }>;
  canonicalColumns: string[];
  canonicalRows: string[][];
  summaryTables: Array<{ title: string; columns: string[]; rows: string[][] }>;
}

function normalizeText(value: unknown): string {
  return String(value ?? '').trim();
}

function titleFromKey(key: string): string {
  const text = String(key ?? '').replace(/_/g, ' ').trim();
  if (!text) {
    return '';
  }
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function parsePaymentDetail(rawValue: string | null | undefined): PaymentDetailViewModel | null {
  const serialized = normalizeText(rawValue);
  if (!serialized) {
    return null;
  }

  try {
    const payload = JSON.parse(serialized) as {
      bank?: unknown;
      metadata?: Record<string, unknown>;
      table?: {
        canonical_columns?: unknown;
        canonical_rows?: unknown;
        summary_tables?: unknown;
      };
    };
    const metadata = payload?.metadata && typeof payload.metadata === 'object' ? payload.metadata : {};
    const metadataEntries = Object.entries(metadata)
      .map(([key, value]) => ({ key: titleFromKey(key), value: normalizeText(value) }))
      .filter((entry) => entry.key && entry.value);

    const canonicalColumns = Array.isArray(payload?.table?.canonical_columns)
      ? payload.table!.canonical_columns.map((item) => normalizeText(item)).filter((item) => item.length > 0)
      : [];

    const canonicalRowsRaw = Array.isArray(payload?.table?.canonical_rows) ? payload.table!.canonical_rows : [];
    const canonicalRows = canonicalRowsRaw
      .map((row) => {
        if (!row || typeof row !== 'object') {
          return null;
        }
        const typed = row as Record<string, unknown>;
        if (canonicalColumns.length > 0) {
          return canonicalColumns.map((col) => normalizeText(typed[col]));
        }
        const keys = Object.keys(typed);
        if (!keys.length) {
          return null;
        }
        return keys.map((key) => normalizeText(typed[key]));
      })
      .filter((row): row is string[] => Array.isArray(row) && row.some((cell) => cell.length > 0));

    const summaryTablesRaw = Array.isArray(payload?.table?.summary_tables) ? payload.table!.summary_tables : [];
    const summaryTables = summaryTablesRaw
      .map((item) => {
        if (!item || typeof item !== 'object') {
          return null;
        }
        const typed = item as { title?: unknown; columns?: unknown; rows?: unknown };
        const columns = Array.isArray(typed.columns) ? typed.columns.map((c) => normalizeText(c)) : [];
        const rows = Array.isArray(typed.rows)
          ? typed.rows
              .map((row) => (Array.isArray(row) ? row.map((cell) => normalizeText(cell)) : null))
              .filter((row): row is string[] => Array.isArray(row) && row.some((cell) => cell.length > 0))
          : [];
        return {
          title: normalizeText(typed.title) || 'Resumen',
          columns,
          rows,
        };
      })
      .filter(
        (item): item is { title: string; columns: string[]; rows: string[][] } =>
          item !== null && (item.columns.length > 0 || item.rows.length > 0)
      );

    if (!metadataEntries.length && !canonicalRows.length && !summaryTables.length) {
      return null;
    }

    return {
      bank: normalizeText(payload?.bank) || 'DESCONOCIDO',
      metadataEntries,
      canonicalColumns,
      canonicalRows,
      summaryTables,
    };
  } catch {
    return null;
  }
}
