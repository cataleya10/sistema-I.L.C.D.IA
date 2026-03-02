import { TestBed } from '@angular/core/testing';
import { ReplicaCalibrationPanelComponent, CalibrationFormModel } from './replica-calibration-panel.component';

describe('ReplicaCalibrationPanelComponent', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<ReplicaCalibrationPanelComponent>>;
  let component: ReplicaCalibrationPanelComponent;

  const defaultForm: CalibrationFormModel = {
    scaleX: 1,
    scaleY: 1,
    offsetX: 0,
    offsetY: 0,
    aspectShift: 0,
    fontScale: 1,
    lineHeight: '1.2',
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ReplicaCalibrationPanelComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(ReplicaCalibrationPanelComponent);
    component = fixture.componentInstance;
    component.form = { ...defaultForm };
    component.presetOptions = ['default', 'scotia', 'bbva'];
    component.selectedPreset = 'default';
    component.detectedBankLabel = 'BBVA';
  });

  it('should create', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('should display detected bank label', () => {
    fixture.detectChanges();
    const status = fixture.nativeElement.querySelector('.calibration-status');
    expect(status.textContent).toContain('BBVA');
  });

  it('should render preset options', () => {
    fixture.detectChanges();
    const options = fixture.nativeElement.querySelectorAll('option');
    expect(options.length).toBe(3);
  });

  it('should emit apply event', () => {
    fixture.detectChanges();
    spyOn(component.apply, 'emit');
    const applyBtn = Array.from(fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>)
      .find((b: HTMLButtonElement) => b.textContent?.includes('Aplicar'));
    applyBtn?.click();
    expect(component.apply.emit).toHaveBeenCalled();
  });

  it('should emit resetPreset event', () => {
    fixture.detectChanges();
    spyOn(component.resetPreset, 'emit');
    const btn = Array.from(fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>)
      .find((b: HTMLButtonElement) => b.textContent?.includes('Reset preset'));
    btn?.click();
    expect(component.resetPreset.emit).toHaveBeenCalled();
  });

  it('should emit resetAll event', () => {
    fixture.detectChanges();
    spyOn(component.resetAll, 'emit');
    const btn = Array.from(fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>)
      .find((b: HTMLButtonElement) => b.textContent?.includes('Reset total'));
    btn?.click();
    expect(component.resetAll.emit).toHaveBeenCalled();
  });

  it('should show status when provided', () => {
    component.status = 'Calibracion aplicada';
    fixture.detectChanges();
    const statuses = fixture.nativeElement.querySelectorAll('.calibration-status');
    const statusTexts = Array.from(statuses).map((s: any) => s.textContent);
    expect(statusTexts.some((t: string) => t.includes('Calibracion aplicada'))).toBeTrue();
  });
});
