"""
Fuente única de verdad para todos los patrones regex del sistema.

Importa desde aquí en cualquier módulo que necesite detectar
RFC, CURP, NSS, CLABE, fechas, folios, montos o cuentas bancarias.
"""

from __future__ import annotations

import re

# ──────────────────────────────────────────────────────────────────────────────
# 1. IDENTIFICADORES PERSONALES
# ──────────────────────────────────────────────────────────────────────────────

# CURP — 18 caracteres con validación de mes/día
CURP_PATTERN = re.compile(
    r"\b[A-Z][AEIOUX][A-Z]{2}"          # 4 letras iniciales
    r"\d{2}(?:0[1-9]|1[0-2])"           # año + mes (01-12)
    r"(?:0[1-9]|[12]\d|3[01])"          # día  (01-31)
    r"[HM]"                              # sexo
    r"[A-Z]{5}"                          # entidad + consonantes
    r"[A-Z0-9]\d\b"                      # diferenciador + dígito verificador
)

# RFC — persona física (13 chars) o moral (12 chars)
RFC_PATTERN = re.compile(r"\b[A-Z&]{3,4}\d{6}[A-Z0-9]{3}\b")

# Alias explícito que deja claro que incluye homoclave
RFC_WITH_HOMOCLAVE = RFC_PATTERN

# NSS — Número de Seguro Social (11 dígitos)
NSS_PATTERN = re.compile(r"\b\d{11}\b")

# Clave de elector INE — 6 letras + 8 dígitos + H/M + 3 dígitos
CLAVE_ELECTOR_PATTERN = re.compile(r"\b[A-Z]{6}\d{8}[HM]\d{3}\b")

# ──────────────────────────────────────────────────────────────────────────────
# 2. DATOS BANCARIOS
# ──────────────────────────────────────────────────────────────────────────────

# CLABE interbancaria — 18 dígitos
CLABE_PATTERN = re.compile(r"\b\d{18}\b")

# Número de cuenta bancaria — 10-16 dígitos
ACCOUNT_PATTERN = re.compile(r"\b\d{10,16}\b")

# CLABE con etiqueta contextual (captura grupo 1)
CLABE_LABELED_PATTERN = re.compile(
    r"(?:CUENTA[/\s]*CLABE\s*BENEFICIARIO|CUENTA\s*DE\s*RETIRO"
    r"|CUENTA\s*CLABE|NO\.\s*CUENTA\s*BENEFICIARIO)[:\s]+(\d{18})",
    re.IGNORECASE,
)

# Cuenta ordenante con etiqueta contextual (captura grupo 1)
CUENTA_ORDENANTE_LABELED_PATTERN = re.compile(
    r"(?:CUENTA[/\s]*CLABE\s*ORDENANTE|CUENTA\s*DE\s*DEP[OÓ]SITO"
    r"|CUENTA\s*CARGO[:\s]+|N[UÚ]MERO\s*DE\s*CONTRATO\s*ENLACE)[:\s]+(\d{10,13})",
    re.IGNORECASE,
)

# ──────────────────────────────────────────────────────────────────────────────
# 3. RFC CONTEXTUAL
# ──────────────────────────────────────────────────────────────────────────────

# RFC del ordenante/empresa con etiqueta (captura grupo 1)
RFC_ORDENANTE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"RFC\s*O\s*CURP\s*DEL\s*ORDENANTE[:\s]+([A-Z&]{3,4}\d{6}[A-Z0-9]{3,4})", re.IGNORECASE),
    re.compile(r"RFC\s*ORDENANTE[:\s]+([A-Z&]{3,4}\d{6}[A-Z0-9]{3,4})", re.IGNORECASE),
    re.compile(r"RFC\s*(?:DEL\s*ORDENANTE|EMPRESA)[:\s]+([A-Z&]{3,4}\d{6}[A-Z0-9]{3,4})", re.IGNORECASE),
]

# RFC genérico / institucional que se debe ignorar en la búsqueda de ordenante
RFC_EXCLUIR: frozenset[str] = frozenset({
    "XAXX010101000",   # RFC genérico operaciones al público en general
    "XEXX010101000",   # RFC genérico extranjeros
    "BMN930209927",    # Banorte
    "BMN9302099Z7",    # Banorte (variante)
})

# ──────────────────────────────────────────────────────────────────────────────
# 4. FECHAS
# ──────────────────────────────────────────────────────────────────────────────

# Fecha estricta dd/mm/yyyy o dd-mm-yyyy
DATE_PATTERN = re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b")

