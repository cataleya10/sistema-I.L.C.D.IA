import { HttpErrorResponse, HttpEvent, HttpHandler, HttpInterceptor, HttpRequest } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, Subject, throwError } from 'rxjs';
import { catchError, switchMap, take } from 'rxjs/operators';
import { Router } from '@angular/router';
import { AuthService } from '../services/auth.service';
import { NotificationService } from '../services/notification.service';

@Injectable()
export class ErrorInterceptor implements HttpInterceptor {
  private isRefreshing = false;
  private refreshTokenSubject = new Subject<string>();

  constructor(
    private readonly auth: AuthService,
    private readonly router: Router,
    private readonly notifications: NotificationService
  ) {}

  intercept(req: HttpRequest<unknown>, next: HttpHandler): Observable<HttpEvent<unknown>> {
    return next.handle(req).pipe(
      catchError((error: HttpErrorResponse) => {
        if (error.status !== 401) {
          this.notifyError(error);
          return throwError(() => error);
        }

        // Login failures should be handled by the login page, not by refresh flow.
        if (this.isLoginRequest(req)) {
          return throwError(() => error);
        }

        if (this.isRefreshRequest(req)) {
          this.auth.logout();
          this.router.navigate(['/login']);
          this.notifications.show('Sesion expirada. Inicia sesion nuevamente.');
          return throwError(() => error);
        }

        if (this.isRefreshing) {
          return this.refreshTokenSubject.pipe(
            take(1),
            switchMap((token) => next.handle(this.addAuthHeader(req, token)))
          );
        }

        const refreshToken = this.auth.getRefreshToken();
        if (!refreshToken) {
          this.auth.logout();
          this.router.navigate(['/login']);
          this.notifications.show('Sesion expirada. Inicia sesion nuevamente.');
          return throwError(() => error);
        }

        this.isRefreshing = true;
        return this.auth.refreshToken(refreshToken).pipe(
          switchMap((response) => {
            this.isRefreshing = false;
            this.auth.setToken(response.token);
            this.auth.setRefreshToken(response.refreshToken);
            this.refreshTokenSubject.next(response.token);
            return next.handle(this.addAuthHeader(req, response.token));
          }),
          catchError((refreshError) => {
            this.isRefreshing = false;
            this.refreshTokenSubject.error(refreshError);
            this.refreshTokenSubject = new Subject<string>();
            this.auth.logout();
            this.router.navigate(['/login']);
            this.notifications.show('Sesion expirada. Inicia sesion nuevamente.');
            return throwError(() => refreshError);
          })
        );
      })
    );
  }

  private isRefreshRequest(req: HttpRequest<unknown>): boolean {
    return req.url.includes('/api/auth/refresh');
  }

  private isLoginRequest(req: HttpRequest<unknown>): boolean {
    return req.url.includes('/api/auth/login');
  }

  private addAuthHeader(req: HttpRequest<unknown>, token: string): HttpRequest<unknown> {
    return req.clone({
      setHeaders: { Authorization: `Bearer ${token}` }
    });
  }

  private notifyError(error: HttpErrorResponse): void {
    const message = this.getErrorMessage(error);
    if (message) {
      this.notifications.show(message);
    }
  }

  private getErrorMessage(error: HttpErrorResponse): string | null {
    if (error.status === 0) {
      return 'No se pudo conectar al servidor.';
    }
    if (error.status === 400) {
      return this.extractDetail(error) ?? 'Solicitud invalida.';
    }
    if (error.status === 403) {
      return 'No tienes permisos para esta accion.';
    }
    if (error.status === 404) {
      return 'Recurso no encontrado.';
    }
    if (error.status >= 500) {
      return 'Error interno del servidor.';
    }
    return this.extractDetail(error);
  }

  private extractDetail(error: HttpErrorResponse): string | null {
    const payload = error.error as
      | { detail?: string; message?: string; error?: string | { message?: string } }
      | string
      | null;

    if (!payload) {
      return null;
    }
    if (typeof payload === 'string') {
      return payload;
    }
    if (typeof payload.error === 'string' && payload.error.trim().length) {
      return payload.error;
    }
    if (typeof payload.error === 'object' && payload.error?.message) {
      return payload.error.message ?? null;
    }
    return payload.detail ?? payload.message ?? null;
  }
}
