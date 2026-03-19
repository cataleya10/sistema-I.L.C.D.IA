import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { SubirDocumentoComponent } from '../components/subir-documento.component';

@Component({
  selector: 'app-documents-upload-page',
  standalone: true,
  imports: [CommonModule, SubirDocumentoComponent],
  template: `
    <section class="page">
      <app-subir-documento></app-subir-documento>
    </section>
  `,
  styles: [`
    .page {
      width: min(100%, 720px);
      display: grid;
      gap: 18px;
    }
  `]
})
export class DocumentsUploadPage {}