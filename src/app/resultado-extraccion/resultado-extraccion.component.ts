import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ResultadoDocumento } from '../interfaces/documento-resultado.interface';

interface TablaExtraida {
  encabezados: string[];
  filas: string[][];
  banco: string;
  totalFilas: number;
}

@Component({
  selector: 'app-resultado-extraccion',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './resultado-extraccion.component.html',
  styleUrls: ['./resultado-extraccion.component.css'],
})
export class ResultadoExtraccionComponent {

  tablas: TablaExtraida[] = [];
  tablaActiva = 0;
  resumenItems: { label: string; value: string }[] = [];
  private _resultado: ResultadoDocumento | null = null;

  @Input() set resultado(value: ResultadoDocumento | null) {
    this._resultado = value;
    this.tablas = [];
    this.resumenItems = [];
    this.tablaActiva = 0;
    if (value) this._procesar(value);
  }

  get resultado(): ResultadoDocumento | null {
    return this._resultado;
  }

  seleccionarTab(idx: number): void {
    this.tablaActiva = idx;
  }

  private _procesar(r: ResultadoDocumento): void {
    // ── Resumen ──────────────────────────────────────
    const res = r.resumen;
    if (res) {
      if (res.banco)               this.resumenItems.push({ label: 'Banco',         value: res.banco });
      if (res.folio)               this.resumenItems.push({ label: 'Folio',         value: res.folio });
      if (res.nombreArchivo)       this.resumenItems.push({ label: 'Archivo',       value: res.nombreArchivo });
      if (res.cantidadMovimientos) this.resumenItems.push({ label: 'Movimientos',   value: res.cantidadMovimientos });
      if (res.importeTotal)        this.resumenItems.push({ label: 'Importe total', value: res.importeTotal });
    }

    // ── Tabla de beneficiarios ───────────────────────
    const beneficiarios = r.beneficiarios;
    if (!beneficiarios?.length) return;

    const encabezados = [
      'Clave', 'Nombre', 'Importe', 'Fecha',
      'Referencia', 'Cuenta', 'Banco',
      'Dias', 'Concepto',
    ];

    const filas = beneficiarios.map(b => [
      b.claveBeneficiario   || '—',
      b.nombre              || '—',
      b.importe             || '—',
      b.fechaAplicacion     || '—',
      b.referencia          || '—',
      b.cuentaBeneficiario  || '—',
      b.bancoReceptor       || '—',
      b.diasVigencia        || '—',
      b.conceptoPago        || '—',
    ]);

    this.tablas.push({
      encabezados,
      filas,
      banco: res?.banco || '',
      totalFilas: filas.length,
    });
  }
}