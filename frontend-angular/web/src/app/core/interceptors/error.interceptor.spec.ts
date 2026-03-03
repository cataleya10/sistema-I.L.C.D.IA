import { TestBed } from '@angular/core/testing';
import {
  HttpClient,
  HttpErrorResponse,
  HTTP_INTERCEPTORS,
  provideHttpClient,
  withInterceptorsFromDi,
} from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router } from '@angular/router';
import { provideRouter } from '@angular/router';
import { ErrorInterceptor } from './error.interceptor';
import { AuthInterceptor } from './auth.interceptor';
import { AuthService } from '../services/auth.service';
import { NotificationService } from '../services/notification.service';

describe('ErrorInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let authService: AuthService;
  let router: Router;
  let notifications: NotificationService;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([{ path: 'login', component: {} as any }]),
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting(),
        { provide: HTTP_INTERCEPTORS, useClass: AuthInterceptor, multi: true },
        { provide: HTTP_INTERCEPTORS, useClass: ErrorInterceptor, multi: true },
      ],
    });
    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
    authService = TestBed.inject(AuthService);
    router = TestBed.inject(Router);
    notifications = TestBed.inject(NotificationService);

    spyOn(router, 'navigate');
    spyOn(notifications, 'show');
  });

  afterEach(() => {
    httpMock.verify();
  });

  // ─── Non-401 errors ──────────────────────────────────────────────

  it('should show connection error for status 0', () => {
    http.get('/api/documents').subscribe({ error: () => {} });

    const req = httpMock.expectOne('/api/documents');
    req.error(new ProgressEvent('error'), { status: 0, statusText: '' });

    expect(notifications.show).toHaveBeenCalledWith('No se pudo conectar al servidor.');
  });

  it('should show "Solicitud invalida." for status 400 without body detail', () => {
    http.get('/api/documents').subscribe({ error: () => {} });

    const req = httpMock.expectOne('/api/documents');
    req.flush(null, { status: 400, statusText: 'Bad Request' });

    expect(notifications.show).toHaveBeenCalledWith('Solicitud invalida.');
  });

  it('should extract detail from 400 body when available', () => {
    http.get('/api/documents').subscribe({ error: () => {} });

    const req = httpMock.expectOne('/api/documents');
    req.flush({ detail: 'Campo requerido: nombre' }, { status: 400, statusText: 'Bad Request' });

    expect(notifications.show).toHaveBeenCalledWith('Campo requerido: nombre');
  });

  it('should show permission error for status 403', () => {
    http.get('/api/admin').subscribe({ error: () => {} });

    const req = httpMock.expectOne('/api/admin');
    req.flush(null, { status: 403, statusText: 'Forbidden' });

    expect(notifications.show).toHaveBeenCalledWith('No tienes permisos para esta accion.');
  });

  it('should show not found for status 404', () => {
    http.get('/api/documents/999').subscribe({ error: () => {} });

    const req = httpMock.expectOne('/api/documents/999');
    req.flush(null, { status: 404, statusText: 'Not Found' });

    expect(notifications.show).toHaveBeenCalledWith('Recurso no encontrado.');
  });

  it('should show server error for status 500', () => {
    http.get('/api/documents').subscribe({ error: () => {} });

    const req = httpMock.expectOne('/api/documents');
    req.flush(null, { status: 500, statusText: 'Internal Server Error' });

    expect(notifications.show).toHaveBeenCalledWith('Error interno del servidor.');
  });

  it('should show server error for status 502', () => {
    http.get('/api/documents').subscribe({ error: () => {} });

    const req = httpMock.expectOne('/api/documents');
    req.flush(null, { status: 502, statusText: 'Bad Gateway' });

    expect(notifications.show).toHaveBeenCalledWith('Error interno del servidor.');
  });

  it('should re-throw the error to subscribers', () => {
    let errorReceived: HttpErrorResponse | undefined;
    http.get('/api/documents').subscribe({
      error: (err) => (errorReceived = err),
    });

    const req = httpMock.expectOne('/api/documents');
    req.flush(null, { status: 500, statusText: 'Internal Server Error' });

    expect(errorReceived).toBeDefined();
    expect(errorReceived!.status).toBe(500);
  });

  // ─── Error detail extraction shapes ──────────────────────────────

  it('should extract string payload', () => {
    http.get('/api/documents').subscribe({ error: () => {} });

    const req = httpMock.expectOne('/api/documents');
    req.flush('Algo salio mal', { status: 422, statusText: 'Unprocessable' });

    expect(notifications.show).toHaveBeenCalledWith('Algo salio mal');
  });

  it('should extract error string from body', () => {
    http.get('/api/documents').subscribe({ error: () => {} });

    const req = httpMock.expectOne('/api/documents');
    req.flush({ error: 'Token invalido' }, { status: 422, statusText: 'Unprocessable' });

    expect(notifications.show).toHaveBeenCalledWith('Token invalido');
  });

  it('should extract error.message from nested object', () => {
    http.get('/api/documents').subscribe({ error: () => {} });

    const req = httpMock.expectOne('/api/documents');
    req.flush({ error: { message: 'Nested error msg' } }, { status: 422, statusText: 'Unprocessable' });

    expect(notifications.show).toHaveBeenCalledWith('Nested error msg');
  });

  it('should extract message field', () => {
    http.get('/api/documents').subscribe({ error: () => {} });

    const req = httpMock.expectOne('/api/documents');
    req.flush({ message: 'Mensaje de error' }, { status: 422, statusText: 'Unprocessable' });

    expect(notifications.show).toHaveBeenCalledWith('Mensaje de error');
  });

  // ─── 401 on login – no refresh attempt ───────────────────────────

  it('should NOT attempt refresh for login 401', () => {
    let errorReceived: HttpErrorResponse | undefined;
    http.post('/api/auth/login', { username: 'a', password: 'b' }).subscribe({
      error: (err) => (errorReceived = err),
    });

    const req = httpMock.expectOne('/api/auth/login');
    req.flush(null, { status: 401, statusText: 'Unauthorized' });

    expect(errorReceived!.status).toBe(401);
    expect(router.navigate).not.toHaveBeenCalled();
  });

  // ─── 401 on refresh – logout immediately ─────────────────────────

  it('should logout and redirect when refresh endpoint returns 401', () => {
    spyOn(authService, 'logout');

    let errorReceived: HttpErrorResponse | undefined;
    http.post('/api/auth/refresh', { refresh_token: 'abc' }).subscribe({
      error: (err) => (errorReceived = err),
    });

    const req = httpMock.expectOne('/api/auth/refresh');
    req.flush(null, { status: 401, statusText: 'Unauthorized' });

    expect(authService.logout).toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith(['/login']);
    expect(notifications.show).toHaveBeenCalledWith('Sesion expirada. Inicia sesion nuevamente.');
  });

  // ─── 401 with no refresh token stored ────────────────────────────

  it('should logout and redirect when no refresh token available', () => {
    spyOn(authService, 'logout');
    spyOn(authService, 'getRefreshToken').and.returnValue(null);

    let errorReceived: HttpErrorResponse | undefined;
    http.get('/api/documents').subscribe({
      error: (err) => (errorReceived = err),
    });

    const req = httpMock.expectOne('/api/documents');
    req.flush(null, { status: 401, statusText: 'Unauthorized' });

    expect(authService.logout).toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith(['/login']);
    expect(notifications.show).toHaveBeenCalledWith('Sesion expirada. Inicia sesion nuevamente.');
  });

  // ─── 401 with successful token refresh ───────────────────────────

  it('should refresh token and retry the original request on 401', () => {
    const newToken = 'new-access-token';
    spyOn(authService, 'getRefreshToken').and.returnValue('valid-refresh');
    spyOn(authService, 'setToken');
    spyOn(authService, 'setRefreshToken');

    let result: any;
    http.get('/api/documents').subscribe({ next: (data) => (result = data) });

    // Original request returns 401
    const originalReq = httpMock.expectOne('/api/documents');
    originalReq.flush(null, { status: 401, statusText: 'Unauthorized' });

    // Interceptor fires refresh call
    const refreshReq = httpMock.expectOne((r) => r.url.includes('/api/auth/refresh'));
    refreshReq.flush({
      token: newToken,
      refresh_token: 'new-refresh',
      username: 'admin',
      role: 'admin',
    });

    // Interceptor retries original request with new token
    const retryReq = httpMock.expectOne('/api/documents');
    expect(retryReq.request.headers.get('Authorization')).toBe(`Bearer ${newToken}`);
    retryReq.flush([{ id: 1 }]);

    expect(authService.setToken).toHaveBeenCalledWith(newToken);
    expect(authService.setRefreshToken).toHaveBeenCalled();
    expect(result).toEqual([{ id: 1 }]);
  });

  // ─── 401 with failed token refresh ──────────────────────────────

  it('should logout and redirect when token refresh fails', () => {
    spyOn(authService, 'getRefreshToken').and.returnValue('expired-refresh');
    spyOn(authService, 'logout');

    let errorReceived: HttpErrorResponse | undefined;
    http.get('/api/documents').subscribe({
      error: (err) => (errorReceived = err),
    });

    // Original request returns 401
    const originalReq = httpMock.expectOne('/api/documents');
    originalReq.flush(null, { status: 401, statusText: 'Unauthorized' });

    // Refresh also fails
    const refreshReq = httpMock.expectOne((r) => r.url.includes('/api/auth/refresh'));
    refreshReq.flush(null, { status: 401, statusText: 'Unauthorized' });

    expect(authService.logout).toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith(['/login']);
    expect(notifications.show).toHaveBeenCalledWith('Sesion expirada. Inicia sesion nuevamente.');
    expect(errorReceived).toBeDefined();
  });
});
