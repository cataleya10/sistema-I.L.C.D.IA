import { TestBed } from '@angular/core/testing';
import { ToastNotificationComponent } from './toast-notification.component';

describe('ToastNotificationComponent', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<ToastNotificationComponent>>;
  let component: ToastNotificationComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ToastNotificationComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(ToastNotificationComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('should not render toast when message is null', () => {
    component.message = null;
    fixture.detectChanges();
    const toast = fixture.nativeElement.querySelector('.toast');
    expect(toast).toBeNull();
  });

  it('should render toast when message is set', () => {
    component.message = 'Archivo guardado';
    fixture.detectChanges();
    const toast = fixture.nativeElement.querySelector('.toast');
    expect(toast).toBeTruthy();
    expect(toast.textContent).toContain('Archivo guardado');
  });

  it('should emit dismiss when close button is clicked', () => {
    component.message = 'Test';
    fixture.detectChanges();
    spyOn(component.dismiss, 'emit');

    const btn = fixture.nativeElement.querySelector('button');
    btn.click();

    expect(component.dismiss.emit).toHaveBeenCalled();
  });
});
