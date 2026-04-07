export type DocumentStatus = 'UPLOADED' | 'PROCESSING' | 'READY' | 'NEEDS_REVIEW' | 'FAILED';

export type DocumentType =
  | 'INE'
  | 'CURP'
  | 'ACTA_NACIMIENTO'
  | 'COMPROBANTE_DOMICILIO'
  | 'NSS'
  | 'DATOS_BANCARIOS'
  | 'FACTURA'
  | 'CONSTANCIA_SITUACION_FISCAL'
  | 'GENERICO'
  | 'UNKNOWN';

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  INE: 'INE',
  CURP: 'CURP',
  ACTA_NACIMIENTO: 'ACTA_NACIMIENTO',
  COMPROBANTE_DOMICILIO: 'COMPROBANTE_DOMICILIO',
  NSS: 'NSS',
  DATOS_BANCARIOS: 'DATOS_BANCARIOS',
  FACTURA: 'FACTURA / PAGO',
  CONSTANCIA_SITUACION_FISCAL: 'CONSTANCIA_SITUACION_FISCAL',
  GENERICO: 'GENÉRICO',
  UNKNOWN: 'UNKNOWN'
};

export function getDocumentTypeLabel(type: DocumentType | string | null | undefined): string {
  if (!type) {
    return 'UNKNOWN';
  }
  return DOCUMENT_TYPE_LABELS[type as DocumentType] ?? String(type);
}

export interface ExtractedTable {
  columns: string[];
  rows: Array<Record<string, string | null>>;
  quality: number;
  row_count: number;
  doc_type_hint?: string | null;
}

export interface DocumentField {
  key: string;
  label: string;
  value: string | null;
  confidence: number;
  valid: boolean;
  validation_errors: string[];
  source?: {
    page: number;
    bbox: [number, number, number, number];
  };
  corrected?: boolean;
  corrected_value?: string | null;
}

export interface DocumentSummary {
  id: string;
  original_filename: string;
  status: DocumentStatus;
  document_type: DocumentType;
  confidence: number | null;
  uploaded_at: string;
  processed_at?: string | null;
}

export interface DocumentDetail extends DocumentSummary {
  fields: DocumentField[];
  tables: ExtractedTable[];
  file_url: string;
  mime_type?: string | null;
  needs_review: boolean;
}

export interface DocumentProcessResponse {
  document_id: string;
  status: DocumentStatus;
  document_type: DocumentType;
  confidence: number;
  fields: DocumentField[];
  tables: ExtractedTable[];
  warnings: string[];
  errors: string[];
  meta: {
    pages_processed: number;
    ocr_engine: string;
    pipeline_version: string;
    model_version: string;
    processing_ms: number;
    tables_found?: number;
  };
}

export interface ProcessingLog {
  id: string;
  document_id: string;
  stage: string;
  level: string;
  message: string;
  created_at: string;
}

export interface LoginResponse {
  token: string;
  refresh_token?: string;
  refreshToken?: string;
  username: string;
  role: string;
  expires_at?: string;
  expiresAt?: string;
}
