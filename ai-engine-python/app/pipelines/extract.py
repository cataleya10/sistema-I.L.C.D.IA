import re

CURP_PATTERN = re.compile(r"\b[A-Z][AEIOUX][A-Z]{2}\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[HM][A-Z]{5}[A-Z0-9]\d\b")
RFC_PATTERN = re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b")
NSS_PATTERN = re.compile(r"\b\d{11}\b")
CLABE_PATTERN = re.compile(r"\b\d{18}\b")
DATE_PATTERN = re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b")
NAME_PATTERN = re.compile(r"\b[A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,}){1,4}\b")


def _find_source(value: str, ocr_boxes):
    if not value or not ocr_boxes:
        return None
    for box in ocr_boxes:
        if value in box.get("text", "").upper():
            return {"page": 1, "bbox": box.get("bbox", [])}
    return None


def _make_field(key: str, label: str, value: str, ocr_boxes, confidence: float = 0.7):
    return {
        "key": key,
        "label": label,
        "value": value,
        "confidence": confidence,
        "valid": True,
        "validation_errors": [],
        "source": _find_source(value, ocr_boxes)
    }


def _pick_address(lines: list[str]):
    keywords = (
        "CALLE",
        "AV",
        "AV.",
        "AVENIDA",
        "COL",
        "COL.",
        "COLONIA",
        "FRACC",
        "FRACCIONAMIENTO",
        "CP",
        "C.P.",
        "CODIGO POSTAL",
        "CÓDIGO POSTAL",
        "NUM",
        "NÚM",
        "NO.",
        "#",
        "MUNICIPIO",
        "ESTADO",
    )
    candidates = [line for line in lines if any(k in line for k in keywords)]
    if not candidates:
        return None
    primary = candidates[0]
    idx = lines.index(primary)
    extra = []
    if idx + 1 < len(lines):
        extra.append(lines[idx + 1])
    if idx + 2 < len(lines) and ("CP" in lines[idx + 2] or "C.P." in lines[idx + 2]):
        extra.append(lines[idx + 2])
    return " ".join([primary, *extra]).strip()


async def extract_fields(document_type: str, ocr_text: str, ocr_boxes, raw_text: str = "", filename: str | None = None):
    fields = []
    base_text = raw_text or ocr_text
    text = base_text.upper()
    lines = [line.strip().upper() for line in base_text.splitlines() if line.strip()]
    compact_text = re.sub(r"\s+", "", text)

    curps = [match.group(0) for match in CURP_PATTERN.finditer(compact_text)]
    rfcs = [match.group(0) for match in RFC_PATTERN.finditer(compact_text)]
    nss = [match.group(0) for match in NSS_PATTERN.finditer(compact_text)]
    clabes = [match.group(0) for match in CLABE_PATTERN.finditer(compact_text)]
    dates = [match.group(0) for match in DATE_PATTERN.finditer(text)]

    if document_type in {"INE", "CURP"}:
        for value in curps:
            fields.append(_make_field("curp", "CURP", value, ocr_boxes))
        name_match = NAME_PATTERN.findall(text)
        if name_match:
            fields.append(_make_field("nombre", "Nombre", name_match[0], ocr_boxes, confidence=0.6))
        if not curps and filename:
            name_curps = [match.group(0) for match in CURP_PATTERN.finditer(filename.upper())]
            for value in name_curps:
                fields.append(_make_field("curp", "CURP", value, ocr_boxes, confidence=0.9))

    if document_type in {"CONSTANCIA_SITUACION_FISCAL", "DATOS_BANCARIOS"}:
        for value in rfcs:
            fields.append(_make_field("rfc", "RFC", value, ocr_boxes))

    if document_type == "NSS":
        for value in nss:
            fields.append(_make_field("nss", "NSS", value, ocr_boxes))

    if document_type == "DATOS_BANCARIOS":
        for value in clabes:
            fields.append(_make_field("clabe", "CLABE", value, ocr_boxes))

    if document_type in {"ACTA_NACIMIENTO", "INE"}:
        for value in dates:
            fields.append(_make_field("fecha", "Fecha", value, ocr_boxes, confidence=0.6))

    if document_type == "COMPROBANTE_DOMICILIO":
        address = _pick_address(lines)
        if address:
            fields.append(_make_field("domicilio", "Domicilio", address, ocr_boxes, confidence=0.8))

    if base_text:
        snippet = base_text.strip()
        if len(snippet) > 1200:
            snippet = snippet[:1200].rstrip() + "..."
        fields.insert(0, _make_field("texto_detectado", "Texto detectado", snippet, ocr_boxes, confidence=1.0))

    if not fields:
        for value in curps:
            fields.append(_make_field("curp", "CURP", value, ocr_boxes))
        for value in rfcs:
            fields.append(_make_field("rfc", "RFC", value, ocr_boxes))
        for value in nss:
            fields.append(_make_field("nss", "NSS", value, ocr_boxes))
        for value in clabes:
            fields.append(_make_field("clabe", "CLABE", value, ocr_boxes))
        if not fields and filename:
            name_curps = [match.group(0) for match in CURP_PATTERN.finditer(filename.upper())]
            for value in name_curps:
                fields.append(_make_field("curp", "CURP", value, ocr_boxes, confidence=0.9))

    return fields
