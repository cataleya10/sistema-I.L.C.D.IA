import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { getApiBaseUrl } from '../config/runtime-config';

export interface SystemInfo {
  service_name: string;
  pipeline_version: string;
  model_version: string;
  timestamp: string;
}

export interface SystemMetrics {
  requests: number;
  errors: number;
  timestamp: string;
}

export interface AuditFolderRequest {
  folder_path: string;
  recurse: boolean;
  limit: number;
  issues_only: boolean;
}

export interface AuditDocumentSummary {
  name: string;
  file_path: string;
  status: string;
  document_type: string | null;
  confidence: number | null;
  tabla_rows: number;
  detalle_rows: number;
  warning_count: number;
  warnings: string[];
  hard_fail: boolean;
  mapped_fields: Record<string, string>;
  error: string | null;
}

export interface AuditFolderResponse {
  folder_path: string;
  recurse: boolean;
  limit: number;
  issues_only: boolean;
  matched_files: number;
  processed_files: number;
  documents_returned: number;
  clean_count: number;
  issue_count: number;
  error_count: number;
  hard_fail_count: number;
  non_factura_count: number;
  document_type_counts: Record<string, number>;
  documents: AuditDocumentSummary[];
}

@Injectable({ providedIn: 'root' })
export class SystemService {
  private readonly systemBaseUrl = `${getApiBaseUrl()}/api/system`;
  private readonly documentsBaseUrl = `${getApiBaseUrl()}/api/documents`;

  constructor(private readonly http: HttpClient) {}

  getInfo() {
    return this.http.get<SystemInfo>(`${this.systemBaseUrl}/info`);
  }

  getMetrics() {
    return this.http.get<SystemMetrics>(`${this.systemBaseUrl}/metrics`);
  }

  auditFolder(payload: AuditFolderRequest) {
    return this.http.post<AuditFolderResponse>(`${this.documentsBaseUrl}/diagnostics/audit-folder`, payload);
  }
}
