export type ReplicaPreset = 'default' | 'scotia' | 'bbva';

export interface ReplicaLayoutLineView {
  text: string;
  leftPct: number;
  topPct: number;
  widthPct: number;
  heightPx: number;
  fontSizePx: number;
  lineHeight: string;
}

export interface ReplicaLayoutPageView {
  aspectRatio: number;
  lines: ReplicaLayoutLineView[];
}

export interface ReplicaLayoutView {
  preset: ReplicaPreset;
  detectedBank: string;
  detectedBankLabel: string;
  pages: ReplicaLayoutPageView[];
}

export interface ReplicaGeometryPreset {
  scaleX: number;
  scaleY: number;
  offsetX: number;
  offsetY: number;
  aspectShift: number;
}

export interface ReplicaTypographyPreset {
  fontScale: number;
  lineHeight: string;
}

export interface ReplicaPresetTuning {
  geometry: ReplicaGeometryPreset;
  typography: ReplicaTypographyPreset;
}

export interface ReplicaPresetTuningOverride {
  geometry?: Partial<ReplicaGeometryPreset>;
  typography?: Partial<ReplicaTypographyPreset>;
}

export type ReplicaPresetTuningOverrides = Partial<Record<ReplicaPreset, ReplicaPresetTuningOverride>>;

interface RawLayoutLine {
  text?: string;
  x?: number;
  y?: number;
  w?: number;
  h?: number;
}

interface RawLayoutPage {
  width?: number;
  height?: number;
  lines?: RawLayoutLine[];
}

interface RawLayoutPayload {
  pages?: RawLayoutPage[];
}

const BASE_FONT_SIZE_MIN = 9;
const BASE_FONT_SIZE_MAX = 14;

export const REPLICA_PRESET_TUNING: Record<ReplicaPreset, ReplicaPresetTuning> = {
  default: {
    geometry: { scaleX: 1, scaleY: 1, offsetX: 0, offsetY: 0, aspectShift: 0 },
    typography: { fontScale: 0.9, lineHeight: '1.08' }
  },
  scotia: {
    geometry: { scaleX: 0.965, scaleY: 0.97, offsetX: 1.6, offsetY: 2.2, aspectShift: 2 },
    typography: { fontScale: 0.88, lineHeight: '1.02' }
  },
  bbva: {
    geometry: { scaleX: 0.975, scaleY: 0.98, offsetX: 1.2, offsetY: 1.4, aspectShift: 1 },
    typography: { fontScale: 0.95, lineHeight: '1.0' }
  }
};

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function resolvePresetTuning(overrides?: ReplicaPresetTuningOverrides): Record<ReplicaPreset, ReplicaPresetTuning> {
  if (!overrides) {
    return REPLICA_PRESET_TUNING;
  }
  const resolved = {} as Record<ReplicaPreset, ReplicaPresetTuning>;
  (Object.keys(REPLICA_PRESET_TUNING) as ReplicaPreset[]).forEach((preset) => {
    const base = REPLICA_PRESET_TUNING[preset];
    const override = overrides[preset];
    resolved[preset] = {
      geometry: {
        ...base.geometry,
        ...(override?.geometry ?? {})
      },
      typography: {
        ...base.typography,
        ...(override?.typography ?? {})
      }
    };
  });
  return resolved;
}

function detectPresetFromText(sample: string): ReplicaPreset {
  const normalized = sample.toUpperCase();
  if (normalized.includes('SCOTIABANK')) {
    return 'scotia';
  }
  if (
    normalized.includes('BBVA')
    || normalized.includes('REPORTE DE TRANSMISION')
    || normalized.includes('BANCOMER')
  ) {
    return 'bbva';
  }
  return 'default';
}

function detectBankFromText(sample: string): { code: string; label: string } {
  const normalized = sample.toUpperCase();
  if (normalized.includes('SCOTIABANK')) {
    return { code: 'scotia', label: 'Scotiabank' };
  }
  if (normalized.includes('BBVA') || normalized.includes('BANCOMER')) {
    return { code: 'bbva', label: 'BBVA' };
  }
  if (normalized.includes('SANTANDER')) {
    return { code: 'santander', label: 'Santander' };
  }
  if (normalized.includes('BANORTE') || normalized.includes('IXE')) {
    return { code: 'banorte', label: 'Banorte' };
  }
  if (normalized.includes('BANAMEX') || normalized.includes('CITIBANAMEX') || normalized.includes('CITI')) {
    return { code: 'banamex', label: 'Banamex / CitiBanamex' };
  }
  if (normalized.includes('HSBC')) {
    return { code: 'hsbc', label: 'HSBC' };
  }
  if (normalized.includes('INBURSA')) {
    return { code: 'inbursa', label: 'Inbursa' };
  }
  if (normalized.includes('AZTECA') || normalized.includes('BANCO AZTECA')) {
    return { code: 'azteca', label: 'Banco Azteca' };
  }
  if (normalized.includes('BANBAJIO') || normalized.includes('BAJIO')) {
    return { code: 'banbajio', label: 'BanBajio' };
  }
  return { code: 'unknown', label: 'No identificado' };
}

