import re
import json
import os

from app.pipelines.legacy_adapter import legacy_extract_fields

CURP_PATTERN = re.compile(r"\b[A-Z][AEIOUX][A-Z]{2}\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[HM][A-Z]{5}[A-Z0-9]\d\b")
RFC_PATTERN = re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b")
NSS_PATTERN = re.compile(r"\b\d{11}\b")
CLABE_PATTERN = re.compile(r"\b\d{18}\b")
ACCOUNT_PATTERN = re.compile(r"\b\d{10,16}\b")
AMOUNT_PATTERN = re.compile(r"\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\b")
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

LABEL_ALIASES = {
    "NOMBRE": ["NOMBRE", "NOMBRES", "APELLIDO", "APELLIDOS", "APELLIDO PATERNO", "APELLIDO MATERNO", "NOMBRE(S)"],
    "CURP": ["CURP", "CLAVE UNICA DE REGISTRO DE POBLACION"],
    "RFC": ["RFC", "R.F.C.", "REGISTRO FEDERAL DE CONTRIBUYENTES"],
    "SEXO": ["SEXO", "GENERO", "GEN"],
    "DOMICILIO": ["DOMICILIO", "DIRECCION", "DIR"],
    "FECHA DE NACIMIENTO": ["FECHA DE NACIMIENTO", "FECHA NACIMIENTO", "F NACIMIENTO", "NACIMIENTO"],
    "LUGAR DE NACIMIENTO": ["LUGAR DE NACIMIENTO", "LUGAR NACIMIENTO"],
    "ENTIDAD DE REGISTRO": ["ENTIDAD DE REGISTRO", "ENTIDAD REGISTRO"],
    "MUNICIPIO DE REGISTRO": ["MUNICIPIO DE REGISTRO", "MUNICIPIO REGISTRO", "MUNICLPIO DE REGISTRO"],
    "FECHA DE REGISTRO": ["FECHA DE REGISTRO", "FECHA REGISTRO"],
    "NUMERO DE ACTA": ["NUMERO DE ACTA", "NUMERO ACTA", "NO ACTA", "NRO ACTA", "NUMERO DE ACTE", "NUMERO ACTE"],
    "NUMERO DE CERTIFICADO DE NACIMIENTO": [
        "NUMERO DE CERTIFICADO DE NACIMIENTO",
        "NUMERO CERTIFICADO",
        "NO CERTIFICADO",
        "CERTIFICADO NACIMIENTO",
    ],
    "NUMERO DE SERVICIO": ["NUMERO DE SERVICIO", "NUMERO SERVICIO", "NO SERVICIO", "NRO SERVICIO", "SERVICIO"],
    "NUMERO DE CLIENTE": ["NUMERO DE CLIENTE", "NO CLIENTE", "NRO CLIENTE", "CLIENTE"],
    "FECHA DE CORTE": ["FECHA DE CORTE", "FECHA CORTE"],
    "FECHA LIMITE": ["FECHA LIMITE", "F LIMITE", "VENCE"],
    "CLAVE DE ELECTOR": ["CLAVE DE ELECTOR", "CLAVE ELECTOR", "CLAVE ELECT"],
    "SECCION": ["SECCION", "SECC"],
}

LEGACY_LABELS = {
    "nombre": "Nombre",
    "nombres": "Nombres",
    "apellido_paterno": "Apellido paterno",
    "apellido_materno": "Apellido materno",
    "sexo": "Sexo",
    "domicilio": "Domicilio",
    "clave_elector": "Clave de elector",
    "curp": "CURP",
    "anio_registro": "Año de registro",
    "fecha_nacimiento": "Fecha de nacimiento",
    "seccion": "Sección",
    "vigencia": "Vigencia",
    "entidad_registro": "Entidad de registro",
    "municipio_registro": "Municipio de registro",
    "primer_apellido": "Primer apellido",
    "segundo_apellido": "Segundo apellido",
    "lugar_nacimiento": "Lugar de nacimiento",
    "fecha_emision": "Fecha de emisión",
    "nss": "NSS",
    "fecha_documento": "Fecha documento",
    "folio_solicitud": "Folio solicitud",
    "rfc": "RFC",
    "cp": "CP",
    "id_cif": "Id CIF",
    "regimen": "Régimen",
    "banco": "Banco",
    "titular": "Titular",
    "clabe": "CLABE",
    "cuenta": "Cuenta",
    "proveedor": "Proveedor",
}

LEGACY_OVERRIDE_KEYS = {
    "seccion",
    "vigencia",
    "sexo",
    "clave_elector",
    "curp",
}


def _normalize_legacy_value(key: str, value: str) -> str:
    if value is None:
        return ""
    if key in {"curp", "rfc", "clave_elector", "folio_solicitud"}:
        return _normalize_alnum(value)
    if key in {"nss", "clabe", "cuenta", "cp", "seccion"}:
        return _normalize_numeric_field(value)
    if key in {"fecha_nacimiento", "fecha_emision", "fecha_documento"}:
        return _normalize_date_value(value)
    if key in {"domicilio", "lugar_nacimiento", "entidad_registro", "municipio_registro", "banco"}:
        return _normalize_address(value)
    if key in {"nombre", "nombres", "apellido_paterno", "apellido_materno", "primer_apellido", "segundo_apellido", "titular"}:
        return _normalize_name(value)
    if key == "sexo":
        return _normalize_sex(value)
    return _normalize_text(value)


def _merge_legacy_fields(fields: list[dict], legacy_values: dict[str, str], ocr_boxes):
    existing = {field.get("key"): field for field in fields if field.get("value")}
    for key, value in legacy_values.items():
        if not value:
            continue
        label = LEGACY_LABELS.get(key, key)
        normalized = _normalize_legacy_value(key, value)
        if not normalized:
            continue
        if key not in LEGACY_OVERRIDE_KEYS and key in existing:
            continue
        confidence = 0.9 if key in LEGACY_OVERRIDE_KEYS else 0.65
        fields.append(_make_field(key, label, normalized, ocr_boxes, confidence=confidence))

def _load_alias_model():
    path = os.getenv("FIELD_ALIAS_PATH", os.path.join(os.path.dirname(__file__), "..", "models", "field_aliases.json"))
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


ALIASES_FROM_MODEL = _load_alias_model()


def _merge_aliases(label: str) -> list[str]:
    base = LABEL_ALIASES.get(label, [label])
    extra = ALIASES_FROM_MODEL.get(LABEL_MAP.get(label, label), [])
    return list(dict.fromkeys([*base, *extra]))

