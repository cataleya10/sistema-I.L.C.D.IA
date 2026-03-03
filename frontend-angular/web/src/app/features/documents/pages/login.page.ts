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
      <h2>{{ isRegisterMode ? 'Registrarse' : 'Iniciar sesion' }}</h2>

      <!-- LOGIN FORM -->
      <form *ngIf="!isRegisterMode" (ngSubmit)="submit()">
        <label for="username">Usuario o correo</label>
        <input
          id="username"
          type="text"
          name="username"
          [(ngModel)]="username"
          placeholder="Usuario o correo"
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

      <!-- REGISTER FORM -->
      <form *ngIf="isRegisterMode" (ngSubmit)="submitRegister()">
        <label for="reg-email">Correo electronico</label>
        <input
          id="reg-email"
          type="email"
          name="regEmail"
          [(ngModel)]="regEmail"
          placeholder="tucorreo@gmail.com"
          autocomplete="email"
          required
        />

        <label for="reg-password">Contrasena (min. 6 caracteres)</label>
        <input
          id="reg-password"
          type="password"
          name="regPassword"
          [(ngModel)]="regPassword"
          placeholder="Contrasena"
          autocomplete="new-password"
          required
        />

        <button type="submit" [disabled]="isSubmitting">
          {{ isSubmitting ? 'Registrando...' : 'Registrarse' }}
        </button>

        <p class="error" *ngIf="registerError" role="alert">{{ registerError }}</p>
        <p class="success" *ngIf="registerSuccess" role="status">Registro exitoso</p>
      </form>

      <p class="toggle-link">
        <a href="javascript:void(0)" (click)="toggleMode()">
          {{ isRegisterMode ? 'Ya tengo cuenta — Iniciar sesion' : 'No tengo cuenta — Registrarme' }}
        </a>
      </p>

      <div class="divider" *ngIf="googleEnabled && !isRegisterMode">
        <span>o</span>
      </div>

      <div id="google-signin-btn" *ngIf="googleEnabled && !isRegisterMode"></div>
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
      .toggle-link {
        text-align: center;
        margin: 0;
      }
      .toggle-link a {
        color: #4f46e5;
        font-size: 13px;
        text-decoration: none;
      }
      .toggle-link a:hover {
        text-decoration: underline;
      }
      .success {
        color: #15803d;
        margin: 0;
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
  isRegisterMode = false;
  regEmail = '';
  regPassword = '';
  registerError = '';
  registerSuccess = false;
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

  toggleMode(): void {
    this.isRegisterMode = !this.isRegisterMode;
    this.error = false;
    this.registerError = '';
    this.registerSuccess = false;
    this.googleError = '';
  }

  submitRegister(): void {
    this.registerError = '';
    this.registerSuccess = false;
    const email = this.regEmail.trim();

    if (!email || !email.includes('@')) {
      this.registerError = 'Ingresa un correo valido';
      return;
    }

    if (!this.regPassword || this.regPassword.length < 6) {
      this.registerError = 'La contrasena debe tener al menos 6 caracteres';
      return;
    }

    this.isSubmitting = true;
    this.auth.register(email, this.regPassword).subscribe({
      next: (session) => {
        this.auth.setToken(session.token);
        this.auth.setRefreshToken(session.refreshToken);
        this.auth.setUser(session.username, session.role);
        this.isSubmitting = false;
        this.router.navigate(['/documents']);
      },
      error: (err) => {
        this.registerError = err?.error?.error || 'Error al registrarse';
        this.isSubmitting = false;
      }
    });
  }
}
