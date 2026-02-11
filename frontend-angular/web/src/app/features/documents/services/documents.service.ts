import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { environment } from '../../../../environments/environment';
import { DocumentDetail, DocumentProcessResponse, DocumentSummary, ProcessingLog } from '../../../shared/models/document.models';

export interface DocumentListQuery {
  status?: string;
  type?: string;
  q?: string;
  from?: string;
  to?: string;
  page?: number;
  pageSize?: number;
}

@Injectable({ providedIn: 'root' })
export class DocumentsService {
  private readonly baseUrl = `${environment.apiUrl}/api/documents`;

  constructor(private readonly http: HttpClient) {}

  upload(file: File) {
    const formData = new FormData();
    formData.append('file', file);
    return this.http.post<DocumentSummary>(`${this.baseUrl}/upload`, formData);
  }

  list(query: DocumentListQuery) {
    let params = new HttpParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        params = params.set(key, String(value));
      }
    });
    return this.http.get<DocumentSummary[]>(this.baseUrl, { params });
  }

  getById(id: string) {
    return this.http.get<DocumentDetail>(`${this.baseUrl}/${id}`);
  }

  getFileUrl(id: string) {
    return `${this.baseUrl}/${id}/file`;
  }

  downloadFile(id: string) {
    return this.http.get(`${this.baseUrl}/${id}/file`, { responseType: 'blob' });
  }

  process(id: string) {
    return this.http.post<DocumentProcessResponse>(`${this.baseUrl}/${id}/process`, {});
  }

  getProcessStatus(id: string) {
    return this.http.get<DocumentProcessResponse>(`${this.baseUrl}/${id}/process/status`);
  }

  reprocess(id: string) {
    return this.http.post<DocumentProcessResponse>(`${this.baseUrl}/${id}/reprocess`, {});
  }

  updateFields(id: string, fields: { key: string; value: string }[]) {
    return this.http.put(`${this.baseUrl}/${id}/fields`, { fields });
  }

  getLogs(id: string) {
    return this.http.get<ProcessingLog[]>(`${this.baseUrl}/${id}/logs`);
  }

  delete(id: string) {
    return this.http.delete(`${this.baseUrl}/${id}`);
  }

  downloadWord(id: string) {
    return this.http.get(`${this.baseUrl}/${id}/export/word`, { responseType: 'blob' });
  }

  downloadExcel(id: string) {
    return this.http.get(`${this.baseUrl}/${id}/export/excel`, { responseType: 'blob' });
  }
}
