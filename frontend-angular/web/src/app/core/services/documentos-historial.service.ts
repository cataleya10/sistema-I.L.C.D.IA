import { Injectable } from '@angular/core';

@Injectable({
  providedIn: 'root'
})
export class DocumentosHistorialService {
  private documentos: any[] = [];

  agregarDocumento(doc: any) {
    this.documentos.unshift(doc);
  }

  obtenerDocumentos() {
    return this.documentos;
  }

  limpiarHistorial() {
    this.documentos = [];
  }
}
