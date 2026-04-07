import { CommonModule } from '@angular/common';
import { Component, OnDestroy, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { DocumentProcessOptions, DocumentsService } from '../services/documents.service';
import {
  DOCUMENT_TYPE_LABELS,
  DocumentStatus,
  DocumentDetail,
  DocumentSummary,
  getDocumentTypeLabel
} from '../../../shared/models/document.models';
import { parsePaymentDetail } from '../utils/payment-detail';

const STATUS_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'Todos los estados' },
  { value: 'UPLOADED', label: 'Subidos' },
  { value: 'PROCESSING', label: 'Procesando' },
  { value: 'READY', label: 'Listos' },
  { value: 'NEEDS_REVIEW', label: 'Requieren revision' },
  { value: 'FAILED', label: 'Fallidos' }
];

const TYPE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'Todos los tipos' },
  ...Object.entries(DOCUMENT_TYPE_LABELS).map(([value, label]) => ({ value, label }))
];

@Component({
  selector: 'app-documents-list-page',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  template: `
    <section class="page-header">
      <div>
        <p class="eyebrow">Documentos</p>
        <h1>Bandeja operativa</h1>
        <p class="subtitle">
          Consulta estado, confianza y fecha de procesamiento sin salir del frontend.
        </p>
      </div>

      <a routerLink="/documents/upload" class="cta">Subir documento</a>
    </section>

    <section class="filters-card">
      <div class="field">
        <label for="search">Buscar</label>
        <input
          id="search"
          type="search"
          [(ngModel)]="searchTerm"
          (ngModelChange)="applyFilters()"
          placeholder="Archivo, tipo o id"
        />
      </div>

      <div class="field">
        <label for="status">Estado</label>
        <select id="status" [(ngModel)]="selectedStatus" (ngModelChange)="applyFilters()">
          <option *ngFor="let option of statusOptions" [value]="option.value">{{ option.label }}</option>
        </select>
      </div>

      <div class="field">
        <label for="type">Tipo</label>
        <select id="type" [(ngModel)]="selectedType" (ngModelChange)="applyFilters()">
          <option *ngFor="let option of typeOptions" [value]="option.value">{{ option.label }}</option>
        </select>
      </div>

      <button type="button" class="ghost" (click)="resetFilters()">Limpiar filtros</button>
    </section>

    <section class="table-card">
      <header class="table-head">
        <div>
          <p class="eyebrow">Resultados</p>
          <h2>{{ documents().length }} documentos</h2>
        </div>

        <div class="pagination-controls">
          <button type="button" class="ghost" (click)="prevPage()" [disabled]="page() === 1">Anterior</button>
          <span>Pagina {{ page() }}</span>
          <button type="button" class="ghost" (click)="nextPage()" [disabled]="!hasMore()">Siguiente</button>
        </div>
      </header>

      <div class="empty-state" *ngIf="isLoading()">Cargando documentos...</div>
      <div class="empty-state error" *ngIf="error()">{{ error() }}</div>
      <div class="empty-state" *ngIf="!isLoading() && !error() && documents().length === 0">
        <p>No hay documentos para mostrar.</p>
        <a routerLink="/documents/upload">Subir primer documento</a>
      </div>

      <div class="table-wrap" *ngIf="!isLoading() && !error() && documents().length">
        <table>
          <thead>
            <tr>
              <th>Archivo</th>
              <th>Tipo</th>
              <th>Estado</th>
              <th>Confianza</th>
              <th>Subido</th>
              <th>Procesado</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let document of documents()" class="row-link">
              <td>
                <strong>{{ document.original_filename }}</strong>
                <small>{{ document.id }}</small>
              </td>
              <td>{{ typeLabel(document.document_type) }}</td>
              <td>
                <span class="pill" [ngClass]="statusClass(document.status)">
                  {{ document.status }}
                </span>
              </td>
              <td>{{ confidenceLabel(document) }}</td>
              <td>{{ document.uploaded_at | date: 'medium' }}</td>
              <td>{{ document.processed_at ? (document.processed_at | date: 'medium') : 'Pendiente' }}</td>
              <td class="actions-cell">
                <button type="button" class="ghost" (click)="verDetalleDocumento(document)">
                  Ver detalle
                </button>
                <button
                  type="button"
                  class="ghost btn-reprocesar"
                  [disabled]="reprocesando()[document.id]"
                  (click)="reprocesarDocumento(document.id, $event)"
                >
                  {{ reprocesando()[document.id] ? 'Procesando...' : 'Reprocesar' }}
                </button>
                <button
                  *ngIf="document.document_type === 'DATOS_BANCARIOS'"
                  type="button"
                  class="ghost btn-factura"
                  [disabled]="reprocesando()[document.id]"
                  (click)="reprocesarDocumentoComoFactura(document.id, $event)"
                >
                  {{ reprocesando()[document.id] ? 'Procesando...' : 'Como Factura' }}
                </button>
                <button
                  type="button"
                  class="ghost btn-eliminar"
                  [disabled]="eliminando()[document.id]"
                  (click)="eliminarDocumento(document.id, $event)"
                >
                  {{ eliminando()[document.id] ? 'Eliminando...' : 'Eliminar' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="table-card" *ngIf="documentoSeleccionado() as seleccionado">
      <div class="section-head">
        <div>
          <p class="eyebrow">Detalle</p>
          <h2>Documento seleccionado</h2>
          <p class="subtitle">
            Vista rapida del documento procesado desde la bandeja operativa.
          </p>
        </div>

        <div class="detail-actions">
          <button
            type="button"
            class="ghost btn-reprocesar"
            [disabled]="reprocesando()[seleccionado.id] || seleccionado.status === 'PROCESSING'"
            (click)="reprocesarDocumento(seleccionado.id, $event)"
          >
            {{ reprocesando()[seleccionado.id] ? 'Procesando...' : 'Reprocesar' }}
          </button>
          <button
            *ngIf="seleccionado.document_type === 'DATOS_BANCARIOS'"
            type="button"
            class="ghost btn-factura"
            [disabled]="reprocesando()[seleccionado.id] || seleccionado.status === 'PROCESSING'"
            (click)="reprocesarDocumentoComoFactura(seleccionado.id, $event)"
          >
            {{ reprocesando()[seleccionado.id] ? 'Procesando...' : 'Reprocesar como Factura' }}
          </button>
          <button type="button" class="ghost" (click)="cerrarDetalle()">Cerrar</button>
        </div>
      </div>

      <div class="summary-grid">
        <article class="summary-item">
          <span>ID</span>
          <strong>{{ seleccionado.id }}</strong>
        </article>

        <article class="summary-item">
          <span>Archivo</span>
          <strong>{{ seleccionado.original_filename }}</strong>
        </article>

        <article class="summary-item">
          <span>Tipo</span>
          <strong>{{ typeLabel(seleccionado.document_type) }}</strong>
        </article>

        <article class="summary-item">
          <span>Estado</span>
          <strong>{{ seleccionado.status }}</strong>
        </article>

        <article class="summary-item">
          <span>Confianza</span>
          <strong>{{ confidenceLabel(seleccionado) }}</strong>
        </article>

        <article class="summary-item">
          <span>Procesado</span>
          <strong>{{ seleccionado.processed_at ? (seleccionado.processed_at | date: 'medium') : 'Pendiente' }}</strong>
        </article>
      </div>

      <p class="subtitle" *ngIf="cargandoDetalle()">Cargando detalle del documento...</p>

      <div *ngIf="!cargandoDetalle() && detalleDocumento()">
        <section class="summary-card">
          <h3>Resumen</h3>

          <div class="summary-grid" *ngIf="getResumenMetadata().length">
            <article class="summary-item" *ngFor="let item of getResumenMetadata()">
              <span>{{ item.key }}</span>
              <strong>{{ item.value }}</strong>
            </article>
          </div>
        </section>

        <section class="summary-card" *ngIf="getBeneficiariosTabla().filas.length">
          <h3>Validación financiera</h3>

          <div class="summary-grid">
            <article class="summary-item">
              <span>Importe total documento</span>
              <strong>{{ '$' + formatearMoneda(obtenerImporteTotalDetalle()) }}</strong>
            </article>

            <article class="summary-item">
              <span>Suma beneficiarios</span>
              <strong>{{ '$' + formatearMoneda(obtenerSumaBeneficiariosDetalle()) }}</strong>
            </article>

            <article class="summary-item">
              <span>Resultado</span>
              <strong [class.valid-ok]="validacionDetalleCorrecta()" [class.valid-fail]="!validacionDetalleCorrecta()">
                {{ textoValidacionDetalle() }}
              </strong>
            </article>
          </div>

          <div class="warning-list" *ngIf="getValidacionWarningsDetalle().length">
            <p class="warning-list__title">Observaciones detectadas</p>
            <ul>
              <li *ngFor="let warning of getValidacionWarningsDetalle()">{{ warning }}</li>
            </ul>
          </div>
        </section>

        <section class="table-card inner-card" *ngIf="getTablasDetalleRapido().length">
          <div class="section-head">
            <div>
              <p class="eyebrow">Tabla</p>
              <h3>Tablas detectadas</h3>
            </div>
          </div>

          <div class="table-block" *ngFor="let tabla of getTablasDetalleRapido(); let tableIndex = index">
            <h4>{{ tabla.titulo }}</h4>
            <div class="table-wrap">
              <table class="data-table">
                <thead>
                  <tr>
                    <th *ngFor="let col of tabla.columnas">{{ col }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr *ngFor="let fila of tabla.filas; let rowIndex = index" [class.alt]="rowIndex % 2 === 1">
                    <td *ngFor="let cell of fila">{{ cell }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </div>
    </section>
  `,
  styles: [
    `
      :host {
        display: grid;
        gap: 20px;
      }

      .page-header,
      .filters-card,
      .table-card {
        background: #ffffff;
        border-radius: 24px;
        border: 1px solid #dbe4f0;
        padding: 24px;
        box-shadow: 0 20px 45px rgba(15, 23, 42, 0.08);
      }

      .page-header {
        display: flex;
        justify-content: space-between;
        gap: 16px;
        align-items: center;
      }

      .eyebrow {
        margin: 0 0 8px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-size: 12px;
        color: #64748b;
      }

      h1,
      h2,
      .subtitle {
        margin: 0;
      }

      .subtitle {
        color: #475569;
        margin-top: 8px;
        max-width: 60ch;
        line-height: 1.5;
      }

      .cta,
      button {
        border: 0;
        border-radius: 999px;
        padding: 12px 18px;
        font-weight: 600;
        text-decoration: none;
        cursor: pointer;
      }

      .cta,
      button:not(.ghost) {
        background: #0f172a;
        color: #ffffff;
      }

      .ghost {
        background: #e2e8f0;
        color: #0f172a;
      }

      .filters-card {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 14px;
        align-items: end;
      }

      .field {
        display: grid;
        gap: 8px;
      }

      .field label {
        font-size: 14px;
        font-weight: 600;
        color: #334155;
      }

      .field input,
      .field select {
        padding: 12px;
        border-radius: 14px;
        border: 1px solid #cbd5e1;
        background: #f8fafc;
      }

      .table-head {
        display: flex;
        justify-content: space-between;
        gap: 16px;
        align-items: center;
        margin-bottom: 18px;
      }

      .pagination-controls {
        display: flex;
        align-items: center;
        gap: 10px;
      }

      .empty-state {
        padding: 18px;
        border-radius: 18px;
        background: #f8fafc;
        color: #475569;
      }

      .empty-state.error {
        background: #fee2e2;
        color: #b91c1c;
      }

      .table-wrap {
        overflow-x: auto;
      }

      table {
        width: 100%;
        border-collapse: collapse;
      }

      th,
      td {
        padding: 14px 12px;
        text-align: left;
        border-bottom: 1px solid #e2e8f0;
        vertical-align: top;
      }

      th {
        font-size: 13px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #64748b;
      }

      td strong,
      td small {
        display: block;
      }

      td small {
        margin-top: 4px;
        color: #64748b;
      }

      .row-link:hover {
        background: #f8fafc;
      }

      .pill {
        display: inline-flex;
        align-items: center;
        border-radius: 999px;
        padding: 6px 10px;
        font-size: 12px;
        font-weight: 700;
      }

      .status-ready {
        background: #dcfce7;
        color: #166534;
      }

      .status-processing {
        background: #dbeafe;
        color: #1d4ed8;
      }

      .status-review {
        background: #fef3c7;
        color: #92400e;
      }

      .status-failed {
        background: #fee2e2;
        color: #b91c1c;
      }

      .status-uploaded {
        background: #e2e8f0;
        color: #334155;
      }

      .actions-cell {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        align-items: center;
      }

      .btn-reprocesar {
        background: #dbeafe;
        color: #1d4ed8;
      }

      .btn-reprocesar:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }

      .btn-factura {
        background: #dcfce7;
        color: #166534;
      }

      .btn-factura:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }

      .btn-eliminar {
        background: #fee2e2;
        color: #b91c1c;
      }

      .btn-eliminar:disabled {
        opacity: 0.6;
        cursor: not-allowed;
      }

      .section-head {
        display: flex;
        justify-content: space-between;
        gap: 16px;
        align-items: flex-start;
        margin-bottom: 18px;
      }

      .detail-actions {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        justify-content: flex-end;
      }

      .summary-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 14px;
      }

      .summary-item {
        display: grid;
        gap: 6px;
        padding: 16px;
        border-radius: 18px;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
      }

      .summary-item span {
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #64748b;
      }

      .summary-item strong {
        color: #0f172a;
        word-break: break-word;
      }

      .summary-card {
        margin-top: 20px;
        padding: 20px;
        background: #ffffff;
        border: 1px solid #dbe4f0;
        border-radius: 20px;
      }

      .warning-list {
        margin-top: 16px;
        padding: 16px 18px;
        border-radius: 16px;
        background: #fff7ed;
        border: 1px solid #fdba74;
        color: #9a3412;
      }

      .warning-list__title {
        margin: 0 0 10px;
        font-size: 13px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.06em;
      }

      .warning-list ul {
        margin: 0;
        padding-left: 18px;
      }

      .warning-list li + li {
        margin-top: 6px;
      }

      .inner-card {
        margin-top: 20px;
        padding: 20px;
        box-shadow: none;
      }

      .valid-ok {
        color: #166534;
        font-weight: 700;
      }

      .valid-fail {
        color: #b91c1c;
        font-weight: 700;
      }

      @media (max-width: 768px) {
        .page-header,
        .table-head,
        .section-head {
          flex-direction: column;
          align-items: stretch;
        }

        .pagination-controls {
          justify-content: space-between;
        }
      }
    `
  ]
})
export class DocumentsListPage implements OnInit, OnDestroy {
  readonly documentoSeleccionado = signal<DocumentSummary | null>(null);
  readonly detalleDocumento = signal<any | null>(null);
  readonly cargandoDetalle = signal(false);
  readonly documents = signal<DocumentSummary[]>([]);
  readonly isLoading = signal(true);
  readonly error = signal<string | null>(null);
  readonly page = signal(1);
  readonly hasMore = signal(false);
  readonly pageSize = 20;
  readonly reprocesando = signal<Record<string, boolean>>({});
  readonly eliminando = signal<Record<string, boolean>>({});

