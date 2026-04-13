"""
Clasificador de tipo de documento.

Flujo de decisión:
  1. Motor de reglas por filename (alta precisión, no necesita texto)
  2. Motor de reglas por contenido OCR (patrones y marcadores)
  3. Modelo Naive Bayes (estadístico, solo si existe el modelo entrenado)
  4. GENERICO como fallback

Cómo agregar un nuevo tipo de documento:
  1. Agregar sus marcadores de filename en _FILENAME_RULES
  2. Agregar sus marcadores de contenido en _CONTENT_RULES
  3. Agregar sus hard markers en _HARD_MARKERS
  4. No tocar la lógica de classify_document
"""

import json
import logging
import math
import os
import re
import unicodedata
from typing import NamedTuple

logger = logging.getLogger(__name__)

MODEL_PATH = os.getenv(
    "DOC_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "..", "models", "doc_type_nb.json"),
)

# ─── Normalización ────────────────────────────────────────────────────────────

def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.upper()
    text = re.sub(r"[^A-Z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokenize(text: str) -> list[str]:
    return [tok for tok in _normalize_text(text).split() if len(tok) > 1]


# ─── Modelo Naive Bayes ───────────────────────────────────────────────────────

def _load_model():
    try:
        if not os.path.exists(MODEL_PATH):
            return None
        with open(MODEL_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logger.warning("Failed to load classification model from %s", MODEL_PATH, exc_info=True)
        return None


def _predict_nb(model, text: str):
    tokens = _tokenize(text)
    if not tokens:
        return None, 0.0
    classes = model.get("classes", [])
    class_counts = model.get("class_counts", {})
    token_counts = model.get("token_counts", {})
    vocab = set(model.get("vocab", []))
    total_docs = max(1, model.get("total_docs", 1))
    vocab_size = max(1, len(vocab))

    if not classes:
        return None, 0.0

    # Log-probabilidad para cada clase
    log_scores: dict[str, float] = {}
    for cls in classes:
        prior = (class_counts.get(cls, 0) + 1) / (total_docs + len(classes))
        score = math.log(prior)
        cls_tokens = token_counts.get(cls, {})
        cls_total = sum(cls_tokens.values()) + vocab_size
        for tok in tokens:
            if tok not in vocab:
                continue
            count = cls_tokens.get(tok, 0) + 1
            score += math.log(count / cls_total)
        log_scores[cls] = score

    best_cls = max(log_scores, key=log_scores.__getitem__)

    # Softmax → confianza real [0, 0.95]
    max_score = log_scores[best_cls]
    exp_scores = {cls: math.exp(s - max_score) for cls, s in log_scores.items()}
    total_exp = sum(exp_scores.values())
    confidence = exp_scores[best_cls] / total_exp if total_exp > 0 else 0.0
    confidence = min(confidence, 0.95)  # NB tiende a sobre-polarizarse

    return best_cls, confidence


# ─── Motor de reglas ──────────────────────────────────────────────────────────
#
# Cada regla tiene:
#   doc_type   → tipo de documento si hay match
#   confidence → confianza retornada
#   text_any   → match si CUALQUIERA de estas frases está en el texto normalizado
#   compact_any→ match si CUALQUIERA de estas frases está en el texto sin espacios
#   name_any   → match si CUALQUIERA de estos tokens está en el nombre de archivo normalizado
#   name_all   → match si TODOS estos tokens están en el nombre de archivo normalizado
#   name_last  → match si el ÚLTIMO token del nombre es este valor
#   custom     → función (text, compact, name) → bool para condiciones compuestas
#
# Las reglas se evalúan EN ORDEN; la primera que hace match gana.

class _Rule(NamedTuple):
    doc_type: str
    confidence: float
    text_any: tuple[str, ...] = ()
    compact_any: tuple[str, ...] = ()
    name_any: tuple[str, ...] = ()
    name_all: tuple[str, ...] = ()
    name_last: str | None = None
    custom: object = None  # Callable[[str, str, str], bool] | None


def _rule_matches(rule: _Rule, text: str, compact: str, name: str) -> bool:
    """Evalúa si una regla hace match con el contexto dado."""
    name_parts = name.split()

    if rule.name_last and (not name_parts or name_parts[-1] != rule.name_last):
        pass
    elif rule.name_last:
        return True

    if rule.name_any and any(tok in name for tok in rule.name_any):
        return True

    if rule.name_all and all(tok in name for tok in rule.name_all):
        return True

    if rule.text_any and any(m in text for m in rule.text_any):
        return True

    if rule.compact_any and any(m in compact for m in rule.compact_any):
        return True

    if rule.custom is not None and rule.custom(text, compact, name):  # type: ignore[operator]
        return True

    return False


# ── Constantes de markers (module-level, fáciles de extender) ─────────────────

_BANK_NAMES = (
    "BBVA", "BANAMEX", "BANCOMER", "SANTANDER", "SCOTIABANK", "HSBC", "BANORTE",
)

_NOMINA_TEXT = (
    "RECIBO DE NOMINA",
    "RECIBO DE PAGO DE NOMINA",
    "COMPROBANTE DE NOMINA",
    "COMPROBANTE DE PAGO DE NOMINA",
    "DESGLOSE DE NOMINA",
    "TOTAL PERCEPCIONES",
    "TOTAL DEDUCCIONES",
    "NETO A PAGAR",
    "NETO PAGAR",
    "SUELDO BASE",
    "SUELDO DIARIO",
    "DIAS TRABAJADOS",
    "DIAS HABILES",
    "INFONAVIT",
    "FONACOT",
    "QUINCENA",
)
_NOMINA_COMPACT = (
    "RECIBODENOMINA",
    "RECIBODEPAGODEDOMINA",
    "COMPROBANTEDENOMINA",
    "TOTALPERCEPCIONES",
    "TOTALDEDUCCIONES",
    "NETOAPAGAR",
    "NETOPAGAR",
    "SUELDOBASE",
    "SUELDOMENSUAL",
    "DIASTRABAJOS",
    "INFONAVIT",
    "FONACOT",
)
_NOMINA_FILENAME = (
    "RECIBO DE NOMINA", "RECIBO NOMINA", "RECIBODENOMINA",
    "COMPROBANTE PAGO NOMINA", "COMPROBANTE NOMINA",
)
_DISPERSION_FILENAME = (
    "DISPERSION", "ARCHIVO DE PAGOS", "REPORTE DE TRANSMISION", "REPORTE TRANSMISION",
)
_PAYMENT_FILENAME = ("PAGO", "TRANSFERENCIA", "SPEI", "NOMINA")
_BANK_FILENAME = (
    "ESTADO DE CUENTA", "ESTADO CUENTA", "ESTADODECUENTA",
    "CLABE", "BBVA", "BANAMEX", "BANCOMER", "SANTANDER", "SCOTIABANK", "HSBC", "BANORTE",
)
_SERVICE_FILENAME = (
    "DOMICILIO", "COMPROBANTE", "RECIBO", "CFE", "TELMEX",
    "TELCEL", "TOTALPLAY", "IZZI", "MEGACABLE",
)
_DISPERSION_TEXT = (
    "REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS",
    "REPORTE DE TRANSMISION DE ARCHIVO DE PAGO",
    "DISPERSION DE PAGO DE NOMINA",
    "DISPERSION DE NOMINA",
    "ARCHIVO DE PAGOS",
    "ARCHIVO DE PAGO DE NOMINA",
    "RESULTADO DE ARCHIVO DE PAGOS",
    "REPORTE DE DISPERSION",
    "REPORTE DE TRANSMISION",
    # Scotiabank: "Transferencia de Archivos" / "Transferencia de Archivo de Pagos"
    "TRANSFERENCIA DE ARCHIVOS",
    "TRANSFERENCIA DE ARCHIVO DE PAGOS",
    "TRANSFERENCIA DE ARCHIVO DE PAGO",
    # Banorte / genérico
    "PAGO DE NOMINA MASIVO",
    "PAGO MASIVO",
    "LAYOUT DE PAGOS",
    "LAYOUT DE DISPERSION",
)
_DISPERSION_COMPACT = (
    "REPORTEDETRANSMISIONDEARCHIVODEPAGOS",
    "REPORTEDETRANSMISIONDEARCHIVODEPAGO",
    "DISPERSIONDEPAGODENOMINA",
    "DISPERSIONDENOMINA",
    "ARCHIVODEPAGOS",
    "ARCHIVODEPAGODEDOMINA",
    "RESULTADODEARCHIVODEPAGOS",
    "REPORTEDEDISPERSION",
    "REPORTEDETRANSMISION",
    # Scotiabank
    "TRANSFERENCIADEARCHIVOS",
    "TRANSFERENCIADEARCHIVODEPAGOS",
    "TRANSFERENCIADEARCHIVODEPAGO",
    # Genérico
    "PAGONOMASIVOMASIVO",
    "PAGOMASIVO",
    "LAYOUTDEPAGOS",
    "LAYOUTDEDISPERSION",
)
_PAYMENT_TEXT = (
    "PAGO DE NOMINA",
    "REPORTE DE OPERACIONES",
    "COMPROBANTE DE LA OPERACION",
    "RESULTADO DEL TRASPASO",
    "TRASPASOS A TERCEROS",
    "TRASPASOS A OTROS BANCOS",
    "CLAVE RASTREO",
    "DATOS DEL BENEFICIARIO",
    "TIPO DE MOVIMIENTO (PAGO)",
    "ABONO NOMINA",
    "TRANSFERENCIA SPEI",
    "SPEI ENVIADO",
    "SPEI RECIBIDO",
    "FOLIO SPEI",
    "COMPROBANTE DE TRANSFERENCIA",
    "ENVIO DE DINERO INTERBANCARIO",
    "NUMERO DE RASTREO",
    "REFERENCIA NUMERICA",
    "OPERACION INTERBANCARIA",
    "PAGO MISMO BANCO",
    "GRUPO PAGO MISMO BANCO",
    "OPERACION AUTORIZADA",
    "DATOS DE CONFIRMACION DE LA TRANSFERENCIA",
    "FOLIO DE FIRMA",
    "FOLIO UNICO",
    "BBVA NET CASH",
    "BBVA NETCASH",
)
_PAYMENT_COMPACT = (
    "PAGODENOMINA",
    "REPORTEDEOPERACIONES",
    "COMPROBANTEDELAOPERACION",
    "RESULTADODELTRASPASO",
    "TRASPASOSATERCEROS",
    "TRASPASOSAOTROSBANCOS",
    "CLAVERASTREO",
    "DATOSDELBENEFICIARIO",
    "TIPODEMOVIMIENTOPAGO",
    "ABONONOMINA",
    "TRANSFERENCIASPEI",
    "SPEIENVIADO",
    "SPEIRECIBIDO",
    "FOLIOSPEI",
    "COMPROBANTEDETRANSFERENCIA",
    "NUMERODERASTREO",
    "REFERENCIANUMERICA",
    "OPERACIONINTERBANCARIA",
    "GRUPOPAGOMISMOBANCO",
    "PAGOMISMOBANCO",
    "OPERACIONAUTORIZADA",
    "DATOSDECONFIRMACIONDELATRANSFERENCIA",
    "FOLIODEFIRMA",
    "FOLIOUNICO",
    "BBVANETCASH",
)
_SERVICE_TEXT = (
    "RECIBO",
    "COMISION FEDERAL DE ELECTRICIDAD",
    "CFE",
    "TELMEX",
    "TELCEL",
    "AT T",
    "ATT",
    "TOTALPLAY",
    "IZZI",
    "MEGACABLE",
    "AGUA",
    "PREDIAL",
    "GAS",
    "NO DE SERVICIO",
    "NUMERO DE SERVICIO",
    "TARIFA DOMESTICA",
    "LECTURA ANTERIOR",
    "LECTURA ACTUAL",
    "CONSUMO KWH",
    "KWH",
    "BIMESTRE",
    "PERIODO DE FACTURACION",
    "LIMITE DE PAGO",
    "LINEA DE CAPTURA",
    "REFERENCIA UNICA",
    "PAGAR ANTES DE",
    "NUMERO TELEFONICO",
    "TOTAL A PAGAR",
)
_SERVICE_COMPACT = (
    "LINEADECAPTURA",
    "REFERENCIAUNICA",
    "PAGARANTESDE",
    "NUMEROTELEFONICO",
    "TOTALAPAGAR",
    "COMISIONFEDERALDEELECTRICIDAD",
)
_BANK_STATEMENT_TEXT = (
    "ESTADO DE CUENTA", "ACCOUNT STATEMENT", "SALDO INICIAL", "SALDO FINAL",
    "SALDO ANTERIOR", "MOVIMIENTOS DEL PERIODO", "FECHA DE CORTE",
)
_BANK_STATEMENT_COMPACT = (
    "ESTADODECUENTA", "SALDOINICIAL", "SALDOFINAL", "SALDOANTERIOR",
    "MOVIMIENTOSDEL", "FECHADECORTE",
)
_CSF_TEXT = (
    "CONSTANCIA DE SITUACION FISCAL",
    "CEDULA DE IDENTIFICACION FISCAL",
)
_CSF_COMPACT = (
    "CONSTANCIADESITUACIONFISCAL",
    "CEDULADEIDENTIFICACIONFISCAL",
)


# ── Funciones para condiciones compuestas ─────────────────────────────────────

def _is_payment_filename(text: str, compact: str, name: str) -> bool:
    """Comprobante individual de pago/SPEI con nombre de banco en el archivo."""
    return (
        any(p in name for p in _PAYMENT_FILENAME)
        and any(b in name for b in _BANK_NAMES)
    )


def _is_csf_content(text: str, compact: str, name: str) -> bool:
    """Constancia de Situación Fiscal por combinación de señales."""
    has_csf = any(m in text for m in _CSF_TEXT) or any(m in compact for m in _CSF_COMPACT)
    if has_csf:
        return True
    fiscal_combo = "SITUACION FISCAL" in text and any(k in text for k in ("RFC", "REGIMEN", "CIF"))
    sat_combo = "SAT" in text and any(m in text for m in _CSF_TEXT)
    fiscal_compact = "SITUACIONFISCAL" in compact and any(k in compact for k in ("RFC", "REGIMEN", "CIF"))
    sat_compact = "SAT" in compact and any(m in compact for m in _CSF_COMPACT)
    return fiscal_combo or sat_combo or fiscal_compact or sat_compact


def _is_bank_statement_content(text: str, compact: str, name: str) -> bool:
    """Estado de cuenta bancario por señales combinadas."""
    has_signal = (
        any(s in text for s in _BANK_STATEMENT_TEXT)
        or any(s in compact for s in _BANK_STATEMENT_COMPACT)
    )
    has_bank = any(b in text for b in ("BBVA", "BANCOMER", "BANAMEX", "SANTANDER", "SCOTIABANK", "HSBC", "BANORTE", "AZTECA"))
    return "CLABE" in text or "ESTADODECUENTA" in compact or has_signal or (has_bank and has_signal)


def _is_payment_name_combo(text: str, compact: str, name: str) -> bool:
    """Archivo cuyo nombre indica pago con tokens de dispersión."""
    return "PAGO" in name and any(
        tok in name for tok in ("NOMINA", "DISPERSION", "BMPEI", "SBK", "BNT", "SPEI", "BENEFICIARIO")
    )


def _is_single_spei_receipt(text: str, compact: str, name: str) -> bool:
    """Comprobante individual de transferencia SPEI (no dispersión masiva).

    Detecta recibos SPEI de Banorte, BBVA, etc. que contienen campos
    de una sola transferencia (nombre del beneficiario, CLABE, importe)
    en vez de tablas de dispersión masiva.
    """
    spei_markers = (
        "TRANSFERENCIA SPEI", "TRANSFERENCIAS SPEI",
        "SPEI ENVIADO", "SPEI MISMO DIA",
        "COMPROBANTE DE TRANSFERENCIA", "COMPROBANTE DE LA OPERACION",
        "ENVIO DE DINERO INTERBANCARIO",
        "BANCOS NACIONAL SPEI", "OTROS BANCOS NACIONAL",
    )
    individual_markers = (
        "NOMBRE DEL BENEFICIARIO", "CLABE BENEFICIARIO",
        "IMPORTE A TRANSFERIR", "CLAVE DE RASTREO",
        "BANCO DESTINO", "CUENTA BENEFICIARIO",
    )
    has_spei = any(m in text for m in spei_markers)
    # Fallback: "SPEI" as standalone word anywhere in text
    if not has_spei:
        has_spei = bool(re.search(r"\bSPEI\b", text))
    has_individual = sum(1 for m in individual_markers if m in text) >= 2
    return has_spei and has_individual


# ── Tabla de reglas ordenadas por prioridad ───────────────────────────────────
#
# IMPORTANTE: el orden importa. La primera regla que hace match gana.
# Reglas de filename van primero (más precisas).
# Reglas de contenido van después, de más específico a menos específico.

_RULES: list[_Rule] = [
    # ── CFDI / Factura XML ────────────────────────────────────────────────────
    _Rule("CFDI", 0.95, name_last="XML"),
    _Rule("CFDI", 0.92, text_any=(
        "TIMBRE FISCAL DIGITAL",
        "FOLIO FISCAL",
        "COMPROBANTE FISCAL DIGITAL",
    ), compact_any=(
        "CFDI:COMPROBANTE",
        "XMLNS:CFDI",
        "WWW.SAT.GOB.MX/CFD",
        "TIMBREFISCALDIGITAL",
        "FOLIOFISCAL",
        "COMPROBANTEDIGITAL",
    )),

    # ── Filename rules (alta precisión) ───────────────────────────────────────
    _Rule("NOMINA",                    0.92, name_any=_NOMINA_FILENAME),
    _Rule("INE",                       0.90, name_any=("INE", "ELECTOR")),
    _Rule("ACTA_NACIMIENTO",           0.88, name_any=("ACTA", "NACIMIENTO")),
    _Rule("CURP",                      0.90, name_any=("CURP",)),
    _Rule("NSS",                       0.88, name_any=("NSS", "IMSS", "SEGURIDAD SOCIAL")),
    _Rule("COMPROBANTE_DOMICILIO",     0.90, name_any=_SERVICE_FILENAME),
    _Rule("DATOS_BANCARIOS",           0.92, name_any=_DISPERSION_FILENAME),
    _Rule("FACTURA",                   0.90, custom=_is_payment_filename),
    _Rule("DATOS_BANCARIOS",           0.88, name_any=_BANK_FILENAME),
    _Rule("CONSTANCIA_SITUACION_FISCAL", 0.88, name_any=("RFC", "SITUACION FISCAL", "CONSTANCIA")),

    # ── Contenido: identidad / documentos personales ──────────────────────────
    _Rule("INE", 0.88, text_any=(
        "INSTITUTO NACIONAL ELECTORAL",
        "CREDENCIAL PARA VOTAR",
    ), compact_any=(
        "INSTITUTONACIONALELECTORAL",
        "CREDENCIALPARAVOTAR",
    )),
    _Rule("CURP", 0.90, text_any=(
        "CONSTANCIA DE LA CLAVE UNICA",
        "CONSTANCIA DE LA CLAVE UNICA DE REGISTRO DE POBLACION",
        "CURP CERTIFICADA",
    ), compact_any=(
        "CONSTANCIADELACLAVEUNICA",
        "CONSTANCIADELACLAVEUNICADEREGISTRODEPOBLACION",
        "CURPCERTIFICADA",
    )),
    _Rule("ACTA_NACIMIENTO", 0.85, text_any=(
        "ACTA DE NACIMIENTO",
        "REGISTRO CIVIL",
        "CERTIFICADO DE NACIMIENTO",
        "NUMERO DE CERTIFICADO DE NACIMIENTO",
        "DATOS DE LA PERSONA REGISTRADA",
        "ENTIDAD DE REGISTRO",
        "NUMERO DE ACTA",
        "OFICIALIA",
        "LIBRO",
        "TOMO",
    ), compact_any=(
        "ACTADENACIMIENTO",
        "REGISTROCIVIL",
    )),

    # ── Contenido: nómina (antes de FACTURA para evitar falsos positivos) ────────
    _Rule("NOMINA", 0.90, text_any=_NOMINA_TEXT, compact_any=_NOMINA_COMPACT),

    # ── Contenido: documentos bancarios y fiscales ────────────────────────────
    _Rule("DATOS_BANCARIOS", 0.92, text_any=_DISPERSION_TEXT, compact_any=_DISPERSION_COMPACT),
    _Rule("DATOS_BANCARIOS", 0.92, custom=_is_single_spei_receipt),
    _Rule("FACTURA",         0.90, text_any=_PAYMENT_TEXT,    compact_any=_PAYMENT_COMPACT),
    _Rule("COMPROBANTE_DOMICILIO", 0.86, text_any=_SERVICE_TEXT, compact_any=_SERVICE_COMPACT),

    # ── Contenido: NSS, CSF, CURP, banco (orden: más específico primero) ──────
    _Rule("NSS", 0.85, text_any=(
        "NUMERO DE SEGURIDAD SOCIAL",
        "SEGURIDAD SOCIAL",
    ), compact_any=(
        "NUMERODESEGURIDADSOCIAL",
        "SEGURIDADSOCIAL",
    )),
    _Rule("CONSTANCIA_SITUACION_FISCAL", 0.86, custom=_is_csf_content),
    _Rule("CURP", 0.90, text_any=("CLAVE UNICA DE REGISTRO DE POBLACION", "CURP")),
    _Rule("NSS",  0.82, text_any=("NSS", "IMSS", "SEGURIDAD SOCIAL")),
    _Rule("DATOS_BANCARIOS", 0.80, custom=_is_bank_statement_content),
]


# ── Hard markers por tipo (para validar predicciones NB) ─────────────────────
#
# Un tipo sin entrada en este dict siempre se acepta (True por defecto).

_HARD_MARKERS: dict[str, list[str]] = {
    "INE": [
        "INSTITUTO NACIONAL ELECTORAL", "CREDENCIAL PARA VOTAR", "CLAVE DE ELECTOR",
        "INSTITUTONACIONALELECTORAL", "CREDENCIALPARAVOTAR", "CLAVEDEELECTOR",
    ],
    "CURP": [
        "CONSTANCIA DE LA CLAVE UNICA", "CLAVE UNICA DE REGISTRO DE POBLACION",
        "CURP CERTIFICADA", "CONSTANCIADELACLAVEUNICA", "CURPCERTIFICADA",
    ],
    "ACTA_NACIMIENTO": [
        "ACTA DE NACIMIENTO", "REGISTRO CIVIL", "ACTADENACIMIENTO", "REGISTROCIVIL",
    ],
    "NSS": [
        "NUMERO DE SEGURIDAD SOCIAL", "IMSS", "SEGURIDADSOCIAL",
    ],
    "COMPROBANTE_DOMICILIO": [
        "TELMEX", "CFE", "TOTALPLAY", "IZZI", "MEGACABLE", "TELCEL",
        "LINEA DE CAPTURA", "TOTAL A PAGAR", "NUMERO DE SERVICIO",
        "NO DE SERVICIO", "TARIFA DOMESTICA", "LECTURA ANTERIOR",
        "CONSUMO KWH", "KWH", "BIMESTRE", "LIMITE DE PAGO",
    ],
    "CONSTANCIA_SITUACION_FISCAL": [
        "CONSTANCIA DE SITUACION FISCAL", "CEDULA DE IDENTIFICACION FISCAL",
        "CONSTANCIADESITUACIONFISCAL", "CEDULADEIDENTIFICACIONFISCAL",
        "SITUACION FISCAL",
    ],
    "DATOS_BANCARIOS": [
        "ESTADO DE CUENTA", "CLABE", "ESTADODECUENTA",
        "REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS",
        "DISPERSION DE NOMINA", "DISPERSION DE PAGO DE NOMINA",
        "ARCHIVO DE PAGOS", "REPORTE DE DISPERSION",
        "REPORTEDETRANSMISIONDEARCHIVODEPAGOS",
        "DISPERSIONDENOMINA", "ARCHIVODEPAGOS",
        # Scotiabank
        "TRANSFERENCIA DE ARCHIVOS", "TRANSFERENCIADEARCHIVOS",
        "TRANSFERENCIA DE ARCHIVO DE PAGOS",
        # Comprobantes individuales SPEI
        "TRANSFERENCIA SPEI", "TRANSFERENCIASPEI",
        "COMPROBANTE DE TRANSFERENCIA", "COMPROBANTEDETRANSFERENCIA",
        "COMPROBANTE DE LA OPERACION", "COMPROBANTEDELAOPERACION",
        "NOMBRE DEL BENEFICIARIO", "CLAVE DE RASTREO",
    ],
    "NOMINA": [
        "RECIBO DE NOMINA", "COMPROBANTE DE NOMINA", "TOTAL PERCEPCIONES",
        "TOTAL DEDUCCIONES", "NETO A PAGAR", "NETO PAGAR",
        "SUELDO BASE", "DIAS TRABAJADOS", "INFONAVIT",
        "RECIBODENOMINA", "TOTALPERCEPCIONES", "TOTALDEDUCCIONES",
        "NETOAPAGAR", "SUELDOBASE", "INFONAVIT",
    ],
    "FACTURA": [
        "PAGO DE NOMINA", "DISPERSION DE NOMINA", "TRANSFERENCIA SPEI", "SPEI",
        "COMPROBANTE DE TRANSFERENCIA", "ABONO NOMINA",
        "PAGO MISMO BANCO", "GRUPO PAGO MISMO BANCO",
        "DISPERSIONNOMINA", "PAGODENOMINA", "TRANSFERENCIASPEI",
        "OPERACION AUTORIZADA", "FOLIO DE FIRMA",
        "DATOS DE CONFIRMACION DE LA TRANSFERENCIA",
        "BBVA NET CASH", "BBVA NETCASH",
        "OPERACIONAUTORIZADA", "FOLIODEFIRMA",
        "DATOSDECONFIRMACIONDELATRANSFERENCIA",
        "BBVANETCASH", "GRUPOPAGOMISMOBANCO", "PAGOMISMOBANCO",
    ],
    "CFDI": [
        "TIMBRE FISCAL DIGITAL", "FOLIO FISCAL", "COMPROBANTE FISCAL DIGITAL",
        "TIMBREFISCALDIGITAL", "FOLIOFISCAL",
    ],
}


def _has_hard_markers(doc_type: str, text: str, compact_text: str) -> bool:
    """Verifica que el texto contenga evidencia del tipo predicho por el NB."""
    markers = _HARD_MARKERS.get(doc_type)
    if markers is None:
        return True  # tipos sin lista se aceptan siempre
    combined = text + " " + compact_text
    return any(marker in combined for marker in markers)


# ─── Clasificador principal ───────────────────────────────────────────────────

def _apply_rules(text: str, compact: str, name: str) -> tuple[str | None, float]:
    """Aplica las reglas en orden y retorna el primer match."""
    name_parts = name.split()
    for rule in _RULES:
        # Evaluar name_last primero (más específico)
        if rule.name_last is not None:
            if name_parts and name_parts[-1] == rule.name_last:
                return rule.doc_type, rule.confidence
            # name_last definido pero no coincide: no evaluar el resto de la regla
            continue
        if _rule_matches(rule, text, compact, name):
            return rule.doc_type, rule.confidence
    return None, 0.0


async def classify_document(image, ocr_text: str, filename: str | None = None):
    """
    Clasifica un documento y retorna (tipo, confianza).

    Prioridad:
      1. Reglas por filename + contenido (alta precisión, deterministas)
      2. Modelo NB si tiene confianza ≥ 0.6 Y hay hard markers en el texto
      3. GENERICO como fallback
    """
    text = _normalize_text(ocr_text or "")
    compact = text.replace(" ", "")
    name = _normalize_text(filename or "")

    # ── 1. Motor de reglas ────────────────────────────────────────────────────
    rule_type, rule_conf = _apply_rules(text, compact, name)
    if rule_type:
        logger.debug("classify rules: %s (%.2f) para '%s'", rule_type, rule_conf, filename or "?")
        return rule_type, rule_conf

    # ── 2. Modelo NB ──────────────────────────────────────────────────────────
    model = _load_model()
    if model:
        predicted, confidence = _predict_nb(model, ocr_text or "")
        if predicted and confidence >= 0.6:
            if _has_hard_markers(predicted, text, compact):
                logger.debug("classify NB: %s (%.2f) con hard markers", predicted, confidence)
                return predicted, confidence
            logger.info(
                "NB predicted %s (conf=%.2f) pero sin hard markers → GENERICO",
                predicted, confidence,
            )

    # ── 3. Fallback ───────────────────────────────────────────────────────────
    return "GENERICO", 0.5
