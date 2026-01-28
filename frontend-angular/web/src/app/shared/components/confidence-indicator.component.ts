import { CommonModule } from '@angular/common';
import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-confidence-indicator',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="confidence">
      <div class="confidence__bar" [style.width.%]="percentage"></div>
      <span>{{ percentage }}%</span>
    </div>
  `,
  styles: [
    `
      .confidence {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .confidence__bar {
        height: 6px;
        flex: 1;
        background: linear-gradient(90deg, #4f46e5, #06b6d4);
        border-radius: 999px;
      }
      span {
        font-size: 12px;
        font-weight: 600;
        color: #1f2937;
      }
    `
  ]
})
export class ConfidenceIndicatorComponent {
  @Input() value = 0;

  get percentage(): number {
    return Math.round(this.value * 100);
  }
}
