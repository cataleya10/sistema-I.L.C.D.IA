import { TestBed } from '@angular/core/testing';
import { ConfidenceIndicatorComponent } from './confidence-indicator.component';

describe('ConfidenceIndicatorComponent', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<ConfidenceIndicatorComponent>>;
  let component: ConfidenceIndicatorComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ConfidenceIndicatorComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(ConfidenceIndicatorComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('should compute percentage from value', () => {
    component.value = 0.85;
    expect(component.percentage).toBe(85);
  });

  it('should round percentage to nearest integer', () => {
    component.value = 0.876;
    expect(component.percentage).toBe(88);
  });

  it('should show 0% for value 0', () => {
    component.value = 0;
    expect(component.percentage).toBe(0);
  });

  it('should show 100% for value 1', () => {
    component.value = 1;
    expect(component.percentage).toBe(100);
  });

  it('should render percentage text', () => {
    component.value = 0.72;
    fixture.detectChanges();
    const span = fixture.nativeElement.querySelector('span');
    expect(span.textContent.trim()).toBe('72%');
  });

  it('should set bar width based on percentage', () => {
    component.value = 0.6;
    fixture.detectChanges();
    const bar = fixture.nativeElement.querySelector('.confidence__bar') as HTMLElement;
    expect(bar.style.width).toBe('60%');
  });
});
