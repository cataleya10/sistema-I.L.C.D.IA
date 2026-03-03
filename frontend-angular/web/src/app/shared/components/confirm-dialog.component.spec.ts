import { TestBed } from '@angular/core/testing';
import { ConfirmDialogComponent } from './confirm-dialog.component';

describe('ConfirmDialogComponent', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<ConfirmDialogComponent>>;
  let component: ConfirmDialogComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ConfirmDialogComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(ConfirmDialogComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('should not render backdrop when closed', () => {
    component.open = false;
    fixture.detectChanges();
    const backdrop = fixture.nativeElement.querySelector('.backdrop');
    expect(backdrop).toBeNull();
  });

  it('should render backdrop and dialog when open', () => {
    component.open = true;
    fixture.detectChanges();
    const backdrop = fixture.nativeElement.querySelector('.backdrop');
    const dialog = fixture.nativeElement.querySelector('.dialog');
    expect(backdrop).toBeTruthy();
    expect(dialog).toBeTruthy();
  });

  it('should display custom title and message', () => {
    component.open = true;
    component.title = '¿Eliminar?';
    component.message = 'Esta acción no se puede deshacer.';
    fixture.detectChanges();

    const h3 = fixture.nativeElement.querySelector('h3');
    const p = fixture.nativeElement.querySelector('p');
    expect(h3.textContent).toContain('¿Eliminar?');
    expect(p.textContent).toContain('Esta acción no se puede deshacer.');
  });

  it('should display default title and message', () => {
    component.open = true;
    fixture.detectChanges();

    const h3 = fixture.nativeElement.querySelector('h3');
    const p = fixture.nativeElement.querySelector('p');
    expect(h3.textContent).toContain('Confirmación');
    expect(p.textContent).toContain('¿Deseas continuar?');
  });

  it('should emit confirm when confirm button clicked', () => {
    component.open = true;
    fixture.detectChanges();
    spyOn(component.confirm, 'emit');

    const buttons = fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>;
    const confirmBtn = Array.from(buttons).find((b) => b.textContent?.trim() === 'Confirmar')!;
    confirmBtn.click();

    expect(component.confirm.emit).toHaveBeenCalled();
  });

  it('should emit cancel when cancel button clicked', () => {
    component.open = true;
    fixture.detectChanges();
    spyOn(component.cancel, 'emit');

    const buttons = fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>;
    const cancelBtn = Array.from(buttons).find((b) => b.textContent?.trim() === 'Cancelar')!;
    cancelBtn.click();

    expect(component.cancel.emit).toHaveBeenCalled();
  });
});
