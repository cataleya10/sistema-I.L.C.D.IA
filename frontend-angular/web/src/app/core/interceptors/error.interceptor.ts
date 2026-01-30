import { HttpErrorResponse, HttpEvent, HttpHandler, HttpInterceptor, HttpRequest } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, Subject, throwError } from 'rxjs';
import { catchError, switchMap, take } from 'rxjs/operators';
import { AuthService } from '../services/auth.service';
import { Router } from '@angular/router';
@Injectable()
export class ErrorInterceptor implements HttpInterceptor {
  private isRefreshing = false;
  private refreshTokenSubject = new Subject<string>();

  constructor(private readonly auth: AuthService, private readonly router: Router) {}

  intercept(req: HttpRequest<unknown>, next: HttpHandler): Observable<HttpEvent<unknown>> {
    return next.handle(req).pipe(
      catchError((error: HttpErrorResponse) => {
        if (error.status !== 401) {
          return throwError(() => error);
        }

        if (this.isRefreshRequest(req)) {
          this.auth.logout();
          this.router.navigate(['/login']);
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
          return throwError(() => error);
        }

        this.isRefreshing = true;
        return this.auth.refreshToken(refreshToken).pipe(
          switchMap((response) => {
            this.isRefreshing = false;
            this.auth.setToken(response.token);
            this.auth.setRefreshToken(response.refresh_token);
            this.refreshTokenSubject.next(response.token);
            return next.handle(this.addAuthHeader(req, response.token));
          }),
          catchError((refreshError) => {
            this.isRefreshing = false;
            this.refreshTokenSubject.error(refreshError);
            this.refreshTokenSubject = new Subject<string>();
            this.auth.logout();
            this.router.navigate(['/login']);
            return throwError(() => refreshError);
          })
        );
      })
    );
  }

  private isRefreshRequest(req: HttpRequest<unknown>): boolean {
    return req.url.includes('/api/auth/refresh');
  }

  private addAuthHeader(req: HttpRequest<unknown>, token: string): HttpRequest<unknown> {
    return req.clone({
      setHeaders: { Authorization: `Bearer ${token}` }
    });
  }
}
