import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { AuthService } from '../../../core/services/auth.service';
import { SystemMetricsPage } from './system-metrics.page';

describe('SystemMetricsPage', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<SystemMetricsPage>>;
  let component: SystemMetricsPage;
  let httpMock: HttpTestingController;
  let authStub: { getRole: jasmine.Spy };

  beforeEach(async () => {
    localStorage.removeItem('system.audit.folder.v1');

    authStub = {
      getRole: jasmine.createSpy('getRole').and.returnValue('Admin')
    };

    await TestBed.configureTestingModule({
      imports: [SystemMetricsPage],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: authStub }
      ]
    }).compileComponents();
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    localStorage.removeItem('system.audit.folder.v1');
    httpMock.verify();
  });

  it('should create', () => {
    fixture = TestBed.createComponent(SystemMetricsPage);
    component = fixture.componentInstance;
    expect(component).toBeTruthy();

    fixture.detectChanges();
    flushMetrics();
  });

  it('should render page header and metrics cards', () => {
    fixture = TestBed.createComponent(SystemMetricsPage);
    component = fixture.componentInstance;
    fixture.detectChanges();

    flushMetrics({ requests: 1234, errors: 5, timestamp: '2026-03-01T00:00:00Z' });
    fixture.detectChanges();

    const h2 = fixture.nativeElement.querySelector('h2');
    expect(h2.textContent).toContain('Estado del sistema');

    const cards = fixture.nativeElement.querySelectorAll('.card');
    expect(cards.length).toBeGreaterThanOrEqual(3);
    expect(component.metrics?.requests).toBe(1234);
  });

  it('should show audit result after successful run', () => {
    fixture = TestBed.createComponent(SystemMetricsPage);
    component = fixture.componentInstance;
    fixture.detectChanges();
    flushMetrics();

    component.auditFolderPath = 'C:\\audits\\nomina';
    component.auditLimit = 50;
    component.auditRecurse = true;
    component.auditIssuesOnly = false;
    component.runAudit();

    const req = httpMock.expectOne((r) => r.url.includes('/api/documents/diagnostics/audit-folder'));
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      folder_path: 'C:\\audits\\nomina',
      recurse: true,
      limit: 50,
      issues_only: false
    });

    req.flush({
      folder_path: 'C:\\audits\\nomina',
      recurse: true,
      limit: 50,
      issues_only: false,
      matched_files: 12,
      processed_files: 12,
      documents_returned: 1,
      clean_count: 11,
      issue_count: 1,
      error_count: 0,
      hard_fail_count: 0,
      non_factura_count: 0,
      document_type_counts: { FACTURA: 12 },
      documents: [
        {
          name: 'nomina-01.pdf',
          file_path: 'C:\\audits\\nomina\\nomina-01.pdf',
          status: 'READY',
          document_type: 'FACTURA',
          confidence: 0.99,
          tabla_rows: 5,
          detalle_rows: 4,
          warning_count: 1,
          warnings: ['fila incompleta'],
          hard_fail: false,
          mapped_fields: { referencia: 'ABC123' },
          error: null
        }
      ]
    });
    fixture.detectChanges();

    expect(component.auditResult?.matched_files).toBe(12);
    expect(fixture.nativeElement.textContent).toContain('nomina-01.pdf');
    expect(fixture.nativeElement.textContent).toContain('ABC123');
  });

  it('should show admin notice when user is not admin', () => {
    authStub.getRole.and.returnValue('User');

    fixture = TestBed.createComponent(SystemMetricsPage);
    component = fixture.componentInstance;
    fixture.detectChanges();
    flushMetrics();
    fixture.detectChanges();

    expect(component.canAudit()).toBeFalse();
    expect(fixture.nativeElement.textContent).toContain('solo esta disponible para usuarios con rol Admin');
  });

  function flushMetrics(metrics = { requests: 10, errors: 1, timestamp: '2026-03-01T00:00:00Z' }): void {
    const req = httpMock.expectOne((r) => r.url.includes('/api/system/metrics'));
    expect(req.request.method).toBe('GET');
    req.flush(metrics);
  }
});
