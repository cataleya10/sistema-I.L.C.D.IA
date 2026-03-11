import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component } from '@angular/core';
import { ResultadoDocumento } from '../interfaces/documento-resultado.interface';
import { DocumentoService } from '../services/documento.service';

@Component({
  selector: 'app-subir-documento',
  standalone: true,
  templateUrl: './subir-documento.component.html',
  styleUrls: ['./subir-documento.component.css'],
  imports: [CommonModule],
  providers: [DocumentoService]
})
export class SubirDocumentoComponent {
  archivoSeleccionado: File | null = null;
  tipoDocumento = 'FACTURA';
  resultado: ResultadoDocumento | null = null;
  cargando = false;
  error = '';

  constructor(private readonly documentoService: DocumentoService) {}

  seleccionarArchivo(event: Event): void {
    const input = event.target as HTMLInputElement | null;
    this.archivoSeleccionado = input?.files?.[0] ?? null;
  }

  procesar(): void {
    if (!this.archivoSeleccionado) {
      alert('Selecciona un PDF');
      return;
    }

    this.cargando = true;
    this.error = '';
    this.resultado = null;
    this.documentoService.procesarDocumento(this.archivoSeleccionado, this.tipoDocumento).subscribe({
      next: (res) => {
        this.resultado = res;
        this.cargando = false;
      },
      error: (error: HttpErrorResponse) => {
        this.error = this.resolveError(error);
        this.cargando = false;
      }
    });
  }

  private resolveError(error: HttpErrorResponse): string {
    if (error.status === 0) {
      return 'No se pudo conectar con el backend.';
    }

    const payload = error.error as { detail?: string; message?: string; error?: string } | string | null;
    if (typeof payload === 'string' && payload.trim().length) {
      return payload;
    }

    if (payload && typeof payload === 'object') {
      return payload.detail ?? payload.message ?? payload.error ?? 'El procesamiento no se pudo completar.';
    }

    return 'El procesamiento no se pudo completar.';
  }
}