  searchTerm = '';
  selectedStatus = '';
  selectedType = '';

  readonly statusOptions = STATUS_OPTIONS;
  readonly typeOptions = TYPE_OPTIONS;

  private requestToken = 0;
  private readonly pollingTimers = new Map<string, ReturnType<typeof window.setTimeout>>();

  constructor(private readonly documentsService: DocumentsService) {}

  ngOnInit(): void {
    this.fetchDocuments();
  }

  ngOnDestroy(): void {
    this.clearAllPolling();
  }

  applyFilters(): void {
    this.page.set(1);
    this.fetchDocuments();
  }

  resetFilters(): void {
    this.searchTerm = '';
    this.selectedStatus = '';
    this.selectedType = '';
    this.page.set(1);
    this.fetchDocuments();
  }

  nextPage(): void {
    if (!this.hasMore()) {
      return;
    }

    this.page.update((page) => page + 1);
    this.fetchDocuments();
  }

  prevPage(): void {
    if (this.page() === 1) {
      return;
    }

    this.page.update((page) => Math.max(1, page - 1));
    this.fetchDocuments();
  }

  verDetalleDocumento(document: DocumentSummary): void {
    this.documentoSeleccionado.set(document);
    this.detalleDocumento.set(null);
    this.cargandoDetalle.set(true);

    this.documentsService.getById(document.id).subscribe({
      next: (detail) => {
        console.log('DETALLE DOCUMENTO COMPLETO:', detail);
        console.log('FIELDS:', detail?.fields);
        console.log('DETAIL JSON:', JSON.stringify(detail, null, 2));

        this.documentoSeleccionado.set(this.toSummary(detail));
        this.detalleDocumento.set(detail);
        this.cargandoDetalle.set(false);
      },
      error: (err) => {
        console.error('ERROR DETALLE DOCUMENTO:', err);
        this.detalleDocumento.set(null);
        this.cargandoDetalle.set(false);
      }
    });
  }

