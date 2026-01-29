import re

CURP_PATTERN = re.compile(r"\b[A-Z][AEIOUX][A-Z]{2}\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[HM][A-Z]{5}[A-Z0-9]\d\b")
RFC_PATTERN = re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b")
NSS_PATTERN = re.compile(r"\b\d{11}\b")
CLABE_PATTERN = re.compile(r"\b\d{18}\b")
DATE_PATTERN = re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b")
NAME_PATTERN = re.compile(r"\b[A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,}){1,4}\b")
RFC_WITH_HOMOCLAVE = re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b")
CP_PATTERN = re.compile(r"\b\d{5}\b")

LABEL_MAP = {
    "CURP": "curp",
    "RFC": "rfc",
    "NSS": "nss",
    "CLABE": "clabe",
}


def _find_source(value: str, ocr_boxes):
    if not value or not ocr_boxes:
        return None
    for box in ocr_boxes:
        if value in box.get("text", "").upper():
            return {"page": box.get("page", 1), "bbox": box.get("bbox", [])}
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


def _normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _normalize_sex(value: str) -> str:
    value = value.strip().upper()
    if value in {"H", "HOMBRE", "MASCULINO"}:
        return "H"
    if value in {"M", "MUJER", "FEMENINO"}:
        return "M"
    return value


def _normalize_date_value(value: str) -> str:
    value = value.strip()
    value = value.replace("-", "/")
    match = re.search(r"(\d{2}[/-]\d{2}[/-]\d{4})", value)
    return match.group(1).replace("-", "/") if match else value


