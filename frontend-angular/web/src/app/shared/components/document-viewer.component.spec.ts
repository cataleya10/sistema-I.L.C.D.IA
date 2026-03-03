import { TestBed } from '@angular/core/testing';
import { DocumentViewerComponent } from './document-viewer.component';

describe('DocumentViewerComponent', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<DocumentViewerComponent>>;
  let component: DocumentViewerComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DocumentViewerComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(DocumentViewerComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('should show empty message when no file', () => {
    fixture.detectChanges();
    const msg = fixture.nativeElement.querySelector('.viewer-message');
    expect(msg.textContent).toContain('Sin documento seleccionado.');
  });

  it('should show loading message when loading', () => {
    component.loading = true;
    fixture.detectChanges();
    const msg = fixture.nativeElement.querySelector('.viewer-message');
    expect(msg.textContent).toContain('Cargando vista previa...');
  });

  it('should show error message when set', () => {
    component.errorMessage = 'Fallo al cargar';
    fixture.detectChanges();
    const msg = fixture.nativeElement.querySelector('.viewer-message');
    expect(msg.textContent).toContain('Fallo al cargar');
  });

  it('should render image when fileUrl is set and not PDF', () => {
    component.fileUrl = 'http://localhost/test.png';
    component.mimeType = 'image/png';
    component.ngOnChanges();
    fixture.detectChanges();
    const img = fixture.nativeElement.querySelector('img');
    expect(img).toBeTruthy();
    expect(img.src).toContain('test.png');
  });

  it('should render iframe for PDF', () => {
    component.fileUrl = 'http://localhost/test.pdf';
    component.mimeType = 'application/pdf';
    component.ngOnChanges();
    fixture.detectChanges();
    const iframe = fixture.nativeElement.querySelector('iframe');
    expect(iframe).toBeTruthy();
  });

  it('should detect isPdf correctly', () => {
    component.mimeType = 'application/pdf';
    expect(component.isPdf).toBeTrue();

    component.mimeType = 'image/png';
    expect(component.isPdf).toBeFalse();

    component.mimeType = null;
    expect(component.isPdf).toBeFalse();
  });

  // ─── Zoom controls ────────────────────────────────────────────

  it('should start at 100% zoom', () => {
    expect(component.zoomValue).toBe(1);
    expect(component.zoomPercent).toBe(100);
  });

  it('should zoom in', () => {
    component.fileUrl = 'http://localhost/test.png';
    component.mimeType = 'image/png';
    component.ngOnChanges();

    component.zoomIn();
    expect(component.zoomValue).toBeGreaterThan(1);
    expect(component.zoomPercent).toBe(110);
  });

  it('should zoom out', () => {
    component.fileUrl = 'http://localhost/test.png';
    component.mimeType = 'image/png';
    component.ngOnChanges();

    component.zoomOut();
    expect(component.zoomValue).toBeLessThan(1);
    expect(component.zoomPercent).toBe(90);
  });

  it('should not zoom below minZoom', () => {
    component.zoomValue = component.minZoom;
    component.zoomOut();
    expect(component.zoomValue).toBe(component.minZoom);
  });

  it('should not zoom above maxZoom', () => {
    component.zoomValue = component.maxZoom;
    component.zoomIn();
    expect(component.zoomValue).toBe(component.maxZoom);
  });

  it('should reset zoom', () => {
    component.fileUrl = 'http://localhost/test.png';
    component.mimeType = 'image/png';
    component.ngOnChanges();

    component.zoomIn();
    component.zoomIn();
    expect(component.zoomValue).toBeGreaterThan(1);

    component.resetZoom();
    expect(component.zoomValue).toBe(1);
  });

  it('should reset zoom when fileUrl changes', () => {
    component.fileUrl = 'http://localhost/a.png';
    component.mimeType = 'image/png';
    component.ngOnChanges();
    component.zoomIn();
    component.zoomIn();

    component.fileUrl = 'http://localhost/b.png';
    component.ngOnChanges();
    expect(component.zoomValue).toBe(1);
  });

  it('should compute imageTransform', () => {
    component.zoomValue = 1.5;
    expect(component.imageTransform).toBe('scale(1.50)');
  });

  it('should show toolbar when fileUrl exists and not loading', () => {
    component.fileUrl = 'http://localhost/test.png';
    component.mimeType = 'image/png';
    component.loading = false;
    component.errorMessage = null;
    component.ngOnChanges();
    fixture.detectChanges();
    const toolbar = fixture.nativeElement.querySelector('.viewer-toolbar');
    expect(toolbar).toBeTruthy();
  });

  it('should show kind label Imagen for non-pdf', () => {
    component.fileUrl = 'http://localhost/test.png';
    component.mimeType = 'image/png';
    component.ngOnChanges();
    fixture.detectChanges();
    const kind = fixture.nativeElement.querySelector('.viewer-kind');
    expect(kind.textContent.trim()).toBe('Imagen');
  });

  it('should show kind label PDF for pdf', () => {
    component.fileUrl = 'http://localhost/test.pdf';
    component.mimeType = 'application/pdf';
    component.ngOnChanges();
    fixture.detectChanges();
    const kind = fixture.nativeElement.querySelector('.viewer-kind');
    expect(kind.textContent.trim()).toBe('PDF');
  });
});
