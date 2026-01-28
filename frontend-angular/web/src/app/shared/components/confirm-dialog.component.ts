import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';

@Component({
  selector: 'app-confirm-dialog',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="backdrop" *ngIf="open">
      <div class="dialog">
        <h3>{{ title }}</h3>
        <p>{{ message }}</p>
        <div class="actions">
          <button type="button" class="ghost" (click)="cancel.emit()">Cancelar</button>
          <button type="button" (click)="confirm.emit()">Confirmar</button>
        </div>
      </div>
    </div>
  `,
  styles: [
    `
      .backdrop {
        position: fixed;
        inset: 0;
        background: rgba(15, 23, 42, 0.6);
        display: grid;
        place-items: center;
        z-index: 50;
      }
      .dialog {
        background: #fff;
        border-radius: 16px;
        padding: 24px;
        width: min(420px, 90vw);
        display: grid;
        gap: 12px;
      }
      .actions {
        display: flex;
        justify-content: flex-end;
        gap: 12px;
      }
      button {
        padding: 8px 16px;
        border-radius: 999px;
        border: none;
        background: #4f46e5;
        color: #fff;
      }
      .ghost {
        background: #e5e7eb;
        color: #111827;
      }
    `
  ]
})
export class ConfirmDialogComponent {
  @Input() open = false;
  @Input() title = 'Confirmación';
  @Input() message = '¿Deseas continuar?';
  @Output() confirm = new EventEmitter<void>();
  @Output() cancel = new EventEmitter<void>();
}
