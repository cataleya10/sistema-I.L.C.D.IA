import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { DocumentViewerComponent } from '../../../shared/components/document-viewer.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge.component';
import { DocumentsService } from '../services/documents.service';
import { DocumentDetail, ProcessingLog } from '../../../shared/models/document.models';
import { ToastNotificationComponent } from '../../../shared/components/toast-notification.component';
import { DOCUMENT_FIELD_TEMPLATES } from '../field-templates';

@Component({
  selector: 'app-documents-detail-page',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    DocumentViewerComponent,
    StatusBadgeComponent,
    RouterLink,
    ToastNotificationComponent
  ],
  template: `
    <section class="page" *ngIf="document; else loading">
      <header>
        <div>
          <h2>{{ document.original_filename }}</h2>
          <p>{{ document.document_type }} - Confianza {{ document.confidence ?? 0 | percent: '1.0-0' }}</p>
        </div>
        <app-status-badge [status]="document.status" />
      </header>

      <div class="actions">
        <button type="button" (click)="process()" [disabled]="isProcessing">Procesar</button>
        <button type="button" class="ghost" (click)="reprocess()" [disabled]="isProcessing">Reprocesar</button>
        <button type="button" class="ghost" (click)="toggleEdit()" [disabled]="isSaving">
          {{ editMode ? 'Cancelar edicion' : 'Editar campos' }}
        </button>
        <button type="button" class="ghost" *ngIf="editMode" (click)="saveEdits()" [disabled]="isSaving">
          Guardar cambios
        </button>
        <button type="button" class="ghost" (click)="downloadWord()" [disabled]="!document">Descargar Word</button>
        <button type="button" class="ghost" (click)="downloadExcel()" [disabled]="!document">Descargar Excel</button>
        <button type="button" class="ghost" (click)="copyFields()" [disabled]="!document">Copiar campos</button>
        <a class="ghost" [routerLink]="['/documents', document.id, 'results']">Ver resultados</a>
      </div>

      <div class="grid">
        <app-document-viewer [fileUrl]="document.file_url" [mimeType]="document.mime_type ?? null"></app-document-viewer>
        <div class="fields">
          <h3>Resultados extraidos</h3>
          <p class="review" *ngIf="document.needs_review">Revision requerida por baja confianza o validacion.</p>
          <table class="results" *ngIf="displayFields.length">
            <thead>
              <tr>
                <th>Campo</th>
                <th>Valor</th>
                <th>Validez</th>
              </tr>
            </thead>
            <tbody>
              <tr *ngFor="let field of displayFields">
                <td>{{ field.label }}</td>
                <td>
                  <ng-container *ngIf="!editMode; else editField">
                    {{ field.corrected_value ?? field.value ?? '-' }}
                  </ng-container>
                  <ng-template #editField>
                    <input
                      class="field-input"
                      type="text"
                      [name]="field.key"
                      [(ngModel)]="editedValues[field.key]"
                    />
                  </ng-template>
                </td>
                <td>
                  <span class="badge" [ngClass]="field.valid ? 'ok' : 'warn'">
                    {{ field.valid ? 'OK' : 'Revisar' }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
          <p class="empty" *ngIf="!displayFields.length">No se detectaron campos todavia.</p>
        </div>
      </div>

      <details class="logs">
        <summary>Ver logs</summary>
        <p class="warning" *ngIf="hasWarnings">Se detectaron advertencias en el procesamiento.</p>
        <p class="warning" *ngIf="missingCritical.length">Campos criticos faltantes: {{ missingCritical.join(', ') }}</p>
        <div class="log" *ngFor="let log of logs">
          <span class="tag">{{ log.stage }}</span>
          <span class="level" [ngClass]="levelClass(log.level)">{{ log.level }}</span>
          <span class="message">{{ log.message }}</span>
          <span class="date">{{ log.created_at | date: 'short' }}</span>
        </div>
        <p class="empty" *ngIf="!logs.length">Sin logs aun.</p>
      </details>
    </section>

    <ng-template #loading>
      <section class="page">
        <p class="loading">Cargando documento...</p>
      </section>
    </ng-template>

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
        flex-wrap: wrap;
      }
      .actions button {
        padding: 8px 16px;
        border-radius: 999px;
        border: none;
        background: #4f46e5;
        color: #fff;
        position: relative;
        transition:
          transform 160ms cubic-bezier(0.21, 0.8, 0.25, 1),
          box-shadow 160ms cubic-bezier(0.21, 0.8, 0.25, 1),
          filter 160ms ease,
          background 160ms ease;
      }
      .actions button.ghost {
        background: #e5e7eb;
        color: #111827;
      }
      .actions .ghost {
        background: #e5e7eb;
        color: #111827;
      }
      .actions button:hover,
      .actions a:hover {
        transform: translateY(-2px) scale(1.01);
        box-shadow:
          0 10px 24px rgba(15, 23, 42, 0.18),
          0 2px 6px rgba(15, 23, 42, 0.12);
        filter: brightness(1.03);
      }
      .actions button:active,
      .actions a:active {
        transform: translateY(-1px) scale(0.995);
        box-shadow: 0 6px 14px rgba(15, 23, 42, 0.16);
      }
      .actions a {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        position: relative;
        transition:
          transform 160ms cubic-bezier(0.21, 0.8, 0.25, 1),
          box-shadow 160ms cubic-bezier(0.21, 0.8, 0.25, 1),
          filter 160ms ease,
          background 160ms ease;
      }
      .actions a::after,
      .actions button::after {
        content: '';
        position: absolute;
        inset: -2px;
        border-radius: 999px;
        border: 1px solid rgba(79, 70, 229, 0.25);
        opacity: 0;
        transform: scale(0.96);
        transition: opacity 160ms ease, transform 160ms ease;
        pointer-events: none;
      }
      .actions a:hover::after,
      .actions button:hover::after {
        opacity: 1;
        transform: scale(1);
      }
      .actions a.ghost::after,
      .actions button.ghost::after {
        border-color: rgba(15, 23, 42, 0.12);
      }
      .actions a:focus-visible,
      .actions button:focus-visible {
        outline: 2px solid rgba(79, 70, 229, 0.45);
        outline-offset: 2px;
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
      .field-input {
        width: 100%;
        padding: 6px 8px;
        border-radius: 8px;
        border: 1px solid #e5e7eb;
        font-size: 13px;
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
      .loading {
        font-size: 13px;
        color: #6b7280;
      }
    `
  ]
})
export class DocumentsDetailPage implements OnInit, OnDestroy {
  document: DocumentDetail | null = null;
  logs: ProcessingLog[] = [];
  message: string | null = null;
  hasWarnings = false;
  missingCritical: string[] = [];
  editMode = false;
  editedValues: Record<string, string> = {};
  isLoading = false;
  isProcessing = false;
  isSaving = false;
  isDownloading = false;
  displayFields: DocumentDetail['fields'] = [];
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private pollAttempts = 0;
  private readonly maxPollAttempts = 60;
  private pollInFlight = false;

