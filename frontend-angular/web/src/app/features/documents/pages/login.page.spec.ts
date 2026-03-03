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
});

function buildJwt(exp: number): string {
  const header = base64UrlEncode(JSON.stringify({ alg: 'none', typ: 'JWT' }));
  const payload = base64UrlEncode(JSON.stringify({ exp }));
  return `${header}.${payload}.signature`;
}

function base64UrlEncode(value: string): string {
  return btoa(value).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}