# Fecha flexible: numérica o con mes en texto ('06/feb./2026', '6 de enero 2026')
DATE_FLEX_PATTERN = re.compile(
    r"\b(?:"
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"               # dd/mm/aaaa
    r"|"
    r"\d{1,2}(?:\s+|[-/])[A-Z]{3,9}(?:\s+|[-/])\d{2,4}"  # dd mes aaaa
    r")\b",
    re.IGNORECASE,
)

# Abreviaturas de meses en español → número de 2 dígitos
MESES_ES: dict[str, str] = {
    "ENE": "01", "FEB": "02", "MAR": "03", "ABR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AGO": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DIC": "12",
}


def normalize_date(fecha: str) -> str:
    """
    Normaliza una fecha a formato dd/mm/yyyy.

    Ejemplos:
        '06/feb./2026'  ->  '06/02/2026'
        '06-02-2026'    ->  '06/02/2026'
        '15-MAR-2025'   ->  '15/03/2025'
    """
    fecha = fecha.strip().upper().replace(".", "")
    for mes_es, mes_num in MESES_ES.items():
        fecha = fecha.replace(f"/{mes_es}/", f"/{mes_num}/")
        fecha = fecha.replace(f"-{mes_es}-", f"-{mes_num}-")
    # Normaliza separador a /
    fecha = re.sub(r"(\d{1,2})-(\d{2})-(\d{4})", r"\1/\2/\3", fecha)
    return fecha


# ──────────────────────────────────────────────────────────────────────────────
# 5. MONTOS Y CÓDIGOS POSTALES
# ──────────────────────────────────────────────────────────────────────────────

# Monto monetario: 1,234.56 / 1234.56 / 1.234,56
AMOUNT_PATTERN = re.compile(r"\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\b")

# Código postal mexicano — 5 dígitos
CP_PATTERN = re.compile(r"\b\d{5}\b")

# ──────────────────────────────────────────────────────────────────────────────
# 6. FOLIOS Y REFERENCIAS
# ──────────────────────────────────────────────────────────────────────────────

# Folio / número de acta / referencia alfanumérica
FOLIO_PATTERN = re.compile(
    r"(?:FOLIO|N[UÚ]MERO\s*DE\s*ACTA|REFERENCIA|REF)[:\s]+([A-Z0-9/\-]+)",
    re.IGNORECASE,
)

# Clave de rastreo SPEI (30 caracteres numéricos típico)
CLAVE_RASTREO_PATTERN = re.compile(r"\b\d{30}\b")

# ──────────────────────────────────────────────────────────────────────────────
# 7. NOMBRES
# ──────────────────────────────────────────────────────────────────────────────

# Nombre en mayúsculas: 2+ palabras de 2+ letras
NAME_PATTERN = re.compile(r"\b[A-Z]{2,}(?:\s+[A-Z]{2,}){1,7}\b")

# ──────────────────────────────────────────────────────────────────────────────
# 8. CURP — UTILIDADES DE CORRECCIÓN OCR
# ──────────────────────────────────────────────────────────────────────────────

# Posiciones (0-base) que deben ser letras o dígitos en un CURP de 18 chars
_CURP_LETTER_POS: frozenset[int] = frozenset({0, 1, 2, 3, 10, 11, 12, 13, 14, 15, 16})
_CURP_DIGIT_POS: frozenset[int] = frozenset({4, 5, 6, 7, 8, 9, 17})

# Confusiones OCR típicas
_CURP_DIGIT_TO_LETTER: dict[str, str] = {"0": "O", "1": "I", "5": "S", "8": "B"}
_CURP_LETTER_TO_DIGIT: dict[str, str] = {"O": "0", "I": "1", "L": "1", "S": "5", "B": "8"}


def fix_curp_ocr(candidate: str) -> str:
    """Corrige confusiones OCR en un candidato de 18 caracteres que podría ser CURP."""
    if len(candidate) != 18:
        return candidate
    chars = list(candidate.upper())
    for i, ch in enumerate(chars):
        if i in _CURP_LETTER_POS and ch in _CURP_DIGIT_TO_LETTER:
            chars[i] = _CURP_DIGIT_TO_LETTER[ch]
        elif i in _CURP_DIGIT_POS and ch in _CURP_LETTER_TO_DIGIT:
            chars[i] = _CURP_LETTER_TO_DIGIT[ch]
    return "".join(chars)


def search_curp(text: str) -> str | None:
    """
    Busca un CURP válido en ``text``.
    Si no hay match directo intenta corrección OCR sobre candidatos de 18 chars.
    """
    m = CURP_PATTERN.search(text.upper())
    if m:
        return m.group(0)
    for candidate in re.findall(r"[A-Z0-9]{18}", text.upper()):
        fixed = fix_curp_ocr(candidate)
        if CURP_PATTERN.fullmatch(fixed):
            return fixed
    return None
