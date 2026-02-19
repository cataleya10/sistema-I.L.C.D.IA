export const DOCUMENT_FIELD_TEMPLATES: Record<string, Array<{ key: string; label: string }>> = {
  INE: [
    { key: 'nombre', label: 'Nombre completo' },
    { key: 'curp', label: 'CURP' },
    { key: 'clave_elector', label: 'Clave de elector' },
    { key: 'fecha_nacimiento', label: 'Fecha de nacimiento' },
    { key: 'sexo', label: 'Sexo' },
    { key: 'domicilio', label: 'Domicilio' },
    { key: 'seccion', label: 'Sección' },
    { key: 'vigencia', label: 'Vigencia' }
  ],
  CURP: [
    { key: 'nombre', label: 'Nombre completo' },
    { key: 'curp', label: 'CURP' },
    { key: 'fecha_nacimiento', label: 'Fecha de nacimiento' },
    { key: 'sexo', label: 'Sexo' },
    { key: 'entidad_nacimiento', label: 'Entidad de nacimiento' }
  ],
  ACTA_NACIMIENTO: [
    { key: 'nombre', label: 'Nombre completo' },
    { key: 'sexo', label: 'Sexo' },
    { key: 'fecha_nacimiento', label: 'Fecha de nacimiento' },
    { key: 'lugar_nacimiento', label: 'Lugar de nacimiento' },
    { key: 'folio', label: 'Folio' },
    { key: 'numero_acta', label: 'Número de acta' },
    { key: 'fecha_registro', label: 'Fecha de registro' },
    { key: 'municipio_registro', label: 'Municipio de registro' },
    { key: 'entidad_registro', label: 'Entidad de registro' }
  ],
  NSS: [
    { key: 'nombre', label: 'Nombre completo' },
    { key: 'nss', label: 'NSS' }
  ],
  COMPROBANTE_DOMICILIO: [
    { key: 'proveedor', label: 'Proveedor' },
    { key: 'numero_servicio', label: 'Número de servicio' },
    { key: 'cuenta', label: 'Cuenta' },
    { key: 'referencia', label: 'Referencia' },
    { key: 'titular', label: 'Titular' },
    { key: 'domicilio', label: 'Domicilio' },
    { key: 'cp', label: 'Código postal' },
    { key: 'fecha_limite', label: 'Fecha límite' },
    { key: 'total', label: 'Total' }
  ],
  DATOS_BANCARIOS: [
    { key: 'banco', label: 'Banco' },
    { key: 'clabe', label: 'CLABE' },
    { key: 'cuenta', label: 'Cuenta' },
    { key: 'titular', label: 'Titular' },
    { key: 'rfc', label: 'RFC' },
    { key: 'fecha_corte', label: 'Fecha de corte' },
    { key: 'periodo', label: 'Periodo' },
    { key: 'tabla_celdas', label: 'Tabla celdas' },
    { key: 'pago_detalle', label: 'Pago detalle (estructurado)' }
  ],
  FACTURA: [
    { key: 'tabla_celdas', label: 'Tabla celdas' },
    { key: 'pago_detalle', label: 'Pago detalle (estructurado)' },
    { key: 'replica_pdf_layout', label: 'Replica PDF (layout)' },
    { key: 'replica_pdf_texto', label: 'Replica PDF (texto completo)' }
  ],
  CONSTANCIA_SITUACION_FISCAL: [
    { key: 'rfc', label: 'RFC' },
    { key: 'nombre', label: 'Nombre completo' },
    { key: 'regimen', label: 'Régimen' },
    { key: 'domicilio', label: 'Domicilio' }
  ]
};
