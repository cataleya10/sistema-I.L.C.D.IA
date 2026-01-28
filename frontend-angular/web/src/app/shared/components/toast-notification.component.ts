import { CommonModule } from '@angular/common';
import { Component, EventEmitter, Input, Output } from '@angular/core';

@Component({
  selector: 'app-toast-notification',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="toast" *ngIf="message">
      <span>{{ message }}</span>
      <button type="button" (click)="dismiss.emit()">×</button>
    </div>
  `,
  styles: [
    `
      .toast {
        position: fixed;
        bottom: 24px;
        right: 24px;
        background: #111827;
        color: #fff;
        padding: 12px 16px;
        border-radius: 12px;
        display: flex;
        align-items: center;
        gap: 12px;
        z-index: 60;
      }
      button {
        background: transparent;
        border: none;
        color: #fff;
        font-size: 16px;
        cursor: pointer;
      }
    `
  ]
})
export class ToastNotificationComponent {
  @Input() message: string | null = null;
  @Output() dismiss = new EventEmitter<void>();
}
