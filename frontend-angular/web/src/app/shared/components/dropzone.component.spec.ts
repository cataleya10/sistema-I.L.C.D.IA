import { TestBed } from '@angular/core/testing';
import { DropzoneComponent } from './dropzone.component';

describe('DropzoneComponent', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<DropzoneComponent>>;
  let component: DropzoneComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DropzoneComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(DropzoneComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('should render default label', () => {
    fixture.detectChanges();
    const p = fixture.nativeElement.querySelector('p');
    expect(p.textContent).toContain('Arrastra y suelta tu documento aqui');
  });

  it('should render custom label', () => {
    component.label = 'Sube tu archivo';
    fixture.detectChanges();
    const p = fixture.nativeElement.querySelector('p');
    expect(p.textContent).toContain('Sube tu archivo');
  });

  it('should set isDragging on dragover', () => {
    fixture.detectChanges();
    expect(component.isDragging).toBeFalse();

    const event = new DragEvent('dragover', { cancelable: true });
    fixture.nativeElement.querySelector('.dropzone').dispatchEvent(event);

    expect(component.isDragging).toBeTrue();
  });

  it('should clear isDragging on dragleave', () => {
    component.isDragging = true;
    fixture.detectChanges();

    const event = new DragEvent('dragleave', { cancelable: true });
    fixture.nativeElement.querySelector('.dropzone').dispatchEvent(event);

    expect(component.isDragging).toBeFalse();
  });

  it('should add dragging class when isDragging', () => {
    component.isDragging = true;
    fixture.detectChanges();
    const zone = fixture.nativeElement.querySelector('.dropzone');
    expect(zone.classList.contains('dropzone--dragging')).toBeTrue();
  });

  it('should emit file on drop', () => {
    fixture.detectChanges();
    spyOn(component.fileDropped, 'emit');

    const file = new File(['data'], 'test.pdf', { type: 'application/pdf' });
    const dt = new DataTransfer();
    dt.items.add(file);
    const event = new DragEvent('drop', { cancelable: true, dataTransfer: dt });

    fixture.nativeElement.querySelector('.dropzone').dispatchEvent(event);

    expect(component.fileDropped.emit).toHaveBeenCalledWith(jasmine.any(File));
    expect(component.isDragging).toBeFalse();
  });

  it('should emit file on input change', () => {
    fixture.detectChanges();
    spyOn(component.fileDropped, 'emit');

    const file = new File(['data'], 'invoice.pdf', { type: 'application/pdf' });
    const dt = new DataTransfer();
    dt.items.add(file);

    const input = fixture.nativeElement.querySelector('input[type="file"]') as HTMLInputElement;
    input.files = dt.files;
    input.dispatchEvent(new Event('change'));

    expect(component.fileDropped.emit).toHaveBeenCalledWith(jasmine.any(File));
  });

  it('should open file picker when button is clicked', () => {
    fixture.detectChanges();
    const input = fixture.nativeElement.querySelector('input[type="file"]') as HTMLInputElement;
    spyOn(input, 'click');

    const button = fixture.nativeElement.querySelector('button');
    button.click();

    expect(input.click).toHaveBeenCalled();
  });

  it('should have correct accept attribute', () => {
    component.accept = '.pdf,.docx';
    fixture.detectChanges();
    const input = fixture.nativeElement.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input.accept).toBe('.pdf,.docx');
  });
});
