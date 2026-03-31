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

import logging
import re
from typing import Any

from app.pipelines.extract import extract_fields as _extract_fields
from app.pipelines.extract.extractors import _extract_financial_from_boxes

logger = logging.getLogger(__name__)

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
    pdf_tables: list[list[list[str]]] | None = None,
) -> list[dict[str, Any]]:
    """
    Extrae campos de un Estado de Cuenta o Comprobante Bancario.

    Args:
        ocr_text:   Texto completo resultado del OCR.
        ocr_boxes:  Lista de bounding boxes del OCR (mejora CLABE y cuenta).
        raw_text:   Texto del layer nativo del PDF.
        filename:   Nombre del archivo.
        pdf_tables: Tablas detectadas por el preprocesador.

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
        pdf_tables=pdf_tables,
    )

    # Enriquecimiento: inferir banco desde CLABE y completar campos con
    # etiquetas específicas de banco (Santander, Banorte, BBVA, etc.)
    _enrich_banco_from_clabe(fields)
    _enrich_bancario_fields(fields, ocr_text=ocr_text, raw_text=raw_text, ocr_boxes=ocr_boxes or [])

    _log_coverage(fields, filename)
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


# ─── Patrones de enriquecimiento por etiqueta de banco ───────────────────────

# Titular — etiquetas usadas por distintos bancos
_TITULAR_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?:NOMBRE\s+DEL?\s+CLIENTE|CLIENTE|TITULAR|A\s+NOMBRE\s+DE|BENEFICIARIO)[:\s]+([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ\s,\.]{4,80}?)(?:\n|\s{2,}|RFC|CLABE|CUENTA|$)", re.IGNORECASE),
]

# Fecha de corte — múltiples etiquetas
_FECHA_CORTE_PATTERNS: list[re.Pattern] = [
    re.compile(r"FECHA\s+DE\s+CORTE[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.IGNORECASE),
    re.compile(r"CORTE[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.IGNORECASE),
    re.compile(r"FECHA\s+CORTE[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", re.IGNORECASE),
    re.compile(r"AL\s+(\d{1,2}\s+DE\s+[A-ZÁÉÍÓÚÜÑ]{4,}\s+(?:DE\s+)?\d{4})", re.IGNORECASE),
]

# Periodo / rango del estado de cuenta
_PERIODO_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"PERIODO[:\s]+(?:DEL?\s+)?(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+(?:AL?|A)\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"DEL?\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+(?:AL?|A)\s+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(\d{1,2}\s+DE\s+[A-ZÁÉÍÓÚÜÑ]{4,}\s+(?:DE\s+)?\d{4})\s+(?:AL?|A)\s+(\d{1,2}\s+DE\s+[A-ZÁÉÍÓÚÜÑ]{4,}\s+(?:DE\s+)?\d{4})",
        re.IGNORECASE,
    ),
]

# Cuenta (etiquetas alternativas)
_CUENTA_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?:N[UÚ]MERO\s+DE\s+CUENTA|NO[.:]?\s*DE\s*CUENTA|CUENTA)[:\s]+(\d{10,16})\b", re.IGNORECASE),
    re.compile(r"CUENTA\s+SANTANDER[:\s]+(\d{10,16})\b", re.IGNORECASE),
]

# RFC del titular (persona física o moral)
_RFC_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bRFC[:\s]+([A-Z&]{3,4}\d{6}[A-Z0-9]{3})\b", re.IGNORECASE),
    re.compile(r"R\.F\.C\.[:\s]+([A-Z&]{3,4}\d{6}[A-Z0-9]{3})\b", re.IGNORECASE),
]


def _enrich_bancario_fields(
    fields: list[dict[str, Any]],
    ocr_text: str,
    raw_text: str,
    ocr_boxes: list[dict[str, Any]],
) -> None:
    """
    Complementa campos bancarios que el pipeline de boxes puede no detectar
    cuando las etiquetas varían por banco (Santander, Banorte, BBVA, etc.).
    Opera in-place sobre fields.

    Usa raw_text como fuente primaria (PDFs con capa de texto nativa).
    """
    from app.pipelines.extract.common import _make_field

    # low_conf: campos que el orchestrator pudo haber añadido con confidence < 0.7
    # → el enriquecimiento puede mejorarlos si encuentra un match más sólido.
    _LOW_CONF_THRESHOLD = 0.7
    existing: dict[str, dict] = {f.get("key"): f for f in fields if f.get("value")}
    existing_keys = set(existing.keys())
    primary = raw_text.strip() if raw_text and raw_text.strip() else ocr_text
    secondary = ocr_text if primary is raw_text and ocr_text != raw_text else ""

    def _try(patterns: list[re.Pattern], key: str, label: str, confidence: float = 0.78, group: int = 1) -> bool:
        # Si ya existe con buena confianza, no tocar
        if key in existing_keys and existing[key].get("confidence", 1.0) >= _LOW_CONF_THRESHOLD:
            return False
        for src in (primary, secondary):
            if not src:
                continue
            for pat in patterns:
                m = pat.search(src)
                if m:
                    val = m.group(group).strip()
                    if val:
                        if key in existing_keys:
                            # Actualizar el campo existente de baja confianza
                            existing[key]["value"] = val
                            existing[key]["confidence"] = confidence
                            logger.debug("bancario enrich (override): %s='%s'", key, val)
                        else:
                            fields.append(_make_field(key, label, val, ocr_boxes, confidence=confidence))
                            existing_keys.add(key)
                            logger.debug("bancario enrich: %s='%s'", key, val)
                        return True
        return False

    _try(_TITULAR_PATTERNS, "titular", "Titular", confidence=0.78)
    _try(_FECHA_CORTE_PATTERNS, "fecha_corte", "Fecha de corte", confidence=0.82)
    _try(_CUENTA_PATTERNS, "cuenta", "Cuenta", confidence=0.80)
    _try(_RFC_PATTERNS, "rfc", "RFC", confidence=0.82)

    # Periodo — rango de fechas
    _period_sufficient = (
        "periodo" in existing_keys
        and existing.get("periodo", {}).get("confidence", 1.0) >= _LOW_CONF_THRESHOLD
    )
    if not _period_sufficient:
        for src in (primary, secondary):
            if not src:
                continue
            for pat in _PERIODO_PATTERNS:
                m = pat.search(src)
                if m:
                    if m.lastindex and m.lastindex >= 2:
                        val = f"{m.group(1).strip()} al {m.group(2).strip()}"
                    else:
                        val = m.group(1).strip()
                    if "periodo" in existing_keys:
                        existing["periodo"]["value"] = val
                        existing["periodo"]["confidence"] = 0.80
                        logger.debug("bancario enrich (override): periodo='%s'", val)
                    else:
                        fields.append(_make_field("periodo", "Periodo", val, ocr_boxes, confidence=0.80))
                        existing_keys.add("periodo")
                        logger.debug("bancario enrich: periodo='%s'", val)
                    break
            if "periodo" in existing_keys:
                break


def _log_coverage(fields: list[dict[str, Any]], filename: str | None) -> None:
    """Emite un log INFO con cobertura de campos encontrados."""
    found = {f.get("key") for f in fields if f.get("value")}
    missing = EXPECTED_FIELDS - found
    pct = int(100 * len(found & EXPECTED_FIELDS) / len(EXPECTED_FIELDS))
    if missing:
        logger.info(
            "bancario [%s] cobertura %d%% — faltan: %s",
            filename or "?", pct, ", ".join(sorted(missing)),
        )
    else:
        logger.info("bancario [%s] cobertura 100%%", filename or "?")


def get_expected_fields() -> frozenset[str]:
    """Devuelve el conjunto de campos que este extractor debe producir."""
    return EXPECTED_FIELDS
