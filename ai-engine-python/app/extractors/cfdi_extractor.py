"""
CFDI Extractor — Comprobante Fiscal Digital por Internet (SAT México)

Soporta dos modos de extracción:

  1. XML directo (máxima precisión)
     - Parseo con xml.etree.ElementTree
     - CFDI versión 3.3 y 4.0
     - Complementos: tfd:TimbreFiscalDigital, nomina12:Nomina

  2. PDF/OCR (fallback cuando solo hay imagen o PDF escaneado)
     - Patrones regex sobre texto OCR
     - Extrae los campos más importantes cuando el XML no está disponible

Campos que extrae:
  Identificación:
    uuid, folio, serie, fecha, tipo_comprobante

  Emisor:
    rfc_emisor, nombre_emisor, regimen_fiscal_emisor

  Receptor:
    rfc_receptor, nombre_receptor, uso_cfdi, cp_receptor

  Totales:
    subtotal, descuento, total, moneda

  Pago:
    forma_pago, metodo_pago

  Impuestos:
    total_iva, total_retenciones

  Conceptos (tabla):
    conceptos

  Timbrado:
    no_certificado, fecha_timbrado, lugar_expedicion

Detección de tipo:
  - Ingreso (I), Egreso (E), Traslado (T), Pago (P)
  - Nómina (N) → delega a los campos del complemento nomina12
"""

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any

logger = logging.getLogger(__name__)

# Campos que este extractor puede devolver
EXPECTED_FIELDS = frozenset({
    "uuid", "folio", "serie", "fecha", "tipo_comprobante",
    "rfc_emisor", "nombre_emisor", "regimen_fiscal_emisor",
    "rfc_receptor", "nombre_receptor", "uso_cfdi", "cp_receptor",
    "subtotal", "descuento", "total", "moneda",
    "forma_pago", "metodo_pago",
    "total_iva", "total_retenciones",
    "conceptos",
    "no_certificado", "fecha_timbrado", "lugar_expedicion",
})

DOCUMENT_TYPE = "CFDI"

# ─── Namespaces CFDI (SAT) ────────────────────────────────────────────────────

_NS = {
    "cfdi":     "http://www.sat.gob.mx/cfd/4",
    "cfdi33":   "http://www.sat.gob.mx/cfd/3",
    "tfd":      "http://www.sat.gob.mx/TimbreFiscalDigital",
    "nomina12": "http://www.sat.gob.mx/nomina12",
}

# Registrar todos los namespaces para que ET no genere prefijos genéricos
for _prefix, _uri in _NS.items():
    try:
        ET.register_namespace(_prefix, _uri)
    except Exception:
        pass


# ─── Códigos de tipo de comprobante ──────────────────────────────────────────

_TIPO_COMPROBANTE_MAP = {
    "I": "Ingreso",
    "E": "Egreso",
    "T": "Traslado",
    "N": "Nómina",
    "P": "Pago",
}

# ─── Formas de pago SAT (catálogo c_FormaPago) ───────────────────────────────

_FORMA_PAGO_MAP = {
    "01": "Efectivo",
    "02": "Cheque nominativo",
    "03": "Transferencia electrónica de fondos",
    "04": "Tarjeta de crédito",
    "05": "Monedero electrónico",
    "06": "Dinero electrónico",
    "08": "Vales de despensa",
    "12": "Dación en pago",
    "13": "Pago por subrogación",
    "14": "Pago por consignación",
    "15": "Condonación",
    "17": "Compensación",
    "23": "Novación",
    "24": "Confusión",
    "25": "Remisión de deuda",
    "26": "Prescripción o caducidad",
    "27": "A satisfacción del acreedor",
    "28": "Tarjeta de débito",
    "29": "Tarjeta de servicios",
    "30": "Aplicación de anticipos",
    "31": "Intermediario pagos",
    "99": "Por definir",
}

# ─── Patrones OCR (fallback para PDFs sin capa XML) ──────────────────────────

