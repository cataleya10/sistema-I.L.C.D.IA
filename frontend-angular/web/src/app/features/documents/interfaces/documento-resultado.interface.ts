export interface ResultadoDocumento {
  exito: boolean;
  mensaje: string;
  tipo: string;
  nombreArchivo: string;
  estado?: string;
  documentId?: string;
}
