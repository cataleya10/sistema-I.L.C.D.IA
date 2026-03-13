export interface ResultadoDocumento {
  tipoDocumento: string;
  success: boolean;
  message: string;
  documentId?: string;

  resumen?: {
    banco?: string;
    folio?: string;
    nombreArchivo?: string;
    cantidadMovimientos?: string;
    importeTotal?: string;
  };

  beneficiarios?: Array<{
    claveBeneficiario?: string;
    nombre?: string;
    importe?: string;
    fechaAplicacion?: string;
    referencia?: string;
    cuentaBeneficiario?: string;
    bancoReceptor?: string;
    diasVigencia?: string;
    conceptoPago?: string;
  }>;
}
