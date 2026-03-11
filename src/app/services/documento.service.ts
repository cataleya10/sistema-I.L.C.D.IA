import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { ResultadoDocumento } from '../interfaces/documento-resultado.interface';

@Injectable({
  providedIn: 'root'
})
export class DocumentoService {
  private readonly apiUrl = 'https://localhost:53285/api/Documento';

  constructor(private readonly http: HttpClient) {}

  procesarDocumento(archivo: File, tipoDocumento: string): Observable<ResultadoDocumento> {
    const formData = new FormData();
    formData.append('Archivo', archivo);
    formData.append('TipoDocumento', tipoDocumento);

    return this.http.post<ResultadoDocumento>(`${this.apiUrl}/procesar`, formData);
  }
}
