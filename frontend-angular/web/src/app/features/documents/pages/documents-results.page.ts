import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { DocumentsService } from '../services/documents.service';
import { DocumentDetail, DocumentField } from '../../../shared/models/document.models';

@Component({
  selector: 'app-documents-results-page',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  template: `
    <section class="page" *ngIf="document">
      <header class="page__header">
        <div>
          <a class="back" routerLink="/documents">← Volver</a>
          <h2>Resultados extraídos</h2>
          <p>{{ document.original_filename }}</p>
        </div>
        <div class="actions">
          <button type="button" (click)="refresh()">Actualizar</button>
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
          <strong>{{ document.document_type }}</strong>
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
          <span>Válidos</span>
          <strong>{{ validCount }}</strong>
        </div>
        <div class="card">
          <span>Revisar</span>
          <strong>{{ invalidCount }}</strong>
        </div>
      </section>

      <section class="panel">
        <div class="panel__header">
          <div>
            <h3>Campos extraídos</h3>
            <p class="hint" *ngIf="document.needs_review">Revisión requerida por baja confianza o validación.</p>
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
              <td>{{ field.corrected_value ?? field.value ?? '-' }}</td>
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
    </section>
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
    `
  ]
})
export class DocumentsResultsPage implements OnInit {
  document: DocumentDetail | null = null;
  search = '';
  onlyInvalid = false;

  constructor(private readonly route: ActivatedRoute, private readonly documents: DocumentsService) {}

  get filteredFields(): DocumentField[] {
    if (!this.document) {
      return [];
    }
    const query = this.search.trim().toLowerCase();
    return this.document.fields.filter((field) => {
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
    return this.document?.fields.filter((field) => field.valid).length ?? 0;
  }

  get invalidCount(): number {
    return this.document?.fields.filter((field) => !field.valid).length ?? 0;
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
    this.documents.getById(id).subscribe({
      next: (data) => {
        this.document = {
          ...data,
          file_url: this.documents.getFileUrl(data.id)
        };
      }
    });
  }
}
