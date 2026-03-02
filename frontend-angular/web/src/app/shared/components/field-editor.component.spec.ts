import { TestBed } from '@angular/core/testing';
import { FieldEditorComponent } from './field-editor.component';

describe('FieldEditorComponent', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<FieldEditorComponent>>;
  let component: FieldEditorComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [FieldEditorComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(FieldEditorComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('should display label', () => {
    component.label = 'Nombre';
    fixture.detectChanges();
    const label = fixture.nativeElement.querySelector('label');
    expect(label.textContent.trim()).toBe('Nombre');
  });

  it('should sync currentValue from value input', () => {
    component.value = 'test value';
    component.ngOnChanges();
    expect(component.currentValue).toBe('test value');
  });

  it('should handle null value', () => {
    component.value = null;
    component.ngOnChanges();
    expect(component.currentValue).toBe('');
  });

  it('should emit valueChange on input', () => {
    fixture.detectChanges();
    spyOn(component.valueChange, 'emit');
    component.emitChange('new value');
    expect(component.valueChange.emit).toHaveBeenCalledWith('new value');
  });

  it('should show valid text when valid', () => {
    component.valid = true;
    fixture.detectChanges();
    const meta = fixture.nativeElement.querySelector('.meta span');
    expect(meta.textContent.trim()).toBe('Válido');
    expect(meta.classList.contains('invalid')).toBeFalse();
  });

  it('should show invalid text when invalid', () => {
    component.valid = false;
    fixture.detectChanges();
    const meta = fixture.nativeElement.querySelector('.meta span');
    expect(meta.textContent.trim()).toBe('Inválido');
    expect(meta.classList.contains('invalid')).toBeTrue();
  });

  it('should display error messages', () => {
    component.errors = ['Error 1', 'Error 2'];
    fixture.detectChanges();
    const spans = fixture.nativeElement.querySelectorAll('.meta span');
    // First span is valid/invalid, rest are errors
    expect(spans.length).toBe(3);
    expect(spans[1].textContent.trim()).toBe('Error 1');
    expect(spans[2].textContent.trim()).toBe('Error 2');
  });
});
