import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Observable } from 'rxjs';
import { AuthSession, AuthService } from '../../../core/services/auth.service';
import { SubirDocumentoComponent } from '../components/subir-documento.component';

@Component({
  selector: 'app-documents-upload-page',
  standalone: true,
  imports: [CommonModule, FormsModule, SubirDocumentoComponent],
  template: `
    <section class="page">
      <ng-container *ngIf="isAuthenticated(); else authCard">
        <div class="session-bar">
          <div>
            <p class="session-bar__label">Backend conectado</p>
            <strong>{{ auth.getUsername() }}</strong>
          </div>
          <button type="button" class="ghost" (click)="logout()">Cerrar sesion</button>
        </div>

        <app-subir-documento></app-subir-documento>
      </ng-container> 

      <ng-template #authCard>
        <section class="auth-card">
          <p class="eyebrow">Conectar con backend</p>
          <h2>Inicia sesion o crea un usuario local</h2>
          <p class="auth-card__copy">
            El procesamiento real usa JWT. Desde aqui puedes autenticarte y probar el upload
            contra el API .NET y el motor IA.
          </p>

          <form class="auth-form" (ngSubmit)="login()">
            <label for="auth-email">Usuario o correo</label>
            <input
              id="auth-email"
              name="email"
              type="text"
              [(ngModel)]="email"
              autocomplete="username"
              placeholder="usuario o correo"
            />

            <label for="auth-password">Contrasena</label>
            <input
              id="auth-password"
              name="password"
              type="password"
              [(ngModel)]="password"
              autocomplete="current-password"
              placeholder="contrasena"
            />

            <div class="actions">
              <button type="submit" [disabled]="authLoading">
                {{ authLoading ? 'Conectando...' : 'Iniciar sesion' }}
              </button>
              <button type="button" class="ghost" (click)="register()" [disabled]="authLoading">
                Crear usuario local
              </button>
            </div>

            <p class="hint">Para pruebas nuevas, usa correo + contrasena y presiona "Crear usuario local".</p>
            <p class="error" *ngIf="authError">{{ authError }}</p>
          </form>
        </section>
      </ng-template>
    </section>
  `,
  styles: [
    `
      .page {
        width: min(100%, 720px);
        display: grid;
        gap: 18px;
      }
      .session-bar,
      .auth-card {
        border: 1px solid #dbe4f0;
        border-radius: 20px;
        background: #ffffff;
        box-shadow: 0 20px 45px rgba(15, 23, 42, 0.08);
      }
      .session-bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 18px 22px;
      }
      .session-bar__label,
      .eyebrow {
        margin: 0 0 4px;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-size: 12px;
        color: #64748b;
      }
      .auth-card {
        display: grid;
        gap: 16px;
        padding: 28px;
      }
      .auth-card h2,
      .auth-card__copy {
        margin: 0;
      }
      .auth-card__copy {
        color: #475569;
        line-height: 1.5;
      }
      .auth-form {
        display: grid;
        gap: 10px;
      }
      .auth-form label {
        font-size: 14px;
        color: #334155;
        font-weight: 600;
      }
      .auth-form input {
        padding: 12px;
        border: 1px solid #cbd5e1;
        border-radius: 12px;
        background: #f8fafc;
      }
      .actions {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        margin-top: 6px;
      }
      button {
        width: fit-content;
        min-width: 180px;
        padding: 12px 18px;
        border: 0;
        border-radius: 999px;
        background: #0f172a;
        color: #ffffff;
        font-weight: 600;
        cursor: pointer;
      }
      button.ghost {
        background: #e2e8f0;
        color: #0f172a;
      }
      button:disabled {
        opacity: 0.75;
        cursor: wait;
      }
      .hint,
      .error {
        margin: 0;
        font-size: 13px;
      }
      .hint {
        color: #64748b;
      }
      .error {
        color: #b91c1c;
      }
    `
  ]
})
export class DocumentsUploadPage {
  email = '';
  password = '';
  authLoading = false;
  authError = '';

  constructor(public readonly auth: AuthService) {}

  isAuthenticated(): boolean {
    return this.auth.isAuthenticated();
  }

  login(): void {
    if (!this.email.trim() || !this.password) {
      this.authError = 'Ingresa usuario/correo y contrasena.';
      return;
    }

    this.runAuthRequest(this.auth.login(this.email.trim(), this.password));
  }

  register(): void {
    const email = this.email.trim().toLowerCase();
    if (!email || !email.includes('@') || !this.password) {
      this.authError = 'Para registrar, usa un correo valido y una contrasena.';
      return;
    }

    this.runAuthRequest(this.auth.register(email, this.password));
  }

  logout(): void {
    this.auth.logout();
    this.authError = '';
    this.password = '';
  }

  private runAuthRequest(request$: Observable<AuthSession>): void {
    this.authLoading = true;
    this.authError = '';

    request$.subscribe({
      next: (session) => {
        this.auth.setToken(session.token);
        this.auth.setRefreshToken(session.refreshToken);
        this.auth.setUser(session.username, session.role);
        this.authLoading = false;
      },
      error: (error: HttpErrorResponse) => {
        this.authError = this.resolveAuthError(error);
        this.authLoading = false;
      }
    });
  }

  private resolveAuthError(error: HttpErrorResponse): string {
    if (error.status === 0) {
      return 'No se pudo conectar al API.';
    }

    const payload = error.error as { error?: string; detail?: string; message?: string } | null;
    return payload?.error ?? payload?.detail ?? payload?.message ?? 'No fue posible autenticar.';
  }
}
