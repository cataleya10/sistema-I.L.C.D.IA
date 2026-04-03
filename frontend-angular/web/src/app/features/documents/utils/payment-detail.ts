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

const PAYMENT_COLUMN_LABELS: Record<string, string> = {
  // Esquema fijo de 9 columnas objetivo
  clave_beneficiario: 'CLAVE DEL BENEFICIARIO',
  nombre_beneficiario: 'NOMBRE DEL BENEFICIARIO',
  importe: 'IMPORTE',
  fecha_aplicacion: 'FECHA DE APLICACION',
  referencia: 'REFERENCIA',
  cuenta_beneficiario: 'NO. CUENTA BENEFICIARIO',
  banco_receptor: 'NO. BANCO RECEPTOR',
  dias_vigencia: 'DIAS DE VIGENCIA',
  concepto_pago: 'CONCEPTO PAGO',
  // Sinónimos adicionales (por compatibilidad con documentos históricos)
  cuenta: 'NO. CUENTA BENEFICIARIO',
  cuenta_retiro: 'NO. CUENTA BENEFICIARIO',
  nombre: 'NOMBRE DEL BENEFICIARIO',
  concepto: 'CONCEPTO PAGO',
  banco_destino: 'NO. BANCO RECEPTOR',
  banco: 'NO. BANCO RECEPTOR',
  fecha: 'FECHA DE APLICACION',
  fecha_operacion: 'FECHA DE APLICACION',
  clave_rastreo: 'REFERENCIA',
  apellido_paterno: 'Apellido paterno',
  apellido_materno: 'Apellido materno',
  estatus: 'Estatus',
  numero_empleado: 'No. Empleado',
  tipo_cuenta: 'Tipo cuenta',
  tipo_operacion: 'Tipo operacion',
  codigo: 'Codigo',
  descripcion: 'CONCEPTO PAGO',
  forma_deposito: 'Forma deposito',
  motivo_pago: 'CONCEPTO PAGO',
  divisa: 'Divisa',
  titular: 'NOMBRE DEL BENEFICIARIO',
  contrato: 'Contrato',
  folio_firma: 'Folio firma',
  folio_unico: 'REFERENCIA',
  folio_operacion: 'REFERENCIA',
  folio_internet: 'REFERENCIA',
  numero_lote: 'No. lote',
  estado: 'Estado',
  fecha_creacion: 'Fecha creacion',
  hora_captura: 'Hora captura'
};

function labelForPaymentColumn(key: string): string {
  const normalized = key.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
  return PAYMENT_COLUMN_LABELS[normalized] || titleFromKey(key);
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
      canonical_columns?: unknown;
      canonical_rows?: unknown;
      display_columns?: Record<string, string>;
      summary_tables?: unknown;
      table?: {
        canonical_columns?: unknown;
        canonical_rows?: unknown;
        display_columns?: Record<string, string>;
        summary_tables?: unknown;
      };
    };

    const metadata = payload?.metadata && typeof payload.metadata === 'object' ? payload.metadata : {};
    const metadataEntries = Object.entries(metadata)
      .map(([key, value]) => ({ key: titleFromKey(key), value: normalizeText(value) }))
      .filter((entry) => entry.key && entry.value);

    const canonicalColumnsRaw = Array.isArray(payload?.canonical_columns)
      ? payload.canonical_columns
      : Array.isArray(payload?.table?.canonical_columns)
        ? payload.table!.canonical_columns
        : [];
    const canonicalColumns = canonicalColumnsRaw
      .map((item) => normalizeText(item))
      .filter((item) => item.length > 0);

    const displayColumnsMap: Record<string, string> =
      payload?.display_columns && typeof payload.display_columns === 'object'
        ? payload.display_columns
        : payload?.table?.display_columns && typeof payload.table.display_columns === 'object'
          ? payload.table.display_columns
          : {};

    const canonicalRowsRaw = Array.isArray(payload?.canonical_rows)
      ? payload.canonical_rows
      : Array.isArray(payload?.table?.canonical_rows)
        ? payload.table!.canonical_rows
        : [];
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

    const summaryTablesRaw = Array.isArray(payload?.summary_tables)
      ? payload.summary_tables
      : Array.isArray(payload?.table?.summary_tables)
        ? payload.table!.summary_tables
        : [];
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
          rows
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
      canonicalColumns: canonicalColumns.map((col) => {
        const normalized = col.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
        return displayColumnsMap[normalized] || displayColumnsMap[col] || labelForPaymentColumn(col);
      }),
      canonicalRows,
      summaryTables
    };
  } catch {
    return null;
  }
}
