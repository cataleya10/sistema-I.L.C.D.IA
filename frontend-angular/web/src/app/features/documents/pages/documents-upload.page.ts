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
        <p>Sube un documento para procesarlo automáticamente.</p>
      </header>
      <app-dropzone (fileDropped)="handleFile($event)" />
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
    `
  ]
})
export class DocumentsUploadPage {
  message: string | null = null;

  constructor(private readonly documents: DocumentsService) {}

  handleFile(file: File): void {
    this.documents.upload(file).subscribe({
      next: () => (this.message = 'Documento cargado correctamente.'),
      error: (error: HttpErrorResponse) => {
        const detail = typeof error.error === 'string' ? error.error : error.message;
        this.message = `Error al cargar el documento. ${detail}`;
      }
    });
  }
}
