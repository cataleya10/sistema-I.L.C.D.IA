import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, OnChanges, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';

@Component({
  selector: 'app-field-editor',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="field">
      <label>{{ label }}</label>
      <input [(ngModel)]="currentValue" (ngModelChange)="emitChange($event)" />
      <div class="meta">
        <span [class.invalid]="!valid">{{ valid ? 'Válido' : 'Inválido' }}</span>
        <ng-container *ngIf="errors?.length">
          <span *ngFor="let err of errors">{{ err }}</span>
        </ng-container>
      </div>
    </div>
  `,
  styles: [
    `
      .field {
        display: grid;
        gap: 6px;
      }
      label {
        font-size: 13px;
        font-weight: 600;
        color: #111827;
      }
      input {
        border: 1px solid #d1d5db;
        border-radius: 8px;
        padding: 8px 12px;
      }
      .meta {
        display: flex;
        gap: 8px;
        font-size: 12px;
        color: #6b7280;
      }
      .invalid {
        color: #dc2626;
      }
    `
  ]
})
export class FieldEditorComponent implements OnChanges {
  @Input() label = '';
  @Input() value: string | null = null;
  @Input() valid = true;
  @Input() errors: string[] = [];
  @Output() valueChange = new EventEmitter<string>();

  currentValue = '';

  ngOnChanges(): void {
    this.currentValue = this.value ?? '';
  }

  emitChange(value: string): void {
    this.valueChange.emit(value);
  }
}
