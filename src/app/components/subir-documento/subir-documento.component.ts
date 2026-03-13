import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { DocumentoService } from '../../services/documento.service';
import { ResultadoDocumento } from '../../interfaces/documento-resultado.interface';

@Component({
  selector: 'app-carga-documento-legacy',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './subir-documento.component.html',
  styleUrls: ['./subir-documento.component.css']
})
export class SubirDocumentoLegacyComponent {
  archivoSeleccionado: File | null = null;
  tipoDocumento = 'FACTURA';
  resultado: ResultadoDocumento | null = null;
  cargando = false;

  constructor(private documentoService: DocumentoService) {}

  seleccionarArchivo(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      this.archivoSeleccionado = input.files[0];
    }
  }

  procesar(): void {
    if (!this.archivoSeleccionado) {
      alert('Selecciona un PDF');
      return;
    }

    this.cargando = true;
    this.resultado = null;

    this.documentoService
      .procesarDocumento(this.archivoSeleccionado, this.tipoDocumento)
      .subscribe({
        next: (res) => {
          console.log('RESPUESTA API:', res);
          this.resultado = res;
          this.cargando = false;
        },
        error: (err) => {
          console.error('ERROR API:', err);
          this.cargando = false;
          alert('Error al procesar el documento');
        }
      });
  }
}
