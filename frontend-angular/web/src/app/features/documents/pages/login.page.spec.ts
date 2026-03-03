import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { LoginPage } from './login.page';
import { AuthService } from '../../../core/services/auth.service';

describe('LoginPage', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<LoginPage>>;
  let component: LoginPage;
  let authService: AuthService;
  let httpMock: HttpTestingController;
  let router: Router;

  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      imports: [LoginPage],
      providers: [
        provideRouter([
          { path: 'documents', component: {} as any },
          { path: 'login', component: LoginPage },
        ]),
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    }).compileComponents();

    authService = TestBed.inject(AuthService);
    httpMock = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    spyOn(router, 'navigate');
  });

  function createComponent(): void {
    fixture = TestBed.createComponent(LoginPage);
    component = fixture.componentInstance;
    fixture.detectChanges();
  }

  afterEach(() => {
    httpMock.verify();
  });

  it('should create', () => {
    createComponent();
    expect(component).toBeTruthy();
  });

  it('should render login form', () => {
    createComponent();
    const h2 = fixture.nativeElement.querySelector('h2');
    expect(h2.textContent).toContain('Iniciar sesion');
  });

  it('should redirect to /documents if already authenticated', () => {
    const token = buildJwt(Math.floor(Date.now() / 1000) + 300);
    authService.setToken(token);

    createComponent();
    expect(router.navigate).toHaveBeenCalledWith(['/documents']);
  });

  it('should show error on empty username', () => {
    createComponent();
    component.username = '  ';
    component.password = 'pass';
    component.submit();

    expect(component.error).toBeTrue();
  });

  it('should show error on empty password', () => {
    createComponent();
    component.username = 'admin';
    component.password = '';
    component.submit();

    expect(component.error).toBeTrue();
  });

  it('should call auth.login on valid submit', () => {
    createComponent();
    component.username = 'admin';
    component.password = 'secret';
    component.submit();

    expect(component.isSubmitting).toBeTrue();

    const req = httpMock.expectOne((r) => r.url.includes('/api/auth/login'));
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ username: 'admin', password: 'secret' });

    req.flush({
      token: 'new-token',
      refresh_token: 'new-refresh',
      username: 'admin',
      role: 'admin',
    });

    expect(component.isSubmitting).toBeFalse();
    expect(router.navigate).toHaveBeenCalledWith(['/documents']);
  });

  it('should show error on login failure', () => {
    createComponent();
    component.username = 'admin';
    component.password = 'wrong';
    component.submit();

    const req = httpMock.expectOne((r) => r.url.includes('/api/auth/login'));
    req.flush(null, { status: 401, statusText: 'Unauthorized' });

    expect(component.error).toBeTrue();
    expect(component.isSubmitting).toBeFalse();
  });

  it('should disable button while submitting', () => {
    createComponent();
    component.isSubmitting = true;
    fixture.detectChanges();

    const button = fixture.nativeElement.querySelector('button[type="submit"]');
    expect(button.disabled).toBeTrue();
    expect(button.textContent).toContain('Ingresando...');
  });

  it('should show error alert in template', () => {
    createComponent();
    component.error = true;
    fixture.detectChanges();

    const alert = fixture.nativeElement.querySelector('[role="alert"]');
    expect(alert).toBeTruthy();
    expect(alert.textContent).toContain('Credenciales invalidas');
  });

  it('should hide google button when googleClientId is not configured', () => {
    createComponent();
    expect(component.googleEnabled).toBeFalse();

    const googleBtn = fixture.nativeElement.querySelector('#google-signin-btn');
    expect(googleBtn).toBeNull();
  });

  it('should show google button when googleClientId is configured', () => {
    (window as any).__APP_CONFIG__ = { apiUrl: 'http://localhost:5000', googleClientId: 'test-client-id' };
    createComponent();
    expect(component.googleEnabled).toBeTrue();

    const divider = fixture.nativeElement.querySelector('.divider');
    expect(divider).toBeTruthy();
    expect(divider.textContent).toContain('o');

    (window as any).__APP_CONFIG__ = { apiUrl: 'http://localhost:5000', googleClientId: '' };
  });

  // ─── Register mode ──────────────────────────────────────

  it('should toggle to register mode', () => {
    createComponent();
    expect(component.isRegisterMode).toBeFalse();

    component.toggleMode();
    fixture.detectChanges();

    expect(component.isRegisterMode).toBeTrue();
    const h2 = fixture.nativeElement.querySelector('h2');
    expect(h2.textContent).toContain('Registrarse');
  });

  it('should toggle back to login mode', () => {
    createComponent();
    component.toggleMode(); // to register
    component.toggleMode(); // back to login
    fixture.detectChanges();

    expect(component.isRegisterMode).toBeFalse();
    const h2 = fixture.nativeElement.querySelector('h2');
    expect(h2.textContent).toContain('Iniciar sesion');
  });

  it('should show register error for invalid email', () => {
    createComponent();
    component.toggleMode();
    component.regEmail = 'not-an-email';
    component.regPassword = 'secret123';
    component.submitRegister();

    expect(component.registerError).toBeTruthy();
  });

  it('should show register error for short password', () => {
    createComponent();
    component.toggleMode();
    component.regEmail = 'user@example.com';
    component.regPassword = '12345';
    component.submitRegister();

    expect(component.registerError).toContain('6 caracteres');
  });

  it('should call auth.register on valid register submit', () => {
    createComponent();
    component.toggleMode();
    component.regEmail = 'user@example.com';
    component.regPassword = 'secret123';
    component.submitRegister();

    expect(component.isSubmitting).toBeTrue();

    const req = httpMock.expectOne((r) => r.url.includes('/api/auth/register'));
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ email: 'user@example.com', password: 'secret123' });

    req.flush({
      token: 'new-token',
      refreshToken: 'new-refresh',
      username: 'user@example.com',
      role: 'User',
    });

    expect(component.isSubmitting).toBeFalse();
    expect(router.navigate).toHaveBeenCalledWith(['/documents']);
  });

  it('should show error on register failure', () => {
    createComponent();
    component.toggleMode();
    component.regEmail = 'dup@example.com';
    component.regPassword = 'secret123';
    component.submitRegister();

    const req = httpMock.expectOne((r) => r.url.includes('/api/auth/register'));
    req.flush({ error: 'El correo ya esta registrado' }, { status: 400, statusText: 'Bad Request' });

    expect(component.registerError).toContain('ya esta registrado');
    expect(component.isSubmitting).toBeFalse();
  });

  it('should clear errors when toggling mode', () => {
    createComponent();
    component.error = true;
    component.googleError = 'some error';
    component.toggleMode();

    expect(component.error).toBeFalse();
    expect(component.googleError).toBe('');
    expect(component.registerError).toBe('');
    expect(component.registerSuccess).toBeFalse();
  });

  it('should render toggle link', () => {
    createComponent();
    const link = fixture.nativeElement.querySelector('.toggle-link a');
    expect(link).toBeTruthy();
    expect(link.textContent).toContain('Registrarme');
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
