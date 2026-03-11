export interface FacturaResumen {
  banco: string;
  folio: string;
  nombreArchivo: string;
  cantidadMovimientos: string;
  importeTotal: string;
}

export interface FacturaBeneficiario {
  claveBeneficiario: string;
  nombre: string;
  importe: string;
  fechaAplicacion: string;
  referencia: string;
  cuentaBeneficiario: string;
  bancoReceptor: string;
  diasVigencia: string;
  conceptoPago: string;
}

export interface ResultadoDocumento {
  tipoDocumento: string;
  success: boolean;
  message: string;
  resumen: FacturaResumen;
  beneficiarios: FacturaBeneficiario[];
}
