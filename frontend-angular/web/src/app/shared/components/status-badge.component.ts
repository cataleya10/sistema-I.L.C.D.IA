import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';
import { DocumentStatus } from '../models/document.models';

@Component({
  selector: 'app-status-badge',
  standalone: true,
  imports: [CommonModule],
  template: `
    <span class="badge" [ngClass]="statusClass">{{ statusLabel }}</span>
  `,
  styles: [
    `
      .badge {
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0.3px;
      }
      .uploaded {
        background: #e0f2fe;
        color: #0369a1;
      }
      .processing {
        background: #ede9fe;
        color: #5b21b6;
      }
      .ready {
        background: #dcfce7;
        color: #15803d;
      }
      .needs_review {
        background: #fef9c3;
        color: #a16207;
      }
      .failed {
        background: #fee2e2;
        color: #b91c1c;
      }
    `
  ]
})
export class StatusBadgeComponent {
  @Input() status: DocumentStatus = 'UPLOADED';

  get statusClass(): string {
    return this.status.toLowerCase();
  }

  get statusLabel(): string {
    switch (this.status) {
      case 'UPLOADED':
        return 'CARGADO';
      case 'PROCESSING':
        return 'PROCESANDO';
      case 'READY':
        return 'LISTO';
      case 'NEEDS_REVIEW':
        return 'REVISAR';
      case 'FAILED':
        return 'FALLÓ';
      default:
        return this.status;
    }
  }
}
