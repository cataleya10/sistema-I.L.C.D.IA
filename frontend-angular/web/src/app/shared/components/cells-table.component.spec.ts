import { TestBed } from '@angular/core/testing';
import { CellsTableComponent, CellsTableViewModel } from './cells-table.component';

describe('CellsTableComponent', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<CellsTableComponent>>;
  let component: CellsTableComponent;

  const sampleTable: CellsTableViewModel = {
    headerRows: [['Nombre', 'Monto', 'Estado']],
    bodyRows: [
      ['Juan', '1,000.00', 'OK'],
      ['Ana', '2,500.50', 'Revisar'],
    ],
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CellsTableComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(CellsTableComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    component.tableView = sampleTable;
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('should render header row', () => {
    component.tableView = sampleTable;
    fixture.detectChanges();
    const ths = fixture.nativeElement.querySelectorAll('th');
    expect(ths.length).toBe(3);
    expect(ths[0].textContent.trim()).toBe('Nombre');
  });

  it('should render body rows', () => {
    component.tableView = sampleTable;
    fixture.detectChanges();
    const trs = fixture.nativeElement.querySelectorAll('tbody tr');
    expect(trs.length).toBe(2);
  });

  it('should alternate row classes', () => {
    component.tableView = sampleTable;
    fixture.detectChanges();
    const rows = fixture.nativeElement.querySelectorAll('tbody tr');
    expect(rows[0].classList.contains('alt')).toBeFalse();
    expect(rows[1].classList.contains('alt')).toBeTrue();
  });

  it('should hide when no body rows', () => {
    component.tableView = { headerRows: [['A']], bodyRows: [] };
    fixture.detectChanges();
    const wrap = fixture.nativeElement.querySelector('.cells-table-wrap');
    expect(wrap).toBeNull();
  });

  it('should apply report-mode class', () => {
    component.tableView = sampleTable;
    component.reportMode = true;
    fixture.detectChanges();
    const table = fixture.nativeElement.querySelector('table');
    expect(table.classList.contains('report-mode')).toBeTrue();
  });
});
