import json
import logging
import math
import os
import re
import unicodedata

logger = logging.getLogger(__name__)

MODEL_PATH = os.getenv("DOC_MODEL_PATH", os.path.join(os.path.dirname(__file__), "..", "models", "doc_type_nb.json"))


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.upper()
    text = re.sub(r"[^A-Z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokenize(text: str) -> list[str]:
    return [tok for tok in _normalize_text(text).split() if len(tok) > 1]


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

    best_cls = None
    best_score = None
    for cls in classes:
        prior = (class_counts.get(cls, 0) + 1) / (total_docs + len(classes))
        score = 0.0
        score += math.log(prior)
        cls_tokens = token_counts.get(cls, {})
        cls_total = sum(cls_tokens.values()) + vocab_size
        for tok in tokens:
            if tok not in vocab:
                continue
            count = cls_tokens.get(tok, 0) + 1
            score += math.log(count / cls_total)
        if best_score is None or score > best_score:
            best_score = score
            best_cls = cls

    if best_cls is None:
        return None, 0.0
    return best_cls, 0.85


def _keyword_override(text: str, compact_text: str, filename: str | None):
    # ── Filename check FIRST: high-precision, no text needed ──────────────
    _name = _normalize_text(filename or "")
    if "INE" in _name or "ELECTOR" in _name:
        return "INE", 0.9
    if "ACTA" in _name or "NACIMIENTO" in _name:
        return "ACTA_NACIMIENTO", 0.88
    if "CURP" in _name:
        return "CURP", 0.9
    if "NSS" in _name or "IMSS" in _name or "SEGURIDAD SOCIAL" in _name:
        return "NSS", 0.88
    if (
        "DOMICILIO" in _name
        or "COMPROBANTE" in _name
        or "RECIBO" in _name
        or "CFE" in _name
        or "TELMEX" in _name
        or "TELCEL" in _name
        or "TOTALPLAY" in _name
        or "IZZI" in _name
        or "MEGACABLE" in _name
    ):
        return "COMPROBANTE_DOMICILIO", 0.9
    # Comprobantes de pago/transferencia con nombre de banco → FACTURA, no DATOS_BANCARIOS
    # Ej: "PAGO FIS BMPEI 9,243.60 BBVA.pdf", "TRANSFERENCIA SPEI SANTANDER.pdf"
    _bank_names = ("BBVA", "BANAMEX", "BANCOMER", "SANTANDER", "SCOTIABANK", "HSBC", "BANORTE")
    _payment_signals = ("PAGO", "TRANSFERENCIA", "DISPERSION", "SPEI", "NOMINA")
    if any(p in _name for p in _payment_signals) and any(b in _name for b in _bank_names):
        return "FACTURA", 0.9
    if (
        "ESTADO DE CUENTA" in _name
        or "ESTADO CUENTA" in _name
        or "ESTADODECUENTA" in _name
        or "CLABE" in _name
        or "BBVA" in _name
        or "BANAMEX" in _name
        or "BANCOMER" in _name
        or "SANTANDER" in _name
        or "SCOTIABANK" in _name
        or "HSBC" in _name
        or "BANORTE" in _name
    ):
        return "DATOS_BANCARIOS", 0.88
    if "RFC" in _name or "SITUACION FISCAL" in _name or "CONSTANCIA" in _name:
        return "CONSTANCIA_SITUACION_FISCAL", 0.88
    # ─────────────────────────────────────────────────────────────────────

    service_markers = (
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
        # CFE data-section keywords (appear in billing body, not just logo)
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
    service_markers_compact = (
        "LINEADECAPTURA",
        "REFERENCIAUNICA",
        "PAGARANTESDE",
        "NUMEROTELEFONICO",
        "TOTALAPAGAR",
        "COMISIONFEDERALDEELECTRICIDAD",
    )
    payment_markers = (
        "DISPERSION DE PAGO DE NOMINA",
        "PAGO DE NOMINA",
        "REPORTE DE OPERACIONES",
        "COMPROBANTE DE LA OPERACION",
        "RESULTADO DEL TRASPASO",
        "TRASPASOS A TERCEROS",
        "TRASPASOS A OTROS BANCOS",
        "CLAVE RASTREO",
        "DATOS DEL BENEFICIARIO",
        "REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS",
        "TIPO DE MOVIMIENTO (PAGO)",
        "ABONO NOMINA",
        # SPEI / transferencias interbancarias
        "TRANSFERENCIA SPEI",
        "SPEI ENVIADO",
        "SPEI RECIBIDO",
        "FOLIO SPEI",
        "COMPROBANTE DE TRANSFERENCIA",
        "ENVIO DE DINERO INTERBANCARIO",
        "NUMERO DE RASTREO",
        "REFERENCIA NUMERICA",
        "OPERACION INTERBANCARIA",
        # BBVA Pago Mismo Banco / transferencias
        "PAGO MISMO BANCO",
        "GRUPO PAGO MISMO BANCO",
        "OPERACION AUTORIZADA",
        "DATOS DE CONFIRMACION DE LA TRANSFERENCIA",
        "FOLIO DE FIRMA",
        "FOLIO UNICO",
        # BBVA Net Cash (plataforma de pagos empresariales)
        "BBVA NET CASH",
        "BBVA NETCASH",
    )
    payment_markers_compact = (
        "DISPERSIONDEPAGODENOMINA",
        "PAGODENOMINA",
        "REPORTEDEOPERACIONES",
        "COMPROBANTEDELAOPERACION",
        "RESULTADODELTRASPASO",
        "TRASPASOSATERCEROS",
        "TRASPASOSAOTROSBANCOS",
        "CLAVERASTREO",
        "DATOSDELBENEFICIARIO",
        "REPORTEDETRANSMISIONDEARCHIVODEPAGOS",
        "TIPODEMOVIMIENTOPAGO",
        "ABONONOMINA",
        # SPEI compact
        "TRANSFERENCIASPEI",
        "SPEIENVIADO",
        "SPEIRECIBIDO",
        "FOLIOSPEI",
        "COMPROBANTEDETRANSFERENCIA",  # fix: antes faltaba la E
        "NUMERODERASTREO",
        "REFERENCIANUMERICA",
        "OPERACIONINTERBANCARIA",
        # BBVA Pago Mismo Banco compact
        "GRUPOPAGOMISMOBANCO",
        "PAGOMISMOBANCO",
        "OPERACIONAUTORIZADA",
        "DATOSDECONFIRMACIONDELATRANSFERENCIA",
        "FOLIODEFIRMA",
        "FOLIOUNICO",
        # BBVA Net Cash compact
        "BBVANETCASH",
    )

    if (
        "INSTITUTO NACIONAL ELECTORAL" in text
        or "CREDENCIAL PARA VOTAR" in text
        or "INSTITUTONACIONALELECTORAL" in compact_text
        or "CREDENCIALPARAVOTAR" in compact_text
    ):
        return "INE", 0.88
    if (
        "CONSTANCIA DE LA CLAVE UNICA" in text
        or "CONSTANCIA DE LA CLAVE UNICA DE REGISTRO DE POBLACION" in text
        or "CURP CERTIFICADA" in text
        or "CONSTANCIADELACLAVEUNICA" in compact_text
        or "CONSTANCIADELACLAVEUNICADEREGISTRODEPOBLACION" in compact_text
        or "CURPCERTIFICADA" in compact_text
    ):
        return "CURP", 0.9
    if (
        "ACTA DE NACIMIENTO" in text
        or "REGISTRO CIVIL" in text
        or "ACTADENACIMIENTO" in compact_text
        or "REGISTROCIVIL" in compact_text
    ):
        return "ACTA_NACIMIENTO", 0.85
    if (
        "CERTIFICADO DE NACIMIENTO" in text
        or "NUMERO DE CERTIFICADO DE NACIMIENTO" in text
        or "DATOS DE LA PERSONA REGISTRADA" in text
        or "ENTIDAD DE REGISTRO" in text
        or "NUMERO DE ACTA" in text
        or "OFICIALIA" in text
        or "LIBRO" in text
        or "TOMO" in text
    ):
        return "ACTA_NACIMIENTO", 0.85
    # Nómina/SPEI/pago keywords tienen prioridad sobre service_markers Y sobre NSS
    # (una nómina BBVA puede tener "TOTAL A PAGAR" o "NSS" que dispara clasificación incorrecta)
    if (
        any(marker in text for marker in payment_markers)
        or any(marker in compact_text for marker in payment_markers_compact)
    ):
        return "FACTURA", 0.9
    if any(marker in text for marker in service_markers) or any(marker in compact_text for marker in service_markers_compact):
        return "COMPROBANTE_DOMICILIO", 0.86
    # NSS check después de FACTURA para evitar que nóminas con "NSS"/"IMSS" se clasifiquen mal
    if (
        "NUMERO DE SEGURIDAD SOCIAL" in text
        or "NSS" in text
        or "IMSS" in text
        or "SEGURIDAD SOCIAL" in text
        or "NUMERODESEGURIDADSOCIAL" in compact_text
        or "SEGURIDADSOCIAL" in compact_text
    ):
        return "NSS", 0.85
    if (
        "CONSTANCIA DE SITUACION FISCAL" in text
        or "CEDULA DE IDENTIFICACION FISCAL" in text
        or "CONSTANCIADESITUACIONFISCAL" in compact_text
        or "CEDULADEIDENTIFICACIONFISCAL" in compact_text
        or (
            "SITUACION FISCAL" in text
            and ("RFC" in text or "REGIMEN" in text or "CIF" in text)
        )
        or (
            "SAT" in text
            and ("CEDULA DE IDENTIFICACION FISCAL" in text or "CONSTANCIA DE SITUACION FISCAL" in text)
        )
        or (
            "SITUACIONFISCAL" in compact_text
            and ("RFC" in compact_text or "REGIMEN" in compact_text or "CIF" in compact_text)
        )
        or (
            "SAT" in compact_text
            and ("CEDULADEIDENTIFICACIONFISCAL" in compact_text or "CONSTANCIADESITUACIONFISCAL" in compact_text)
        )
    ):
        return "CONSTANCIA_SITUACION_FISCAL", 0.86
    if "CLAVE UNICA DE REGISTRO DE POBLACION" in text or "CURP" in text:
        return "CURP", 0.9
    if "NSS" in text or "IMSS" in text or "SEGURIDAD SOCIAL" in text:
        return "NSS", 0.82
    # Señales fuertes de estado de cuenta bancario (sin importar banco)
    _bank_statement_signals = (
        "ESTADO DE CUENTA", "ACCOUNT STATEMENT", "SALDO INICIAL", "SALDO FINAL",
        "SALDO ANTERIOR", "MOVIMIENTOS DEL PERIODO", "FECHA DE CORTE",
    )
    _bank_statement_signals_compact = (
        "ESTADODECUENTA", "SALDOINICIAL", "SALDOFINAL", "SALDOANTERIOR",
        "MOVIMIENTOSDEL", "FECHADECORTE",
    )
    _bank_names_content = ("BBVA", "BANCOMER", "BANAMEX", "SANTANDER", "SCOTIABANK", "HSBC", "BANORTE", "AZTECA")
    _has_statement_signal = (
        any(s in text for s in _bank_statement_signals)
        or any(s in compact_text for s in _bank_statement_signals_compact)
    )
    _has_bank_name = any(b in text for b in _bank_names_content)
    if (
        "CLABE" in text
        or "ESTADODECUENTA" in compact_text
        or _has_statement_signal
        or (_has_bank_name and _has_statement_signal)
    ):
        return "DATOS_BANCARIOS", 0.8
    # Filename-based PAGO/FACTURA check (pago nómina only — kept at end since less precise)
    if (
        "PAGO" in _name
        and any(token in _name for token in ("NOMINA", "DISPERSION", "BMPEI", "SBK", "BNT", "SPEI", "BENEFICIARIO"))
    ):
        return "FACTURA", 0.9
    return None, 0.0


async def classify_document(image, ocr_text: str, filename: str | None = None):
    text = _normalize_text(ocr_text or "")
    compact_text = text.replace(" ", "")
    name = _normalize_text(filename or "")

    model = _load_model()
    if model:
        predicted, confidence = _predict_nb(model, ocr_text or "")
        if predicted and confidence >= 0.6:
            override, override_conf = _keyword_override(text, compact_text, name)
            if override:
                return override, max(confidence, override_conf)
            # Validate NB prediction — if the doc doesn't have hard markers
            # for the predicted type, the NB is likely wrong (e.g. a generic
            # document with "NOMBRE" being classified as INE).
            if _has_hard_markers(predicted, text, compact_text):
                return predicted, confidence
            # NB prediction not confirmed by hard markers → GENERICO
            logger.info(
                "NB predicted %s (conf=%.2f) but no hard markers found, downgrading to GENERICO",
                predicted, confidence,
            )
            return "GENERICO", 0.5
    override, override_conf = _keyword_override(text, compact_text, name)
    if override:
        return override, override_conf
    # No specific document type recognized — use GENERICO for universal extraction
    return "GENERICO", 0.5


def _has_hard_markers(doc_type: str, text: str, compact_text: str) -> bool:
    """Check if the text contains hard evidence for the predicted document type.

    This prevents the NB classifier from misclassifying generic documents
    that happen to contain words like 'NOMBRE', 'CEDULA', 'FECHA' etc.
    """
    checks: dict[str, list[str]] = {
        "INE": [
            "INSTITUTO NACIONAL ELECTORAL",
            "CREDENCIAL PARA VOTAR",
            "CLAVE DE ELECTOR",
            "INSTITUTONACIONALELECTORAL",
            "CREDENCIALPARAVOTAR",
            "CLAVEDEELECTOR",
        ],
        "CURP": [
            "CONSTANCIA DE LA CLAVE UNICA",
            "CLAVE UNICA DE REGISTRO DE POBLACION",
            "CURP CERTIFICADA",
            "CONSTANCIADELACLAVEUNICA",
            "CURPCERTIFICADA",
        ],
        "ACTA_NACIMIENTO": [
            "ACTA DE NACIMIENTO",
            "REGISTRO CIVIL",
            "ACTADENACIMIENTO",
            "REGISTROCIVIL",
        ],
        "NSS": [
            "NUMERO DE SEGURIDAD SOCIAL",
            "IMSS",
            "SEGURIDADSOCIAL",
        ],
        "COMPROBANTE_DOMICILIO": [
            "TELMEX",
            "CFE",
            "TOTALPLAY",
            "IZZI",
            "MEGACABLE",
            "TELCEL",
            "LINEA DE CAPTURA",
            "TOTAL A PAGAR",
            "NUMERO DE SERVICIO",
            "NO DE SERVICIO",
            "TARIFA DOMESTICA",
            "LECTURA ANTERIOR",
            "CONSUMO KWH",
            "KWH",
            "BIMESTRE",
            "LIMITE DE PAGO",
        ],
        "CONSTANCIA_SITUACION_FISCAL": [
            "CONSTANCIA DE SITUACION FISCAL",
            "CEDULA DE IDENTIFICACION FISCAL",
            "CONSTANCIADESITUACIONFISCAL",
            "CEDULADEIDENTIFICACIONFISCAL",
            "SITUACION FISCAL",
        ],
        "DATOS_BANCARIOS": [
            "ESTADO DE CUENTA",
            "CLABE",
            "ESTADODECUENTA",
        ],
        "FACTURA": [
            # Payment / payroll / SPEI markers
            "PAGO DE NOMINA",
            "DISPERSION DE NOMINA",
            "TRANSFERENCIA SPEI",
            "SPEI",
            "COMPROBANTE DE TRANSFERENCIA",
            "ABONO NOMINA",
            "PAGO MISMO BANCO",
            "GRUPO PAGO MISMO BANCO",
            "DISPERSIONNOMINA",
            "PAGODENOMINA",
            "TRANSFERENCIASPEI",
            # BBVA Net Cash payment confirmation signals
            "OPERACION AUTORIZADA",
            "FOLIO DE FIRMA",
            "DATOS DE CONFIRMACION DE LA TRANSFERENCIA",
            "BBVA NET CASH",
            "BBVA NETCASH",
            "OPERACIONAUTORIZADA",
            "FOLIODEFIRMA",
            "DATOSDECONFIRMACIONDELATRANSFERENCIA",
            "BBVANETCASH",
            "GRUPOPAGOMISMOBANCO",
            "PAGOMISMOBANCO",
        ],
    }

    markers = checks.get(doc_type)
    if markers is None:
        # No hard markers defined for this type → trust NB
        return True

    combined = text + " " + compact_text
    return any(marker in combined for marker in markers)
