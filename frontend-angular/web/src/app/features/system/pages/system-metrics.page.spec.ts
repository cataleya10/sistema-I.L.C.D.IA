import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { SystemMetricsPage } from './system-metrics.page';

describe('SystemMetricsPage', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<SystemMetricsPage>>;
  let component: SystemMetricsPage;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SystemMetricsPage],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    }).compileComponents();
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should create', () => {
    fixture = TestBed.createComponent(SystemMetricsPage);
    component = fixture.componentInstance;
    expect(component).toBeTruthy();

    // Flush the auto-load on init
    fixture.detectChanges();
    const req = httpMock.expectOne((r) => r.url.includes('/api/system/metrics'));
    req.flush({ requests: 10, errors: 1, timestamp: '2026-03-01T00:00:00Z' });
  });

  it('should render page header', () => {
    fixture = TestBed.createComponent(SystemMetricsPage);
    component = fixture.componentInstance;
    fixture.detectChanges();

    const h2 = fixture.nativeElement.querySelector('h2');
    expect(h2.textContent).toContain('Estado del sistema');

    const req = httpMock.expectOne((r) => r.url.includes('/api/system/metrics'));
    req.flush({ requests: 0, errors: 0, timestamp: '2026-03-01T00:00:00Z' });
  });

  it('should show loading while fetching', () => {
    fixture = TestBed.createComponent(SystemMetricsPage);
    component = fixture.componentInstance;
    fixture.detectChanges();

    expect(component.isLoading).toBeTrue();
    const loadingEl = fixture.nativeElement.querySelector('.loading');
    expect(loadingEl?.textContent).toContain('Cargando metricas');

    const req = httpMock.expectOne((r) => r.url.includes('/api/system/metrics'));
    req.flush({ requests: 0, errors: 0, timestamp: '2026-03-01T00:00:00Z' });
  });

  it('should display metrics after successful load', () => {
    fixture = TestBed.createComponent(SystemMetricsPage);
    component = fixture.componentInstance;
    fixture.detectChanges();

    const req = httpMock.expectOne((r) => r.url.includes('/api/system/metrics'));
    req.flush({ requests: 1234, errors: 5, timestamp: '2026-03-01T00:00:00Z' });
    fixture.detectChanges();

    expect(component.metrics).toBeTruthy();
    expect(component.metrics!.requests).toBe(1234);
    expect(component.metrics!.errors).toBe(5);
    expect(component.isLoading).toBeFalse();

    const cards = fixture.nativeElement.querySelectorAll('.card');
    expect(cards.length).toBe(3);
  });

  it('should show error on failure', () => {
    fixture = TestBed.createComponent(SystemMetricsPage);
    component = fixture.componentInstance;
    fixture.detectChanges();

    const req = httpMock.expectOne((r) => r.url.includes('/api/system/metrics'));
    req.flush(null, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    expect(component.metrics).toBeNull();
    expect(component.errorMessage).toContain('No se pudieron cargar las metricas');
    expect(component.isLoading).toBeFalse();

    const errorEl = fixture.nativeElement.querySelector('[role="alert"]');
    expect(errorEl).toBeTruthy();
  });

  it('should retry on click', () => {
    fixture = TestBed.createComponent(SystemMetricsPage);
    component = fixture.componentInstance;
    fixture.detectChanges();

    const req1 = httpMock.expectOne((r) => r.url.includes('/api/system/metrics'));
    req1.flush(null, { status: 500, statusText: 'Server Error' });
    fixture.detectChanges();

    component.load();
    const req2 = httpMock.expectOne((r) => r.url.includes('/api/system/metrics'));
    req2.flush({ requests: 42, errors: 0, timestamp: '2026-03-01T00:00:00Z' });

    expect(component.metrics!.requests).toBe(42);
  });
});
