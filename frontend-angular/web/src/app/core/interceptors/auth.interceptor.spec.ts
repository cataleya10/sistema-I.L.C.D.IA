import { TestBed } from '@angular/core/testing';
import { HttpClient, HTTP_INTERCEPTORS, provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { AuthInterceptor } from './auth.interceptor';
import { AuthService } from '../services/auth.service';

describe('AuthInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let authService: AuthService;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting(),
        { provide: HTTP_INTERCEPTORS, useClass: AuthInterceptor, multi: true },
      ],
    });
    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
    authService = TestBed.inject(AuthService);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should add Authorization header when token exists', () => {
    const token = buildJwt(Math.floor(Date.now() / 1000) + 300);
    authService.setToken(token);

    http.get('/api/documents').subscribe();

    const req = httpMock.expectOne('/api/documents');
    expect(req.request.headers.has('Authorization')).toBeTrue();
    expect(req.request.headers.get('Authorization')).toBe(`Bearer ${token}`);
    req.flush([]);
  });

  it('should NOT add Authorization header when no token exists', () => {
    http.get('/api/documents').subscribe();

    const req = httpMock.expectOne('/api/documents');
    expect(req.request.headers.has('Authorization')).toBeFalse();
    req.flush([]);
  });

  it('should skip auth header for login requests', () => {
    const token = buildJwt(Math.floor(Date.now() / 1000) + 300);
    authService.setToken(token);

    http.post('/api/auth/login', { username: 'a', password: 'b' }).subscribe();

    const req = httpMock.expectOne('/api/auth/login');
    expect(req.request.headers.has('Authorization')).toBeFalse();
    req.flush({});
  });

  it('should skip auth header for refresh requests', () => {
    const token = buildJwt(Math.floor(Date.now() / 1000) + 300);
    authService.setToken(token);

    http.post('/api/auth/refresh', { refresh_token: 'abc' }).subscribe();

    const req = httpMock.expectOne('/api/auth/refresh');
    expect(req.request.headers.has('Authorization')).toBeFalse();
    req.flush({});
  });

  it('should skip auth header for logout requests', () => {
    const token = buildJwt(Math.floor(Date.now() / 1000) + 300);
    authService.setToken(token);

    http.post('/api/auth/logout', { refresh_token: 'abc' }).subscribe();

    const req = httpMock.expectOne('/api/auth/logout');
    expect(req.request.headers.has('Authorization')).toBeFalse();
    req.flush({});
  });

  it('should not override existing Authorization header', () => {
    const token = buildJwt(Math.floor(Date.now() / 1000) + 300);
    authService.setToken(token);

    http.get('/api/documents', { headers: { Authorization: 'Custom xyz' } }).subscribe();

    const req = httpMock.expectOne('/api/documents');
    expect(req.request.headers.get('Authorization')).toBe('Custom xyz');
    req.flush([]);
  });

  it('should skip auth header for google login requests', () => {
    const token = buildJwt(Math.floor(Date.now() / 1000) + 300);
    authService.setToken(token);

    http.post('/api/auth/google', { id_token: 'gtoken' }).subscribe();

    const req = httpMock.expectOne('/api/auth/google');
    expect(req.request.headers.has('Authorization')).toBeFalse();
    req.flush({});
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
