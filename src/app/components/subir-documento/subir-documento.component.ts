import { CommonModule } from '@angular/common';
import { Component, Output, EventEmitter } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DocumentoService } from '../../services/documento.service';
import { AuthService } from '../../services/auth.service';
import { ResultadoDocumento } from '../../interfaces/documento-resultado.interface';

@Component({
  selector: 'app-carga-documento-legacy',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './subir-documento.component.html',
  styleUrls: ['./subir-documento.component.css']
})
export class SubirDocumentoLegacyComponent {
  // ── Auth ────────────────────────────────────────────────────────────────
  username = '';
  password = '';
  loginError = '';
  iniciandoSesion = false;

  // ── Carga ───────────────────────────────────────────────────────────────
  archivoSeleccionado: File | null = null;
  tipoDocumento = 'FACTURA';
  resultado: ResultadoDocumento | null = null;
  cargando = false;

  @Output() resultadoExtraido = new EventEmitter<ResultadoDocumento>();

  constructor(
    private readonly documentoService: DocumentoService,
    public readonly auth: AuthService
  ) {}

  // ── Métodos de autenticación ────────────────────────────────────────────

  iniciarSesion(): void {
    if (!this.username || !this.password) return;
    this.iniciandoSesion = true;
    this.loginError = '';

    this.auth.login(this.username, this.password).subscribe({
      next: () => {
        this.iniciandoSesion = false;
        this.username = '';
        this.password = '';
      },
      error: () => {
        this.iniciandoSesion = false;
        this.loginError = 'Usuario o contraseña incorrectos.';
      },
    });
  }

  cerrarSesion(): void {
    this.auth.logout();
    this.resultado = null;
  }

  // ── Métodos de carga ────────────────────────────────────────────────────

  seleccionarArchivo(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      this.archivoSeleccionado = input.files[0];
    }
  }

  procesar(): void {
    if (!this.archivoSeleccionado) {
      alert('Selecciona un PDF primero.');
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
          this.resultadoExtraido.emit(res);
        },
        error: (err) => {
          console.error('ERROR API:', err);
          this.cargando = false;
          const msg =
            err?.error?.detail ??
            err?.error?.message ??
            err?.message ??
            'Error al procesar el documento.';
          alert(msg);
        },
      });
  }
}

