import { CommonModule } from '@angular/common';
import { Component, OnInit, AfterViewInit, NgZone, OnDestroy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../../core/services/auth.service';
import { Router } from '@angular/router';
import { getGoogleClientId } from '../../../core/config/runtime-config';

declare const google: any;

@Component({
  selector: 'app-login-page',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <section class="login">
      <h2>Iniciar sesion</h2>
      <form (ngSubmit)="submit()">
        <label for="username">Usuario</label>
        <input
          id="username"
          type="text"
          name="username"
          [(ngModel)]="username"
          placeholder="Usuario"
          autocomplete="username"
          required
        />

        <label for="password">Contrasena</label>
        <input
          id="password"
          type="password"
          name="password"
          [(ngModel)]="password"
          placeholder="Contrasena"
          autocomplete="current-password"
          required
        />

        <button type="submit" [disabled]="isSubmitting">
          {{ isSubmitting ? 'Ingresando...' : 'Ingresar' }}
        </button>

        <p class="error" *ngIf="error" role="alert">{{ errorMessage }}</p>
      </form>

      <div class="divider" *ngIf="googleEnabled">
        <span>o</span>
      </div>

      <div id="google-signin-btn" *ngIf="googleEnabled"></div>
      <p class="error" *ngIf="googleError" role="alert">{{ googleError }}</p>
    </section>
  `,
  styles: [
    `
      .login {
        max-width: 360px;
        margin: 60px auto;
        padding: 24px;
        background: #fff;
        border-radius: 12px;
        border: 1px solid #e5e7eb;
        display: grid;
        gap: 16px;
      }
      form {
        display: grid;
        gap: 12px;
      }
      label {
        font-size: 12px;
        color: #4b5563;
      }
      input {
        padding: 10px 12px;
        border-radius: 8px;
        border: 1px solid #e5e7eb;
      }
      button {
        padding: 10px 16px;
        border-radius: 999px;
        border: none;
        background: #4f46e5;
        color: #fff;
      }
      button:disabled {
        opacity: 0.7;
      }
      .error {
        color: #b91c1c;
        margin: 0;
      }
      .divider {
        display: flex;
        align-items: center;
        gap: 12px;
        color: #9ca3af;
        font-size: 13px;
      }
      .divider::before,
      .divider::after {
        content: '';
        flex: 1;
        height: 1px;
        background: #e5e7eb;
      }
      #google-signin-btn {
        display: flex;
        justify-content: center;
      }
    `
  ]
})
export class LoginPage implements OnInit, AfterViewInit, OnDestroy {
  username = '';
  password = '';
  error = false;
  errorMessage = 'Credenciales invalidas';
  isSubmitting = false;
  googleEnabled = false;
  googleError = '';
  private googleClientId = '';

  constructor(
    private readonly auth: AuthService,
    private readonly router: Router,
    private readonly ngZone: NgZone
  ) {}

  ngOnInit(): void {
    if (this.auth.getToken()) {
      this.router.navigate(['/documents']);
    }
    this.googleClientId = getGoogleClientId();
    this.googleEnabled = !!this.googleClientId;
  }

  ngAfterViewInit(): void {
    if (!this.googleEnabled) {
      return;
    }
    this.initGoogleSignIn();
  }

  ngOnDestroy(): void {
    // cleanup if needed
  }

  private initGoogleSignIn(): void {
    const tryInit = (retries: number): void => {
      if (typeof google !== 'undefined' && google.accounts) {
        google.accounts.id.initialize({
          client_id: this.googleClientId,
          callback: (response: any) => this.handleGoogleCredential(response),
          auto_select: false
        });

        google.accounts.id.renderButton(
          document.getElementById('google-signin-btn'),
          {
            theme: 'outline',
            size: 'large',
            width: 312,
            text: 'signin_with',
            locale: 'es'
          }
        );
      } else if (retries > 0) {
        setTimeout(() => tryInit(retries - 1), 300);
      }
    };

    tryInit(10);
  }

  private handleGoogleCredential(response: any): void {
    this.ngZone.run(() => {
      const idToken = response?.credential;
      if (!idToken) {
        this.googleError = 'No se recibio token de Google';
        return;
      }

      this.googleError = '';
      this.error = false;
      this.isSubmitting = true;

      this.auth.loginWithGoogle(idToken).subscribe({
        next: (session) => {
          this.auth.setToken(session.token);
          this.auth.setRefreshToken(session.refreshToken);
          this.auth.setUser(session.username, session.role);
          this.isSubmitting = false;
          this.router.navigate(['/documents']);
        },
        error: () => {
          this.googleError = 'Error al autenticar con Google';
          this.isSubmitting = false;
        }
      });
    });
  }

  submit(): void {
    this.error = false;
    this.googleError = '';
    const username = this.username.trim();
    if (!username || !this.password) {
      this.error = true;
      return;
    }

    this.isSubmitting = true;
    this.auth.login(username, this.password).subscribe({
      next: (response) => {
        this.auth.setToken(response.token);
        this.auth.setRefreshToken(response.refreshToken);
        this.auth.setUser(response.username, response.role);
        this.isSubmitting = false;
        this.router.navigate(['/documents']);
      },
      error: () => {
        this.error = true;
        this.isSubmitting = false;
      }
    });
  }
}
