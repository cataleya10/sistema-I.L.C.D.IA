import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { AuditFolderResponse, SystemService, SystemInfo, SystemMetrics } from './system.service';

describe('SystemService', () => {
  let service: SystemService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(SystemService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should GET system info', () => {
    const mockInfo: SystemInfo = {
      service_name: 'ILCDIA',
      pipeline_version: '2.1.0',
      model_version: '1.5.0',
      timestamp: '2026-03-01T00:00:00Z',
    };

    service.getInfo().subscribe((info) => {
      expect(info).toEqual(mockInfo);
    });

    const req = httpMock.expectOne((r) => r.url.includes('/api/system/info'));
    expect(req.request.method).toBe('GET');
    req.flush(mockInfo);
  });

  it('should GET system metrics', () => {
    const mockMetrics: SystemMetrics = {
      requests: 1234,
      errors: 5,
      timestamp: '2026-03-01T00:00:00Z',
    };

    service.getMetrics().subscribe((metrics) => {
      expect(metrics).toEqual(mockMetrics);
    });

    const req = httpMock.expectOne((r) => r.url.includes('/api/system/metrics'));
    expect(req.request.method).toBe('GET');
    req.flush(mockMetrics);
  });

  it('should POST folder audit payload', () => {
    const mockResponse: AuditFolderResponse = {
      folder_path: 'C:\\audits\\nomina',
      recurse: true,
      limit: 50,
      issues_only: false,
      matched_files: 10,
      processed_files: 10,
      documents_returned: 2,
      clean_count: 8,
      issue_count: 2,
      error_count: 0,
      hard_fail_count: 0,
      non_factura_count: 0,
      document_type_counts: { FACTURA: 10 },
      documents: []
    };

    service
      .auditFolder({
        folder_path: 'C:\\audits\\nomina',
        recurse: true,
        limit: 50,
        issues_only: false
      })
      .subscribe((response) => {
        expect(response).toEqual(mockResponse);
      });

    const req = httpMock.expectOne((r) => r.url.includes('/api/documents/diagnostics/audit-folder'));
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      folder_path: 'C:\\audits\\nomina',
      recurse: true,
      limit: 50,
      issues_only: false
    });
    req.flush(mockResponse);
  });
});
