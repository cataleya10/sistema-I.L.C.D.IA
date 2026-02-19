import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { DocumentsService } from '../services/documents.service';
import { DocumentDetail, DocumentField, getDocumentTypeLabel } from '../../../shared/models/document.models';
import { DOCUMENT_FIELD_TEMPLATES } from '../field-templates';
import {
  TableLayoutMode,
  TableViewModel,
  buildExcelXml,
  buildReportHtmlDocument,
  buildTableView,
  detectTableLayoutMode,
  isTableCellsField,
  parseTableRows
} from '../utils/table-cells';
import {
  parseReplicaLayout,
  ReplicaLayoutView,
  ReplicaPreset,
  ReplicaPresetTuning,
  ReplicaPresetTuningOverrides,
  REPLICA_PRESET_TUNING
} from '../utils/pdf-replica-layout';
import { parsePaymentDetail, PaymentDetailViewModel } from '../utils/payment-detail';
import { buildExtractionHtmlDocument } from '../utils/extraction-export';

@Component({
  selector: 'app-documents-results-page',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  template: `
    <section class="page" *ngIf="document; else loading">
      <header class="page__header">
        <div>
          <a class="back" routerLink="/documents">Volver</a>
          <h2>Resultados extraidos</h2>
          <p>{{ document.original_filename }}</p>
        </div>
        <div class="actions">
          <button type="button" (click)="refresh()" [disabled]="isLoading">Actualizar</button>
          <button type="button" class="ghost" (click)="downloadTableCsv()" [disabled]="!tableView.bodyRows.length">
            Descargar CSV tabla
          </button>
          <button type="button" class="ghost" (click)="downloadTableExcel()" [disabled]="!tableView.bodyRows.length">
            Descargar Excel tabla
          </button>
          <button type="button" class="ghost" (click)="downloadTablePdfReport()" [disabled]="!tableView.bodyRows.length">
            Descargar PDF reporte
          </button>
          <button type="button" class="ghost" (click)="downloadExtractionSnapshot()" [disabled]="!document">
            Descargar extraccion completa
          </button>
          <button type="button" class="ghost" (click)="downloadExtractionPdf()" [disabled]="!document">
            Descargar extraccion PDF
          </button>
          <a class="ghost" [routerLink]="['/documents', document.id]">Ver detalle</a>
        </div>
      </header>

      <section class="summary">
        <div class="card">
          <span>Estado</span>
          <strong>{{ document.status }}</strong>
        </div>
        <div class="card">
          <span>Tipo</span>
          <strong>{{ typeLabel(document.document_type) }}</strong>
        </div>
        <div class="card">
          <span>Confianza</span>
          <strong>{{ (document.confidence ?? 0) | percent: '1.0-0' }}</strong>
        </div>
        <div class="card">
          <span>Campos</span>
          <strong>{{ document.fields.length }}</strong>
        </div>
        <div class="card">
          <span>Validos</span>
          <strong>{{ validCount }}</strong>
        </div>
        <div class="card">
          <span>Revisar</span>
          <strong>{{ invalidCount }}</strong>
        </div>
      </section>

      <section class="panel calibration-panel">
        <div class="panel__header">
          <div>
            <h3>Calibracion replica PDF</h3>
            <p class="hint">Ajusta escala/margenes por preset y guarda localmente.</p>
            <p class="hint">Banco detectado: {{ detectedBankLabel() }}</p>
          </div>
        </div>
        <div class="calibration-panel__controls">
          <label>
            Preset
            <select [(ngModel)]="selectedReplicaPreset" (ngModelChange)="onReplicaPresetChange()">
              <option *ngFor="let preset of replicaPresetOptions" [ngValue]="preset">{{ preset }}</option>
            </select>
          </label>
          <label>
            Scale X
            <input type="number" step="0.005" [(ngModel)]="calibrationForm.scaleX" />
          </label>
          <label>
            Scale Y
            <input type="number" step="0.005" [(ngModel)]="calibrationForm.scaleY" />
          </label>
          <label>
            Offset X
            <input type="number" step="0.1" [(ngModel)]="calibrationForm.offsetX" />
          </label>
          <label>
            Offset Y
            <input type="number" step="0.1" [(ngModel)]="calibrationForm.offsetY" />
          </label>
          <label>
            Aspect Shift
            <input type="number" step="0.1" [(ngModel)]="calibrationForm.aspectShift" />
          </label>
          <label>
            Font Scale
            <input type="number" step="0.01" [(ngModel)]="calibrationForm.fontScale" />
          </label>
          <label>
            Line Height
            <input type="text" [(ngModel)]="calibrationForm.lineHeight" />
          </label>
        </div>
        <div class="calibration-panel__actions">
          <button type="button" class="ghost" (click)="applyReplicaCalibration()">Aplicar calibracion</button>
          <button type="button" class="ghost" (click)="resetReplicaCalibrationPreset()">Reset preset</button>
          <button type="button" class="ghost" (click)="resetReplicaCalibrationAll()">Reset total</button>
          <button type="button" class="ghost" (click)="exportReplicaCalibration()">Exportar JSON</button>
          <button type="button" class="ghost" (click)="replicaImportInput.click()">Importar JSON</button>
          <input
            #replicaImportInput
            class="calibration-file"
            type="file"
            accept="application/json,.json"
            (change)="importReplicaCalibration($event)"
          />
        </div>
        <p class="hint" *ngIf="calibrationStatus">{{ calibrationStatus }}</p>
      </section>

      <section class="panel">
        <div class="panel__header">
          <div>
            <h3>Campos extraidos</h3>
            <p class="hint" *ngIf="document.needs_review">Revision requerida por baja confianza o validacion.</p>
          </div>
          <div class="filters">
            <input type="text" placeholder="Buscar campo o valor" [(ngModel)]="search" />
            <label class="toggle">
              <input type="checkbox" [(ngModel)]="onlyInvalid" />
              <span>Solo revisar</span>
            </label>
          </div>
        </div>

        <table class="results" *ngIf="filteredFields.length">
          <thead>
            <tr>
              <th>Campo</th>
              <th>Valor</th>
              <th>Confianza</th>
              <th>Validez</th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let field of filteredFields">
              <td>{{ field.label }}</td>
              <td>
                <ng-container *ngIf="isPdfReplicaLayoutField(field); else notLayoutReplica">
                  <ng-container *ngIf="replicaLayoutForField(field) as layout">
                    <div class="pdf-layout-wrap" [ngClass]="'preset-' + layout.preset" *ngIf="layout.pages.length; else plainValue">
                      <p class="bank-chip">Banco detectado: {{ layout.detectedBankLabel }}</p>
                      <article class="pdf-layout-page" *ngFor="let page of layout.pages">
                        <div class="pdf-layout-canvas" [style.paddingBottom.%]="page.aspectRatio">
                          <span
                            class="pdf-layout-line"
                            *ngFor="let line of page.lines"
                            [style.left.%]="line.leftPct"
                            [style.top.%]="line.topPct"
                            [style.width.%]="line.widthPct"
                            [style.height.px]="line.heightPx"
                            [style.font-size.px]="line.fontSizePx"
                            [style.lineHeight]="line.lineHeight"
                          >
                            {{ line.text }}
                          </span>
                        </div>
                      </article>
                    </div>
                  </ng-container>
                </ng-container>
                <ng-template #notLayoutReplica>
                <ng-container *ngIf="isPdfReplicaField(field); else notReplica">
                  <pre class="pdf-replica">{{ field.corrected_value ?? field.value ?? '-' }}</pre>
                </ng-container>
                <ng-template #notReplica>
                <ng-container *ngIf="isPaymentDetailField(field); else notPaymentDetail">
                  <ng-container *ngIf="paymentDetailForField(field) as paymentDetail; else plainValue">
                    <div class="payment-detail">
                      <p class="payment-detail__bank">Banco: {{ paymentDetail.bank }}</p>
                      <div class="payment-detail__meta" *ngIf="paymentDetail.metadataEntries.length">
                        <p class="payment-detail__meta-item" *ngFor="let meta of paymentDetail.metadataEntries">
                          <strong>{{ meta.key }}:</strong> {{ meta.value }}
                        </p>
                      </div>
                      <div class="cells-table-wrap" *ngIf="paymentDetail.canonicalRows.length">
                        <table class="cells-table">
                          <thead *ngIf="paymentDetail.canonicalColumns.length">
                            <tr>
                              <th *ngFor="let col of paymentDetail.canonicalColumns">{{ col }}</th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr *ngFor="let row of paymentDetail.canonicalRows; let rowIndex = index" [class.alt]="rowIndex % 2 === 1">
                              <td *ngFor="let cell of row">{{ cell }}</td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                      <div class="payment-detail__summary" *ngFor="let summary of paymentDetail.summaryTables">
                        <p class="payment-detail__summary-title">{{ summary.title }}</p>
                        <div class="cells-table-wrap">
                          <table class="cells-table">
                            <thead *ngIf="summary.columns.length">
                              <tr>
                                <th *ngFor="let col of summary.columns">{{ col }}</th>
                              </tr>
                            </thead>
                            <tbody>
                              <tr *ngFor="let row of summary.rows; let rowIndex = index" [class.alt]="rowIndex % 2 === 1">
                                <td *ngFor="let cell of row">{{ cell }}</td>
                              </tr>
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                  </ng-container>
                </ng-container>
                <ng-template #notPaymentDetail>
                <ng-container *ngIf="isTableField(field); else plainValue">
                  <ng-container *ngIf="tableViewForField(field) as tableView">
                    <div class="cells-table-wrap" *ngIf="tableView.bodyRows.length; else plainValue">
                      <table class="cells-table">
                        <thead *ngIf="tableView.headerRows.length">
                          <tr *ngFor="let row of tableView.headerRows">
                            <th *ngFor="let cell of row">{{ cell }}</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr *ngFor="let row of tableView.bodyRows; let rowIndex = index" [class.alt]="rowIndex % 2 === 1">
                            <td *ngFor="let cell of row">{{ cell }}</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </ng-container>
                </ng-container>
                </ng-template>
                </ng-template>
                </ng-template>
                <ng-template #plainValue>
                  {{ field.corrected_value ?? field.value ?? '-' }}
                </ng-template>
              </td>
              <td>{{ field.confidence | percent: '1.0-0' }}</td>
              <td>
                <span class="badge" [ngClass]="field.valid ? 'ok' : 'warn'">
                  {{ field.valid ? 'OK' : 'Revisar' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
        <p class="empty" *ngIf="!filteredFields.length">No hay campos con esos filtros.</p>
      </section>

      <section class="panel table-panel" [ngClass]="tableLayoutMode" *ngIf="tableView.bodyRows.length">
        <div class="panel__header">
          <div class="table-panel__title">
            <h3>Tabla detectada</h3>
            <span class="table-mode">{{ tableLayoutLabel() }}</span>
          </div>
          <div class="table-panel__actions">
            <button type="button" class="ghost" (click)="toggleTableRenderMode()">{{ tableRenderModeLabel() }}</button>
          </div>
        </div>
        <div class="cells-table-wrap">
          <table class="cells-table" [ngClass]="{ 'report-mode': tableRenderMode === 'report' }">
            <thead *ngIf="tableView.headerRows.length">
              <tr *ngFor="let row of tableView.headerRows">
                <th *ngFor="let cell of row">{{ cell }}</th>
              </tr>
            </thead>
            <tbody>
              <tr *ngFor="let row of tableView.bodyRows; let rowIndex = index" [class.alt]="rowIndex % 2 === 1">
                <td *ngFor="let cell of row">{{ cell }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </section>

    <ng-template #loading>
      <section class="page">
        <p class="loading">Cargando resultados...</p>
      </section>
    </ng-template>
  `,
  styles: [
    `
      .page {
        display: grid;
        gap: 20px;
      }
      .page__header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 16px;
      }
      .page__header h2 {
        margin: 6px 0 0;
      }
      .page__header p {
        margin: 4px 0 0;
        color: #6b7280;
      }
      .back {
        display: inline-flex;
        color: #4f46e5;
        text-decoration: none;
        font-size: 12px;
      }
      .actions {
        display: flex;
        gap: 12px;
        align-items: center;
      }
      .actions button,
      .actions a {
        padding: 8px 16px;
        border-radius: 999px;
        border: none;
        background: #4f46e5;
        color: #fff;
        text-decoration: none;
        font-size: 14px;
      }
      .actions .ghost {
        background: #e5e7eb;
        color: #111827;
      }
      .calibration-panel__actions .ghost {
        background: #f3f4f6;
        color: #111827;
        border: 1px solid #d1d5db;
      }
      .summary {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
        gap: 12px;
      }
      .card {
        background: #fff;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 14px;
        display: grid;
        gap: 6px;
      }
      .card span {
        font-size: 12px;
        color: #6b7280;
      }
      .card strong {
        font-size: 16px;
      }
      .panel {
        background: #fff;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 16px;
        display: grid;
        gap: 16px;
      }
      .table-panel.advanced_nomina {
        border-color: #93c5fd;
        box-shadow: 0 8px 18px rgba(37, 99, 235, 0.12);
      }
      .table-panel__title {
        display: inline-flex;
        align-items: center;
        gap: 8px;
      }
      .table-panel__actions {
        display: inline-flex;
        gap: 8px;
      }
      .table-mode {
        display: inline-flex;
        align-items: center;
        padding: 2px 8px;
        border-radius: 999px;
        background: #dbeafe;
        color: #1d4ed8;
        font-size: 11px;
        font-weight: 700;
      }
      .panel__header {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        flex-wrap: wrap;
      }
      .hint {
        color: #b45309;
        font-size: 12px;
        margin: 4px 0 0;
      }
      .calibration-panel__controls {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
        gap: 10px;
      }
      .calibration-panel__controls label {
        display: grid;
        gap: 4px;
        font-size: 12px;
        color: #374151;
      }
      .calibration-panel__controls input,
      .calibration-panel__controls select {
        border: 1px solid #d1d5db;
        border-radius: 8px;
        padding: 7px 8px;
        font-size: 12px;
      }
      .calibration-panel__actions {
        display: inline-flex;
        gap: 8px;
        flex-wrap: wrap;
      }
      .calibration-file {
        display: none;
      }
      .filters {
        display: flex;
        gap: 12px;
        align-items: center;
        flex-wrap: wrap;
      }
      .filters input {
        padding: 8px 12px;
        border-radius: 8px;
        border: 1px solid #e5e7eb;
      }
      .toggle {
        display: inline-flex;
        gap: 8px;
        align-items: center;
        font-size: 12px;
        color: #374151;
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
      }
      .results th {
        font-size: 12px;
        color: #6b7280;
      }
      .cells-table-wrap {
        overflow-x: auto;
      }
      .cells-table {
        width: max-content;
        min-width: 100%;
        border-collapse: collapse;
        font-size: 12px;
      }
      .cells-table th,
      .cells-table td {
        padding: 6px 8px;
        border: 1px solid #e5e7eb;
        white-space: nowrap;
        text-align: left;
      }
      .cells-table th {
        background: #f3f4f6;
        color: #111827;
        font-weight: 700;
        position: sticky;
        top: 0;
        z-index: 1;
      }
      .cells-table tbody tr.alt td {
        background: #fafafa;
      }
      .cells-table tbody tr:hover td {
        background: #eef2ff;
      }
      .cells-table.report-mode {
        table-layout: fixed;
        width: 100%;
        font-family: 'Times New Roman', 'Georgia', serif;
        font-size: 11px;
        line-height: 1.1;
      }
      .cells-table.report-mode th,
      .cells-table.report-mode td {
        white-space: normal;
        text-align: center;
        vertical-align: middle;
        padding: 4px 6px;
        border-color: #d1d5db;
      }
      .cells-table.report-mode th {
        background: #eef2f7;
        letter-spacing: 0.2px;
      }
      .cells-table.report-mode tbody tr:nth-child(even) td {
        background: #fcfcfd;
      }
      .cells-table.report-mode tbody tr:hover td {
        background: #eaf0ff;
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
      .pdf-replica {
        margin: 0;
        white-space: pre-wrap;
        font-family: 'Times New Roman', 'Georgia', serif;
        font-size: 11px;
        line-height: 1.15;
        background: #f8fafc;
        border: 1px solid #d1d5db;
        border-radius: 8px;
        padding: 10px;
        max-height: 360px;
        overflow: auto;
      }
      .payment-detail {
        display: grid;
        gap: 8px;
      }
      .payment-detail__bank {
        margin: 0;
        font-size: 12px;
        font-weight: 700;
        color: #1f2937;
      }
      .payment-detail__meta {
        display: grid;
        gap: 3px;
      }
      .payment-detail__meta-item {
        margin: 0;
        font-size: 12px;
        color: #374151;
      }
      .payment-detail__summary {
        display: grid;
        gap: 6px;
      }
      .payment-detail__summary-title {
        margin: 0;
        font-size: 12px;
        font-weight: 700;
      }
      .pdf-layout-wrap {
        display: grid;
        gap: 12px;
      }
      .bank-chip {
        margin: 0;
        font-size: 12px;
        color: #374151;
      }
      .pdf-layout-wrap.preset-scotia .pdf-layout-line {
        font-family: 'Times New Roman', 'Georgia', serif;
        letter-spacing: 0;
        line-height: 1.04;
      }
      .pdf-layout-wrap.preset-bbva .pdf-layout-line {
        font-family: 'Arial Narrow', 'Arial', sans-serif;
        letter-spacing: -0.08px;
        line-height: 1;
      }
      .pdf-layout-wrap.preset-bbva .pdf-layout-canvas {
        background: #fdfefe;
      }
      .pdf-layout-page {
        border: 1px solid #d1d5db;
        border-radius: 8px;
        background: #f8fafc;
        overflow: hidden;
      }
      .pdf-layout-canvas {
        position: relative;
        width: 100%;
        min-height: 420px;
        background: #fff;
      }
      .pdf-layout-line {
        position: absolute;
        display: block;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
        font-family: 'Times New Roman', 'Georgia', serif;
        font-size: 10px;
        line-height: 1.08;
        color: #111827;
      }
      .empty {
        font-size: 12px;
        color: #6b7280;
      }
      .loading {
        font-size: 13px;
        color: #6b7280;
      }
    `
  ]
})
export class DocumentsResultsPage implements OnInit {
  private static readonly REPLICA_TUNING_STORAGE_KEY = 'documents.replicaPresetTuning.v1';
  private static readonly HIDDEN_FIELD_KEYS = new Set(['pago_detalle']);
  document: DocumentDetail | null = null;
  displayFields: DocumentField[] = [];
  search = '';
  onlyInvalid = false;
  isLoading = false;
  tableView: TableViewModel = { headerRows: [], bodyRows: [] };
  tableLayoutMode: TableLayoutMode = 'standard';
  tableRenderMode: 'standard' | 'report' = 'standard';
  replicaPresetOptions: ReplicaPreset[] = ['default', 'scotia', 'bbva'];
  selectedReplicaPreset: ReplicaPreset = 'default';
  calibrationForm = {
    scaleX: 1,
    scaleY: 1,
    offsetX: 0,
    offsetY: 0,
    aspectShift: 0,
    fontScale: 0.9,
    lineHeight: '1.08'
  };
  calibrationStatus: string | null = null;
  private tableRowsCache = new Map<string, string[][]>();
  private tableViewCache = new Map<string, TableViewModel>();
  private replicaLayoutCache = new Map<string, ReplicaLayoutView | null>();
  private paymentDetailCache = new Map<string, PaymentDetailViewModel | null>();
  private replicaTuningOverrides: ReplicaPresetTuningOverrides = {};