  cerrarDetalle(): void {
    this.documentoSeleccionado.set(null);
    this.detalleDocumento.set(null);
  }

  reprocesarDocumento(id: string, event: Event): void {
    event.stopPropagation();
    this.solicitarReproceso(id);
  }

  reprocesarDocumentoComoFactura(id: string, event: Event): void {
    event.stopPropagation();
    this.solicitarReproceso(id, { forceDocumentType: 'FACTURA' });
  }

  private solicitarReproceso(id: string, options?: DocumentProcessOptions): void {
    if (this.reprocesando()[id]) {
      return;
    }

    this.stopPolling(id);
    this.reprocesando.update((r) => ({ ...r, [id]: true }));
    this.marcarDocumentoComoProcesando(id);

    this.documentsService.reprocess(id, options).subscribe({
      next: () => {
        this.fetchDocuments();
        this.scheduleStatusPoll(id);
      },
      error: () => {
        this.reprocesando.update((r) => ({ ...r, [id]: false }));
        alert('No se pudo reprocesar el documento. Intenta de nuevo.');
      }
    });
  }

  eliminarDocumento(id: string, event: Event): void {
    event.stopPropagation();
    if (this.eliminando()[id]) return;
    if (!confirm('¿Eliminar este documento? Esta acción no se puede deshacer.')) return;
    this.eliminando.update((r) => ({ ...r, [id]: true }));
    this.documentsService.delete(id).subscribe({
      next: () => {
        this.eliminando.update((r) => ({ ...r, [id]: false }));
        if (this.documentoSeleccionado()?.id === id) {
          this.documentoSeleccionado.set(null);
          this.detalleDocumento.set(null);
        }
        this.fetchDocuments();
      },
      error: () => {
        this.eliminando.update((r) => ({ ...r, [id]: false }));
        alert('No se pudo eliminar el documento. Intenta de nuevo.');
      }
    });
  }

