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
        <input type="text" [(ngModel)]="query.q" placeholder="Buscar por nombre" />
        <select [(ngModel)]="query.status">
          <option value="">Estado</option>
          <option *ngFor="let status of statusOptions" [value]="status">{{ status }}</option>
        </select>
        <select [(ngModel)]="query.type">
          <option value="">Tipo</option>
          <option *ngFor="let type of typeOptions" [value]="type">{{ type }}</option>
        </select>
        <button type="button" (click)="load()">Filtrar</button>
      </div>
      <div class="list" *ngIf="documents.length; else empty">
        <a class="card" *ngFor="let doc of documents" [routerLink]="['/documents', doc.id]">
          <div>
            <h3>{{ doc.original_filename }}</h3>
            <p>{{ doc.document_type }}</p>
          </div>
          <app-status-badge [status]="doc.status" />
        </a>
      </div>
      <ng-template #empty>
        <p>No hay documentos aún.</p>
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
    `
  ]
})
export class DocumentsListPage implements OnInit {
  documents: DocumentSummary[] = [];
  query = {
    status: '',
    type: '',
    q: ''
  };
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
    this.documentsService.list(this.query).subscribe({
      next: (data) => (this.documents = data),
      error: () => (this.documents = [])
    });
  }
}
