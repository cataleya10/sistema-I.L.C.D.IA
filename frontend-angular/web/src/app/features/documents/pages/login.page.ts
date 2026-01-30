import { CommonModule } from '@angular/common';
import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../../core/services/auth.service';
import { Router } from '@angular/router';

@Component({
  selector: 'app-login-page',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <section class="login">
      <h2>Iniciar sesión</h2>
      <form (ngSubmit)="submit()">
        <input type="text" name="username" [(ngModel)]="username" placeholder="Usuario" required />
        <input type="password" name="password" [(ngModel)]="password" placeholder="Contraseña" required />
        <button type="submit">Ingresar</button>
        <p *ngIf="error">Credenciales inválidas</p>
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
      p {
        color: #b91c1c;
      }
    `
  ]
})
export class LoginPage {
  username = '';
  password = '';
  error = false;

  constructor(private readonly auth: AuthService, private readonly router: Router) {}

  submit(): void {
    this.error = false;
    this.auth.login(this.username, this.password).subscribe({
      next: (response) => {
        this.auth.setToken(response.token);
        this.auth.setRefreshToken(response.refresh_token);
        this.router.navigate(['/documents']);
      },
      error: () => (this.error = true)
    });
  }
}
