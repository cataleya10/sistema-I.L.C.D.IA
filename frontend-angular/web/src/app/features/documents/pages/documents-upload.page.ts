import { Component } from '@angular/core';
import { DropzoneComponent } from '../../../shared/components/dropzone.component';
import { DocumentsService } from '../services/documents.service';
import { HttpErrorResponse } from '@angular/common/http';
import { ToastNotificationComponent } from '../../../shared/components/toast-notification.component';

@Component({
  selector: 'app-documents-upload-page',
  standalone: true,
  imports: [DropzoneComponent, ToastNotificationComponent],
  template: `
    <section class="page">
      <header>
        <h2>Carga de documentos</h2>
        <p>Sube un documento para procesarlo automaticamente.</p>
      </header>

      <div class="helper">
        <span>Tipos permitidos: PDF, PNG, JPG.</span>
        <span>Tamano maximo: 15 MB.</span>
      </div>

      <div class="loading" *ngIf="isUploading">Subiendo documento...</div>
      <app-dropzone (fileDropped)="handleFile($event)" />

      <div class="file-info" *ngIf="lastFileName">
        <strong>Archivo:</strong> {{ lastFileName }}
        <span>{{ lastFileSize }}</span>
      </div>

      <app-toast-notification [message]="message" (dismiss)="message = null" />
    </section>
  `,
  styles: [
    `
      .page {
        display: grid;
        gap: 20px;
        max-width: 640px;
      }
      .helper {
        display: grid;
        gap: 4px;
        font-size: 12px;
        color: #6b7280;
      }
      .loading {
        font-size: 13px;
        color: #6b7280;
      }
      .file-info {
        display: grid;
        gap: 4px;
        font-size: 12px;
        color: #374151;
      }
      .file-info strong {
        font-weight: 600;
      }
    `
  ]
})
export class DocumentsUploadPage {
  message: string | null = null;
  isUploading = false;
  lastFileName: string | null = null;
  lastFileSize = '';

  private readonly maxFileSizeBytes = 15728640;
  private readonly allowedContentTypes = new Set(['application/pdf', 'image/png', 'image/jpeg']);
  private readonly allowedExtensions = new Set(['.pdf', '.png', '.jpg', '.jpeg']);

  constructor(private readonly documents: DocumentsService) {}

  handleFile(file: File): void {
    this.message = null;
    if (!file || this.isUploading) {
      return;
    }

    if (!this.isAllowedType(file)) {
      this.message = 'Tipo de archivo no permitido. Usa PDF o imagen JPG/PNG.';
      return;
    }

    if (file.size > this.maxFileSizeBytes) {
      this.message = 'El archivo excede el maximo permitido (15 MB).';
      return;
    }

    this.lastFileName = file.name;
    this.lastFileSize = this.formatBytes(file.size);
    this.isUploading = true;

    this.documents.upload(file).subscribe({
      next: () => {
        this.message = 'Documento cargado correctamente.';
        this.isUploading = false;
      },
      error: (error: HttpErrorResponse) => {
        const detail = typeof error.error === 'string' ? error.error : error.message;
        this.message = `Error al cargar el documento. ${detail}`;
        this.isUploading = false;
      }
    });
  }

  private isAllowedType(file: File): boolean {
    if (this.allowedContentTypes.has(file.type)) {
      return true;
    }
    const name = file.name.toLowerCase();
    return Array.from(this.allowedExtensions).some((ext) => name.endsWith(ext));
  }

  private formatBytes(bytes: number): string {
    if (bytes < 1024) {
      return `${bytes} B`;
    }
    const kb = bytes / 1024;
    if (kb < 1024) {
      return `${kb.toFixed(1)} KB`;
    }
    const mb = kb / 1024;
    return `${mb.toFixed(2)} MB`;
  }
}
