import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { DocumentViewerComponent } from '../../../shared/components/document-viewer.component';
import { FieldEditorComponent } from '../../../shared/components/field-editor.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge.component';
import { ConfidenceIndicatorComponent } from '../../../shared/components/confidence-indicator.component';
import { DocumentsService } from '../services/documents.service';
import { DocumentDetail, ProcessingLog } from '../../../shared/models/document.models';
import { ToastNotificationComponent } from '../../../shared/components/toast-notification.component';

@Component({
  selector: 'app-documents-detail-page',
  standalone: true,
  imports: [
    CommonModule,
    DocumentViewerComponent,
    FieldEditorComponent,
    StatusBadgeComponent,
    ConfidenceIndicatorComponent,
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
        <button type="button" class="ghost" (click)="saveEdits()">Guardar correcciones</button>
      </div>

      <div class="grid">
        <app-document-viewer [fileUrl]="document.file_url" [mimeType]="document.mime_type ?? null"></app-document-viewer>
        <div class="fields">
          <h3>Campos extraídos</h3>
          <p class="review" *ngIf="document.needs_review">Revisión requerida por baja confianza o validación.</p>
          <div class="field" *ngFor="let field of document.fields">
            <app-field-editor
              [label]="field.label"
              [value]="field.corrected_value ?? field.value"
              [valid]="field.valid"
              [errors]="field.validation_errors"
              (valueChange)="field.corrected_value = $event"
            />
            <app-confidence-indicator [value]="field.confidence" />
          </div>
          <p class="empty" *ngIf="!document.fields.length">No se detectaron campos todavía.</p>
        </div>
      </div>

      <div class="logs">
        <h3>Logs de procesamiento</h3>
        <div class="log" *ngFor="let log of logs">
          <span class="tag">{{ log.stage }}</span>
          <span class="level">{{ log.level }}</span>
          <span class="message">{{ log.message }}</span>
          <span class="date">{{ log.created_at | date: 'short' }}</span>
        </div>
        <p class="empty" *ngIf="!logs.length">Sin logs aún.</p>
      </div>
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
      .field {
        display: grid;
        gap: 6px;
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
    `
  ]
})
export class DocumentsDetailPage implements OnInit {
  document: DocumentDetail | null = null;
  logs: ProcessingLog[] = [];
  message: string | null = null;

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

  saveEdits(): void {
    if (!this.document) {
      return;
    }
    const payload = this.document.fields
      .filter((field) => field.corrected_value !== undefined)
      .map((field) => ({ key: field.key, value: field.corrected_value ?? '' }));

    this.documents.updateFields(this.document.id, payload).subscribe({
      next: () => (this.message = 'Correcciones guardadas.'),
      error: () => (this.message = 'No se pudieron guardar las correcciones.')
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
      next: (data) => (this.logs = data),
      error: () => (this.logs = [])
    });
  }
}
