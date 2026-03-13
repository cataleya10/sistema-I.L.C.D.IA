import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, of, timer } from 'rxjs';
import { catchError, filter, map, switchMap, take, timeout } from 'rxjs/operators';
import { getApiBaseUrl } from '../core/config/runtime-config';
import { ResultadoDocumento } from '../features/documents/interfaces/documento-resultado.interface';
import { parsePaymentDetail } from '../features/documents/utils/payment-detail';
import { buildTableView, parseTableRows } from '../features/documents/utils/table-cells';
import { DocumentDetail, DocumentProcessResponse, DocumentSummary } from '../shared/models/document.models';

@Injectable({
  providedIn: 'root'
})
export class DocumentoService {
  private readonly apiUrl = `${getApiBaseUrl()}/api/documents`;

  constructor(private readonly http: HttpClient) {}

  procesarDocumento(archivo: File, tipoDocumento: string): Observable<ResultadoDocumento> {
    const formData = new FormData();
    formData.append('file', archivo);

    console.log('URL API USADA:', `${this.apiUrl}/upload`);

    return this.http.post<DocumentSummary>(`${this.apiUrl}/upload`, formData).pipe(
      switchMap((uploaded) => {
        console.log('URL API USADA:', `${this.apiUrl}/${uploaded.id}/process`);
        return this.http
          .post<DocumentProcessResponse>(`${this.apiUrl}/${uploaded.id}/process`, this.buildProcessOptions(tipoDocumento))
          .pipe(switchMap((response) => this.waitForResult(uploaded, response)));
      })
    );
  }

  private waitForResult(
    uploaded: DocumentSummary,
    response: DocumentProcessResponse
  ): Observable<ResultadoDocumento> {
    if (response.status !== 'PROCESSING') {
      return this.loadDocumentResult(uploaded, response);
    }

    return timer(2000, 2000).pipe(
      switchMap(() => this.http.get<DocumentProcessResponse>(`${this.apiUrl}/${uploaded.id}/process/status`)),
      filter((status) => status.status !== 'PROCESSING'),
      take(1),
      timeout({ first: 120000 }),
      switchMap((status) => this.loadDocumentResult(uploaded, status))
    );
  }

  private loadDocumentResult(
    uploaded: DocumentSummary,
    response: DocumentProcessResponse
  ): Observable<ResultadoDocumento> {
    if (!response.document_id) {
      return of(this.mapResult(uploaded, response, null));
    }

    return this.http.get<DocumentDetail>(`${this.apiUrl}/${response.document_id}`).pipe(
      map((detail) => this.mapResult(uploaded, response, detail)),
      catchError(() => of(this.mapResult(uploaded, response, null)))
    );
  }

  private buildProcessOptions(tipoDocumento: string): { forceDocumentType: 'FACTURA' } | {} {
    return tipoDocumento.toUpperCase() === 'FACTURA' ? { forceDocumentType: 'FACTURA' } : {};
  }

  private mapResult(
    uploaded: DocumentSummary,
    response: DocumentProcessResponse,
    detail: DocumentDetail | null
  ): ResultadoDocumento {
    const rawPagoDetalle = this.getFieldValue(detail, 'pago_detalle');
    const rawTablaCeldas = this.getTableCellsValue(detail);
    const paymentDetail = parsePaymentDetail(rawPagoDetalle) || parsePaymentDetail(rawTablaCeldas);
    const fallbackTable = rawTablaCeldas ? buildTableView(parseTableRows(rawTablaCeldas)) : null;

    return {
      tipoDocumento: response.document_type,
      success: response.status === 'READY' || response.status === 'NEEDS_REVIEW',
      message: this.buildMessage(response),
      documentId: response.document_id,
      resumen: this.buildResumen(uploaded, paymentDetail),
      beneficiarios: paymentDetail
        ? this.buildBeneficiarios(paymentDetail.canonicalColumns, paymentDetail.canonicalRows)
        : this.buildBeneficiarios(fallbackTable?.headerRows[0] ?? [], fallbackTable?.bodyRows ?? [])
    };
  }

  private buildMessage(response: DocumentProcessResponse): string {
    if (response.status === 'READY') {
      return 'Documento procesado correctamente.';
    }

    if (response.status === 'NEEDS_REVIEW') {
      return 'Documento procesado, pero requiere revision.';
    }

    if (response.status === 'FAILED') {
      return response.errors[0] ?? 'El procesamiento del documento fallo.';
    }

    return 'Documento enviado a procesamiento.';
  }

  private getFieldValue(detail: DocumentDetail | null, key: string): string {
    if (!detail?.fields?.length) {
      return '';
    }

    const field = detail.fields.find((item) => String(item.key ?? '').toLowerCase() === key.toLowerCase());
    return String(field?.corrected_value ?? field?.value ?? '').trim();
  }