_OCR_PATTERNS: dict[str, list[re.Pattern]] = {
    "uuid": [
        re.compile(
            r"(?:UUID|FOLIO\s*FISCAL|TIMBRE\s*FISCAL)[:\s]*"
            r"([0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12})",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b([0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12})\b",
            re.IGNORECASE,
        ),
    ],
    "folio": [
        re.compile(r"FOLIO[:\s]+([A-Z0-9\-]{1,20})\b", re.IGNORECASE),
    ],
    "serie": [
        re.compile(r"SERIE[:\s]+([A-Z]{1,5})\b", re.IGNORECASE),
    ],
    "fecha": [
        re.compile(r"FECHA\s*(?:DE\s*)?EMISI[OÓ]N[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.IGNORECASE),
        re.compile(r"FECHA[:\s]+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", re.IGNORECASE),
    ],
    "rfc_emisor": [
        re.compile(r"RFC\s*(?:DEL\s*)?EMISOR[:\s]+([A-Z&]{3,4}\d{6}[A-Z0-9]{3,4})\b", re.IGNORECASE),
    ],
    "nombre_emisor": [
        re.compile(
            r"(?:EMISOR|EMPRESA|RAZ[OÓ]N\s*SOCIAL)[:\s]+([A-ZÁÉÍÓÚÜÑ&][A-ZÁÉÍÓÚÜÑ\s,\.&\-]{4,80}?)"
            r"(?:\n|\s{2,}|RFC|$)",
            re.IGNORECASE,
        ),
    ],
    "rfc_receptor": [
        re.compile(r"RFC\s*(?:DEL\s*)?RECEPTOR[:\s]+([A-Z&]{3,4}\d{6}[A-Z0-9]{3,4})\b", re.IGNORECASE),
    ],
    "nombre_receptor": [
        re.compile(
            r"RECEPTOR[:\s]+([A-ZÁÉÍÓÚÜÑ&][A-ZÁÉÍÓÚÜÑ\s,\.&\-]{4,80}?)"
            r"(?:\n|\s{2,}|RFC|$)",
            re.IGNORECASE,
        ),
    ],
    "total": [
        re.compile(r"TOTAL[:\s\$]+([\d,]+\.?\d{0,2})\b", re.IGNORECASE),
        re.compile(r"IMPORTE\s*TOTAL[:\s\$]+([\d,]+\.?\d{0,2})\b", re.IGNORECASE),
    ],
    "subtotal": [
        re.compile(r"SUBTOTAL[:\s\$]+([\d,]+\.?\d{0,2})\b", re.IGNORECASE),
    ],
    "fecha_timbrado": [
        re.compile(r"FECHA\s*(?:DE\s*)?TIMBRADO[:\s]+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", re.IGNORECASE),
    ],
    "no_certificado": [
        re.compile(r"(?:N[ÚU]M(?:ERO)?\.?\s*DE?\s*)?CERTIFICADO[:\s]+(\d{20})\b", re.IGNORECASE),
    ],
}


# ─── Extractor principal ─────────────────────────────────────────────────────

async def extract(
    ocr_text: str,
    ocr_boxes: list[dict[str, Any]] | None = None,
    raw_text: str = "",
    filename: str | None = None,
    pdf_tables: list[list[list[str]]] | None = None,
    xml_content: bytes | str | None = None,
) -> list[dict[str, Any]]:
    """
    Extrae campos de un CFDI (factura electrónica SAT México).

    Prioridad de fuentes:
      1. xml_content  → parseo XML directo (máxima precisión)
      2. raw_text     → si contiene <?xml, intenta parseo XML
      3. ocr_text     → extracción por patrones regex (fallback)

    Args:
        ocr_text:    Texto OCR del documento.
        ocr_boxes:   Bounding boxes OCR.
        raw_text:    Texto nativo del PDF o contenido XML.
        filename:    Nombre del archivo.
        pdf_tables:  Tablas extraídas por pdfplumber.
        xml_content: Contenido XML explícito (bytes o str).

    Returns:
        Lista de campos extraídos.
    """
    fields: list[dict[str, Any]] = []

    # ── 1. Intentar extracción XML ────────────────────────────────────────────
    xml_src = xml_content or (raw_text if _looks_like_xml(raw_text) else None)
    if xml_src:
        try:
            fields = _extract_from_xml(xml_src)
            if fields:
                logger.info("cfdi [%s]: extracción XML exitosa, %d campos", filename or "?", len(fields))
                _log_coverage(fields, filename)
                return fields
        except Exception:
            logger.warning("cfdi [%s]: fallo en parseo XML, usando OCR fallback", filename or "?", exc_info=True)

    # ── 2. Fallback OCR ───────────────────────────────────────────────────────
    combined = f"{ocr_text or ''}\n{raw_text or ''}".strip()
    if combined:
        fields = _extract_from_ocr(combined, ocr_boxes or [])
        logger.info("cfdi [%s]: extracción OCR, %d campos", filename or "?", len(fields))

    _log_coverage(fields, filename)
    return fields


# ─── Extracción desde XML ─────────────────────────────────────────────────────

def _looks_like_xml(text: str) -> bool:
    """True si el texto parece ser un documento XML."""
    stripped = (text or "").lstrip()
    return stripped.startswith("<?xml") or stripped.startswith("<cfdi:")


def _parse_xml_tree(xml_src: bytes | str) -> ET.Element | None:
    """Parsea el XML y retorna el elemento raíz. Intenta con y sin declaración."""
    if isinstance(xml_src, str):
        xml_bytes = xml_src.encode("utf-8")
    else:
        xml_bytes = xml_src
    try:
        return ET.fromstring(xml_bytes)
    except ET.ParseError:
        # Intenta eliminar BOM o caracteres inválidos al inicio
        xml_bytes = xml_bytes.lstrip(b"\xef\xbb\xbf").lstrip()
        try:
            return ET.fromstring(xml_bytes)
        except ET.ParseError:
            return None


def _find_element(root: ET.Element, *local_names: str) -> ET.Element | None:
    """Busca un elemento por su nombre local (sin namespace) en todo el árbol."""
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag in local_names:
            return elem
    return None


def _find_all_elements(root: ET.Element, *local_names: str) -> list[ET.Element]:
    """Busca todos los elementos con cualquiera de los nombres locales dados."""
    result = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag in local_names:
            result.append(elem)
    return result


def _attr(element: ET.Element | None, *names: str) -> str:
    """Obtiene el primer atributo encontrado de una lista de nombres posibles."""
    if element is None:
        return ""
    for name in names:
        val = element.get(name)
        if val:
            return val.strip()
    return ""


def _make_field(key: str, label: str, value: str, confidence: float = 0.97) -> dict[str, Any]:
    """Construye un campo en el formato estándar del sistema."""
    return {
        "key": key,
        "label": label,
        "value": value,
        "confidence": confidence,
        "valid": True,
        "source": "xml",
    }


def _extract_from_xml(xml_src: bytes | str) -> list[dict[str, Any]]:
    """Extrae todos los campos del XML CFDI. Soporta v3.3 y v4.0."""
    root = _parse_xml_tree(xml_src)
    if root is None:
        raise ValueError("No se pudo parsear el XML CFDI")

    # El elemento raíz puede ser <cfdi:Comprobante> directamente
    comprobante = root
    root_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if root_tag != "Comprobante":
        comprobante = _find_element(root, "Comprobante") or root

    fields: list[dict[str, Any]] = []

    def add(key: str, label: str, value: str, conf: float = 0.97) -> None:
        if value:
            fields.append(_make_field(key, label, value.strip(), conf))

    # ── Atributos del Comprobante ─────────────────────────────────────────────
    add("fecha",             "Fecha emisión",       _attr(comprobante, "Fecha"))
    add("folio",             "Folio",               _attr(comprobante, "Folio"))
    add("serie",             "Serie",               _attr(comprobante, "Serie"))
    add("subtotal",          "Subtotal",            _attr(comprobante, "SubTotal"))
    add("descuento",         "Descuento",           _attr(comprobante, "Descuento"))
    add("total",             "Total",               _attr(comprobante, "Total"))
    add("moneda",            "Moneda",              _attr(comprobante, "Moneda"))
    add("forma_pago",        "Forma de pago",       _attr(comprobante, "FormaPago"))
    add("metodo_pago",       "Método de pago",      _attr(comprobante, "MetodoPago"))
    add("lugar_expedicion",  "Lugar de expedición", _attr(comprobante, "LugarExpedicion"))
    add("no_certificado",    "No. de certificado",  _attr(comprobante, "NoCertificado"))

    tipo_raw = _attr(comprobante, "TipoDeComprobante")
    if tipo_raw:
        tipo_desc = _TIPO_COMPROBANTE_MAP.get(tipo_raw.upper(), tipo_raw)
        add("tipo_comprobante", "Tipo de comprobante", f"{tipo_raw} - {tipo_desc}")

    # Forma de pago: enriquecer con descripción
    fp_raw = _attr(comprobante, "FormaPago")
    if fp_raw:
        fp_desc = _FORMA_PAGO_MAP.get(fp_raw, fp_raw)
        # Actualiza el campo ya agregado
        for f in fields:
            if f["key"] == "forma_pago":
                f["value"] = f"{fp_raw} - {fp_desc}"
                break

    # ── Emisor ────────────────────────────────────────────────────────────────
    emisor = _find_element(comprobante, "Emisor")
    add("rfc_emisor",            "RFC emisor",          _attr(emisor, "Rfc"))
    add("nombre_emisor",         "Nombre emisor",       _attr(emisor, "Nombre"))
    add("regimen_fiscal_emisor", "Régimen fiscal",      _attr(emisor, "RegimenFiscal"))

    # ── Receptor ──────────────────────────────────────────────────────────────
    receptor = _find_element(comprobante, "Receptor")
    add("rfc_receptor",    "RFC receptor",     _attr(receptor, "Rfc"))
    add("nombre_receptor", "Nombre receptor",  _attr(receptor, "Nombre"))
    add("uso_cfdi",        "Uso CFDI",         _attr(receptor, "UsoCFDI"))
    # CFDI 4.0 agrega DomicilioFiscalReceptor
    add("cp_receptor",     "CP receptor",      _attr(receptor, "DomicilioFiscalReceptor"))

    # ── Impuestos ─────────────────────────────────────────────────────────────
    impuestos = _find_element(comprobante, "Impuestos")
    if impuestos is not None:
        add("total_iva",          "Total IVA traslados", _attr(impuestos, "TotalImpuestosTrasladados"))
        add("total_retenciones",  "Total retenciones",   _attr(impuestos, "TotalImpuestosRetenidos"))

    # ── Timbre Fiscal Digital (UUID) ──────────────────────────────────────────
    tfd = _find_element(comprobante, "TimbreFiscalDigital")
    add("uuid",           "UUID (Folio Fiscal)", _attr(tfd, "UUID"))
    add("fecha_timbrado", "Fecha timbrado",      _attr(tfd, "FechaTimbrado"))

    # ── Conceptos (tabla de líneas de factura) ────────────────────────────────
    conceptos_table = _extract_conceptos(comprobante)
    if conceptos_table:
        import json
        fields.append(_make_field(
            "conceptos",
            "Conceptos",
            json.dumps(conceptos_table, ensure_ascii=False),
            confidence=0.97,
        ))

    # ── Complemento Nómina (tipo N) ──────────────────────────────────────────
    if tipo_raw and tipo_raw.upper() == "N":
        _extract_nomina_complement(comprobante, fields)

    return fields


def _extract_conceptos(comprobante: ET.Element) -> dict | None:
    """Extrae la tabla de conceptos/líneas del comprobante."""
    conceptos_el = _find_element(comprobante, "Conceptos")
    if conceptos_el is None:
        return None

    concepto_items = _find_all_elements(conceptos_el, "Concepto")
    if not concepto_items:
        return None

    rows = []
    columns = ["ClaveProdServ", "Cantidad", "ClaveUnidad", "Descripcion", "ValorUnitario", "Importe", "Descuento"]

    for concepto in concepto_items:
        row = {
            "clave_prod_serv":  _attr(concepto, "ClaveProdServ"),
            "cantidad":         _attr(concepto, "Cantidad"),
            "clave_unidad":     _attr(concepto, "ClaveUnidad"),
            "unidad":           _attr(concepto, "Unidad"),
            "descripcion":      _attr(concepto, "Descripcion"),
            "valor_unitario":   _attr(concepto, "ValorUnitario"),
            "importe":          _attr(concepto, "Importe"),
            "descuento":        _attr(concepto, "Descuento"),
        }
        # Eliminar campos vacíos
        row = {k: v for k, v in row.items() if v}
        if row:
            rows.append(row)

    if not rows:
        return None

    return {
        "columns": list(rows[0].keys()) if rows else [],
        "rows": rows,
        "row_count": len(rows),
    }


def _extract_nomina_complement(comprobante: ET.Element, fields: list[dict[str, Any]]) -> None:
    """
    Extrae campos del complemento nomina12:Nomina.
    Modifica la lista fields in-place.
    """
    import json

    nomina = _find_element(comprobante, "Nomina")
    if nomina is None:
        return

    def add(key: str, label: str, value: str, conf: float = 0.97) -> None:
        if value:
            fields.append(_make_field(key, label, value.strip(), conf))

    add("tipo_nomina",  "Tipo nómina",       _attr(nomina, "TipoNomina"))
    add("fecha_pago",   "Fecha de pago",     _attr(nomina, "FechaPago"))
    add("periodo",      "Periodo",
        _build_periodo(_attr(nomina, "FechaInicialPago"), _attr(nomina, "FechaFinalPago")))
    add("num_dias_pagados", "Días pagados",  _attr(nomina, "NumDiasPagados"))
    add("total_percepciones", "Total percepciones", _attr(nomina, "TotalPercepciones"))
    add("total_deducciones",  "Total deducciones",  _attr(nomina, "TotalDeducciones"))
    add("total_otros_pagos",  "Total otros pagos",  _attr(nomina, "TotalOtrosPagos"))

    # Receptor de nómina (datos del empleado)
    receptor_nom = _find_element(nomina, "Receptor")
    if receptor_nom is not None:
        add("curp",           "CURP empleado",    _attr(receptor_nom, "Curp"))
        add("nss",            "NSS empleado",     _attr(receptor_nom, "NumSeguridadSocial"))
        add("nombre",         "Nombre empleado",  _attr(receptor_nom, "Nombre"))
        add("tipo_contrato",  "Tipo contrato",    _attr(receptor_nom, "TipoContrato"))
        add("tipo_regimen",   "Tipo régimen",     _attr(receptor_nom, "TipoRegimen"))
        add("num_empleado",   "No. empleado",     _attr(receptor_nom, "NumEmpleado"))
        add("departamento",   "Departamento",     _attr(receptor_nom, "Departamento"))
        add("puesto",         "Puesto",           _attr(receptor_nom, "Puesto"))
        add("riesgo_puesto",  "Riesgo puesto",    _attr(receptor_nom, "RiesgoPuesto"))
        add("periodicidad_pago", "Periodicidad",  _attr(receptor_nom, "PeriodicidadPago"))
        add("banco",          "Banco",            _attr(receptor_nom, "Banco"))
        add("cuenta_bancaria","Cuenta bancaria",  _attr(receptor_nom, "CuentaBancaria"))
        add("salario_base",   "Salario base",     _attr(receptor_nom, "SalarioBaseCotApor"))
        add("salario_diario", "Salario diario",   _attr(receptor_nom, "SalarioDiarioIntegrado"))

    # Percepciones → tabla
    percepciones_el = _find_element(nomina, "Percepciones")
    if percepciones_el is not None:
        percepciones = _extract_nomina_percepciones(percepciones_el)
        if percepciones:
            fields.append(_make_field(
                "percepciones_detalle",
                "Percepciones detalle",
                json.dumps(percepciones, ensure_ascii=False),
                confidence=0.97,
            ))

    # Deducciones → tabla
    deducciones_el = _find_element(nomina, "Deducciones")
    if deducciones_el is not None:
        deducciones = _extract_nomina_deducciones(deducciones_el)
        if deducciones:
            fields.append(_make_field(
                "deducciones_detalle",
                "Deducciones detalle",
                json.dumps(deducciones, ensure_ascii=False),
                confidence=0.97,
            ))


def _extract_nomina_percepciones(percepciones_el: ET.Element) -> dict | None:
    items = _find_all_elements(percepciones_el, "Percepcion")
    rows = []
    for item in items:
        row = {
            "tipo":          _attr(item, "TipoPercepcion"),
            "clave":         _attr(item, "Clave"),
            "concepto":      _attr(item, "Concepto"),
            "importe_gravado": _attr(item, "ImporteGravado"),
            "importe_exento":  _attr(item, "ImporteExento"),
        }
        row = {k: v for k, v in row.items() if v}
        if row:
            rows.append(row)
    if not rows:
        return None
    return {"rows": rows, "row_count": len(rows)}


def _extract_nomina_deducciones(deducciones_el: ET.Element) -> dict | None:
    items = _find_all_elements(deducciones_el, "Deduccion")
    rows = []
    for item in items:
        row = {
            "tipo":    _attr(item, "TipoDeduccion"),
            "clave":   _attr(item, "Clave"),
            "concepto": _attr(item, "Concepto"),
            "importe": _attr(item, "Importe"),
        }
        row = {k: v for k, v in row.items() if v}
        if row:
            rows.append(row)
    if not rows:
        return None
    return {"rows": rows, "row_count": len(rows)}


def _build_periodo(fecha_inicio: str, fecha_fin: str) -> str:
    if fecha_inicio and fecha_fin:
        return f"{fecha_inicio} al {fecha_fin}"
    return fecha_inicio or fecha_fin


# ─── Extracción desde OCR (fallback) ─────────────────────────────────────────

def _extract_from_ocr(text: str, ocr_boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extrae campos CFDI desde texto OCR usando patrones regex."""
    from app.pipelines.extract.common import _make_field as _make_field_with_boxes

    fields: list[dict[str, Any]] = []
    existing_keys: set[str] = set()

    _LABEL_MAP = {
        "uuid":           "UUID (Folio Fiscal)",
        "folio":          "Folio",
        "serie":          "Serie",
        "fecha":          "Fecha emisión",
        "rfc_emisor":     "RFC emisor",
        "nombre_emisor":  "Nombre emisor",
        "rfc_receptor":   "RFC receptor",
        "nombre_receptor":"Nombre receptor",
        "total":          "Total",
        "subtotal":       "Subtotal",
        "fecha_timbrado": "Fecha timbrado",
        "no_certificado": "No. certificado",
    }

    for key, patterns in _OCR_PATTERNS.items():
        if key in existing_keys:
            continue
        for pat in patterns:
            m = pat.search(text)
            if m:
                val = m.group(1).strip()
                if val:
                    label = _LABEL_MAP.get(key, key)
                    fields.append(_make_field_with_boxes(key, label, val, ocr_boxes, confidence=0.75))
                    existing_keys.add(key)
                    break

    return fields


# ─── Utilidades ───────────────────────────────────────────────────────────────

def _log_coverage(fields: list[dict[str, Any]], filename: str | None) -> None:
    found = {f.get("key") for f in fields if f.get("value")}
    # Campos mínimos que determinan si el CFDI fue bien extraído
    core = {"uuid", "rfc_emisor", "rfc_receptor", "total", "fecha"}
    missing_core = core - found
    pct = int(100 * len(found & EXPECTED_FIELDS) / len(EXPECTED_FIELDS))
    if missing_core:
        logger.info(
            "cfdi [%s] cobertura %d%% — campos core faltantes: %s",
            filename or "?", pct, ", ".join(sorted(missing_core)),
        )
    else:
        logger.info("cfdi [%s] cobertura %d%% — campos core completos", filename or "?", pct)


def get_expected_fields() -> frozenset[str]:
    """Devuelve el conjunto de campos que este extractor puede producir."""
    return EXPECTED_FIELDS
