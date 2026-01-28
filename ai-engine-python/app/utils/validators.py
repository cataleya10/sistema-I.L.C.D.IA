import re
from datetime import datetime

CURP_REGEX = re.compile(r"^[A-Z][AEIOUX][A-Z]{2}\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])[HM][A-Z]{5}[A-Z0-9]\d$")
RFC_REGEX = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")
NSS_REGEX = re.compile(r"^\d{11}$")
CLABE_REGEX = re.compile(r"^\d{18}$")
DATE_REGEX = re.compile(r"^(\d{2})[/-](\d{2})[/-](\d{4})$")

CLABE_WEIGHTS = [3, 7, 1] * 6


def validate_curp(value: str) -> tuple[bool, list[str]]:
    if not CURP_REGEX.match(value):
        return False, ["Formato de CURP inválido."]
    return True, []


def validate_rfc(value: str) -> tuple[bool, list[str]]:
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
