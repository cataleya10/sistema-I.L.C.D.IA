import { CommonModule } from '@angular/common';
import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../../core/services/auth.service';
import { Router } from '@angular/router';

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

        <p class="error" *ngIf="error" role="alert">Credenciales invalidas</p>
      </form>
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
    `
  ]
})
export class LoginPage implements OnInit {
  username = '';
  password = '';
  error = false;
  isSubmitting = false;

  constructor(private readonly auth: AuthService, private readonly router: Router) {}

  ngOnInit(): void {
    if (this.auth.getToken()) {
      this.router.navigate(['/documents']);
    }
  }

  submit(): void {
    this.error = false;
    const username = this.username.trim();
    if (!username || !this.password) {
      this.error = true;
      return;
    }

    this.isSubmitting = true;
    this.auth.login(username, this.password).subscribe({
      next: (response) => {
        this.auth.setToken(response.token);
        this.auth.setRefreshToken(response.refresh_token);
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
