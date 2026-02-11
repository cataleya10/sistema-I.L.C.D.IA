import asyncio
import unittest

from app.pipelines import classify
from app.pipelines.extract import extract_fields
from app.pipelines.validate import validate_fields


def _field_by_key(fields: list[dict], key: str) -> dict | None:
    return next((f for f in fields if f.get("key") == key), None)


class PipelineIntegrationTests(unittest.TestCase):
    def setUp(self):
        # Keep classification deterministic in tests.
        classify.MODEL_PATH = "__missing_model_for_tests__.json"

    def test_pipeline_ine_end_to_end(self):
        text = "\n".join(
            [
                "INSTITUTO NACIONAL ELECTORAL",
                "CREDENCIAL PARA VOTAR",
                "CURP AACD900101HDFRRL09",
                "SECCION 1234",
                "VIGENCIA 2030",
            ]
        )
        doc_type, _ = asyncio.run(classify.classify_document(None, text, "credencial.png"))
        self.assertEqual(doc_type, "INE")

        fields = asyncio.run(extract_fields(doc_type, text, None, raw_text=text, filename="credencial.png"))
        validated = asyncio.run(validate_fields(fields))

        curp = _field_by_key(validated, "curp")
        seccion = _field_by_key(validated, "seccion")
        vigencia = _field_by_key(validated, "vigencia")
        self.assertIsNotNone(curp)
        self.assertIsNotNone(seccion)
        self.assertIsNotNone(vigencia)
        self.assertEqual(curp.get("value"), "AACD900101HDFRRL09")
        self.assertTrue(bool(curp.get("valid")))
        self.assertEqual(seccion.get("value"), "1234")
        self.assertTrue(bool(seccion.get("valid")))
        self.assertEqual(vigencia.get("value"), "2030")
        self.assertTrue(bool(vigencia.get("valid")))

    def test_pipeline_comprobante_end_to_end(self):
        text = "\n".join(
            [
                "TELMEX",
                "NUMERO TELEFONICO (33) 1234-5678",
                "NO DE CUENTA 0011223344",
                "LINEA DE CAPTURA O2345I789OI2345678",
                "CP 44I0O",
            ]
        )
        doc_type, _ = asyncio.run(classify.classify_document(None, text, "telmex.pdf"))
        self.assertEqual(doc_type, "COMPROBANTE_DOMICILIO")

        fields = asyncio.run(extract_fields(doc_type, text, None, raw_text=text, filename="telmex.pdf"))
        validated = asyncio.run(validate_fields(fields))

        cp = _field_by_key(validated, "cp")
        referencia = _field_by_key(validated, "referencia")
        numero_servicio = _field_by_key(validated, "numero_servicio")
        self.assertIsNotNone(cp)
        self.assertIsNotNone(referencia)
        self.assertIsNotNone(numero_servicio)
        self.assertEqual(cp.get("value"), "44100")
        self.assertTrue(bool(cp.get("valid")))
        self.assertEqual(referencia.get("value"), "023451789012345678")
        self.assertEqual(numero_servicio.get("value"), "3312345678")

    def test_pipeline_bancarios_end_to_end(self):
        text = "\n".join(
            [
                "BANCO BBVA",
                "CLABE 032180000118359719",
                "RFC XAXX010101000",
            ]
        )
        doc_type, _ = asyncio.run(classify.classify_document(None, text, "estado_cuenta.pdf"))
        self.assertEqual(doc_type, "DATOS_BANCARIOS")

        fields = asyncio.run(extract_fields(doc_type, text, None, raw_text=text, filename="estado_cuenta.pdf"))
        validated = asyncio.run(validate_fields(fields))

        clabe = _field_by_key(validated, "clabe")
        rfc = _field_by_key(validated, "rfc")
        self.assertIsNotNone(clabe)
        self.assertIsNotNone(rfc)
        self.assertEqual(clabe.get("value"), "032180000118359719")
        self.assertTrue(bool(clabe.get("valid")))
        self.assertEqual(rfc.get("value"), "XAXX010101000")
        self.assertTrue(bool(rfc.get("valid")))

    def test_pipeline_nss_end_to_end(self):
        text = "NUMERO DE SEGURIDAD SOCIAL 12345678901"
        doc_type, _ = asyncio.run(classify.classify_document(None, text, "imss.pdf"))
        self.assertEqual(doc_type, "NSS")

        fields = asyncio.run(extract_fields(doc_type, text, None, raw_text=text, filename="imss.pdf"))
        validated = asyncio.run(validate_fields(fields))

        nss = _field_by_key(validated, "nss")
        self.assertIsNotNone(nss)
        self.assertEqual(nss.get("value"), "12345678901")
        self.assertTrue(bool(nss.get("valid")))


if __name__ == "__main__":
    unittest.main()
