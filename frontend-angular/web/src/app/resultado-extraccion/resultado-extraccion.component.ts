import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-resultado-extraccion',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './resultado-extraccion.component.html',
  styleUrls: ['./resultado-extraccion.component.css']
})
export class ResultadoExtraccionComponent {
  @Input() resultado: any;

  esJsonTabla(valor: string): boolean {
    if (!valor || typeof valor !== 'string') return false;

    try {
      const parsed = JSON.parse(valor);
      return !!parsed && (
        Array.isArray(parsed.rows) ||
        Array.isArray(parsed.canonical_rows) ||
        Array.isArray(parsed.columns)
      );
    } catch {
      return false;
    }
  }

  obtenerTabla(valor: string): any | null {
    if (!valor || typeof valor !== 'string') return null;

    try {
      return JSON.parse(valor);
    } catch {
      return null;
    }
  }

  obtenerHeaders(valor: string): string[] {
    const tabla = this.obtenerTabla(valor);
    if (!tabla) return [];

    if (Array.isArray(tabla.columns) && tabla.columns.length > 0) {
      return tabla.columns;
    }

    if (Array.isArray(tabla.rows) && tabla.rows.length > 0 && Array.isArray(tabla.rows[0])) {
      return tabla.rows[0];
    }

    if (Array.isArray(tabla.canonical_columns) && tabla.canonical_columns.length > 0) {
      return tabla.canonical_columns;
    }

    if (Array.isArray(tabla.canonical_rows) && tabla.canonical_rows.length > 0) {
      return Object.keys(tabla.canonical_rows[0]);
    }

    return [];
  }

  obtenerRows(valor: string): any[] {
    const tabla = this.obtenerTabla(valor);
    if (!tabla) return [];

    if (Array.isArray(tabla.rows) && tabla.rows.length > 1 && Array.isArray(tabla.rows[0])) {
      return tabla.rows.slice(1);
    }

    if (Array.isArray(tabla.canonical_rows) && tabla.canonical_rows.length > 0) {
      return tabla.canonical_rows;
    }

    return [];
  }

  esFilaObjeto(fila: any): boolean {
    return fila && typeof fila === 'object' && !Array.isArray(fila);
  }
}
