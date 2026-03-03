import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { AuthService } from './auth.service';

describe('AuthService', () => {
  let service: AuthService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()]
    });
    service = TestBed.inject(AuthService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('returns token when it is not expired', () => {
    const token = buildJwt(Math.floor(Date.now() / 1000) + 300);
    service.setToken(token);

    expect(service.getToken()).toBe(token);
    expect(service.isAuthenticated()).toBeTrue();
  });

  it('clears token when it is expired', () => {
    const token = buildJwt(Math.floor(Date.now() / 1000) - 10);
    service.setToken(token);

    expect(service.getToken()).toBeNull();
    expect(service.isAuthenticated()).toBeFalse();
  });

  it('treats token near expiration as expired to avoid edge failures', () => {
    const token = buildJwt(Math.floor(Date.now() / 1000) + 10);
    service.setToken(token);

    expect(service.getToken()).toBeNull();
    expect(service.isAuthenticated()).toBeFalse();
  });

  it('loginWithGoogle sends id_token to /api/auth/google', () => {
    service.loginWithGoogle('google-id-token-abc').subscribe((session) => {
      expect(session.token).toBe('jwt-token');
      expect(session.username).toBe('googleuser');
    });

    const req = httpMock.expectOne((r: any) => r.url.includes('/api/auth/google'));
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ id_token: 'google-id-token-abc' });
    req.flush({
      token: 'jwt-token',
      refresh_token: 'rt',
      username: 'googleuser',
      role: 'User',
    });
  });

  it('register sends email and password to /api/auth/register', () => {
    service.register('new@example.com', 'secret123').subscribe((session) => {
      expect(session.token).toBe('reg-token');
      expect(session.username).toBe('new@example.com');
    });

    const req = httpMock.expectOne((r: any) => r.url.includes('/api/auth/register'));
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ email: 'new@example.com', password: 'secret123' });
    req.flush({
      token: 'reg-token',
      refreshToken: 'reg-refresh',
      username: 'new@example.com',
      role: 'User',
    });
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