  typeLabel(type: DocumentSummary['document_type']): string {
    return getDocumentTypeLabel(type);
  }

  confidenceLabel(document: DocumentSummary): string {
    if (document.confidence === null || document.confidence === undefined) {
      return 'Pendiente';
    }

    return `${Math.round(document.confidence * 100)}%`;
  }

  getFieldValue(key: string): string {
    const fields = this.detalleDocumento()?.fields ?? [];
    const field = fields.find((item: any) => String(item.key ?? '').toLowerCase() === key.toLowerCase());
    return String(field?.corrected_value ?? field?.value ?? '').trim();
  }

  getResumenMetadata(): Array<{ key: string; value: string }> {
    return this.getParsedPaymentDetail()?.metadataEntries ?? [];
  }

  obtenerImporteTotalDetalle(): number {
    return this.getParsedPaymentDetail()?.expectedTotalAmount ?? 0;
  }

  obtenerSumaBeneficiariosDetalle(): number {
    return this.getParsedPaymentDetail()?.extractedTotalAmount ?? 0;
  }

  validacionDetalleCorrecta(): boolean {
    return this.getParsedPaymentDetail()?.totalsMatch === true;
  }

  textoValidacionDetalle(): string {
    const paymentDetail = this.getParsedPaymentDetail();
    if (!paymentDetail) {
      return 'SIN DATOS';
    }
    if (paymentDetail.totalsMatch === true) {
      return 'VALIDACION CORRECTA';
    }
    if (paymentDetail.expectedTotalAmount === null) {
      return paymentDetail.validationWarnings.length ? 'REVISAR OBSERVACIONES' : 'SIN TOTAL DE CONTROL';
    }
    return 'NO COINCIDE';
  }