def _normalize_alnum(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _normalize_name(value: str) -> str:
    value = _normalize_text(value)
    return value.upper()


def _normalize_address(value: str) -> str:
    value = _normalize_text(value)
    replacements = {
        "AV.": "AV ",
        "AVENIDA": "AV ",
        "C.P.": "CP ",
        "CÓDIGO POSTAL": "CP ",
        "COL.": "COL ",
        "COLONIA": "COL ",
        "FRACC.": "FRACC ",
        "FRACCIONAMIENTO": "FRACC ",
        "MUNICIPIO": "MUN ",
        "ESTADO": "EDO ",
    }
    upper = value.upper()
    for key, repl in replacements.items():
        upper = upper.replace(key, repl)
    return upper


def _normalize_vigencia(value: str) -> str:
    value = value.strip().upper().replace("-", "/")
    year_range = re.search(r"(\d{4}\s*/\s*\d{4})", value)
    if year_range:
        return year_range.group(1).replace(" ", "")
    date_match = re.search(r"(\d{2}/\d{2}/\d{4})", value)
    return date_match.group(1) if date_match else value


def _normalize_numeric_field(value: str) -> str:
    value = value.upper()
    value = value.replace("O", "0").replace("I", "1").replace("L", "1")
    return re.sub(r"\D", "", value)


def _extract_city_state(lines: list[str]) -> tuple[str | None, str | None]:
    city = None
    state = None
    for line in lines:
        if "MUNICIPIO" in line or "MUN" in line:
            city = line.split("MUNICIPIO")[-1].split("MUN")[-1].strip(" :.-")
        if "ESTADO" in line or "EDO" in line:
            state = line.split("ESTADO")[-1].split("EDO")[-1].strip(" :.-")
    return city, state


def _extract_postal_code(text: str) -> str | None:
    match = CP_PATTERN.search(text)
    return match.group(0) if match else None


def _extract_curp_state(curps: list[str]) -> str | None:
    if not curps:
        return None
    curp = _normalize_alnum(curps[0])
    if len(curp) < 13:
        return None
    return curp[11:13]


def _extract_curp_birth_date(curps: list[str]) -> str | None:
    if not curps:
        return None
    curp = _normalize_alnum(curps[0])
    if len(curp) < 10:
        return None
    yy = curp[4:6]
    mm = curp[6:8]
    dd = curp[8:10]
    if not (yy.isdigit() and mm.isdigit() and dd.isdigit()):
        return None
    return f"{dd}/{mm}/19{yy}" if int(yy) >= 30 else f"{dd}/{mm}/20{yy}"


def _extract_curp_sex(curps: list[str]) -> str | None:
    if not curps:
        return None
    curp = _normalize_alnum(curps[0])
    if len(curp) < 11:
        return None
    sex = curp[10]
    return sex if sex in {"H", "M"} else None


def _guess_name(text: str) -> str | None:
    candidates = NAME_PATTERN.findall(text)
    if not candidates:
        return None
    blacklist = {"CURP", "RFC", "ACTA", "NACIMIENTO", "INSTITUTO", "ELECTOR", "DOMICILIO"}
    for name in candidates:
        if any(word in blacklist for word in name.split()):
            continue
        return name
    return candidates[0] if candidates else None


def _find_labeled_value(lines: list[str], label: str) -> str | None:
    label_upper = label.upper()
    for line in lines:
        if label_upper in line:
            parts = line.split(label_upper, 1)
            if len(parts) > 1:
                candidate = parts[1].strip(" :.-")
                if candidate:
                    return candidate
    return None


def _find_value_after_keyword(lines: list[str], keywords: list[str]) -> str | None:
    for idx, line in enumerate(lines):
        if any(keyword in line for keyword in keywords):
            for keyword in keywords:
                if keyword in line:
                    tail = line.split(keyword, 1)[-1].strip(" :.-")
                    if tail:
                        return tail
            if idx + 1 < len(lines):
                return lines[idx + 1].strip(" :.-")
    return None


def _dedupe_fields(fields: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for field in fields:
        key = field.get("key")
        if not key:
            continue
        if key not in best:
            best[key] = field
            continue
        if field.get("confidence", 0) > best[key].get("confidence", 0):
            best[key] = field
    return list(best.values())


async def extract_fields(document_type: str, ocr_text: str, ocr_boxes, raw_text: str = "", filename: str | None = None):
    fields = []
    base_text = raw_text or ocr_text
    base_text = _normalize_text(base_text)
    text = base_text.upper()
    lines = [line.strip().upper() for line in base_text.splitlines() if line.strip()]
    compact_text = re.sub(r"\s+", "", text)

    curps = [match.group(0) for match in CURP_PATTERN.finditer(compact_text)]
    rfcs = [match.group(0) for match in RFC_WITH_HOMOCLAVE.finditer(compact_text)]
    nss = [match.group(0) for match in NSS_PATTERN.finditer(compact_text)]
    clabes = [match.group(0) for match in CLABE_PATTERN.finditer(compact_text)]
    dates = [match.group(0) for match in DATE_PATTERN.finditer(text)]

    if document_type in {"INE", "CURP"}:
        for value in curps:
            fields.append(_make_field("curp", "CURP", _normalize_alnum(value), ocr_boxes))
        labeled_curp = _find_labeled_value(lines, "CURP")
        if labeled_curp:
            fields.append(_make_field("curp", "CURP", _normalize_alnum(labeled_curp), ocr_boxes, confidence=0.8))
        name_match = _guess_name(text)
        if name_match:
            fields.append(_make_field("nombre", "Nombre", _normalize_name(name_match), ocr_boxes, confidence=0.6))
        birth_date = _find_value_after_keyword(lines, ["FECHA DE NACIMIENTO", "FECHA NACIMIENTO", "NACIMIENTO"])
        if birth_date:
            fields.append(_make_field("fecha_nacimiento", "Fecha de nacimiento", _normalize_date_value(birth_date), ocr_boxes, confidence=0.6))
        sexo = _find_value_after_keyword(lines, ["SEXO", "GENERO", "GÉNERO"])
        if sexo:
            fields.append(_make_field("sexo", "Sexo", _normalize_sex(sexo), ocr_boxes, confidence=0.6))
        else:
            curp_sex = _extract_curp_sex(curps)
            if curp_sex:
                fields.append(_make_field("sexo", "Sexo", curp_sex, ocr_boxes, confidence=0.5))
        ine_address = _pick_address(lines)
        if ine_address:
            fields.append(_make_field("domicilio", "Domicilio", _normalize_address(ine_address), ocr_boxes, confidence=0.7))
        clave_elector = _find_value_after_keyword(lines, ["CLAVE DE ELECTOR", "CLAVE ELECTOR", "ELECTOR"])
        if clave_elector:
            fields.append(_make_field("clave_elector", "Clave de elector", _normalize_alnum(clave_elector), ocr_boxes, confidence=0.6))
        seccion = _find_value_after_keyword(lines, ["SECCION", "SECCIÓN"])
        if seccion:
            fields.append(_make_field("seccion", "Sección", _normalize_alnum(seccion), ocr_boxes, confidence=0.6))
        vigencia = _find_value_after_keyword(lines, ["VIGENCIA", "VÁLIDA HASTA", "VALIDA HASTA"])
        if vigencia:
            fields.append(_make_field("vigencia", "Vigencia", _normalize_vigencia(vigencia), ocr_boxes, confidence=0.6))
        curp_entidad = _extract_curp_state(curps)
        if curp_entidad:
            fields.append(_make_field("entidad_nacimiento", "Entidad de nacimiento", curp_entidad, ocr_boxes, confidence=0.6))
        if not birth_date:
            curp_birth = _extract_curp_birth_date(curps)
            if curp_birth:
                fields.append(_make_field("fecha_nacimiento", "Fecha de nacimiento", curp_birth, ocr_boxes, confidence=0.5))
        if not curps and filename:
            name_curps = [match.group(0) for match in CURP_PATTERN.finditer(filename.upper())]
            for value in name_curps:
                fields.append(_make_field("curp", "CURP", _normalize_alnum(value), ocr_boxes, confidence=0.9))

    if document_type in {"CONSTANCIA_SITUACION_FISCAL", "DATOS_BANCARIOS"}:
        for value in rfcs:
            fields.append(_make_field("rfc", "RFC", _normalize_alnum(value), ocr_boxes))
        labeled_rfc = _find_labeled_value(lines, "RFC")
        if labeled_rfc:
            fields.append(_make_field("rfc", "RFC", _normalize_alnum(labeled_rfc), ocr_boxes, confidence=0.8))

    if document_type == "NSS":
        for value in nss:
            fields.append(_make_field("nss", "NSS", _normalize_alnum(value), ocr_boxes))
        afiliacion = _find_value_after_keyword(lines, ["NUMERO DE SEGURIDAD SOCIAL", "NÚMERO DE SEGURIDAD SOCIAL", "SEGURIDAD SOCIAL"])
        if afiliacion:
            fields.append(_make_field("nss", "NSS", _normalize_numeric_field(afiliacion), ocr_boxes, confidence=0.7))

    if document_type == "DATOS_BANCARIOS":
        for value in clabes:
            fields.append(_make_field("clabe", "CLABE", _normalize_alnum(value), ocr_boxes))
        banco = _find_value_after_keyword(lines, ["BANCO", "INSTITUCION", "INSTITUCIÓN"])
        if banco:
            fields.append(_make_field("banco", "Banco", _normalize_address(banco), ocr_boxes, confidence=0.6))
        labeled_clabe = _find_labeled_value(lines, "CLABE")
        if labeled_clabe:
            fields.append(_make_field("clabe", "CLABE", _normalize_numeric_field(labeled_clabe), ocr_boxes, confidence=0.8))

    if document_type in {"ACTA_NACIMIENTO", "INE"}:
        for value in dates:
            fields.append(_make_field("fecha", "Fecha", _normalize_date_value(value), ocr_boxes, confidence=0.6))
        folio = _find_value_after_keyword(lines, ["FOLIO", "ACTA"])
        if folio:
            fields.append(_make_field("folio", "Folio", folio, ocr_boxes, confidence=0.6))
        if document_type == "ACTA_NACIMIENTO":
            libro = _find_value_after_keyword(lines, ["LIBRO"])
            if libro:
                fields.append(_make_field("libro", "Libro", _normalize_alnum(libro), ocr_boxes, confidence=0.6))
            tomo = _find_value_after_keyword(lines, ["TOMO"])
            if tomo:
                fields.append(_make_field("tomo", "Tomo", _normalize_alnum(tomo), ocr_boxes, confidence=0.6))
            oficialia = _find_value_after_keyword(lines, ["OFICIALIA", "OFICIALÍA"])
            if oficialia:
                fields.append(_make_field("oficialia", "Oficialía", _normalize_alnum(oficialia), ocr_boxes, confidence=0.6))
            registro_civil = _find_value_after_keyword(lines, ["REGISTRO CIVIL"])
            if registro_civil:
                fields.append(_make_field("registro_civil", "Registro civil", _normalize_address(registro_civil), ocr_boxes, confidence=0.6))
            juez = _find_value_after_keyword(lines, ["JUEZ", "JUEZA"])
            if juez:
                fields.append(_make_field("juez", "Juez", _normalize_name(juez), ocr_boxes, confidence=0.6))

    if document_type == "COMPROBANTE_DOMICILIO":
        address = _pick_address(lines)
        if address:
            fields.append(_make_field("domicilio", "Domicilio", _normalize_address(address), ocr_boxes, confidence=0.8))
            cp = _extract_postal_code(address)
            if cp:
                fields.append(_make_field("cp", "CP", cp, ocr_boxes, confidence=0.7))
        city, state = _extract_city_state(lines)
        if city:
            fields.append(_make_field("ciudad", "Ciudad", _normalize_address(city), ocr_boxes, confidence=0.6))
        if state:
            fields.append(_make_field("estado", "Estado", _normalize_address(state), ocr_boxes, confidence=0.6))
        referencia = _find_value_after_keyword(lines, ["REFERENCIA", "REFERENCIA DE PAGO", "NUMERO DE SERVICIO", "NÚMERO DE SERVICIO"])
        if referencia:
            fields.append(_make_field("referencia", "Referencia", referencia, ocr_boxes, confidence=0.7))

    for label, key in LABEL_MAP.items():
        labeled_value = _find_labeled_value(lines, label)
        if labeled_value:
            fields.append(_make_field(key, label, labeled_value, ocr_boxes, confidence=0.85))

    if base_text:
        snippet = base_text.strip()
        if len(snippet) > 1200:
            snippet = snippet[:1200].rstrip() + "..."
        fields.insert(0, _make_field("texto_detectado", "Texto detectado", snippet, ocr_boxes, confidence=1.0))

    if not fields:
        for value in curps:
            fields.append(_make_field("curp", "CURP", _normalize_alnum(value), ocr_boxes))
        for value in rfcs:
            fields.append(_make_field("rfc", "RFC", _normalize_alnum(value), ocr_boxes))
        for value in nss:
            fields.append(_make_field("nss", "NSS", _normalize_alnum(value), ocr_boxes))
        for value in clabes:
            fields.append(_make_field("clabe", "CLABE", _normalize_alnum(value), ocr_boxes))
        if not fields and filename:
            name_curps = [match.group(0) for match in CURP_PATTERN.finditer(filename.upper())]
            for value in name_curps:
                fields.append(_make_field("curp", "CURP", _normalize_alnum(value), ocr_boxes, confidence=0.9))

    return _dedupe_fields(fields)
