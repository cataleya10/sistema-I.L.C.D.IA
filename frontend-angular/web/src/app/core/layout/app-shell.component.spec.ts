import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { AppShellComponent } from './app-shell.component';
import { AuthService } from '../services/auth.service';
import { NotificationService } from '../services/notification.service';

describe('AppShellComponent', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<AppShellComponent>>;
  let component: AppShellComponent;
  let httpMock: HttpTestingController;
  let authService: AuthService;
  let notifications: NotificationService;
  let router: Router;

  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      imports: [AppShellComponent],
      providers: [
        provideRouter([{ path: 'login', component: {} as any }]),
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    authService = TestBed.inject(AuthService);
    notifications = TestBed.inject(NotificationService);
    router = TestBed.inject(Router);
  });

  function createAndFlush(): void {
    fixture = TestBed.createComponent(AppShellComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    // Flush the system info request made in constructor
    const infoReqs = httpMock.match((r) => r.url.includes('/api/system/info'));
    infoReqs.forEach((r) => r.flush({ service_name: 'ILCDIA', pipeline_version: '2.0', model_version: '1.0', timestamp: '' }));
  }

  afterEach(() => {
    httpMock.verify();
    component?.ngOnDestroy();
  });

  it('should create', () => {
    createAndFlush();
    expect(component).toBeTruthy();
  });

  it('should render title', () => {
    createAndFlush();
    const h1 = fixture.nativeElement.querySelector('h1');
    expect(h1.textContent).toContain('SISTEMA DE LECTURA INTELIGENTE');
  });

  it('should show login link when not authenticated', () => {
    createAndFlush();
    fixture.detectChanges();
    const links = fixture.nativeElement.querySelectorAll('a');
    const loginLink = Array.from(links as NodeListOf<HTMLAnchorElement>).find((l) =>
      l.textContent?.includes('Login')
    );
    expect(loginLink).toBeTruthy();
  });

  it('should show nav links when authenticated', () => {
    const token = buildJwt(Math.floor(Date.now() / 1000) + 300);
    authService.setToken(token);

    createAndFlush();
    fixture.detectChanges();

    const links = fixture.nativeElement.querySelectorAll('a');
    const texts = Array.from(links as NodeListOf<HTMLAnchorElement>).map((l) => l.textContent?.trim());
    expect(texts).toContain('Carga');
    expect(texts).toContain('Bandeja');
    expect(texts).toContain('Sistema');
  });

  it('should display system info version', () => {
    createAndFlush();
    fixture.detectChanges();
    const version = fixture.nativeElement.querySelector('.version');
    expect(version?.textContent).toContain('2.0');
  });

  it('should show toast when notification fires', () => {
    createAndFlush();
    notifications.show('Algo paso');
    fixture.detectChanges();

    expect(component.toastMessage).toBe('Algo paso');
  });

  it('should clear toast on dismiss', () => {
    createAndFlush();
    notifications.show('Test');
    fixture.detectChanges();

    component.clearToast();
    expect(component.toastMessage).toBeNull();
  });

  it('should show user info when authenticated', () => {
    const token = buildJwt(Math.floor(Date.now() / 1000) + 300);
    authService.setToken(token);
    authService.setUser('admin', 'ADMIN');

    createAndFlush();
    fixture.detectChanges();

    expect(component.userName).toBe('admin');
    expect(component.userRole).toBe('ADMIN');
  });

  it('should logout and navigate to login', () => {
    const token = buildJwt(Math.floor(Date.now() / 1000) + 300);
    authService.setToken(token);
    authService.setRefreshToken('refresh-tok');
    spyOn(router, 'navigate');

    createAndFlush();
    component.logout();

    // Flush the remote logout call
    const logoutReqs = httpMock.match((r) => r.url.includes('/api/auth/logout'));
    logoutReqs.forEach((r) => r.flush({}));

    expect(router.navigate).toHaveBeenCalledWith(['/login']);
  });

  it('should unsubscribe on destroy', () => {
    createAndFlush();
    expect(() => component.ngOnDestroy()).not.toThrow();
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
