import json
import os
import re
import unicodedata

MODEL_PATH = os.getenv("DOC_MODEL_PATH", os.path.join(os.path.dirname(__file__), "..", "models", "doc_type_nb.json"))


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.upper()
    text = re.sub(r"[^A-Z0-9\\s]", " ", text)
    return re.sub(r"\\s+", " ", text).strip()


def _tokenize(text: str) -> list[str]:
    return [tok for tok in _normalize_text(text).split() if len(tok) > 1]


def _load_model():
    try:
        if not os.path.exists(MODEL_PATH):
            return None
        with open(MODEL_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
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
        score += float(__import__("math").log(prior))
        cls_tokens = token_counts.get(cls, {})
        cls_total = sum(cls_tokens.values()) + vocab_size
        for tok in tokens:
            if tok not in vocab:
                continue
            count = cls_tokens.get(tok, 0) + 1
            score += float(__import__("math").log(count / cls_total))
        if best_score is None or score > best_score:
            best_score = score
            best_cls = cls

    if best_cls is None:
        return None, 0.0
    return best_cls, 0.85


def _keyword_override(text: str, compact_text: str, filename: str | None):
    if (
        "INSTITUTO NACIONAL ELECTORAL" in text
        or "CREDENCIAL PARA VOTAR" in text
        or "INSTITUTONACIONALELECTORAL" in compact_text
        or "CREDENCIALPARAVOTAR" in compact_text
    ):
        return "INE", 0.88
    if "NUMERO DE SEGURIDAD SOCIAL" in text or "NSS" in text or "IMSS" in text or "SEGURIDAD SOCIAL" in text:
        return "NSS", 0.85
    if (
        "CONSTANCIA DE LA CLAVE UNICA" in text
        or "CONSTANCIA DE LA CLAVE UNICA DE REGISTRO DE POBLACION" in text
        or "CURP CERTIFICADA" in text
    ):
        return "CURP", 0.9
    if "ACTA DE NACIMIENTO" in text or "REGISTRO CIVIL" in text:
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
    if "SITUACION FISCAL" in text or "CEDULA DE IDENTIFICACION FISCAL" in text or "SAT" in text:
        return "CONSTANCIA_SITUACION_FISCAL", 0.86
    if "CLAVE UNICA DE REGISTRO DE POBLACION" in text or "CURP" in text:
        return "CURP", 0.9
    if "NSS" in text or "IMSS" in text or "SEGURIDAD SOCIAL" in text:
        return "NSS", 0.82
    if (
        "RECIBO" in text
        or "COMISION FEDERAL DE ELECTRICIDAD" in text
        or "CFE" in text
        or "TELMEX" in text
        or "TELCEL" in text
        or "AT&T" in text
        or "TOTALPLAY" in text
        or "IZZI" in text
        or "MEGACABLE" in text
        or "AGUA" in text
        or "PREDIAL" in text
        or "GAS" in text
    ):
        return "COMPROBANTE_DOMICILIO", 0.8
    if (
        "CLABE" in text
        or "BANCO" in text
        or "CUENTA" in text
        or "ESTADO DE CUENTA" in text
        or "ACCOUNT STATEMENT" in text
        or "BBVA" in text
        or "BANCOMER" in text
        or "BANAMEX" in text
        or "SANTANDER" in text
        or "SCOTIABANK" in text
        or "HSBC" in text
        or "BANORTE" in text
        or "AZTECA" in text
    ):
        return "DATOS_BANCARIOS", 0.8
    name = (filename or "").upper()
    if "INE" in name or "ELECTOR" in name:
        return "INE", 0.9
    if "ACTA" in name or "NACIMIENTO" in name:
        return "ACTA_NACIMIENTO", 0.85
    if "CURP" in name:
        return "CURP", 0.9
    if "NSS" in name or "IMSS" in name:
        return "NSS", 0.85
    if "CLABE" in name or "BANCO" in name:
        return "DATOS_BANCARIOS", 0.85
    if "ESTADO DE CUENTA" in name or "ESTADO_CUENTA" in name or "CUENTA" in name:
        return "DATOS_BANCARIOS", 0.8
    if "RFC" in name or "SITUACION" in name:
        return "CONSTANCIA_SITUACION_FISCAL", 0.85
    if "DOMICILIO" in name or "COMPROBANTE" in name or "RECIBO" in name:
        return "COMPROBANTE_DOMICILIO", 0.9
    return None, 0.0


async def classify_document(image, ocr_text: str, filename: str | None = None):
    text = (ocr_text or "").upper()
    name = (filename or "").upper()
    text = text.replace("\u00a0", " ")
    text = " ".join(text.split())
    compact_text = text.replace(" ", "")

    model = _load_model()
    if model:
        predicted, confidence = _predict_nb(model, ocr_text or "")
        if predicted and confidence >= 0.6:
            override, override_conf = _keyword_override(text, compact_text, filename)
            if override:
                return override, max(confidence, override_conf)
            return predicted, confidence
    override, override_conf = _keyword_override(text, compact_text, filename)
    if override:
        return override, override_conf
    return "UNKNOWN", 0.5