  getValidacionWarningsDetalle(): string[] {
    return this.getParsedPaymentDetail()?.validationWarnings ?? [];
  }

  formatearMoneda(valor: number): string {
    return valor.toLocaleString('es-MX', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }

  getBeneficiariosTabla(): { columnas: string[]; filas: string[][] } {
    const tablas = this.getTablasDetalleRapido();
    return tablas[0] ?? { columnas: [], filas: [] };
  }

  getTablasDetalleRapido(): Array<{ titulo: string; columnas: string[]; filas: string[][] }> {
    const rawPagoDetalle = this.getFieldValue('pago_detalle');
    const rawTablaCeldas = this.getFieldValue('tabla_celdas');
    const raw = rawPagoDetalle || rawTablaCeldas;

    const parsedPaymentDetail = parsePaymentDetail(raw);
    if (parsedPaymentDetail) {
      const tablas: Array<{ titulo: string; columnas: string[]; filas: string[][] }> = [];

      if (parsedPaymentDetail.canonicalRows.length) {
        tablas.push({
          titulo: 'Beneficiarios',
          columnas: parsedPaymentDetail.canonicalColumns,
          filas: parsedPaymentDetail.canonicalRows
        });
      }

      for (const summaryTable of parsedPaymentDetail.summaryTables) {
        if (!summaryTable.rows.length) {
          continue;
        }

        tablas.push({
          titulo: summaryTable.title || `Tabla ${tablas.length + 1}`,
          columnas: summaryTable.columns,
          filas: summaryTable.rows
        });
      }

      if (tablas.length) {
        return tablas;
      }
    }

    const extractedTables = this.detalleDocumento()?.tables ?? [];
    const structuredTables = extractedTables
      .filter((table: any) =>
        Array.isArray(table?.columns) &&
        table.columns.length > 0 &&
        Array.isArray(table?.rows) &&
        table.rows.length > 0
      )
      .map((table: any, index: number) => {
        const columnas = table.columns.map((col: unknown) => {
          const text = String(col ?? '').trim();
          return /^col_\d+$/i.test(text) ? text.toUpperCase() : this.formatearClave(text);
        });
        const filas = table.rows
          .map((row: Record<string, unknown>) =>
            table.columns.map((col: string) => String(row?.[col] ?? ''))
          )
          .filter((fila: string[]) => fila.some((cell) => String(cell ?? '').trim().length > 0));

        return {
          titulo: table.doc_type_hint ? `Tabla ${index + 1} - ${table.doc_type_hint}` : `Tabla ${index + 1}`,
          columnas,
          filas
        };
      })
      .filter((table: { columnas: string[]; filas: string[][] }) => table.columnas.length && table.filas.length);

    if (structuredTables.length) {
      return structuredTables;
    }

    if (!raw) {
      return [];
    }

    try {
      const parsed = JSON.parse(raw);

      const nestedCanonicalRows = Array.isArray(parsed?.table?.canonical_rows)
        ? parsed.table.canonical_rows
        : [];
      const nestedCanonicalColumnsRaw = Array.isArray(parsed?.table?.canonical_columns)
        ? parsed.table.canonical_columns
        : [];
      const nestedDisplayColumns = parsed?.table?.display_columns ?? {};

      if (nestedCanonicalRows.length) {
        const nestedCanonicalColumns = nestedCanonicalColumnsRaw
          .map((value: unknown) => String(value ?? '').trim())
          .filter((value: string) => value.length > 0);

        const orderedKeys = nestedCanonicalColumns.length
          ? nestedCanonicalColumns
          : Object.keys(nestedCanonicalRows[0] ?? {});

        const columnas = orderedKeys.map((key: string) =>
          String(nestedDisplayColumns[key] ?? this.formatearClave(key))
        );

        const filas = nestedCanonicalRows
          .filter((row: any) => row && typeof row === 'object')
          .map((row: any) => orderedKeys.map((key: string) => String(row?.[key] ?? '')))
          .filter((fila: string[]) => fila.some((cell) => String(cell ?? '').trim().length > 0));

        if (filas.length) {
          return [{ titulo: 'Beneficiarios', columnas, filas }];
        }
      }

      if (Array.isArray(parsed?.canonical_rows) && parsed.canonical_rows.length) {
        const displayColumns = parsed?.display_columns ?? {};

        const orderedKeys = [
          'clave_beneficiario',
          'nombre',
          'importe',
          'fecha_aplicacion',
          'referencia',
          'cuenta_beneficiario',
          'banco_receptor',
          'dias_vigencia',
          'concepto_pago'
        ];

        const columnas = orderedKeys.map((key) =>
          String(displayColumns[key] ?? this.formatearClave(key))
        );

        const filas = parsed.canonical_rows
          .filter((row: any) => {
            const clave = String(row?.clave_beneficiario ?? '').trim().toUpperCase();
            const nombre = String(row?.nombre ?? '').trim().toUpperCase();
            const importe = String(row?.importe ?? '').trim();
            const concepto = String(row?.concepto_pago ?? '').trim();

            if (!importe && !concepto && !clave && !nombre) {
              return false;
            }

            if (clave.startsWith('CANTIDAD') || clave.startsWith('TOTAL')) {
              return false;
            }

            if (nombre.startsWith('CANTIDAD') || nombre.startsWith('TOTAL')) {
              return false;
            }

            if (importe === '0' && !concepto && !clave && !nombre) {
              return false;
            }

            return true;
          })
          .map((row: any) => orderedKeys.map((key) => String(row?.[key] ?? '')));

        return [{ titulo: 'Beneficiarios', columnas, filas }];
      }

      if (Array.isArray(parsed?.rows) && parsed.rows.length) {
        const rows = parsed.rows as string[][];
        if (!rows.length) {
          return [];
        }

        const columnas = rows[0].map((c) => String(c ?? ''));
        const filas = rows.slice(1);

        return [{ titulo: 'Tabla 1', columnas, filas }];
      }

      return [];
    } catch {
      return [];
    }
  }

  private convertirImporteANumero(valor: string): number {
    if (!valor) {
      return 0;
    }

    const limpio = String(valor)
      .replace(/\$/g, '')
      .replace(/,/g, '')
      .trim();

    const numero = parseFloat(limpio);

    return isNaN(numero) ? 0 : numero;
  }

  private getParsedPaymentDetail() {
    const rawPagoDetalle = this.getFieldValue('pago_detalle');
    const rawTablaCeldas = this.getFieldValue('tabla_celdas');
    return parsePaymentDetail(rawPagoDetalle || rawTablaCeldas);
  }

  private normalizarTexto(valor: string): string {
    return String(valor ?? '')
      .trim()
      .toLowerCase()
      .replace(/\s+/g, ' ');
  }

  private formatearClave(valor: string): string {
    return String(valor ?? '')
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (l) => l.toUpperCase());
  }

