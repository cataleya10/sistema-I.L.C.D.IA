import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { DocumentViewerComponent } from '../../../shared/components/document-viewer.component';
import { StatusBadgeComponent } from '../../../shared/components/status-badge.component';
import { DocumentsService } from '../services/documents.service';
import { DocumentDetail, getDocumentTypeLabel, ProcessingLog } from '../../../shared/models/document.models';
import { ToastNotificationComponent } from '../../../shared/components/toast-notification.component';
import { DOCUMENT_FIELD_TEMPLATES } from '../field-templates';
import {
  TableLayoutMode,
  TableViewModel,
  buildTablePdfBytes,
  buildCsv,
  buildExcelXml,
  flattenTableView,
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
          <p>{{ typeLabel(document.document_type) }} - Confianza {{ document.confidence ?? 0 | percent: '1.0-0' }}</p>
        </div>
        <app-status-badge [status]="document.status" />
      </header>

      <div class="actions">
        <button type="button" (click)="process()" [disabled]="isProcessing || document.status === 'PROCESSING'">Procesar</button>
        <button
          type="button"
          (click)="processAsFactura()"
          [disabled]="isProcessing || document.status === 'PROCESSING'"
        >
          Procesar como Factura
        </button>
        <button type="button" class="ghost" (click)="reprocess()" [disabled]="isProcessing || document.status === 'PROCESSING'">Reprocesar</button>
        <button
          type="button"
          class="ghost"
          (click)="reprocessAsFactura()"
          [disabled]="isProcessing || document.status === 'PROCESSING'"
        >
          Reprocesar como Factura
        </button>
        <button type="button" class="ghost" (click)="toggleEdit()" [disabled]="isSaving">
          {{ editMode ? 'Cancelar edicion' : 'Editar campos' }}
        </button>
        <button type="button" class="ghost" *ngIf="editMode" (click)="saveEdits()" [disabled]="isSaving">
          Guardar cambios
        </button>
        <button type="button" class="ghost" (click)="downloadWord()" [disabled]="!document">Descargar Word</button>
        <button type="button" class="ghost" (click)="downloadExcel()" [disabled]="!document">Descargar Excel</button>
        <button type="button" class="ghost" (click)="downloadExtractionSnapshot()" [disabled]="!document">Descargar extraccion completa</button>
        <button type="button" class="ghost" (click)="downloadExtractionPdf()" [disabled]="!document">Descargar extraccion PDF</button>
        <button type="button" class="ghost" (click)="copyFields()" [disabled]="!document">Copiar campos</button>
        <a class="ghost" [routerLink]="['/documents', document.id, 'results']">Ver resultados</a>
      </div>

      <div class="grid" [class.grid--full]="isFacturaType">
        <app-document-viewer
          [fileUrl]="previewFileUrl"
          [mimeType]="previewMimeType"
          [loading]="isPreviewLoading"
          [errorMessage]="previewError"
        ></app-document-viewer>
        <div class="fields" *ngIf="!isFacturaType">
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
                  </ng-container>
                  <ng-template #editField>
                    <ng-container *ngIf="!isTableField(field) && !isPaymentDetailField(field); else tableReadonly">
                      <input
                        class="field-input"
                        type="text"
                        [name]="field.key"
                        [(ngModel)]="editedValues[field.key]"
                      />
                    </ng-container>
                    <ng-template #tableReadonly>
                      <span class="table-readonly">Tabla generada automaticamente.</span>
                    </ng-template>
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

      <section class="table-panel" [ngClass]="tableLayoutMode" *ngIf="tableView.bodyRows.length">
        <div class="table-panel__header">
          <div class="table-panel__title">
            <h3>Tabla detectada</h3>
            <span class="table-mode">{{ tableLayoutLabel() }}</span>
          </div>
          <div class="table-panel__actions">
            <button type="button" class="ghost" (click)="toggleTableRenderMode()">{{ tableRenderModeLabel() }}</button>
            <button type="button" class="ghost" (click)="downloadTableCsv()">Descargar CSV tabla</button>
            <button type="button" class="ghost" (click)="downloadTableExcel()">Descargar Excel tabla</button>
            <button type="button" class="ghost" (click)="downloadTablePdfReport()">Descargar PDF reporte</button>
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

      <section class="calibration-panel">
        <div class="calibration-panel__header">
          <h3>Calibracion replica PDF</h3>
          <p>Ajusta escala/margenes por banco y guarda localmente.</p>
          <p class="calibration-status">Banco detectado: {{ detectedBankLabel() }}</p>
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
        <p class="calibration-status" *ngIf="calibrationStatus">{{ calibrationStatus }}</p>
      </section>

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
        grid-template-columns: minmax(380px, 1.15fr) minmax(460px, 1fr);
        gap: 20px;
        align-items: start;
      }
      .grid--full {
        grid-template-columns: 1fr;
      }
      app-document-viewer,
      .fields {
        min-width: 0;
      }
      .fields {
        background: #fff;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 16px;
        display: grid;
        gap: 12px;
      }
      .table-panel {
        background: #fff;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 16px;
        display: grid;
        gap: 12px;
      }
      .table-panel.advanced_nomina {
        border-color: #93c5fd;
        box-shadow: 0 8px 18px rgba(37, 99, 235, 0.12);
      }
      .table-panel__header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
      }
      .table-panel__title {
        display: inline-flex;
        align-items: center;
        gap: 8px;
      }
      .table-panel__actions {
        display: inline-flex;
        gap: 8px;
        flex-wrap: wrap;
      }
      .table-panel__header h3 {
        margin: 0;
      }
      .calibration-panel {
        background: #fff;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 16px;
        display: grid;
        gap: 12px;
      }
      .calibration-panel__header h3 {
        margin: 0;
      }
      .calibration-panel__header p {
        margin: 4px 0 0;
        font-size: 12px;
        color: #6b7280;
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
        flex-wrap: wrap;
        gap: 8px;
      }
      .calibration-panel__actions button {
        padding: 8px 12px;
        border-radius: 999px;
        border: 1px solid #d1d5db;
        background: #f3f4f6;
        color: #111827;
      }
      .calibration-file {
        display: none;
      }
      .calibration-status {
        margin: 0;
        font-size: 12px;
        color: #374151;
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
      .table-readonly {
        color: #6b7280;
        font-size: 12px;
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
        font-size: 10px;
        line-height: 1.08;
        letter-spacing: 0.02px;
      }
      .pdf-layout-wrap.preset-bbva .pdf-layout-line {
        font-size: 9.6px;
        line-height: 1.05;
        letter-spacing: 0;
      }
      .pdf-layout-wrap.preset-bbva .pdf-layout-canvas {
        background: #fbfbfc;
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
      @media (max-width: 1200px) {
        .grid {
          grid-template-columns: 1fr;
        }
      }
    `
  ]
})
export class DocumentsDetailPage implements OnInit, OnDestroy {
  private static readonly REPLICA_TUNING_STORAGE_KEY = 'documents.replicaPresetTuning.v1';
  private static readonly HIDDEN_FIELD_KEYS = new Set(['pago_detalle']);
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
  isPreviewLoading = false;
  previewFileUrl: string | null = null;
  previewMimeType: string | null = null;
  previewError: string | null = null;
  displayFields: DocumentDetail['fields'] = [];

  /** True when the current document is FACTURA — hides "Resultados extraídos" in favour of Tabla detectada. */
  get isFacturaType(): boolean {
    return this.document?.document_type === 'FACTURA';
  }
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
  private replicaTuningOverrides: ReplicaPresetTuningOverrides = {};
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private pollAttempts = 0;
  private readonly maxPollAttempts = 80;
  private readonly pollIntervalMs = 1500;
  private pollInFlight = false;
  private previewRequestId = 0;
  private tableRowsCache = new Map<string, string[][]>();
  private tableViewCache = new Map<string, TableViewModel>();
  private replicaLayoutCache = new Map<string, ReplicaLayoutView | null>();
  private paymentDetailCache = new Map<string, PaymentDetailViewModel | null>();

  constructor(private readonly route: ActivatedRoute, private readonly documents: DocumentsService) {
    this.replicaTuningOverrides = this.loadReplicaTuningOverrides();
    this.onReplicaPresetChange();
  }

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.load(id);
      this.loadLogs(id);
    }
  }

  ngOnDestroy(): void {
    this.stopProcessingPoll();
    this.revokePreviewFileUrl();
  }

  process(): void {
    if (!this.document) {
      return;
    }
    if (this.document.status === 'PROCESSING') {
      this.message = 'El documento ya esta en procesamiento.';
      return;
    }
    this.isProcessing = true;
    this.documents.process(this.document.id).subscribe({
      next: () => {
        this.message = 'Procesamiento en cola.';
        this.markDocumentAsProcessing();
        this.startProcessingPoll(this.document!.id);
        this.isProcessing = false;
      },
      error: () => {
        this.message = 'No se pudo procesar el documento.';
        this.isProcessing = false;
      }
    });
  }

  processAsFactura(): void {
    if (!this.document) {
      return;
    }
    if (this.document.status === 'PROCESSING') {
      this.message = 'El documento ya esta en procesamiento.';
      return;
    }
    this.isProcessing = true;
    this.documents.process(this.document.id, { forceDocumentType: 'FACTURA' }).subscribe({
      next: () => {
        this.message = 'Procesamiento en cola (tipo forzado FACTURA).';
        this.markDocumentAsProcessing();
        this.startProcessingPoll(this.document!.id);
        this.isProcessing = false;
      },
      error: () => {
        this.message = 'No se pudo procesar el documento como FACTURA.';
        this.isProcessing = false;
      }
    });
  }

  reprocess(): void {
    if (!this.document) {
      return;
    }
    if (this.document.status === 'PROCESSING') {
      this.message = 'El documento ya esta en procesamiento.';
      return;
    }
    this.isProcessing = true;
    this.documents.reprocess(this.document.id).subscribe({
      next: () => {
        this.message = 'Reprocesamiento solicitado.';
        this.markDocumentAsProcessing();
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
        this.tableRowsCache.clear();
        this.tableViewCache.clear();
        this.replicaLayoutCache.clear();
        this.paymentDetailCache.clear();
        this.loadPreview(data.id, data.mime_type ?? null, data.original_filename ?? '');
        this.displayFields = this.mapDisplayFields(this.document);
        this.syncTableRows();
        if (this.document.status === 'PROCESSING') {
          this.startProcessingPoll(this.document.id);
        } else {
          this.stopProcessingPoll();
        }
        this.isLoading = false;
      },
      error: () => {
        this.stopProcessingPoll();
        this.revokePreviewFileUrl();
        this.previewError = 'No se pudo cargar la vista previa.';
        this.tableView = { headerRows: [], bodyRows: [] };
        this.message = 'No se pudo cargar el documento.';
        this.isLoading = false;
      }
    });
  }

  reprocessAsFactura(): void {
    if (!this.document) {
      return;
    }
    if (this.document.status === 'PROCESSING') {
      this.message = 'El documento ya esta en procesamiento.';
      return;
    }
    this.isProcessing = true;
    this.documents.reprocess(this.document.id, { forceDocumentType: 'FACTURA' }).subscribe({
      next: () => {
        this.message = 'Reprocesamiento solicitado (tipo forzado FACTURA).';
        this.markDocumentAsProcessing();
        this.startProcessingPoll(this.document!.id);
        this.isProcessing = false;
      },
      error: () => {
        this.message = 'No se pudo reprocesar el documento como FACTURA.';
        this.isProcessing = false;
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

  downloadTableCsv(): void {
    if (!this.document || this.tableView.bodyRows.length === 0 || this.isDownloading) {
      return;
    }
    this.isDownloading = true;
    const baseName = (this.document.original_filename || 'documento')
      .replace(/\.[^/.]+$/, '')
      .trim();
    const filename = baseName ? `${baseName}-tabla.csv` : 'documento-tabla.csv';
    const csvRows = flattenTableView(this.tableView);
    const csvContent = buildCsv(csvRows);
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    window.URL.revokeObjectURL(url);
    this.isDownloading = false;
  }

  downloadTableExcel(): void {
    if (!this.document || this.tableView.bodyRows.length === 0 || this.isDownloading) {
      return;
    }
    this.isDownloading = true;
    const baseName = (this.document.original_filename || 'documento')
      .replace(/\.[^/.]+$/, '')
      .trim();
    const filename = baseName ? `${baseName}-tabla.xls` : 'documento-tabla.xls';
    const rows = flattenTableView(this.tableView);
    const xml = buildExcelXml(rows, { reportMode: this.tableRenderMode === 'report' });
    const blob = new Blob([xml], { type: 'application/vnd.ms-excel;charset=utf-8;' });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    window.URL.revokeObjectURL(url);
    this.isDownloading = false;
  }

  downloadTablePdfReport(): void {
    if (!this.document || this.tableView.bodyRows.length === 0 || this.isDownloading) {
      return;
    }
    this.isDownloading = true;
    const baseName = (this.document.original_filename || 'documento')
      .replace(/\.[^/.]+$/, '')
      .trim();
    const filename = baseName ? `${baseName}-tabla.pdf` : 'documento-tabla.pdf';
    const title = `Reporte de tabla - ${this.document.original_filename || 'documento'}`;
    const bytes = buildTablePdfBytes(title, this.tableView);
    const buffer = new ArrayBuffer(bytes.byteLength);
    new Uint8Array(buffer).set(bytes);
    const blob = new Blob([buffer], { type: 'application/pdf' });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    window.URL.revokeObjectURL(url);
    this.isDownloading = false;
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
      title: 'BMPI',
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
      title: 'BMPI',
      tableView: this.tableView,
      replicaLayout,
      replicaText,
      paymentDetail,
    });
    this.openPrintableHtml(
      html,
      'No se pudo abrir la ventana de impresion. Revisa el bloqueador de popups.'
    );
  }

  toggleTableRenderMode(): void {
    this.tableRenderMode = this.tableRenderMode === 'report' ? 'standard' : 'report';
  }

  private mapDisplayFields(document: DocumentDetail): DocumentDetail['fields'] {
    const onlyTableMode = this.isAdvancedNominaTableOnlyMode(document);
    const template = DOCUMENT_FIELD_TEMPLATES[document.document_type];
    if (!template) {
      const visibleFields = document.fields.filter((field) => !this.isHiddenField(field.key));
      return onlyTableMode ? this.keepOnlyTableField(visibleFields) : visibleFields;
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
    if (document.document_type === 'FACTURA') {
      return onlyTableMode ? this.keepOnlyTableField(mappedFromTemplate) : mappedFromTemplate;
    }

    const templateKeys = new Set(template.map((field) => field.key.toLowerCase()));
    const extras = document.fields.filter(
      (field) => !templateKeys.has(field.key.toLowerCase()) && !this.isHiddenField(field.key)
    );
    const merged = [...mappedFromTemplate, ...extras];
    return onlyTableMode ? this.keepOnlyTableField(merged) : merged;
  }

  private isAdvancedNominaTableOnlyMode(document: DocumentDetail): boolean {
    const tableField = document.fields.find((field) => isTableCellsField(field));
    if (!tableField) {
      return false;
    }

    const rawValue = String(tableField.corrected_value ?? tableField.value ?? '').trim();
    if (!rawValue) {
      return false;
    }

    const rows = parseTableRows(rawValue);
    if (rows.length < 3) {
      return false;
    }

    const tableView = buildTableView(rows);
    return detectTableLayoutMode(tableView) === 'advanced_nomina' && tableView.bodyRows.length >= 2;
  }

  private keepOnlyTableField(fields: DocumentDetail['fields']): DocumentDetail['fields'] {
    const tableFields = fields.filter((field) => this.isTableField(field));
    return tableFields.length ? tableFields : fields;
  }

  private isHiddenField(key: string | null | undefined): boolean {
    return DocumentsDetailPage.HIDDEN_FIELD_KEYS.has(String(key ?? '').toLowerCase());
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
    }, this.pollIntervalMs);
  }

  private markDocumentAsProcessing(): void {
    if (!this.document) {
      return;
    }

    this.document = {
      ...this.document,
      status: 'PROCESSING'
    };
  }

  private stopProcessingPoll(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
    this.pollInFlight = false;
  }

  private loadPreview(id: string, mimeType: string | null, filename: string): void {
    this.previewRequestId += 1;
    const requestId = this.previewRequestId;
    this.isPreviewLoading = true;
    this.previewError = null;
    this.previewMimeType = mimeType;
    this.revokePreviewFileUrl();

    this.documents.downloadFile(id).subscribe({
      next: (blob) => {
        if (requestId !== this.previewRequestId) {
          return;
        }
        this.previewMimeType = this.resolveMimeType(mimeType, blob.type, filename);
        this.previewFileUrl = window.URL.createObjectURL(blob);
        this.isPreviewLoading = false;
      },
      error: () => {
        if (requestId !== this.previewRequestId) {
          return;
        }
        this.previewError = 'No se pudo mostrar el archivo en pantalla.';
        this.isPreviewLoading = false;
      }
    });
  }

  private revokePreviewFileUrl(): void {
    if (!this.previewFileUrl) {
      return;
    }
    window.URL.revokeObjectURL(this.previewFileUrl);
    this.previewFileUrl = null;
  }

  private resolveMimeType(primary: string | null, fallback: string | null, filename: string): string | null {
    if (primary && primary.trim()) {
      return primary;
    }
    if (fallback && fallback.trim()) {
      return fallback;
    }
    const lower = filename.toLowerCase();
    if (lower.endsWith('.pdf')) {
      return 'application/pdf';
    }
    if (lower.endsWith('.png')) {
      return 'image/png';
    }
    if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) {
      return 'image/jpeg';
    }
    return null;
  }

  private openPrintableHtml(html: string, popupErrorMessage: string): void {
    const blob = new Blob([html], { type: 'text/html;charset=utf-8;' });
    const url = window.URL.createObjectURL(blob);
    const targetWindow = window.open(url, '_blank');
    if (!targetWindow) {
      this.message = popupErrorMessage;
      window.URL.revokeObjectURL(url);
      return;
    }
    setTimeout(() => {
      window.URL.revokeObjectURL(url);
    }, 10000);
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

  typeLabel(type: DocumentDetail['document_type']): string {
    return getDocumentTypeLabel(type);
  }

  isTableField(field: DocumentDetail['fields'][number]): boolean {
    return isTableCellsField(field);
  }

  isPdfReplicaField(field: DocumentDetail['fields'][number]): boolean {
    return String(field.key ?? '').toLowerCase() === 'replica_pdf_texto';
  }

  isPdfReplicaLayoutField(field: DocumentDetail['fields'][number]): boolean {
    return String(field.key ?? '').toLowerCase() === 'replica_pdf_layout';
  }

  isPaymentDetailField(field: DocumentDetail['fields'][number]): boolean {
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
    this.message = `Calibracion aplicada para preset ${this.selectedReplicaPreset}.`;
  }

  resetReplicaCalibrationPreset(): void {
    delete this.replicaTuningOverrides[this.selectedReplicaPreset];
    this.persistReplicaTuningOverrides();
    this.replicaLayoutCache.clear();
    this.onReplicaPresetChange();
    this.calibrationStatus = `Preset ${this.selectedReplicaPreset} restaurado.`;
    this.message = `Preset ${this.selectedReplicaPreset} restaurado.`;
  }

  resetReplicaCalibrationAll(): void {
    this.replicaTuningOverrides = {};
    this.persistReplicaTuningOverrides();
    this.replicaLayoutCache.clear();
    this.onReplicaPresetChange();
    this.calibrationStatus = 'Calibracion global restaurada.';
    this.message = 'Calibracion global restaurada.';
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

  replicaLayoutForField(field: DocumentDetail['fields'][number]): ReplicaLayoutView | null {
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

  paymentDetailForField(field: DocumentDetail['fields'][number]): PaymentDetailViewModel | null {
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
        DocumentsDetailPage.REPLICA_TUNING_STORAGE_KEY,
        JSON.stringify(this.replicaTuningOverrides)
      );
    } catch {
      // Ignore persistence errors in restricted contexts.
    }
  }

  private loadReplicaTuningOverrides(): ReplicaPresetTuningOverrides {
    try {
      const raw = window.localStorage.getItem(DocumentsDetailPage.REPLICA_TUNING_STORAGE_KEY);
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

  tableRowsForField(field: DocumentDetail['fields'][number]): string[][] {
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

  tableViewForField(field: DocumentDetail['fields'][number]): TableViewModel {
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
    return this.tableRenderMode === 'report' ? 'Vista cuadrícula' : 'Vista reporte';
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

