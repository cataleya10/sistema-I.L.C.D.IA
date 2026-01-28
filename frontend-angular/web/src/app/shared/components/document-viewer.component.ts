import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-document-viewer',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="viewer">
      <ng-container *ngIf="fileUrl; else empty">
        <iframe *ngIf="isPdf" [src]="fileUrl" title="Documento PDF"></iframe>
        <img *ngIf="!isPdf" [src]="fileUrl" alt="Documento" />
      </ng-container>
      <ng-template #empty>
        <p>Sin documento seleccionado.</p>
      </ng-template>
    </div>
  `,
  styles: [
    `
      .viewer {
        border-radius: 12px;
        border: 1px solid #e5e7eb;
        background: #fff;
        padding: 12px;
      }
      iframe,
      img {
        width: 100%;
        height: 520px;
        border: none;
        border-radius: 8px;
        object-fit: contain;
      }
    `
  ]
})
export class DocumentViewerComponent {
  @Input() fileUrl: string | null = null;
  @Input() mimeType: string | null = null;

  get isPdf(): boolean {
    return (this.mimeType ?? '').includes('pdf');
  }
}
