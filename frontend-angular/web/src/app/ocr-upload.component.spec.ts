import { TestBed, ComponentFixture } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { OcrUploadComponent } from './ocr-upload.component';
import { By } from '@angular/platform-browser';

describe('OcrUploadComponent', () => {
  let component: OcrUploadComponent;
  let fixture: ComponentFixture<OcrUploadComponent>;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      declarations: [OcrUploadComponent],
      imports: [HttpClientTestingModule]
    });
    fixture = TestBed.createComponent(OcrUploadComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  it('debe subir imagen y mostrar resultado', () => {
    // Simula selección de archivo
    const file = new File(['dummy'], 'test.jpg', { type: 'image/jpeg' });
    component.selectedFile = file;
    component.uploadImage();

    // Simula respuesta del backend
    const req = httpMock.expectOne('/api/ocr/upload');
    expect(req.request.method).toBe('POST');
    req.flush({
      campos: [{ key: 'nombre', value: 'Juan' }],
      tablas: [[['col1', 'col2'], ['val1', 'val2']]],
      tipo_documento: 'INE',
      confianza: 0.95,
      advertencias: []
    });

    expect(component.ocrResult.campos[0].key).toBe('nombre');
    expect(component.ocrResult.tipo_documento).toBe('INE');
  });
});
