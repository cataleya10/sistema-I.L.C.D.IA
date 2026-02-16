import unittest

from app.utils import validators


class ValidatorsTests(unittest.TestCase):
    def test_validate_curp_valid(self):
        ok, errors = validators.validate_curp("GODE561231HDFRRN09")
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_validate_curp_invalid_state(self):
        ok, errors = validators.validate_curp("GODE561231HXXRRN09")
        self.assertFalse(ok)
        self.assertTrue(errors)

    def test_validate_rfc_homoclave_valid(self):
        ok, errors = validators.validate_rfc_homoclave("XAXX010101000")
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_validate_rfc_invalid(self):
        ok, errors = validators.validate_rfc("XAXX01010100")
        self.assertFalse(ok)
        self.assertTrue(errors)

    def test_validate_nss(self):
        ok, _ = validators.validate_nss("12345678901")
        self.assertTrue(ok)
        bad, _ = validators.validate_nss("12345")
        self.assertFalse(bad)

    def test_validate_clabe_check_digit(self):
        ok, _ = validators.validate_clabe("032180000118359719")
        self.assertTrue(ok)
        bad, _ = validators.validate_clabe("032180000118359718")
        self.assertFalse(bad)

    def test_validate_date(self):
        ok, _ = validators.validate_date("29/02/2024")
        self.assertTrue(ok)
        bad, _ = validators.validate_date("31/02/2024")
        self.assertFalse(bad)

    def test_validate_sex(self):
        ok, _ = validators.validate_sex("femenino")
        self.assertTrue(ok)
        bad, _ = validators.validate_sex("X")
        self.assertFalse(bad)

    def test_validate_cp(self):
        ok, _ = validators.validate_cp("44100")
        self.assertTrue(ok)
        bad, _ = validators.validate_cp("4410")
        self.assertFalse(bad)

    def test_validate_folio(self):
        ok, _ = validators.validate_folio("ABCD-1234")
        self.assertTrue(ok)
        short_ok, _ = validators.validate_folio("437")
        self.assertTrue(short_ok)
        bad, _ = validators.validate_folio("A1")
        self.assertFalse(bad)

    def test_validate_state_code(self):
        ok_short, _ = validators.validate_state_code("DF")
        ok_name, _ = validators.validate_state_code("JALISCO")
        bad, _ = validators.validate_state_code("ZZ")
        self.assertTrue(ok_short)
        self.assertTrue(ok_name)
        self.assertFalse(bad)

    def test_validate_clave_elector(self):
        ok, _ = validators.validate_clave_elector("ABCDEF1234567890")
        self.assertTrue(ok)
        bad, _ = validators.validate_clave_elector("123")
        self.assertFalse(bad)

    def test_validate_seccion(self):
        ok, _ = validators.validate_seccion("1234")
        self.assertTrue(ok)
        bad, _ = validators.validate_seccion("12")
        self.assertFalse(bad)

    def test_validate_vigencia(self):
        ok_year, _ = validators.validate_vigencia("2030")
        ok_range, _ = validators.validate_vigencia("2020/2030")
        bad_year, _ = validators.validate_vigencia("1800")
        bad_text, _ = validators.validate_vigencia("VIGENTE")
        self.assertTrue(ok_year)
        self.assertTrue(ok_range)
        self.assertFalse(bad_year)
        self.assertFalse(bad_text)


if __name__ == "__main__":
    unittest.main()
