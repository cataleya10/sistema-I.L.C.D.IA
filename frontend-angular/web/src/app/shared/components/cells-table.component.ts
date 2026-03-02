import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

export interface CellsTableViewModel {
  headerRows: string[][];
  bodyRows: string[][];
}

@Component({
  selector: 'app-cells-table',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="cells-table-wrap" *ngIf="tableView?.bodyRows?.length">
      <table class="cells-table" [ngClass]="{ 'report-mode': reportMode }">
        <thead *ngIf="tableView.headerRows.length">
          <tr *ngFor="let row of tableView.headerRows; trackBy: trackByIndex">
            <th *ngFor="let cell of row; trackBy: trackByIndex">{{ cell }}</th>
          </tr>
        </thead>
        <tbody>
          <tr *ngFor="let row of tableView.bodyRows; let rowIndex = index; trackBy: trackByIndex" [class.alt]="rowIndex % 2 === 1">
            <td *ngFor="let cell of row; trackBy: trackByIndex">{{ cell }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  `,
  styles: [`
    .cells-table-wrap {
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }
    .cells-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    .cells-table th,
    .cells-table td {
      padding: 6px 10px;
      border: 1px solid #e5e7eb;
      white-space: nowrap;
      text-align: left;
    }
    .cells-table th {
      background: #f3f4f6;
      font-weight: 600;
    }
    .cells-table tr.alt td {
      background: #f9fafb;
    }
    .cells-table tr:hover td {
      background: #eef2ff;
    }
    .cells-table.report-mode td {
      white-space: normal;
    }
  `]
})
export class CellsTableComponent {
  @Input() tableView!: CellsTableViewModel;
  @Input() reportMode = false;

  trackByIndex(index: number): number { return index; }
}
