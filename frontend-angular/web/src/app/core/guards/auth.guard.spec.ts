import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { authGuard } from './auth.guard';
import { AuthService } from '../services/auth.service';

describe('authGuard', () => {
  let authService: AuthService;
  let router: Router;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([{ path: 'login', component: {} as any }]),
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    });
    authService = TestBed.inject(AuthService);
    router = TestBed.inject(Router);
  });

  it('should allow access when user is authenticated', () => {
    const token = buildJwt(Math.floor(Date.now() / 1000) + 300);
    authService.setToken(token);

    const result = TestBed.runInInjectionContext(() => authGuard({} as any, {} as any));

    expect(result).toBeTrue();
  });

  it('should deny access and redirect to /login when not authenticated', () => {
    spyOn(router, 'navigate');

    const result = TestBed.runInInjectionContext(() => authGuard({} as any, {} as any));

    expect(result).toBeFalse();
    expect(router.navigate).toHaveBeenCalledWith(['/login']);
  });

  it('should deny access when token is expired', () => {
    const token = buildJwt(Math.floor(Date.now() / 1000) - 60);
    authService.setToken(token);
    spyOn(router, 'navigate');

    const result = TestBed.runInInjectionContext(() => authGuard({} as any, {} as any));

    expect(result).toBeFalse();
    expect(router.navigate).toHaveBeenCalledWith(['/login']);
  });
});

function buildJwt(exp: number): string {
  const header = base64UrlEncode(JSON.stringify({ alg: 'none', typ: 'JWT' }));
  const payload = base64UrlEncode(JSON.stringify({ exp }));
  return `${header}.${payload}.signature`;
}

function base64UrlEncode(value: string): string {
  return btoa(value).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}
