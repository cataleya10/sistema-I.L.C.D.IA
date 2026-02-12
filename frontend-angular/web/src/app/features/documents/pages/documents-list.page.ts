import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { StatusBadgeComponent } from '../../../shared/components/status-badge.component';
import { DocumentsService } from '../services/documents.service';
import { DocumentSummary, DocumentStatus, DocumentType } from '../../../shared/models/document.models';

@Component({
  selector: 'app-documents-list-page',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule, StatusBadgeComponent],
  template: `
    <section class="page">
      <header>
        <h2>Bandeja de documentos</h2>
        <p>Historial con estado del procesamiento.</p>
      </header>
      <div class="filters">
        <input type="text" [(ngModel)]="query.q" placeholder="Buscar por nombre" aria-label="Buscar por nombre" />
        <select [(ngModel)]="query.status" aria-label="Filtrar por estado">
          <option value="">Estado</option>
          <option *ngFor="let status of statusOptions" [value]="status">{{ status }}</option>
        </select>
        <select [(ngModel)]="query.type" aria-label="Filtrar por tipo">
          <option value="">Tipo</option>
          <option *ngFor="let type of typeOptions" [value]="type">{{ type }}</option>
        </select>
        <button type="button" (click)="applyFilters()" [disabled]="isLoading">Filtrar</button>
      </div>
      <div class="loading" *ngIf="isLoading">Cargando documentos...</div>
      <div class="error" *ngIf="errorMessage && !isLoading" role="alert">
        <span>{{ errorMessage }}</span>
        <button type="button" class="ghost" (click)="load()">Reintentar</button>
      </div>
      <div class="list" *ngIf="documents.length && !isLoading; else empty">
        <div class="card" *ngFor="let doc of documents">
          <a class="card-link" [routerLink]="['/documents', doc.id]">
            <div>
              <h3>{{ doc.original_filename }}</h3>
              <p>{{ doc.document_type }}</p>
            </div>
            <app-status-badge [status]="doc.status" />
          </a>
          <button
            type="button"
            class="danger"
            (click)="confirmDelete(doc, $event)"
            [disabled]="isLoading"
          >
            Eliminar
          </button>
        </div>
      </div>
      <div class="pagination">
        <button type="button" class="ghost" (click)="prevPage()" [disabled]="page <= 1 || isLoading">Anterior</button>
        <span>Pagina {{ page }}</span>
        <button type="button" class="ghost" (click)="nextPage()" [disabled]="isLoading || !hasNextPage">Siguiente</button>
      </div>
      <ng-template #empty>
        <div class="empty" *ngIf="!isLoading && !errorMessage">
          <p>No hay documentos aun.</p>
          <a routerLink="/documents/upload">Subir primer documento</a>
        </div>
      </ng-template>
    </section>
  `,
  styles: [
    `
      .page {
        display: grid;
        gap: 20px;
      }
      .filters {
        display: grid;
        grid-template-columns: 2fr 1fr 1fr auto;
        gap: 12px;
      }
      .loading {
        font-size: 13px;
        color: #6b7280;
      }
      .error {
        font-size: 13px;
        color: #b91c1c;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
      }
      input,
      select {
        padding: 8px 12px;
        border-radius: 8px;
        border: 1px solid #e5e7eb;
      }
      button {
        padding: 8px 16px;
        border-radius: 999px;
        border: none;
        background: #4f46e5;
        color: #fff;
      }
      .pagination {
        display: flex;
        gap: 12px;
        align-items: center;
        flex-wrap: wrap;
      }
      .ghost {
        background: #e5e7eb;
        color: #111827;
      }
      .ghost[disabled] {
        opacity: 0.6;
      }
      .list {
        display: grid;
        gap: 12px;
      }
      .card {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: #fff;
        border-radius: 12px;
        border: 1px solid #e5e7eb;
        padding: 16px;
        gap: 12px;
      }
      .card-link {
        display: flex;
        flex: 1;
        justify-content: space-between;
        align-items: center;
        text-decoration: none;
        color: inherit;
      }
      h3 {
        margin: 0;
        font-size: 16px;
      }
      p {
        margin: 4px 0 0;
        color: #6b7280;
      }
      .danger {
        background: #ef4444;
        color: #fff;
        padding: 6px 12px;
        border-radius: 10px;
        border: none;
        font-size: 12px;
      }
      .danger[disabled] {
        opacity: 0.6;
      }
      .empty {
        display: grid;
        gap: 6px;
      }
      .empty p {
        margin: 0;
      }
      .empty a {
        color: #4f46e5;
        text-decoration: none;
        font-size: 13px;
      }
      @media (max-width: 960px) {
        .filters {
          grid-template-columns: 1fr;
        }
      }
    `
  ]
})
export class DocumentsListPage implements OnInit {
  documents: DocumentSummary[] = [];
  isLoading = false;
  errorMessage = '';
  hasNextPage = true;
  private requestToken = 0;
  query = {
    status: '',
    type: '',
    q: ''
  };
  page = 1;
  pageSize = 20;
  statusOptions: DocumentStatus[] = ['UPLOADED', 'PROCESSING', 'READY', 'NEEDS_REVIEW', 'FAILED'];
  typeOptions: DocumentType[] = [
    'INE',
    'CURP',
    'ACTA_NACIMIENTO',
    'COMPROBANTE_DOMICILIO',
    'NSS',
    'DATOS_BANCARIOS',
    'CONSTANCIA_SITUACION_FISCAL',
    'UNKNOWN'
  ];

  constructor(private readonly documentsService: DocumentsService) {}

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.isLoading = true;
    this.errorMessage = '';
    const token = ++this.requestToken;
    this.documentsService
      .list({
        ...this.query,
        page: this.page,
        pageSize: this.pageSize
      })
      .subscribe({
        next: (data) => {
          if (token !== this.requestToken) {
            return;
          }
          this.documents = data;
          this.hasNextPage = data.length === this.pageSize;
          this.isLoading = false;
        },
        error: (err) => {
          if (token !== this.requestToken) {
            return;
          }
          this.documents = [];
          this.hasNextPage = false;
          this.errorMessage = this.resolveErrorMessage(
            err,
            'No se pudo cargar la lista. Intenta de nuevo.'
          );
          this.isLoading = false;
        }
      });
  }

  applyFilters(): void {
    this.page = 1;
    this.load();
  }

  nextPage(): void {
    if (!this.hasNextPage) {
      return;
    }
    this.page += 1;
    this.load();
  }

  prevPage(): void {
    if (this.page <= 1) {
      return;
    }
    this.page -= 1;
    this.load();
  }

  confirmDelete(doc: DocumentSummary, event: Event): void {
    event.preventDefault();
    event.stopPropagation();
    const ok = window.confirm(`Eliminar "${doc.original_filename}"? Esta accion no se puede deshacer.`);
    if (!ok) {
      return;
    }
    this.isLoading = true;
    this.documentsService.delete(doc.id).subscribe({
      next: () => this.load(),
      error: (err) => {
        this.errorMessage = this.resolveErrorMessage(
          err,
          'No se pudo eliminar el documento. Intenta de nuevo.'
        );
        this.isLoading = false;
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
}


