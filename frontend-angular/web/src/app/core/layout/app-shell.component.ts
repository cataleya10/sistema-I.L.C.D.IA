import { Component, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { Subscription } from 'rxjs';
import { AuthService } from '../services/auth.service';
import { SystemService, SystemInfo } from '../services/system.service';
import { NotificationService } from '../services/notification.service';
import { ToastNotificationComponent } from '../../shared/components/toast-notification.component';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [CommonModule, RouterOutlet, RouterLink, RouterLinkActive, ToastNotificationComponent],
  template: `
    <div class="shell">
      <header class="shell__header">
        <div>
          <h1>SISTEMA DE LECTURA INTELIGENTE</h1>
          <p>Bufete de Mantenimiento Predictivo e Ingenieria</p>
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
            <div class="user" *ngIf="userName">
              <span class="user__name">{{ userName }}</span>
              <span class="user__role">{{ userRole }}</span>
            </div>
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
    <app-toast-notification [message]="toastMessage" (dismiss)="clearToast()" />
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
        flex-wrap: wrap;
        gap: 16px;
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
        flex-wrap: wrap;
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
      .user {
        display: grid;
        gap: 2px;
        padding: 6px 12px;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.08);
        border: 1px solid rgba(255, 255, 255, 0.12);
      }
      .user__name {
        font-size: 12px;
        font-weight: 600;
      }
      .user__role {
        font-size: 10px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #cbd5f5;
      }
      .shell__nav a.active {
        text-decoration: underline;
      }
      .shell__content {
        padding: 32px 40px;
      }
      @media (max-width: 960px) {
        .shell__header {
          padding: 20px 16px;
        }
        .shell__content {
          padding: 20px 16px;
        }
        .shell__header h1 {
          font-size: 16px;
        }
        .shell__nav {
          width: 100%;
        }
      }
    `
  ]
})
export class AppShellComponent implements OnDestroy {
  systemInfo: SystemInfo | null = null;
  toastMessage: string | null = null;
  private readonly subscriptions: Subscription[] = [];

  constructor(
    private readonly auth: AuthService,
    private readonly router: Router,
    private readonly system: SystemService,
    private readonly notifications: NotificationService
  ) {
    this.subscriptions.push(
      this.system.getInfo().subscribe({
        next: (info) => (this.systemInfo = info),
        error: () => (this.systemInfo = null)
      })
    );

    this.subscriptions.push(
      this.notifications.message$.subscribe((message) => {
        this.toastMessage = message;
      })
    );
  }

  ngOnDestroy(): void {
    this.subscriptions.forEach((s) => s.unsubscribe());
  }

  isAuthenticated(): boolean {
    return !!this.auth.getToken();
  }

  get userName(): string | null {
    return this.auth.getUsername();
  }

  get userRole(): string | null {
    return this.auth.getRole();
  }

  clearToast(): void {
    this.notifications.clear();
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