  private getTableCellsValue(detail: DocumentDetail | null): string {
    if (!detail?.fields?.length) {
      return '';
    }

    const field = detail.fields.find((item) => String(item.key ?? '').toLowerCase().startsWith('tabla_celdas'));
    return String(field?.corrected_value ?? field?.value ?? '').trim();
  }

  private buildResumen(
    uploaded: DocumentSummary,
    paymentDetail: ReturnType<typeof parsePaymentDetail>
  ): ResultadoDocumento['resumen'] {
    if (!paymentDetail) {
      return {
        nombreArchivo: uploaded.original_filename
      };
    }

    const metadata = paymentDetail.metadataEntries.reduce<Record<string, string>>((acc, item) => {
      acc[this.normalizeKey(item.key)] = item.value;
      return acc;
    }, {});

    return {
      banco: paymentDetail.bank,
      folio:
        metadata['folio'] ??
        metadata['folio_firma'] ??
        metadata['folio_unico'] ??
        metadata['folio_operacion'] ??
        metadata['folio_internet'],
      nombreArchivo: uploaded.original_filename,
      cantidadMovimientos:
        metadata['cantidad_total_movimientos'] ??
        metadata['cantidad_movimientos'] ??
        String(paymentDetail.canonicalRows.length || ''),
      importeTotal:
        metadata['importe_total_movimientos'] ??
        metadata['importe_total'] ??
        metadata['importe_detectado']
    };
  }

  private buildBeneficiarios(
    columnas: string[],
    filas: string[][]
  ): NonNullable<ResultadoDocumento['beneficiarios']> {
    if (!columnas.length || !filas.length) {
      return [];
    }

    const indexMap = new Map<string, number>();
    columnas.forEach((columna, index) => {
      indexMap.set(this.normalizeKey(columna), index);
    });

    return filas
      .map((fila) => ({
        claveBeneficiario: this.getRowValue(fila, indexMap, [
          'clave_beneficiario',
          'clave_del_beneficiario',
          'clave',
        ]),
        nombre: this.getRowValue(fila, indexMap, [
          'nombre',
          'nombre_beneficiario',
          'nombre_del_beneficiario',
          'titular',
        ]),
        importe: this.getRowValue(fila, indexMap, [
          'importe',
          'importe_detectado',
          'total',
        ]),
        fechaAplicacion: this.getRowValue(fila, indexMap, [
          'fecha_aplicacion',
          'fecha_de_aplicacion',
          'fecha',
        ]),
        referencia: this.getRowValue(fila, indexMap, [
          'referencia',
        ]),
        cuentaBeneficiario: this.getRowValue(
          fila,
          indexMap,
          [
            'cuenta_beneficiario',
            'no_cuenta_beneficiario',
            'numero_cuenta_beneficiario',
            'cuenta',
            'cuenta_destino',
            'cuenta_deposito',
          ]
        ),
        bancoReceptor: this.getRowValue(fila, indexMap, [
          'banco_receptor',
          'no_banco_receptor',
          'numero_banco_receptor',
          'banco_destino',
          'banco',
        ]),
        diasVigencia: this.getRowValue(fila, indexMap, [
          'dias_vigencia',
          'dias_de_vigencia',
          'dias',
        ]),
        conceptoPago: this.getRowValue(fila, indexMap, [
          'concepto_pago',
          'concepto',
          'motivo_pago',
        ]),
      }))
      .filter((beneficiario) => {
        const tieneDatos = Object.values(beneficiario).some(
          (valor) => String(valor ?? '').trim().length > 0
        );

        if (!tieneDatos) {
          return false;
        }

        const clave = String(beneficiario.claveBeneficiario ?? '').trim().toUpperCase();
        const nombre = String(beneficiario.nombre ?? '').trim().toUpperCase();
        const importe = String(beneficiario.importe ?? '').trim().toUpperCase();
        const concepto = String(beneficiario.conceptoPago ?? '').trim().toUpperCase();

        if (clave.startsWith('CANTIDAD') || clave.startsWith('TOTAL')) {
          return false;
        }

        if (nombre.startsWith('CANTIDAD') || nombre.startsWith('TOTAL')) {
          return false;
        }

        if (
          importe === '0' &&
          !concepto &&
          !clave &&
          !nombre
        ) {
          return false;
        }

        return true;
      });
  }

  private getRowValue(fila: string[], indexMap: Map<string, number>, claves: string[]): string {
    for (const clave of claves) {
      const index = indexMap.get(clave);
      if (index !== undefined) {
        return String(fila[index] ?? '').trim();
      }
    }

    return '';
  }

  private normalizeKey(valor: string): string {
    return String(valor ?? '')
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '');
  }
}
