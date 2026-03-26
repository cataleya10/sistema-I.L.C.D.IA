"""
Bancario Extractor — extractor dedicado para Estados de Cuenta y Comprobantes Bancarios

Campos que extrae:
  - clabe      (18 dígitos — clave bancaria estandarizada)
  - cuenta     (número de cuenta 10–16 dígitos)
  - banco      (nombre de la institución bancaria)
  - titular    (nombre del titular de la cuenta)
  - rfc        (RFC del titular, si aparece)
  - fecha_corte
  - periodo

Reglas específicas del documento bancario:
  - La CLABE de 18 dígitos tiene prioridad sobre números de cuenta cortos
  - El banco se puede inferir de los primeros 3 dígitos de la CLABE (código de banco BANXICO)
  - Evita confundir folio de operación (7–9 dígitos) con número de cuenta
  - El titular puede aparecer después de "CLIENTE:", "A NOMBRE DE:", "BENEFICIARIO:"

Delega al motor interno _extract_financial_from_boxes.
"""

from typing import Any

from app.pipelines.extract import extract_fields as _extract_fields
from app.pipelines.extract.extractors import _extract_financial_from_boxes

# Campos que este extractor debe devolver
EXPECTED_FIELDS = frozenset({
    "clabe", "cuenta", "banco", "titular", "rfc", "fecha_corte", "periodo",
})

DOCUMENT_TYPE = "DATOS_BANCARIOS"

# Mapa de prefijos CLABE → banco (primeros 3 dígitos = código BANXICO)
_CLABE_BANCO_MAP: dict[str, str] = {
    "002": "BBVA BANCOMER",
    "006": "BANCOMEXT",
    "009": "BANOBRAS",
    "012": "HSBC",
    "014": "SANTANDER",
    "021": "HSBC",
    "030": "BAJÍO",
    "032": "IXE",
    "036": "INBURSA",
    "037": "MULTIVA",
    "042": "MIFEL",
    "044": "SCOTIABANK",
    "058": "BANREGIO",
    "059": "INVEX",
    "060": "BANSI",
    "062": "AFIRME",
    "072": "BANORTE",
    "102": "ABN AMRO",
    "103": "AMERICAN EXPRESS",
    "106": "BAMSA",
    "108": "TOKYO",
    "110": "JP MORGAN",
    "112": "BANSÍ",
    "113": "VE POR MÁS",
    "116": "ING",
    "124": "DEUTSCHE",
    "126": "CREDIT SUISSE",
    "127": "AZTECA",
    "128": "AUTOFIN",
    "129": "BARCLAYS",
    "130": "COMPARTAMOS",
    "132": "AKALA",
    "133": "WALMART",
    "135": "NAFIN",
    "136": "INTERBANCO",
    "137": "BANCOPPEL",
    "138": "ABC CAPITAL",
    "139": "UBS BANK",
    "140": "CONSUBANCO",
    "141": "VOLKSWAGEN",
    "143": "CIBanco",
    "145": "BBASE",
    "147": "BANKAOOL",
    "148": "PAGATODO",
    "149": "INMOBILIARIO MEXICANO",
    "155": "ICBC",
    "156": "SABADELL",
    "166": "BaBien",
    "168": "HIPOTECARIA FEDERAL",
    "600": "MONEXCB",
    "601": "GBM",
    "602": "MASARI",
    "605": "VALUÉ",
    "606": "FONDIVISA",
    "607": "BASE",
    "608": "FINCOMÚN",
    "610": "HMS",
    "611": "ACTINVER",
    "613": "MULTIVA CBOLSA",
    "616": "FINAMEX",
    "617": "VALORE",
    "618": "ÚNICA",
    "619": "MAPFRE",
    "620": "PROFUTURO",
    "621": "CB ACTINVER",
    "622": "OACTIN",
    "623": "OACTIN",
    "626": "CBDEUTSCHE",
    "627": "ZURICHVI",
    "628": "ZURICHVI",
    "629": "SU CASITA",
    "630": "CB INTERCAM",
    "631": "CI BOLSA",
    "632": "BULLTICK CB",
    "633": "HDI SEGUROS",
    "636": "HDI SEGUROS",
    "637": "ORDER",
    "638": "AKALA",
    "640": "CB JP MORGAN",
    "642": "REFORMA",
    "646": "STP",
    "648": "EVER CORE",
    "649": "SKANDIA",
    "651": "SEGUROSMTY",
    "652": "ASEA",
    "653": "KUSPIT",
    "655": "SOFIEXPRESS",
    "656": "UNAGRA",
    "659": "ASP INTEGRA OPC",
    "670": "LIBERTAD",
    "674": "AXA",
    "677": "CAJA POP MEXICANA",
    "679": "FND",
    "684": "TRANSFER",
    "685": "FONDO (FIRA)",
    "686": "INVERCAP",
    "689": "FDEAM",
    "699": "CoDi Valida",
    "706": "ARCUS",
    "710": "TELECOMUNICACIONES",
    "722": "MERCADO PAGO",
    "723": "CUENCA",
    "728": "SPIN BY OXXO",
    "730": "NVIO",
    "732": "NVIO",
    "733": "BBVA WALLET",
    "734": "TRANSFER",
    "736": "HDRX",
    "741": "BIMBO NET",
    "743": "TRANSFER",
    "744": "TRANSFER",
    "745": "BIMBO NET",
    "706": "ARCUS",
    "812": "CAJA SPEI",
    "814": "INDEVAL",
    "846": "STP",
    "899": "CLABE TRANSITORIA",
}