  constructor(private readonly route: ActivatedRoute, private readonly documents: DocumentsService) {
    this.replicaTuningOverrides = this.loadReplicaTuningOverrides();
    this.onReplicaPresetChange();
  }

  get filteredFields(): DocumentField[] {
    if (!this.document) {
      return [];
    }
    const query = this.search.trim().toLowerCase();
    return this.displayFields.filter((field) => {
      if (this.onlyInvalid && field.valid) {
        return false;
      }
      if (!query) {
        return true;
      }
      const label = field.label?.toLowerCase() ?? '';
      const value = (field.corrected_value ?? field.value ?? '').toString().toLowerCase();
      return label.includes(query) || value.includes(query);
    });
  }

  get validCount(): number {
    return this.displayFields.filter((field) => field.valid).length;
  }

  get invalidCount(): number {
    return this.displayFields.filter((field) => !field.valid).length;
  }

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.load(id);
    }
  }

  refresh(): void {
    if (!this.document) {
      return;
    }
    this.load(this.document.id);
  }

  private load(id: string): void {
    this.isLoading = true;
    this.documents.getById(id).subscribe({
      next: (data) => {
        this.document = {
          ...data,
          file_url: this.documents.getFileUrl(data.id)
        };
        this.tableRowsCache.clear();
        this.tableViewCache.clear();
        this.replicaLayoutCache.clear();
        this.paymentDetailCache.clear();
        this.displayFields = this.mapDisplayFields(this.document);
        this.syncTableRows();
        this.isLoading = false;
      },
      error: () => {
        this.document = null;
        this.displayFields = [];
        this.tableView = { headerRows: [], bodyRows: [] };
        this.isLoading = false;
      }
    });
  }

  private mapDisplayFields(document: DocumentDetail): DocumentField[] {
    const template = DOCUMENT_FIELD_TEMPLATES[document.document_type];
    if (!template) {
      return document.fields.filter((field) => !this.isHiddenField(field.key));
    }
    const fieldMap = new Map(document.fields.map((field) => [field.key.toLowerCase(), field]));
    const mappedFromTemplate = template.map((field) => {
      const resolved = fieldMap.get(field.key.toLowerCase());
      return {
        key: field.key,
        label: field.label,
        value: resolved?.value ?? null,
        confidence: resolved?.confidence ?? 0,
        valid: resolved?.valid ?? true,
        validation_errors: resolved?.validation_errors ?? [],
        source: resolved?.source,
        corrected: resolved?.corrected ?? false,
        corrected_value: resolved?.corrected_value ?? null
      };
    });
    if (document.document_type === 'FACTURA') {
      return mappedFromTemplate;
    }
    const templateKeys = new Set(template.map((field) => field.key.toLowerCase()));
    const extras = document.fields.filter(
      (field) => !templateKeys.has(field.key.toLowerCase()) && !this.isHiddenField(field.key)
    );
    return [...mappedFromTemplate, ...extras];
  }

  private isHiddenField(key: string | null | undefined): boolean {
    return DocumentsResultsPage.HIDDEN_FIELD_KEYS.has(String(key ?? '').toLowerCase());
  }

  typeLabel(type: DocumentDetail['document_type']): string {
    return getDocumentTypeLabel(type);
  }

  isTableField(field: DocumentField): boolean {
    return isTableCellsField(field);
  }

  isPdfReplicaField(field: DocumentField): boolean {
    return String(field.key ?? '').toLowerCase() === 'replica_pdf_texto';
  }

  isPdfReplicaLayoutField(field: DocumentField): boolean {
    return String(field.key ?? '').toLowerCase() === 'replica_pdf_layout';
  }

  isPaymentDetailField(field: DocumentField): boolean {
    return String(field.key ?? '').toLowerCase() === 'pago_detalle';
  }

  detectedBankLabel(): string {
    const layoutField = this.displayFields.find((field) => this.isPdfReplicaLayoutField(field));
    if (!layoutField) {
      return 'No identificado';
    }
    const layout = this.replicaLayoutForField(layoutField);
    return layout?.detectedBankLabel ?? 'No identificado';
  }

  onReplicaPresetChange(): void {
    const tuning = this.currentPresetTuning(this.selectedReplicaPreset);
    this.calibrationForm = {
      scaleX: tuning.geometry.scaleX,
      scaleY: tuning.geometry.scaleY,
      offsetX: tuning.geometry.offsetX,
      offsetY: tuning.geometry.offsetY,
      aspectShift: tuning.geometry.aspectShift,
      fontScale: tuning.typography.fontScale,
      lineHeight: tuning.typography.lineHeight
    };
  }

  applyReplicaCalibration(): void {
    const lineHeightText = String(this.calibrationForm.lineHeight ?? '').trim();
    this.replicaTuningOverrides[this.selectedReplicaPreset] = {
      geometry: {
        scaleX: this.clampNumeric(this.calibrationForm.scaleX, 0.8, 1.2),
        scaleY: this.clampNumeric(this.calibrationForm.scaleY, 0.8, 1.2),
        offsetX: this.clampNumeric(this.calibrationForm.offsetX, -20, 20),
        offsetY: this.clampNumeric(this.calibrationForm.offsetY, -20, 20),
        aspectShift: this.clampNumeric(this.calibrationForm.aspectShift, -20, 20)
      },
      typography: {
        fontScale: this.clampNumeric(this.calibrationForm.fontScale, 0.7, 1.4),
        lineHeight: lineHeightText || REPLICA_PRESET_TUNING[this.selectedReplicaPreset].typography.lineHeight
      }
    };
    this.persistReplicaTuningOverrides();
    this.replicaLayoutCache.clear();
    this.onReplicaPresetChange();
    this.calibrationStatus = `Calibracion aplicada para ${this.selectedReplicaPreset}.`;
  }

  resetReplicaCalibrationPreset(): void {
    delete this.replicaTuningOverrides[this.selectedReplicaPreset];
    this.persistReplicaTuningOverrides();
    this.replicaLayoutCache.clear();
    this.onReplicaPresetChange();
    this.calibrationStatus = `Preset ${this.selectedReplicaPreset} restaurado.`;
  }

  resetReplicaCalibrationAll(): void {
    this.replicaTuningOverrides = {};
    this.persistReplicaTuningOverrides();
    this.replicaLayoutCache.clear();
    this.onReplicaPresetChange();
    this.calibrationStatus = 'Calibracion global restaurada.';
  }

  exportReplicaCalibration(): void {
    const payload = JSON.stringify(this.replicaTuningOverrides, null, 2);
    const blob = new Blob([payload], { type: 'application/json;charset=utf-8;' });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'replica-calibration.json';
    anchor.click();
    window.URL.revokeObjectURL(url);
    this.calibrationStatus = 'Calibracion exportada.';
  }

  importReplicaCalibration(event: Event): void {
    const input = event.target as HTMLInputElement | null;
    const file = input?.files?.[0];
    if (!file) {
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result ?? '{}'));
        this.replicaTuningOverrides = this.coerceReplicaOverrides(parsed);
        this.persistReplicaTuningOverrides();
        this.replicaLayoutCache.clear();
        this.onReplicaPresetChange();
        this.calibrationStatus = 'Calibracion importada correctamente.';
      } catch {
        this.calibrationStatus = 'No se pudo importar el JSON de calibracion.';
      } finally {
        if (input) {
          input.value = '';
        }
      }
    };
    reader.onerror = () => {
      this.calibrationStatus = 'No se pudo leer el archivo de calibracion.';
      if (input) {
        input.value = '';
      }
    };
    reader.readAsText(file, 'utf-8');
  }

  replicaLayoutForField(field: DocumentField): ReplicaLayoutView | null {
    const rawValue = (field.corrected_value ?? field.value ?? '').toString();
    if (!rawValue) {
      return null;
    }
    const cached = this.replicaLayoutCache.get(rawValue);
    if (cached !== undefined) {
      return cached;
    }
    const parsed = parseReplicaLayout(rawValue, this.replicaTuningOverrides);
    this.replicaLayoutCache.set(rawValue, parsed);
    return parsed;
  }

  paymentDetailForField(field: DocumentField): PaymentDetailViewModel | null {
    const rawValue = (field.corrected_value ?? field.value ?? '').toString();
    if (!rawValue) {
      return null;
    }
    const cached = this.paymentDetailCache.get(rawValue);
    if (cached !== undefined) {
      return cached;
    }
    const parsed = parsePaymentDetail(rawValue);
    this.paymentDetailCache.set(rawValue, parsed);
    return parsed;
  }

  tableRowsForField(field: DocumentField): string[][] {
    const rawValue = (field.corrected_value ?? field.value ?? '').toString();
    if (!rawValue) {
      return [];
    }
    const cached = this.tableRowsCache.get(rawValue);
    if (cached) {
      return cached;
    }

    const rows = parseTableRows(rawValue);
    this.tableRowsCache.set(rawValue, rows);
    return rows;
  }

  tableViewForField(field: DocumentField): TableViewModel {
    const rawValue = (field.corrected_value ?? field.value ?? '').toString();
    if (!rawValue) {
      return { headerRows: [], bodyRows: [] };
    }
    const cached = this.tableViewCache.get(rawValue);
    if (cached) {
      return cached;
    }

    const tableView = buildTableView(this.tableRowsForField(field));
    this.tableViewCache.set(rawValue, tableView);
    return tableView;
  }

  downloadTableCsv(): void {
    if (!this.document || this.tableView.bodyRows.length === 0) {
      return;
    }
    const baseName = (this.document.original_filename || 'documento')
      .replace(/\.[^/.]+$/, '')
      .trim();
    const filename = baseName ? `${baseName}-tabla.csv` : 'documento-tabla.csv';
    const csvRows = [...this.tableView.headerRows, ...this.tableView.bodyRows];
    const csvContent = this.buildCsv(csvRows);
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    window.URL.revokeObjectURL(url);
  }

  downloadTableExcel(): void {
    if (!this.document || this.tableView.bodyRows.length === 0) {
      return;
    }
    const baseName = (this.document.original_filename || 'documento')
      .replace(/\.[^/.]+$/, '')
      .trim();
    const filename = baseName ? `${baseName}-tabla.xls` : 'documento-tabla.xls';
    const rows = [...this.tableView.headerRows, ...this.tableView.bodyRows];
    const xml = buildExcelXml(rows, { reportMode: this.tableRenderMode === 'report' });
    const blob = new Blob([xml], { type: 'application/vnd.ms-excel;charset=utf-8;' });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    window.URL.revokeObjectURL(url);
  }

  downloadTablePdfReport(): void {
    if (!this.document || this.tableView.bodyRows.length === 0) {
      return;
    }
    const rows = [...this.tableView.headerRows, ...this.tableView.bodyRows];
    const title = `Reporte de tabla - ${this.document.original_filename || 'documento'}`;
    const html = buildReportHtmlDocument(title, rows);
    const reportWindow = window.open('', '_blank', 'noopener,noreferrer,width=1200,height=900');
    if (!reportWindow) {
      return;
    }
    reportWindow.document.open();
    reportWindow.document.write(html);
    reportWindow.document.close();
  }

  downloadExtractionSnapshot(): void {
    if (!this.document) {
      return;
    }
    const fields = this.document.fields ?? [];
    const findRaw = (key: string): string => {
      const match = fields.find((f) => String(f.key ?? '').toLowerCase() === key);
      return String(match?.corrected_value ?? match?.value ?? '');
    };
    const replicaLayout = parseReplicaLayout(findRaw('replica_pdf_layout'), this.replicaTuningOverrides);
    const replicaText = findRaw('replica_pdf_texto');
    const paymentDetail = parsePaymentDetail(findRaw('pago_detalle'));
    const html = buildExtractionHtmlDocument({
      title: `Extraccion - ${this.document.original_filename || 'documento'}`,
      tableView: this.tableView,
      replicaLayout,
      replicaText,
      paymentDetail,
    });
    const blob = new Blob([html], { type: 'text/html;charset=utf-8;' });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    const baseName = (this.document.original_filename || 'documento').replace(/\.[^/.]+$/, '');
    anchor.href = url;
    anchor.download = `${baseName}-extraccion.html`;
    anchor.click();
    window.URL.revokeObjectURL(url);
  }

  downloadExtractionPdf(): void {
    if (!this.document) {
      return;
    }
    const fields = this.document.fields ?? [];
    const findRaw = (key: string): string => {
      const match = fields.find((f) => String(f.key ?? '').toLowerCase() === key);
      return String(match?.corrected_value ?? match?.value ?? '');
    };
    const replicaLayout = parseReplicaLayout(findRaw('replica_pdf_layout'), this.replicaTuningOverrides);
    const replicaText = findRaw('replica_pdf_texto');
    const paymentDetail = parsePaymentDetail(findRaw('pago_detalle'));
    const html = buildExtractionHtmlDocument({
      title: `Extraccion - ${this.document.original_filename || 'documento'}`,
      tableView: this.tableView,
      replicaLayout,
      replicaText,
      paymentDetail,
    });
    const printWindow = window.open('', '_blank', 'noopener,noreferrer,width=1200,height=900');
    if (!printWindow) {
      return;
    }
    printWindow.document.open();
    printWindow.document.write(html);
    printWindow.document.close();
    setTimeout(() => {
      printWindow.focus();
      printWindow.print();
    }, 180);
  }

  toggleTableRenderMode(): void {
    this.tableRenderMode = this.tableRenderMode === 'report' ? 'standard' : 'report';
  }

  private syncTableRows(): void {
    const tableField = this.displayFields.find((field) => this.isTableField(field));
    this.tableView = tableField ? this.tableViewForField(tableField) : { headerRows: [], bodyRows: [] };
    this.tableLayoutMode = detectTableLayoutMode(this.tableView);
    this.tableRenderMode = this.tableLayoutMode === 'advanced_nomina' ? 'report' : 'standard';
  }

  tableLayoutLabel(): string {
    return this.tableLayoutMode === 'advanced_nomina' ? 'Modo nomina avanzada' : 'Modo estandar';
  }

  tableRenderModeLabel(): string {
    return this.tableRenderMode === 'report' ? 'Vista cuadricula' : 'Vista reporte';
  }

  private buildCsv(rows: string[][]): string {
    return rows
      .map((row) => row.map((cell) => this.escapeCsvCell(cell)).join(','))
      .join('\n');
  }

  private escapeCsvCell(value: string): string {
    const normalized = String(value ?? '');
    if (/[",\n\r]/.test(normalized)) {
      return `"${normalized.replace(/"/g, '""')}"`;
    }
    return normalized;
  }

  private currentPresetTuning(preset: ReplicaPreset): ReplicaPresetTuning {
    const base = REPLICA_PRESET_TUNING[preset];
    const override = this.replicaTuningOverrides[preset];
    return {
      geometry: {
        ...base.geometry,
        ...(override?.geometry ?? {})
      },
      typography: {
        ...base.typography,
        ...(override?.typography ?? {})
      }
    };
  }

  private clampNumeric(value: unknown, min: number, max: number): number {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
      return min;
    }
    return Math.max(min, Math.min(max, numeric));
  }

  private persistReplicaTuningOverrides(): void {
    try {
      window.localStorage.setItem(
        DocumentsResultsPage.REPLICA_TUNING_STORAGE_KEY,
        JSON.stringify(this.replicaTuningOverrides)
      );
    } catch {
      // Ignore persistence errors in restricted contexts.
    }
  }

  private loadReplicaTuningOverrides(): ReplicaPresetTuningOverrides {
    try {
      const raw = window.localStorage.getItem(DocumentsResultsPage.REPLICA_TUNING_STORAGE_KEY);
      if (!raw) {
        return {};
      }
      const parsed = JSON.parse(raw) as ReplicaPresetTuningOverrides;
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
      return {};
    }
  }

  private coerceReplicaOverrides(raw: unknown): ReplicaPresetTuningOverrides {
    if (!raw || typeof raw !== 'object') {
      return {};
    }
    const source = raw as Record<string, unknown>;
    const output: ReplicaPresetTuningOverrides = {};
    this.replicaPresetOptions.forEach((preset) => {
      const candidate = source[preset];
      if (!candidate || typeof candidate !== 'object') {
        return;
      }
      const typed = candidate as { geometry?: Record<string, unknown>; typography?: Record<string, unknown> };
      output[preset] = {
        geometry: {
          scaleX: this.clampNumeric(typed.geometry?.['scaleX'], 0.8, 1.2),
          scaleY: this.clampNumeric(typed.geometry?.['scaleY'], 0.8, 1.2),
          offsetX: this.clampNumeric(typed.geometry?.['offsetX'], -20, 20),
          offsetY: this.clampNumeric(typed.geometry?.['offsetY'], -20, 20),
          aspectShift: this.clampNumeric(typed.geometry?.['aspectShift'], -20, 20)
        },
        typography: {
          fontScale: this.clampNumeric(typed.typography?.['fontScale'], 0.7, 1.4),
          lineHeight: String(typed.typography?.['lineHeight'] ?? REPLICA_PRESET_TUNING[preset].typography.lineHeight)
        }
      };
    });
    return output;
  }
}
