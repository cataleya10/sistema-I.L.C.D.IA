import asyncio
import unittest
from collections.abc import Coroutine
from typing import Any, TypeVar, cast, overload

from app.pipelines import classify
from app.pipelines.extract import extract_fields
from app.pipelines.validate import validate_fields


T = TypeVar("T")


@overload
def _run_sync(value: Coroutine[Any, Any, T]) -> T: ...


@overload
def _run_sync(value: T) -> T: ...


def _run_sync(value: Coroutine[Any, Any, T] | T) -> T:
    if asyncio.iscoroutine(value):
        return asyncio.run(cast(Coroutine[Any, Any, T], value))
    return value


def _field_by_key(fields: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    return next((f for f in fields if f.get("key") == key), None)


def _require_field(fields: list[dict[str, Any]], key: str) -> dict[str, Any]:
    field = _field_by_key(fields, key)
    assert field is not None, f"Missing expected field: {key}"
    return field


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
        doc_type, _ = _run_sync(classify.classify_document(None, text, "credencial.png"))
        self.assertEqual(doc_type, "INE")

        fields = _run_sync(extract_fields(doc_type, text, None, raw_text=text, filename="credencial.png"))
        validated = _run_sync(validate_fields(fields))

        curp = _require_field(validated, "curp")
        seccion = _require_field(validated, "seccion")
        vigencia = _require_field(validated, "vigencia")
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
        doc_type, _ = _run_sync(classify.classify_document(None, text, "telmex.pdf"))
        self.assertEqual(doc_type, "COMPROBANTE_DOMICILIO")

        fields = _run_sync(extract_fields(doc_type, text, None, raw_text=text, filename="telmex.pdf"))
        validated = _run_sync(validate_fields(fields))

        cp = _require_field(validated, "cp")
        referencia = _require_field(validated, "referencia")
        numero_servicio = _require_field(validated, "numero_servicio")
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
        doc_type, _ = _run_sync(classify.classify_document(None, text, "estado_cuenta.pdf"))
        self.assertEqual(doc_type, "DATOS_BANCARIOS")

        fields = _run_sync(extract_fields(doc_type, text, None, raw_text=text, filename="estado_cuenta.pdf"))
        validated = _run_sync(validate_fields(fields))

        clabe = _require_field(validated, "clabe")
        rfc = _require_field(validated, "rfc")
        self.assertEqual(clabe.get("value"), "032180000118359719")
        self.assertTrue(bool(clabe.get("valid")))
        self.assertEqual(rfc.get("value"), "XAXX010101000")
        self.assertTrue(bool(rfc.get("valid")))

    def test_pipeline_nss_end_to_end(self):
        text = "NUMERO DE SEGURIDAD SOCIAL 12345678901"
        doc_type, _ = _run_sync(classify.classify_document(None, text, "imss.pdf"))
        self.assertEqual(doc_type, "NSS")

        fields = _run_sync(extract_fields(doc_type, text, None, raw_text=text, filename="imss.pdf"))
        validated = _run_sync(validate_fields(fields))

        nss = _require_field(validated, "nss")
        self.assertEqual(nss.get("value"), "12345678901")
        self.assertTrue(bool(nss.get("valid")))

    def test_pipeline_factura_pago_end_to_end(self):
        text = "\n".join(
            [
                "Reporte de operaciones",
                "Dispersion de Pago de Nomina",
                "Cuenta    Referencia    Importe    Nombre",
                "56551346133    1620260115132703271255    $1,462.58    JOSE LUIS",
            ]
        )
        doc_type, _ = _run_sync(classify.classify_document(None, text, "PAGO FIS BMPEI.pdf"))
        self.assertEqual(doc_type, "FACTURA")

        fields = _run_sync(extract_fields(doc_type, text, None, raw_text=text, filename="PAGO FIS BMPEI.pdf"))
        validated = _run_sync(validate_fields(fields))

        table_field = _require_field(validated, "tabla_celdas")
        self.assertTrue(bool(table_field.get("value")))


if __name__ == "__main__":
    unittest.main()

