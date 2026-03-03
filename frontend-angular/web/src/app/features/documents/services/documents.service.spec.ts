import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient } from '@angular/common/http';
import { DocumentsService, DocumentListQuery } from './documents.service';

describe('DocumentsService', () => {
  let service: DocumentsService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(DocumentsService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  // ─── upload ────────────────────────────────────────────────────

  it('should POST file via FormData on upload', () => {
    const file = new File(['content'], 'test.pdf', { type: 'application/pdf' });

    service.upload(file).subscribe();

    const req = httpMock.expectOne((r) => r.url.includes('/api/documents/upload'));
    expect(req.request.method).toBe('POST');
    expect(req.request.body instanceof FormData).toBeTrue();
    req.flush({ id: 'abc', filename: 'test.pdf' });
  });

  // ─── list ──────────────────────────────────────────────────────

  it('should GET documents list with query params', () => {
    const query: DocumentListQuery = { status: 'READY', page: 1, pageSize: 10 };

    service.list(query).subscribe();

    const req = httpMock.expectOne((r) => r.method === 'GET' && r.url.endsWith('/api/documents'));
    expect(req.request.method).toBe('GET');
    expect(req.request.params.get('status')).toBe('READY');
    expect(req.request.params.get('page')).toBe('1');
    expect(req.request.params.get('pageSize')).toBe('10');
    req.flush([]);
  });

  it('should omit undefined/null/empty params', () => {
    const query: DocumentListQuery = { status: undefined, q: '', page: 2 };

    service.list(query).subscribe();

    const req = httpMock.expectOne((r) => r.url.includes('/api/documents'));
    expect(req.request.params.has('status')).toBeFalse();
    expect(req.request.params.has('q')).toBeFalse();
    expect(req.request.params.get('page')).toBe('2');
    req.flush([]);
  });

  // ─── getById ───────────────────────────────────────────────────

  it('should GET document by id', () => {
    service.getById('abc123').subscribe();

    const req = httpMock.expectOne((r) => r.url.includes('/api/documents/abc123'));
    expect(req.request.method).toBe('GET');
    req.flush({ id: 'abc123' });
  });

  // ─── getFileUrl ────────────────────────────────────────────────

  it('should return file URL string', () => {
    const url = service.getFileUrl('abc123');
    expect(url).toContain('/api/documents/abc123/file');
  });

  // ─── downloadFile ──────────────────────────────────────────────

  it('should GET file as blob', () => {
    service.downloadFile('abc123').subscribe();

    const req = httpMock.expectOne((r) => r.url.includes('/api/documents/abc123/file'));
    expect(req.request.method).toBe('GET');
    expect(req.request.responseType).toBe('blob');
    req.flush(new Blob());
  });

  // ─── process ───────────────────────────────────────────────────

  it('should POST process request', () => {
    service.process('abc123').subscribe();

    const req = httpMock.expectOne((r) => r.url.includes('/api/documents/abc123/process') && !r.url.includes('status'));
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({});
    req.flush({ status: 'PROCESSING' });
  });

  it('should POST process with options', () => {
    service.process('abc123', { forceDocumentType: 'FACTURA' }).subscribe();

    const req = httpMock.expectOne((r) => r.url.includes('/api/documents/abc123/process') && !r.url.includes('status'));
    expect(req.request.body).toEqual({ forceDocumentType: 'FACTURA' });
    req.flush({ status: 'PROCESSING' });
  });

  // ─── getProcessStatus ─────────────────────────────────────────

  it('should GET process status', () => {
    service.getProcessStatus('abc123').subscribe();

    const req = httpMock.expectOne((r) => r.url.includes('/api/documents/abc123/process/status'));
    expect(req.request.method).toBe('GET');
    req.flush({ status: 'READY' });
  });

  // ─── reprocess ────────────────────────────────────────────────

  it('should POST reprocess request', () => {
    service.reprocess('abc123').subscribe();

    const req = httpMock.expectOne((r) => r.url.includes('/api/documents/abc123/reprocess'));
    expect(req.request.method).toBe('POST');
    req.flush({ status: 'PROCESSING' });
  });

  // ─── updateFields ─────────────────────────────────────────────

  it('should PUT updated fields', () => {
    const fields = [{ key: 'invoice_number', value: '12345' }];
    service.updateFields('abc123', fields).subscribe();

    const req = httpMock.expectOne((r) => r.url.includes('/api/documents/abc123/fields'));
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ fields });
    req.flush({});
  });

  // ─── getLogs ───────────────────────────────────────────────────

  it('should GET processing logs', () => {
    service.getLogs('abc123').subscribe();

    const req = httpMock.expectOne((r) => r.url.includes('/api/documents/abc123/logs'));
    expect(req.request.method).toBe('GET');
    req.flush([]);
  });

  // ─── delete ────────────────────────────────────────────────────

  it('should DELETE document', () => {
    service.delete('abc123').subscribe();

    const req = httpMock.expectOne((r) => r.url.includes('/api/documents/abc123'));
    expect(req.request.method).toBe('DELETE');
    req.flush(null);
  });

  // ─── exports ───────────────────────────────────────────────────

  it('should GET word export as blob', () => {
    service.downloadWord('abc123').subscribe();

    const req = httpMock.expectOne((r) => r.url.includes('/api/documents/abc123/export/word'));
    expect(req.request.method).toBe('GET');
    expect(req.request.responseType).toBe('blob');
    req.flush(new Blob());
  });

  it('should GET excel export as blob', () => {
    service.downloadExcel('abc123').subscribe();

    const req = httpMock.expectOne((r) => r.url.includes('/api/documents/abc123/export/excel'));
    expect(req.request.method).toBe('GET');
    expect(req.request.responseType).toBe('blob');
    req.flush(new Blob());
  });
});
