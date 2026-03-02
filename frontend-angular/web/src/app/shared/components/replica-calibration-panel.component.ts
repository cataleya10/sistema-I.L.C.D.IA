import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';

export interface CalibrationFormModel {
  scaleX: number;
  scaleY: number;
  offsetX: number;
  offsetY: number;
  aspectShift: number;
  fontScale: number;
  lineHeight: string;
}

@Component({
  selector: 'app-replica-calibration-panel',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <section class="calibration-panel">
      <div class="calibration-panel__header">
        <h3>Calibracion replica PDF</h3>
        <p>Ajusta escala/margenes por banco y guarda localmente.</p>
        <p class="calibration-status">Banco detectado: {{ detectedBankLabel }}</p>
      </div>
      <div class="calibration-panel__controls">
        <label>
          Preset
          <select [(ngModel)]="selectedPreset" (ngModelChange)="presetChange.emit($event)">
            <option *ngFor="let preset of presetOptions; trackBy: trackByIndex" [ngValue]="preset">{{ preset }}</option>
          </select>
        </label>
        <label>
          Scale X
          <input type="number" step="0.005" [(ngModel)]="form.scaleX" />
        </label>
        <label>
          Scale Y
          <input type="number" step="0.005" [(ngModel)]="form.scaleY" />
        </label>
        <label>
          Offset X
          <input type="number" step="0.1" [(ngModel)]="form.offsetX" />
        </label>
        <label>
          Offset Y
          <input type="number" step="0.1" [(ngModel)]="form.offsetY" />
        </label>
        <label>
          Aspect Shift
          <input type="number" step="0.1" [(ngModel)]="form.aspectShift" />
        </label>
        <label>
          Font Scale
          <input type="number" step="0.01" [(ngModel)]="form.fontScale" />
        </label>
        <label>
          Line Height
          <input type="text" [(ngModel)]="form.lineHeight" />
        </label>
      </div>
      <div class="calibration-panel__actions">
        <button type="button" class="ghost" (click)="apply.emit()">Aplicar calibracion</button>
        <button type="button" class="ghost" (click)="resetPreset.emit()">Reset preset</button>
        <button type="button" class="ghost" (click)="resetAll.emit()">Reset total</button>
        <button type="button" class="ghost" (click)="exportJson.emit()">Exportar JSON</button>
        <button type="button" class="ghost" (click)="fileInput.click()">Importar JSON</button>
        <input
          #fileInput
          class="calibration-file"
          type="file"
          accept="application/json,.json"
          (change)="importJson.emit($event)"
        />
      </div>
      <p class="calibration-status" *ngIf="status">{{ status }}</p>
    </section>
  `,
  styles: [`
    .calibration-panel {
      background: #fff;
      border: 1px solid #e5e7eb;
      border-radius: 12px;
      padding: 16px;
      display: grid;
      gap: 12px;
    }
    .calibration-panel__header h3 { margin: 0; }
    .calibration-panel__header p { margin: 4px 0 0; font-size: 12px; color: #6b7280; }
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
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .ghost {
      background: #e5e7eb;
      color: #111827;
      border: none;
      border-radius: 999px;
      padding: 8px 18px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
    }
    .calibration-file { display: none; }
    .calibration-status { font-size: 12px; color: #6b7280; }
    .calibration-panel__header .calibration-status { margin-top: 4px; }
  `]
})
export class ReplicaCalibrationPanelComponent {
  @Input() presetOptions: string[] = [];
  @Input() selectedPreset: any = '';
  @Input() form!: CalibrationFormModel;
  @Input() status: string | null = null;
  @Input() detectedBankLabel = '';

  @Output() presetChange = new EventEmitter<any>();
  @Output() apply = new EventEmitter<void>();
  @Output() resetPreset = new EventEmitter<void>();
  @Output() resetAll = new EventEmitter<void>();
  @Output() exportJson = new EventEmitter<void>();
  @Output() importJson = new EventEmitter<Event>();

  trackByIndex(index: number): number { return index; }
}
