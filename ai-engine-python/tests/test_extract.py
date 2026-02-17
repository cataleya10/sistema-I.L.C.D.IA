import asyncio
import json
import unittest
from unittest.mock import patch

from app.pipelines.extract import extract_fields


def _field_map(fields: list[dict]) -> dict[str, str]:
    return {str(f.get("key")): str(f.get("value")) for f in fields if f.get("key") and f.get("value") is not None}


def _box(text: str, y: int) -> dict:
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
        fields = asyncio.run(extract_fields("INE", ocr_text, None))
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
        fields = asyncio.run(extract_fields("DATOS_BANCARIOS", ocr_text, None))
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
        fields = asyncio.run(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None))
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
        fields = asyncio.run(extract_fields("INE", ocr_text, None))
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
        fields = asyncio.run(extract_fields("DATOS_BANCARIOS", ocr_text, None))
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

        fields = asyncio.run(extract_fields("DATOS_BANCARIOS", ocr_text, ocr_boxes))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        self.assertEqual(payload.get("source"), "ocr_boxes")
        self.assertGreaterEqual(len(payload.get("rows", [])), 2)
        self.assertEqual(payload["rows"][0][0], "CUENTA")

    def test_extract_datos_bancarios_payment_table_from_text_lines(self):
        ocr_text = "\n".join(
            [
                "Cuenta    Referencia    Importe    Nombre",
                "56551346133    1620260115132703271255    $1,462.58    JOSE LUIS",
            ]
        )
        fields = asyncio.run(extract_fields("DATOS_BANCARIOS", ocr_text, None))
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
        fields = asyncio.run(extract_fields("FACTURA", ocr_text, None))
        data = _field_map(fields)

        self.assertIn("tabla_celdas", data)
        payload = json.loads(data["tabla_celdas"])
        self.assertEqual(payload.get("source"), "text_lines")
        self.assertEqual(payload["rows"][0][0], "CUENTA")

    def test_extract_factura_contract_keeps_only_table_cells(self):
        ocr_text = "\n".join(
            [
                "BANCO SCOTIABANK INVERLAT",
                "TITULAR: NOMBRE DEL ARCHIVO",
                "Cuenta    Referencia    Importe    Nombre",
                "56551346133    1620260115132703271255    $1,462.58    JOSE LUIS",
            ]
        )
        fields = asyncio.run(extract_fields("FACTURA", ocr_text, None))
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
        fields = asyncio.run(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None))
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
        fields = asyncio.run(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("cp"), "44100")

    def test_extract_acta_folio_with_ocr_confusions(self):
        ocr_text = "\n".join(
            [
                "ACTA DE NACIMIENTO",
                "FOLIO I2O3",
            ]
        )
        fields = asyncio.run(extract_fields("ACTA_NACIMIENTO", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("folio"), "1203")

    def test_extract_comprobante_referencia_with_ocr_confusions(self):
        ocr_text = "\n".join(
            [
                "TELMEX",
                "LINEA DE CAPTURA O2345I789OI2345678",
            ]
        )
        fields = asyncio.run(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None))
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
        fields = asyncio.run(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, ocr_boxes))
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
        fields = asyncio.run(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, ocr_boxes))
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
        fields = asyncio.run(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None, raw_text=ocr_text, filename="telcel.jpg"))
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
        fields = asyncio.run(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None))
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
        fields = asyncio.run(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("referencia"), "24180130522010101002")

    def test_extract_cfe_domicilio_removes_amount_prefix_noise(self):
        ocr_text = "\n".join(
            [
                "CFE COMISION FEDERAL DE ELECTRICIDAD",
                "TOTAL A PAGAR $ 548.17",
                "$ 548 17 DN. 223 DEPTO. 1 BENITO JUAREZ",
                "CP 24180",
            ]
        )
        fields = asyncio.run(extract_fields("COMPROBANTE_DOMICILIO", ocr_text, None))
        data = _field_map(fields)
        domicilio = data.get("domicilio", "")

        self.assertIn("DN", domicilio)
        self.assertNotIn("$", domicilio)
        self.assertNotIn("548 17", domicilio)

    def test_extract_acta_numero_acta_with_ocr_confusions_from_boxes(self):
        ocr_boxes = [
            _box("ACTA DE NACIMIENTO", 10),
            _box("NUMERO DE ACTA I2O3L", 40),
        ]
        with patch("app.pipelines.extract.legacy_extract_fields", return_value={}):
            fields = asyncio.run(
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
            fields = asyncio.run(
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
            fields = asyncio.run(
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
        fields = asyncio.run(extract_fields("ACTA_NACIMIENTO", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("numero_acta"), "3")
        self.assertEqual(data.get("folio"), "437")

    def test_extract_acta_lugar_nacimiento_cleans_label_noise(self):
        ocr_text = "ACTA DE NACIMIENTO\nHOMBRE 25/04/2001 JONUTA SEXO: FECHA DE NACIMIENTO: LUGAR DE NACIMIENTO:"
        ocr_boxes = [
            _box("ACTA DE NACIMIENTO", 10),
            _box("HOMBRE 25/04/2001 JONUTA SEXO: FECHA DE NACIMIENTO: LUGAR DE NACIMIENTO:", 40),
        ]
        fields = asyncio.run(extract_fields("ACTA_NACIMIENTO", ocr_text, ocr_boxes))
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
        fields = asyncio.run(extract_fields("NSS", ocr_text, None))
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
        fields = asyncio.run(extract_fields("NSS", ocr_text, None))
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
        fields = asyncio.run(extract_fields("NSS", ocr_text, None))
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
        fields = asyncio.run(extract_fields("NSS", ocr_text, None))
        data = _field_map(fields)

        self.assertEqual(data.get("nss"), "60160194696")
        self.assertEqual(data.get("nombre"), "ERWIN GUSTAVO GARCIA CAMPOS")

    def test_field_contract_drops_invalid_legacy_curp(self):
        with patch("app.pipelines.extract.legacy_extract_fields", return_value={"curp": "ABCD123"}):
            fields = asyncio.run(extract_fields("INE", "CREDENCIAL PARA VOTAR", None))
        data = _field_map(fields)

        self.assertIsNone(data.get("curp"))

    def test_field_contract_drops_invalid_legacy_referencia(self):
        with patch("app.pipelines.extract.legacy_extract_fields", return_value={"referencia": "12345"}):
            fields = asyncio.run(extract_fields("COMPROBANTE_DOMICILIO", "COMPROBANTE", None))
        data = _field_map(fields)

        self.assertIsNone(data.get("referencia"))

    def test_field_contract_drops_noisy_lugar_nacimiento(self):
        with patch(
            "app.pipelines.extract.legacy_extract_fields",
            return_value={"lugar_nacimiento": "ACTA DE NACIMIENTO SEXO FECHA DE NACIMIENTO"},
        ):
            fields = asyncio.run(extract_fields("ACTA_NACIMIENTO", "ACTA DE NACIMIENTO", None))
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
            fields = asyncio.run(extract_fields("COMPROBANTE_DOMICILIO", "COMPROBANTE DE DOMICILIO", None))
        data = _field_map(fields)

        self.assertIsNone(data.get("cliente"))
        self.assertIsNone(data.get("medidor"))
        self.assertIsNone(data.get("rfc"))

    def test_field_contract_drops_noisy_titular_text(self):
        with patch(
            "app.pipelines.extract.legacy_extract_fields",
            return_value={"titular": "ESTE GRAFICO REFLEJA TU NIVEL DE CONSUMO"},
        ):
            fields = asyncio.run(extract_fields("COMPROBANTE_DOMICILIO", "COMPROBANTE DE DOMICILIO", None))
        data = _field_map(fields)

        self.assertIsNone(data.get("titular"))


if __name__ == "__main__":
    unittest.main()
