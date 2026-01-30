import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { SystemMetrics, SystemService } from '../../../core/services/system.service';

@Component({
  selector: 'app-system-metrics-page',
  standalone: true,
  imports: [CommonModule],
  template: `
    <section class="page">
      <header>
        <h2>Estado del sistema</h2>
        <p>Métricas básicas de solicitudes y errores.</p>
      </header>
      <div class="cards" *ngIf="metrics; else empty">
        <div class="card">
          <h3>Requests</h3>
          <strong>{{ metrics.requests }}</strong>
        </div>
        <div class="card">
          <h3>Errors</h3>
          <strong>{{ metrics.errors }}</strong>
        </div>
        <div class="card">
          <h3>Última actualización</h3>
          <span>{{ metrics.timestamp | date: 'short' }}</span>
        </div>
      </div>
      <ng-template #empty>
        <p>No hay métricas disponibles.</p>
      </ng-template>
    </section>
  `,
  styles: [
    `
      .page {
        display: grid;
        gap: 20px;
        max-width: 720px;
      }
      .cards {
        display: grid;
        gap: 16px;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      }
      .card {
        background: #fff;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 16px;
        display: grid;
        gap: 8px;
      }
      h3 {
        margin: 0;
        font-size: 14px;
        color: #6b7280;
      }
      strong {
        font-size: 22px;
      }
    `
  ]
})
export class SystemMetricsPage implements OnInit {
  metrics: SystemMetrics | null = null;

  constructor(private readonly system: SystemService) {}

  ngOnInit(): void {
    this.system.getMetrics().subscribe({
      next: (data) => (this.metrics = data),
      error: () => (this.metrics = null)
    });
  }
}
