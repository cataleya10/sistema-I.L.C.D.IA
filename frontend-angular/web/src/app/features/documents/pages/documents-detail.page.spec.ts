import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { DocumentsDetailPage } from './documents-detail.page';
import { ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';

describe('DocumentsDetailPage', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<DocumentsDetailPage>>;
  let component: DocumentsDetailPage;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DocumentsDetailPage],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: { get: (_k: string) => null } },
            paramMap: of({ get: (_k: string) => null }),
          },
        },
      ],
    }).compileComponents();

    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(DocumentsDetailPage);
    component = fixture.componentInstance;
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should not load when id is null', () => {
    fixture.detectChanges();
    expect(component.document).toBeNull();
    expect(component.isLoading).toBeFalse();
  });

  it('should initialise with default state', () => {
    expect(component.isLoading).toBeFalse();
    expect(component.isProcessing).toBeFalse();
    expect(component.editMode).toBeFalse();
    expect(component.message).toBeNull();
  });

  it('should hide tabla_celdas for personal documents', () => {
    const mapped = (component as any).mapDisplayFields({
      document_type: 'CONSTANCIA_SITUACION_FISCAL',
      fields: [
        { key: 'rfc', label: 'RFC', value: 'GACE010425NW6', corrected_value: null, confidence: 0.9, valid: true, validation_errors: [] },
        { key: 'tabla_celdas_2', label: 'Tabla detectada #2', value: '{"rows":[["A","B"]]}', corrected_value: null, confidence: 0.9, valid: true, validation_errors: [] },
      ],
    });
    expect(mapped.some((field: any) => String(field.key).toLowerCase().startsWith('tabla_celdas'))).toBeFalse();
  });

  it('should keep tabla_celdas for factura documents', () => {
    const mapped = (component as any).mapDisplayFields({
      document_type: 'FACTURA',
      fields: [
        { key: 'tabla_celdas', label: 'Tabla celdas', value: '{"rows":[["A","B"]]}', corrected_value: null, confidence: 0.9, valid: true, validation_errors: [] },
      ],
    });
    expect(mapped.some((field: any) => String(field.key).toLowerCase() === 'tabla_celdas')).toBeTrue();
  });
});
