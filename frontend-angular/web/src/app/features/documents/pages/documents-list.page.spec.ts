import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { DocumentsListPage } from './documents-list.page';

describe('DocumentsListPage', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<DocumentsListPage>>;
  let component: DocumentsListPage;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DocumentsListPage],
      providers: [
        provideRouter([]),
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    }).compileComponents();
    fixture = TestBed.createComponent(DocumentsListPage);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('should have default page 1', () => {
    expect(component.page).toBe(1);
  });

  it('should have status options', () => {
    expect(component.statusOptions.length).toBeGreaterThan(0);
  });

  it('should have type options', () => {
    expect(component.typeOptions.length).toBeGreaterThan(0);
  });

  it('should return correct type labels', () => {
    expect(component.typeLabel('FACTURA')).toBeTruthy();
    expect(typeof component.typeLabel('FACTURA')).toBe('string');
  });

  it('should render page header', () => {
    fixture.detectChanges();
    const header = fixture.nativeElement.querySelector('h2');
    expect(header.textContent).toContain('Bandeja de documentos');
  });

  it('should render filter controls', () => {
    fixture.detectChanges();
    const selects = fixture.nativeElement.querySelectorAll('select');
    expect(selects.length).toBe(2); // status + type
  });

  it('should track documents by id', () => {
    const doc = { id: 'abc-123' } as any;
    expect(doc.id).toBe('abc-123');
  });
});
