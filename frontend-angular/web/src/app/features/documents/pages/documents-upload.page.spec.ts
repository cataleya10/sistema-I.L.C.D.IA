import { provideHttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { DocumentsUploadPage } from './documents-upload.page';

describe('DocumentsUploadPage', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<DocumentsUploadPage>>;
  let component: DocumentsUploadPage;

  beforeEach(async () => {
    localStorage.clear();

    await TestBed.configureTestingModule({
      imports: [DocumentsUploadPage],
      providers: [provideHttpClient()]
    }).compileComponents();

    fixture = TestBed.createComponent(DocumentsUploadPage);
    component = fixture.componentInstance;
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('should create', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('should render auth form when there is no session', () => {
    fixture.detectChanges();

    const h2 = fixture.nativeElement.querySelector('h2');
    const inputs = fixture.nativeElement.querySelectorAll('input');
    const buttons = fixture.nativeElement.querySelectorAll('button');

    expect(h2?.textContent).toContain('Inicia sesion o crea un usuario local');
    expect(inputs.length).toBe(2);
    expect(buttons.length).toBe(2);
  });
});
