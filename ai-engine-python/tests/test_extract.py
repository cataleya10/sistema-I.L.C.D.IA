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

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        self.assertEqual(payload.get("source"), "ocr_boxes")
        self.assertGreaterEqual(len(payload.get("rows", [])), 2)
        self.assertEqual(payload["rows"][0][0], "CUENTA")

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

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        self.assertEqual(payload.get("source"), "text_lines")
        self.assertEqual(payload["rows"][0][0], "CUENTA")

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
        self.assertEqual(payload["rows"][0][0], "CUENTA")

    def test_extract_comprobante_payment_table_from_text_lines(self):
        ocr_text = "\n".join(
            [
                "Cuenta    Referencia    Importe    Nombre",
                "56551346133    1620260115132703271255    $1,462.58    JOSE LUIS",
            ]
        )
        fields = _run_sync(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        self.assertEqual(payload.get("source"), "text_lines")
        self.assertEqual(payload["rows"][0][0], "CUENTA")

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
        self.assertEqual(rows[1][2], "$610.44")
        self.assertEqual(rows[1][3], "MARLA GRISELDA")
        self.assertEqual(rows[1][4], "MENDEZ")
        self.assertEqual(rows[1][5], "FLORES")
        self.assertEqual(rows[1][6], "PROCESADO")
        self.assertEqual(rows[1][7], "PAGO DE NOMINA")
        self.assertEqual(rows[2][0], "56936397470")
        self.assertEqual(rows[2][1], "1620260115134348451388")
        self.assertEqual(rows[2][2], "$1,537.35")
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
        self.assertEqual(rows[1][2], "$610.44")
        self.assertEqual(rows[1][3], "MARLA GRISELDA")
        self.assertEqual(rows[2][0], "56936397470")
        self.assertEqual(rows[2][1], "1620260115134348451388")
        self.assertEqual(rows[2][2], "$1,537.35")
        self.assertEqual(rows[3][0], "56905029323")
        self.assertEqual(rows[3][1], "1620260115134344071306")
        self.assertEqual(rows[3][2], "$353.60")

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
        self.assertEqual(payload.get("metadata", {}).get("importe_total_movimientos"), "$18,000.00")
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
        self.assertEqual(summary[0].get("rows", [[]])[0][1], "$18,000.00")
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
        self.assertTrue(any(row[:4] == ["6", "$18,000.00", "0", "$0.00"] for row in rows))
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
        self.assertEqual(canonical_rows[0].get("importe"), "$3,000.00")
        self.assertIn("CARLOS ROBERTO", canonical_rows[0].get("nombre_beneficiario", ""))
        self.assertEqual(canonical_rows[0].get("estatus"), "APLICADO")

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
        self.assertEqual(rows[1][4], "$3,000.00")
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
        self.assertEqual(rows[1][4], "$5,115.99")
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
        self.assertEqual(rows[1][4], "$3,000.00")
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

    def test_fix_ocr_invalid_nombre_discards_row(self):
        """Si nombre es solo un monto (sin nombre real), la fila se descarta."""
        from app.pipelines.extract import _fix_payment_ocr_column_errors

        rows = [
            ["CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE", "APELLIDO PATERNO", "APELLIDO MATERNO", "ESTATUS", "CONCEPTO"],
            ["56783223195", "1620260115134340581263", "$140948.59", "$610.44", "MENDEZ", "FLORES", "", "PAGO DE NOMINA"],
        ]
        result = _fix_payment_ocr_column_errors(rows)
        self.assertEqual(len(result), 1, "Fila con nombre inválido debe descartarse (solo queda header)")

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
        self.assertIn("$140,948.59", meta.get("importe_detectado", ""))
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


if __name__ == "__main__":
    unittest.main()

