import { TestBed } from '@angular/core/testing';
import { PaymentDetailComponent, PaymentDetailView } from './payment-detail.component';

describe('PaymentDetailComponent', () => {
  let fixture: ReturnType<typeof TestBed.createComponent<PaymentDetailComponent>>;
  let component: PaymentDetailComponent;

  const sampleDetail: PaymentDetailView = {
    bank: 'BBVA',
    metadataEntries: [
      { key: 'Fecha', value: '01/01/2025' },
      { key: 'Referencia', value: 'ABC123' },
    ],
    canonicalColumns: ['Cuenta', 'Monto'],
    canonicalRows: [['123456', '1,000.00']],
    summaryTables: [
      {
        title: 'Resumen',
        columns: ['Concepto', 'Total'],
        rows: [['Nomina', '50,000.00']],
      },
    ],
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PaymentDetailComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(PaymentDetailComponent);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    component.detail = sampleDetail;
    fixture.detectChanges();
    expect(component).toBeTruthy();
  });

  it('should display bank name', () => {
    component.detail = sampleDetail;
    fixture.detectChanges();
    const bankEl = fixture.nativeElement.querySelector('.payment-detail__bank');
    expect(bankEl.textContent).toContain('BBVA');
  });

  it('should render metadata entries', () => {
    component.detail = sampleDetail;
    fixture.detectChanges();
    const items = fixture.nativeElement.querySelectorAll('.payment-detail__meta-item');
    expect(items.length).toBe(2);
    expect(items[0].textContent).toContain('Fecha');
  });

  it('should render canonical table via app-cells-table', () => {
    component.detail = sampleDetail;
    fixture.detectChanges();
    const cellsTable = fixture.nativeElement.querySelector('app-cells-table');
    expect(cellsTable).toBeTruthy();
  });

  it('should render summary tables', () => {
    component.detail = sampleDetail;
    fixture.detectChanges();
    const summaryTitles = fixture.nativeElement.querySelectorAll('.payment-detail__summary-title');
    expect(summaryTitles.length).toBe(1);
    expect(summaryTitles[0].textContent).toContain('Resumen');
  });

  it('should build canonicalTableView from input', () => {
    component.detail = sampleDetail;
    const view = component.canonicalTableView;
    expect(view.headerRows).toEqual([['Cuenta', 'Monto']]);
    expect(view.bodyRows).toEqual([['123456', '1,000.00']]);
  });
});
