import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../../core/services/auth.service';
import {
  AuditDocumentSummary,
  AuditFolderResponse,
  SystemMetrics,
  SystemService
} from '../../../core/services/system.service';

@Component({
  selector: 'app-system-metrics-page',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <section class="page">
      <header class="page__header">
        <div>
          <h2>Estado del sistema</h2>
          <p>Metricas basicas y auditoria de carpetas del motor IA.</p>
        </div>
      </header>

      <section class="panel">
        <div class="panel__header">
          <div>
            <h3>Metricas</h3>
            <p>Solicitudes y errores reportados por la API.</p>
          </div>
          <button type="button" class="ghost" (click)="load()" [disabled]="isLoading">
            {{ isLoading ? 'Actualizando...' : 'Actualizar metricas' }}
          </button>
        </div>

        <div class="loading" *ngIf="isLoading">Cargando metricas...</div>
        <div class="error" *ngIf="errorMessage && !isLoading" role="alert">
          <span>{{ errorMessage }}</span>
          <button type="button" (click)="load()">Reintentar</button>
        </div>

        <div class="cards" *ngIf="metrics && !isLoading; else emptyMetrics">
          <div class="card">
            <h4>Requests</h4>
            <strong>{{ metrics.requests }}</strong>
          </div>
          <div class="card">
            <h4>Errors</h4>
            <strong>{{ metrics.errors }}</strong>
          </div>
          <div class="card">
            <h4>Ultima actualizacion</h4>
            <span>{{ metrics.timestamp | date: 'short' }}</span>
          </div>
        </div>
        <ng-template #emptyMetrics>
          <p *ngIf="!isLoading && !errorMessage" class="empty">No hay metricas disponibles.</p>
        </ng-template>
      </section>

      <section class="panel audit-panel">
        <div class="panel__header">
          <div>
            <h3>Auditoria de carpeta</h3>
            <p>Ejecuta el diagnostico del lote desde la UI usando una ruta absoluta del servidor.</p>
          </div>
        </div>

        <div class="notice" *ngIf="!canAudit()">
          Esta herramienta solo esta disponible para usuarios con rol Admin.
        </div>

        <form class="audit-form" *ngIf="canAudit()" (ngSubmit)="runAudit()">
          <label class="field field--full">
            <span>Ruta de carpeta</span>
            <input
              type="text"
              name="folderPath"
              [(ngModel)]="auditFolderPath"
              (ngModelChange)="persistAuditDraft()"
              placeholder="C:\\Users\\100156643\\Documents\\COMPROBANTES DE PAGO - copia\\15-01-26"
            />
          </label>

          <label class="field">
            <span>Limite</span>
            <input
              type="number"
              name="limit"
              min="1"
              max="500"
              [(ngModel)]="auditLimit"
              (ngModelChange)="persistAuditDraft()"
            />
          </label>

          <label class="toggle">
            <input
              type="checkbox"
              name="recurse"
              [(ngModel)]="auditRecurse"
              (ngModelChange)="persistAuditDraft()"
            />
            <span>Incluir subcarpetas</span>
          </label>

          <label class="toggle">
            <input
              type="checkbox"
              name="issuesOnly"
              [(ngModel)]="auditIssuesOnly"
              (ngModelChange)="persistAuditDraft()"
            />
            <span>Solo devolver issues</span>
          </label>

          <div class="audit-actions">
            <button type="submit" [disabled]="isAuditLoading || !auditFolderPath.trim()">
              {{ isAuditLoading ? 'Auditando...' : 'Ejecutar auditoria' }}
            </button>
            <button type="button" class="ghost" (click)="clearAuditResult()" [disabled]="isAuditLoading">
              Limpiar resultado
            </button>
          </div>
        </form>

        <div class="loading" *ngIf="isAuditLoading">Ejecutando auditoria del lote...</div>
        <div class="error" *ngIf="auditErrorMessage && !isAuditLoading" role="alert">
          <span>{{ auditErrorMessage }}</span>
          <button type="button" (click)="runAudit()" *ngIf="canAudit()">Reintentar</button>
        </div>

        <div class="audit-result" *ngIf="auditResult && !isAuditLoading">
          <div class="audit-result__header">
            <div>
              <h4>Resultado del lote</h4>
              <p>{{ auditResult.folder_path }}</p>
            </div>
            <div class="badge-row">
              <span class="pill">{{ auditResult.documents_returned }} devueltos</span>
              <span class="pill" *ngIf="auditResult.issues_only">modo issues_only</span>
            </div>
          </div>

          <div class="cards cards--audit">
            <div class="card">
              <h4>Archivos encontrados</h4>
              <strong>{{ auditResult.matched_files }}</strong>
            </div>
            <div class="card">
              <h4>Procesados</h4>
              <strong>{{ auditResult.processed_files }}</strong>
            </div>
            <div class="card">
              <h4>Limpios</h4>
              <strong>{{ auditResult.clean_count }}</strong>
            </div>
            <div class="card">
              <h4>Issues</h4>
              <strong>{{ auditResult.issue_count }}</strong>
            </div>
            <div class="card">
              <h4>Hard fail</h4>
              <strong>{{ auditResult.hard_fail_count }}</strong>
            </div>
            <div class="card">
              <h4>No FACTURA</h4>
              <strong>{{ auditResult.non_factura_count }}</strong>
            </div>
          </div>

          <div class="type-counts" *ngIf="documentTypeCountEntries().length">
            <h4>Tipos detectados</h4>
            <div class="badge-row">
              <span class="pill" *ngFor="let entry of documentTypeCountEntries()">
                {{ entry.key }}: {{ entry.value }}
              </span>
            </div>
          </div>

          <div class="empty" *ngIf="auditResult.documents.length === 0">
            No se devolvieron documentos en la respuesta. El lote quedo limpio o el limite aplicado no trajo filas.
          </div>

          <div class="document-list" *ngIf="auditResult.documents.length">
            <article class="document-card" *ngFor="let document of auditResult.documents; trackBy: trackDocument">
              <div class="document-card__header">
                <div>
                  <h5>{{ document.name }}</h5>
                  <p>{{ document.file_path }}</p>
                </div>
                <div class="badge-row">
                  <span class="pill">{{ document.status }}</span>
                  <span class="pill" *ngIf="document.document_type">{{ document.document_type }}</span>
                  <span class="pill warn" *ngIf="document.hard_fail">hard_fail</span>
                </div>
              </div>

              <div class="document-card__meta">
                <span *ngIf="document.confidence !== null">Confianza: {{ document.confidence | number: '1.0-2' }}</span>
                <span>Tabla: {{ document.tabla_rows }}</span>
                <span>Detalle: {{ document.detalle_rows }}</span>
                <span>Warnings: {{ document.warning_count }}</span>
              </div>

              <p class="document-card__error" *ngIf="document.error">{{ document.error }}</p>

              <div class="document-card__section" *ngIf="document.warnings.length">
                <h6>Warnings</h6>
                <ul>
                  <li *ngFor="let warning of document.warnings">{{ warning }}</li>
                </ul>
              </div>

              <div class="document-card__section" *ngIf="mappedFieldEntries(document).length">
                <h6>Mapped fields</h6>
                <div class="mapped-fields">
                  <span class="field-chip" *ngFor="let entry of mappedFieldEntries(document)">
                    <strong>{{ entry.key }}:</strong> {{ entry.value }}
                  </span>
                </div>
              </div>
            </article>
          </div>
        </div>
      </section>
    </section>
  `,
  styles: [
    `
      .page {
        display: grid;
        gap: 24px;
      }
      .page__header h2 {
        margin: 0;
        font-size: 28px;
      }
      .page__header p {
        margin: 8px 0 0;
        color: #6b7280;
      }
      .panel {
        display: grid;
        gap: 18px;
        background: #fff;
        border: 1px solid #e5e7eb;
        border-radius: 20px;
        padding: 24px;
        box-shadow: 0 16px 40px rgba(15, 23, 42, 0.06);
      }
      .panel__header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 16px;
        flex-wrap: wrap;
      }
      .panel__header h3,
      .audit-result__header h4,
      .type-counts h4,
      .document-card__section h6 {
        margin: 0;
      }
      .panel__header p,
      .audit-result__header p {
        margin: 6px 0 0;
        color: #6b7280;
      }
      .cards {
        display: grid;
        gap: 16px;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      }
      .cards--audit .card strong {
        color: #0f766e;
      }
      .card {
        background: #f8fafc;
        border: 1px solid #e5e7eb;
        border-radius: 16px;
        padding: 16px;
        display: grid;
        gap: 8px;
      }
      .card h4 {
        margin: 0;
        font-size: 13px;
        color: #6b7280;
      }
      .card strong {
        font-size: 26px;
        line-height: 1;
      }
      .loading,
      .empty {
        font-size: 13px;
        color: #6b7280;
      }
      .notice,
      .error {
        display: flex;
        align-items: center;
        gap: 12px;
        flex-wrap: wrap;
        border-radius: 14px;
        padding: 12px 14px;
        font-size: 13px;
      }
      .notice {
        background: #eff6ff;
        border: 1px solid #bfdbfe;
        color: #1d4ed8;
      }
      .error {
        background: #fef2f2;
        border: 1px solid #fecaca;
        color: #b91c1c;
      }
      .audit-form {
        display: grid;
        gap: 16px;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        align-items: end;
      }
      .field {
        display: grid;
        gap: 8px;
      }
      .field--full {
        grid-column: 1 / -1;
      }
      .field span {
        font-size: 12px;
        font-weight: 600;
        color: #374151;
      }
      .field input {
        border: 1px solid #d1d5db;
        border-radius: 12px;
        padding: 12px 14px;
        font: inherit;
      }
      .toggle {
        display: flex;
        align-items: center;
        gap: 10px;
        min-height: 44px;
        color: #374151;
      }
      .audit-actions,
      .badge-row {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
      }
      button {
        border: none;
        border-radius: 999px;
        padding: 10px 16px;
        font: inherit;
        font-weight: 600;
        background: #0f766e;
        color: #fff;
        cursor: pointer;
      }
      button.ghost {
        background: #e5e7eb;
        color: #111827;
      }
      button:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }
      .audit-result {
        display: grid;
        gap: 20px;
      }
      .audit-result__header,
      .document-card__header {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 16px;
        flex-wrap: wrap;
      }
      .pill {
        display: inline-flex;
        align-items: center;
        border-radius: 999px;
        padding: 6px 10px;
        background: #ecfeff;
        border: 1px solid #bae6fd;
        color: #155e75;
        font-size: 12px;
        font-weight: 600;
      }
      .pill.warn {
        background: #fff7ed;
        border-color: #fed7aa;
        color: #c2410c;
      }
      .type-counts,
      .document-list {
        display: grid;
        gap: 12px;
      }
      .document-card {
        display: grid;
        gap: 14px;
        padding: 18px;
        border-radius: 16px;
        border: 1px solid #e5e7eb;
        background: #f8fafc;
      }
      .document-card h5 {
        margin: 0;
        font-size: 16px;
      }
      .document-card p {
        margin: 6px 0 0;
        color: #6b7280;
        word-break: break-word;
      }
      .document-card__meta {
        display: flex;
        gap: 12px;
        flex-wrap: wrap;
        color: #475569;
        font-size: 13px;
      }
      .document-card__error {
        color: #b91c1c;
        font-weight: 600;
      }
      .document-card__section ul {
        margin: 8px 0 0;
        padding-left: 18px;
      }
      .mapped-fields {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-top: 10px;
      }
      .field-chip {
        display: inline-flex;
        gap: 6px;
        border-radius: 999px;
        padding: 8px 12px;
        background: #fff;
        border: 1px solid #dbeafe;
        color: #1e3a8a;
        font-size: 12px;
      }
      @media (max-width: 960px) {
        .page__header h2 {
          font-size: 24px;
        }
        .panel {
          padding: 18px;
        }
        .audit-form {
          grid-template-columns: 1fr;
        }
      }
    `
  ]
})
export class SystemMetricsPage implements OnInit {
  private static readonly AUDIT_DRAFT_STORAGE_KEY = 'system.audit.folder.v1';

  metrics: SystemMetrics | null = null;
  isLoading = false;
  errorMessage = '';

  auditFolderPath = '';
  auditRecurse = true;
  auditLimit = 100;
  auditIssuesOnly = false;
  auditResult: AuditFolderResponse | null = null;
  isAuditLoading = false;
  auditErrorMessage = '';

  constructor(
    private readonly system: SystemService,
    private readonly auth: AuthService
  ) {
    this.restoreAuditDraft();
  }

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.isLoading = true;
    this.errorMessage = '';
    this.system.getMetrics().subscribe({
      next: (data) => {
        this.metrics = data;
        this.isLoading = false;
      },
      error: () => {
        this.metrics = null;
        this.errorMessage = 'No se pudieron cargar las metricas.';
        this.isLoading = false;
      }
    });
  }

  canAudit(): boolean {
    return (this.auth.getRole() ?? '').toUpperCase() === 'ADMIN';
  }

  runAudit(): void {
    const folderPath = this.auditFolderPath.trim();
    if (!folderPath) {
      this.auditErrorMessage = 'Captura una ruta absoluta antes de ejecutar la auditoria.';
      return;
    }

    this.persistAuditDraft();
    this.isAuditLoading = true;
    this.auditErrorMessage = '';

    this.system
      .auditFolder({
        folder_path: folderPath,
        recurse: this.auditRecurse,
        limit: this.normalizeLimit(this.auditLimit),
        issues_only: this.auditIssuesOnly
      })
      .subscribe({
        next: (data) => {
          this.auditResult = data;
          this.isAuditLoading = false;
        },
        error: (err) => {
          this.auditResult = null;
          this.auditErrorMessage =
            err?.error?.detail ??
            err?.error?.message ??
            (typeof err?.error === 'string' ? err.error : null) ??
            'No se pudo ejecutar la auditoria del lote.';
          this.isAuditLoading = false;
        }
      });
  }

  clearAuditResult(): void {
    this.auditResult = null;
    this.auditErrorMessage = '';
  }

  documentTypeCountEntries(): Array<{ key: string; value: number }> {
    return Object.entries(this.auditResult?.document_type_counts ?? {})
      .map(([key, value]) => ({ key, value }))
      .sort((a, b) => b.value - a.value);
  }

  mappedFieldEntries(document: AuditDocumentSummary): Array<{ key: string; value: string }> {
    return Object.entries(document.mapped_fields ?? {})
      .filter(([, value]) => String(value ?? '').trim().length > 0)
      .map(([key, value]) => ({ key, value }));
  }

  trackDocument(_: number, document: AuditDocumentSummary): string {
    return document.file_path || document.name;
  }

  persistAuditDraft(): void {
    const payload = {
      folderPath: this.auditFolderPath,
      recurse: this.auditRecurse,
      limit: this.normalizeLimit(this.auditLimit),
      issuesOnly: this.auditIssuesOnly
    };

    try {
      localStorage.setItem(SystemMetricsPage.AUDIT_DRAFT_STORAGE_KEY, JSON.stringify(payload));
    } catch {
      // Ignore local storage failures in private mode or restricted environments.
    }
  }

  private restoreAuditDraft(): void {
    try {
      const raw = localStorage.getItem(SystemMetricsPage.AUDIT_DRAFT_STORAGE_KEY);
      if (!raw) {
        return;
      }

      const payload = JSON.parse(raw) as {
        folderPath?: string;
        recurse?: boolean;
        limit?: number;
        issuesOnly?: boolean;
      };

      this.auditFolderPath = payload.folderPath?.trim() ?? '';
      this.auditRecurse = payload.recurse ?? true;
      this.auditLimit = this.normalizeLimit(payload.limit ?? 100);
      this.auditIssuesOnly = payload.issuesOnly ?? false;
    } catch {
      this.auditFolderPath = '';
      this.auditRecurse = true;
      this.auditLimit = 100;
      this.auditIssuesOnly = false;
    }
  }

  private normalizeLimit(value: number): number {
    if (!Number.isFinite(value)) {
      return 100;
    }
    return Math.max(1, Math.min(500, Math.trunc(value)));
  }
}
