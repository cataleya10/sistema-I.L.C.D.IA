import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { AuthService } from '../services/auth.service';
import { SystemService, SystemInfo } from '../services/system.service';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [CommonModule, RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <div class="shell">
      <header class="shell__header">
        <div>
          <h1>Sistema I.L.C.D.IA</h1>
          <p>Inteligencia documental empresarial</p>
        </div>
        <div class="version" *ngIf="systemInfo">
          <span>{{ systemInfo.pipeline_version }}</span>
          <span>{{ systemInfo.model_version }}</span>
        </div>
        <nav class="shell__nav">
          <ng-container *ngIf="isAuthenticated(); else loginLink">
            <a routerLink="/documents/upload" routerLinkActive="active">Carga</a>
            <a routerLink="/documents" routerLinkActive="active" [routerLinkActiveOptions]="{ exact: true }">Bandeja</a>
            <a routerLink="/system" routerLinkActive="active">Sistema</a>
            <button type="button" (click)="logout()">Salir</button>
          </ng-container>
          <ng-template #loginLink>
            <a routerLink="/login" routerLinkActive="active">Login</a>
          </ng-template>
        </nav>
      </header>
      <main class="shell__content">
        <router-outlet />
      </main>
    </div>
  `,
  styles: [
    `
      .shell {
        min-height: 100vh;
        background: #f8fafc;
        color: #0f172a;
      }
      .shell__header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 24px 40px;
        background: #111827;
        color: #fff;
      }
      .shell__header h1 {
        margin: 0;
        font-size: 20px;
      }
      .shell__header p {
        margin: 4px 0 0;
        font-size: 12px;
        opacity: 0.8;
      }
      .shell__nav {
        display: flex;
        gap: 16px;
        align-items: center;
      }
      .version {
        display: flex;
        gap: 8px;
        font-size: 12px;
        color: #cbd5f5;
      }
      .shell__nav a {
        color: #fff;
        text-decoration: none;
        font-weight: 500;
      }
      .shell__nav button {
        background: #1f2937;
        color: #fff;
        border: 1px solid #374151;
        border-radius: 999px;
        padding: 6px 12px;
      }
      .shell__nav a.active {
        text-decoration: underline;
      }
      .shell__content {
        padding: 32px 40px;
      }
    `
  ]
})
export class AppShellComponent {
  systemInfo: SystemInfo | null = null;

  constructor(
    private readonly auth: AuthService,
    private readonly router: Router,
    private readonly system: SystemService
  ) {
    this.system.getInfo().subscribe({
      next: (info) => (this.systemInfo = info),
      error: () => (this.systemInfo = null)
    });
  }

  isAuthenticated(): boolean {
    return !!this.auth.getToken();
  }

  logout(): void {
    const refresh = this.auth.getRefreshToken();
    if (refresh) {
      this.auth.logoutRemote(refresh).subscribe({
        next: () => this.auth.logout(),
        error: () => this.auth.logout()
      });
    } else {
      this.auth.logout();
    }
    this.router.navigate(['/login']);
  }
}
