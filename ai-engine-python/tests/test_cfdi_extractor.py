"""Tests for app.extractors.cfdi_extractor — XML and OCR extraction paths."""

import pytest
from app.extractors.cfdi_extractor import extract, _extract_from_ocr


# ── OCR Extraction ──────────────────────────────────────────────────────

class CfdiOcrExtractionTests:
    def test_uuid_extraction(self):
        text = "UUID: A1B2C3D4-E5F6-7890-ABCD-EF1234567890"
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}
        assert fm["uuid"] == "A1B2C3D4-E5F6-7890-ABCD-EF1234567890"

    def test_folio_fiscal_alias(self):
        text = "FOLIO FISCAL: A1B2C3D4-E5F6-7890-ABCD-EF1234567890"
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}
        assert fm["uuid"] == "A1B2C3D4-E5F6-7890-ABCD-EF1234567890"

    def test_rfc_emisor(self):
        text = "RFC DEL EMISOR: ABC123456XYZ"
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}
        assert fm["rfc_emisor"] == "ABC123456XYZ"

    def test_rfc_receptor_from_cliente(self):
        text = "CLIENTE  RFC: XAXX010101000\nA FAVOR DE  RFC: PEGJ800101ABC"
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}
        # Should pick at least one receptor RFC
        assert "rfc_receptor" in fm or "rfc_emisor" in fm

    def test_total_with_currency_symbol_space(self):
        text = "TOTAL: $ 1,234,567.89"
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}
        assert "total" in fm
        assert "1,234,567.89" in fm["total"]

    def test_total_a_pagar(self):
        text = "TOTAL A PAGAR: $15,000.00"
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}
        assert "total" in fm
        assert "15,000.00" in fm["total"]

    def test_subtotal_extraction(self):
        text = "SUBTOTAL: $12,931.03\nIVA: $2,068.97\nTOTAL: $15,000.00"
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}
        assert "subtotal" in fm
        assert "total" in fm

    def test_forma_pago(self):
        text = "FORMA DE PAGO: 03 - Transferencia electrónica"
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}
        assert "forma_pago" in fm
        assert "03" in fm["forma_pago"]

    def test_metodo_pago(self):
        text = "MÉTODO DE PAGO: PUE\nOTRA LINEA"
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}
        assert "metodo_pago" in fm
        assert "PUE" in fm["metodo_pago"]

    def test_uso_cfdi(self):
        text = "USO DE CFDI: G03 - Gastos en general"
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}
        assert "uso_cfdi" in fm
        assert "G03" in fm["uso_cfdi"]

    def test_moneda(self):
        text = "MONEDA: MXN"
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}
        assert fm.get("moneda") == "MXN"

    def test_descuento(self):
        text = "DESCUENTO: $500.00"
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}
        assert "descuento" in fm
        assert "500.00" in fm["descuento"]

    def test_clave_rastreo(self):
        text = "CLAVE DE RASTREO: 2026040900001BBVA1234"
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}
        assert "clave_rastreo" in fm

    def test_beneficiario(self):
        text = "BENEFICIARIO: JUAN CARLOS GARCIA LOPEZ\nCUENTA: 1234567890"
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}
        assert "beneficiario" in fm
        assert "JUAN CARLOS" in fm["beneficiario"]

    def test_lugar_expedicion(self):
        text = "LUGAR DE EXPEDICIÓN: 06600"
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}
        assert fm.get("lugar_expedicion") == "06600"

    def test_fecha_with_different_formats(self):
        text = "FECHA: 2026-04-09T10:30:00"
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}
        assert "fecha" in fm
        assert "2026-04-09T10:30:00" in fm["fecha"]

    def test_fecha_emision_dd_mm_yyyy(self):
        text = "FECHA DE EMISIÓN: 09/04/2026"
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}
        assert "fecha" in fm
        assert "09/04/2026" in fm["fecha"]

    def test_iva_extraction(self):
        text = "IVA: $2,068.97"
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}
        assert "total_iva" in fm


# ── XML Extraction ──────────────────────────────────────────────────────

