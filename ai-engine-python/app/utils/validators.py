import re
from datetime import datetime

CURP_REGEX = re.compile(r"^[A-Z][AEIOUX][A-Z]{2}\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[HM][A-Z]{5}[A-Z0-9]\d$")
RFC_REGEX = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")
NSS_REGEX = re.compile(r"^\d{11}$")
CLABE_REGEX = re.compile(r"^\d{18}$")
DATE_REGEX = re.compile(r"^(\d{2})[/-](\d{2})[/-](\d{4})$")
SEX_REGEX = re.compile(r"^(H|M|HOMBRE|MUJER|MASCULINO|FEMENINO)$", re.IGNORECASE)
BANK_REGEX = re.compile(r"^[A-ZÁÉÍÓÚÑ0-9 .&-]{3,}$", re.IGNORECASE)
FOLIO_REGEX = re.compile(r"^[A-Z0-9-]{4,}$", re.IGNORECASE)
CP_REGEX = re.compile(r"^\d{5}$")
CLAVE_ELECTOR_REGEX = re.compile(r"^[A-Z0-9]{6,18}$", re.IGNORECASE)
SECCION_REGEX = re.compile(r"^\d{3,6}$")
NAME_TEXT_REGEX = re.compile(r"^[A-ZÁÉÍÓÚÑ .'-]{3,}$", re.IGNORECASE)
GENERIC_TEXT_REGEX = re.compile(r"^[A-ZÁÉÍÓÚÑ0-9 .'-]{3,}$", re.IGNORECASE)
VIGENCIA_REGEX = re.compile(r"^(\d{4}([/-]\d{4})?|\d{2}/\d{2}/\d{4})$")
STATE_CODES = {
    "AS", "BC", "BS", "CC", "CL", "CM", "CS", "CH", "DF", "DG", "GT", "GR",
    "HG", "JC", "MC", "MN", "MS", "NT", "NL", "OC", "PL", "QT", "QR", "SP",
    "SL", "SR", "TC", "TS", "TL", "VZ", "YN", "ZS", "NE"
}

CLABE_WEIGHTS = [3, 7, 1] * 6


def validate_curp(value: str) -> tuple[bool, list[str]]:
    if not CURP_REGEX.match(value):
        return False, ["Formato de CURP inválido."]
    # Validación básica: entidad válida y sexo válido
    state_code = value[11:13]
    if state_code not in STATE_CODES:
        return False, ["Entidad CURP inválida."]
    if value[10] not in {"H", "M"}:
        return False, ["Sexo CURP inválido."]
    return True, []


def validate_rfc(value: str) -> tuple[bool, list[str]]:
    if not RFC_REGEX.match(value):
        return False, ["Formato de RFC inválido."]
    return True, []


def validate_rfc_homoclave(value: str) -> tuple[bool, list[str]]:
    if not RFC_REGEX.match(value):
        return False, ["Formato de RFC inválido."]
    return True, []


def validate_nss(value: str) -> tuple[bool, list[str]]:
    if not NSS_REGEX.match(value):
        return False, ["Formato de NSS inválido."]
    return True, []


def validate_clabe(value: str) -> tuple[bool, list[str]]:
    if not CLABE_REGEX.match(value):
        return False, ["Formato de CLABE inválido."]

    digits = [int(d) for d in value]
    total = 0
    for i in range(17):
        total += (digits[i] * CLABE_WEIGHTS[i]) % 10
    check_digit = (10 - (total % 10)) % 10
    if check_digit != digits[17]:
        return False, ["Dígito verificador de CLABE inválido."]
    return True, []


def validate_date(value: str) -> tuple[bool, list[str]]:
    match = DATE_REGEX.match(value)
    if not match:
        return False, ["Formato de fecha inválido."]
    day, month, year = map(int, match.groups())
    try:
        datetime(year, month, day)
    except ValueError:
        return False, ["Fecha inválida."]
    return True, []


def validate_sex(value: str) -> tuple[bool, list[str]]:
    if not SEX_REGEX.match(value.strip().upper()):
        return False, ["Sexo inválido."]
    return True, []


def validate_bank(value: str) -> tuple[bool, list[str]]:
    if not BANK_REGEX.match(value.strip().upper()):
        return False, ["Banco inválido."]
    return True, []


def validate_folio(value: str) -> tuple[bool, list[str]]:
    if not FOLIO_REGEX.match(value.strip().upper()):
        return False, ["Folio inválido."]
    return True, []


def validate_cp(value: str) -> tuple[bool, list[str]]:
    if not CP_REGEX.match(value.strip()):
        return False, ["CP inválido."]
    return True, []


def validate_state_code(value: str) -> tuple[bool, list[str]]:
    code = value.strip().upper()
    if " - " in code:
        code = code.split(" - ", 1)[0].strip()
    if code not in STATE_CODES:
        if code in {
            "AGUASCALIENTES", "BAJA CALIFORNIA", "BAJA CALIFORNIA SUR", "CAMPECHE",
            "COAHUILA", "COLIMA", "CHIAPAS", "CHIHUAHUA", "CIUDAD DE MEXICO", "DURANGO",
            "GUANAJUATO", "GUERRERO", "HIDALGO", "JALISCO", "MEXICO", "MICHOACAN",
            "MORELOS", "NAYARIT", "NUEVO LEON", "OAXACA", "PUEBLA", "QUERETARO",
            "QUINTANA ROO", "SAN LUIS POTOSI", "SINALOA", "SONORA", "TABASCO",
            "TAMAULIPAS", "TLAXCALA", "VERACRUZ", "YUCATAN", "ZACATECAS",
            "NACIDO EN EL EXTRANJERO"
        }:
            return True, []
        return False, ["Entidad inv??lida."]
    return True, []


def validate_clave_elector(value: str) -> tuple[bool, list[str]]:
    if not CLAVE_ELECTOR_REGEX.match(value.strip().upper()):
        return False, ["Clave de elector inválida."]
    return True, []


def validate_seccion(value: str) -> tuple[bool, list[str]]:
    if not SECCION_REGEX.match(value.strip()):
        return False, ["Sección inválida."]
    return True, []


def validate_person_name(value: str) -> tuple[bool, list[str]]:
    if not NAME_TEXT_REGEX.match(value.strip().upper()):
        return False, ["Nombre inválido."]
    return True, []


def validate_generic_text(value: str) -> tuple[bool, list[str]]:
    if not GENERIC_TEXT_REGEX.match(value.strip().upper()):
        return False, ["Texto inválido."]
    return True, []


def validate_vigencia(value: str) -> tuple[bool, list[str]]:
    text = value.strip()
    if not VIGENCIA_REGEX.match(text):
        return False, ["Vigencia inv?lida."]
    if re.fullmatch(r"\d{4}", text):
        year = int(text)
        if year < 1990 or year > 2100:
            return False, ["Vigencia fuera de rango."]
    return True, []
