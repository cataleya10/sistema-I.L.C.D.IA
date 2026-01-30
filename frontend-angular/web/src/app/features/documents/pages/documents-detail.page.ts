import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { DocumentViewerComponent } from '../../../shared/components/document-viewer.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge.component';
import { DocumentsService } from '../services/documents.service';
import { DocumentDetail, ProcessingLog } from '../../../shared/models/document.models';
import { ToastNotificationComponent } from '../../../shared/components/toast-notification.component';

@Component({
  selector: 'app-documents-detail-page',
  standalone: true,
  imports: [
    CommonModule,
    DocumentViewerComponent,
    StatusBadgeComponent,
    RouterLink,
    ToastNotificationComponent
  ],
  template: `
    <section class="page" *ngIf="document">
      <header>
        <div>
          <h2>{{ document.original_filename }}</h2>
          <p>{{ document.document_type }} · Confianza {{ document.confidence ?? 0 | percent: '1.0-0' }}</p>
        </div>
        <app-status-badge [status]="document.status" />
      </header>

      <div class="actions">
        <button type="button" (click)="process()">Procesar</button>
        <button type="button" class="ghost" (click)="reprocess()">Reprocesar</button>
        <a class="ghost" [routerLink]="['/documents', document.id, 'results']">Ver resultados</a>
      </div>

      <div class="grid">
        <app-document-viewer [fileUrl]="document.file_url" [mimeType]="document.mime_type ?? null"></app-document-viewer>
        <div class="fields">
          <h3>Resultados extraídos</h3>
          <p class="review" *ngIf="document.needs_review">Revisión requerida por baja confianza o validación.</p>
          <table class="results" *ngIf="document.fields.length">
            <thead>
              <tr>
                <th>Campo</th>
                <th>Valor</th>
                <th>Validez</th>
              </tr>
            </thead>
            <tbody>
              <tr *ngFor="let field of document.fields">
                <td>{{ field.label }}</td>
                <td>{{ field.corrected_value ?? field.value ?? '-' }}</td>
                <td>
                  <span class="badge" [ngClass]="field.valid ? 'ok' : 'warn'">
                    {{ field.valid ? 'OK' : 'Revisar' }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
          <p class="empty" *ngIf="!document.fields.length">No se detectaron campos todavía.</p>
        </div>
      </div>

      <details class="logs">
        <summary>Ver logs</summary>
        <p class="warning" *ngIf="hasWarnings">Se detectaron advertencias en el procesamiento.</p>
        <p class="warning" *ngIf="missingCritical.length">Campos críticos faltantes: {{ missingCritical.join(', ') }}</p>
        <div class="log" *ngFor="let log of logs">
          <span class="tag">{{ log.stage }}</span>
          <span class="level" [ngClass]="levelClass(log.level)">{{ log.level }}</span>
          <span class="message">{{ log.message }}</span>
          <span class="date">{{ log.created_at | date: 'short' }}</span>
        </div>
        <p class="empty" *ngIf="!logs.length">Sin logs aún.</p>
      </details>
    </section>

    <app-toast-notification [message]="message" (dismiss)="message = null" />
  `,
  styles: [
    `
      .page {
        display: grid;
        gap: 20px;
      }
      header {
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
      .actions {
        display: flex;
        gap: 12px;
      }
      .actions button {
        padding: 8px 16px;
        border-radius: 999px;
        border: none;
        background: #4f46e5;
        color: #fff;
      }
      .actions button.ghost {
        background: #e5e7eb;
        color: #111827;
      }
      .actions .ghost {
        background: #e5e7eb;
        color: #111827;
      }
      .grid {
        display: grid;
        grid-template-columns: 1.2fr 1fr;
        gap: 20px;
      }
      .fields {
        background: #fff;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 16px;
        display: grid;
        gap: 12px;
      }
      .review {
        color: #b45309;
        font-size: 12px;
      }
      .warning {
        color: #b45309;
        font-size: 12px;
        margin: 0;
      }
      .field {
        display: grid;
        gap: 6px;
      }
      .results {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
      }
      .results th,
      .results td {
        padding: 8px 10px;
        border-bottom: 1px solid #e5e7eb;
        text-align: left;
        vertical-align: top;
      }
      .results th {
        font-size: 12px;
        color: #6b7280;
        font-weight: 600;
      }
      .badge {
        display: inline-flex;
        align-items: center;
        border-radius: 999px;
        padding: 2px 8px;
        font-size: 11px;
        font-weight: 600;
      }
      .badge.ok {
        background: #dcfce7;
        color: #166534;
      }
      .badge.warn {
        background: #fef3c7;
        color: #b45309;
      }
      .empty {
        font-size: 12px;
        color: #6b7280;
      }
      .logs {
        display: grid;
        gap: 8px;
        background: #fff;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 16px;
      }
      .logs summary {
        cursor: pointer;
        font-weight: 600;
      }
      .log {
        display: grid;
        grid-template-columns: 80px 80px 1fr 140px;
        gap: 12px;
        font-size: 12px;
        color: #374151;
      }
      .tag {
        font-weight: 600;
        color: #4f46e5;
      }
      .level {
        text-transform: uppercase;
        font-weight: 600;
      }
      .level.warn {
        color: #b45309;
      }
      .level.error {
        color: #b91c1c;
      }
    `
  ]
})
export class DocumentsDetailPage implements OnInit {
  document: DocumentDetail | null = null;
  logs: ProcessingLog[] = [];
  message: string | null = null;
  hasWarnings = false;
  missingCritical: string[] = [];

  constructor(private readonly route: ActivatedRoute, private readonly documents: DocumentsService) {}

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.load(id);
      this.loadLogs(id);
    }
  }

  process(): void {
    if (!this.document) {
      return;
    }
    this.documents.process(this.document.id).subscribe({
      next: () => {
        this.message = 'Procesamiento iniciado.';
        this.load(this.document!.id);
      },
      error: () => (this.message = 'No se pudo procesar el documento.')
    });
  }

  reprocess(): void {
    if (!this.document) {
      return;
    }
    this.documents.reprocess(this.document.id).subscribe({
      next: () => {
        this.message = 'Reprocesamiento iniciado.';
        this.load(this.document!.id);
      },
      error: () => (this.message = 'No se pudo reprocesar el documento.')
    });
  }

  private load(id: string): void {
    this.documents.getById(id).subscribe({
      next: (data) => {
        this.document = {
          ...data,
          file_url: this.documents.getFileUrl(data.id)
        };
      },
      error: () => (this.message = 'No se pudo cargar el documento.')
    });
  }

  private loadLogs(id: string): void {
    this.documents.getLogs(id).subscribe({
      next: (data) => {
        this.logs = data;
        this.hasWarnings = data.some((log) => log.level.toLowerCase() === 'warn');
        this.missingCritical = this.extractMissingCritical(data);
      },
      error: () => {
        this.logs = [];
        this.hasWarnings = false;
        this.missingCritical = [];
      }
    });
  }

  private extractMissingCritical(logs: ProcessingLog[]): string[] {
    const prefix = 'Campos críticos faltantes:';
    const match = logs.find((log) => log.message.startsWith(prefix));
    if (!match) {
      return [];
    }
    return match.message
      .replace(prefix, '')
      .split(',')
      .map((value) => value.trim())
      .filter((value) => value.length > 0);
  }

  levelClass(level: string): string {
    const normalized = level.toLowerCase();
    if (normalized === 'warn' || normalized === 'warning') {
      return 'warn';
    }
    if (normalized === 'error') {
      return 'error';
    }
    return '';
  }
}
