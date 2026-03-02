import { TestBed } from '@angular/core/testing';
import { StatusBadgeComponent } from './status-badge.component';

describe('StatusBadgeComponent', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<StatusBadgeComponent>>;
  let component: StatusBadgeComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [StatusBadgeComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(StatusBadgeComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('should display CARGADO for UPLOADED', () => {
    component.status = 'UPLOADED';
    fixture.detectChanges();
    const badge = fixture.nativeElement.querySelector('.badge');
    expect(badge.textContent.trim()).toBe('CARGADO');
    expect(badge.classList.contains('uploaded')).toBeTrue();
  });

  it('should display PROCESANDO for PROCESSING', () => {
    component.status = 'PROCESSING';
    fixture.detectChanges();
    const badge = fixture.nativeElement.querySelector('.badge');
    expect(badge.textContent.trim()).toBe('PROCESANDO');
  });

  it('should display LISTO for READY', () => {
    component.status = 'READY';
    fixture.detectChanges();
    const badge = fixture.nativeElement.querySelector('.badge');
    expect(badge.textContent.trim()).toBe('LISTO');
    expect(badge.classList.contains('ready')).toBeTrue();
  });

  it('should display REVISAR for NEEDS_REVIEW', () => {
    component.status = 'NEEDS_REVIEW';
    fixture.detectChanges();
    const badge = fixture.nativeElement.querySelector('.badge');
    expect(badge.textContent.trim()).toBe('REVISAR');
  });

  it('should display FALLÓ for FAILED', () => {
    component.status = 'FAILED';
    fixture.detectChanges();
    const badge = fixture.nativeElement.querySelector('.badge');
    expect(badge.textContent.trim()).toBe('FALLÓ');
    expect(badge.classList.contains('failed')).toBeTrue();
  });
});
