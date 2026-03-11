import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, of, timer } from 'rxjs';
import { filter, map, switchMap, take, timeout } from 'rxjs/operators';
import { getApiBaseUrl } from '../core/config/runtime-config';
import { ResultadoDocumento } from '../features/documents/interfaces/documento-resultado.interface';
import { DocumentProcessResponse, DocumentSummary } from '../shared/models/document.models';

@Injectable({
  providedIn: 'root'
})
export class DocumentoService {
  private readonly apiUrl = `${getApiBaseUrl()}/api/documents`;

  constructor(private readonly http: HttpClient) {}

  procesarDocumento(archivo: File, tipoDocumento: string): Observable<ResultadoDocumento> {
    const formData = new FormData();
    formData.append('file', archivo);

    return this.http.post<DocumentSummary>(`${this.apiUrl}/upload`, formData).pipe(
      switchMap((uploaded) =>
        this.http
          .post<DocumentProcessResponse>(`${this.apiUrl}/${uploaded.id}/process`, this.buildProcessOptions(tipoDocumento))
          .pipe(switchMap((response) => this.waitForResult(uploaded, response)))
      )
    );
  }

  private waitForResult(
    uploaded: DocumentSummary,
    response: DocumentProcessResponse
  ): Observable<ResultadoDocumento> {
    if (response.status !== 'PROCESSING') {
      return of(this.mapResult(uploaded, response));
    }

    return timer(2000, 2000).pipe(
      switchMap(() =>
        this.http.get<DocumentProcessResponse>(`${this.apiUrl}/${uploaded.id}/process/status`)
      ),
      filter((status) => status.status !== 'PROCESSING'),
      take(1),
      timeout({ first: 120000 }),
      map((status) => this.mapResult(uploaded, status))
    );
  }

  private buildProcessOptions(tipoDocumento: string): { forceDocumentType: 'FACTURA' } | {} {
    return tipoDocumento.toUpperCase() === 'FACTURA' ? { forceDocumentType: 'FACTURA' } : {};
  }

  private mapResult(uploaded: DocumentSummary, response: DocumentProcessResponse): ResultadoDocumento {
    return {
      exito: response.status === 'READY' || response.status === 'NEEDS_REVIEW',
      mensaje: this.buildMessage(response),
      tipo: response.document_type,
      nombreArchivo: uploaded.original_filename,
      estado: response.status,
      documentId: response.document_id
    };
  }

  private buildMessage(response: DocumentProcessResponse): string {
    if (response.status === 'READY') {
      return 'Documento procesado correctamente.';
    }

    if (response.status === 'NEEDS_REVIEW') {
      return 'Documento procesado, pero requiere revision.';
    }

    if (response.status === 'FAILED') {
      return response.errors[0] ?? 'El procesamiento del documento fallo.';
    }

    return 'Documento enviado a procesamiento.';
  }
}
