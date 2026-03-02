import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';
import { CellsTableComponent, CellsTableViewModel } from './cells-table.component';

export interface PaymentDetailView {
  bank: string;
  metadataEntries: { key: string; value: string }[];
  canonicalColumns: string[];
  canonicalRows: string[][];
  summaryTables: { title: string; columns: string[]; rows: string[][] }[];
}

@Component({
  selector: 'app-payment-detail',
  standalone: true,
  imports: [CommonModule, CellsTableComponent],
  template: `
    <div class="payment-detail" *ngIf="detail">
      <p class="payment-detail__bank">Banco: {{ detail.bank }}</p>
      <div class="payment-detail__meta" *ngIf="detail.metadataEntries.length">
        <p class="payment-detail__meta-item" *ngFor="let meta of detail.metadataEntries; trackBy: trackByMetaKey">
          <strong>{{ meta.key }}:</strong> {{ meta.value }}
        </p>
      </div>
      <app-cells-table
        *ngIf="canonicalTableView.bodyRows.length"
        [tableView]="canonicalTableView"
      ></app-cells-table>
      <div class="payment-detail__summary" *ngFor="let summary of detail.summaryTables; trackBy: trackBySummaryTitle">
        <p class="payment-detail__summary-title">{{ summary.title }}</p>
        <app-cells-table [tableView]="summaryToTableView(summary)"></app-cells-table>
      </div>
    </div>
  `,
  styles: [`
    .payment-detail__bank {
      font-weight: 600;
      margin-bottom: 8px;
    }
    .payment-detail__meta {
      margin-bottom: 8px;
    }
    .payment-detail__meta-item {
      font-size: 12px;
      margin: 2px 0;
    }
    .payment-detail__summary {
      margin-top: 12px;
    }
    .payment-detail__summary-title {
      font-weight: 600;
      font-size: 13px;
      margin-bottom: 6px;
    }
  `]
})
export class PaymentDetailComponent {
  @Input() detail!: PaymentDetailView;

  get canonicalTableView(): CellsTableViewModel {
    if (!this.detail) return { headerRows: [], bodyRows: [] };
    return {
      headerRows: this.detail.canonicalColumns.length ? [this.detail.canonicalColumns] : [],
      bodyRows: this.detail.canonicalRows
    };
  }

  summaryToTableView(summary: { columns: string[]; rows: string[][] }): CellsTableViewModel {
    return {
      headerRows: summary.columns.length ? [summary.columns] : [],
      bodyRows: summary.rows
    };
  }

  trackByMetaKey(_: number, m: { key: string }): string { return m.key; }
  trackBySummaryTitle(_: number, s: { title: string }): string { return s.title; }
}
