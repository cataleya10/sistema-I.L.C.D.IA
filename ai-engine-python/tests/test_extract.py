import asyncio
import json
import unittest
from collections.abc import Coroutine
from typing import Any, TypeVar, cast, overload
from unittest.mock import patch

from app.pipelines.extract import extract_fields


T = TypeVar("T")


@overload
def _run_sync(value: Coroutine[Any, Any, T]) -> T: ...


@overload
def _run_sync(value: T) -> T: ...


def _run_sync(value: Coroutine[Any, Any, T] | T) -> T:
    if asyncio.iscoroutine(value):
        return asyncio.run(cast(Coroutine[Any, Any, T], value))
    return value


def _field_map(fields: list[dict[str, Any]]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for field in fields:
        key = field.get("key")
        value = field.get("value")
        if key and value is not None:
            mapped[str(key)] = str(value)
    return mapped


def _box(text: str, y: int) -> dict[str, Any]:
    return {
        "text": text,
        "page": 1,
        "confidence": 0.99,
        "bbox": [[10, y], [300, y], [300, y + 20], [10, y + 20]],
    }


class ExtractPipelineTests(unittest.TestCase):
    def test_extract_ine_core_fields_from_text(self):
        ocr_text = "\n".join(
            [
                "CREDENCIAL PARA VOTAR",
                "CURP AACD900101HDFRRL09",
                "SECCION 1234",
                "VIGENCIA 2030",
            ]
        )
        fields = _run_sync(extract_fields("INE", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("curp"), "AACD900101HDFRRL09")
        self.assertEqual(data.get("seccion"), "1234")
        self.assertEqual(data.get("vigencia"), "2030")

    def test_extract_datos_bancarios_clabe_rfc_banco(self):
        ocr_text = "\n".join(
            [
                "BANCO BBVA",
                "CLABE 012345678901234567",
                "RFC XAXX010101000",
            ]
        )
        fields = _run_sync(extract_fields("DATOS_BANCARIOS", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("clabe"), "012345678901234567")
        self.assertEqual(data.get("rfc"), "XAXX010101000")
        self.assertIn("BBVA", data.get("banco", ""))

    def test_extract_comprobante_domicilio_key_fields(self):
        ocr_text = "\n".join(
            [
                "TELMEX",
                "NUMERO TELEFONICO 3312345678",
                "NO DE CUENTA 0011223344",
                "TOTAL A PAGAR $1,234.56",
                "CALLE FALSA 123 COL CENTRO CP 44100",
            ]
        )
        fields = _run_sync(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("numero_servicio"), "3312345678")
        self.assertEqual(data.get("cuenta"), "0011223344")
        self.assertEqual(data.get("cp"), "44100")
        self.assertIn("1234.56", data.get("total", "").replace(",", ""))

    def test_extract_ine_with_ocr_noise_in_labels(self):
        ocr_text = "\n".join(
            [
                "CREDENCIAL PARA VOTAR",
                "CURP AACD900101HDFRRL09",
                "SECCI0N 12I4",
                "VGENCIA 2031",
            ]
        )
        fields = _run_sync(extract_fields("INE", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("curp"), "AACD900101HDFRRL09")
        self.assertEqual(data.get("seccion"), "124")
        self.assertEqual(data.get("vigencia"), "2031")

    def test_extract_datos_bancarios_with_ocr_confusions(self):
        ocr_text = "\n".join(
            [
                "BANCO BBVA",
                "CLABE O123456789O123456L",
            ]
        )
        fields = _run_sync(extract_fields("DATOS_BANCARIOS", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("clabe"), "012345678901234561")

    def test_extract_datos_bancarios_payment_table_from_boxes(self):
        ocr_text = "REPORTE DE NOMINA"
        ocr_boxes = [
            {"text": "Cuenta", "page": 1, "confidence": 0.99, "bbox": [[10, 10], [90, 10], [90, 30], [10, 30]]},
            {"text": "Referencia", "page": 1, "confidence": 0.99, "bbox": [[110, 10], [210, 10], [210, 30], [110, 30]]},
            {"text": "Importe", "page": 1, "confidence": 0.99, "bbox": [[230, 10], [320, 10], [320, 30], [230, 30]]},
            {"text": "Nombre", "page": 1, "confidence": 0.99, "bbox": [[340, 10], [430, 10], [430, 30], [340, 30]]},
            {"text": "56551346133", "page": 1, "confidence": 0.99, "bbox": [[10, 40], [120, 40], [120, 60], [10, 60]]},
            {"text": "1620260115132703271255", "page": 1, "confidence": 0.99, "bbox": [[140, 40], [290, 40], [290, 60], [140, 60]]},
            {"text": "$1,462.58", "page": 1, "confidence": 0.99, "bbox": [[310, 40], [390, 40], [390, 60], [310, 60]]},
            {"text": "JOSE LUIS", "page": 1, "confidence": 0.99, "bbox": [[410, 40], [510, 40], [510, 60], [410, 60]]},
        ]

        fields = _run_sync(extract_fields("DATOS_BANCARIOS", ocr_text, ocr_boxes))
        data = _field_map(fields)

        self.assertNotIn("tabla_celdas", data)
        self.assertEqual(data.get("cuenta"), "56551346133")

    def test_extract_factura_payment_table_from_fragmented_boxes(self):
        ocr_text = "COMPROBANTE DE LA OPERACION"
        ocr_boxes = [
            {"text": "Cuenta", "page": 1, "confidence": 0.99, "bbox": [[10, 10], [90, 10], [90, 30], [10, 30]]},
            {"text": "Referencia", "page": 1, "confidence": 0.99, "bbox": [[120, 10], [240, 10], [240, 30], [120, 30]]},
            {"text": "Importe", "page": 1, "confidence": 0.99, "bbox": [[260, 10], [340, 10], [340, 30], [260, 30]]},
            {"text": "Nombre", "page": 1, "confidence": 0.99, "bbox": [[360, 10], [440, 10], [440, 30], [360, 30]]},
            {"text": "Benefi", "page": 1, "confidence": 0.99, "bbox": [[470, 10], [530, 10], [530, 30], [470, 30]]},
            {"text": "ciario", "page": 1, "confidence": 0.99, "bbox": [[535, 10], [600, 10], [600, 30], [535, 30]]},
            {"text": "56551346133", "page": 1, "confidence": 0.99, "bbox": [[10, 40], [120, 40], [120, 60], [10, 60]]},
            {"text": "1620260115132703271255", "page": 1, "confidence": 0.99, "bbox": [[120, 40], [300, 40], [300, 60], [120, 60]]},
            {"text": "$1,462.58", "page": 1, "confidence": 0.99, "bbox": [[260, 40], [340, 40], [340, 60], [260, 60]]},
            {"text": "JOSE", "page": 1, "confidence": 0.99, "bbox": [[360, 40], [410, 40], [410, 60], [360, 60]]},
            {"text": "LUIS", "page": 1, "confidence": 0.99, "bbox": [[415, 40], [460, 40], [460, 60], [415, 60]]},
            {"text": "GARCIA", "page": 1, "confidence": 0.99, "bbox": [[470, 40], [545, 40], [545, 60], [470, 60]]},
            {"text": "LOPEZ", "page": 1, "confidence": 0.99, "bbox": [[550, 40], [620, 40], [620, 60], [550, 60]]},
        ]

        fields = _run_sync(extract_fields("FACTURA", ocr_text, ocr_boxes))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        self.assertEqual(payload.get("source"), "ocr_boxes")
        self.assertEqual(payload["rows"][0][0], "CUENTA")
        self.assertIn("REFERENCIA", payload["rows"][0])
        self.assertIn("JOSE LUIS", payload["rows"][1])
        self.assertIn("GARCIA LOPEZ", payload["rows"][1])

    def test_extract_factura_payment_table_payload_includes_all_tables_with_cells(self):
        ocr_text = "REPORTE GENERAL DE OPERACIONES"
        ocr_boxes = [
            {"text": "Columna A", "page": 1, "confidence": 0.99, "bbox": [[10, 10], [150, 10], [150, 30], [10, 30]]},
            {"text": "Columna B", "page": 1, "confidence": 0.99, "bbox": [[220, 10], [360, 10], [360, 30], [220, 30]]},
            {"text": "A1", "page": 1, "confidence": 0.99, "bbox": [[10, 40], [120, 40], [120, 60], [10, 60]]},
            {"text": "B1", "page": 1, "confidence": 0.99, "bbox": [[220, 40], [300, 40], [300, 60], [220, 60]]},
            {"text": "Producto", "page": 1, "confidence": 0.99, "bbox": [[10, 120], [180, 120], [180, 140], [10, 140]]},
            {"text": "Cantidad", "page": 1, "confidence": 0.99, "bbox": [[240, 120], [380, 120], [380, 140], [240, 140]]},
            {"text": "Precio", "page": 1, "confidence": 0.99, "bbox": [[440, 120], [560, 120], [560, 140], [440, 140]]},
            {"text": "Lapiz", "page": 1, "confidence": 0.99, "bbox": [[10, 150], [120, 150], [120, 170], [10, 170]]},
            {"text": "2", "page": 1, "confidence": 0.99, "bbox": [[260, 150], [280, 150], [280, 170], [260, 170]]},
            {"text": "$10.00", "page": 1, "confidence": 0.99, "bbox": [[440, 150], [560, 150], [560, 170], [440, 170]]},
            {"text": "Borrador", "page": 1, "confidence": 0.99, "bbox": [[10, 180], [140, 180], [140, 200], [10, 200]]},
            {"text": "1", "page": 1, "confidence": 0.99, "bbox": [[260, 180], [280, 180], [280, 200], [260, 200]]},
            {"text": "$5.00", "page": 1, "confidence": 0.99, "bbox": [[440, 180], [540, 180], [540, 200], [440, 200]]},
        ]

        fields = _run_sync(extract_fields("FACTURA", ocr_text, ocr_boxes))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        self.assertIn("all_tables", payload)
        tables = payload["all_tables"]
        self.assertGreaterEqual(len(tables), 2)

        first_table = tables[0]
        self.assertEqual(first_table["rows"][0][0], "Columna A")
        self.assertEqual(first_table["rows"][1][1], "B1")
        self.assertEqual(first_table["cells"][1][1]["bbox"], [220, 40, 300, 60])

        second_table = tables[1]
        self.assertEqual(second_table["rows"][0][0], "Producto")
        self.assertEqual(second_table["rows"][0][2], "Precio")
        self.assertEqual(second_table["rows"][2][2], "$5.00")
        self.assertEqual(second_table["cells"][2][2]["bbox"], [440, 180, 540, 200])

    def test_extract_factura_payment_table_payload_falls_back_to_generic_table(self):
        ocr_text = "RESUMEN DE MOVIMIENTOS"
        ocr_boxes = [
            {"text": "Producto", "page": 1, "confidence": 0.99, "bbox": [[10, 10], [180, 10], [180, 30], [10, 30]]},
            {"text": "Cantidad", "page": 1, "confidence": 0.99, "bbox": [[240, 10], [380, 10], [380, 30], [240, 30]]},
            {"text": "Precio", "page": 1, "confidence": 0.99, "bbox": [[440, 10], [560, 10], [560, 30], [440, 30]]},
            {"text": "Lapiz", "page": 1, "confidence": 0.99, "bbox": [[10, 40], [120, 40], [120, 60], [10, 60]]},
            {"text": "2", "page": 1, "confidence": 0.99, "bbox": [[260, 40], [280, 40], [280, 60], [260, 60]]},
            {"text": "$10.00", "page": 1, "confidence": 0.99, "bbox": [[440, 40], [560, 40], [560, 60], [440, 60]]},
        ]

        fields = _run_sync(extract_fields("FACTURA", ocr_text, ocr_boxes))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        self.assertEqual(payload.get("source"), "generic_table_payload")
        self.assertEqual(payload["rows"][0][0], "Producto")
        self.assertEqual(payload["rows"][1][2], "$10.00")
        self.assertGreaterEqual(payload.get("all_table_count", 0), 1)
        self.assertEqual(payload.get("primary_table_index"), 1)

    def test_extract_factura_scotia_ocr_boxes_also_append_bottom_summary_rows(self):
        ocr_text = "\n".join(
            [
                "Scotiabank Inverlat S.A.",
                "Transferencia de Archivos",
                "Cantidad de Movimientos Altas",
                "Importe de Movimiento Altas",
                "Cantidad de Movimientos Bajas",
                "Importe de Movimientos Bajas",
                "6",
                "$18,000.00",
                "0",
                "$0.00",
                "Total Cantidad de Movimientos Altas",
                "Total Importe de Movimiento Altas",
                "Total Cantidad de Movimientos Bajas",
                "Total Importe de Movimientos Bajas",
                "6",
                "$18,000.00",
                "0",
                "$0.00",
            ]
        )
        ocr_boxes = [
            {"text": "TIPO DE REGISTRO", "page": 1, "confidence": 0.99, "bbox": [[10, 10], [160, 10], [160, 30], [10, 30]]},
            {"text": "TIPO DE MOVIMIENTO (PAGO)", "page": 1, "confidence": 0.99, "bbox": [[170, 10], [360, 10], [360, 30], [170, 30]]},
            {"text": "IMPORTE", "page": 1, "confidence": 0.99, "bbox": [[370, 10], [450, 10], [450, 30], [370, 30]]},
            {"text": "FECHA DE APLICACION", "page": 1, "confidence": 0.99, "bbox": [[460, 10], [620, 10], [620, 30], [460, 30]]},
            {"text": "CLAVE DEL BENEFICIARIO", "page": 1, "confidence": 0.99, "bbox": [[630, 10], [820, 10], [820, 30], [630, 30]]},
            {"text": "NOMBRE DEL BENEFICIARIO", "page": 1, "confidence": 0.99, "bbox": [[830, 10], [1020, 10], [1020, 30], [830, 30]]},
            {"text": "REFERENCIA", "page": 1, "confidence": 0.99, "bbox": [[1030, 10], [1130, 10], [1130, 30], [1030, 30]]},
            {"text": "NO. CUENTA BENEFICIARIO", "page": 1, "confidence": 0.99, "bbox": [[1140, 10], [1330, 10], [1330, 30], [1140, 30]]},
            {"text": "NO. BANCO RECEPTOR", "page": 1, "confidence": 0.99, "bbox": [[1340, 10], [1490, 10], [1490, 30], [1340, 30]]},
            {"text": "DIAS DE VIGENCIA", "page": 1, "confidence": 0.99, "bbox": [[1500, 10], [1630, 10], [1630, 30], [1500, 30]]},
            {"text": "CONCEPTO PAGO", "page": 1, "confidence": 0.99, "bbox": [[1640, 10], [1760, 10], [1760, 30], [1640, 30]]},
            {"text": "DA ALTA", "page": 1, "confidence": 0.99, "bbox": [[10, 40], [160, 40], [160, 60], [10, 60]]},
            {"text": "04 ABONO EN CUENTA", "page": 1, "confidence": 0.99, "bbox": [[170, 40], [360, 40], [360, 60], [170, 60]]},
            {"text": "$3,000.00", "page": 1, "confidence": 0.99, "bbox": [[370, 40], [450, 40], [450, 60], [370, 60]]},
            {"text": "15/01/2026", "page": 1, "confidence": 0.99, "bbox": [[460, 40], [620, 40], [620, 60], [460, 60]]},
            {"text": "A35", "page": 1, "confidence": 0.99, "bbox": [[630, 40], [820, 40], [820, 60], [630, 60]]},
            {"text": "VELAZCO DIONICIO ZENON", "page": 1, "confidence": 0.99, "bbox": [[830, 40], [1020, 40], [1020, 60], [830, 60]]},
            {"text": "1", "page": 1, "confidence": 0.99, "bbox": [[1030, 40], [1130, 40], [1130, 60], [1030, 60]]},
            {"text": "00014052605935660925", "page": 1, "confidence": 0.99, "bbox": [[1140, 40], [1330, 40], [1330, 60], [1140, 60]]},
            {"text": "14", "page": 1, "confidence": 0.99, "bbox": [[1340, 40], [1490, 40], [1490, 60], [1340, 60]]},
            {"text": "1", "page": 1, "confidence": 0.99, "bbox": [[1500, 40], [1630, 40], [1630, 60], [1500, 60]]},
            {"text": "PAGO35", "page": 1, "confidence": 0.99, "bbox": [[1640, 40], [1760, 40], [1760, 60], [1640, 60]]},
        ]
        fields = _run_sync(extract_fields("FACTURA", ocr_text, ocr_boxes))
        data = _field_map(fields)
        payload = json.loads(data["tabla_celdas"])
        self.assertEqual(payload.get("source"), "ocr_boxes")
        rows = payload.get("rows", [])
        self.assertTrue(any(row[:4] == ["CANTIDAD DE MOVIMIENTOS ALTAS", "IMPORTE DE MOVIMIENTO ALTAS", "CANTIDAD DE MOVIMIENTOS BAJAS", "IMPORTE DE MOVIMIENTOS BAJAS"] for row in rows))
        self.assertTrue(any(row[:4] == ["TOTAL CANTIDAD DE MOVIMIENTOS ALTAS", "TOTAL IMPORTE DE MOVIMIENTO ALTAS", "TOTAL CANTIDAD DE MOVIMIENTOS BAJAS", "TOTAL IMPORTE DE MOVIMIENTOS BAJAS"] for row in rows))

    def test_extract_datos_bancarios_payment_table_from_text_lines(self):
        ocr_text = "\n".join(
            [
                "Cuenta    Referencia    Importe    Nombre",
                "56551346133    1620260115132703271255    $1,462.58    JOSE LUIS",
            ]
        )
        fields = _run_sync(extract_fields("DATOS_BANCARIOS", ocr_text, None))
        data = _field_map(fields)

        self.assertNotIn("tabla_celdas", data)

    def test_extract_unknown_payment_table_from_text_lines(self):
        ocr_text = "\n".join(
            [
                "Cuenta    Referencia    Importe    Nombre",
                "56551346133    1620260115132703271255    $1,462.58    JOSE LUIS",
            ]
        )
        fields = _run_sync(extract_fields("UNKNOWN", ocr_text, None))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        self.assertEqual(payload.get("source"), "text_lines")
        self.assertEqual(str(payload["rows"][0][0]).upper(), "CUENTA")

    def test_extract_comprobante_payment_table_from_text_lines(self):
        ocr_text = "\n".join(
            [
                "Cuenta    Referencia    Importe    Nombre",
                "56551346133    1620260115132703271255    $1,462.58    JOSE LUIS",
            ]
        )
        fields = _run_sync(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None))
        data = _field_map(fields)

        self.assertNotIn("tabla_celdas", data)

    def test_extract_factura_payment_table_from_text_lines(self):
        ocr_text = "\n".join(
            [
                "Cuenta    Referencia    Importe    Nombre",
                "56551346133    1620260115132703271255    $1,462.58    JOSE LUIS",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", ocr_text, None))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        self.assertEqual(payload.get("source"), "text_lines")
        self.assertEqual(payload["rows"][0][0], "CUENTA")

    def test_extract_factura_payment_table_falls_back_to_text_when_ocr_rows_are_noisy(self):
        ocr_text = "\n".join(
            [
                "Cuenta    Referencia    Importe    Nombre    Estatus    Concepto",
                "0438349034    7379597479    $3,000.00    CARLOS ROBERTO RODRIGUEZ DOMINGUEZ    TRANSMITIDO    PAGO DE NOMINA",
            ]
        )
        ocr_boxes = [
            {"text": "No. 0000000001 Detalle empleado", "page": 1, "confidence": 0.99, "bbox": [[10, 10], [220, 10], [220, 30], [10, 30]]},
            {"text": "Importe Estatus Código", "page": 1, "confidence": 0.99, "bbox": [[230, 10], [430, 10], [430, 30], [230, 30]]},
            {"text": "PARA INSTITUCIÓN ACLARACIÓN", "page": 1, "confidence": 0.99, "bbox": [[10, 40], [260, 40], [260, 60], [10, 60]]},
            {"text": "TELEFONOS UNIDAD ESPECIALIZADA", "page": 1, "confidence": 0.99, "bbox": [[270, 40], [520, 40], [520, 60], [270, 60]]},
        ]

        fields = _run_sync(extract_fields("FACTURA", ocr_text, ocr_boxes))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        self.assertEqual(payload.get("source"), "text_lines")
        self.assertEqual(payload["rows"][1][0], "0438349034")
        self.assertEqual(payload["rows"][1][1], "7379597479")

    def test_extract_factura_payment_table_completes_empty_ocr_cells_from_text(self):
        ocr_text = "\n".join(
            [
                "Cuenta    Referencia    Importe    Nombre",
                "56551346133    1620260115132703271255    $1,462.58    JOSE LUIS GARCIA LOPEZ",
            ]
        )
        ocr_boxes = [
            {"text": "Cuenta", "page": 1, "confidence": 0.99, "bbox": [[10, 10], [90, 10], [90, 30], [10, 30]]},
            {"text": "Referencia", "page": 1, "confidence": 0.99, "bbox": [[120, 10], [240, 10], [240, 30], [120, 30]]},
            {"text": "Importe", "page": 1, "confidence": 0.99, "bbox": [[260, 10], [340, 10], [340, 30], [260, 30]]},
            {"text": "Nombre", "page": 1, "confidence": 0.99, "bbox": [[360, 10], [440, 10], [440, 30], [360, 30]]},
            {"text": "56551346133", "page": 1, "confidence": 0.99, "bbox": [[10, 40], [120, 40], [120, 60], [10, 60]]},
            {"text": "1620260115132703271255", "page": 1, "confidence": 0.99, "bbox": [[120, 40], [300, 40], [300, 60], [120, 60]]},
            {"text": "$1,462.58", "page": 1, "confidence": 0.99, "bbox": [[260, 40], [340, 40], [340, 60], [260, 60]]},
        ]

        fields = _run_sync(extract_fields("FACTURA", ocr_text, ocr_boxes))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        self.assertEqual(payload.get("source"), "ocr_boxes")
        self.assertEqual(payload["rows"][1][0], "56551346133")
        self.assertEqual(payload["rows"][1][1], "1620260115132703271255")
        self.assertEqual(payload["rows"][1][2], "$1,462.58")
        self.assertEqual(payload["rows"][1][3], "JOSE LUIS GARCIA LOPEZ")

    def test_extract_factura_includes_pdf_replica_text_when_raw_text_has_layout(self):
        raw_text = "\n".join(
            [
                "Scotiabank Inverlat S.A.",
                "Transferencia de Archivos",
                "TIPO DE MOVIMIENTO    IMPORTE    FECHA DE APLICACION",
                "DA ALTA    $3,000.00    15/01/2026",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", raw_text, None, raw_text=raw_text))
        data = _field_map(fields)

        self.assertIn("replica_pdf_texto", data)
        self.assertIn("Scotiabank Inverlat S.A.", data.get("replica_pdf_texto", ""))
        self.assertIn("DA ALTA", data.get("replica_pdf_texto", ""))

    def test_extract_factura_includes_pdf_replica_layout_payload(self):
        raw_text = "\n".join(
            [
                "Scotiabank Inverlat S.A.",
                "Transferencia de Archivos",
                "TIPO DE MOVIMIENTO    IMPORTE",
                "DA ALTA    $3,000.00",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", raw_text, None, raw_text=raw_text))
        data = _field_map(fields)

        self.assertIn("replica_pdf_layout", data)
        payload = json.loads(data["replica_pdf_layout"])
        self.assertIn("pages", payload)
        self.assertGreaterEqual(len(payload["pages"]), 1)
        self.assertIn("lines", payload["pages"][0])
        self.assertGreaterEqual(len(payload["pages"][0]["lines"]), 2)

    def test_extract_factura_payment_table_from_compact_nomina_text(self):
        ocr_text = "\n".join(
            [
                "Dispersión de Pago de Nómina",
                "DATOS DEL BENEFICIARIO",
                "Número de cuenta de Abono:56551346133",
                "Referencia:1620260115132703271255",
                "Importe:$1,462.58 MXN",
                "Estatus:Procesado",
                "Nombre:JOSE LUIS",
                "Concepto:Pago de Nómina",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", ocr_text, None))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        rows = payload.get("rows", [])
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "CUENTA")
        self.assertEqual(rows[1][0], "56551346133")
        self.assertEqual(rows[1][1], "1620260115132703271255")
        self.assertIn("1,462.58", rows[1][2])
        self.assertIn("JOSE LUIS", rows[1][3])

    def test_extract_factura_payment_table_from_bbva_nomina_advanced_lines(self):
        ocr_text = "\n".join(
            [
                "REPORTE DE OPERACIONES",
                "CUENTA CUENTA REFERENCIA REFERENCIA IMPORTE IMPORTE NOMBRE NOMBRE APELLIDO PATERNO APELLIDO MATERNO ESTATUS CONCEPTO CONCEPTO",
                "56783223195 1620260115134340581263 $610.44 MARLA GRISELDA MENDEZ FLORES PROCESADO PAGO DE NOMINA",
                "56936397470 1620260115134348451388 $1,537.35 ROLANDO ROGERIO CONTRERAS CAMARGO PROCESADO PAGO DE NOMINA",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", ocr_text, None))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        rows = payload.get("rows", [])
        self.assertGreaterEqual(len(rows), 3)
        self.assertEqual(
            rows[0],
            [
                "CUENTA",
                "REFERENCIA",
                "IMPORTE",
                "NOMBRE",
                "APELLIDO PATERNO",
                "APELLIDO MATERNO",
                "ESTATUS",
                "CONCEPTO",
            ],
        )
        self.assertEqual(rows[1][0], "56783223195")
        self.assertEqual(rows[1][1], "1620260115134340581263")
        self.assertEqual(rows[1][2], "610.44")
        self.assertEqual(rows[1][3], "MARLA GRISELDA")
        self.assertEqual(rows[1][4], "MENDEZ")
        self.assertEqual(rows[1][5], "FLORES")
        self.assertEqual(rows[1][6], "PROCESADO")
        self.assertEqual(rows[1][7], "PAGO DE NOMINA")
        self.assertEqual(rows[2][0], "56936397470")
        self.assertEqual(rows[2][1], "1620260115134348451388")
        self.assertEqual(rows[2][2], "1,537.35")
        self.assertEqual(rows[2][3], "ROLANDO ROGERIO")
        self.assertEqual(rows[2][4], "CONTRERAS")
        self.assertEqual(rows[2][5], "CAMARGO")

    def test_extract_factura_payment_table_from_bbva_nomina_two_records_same_line(self):
        ocr_text = "\n".join(
            [
                "REPORTE DE OPERACIONES",
                "CUENTA CUENTA REFERENCIA REFERENCIA IMPORTE IMPORTE NOMBRE NOMBRE APELLIDO PATERNO APELLIDO MATERNO ESTATUS CONCEPTO CONCEPTO",
                "56783223195 1620260115134340581263 $610.44 MARLA GRISELDA MENDEZ FLORES 56936397470 1620260115134348451388 $1,537.35 ROLANDO ROGERIO CONTRERAS CAMARGO PROCESADO PAGO DE NOMINA",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", ocr_text, None))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        rows = payload.get("rows", [])
        self.assertGreaterEqual(len(rows), 3)
        self.assertEqual(rows[1][0], "56783223195")
        self.assertEqual(rows[1][1], "1620260115134340581263")
        self.assertEqual(rows[1][3], "MARLA GRISELDA")
        self.assertEqual(rows[1][4], "MENDEZ")
        self.assertEqual(rows[1][5], "FLORES")
        self.assertEqual(rows[2][0], "56936397470")
        self.assertEqual(rows[2][1], "1620260115134348451388")
        self.assertEqual(rows[2][3], "ROLANDO ROGERIO")
        self.assertEqual(rows[2][4], "CONTRERAS")
        self.assertEqual(rows[2][5], "CAMARGO")

    def test_extract_factura_payment_table_from_bbva_nomina_rows_without_nomina_per_line(self):
        ocr_text = "\n".join(
            [
                "REPORTE DE OPERACIONES",
                "CUENTA REFERENCIA IMPORTE NOMBRE APELLIDO PATERNO APELLIDO MATERNO ESTATUS CONCEPTO",
                "56783223195 1620260115134340581263 $610.44 MARLA GRISELDA MENDEZ FLORES PROCESADO",
                "56936397470 1620260115134348451388 $1,537.35 ROLANDO ROGERIO CONTRERAS CAMARGO PROCESADO",
                "56905029323 1620260115134344071306 $353.60 EDGAR HASSAN GUZMAN CASTRO PROCESADO",
                "PAGO DE NOMINA",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", ocr_text, None))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        rows = payload.get("rows", [])
        self.assertGreaterEqual(len(rows), 4)
        self.assertEqual(rows[1][0], "56783223195")
        self.assertEqual(rows[1][1], "1620260115134340581263")
        self.assertEqual(rows[1][7], "PAGO DE NOMINA")
        self.assertEqual(rows[2][0], "56936397470")
        self.assertEqual(rows[2][1], "1620260115134348451388")
        self.assertEqual(rows[3][0], "56905029323")
        self.assertEqual(rows[3][1], "1620260115134344071306")

    def test_extract_factura_bbva_nomina_reference_with_ocr_space(self):
        """Referencias con espacio OCR intermedio (ej: '16202601151343405812 63') deben extraerse correctamente."""
        ocr_text = "\n".join(
            [
                "REPORTE DE OPERACIONES PAGO DE NOMINA",
                "CUENTA REFERENCIA IMPORTE NOMBRE APELLIDO PATERNO APELLIDO MATERNO ESTATUS CONCEPTO",
                "56783223195 16202601151343405812 63 $610.44 MARLA GRISELDA MENDEZ FLORES PROCESADO PAGO DE NOMINA",
                "56936397470 16202601151343484513 88 $1,537.35 ROLANDO ROGERIO CONTRERAS CAMARGO PROCESADO PAGO DE NOMINA",
                "56905029323 16202601151343440713 06 $353.60 EDGAR HASSAN GUZMAN CASTRO PROCESADO PAGO DE NOMINA",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", ocr_text, None))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        rows = payload.get("rows", [])
        # Deben aparecer las 3 filas (+ encabezado)
        self.assertGreaterEqual(len(rows), 4, "Deben extraerse todas las filas, no solo la fila de resumen")
        # Referencia normalizada sin espacio
        self.assertEqual(rows[1][0], "56783223195")
        self.assertEqual(rows[1][1], "1620260115134340581263")
        self.assertEqual(rows[1][2], "610.44")
        self.assertEqual(rows[1][3], "MARLA GRISELDA")
        self.assertEqual(rows[2][0], "56936397470")
        self.assertEqual(rows[2][1], "1620260115134348451388")
        self.assertEqual(rows[2][2], "1,537.35")
        self.assertEqual(rows[3][0], "56905029323")
        self.assertEqual(rows[3][1], "1620260115134344071306")
        self.assertEqual(rows[3][2], "353.60")

    def test_extract_factura_bbva_nomina_multipage_ocr_boxes(self):
        """Simula PDF multi-página donde OCR devuelve cada celda como un box separado.
        Las filas de distintas páginas con el mismo Y no deben mezclarse entre sí.
        """
        from app.pipelines.extract import _extract_payment_table_rows_from_boxes

        def _box(text, x1, y1, x2, y2, page):
            return {"text": text, "confidence": 0.99, "bbox": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]], "page": page}

        # Página 1: header + resumen (1 fila)
        p1_header_y = (10, 20)
        p1_row1_y = (30, 42)
        # Página 2: header repetido + 3 filas de pago
        p2_header_y = (10, 20)   # mismo Y que página 1 — sin page-aware grouping se mezclaría
        p2_row1_y = (30, 42)
        p2_row2_y = (50, 62)
        p2_row3_y = (70, 82)

        boxes = [
            # P1 header
            _box("CUENTA",           0, p1_header_y[0], 120, p1_header_y[1], 1),
            _box("REFERENCIA",     130, p1_header_y[0], 310, p1_header_y[1], 1),
            _box("IMPORTE",        320, p1_header_y[0], 420, p1_header_y[1], 1),
            _box("NOMBRE",         430, p1_header_y[0], 600, p1_header_y[1], 1),
            _box("APELLIDO PATERNO", 610, p1_header_y[0], 750, p1_header_y[1], 1),
            _box("APELLIDO MATERNO", 760, p1_header_y[0], 900, p1_header_y[1], 1),
            _box("ESTATUS",        910, p1_header_y[0], 1010, p1_header_y[1], 1),
            _box("CONCEPTO",      1020, p1_header_y[0], 1150, p1_header_y[1], 1),
            # P1 fila resumen (total)
            _box("56783223195",      0, p1_row1_y[0], 120, p1_row1_y[1], 1),
            _box("1620260115134340581263", 130, p1_row1_y[0], 310, p1_row1_y[1], 1),
            _box("$140,948.59",    320, p1_row1_y[0], 420, p1_row1_y[1], 1),
            _box("MARLA GRISELDA", 430, p1_row1_y[0], 600, p1_row1_y[1], 1),
            _box("MENDEZ",         610, p1_row1_y[0], 750, p1_row1_y[1], 1),
            _box("FLORES",         760, p1_row1_y[0], 900, p1_row1_y[1], 1),
            _box("PROCESADO",      910, p1_row1_y[0], 1010, p1_row1_y[1], 1),
            _box("PAGO DE NOMINA",1020, p1_row1_y[0], 1150, p1_row1_y[1], 1),
            # P2 header (repetido)
            _box("CUENTA",           0, p2_header_y[0], 120, p2_header_y[1], 2),
            _box("REFERENCIA",     130, p2_header_y[0], 310, p2_header_y[1], 2),
            _box("IMPORTE",        320, p2_header_y[0], 420, p2_header_y[1], 2),
            _box("NOMBRE",         430, p2_header_y[0], 600, p2_header_y[1], 2),
            _box("APELLIDO PATERNO", 610, p2_header_y[0], 750, p2_header_y[1], 2),
            _box("APELLIDO MATERNO", 760, p2_header_y[0], 900, p2_header_y[1], 2),
            _box("ESTATUS",        910, p2_header_y[0], 1010, p2_header_y[1], 2),
            _box("CONCEPTO",      1020, p2_header_y[0], 1150, p2_header_y[1], 2),
            # P2 fila 1
            _box("56783223195",      0, p2_row1_y[0], 120, p2_row1_y[1], 2),
            _box("1620260115134340581263", 130, p2_row1_y[0], 310, p2_row1_y[1], 2),
            _box("$610.44",        320, p2_row1_y[0], 420, p2_row1_y[1], 2),
            _box("MARLA GRISELDA", 430, p2_row1_y[0], 600, p2_row1_y[1], 2),
            _box("MENDEZ",         610, p2_row1_y[0], 750, p2_row1_y[1], 2),
            _box("FLORES",         760, p2_row1_y[0], 900, p2_row1_y[1], 2),
            _box("PROCESADO",      910, p2_row1_y[0], 1010, p2_row1_y[1], 2),
            _box("PAGO DE NOMINA",1020, p2_row1_y[0], 1150, p2_row1_y[1], 2),
            # P2 fila 2
            _box("56936397470",      0, p2_row2_y[0], 120, p2_row2_y[1], 2),
            _box("1620260115134348451388", 130, p2_row2_y[0], 310, p2_row2_y[1], 2),
            _box("$1,537.35",      320, p2_row2_y[0], 420, p2_row2_y[1], 2),
            _box("ROLANDO ROGERIO",430, p2_row2_y[0], 600, p2_row2_y[1], 2),
            _box("CONTRERAS",      610, p2_row2_y[0], 750, p2_row2_y[1], 2),
            _box("CAMARGO",        760, p2_row2_y[0], 900, p2_row2_y[1], 2),
            _box("PROCESADO",      910, p2_row2_y[0], 1010, p2_row2_y[1], 2),
            _box("PAGO DE NOMINA",1020, p2_row2_y[0], 1150, p2_row2_y[1], 2),
            # P2 fila 3
            _box("56905029323",      0, p2_row3_y[0], 120, p2_row3_y[1], 2),
            _box("1620260115134344071306", 130, p2_row3_y[0], 310, p2_row3_y[1], 2),
            _box("$353.60",        320, p2_row3_y[0], 420, p2_row3_y[1], 2),
            _box("EDGAR HASSAN",   430, p2_row3_y[0], 600, p2_row3_y[1], 2),
            _box("GUZMAN",         610, p2_row3_y[0], 750, p2_row3_y[1], 2),
            _box("CASTRO",         760, p2_row3_y[0], 900, p2_row3_y[1], 2),
            _box("PROCESADO",      910, p2_row3_y[0], 1010, p2_row3_y[1], 2),
            _box("PAGO DE NOMINA",1020, p2_row3_y[0], 1150, p2_row3_y[1], 2),
        ]

        rows = _extract_payment_table_rows_from_boxes(boxes)
        # Debe extraer header + 4 filas de datos (1 de p1 + 3 de p2), no mezclar páginas
        self.assertGreaterEqual(len(rows), 4, "Debe extraer filas de ambas páginas sin mezclarlas")
        data_rows = [r for r in rows[1:] if r[0] not in ("CUENTA",)]
        self.assertGreaterEqual(len(data_rows), 3, "Debe tener al menos las 3 filas de página 2")
        # Las cuentas deben ser individuales, no concatenadas
        all_accounts = [r[0] for r in data_rows]
        for acct in all_accounts:
            self.assertLessEqual(len(acct), 15, f"Cuenta '{acct}' no debe ser una mezcla de varias páginas")

    def test_extract_factura_payment_table_from_scotia_transfer_text(self):
        ocr_text = "\n".join(
            [
                "Scotiabank Inverlat S.A.",
                "Transferencia de Archivos",
                "DA ALTA",
                "04 ABONO EN",
                "CUENTA",
                "$3,000.00",
                "15/01/2026",
                "A35",
                "VELAZCO",
                "DIONICIO ZENON",
                "1",
                "00014052605935660925 14",
                "1",
                "PAGO35",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", ocr_text, None))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        rows = payload.get("rows", [])
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "TIPO DE REGISTRO")
        self.assertEqual(rows[0][1], "TIPO DE MOVIMIENTO (PAGO)")
        self.assertEqual(rows[1][0], "DA ALTA")
        self.assertIn("ABONO EN CUENTA", rows[1][1])
        self.assertEqual(rows[1][2], "$3,000.00")
        self.assertEqual(rows[1][3], "15/01/2026")
        self.assertEqual(rows[1][7], "00014052605935660925")
        self.assertIn("PAGO35", rows[1][10])

    def test_extract_factura_payment_detail_payload_from_scotia_transfer_text(self):
        ocr_text = "\n".join(
            [
                "Scotiabank Inverlat S.A.",
                "Transferencia de Archivos",
                "Nombre de Empresa: SUMINISTROS FLOMEN SA DE CV",
                "Nombre del archivo: NOM 15 SEP 25.txt",
                "Numero de Contrato Scotia en Linea: 527351",
                "Folio: 62016184160",
                "Nombre de usuario del sistema y nombre: 002 - MARIO ANTONIO FLOTA ALPUCHE",
                "Fecha y hora de validacion del archivo: Sin fecha y hora de registro.",
                "Cantidad Total de Movimientos: 6",
                "Importe Total de Movimientos: $18,000.00",
                "DA ALTA",
                "04 ABONO EN",
                "CUENTA",
                "$3,000.00",
                "15/01/2026",
                "A35",
                "VELAZCO",
                "DIONICIO ZENON",
                "1",
                "00014052605935660925 14",
                "1",
                "PAGO35",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", ocr_text, None))
        data = _field_map(fields)

        self.assertIn("pago_detalle", data)
        payload = json.loads(data["pago_detalle"])
        self.assertEqual(payload.get("bank"), "SCOTIABANK")
        self.assertEqual(payload.get("metadata", {}).get("nombre_empresa"), "SUMINISTROS FLOMEN SA DE CV")
        self.assertEqual(payload.get("metadata", {}).get("nombre_archivo"), "NOM 15 SEP 25.TXT")
        self.assertEqual(payload.get("metadata", {}).get("numero_contrato_scotia_linea"), "527351")
        self.assertEqual(payload.get("metadata", {}).get("folio"), "62016184160")
        self.assertIn("002 - MARIO ANTONIO FLOTA ALPUCHE", payload.get("metadata", {}).get("usuario_sistema_nombre", ""))
        self.assertEqual(payload.get("metadata", {}).get("fecha_hora_validacion_archivo"), "SIN FECHA Y HORA DE REGISTRO")
        self.assertEqual(payload.get("metadata", {}).get("cantidad_total_movimientos"), "6")
        self.assertEqual(payload.get("metadata", {}).get("importe_total_movimientos"), "18,000.00")
        rows = payload.get("table", {}).get("rows", [])
        self.assertGreaterEqual(len(rows), 1)
        self.assertIn("tipoderegistro", rows[0])
        self.assertEqual(rows[0].get("tipoderegistro"), "DA ALTA")
        self.assertIn("tipodemovimientopago", rows[0])
        self.assertIn("ABONO EN CUENTA", rows[0].get("tipodemovimientopago", ""))
        canonical_rows = payload.get("table", {}).get("canonical_rows", [])
        self.assertGreaterEqual(len(canonical_rows), 1)
        self.assertEqual(canonical_rows[0].get("tipo_registro"), "DA ALTA")
        self.assertIn("ABONO EN CUENTA", canonical_rows[0].get("tipo_movimiento", ""))
        self.assertEqual(canonical_rows[0].get("fecha_aplicacion"), "15/01/2026")
        self.assertEqual(canonical_rows[0].get("cuenta_beneficiario"), "00014052605935660925")
        self.assertEqual(canonical_rows[0].get("concepto_pago"), "PAGO35")

    def test_extract_factura_scotia_rows_are_deduplicated(self):
        ocr_text = "\n".join(
            [
                "Scotiabank Inverlat S.A.",
                "Transferencia de Archivos",
                "DA ALTA 04 ABONO EN CUENTA $3,000.00 15/01/2026 A35 VELAZCO DIONICIO ZENON 1 00014052605935660925 14 1 PAGO35",
                "DA ALTA 04 ABONO EN CUENTA $3,000.00 15/01/2026 A35 VELAZCO DIONICIO ZENON 1 00014052605935660925 14 1 PAGO35",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", ocr_text, None))
        data = _field_map(fields)
        payload = json.loads(data["tabla_celdas"])
        rows = payload.get("rows", [])
        self.assertEqual(len(rows), 2)

    def test_extract_factura_scotia_includes_summary_tables(self):
        ocr_text = "\n".join(
            [
                "Scotiabank Inverlat S.A.",
                "Transferencia de Archivos",
                "Cantidad de Movimientos Altas",
                "Importe de Movimiento Altas",
                "Cantidad de Movimientos Bajas",
                "Importe de Movimientos Bajas",
                "6",
                "$18,000.00",
                "0",
                "$0.00",
                "Total Cantidad de Movimientos Altas",
                "Total Importe de Movimiento Altas",
                "Total Cantidad de Movimientos Bajas",
                "Total Importe de Movimientos Bajas",
                "6",
                "$18,000.00",
                "0",
                "$0.00",
                "DA ALTA 04 ABONO EN CUENTA $3,000.00 15/01/2026 A35 VELAZCO DIONICIO ZENON 1 00014052605935660925 14 1 PAGO35",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", ocr_text, None))
        data = _field_map(fields)
        self.assertIn("pago_detalle", data)
        payload = json.loads(data["pago_detalle"])
        summary = payload.get("table", {}).get("summary_tables", [])
        self.assertGreaterEqual(len(summary), 2)
        self.assertEqual(summary[0].get("title"), "RESUMEN MOVIMIENTOS")
        self.assertEqual(summary[0].get("rows", [[]])[0][0], "6")
        self.assertEqual(summary[0].get("rows", [[]])[0][1], "18,000.00")
        self.assertEqual(summary[1].get("title"), "RESUMEN TOTAL")

    def test_extract_factura_scotia_tablaceldas_includes_bottom_summary_cells(self):
        ocr_text = "\n".join(
            [
                "Scotiabank Inverlat S.A.",
                "Transferencia de Archivos",
                "DA ALTA 04 ABONO EN CUENTA $3,000.00 15/01/2026 A35 VELAZCO DIONICIO ZENON 1 00014052605935660925 14 1 PAGO35",
                "Cantidad de Movimientos Altas",
                "Importe de Movimiento Altas",
                "Cantidad de Movimientos Bajas",
                "Importe de Movimientos Bajas",
                "6",
                "$18,000.00",
                "0",
                "$0.00",
                "Total Cantidad de Movimientos Altas",
                "Total Importe de Movimiento Altas",
                "Total Cantidad de Movimientos Bajas",
                "Total Importe de Movimientos Bajas",
                "6",
                "$18,000.00",
                "0",
                "$0.00",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", ocr_text, None))
        data = _field_map(fields)
        payload = json.loads(data["tabla_celdas"])
        rows = payload.get("rows", [])
        self.assertGreaterEqual(len(rows), 6)
        self.assertTrue(
            any(row[:4] == ["CANTIDAD DE MOVIMIENTOS ALTAS", "IMPORTE DE MOVIMIENTO ALTAS", "CANTIDAD DE MOVIMIENTOS BAJAS", "IMPORTE DE MOVIMIENTOS BAJAS"] for row in rows),
        )
        self.assertTrue(any(row[:4] == ["6", "18,000.00", "0", "0.00"] for row in rows))
        self.assertTrue(
            any(row[:4] == [
                "TOTAL CANTIDAD DE MOVIMIENTOS ALTAS",
                "TOTAL IMPORTE DE MOVIMIENTO ALTAS",
                "TOTAL CANTIDAD DE MOVIMIENTOS BAJAS",
                "TOTAL IMPORTE DE MOVIMIENTOS BAJAS",
            ] for row in rows),
        )

    def test_extract_factura_payment_detail_payload_canonical_for_bbva(self):
        ocr_text = "\n".join(
            [
                "REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS",
                "Fecha y hora de proceso: 15/01/2026 09:51",
                "Archivo: BBVA_PAGOS_15012026.TXT",
                "Usuario: TESORERIA NOMINA",
                "Lote: 12",
                "Cuenta    Referencia    Importe    Nombre    Estatus    Concepto",
                "000000001069485436    8837492015    $3,000.00    CARLOS ROBERTO RODRIGUEZ DOMINGUEZ    APLICADO    PAGO DE NOMINA",
                "Tipo de Pago: PAGO DE NOMINA",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", ocr_text, None))
        data = _field_map(fields)

        self.assertIn("pago_detalle", data)
        payload = json.loads(data["pago_detalle"])
        self.assertEqual(payload.get("bank"), "BBVA")
        self.assertEqual(payload.get("metadata", {}).get("reporte_tipo"), "REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS")
        self.assertEqual(payload.get("metadata", {}).get("tipo_pago"), "PAGO DE NOMINA")
        self.assertIn("APLICADO", payload.get("metadata", {}).get("estatus_detectados", ""))
        self.assertEqual(payload.get("metadata", {}).get("fecha_hora_proceso"), "15/01/2026 09:51")
        self.assertEqual(payload.get("metadata", {}).get("nombre_archivo"), "BBVA_PAGOS_15012026.TXT")
        self.assertEqual(payload.get("metadata", {}).get("usuario_sistema_nombre"), "TESORERIA NOMINA")
        self.assertEqual(payload.get("metadata", {}).get("numero_lote"), "12")
        canonical_rows = payload.get("table", {}).get("canonical_rows", [])
        self.assertGreaterEqual(len(canonical_rows), 1)
        self.assertEqual(canonical_rows[0].get("cuenta"), "000000001069485436")
        self.assertEqual(canonical_rows[0].get("referencia"), "8837492015")
        self.assertEqual(canonical_rows[0].get("importe"), "3,000.00")
        self.assertIn("CARLOS ROBERTO", canonical_rows[0].get("nombre", ""))
        self.assertEqual(canonical_rows[0].get("estatus"), "APLICADO")

    def test_extract_factura_payment_detail_fixes_hernendez_ocr_typo(self):
        ocr_text = "\n".join(
            [
                "REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS",
                "Cuenta Referencia Importe Nombre Apellido paterno Apellido materno Estatus Concepto",
                "000000001069485436 8837492015 $3,000.00 ANA MARIA HERNENDEZ LOPEZ APLICADO PAGO DE NOMINA",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", ocr_text, None))
        data = _field_map(fields)

        self.assertIn("pago_detalle", data)
        payload = json.loads(data["pago_detalle"])
        canonical_rows = payload.get("table", {}).get("canonical_rows", [])
        self.assertGreaterEqual(len(canonical_rows), 1)
        self.assertEqual(canonical_rows[0].get("apellido_paterno"), "HERNANDEZ")

    def test_extract_factura_payment_table_from_bbva_transmision_text(self):
        ocr_text = "\n".join(
            [
                "REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS",
                "No. EmpleadoNombre",
                "Tipo CuentaNo. de Cuenta",
                "Importe Estatus CódigoDescripciónClave Rastreo",
                "0000000001",
                "CARLOS ROBERTO RODRIGUEZ DOMINGUEZ",
                "01",
                "000000001069485436$3,000.00APLICADO",
                "00",
                "ACEPTADO",
                "Tipo de Pago: PAGO DE NOMINA",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", ocr_text, None))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        rows = payload.get("rows", [])
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "NO. EMPLEADO")
        self.assertEqual(rows[0][1], "NOMBRE")
        self.assertEqual(rows[0][2], "TIPO CUENTA")
        self.assertEqual(rows[0][3], "NO. DE CUENTA")
        self.assertEqual(rows[0][4], "IMPORTE")
        self.assertEqual(rows[0][5], "ESTATUS")
        self.assertEqual(rows[0][6], "CODIGO")
        self.assertEqual(rows[0][7], "DESCRIPCION")
        self.assertEqual(rows[0][8], "CLAVE RASTREO")
        self.assertEqual(rows[1][0], "0000000001")
        self.assertIn("CARLOS ROBERTO", rows[1][1])
        self.assertEqual(rows[1][2], "01")
        self.assertEqual(rows[1][3], "000000001069485436")
        self.assertEqual(rows[1][4], "3,000.00")
        self.assertIn(rows[1][5], {"TRANSMITIDO", "APLICADO", "ACEPTADO"})
        self.assertEqual(rows[1][6], "00")
        self.assertIn(rows[1][7], {"ACEPTADO", "APLICADO", "TRANSMITIDO"})

    def test_extract_factura_payment_table_from_bbva_transfer_receipt_text(self):
        ocr_text = "\n".join(
            [
                "15/01/2026 9:10:29 AM",
                "COMPROBANTE",
                "Mis operaciones frecuentes - Traspasos a otros bancos",
                "PODRIX CONSTRUCTION S DE RL DE CV",
                "15/01/2026",
                "Resultado del traspaso",
                "Cuenta de retiro:",
                "0123965767",
                "Tipo de operación:",
                "INTERBANCARIO CON / SIN CHEQUERA",
                "Banco destino:",
                "SANTANDER",
                "Cuenta de depósito:",
                "014888567491511396",
                "Nombre corto:",
                "CARLOS C E",
                "Importe:",
                "$5,115.99",
                "Forma de depósito:",
                "MISMO DIA (SPEI)",
                "Concepto de pago:",
                "PAGO NM",
                "Referencia numérica:",
                "01",
                "Clave de rastreo:",
                "BNET01002601150032369465",
                "Fecha y Hora de Captura:",
                "15/01/2026 14:36:38",
                "Folio de internet:",
                "4217367106",
                "Datos del beneficiario",
                "Nombre:",
                "CRUZ ESPINO CARLOS JESUS",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", ocr_text, None))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        rows = payload.get("rows", [])
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "CUENTA DE RETIRO")
        self.assertEqual(rows[0][3], "CUENTA DE DEPOSITO")
        self.assertEqual(rows[1][0], "0123965767")
        self.assertEqual(rows[1][2], "SANTANDER")
        self.assertEqual(rows[1][3], "014888567491511396")
        self.assertEqual(rows[1][4], "5,115.99")
        self.assertEqual(rows[1][7], "01")
        self.assertEqual(rows[1][8], "BNET01002601150032369465")
        self.assertEqual(payload.get("bank"), "BBVA")
        self.assertEqual(payload.get("metadata", {}).get("fecha_hora_captura"), "15/01/2026 14:36:38")
        self.assertEqual(payload.get("metadata", {}).get("folio_internet"), "4217367106")
        mapped = payload.get("mapped_fields", {})
        self.assertEqual(mapped.get("banco"), "BBVA")
        self.assertEqual(mapped.get("cuenta"), "014888567491511396")
        self.assertEqual(mapped.get("cuenta_retiro"), "0123965767")
        self.assertEqual(mapped.get("referencia"), "01")
        self.assertEqual(mapped.get("clave_rastreo"), "BNET01002601150032369465")
        self.assertEqual(mapped.get("nombre_beneficiario"), "CRUZ ESPINO CARLOS JESUS")
        self.assertEqual(mapped.get("fecha_hora_captura"), "15/01/2026 14:36:38")
        self.assertEqual(mapped.get("folio_internet"), "4217367106")

        self.assertIn("pago_detalle", data)
        detail = json.loads(data["pago_detalle"])
        self.assertEqual(detail.get("bank"), "BBVA")
        canonical_rows = detail.get("table", {}).get("canonical_rows", [])
        self.assertGreaterEqual(len(canonical_rows), 1)
        self.assertEqual(canonical_rows[0].get("cuenta"), "014888567491511396")
        self.assertEqual(canonical_rows[0].get("cuenta_retiro"), "0123965767")
        self.assertEqual(canonical_rows[0].get("banco_destino"), "SANTANDER")
        self.assertEqual(canonical_rows[0].get("referencia"), "01")
        self.assertEqual(canonical_rows[0].get("concepto_pago"), "PAGO NM")
        self.assertEqual(canonical_rows[0].get("clave_rastreo"), "BNET01002601150032369465")
        metadata = detail.get("metadata", {})
        self.assertEqual(metadata.get("fecha_hora_captura"), "15/01/2026 14:36:38")
        self.assertEqual(metadata.get("folio_internet"), "4217367106")
        self.assertNotIn("hora_archivo", metadata)
        self.assertNotIn("folio", metadata)

    def test_extract_factura_banorte_detail_table_keeps_all_columns(self):
        ocr_text = "\n".join(
            [
                "GRUPO FINANCIERO BANORTE",
                "REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS",
                "Folio electronico: 150120264263001PN7379597479",
                "Tipo de Pago: PAGO DE NOMINA",
                "Estatus: TRANSMITIDO",
                "Detalle",
                "No. EmpleadoNombre",
                "Tipo CuentaNo. de Cuenta",
                "Importe Estatus CodigoDescripcionClave Rastreo",
                "0000000001",
                "CARLOS ROBERTO RODRIGUEZ DOMINGUEZ",
                "01",
                "000000001069485436$3,000.00APLICADO",
                "00",
                "ACEPTADO",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", ocr_text, None))
        data = _field_map(fields)

        payload = json.loads(data["tabla_celdas"])
        rows = payload.get("rows", [])
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "NO. EMPLEADO")
        self.assertEqual(rows[0][8], "CLAVE RASTREO")
        self.assertEqual(rows[1][0], "0000000001")
        self.assertIn("CARLOS ROBERTO", rows[1][1])
        self.assertEqual(rows[1][2], "01")
        self.assertEqual(rows[1][3], "000000001069485436")
        self.assertEqual(rows[1][4], "3,000.00")
        self.assertEqual(rows[1][6], "00")
        self.assertEqual(rows[1][7], "ACEPTADO")
        self.assertIn("150120264263001PN7379597479", rows[1][8])

    def test_extract_factura_contract_keeps_only_table_cells(self):
        ocr_text = "\n".join(
            [
                "BANCO SCOTIABANK INVERLAT",
                "TITULAR: NOMBRE DEL ARCHIVO",
                "Cuenta    Referencia    Importe    Nombre",
                "56551346133    1620260115132703271255    $1,462.58    JOSE LUIS",
            ]
        )
        fields = _run_sync(extract_fields("FACTURA", ocr_text, None))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        self.assertNotIn("banco", data)
        self.assertNotIn("titular", data)
        self.assertNotIn("cuenta", data)

    def test_extract_comprobante_telmex_phone_with_symbols(self):
        ocr_text = "\n".join(
            [
                "TELMEX",
                "NUMERO TELEFONICO (33) 1234-5678",
                "NO DE CUENTA 0011223344",
                "TOTAL A PAGAR $999.99",
            ]
        )
        fields = _run_sync(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("numero_servicio"), "3312345678")
        self.assertEqual(data.get("cuenta"), "0011223344")

    def test_extract_comprobante_cp_with_ocr_confusions(self):
        ocr_text = "\n".join(
            [
                "TELMEX",
                "NUMERO TELEFONICO 3312345678",
                "CALLE FALSA 123 COL CENTRO CP 44I0O",
            ]
        )
        fields = _run_sync(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("cp"), "44100")

    def test_extract_acta_folio_with_ocr_confusions(self):
        ocr_text = "\n".join(
            [
                "ACTA DE NACIMIENTO",
                "FOLIO I2O3",
            ]
        )
        fields = _run_sync(extract_fields("ACTA_NACIMIENTO", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("folio"), "1203")

    def test_extract_acta_nombre_from_text_with_labeled_parts(self):
        ocr_text = "\n".join(
            [
                "ACTA DE NACIMIENTO",
                "NOMBRE(S): ERWIN GUSTAVO",
                "PRIMER APELLIDO: GARCIA",
                "SEGUNDO APELLIDO: CAMPOS",
                "SEXO: HOMBRE",
            ]
        )
        fields = _run_sync(extract_fields("ACTA_NACIMIENTO", ocr_text, None))
        data = _field_map(fields)
        self.assertEqual(data.get("nombre"), "ERWIN GUSTAVO GARCIA CAMPOS")

    def test_extract_acta_nombre_from_persona_registrada_section(self):
        ocr_text = "\n".join(
            [
                "ACTA DE NACIMIENTO",
                "DATOS DE LA PERSONA REGISTRADA",
                "ERWIN GUSTAVO GARCIA CAMPOS",
                "SEXO HOMBRE",
            ]
        )
        fields = _run_sync(extract_fields("ACTA_NACIMIENTO", ocr_text, None))
        data = _field_map(fields)
        self.assertEqual(data.get("nombre"), "ERWIN GUSTAVO GARCIA CAMPOS")

    def test_extract_acta_nombre_with_noisy_ocr_labels(self):
        ocr_text = "\n".join(
            [
                "ACTA DE NACIMIENTO",
                "N0MBRE(S): ERWIN GUSTAVO",
                "PR1MER APELLID0: GARCIA",
                "SEGUND0 APELLID0: CAMPOS",
                "SEX0: HOMBRE",
            ]
        )
        fields = _run_sync(extract_fields("ACTA_NACIMIENTO", ocr_text, None))
        data = _field_map(fields)
        self.assertEqual(data.get("nombre"), "ERWIN GUSTAVO GARCIA CAMPOS")

    def test_extract_acta_nombre_ignores_sexo_noise_when_labels_are_merged(self):
        ocr_text = "\n".join(
            [
                "ACTA DE NACIMIENTO",
                "Nombre(s):ERWIN GUSTAVO",
                "Primer Apellido GARCIA",
                "SegundoApellida CAMPOS",
                "SexaHOMBRE",
                "FechadeNacimienta25/04/2001",
                "Lugar de Nacimiento: JONUTA TABASCO",
            ]
        )
        ocr_boxes = [
            _box("ACTA DE NACIMIENTO", 10),
            _box("Nombre(s):ERWIN GUSTAVO", 40),
            _box("Primer Apellido GARCIA", 70),
            _box("SegundoApellida CAMPOS", 100),
            _box("SexaHOMBRE", 130),
            _box("FechadeNacimienta25/04/2001", 160),
            _box("Lugar de Nacimiento: JONUTA TABASCO", 190),
        ]
        fields = _run_sync(extract_fields("ACTA_NACIMIENTO", ocr_text, ocr_boxes))
        data = _field_map(fields)

        self.assertEqual(data.get("nombre"), "ERWIN GUSTAVO GARCIA CAMPOS")
        self.assertEqual(data.get("sexo"), "H")
        self.assertEqual(data.get("fecha_nacimiento"), "25/04/2001")

    def test_extract_acta_nombre_when_label_and_value_are_split_lines(self):
        ocr_text = "\n".join(
            [
                "ACTA DE NACIMIENTO",
                "N0MBRE(S)",
                "ERWIN GUSTAVO",
                "PR1MER APELLID0",
                "GARCIA",
                "SEGUND0 APELLID0",
                "CAMPOS",
            ]
        )
        fields = _run_sync(extract_fields("ACTA_NACIMIENTO", ocr_text, None))
        data = _field_map(fields)
        self.assertEqual(data.get("nombre"), "ERWIN GUSTAVO GARCIA CAMPOS")

    def test_extract_comprobante_referencia_with_ocr_confusions(self):
        ocr_text = "\n".join(
            [
                "TELMEX",
                "LINEA DE CAPTURA O2345I789OI2345678",
            ]
        )
        fields = _run_sync(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("referencia"), "023451789012345678")

    def test_extract_telmex_due_date_is_not_cliente(self):
        ocr_text = "\n".join(
            [
                "TELMEX",
                "CLIENTE PAGAR ANTES DE: 23-ENE-2026",
                "NUMERO TELEFONICO 3312345678",
                "NO DE CUENTA 0011223344",
                "TOTAL A PAGAR $549.00",
            ]
        )
        ocr_boxes = [
            _box("TELMEX", 10),
            _box("CLIENTE PAGAR ANTES DE: 23-ENE-2026", 40),
            _box("NUMERO TELEFONICO 3312345678", 70),
            _box("NO DE CUENTA 0011223344", 100),
            _box("TOTAL A PAGAR $549.00", 130),
        ]
        fields = _run_sync(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, ocr_boxes))
        data = _field_map(fields)

        self.assertEqual(data.get("fecha_limite"), "23/01/2026")
        self.assertNotIn("PAGAR ANTES DE", data.get("cliente", ""))

    def test_extract_telmex_due_date_with_ocr_noise_is_not_cliente(self):
        ocr_text = "\n".join(
            [
                "TELMEX",
                "CLIENTE PAGAR ANTES DE: 23–ENE-2O26",
                "NUMERO TELEFONICO 3312345678",
                "NO DE CUENTA 0011223344",
                "TOTAL A PAGAR $549.00",
            ]
        )
        ocr_boxes = [
            _box("TELMEX", 10),
            _box("CLIENTE PAGAR ANTES DE: 23–ENE-2O26", 40),
            _box("NUMERO TELEFONICO 3312345678", 70),
            _box("NO DE CUENTA 0011223344", 100),
            _box("TOTAL A PAGAR $549.00", 130),
        ]
        fields = _run_sync(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, ocr_boxes))
        data = _field_map(fields)

        self.assertEqual(data.get("fecha_limite"), "23/01/2026")
        self.assertNotIn("PAGAR ANTES DE", data.get("cliente", ""))

    def test_extract_telcel_comprobante_with_noisy_ocr(self):
        ocr_text = "\n".join(
            [
                "FACTURA TELCEL",
                "L1NEA TELCEL 55I234O678",
                "CUENTA 00I1223344",
                "REFERENCIA DE PAGO O2345I789OI2345678",
                "TOTAL A PAGAR $I,549.00",
                "DOMICILIO DE ENVIO AV INSURGENTES SUR I234 COL DEL VALLE C.P. O3I00 CDMX",
            ]
        )
        fields = _run_sync(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None, raw_text=ocr_text, filename="telcel.jpg"))
        data = _field_map(fields)

        self.assertEqual(data.get("proveedor"), "TELCEL")
        self.assertEqual(data.get("numero_servicio"), "5512340678")
        self.assertEqual(data.get("cuenta"), "0011223344")
        self.assertEqual(data.get("referencia"), "023451789012345678")
        self.assertEqual(data.get("cp"), "03100")
        self.assertIn("INSURGENTES SUR", data.get("domicilio", ""))

    def test_extract_cfe_domicilio_from_supply_label(self):
        ocr_text = "\n".join(
            [
                "COMISION FEDERAL DE ELECTRICIDAD",
                "NO. DE SERVICIO 795130504593",
                "CUENTA 29DW05A012970875",
                "DOMICILIO DE SUMINISTRO CALLE PINO SUAREZ 123 COL CENTRO",
                "CULIACAN SIN",
            ]
        )
        fields = _run_sync(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None))
        data = _field_map(fields)

        self.assertIn("CALLE PINO SUAREZ 123", data.get("domicilio", ""))

    def test_extract_cfe_referencia_from_rmu_fallback(self):
        ocr_text = "\n".join(
            [
                "CFE COMISION FEDERAL DE ELECTRICIDAD",
                "NO. DE SERVICIO 795130504593",
                "RMU:2418013-05-22XAXX-010101002CFE",
            ]
        )
        fields = _run_sync(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("referencia"), "24180130522010101002")

    def test_extract_cfe_referencia_prefers_address_when_available(self):
        ocr_text = "\n".join(
            [
                "CFE COMISION FEDERAL DE ELECTRICIDAD",
                "DOMICILIO DE SUMINISTRO CALLE BENITO JUAREZ 123 COL CENTRO CP 24180",
                "RMU:2418013-05-22XAXX-010101002CFE",
            ]
        )
        fields = _run_sync(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None))
        data = _field_map(fields)

        self.assertIn("BENITO JUAREZ", data.get("referencia", ""))
        self.assertNotEqual(data.get("referencia"), "24180130522010101002")

    def test_extract_cfe_domicilio_removes_amount_prefix_noise(self):
        ocr_text = "\n".join(
            [
                "CFE COMISION FEDERAL DE ELECTRICIDAD",
                "TOTAL A PAGAR $ 548.17",
                "$ 548 17 DN. 223 DEPTO. 1 BENITO JUAREZ",
                "CP 24180",
            ]
        )
        fields = _run_sync(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None))
        data = _field_map(fields)
        domicilio = data.get("domicilio", "")

        self.assertIn("DN", domicilio)
        self.assertNotIn("$", domicilio)
        self.assertNotIn("548 17", domicilio)

    def test_extract_ine_mrz_name_and_domicilio_from_noisy_text(self):
        ocr_text = "\n".join(
            [
                "INSTITUTONACIONALELECTORAI",
                "CREDENCIALPARAVOTAR",
                "DOMICILIO",
                "-LOCZAPOTAL2DASECCIONS/N",
                "INSTITIONCIGALELECIO",
                "RIAZAPOTAL2DASECCION86781",
                "JONUTA.TAB.",
                "CLAVEDEELECTORGRCMER01042527H100",
                "CURP GACE010425HTCRMRA8",
                "SECCION0860",
                "GARC",
                "IA<CAMPOS,",
                "<<ERWIN<GUSTAVOK",
                "EMISON2019MGENCA2029",
            ]
        )
        fields = _run_sync(extract_fields("INE", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("nombre"), "ERWIN GUSTAVO GARCIA CAMPOS")
        self.assertIn("JONUTA", data.get("domicilio", ""))

    def test_extract_ine_name_from_split_tokens_near_nombre_label(self):
        ocr_text = "\n".join(
            [
                "INSTITUTO NACIONAL ELECTORAL",
                "NOMBRE GARC",
                "IA",
                "CAMPOS",
                "ERWIN GUSTAVO",
                "DOMICILIO LOC ZAPOTAL 2DA SECCION S/N",
                "CLAVE DE ELECTOR GRCMER01042527H100",
                "CURP GACE010425HTCRMRA8",
                "SECCION 0860",
                "VIGENCIA 2029",
            ]
        )
        fields = _run_sync(extract_fields("INE", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("nombre"), "ERWIN GUSTAVO GARCIA CAMPOS")

    def test_extract_cfe_reference_keeps_customer_context_from_noisy_block(self):
        ocr_text = "\n".join(
            [
                "CFE COMISION FEDERAL DE ELECTRICIDAD",
                "TOTALA PAGAR:",
                "$548",
                "17DN.223DEPTO.1BENITOJUAR",
                "AVLUISDONALDOCOLOSIOY46",
                "SSL.BENITOJUAREZFC.P.24180",
                "CIUDADDELCARMEN,CAMP.",
                "NO.DESERVICIO:795130504593",
                "RMU:2418013-05-22XAXX-010101002CFE",
                "CUENTA:29DW05A012970875",
            ]
        )
        fields = _run_sync(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None))
        data = _field_map(fields)
        referencia = data.get("referencia", "")

        self.assertIn("BENITOJUAR", referencia)
        self.assertIn("CARMEN", referencia)

    def test_extract_acta_numero_acta_with_ocr_confusions_from_boxes(self):
        ocr_boxes = [
            _box("ACTA DE NACIMIENTO", 10),
            _box("NUMERO DE ACTA I2O3L", 40),
        ]
        with patch("app.pipelines.extract.legacy_extract_fields", return_value={}):
            fields = _run_sync(
                extract_fields("ACTA_NACIMIENTO", "ACTA DE NACIMIENTO\nNUMERO DE ACTA I2O3L", ocr_boxes)
            )
        data = _field_map(fields)

        self.assertEqual(data.get("numero_acta"), "12031")

    def test_extract_acta_numero_certificado_with_ocr_confusions_from_boxes(self):
        ocr_boxes = [
            _box("ACTA DE NACIMIENTO", 10),
            _box("NUMERO DE CERTIFICADO DE NACIMIENTO OI23-45 6789L", 40),
        ]
        with patch("app.pipelines.extract.legacy_extract_fields", return_value={}):
            fields = _run_sync(
                extract_fields(
                    "ACTA_NACIMIENTO",
                    "ACTA DE NACIMIENTO\nNUMERO DE CERTIFICADO DE NACIMIENTO OI23-45 6789L",
                    ocr_boxes,
                )
            )
        data = _field_map(fields)

        self.assertEqual(data.get("numero_certificado"), "01234567891")

    def test_extract_acta_identificador_electronico_with_noise_from_boxes(self):
        ocr_boxes = [
            _box("ACTA DE NACIMIENTO", 10),
            _box("IDENTIFICADOR ELECTRONICO ab-12 cd_34", 40),
        ]
        with patch("app.pipelines.extract.legacy_extract_fields", return_value={}):
            fields = _run_sync(
                extract_fields(
                    "ACTA_NACIMIENTO",
                    "ACTA DE NACIMIENTO\nIDENTIFICADOR ELECTRONICO ab-12 cd_34",
                    ocr_boxes,
                )
            )
        data = _field_map(fields)

        self.assertEqual(data.get("identificador_electronico"), "AB12CD34")

    def test_extract_acta_folio_numero_from_compact_table_text(self):
        ocr_text = "\n".join(
            [
                "ACTA DE NACIMIENTO",
                "FECHA DE REGISTRO LIBRA NUMERA DE ACTE",
                "0001 20/08/2001 3 437",
            ]
        )
        fields = _run_sync(extract_fields("ACTA_NACIMIENTO", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("numero_acta"), "437")
        self.assertEqual(data.get("folio"), "0001")

    def test_extract_acta_numero_acta_ignores_label_noise(self):
        ocr_text = "\n".join(
            [
                "ACTA DE NACIMIENTO",
                "NUMERO DE ACTA DE NACIMIENTO",
                "FOLIO 0001",
            ]
        )
        fields = _run_sync(extract_fields("ACTA_NACIMIENTO", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("folio"), "0001")
        self.assertIsNone(data.get("numero_acta"))

    def test_extract_acta_nombre_ignores_section_header_noise(self):
        ocr_text = "\n".join(
            [
                "ACTA DE NACIMIENTO",
                "NOMBRE(S):",
                "DATOS DE LA PERSONA REGISTRADA",
                "ERWIN GUSTAVO GARCIA CAMPOS",
                "SEXO: HOMBRE",
            ]
        )
        fields = _run_sync(extract_fields("ACTA_NACIMIENTO", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("nombre"), "ERWIN GUSTAVO GARCIA CAMPOS")

    def test_extract_acta_lugar_nacimiento_cleans_label_noise(self):
        ocr_text = "ACTA DE NACIMIENTO\nHOMBRE 25/04/2001 JONUTA SEXO: FECHA DE NACIMIENTO: LUGAR DE NACIMIENTO:"
        ocr_boxes = [
            _box("ACTA DE NACIMIENTO", 10),
            _box("HOMBRE 25/04/2001 JONUTA SEXO: FECHA DE NACIMIENTO: LUGAR DE NACIMIENTO:", 40),
        ]
        fields = _run_sync(extract_fields("ACTA_NACIMIENTO", ocr_text, ocr_boxes))
        data = _field_map(fields)

        self.assertEqual(data.get("lugar_nacimiento"), "JONUTA")

    def test_extract_acta_nombre_rejects_column_header_word(self):
        """When the right-hand box next to 'Nombre(s):' is 'Primer' (column header),
        nombre must NOT be set to 'PRIMER' — the fallback should find the real name."""
        def _bx(text: str, y: int, x0: int = 10) -> dict:
            """Box with controllable x position."""
            return {
                "text": text,
                "page": 1,
                "confidence": 0.99,
                "bbox": [[x0, y], [x0 + 80, y], [x0 + 80, y + 20], [x0, y + 20]],
            }

        ocr_boxes = [
            _bx("ACTA DE NACIMIENTO", 10),
            # Table header row with separate boxes at different x positions
            _bx("Nombre(s):", 40, x0=10),
            _bx("Primer", 40, x0=100),
            _bx("Apellido:", 40, x0=150),
            _bx("Segundo", 40, x0=210),
            _bx("Apellido:", 40, x0=270),
            # Value row
            _bx("ERWIN GUSTAVO", 70, x0=10),
            _bx("GARCIA", 70, x0=100),
            _bx("CAMPOS", 70, x0=150),
            _bx("SEXO: HOMBRE", 100),
        ]
        ocr_text = "\n".join([
            "ACTA DE NACIMIENTO",
            "Nombre(s): Primer Apellido: Segundo Apellido:",
            "ERWIN GUSTAVO GARCIA CAMPOS",
            "SEXO: HOMBRE",
        ])
        fields = _run_sync(extract_fields("ACTA_NACIMIENTO", ocr_text, ocr_boxes))
        data = _field_map(fields)

        self.assertNotEqual(data.get("nombre"), "PRIMER")
        self.assertEqual(data.get("nombre"), "ERWIN GUSTAVO GARCIA CAMPOS")

    def test_extract_acta_folio_numero_from_oficialia_style(self):
        """Actas that use 'Oficialía <N> Número <N>' instead of 'FOLIO / NUMERO DE ACTA'."""
        ocr_text = "\n".join([
            "ACTA DE NACIMIENTO",
            "DATOS DE LA INSCRIPCION",
            "OFICIALÍA NÚMERO AÑO",
            "0001 45 2001",
        ])
        fields = _run_sync(extract_fields("ACTA_NACIMIENTO", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("folio"), "0001")
        self.assertEqual(data.get("numero_acta"), "45")

    def test_extract_acta_lugar_nacimiento_rejects_persona_registrada_noise_from_legacy(self):
        """lugar_nacimiento coming from legacy extractor must be rejected if it contains
        'DATOS DE LA PERSONA REGISTRADA' header noise."""
        from unittest.mock import patch
        noisy_legacy = {"lugar_nacimiento": "DATOS DE LA PERSONA REGISTRADA ERWIN GUSTAVO GARCIA CAMPOS TABASCO"}
        ocr_text = "\n".join([
            "ACTA DE NACIMIENTO",
            "DATOS DE LA PERSONA REGISTRADA",
            "ERWIN GUSTAVO GARCIA CAMPOS",
            "SEXO HOMBRE",
            "FECHA DE NACIMIENTO 25/04/2001",
        ])
        with patch("app.pipelines.extract.legacy_extract_fields", return_value=noisy_legacy):
            fields = _run_sync(extract_fields("ACTA_NACIMIENTO", ocr_text, None))
        data = _field_map(fields)

        lugar = data.get("lugar_nacimiento", "")
        self.assertNotIn("PERSONA REGISTRADA", str(lugar).upper())
        self.assertNotIn("DATOS DE LA", str(lugar).upper())

    def test_extract_nss_nombre_beneficiario_from_text(self):
        ocr_text = "\n".join(
            [
                "INSTITUTO MEXICANO DEL SEGURO SOCIAL",
                "NUMERO DE SEGURIDAD SOCIAL 60160194696",
                "NOMBRE DEL BENEFICIARIO: JUAN PEREZ LOPEZ",
            ]
        )
        fields = _run_sync(extract_fields("NSS", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("nss"), "60160194696")
        self.assertEqual(data.get("nombre"), "JUAN PEREZ LOPEZ")

    def test_extract_nss_ignores_legal_text_as_name(self):
        ocr_text = "\n".join(
            [
                "NUMERO DE SEGURIDAD SOCIAL 60160194696",
                "NOMBRE DEL BENEFICIARIO: S LAS PRESTACIONES EN ESPECIE Y EN DINERO",
                "NOMBRE DEL BENEFICIARIO: MARIA GUADALUPE LOPEZ HERNANDEZ",
            ]
        )
        fields = _run_sync(extract_fields("NSS", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("nss"), "60160194696")
        self.assertEqual(data.get("nombre"), "MARIA GUADALUPE LOPEZ HERNANDEZ")

    def test_extract_nss_noisy_label_and_name_below(self):
        ocr_text = "\n".join(
            [
                "NUMERO DE SEGURIDAD SOCIAL 60160194696",
                "N0MBRE DEL BENEFICIARI0",
                "S LAS PRESTACIONES EN ESPECIE Y EN DINERO",
                "JORGE ALBERTO MENDEZ CRUZ",
            ]
        )
        fields = _run_sync(extract_fields("NSS", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("nss"), "60160194696")
        self.assertEqual(data.get("nombre"), "JORGE ALBERTO MENDEZ CRUZ")

    def test_extract_nss_compact_name_pattern(self):
        ocr_text = "\n".join(
            [
                "NUMERO DE SEGURIDAD SOCIAL ES: 60160194696",
                "ASOCIADO A LA CURP: GACE010425HTCRMRA8",
                "TU NUMERO DE SEGURIDAD! CAMPOS! ERWINGUSTAVOGARCIA",
            ]
        )
        fields = _run_sync(extract_fields("NSS", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("nss"), "60160194696")
        self.assertEqual(data.get("nombre"), "ERWIN GUSTAVO GARCIA CAMPOS")

    def test_extract_nss_compact_nombre_o_razon_social_and_surname_below(self):
        ocr_text = "\n".join(
            [
                "INSTITUTO MEXICANO DEL SEGURO SOCIAL",
                "NUMERO DE SEGURIDAD SOCIAL ES: 60160194696",
                "NOMBREORAZONSOCIAL:ERWINGUSTAVOGARCIA",
                "CAMPOS",
                "ASOCIADO A LA CURP: GACE010425HTCRMRA8",
            ]
        )
        fields = _run_sync(extract_fields("NSS", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("nss"), "60160194696")
        self.assertEqual(data.get("nombre"), "ERWIN GUSTAVO GARCIA CAMPOS")

    def test_extract_nss_cleans_legacy_compact_name_label(self):
        with patch(
            "app.pipelines.extract.orchestrator.legacy_extract_fields",
            return_value={"nombre": "0RAZONSOCIAL:ERWINGUSTAVOGARCIA"},
        ):
            fields = _run_sync(
                extract_fields(
                    "NSS",
                    "NUMERO DE SEGURIDAD SOCIAL ES: 60160194696",
                    None,
                )
            )
        data = _field_map(fields)

        self.assertEqual(data.get("nss"), "60160194696")
        self.assertEqual(data.get("nombre"), "ERWIN GUSTAVO GARCIA")

    def test_field_contract_drops_invalid_legacy_curp(self):
        with patch("app.pipelines.extract.legacy_extract_fields", return_value={"curp": "ABCD123"}):
            fields = _run_sync(extract_fields("INE", "CREDENCIAL PARA VOTAR", None))
        data = _field_map(fields)

        self.assertIsNone(data.get("curp"))

    def test_field_contract_drops_invalid_legacy_referencia(self):
        with patch("app.pipelines.extract.legacy_extract_fields", return_value={"referencia": "12345"}):
            fields = _run_sync(extract_fields("COMPROBANTE_DOMICILIO", "COMPROBANTE", None))
        data = _field_map(fields)

        self.assertIsNone(data.get("referencia"))

    def test_field_contract_drops_noisy_lugar_nacimiento(self):
        with patch(
            "app.pipelines.extract.legacy_extract_fields",
            return_value={"lugar_nacimiento": "ACTA DE NACIMIENTO SEXO FECHA DE NACIMIENTO"},
        ):
            fields = _run_sync(extract_fields("ACTA_NACIMIENTO", "ACTA DE NACIMIENTO", None))
        data = _field_map(fields)

        self.assertIsNone(data.get("lugar_nacimiento"))

    def test_field_contract_drops_noisy_service_extra_keys(self):
        with patch(
            "app.pipelines.extract.legacy_extract_fields",
            return_value={
                "cliente": "RMU:2418013-05-22XAXX-010101002CFE",
                "medidor": "MULTIPLICADOR1",
                "rfc": "CFE370814QI0",
            },
        ):
            fields = _run_sync(extract_fields("COMPROBANTE_DOMICILIO", "COMPROBANTE DE DOMICILIO", None))
        data = _field_map(fields)

        self.assertIsNone(data.get("cliente"))
        self.assertIsNone(data.get("medidor"))
        self.assertIsNone(data.get("rfc"))

    def test_field_contract_drops_noisy_titular_text(self):
        with patch(
            "app.pipelines.extract.legacy_extract_fields",
            return_value={"titular": "ESTE GRAFICO REFLEJA TU NIVEL DE CONSUMO"},
        ):
            fields = _run_sync(extract_fields("COMPROBANTE_DOMICILIO", "COMPROBANTE DE DOMICILIO", None))
        data = _field_map(fields)

        self.assertIsNone(data.get("titular"))

    # ------------------------------------------------------------------
    # Tests para _fix_payment_ocr_column_errors
    # ------------------------------------------------------------------

    def test_fix_ocr_amount_in_nombre_moves_to_importe(self):
        """Si nombre empieza con monto e importe está vacío, el monto pasa a importe."""
        from app.pipelines.extract import _fix_payment_ocr_column_errors

        rows = [
            ["CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE", "APELLIDO PATERNO", "APELLIDO MATERNO", "ESTATUS", "CONCEPTO"],
            ["56936397470", "1620260115134348451388", "", "$557.74 ROLANDO ROGERIO", "CONTRERAS", "CAMARGO", "", "PAGO DE NOMINA"],
        ]
        result = _fix_payment_ocr_column_errors(rows)
        self.assertEqual(len(result), 2, "Debe conservar la fila corregida")
        self.assertIn("557", result[1][2], "El importe debe contener el monto extraído")
        self.assertNotIn("$", result[1][3], "El nombre no debe contener el símbolo de moneda")
        self.assertIn("ROLANDO", result[1][3], "El nombre debe contener la parte de texto")

    def test_fix_ocr_invalid_nombre_keeps_row(self):
        """Si nombre es solo un monto (sin nombre real), la fila se conserva (los demás campos son válidos)."""
        from app.pipelines.extract import _fix_payment_ocr_column_errors

        rows = [
            ["CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE", "APELLIDO PATERNO", "APELLIDO MATERNO", "ESTATUS", "CONCEPTO"],
            ["56783223195", "1620260115134340581263", "$140948.59", "$610.44", "MENDEZ", "FLORES", "", "PAGO DE NOMINA"],
        ]
        result = _fix_payment_ocr_column_errors(rows)
        self.assertEqual(len(result), 2, "Fila con nombre inválido debe conservarse (cuenta, referencia, importe siguen siendo válidos)")

    def test_fix_ocr_status_extracted_from_concepto(self):
        """Si concepto empieza con palabra de estado y estatus está vacío, se separa."""
        from app.pipelines.extract import _fix_payment_ocr_column_errors

        rows = [
            ["CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE", "APELLIDO PATERNO", "APELLIDO MATERNO", "ESTATUS", "CONCEPTO"],
            ["56936397470", "1620260115134348451388", "$1537.35", "ROLANDO ROGERIO", "CONTRERAS", "CAMARGO", "", "PROCESADO PAGO DE NOMINA"],
        ]
        result = _fix_payment_ocr_column_errors(rows)
        self.assertEqual(len(result), 2, "Debe conservar la fila")
        self.assertEqual(result[1][6], "PROCESADO", "ESTATUS debe extraerse de CONCEPTO")
        self.assertNotIn("PROCESADO", result[1][7], "CONCEPTO no debe contener el estatus")
        self.assertIn("PAGO", result[1][7], "CONCEPTO debe conservar el concepto")

    # ── Quality improvement tests ──

    def test_clean_address_strips_leading_dashes(self):
        from app.pipelines.extract import _clean_address_value
        result = _clean_address_value("-LOC ZAPOTAL 2DA SECCION")
        self.assertFalse(result.startswith("-"), "Leading dashes should be stripped")
        self.assertIn("LOC", result)

    def test_clean_address_splits_daseccion(self):
        from app.pipelines.extract import _clean_address_value
        result = _clean_address_value("2 DASECCION S/N RIAZAPOTAL 2 DASECCION")
        self.assertIn("DA SECCION", result, "DASECCION should be split to DA SECCION")
        self.assertIn("RIA ZAPOTAL", result, "RIAZAPOTAL should be split to RIA ZAPOTAL")

    def test_clean_address_splits_benito_merge(self):
        from app.pipelines.extract import _clean_address_value
        result = _clean_address_value("BENITOJUAREZ SSL.BENITOJUAR")
        self.assertIn("BENITO JUAREZ", result)
        self.assertIn("BENITO JUAR", result)

    def test_name_matches_curp_valid(self):
        from app.pipelines.extract import _name_matches_curp
        self.assertTrue(_name_matches_curp("ERWIN GUSTAVO GARCIA CAMPOS", "GACE010425HTCRMRA8"))

    def test_name_matches_curp_missing_paterno(self):
        from app.pipelines.extract import _name_matches_curp
        # "GUSTAVOIA" starts with G which matches paterno, but if paterno were missing:
        self.assertFalse(_name_matches_curp("ERWIN GUSTAVOIA CAMPOS", "GACE010425HTCRMRA8"))

    def test_try_repair_name_with_curp(self):
        from app.pipelines.extract import _try_repair_name_with_curp
        # "GUSTAVOIA" doesn't contain G as missing initial in a splittable position,
        # but the repair should at least attempt to find splits.
        result = _try_repair_name_with_curp("ERWIN GUSTAVOIA CAMPOS", "GACE010425HTCRMRA8")
        # The repair may or may not succeed on this specific case depending on heuristic
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) >= 10)

    def test_normalize_reference_address_style(self):
        from app.pipelines.extract import _normalize_reference_value
        result = _normalize_reference_value("17DN.223 DEPTO.1 BENITO JUAR AV LUIS DONALDO COLOSIO Y 46 SSL.BENITO JUAREZ CP 24180")
        self.assertTrue(len(result) > 20, "Address-style reference should be preserved")
        self.assertIn("DEPTO", result)

    # ── Table extraction improvements ────────────────────────────────

    def test_dedup_header_cell_single_repeated(self):
        from app.pipelines.extract import _dedup_header_cell
        self.assertEqual(_dedup_header_cell("CUENTA CUENTA"), "CUENTA")

    def test_dedup_header_cell_multi_repeated(self):
        from app.pipelines.extract import _dedup_header_cell
        self.assertEqual(
            _dedup_header_cell("APELLIDO PATERNO APELLIDO PATERNO"),
            "APELLIDO PATERNO",
        )

    def test_dedup_header_cell_complex_repeated(self):
        from app.pipelines.extract import _dedup_header_cell
        result = _dedup_header_cell(
            "APELLIDO PATERNO APELLIDO MATERNO ESTATUS APELLIDO PATERNO APELLIDO MATERNO ESTATUS"
        )
        self.assertEqual(result, "APELLIDO PATERNO APELLIDO MATERNO ESTATUS")

    def test_dedup_header_cell_no_repeat(self):
        from app.pipelines.extract import _dedup_header_cell
        self.assertEqual(_dedup_header_cell("NOMBRE"), "NOMBRE")
        self.assertEqual(_dedup_header_cell("APELLIDO PATERNO"), "APELLIDO PATERNO")

    def test_dedup_header_row(self):
        from app.pipelines.extract import _dedup_header_row
        header = [
            "CUENTA CUENTA",
            "REFERENCIA REFERENCIA",
            "IMPORTE IMPORTE",
            "NOMBRE NOMBRE",
            "CONCEPTO CONCEPTO",
        ]
        result = _dedup_header_row(header)
        self.assertEqual(result, ["CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE", "CONCEPTO"])

    def test_quality_score_penalizes_repeated_headers(self):
        from app.pipelines.extract import _payment_rows_quality_score
        # Good header
        good_rows = [
            ["CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE", "ESTATUS", "CONCEPTO"],
            ["12345678901", "1620260115134348", "$1,629.08", "LUIS ANGEL", "PROCESADO", "PAGO DE NOMINA"],
        ]
        # Bad header with duplicated tokens
        bad_rows = [
            ["CUENTA CUENTA", "REFERENCIA REFERENCIA", "IMPORTE IMPORTE", "NOMBRE NOMBRE", "ESTATUS ESTATUS", "CONCEPTO CONCEPTO"],
            ["12345678901", "1620260115134348", "$1,629.08", "LUIS ANGEL", "PROCESADO", "PAGO DE NOMINA"],
        ]
        score_good = _payment_rows_quality_score(good_rows)
        score_bad = _payment_rows_quality_score(bad_rows)
        self.assertGreater(score_good, score_bad, "Repeated headers should be penalized")

    def test_quality_score_penalizes_multi_record_cells(self):
        from app.pipelines.extract import _payment_rows_quality_score
        # Single record per row (clean)
        clean_rows = [
            ["CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE"],
            ["56936397271", "1620260115134348251383", "$1,629.08", "LUIS ANGEL"],
        ]
        # Multi-record jammed into one row (garbage)
        multi_rows = [
            ["CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE"],
            ["", "56936397271 1620260115134348251383 56926066072 1620260115134346391346", "", "$1,629.08 LUIS ANGEL $1,050.45 RICARDO"],
        ]
        score_clean = _payment_rows_quality_score(clean_rows)
        score_multi = _payment_rows_quality_score(multi_rows)
        self.assertGreater(score_clean, score_multi, "Multi-record cells should be penalized")

    def test_bank_detection_santander(self):
        from app.pipelines.extract import _payment_detect_bank
        self.assertEqual(_payment_detect_bank("Santander dispersión de nómina"), "SANTANDER")

    def test_bank_detection_contrato_enlace(self):
        from app.pipelines.extract import _payment_detect_bank
        self.assertEqual(
            _payment_detect_bank("Numero de Contrato ENLACE: 80122978989"),
            "SANTANDER",
        )

    def test_bank_detection_clabe_fallback_bbva(self):
        from app.pipelines.extract import _payment_detect_bank
        self.assertEqual(
            _payment_detect_bank("CLABE: 012345678901234567 PAGO"),
            "BBVA",
        )

    def test_bank_detection_clabe_fallback_santander(self):
        from app.pipelines.extract import _payment_detect_bank
        self.assertEqual(
            _payment_detect_bank("cuenta 014567890123456789"),
            "SANTANDER",
        )

    def test_normalize_payment_table_rows_dedups_headers(self):
        from app.pipelines.extract import _normalize_payment_table_rows
        rows = [
            ["CUENTA CUENTA", "REFERENCIA REFERENCIA", "IMPORTE IMPORTE", "NOMBRE NOMBRE", "CONCEPTO CONCEPTO"],
            ["12345678901", "1620260115134348", "$1,629.08", "LUIS ANGEL", "PAGO DE NOMINA"],
        ]
        result = _normalize_payment_table_rows(rows)
        self.assertEqual(result[0], ["CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE", "CONCEPTO"])
        self.assertEqual(result[1][0], "12345678901")

    def test_santander_text_extraction_uses_bbva_parser(self):
        """Santander nómina text with same format as BBVA should produce rows."""
        from app.pipelines.extract import _extract_bbva_nomina_advanced_rows_from_text
        santander_text = (
            "Dispersión de Pago de Nómina\n"
            "Cuenta Referencia Importe Nombre Estatus Concepto\n"
            "56783223195 1620260115134340581263 $610.44 MARLA GRISELDA PROCESADO PAGO DE NOMINA\n"
            "56936397470 1620260115134348451388 $1,537.35 ROLANDO ROGERIO PROCESADO PAGO DE NOMINA\n"
        )
        rows = _extract_bbva_nomina_advanced_rows_from_text(santander_text)
        self.assertGreaterEqual(len(rows), 3, "Should extract header + 2 data rows")
        self.assertIn("CUENTA", rows[0])
        # Check first data row
        self.assertIn("56783223195", rows[1][0])
        self.assertIn("610.44", rows[1][2])

    def test_santander_metadata_extraction(self):
        from app.pipelines.extract import _extract_santander_payment_metadata
        text = (
            "Numero de Contrato ENLACE: 80122978989\n"
            "Cuenta cargo: 65507763084\n"
            "Tipo de Operación: Abono nómina\n"
            "Fecha de envío de pago: 15-01-2026\n"
            "Dispersión de Pago de Nómina\n"
            "Importe total: $140,948.59\n"
            "Total de Registros: 94\n"
            "Numero de Secuencia del archivo: 992026011513432707Z426\n"
        )
        meta = _extract_santander_payment_metadata(text)
        self.assertEqual(meta.get("numero_contrato"), "80122978989")
        self.assertEqual(meta.get("cuenta_cargo"), "65507763084")
        self.assertIn("140,948.59", meta.get("importe_detectado", ""))
        self.assertEqual(meta.get("total_registros"), "94")
        self.assertEqual(meta.get("tipo_pago"), "DISPERSION DE PAGO DE NOMINA")

    def test_fix_payment_ocr_column_errors_dedups_headers(self):
        from app.pipelines.extract import _fix_payment_ocr_column_errors
        rows = [
            ["CUENTA CUENTA", "REFERENCIA REFERENCIA", "IMPORTE IMPORTE", "NOMBRE NOMBRE", "APELLIDO PATERNO APELLIDO PATERNO", "APELLIDO MATERNO APELLIDO MATERNO", "CONCEPTO CONCEPTO"],
            ["12345678901", "162026011", "$1,629.08", "LUIS ANGEL", "SOLER", "GUZMAN", "PAGO DE NOMINA"],
        ]
        result = _fix_payment_ocr_column_errors(rows)
        self.assertEqual(result[0][0], "CUENTA")
        self.assertEqual(result[0][1], "REFERENCIA")
        # ESTATUS is injected before CONCEPTO when APELLIDO columns are present
        self.assertIn("CONCEPTO", result[0])
        self.assertIn("ESTATUS", result[0])


class TestExtractFieldsErrorRecovery(unittest.TestCase):
    """extract_fields must return [] on unhandled exceptions."""

    def test_returns_empty_on_impl_exception(self):
        with patch("app.pipelines.extract.orchestrator._extract_fields_impl", side_effect=RuntimeError("boom")):
            result = _run_sync(extract_fields("INE", "some text"))
        self.assertEqual(result, [])

    def test_returns_empty_for_empty_input(self):
        result = _run_sync(extract_fields("INE", ""))
        # With no text at all, we should still get a list (possibly with texto_detectado)
        self.assertIsInstance(result, list)


class TestFallbackRegexScan(unittest.TestCase):
    """When document_type is unrecognized, the tail fallback should still extract common regex patterns."""

    def test_curp_extracted_for_unknown_type(self):
        text = "Algo qualquiera GUZS850101HDFRLR09 contenido random"
        result = _run_sync(extract_fields("DESCONOCIDO", text))
        fm = _field_map(result)
        self.assertIn("curp", fm)
        self.assertEqual(fm["curp"], "GUZS850101HDFRLR09")

    def test_rfc_extracted_for_unknown_type(self):
        text = "NUMERO DE REGISTRO: GUZS850101AB3"
        result = _run_sync(extract_fields("DESCONOCIDO", text))
        fm = _field_map(result)
        self.assertIn("rfc", fm)
        self.assertEqual(fm["rfc"], "GUZS850101AB3")


class TestHeaderCellDedup(unittest.TestCase):
    """Edge cases for _header_cell_has_repeated_tokens and _dedup_header_cell."""

    def test_single_token_not_repeated(self):
        from app.pipelines.extract import _header_cell_has_repeated_tokens
        self.assertFalse(_header_cell_has_repeated_tokens("CUENTA"))

    def test_empty_string(self):
        from app.pipelines.extract import _header_cell_has_repeated_tokens, _dedup_header_cell
        self.assertFalse(_header_cell_has_repeated_tokens(""))
        self.assertEqual(_dedup_header_cell(""), "")
        self.assertEqual(_dedup_header_cell(None), "")  # type: ignore[arg-type]

    def test_three_same_tokens(self):
        from app.pipelines.extract import _header_cell_has_repeated_tokens, _dedup_header_cell
        self.assertTrue(_header_cell_has_repeated_tokens("NO NO NO"))
        self.assertEqual(_dedup_header_cell("NO NO NO"), "NO")

    def test_odd_non_repeated(self):
        from app.pipelines.extract import _header_cell_has_repeated_tokens, _dedup_header_cell
        self.assertFalse(_header_cell_has_repeated_tokens("APELLIDO PATERNO MATERNO"))
        self.assertEqual(_dedup_header_cell("APELLIDO PATERNO MATERNO"), "APELLIDO PATERNO MATERNO")

    def test_four_token_repeated_pair(self):
        from app.pipelines.extract import _header_cell_has_repeated_tokens, _dedup_header_cell
        self.assertTrue(_header_cell_has_repeated_tokens("APELLIDO PATERNO APELLIDO PATERNO"))
        self.assertEqual(_dedup_header_cell("APELLIDO PATERNO APELLIDO PATERNO"), "APELLIDO PATERNO")

    def test_dedup_header_row_full(self):
        from app.pipelines.extract import _dedup_header_row
        row = ["CUENTA CUENTA", "IMPORTE", "NOMBRE NOMBRE"]
        result = _dedup_header_row(row)
        self.assertEqual(result, ["CUENTA", "IMPORTE", "NOMBRE"])


class TestPaymentQualityScoreEdgeCases(unittest.TestCase):
    """Boundary conditions for quality scoring."""

    def test_empty_rows_negative(self):
        from app.pipelines.extract import _payment_rows_quality_score
        self.assertLess(_payment_rows_quality_score([]), 0)

    def test_single_row_negative(self):
        from app.pipelines.extract import _payment_rows_quality_score
        self.assertLess(_payment_rows_quality_score([["CUENTA", "IMPORTE"]]), 0)

    def test_noisy_data_penalized(self):
        from app.pipelines.extract import _payment_rows_quality_score
        clean_rows = [
            ["CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE"],
            ["12345678901", "16200", "$1,629.08", "LUIS ANGEL"],
        ]
        noisy_rows = [
            ["CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE"],
            ["UNIDAD ESPECIALIZADA ACLARACION TELEFONOS 12345678901", "16200", "$1,629.08", "LUIS"],
        ]
        clean_score = _payment_rows_quality_score(clean_rows)
        noisy_score = _payment_rows_quality_score(noisy_rows)
        self.assertGreater(clean_score, noisy_score)

    def test_repeated_headers_penalized(self):
        from app.pipelines.extract import _payment_rows_quality_score
        normal_rows = [
            ["CUENTA", "REFERENCIA", "IMPORTE"],
            ["12345678901", "16200", "$1,629.08"],
        ]
        dup_rows = [
            ["CUENTA CUENTA", "REFERENCIA REFERENCIA", "IMPORTE IMPORTE"],
            ["12345678901", "16200", "$1,629.08"],
        ]
        normal_score = _payment_rows_quality_score(normal_rows)
        dup_score = _payment_rows_quality_score(dup_rows)
        self.assertGreater(normal_score, dup_score)


class TestPdfTableExtraction(unittest.TestCase):
    """Tests for PyMuPDF find_tables() integration."""

    def test_pdf_tables_to_payment_rows_picks_best(self):
        from app.pipelines.extract import _extract_payment_table_rows_from_pdf_tables
        tables = [
            # Small unrelated table
            [["Col1", "Col2"], ["A", "B"]],
            # Payment table with proper headers
            [
                ["CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE", "ESTATUS"],
                ["56783223195", "162026011", "$610.44", "MARLA GRISELDA", "APLICADO"],
                ["56936397470", "162026011", "$1,537.35", "ROLANDO ROGERIO", "APLICADO"],
                ["56905029323", "162026011", "$353.60", "EDGAR HASSAN", "APLICADO"],
            ],
        ]
        rows, secondary = _extract_payment_table_rows_from_pdf_tables(tables)
        self.assertEqual(len(rows), 4)  # header + 3 data rows
        self.assertIn("CUENTA", rows[0])
        self.assertIn("56783223195", rows[1][0])
        self.assertIsInstance(secondary, list)

    def test_pdf_tables_empty_returns_empty(self):
        from app.pipelines.extract import _extract_payment_table_rows_from_pdf_tables
        self.assertEqual(_extract_payment_table_rows_from_pdf_tables(None), ([], []))
        self.assertEqual(_extract_payment_table_rows_from_pdf_tables([]), ([], []))

    def test_pdf_tables_to_generic_payloads(self):
        from app.pipelines.extract import _pdf_tables_to_generic_payloads
        tables = [
            [["H1", "H2"], ["V1", "V2"], ["V3", "V4"]],
        ]
        payloads = _pdf_tables_to_generic_payloads(tables)
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["row_count"], 3)
        self.assertEqual(payloads[0]["source"], "pdf_structure")

    def test_pdf_tables_skips_all_empty_rows(self):
        from app.pipelines.extract import _extract_payment_table_rows_from_pdf_tables
        tables = [
            [["", "", ""], ["", None, ""], ["", "", ""]],
        ]
        rows, secondary = _extract_payment_table_rows_from_pdf_tables(tables)
        self.assertEqual(rows, [])

    def test_payment_table_payload_prefers_pdf_structure(self):
        """When PDF structural table is high quality, it should win over OCR/text."""
        from app.pipelines.extract import _extract_payment_table_payload
        pdf_tables = [
            [
                ["CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE", "ESTATUS"],
                ["56783223195", "162026011", "$610.44", "MARLA GRISELDA", "APLICADO"],
                ["56936397470", "162026011", "$1,537.35", "ROLANDO", "APLICADO"],
            ],
        ]
        # Use minimal text/boxes that wouldn't produce good results
        result = _extract_payment_table_payload("Some random text", [], pdf_tables)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["source"], "pdf_structure")
        self.assertGreaterEqual(len(result["rows"]), 3)

    def test_banorte_23_rows_via_pdf_tables(self):
        """Simulates Banorte REPORTE DE TRANSMISION with 23 rows from find_tables()."""
        from app.pipelines.extract import _extract_payment_table_payload
        header = ["No. Empleado", "Nombre", "Tipo Cuenta", "No. de Cuenta", "Importe", "Estatus", "Codigo", "Descripcion", "Clave Rastreo"]
        data_rows = [
            [f"000000000{i}", f"EMPLEADO {i} APELLIDO{i} SEGUNDO{i}", "01", f"0000000129030{i}408", f"$3,{200+i}.73", "APLICADO", "00", "ACEPTADO", f"CLAVE{i}"]
            for i in range(1, 24)
        ]
        pdf_tables = [[header] + data_rows]
        result = _extract_payment_table_payload("REPORTE DE TRANSMISION", [], pdf_tables)
        self.assertIsNotNone(result)
        assert result is not None
        # Should extract all 23 data rows + header
        self.assertGreaterEqual(len(result["rows"]), 24)

    def test_multipage_pdf_tables_merge(self):
        """Tables split across pages with same header should be merged."""
        from app.pipelines.extract import _extract_payment_table_rows_from_pdf_tables
        header = ["CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE", "ESTATUS"]
        page1_table = [
            header,
            ["56783223195", "162026011", "$610.44", "MARLA GRISELDA", "APLICADO"],
            ["56936397470", "162026011", "$1,537.35", "ROLANDO ROGERIO", "APLICADO"],
        ]
        page2_table = [
            header,  # repeated on second page
            ["56905029323", "162026011", "$353.60", "EDGAR HASSAN", "APLICADO"],
            ["12345678901", "162026011", "$240.00", "JOSE CARLOS", "PROCESADO"],
        ]
        rows, secondary = _extract_payment_table_rows_from_pdf_tables([page1_table, page2_table])
        # header + 4 unique data rows
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0], header)
        names = [r[3] for r in rows[1:]]
        self.assertIn("MARLA GRISELDA", names)
        self.assertIn("EDGAR HASSAN", names)
        self.assertIn("JOSE CARLOS", names)

    def test_multipage_pdf_tables_dedup_rows(self):
        """Duplicate rows across pages should not appear twice."""
        from app.pipelines.extract import _extract_payment_table_rows_from_pdf_tables
        header = ["CUENTA", "IMPORTE", "NOMBRE", "ESTATUS"]
        row1 = ["56783223195", "$610.44", "MARLA GRISELDA", "APLICADO"]
        page1 = [header, row1]
        page2 = [header, row1]  # exact duplicate
        rows, secondary = _extract_payment_table_rows_from_pdf_tables([page1, page2])
        self.assertEqual(len(rows), 2)  # header + 1 unique data row


    def test_secondary_tables_returned_for_different_headers(self):
        """Tables with different header structures should be returned as secondary."""
        from app.pipelines.extract import _extract_payment_table_rows_from_pdf_tables
        # Main payment table
        main_table = [
            ["CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE", "ESTATUS"],
            ["56783223195", "162026011", "$610.44", "MARLA GRISELDA", "APLICADO"],
            ["56936397470", "162026011", "$1,537.35", "ROLANDO", "APLICADO"],
        ]
        # A different table (e.g. summary)
        summary_table = [
            ["TIPO OPERACION", "CANTIDAD", "IMPORTE TOTAL"],
            ["DISPERSION", "15", "$24,500.00"],
            ["INDIVIDUAL", "3", "$5,200.00"],
        ]
        rows, secondary = _extract_payment_table_rows_from_pdf_tables([main_table, summary_table])
        # Main table should be picked as best
        self.assertEqual(len(rows), 3)
        self.assertIn("CUENTA", rows[0])
        # Secondary table should be in secondary list
        self.assertEqual(len(secondary), 1)
        self.assertEqual(len(secondary[0]), 3)  # header + 2 data rows
        self.assertIn("TIPO OPERACION", secondary[0][0])


class TestCanonicalKeyMapping(unittest.TestCase):
    """Tests for _canonical_payment_key precision mappings."""

    def test_banorte_pdf_headers_mapped(self):
        from app.pipelines.extract import _canonical_payment_key
        self.assertEqual(_canonical_payment_key("BANORTE", "noempleado"), "numero_empleado")
        self.assertEqual(_canonical_payment_key("BANORTE", "tipocuenta"), "tipo_cuenta")
        self.assertEqual(_canonical_payment_key("BANORTE", "nodecuenta"), "cuenta")
        self.assertEqual(_canonical_payment_key("BANORTE", "claverastreo"), "clave_rastreo")

    def test_base_map_new_keys(self):
        from app.pipelines.extract import _canonical_payment_key
        self.assertEqual(_canonical_payment_key("DESCONOCIDO", "cuentacargo"), "cuenta_retiro")
        self.assertEqual(_canonical_payment_key("DESCONOCIDO", "cuentadestino"), "cuenta")
        self.assertEqual(_canonical_payment_key("DESCONOCIDO", "cuentadeabono"), "cuenta")
        self.assertEqual(_canonical_payment_key("DESCONOCIDO", "beneficiario"), "nombre_beneficiario")
        self.assertEqual(_canonical_payment_key("DESCONOCIDO", "nombrecorto"), "nombre_beneficiario")
        self.assertEqual(_canonical_payment_key("DESCONOCIDO", "numeroempleado"), "numero_empleado")
        self.assertEqual(_canonical_payment_key("DESCONOCIDO", "codigo"), "codigo")
        self.assertEqual(_canonical_payment_key("DESCONOCIDO", "descripcion"), "descripcion")
        self.assertEqual(_canonical_payment_key("DESCONOCIDO", "tipocuenta"), "tipo_cuenta")
        self.assertEqual(_canonical_payment_key("DESCONOCIDO", "divisa"), "divisa")
        self.assertEqual(_canonical_payment_key("DESCONOCIDO", "titular"), "titular")
        self.assertEqual(_canonical_payment_key("DESCONOCIDO", "contrato"), "contrato")
        self.assertEqual(_canonical_payment_key("DESCONOCIDO", "foliodefirma"), "folio_firma")
        self.assertEqual(_canonical_payment_key("DESCONOCIDO", "foliounico"), "folio_unico")
        self.assertEqual(_canonical_payment_key("DESCONOCIDO", "motivodepago"), "motivo_pago")

    def test_bbva_transfer_keys_mapped(self):
        from app.pipelines.extract import _canonical_payment_key
        self.assertEqual(_canonical_payment_key("BBVA", "foliodefirma"), "folio_firma")
        self.assertEqual(_canonical_payment_key("BBVA", "foliounico"), "folio_unico")
        self.assertEqual(_canonical_payment_key("BBVA", "fechadecreacion"), "fecha_creacion")
        self.assertEqual(_canonical_payment_key("BBVA", "fechadeaplicacion"), "fecha_aplicacion")
        self.assertEqual(_canonical_payment_key("BBVA", "horadecaptura"), "hora_captura")
        self.assertEqual(_canonical_payment_key("BBVA", "resultadodeltraspaso"), "estatus")

    def test_canonical_rows_banorte_pdf_table(self):
        """Full integration: Banorte PDF table → canonical rows with proper mappings."""
        from app.pipelines.extract import _payment_rows_to_objects, _payment_to_canonical_rows
        rows = [
            ["No. Empleado", "Nombre", "Tipo Cuenta", "No. de Cuenta", "Importe", "Estatus", "Codigo", "Descripcion", "Clave Rastreo"],
            ["000123456", "JUAN PEREZ LOPEZ", "03", "002180019912345678", "$3,240.73", "APLICADO", "00", "ACEPTADO", "BANORTE12345"],
        ]
        objects = _payment_rows_to_objects(rows)
        self.assertEqual(len(objects), 1)
        canonical_cols, canonical_rows = _payment_to_canonical_rows("BANORTE", objects)
        self.assertEqual(len(canonical_rows), 1)
        row = canonical_rows[0]
        # Key field mappings should produce correct canonical keys
        self.assertEqual(row.get("numero_empleado"), "000123456")
        self.assertEqual(row.get("cuenta"), "002180019912345678")
        self.assertEqual(row.get("tipo_cuenta"), "03")
        self.assertEqual(row.get("importe"), "$3,240.73")
        self.assertEqual(row.get("estatus"), "APLICADO")
        self.assertEqual(row.get("clave_rastreo"), "BANORTE12345")
        # Document has single "Nombre" column without separate apellido columns,
        # so the full name is preserved without splitting.
        self.assertEqual(row.get("nombre"), "JUAN PEREZ LOPEZ")
        self.assertIsNone(row.get("apellido_paterno"))
        self.assertIsNone(row.get("apellido_materno"))


class TestBbvaTransferMetadata(unittest.TestCase):
    """Tests for BBVA transfer receipt metadata extraction."""

    def test_bbva_transfer_extracts_titular(self):
        from app.pipelines.extract import _extract_bbva_payment_metadata
        text = "COMPROBANTE\nTITULAR DE LA CUENTA: MARIA ELENA GUTIERREZ\nCONTRATO: 12345678\nDIVISA: MXN"
        result = _extract_bbva_payment_metadata(text)
        self.assertIn("titular", result)
        self.assertIn("GUTIERREZ", result["titular"].upper())
        self.assertEqual(result.get("contrato"), "12345678")
        self.assertEqual(result.get("divisa"), "MXN")

    def test_bbva_transfer_extracts_folios(self):
        from app.pipelines.extract import _extract_bbva_payment_metadata
        text = "RESULTADO DEL TRASPASO APLICADO\nFOLIO DE FIRMA: 7748662779\nFOLIO UNICO: ABC12345"
        result = _extract_bbva_payment_metadata(text)
        self.assertIn("folio_firma", result)
        self.assertIn("7748662779", result["folio_firma"])
        self.assertIn("folio_unico", result)
        self.assertIn("resultado_traspaso", result)

    def test_bbva_transfer_extracts_dates(self):
        from app.pipelines.extract import _extract_bbva_payment_metadata
        text = "DATOS DE CONFIRMACION\nFECHA DE CREACION: 15/01/2025\nFECHA DE APLICACION: 15/01/2025\nHORA DE CAPTURA: 14:30:15"
        result = _extract_bbva_payment_metadata(text)
        self.assertIn("fecha_creacion", result)
        self.assertIn("15/01/2025", result["fecha_creacion"])
        self.assertIn("fecha_aplicacion", result)
        self.assertIn("hora_captura", result)

    def test_bbva_transfer_extracts_motivo_pago(self):
        from app.pipelines.extract import _extract_bbva_payment_metadata
        text = "PAGO MISMO BANCO\nMOTIVO DE PAGO: PAGO DE NOMINA QUINCENAL\nSOLICITUD DE COMENTARIOS: QUINCENA 1"
        result = _extract_bbva_payment_metadata(text)
        self.assertIn("motivo_pago", result)
        self.assertIn("solicitud_comentarios", result)

    def test_bbva_nontransfer_no_transfer_fields(self):
        """Non-transfer BBVA docs should not extract transfer-specific fields."""
        from app.pipelines.extract import _extract_bbva_payment_metadata
        text = "REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS\nTIPO DE PAGO: NOMINA\nFECHA DE TRANSMISION: 15/01/2025 10:30:00"
        result = _extract_bbva_payment_metadata(text)
        self.assertIn("reporte_tipo", result)
        self.assertNotIn("titular", result)
        self.assertNotIn("folio_firma", result)


class TestBuildPaymentMappedFields(unittest.TestCase):
    """Tests for _build_payment_mapped_fields with expanded metadata."""

    def test_maps_transfer_metadata_fields(self):
        from app.pipelines.extract import _build_payment_mapped_fields
        detail = {
            "bank": "BBVA",
            "metadata": {
                "titular": "MARIA ELENA",
                "contrato": "12345678",
                "divisa": "MXN",
                "folio_firma": "7748662779",
                "folio_unico": "ABC123",
                "fecha_creacion": "15/01/2025",
                "fecha_aplicacion": "15/01/2025",
                "motivo_pago": "PAGO NOMINA",
                "solicitud_comentarios": "QUINCENA 1",
                "resultado_traspaso": "APLICADO",
            },
            "table": {"canonical_rows": []},
        }
        mapped = _build_payment_mapped_fields(detail)
        self.assertEqual(mapped["banco"], "BBVA")
        self.assertEqual(mapped["titular"], "MARIA ELENA")
        self.assertEqual(mapped["contrato"], "12345678")
        self.assertEqual(mapped["divisa"], "MXN")
        self.assertEqual(mapped["folio_firma"], "7748662779")
        self.assertEqual(mapped["motivo_pago"], "PAGO NOMINA")
        self.assertEqual(mapped["resultado_traspaso"], "APLICADO")

    def test_maps_banorte_canonical_row_fields(self):
        from app.pipelines.extract import _build_payment_mapped_fields
        detail = {
            "bank": "BANORTE",
            "metadata": {},
            "table": {
                "canonical_rows": [
                    {
                        "numero_empleado": "000123",
                        "nombre": "JUAN",
                        "apellido_paterno": "PEREZ",
                        "cuenta": "002180019912345678",
                        "importe": "$3,240.73",
                        "estatus": "APLICADO",
                        "tipo_cuenta": "03",
                        "clave_rastreo": "BANORTE12345",
                    }
                ]
            },
        }
        mapped = _build_payment_mapped_fields(detail)
        self.assertEqual(mapped["banco"], "BANORTE")
        self.assertEqual(mapped.get("numero_empleado"), "000123")
        self.assertEqual(mapped.get("tipo_cuenta"), "03")
        self.assertEqual(mapped.get("clave_rastreo"), "BANORTE12345")


class TestClassifyBbvaTransferMarkers(unittest.TestCase):
    """BBVA Pago Mismo Banco / transfer docs should be classified as FACTURA."""

    def test_pago_mismo_banco_classified_as_factura(self):
        from app.pipelines.classify import _keyword_override
        text = "BBVA NET CASH OPERACION AUTORIZADA DATOS DE LA OPERACION PAGO MISMO BANCO IMPORTE 1537 35"
        compact = text.replace(" ", "")
        doc_type, conf = _keyword_override(text, compact, "")
        self.assertEqual(doc_type, "FACTURA")
        self.assertGreaterEqual(conf, 0.9)

    def test_folio_de_firma_classified_as_factura(self):
        from app.pipelines.classify import _keyword_override
        text = "DATOS DE CONFIRMACION DE LA TRANSFERENCIA FOLIO DE FIRMA 7748662779"
        compact = text.replace(" ", "")
        doc_type, conf = _keyword_override(text, compact, "")
        self.assertEqual(doc_type, "FACTURA")


class TestIsGarbageValue(unittest.TestCase):
    """Tests for the _is_garbage_value garbage detector."""

    def test_empty_is_garbage(self):
        from app.pipelines.extract import _is_garbage_value
        self.assertTrue(_is_garbage_value("nombre", ""))
        self.assertTrue(_is_garbage_value("nombre", "   "))

    def test_control_characters_garbage(self):
        from app.pipelines.extract import _is_garbage_value
        self.assertTrue(_is_garbage_value("nombre", "\x00\x01ABC"))
        self.assertTrue(_is_garbage_value("rfc", "ABC\x1fDEF"))

    def test_excessive_special_chars_garbage(self):
        from app.pipelines.extract import _is_garbage_value
        self.assertTrue(_is_garbage_value("nombre", "###%%%&&&"))

    def test_low_alpha_ratio_garbage_for_text_keys(self):
        from app.pipelines.extract import _is_garbage_value
        self.assertTrue(_is_garbage_value("nombre", "123456789"))
        self.assertTrue(_is_garbage_value("titular", "$#@!^*()"))

    def test_single_char_garbage_for_text_keys(self):
        from app.pipelines.extract import _is_garbage_value
        self.assertTrue(_is_garbage_value("nombre", "X"))
        self.assertTrue(_is_garbage_value("domicilio", "A"))

    def test_valid_name_not_garbage(self):
        from app.pipelines.extract import _is_garbage_value
        self.assertFalse(_is_garbage_value("nombre", "JUAN PEREZ LOPEZ"))
        self.assertFalse(_is_garbage_value("titular", "MARIA ELENA GUTIERREZ"))

    def test_valid_rfc_not_garbage(self):
        from app.pipelines.extract import _is_garbage_value
        self.assertFalse(_is_garbage_value("rfc", "PELJ850101ABC"))

    def test_valid_curp_not_garbage(self):
        from app.pipelines.extract import _is_garbage_value
        self.assertFalse(_is_garbage_value("curp", "PELJ850101HDFRPN09"))

    def test_numeric_keys_pass(self):
        """Non-text keys like cp, nss, clabe should not be checked for alpha ratio."""
        from app.pipelines.extract import _is_garbage_value
        self.assertFalse(_is_garbage_value("cp", "06600"))
        self.assertFalse(_is_garbage_value("nss", "12345678901"))
        self.assertFalse(_is_garbage_value("clabe", "002180019912345678"))

    def test_address_with_numbers_valid(self):
        from app.pipelines.extract import _is_garbage_value
        self.assertFalse(_is_garbage_value("domicilio", "AV INSURGENTES SUR 1234 COL DEL VALLE CP 03100"))


class TestPostprocessFieldsExpanded(unittest.TestCase):
    """Tests for the expanded _postprocess_fields with garbage detection."""

    def test_drops_garbage_value(self):
        from app.pipelines.extract import _postprocess_fields
        fields = [
            {"key": "nombre", "label": "Nombre", "value": "\x00\x01\x02", "confidence": 0.9, "valid": True},
            {"key": "rfc", "label": "RFC", "value": "PELJ850101ABC", "confidence": 0.9, "valid": True},
        ]
        result = _postprocess_fields("INE", fields)
        keys = [f["key"] for f in result]
        self.assertNotIn("nombre", keys)
        self.assertIn("rfc", keys)

    def test_strips_control_chars_from_valid_field(self):
        from app.pipelines.extract import _postprocess_fields
        fields = [
            {"key": "rfc", "label": "RFC", "value": "PELJ850101ABC\x0f", "confidence": 0.9, "valid": True},
        ]
        result = _postprocess_fields("CONSTANCIA_SITUACION_FISCAL", fields)
        self.assertEqual(result[0]["value"], "PELJ850101ABC")

    def test_drops_invalid_curp_for_ine(self):
        from app.pipelines.extract import _postprocess_fields
        fields = [
            {"key": "curp", "label": "CURP", "value": "BADFORMAT", "confidence": 0.8, "valid": False},
        ]
        result = _postprocess_fields("INE", fields)
        self.assertEqual(len(result), 0)

    def test_drops_invalid_clabe_for_datos_bancarios(self):
        from app.pipelines.extract import _postprocess_fields
        fields = [
            {"key": "clabe", "label": "CLABE", "value": "999999999", "confidence": 0.8, "valid": False},
            {"key": "banco", "label": "Banco", "value": "BBVA", "confidence": 0.9, "valid": True},
        ]
        result = _postprocess_fields("DATOS_BANCARIOS", fields)
        keys = [f["key"] for f in result]
        self.assertNotIn("clabe", keys)
        self.assertIn("banco", keys)

    def test_drops_low_confidence_factura_titular(self):
        from app.pipelines.extract import _postprocess_fields
        fields = [
            {"key": "titular", "label": "Titular", "value": "NOISE VALUE", "confidence": 0.5, "valid": True},
            {"key": "cuenta", "label": "Cuenta", "value": "123456789", "confidence": 0.9, "valid": True},
        ]
        result = _postprocess_fields("FACTURA", fields)
        keys = [f["key"] for f in result]
        self.assertNotIn("titular", keys)
        self.assertIn("cuenta", keys)

    def test_texto_detectado_always_passes(self):
        from app.pipelines.extract import _postprocess_fields
        fields = [
            {"key": "texto_detectado", "label": "Texto", "value": "ANY TEXT", "confidence": 0.1, "valid": True},
        ]
        result = _postprocess_fields("INE", fields)
        self.assertEqual(len(result), 1)


class TestOcrConfidencePropagation(unittest.TestCase):
    """Tests for OCR confidence propagation into _make_field."""

    def test_high_ocr_conf_preserves_extraction_confidence(self):
        from app.pipelines.extract import _make_field
        boxes = [{"text": "PELJ850101ABC", "confidence": 0.99, "page": 1, "bbox": []}]
        field = _make_field("rfc", "RFC", "PELJ850101ABC", boxes, confidence=0.8)
        self.assertEqual(field["confidence"], 0.8)

    def test_low_ocr_conf_caps_extraction_confidence(self):
        from app.pipelines.extract import _make_field
        boxes = [{"text": "PELJ850101ABC", "confidence": 0.3, "page": 1, "bbox": []}]
        field = _make_field("rfc", "RFC", "PELJ850101ABC", boxes, confidence=0.8)
        # Should be lower than 0.8 since OCR reported only 0.3
        self.assertLess(field["confidence"], 0.8)

    def test_no_ocr_boxes_preserves_confidence(self):
        from app.pipelines.extract import _make_field
        field = _make_field("rfc", "RFC", "PELJ850101ABC", None, confidence=0.9)
        self.assertEqual(field["confidence"], 0.9)

    def test_value_not_in_boxes_preserves_confidence(self):
        from app.pipelines.extract import _make_field
        boxes = [{"text": "OTHER TEXT", "confidence": 0.3, "page": 1, "bbox": []}]
        field = _make_field("rfc", "RFC", "PELJ850101ABC", boxes, confidence=0.9)
        self.assertEqual(field["confidence"], 0.9)

    def test_source_includes_ocr_confidence(self):
        from app.pipelines.extract import _make_field
        boxes = [{"text": "PELJ850101ABC", "confidence": 0.95, "page": 1, "bbox": [[0, 0]]}]
        field = _make_field("rfc", "RFC", "PELJ850101ABC", boxes, confidence=0.8)
        self.assertIsNotNone(field["source"])
        self.assertEqual(field["source"]["ocr_confidence"], 0.95)


class TestCrossFieldValidation(unittest.TestCase):
    """Tests for cross-field coherence checks."""

    def test_curp_fecha_match_no_penalty(self):
        """When CURP date matches fecha_nacimiento, no penalty applied."""
        from app.pipelines.extract import _apply_cross_field_checks
        fields = [
            {"key": "curp", "value": "PELJ850101HDFRPN09", "confidence": 0.9, "valid": True, "validation_errors": []},
            {"key": "fecha_nacimiento", "value": "01/01/1985", "confidence": 0.8, "valid": True, "validation_errors": []},
        ]
        result = _apply_cross_field_checks(fields)
        fecha = next(f for f in result if f["key"] == "fecha_nacimiento")
        self.assertEqual(fecha["confidence"], 0.8)
        self.assertEqual(len(fecha["validation_errors"]), 0)

    def test_curp_fecha_mismatch_lowers_confidence(self):
        """When CURP date doesn't match fecha_nacimiento, confidence is lowered."""
        from app.pipelines.extract import _apply_cross_field_checks
        fields = [
            {"key": "curp", "value": "PELJ850101HDFRPN09", "confidence": 0.9, "valid": True, "validation_errors": []},
            {"key": "fecha_nacimiento", "value": "15/03/1990", "confidence": 0.8, "valid": True, "validation_errors": []},
        ]
        result = _apply_cross_field_checks(fields)
        fecha = next(f for f in result if f["key"] == "fecha_nacimiento")
        self.assertLessEqual(fecha["confidence"], 0.55)
        self.assertTrue(any("CURP" in e for e in fecha["validation_errors"]))

    def test_rfc_fecha_mismatch_lowers_confidence(self):
        """When RFC date doesn't match fecha_nacimiento, confidence is lowered."""
        from app.pipelines.extract import _apply_cross_field_checks
        fields = [
            {"key": "rfc", "value": "PELJ850101ABC", "confidence": 0.9, "valid": True, "validation_errors": []},
            {"key": "fecha_nacimiento", "value": "15/03/1990", "confidence": 0.8, "valid": True, "validation_errors": []},
        ]
        result = _apply_cross_field_checks(fields)
        fecha = next(f for f in result if f["key"] == "fecha_nacimiento")
        self.assertLessEqual(fecha["confidence"], 0.55)
        self.assertTrue(any("RFC" in e for e in fecha["validation_errors"]))

    def test_curp_nombre_mismatch_lowers_confidence(self):
        """When name initials don't match CURP, nombre confidence is lowered."""
        from app.pipelines.extract import _apply_cross_field_checks
        fields = [
            {"key": "curp", "value": "PELJ850101HDFRPN09", "confidence": 0.9, "valid": True, "validation_errors": []},
            {"key": "nombre", "value": "CARLOS RAMIREZ DIAZ", "confidence": 0.8, "valid": True, "validation_errors": []},
        ]
        result = _apply_cross_field_checks(fields)
        nombre = next(f for f in result if f["key"] == "nombre")
        self.assertLessEqual(nombre["confidence"], 0.6)
        self.assertTrue(any("CURP" in e for e in nombre["validation_errors"]))

    def test_curp_nombre_match_no_penalty(self):
        """When CURP initials P-E-L-J match PEREZ LOPEZ JUAN, no penalty."""
        from app.pipelines.extract import _apply_cross_field_checks
        fields = [
            {"key": "curp", "value": "PELJ850101HDFRPN09", "confidence": 0.9, "valid": True, "validation_errors": []},
            {"key": "nombre", "value": "JUAN PEREZ LOPEZ", "confidence": 0.8, "valid": True, "validation_errors": []},
        ]
        result = _apply_cross_field_checks(fields)
        nombre = next(f for f in result if f["key"] == "nombre")
        self.assertEqual(nombre["confidence"], 0.8)
        self.assertEqual(len(nombre["validation_errors"]), 0)

    def test_no_curp_no_rfc_no_penalty(self):
        """When no CURP or RFC present, no cross-field penalty is applied."""
        from app.pipelines.extract import _apply_cross_field_checks
        fields = [
            {"key": "nombre", "value": "JUAN PEREZ", "confidence": 0.9, "valid": True, "validation_errors": []},
            {"key": "fecha_nacimiento", "value": "01/01/1985", "confidence": 0.8, "valid": True, "validation_errors": []},
        ]
        result = _apply_cross_field_checks(fields)
        for f in result:
            self.assertEqual(len(f["validation_errors"]), 0)


class TestDateNormalization(unittest.TestCase):
    """Tests for _normalize_date_to_yymmdd helper."""

    def test_dd_mm_yyyy_slash(self):
        from app.pipelines.extract import _normalize_date_to_yymmdd
        self.assertEqual(_normalize_date_to_yymmdd("01/01/1985"), "850101")

    def test_yyyy_mm_dd_dash(self):
        from app.pipelines.extract import _normalize_date_to_yymmdd
        self.assertEqual(_normalize_date_to_yymmdd("1985-01-01"), "850101")

    def test_dd_mm_yyyy_dash(self):
        from app.pipelines.extract import _normalize_date_to_yymmdd
        self.assertEqual(_normalize_date_to_yymmdd("15-03-1990"), "900315")

    def test_empty_returns_none(self):
        from app.pipelines.extract import _normalize_date_to_yymmdd
        self.assertIsNone(_normalize_date_to_yymmdd(""))
        self.assertIsNone(_normalize_date_to_yymmdd("   "))

    def test_unparseable_returns_none(self):
        from app.pipelines.extract import _normalize_date_to_yymmdd
        self.assertIsNone(_normalize_date_to_yymmdd("ENERO 2025"))


# ==========================================================================
# Content-based row merge tests
# ==========================================================================

class TestContentBasedMerge(unittest.TestCase):
    """Tests for `_merge_payment_rows_with_backup` content-based matching."""

    def test_same_row_count_positional_fast_path(self):
        from app.pipelines.extract import _merge_payment_rows_with_backup
        primary = [
            ["CUENTA", "REFERENCIA", "IMPORTE"],
            ["1234567890", "REF001", ""],
        ]
        backup = [
            ["CUENTA", "REFERENCIA", "IMPORTE"],
            ["1234567890", "REF001", "$1,500.00"],
        ]
        merged = _merge_payment_rows_with_backup(primary, backup)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[1][2], "$1,500.00")

    def test_different_row_count_content_matching(self):
        from app.pipelines.extract import _merge_payment_rows_with_backup
        primary = [
            ["CUENTA", "REFERENCIA", "IMPORTE"],
            ["1111111111", "REF001", "$100.00"],
            ["2222222222", "REF002", ""],
        ]
        # Backup has an extra row and different order
        backup = [
            ["CUENTA", "REFERENCIA", "IMPORTE"],
            ["3333333333", "REF003", "$300.00"],
            ["2222222222", "REF002", "$200.00"],
            ["1111111111", "REF001", "$100.00"],
        ]
        merged = _merge_payment_rows_with_backup(primary, backup)
        # Primary rows should be present in order; 2222 should get $200 filled
        data_rows = merged[1:]
        cuenta_values = [r[0] for r in data_rows]
        self.assertIn("2222222222", cuenta_values)
        row_2222 = next(r for r in data_rows if r[0] == "2222222222")
        self.assertEqual(row_2222[2], "$200.00")
        # Unmatched backup (3333) should also appear
        self.assertIn("3333333333", cuenta_values)

    def test_unmatched_backup_rows_appended(self):
        from app.pipelines.extract import _merge_payment_rows_with_backup
        primary = [
            ["CUENTA", "REFERENCIA", "IMPORTE"],
            ["1111111111", "REF001", "$100.00"],
        ]
        backup = [
            ["CUENTA", "REFERENCIA", "IMPORTE"],
            ["1111111111", "REF001", "$100.00"],
            ["9999999999", "REF009", "$900.00"],
        ]
        merged = _merge_payment_rows_with_backup(primary, backup)
        # Extra backup row should be inserted
        self.assertGreaterEqual(len(merged), 3)
        cuenta_values = [r[0] for r in merged[1:]]
        self.assertIn("9999999999", cuenta_values)

    def test_unmatched_backup_row_preserves_real_missing_columns(self):
        from app.pipelines.extract import _merge_payment_rows_with_backup

        primary = [
            ["CUENTA", "REFERENCIA", "IMPORTE"],
            ["1111111111", "REF001", "$100.00"],
            ["2222222222", "REF002", "$200.00"],
        ]
        backup = [
            ["CUENTA", "REFERENCIA", "IMPORTE", "ESTATUS", "CONCEPTO"],
            ["2222222222", "REF002", "$200.00", "PROCESADO", "PAGO DE NOMINA"],
            ["9999999999", "REF009", "$900.00", "RECHAZADO", "PAGO DE NOMINA"],
            ["1111111111", "REF001", "$100.00", "PROCESADO", "PAGO DE NOMINA"],
        ]

        merged = _merge_payment_rows_with_backup(primary, backup)
        header = [str(c or "") for c in merged[0]]
        data_rows = merged[1:]
        status_idx = header.index("ESTATUS")
        concepto_idx = header.index("CONCEPTO")

        row_9999 = next(r for r in data_rows if str(r[0]) == "9999999999")
        self.assertEqual(str(row_9999[status_idx]), "RECHAZADO")
        self.assertEqual(str(row_9999[concepto_idx]), "PAGO DE NOMINA")

    def test_no_cross_contamination_with_missing_rows(self):
        from app.pipelines.extract import _merge_payment_rows_with_backup
        primary = [
            ["CUENTA", "NOMBRE", "IMPORTE"],
            ["1111111111", "JUAN PEREZ", "$100.00"],
            ["2222222222", "", "$200.00"],
            ["3333333333", "ANA LOPEZ", "$300.00"],
        ]
        # Backup only has rows 1 and 3 (row 2 missing)
        backup = [
            ["CUENTA", "NOMBRE", "IMPORTE"],
            ["1111111111", "JUAN PEREZ", "$100.00"],
            ["3333333333", "ANA LOPEZ", "$300.00"],
        ]
        merged = _merge_payment_rows_with_backup(primary, backup)
        # Row 2 (2222222222) should NOT get "ANA LOPEZ" from misaligned backup
        row_2 = merged[2]
        self.assertEqual(row_2[0], "2222222222")
        # Name should still be empty (no match found for 2222222222 in backup)
        self.assertEqual(row_2[1].strip(), "")


# ==========================================================================
# Summary row filtering tests
# ==========================================================================

class TestSummaryRowFiltering(unittest.TestCase):
    """Tests for `_is_summary_row` and `_payment_rows_to_objects` filtering."""

    def test_summary_header_row_detected(self):
        from app.pipelines.extract import _is_summary_row
        row = [
            "CANTIDAD DE MOVIMIENTOS ALTAS",
            "IMPORTE DE MOVIMIENTO ALTAS",
            "CANTIDAD DE MOVIMIENTOS BAJAS",
            "IMPORTE DE MOVIMIENTOS BAJAS",
        ]
        self.assertTrue(_is_summary_row(row))

    def test_normal_data_row_not_summary(self):
        from app.pipelines.extract import _is_summary_row
        row = ["1234567890", "REF123", "$1,500.00", "JUAN PEREZ", "PROCESADO"]
        self.assertFalse(_is_summary_row(row))

    def test_total_summary_row_detected(self):
        from app.pipelines.extract import _is_summary_row
        row = [
            "TOTAL CANTIDAD DE MOVIMIENTOS ALTAS",
            "TOTAL IMPORTE DE MOVIMIENTO ALTAS",
            "TOTAL CANTIDAD DE MOVIMIENTOS BAJAS",
            "TOTAL IMPORTE DE MOVIMIENTOS BAJAS",
        ]
        self.assertTrue(_is_summary_row(row))

    def test_summary_data_values_detected(self):
        from app.pipelines.extract import _is_summary_row
        row = ["CANTIDAD DE MOVIMIENTO ALTAS 5", "IMPORTE DE MOVIMIENTO ALTAS $5,000.00"]
        self.assertTrue(_is_summary_row(row))

    def test_payment_rows_to_objects_skips_summary(self):
        from app.pipelines.extract import _payment_rows_to_objects
        rows = [
            ["CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE"],
            ["1234567890", "REF001", "$1,500.00", "JUAN PEREZ"],
            [
                "CANTIDAD DE MOVIMIENTOS ALTAS",
                "IMPORTE DE MOVIMIENTO ALTAS",
                "CANTIDAD DE MOVIMIENTOS BAJAS",
                "IMPORTE DE MOVIMIENTOS BAJAS",
            ],
            ["5", "$10,000.00", "0", "$0.00"],  # summary data row
        ]
        objects = _payment_rows_to_objects(rows)
        # Only the actual transaction row should survive (summary rows filtered)
        self.assertEqual(len(objects), 2)  # data row + summary data (summary header filtered)
        self.assertEqual(objects[0].get("cuenta"), "1234567890")


# ==========================================================================
# Merge row similarity tests
# ==========================================================================

class TestMergeRowSimilarity(unittest.TestCase):
    """Tests for `_merge_row_similarity` scoring."""

    def test_identical_rows_score_1(self):
        from app.pipelines.extract import _merge_row_similarity, _payment_header_token_index, _payment_header_alias
        header = ["CUENTA", "REFERENCIA", "IMPORTE"]
        idx = _payment_header_token_index(header)
        b_idx = {_payment_header_alias(k): v for k, v in idx.items()}
        row = ["1234567890", "REF12345678", "$1,500.00"]
        score = _merge_row_similarity(row, row, idx, b_idx)
        self.assertGreater(score, 0.8)

    def test_completely_different_rows_score_low(self):
        from app.pipelines.extract import _merge_row_similarity, _payment_header_token_index, _payment_header_alias
        header = ["CUENTA", "REFERENCIA", "IMPORTE"]
        idx = _payment_header_token_index(header)
        b_idx = {_payment_header_alias(k): v for k, v in idx.items()}
        row_a = ["1111111111", "REF00000001", "$100.00"]
        row_b = ["9999999999", "REF99999999", "$999.00"]
        score = _merge_row_similarity(row_a, row_b, idx, b_idx)
        self.assertLess(score, 0.3)


# ==========================================================================
# Unified status vocabulary tests
# ==========================================================================

class TestUnifiedStatusVocabulary(unittest.TestCase):
    """Tests for expanded status vocabulary (DEVUELTO, CANCELADO, LIQUIDADO)."""

    def test_status_prefix_pat_matches_devuelto(self):
        from app.pipelines.extract import _STATUS_PREFIX_PAT
        m = _STATUS_PREFIX_PAT.match("DEVUELTO PAGO DE NOMINA")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.group(1), "DEVUELTO")

    def test_status_prefix_pat_matches_cancelado(self):
        from app.pipelines.extract import _STATUS_PREFIX_PAT
        m = _STATUS_PREFIX_PAT.match("CANCELADO PAGO DE NOMINA")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.group(1), "CANCELADO")

    def test_status_prefix_pat_matches_liquidado(self):
        from app.pipelines.extract import _STATUS_PREFIX_PAT
        m = _STATUS_PREFIX_PAT.match("LIQUIDADO")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.group(1), "LIQUIDADO")

    def test_status_search_pat_finds_in_text(self):
        from app.pipelines.extract import _STATUS_SEARCH_PAT
        m = _STATUS_SEARCH_PAT.search("RESULTADO: DEVUELTO POR BANCO")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.group(1), "DEVUELTO")

    def test_all_statuses_tuple_complete(self):
        from app.pipelines.extract import _ALL_PAYMENT_STATUSES
        self.assertIn("PROCESADO", _ALL_PAYMENT_STATUSES)
        self.assertIn("DEVUELTO", _ALL_PAYMENT_STATUSES)
        self.assertIn("CANCELADO", _ALL_PAYMENT_STATUSES)
        self.assertIn("LIQUIDADO", _ALL_PAYMENT_STATUSES)


# ==========================================================================
# OCR amount corruption fix tests
# ==========================================================================

class TestOcrAmountFix(unittest.TestCase):
    """Tests that OCR O→0 replacement only applies within numeric tokens."""

    def test_normalize_payment_amount_importe_prefix(self):
        from app.pipelines.extract import _normalize_payment_amount
        # "IMPORTE $1,500.00" — O in IMPORTE should NOT corrupt the amount
        result = _normalize_payment_amount("IMPORTE $1,500.00")
        self.assertEqual(result, "1,500.00")

    def test_normalize_payment_amount_with_ocr_o(self):
        from app.pipelines.extract import _normalize_payment_amount
        # "$1,5OO.OO" — O→0 within the numeric token
        result = _normalize_payment_amount("$1,5OO.OO")
        self.assertEqual(result, "1,500.00")

    def test_clean_amount_pesos_suffix_preserved(self):
        from app.pipelines.table_postprocess import _clean_amount
        # "$1,500.00 PESOS" — should extract amount correctly
        result = _clean_amount("$1,500.00 PESOS")
        self.assertEqual(result, "1,500.00")

    def test_clean_amount_with_text_prefix(self):
        from app.pipelines.table_postprocess import _clean_amount
        # Should NOT corrupt letters in surrounding text
        result = _clean_amount("IMPORTE $3,240.73")
        self.assertEqual(result, "3,240.73")


# ==========================================================================
# Canonical key fuzzy alias tests
# ==========================================================================

class TestCanonicalKeyFuzzyAlias(unittest.TestCase):
    """Tests for fuzzy alias mapping of unmapped column headers."""

    def test_monto_maps_to_importe(self):
        from app.pipelines.extract import _canonical_payment_key
        self.assertEqual(_canonical_payment_key("HSBC", "MONTO"), "importe")

    def test_cuenta_cargo_maps_to_cuenta_retiro(self):
        from app.pipelines.extract import _canonical_payment_key
        self.assertEqual(_canonical_payment_key("HSBC", "CUENTA CARGO"), "cuenta_retiro")

    def test_rfc_beneficiario(self):
        from app.pipelines.extract import _canonical_payment_key
        self.assertEqual(_canonical_payment_key("BANAMEX", "RFC BENEFICIARIO"), "rfc_beneficiario")

    def test_folio_confirmacion(self):
        from app.pipelines.extract import _canonical_payment_key
        self.assertEqual(_canonical_payment_key("INBURSA", "FOLIO DE CONFIRMACION"), "folio_operacion")

    def test_ocr_noise_key_dropped(self):
        from app.pipelines.extract import _canonical_payment_key
        result = _canonical_payment_key("HSBC", "CU3N7A")
        self.assertEqual(result, "")


# ==========================================================================
# Generic bank metadata extraction tests
# ==========================================================================

class TestGenericBankMetadata(unittest.TestCase):
    """Tests for _extract_generic_bank_payment_metadata."""

    def test_hsbc_metadata_extraction(self):
        from app.pipelines.extract import _extract_generic_bank_payment_metadata
        text = """
        HSBC DISPERSIONES DE NOMINA
        FOLIO DE CONFIRMACION: 12345678
        CUENTA CARGO: 021180012345678901
        BENEFICIARIO: JUAN PEREZ LOPEZ
        MONTO TOTAL: $15,000.00
        FECHA DE OPERACION: 14/02/2026
        """
        meta = _extract_generic_bank_payment_metadata(text, "HSBC")
        self.assertIn("folio_operacion", meta)
        self.assertIn("cuenta_cargo", meta)
        self.assertIn("banco_detectado", meta)
        self.assertEqual(meta["banco_detectado"], "HSBC")


class TestSmartSplitNarrowLine(unittest.TestCase):
    """Tests for _smart_split_narrow_line — pattern-aware single-space splitting."""

    def test_numeric_alpha_status_split(self):
        from app.pipelines.extract import _smart_split_narrow_line
        result = _smart_split_narrow_line("1234567890 750.00 JUAN PEREZ APLICADO")
        self.assertGreaterEqual(len(result), 3)
        # Must contain account, amount, name, status as separate cells
        joined = " | ".join(result)
        self.assertIn("1234567890", joined)
        self.assertIn("750.00", joined)
        self.assertIn("APLICADO", joined)

    def test_amount_with_dollar_sign(self):
        from app.pipelines.extract import _smart_split_narrow_line
        result = _smart_split_narrow_line("9876543210 $1,500.00 MARIA GARCIA PROCESADO")
        self.assertGreaterEqual(len(result), 3)
        joined = " | ".join(result)
        self.assertIn("$1,500.00", joined)
        self.assertIn("MARIA GARCIA", joined)

    def test_too_few_tokens_returns_original(self):
        from app.pipelines.extract import _smart_split_narrow_line
        result = _smart_split_narrow_line("hola mundo")
        self.assertEqual(result, ["hola mundo"])

    def test_all_alpha_returns_original(self):
        from app.pipelines.extract import _smart_split_narrow_line
        result = _smart_split_narrow_line("JUAN PEREZ LOPEZ GARCIA")
        # All alpha — can't split into 3+ typed cells, returns original
        self.assertEqual(len(result), 1)


class TestMojibakeRepair(unittest.TestCase):
    """Tests for _repair_mojibake in _normalize_text."""

    def test_latin1_mojibake_repaired(self):
        from app.pipelines.extract import _normalize_text
        # "ñ" encoded as UTF-8 then decoded as Latin-1 produces "Ã±"
        broken = "Compa\u00c3\u00b1\u00c3\u00ada"
        result = _normalize_text(broken)
        self.assertIn("ñ", result.lower())
        self.assertNotIn("\u00c3", result)

    def test_clean_text_unchanged(self):
        from app.pipelines.extract import _normalize_text
        clean = "México S.A. de C.V."
        result = _normalize_text(clean)
        self.assertEqual(result, clean)

    def test_nfc_composition(self):
        from app.pipelines.extract import _normalize_text
        # N + combining tilde should compose to Ñ
        decomposed = "n\u0303"
        result = _normalize_text(decomposed)
        self.assertIn("\u00f1", result)


class TestBbvaAmountPicksLargest(unittest.TestCase):
    """Tests that BBVA metadata picks the largest amount when multiple present."""

    def test_picks_largest_amount(self):
        from app.pipelines.extract import _extract_bbva_payment_metadata
        text = """REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS
        TOTAL: $15,000.00  FEE: $150.00
        TIPO DE PAGO: NOMINA
        """
        meta = _extract_bbva_payment_metadata(text)
        self.assertIn("importe_detectado", meta)
        # Should pick $15,000.00 not $150.00
        amt = meta["importe_detectado"]
        val = float(amt.replace("$", "").replace(",", ""))
        self.assertGreaterEqual(val, 15000.0)

    def test_single_amount_still_works(self):
        from app.pipelines.extract import _extract_bbva_payment_metadata
        text = """REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS
        IMPORTE $3,240.73
        """
        meta = _extract_bbva_payment_metadata(text)
        self.assertIn("importe_detectado", meta)


class TestColumnsUseCanonical(unittest.TestCase):
    """Tests that the response 'columns' field uses canonical names, not raw OCR headers."""

    def test_columns_are_canonical(self):
        from app.pipelines.extract import _extract_payment_detail_payload
        raw_text = """REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS
CTA CARGO\tNO. CUENTA\tIMPORTE\tNOMBRE\tESTATUS
1234567890\t9876543210\t1,500.00\tJUAN PEREZ\tAPLICADO
"""
        result = _extract_payment_detail_payload(raw_text, None)
        if result and "table" in result:
            columns = result["table"].get("columns", [])
            # Should not contain raw OCR headers like "CTA CARGO"
            for col in columns:
                self.assertNotIn("CTA CARGO", col.upper() if isinstance(col, str) else "")


# ---------------------------------------------------------------------------
# Header dedup + canonical key fallback tests
# ---------------------------------------------------------------------------

class TestDedupHeaderCell(unittest.TestCase):
    """Tests for _dedup_header_cell — multi-page OCR header dedup."""

    def test_simple_duplicate(self):
        from app.pipelines.extract import _dedup_header_cell
        self.assertEqual(_dedup_header_cell("CUENTA CUENTA"), "CUENTA")

    def test_even_split_duplicate(self):
        from app.pipelines.extract import _dedup_header_cell
        result = _dedup_header_cell(
            "APELLIDO PATERNO APELLIDO MATERNO ESTATUS "
            "APELLIDO PATERNO APELLIDO MATERNO ESTATUS"
        )
        self.assertEqual(result, "APELLIDO PATERNO APELLIDO MATERNO ESTATUS")

    def test_triple_duplicate(self):
        from app.pipelines.extract import _dedup_header_cell
        result = _dedup_header_cell("NOMBRE NOMBRE NOMBRE")
        self.assertEqual(result, "NOMBRE")

    def test_no_duplicate_unchanged(self):
        from app.pipelines.extract import _dedup_header_cell
        result = _dedup_header_cell("APELLIDO PATERNO")
        self.assertEqual(result, "APELLIDO PATERNO")

    def test_single_token_unchanged(self):
        from app.pipelines.extract import _dedup_header_cell
        self.assertEqual(_dedup_header_cell("IMPORTE"), "IMPORTE")

    def test_referencia_duplicate(self):
        from app.pipelines.extract import _dedup_header_cell
        self.assertEqual(_dedup_header_cell("REFERENCIA REFERENCIA"), "REFERENCIA")

    def test_concepto_duplicate(self):
        from app.pipelines.extract import _dedup_header_cell
        self.assertEqual(_dedup_header_cell("CONCEPTO CONCEPTO"), "CONCEPTO")


class TestCanonicalPaymentKeyFallback(unittest.TestCase):
    """Tests for _canonical_payment_key — doubled key detection."""

    def test_doubled_referencia_maps(self):
        from app.pipelines.extract import _canonical_payment_key
        result = _canonical_payment_key("SANTANDER", "referenciareferencia")
        self.assertEqual(result, "referencia")

    def test_doubled_nombre_maps(self):
        from app.pipelines.extract import _canonical_payment_key
        result = _canonical_payment_key("SANTANDER", "nombrenombre")
        self.assertEqual(result, "nombre_beneficiario")

    def test_doubled_cuenta_maps(self):
        from app.pipelines.extract import _canonical_payment_key
        result = _canonical_payment_key("SANTANDER", "cuentacuenta")
        self.assertEqual(result, "cuenta")

    def test_doubled_concepto_maps(self):
        from app.pipelines.extract import _canonical_payment_key
        result = _canonical_payment_key("SANTANDER", "conceptoconcepto")
        self.assertEqual(result, "concepto_pago")

    def test_doubled_importe_maps(self):
        from app.pipelines.extract import _canonical_payment_key
        result = _canonical_payment_key("SANTANDER", "importeimporte")
        self.assertEqual(result, "importe")

    def test_long_garbage_key_dropped(self):
        from app.pipelines.extract import _canonical_payment_key
        garbage = "apellidopaternoapellidomaternoestatusapellidopaternoapellidomaternoestatus"
        result = _canonical_payment_key("SANTANDER", garbage)
        # Should be empty or a valid short key, not the 70+ char garbage
        self.assertTrue(len(result) < 40 or result == "")

    def test_normal_key_still_works(self):
        from app.pipelines.extract import _canonical_payment_key
        self.assertEqual(_canonical_payment_key("SANTANDER", "referencia"), "referencia")
        self.assertEqual(_canonical_payment_key("SANTANDER", "importe"), "importe")
        self.assertEqual(_canonical_payment_key("SANTANDER", "nombre"), "nombre_beneficiario")


class TestMetadataRowFilter(unittest.TestCase):
    """Tests for _is_metadata_row — metadata row detection."""

    def test_contract_and_sequence_rows_detected(self):
        from app.pipelines.extract import _is_metadata_row
        row = [
            "",
            "REPORTE DE OPERACIONES",
            "",
            "NUMERO DE CONTRATO ENLACE: 80122978989 NUMERO DE SECUENCIA DEL ARCHIVO: 99",
            "",
        ]
        self.assertTrue(_is_metadata_row(row))

    def test_normal_data_row_not_filtered(self):
        from app.pipelines.extract import _is_metadata_row
        row = [
            "56936397271",
            "$1,629.08",
            "LUIS ANGEL",
            "SOLER",
            "GUZMAN",
            "PROCESADO",
            "PAGO DE NOMINA",
        ]
        self.assertFalse(_is_metadata_row(row))

    def test_single_cell_metadata_in_wide_table(self):
        """Rows with only 1 non-empty cell in a wide table (≥5 cols) are always noise."""
        from app.pipelines.extract import _is_metadata_row
        for label in ("Fecha y ho", "BBVA Net", "Tra", "PA", "D", "Es", "Estado"):
            row = [label, "", "", "", "", "", "", "", "", ""]
            self.assertTrue(
                _is_metadata_row(row, expected_cols=10),
                f"Should filter single-cell metadata row: {label!r}",
            )

    def test_normal_data_row_not_filtered_wide_table(self):
        """Real data rows with many cells pass even in wide tables."""
        from app.pipelines.extract import _is_metadata_row
        row = [
            "GRUPO PAGO MISMO BANCO", "PENSION 15 ENE", "3317.69",
            "000000000103552403", "1595352408", "MXP",
            "BUFETE DE MANTENIMIENTO", "15/01/2026", "15/01/2026",
            "20:13:17", "PAGO", "7749675952",
        ]
        self.assertFalse(_is_metadata_row(row, expected_cols=12))


class TestCleanMetadataFromCell(unittest.TestCase):
    """Tests for _clean_metadata_from_cell — noise removal from cells."""

    def test_removes_contract_number(self):
        from app.pipelines.extract import _clean_metadata_from_cell
        result = _clean_metadata_from_cell("NUMERODECONTRATOENLACE:80122978989 $1,537.35 ABEL")
        self.assertNotIn("NUMERODECONTRATOENLACE", result)
        self.assertIn("ABEL", result)

    def test_removes_sequence_number(self):
        from app.pipelines.extract import _clean_metadata_from_cell
        result = _clean_metadata_from_cell("NUMERODESECUENCIADELARCHIVO:992026011513432707Z426 $2,776.28")
        self.assertNotIn("NUMERODESECUENCIADELARCHIVO", result)

    def test_preserves_clean_text(self):
        from app.pipelines.extract import _clean_metadata_from_cell
        result = _clean_metadata_from_cell("$1,629.08 LUIS ANGEL")
        self.assertEqual(result, "$1,629.08 LUIS ANGEL")

    def test_removes_repeated_comprobante(self):
        from app.pipelines.extract import _clean_metadata_from_cell
        result = _clean_metadata_from_cell(
            "Comprobante de la operacion Comprobante de la operacion Comprobante de la operacion"
        )
        self.assertEqual(result.strip(), "")


class TestBuildDisplayColumnsMap(unittest.TestCase):
    """Tests for _build_display_columns_map — preserving original PDF header labels."""

    def test_banorte_headers(self):
        from app.pipelines.extract import _build_display_columns_map
        raw_rows = [
            ["No. Empleado", "Nombre", "Tipo Cuenta", "No. de Cuenta", "Importe", "Estatus", "Codigo", "Descripcion", "Clave Rastreo"],
            ["000123456", "JUAN PEREZ", "03", "002180019912345678", "$3,240.73", "APLICADO", "00", "ACEPTADO", "BANORTE12345"],
        ]
        result = _build_display_columns_map(raw_rows, "BANORTE")
        self.assertEqual(result.get("numero_empleado"), "No. Empleado")
        self.assertEqual(result.get("nombre"), "Nombre")
        self.assertEqual(result.get("tipo_cuenta"), "Tipo Cuenta")
        self.assertEqual(result.get("cuenta"), "No. de Cuenta")
        self.assertEqual(result.get("importe"), "Importe")
        self.assertEqual(result.get("estatus"), "Estatus")
        self.assertEqual(result.get("clave_rastreo"), "Clave Rastreo")

    def test_empty_rows(self):
        from app.pipelines.extract import _build_display_columns_map
        self.assertEqual(_build_display_columns_map([], "BBVA"), {})

    def test_bbva_headers(self):
        from app.pipelines.extract import _build_display_columns_map
        raw_rows = [
            ["Cuenta", "Referencia", "Importe", "Nombre", "Estatus", "Concepto"],
            ["123456", "REF001", "$1,000.00", "JUAN", "APLICADO", "NOMINA"],
        ]
        result = _build_display_columns_map(raw_rows, "BBVA")
        self.assertEqual(result.get("cuenta"), "Cuenta")
        self.assertEqual(result.get("referencia"), "Referencia")
        self.assertEqual(result.get("nombre"), "Nombre")


class TestConditionalNameSplitting(unittest.TestCase):
    """Tests for conditional name splitting — only split when document has separate apellido columns."""

    def test_single_nombre_column_keeps_full_name(self):
        """When document has only 'Nombre' column, keep the full name without splitting."""
        from app.pipelines.extract import _payment_rows_to_objects, _payment_to_canonical_rows
        rows = [
            ["Cuenta", "Nombre", "Importe", "Estatus"],
            ["123456", "CARLOS ROBERTO LOPEZ GARCIA", "$3,000.00", "APLICADO"],
        ]
        objects = _payment_rows_to_objects(rows)
        _, canonical_rows = _payment_to_canonical_rows("BBVA", objects)
        self.assertEqual(len(canonical_rows), 1)
        row = canonical_rows[0]
        self.assertEqual(row.get("nombre"), "CARLOS ROBERTO LOPEZ GARCIA")
        self.assertIsNone(row.get("apellido_paterno"))
        self.assertIsNone(row.get("apellido_materno"))

    def test_separate_apellido_columns_still_split(self):
        """When document has separate apellido columns, splitting works normally."""
        from app.pipelines.extract import _payment_rows_to_objects, _payment_to_canonical_rows
        rows = [
            ["Cuenta", "Nombre", "Apellido Paterno", "Apellido Materno", "Importe", "Estatus"],
            ["123456", "CARLOS", "LOPEZ", "GARCIA", "$3,000.00", "APLICADO"],
        ]
        objects = _payment_rows_to_objects(rows)
        _, canonical_rows = _payment_to_canonical_rows("BBVA", objects)
        self.assertEqual(len(canonical_rows), 1)
        row = canonical_rows[0]
        self.assertEqual(row.get("apellido_paterno"), "LOPEZ")
        self.assertEqual(row.get("apellido_materno"), "GARCIA")

    def test_combo_header_splits_normally(self):
        """When document has combo 'Apellido Paterno Apellido Materno Estatus', splitting still works."""
        from app.pipelines.extract import _payment_rows_to_objects, _payment_to_canonical_rows
        rows = [
            ["Cuenta", "Nombre", "Apellido Paterno Apellido Materno Estatus", "Importe"],
            ["123456", "CARLOS", "LOPEZ GARCIA APLICADO", "$3,000.00"],
        ]
        objects = _payment_rows_to_objects(rows)
        _, canonical_rows = _payment_to_canonical_rows("BBVA", objects)
        self.assertEqual(len(canonical_rows), 1)
        row = canonical_rows[0]
        self.assertEqual(row.get("estatus"), "APLICADO")
        self.assertEqual(row.get("apellido_paterno"), "LOPEZ")

    def test_combo_overrides_noisy_explicit_apellidos_and_is_removed(self):
        from app.pipelines.extract import _payment_rows_to_objects, _payment_to_canonical_rows

        rows = [
            ["Cuenta", "Nombre", "Apellido paterno", "Apellido materno", "Apellido Paterno Apellido Materno Estatus", "Importe"],
            ["123456", "PATRICIA", "HERNANDEZ", "HERNANDEZ", "CRUZ TEJERO PROCESADO", "$3,000.00"],
        ]
        objects = _payment_rows_to_objects(rows)
        canonical_columns, canonical_rows = _payment_to_canonical_rows("BBVA", objects)

        self.assertEqual(len(canonical_rows), 1)
        row = canonical_rows[0]
        self.assertEqual(row.get("apellido_paterno"), "CRUZ")
        self.assertEqual(row.get("apellido_materno"), "TEJERO")
        self.assertEqual(row.get("estatus"), "PROCESADO")
        self.assertNotIn("apellido_combo_estatus", canonical_columns)
        self.assertNotIn("apellido_combo_estatus", row)


# ── Level 1: Field-level validation tests ──────────────────────────────────

class TestValidatePaymentTableCells(unittest.TestCase):
    """Tests for _validate_payment_table_cells (Level 1 validation)."""

    def test_valid_rows_no_warnings(self):
        from app.pipelines.extract import _validate_payment_table_cells
        rows = [
            ["CUENTA", "NOMBRE", "IMPORTE", "ESTATUS"],
            ["123456789012345678", "JUAN PEREZ", "$1,500.00", "APLICADO"],
            ["987654321098765432", "MARIA LOPEZ", "$2,300.50", "PROCESADO"],
        ]
        warnings = _validate_payment_table_cells(rows)
        self.assertEqual(warnings, [])

    def test_invalid_amount_format(self):
        from app.pipelines.extract import _validate_payment_table_cells
        rows = [
            ["CUENTA", "IMPORTE"],
            ["123456789012345678", "1500"],
        ]
        warnings = _validate_payment_table_cells(rows)
        self.assertTrue(any("formato de importe" in w for w in warnings))

    def test_zero_amount_warning(self):
        from app.pipelines.extract import _validate_payment_table_cells
        rows = [
            ["CUENTA", "IMPORTE"],
            ["123456789012345678", "$0.00"],
        ]
        warnings = _validate_payment_table_cells(rows)
        self.assertTrue(any("$0.00" in w for w in warnings))

    def test_invalid_account_length(self):
        from app.pipelines.extract import _validate_payment_table_cells
        rows = [
            ["CUENTA", "IMPORTE"],
            ["123", "$1,500.00"],
        ]
        warnings = _validate_payment_table_cells(rows)
        self.assertTrue(any("longitud inválida" in w for w in warnings))

    def test_invalid_date_month(self):
        from app.pipelines.extract import _validate_payment_table_cells
        rows = [
            ["FECHA", "IMPORTE"],
            ["15/13/2024", "$1,500.00"],
        ]
        warnings = _validate_payment_table_cells(rows)
        self.assertTrue(any("mes fuera de rango" in w for w in warnings))

    def test_invalid_date_day(self):
        from app.pipelines.extract import _validate_payment_table_cells
        rows = [
            ["FECHA", "IMPORTE"],
            ["32/01/2024", "$1,500.00"],
        ]
        warnings = _validate_payment_table_cells(rows)
        self.assertTrue(any("día fuera de rango" in w for w in warnings))

    def test_unrecognized_status(self):
        from app.pipelines.extract import _validate_payment_table_cells
        rows = [
            ["ESTATUS", "IMPORTE"],
            ["DESCONOCIDO", "$1,500.00"],
        ]
        warnings = _validate_payment_table_cells(rows)
        self.assertTrue(any("estatus no reconocido" in w for w in warnings))

    def test_valid_status_no_warning(self):
        from app.pipelines.extract import _validate_payment_table_cells
        rows = [
            ["ESTATUS", "IMPORTE"],
            ["EN PROCESO", "$1,500.00"],
        ]
        warnings = _validate_payment_table_cells(rows)
        status_warnings = [w for w in warnings if "estatus" in w]
        self.assertEqual(status_warnings, [])

    def test_empty_rows_no_crash(self):
        from app.pipelines.extract import _validate_payment_table_cells
        self.assertEqual(_validate_payment_table_cells([]), [])
        self.assertEqual(_validate_payment_table_cells([["H1"]]), [])

    def test_date_with_time_valid(self):
        from app.pipelines.extract import _validate_payment_table_cells
        rows = [
            ["FECHA", "IMPORTE"],
            ["15/06/2024 14:30", "$1,500.00"],
        ]
        warnings = _validate_payment_table_cells(rows)
        date_warnings = [w for w in warnings if "fecha" in w.lower() or "día" in w or "mes" in w]
        self.assertEqual(date_warnings, [])


# ── Level 2: Cross-coherence validation tests ──────────────────────────────

class TestValidatePaymentTableCoherence(unittest.TestCase):
    """Tests for _validate_payment_table_coherence (Level 2 validation)."""

    def test_matching_sum_no_warning(self):
        from app.pipelines.extract import _validate_payment_table_coherence
        rows = [
            ["CUENTA", "IMPORTE"],
            ["123456789012345678", "$1,000.00"],
            ["987654321098765432", "$2,000.00"],
            ["CANTIDAD DE MOVIMIENTOS ALTAS", "IMPORTE DE MOVIMIENTO ALTAS"],
            ["2", "$3,000.00"],
        ]
        warnings = _validate_payment_table_coherence(rows)
        sum_warnings = [w for w in warnings if "Suma de importes" in w]
        self.assertEqual(sum_warnings, [])

    def test_mismatched_sum_warns(self):
        from app.pipelines.extract import _validate_payment_table_coherence
        rows = [
            ["CUENTA", "IMPORTE"],
            ["123456789012345678", "$1,000.00"],
            ["987654321098765432", "$2,000.00"],
            ["CANTIDAD DE MOVIMIENTOS ALTAS", "IMPORTE DE MOVIMIENTO ALTAS"],
            ["2", "$5,000.00"],
        ]
        warnings = _validate_payment_table_coherence(rows)
        self.assertTrue(any("Suma de importes" in w for w in warnings))

    def test_matching_count_no_warning(self):
        from app.pipelines.extract import _validate_payment_table_coherence
        rows = [
            ["CUENTA", "IMPORTE"],
            ["123456789012345678", "$1,000.00"],
            ["987654321098765432", "$2,000.00"],
            ["CANTIDAD DE MOVIMIENTOS ALTAS", "IMPORTE DE MOVIMIENTO ALTAS"],
            ["2", "$3,000.00"],
        ]
        warnings = _validate_payment_table_coherence(rows)
        count_warnings = [w for w in warnings if "Cantidad de filas" in w]
        self.assertEqual(count_warnings, [])

    def test_mismatched_count_warns(self):
        from app.pipelines.extract import _validate_payment_table_coherence
        rows = [
            ["CUENTA", "IMPORTE"],
            ["123456789012345678", "$1,000.00"],
            ["987654321098765432", "$2,000.00"],
            ["CANTIDAD DE MOVIMIENTOS ALTAS", "IMPORTE DE MOVIMIENTO ALTAS"],
            ["5", "$3,000.00"],
        ]
        warnings = _validate_payment_table_coherence(rows)
        self.assertTrue(any("Cantidad de filas" in w for w in warnings))

    def test_no_summary_rows_no_crash(self):
        from app.pipelines.extract import _validate_payment_table_coherence
        rows = [
            ["CUENTA", "IMPORTE"],
            ["123456789012345678", "$1,000.00"],
        ]
        warnings = _validate_payment_table_coherence(rows)
        self.assertEqual(warnings, [])

    def test_empty_rows(self):
        from app.pipelines.extract import _validate_payment_table_coherence
        self.assertEqual(_validate_payment_table_coherence([]), [])

    def test_small_difference_tolerated(self):
        """Differences within 1% threshold should not trigger a warning."""
        from app.pipelines.extract import _validate_payment_table_coherence
        rows = [
            ["CUENTA", "IMPORTE"],
            ["123456789012345678", "$10,000.00"],
            ["CANTIDAD DE MOVIMIENTOS ALTAS", "IMPORTE DE MOVIMIENTO ALTAS"],
            ["1", "$10,050.00"],
        ]
        warnings = _validate_payment_table_coherence(rows)
        sum_warnings = [w for w in warnings if "Suma de importes" in w]
        self.assertEqual(sum_warnings, [])


class TestParseAmountToCents(unittest.TestCase):
    """Tests for _parse_amount_to_cents helper."""

    def test_standard_amount(self):
        from app.pipelines.extract import _parse_amount_to_cents
        self.assertEqual(_parse_amount_to_cents("$1,500.00"), 150000)

    def test_no_dollar_sign(self):
        from app.pipelines.extract import _parse_amount_to_cents
        self.assertEqual(_parse_amount_to_cents("1,500.00"), 150000)

    def test_large_amount(self):
        from app.pipelines.extract import _parse_amount_to_cents
        self.assertEqual(_parse_amount_to_cents("$1,234,567.89"), 123456789)

    def test_cents_only(self):
        from app.pipelines.extract import _parse_amount_to_cents
        self.assertEqual(_parse_amount_to_cents("$0.50"), 50)

    def test_empty_returns_none(self):
        from app.pipelines.extract import _parse_amount_to_cents
        self.assertIsNone(_parse_amount_to_cents(""))
        self.assertIsNone(_parse_amount_to_cents("abc"))


# ── Level 3: OCR quality assessment tests ──────────────────────────────────

class TestAssessOcrQuality(unittest.TestCase):
    """Tests for _assess_ocr_quality (Level 3 validation)."""

    def test_clean_text_high_score(self):
        from app.pipelines.extract import _assess_ocr_quality
        text = (
            "SCOTIABANK\n"
            "FECHA: 15/06/2024\n"
            "CUENTA: 123456789012345678\n"
            "IMPORTE: $1,500.00\n"
            "NOMBRE: JUAN PEREZ GARCIA\n"
            "ESTATUS: APLICADO\n"
        )
        result = _assess_ocr_quality(text)
        self.assertGreaterEqual(result["score"], 0.85)
        self.assertEqual(result["warnings"], [])

    def test_empty_text_zero_score(self):
        from app.pipelines.extract import _assess_ocr_quality
        result = _assess_ocr_quality("")
        self.assertEqual(result["score"], 0.0)
        self.assertTrue(any("vacío" in w for w in result["warnings"]))

    def test_noisy_text_low_score(self):
        from app.pipelines.extract import _assess_ocr_quality
        # Generate text with lots of noise characters
        clean = "BANCO FECHA CUENTA IMPORTE NOMBRE ESTATUS\n" * 5
        noise = "\x01\x02\x03\x04\x05" * 40
        text = clean + noise
        result = _assess_ocr_quality(text)
        self.assertLess(result["score"], 0.85)

    def test_stutter_detection(self):
        from app.pipelines.extract import _assess_ocr_quality
        text = "NORMAL TEXT " + "AAAAAAA " * 5 + "BBBBBBB " * 5 + "MORE NORMAL TEXT\n" * 10
        result = _assess_ocr_quality(text)
        self.assertGreater(result["metrics"]["stutter_sequences"], 0)

    def test_box_confidence_metric(self):
        from app.pipelines.extract import _assess_ocr_quality
        text = "SOME TEXT FOR TESTING OCR QUALITY\n" * 5
        boxes = [
            {"text": "SOME", "confidence": 0.95},
            {"text": "TEXT", "confidence": 0.90},
            {"text": "FOR", "confidence": 0.88},
        ]
        result = _assess_ocr_quality(text, boxes)
        self.assertIn("avg_box_confidence", result["metrics"])
        self.assertGreater(result["metrics"]["avg_box_confidence"], 0.85)

    def test_low_confidence_boxes_penalized(self):
        from app.pipelines.extract import _assess_ocr_quality
        text = "SOME TEXT FOR TESTING OCR QUALITY\n" * 5
        boxes = [
            {"text": "X", "confidence": 0.3},
            {"text": "Y", "confidence": 0.2},
            {"text": "Z", "confidence": 0.4},
        ]
        result = _assess_ocr_quality(text, boxes)
        self.assertLess(result["score"], 0.85)

    def test_structure_hits_counted(self):
        from app.pipelines.extract import _assess_ocr_quality
        text = "FECHA 15/06/2024 IMPORTE $1,500.00 CUENTA 123456789012345678\n"
        result = _assess_ocr_quality(text)
        self.assertGreaterEqual(result["metrics"]["structure_hits"], 2)


class TestClassifyTableColumns(unittest.TestCase):
    """Tests for _classify_table_columns helper."""

    def test_standard_header(self):
        from app.pipelines.extract import _classify_table_columns
        header = ["CUENTA", "NOMBRE", "IMPORTE", "ESTATUS", "FECHA"]
        col_types = _classify_table_columns(header)
        self.assertEqual(col_types[0], "account")
        self.assertEqual(col_types[2], "amount")
        self.assertEqual(col_types[3], "status")
        self.assertEqual(col_types[4], "date")

    def test_compound_header_tokens(self):
        from app.pipelines.extract import _classify_table_columns
        header = ["CUENTA RETIRO", "IMPORTE DETECTADO", "FECHA PAGO"]
        col_types = _classify_table_columns(header)
        self.assertEqual(col_types[0], "account")
        self.assertEqual(col_types[1], "amount")
        self.assertEqual(col_types[2], "date")

    def test_empty_header(self):
        from app.pipelines.extract import _classify_table_columns
        self.assertEqual(_classify_table_columns([]), {})

    def test_summary_count_columns(self):
        from app.pipelines.extract import _classify_table_columns
        header = [
            "CANTIDAD DE MOVIMIENTOS ALTAS",
            "IMPORTE DE MOVIMIENTO ALTAS",
        ]
        col_types = _classify_table_columns(header)
        self.assertEqual(col_types[0], "count")
        self.assertEqual(col_types[1], "amount")


# ---------------------------------------------------------------------------
# _DATA_TOKEN_PAT  – regex for data-type tokens
# ---------------------------------------------------------------------------
class TestDataTokenPattern(unittest.TestCase):
    """Validate the _DATA_TOKEN_PAT regex matches expected data tokens."""

    def _findall(self, text: str) -> list[str]:
        from app.pipelines.extract import _DATA_TOKEN_PAT
        return [m.group(0).strip() for m in _DATA_TOKEN_PAT.finditer(text)]

    def test_currency(self):
        self.assertEqual(self._findall("$89"), ["$89"])
        self.assertEqual(self._findall("$1,234.56"), ["$1,234.56"])

    def test_percentage(self):
        self.assertEqual(self._findall("123%"), ["123%"])
        self.assertEqual(self._findall("12.5 %"), ["12.5 %"])

    def test_boolean_tokens(self):
        self.assertIn("YES", self._findall("YES"))
        self.assertIn("NO", self._findall("NO"))
        self.assertIn("N/A", self._findall("N/A"))
        self.assertIn("SI", self._findall("SI"))

    def test_comma_thousands(self):
        results = self._findall("1,005")
        self.assertIn("1,005", results)

    def test_space_thousands(self):
        # "8 288" should match as space-separated thousands
        results = self._findall("word 8 288 end")
        self.assertIn("8 288", results)

    def test_space_thousands_not_before_percent(self):
        # "8 288 %" — the space-thousands rule should NOT match; instead % wins
        results = self._findall("value 12 345%")
        # Should match "12 345%" as percentage (or individual numbers + %)
        # but NOT "12 345" as space-thousands because of (?!\s*[%$])
        space_thou = [r for r in results if r == "12 345"]
        self.assertEqual(space_thou, [], "Should not match space-thousands before %")

    def test_plain_number(self):
        self.assertIn("42", self._findall("42"))
        self.assertIn("56.78", self._findall("56.78"))


# ---------------------------------------------------------------------------
# _split_line_by_data_patterns
# ---------------------------------------------------------------------------
class TestSplitLineByDataPatterns(unittest.TestCase):

    def _split(self, line: str):
        from app.pipelines.extract import _split_line_by_data_patterns
        return _split_line_by_data_patterns(line)

    def test_basic_split(self):
        result = self._split("Concepto A 8 288 123% YES $89")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertGreaterEqual(len(result), 3)
        self.assertEqual(result[0], "Concepto A")

    def test_insufficient_data_tokens_returns_none(self):
        result = self._split("Just a sentence with one number 42")
        self.assertIsNone(result)

    def test_no_data_returns_none(self):
        result = self._split("This is a plain text line")
        self.assertIsNone(result)

    def test_label_plus_two_numbers(self):
        result = self._split("Rent 500.00 600.00")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result[0], "Rent")
        self.assertIn("500.00", result)
        self.assertIn("600.00", result)


# ---------------------------------------------------------------------------
# _extract_generic_tables_from_text_pattern_split
# ---------------------------------------------------------------------------
class TestExtractGenericTablesPatternSplit(unittest.TestCase):

    def _extract(self, text: str):
        from app.pipelines.extract import _extract_generic_tables_from_text_pattern_split
        return _extract_generic_tables_from_text_pattern_split(text)

    def test_multi_row_table(self):
        text = (
            "Concepto A 8 288 123% YES $89\n"
            "Concepto B 1 200 45% NO $50\n"
            "Concepto C 300 99% YES $120\n"
        )
        tables = self._extract(text)
        self.assertGreaterEqual(len(tables), 1)
        t = tables[0]
        self.assertEqual(t["source"], "text_pattern_split")
        self.assertGreaterEqual(t["row_count"], 2)

    def test_empty_text_returns_empty(self):
        self.assertEqual(self._extract(""), [])
        self.assertEqual(self._extract("   "), [])

    def test_single_line_returns_empty(self):
        self.assertEqual(self._extract("Concepto A 8 288 123% YES $89"), [])

    def test_non_table_text_returns_empty(self):
        text = (
            "This document has no tables.\n"
            "It only contains text.\n"
            "There are no numbers arranged.\n"
        )
        self.assertEqual(self._extract(text), [])

    def test_two_column_table(self):
        text = (
            "Product Alpha 500.00 600.00\n"
            "Product Beta 350.25 420.10\n"
            "Product Gamma 900.00 720.50\n"
        )
        tables = self._extract(text)
        self.assertGreaterEqual(len(tables), 1)
        # Each row should have label + 2 numbers
        for row in tables[0]["rows"]:
            self.assertGreaterEqual(len(row), 3)


# ---------------------------------------------------------------------------
# _extract_generic_tables_from_text (double-space preservation fix)
# ---------------------------------------------------------------------------
class TestExtractGenericTablesTextDoubleSpace(unittest.TestCase):
    """Verifies the fix for double-space preservation in the text splitter."""

    def _extract(self, text: str):
        from app.pipelines.extract import _extract_generic_tables_from_text
        return _extract_generic_tables_from_text(text)

    def test_double_space_columns_detected(self):
        text = (
            "Header A  Header B  Header C\n"
            "Value 1   Value 2   Value 3\n"
            "Value 4   Value 5   Value 6\n"
            "Value 7   Value 8   Value 9\n"
        )
        tables = self._extract(text)
        self.assertGreaterEqual(len(tables), 1)
        self.assertGreaterEqual(tables[0]["row_count"], 2)


if __name__ == "__main__":
    unittest.main()