STATE_CODE_TO_NAME = {
    "AS": "AGUASCALIENTES",
    "BC": "BAJA CALIFORNIA",
    "BS": "BAJA CALIFORNIA SUR",
    "CC": "CAMPECHE",
    "CL": "COAHUILA",
    "CM": "COLIMA",
    "CS": "CHIAPAS",
    "CH": "CHIHUAHUA",
    "DF": "CIUDAD DE MEXICO",
    "DG": "DURANGO",
    "GT": "GUANAJUATO",
    "GR": "GUERRERO",
    "HG": "HIDALGO",
    "JC": "JALISCO",
    "MC": "MEXICO",
    "MN": "MICHOACAN",
    "MS": "MORELOS",
    "NT": "NAYARIT",
    "NL": "NUEVO LEON",
    "OC": "OAXACA",
    "PL": "PUEBLA",
    "QT": "QUERETARO",
    "QR": "QUINTANA ROO",
    "SP": "SAN LUIS POTOSI",
    "SL": "SINALOA",
    "SR": "SONORA",
    "TC": "TABASCO",
    "TS": "TAMAULIPAS",
    "TL": "TLAXCALA",
    "VZ": "VERACRUZ",
    "YN": "YUCATAN",
    "ZS": "ZACATECAS",
    "NE": "NACIDO EN EL EXTRANJERO",
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


def _normalize_keyword(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _is_reasonable_acta_optional(value: str) -> bool:
    if not value:
        return False
    cleaned = _normalize_text(value).upper()
    if len(cleaned) > 30:
        return False
    if any(token in cleaned for token in ["FIRMA", "ELECTRON", "EXPEDICION", "CERTIF", "ANOTAC", "REGLAMENTO"]):
        return False
    letters = sum(1 for ch in cleaned if ch.isalpha())
    return letters >= 2


_LOW_CONF_DROP_BY_TYPE = {
    "INE": {
        "nombres",
        "apellido_paterno",
        "apellido_materno",
        "fecha",
        "entidad_nacimiento",
        "anio_registro",
    },
    "ACTA_NACIMIENTO": {
        "libro",
        "tomo",
        "oficialia",
        "registro_civil",
        "juez",
        "primer_apellido",
        "segundo_apellido",
        "anio_registro",
    },
    "COMPROBANTE_DOMICILIO": {
        "periodo",
    },
    "CONSTANCIA_SITUACION_FISCAL": {
        "cp",
        "id_cif",
        "fecha_emision",
    },
    "CURP": {
        "entidad_registro",
    },
    "NSS": {
        "fecha_documento",
        "folio_solicitud",
    },
}


def _postprocess_fields(document_type: str, fields: list[dict]) -> list[dict]:
    cleaned = []
    drop_low = _LOW_CONF_DROP_BY_TYPE.get(document_type, set())
    for field in fields:
        key = field.get("key")
        if key == "texto_detectado":
            cleaned.append(field)
            continue
        if key in drop_low and field.get("confidence", 1) < 0.7:
            continue
        if key in {"registro_civil", "juez"} and field.get("valid") is False:
            continue
        cleaned.append(field)
    return cleaned


def _label_key(text: str) -> str:
    text = text.upper()
    text = text.replace("0", "O").replace("1", "I").replace("5", "S").replace("8", "B")
    return re.sub(r"[^A-Z0-9]", "", text)


def _label_key_no_vowels(text: str) -> str:
    return re.sub(r"[AEIOU]", "", _label_key(text))


def _expand_label_list(label):
    if isinstance(label, (list, tuple, set)):
        labels = []
        for item in label:
            labels.extend(_expand_label_list(item))
        return labels
    return _merge_aliases(label)


def _label_match(line_text: str, label: str) -> bool:
    label_key = _label_key(label)
    line_key = _label_key(line_text)
    if label_key and label_key in line_key:
        return True
    label_nv = _label_key_no_vowels(label)
    line_nv = _label_key_no_vowels(line_text)
    return bool(label_nv and label_nv in line_nv)


def _bbox_to_rect(bbox):
    if not bbox:
        return None
    xs = [point[0] for point in bbox]
    ys = [point[1] for point in bbox]
    return min(xs), min(ys), max(xs), max(ys)


def _boxes_with_rect(ocr_boxes):
    boxed = []
    for box in ocr_boxes or []:
        rect = _bbox_to_rect(box.get("bbox", []))
        if rect is None:
            continue
        boxed.append({**box, "rect": rect})
    return boxed


def _line_groups(boxes, y_tol=12):
    lines = []
    for box in sorted(boxes, key=lambda b: (b["rect"][1], b["rect"][0])):
        x1, y1, x2, y2 = box["rect"]
        placed = False
        for line in lines:
            ly = line["y"]
            if abs(y1 - ly) <= y_tol:
                line["boxes"].append(box)
                line["y"] = (ly + y1) / 2
                placed = True
                break
        if not placed:
            lines.append({"y": y1, "boxes": [box]})
    for line in lines:
        line["boxes"].sort(key=lambda b: b["rect"][0])
        line["text"] = " ".join(b.get("text", "").strip() for b in line["boxes"] if b.get("text"))
        line["text_norm"] = _normalize_keyword(line["text"])
    return lines


def _lines_text_from_boxes(ocr_boxes):
    boxes = _boxes_with_rect(ocr_boxes)
    lines = _line_groups(boxes)
    return lines


def _extract_label_value(lines, label, stop_labels=None, value_regex=None):
    line = _find_label_line(lines, label)
    if not line:
        return None
    right = _value_right_of_label(line, label)
    if right:
        candidate = right.get("text", "").strip()
        if value_regex is None or value_regex.search(candidate):
            return candidate
    labels = _expand_label_list(label)
    line_text = line.get("text", "")
    for alias in labels:
        tokens = [tok for tok in alias.strip().split() if tok]
        if not tokens:
            continue
        pattern = r"(?i)" + r"\\s*".join(re.escape(tok) for tok in tokens) + r"\\s*[:\\-]?\\s*(.+)$"
        match = re.search(pattern, line_text)
        if match:
            candidate = match.group(1).strip()
            if candidate and (value_regex is None or value_regex.search(candidate)):
                return candidate
    if stop_labels is None:
        stop_labels = []
    below = _collect_below(lines, line, stop_labels, max_lines=1)
    if below:
        candidate = below[0]["text"].strip()
        if value_regex is None or value_regex.search(candidate):
            return candidate
    return None


def _extract_curp_from_boxes(ocr_boxes):
    boxes = _boxes_with_rect(ocr_boxes)
    lines = _line_groups(boxes)
    result = {}

    def find_pattern_in_boxes(pattern):
        for box in boxes:
            text = box.get("text", "").upper()
            match = pattern.search(text)
            if match:
                return match.group(0), box
        return None, None

    curp_value, curp_box = find_pattern_in_boxes(CURP_PATTERN)
    if curp_value:
        result["curp"] = {"value": curp_value, "source": curp_box}

    nombre = _extract_label_value(lines, "NOMBRE", stop_labels=["CURP", "FECHA", "SEXO", "DOMICILIO"])
    if nombre:
        result["nombre"] = {"value": nombre}

    fecha = _extract_label_value(lines, "FECHA DE NACIMIENTO", stop_labels=["CURP", "SEXO"], value_regex=DATE_PATTERN)
    if not fecha:
        fecha = _extract_label_value(lines, "FECHADENACIMIENTO", stop_labels=["CURP", "SEXO"], value_regex=DATE_PATTERN)
    if fecha:
        result["fecha_nacimiento"] = {"value": fecha}

    sexo = _extract_label_value(lines, "SEXO", stop_labels=["CURP", "FECHA"])
    if sexo:
        result["sexo"] = {"value": sexo}

    entidad = _extract_label_value(lines, "ENTIDAD", stop_labels=["CURP", "FECHA"])
    if not entidad:
        entidad = _extract_label_value(lines, "ESTADO", stop_labels=["CURP", "FECHA"])
    if entidad:
        result["entidad_nacimiento"] = {"value": entidad}

    return result


def _extract_acta_from_boxes(ocr_boxes):
    boxes = _boxes_with_rect(ocr_boxes)
    lines = _line_groups(boxes)
    result = {}
    full_text = " ".join(line["text"] for line in lines if line.get("text"))
    full_text = _normalize_text(full_text).upper()

    def pick(label, regex=None):
        return _extract_label_value(
            lines,
            label,
            stop_labels=["LIBRO", "TOMO", "OFICIALIA", "REGISTRO", "FOLIO", "FECHA"],
            value_regex=regex,
        )

    folio = pick("FOLIO", re.compile(r"\b\d{1,6}\b"))
    if folio and re.fullmatch(r"\d{1,6}", folio.strip()):
        result["folio"] = {"value": folio}
    fecha = pick("FECHA", DATE_PATTERN)
    if fecha:
        match = DATE_PATTERN.search(fecha)
        result["fecha"] = {"value": match.group(0) if match else fecha}
    libro = pick("LIBRO")
    if libro:
        result["libro"] = {"value": libro}
    tomo = pick("TOMO")
    if tomo:
        result["tomo"] = {"value": tomo}
    oficialia = pick("OFICIALIA")
    if oficialia:
        result["oficialia"] = {"value": oficialia}
    registro = pick("REGISTRO CIVIL")
    if registro:
        result["registro_civil"] = {"value": registro}
    juez = pick("JUEZ")
    if juez:
        result["juez"] = {"value": juez}

    def _clean_name_piece(value: str) -> str | None:
        if not value:
            return None
        cleaned = re.sub(r"[^A-ZÃÃ‰ÃÃ“ÃšÃ‘ ]", " ", value.upper()).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if not cleaned:
            return None
        if "APELLIDO" in cleaned or cleaned.endswith(":"):
            return None
        return cleaned

    nombre = _extract_label_value(lines, "NOMBRE", stop_labels=["FECHA", "FOLIO", "LIBRO", "TOMO"])
    if nombre:
        upper_nombre = nombre.upper()
        if "APELLIDO" not in upper_nombre and not upper_nombre.endswith(":"):
            result["nombre"] = {"value": nombre}
    else:
        match = re.search(r"DATOS DE LA PERSONA REGISTRADA\s+(.+?)\s+NOMBRE", full_text)
        if match:
            result["nombre"] = {"value": match.group(1).strip()}
        else:
            match = re.search(r"PERSONA REGISTRADA\s+(.+?)\s+SEXO", full_text)
            if match:
                result["nombre"] = {"value": match.group(1).strip()}
    if "nombre" not in result:
        section_idx = next((i for i, line in enumerate(lines) if "DATOS DE LA PERSONA REGISTRADA" in line.get("text", "").upper()), None)
        if section_idx is not None:
            name_lines = []
            for line in lines[section_idx + 1:section_idx + 6]:
                text_line = line.get("text", "").strip()
                if not text_line:
                    continue
                upper = text_line.upper()
                if "NOMBRE" in upper or "APELLIDO" in upper or "SEXO" in upper:
                    break
                name_lines.append(upper)
                if len(name_lines) >= 3:
                    break
            if name_lines:
                result["nombre"] = {"value": " ".join(name_lines)}
        if "nombre" not in result:
            nombre_part = _clean_name_piece(_extract_label_value(lines, "NOMBRE(S)", stop_labels=["PRIMER", "SEGUNDO", "SEXO", "FECHA"]))
            primer_apellido = _clean_name_piece(_extract_label_value(lines, "PRIMER APELLIDO", stop_labels=["SEGUNDO", "SEXO", "FECHA"]))
            segundo_apellido = _clean_name_piece(_extract_label_value(lines, "SEGUNDO APELLIDO", stop_labels=["SEXO", "FECHA"]))
            parts = [p for p in [nombre_part, primer_apellido, segundo_apellido] if p]
            if parts:
                result["nombre"] = {"value": " ".join(parts)}
            else:
                label_line = _find_label_line(lines, "NOMBRE")
                if label_line:
                    below = _collect_below(lines, label_line, stop_labels=["SEXO", "FECHA", "LUGAR", "MUNICIPIO"], max_lines=2)
                    if below:
                        candidate = " ".join(line.get("text", "").strip() for line in below if line.get("text"))
                        candidate = candidate.strip()
                        if candidate:
                            result["nombre"] = {"value": candidate}

    sexo = _extract_label_value(lines, "SEXO", stop_labels=["FECHA", "LUGAR", "MUNICIPIO"])
    if sexo:
        normalized = _normalize_sex(sexo)
        if normalized in {"H", "M"}:
            result["sexo"] = {"value": normalized}

    fecha_nacimiento = _extract_label_value(
        lines, "FECHA DE NACIMIENTO", stop_labels=["SEXO", "LUGAR", "MUNICIPIO"], value_regex=DATE_PATTERN
    )
    if fecha_nacimiento:
        result["fecha_nacimiento"] = {"value": fecha_nacimiento}
    else:
        match = re.search(r"FECHA DE NACIMIENTO\s*[:\-]?\s*(\d{2}[/-]\d{2}[/-]\d{4})", full_text)
        if match:
            result["fecha_nacimiento"] = {"value": match.group(1).strip()}
        else:
            curp_match = CURP_PATTERN.search(full_text)
            if curp_match:
                curp_birth = _extract_curp_birth_date([curp_match.group(0)])
                if curp_birth:
                    result["fecha_nacimiento"] = {"value": curp_birth}
    if "fecha_nacimiento" in result and "fecha_registro" in result:
        curp_match = CURP_PATTERN.search(full_text)
        if curp_match:
            curp_birth = _extract_curp_birth_date([curp_match.group(0)])
            if curp_birth and result["fecha_nacimiento"]["value"] == result["fecha_registro"]["value"]:
                result["fecha_nacimiento"] = {"value": curp_birth}

    lugar_nacimiento = _extract_label_value(lines, "LUGAR DE NACIMIENTO", stop_labels=["MUNICIPIO", "ENTIDAD", "FECHA"])
    if lugar_nacimiento:
        upper_lugar = lugar_nacimiento.upper()
        if "DATOS DE FILIACION" not in upper_lugar and "PERSONA REGISTRADA" not in upper_lugar:
            result["lugar_nacimiento"] = {"value": lugar_nacimiento}
        else:
            lugar_nacimiento = None
    else:
        match = re.search(
            r"LUGAR DE NACIMIENTO\s*[:\-]?\s*([A-Z ]{3,}?)\s+(SEXO|FECHA|MUNICIPIO|ENTIDAD|REGISTRO)",
            full_text,
        )
        if match:
            candidate = match.group(1).strip()
            upper_candidate = candidate.upper()
            if "DATOS" not in upper_candidate and "PERSONA REGISTRADA" not in upper_candidate:
                result["lugar_nacimiento"] = {"value": candidate}
        else:
            label_line = _find_label_line(lines, "LUGAR DE NACIMIENTO")
            if label_line:
                below = _collect_below(lines, label_line, stop_labels=["MUNICIPIO", "ENTIDAD", "FECHA"], max_lines=2)
                if below:
                    candidate = " ".join(line.get("text", "").strip() for line in below if line.get("text"))
                    candidate = candidate.strip()
                    if candidate and "DATOS" not in candidate.upper():
                        result["lugar_nacimiento"] = {"value": candidate}

    if "sexo" not in result or "fecha_nacimiento" not in result or "lugar_nacimiento" not in result:
        name_labels = next((i for i, line in enumerate(lines) if "NOMBRE(S)" in line.get("text", "").upper() and "APELLIDO" in line.get("text", "").upper()), None)
        if name_labels is not None and name_labels + 3 < len(lines):
            line1 = lines[name_labels + 1].get("text", "").strip().upper()
            line2 = lines[name_labels + 2].get("text", "").strip().upper()
            line3 = lines[name_labels + 3].get("text", "").strip().upper()
            if "sexo" not in result and ("HOMBRE" in line2 or "MUJER" in line2):
                result["sexo"] = {"value": "H" if "HOMBRE" in line2 else "M"}
            if "fecha_nacimiento" not in result:
                date_match = DATE_PATTERN.search(line2)
                if date_match:
                    result["fecha_nacimiento"] = {"value": date_match.group(0)}
            if "lugar_nacimiento" not in result:
                place_parts = []
                for candidate in (line1, line3):
                    if candidate and not re.search(r"\d", candidate) and "DATOS" not in candidate and "PERSONA" not in candidate:
                        place_parts.append(candidate)
                if place_parts:
                    result["lugar_nacimiento"] = {"value": " ".join(place_parts)}
        sexo_label = _find_label_line(lines, "SEXO")
        if not sexo_label:
            sexo_label = next((line for line in lines if "SEXO" in line.get("text", "").upper()), None)
        if sexo_label:
            try:
                idx = lines.index(sexo_label)
            except ValueError:
                idx = -1
            if idx > 0:
                for probe in range(idx - 1, max(idx - 6, -1), -1):
                    text_line = lines[probe].get("text", "").strip().upper()
                    if not text_line:
                        continue
                    if "HOMBRE" in text_line or "MUJER" in text_line or text_line in {"H", "M"}:
                        if "sexo" not in result:
                            result["sexo"] = {"value": "H" if "H" in text_line else "M"}
                        continue
                    date_match = DATE_PATTERN.search(text_line)
                    if date_match and "fecha_nacimiento" not in result:
                        result["fecha_nacimiento"] = {"value": date_match.group(0)}
                        continue
                if "lugar_nacimiento" not in result:
                    place_parts = []
                    for probe in range(idx - 1, max(idx - 6, -1), -1):
                        text_line = lines[probe].get("text", "").strip().upper()
                        if not text_line:
                            continue
                        if DATE_PATTERN.search(text_line):
                            continue
                        if "HOMBRE" in text_line or "MUJER" in text_line:
                            continue
                        if "NOMBRE" in text_line or "APELLIDO" in text_line or "SEXO" in text_line:
                            continue
                        if re.search(r"\d", text_line):
                            continue
                        place_parts.append(text_line)
                        if len(place_parts) >= 2:
                            break
                    if place_parts:
                        result["lugar_nacimiento"] = {"value": " ".join(reversed(place_parts))}
        if "lugar_nacimiento" not in result:
            lugar_label = _find_label_line(lines, "LUGAR DE NACIMIENTO")
            if lugar_label:
                try:
                    lidx = lines.index(lugar_label)
                except ValueError:
                    lidx = -1
                if lidx > 0:
                    place_parts = []
                    for probe in range(lidx - 1, max(lidx - 6, -1), -1):
                        text_line = lines[probe].get("text", "").strip().upper()
                        if not text_line:
                            continue
                        if DATE_PATTERN.search(text_line):
                            continue
                        if "HOMBRE" in text_line or "MUJER" in text_line:
                            continue
                        if "NOMBRE" in text_line or "APELLIDO" in text_line or "SEXO" in text_line:
                            continue
                        if re.search(r"\d", text_line):
                            continue
                        place_parts.append(text_line)
                        if len(place_parts) >= 2:
                            break
                    if place_parts:
                        result["lugar_nacimiento"] = {"value": " ".join(reversed(place_parts))}
        if "sexo" not in result and "HOMBRE" in full_text:
            result["sexo"] = {"value": "H"}
        if "sexo" not in result and "MUJER" in full_text:
            result["sexo"] = {"value": "M"}

    entidad_registro = _extract_label_value(lines, "ENTIDAD DE REGISTRO", stop_labels=["MUNICIPIO", "ESTADOS", "ACTA"])
    if entidad_registro:
        result["entidad_registro"] = {"value": entidad_registro}
    else:
        label_line = _find_label_line(lines, "ENTIDAD DE REGISTRO")
        if label_line:
            try:
                idx = lines.index(label_line)
            except ValueError:
                idx = -1
            if idx >= 0:
                for probe in lines[idx + 1:idx + 4]:
                    candidate = probe.get("text", "").strip()
                    if not candidate:
                        continue
                    upper = candidate.upper()
                    if "ACTA" in upper or "REGISTRO" in upper:
                        continue
                    result["entidad_registro"] = {"value": candidate}
                    break

    municipio_registro = _extract_label_value(lines, "MUNICIPIO DE REGISTRO", stop_labels=["FECHA", "LIBRO", "ACTA"])
    if municipio_registro:
        result["municipio_registro"] = {"value": municipio_registro}
    else:
        label_line = _find_label_line(lines, "MUNICIPIO DE REGISTRO")
        if label_line:
            try:
                idx = lines.index(label_line)
            except ValueError:
                idx = -1
            if idx >= 0 and idx + 1 < len(lines):
                candidate = lines[idx + 1].get("text", "").strip()
                if candidate:
                    result["municipio_registro"] = {"value": candidate}

    fecha_registro = _extract_label_value(
        lines, "FECHA DE REGISTRO", stop_labels=["LIBRO", "ACTA", "OFICIALIA"], value_regex=DATE_PATTERN
    )
    if fecha_registro:
        match = DATE_PATTERN.search(fecha_registro)
        result["fecha_registro"] = {"value": match.group(0) if match else fecha_registro}

    numero_acta = _extract_label_value(lines, "NUMERO DE ACTA", stop_labels=["FECHA", "OFICIALIA", "LIBRO"])
    if numero_acta and re.fullmatch(r"\d{1,6}", numero_acta.strip()):
        result["numero_acta"] = {"value": numero_acta}

    numero_certificado = _extract_label_value(
        lines, "NUMERO DE CERTIFICADO DE NACIMIENTO", stop_labels=["IDENTIFICADOR", "ENTIDAD"]
    )
    if numero_certificado:
        result["numero_certificado"] = {"value": numero_certificado}

    identificador = _extract_label_value(lines, "IDENTIFICADOR ELECTRONICO", stop_labels=["DATOS", "ENTIDAD"])
    if identificador:
        result["identificador_electronico"] = {"value": identificador}

    if "sexo" not in result or "fecha_nacimiento" not in result or "lugar_nacimiento" not in result:
        match = re.search(
            r"(HOMBRE|MUJER|H|M)\s+(\d{2}[/-]\d{2}[/-]\d{4})\s+([A-Z ]{3,}?)\s+SEXO\s+FECHA DE NACIMIENTO\s+LUGAR DE NACIMIENTO",
            full_text,
        )
        if match:
            if "sexo" not in result:
                result["sexo"] = {"value": match.group(1)}
            if "fecha_nacimiento" not in result:
                result["fecha_nacimiento"] = {"value": match.group(2)}
            if "lugar_nacimiento" not in result:
                result["lugar_nacimiento"] = {"value": match.group(3).strip()}

    if "entidad_registro" not in result:
        match = re.search(
            r"ENTIDAD DE REGISTRO\s+([A-Z ]{3,}?)\s+(ESTADOS UNIDOS|ACTA|CERTIFICADO|IDENTIFICADOR|MUNICIPIO)",
            full_text,
        )
        if match:
            result["entidad_registro"] = {"value": match.group(1).strip()}

    if "municipio_registro" not in result:
        match = re.search(
            r"MUNICIPIO DE REGISTRO\s+([A-Z ]{3,}?)\s+(FECHA DE REGISTRO|LIBRO|ACTA|OFICIALIA)",
            full_text,
        )
        if match:
            result["municipio_registro"] = {"value": match.group(1).strip()}

    if "fecha_registro" not in result:
        match = re.search(r"FECHA DE REGISTRO\s+(\d{2}[/-]\d{2}[/-]\d{4})", full_text)
        if match:
            result["fecha_registro"] = {"value": match.group(1).strip()}

    if "numero_acta" not in result or "folio" not in result:
        acta_line = next((line for line in lines if "NUMERO DE ACT" in line.get("text", "").upper()), None)
        if acta_line:
            try:
                idx = lines.index(acta_line)
            except ValueError:
                idx = -1
            candidates = []
            if idx >= 0:
                for probe in lines[idx + 1:idx + 6]:
                    text_line = probe.get("text", "").strip()
                    if not text_line:
                        continue
                    text_line = DATE_PATTERN.sub(" ", text_line)
                    nums = re.findall(r"\b\d{1,6}\b", text_line)
                    candidates.extend(nums)
            filtered = [t for t in candidates if not (len(t) == 4 and t.startswith(("19", "20")))]
            if filtered:
                if len(filtered) >= 2:
                    result["folio"] = {"value": filtered[0]}
                    result["numero_acta"] = {"value": filtered[-1]}
                else:
                    if "folio" not in result or not re.fullmatch(r"\d{1,6}", str(result["folio"]["value"]).strip()):
                        result["folio"] = {"value": filtered[0]}
    if "numero_acta" not in result:
        match = re.search(r"NUMERO DE ACT[AE]\s+([A-Z0-9-]{3,})", full_text)
        if match:
            result["numero_acta"] = {"value": match.group(1).strip()}

    return result


def _extract_financial_from_boxes(ocr_boxes):
    boxes = _boxes_with_rect(ocr_boxes)
    lines = _line_groups(boxes)
    result = {}

    bank_keywords = {
        "BBVA": "BBVA",
        "BANCOMER": "BBVA",
        "BANAMEX": "BANAMEX",
        "SANTANDER": "SANTANDER",
        "SCOTIABANK": "SCOTIABANK",
        "HSBC": "HSBC",
        "BANORTE": "BANORTE",
        "AZTECA": "BANCO AZTECA",
    }
    bank_code_map = {
        "002": "BANAMEX",
        "012": "BBVA",
        "014": "SANTANDER",
        "021": "HSBC",
        "030": "BANCO DEL BAJIO",
        "032": "IXE",
        "044": "SCOTIABANK",
        "058": "BANREGIO",
        "072": "BANORTE",
        "127": "BANCO AZTECA",
        "137": "BANCOPPEL",
    }

    def find_pattern_in_boxes(pattern):
        for box in boxes:
            text = box.get("text", "").upper()
            match = pattern.search(text)
            if match:
                return match.group(0), box
        return None, None

    # Bank name from top lines
    for line in lines[:10]:
        for keyword, bank_name in bank_keywords.items():
            if keyword in line["text"].upper():
                result["banco"] = {"value": bank_name}
                break
        if "banco" in result:
            break
    clabe_value, clabe_box = find_pattern_in_boxes(CLABE_PATTERN)
    if clabe_value:
        result["clabe"] = {"value": clabe_value, "source": clabe_box}
        if "banco" not in result:
            bank_code = clabe_value[:3]
            if bank_code in bank_code_map:
                result["banco"] = {"value": bank_code_map[bank_code]}
    else:
        # Detect CLABE with spaces: extract digits from CLABE line or nearby
        for idx, line in enumerate(lines):
            if "CLABE" in line["text"].upper():
                candidate_texts = [line["text"]]
                if idx + 1 < len(lines):
                    candidate_texts.append(lines[idx + 1]["text"])
                for text in candidate_texts:
                    digits = re.sub(r"\D", "", text)
                    if len(digits) == 18:
                        result["clabe"] = {"value": digits}
                        if "banco" not in result:
                            bank_code = digits[:3]
                            if bank_code in bank_code_map:
                                result["banco"] = {"value": bank_code_map[bank_code]}
                        break
            if "clabe" in result:
                break
        if "clabe" not in result:
            for line in lines:
                digits = re.sub(r"\D", "", line["text"])
                if len(digits) == 18 and digits.startswith("012"):
                    result["clabe"] = {"value": digits}
                    if "banco" not in result:
                        bank_code = digits[:3]
                        if bank_code in bank_code_map:
                            result["banco"] = {"value": bank_code_map[bank_code]}
                    break

    account_value, account_box = find_pattern_in_boxes(ACCOUNT_PATTERN)
    if account_value and "clabe" not in result:
        result["cuenta"] = {"value": account_value, "source": account_box}

    banco = _extract_label_value(lines, "BANCO", stop_labels=["CLABE", "CUENTA", "TITULAR"])
    if banco:
        result["banco"] = {"value": banco}

    no_cuenta = _extract_label_value(lines, "NO. DE CUENTA", stop_labels=["CLABE", "CLIENTE", "RFC"])
    if not no_cuenta:
        no_cuenta = _extract_label_value(lines, "NO CUENTA", stop_labels=["CLABE", "CLIENTE", "RFC"])
    if no_cuenta:
        result["cuenta"] = {"value": no_cuenta}

    no_cliente = _extract_label_value(lines, "NO. DE CLIENTE", stop_labels=["CLABE", "CUENTA", "RFC"])
    if not no_cliente:
        no_cliente = _extract_label_value(lines, "NO CLIENTE", stop_labels=["CLABE", "CUENTA", "RFC"])
    if no_cliente:
        result["cliente_numero"] = {"value": no_cliente}

    rfc = _extract_label_value(lines, "R.F.C.", stop_labels=["CUENTA", "CLABE", "CLIENTE"])
    if not rfc:
        rfc = _extract_label_value(lines, "RFC", stop_labels=["CUENTA", "CLABE", "CLIENTE"])
    if rfc:
        result["rfc"] = {"value": rfc}

    fecha_corte = _extract_label_value(lines, "FECHA DE CORTE", stop_labels=["PERIODO", "CLABE", "CUENTA"], value_regex=DATE_PATTERN)
    if fecha_corte:
        result["fecha_corte"] = {"value": fecha_corte}

    periodo = _extract_label_value(lines, "PERIODO", stop_labels=["FECHA", "CLABE", "CUENTA"])
    if periodo:
        result["periodo"] = {"value": periodo}

    titular = _extract_label_value(lines, "TITULAR", stop_labels=["CLABE", "CUENTA", "BANCO"])
    if not titular:
        titular = _extract_label_value(lines, "NOMBRE", stop_labels=["CLABE", "CUENTA", "BANCO"])
    if titular:
        result["titular"] = {"value": titular}

    return result


def _extract_rfc_from_boxes(ocr_boxes):
    boxes = _boxes_with_rect(ocr_boxes)
    lines = _line_groups(boxes)
    result = {}

    def find_pattern_in_boxes(pattern):
        for box in boxes:
            text = box.get("text", "").upper()
            match = pattern.search(text)
            if match:
                return match.group(0), box
        return None, None

    rfc_value, rfc_box = find_pattern_in_boxes(RFC_WITH_HOMOCLAVE)
    if rfc_value:
        result["rfc"] = {"value": rfc_value, "source": rfc_box}

    nombre = _extract_label_value(lines, "NOMBRE", stop_labels=["RFC", "REGIMEN", "DOMICILIO"])
    if not nombre:
        nombre = _extract_label_value(lines, "RAZON SOCIAL", stop_labels=["RFC", "REGIMEN", "DOMICILIO"])
    if nombre:
        result["nombre"] = {"value": nombre}

    return result


def _extract_nss_from_boxes(ocr_boxes):
    boxes = _boxes_with_rect(ocr_boxes)
    lines = _line_groups(boxes)
    result = {}

    def find_pattern_in_boxes(pattern):
        for box in boxes:
            text = box.get("text", "").upper()
            match = pattern.search(text)
            if match:
                return match.group(0), box
        return None, None

    nss_value, nss_box = find_pattern_in_boxes(NSS_PATTERN)
    if nss_value:
        result["nss"] = {"value": nss_value, "source": nss_box}

    nombre = _extract_label_value(lines, "NOMBRE", stop_labels=["NSS", "IMSS"])
    if not nombre:
        for idx, line in enumerate(lines):
            text = line.get("text", "").upper()
            match = re.search(r"(NOMBRE0RAZ0NSOCIAL|NOMBREO?RAZ0NSOCIAL|RAZON SOCIAL|NOMBRE)[:\-]?\s*([A-Z ]{3,})", text)
            if match:
                nombre = match.group(2).strip()
                break
    if nombre:
        stop_words = {"IMSS", "RFC", "CURP", "FOLIO", "NSS", "MEXICO", "CONTACTO", "PRESENTE", "TARJETA"}
        for line in lines:
            raw_text = line.get("text", "")
            upper_raw = raw_text.upper()
            if re.search(r"\d", raw_text):
                continue
            if "HTTP" in upper_raw or "WWW" in upper_raw or ".COM" in upper_raw:
                continue
            tokens = re.findall(r"[A-ZÃ‘]+", upper_raw)
            if len(tokens) != 1:
                continue
            candidate = re.sub(r"[^A-ZÃ‘]", "", upper_raw)
            if not candidate or candidate in stop_words:
                continue
            if candidate.startswith("HOJA"):
                continue
            if len(candidate) <= 3:
                continue
            if candidate in nombre.replace(" ", ""):
                continue
            # Single surname-like token
            if re.fullmatch(r"[A-ZÃ‘]{4,}", candidate):
                nombre = f"{nombre} {candidate}".strip()
                break
    if nombre:
        result["nombre"] = {"value": nombre}

    return result


def _extract_service_from_boxes(ocr_boxes):
    boxes = _boxes_with_rect(ocr_boxes)
    lines = _line_groups(boxes)
    result = {}

    base_label_map = {
        "NUMERO DE SERVICIO": "numero_servicio",
        "NÚMERO DE SERVICIO": "numero_servicio",
        "NUMERO SERVICIO": "numero_servicio",
        "NO. DE SERVICIO": "numero_servicio",
        "NO DE SERVICIO": "numero_servicio",
        "NO.DESERVICIO": "numero_servicio",
        "NO.DESERVICI0": "numero_servicio",
        "NO. SERVICIO": "numero_servicio",
        "SERVICIO": "numero_servicio",
        "CUENTA": "cuenta",
        "CONTRATO": "contrato",
        "REFERENCIA": "referencia",
        "MEDIDOR": "medidor",
        "CLIENTE": "cliente",
        "TITULAR": "titular",
        "USUARIO": "cliente",
        "CLIENTE/USUARIO": "cliente",
        "RAZON SOCIAL": "cliente",
        "RFC": "rfc",
        "R.F.C.": "rfc",
        "PERIODO": "periodo",
        "FECHA DE CORTE": "fecha_corte",
        "FECHA LIMITE": "fecha_limite",
        "LIMITE DE PAGO": "fecha_limite",
        "TOTAL A PAGAR": "total",
        "IMPORTE A PAGAR": "total",
        "TOTAL": "total",
    }

    provider_map = {
        "CFE": "CFE",
        "COMISION FEDERAL DE ELECTRICIDAD": "CFE",
        "TELMEX": "TELMEX",
        "TELCEL": "TELCEL",
        "AT&T": "AT&T",
        "ATT": "AT&T",
        "IZZI": "IZZI",
        "TOTALPLAY": "TOTALPLAY",
        "MEGACABLE": "MEGACABLE",
        "CABLEMAS": "CABLEMAS",
        "AGUA": "AGUA",
        "JAPAC": "AGUA",
        "SACMEX": "AGUA",
        "AYUNTAMIENTO": "AGUA",
        "PREDIAL": "PREDIAL",
        "GAS": "GAS",
    }

    provider_labels = {
        "CFE": {
            "NUMERO DE SERVICIO": "numero_servicio",
            "NO. DE SERVICIO": "numero_servicio",
            "SERVICIO": "numero_servicio",
            "CUENTA": "cuenta",
            "REFERENCIA": "referencia",
            "TOTAL A PAGAR": "total",
            "IMPORTE A PAGAR": "total",
            "FECHA LIMITE": "fecha_limite",
        },
        "TELMEX": {
            "REFERENCIA": "referencia",
            "CUENTA": "cuenta",
            "NUMERO": "numero_servicio",
            "TOTAL": "total",
            "PERIODO": "periodo",
        },
        "TELCEL": {
            "REFERENCIA": "referencia",
            "CUENTA": "cuenta",
            "NUMERO": "numero_servicio",
            "TOTAL": "total",
            "FECHA LIMITE": "fecha_limite",
        },
        "AT&T": {
            "REFERENCIA": "referencia",
            "CUENTA": "cuenta",
            "NUMERO": "numero_servicio",
            "TOTAL": "total",
            "FECHA LIMITE": "fecha_limite",
        },
        "IZZI": {
            "REFERENCIA": "referencia",
            "CUENTA": "cuenta",
            "CONTRATO": "contrato",
            "TOTAL": "total",
            "FECHA LIMITE": "fecha_limite",
        },
        "TOTALPLAY": {
            "REFERENCIA": "referencia",
            "CUENTA": "cuenta",
            "CONTRATO": "contrato",
            "TOTAL": "total",
            "FECHA LIMITE": "fecha_limite",
        },
        "MEGACABLE": {
            "REFERENCIA": "referencia",
            "CUENTA": "cuenta",
            "CONTRATO": "contrato",
            "TOTAL": "total",
            "FECHA LIMITE": "fecha_limite",
        },
        "CABLEMAS": {
            "REFERENCIA": "referencia",
            "CUENTA": "cuenta",
            "CONTRATO": "contrato",
            "TOTAL": "total",
            "FECHA LIMITE": "fecha_limite",
        },
        "AGUA": {
            "CUENTA": "cuenta",
            "CONTRATO": "contrato",
            "MEDIDOR": "medidor",
            "REFERENCIA": "referencia",
            "TOTAL": "total",
            "FECHA LIMITE": "fecha_limite",
        },
        "PREDIAL": {
            "CUENTA": "cuenta",
            "REFERENCIA": "referencia",
            "TOTAL": "total",
            "PERIODO": "periodo",
        },
        "GAS": {
            "CONTRATO": "contrato",
            "REFERENCIA": "referencia",
            "TOTAL": "total",
            "FECHA LIMITE": "fecha_limite",
        },
    }

    # Detect provider by keyword presence in top portion of the page
    provider = None
    top_lines = lines[:12] if len(lines) > 12 else lines
    for line in top_lines:
        for keyword, value in provider_map.items():
            if keyword in line["text"].upper():
                provider = value
                break
        if provider:
            break
    if provider:
        result["proveedor"] = {"value": provider}

    label_map = {**base_label_map}
    if provider and provider in provider_labels:
        label_map.update(provider_labels[provider])

    value_regex_map = {
        "fecha_limite": DATE_PATTERN,
        "fecha_corte": DATE_PATTERN,
        "total": AMOUNT_PATTERN,
    }
    for label, key in label_map.items():
        value = _extract_label_value(
            lines,
            label,
            stop_labels=["DOMICILIO", "DIRECCION", "FECHA", "TOTAL", "IMPORTE"],
            value_regex=value_regex_map.get(key),
        )
        if value:
            result[key] = {"value": value}

    # Fallback amount extraction if total missing
    if "total" not in result:
        for line in lines:
            if any(tag in line["text"].upper() for tag in ["TOTAL", "IMPORTE", "PAGO"]):
                match = AMOUNT_PATTERN.search(line["text"])
                if match:
                    result["total"] = {"value": match.group(0)}
                    break

    return result


def _find_label_line(lines, label):
    labels = _expand_label_list(label)
    for line in lines:
        for alias in labels:
            if _label_match(line["text"], alias):
                return line
    return None


def _value_right_of_label(line, label, min_gap=5):
    labels = _expand_label_list(label)
    for box in line["boxes"]:
        box_text = box.get("text", "")
        if any(_label_match(box_text, alias) for alias in labels):
            label_rect = box["rect"]
            candidates = []
            for other in line["boxes"]:
                if other is box:
                    continue
                ox1, oy1, ox2, oy2 = other["rect"]
                if ox1 >= label_rect[2] + min_gap:
                    candidates.append(other)
            if not candidates:
                return None
            best = sorted(candidates, key=lambda b: b["rect"][0])[0]
            return best
    return None


def _collect_below(lines, start_line, stop_labels, max_lines=3):
    expanded = []
    for label in stop_labels:
        expanded.extend(_expand_label_list(label))
    stop_norm = {_label_key(lbl) for lbl in expanded}
    collected = []
    started = False
    for line in lines:
        if line is start_line:
            started = True
            continue
        if not started:
            continue
        line_key = _label_key(line["text"])
        if line_key in stop_norm or any(lbl in line_key for lbl in stop_norm):
            break
        collected.append(line)
        if len(collected) >= max_lines:
            break
    return collected


def _extract_ine_from_boxes(ocr_boxes):
    boxes = _boxes_with_rect(ocr_boxes)
    lines = _line_groups(boxes)
    result = {}

    def line_texts(lines_to_join):
        return " ".join(line["text"] for line in lines_to_join if line["text"]).strip()

    def line_tokens(lines_to_join, min_conf=0.85):
        tokens = []
        for line in lines_to_join:
            for box in line["boxes"]:
                text = box.get("text", "").strip()
                if not text:
                    continue
                conf = box.get("confidence", 0)
                if conf >= min_conf or any(ch.isdigit() for ch in text) or "/" in text or "," in text:
                    tokens.append(text)
        return " ".join(tokens).strip()

    def find_pattern_in_boxes(pattern):
        for box in boxes:
            text = box.get("text", "").upper()
            match = pattern.search(text)
            if match:
                return match.group(0), box
        return None, None

    def find_name_from_mrz(lines_local):
        for line in lines_local:
            if "<<" not in line.get("text", ""):
                continue
            raw = line["text"].upper().replace(" ", "")
            match = re.search(r"([A-ZÑ]+)<<([A-ZÑ]+)<<([A-ZÑ<]+)", raw)
            if not match:
                continue
            last1, last2, first = match.group(1), match.group(2), match.group(3)
            first = first.replace("<", " ").strip()
            name = f"{first} {last1} {last2}".strip()
            if len(name) >= 6:
                return name
        return None

    nombre_line = _find_label_line(lines, "NOMBRE")
    if nombre_line:
        value_lines = _collect_below(
            lines,
            nombre_line,
            ["DOMICILIO", "SEXO", "CLAVE", "CURP", "FECHA", "SECCION", "VIGENCIA"],
            max_lines=3,
        )
        nombre = line_texts(value_lines)
        if nombre:
            result["nombre"] = {"value": nombre}

    if "nombre" not in result or len(result["nombre"]["value"].strip()) < 10:
        mrz_name = find_name_from_mrz(lines)
        if mrz_name:
            result["nombre"] = {"value": mrz_name}

    sexo_line = _find_label_line(lines, "SEXO")
    if sexo_line:
        inline = re.search(r"SEXO\\s*[:\\-]?\\s*([HM])", sexo_line.get("text", "").upper())
        if not inline:
            inline = re.search(r"SEX[O0]([HM])", sexo_line.get("text", "").upper())
        if inline:
            result["sexo"] = {"value": inline.group(1)}
        else:
            sexo_box = _value_right_of_label(sexo_line, "SEXO")
            if sexo_box:
                value = sexo_box.get("text", "").strip()
                normalized = _normalize_sex(value)
                if normalized in {"H", "M"}:
                    result["sexo"] = {"value": normalized, "source": sexo_box}

    domicilio_line = _find_label_line(lines, "DOMICILIO")
    if domicilio_line:
        value_lines = _collect_below(
            lines,
            domicilio_line,
            ["CLAVE", "CURP", "SECCION", "VIGENCIA", "FECHA"],
            max_lines=3,
        )
        domicilio = line_tokens(value_lines, min_conf=0.85) or line_texts(value_lines)
        if domicilio:
            result["domicilio"] = {"value": _clean_address_value(domicilio)}

    curp_value, curp_box = find_pattern_in_boxes(CURP_PATTERN)
    if curp_value:
        result["curp"] = {"value": curp_value, "source": curp_box}

    fecha_line = _find_label_line(lines, "FECHA DE NACIMIENTO") or _find_label_line(lines, "FECHADENACIMIENTO")
    if fecha_line:
        date_box = _value_right_of_label(fecha_line, "FECHA")
        if date_box and DATE_PATTERN.search(date_box.get("text", "")):
            result["fecha_nacimiento"] = {"value": date_box.get("text", "").strip(), "source": date_box}
        else:
            value_lines = _collect_below(lines, fecha_line, ["SECCION", "VIGENCIA", "CLAVE", "CURP"], max_lines=1)
            if value_lines and DATE_PATTERN.search(value_lines[0]["text"]):
                result["fecha_nacimiento"] = {"value": value_lines[0]["text"].strip()}
            else:
                date_value, date_box = find_pattern_in_boxes(DATE_PATTERN)
                if date_value:
                    result["fecha_nacimiento"] = {"value": date_value, "source": date_box}

    seccion_line = _find_label_line(lines, "SECCION")
    if seccion_line:
        sec_box = _value_right_of_label(seccion_line, "SECCION")
        if sec_box:
            result["seccion"] = {"value": sec_box.get("text", "").strip(), "source": sec_box}
        else:
            m = re.search(r"SECCION\s*([0-9OIL]+)", seccion_line["text"], re.IGNORECASE)
            if m:
                result["seccion"] = {"value": m.group(1)}
            else:
                try:
                    idx = lines.index(seccion_line)
                except ValueError:
                    idx = -1
                if idx >= 0 and idx + 1 < len(lines):
                    next_line = lines[idx + 1]
                    numeric_boxes = [
                        box for box in next_line["boxes"]
                        if re.fullmatch(r"\d{3,4}", box.get("text", "").strip())
                    ]
                    if numeric_boxes:
                        result["seccion"] = {"value": numeric_boxes[0].get("text", "").strip(), "source": numeric_boxes[0]}

    clave_line = _find_label_line(lines, "CLAVE DE ELECTOR") or _find_label_line(lines, "CLAVE ELECTOR")
    if clave_line:
        compact = _normalize_keyword(clave_line["text"])
        compact_label = _normalize_keyword("CLAVEDEELECTOR")
        if compact_label in compact:
            tail = compact.split(compact_label, 1)[-1]
            if tail:
                match = re.search(r"[A-Z0-9]{18}", tail)
                result["clave_elector"] = {"value": match.group(0) if match else tail}
        else:
            for box in clave_line["boxes"]:
                text = _normalize_keyword(box.get("text", ""))
                match = re.search(r"[A-Z0-9]{18}", text)
                if match:
                    result["clave_elector"] = {"value": match.group(0), "source": box}
                    break

    vigencia_line = _find_label_line(lines, "VIGENCIA")
    if vigencia_line:
        vig_box = _value_right_of_label(vigencia_line, "VIGENCIA")
        if vig_box:
            result["vigencia"] = {"value": vig_box.get("text", "").strip(), "source": vig_box}

    return result


def _extract_mrz_name_from_text(text: str) -> str | None:
    raw = text.upper().replace(" ", "")
    match = re.search(r"([A-ZÑ]{2,})<([A-ZÑ]{2,})<<([A-ZÑ<]{2,})", raw)
    if not match:
        return None
    last1, last2, first = match.group(1), match.group(2), match.group(3)
    first = first.replace("<", " ").strip()
    name = f"{first} {last1} {last2}".strip()
    return name if len(name) >= 6 else None


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


def _clean_address_value(value: str) -> str:
    if not value:
        return value
    upper = _normalize_address(value)
    upper = upper.replace("DOMICILIO", " ")
    upper = re.sub(r"\bAV(?=[A-Z])", "AV ", upper)
    upper = re.sub(r"\bFCP\b", "CP", upper)
    upper = re.sub(r"([A-Z])S/N\b", r"\1 S/N", upper)
    upper = re.sub(r"\bLOC([A-Z]{3,})\b", r"LOC \1", upper)
    upper = re.sub(r"\bLOC([A-Z]{2,})\b", r"LOC \1", upper)
    upper = re.sub(r"\bLOC([A-Z]{2,})(\d{5})\b", r"LOC \1 \2", upper)
    upper = re.sub(r"\bLOC\s*([A-Z]+)(\d{5})\b", r"LOC \1 \2", upper)
    upper = re.sub(r"(?<=\D)(?=\d)", " ", upper)
    upper = re.sub(r"(?<=\d)(?=\D)", " ", upper)
    # Normalize common OCR merges for address tokens
    upper = re.sub(r"\bCOL([A-Z]{3,})\b", r"COL \1", upper)
    upper = re.sub(r"\bCARRDE\b", "CARR DE", upper)
    upper = re.sub(r"\bCARRDEL\b", "CARR DEL", upper)
    upper = re.sub(r"\bCARRDEL([A-Z]{2,})\b", r"CARR DEL \1", upper)
    upper = re.sub(r"\bCARRDEL([A-Z]{2,})S/N\b", r"CARR DEL \1 S/N", upper)
    upper = re.sub(r"\bCARR DE L([A-Z]{2,})\b", r"CARR DEL \1", upper)
    upper = re.sub(r"\bAVENIDA\b", "AV", upper)
    upper = re.sub(r"\bCARRETERA\b", "CARR", upper)
    upper = re.sub(r"\bCAMP\.\b", "CAMP", upper)
    upper = upper.replace(",", " ")
    upper = re.sub(r"\bGOLFOS/N\b", "GOLFO S/N", upper)
    noise = {
        "INSTITUTO",
        "NACIONAL",
        "ELECTORAL",
        "CREDENCIAL",
        "PARA",
        "VOTAR",
        "NOMBRE",
        "SEXO",
        "CURP",
        "SECCION",
        "FECHA",
        "CLAVE",
        "ELECTOR",
    }
    allowed_keywords = {
        "CALLE", "CARR", "AV", "COL", "FRACC", "CP", "MUN", "EDO", "KM",
        "S/N", "NUM", "NO.", "LOC"
    }
    vowels = set("AEIOU")
    tokens = []
    for tok in upper.split():
        if tok in noise:
            continue
        if tok in allowed_keywords:
            tokens.append(tok)
            continue
        if any(ch.isdigit() for ch in tok) or "/" in tok:
            tokens.append(tok)
            continue
        letters = [ch for ch in tok if ch.isalpha()]
        if letters:
            vowel_count = sum(1 for ch in letters if ch in vowels)
            vowel_ratio = vowel_count / len(letters)
            consonant_ratio = (len(letters) - vowel_count) / len(letters)
            # Drop OCR garbage tokens with very low vowel ratio
            if vowel_ratio < 0.2 and len(letters) >= 6:
                continue
            if vowel_ratio < 0.3 and len(letters) >= 10:
                continue
            if vowel_count <= 2 and len(letters) >= 12:
                continue
            if re.search(r"[BCDFGHJKLMNPQRSTVWXYZ]{4,}", tok) and len(letters) >= 7:
                continue
            if vowel_count == 0 and len(letters) >= 5:
                continue
            if consonant_ratio >= 0.75 and len(letters) >= 8:
                continue
        tokens.append(tok)
    cleaned = " ".join(tokens)
    cleaned = cleaned.replace(" ,", ",").replace("  ", " ").strip()
    # Remove trailing junk tokens that are unlikely in address
    cleaned = re.sub(r"\b(ONKEECTDRA|EDUNGSJACGSOACLNA|STTUTON)\b", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


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
    labels = _expand_label_list(label)
    label_upper = label.upper()
    for line in lines:
        for alias in labels:
            alias_upper = alias.upper()
            if alias_upper in line:
                parts = line.split(alias_upper, 1)
                if len(parts) > 1:
                    candidate = parts[1].strip(" :.-")
                    if candidate:
                        return candidate
            compact_line = _label_key(line)
            compact_label = _label_key(alias_upper)
            if compact_label in compact_line:
                # If label is present but value isn't inline, fallback to next line in caller
                continue
    return None


def _find_value_after_keyword(lines: list[str], keywords: list[str]) -> str | None:
    expanded = []
    for keyword in keywords:
        expanded.extend(_expand_label_list(keyword))
    normalized_keywords = [_label_key(keyword) for keyword in expanded]
    for idx, line in enumerate(lines):
        compact_line = _label_key(line)
        if any(keyword in line for keyword in expanded) or any(keyword in compact_line for keyword in normalized_keywords):
            for keyword in expanded:
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
    base_text_raw = "\n".join(part for part in [raw_text, ocr_text] if part)
    base_text = _normalize_text(base_text_raw)
    text = base_text.upper()
    lines = [line.strip().upper() for line in base_text_raw.splitlines() if line.strip()]
    curps = [match.group(0) for match in CURP_PATTERN.finditer(text)]
    rfcs = [match.group(0) for match in RFC_WITH_HOMOCLAVE.finditer(text)]
    nss = [match.group(0) for match in NSS_PATTERN.finditer(text)]
    clabes = [match.group(0) for match in CLABE_PATTERN.finditer(text)]
    dates = [match.group(0) for match in DATE_PATTERN.finditer(text)]

    if document_type in {"INE", "CURP"}:
        if document_type == "INE":
            box_values = _extract_ine_from_boxes(ocr_boxes) if ocr_boxes else {}
        else:
            box_values = _extract_curp_from_boxes(ocr_boxes) if ocr_boxes else {}
        for value in curps:
            fields.append(_make_field("curp", "CURP", _normalize_alnum(value), ocr_boxes))
        labeled_curp = _find_labeled_value(lines, "CURP") or _find_value_after_keyword(lines, ["CURP"])
        if labeled_curp:
            normalized = _normalize_alnum(labeled_curp)
            if CURP_PATTERN.fullmatch(normalized):
                fields.append(_make_field("curp", "CURP", normalized, ocr_boxes, confidence=0.8))
        if "curp" in box_values:
            normalized = _normalize_alnum(box_values["curp"]["value"])
            if CURP_PATTERN.fullmatch(normalized):
                fields.append(_make_field("curp", "CURP", normalized, ocr_boxes, confidence=0.9))
        name_match = _guess_name(text)
        if name_match:
            fields.append(_make_field("nombre", "Nombre", _normalize_name(name_match), ocr_boxes, confidence=0.6))
        if "nombre" in box_values:
            fields.append(_make_field("nombre", "Nombre", _normalize_name(box_values["nombre"]["value"]), ocr_boxes, confidence=0.8))
        mrz_name = _extract_mrz_name_from_text(base_text_raw)
        if mrz_name:
            fields.append(_make_field("nombre", "Nombre", _normalize_name(mrz_name), ocr_boxes, confidence=0.96))
        birth_date = _find_value_after_keyword(lines, ["FECHA DE NACIMIENTO", "FECHA NACIMIENTO", "NACIMIENTO"])
        if birth_date:
            normalized_birth = _normalize_date_value(birth_date)
            if DATE_PATTERN.search(normalized_birth):
                fields.append(_make_field("fecha_nacimiento", "Fecha de nacimiento", normalized_birth, ocr_boxes, confidence=0.6))
            else:
                birth_date = None
        if "fecha_nacimiento" in box_values:
            normalized_birth = _normalize_date_value(box_values["fecha_nacimiento"]["value"])
            if DATE_PATTERN.search(normalized_birth):
                fields.append(_make_field("fecha_nacimiento", "Fecha de nacimiento", normalized_birth, ocr_boxes, confidence=0.8))
        sexo = _find_value_after_keyword(lines, ["SEXO", "GENERO", "GÉNERO"])
        normalized_sexo = _normalize_sex(sexo) if sexo else ""
        if normalized_sexo in {"H", "M"}:
            fields.append(_make_field("sexo", "Sexo", normalized_sexo, ocr_boxes, confidence=0.6))
        else:
            curp_sex = _extract_curp_sex(curps)
            if curp_sex:
                fields.append(_make_field("sexo", "Sexo", curp_sex, ocr_boxes, confidence=0.5))
        if "sexo" in box_values:
            normalized = _normalize_sex(box_values["sexo"]["value"])
            if normalized in {"H", "M"}:
                fields.append(_make_field("sexo", "Sexo", normalized, ocr_boxes, confidence=0.8))
        if document_type == "INE":
            ine_address = _pick_address(lines)
            if ine_address:
                fields.append(_make_field("domicilio", "Domicilio", _clean_address_value(ine_address), ocr_boxes, confidence=0.7))
            if "domicilio" in box_values:
                fields.append(_make_field("domicilio", "Domicilio", _clean_address_value(box_values["domicilio"]["value"]), ocr_boxes, confidence=0.8))
            clave_elector = _find_value_after_keyword(lines, ["CLAVE DE ELECTOR", "CLAVE ELECTOR", "ELECTOR"])
            if clave_elector:
                normalized_clave = _normalize_alnum(clave_elector)
                if re.fullmatch(r"[A-Z0-9]{18}", normalized_clave):
                    fields.append(_make_field("clave_elector", "Clave de elector", normalized_clave, ocr_boxes, confidence=0.6))
            if "clave_elector" in box_values:
                normalized_clave = _normalize_alnum(box_values["clave_elector"]["value"])
                if re.fullmatch(r"[A-Z0-9]{18}", normalized_clave):
                    fields.append(_make_field("clave_elector", "Clave de elector", normalized_clave, ocr_boxes, confidence=0.8))
            seccion = _find_value_after_keyword(lines, ["SECCION", "SECCIÓN"])
            if seccion:
                normalized_seccion = re.sub(r"\D", "", seccion)
                if re.fullmatch(r"\d{3,4}", normalized_seccion):
                    fields.append(_make_field("seccion", "Sección", normalized_seccion, ocr_boxes, confidence=0.6))
            if "seccion" in box_values:
                normalized_seccion = re.sub(r"\D", "", box_values["seccion"]["value"])
                if re.fullmatch(r"\d{3,4}", normalized_seccion):
                    fields.append(_make_field("seccion", "Sección", normalized_seccion, ocr_boxes, confidence=0.8))
            vigencia = _find_value_after_keyword(lines, ["VIGENCIA", "VÁLIDA HASTA", "VALIDA HASTA"])
            if vigencia:
                fields.append(_make_field("vigencia", "Vigencia", _normalize_vigencia(vigencia), ocr_boxes, confidence=0.6))
            if "vigencia" in box_values:
                fields.append(_make_field("vigencia", "Vigencia", _normalize_vigencia(box_values["vigencia"]["value"]), ocr_boxes, confidence=0.8))
                                                                                    # OCR text fallbacks for INE
            text_lines = [line.strip().upper() for line in base_text_raw.splitlines() if line.strip()]
            seccion_value = None
            for line in text_lines:
                if line.startswith("SECCION") and len(line) <= 12:
                    match = re.search(r"\d{3,4}", line)
                    if match:
                        seccion_value = match.group(0)
                        break
            if not seccion_value:
                match = re.search(r"SECCION\s*(\d{3,4})", text)
                if match:
                    seccion_value = match.group(1)
            if seccion_value:
                fields.append(_make_field("seccion", "Sección", seccion_value, ocr_boxes, confidence=0.95))
            match = re.search(r"(?:VIGENCIA|VGENCIA)\s*(\d{4})", text)
            if match:
                fields.append(_make_field("vigencia", "Vigencia", match.group(1), ocr_boxes, confidence=0.95))
            surname_line = next((line for line in text_lines if "<" in line and "<<" not in line and not re.search(r"\d", line)), "")
            given_line = next((line for line in text_lines if "<<" in line and not re.search(r"\d", line)), "")
            if given_line or surname_line:
                last = surname_line.replace("<", " ").strip()
                first = given_line.split("<<", 1)[-1].replace("<", " ").strip() if given_line else ""
                tokens = []
                for token in f"{first} {last}".split():
                    token = re.sub(r"[^A-Z?]", "", token)
                    if token.endswith("KK") and len(token) > 2:
                        token = token[:-2]
                    elif token.endswith("K") and len(token) > 4:
                        token = token[:-1]
                    tokens.append(token)
                name = " ".join([t for t in tokens if t])
                if name:
                    fields.append(_make_field("nombre", "Nombre", _normalize_name(name), ocr_boxes, confidence=0.95))
            existing_dom = next((f for f in fields if f.get("key") == "domicilio"), None)
            dom_ok = bool(
                existing_dom
                and existing_dom.get("value")
                and "INSTITU" not in existing_dom["value"]
                and "ELECT" not in existing_dom["value"]
                and "CREDENCIAL" not in existing_dom["value"]
                and "VOTAR" not in existing_dom["value"]
            )
            if not dom_ok:
                dom_line_idx = next((i for i, line in enumerate(text_lines) if "DOMICILIO" in line), None)
                addr_lines = []
                if dom_line_idx is not None:
                    line = text_lines[dom_line_idx]
                    after = line.split("DOMICILIO", 1)[-1].strip()
                    if after:
                        addr_lines.append(after)
                    for line in text_lines[dom_line_idx + 1: dom_line_idx + 4]:
                        if any(skip in line for skip in ["INSTITUTO", "INSTITU", "ELECTO", "ELECT", "CREDENCIAL"]):
                            continue
                        addr_lines.append(line)
                if addr_lines:
                    raw_addr = " ".join(addr_lines)
                    # Stop at known trailing fields if they leaked into the address line
                    raw_addr = re.split(r"\b(CLAVE|CURP|FECHA|SECCION|SECCIÓN|VIGENCIA)\b", raw_addr)[0]
                    address = _clean_address_value(raw_addr)
                    fields.append(_make_field("domicilio", "Domicilio", address, ocr_boxes, confidence=0.95))
        curp_entidad = _extract_curp_state(curps)
        if curp_entidad:
            state_name = STATE_CODE_TO_NAME.get(curp_entidad, curp_entidad)
            fields.append(_make_field("entidad_nacimiento", "Entidad de nacimiento", state_name, ocr_boxes, confidence=0.6))
        if not birth_date:
            curp_birth = _extract_curp_birth_date(curps)
            if curp_birth:
                fields.append(_make_field("fecha_nacimiento", "Fecha de nacimiento", curp_birth, ocr_boxes, confidence=0.5))
        if not curps and filename:
            name_curps = [match.group(0) for match in CURP_PATTERN.finditer(filename.upper())]
            for value in name_curps:
                fields.append(_make_field("curp", "CURP", _normalize_alnum(value), ocr_boxes, confidence=0.9))

    if document_type in {"CONSTANCIA_SITUACION_FISCAL", "DATOS_BANCARIOS"}:
        if ocr_boxes:
            rfc_box_values = _extract_rfc_from_boxes(ocr_boxes)
            if "rfc" in rfc_box_values:
                fields.append(_make_field("rfc", "RFC", _normalize_alnum(rfc_box_values["rfc"]["value"]), ocr_boxes, confidence=0.9))
            if "nombre" in rfc_box_values:
                fields.append(_make_field("nombre", "Nombre", _normalize_name(rfc_box_values["nombre"]["value"]), ocr_boxes, confidence=0.7))
        for value in rfcs:
            fields.append(_make_field("rfc", "RFC", _normalize_alnum(value), ocr_boxes))
        labeled_rfc = _find_labeled_value(lines, "RFC")
        if labeled_rfc:
            fields.append(_make_field("rfc", "RFC", _normalize_alnum(labeled_rfc), ocr_boxes, confidence=0.8))

    if document_type == "CONSTANCIA_SITUACION_FISCAL":
        regimen = _find_value_after_keyword(lines, ["REGIMEN FISCAL", "RÉGIMEN FISCAL", "REGIMEN", "RÉGIMEN"])
        if regimen:
            fields.append(_make_field("regimen", "Régimen", _normalize_text(regimen), ocr_boxes, confidence=0.7))
        else:
            if (
                "NOMBRE, DENOMINACION O RAZON" in text
                or "NOMBRE DENOMINACION O RAZON" in text
                or "DENOMINACION O RAZON" in text
                or "RAZON SOCIAL" in text
            ):
                fields.append(_make_field("regimen", "Régimen", "PERSONA MORAL", ocr_boxes, confidence=0.6))
        nombres = _find_value_after_keyword(lines, ["NOMBRE (S)", "NOMBRE(S)"])
        apellido1 = _find_value_after_keyword(lines, ["PRIMER APELLIDO"])
        apellido2 = _find_value_after_keyword(lines, ["SEGUNDO APELLIDO"])
        name_parts = [p for p in [nombres, apellido1, apellido2] if p]
        if name_parts:
            fields.append(_make_field("nombre", "Nombre", _normalize_name(" ".join(name_parts)), ocr_boxes, confidence=0.75))

        cp = _find_value_after_keyword(lines, ["CODIGO POSTAL", "CÓDIGO POSTAL", "C.P", "CP"])
        colonia = _find_value_after_keyword(lines, ["NOMBRE DE LA COLONIA", "COLONIA"])
        localidad = _find_value_after_keyword(lines, ["NOMBRE DE LA LOCALIDAD", "LOCALIDAD"])
        municipio = _find_value_after_keyword(lines, ["NOMBRE DEL MUNICIPIO", "MUNICIPIO", "DEMARCACION TERRITORIAL", "DEMARCACIÓN TERRITORIAL"])
        entidad = _find_value_after_keyword(lines, ["NOMBRE DE LA ENTIDAD FEDERATIVA", "ENTIDAD FEDERATIVA"])
        if entidad:
            entidad = entidad.strip()
            if len(entidad) > 4:
                entidad = entidad[:4]
        domicilio_parts = [p for p in [colonia, localidad or municipio, entidad] if p]
        if cp:
            domicilio_parts.insert(1, f"C.P.{re.sub(r'\\D', '', cp)}")
        if domicilio_parts:
            fields.append(_make_field("domicilio", "Domicilio", _normalize_address(" ".join(domicilio_parts)), ocr_boxes, confidence=0.7))

    if document_type == "NSS":
        if ocr_boxes:
            nss_box_values = _extract_nss_from_boxes(ocr_boxes)
            if "nss" in nss_box_values:
                fields.append(_make_field("nss", "NSS", _normalize_numeric_field(nss_box_values["nss"]["value"]), ocr_boxes, confidence=0.9))
            if "nombre" in nss_box_values:
                fields.append(_make_field("nombre", "Nombre", _normalize_name(nss_box_values["nombre"]["value"]), ocr_boxes, confidence=0.7))
        for value in nss:
            fields.append(_make_field("nss", "NSS", _normalize_alnum(value), ocr_boxes))
        afiliacion = _find_value_after_keyword(lines, ["NUMERO DE SEGURIDAD SOCIAL", "NÚMERO DE SEGURIDAD SOCIAL", "SEGURIDAD SOCIAL"])
        if afiliacion:
            fields.append(_make_field("nss", "NSS", _normalize_numeric_field(afiliacion), ocr_boxes, confidence=0.7))

    if document_type == "DATOS_BANCARIOS":
        if ocr_boxes:
            fin_box_values = _extract_financial_from_boxes(ocr_boxes)
            if "clabe" in fin_box_values:
                fields.append(_make_field("clabe", "CLABE", _normalize_numeric_field(fin_box_values["clabe"]["value"]), ocr_boxes, confidence=0.9))
            if "cuenta" in fin_box_values:
                fields.append(_make_field("cuenta", "Cuenta", _normalize_numeric_field(fin_box_values["cuenta"]["value"]), ocr_boxes, confidence=0.7))
            if "cliente_numero" in fin_box_values:
                fields.append(_make_field("cliente_numero", "No. de cliente", _normalize_numeric_field(fin_box_values["cliente_numero"]["value"]), ocr_boxes, confidence=0.7))
            if "banco" in fin_box_values:
                fields.append(_make_field("banco", "Banco", _normalize_address(fin_box_values["banco"]["value"]), ocr_boxes, confidence=0.7))
            if "titular" in fin_box_values:
                fields.append(_make_field("titular", "Titular", _normalize_name(fin_box_values["titular"]["value"]), ocr_boxes, confidence=0.7))
            if "rfc" in fin_box_values:
                fields.append(_make_field("rfc", "RFC", _normalize_alnum(fin_box_values["rfc"]["value"]), ocr_boxes, confidence=0.7))
            if "fecha_corte" in fin_box_values:
                fields.append(_make_field("fecha_corte", "Fecha de corte", _normalize_date_value(fin_box_values["fecha_corte"]["value"]), ocr_boxes, confidence=0.6))
            if "periodo" in fin_box_values:
                fields.append(_make_field("periodo", "Periodo", _normalize_text(fin_box_values["periodo"]["value"]), ocr_boxes, confidence=0.6))
        for value in clabes:
            fields.append(_make_field("clabe", "CLABE", _normalize_alnum(value), ocr_boxes))
        banco = _find_value_after_keyword(lines, ["BANCO", "INSTITUCION", "INSTITUCIÓN"])
        if banco:
            fields.append(_make_field("banco", "Banco", _normalize_address(banco), ocr_boxes, confidence=0.6))
        labeled_clabe = _find_labeled_value(lines, "CLABE")
        if labeled_clabe:
            fields.append(_make_field("clabe", "CLABE", _normalize_numeric_field(labeled_clabe), ocr_boxes, confidence=0.8))

    if document_type in {"ACTA_NACIMIENTO", "INE"}:
        if document_type == "ACTA_NACIMIENTO" and ocr_boxes:
            acta_box_values = _extract_acta_from_boxes(ocr_boxes)
            for key, label in [
                ("folio", "Folio"),
                ("fecha", "Fecha"),
                ("libro", "Libro"),
                ("tomo", "Tomo"),
                ("oficialia", "Oficial??a"),
                ("registro_civil", "Registro civil"),
                ("juez", "Juez"),
                ("nombre", "Nombre"),
                ("sexo", "Sexo"),
                ("fecha_nacimiento", "Fecha de nacimiento"),
                ("lugar_nacimiento", "Lugar de nacimiento"),
                ("entidad_registro", "Entidad de registro"),
                ("municipio_registro", "Municipio de registro"),
                ("fecha_registro", "Fecha de registro"),
                ("numero_acta", "Numero de acta"),
                ("numero_certificado", "Numero de certificado"),
                ("identificador_electronico", "Identificador electronico"),
            ]:
                if key in acta_box_values:
                    value = acta_box_values[key]["value"]
                    if key in {"libro", "tomo", "oficialia", "registro_civil", "juez"}:
                        if not _is_reasonable_acta_optional(value):
                            continue
                    if key == "fecha":
                        value = _normalize_date_value(value)
                    if key in {"fecha_nacimiento", "fecha_registro"}:
                        value = _normalize_date_value(value)
                    if key in {"nombre"}:
                        value = _normalize_name(value)
                    if key in {"lugar_nacimiento", "entidad_registro", "municipio_registro"}:
                        value = _normalize_address(value)
                    fields.append(_make_field(key, label, value, ocr_boxes, confidence=0.7))
        for value in dates:
            fields.append(_make_field("fecha", "Fecha", _normalize_date_value(value), ocr_boxes, confidence=0.6))
        folio = _find_value_after_keyword(lines, ["FOLIO", "ACTA"])
        if folio:
            folio_num = _normalize_numeric_field(folio)
            if re.fullmatch(r"\d{1,6}", folio_num):
                fields.append(_make_field("folio", "Folio", folio_num, ocr_boxes, confidence=0.6))
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
        box_lines = _lines_text_from_boxes(ocr_boxes) if ocr_boxes else None
        box_text_lines = [line["text"].upper() for line in box_lines] if box_lines else lines
        full_text = " ".join(box_text_lines) if box_text_lines else ""
        if ocr_boxes:
            svc_values = _extract_service_from_boxes(ocr_boxes)
            if "proveedor" in svc_values:
                fields.append(_make_field("proveedor", "Proveedor", _normalize_name(svc_values["proveedor"]["value"]), ocr_boxes, confidence=0.8))
            if "numero_servicio" in svc_values:
                fields.append(_make_field("numero_servicio", "Número de servicio", _normalize_numeric_field(svc_values["numero_servicio"]["value"]), ocr_boxes, confidence=0.8))
            if "cuenta" in svc_values:
                fields.append(_make_field("cuenta", "Cuenta", _normalize_numeric_field(svc_values["cuenta"]["value"]), ocr_boxes, confidence=0.7))
            if "contrato" in svc_values:
                fields.append(_make_field("contrato", "Contrato", _normalize_alnum(svc_values["contrato"]["value"]), ocr_boxes, confidence=0.7))
            if "referencia" in svc_values:
                fields.append(_make_field("referencia", "Referencia", _normalize_alnum(svc_values["referencia"]["value"]), ocr_boxes, confidence=0.7))
            if "medidor" in svc_values:
                fields.append(_make_field("medidor", "Medidor", _normalize_alnum(svc_values["medidor"]["value"]), ocr_boxes, confidence=0.7))
            if "cliente" in svc_values:
                fields.append(_make_field("cliente", "Cliente", _normalize_name(svc_values["cliente"]["value"]), ocr_boxes, confidence=0.7))
            if "titular" in svc_values:
                candidate = _normalize_name(svc_values["titular"]["value"])
                provider_noise = [
                    "CFE",
                    "COMISION",
                    "FEDERAL",
                    "ELECTRICIDAD",
                    "TELMEX",
                    "TELCEL",
                    "TOTALPLAY",
                    "MEGACABLE",
                    "IZZI",
                    "AT&T",
                    "ATT",
                ]
                if candidate and not any(token in candidate for token in provider_noise):
                    fields.append(_make_field("titular", "Titular", candidate, ocr_boxes, confidence=0.7))
            if "rfc" in svc_values:
                fields.append(_make_field("rfc", "RFC", _normalize_alnum(svc_values["rfc"]["value"]), ocr_boxes, confidence=0.7))
            if "periodo" in svc_values:
                fields.append(_make_field("periodo", "Periodo", _normalize_text(svc_values["periodo"]["value"]), ocr_boxes, confidence=0.6))
            if "fecha_corte" in svc_values:
                fields.append(_make_field("fecha_corte", "Fecha de corte", _normalize_date_value(svc_values["fecha_corte"]["value"]), ocr_boxes, confidence=0.6))
            if "fecha_limite" in svc_values:
                fields.append(_make_field("fecha_limite", "Fecha límite", _normalize_date_value(svc_values["fecha_limite"]["value"]), ocr_boxes, confidence=0.6))
            if "total" in svc_values:
                fields.append(_make_field("total", "Total", _normalize_text(svc_values["total"]["value"]), ocr_boxes, confidence=0.6))

        # CFE-style documents: prefer user address block and service identifiers
        if full_text and ("CFE" in full_text or "COMISION FEDERAL" in full_text):
            blacklist_cp = {"06600", "06500", "01210"}
            cp_match = None
            cp_index = None
            for idx, line in enumerate(box_text_lines):
                match = re.search(r"\b(\d{5})\b", line)
                if match and match.group(1) not in blacklist_cp:
                    cp_match = match.group(1)
                    cp_index = idx
                    break

            if not any(f.get("key") == "titular" for f in fields):
                rfc_idx = None
                for idx, line in enumerate(box_text_lines):
                    if "RFC" in line:
                        rfc_idx = idx
                        break
                if rfc_idx is not None and rfc_idx + 1 < len(box_text_lines):
                    candidate = box_text_lines[rfc_idx + 1]
                    if "TOTAL" not in candidate and not re.search(r"\d", candidate):
                        fields.append(_make_field("titular", "Titular", candidate, ocr_boxes, confidence=0.8))
            if cp_match:
                pre_lines = []
                ref_lines = []
                cp_line = ""
                if cp_index is not None:
                    start = max(0, cp_index - 3)
                    for line in box_text_lines[start:cp_index]:
                        if "(" in line and ")" in line:
                            continue
                        if "PESOS" in line:
                            continue
                        if any(tag in line for tag in ["TOTAL", "PAGAR", "IMPORTE", "LIMITE", "CORTE", "TARIFA", "PERIODO", "RFC"]):
                            continue
                        pre_lines.append(line)
                    cp_line = box_text_lines[cp_index]
                    ref_lines = [*pre_lines, cp_line]
                    if cp_index + 1 < len(box_text_lines):
                        next_line = box_text_lines[cp_index + 1]
                        if "PESOS" not in next_line and "DESCARGA" not in next_line:
                            ref_lines.append(next_line)
                domicilio_lines = list(pre_lines)
                if cp_line:
                    cp_clean = re.sub(r"\d{5}", "", cp_line)
                    cp_clean = cp_clean.replace("C.P.", "").replace("CP", "").replace("FCP", "")
                    cp_clean = re.sub(r"\b[A-Z]\b", "", cp_clean)
                    cp_clean = re.sub(r"F\b", "", cp_clean)
                    cp_clean = cp_clean.strip(" .,-")
                    if cp_clean:
                        domicilio_lines.append(cp_clean)
                domicilio_block = " ".join(domicilio_lines).strip()
                referencia_block = " ".join(ref_lines).strip()
                if domicilio_block:
                    fields.append(_make_field("domicilio", "Domicilio", _clean_address_value(domicilio_block), ocr_boxes, confidence=0.85))
                fields.append(_make_field("cp", "CP", cp_match, ocr_boxes, confidence=0.85))
                existing_ref = next((f for f in fields if f.get("key") == "referencia"), None)
                ref_ok = False
                if existing_ref and existing_ref.get("value"):
                    ref_ok = "RMU" not in existing_ref["value"]
                if not ref_ok:
                    fields.append(_make_field("referencia", "Referencia", _normalize_text(referencia_block), ocr_boxes, confidence=0.8))

            existing_num = next((f for f in fields if f.get("key") == "numero_servicio"), None)
            num_ok = False
            if existing_num and existing_num.get("value"):
                num_ok = bool(re.fullmatch(r"\d{10,13}", _normalize_numeric_field(existing_num["value"])))
            if not num_ok:
                match = re.search(r"(?:NO\.?\s*DE\s*SERVICI[O0]|NO\.?DESERVICI[O0]|SERVICI[O0])\D*(\d{10,13})", full_text)
                if match:
                    fields.append(_make_field("numero_servicio", "Número de servicio", match.group(1), ocr_boxes, confidence=0.85))

            existing_cuenta = next((f for f in fields if f.get("key") == "cuenta"), None)
            cuenta_ok = False
            if existing_cuenta and existing_cuenta.get("value"):
                cuenta_norm = _normalize_alnum(existing_cuenta["value"])
                cuenta_ok = len(cuenta_norm) >= 10
            if not cuenta_ok:
                match = re.search(r"CUENTA\D*([A-Z0-9]{10,20})", full_text)
                if match:
                    fields.append(_make_field("cuenta", "Cuenta", match.group(1), ocr_boxes, confidence=0.85))

            existing_limite = next((f for f in fields if f.get("key") == "fecha_limite"), None)
            limite_ok = False
            if existing_limite and existing_limite.get("value"):
                limite_ok = bool(re.search(r"\d{1,2}\s*[A-Z]{3}\s*\d{2,4}", existing_limite["value"]))
                if "CORTE" in existing_limite["value"]:
                    limite_ok = False
            if not limite_ok:
                match = re.search(r"(?:LIMITE\s*DE\s*PAGO|FECHA\s*LIMITE|VENCE)\D*([0-9]{1,2}\s*[A-Z]{3}\s*[0-9]{2,4})", full_text)
                if match:
                    fields.append(_make_field("fecha_limite", "Fecha límite", match.group(1), ocr_boxes, confidence=0.75))

            def _is_person_name(text: str) -> bool:
                text = re.sub(r"[^A-ZÑ ]", " ", text.upper()).strip()
                if not text:
                    return False
                if any(tag in text for tag in ["CFE", "COMISION", "FEDERAL", "ELECTRICIDAD"]):
                    return False
                parts = [p for p in text.split() if p]
                if len(parts) < 2:
                    return False
                return True

            if not any(f.get("key") == "titular" for f in fields):
                rfc_idx = None
                for idx, line in enumerate(box_text_lines):
                    if "RFC" in line:
                        rfc_idx = idx
                        break
                stop_words = ["CFE", "COMISION", "RFC", "TOTAL", "PAGAR", "LIMITE", "CORTE", "TARIFA", "MEDIDOR"]
                candidates = box_text_lines[rfc_idx + 1:rfc_idx + 4] if rfc_idx is not None else box_text_lines
                for line in candidates:
                    cleaned = re.sub(r"[^A-ZÑ ]", " ", line).strip()
                    if len(cleaned) < 10:
                        continue
                    if any(sw in cleaned for sw in stop_words):
                        continue
                    if re.search(r"\d", line):
                        continue
                    if not _is_person_name(cleaned):
                        continue
                    fields.append(_make_field("titular", "Titular", cleaned, ocr_boxes, confidence=0.7))
                    break
            if not any(f.get("key") == "titular" for f in fields):
                rfc_idx = None
                for idx, line in enumerate(box_text_lines):
                    if "RFC" in line:
                        rfc_idx = idx
                        break
                if rfc_idx is not None and rfc_idx + 1 < len(box_text_lines):
                    candidate = box_text_lines[rfc_idx + 1]
                    if "TOTAL" not in candidate and not re.search(r"\d", candidate):
                        if _is_person_name(candidate):
                            fields.append(_make_field("titular", "Titular", candidate, ocr_boxes, confidence=0.8))
            if not any(f.get("key") == "titular" for f in fields):
                for line in box_text_lines:
                    if "TOTAL" not in line:
                        continue
                    if re.search(r"\d", line):
                        continue
                    name_part = line.split("TOTAL", 1)[0].strip()
                    if len(name_part) >= 6 and _is_person_name(name_part):
                        fields.append(_make_field("titular", "Titular", name_part, ocr_boxes, confidence=0.75))
                        break

            # If we still don't have a person name, reuse cliente when it looks like a person.
            if not any(f.get("key") == "titular" for f in fields):
                cliente_field = next((f for f in fields if f.get("key") == "cliente"), None)
                if cliente_field and cliente_field.get("value"):
                    cliente_value = _normalize_name(str(cliente_field["value"]))
                    if _is_person_name(cliente_value):
                        fields.append(_make_field("titular", "Titular", cliente_value, ocr_boxes, confidence=0.72))
        address = _pick_address(box_text_lines)
        if address:
            fields.append(_make_field("domicilio", "Domicilio", _clean_address_value(address), ocr_boxes, confidence=0.8))
            cp = _extract_postal_code(address)
            if cp:
                fields.append(_make_field("cp", "CP", cp, ocr_boxes, confidence=0.7))
        city, state = _extract_city_state(box_text_lines)
        if city:
            fields.append(_make_field("ciudad", "Ciudad", _normalize_address(city), ocr_boxes, confidence=0.6))
        if state:
            fields.append(_make_field("estado", "Estado", _normalize_address(state), ocr_boxes, confidence=0.6))
        referencia = _find_value_after_keyword(box_text_lines, ["REFERENCIA", "REFERENCIA DE PAGO", "NUMERO DE SERVICIO", "NUMERO DE SERVICIO"])
        if referencia:
            fields.append(_make_field("referencia", "Referencia", referencia, ocr_boxes, confidence=0.7))

    legacy_values = legacy_extract_fields(document_type, ocr_boxes)
    if legacy_values:
        _merge_legacy_fields(fields, legacy_values, ocr_boxes)

    for label, key in LABEL_MAP.items():
        labeled_value = _find_labeled_value(lines, label)
        if labeled_value:
            normalized = labeled_value
            if key == "curp":
                normalized = _normalize_alnum(labeled_value)
                if not CURP_PATTERN.fullmatch(normalized):
                    continue
            if key == "rfc":
                normalized = _normalize_alnum(labeled_value)
                if not RFC_WITH_HOMOCLAVE.fullmatch(normalized):
                    continue
            if key == "nss":
                normalized = _normalize_numeric_field(labeled_value)
                if not NSS_PATTERN.fullmatch(normalized):
                    continue
            if key == "clabe":
                normalized = _normalize_numeric_field(labeled_value)
                if not CLABE_PATTERN.fullmatch(normalized):
                    continue
            fields.append(_make_field(key, label, normalized, ocr_boxes, confidence=0.85))

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

    return _dedupe_fields(_postprocess_fields(document_type, fields))