async def extract(
    ocr_text: str,
    ocr_boxes: list[dict[str, Any]] | None = None,
    raw_text: str = "",
    filename: str | None = None,
) -> list[dict[str, Any]]:
    """
    Extrae campos de un Estado de Cuenta o Comprobante Bancario.

    Args:
        ocr_text:  Texto completo resultado del OCR.
        ocr_boxes: Lista de bounding boxes del OCR (mejora CLABE y cuenta).
        raw_text:  Texto del layer nativo del PDF.
        filename:  Nombre del archivo.

    Returns:
        Lista de campos extraídos. Campos esperados:
        clabe, cuenta, banco, titular, rfc, fecha_corte, periodo.
    """
    fields = await _extract_fields(
        document_type=DOCUMENT_TYPE,
        ocr_text=ocr_text,
        ocr_boxes=ocr_boxes,
        raw_text=raw_text,
        filename=filename,
    )

    # Si el banco no fue detectado, intentar inferirlo desde la CLABE
    _enrich_banco_from_clabe(fields)

    return fields


def extract_from_boxes(ocr_boxes: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Extracción directa desde bounding boxes.
    Útil para evaluación rápida y pruebas unitarias.

    Returns:
        Dict con los valores encontrados {campo: valor}.
    """
    return _extract_financial_from_boxes(ocr_boxes)


def infer_banco_from_clabe(clabe: str) -> str | None:
    """
    Infiere el nombre del banco a partir de los primeros 3 dígitos de la CLABE.

    Args:
        clabe: CLABE de 18 dígitos.

    Returns:
        Nombre del banco o None si el código no está en el catálogo.
    """
    if not clabe or len(clabe) < 3:
        return None
    return _CLABE_BANCO_MAP.get(clabe[:3])


def _enrich_banco_from_clabe(fields: list[dict[str, Any]]) -> None:
    """Rellena el campo 'banco' desde la CLABE si banco está vacío. In-place."""
    existing = {f.get("key"): f for f in fields}
    banco_field = existing.get("banco")
    clabe_field = existing.get("clabe")

    if clabe_field and (not banco_field or not banco_field.get("value")):
        clabe_val = clabe_field.get("value", "")
        inferred = infer_banco_from_clabe(str(clabe_val))
        if inferred:
            if banco_field:
                banco_field["value"] = inferred
                banco_field["confidence"] = max(banco_field.get("confidence", 0), 0.7)
            else:
                from app.pipelines.extract.common import _make_field
                fields.append(_make_field("banco", "Banco", inferred, []))


def get_expected_fields() -> frozenset[str]:
    """Devuelve el conjunto de campos que este extractor debe producir."""
    return EXPECTED_FIELDS