  statusClass(status: DocumentStatus): string {
    switch (status) {
      case 'READY':
        return 'status-ready';
      case 'PROCESSING':
        return 'status-processing';
      case 'NEEDS_REVIEW':
        return 'status-review';
      case 'FAILED':
        return 'status-failed';
      default:
        return 'status-uploaded';
    }
  }

  private fetchDocuments(): void {
    this.isLoading.set(true);
    this.error.set(null);
    const token = ++this.requestToken;

    this.documentsService
      .list({
        q: this.searchTerm.trim() || undefined,
        status: this.selectedStatus || undefined,
        type: this.selectedType || undefined,
        page: this.page(),
        pageSize: this.pageSize
      })
      .subscribe({
        next: (data) => {
          if (token !== this.requestToken) {
            return;
          }

          this.documents.set(data);
          this.syncSelectedSummaryFromList(data);
          this.hasMore.set(data.length === this.pageSize);
          this.isLoading.set(false);
        },
        error: (err) => {
          if (token !== this.requestToken) {
            return;
          }

          this.documents.set([]);
          this.hasMore.set(false);
          this.error.set(this.resolveErrorMessage(err, 'No se pudieron cargar los documentos.'));
          this.isLoading.set(false);
        }
      });
  }

  private resolveErrorMessage(error: unknown, fallback: string): string {
    if (!error) {
      return fallback;
    }

    if (typeof error === 'string') {
      return error;
    }

    if (error instanceof Error && error.message.trim().length) {
      return error.message;
    }

    const typedError = error as { error?: unknown; message?: string } | undefined;
    if (typeof typedError?.message === 'string' && typedError.message.trim().length) {
      return typedError.message;
    }

    if (typeof typedError?.error === 'string' && typedError.error.trim().length) {
      return typedError.error;
    }

    if (typeof typedError?.error === 'object' && typedError.error && 'message' in typedError.error) {
      const nested = (typedError.error as { message?: string }).message;
      if (typeof nested === 'string' && nested.trim().length) {
        return nested;
      }
    }

    return fallback;
  }

