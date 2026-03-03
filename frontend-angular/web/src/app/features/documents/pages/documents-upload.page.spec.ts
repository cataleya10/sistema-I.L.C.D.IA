import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { DocumentsUploadPage } from './documents-upload.page';

describe('DocumentsUploadPage', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<DocumentsUploadPage>>;
  let component: DocumentsUploadPage;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DocumentsUploadPage],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    }).compileComponents();
    fixture = TestBed.createComponent(DocumentsUploadPage);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should create', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('should render page header', () => {
    fixture.detectChanges();
    const h2 = fixture.nativeElement.querySelector('h2');
    expect(h2.textContent).toContain('Carga de documentos');
  });

  it('should reject unsupported file type', () => {
    fixture.detectChanges();
    const file = new File(['data'], 'test.docx', { type: 'application/msword' });
    component.handleFile(file);
    expect(component.message).toContain('Tipo de archivo no permitido');
  });

  it('should reject file over 15MB', () => {
    fixture.detectChanges();
    const bigContent = new Uint8Array(16 * 1024 * 1024);
    const file = new File([bigContent], 'big.pdf', { type: 'application/pdf' });
    component.handleFile(file);
    expect(component.message).toContain('excede el maximo');
  });

  it('should upload valid PDF file', () => {
    fixture.detectChanges();
    const file = new File(['pdf content'], 'invoice.pdf', { type: 'application/pdf' });
    component.handleFile(file);

    expect(component.isUploading).toBeTrue();
    expect(component.lastFileName).toBe('invoice.pdf');

    const req = httpMock.expectOne((r) => r.url.includes('/api/documents/upload'));
    expect(req.request.method).toBe('POST');
    req.flush({ id: 'doc1', filename: 'invoice.pdf' });

    expect(component.isUploading).toBeFalse();
    expect(component.message).toContain('Documento cargado correctamente');
  });

  it('should upload valid PNG file', () => {
    fixture.detectChanges();
    const file = new File(['img'], 'scan.png', { type: 'image/png' });
    component.handleFile(file);

    const req = httpMock.expectOne((r) => r.url.includes('/api/documents/upload'));
    req.flush({ id: 'doc2', filename: 'scan.png' });

    expect(component.message).toContain('Documento cargado correctamente');
  });

  it('should handle upload error', () => {
    fixture.detectChanges();
    const file = new File(['data'], 'test.pdf', { type: 'application/pdf' });
    component.handleFile(file);

    const req = httpMock.expectOne((r) => r.url.includes('/api/documents/upload'));
    req.flush('Server error', { status: 500, statusText: 'Internal Server Error' });

    expect(component.isUploading).toBeFalse();
    expect(component.message).toContain('Error al cargar');
  });

  it('should process as FACTURA when toggle is on', () => {
    fixture.detectChanges();
    component.forceFacturaOnUpload = true;
    const file = new File(['data'], 'invoice.pdf', { type: 'application/pdf' });
    component.handleFile(file);

    const uploadReq = httpMock.expectOne((r) => r.url.includes('/api/documents/upload'));
    uploadReq.flush({ id: 'doc1', filename: 'invoice.pdf' });

    const processReq = httpMock.expectOne((r) => r.url.includes('/api/documents/doc1/process'));
    expect(processReq.request.body).toEqual({ forceDocumentType: 'FACTURA' });
    processReq.flush({ status: 'PROCESSING' });

    expect(component.message).toContain('procesamiento forzado como FACTURA');
  });

  it('should not process if already uploading', () => {
    fixture.detectChanges();
    component.isUploading = true;
    const file = new File(['data'], 'test.pdf', { type: 'application/pdf' });
    component.handleFile(file);
    // No requests should be made
  });

  it('should accept JPG by extension', () => {
    fixture.detectChanges();
    const file = new File(['data'], 'photo.jpg', { type: '' });
    component.handleFile(file);

    expect(component.isUploading).toBeTrue();
    const req = httpMock.expectOne((r) => r.url.includes('/api/documents/upload'));
    req.flush({ id: 'doc3' });
  });
});