function toBaseLineView(
  line: RawLayoutLine,
  pageWidth: number,
  pageHeight: number,
  baseTypography: ReplicaTypographyPreset
): ReplicaLayoutLineView | null {
  const text = String(line.text ?? '').trim();
  if (!text) {
    return null;
  }
  const x = Math.max(0, Number(line.x) || 0);
  const y = Math.max(0, Number(line.y) || 0);
  const w = Math.max(1, Number(line.w) || 1);
  const h = Math.max(1, Number(line.h) || 1);
  return {
    text,
    leftPct: clamp((x / pageWidth) * 100, 0, 99),
    topPct: clamp((y / pageHeight) * 100, 0, 99),
    widthPct: clamp((w / pageWidth) * 100, 0.5, 100),
    heightPx: clamp(Math.round(h), 10, 28),
    fontSizePx: clamp(Math.round(h * baseTypography.fontScale), BASE_FONT_SIZE_MIN, BASE_FONT_SIZE_MAX),
    lineHeight: baseTypography.lineHeight
  };
}

function tuneLayoutByPreset(
  pages: ReplicaLayoutPageView[],
  preset: ReplicaPreset,
  tuningByPreset: Record<ReplicaPreset, ReplicaPresetTuning>
): ReplicaLayoutPageView[] {
  const tuning = tuningByPreset[preset];
  return pages.map((page) => ({
    ...page,
    aspectRatio: clamp(page.aspectRatio + tuning.geometry.aspectShift, 45, 180),
    lines: page.lines.map((line) => {
      const leftPct = clamp((line.leftPct * tuning.geometry.scaleX) + tuning.geometry.offsetX, 0, 99);
      const topPct = clamp((line.topPct * tuning.geometry.scaleY) + tuning.geometry.offsetY, 0, 99);
      const widthPct = clamp(line.widthPct * tuning.geometry.scaleX, 0.5, Math.max(0.5, 100 - leftPct));
      return {
        ...line,
        leftPct,
        topPct,
        widthPct,
        fontSizePx: clamp(Math.round(line.heightPx * tuning.typography.fontScale), BASE_FONT_SIZE_MIN, 13),
        lineHeight: tuning.typography.lineHeight
      };
    })
  }));
}

export function parseReplicaLayout(
  rawValue: string | null | undefined,
  overrides?: ReplicaPresetTuningOverrides
): ReplicaLayoutView | null {
  const serialized = String(rawValue ?? '').trim();
  if (!serialized) {
    return null;
  }

  try {
    const tuningByPreset = resolvePresetTuning(overrides);
    const payload = JSON.parse(serialized) as RawLayoutPayload;
    if (!payload?.pages?.length) {
      return null;
    }

    const pages = payload.pages
      .map((page): ReplicaLayoutPageView | null => {
        const width = Math.max(1, Number(page.width) || 1);
        const height = Math.max(1, Number(page.height) || 1);
        const lines = (page.lines ?? [])
          .map((line) => toBaseLineView(line, width, height, tuningByPreset.default.typography))
          .filter((line): line is ReplicaLayoutLineView => line !== null);
        if (!lines.length) {
          return null;
        }
        return {
          aspectRatio: clamp((height / width) * 100, 45, 180),
          lines
        };
      })
      .filter((page): page is ReplicaLayoutPageView => page !== null);

    if (!pages.length) {
      return null;
    }

    const sample = pages[0]?.lines?.slice(0, 60).map((line) => line.text).join(' ') ?? '';
    const preset = detectPresetFromText(sample);
    const bank = detectBankFromText(sample);
    return {
      preset,
      detectedBank: bank.code,
      detectedBankLabel: bank.label,
      pages: tuneLayoutByPreset(pages, preset, tuningByPreset)
    };
  } catch {
    return null;
  }
}