  private marcarDocumentoComoProcesando(id: string): void {
    this.documents.update((items) =>
      items.map((item) =>
        item.id === id
          ? {
              ...item,
              status: 'PROCESSING' as DocumentStatus
            }
          : item
      )
    );

    const selected = this.documentoSeleccionado();
    if (selected?.id === id) {
      this.documentoSeleccionado.set({
        ...selected,
        status: 'PROCESSING'
      });
      this.detalleDocumento.set(null);
      this.cargandoDetalle.set(true);
    }
  }

  private scheduleStatusPoll(id: string, delayMs = 1500): void {
    this.stopPolling(id);
    const timer = window.setTimeout(() => {
      this.documentsService.getProcessStatus(id).subscribe({
        next: (status) => {
          const summaryPatch: Partial<DocumentSummary> = {
            status: status.status,
            document_type: status.document_type,
            confidence: status.confidence
          };
          this.updateDocumentSummary(id, summaryPatch);

          if (status.status === 'PROCESSING' || status.status === 'UPLOADED') {
            this.scheduleStatusPoll(id, 1500);
            return;
          }

          this.stopPolling(id);
          this.reprocesando.update((state) => ({ ...state, [id]: false }));
          this.fetchDocuments();
          if (this.documentoSeleccionado()?.id === id) {
            this.loadDetalleDocumento(id);
          }
        },
        error: () => {
          this.scheduleStatusPoll(id, 2000);
        }
      });
    }, delayMs);

    this.pollingTimers.set(id, timer);
  }

