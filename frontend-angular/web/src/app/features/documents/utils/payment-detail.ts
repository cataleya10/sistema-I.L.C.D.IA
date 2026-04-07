export interface PaymentDetailViewModel {
  bank: string;
  metadataEntries: Array<{ key: string; value: string }>;
  validationWarnings: string[];
  canonicalColumnKeys: string[];
  canonicalColumns: string[];
  canonicalRowObjects: Array<Record<string, string>>;
  canonicalRows: string[][];
  summaryTables: Array<{ title: string; columns: string[]; rows: string[][] }>;
  expectedTotalAmount: number | null;
  expectedTotalSource: string | null;
  extractedTotalAmount: number;
  totalDifferenceAmount: number | null;
  totalsMatch: boolean | null;
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

const TOTAL_METADATA_KEYS = [
  'importe_total_movimientos',
  'importe_movimiento_altas',
  'importe_detectado',
  'importe_total'
];

function parseAmount(value: unknown): number | null {
  const raw = normalizeText(value);
  if (!raw) {
    return null;
  }

  let normalized = raw
    .toUpperCase()
    .replace(/\$/g, '')
    .replace(/MXN/g, '')
    .replace(/PESOS/g, '')
    .replace(/\s+/g, '')
    .replace(/O/g, '0')
    .replace(/[IL]/g, '1')
    .replace(/[^0-9,.\-]/g, '');

  if (!normalized) {
    return null;
  }

  if (normalized.includes(',') && normalized.includes('.')) {
    const decimalSep = normalized.lastIndexOf('.') > normalized.lastIndexOf(',') ? '.' : ',';
    normalized =
      decimalSep === '.'
        ? normalized.replace(/,/g, '')
        : normalized.replace(/\./g, '').replace(',', '.');
  } else if (normalized.split(',').length === 2 && normalized.split(',')[1].length <= 2) {
    normalized = normalized.replace(',', '.');
  } else {
    normalized = normalized.replace(/,/g, '');
  }

  const parsed = Number.parseFloat(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function shouldSkipItemLevelExpectedTotal(
  bank: string,
  metadata: Record<string, unknown>,
  key: string,
  rowCount: number
): boolean {
  if (key !== 'importe_detectado' || rowCount <= 1) {
    return false;
  }

  const normalizedBank = normalizeText(bank).toUpperCase();
  const paymentType = normalizeText(metadata['tipo_pago']).toUpperCase();
  return normalizedBank === 'BBVA' && paymentType.includes('GRUPO PAGO');
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
      validation_warnings?: unknown;
      summary_tables?: unknown;
      table?: {
        canonical_columns?: unknown;
        canonical_rows?: unknown;
        display_columns?: Record<string, string>;
        validation_warnings?: unknown;
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

    const validationWarningsRaw = Array.isArray(payload?.validation_warnings)
      ? payload.validation_warnings
      : Array.isArray(payload?.table?.validation_warnings)
        ? payload.table.validation_warnings
        : [];
    const validationWarnings = validationWarningsRaw
      .map((item) => normalizeText(item))
      .filter((item) => item.length > 0);

    const canonicalRowsRaw = Array.isArray(payload?.canonical_rows)
      ? payload.canonical_rows
      : Array.isArray(payload?.table?.canonical_rows)
        ? payload.table!.canonical_rows
        : [];
    const canonicalRowObjects = canonicalRowsRaw
      .map((row) => {
        if (!row || typeof row !== 'object') {
          return null;
        }

        const typed = row as Record<string, unknown>;
        const entries = Object.entries(typed)
          .map(([key, value]) => [normalizeText(key), normalizeText(value)] as const)
          .filter(([key, value]) => key.length > 0 && value.length > 0);
        if (!entries.length) {
          return null;
        }

        return Object.fromEntries(entries);
      })
      .filter((row): row is Record<string, string> => row !== null);

    const canonicalColumnKeys = canonicalColumns.length > 0
      ? canonicalColumns.map((col) => normalizeText(col))
      : Object.keys(canonicalRowObjects[0] ?? {});

    const canonicalRows = canonicalRowObjects
      .map((row) =>
        canonicalColumnKeys.map((col) => normalizeText(row[col]))
      )
      .filter((row) => row.some((cell) => cell.length > 0));

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

    const bank = normalizeText(payload?.bank) || 'DESCONOCIDO';
    let expectedTotalSource: string | null = null;
    let expectedTotalAmount: number | null = null;
    for (const key of TOTAL_METADATA_KEYS) {
      const amount = parseAmount(metadata[key]);
      if (amount !== null && !shouldSkipItemLevelExpectedTotal(bank, metadata, key, canonicalRowObjects.length)) {
        expectedTotalSource = key;
        expectedTotalAmount = amount;
        break;
      }
    }

    const importeColumnKey = canonicalColumnKeys.find((key) => {
      const normalized = key.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
      return normalized === 'importe';
    });
    const extractedTotalAmount = canonicalRowObjects.reduce((total, row) => {
      const amount = parseAmount(importeColumnKey ? row[importeColumnKey] : null);
      return total + (amount ?? 0);
    }, 0);

    const totalDifferenceAmount =
      expectedTotalAmount !== null ? extractedTotalAmount - expectedTotalAmount : null;
    const totalTolerance =
      expectedTotalAmount !== null
        ? Math.max(0.05, Math.round(expectedTotalAmount * 0.005 * 100) / 100)
        : null;
    const totalsMatch =
      expectedTotalAmount !== null && totalTolerance !== null
        ? Math.abs(totalDifferenceAmount ?? 0) <= totalTolerance
        : null;

    return {
      bank,
      metadataEntries,
      validationWarnings,
      canonicalColumnKeys,
      canonicalColumns: canonicalColumnKeys.map((col) => {
        const normalized = col.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
        return displayColumnsMap[normalized] || displayColumnsMap[col] || labelForPaymentColumn(col);
      }),
      canonicalRowObjects,
      canonicalRows,
      summaryTables
      ,
      expectedTotalAmount,
      expectedTotalSource,
      extractedTotalAmount,
      totalDifferenceAmount,
      totalsMatch
    };
  } catch {
    return null;
  }
}
