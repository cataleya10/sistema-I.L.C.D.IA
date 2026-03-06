import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { DocumentsResultsPage } from './documents-results.page';
import { ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';

describe('DocumentsResultsPage', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<DocumentsResultsPage>>;
  let component: DocumentsResultsPage;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DocumentsResultsPage],
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
    fixture = TestBed.createComponent(DocumentsResultsPage);
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

  it('should have default empty search', () => {
    expect(component.search).toBe('');
  });

  it('should have onlyInvalid false by default', () => {
    expect(component.onlyInvalid).toBeFalse();
  });

  it('should initialise with empty displayFields', () => {
    expect(component.displayFields).toEqual([]);
  });

  it('should hide tabla_celdas for personal documents', () => {
    const mapped = (component as any).mapDisplayFields({
      document_type: 'INE',
      fields: [
        { key: 'nombre', label: 'Nombre', value: 'JUAN', corrected_value: null, confidence: 0.9, valid: true, validation_errors: [] },
        { key: 'tabla_celdas', label: 'Tabla celdas', value: '{"rows":[["A","B"]]}', corrected_value: null, confidence: 0.9, valid: true, validation_errors: [] },
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