  private stopPolling(id: string): void {
    const timer = this.pollingTimers.get(id);
    if (timer !== undefined) {
      window.clearTimeout(timer);
      this.pollingTimers.delete(id);
    }
  }

  private clearAllPolling(): void {
    this.pollingTimers.forEach((timer) => window.clearTimeout(timer));
    this.pollingTimers.clear();
  }

  private loadDetalleDocumento(id: string): void {
    this.cargandoDetalle.set(true);
    this.documentsService.getById(id).subscribe({
      next: (detail) => {
        this.documentoSeleccionado.set(this.toSummary(detail));
        this.detalleDocumento.set(detail);
        this.cargandoDetalle.set(false);
      },
      error: () => {
        this.cargandoDetalle.set(false);
      }
    });
  }

  private syncSelectedSummaryFromList(data: DocumentSummary[]): void {
    const selectedId = this.documentoSeleccionado()?.id;
    if (!selectedId) {
      return;
    }

    const updated = data.find((item) => item.id === selectedId);
    if (updated) {
      this.documentoSeleccionado.set(updated);
    }
  }

  private updateDocumentSummary(id: string, patch: Partial<DocumentSummary>): void {
    this.documents.update((items) =>
      items.map((item) => (item.id === id ? { ...item, ...patch } : item))
    );

    const selected = this.documentoSeleccionado();
    if (selected?.id === id) {
      this.documentoSeleccionado.set({
        ...selected,
        ...patch
      });
    }
  }

  private toSummary(detail: DocumentDetail): DocumentSummary {
    return {
      id: detail.id,
      original_filename: detail.original_filename,
      status: detail.status,
      document_type: detail.document_type,
      confidence: detail.confidence,
      uploaded_at: detail.uploaded_at,
      processed_at: detail.processed_at
    };
  }
}
