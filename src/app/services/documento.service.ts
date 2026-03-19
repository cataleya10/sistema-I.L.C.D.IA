import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { map, switchMap, filter, take } from 'rxjs/operators';
import { timer } from 'rxjs';
import { ResultadoDocumento } from '../interfaces/documento-resultado.interface';

@Injectable({ providedIn: 'root' })
export class DocumentoService {

  private readonly baseUrl = 'http://localhost:5000/api/documents';

  constructor(private readonly http: HttpClient) {}

  procesarDocumento(archivo: File, tipoDocumento: string): Observable<ResultadoDocumento> {
    const formData = new FormData();
    formData.append('file', archivo);

    return this.http.post<any>(`${this.baseUrl}/upload`, formData).pipe(
      switchMap((uploaded) => {
        const options = tipoDocumento.toUpperCase() === 'FACTURA'
          ? { forceDocumentType: 'FACTURA' }
          : {};
        return this.http.post<any>(`${this.baseUrl}/${uploaded.id}/process`, options).pipe(
          switchMap((resp) => {
            if (resp.status === 'PROCESSING') {
              return timer(2000, 2000).pipe(
                switchMap(() => this.http.get<any>(`${this.baseUrl}/${resp.document_id}/process/status`)),
                filter((s) => s.status !== 'PROCESSING'),
                take(1),
                switchMap((s) => this.http.get<any>(`${this.baseUrl}/${s.document_id}`)),
                map((detail) => this.mapRespuesta(uploaded, resp, detail))
              );
            }
            return this.http.get<any>(`${this.baseUrl}/${resp.document_id}`).pipe(
              map((detail) => this.mapRespuesta(uploaded, resp, detail))
            );
          })
        );
      })
    );
  }

  private mapRespuesta(uploaded: any, resp: any, detail: any): ResultadoDocumento {
    const fields: any[] = detail?.fields ?? [];

    const getField = (key: string): any => {
      return fields.find((f: any) => f.key?.toLowerCase() === key.toLowerCase());
    };

    const parseStructuredField = (raw: any): any | null => {
      if (!raw) {
        return null;
      }
      if (typeof raw === 'object') {
        return raw;
      }
      if (typeof raw !== 'string') {
        return null;
      }
      try {
        return JSON.parse(raw);
      } catch {
        return null;
      }
    };

    const pagoDetalleField = getField('pago_detalle');
    const tablaCeldasField = getField('tabla_celdas');
    const pagoDetalle =
      parseStructuredField(pagoDetalleField?.corrected_value ?? pagoDetalleField?.value) ??
      parseStructuredField(tablaCeldasField?.corrected_value ?? tablaCeldasField?.value);

    let beneficiarios: any[] = [];
    let banco = '';
    let folio = '';
    let importeTotal = '';
    let cantidadMovimientos = '';

    if (pagoDetalle && typeof pagoDetalle === 'object') {
      banco = pagoDetalle?.bank ?? pagoDetalle?.mapped_fields?.banco ?? '';
      const metadata = pagoDetalle?.metadata ?? {};
      folio = metadata?.folio ?? metadata?.folio_operacion ?? metadata?.folio_unico ?? metadata?.folio_internet ?? '';
      importeTotal = metadata?.importe_total_movimientos ?? metadata?.importe_detectado ?? '';
      cantidadMovimientos = metadata?.cantidad_total_movimientos ?? metadata?.cantidad_movimientos_altas ?? '';

      const canonicalRows = pagoDetalle?.canonical_rows ?? pagoDetalle?.table?.canonical_rows ?? [];

      if (canonicalRows.length > 0) {
        beneficiarios = canonicalRows.map((row: any) => ({
          claveBeneficiario: row.clave_beneficiario ?? row.clavedebeneficiario ?? '',
          nombre: row.nombre ?? row.nombre_beneficiario ?? '',
          importe: row.importe ?? '',
          fechaAplicacion: row.fecha_aplicacion ?? row.fechaaplicacion ?? '',
          referencia: row.referencia ?? '',
          cuentaBeneficiario: row.cuenta ?? row.cuenta_beneficiario ?? '',
          bancoReceptor: row.banco_destino ?? row.banco_receptor ?? '',
          diasVigencia: row.dias_vigencia ?? row.diasvigencia ?? '',
          conceptoPago: row.concepto_pago ?? row.conceptopago ?? '',
        })).filter((b: any) => Object.values(b).some((v: any) => String(v).trim().length > 0));
      }

      if (beneficiarios.length === 0) {
        const rows = pagoDetalle?.table?.rows ?? pagoDetalle?.rows ?? [];
        if (rows.length > 1) {
          const header = rows[0];
          beneficiarios = rows.slice(1).map((row: any) => {
            const get = (keys: string[]) => {
              for (const k of keys) {
                const idx = header.findIndex((h: string) =>
                  h?.toLowerCase().includes(k.toLowerCase())
                );
                if (idx >= 0 && row[idx]) return String(row[idx]).trim();
              }
              return '';
            };
            return {
              claveBeneficiario: get(['clave']),
              nombre: get(['nombre']),
              importe: get(['importe']),
              fechaAplicacion: get(['fecha']),
              referencia: get(['referencia']),
              cuentaBeneficiario: get(['cuenta']),
              bancoReceptor: get(['banco']),
              diasVigencia: get(['dias', 'vigencia']),
              conceptoPago: get(['concepto']),
            };
          }).filter((b: any) => Object.values(b).some((v: any) => String(v).trim().length > 0));
        }
      }
    }

    return {
      tipoDocumento: resp.document_type ?? detail?.document_type ?? '',
      success: resp.status === 'READY' || resp.status === 'NEEDS_REVIEW',
      message: this.buildMessage(resp.status, resp.errors),
      resumen: {
        banco: banco || undefined,
        folio: folio || undefined,
        nombreArchivo: uploaded.original_filename,
        cantidadMovimientos: cantidadMovimientos || String(beneficiarios.length) || undefined,
        importeTotal: importeTotal || undefined,
      },
      beneficiarios,
    };
  }

  private buildMessage(status: string, errors: string[]): string {
    if (status === 'READY') return 'Documento procesado correctamente.';
    if (status === 'NEEDS_REVIEW') return 'Documento procesado, pero requiere revision.';
    if (status === 'FAILED') return errors?.[0] ?? 'El procesamiento falló.';
    return 'Procesando documento...';
  }
}
