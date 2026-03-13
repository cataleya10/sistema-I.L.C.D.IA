import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component } from '@angular/core';
import { DocumentoService } from '../../../services/documento.service';
import { ResultadoDocumento } from '../interfaces/documento-resultado.interface';
import { DocumentosHistorialService } from '../../../core/services/documentos-historial.service';

@Component({
  selector: 'app-subir-documento',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './subir-documento.component.html',
  styleUrls: ['./subir-documento.component.css']
})
export class SubirDocumentoComponent {
  archivoSeleccionado: File | null = null;
  tipoDocumento = 'FACTURA';
  resultado: ResultadoDocumento | null = null;
  cargando = false;
  mensaje = '';
  error = '';

  constructor(
    private readonly documentoService: DocumentoService,
    private readonly historial: DocumentosHistorialService
  ) {}

  seleccionarArchivo(event: Event): void {
    const input = event.target as HTMLInputElement;

    if (input.files && input.files.length > 0) {
      this.archivoSeleccionado = input.files[0];
      this.resultado = null;
      this.mensaje = '';
      this.error = '';
    }
  }

  procesar(): void {
    if (!this.archivoSeleccionado) {
      alert('Selecciona un PDF');
      return;
    }

    this.cargando = true;
    this.resultado = null;
    this.mensaje = '';
    this.error = '';

    this.documentoService
      .procesarDocumento(this.archivoSeleccionado, this.tipoDocumento)
      .subscribe({
        next: (res) => {
          console.log('RESPUESTA API JSON:', JSON.stringify(res, null, 2));
          console.log('BENEFICIARIO EN CARGA:', res.beneficiarios?.[0]);

          this.resultado = res;

          this.historial.limpiarHistorial();
          this.historial.agregarDocumento({
            tipo: res.tipoDocumento,
            archivo: this.archivoSeleccionado?.name,
            importe: res.resumen?.importeTotal,
            fecha: new Date(),
            datos: res
          });

          this.mensaje = res.message || 'Documento procesado correctamente';
          this.cargando = false;
        },
        error: (err: HttpErrorResponse) => {
          console.error('ERROR API:', err);
          this.error = this.obtenerMensajeError(err);
          this.cargando = false;
        }
      });
  }

  obtenerImporteTotalNumerico(): number {
    if (!this.resultado?.resumen?.importeTotal) {
      return 0;
    }

    return this.convertirImporteANumero(this.resultado.resumen.importeTotal);
  }

  obtenerSumaBeneficiarios(): number {
    if (!this.resultado?.beneficiarios?.length) {
      return 0;
    }

    return this.resultado.beneficiarios.reduce((total, beneficiario) => {
      return total + this.convertirImporteANumero(beneficiario.importe || '0');
    }, 0);
  }

  laValidacionEsCorrecta(): boolean {
    const importeTotal = this.obtenerImporteTotalNumerico();
    const sumaBeneficiarios = this.obtenerSumaBeneficiarios();

    return Math.abs(importeTotal - sumaBeneficiarios) < 0.01;
  }

  formatearMoneda(valor: number): string {
    return valor.toLocaleString('es-MX', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }

  private convertirImporteANumero(valor: string): number {
    if (!valor) {
      return 0;
    }

    const limpio = valor
      .replace(/\$/g, '')
      .replace(/,/g, '')
      .trim();

    const numero = parseFloat(limpio);

    return isNaN(numero) ? 0 : numero;
  }

  private obtenerMensajeError(error: HttpErrorResponse): string {
    const url = error.url ? ` URL: ${error.url}` : '';

    if (error.status === 0) {
      return `No se pudo conectar al servidor.${url} ${error.message}`.trim();
    }

    const payload = error.error as { detail?: string; message?: string; error?: string } | string | null;
    if (typeof payload === 'string' && payload.trim().length > 0) {
      return payload;
    }

    if (payload && typeof payload === 'object') {
      const detail = payload.detail ?? payload.message ?? payload.error;
      if (detail) {
        return `${detail}${url}`.trim();
      }
    }

    return `Error ${error.status}.${url} ${error.message}`.trim();
  }
}
