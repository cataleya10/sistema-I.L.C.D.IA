import asyncio
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


if __name__ == "__main__":
    unittest.main()
