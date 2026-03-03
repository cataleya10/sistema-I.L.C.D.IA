import { HttpEvent, HttpHandler, HttpInterceptor, HttpRequest } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { AuthService } from '../services/auth.service';

@Injectable()
export class AuthInterceptor implements HttpInterceptor {
  constructor(private readonly auth: AuthService) {}

  intercept(req: HttpRequest<unknown>, next: HttpHandler): Observable<HttpEvent<unknown>> {
    if (this.isAuthRequest(req) || req.headers.has('Authorization')) {
      return next.handle(req);
    }

    const token = this.auth.getToken();
    if (!token) {
      return next.handle(req);
    }

    const authReq = req.clone({
      setHeaders: {
        Authorization: `Bearer ${token}`
      }
    });
    return next.handle(authReq);
  }

  private isAuthRequest(req: HttpRequest<unknown>): boolean {
    return (
      req.url.includes('/api/auth/login') ||
      req.url.includes('/api/auth/register') ||
      req.url.includes('/api/auth/google') ||
      req.url.includes('/api/auth/refresh') ||
      req.url.includes('/api/auth/logout')
    );
  }
}