class CfdiXmlExtractionTests:
    @pytest.mark.asyncio
    async def test_cfdi_40_xml(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
        <cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
            xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
            Fecha="2026-04-01T12:00:00" Folio="1234" Serie="A"
            SubTotal="10000.00" Total="11600.00" Moneda="MXN"
            FormaPago="03" MetodoPago="PUE" TipoDeComprobante="I"
            LugarExpedicion="06600" NoCertificado="30001000000400002434">
            <cfdi:Emisor Rfc="ABC123456XYZ" Nombre="EMPRESA SA DE CV" RegimenFiscal="601"/>
            <cfdi:Receptor Rfc="PEGJ800101ABC" Nombre="JUAN PEREZ" UsoCFDI="G03"/>
            <cfdi:Conceptos>
                <cfdi:Concepto ClaveProdServ="84111506" Cantidad="1" ClaveUnidad="E48"
                    Descripcion="Servicios de consultoria" ValorUnitario="10000.00" Importe="10000.00"/>
            </cfdi:Conceptos>
            <cfdi:Impuestos TotalImpuestosTrasladados="1600.00"/>
            <cfdi:Complemento>
                <tfd:TimbreFiscalDigital UUID="A1B2C3D4-E5F6-7890-ABCD-EF1234567890"
                    FechaTimbrado="2026-04-01T12:05:00"/>
            </cfdi:Complemento>
        </cfdi:Comprobante>"""
        fields = await extract(ocr_text="", xml_content=xml)
        fm = {f["key"]: f["value"] for f in fields}

        assert fm["uuid"] == "A1B2C3D4-E5F6-7890-ABCD-EF1234567890"
        assert fm["rfc_emisor"] == "ABC123456XYZ"
        assert fm["nombre_emisor"] == "EMPRESA SA DE CV"
        assert fm["rfc_receptor"] == "PEGJ800101ABC"
        assert fm["total"] == "11600.00"
        assert fm["subtotal"] == "10000.00"
        assert fm["moneda"] == "MXN"
        assert "03" in fm["forma_pago"]
        assert fm["uso_cfdi"] == "G03"
        assert fm["total_iva"] == "1600.00"
        assert "conceptos" in fm
        assert fm["lugar_expedicion"] == "06600"

    @pytest.mark.asyncio
    async def test_xml_in_raw_text_autodetect(self):
        xml = """<?xml version="1.0" encoding="utf-8"?>
        <cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4"
            Fecha="2026-03-15T09:00:00" Total="5000.00" Moneda="MXN" TipoDeComprobante="I">
            <cfdi:Emisor Rfc="XYZ987654ABC" Nombre="TIENDA SA"/>
            <cfdi:Receptor Rfc="GOMJ900101DEF" Nombre="JOSE GOMEZ"/>
        </cfdi:Comprobante>"""
        fields = await extract(ocr_text="", raw_text=xml)
        fm = {f["key"]: f["value"] for f in fields}

        assert fm["rfc_emisor"] == "XYZ987654ABC"
        assert fm["total"] == "5000.00"


# ── Payment dispersal OCR ───────────────────────────────────────────────

class PaymentDispersalOcrTests:
    def test_spei_dispersal_fields(self):
        text = (
            "COMPROBANTE DE LA OPERACION\n"
            "CLAVE DE RASTREO: 2026040900001BBVA1234\n"
            "BENEFICIARIO: CARLOS MARTINEZ LOPEZ\n"
            "TOTAL: $25,000.00\n"
            "RFC ORDENANTE: ABC123456XYZ\n"
            "FECHA DE EMISIÓN: 09/04/2026\n"
        )
        fields = _extract_from_ocr(text, [])
        fm = {f["key"]: f["value"] for f in fields}

        assert "clave_rastreo" in fm
        assert "beneficiario" in fm
        assert "CARLOS" in fm["beneficiario"]
        assert "total" in fm
        assert "fecha" in fm


# ── Full async extraction ───────────────────────────────────────────────

class CfdiFullExtractionTests:
    @pytest.mark.asyncio
    async def test_ocr_fallback_full(self):
        text = (
            "FACTURA\n"
            "UUID: DEADBEEF-1234-5678-9ABC-DEF012345678\n"
            "FOLIO: F-1234\n"
            "SERIE: A\n"
            "FECHA DE EMISIÓN: 01/04/2026\n"
            "RFC EMISOR: ABC123456XYZ\n"
            "SUBTOTAL: $10,000.00\n"
            "IVA: $1,600.00\n"
            "TOTAL: $11,600.00\n"
            "FORMA DE PAGO: 03 - Transferencia\n"
            "MÉTODO DE PAGO: PUE\n"
            "MONEDA: MXN\n"
        )
        fields = await extract(ocr_text=text)
        fm = {f["key"]: f["value"] for f in fields}

        assert "uuid" in fm
        assert "rfc_emisor" in fm
        assert "total" in fm
        assert "subtotal" in fm
        assert "forma_pago" in fm
        assert "metodo_pago" in fm
        assert "moneda" in fm
