"""Extraction constants: regex patterns, label maps, configuration."""

import re
from typing import Any


def _export_all():
    import sys
    mod = sys.modules[__name__]
    return [n for n in dir(mod) if not n.startswith('__')]


_PAYMENT_TABLE_HEADER_TOKENS = (
    "CUENTA",
    "REFERENCIA",
    "IMPORTE",
    "NOMBRE",
    "APELLIDO",
    "ESTATUS",
    "CONCEPTO",
    "BENEFICIARIO",
    "CLAVE RASTREO",
    "EMPLEADO",
    "DESCRIPCION",
)

_PAYMENT_TABLE_STATUS_TOKENS = (
    "PROCESADO",
    "APLICADO",
    "ACEPTADO",
    "TRANSMITIDO",
)

_PAYMENT_TABLE_TEXT_LABELS = (
    "cuenta",
    "referencia",
    "importe",
    "nombre",
    "estatus",
    "concepto",
)

_GENERIC_TABLE_MAX_TABLES = 30
_GENERIC_TABLE_MAX_ROWS = 300
_GENERIC_TABLE_MAX_COLS = 30
_GENERIC_TABLE_MAX_CELL_TEXT = 400
_GENERIC_TABLE_BLOCK_GAP_Y = 36
_GENERIC_TABLE_LARGE_GAP_X = 34
_GENERIC_TABLE_JOIN_GAP_X = 16


_ALLOWED_FIELDS_BY_TYPE: dict[str, set[str]] = {
    "INE": {
        "nombre",
        "curp",
        "clave_elector",
        "fecha_nacimiento",
        "sexo",
        "domicilio",
        "seccion",
        "vigencia",
    },
    "CURP": {
        "nombre",
        "curp",
        "fecha_nacimiento",
        "sexo",
        "entidad_nacimiento",
    },
    "ACTA_NACIMIENTO": {
        "nombre",
        "sexo",
        "fecha_nacimiento",
        "lugar_nacimiento",
        "folio",
        "numero_acta",
        "fecha_registro",
        "municipio_registro",
        "entidad_registro",
        "numero_certificado",
        "identificador_electronico",
    },
    "NSS": {
        "nss",
        "nombre",
        "nombre_beneficiario",
        "nombre_asegurado",
        "nombre_titular",
    },
    "COMPROBANTE_DOMICILIO": {
        "proveedor",
        "numero_servicio",
        "cuenta",
        "referencia",
        "titular",
        "domicilio",
        "cp",
        "fecha_limite",
        "total",
        "contrato",
        "tabla_celdas",
        "pago_detalle",
    },
    "DATOS_BANCARIOS": {
        "banco",
        "clabe",
        "cuenta",
        "cliente_numero",
        "titular",
        "nombre_titular",
        "nombre_beneficiario",
        "rfc",
        "fecha_corte",
        "periodo",
        "tabla_celdas",
        "pago_detalle",
    },
    "FACTURA": {
        "tabla_celdas",
        "pago_detalle",
        "replica_pdf_layout",
        "replica_pdf_texto",
    },
    "CONSTANCIA_SITUACION_FISCAL": {
        "rfc",
        "nombre",
        "regimen",
        "domicilio",
    },
    "CFDI": {
        "uuid", "folio", "serie", "fecha", "tipo_comprobante",
        "rfc_emisor", "nombre_emisor", "regimen_fiscal_emisor",
        "rfc_receptor", "nombre_receptor", "uso_cfdi", "cp_receptor",
        "subtotal", "descuento", "total", "moneda",
        "forma_pago", "metodo_pago",
        "total_iva", "total_retenciones",
        "conceptos",
        "no_certificado", "fecha_timbrado", "lugar_expedicion",
        # Campos del complemento Nómina (TipoDeComprobante = N)
        "nombre", "curp", "nss", "periodo", "fecha_pago",
        "total_percepciones", "total_deducciones", "total_otros_pagos",
        "tipo_nomina", "num_dias_pagados", "tipo_contrato", "tipo_regimen",
        "num_empleado", "departamento", "puesto", "banco", "cuenta_bancaria",
        "salario_base", "salario_diario", "periodicidad_pago",
        "percepciones_detalle", "deducciones_detalle",
    },
}


__all__ = _export_all()