  constructor(private readonly route: ActivatedRoute, private readonly documents: DocumentsService) {}

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.load(id);
      this.loadLogs(id);
    }
  }

  ngOnDestroy(): void {
    this.stopProcessingPoll();
  }

  process(): void {
    if (!this.document) {
      return;
    }
    this.isProcessing = true;
    this.documents.process(this.document.id).subscribe({
      next: () => {
        this.message = 'Procesamiento en cola.';
        this.load(this.document!.id);
        this.loadLogs(this.document!.id);
        this.startProcessingPoll(this.document!.id);
        this.isProcessing = false;
      },
      error: () => {
        this.message = 'No se pudo procesar el documento.';
        this.isProcessing = false;
      }
    });
  }

  reprocess(): void {
    if (!this.document) {
      return;
    }
    this.isProcessing = true;
    this.documents.reprocess(this.document.id).subscribe({
      next: () => {
        this.message = 'Reprocesamiento solicitado.';
        this.load(this.document!.id);
        this.loadLogs(this.document!.id);
        this.startProcessingPoll(this.document!.id);
        this.isProcessing = false;
      },
      error: () => {
        this.message = 'No se pudo reprocesar el documento.';
        this.isProcessing = false;
      }
    });
  }

  toggleEdit(): void {
    if (!this.document) {
      return;
    }
    this.editMode = !this.editMode;
    if (this.editMode) {
      this.editedValues = {};
      this.displayFields.forEach((field) => {
        const value = field.corrected_value ?? field.value ?? '';
        this.editedValues[field.key] = value?.toString() ?? '';
      });
    } else {
      this.editedValues = {};
    }
  }

  downloadWord(): void {
    if (!this.document || this.isDownloading) {
      return;
    }
    this.isDownloading = true;
    this.documents.downloadWord(this.document.id).subscribe({
      next: (blob) => {
        const baseName = (this.document?.original_filename || 'documento')
          .replace(/\.[^/.]+$/, '')
          .trim();
        const filename = baseName ? `${baseName}.doc` : 'documento.doc';
        const url = window.URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = filename;
        anchor.click();
        window.URL.revokeObjectURL(url);
        this.isDownloading = false;
      },
      error: () => {
        this.message = 'No se pudo descargar el Word.';
        this.isDownloading = false;
      }
    });
  }

  copyFields(): void {
    if (!this.document) {
      return;
    }
    const template =
      DOCUMENT_FIELD_TEMPLATES[this.document.document_type] ??
      this.document.fields.map((field) => ({ key: field.key, label: field.label }));
    const fieldMap = new Map(
      this.document.fields.map((field) => [field.key.toLowerCase(), field])
    );
    const lines = template.map((field) => {
      const value =
        fieldMap.get(field.key.toLowerCase())?.corrected_value ??
        fieldMap.get(field.key.toLowerCase())?.value ??
        '-';
      return `${field.label}: ${value}`;
    });
    const text = lines.join('\n');
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(
        () => {
          this.message = 'Campos copiados al portapapeles.';
        },
        () => {
          this.message = 'No se pudo copiar al portapapeles.';
        }
      );
    } else {
      this.message = 'El navegador no soporta copiado automatico.';
    }
  }

  saveEdits(): void {
    if (!this.document) {
      return;
    }
    const updates = this.displayFields
      .map((field) => {
        const current = (this.editedValues[field.key] ?? '').trim();
        const original = (field.corrected_value ?? field.value ?? '').toString();
        if (current === original) {
          return null;
        }
        return { key: field.key, value: current };
      })
      .filter((item): item is { key: string; value: string } => item !== null);

    if (!updates.length) {
      this.message = 'Sin cambios para guardar.';
      this.editMode = false;
      return;
    }

    this.isSaving = true;
    this.documents.updateFields(this.document.id, updates).subscribe({
      next: () => {
        this.message = 'Cambios guardados.';
        this.editMode = false;
        this.editedValues = {};
        this.load(this.document!.id);
        this.loadLogs(this.document!.id);
        this.isSaving = false;
      },
      error: () => {
        this.message = 'No se pudieron guardar los cambios.';
        this.isSaving = false;
      }
    });
  }

  private load(id: string): void {
    this.isLoading = true;
    this.documents.getById(id).subscribe({
      next: (data) => {
        this.document = {
          ...data,
          file_url: this.documents.getFileUrl(data.id)
        };
        this.displayFields = this.mapDisplayFields(this.document);
        if (this.document.status === 'PROCESSING') {
          this.startProcessingPoll(this.document.id);
        } else {
          this.stopProcessingPoll();
        }
        this.isLoading = false;
      },
      error: () => {
        this.stopProcessingPoll();
        this.message = 'No se pudo cargar el documento.';
        this.isLoading = false;
      }
    });
  }

  downloadExcel(): void {
    if (!this.document || this.isDownloading) {
      return;
    }
    this.isDownloading = true;
    this.documents.downloadExcel(this.document.id).subscribe({
      next: (blob) => {
        const baseName = (this.document?.original_filename || 'documento')
          .replace(/\.[^/.]+$/, '')
          .trim();
        const filename = baseName ? `${baseName}.xlsx` : 'documento.xlsx';
        const url = window.URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = filename;
        anchor.click();
        window.URL.revokeObjectURL(url);
        this.isDownloading = false;
      },
      error: () => {
        this.message = 'No se pudo descargar el Excel.';
        this.isDownloading = false;
      }
    });
  }

  private mapDisplayFields(document: DocumentDetail): DocumentDetail['fields'] {
    const template = DOCUMENT_FIELD_TEMPLATES[document.document_type];
    if (!template) {
      return document.fields;
    }
    const fieldMap = new Map(
      document.fields.map((field) => [field.key.toLowerCase(), field])
    );
    const mappedFromTemplate = template.map((field) => {
        const resolved = fieldMap.get(field.key.toLowerCase());
        return {
          key: field.key,
          label: field.label,
          value: resolved?.value ?? null,
          confidence: resolved?.confidence ?? 0,
          corrected_value: resolved?.corrected_value ?? null,
          valid: resolved?.valid ?? true,
          validation_errors: resolved?.validation_errors ?? [],
          source: resolved?.source,
          corrected: resolved?.corrected ?? false
        };
      });

    const templateKeys = new Set(template.map((field) => field.key.toLowerCase()));
    const extras = document.fields.filter((field) => !templateKeys.has(field.key.toLowerCase()));
    return [...mappedFromTemplate, ...extras];
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

  private startProcessingPoll(id: string): void {
    this.stopProcessingPoll();
    this.pollAttempts = 0;
    this.pollTimer = setInterval(() => {
      if (this.pollInFlight) {
        return;
      }
      this.pollInFlight = true;
      this.pollAttempts += 1;
      this.documents.getProcessStatus(id).subscribe({
        next: (status) => {
          this.pollInFlight = false;
          if (status.status === 'READY' || status.status === 'NEEDS_REVIEW' || status.status === 'FAILED') {
            this.stopProcessingPoll();
            this.load(id);
            this.loadLogs(id);
            this.message = status.status === 'FAILED' ? 'El procesamiento terminó con error.' : 'Procesamiento completado.';
            return;
          }

          if (this.pollAttempts >= this.maxPollAttempts) {
            this.stopProcessingPoll();
            this.message = 'El procesamiento sigue en curso. Actualiza para consultar estado.';
          }
        },
        error: () => {
          this.pollInFlight = false;
          this.stopProcessingPoll();
        }
      });
    }, 2000);
  }

  private stopProcessingPoll(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
    this.pollInFlight = false;
  }

  private extractMissingCritical(logs: ProcessingLog[]): string[] {
    const prefix = 'Campos criticos faltantes:';
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

