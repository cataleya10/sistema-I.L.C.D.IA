import re
import json
import os
import logging

from app.pipelines.legacy_adapter import legacy_extract_fields

logger = logging.getLogger(__name__)

CURP_PATTERN = re.compile(r"\b[A-Z][AEIOUX][A-Z]{2}\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[HM][A-Z]{5}[A-Z0-9]\d\b")
RFC_PATTERN = re.compile(r"\b[A-Z&]{3,4}\d{6}[A-Z0-9]{3}\b")
NSS_PATTERN = re.compile(r"\b\d{11}\b")
CLABE_PATTERN = re.compile(r"\b\d{18}\b")
ACCOUNT_PATTERN = re.compile(r"\b\d{10,16}\b")
AMOUNT_PATTERN = re.compile(r"\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\b")
DATE_PATTERN = re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b")
NAME_PATTERN = re.compile(r"\b[A-Z]{2,}(?:\s+[A-Z]{2,}){1,4}\b")
RFC_WITH_HOMOCLAVE = re.compile(r"\b[A-Z&]{3,4}\d{6}[A-Z0-9]{3}\b")
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
    "anio_registro": "Anio de registro",
    "fecha_nacimiento": "Fecha de nacimiento",
    "seccion": "Seccion",
    "vigencia": "Vigencia",
    "entidad_registro": "Entidad de registro",
    "municipio_registro": "Municipio de registro",
    "primer_apellido": "Primer apellido",
    "segundo_apellido": "Segundo apellido",
    "lugar_nacimiento": "Lugar de nacimiento",
    "fecha_emision": "Fecha de emision",
    "nss": "NSS",
    "fecha_documento": "Fecha documento",
    "folio_solicitud": "Folio solicitud",
    "rfc": "RFC",
    "cp": "CP",
    "id_cif": "Id CIF",
    "regimen": "Regimen",
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
        logger.exception("Failed to load alias model from %s", path)
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
        "CODIGO POSTAL",
        "NUM",
        "NUM",
        "NO.",
        "#",
        "MUNICIPIO",
        "ESTADO",
    )
    noise_tokens = (
        "TELMEX",
        "TELEFON",
        "NUMERO DE SERVICIO",
        "LINEA DE CAPTURA",
        "REFERENCIA",
        "CUENTA",
        "PAGAR",
        "TOTAL",
        "SALDO",
        "IMPORTE",
    )
    candidates = [
        line
        for line in lines
        if any(k in line for k in keywords)
        and not any(token in line for token in noise_tokens)
    ]
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

    folio = pick("FOLIO", re.compile(r"\b[0-9OIL]{1,6}\b"))
    if folio:
        normalized_folio = _normalize_value_for_key("folio", folio)
        if normalized_folio:
            result["folio"] = {"value": normalized_folio}
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
        cleaned = re.sub(r"[^A-Z ]", " ", value.upper()).strip()
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
        normalized_cert = _normalize_value_for_key("numero_certificado", numero_certificado)
        if normalized_cert:
            result["numero_certificado"] = {"value": normalized_cert}

    identificador = _extract_label_value(lines, "IDENTIFICADOR ELECTRONICO", stop_labels=["DATOS", "ENTIDAD"])
    if identificador:
        normalized_id = _normalize_value_for_key("identificador_electronico", identificador)
        if normalized_id:
            result["identificador_electronico"] = {"value": normalized_id}

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
            normalized_numero_acta = _normalize_value_for_key("numero_acta", match.group(1))
            if normalized_numero_acta:
                result["numero_acta"] = {"value": normalized_numero_acta}

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
            tokens = re.findall(r"[A-Z]+", upper_raw)
            if len(tokens) != 1:
                continue
            candidate = re.sub(r"[^A-Z]", "", upper_raw)
            if not candidate or candidate in stop_words:
                continue
            if candidate.startswith("HOJA"):
                continue
            if len(candidate) <= 3:
                continue
            if candidate in nombre.replace(" ", ""):
                continue
            # Single surname-like token
            if re.fullmatch(r"[A-Z]{4,}", candidate):
                nombre = f"{nombre} {candidate}".strip()
                break
    if nombre:
        result["nombre"] = {"value": nombre}

    return result


def _extract_service_from_boxes(ocr_boxes):
    boxes = _boxes_with_rect(ocr_boxes)
    lines = _line_groups(boxes)
    result = {}

    def _parse_amount(value: str | None) -> float | None:
        if not value:
            return None
        raw = str(value).replace("$", "").replace(" ", "")
        raw = raw.replace(",", "")
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    base_label_map = {
        "NUMERO DE SERVICIO": "numero_servicio",
        "NUMERO DE SERVICIO": "numero_servicio",
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
        "TELEFONOS DE MEXICO": "TELMEX",
        "TELMEX-TEL": "TELMEX",
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
            "REFERENCIA UNICA": "referencia",
            "LINEA DE CAPTURA": "referencia",
            "CUENTA": "cuenta",
            "NUMERO": "numero_servicio",
            "NUMERO TELEFONICO": "numero_servicio",
            "NUMERO DE TELEFONO": "numero_servicio",
            "TELEFONO": "numero_servicio",
            "LINEA": "numero_servicio",
            "TOTAL": "total",
            "TOTAL A PAGAR": "total",
            "SALDO TOTAL": "total",
            "IMPORTE A PAGAR": "total",
            "PERIODO": "periodo",
            "PAGAR ANTES DE": "fecha_limite",
            "FECHA LIMITE DE PAGO": "fecha_limite",
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
        stop_labels = ["DOMICILIO", "DIRECCION", "FECHA", "TOTAL", "IMPORTE"]
        if key == "fecha_limite":
            stop_labels = ["DOMICILIO", "DIRECCION", "TOTAL", "IMPORTE"]
        if key == "total":
            stop_labels = ["DOMICILIO", "DIRECCION", "FECHA"]
        value = _extract_label_value(
            lines,
            label,
            stop_labels=stop_labels,
            value_regex=value_regex_map.get(key),
        )
        if value:
            result[key] = {"value": value}

    total_amount = _parse_amount(result.get("total", {}).get("value"))
    if "total" not in result or total_amount is None or total_amount <= 0:
        priority_tags = ["TOTAL A PAGAR", "IMPORTE A PAGAR", "SALDO TOTAL"]
        for line in lines:
            upper = line["text"].upper()
            if not any(tag in upper for tag in priority_tags):
                continue
            match = AMOUNT_PATTERN.search(line["text"])
            if match:
                result["total"] = {"value": match.group(0)}
                break

    # Generic fallback amount extraction
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
            match = re.search(r"([A-Z]+)<<([A-Z]+)<<([A-Z<]+)", raw)
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
    match = re.search(r"([A-Z]{2,})<([A-Z]{2,})<<([A-Z<]{2,})", raw)
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


def _split_compact_given_names(value: str) -> str:
    compact = _normalize_alnum(value)
    if not compact:
        return ""
    known_pairs = {
        "JOSEALEJANDRO": "JOSE ALEJANDRO",
        "MARIAJOSE": "MARIA JOSE",
        "JOSELUIS": "JOSE LUIS",
        "JUANCARLOS": "JUAN CARLOS",
        "MIGUELANGEL": "MIGUEL ANGEL",
        "LUISFERNANDO": "LUIS FERNANDO",
    }
    for key, spaced in known_pairs.items():
        if compact == key:
            return spaced
    return compact


def _split_compact_surnames(value: str) -> str:
    token = _normalize_alnum(value)
    if len(token) < 8:
        return token

    def _vowel_ratio(part: str) -> float:
        letters = [ch for ch in part if ch.isalpha()]
        if not letters:
            return 0.0
        vowels = sum(1 for ch in letters if ch in "AEIOU")
        return vowels / len(letters)

    best_split = None
    best_score = None
    for i in range(4, len(token) - 3):
        left = token[:i]
        right = token[i:]
        score = abs(len(left) - len(right)) * 0.1
        score += abs(_vowel_ratio(left) - 0.4)
        score += abs(_vowel_ratio(right) - 0.4)
        common_endings = ("EZ", "ES", "ON", "OS", "AS", "IA", "VA", "RA", "DO", "ZA", "GA", "NA")
        if left.endswith(common_endings):
            score -= 0.15
        if right.startswith("N") and left.endswith(("A", "E", "I", "O", "U")):
            score += 0.12
        if best_score is None or score < best_score:
            best_score = score
            best_split = (left, right)

    if not best_split:
        return token
    return f"{best_split[0]} {best_split[1]}"


def _extract_possible_telmex_holder(line: str) -> str | None:
    upper = _normalize_text(line).upper()
    if "PUBLICO EN GENERAL" in upper:
        return None

    # Prefer already spaced names (e.g., "CALDERON CORDOVA JOSE ALEJANDRO")
    spaced = re.sub(r"[^A-Z ]", " ", upper)
    spaced = re.sub(r"\s+", " ", spaced).strip()
    if spaced:
        tokens = [tok for tok in spaced.split() if tok]
        blacklist = {
            "PUBLICO", "GENERAL", "RFC", "FACTURA", "NUMERO", "PAGAR", "TOTAL",
            "CALLE", "CLL", "COL", "CP", "MZ", "LT", "SN", "S", "N",
            "ATASTA", "CIUDAD", "MEXICO",
        }
        if (
            3 <= len(tokens) <= 6
            and all(len(tok) >= 2 for tok in tokens)
            and not any(tok in blacklist for tok in tokens)
            and not any(ch.isdigit() for ch in spaced)
        ):
            return _normalize_name(" ".join(tokens))

    upper = re.split(r"\b(?:FACTURA|RFC|NUMERO|PAGAR|TOTAL|DV\d+|SELLO|CADENA)\b", upper, maxsplit=1)[0]
    compact_tokens = re.findall(r"[A-Z]{14,60}", _normalize_alnum(upper))
    if not compact_tokens:
        return None
    token = compact_tokens[0]
    if token in {"PUBLICOENGENERAL"}:
        return None

    first_names = [
        "JOSEALEJANDRO",
        "JOSELUIS",
        "JUANCARLOS",
        "MIGUELANGEL",
        "LUISFERNANDO",
        "ALEJANDRO",
        "CARLOS",
        "MIGUEL",
        "FERNANDO",
        "DANIEL",
        "RICARDO",
        "ADRIAN",
        "JOSE",
        "MARIA",
        "JUAN",
        "LUIS",
        "ANA",
    ]
    split_at = None
    found_name = None
    for name in first_names:
        idx = token.rfind(name)
        if idx >= 6:
            split_at = idx
            found_name = name
            break
    if split_at is None or not found_name:
        return None

    surnames = token[:split_at]
    given = token[split_at:]
    surnames_spaced = _split_compact_surnames(surnames)
    given_spaced = _split_compact_given_names(given)
    holder = _normalize_name(f"{surnames_spaced} {given_spaced}")
    return holder if len(holder) >= 10 else None


def _cleanup_telmex_holder(value: str) -> str:
    text = _normalize_text(str(value)).upper()
    text = re.sub(r"[^A-Z ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""

    garbage = {"PUBLICO", "GENERAL", "RFC", "FACTURA", "NUMERO", "TOTAL", "PAGAR"}
    known_compound = ("JOSEALEJANDRO", "JOSELUIS", "JUANCARLOS", "MIGUELANGEL", "LUISFERNANDO", "MARIAJOSE")
    tokens = []
    for tok in text.split():
        if tok in garbage:
            continue
        for comp in known_compound:
            if tok.startswith(comp):
                tok = comp
                break
        vowels = sum(1 for ch in tok if ch in "AEIOU")
        if len(tok) > 18:
            continue
        if len(tok) >= 12 and vowels <= 2:
            continue
        tokens.append(tok)

    normalized_tokens = []
    for tok in tokens:
        split = _split_compact_given_names(tok)
        normalized_tokens.extend([t for t in split.split() if t])

    if len(normalized_tokens) > 4:
        normalized_tokens = normalized_tokens[:4]
    return " ".join(normalized_tokens).strip()


def _clean_telmex_customer_line(line: str) -> str:
    text = _normalize_text(str(line)).upper()
    if not text:
        return ""
    text = re.split(
        r"\b(?:SERIE\s+DEL\s+CERTIFICADO|CERTIFICADO\s+DEL\s+CSD|SELLO\s+DIGITAL|CADENA\s+ORIGINAL|ESTADO\s+DE\s+CUENTA|TUESTADO\s+DE\s+CUENTA\s+PUEDE\s+SER|TU\s*ESTADO\s+DE\s+CUENTA\s+PUEDE\s+SER|FACTURA|RFC|LINEA\s+DE\s+CAPTURA|NUMERO\s+DE\s+SERVICIO|REFERENCIA\s+UNICA|TOTAL\s+A\s+PAGAR|TOTAL|PAGAR\s+ANTES)\b",
        text,
        maxsplit=1,
    )[0]
    text = re.sub(r"[^A-Z0-9N ,./-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .,-")
    return text


def _extract_telmex_customer_address_cp(lines: list[str], customer_idx: int) -> tuple[str | None, str | None]:
    stop_tokens = (
        "SERIE DEL CERTIFICADO",
        "CERTIFICADO DEL CSD",
        "CADENA ORIGINAL",
        "SELLO DIGITAL",
        "ESTADO DE CUENTA",
        "FACTURA",
        "RFC",
        "LINEA DE CAPTURA",
        "REFERENCIA",
        "PAGAR",
        "TOTAL",
        "COBRO",
        "REVERSO",
        "RECIBO",
    )
    strong_markers = ("CLL", "CALLE", "AV", "AVENIDA")
    start_markers = ("CLL", "CALLE", "AV", "AVENIDA", "COL", "FRACC", "MZ", "LT", "SN")
    continue_markers = ("CLL", "CALLE", "AV", "AVENIDA", "COL", "FRACC", "MZ", "LT", "SN", "ATASTA", "CARMEN")

    parts: list[str] = []
    cp_candidates: list[str] = []
    prepared: list[dict] = []

    context_start = max(0, customer_idx - 2)
    context_end = min(len(lines), customer_idx + 15)
    window: list[str] = []
    for idx in range(context_start, context_end):
        line = _normalize_text(lines[idx]).upper()
        if not line:
            continue
        if idx == customer_idx and "PUBLICO EN GENERAL" in line:
            tail = line.split("PUBLICO EN GENERAL", 1)[-1].strip()
            if tail:
                window.append(tail)
            continue
        window.append(line)

    for raw_line in window:
        upper = _normalize_text(raw_line).upper()
        if not upper:
            continue

        cp_with_label = re.findall(r"C\.?\s*P\.?\s*[:.-]?\s*([0-9OIL]{5})", upper)
        cp_candidates.extend(cp_with_label)
        loose_cp = re.findall(r"\b([0-9OIL]{5})(?:-[A-Z0-9-]{2,})?\b", upper)
        cp_candidates.extend(loose_cp)

        has_stop = any(token in upper for token in stop_tokens)
        cleaned = _clean_telmex_customer_line(upper)
        if not cleaned:
            if has_stop and parts:
                break
            continue
        # Remove long OCR crypto/signature blobs but keep nearby address words.
        cleaned = re.sub(r"\b[A-Z0-9]{16,}\b", " ", cleaned)
        cleaned = re.sub(r"(?:^|\s)/+[A-Z0-9]{0,14}(?=\s|$)", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,-")
        # Keep the canonical street segment when present (e.g., "CLL DEL GOLFO SN").
        cstreet = re.search(r"\b(CLL\s+[A-Z ]{2,50}\bS/?N)\b", cleaned)
        if not cstreet:
            cstreet = re.search(r"\b(CALLE\s+[A-Z ]{2,60}\bS/?N)\b", cleaned)
        if cstreet:
            cleaned = cstreet.group(1)
        cleaned = re.split(r"C\.?\s*P\.?", cleaned, maxsplit=1)[0]
        cleaned = re.sub(r"\b[0-9OIL]{5}(?:-[A-Z0-9-]{2,})?\b", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,-")
        if not cleaned:
            if has_stop and parts:
                break
            continue
        if len(cleaned) > 60:
            continue
        if re.search(r"[A-Z0-9]{18,}", cleaned):
            continue
        prepared.append(
            {
                "text": cleaned,
                "has_stop": has_stop,
                "strong": any(marker in cleaned for marker in strong_markers),
                "addr": any(marker in cleaned for marker in continue_markers),
            }
        )

    if prepared:
        start_idx = next((i for i, item in enumerate(prepared) if item["strong"]), None)
        if start_idx is None:
            start_idx = next((i for i, item in enumerate(prepared) if item["addr"]), None)
        if start_idx is not None:
            for item in prepared[start_idx:]:
                text_item = item["text"]
                has_addr = any(marker in text_item for marker in start_markers)
                if not has_addr and parts:
                    break
                if not has_addr:
                    continue
                parts.append(text_item)
                if item["has_stop"] or len(parts) >= 5:
                    break

    address_value = _clean_address_value(" ".join(parts)) if parts else None
    if address_value and len(address_value) < 8:
        address_value = None

    cp_value = None
    for cp in cp_candidates:
        normalized_cp = _normalize_value_for_key("cp", cp)
        if normalized_cp and normalized_cp != "06500":
            cp_value = normalized_cp
            break
    if not cp_value and cp_candidates:
        cp_value = _normalize_value_for_key("cp", cp_candidates[0]) or None

    return address_value, cp_value


def _sanitize_telmex_domicilio(value: str) -> str:
    cleaned = _clean_telmex_customer_line(value)
    cleaned = re.sub(r"\b(?:PAGADO\s+EN|INDICADO\s+AL\s+REVERSO|DE\s+ESTE\s+RECIBO)\b.*$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,-")
    return _clean_address_value(cleaned) if cleaned else ""


def _choose_telmex_cp(fields: list[dict], full_text: str) -> str | None:
    cp_candidates = re.findall(r"(?:C\.?\s*P\.?\s*[:.-]?\s*)([0-9OIL]{5})", full_text)
    cp_candidates.extend(re.findall(r"\b([0-9OIL]{5})\b", full_text))
    for cp in cp_candidates:
        normalized_cp = _normalize_value_for_key("cp", cp)
        if normalized_cp and normalized_cp != "06500":
            return normalized_cp
    if cp_candidates:
        fallback = _normalize_value_for_key("cp", cp_candidates[0])
        return fallback or None
    return None


def _choose_telmex_domicilio(fields: list[dict]) -> str | None:
    candidates = []
    for field in fields:
        if field.get("key") != "domicilio":
            continue
        raw = _normalize_text(str(field.get("value", "")))
        if not raw:
            continue
        clean = _sanitize_telmex_domicilio(raw)
        if not clean:
            continue
        upper = clean.upper()
        tokens = [t for t in upper.split() if t]
        if not tokens:
            continue
        marker_score = 0
        for marker in ("CLL", "CALLE", "AV", "COL", "FRACC", "MZ", "LT", "SN"):
            if marker in upper:
                marker_score += 2
        if "CLL" in upper or "CALLE" in upper:
            marker_score += 5
        length_score = min(len(upper), 60) / 10.0
        only_manzana_lote = re.fullmatch(r"(?:MZ|LT|SN|\d+|\s)+", upper) is not None
        penalty = 8 if only_manzana_lote else 0
        score = marker_score + length_score - penalty
        candidates.append((score, clean))
    if not candidates:
        return None
    strong_candidates = [item for item in candidates if ("CLL" in item[1] or "CALLE" in item[1] or " AV " in f" {item[1]} ")]
    pool = strong_candidates if strong_candidates else candidates
    pool.sort(key=lambda x: x[0], reverse=True)
    return pool[0][1]


def _extract_telmex_domicilio_from_full_text(full_text: str) -> str | None:
    text = _normalize_text(str(full_text)).upper()
    if not text:
        return None

    matches = list(re.finditer(r"PUBLICO\s+EN\s+GENERAL\s+(.+?)\s+C\.?\s*P\.?\s*\d{5}", text))
    if not matches:
        return None

    candidates: list[tuple[float, str]] = []
    for match in matches:
        chunk = match.group(1)
        chunk = re.sub(
            r"\b(?:TUESTADO\s+DE\s+CUENTA\s+PUEDE\s+SER|TU\s*ESTADO\s+DE\s+CUENTA\s+PUEDE\s+SER|ESTADO\s+DE\s+CUENTA\s+PUEDE\s+SER)\b",
            " ",
            chunk,
        )
        # Keep locality lines after payment legend; only strip the legend phrase itself.
        chunk = re.sub(r"\bPAGADO\s+EN\s+CUALQUIER\s+CENTRO\s+DE\s+COBRO\b", " ", chunk)
        chunk = re.split(
            r"\b(?:INDICADO\s+AL\s+REVERSO|DE\s+ESTE\s+RECIBO|CDC|RFCPUBLICOENGENERAL|FACTURA|TOTAL\s+A\s+PAGAR|PAGAR\s+ANTES)\b",
            chunk,
            maxsplit=1,
        )[0]
        chunk = re.sub(r"\s+", " ", chunk).strip(" .,-")
        if not chunk:
            continue
        cleaned = _clean_address_value(chunk)
        if not cleaned or len(cleaned) < 10:
            continue
        if not any(marker in cleaned for marker in ("CLL", "CALLE", "MZ", "LT", "SN", "ATASTA", "CARMEN")):
            continue
        score = len(cleaned) / 10.0
        if "CLL" in cleaned or "CALLE" in cleaned:
            score += 6
        candidates.append((score, cleaned))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _pick_telmex_customer_index(lines: list[str]) -> int | None:
    indices = []
    for idx, line in enumerate(lines):
        norm = _normalize_text(line).upper()
        if "PUBLICO EN GENERAL" in norm or "PUBLICOENGENERAL" in _normalize_alnum(line):
            indices.append(idx)
    if not indices:
        return None
    if len(indices) == 1:
        return indices[0]

    best_idx = indices[0]
    best_score = -1
    for idx in indices:
        score = 0
        window = lines[idx:idx + 14]
        for line in window:
            upper = _normalize_text(line).upper()
            if any(marker in upper for marker in ("CLL", "CALLE", "AV", "MZ", "LT", "SN", "ATASTA", "CARMEN")):
                score += 2
            if re.search(r"C\.?\s*P\.?\s*\d{5}", upper):
                score += 4
            if "PAG 1 DE" in upper or "TELMEX TOTAL A PAGAR" in upper:
                score -= 3
        # Prefer later candidate when score is tied.
        score += idx * 0.01
        if score > best_score:
            best_score = score
            best_idx = idx
    return best_idx


def _enrich_telmex_domicilio(base_dom: str, full_text: str) -> str:
    dom = _normalize_text(base_dom).upper()
    text = _normalize_text(full_text).upper()
    if not dom or not text:
        return dom

    extras: list[str] = []
    mz = re.search(r"\bMZ\s+SN\s+LT\s+SN\b", text)
    if mz and "MZ SN LT SN" not in dom:
        extras.append("MZ SN LT SN")

    # Keep locality labels often present in Telmex receipts.
    if re.search(r"\bATASTA\b", text) and "ATASTA" not in dom:
        extras.append("ATASTA")
    loc = re.search(r"\bATASTA\s*,\s*CARMEN\s*,\s*CA\b", text)
    if loc and "ATASTA CARMEN CA" not in dom:
        extras.append("ATASTA CARMEN CA")

    if extras:
        dom = _clean_address_value(" ".join([dom, *extras]))
    return dom


def _normalize_address(value: str) -> str:
    value = _normalize_text(value)
    replacements = {
        "AV.": "AV ",
        "AVENIDA": "AV ",
        "C.P.": "CP ",
        "CODIGO POSTAL": "CP ",
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


def _normalize_cp_value(value: str) -> str:
    raw = _normalize_numeric_field(value)
    if len(raw) == 5:
        return raw
    if len(raw) > 5:
        return raw[:5]
    return ""


def _normalize_folio_value(value: str) -> str:
    text = str(value or "").upper()
    candidates = re.findall(r"[0-9OIL]{1,6}", text)
    # Avoid false positives from words that only contribute I/O noise.
    candidates = [c for c in candidates if re.search(r"\d", c)]
    if not candidates:
        return ""
    candidate = max(candidates, key=len)
    raw = _normalize_numeric_field(candidate)
    return raw if re.fullmatch(r"\d{1,6}", raw) else ""


def _normalize_numero_acta_value(value: str) -> str:
    text = str(value or "").upper().strip()
    if not text:
        return ""
    if re.search(r"\d", text) or re.fullmatch(r"[0-9OIL\s-]+", text):
        raw = _normalize_numeric_field(text)
        if re.fullmatch(r"\d{3,12}", raw):
            return raw
    normalized = _normalize_alnum(text)
    return normalized if len(normalized) >= 3 else ""


def _normalize_numero_certificado_value(value: str) -> str:
    text = str(value or "").upper().strip()
    if not text:
        return ""
    numeric = _normalize_numeric_field(text)
    if len(numeric) >= 6:
        return numeric
    alnum = _normalize_alnum(text)
    return alnum if len(alnum) >= 6 else ""


def _normalize_identificador_electronico_value(value: str) -> str:
    text = str(value or "").upper().strip()
    if not text:
        return ""
    alnum = _normalize_alnum(text)
    return alnum if len(alnum) >= 6 else ""


def _normalize_reference_value(value: str) -> str:
    text = str(value or "").upper().strip()
    if not text:
        return ""
    numeric = _normalize_numeric_field(text)
    if 10 <= len(numeric) <= 30:
        return numeric
    alnum = _normalize_alnum(text)
    digits = sum(1 for ch in alnum if ch.isdigit())
    if 10 <= len(alnum) <= 30 and digits >= 8:
        return alnum
    return ""


def _normalize_seccion_value(value: str) -> str:
    text = str(value or "").upper().replace("O", "0")
    raw = re.sub(r"\D", "", text)
    if not raw:
        return ""
    trimmed = raw.lstrip("0")
    if re.fullmatch(r"\d{3,4}", trimmed):
        return trimmed
    return raw


FIELD_VALUE_NORMALIZERS = {
    "cp": _normalize_cp_value,
    "folio": _normalize_folio_value,
    "seccion": _normalize_seccion_value,
    "numero_acta": _normalize_numero_acta_value,
    "numero_certificado": _normalize_numero_certificado_value,
    "identificador_electronico": _normalize_identificador_electronico_value,
    "referencia": _normalize_reference_value,
}


def _normalize_value_for_key(key: str, value: str) -> str:
    normalizer = FIELD_VALUE_NORMALIZERS.get(str(key or ""))
    if normalizer is None:
        return str(value or "")
    return normalizer(str(value or ""))


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
    upper = str(text or "").upper()
    match = re.search(r"\b([0-9OIL]{5})\b", upper)
    if not match:
        return None
    normalized = _normalize_value_for_key("cp", match.group(1))
    return normalized or None


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
    def _parse_amount_for_rank(value: str | None) -> float | None:
        if not value:
            return None
        raw = str(value).replace("$", "").replace(" ", "").replace(",", "")
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _rank(field: dict) -> tuple[int, float]:
        key = str(field.get("key", ""))
        confidence = float(field.get("confidence", 0) or 0)
        if key == "total":
            amount = _parse_amount_for_rank(field.get("value"))
            return (1 if amount is not None and amount > 0 else 0, confidence)
        return (1, confidence)

    best: dict[str, dict] = {}
    for field in fields:
        key = field.get("key")
        if not key:
            continue
        if key not in best:
            best[key] = field
            continue
        if _rank(field) > _rank(best[key]):
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
        sexo = _find_value_after_keyword(lines, ["SEXO", "GENERO"])
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
            seccion = _find_value_after_keyword(lines, ["SECCION"])
            if seccion:
                normalized_seccion = _normalize_value_for_key("seccion", seccion)
                if re.fullmatch(r"\d{3,4}", normalized_seccion):
                    fields.append(_make_field("seccion", "Seccion", normalized_seccion, ocr_boxes, confidence=0.6))
            if "seccion" in box_values:
                normalized_seccion = _normalize_value_for_key("seccion", box_values["seccion"]["value"])
                if re.fullmatch(r"\d{3,4}", normalized_seccion):
                    fields.append(_make_field("seccion", "Seccion", normalized_seccion, ocr_boxes, confidence=0.8))
            vigencia = _find_value_after_keyword(lines, ["VIGENCIA", "VALIDA HASTA"])
            if vigencia:
                fields.append(_make_field("vigencia", "Vigencia", _normalize_vigencia(vigencia), ocr_boxes, confidence=0.6))
            if "vigencia" in box_values:
                fields.append(_make_field("vigencia", "Vigencia", _normalize_vigencia(box_values["vigencia"]["value"]), ocr_boxes, confidence=0.8))
                                                                                    # OCR text fallbacks for INE
            text_lines = [line.strip().upper() for line in base_text_raw.splitlines() if line.strip()]
            seccion_value = None
            for line in text_lines:
                if re.search(r"^SECCI[O0]N", line) and len(line) <= 16:
                    match = re.search(r"[0-9OIL]{3,5}", line)
                    if match:
                        seccion_value = match.group(0)
                        break
            if not seccion_value:
                match = re.search(r"SECCI[O0]N\s*([0-9OIL]{3,5})", text)
                if match:
                    seccion_value = match.group(1)
            if seccion_value:
                normalized_seccion = _normalize_value_for_key("seccion", seccion_value)
                if re.fullmatch(r"\d{3,4}", normalized_seccion):
                    fields.append(_make_field("seccion", "Seccion", normalized_seccion, ocr_boxes, confidence=0.95))
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
                    raw_addr = re.split(r"\b(CLAVE|CURP|FECHA|SECCION|VIGENCIA)\b", raw_addr)[0]
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
        regimen = _find_value_after_keyword(lines, ["REGIMEN FISCAL", "REGIMEN"])
        if regimen:
            fields.append(_make_field("regimen", "Regimen", _normalize_text(regimen), ocr_boxes, confidence=0.7))
        else:
            if (
                "NOMBRE, DENOMINACION O RAZON" in text
                or "NOMBRE DENOMINACION O RAZON" in text
                or "DENOMINACION O RAZON" in text
                or "RAZON SOCIAL" in text
            ):
                fields.append(_make_field("regimen", "Regimen", "PERSONA MORAL", ocr_boxes, confidence=0.6))
        nombres = _find_value_after_keyword(lines, ["NOMBRE (S)", "NOMBRE(S)"])
        apellido1 = _find_value_after_keyword(lines, ["PRIMER APELLIDO"])
        apellido2 = _find_value_after_keyword(lines, ["SEGUNDO APELLIDO"])
        name_parts = [p for p in [nombres, apellido1, apellido2] if p]
        if name_parts:
            fields.append(_make_field("nombre", "Nombre", _normalize_name(" ".join(name_parts)), ocr_boxes, confidence=0.75))

        cp = _find_value_after_keyword(lines, ["CODIGO POSTAL", "C.P", "CP"])
        colonia = _find_value_after_keyword(lines, ["NOMBRE DE LA COLONIA", "COLONIA"])
        localidad = _find_value_after_keyword(lines, ["NOMBRE DE LA LOCALIDAD", "LOCALIDAD"])
        municipio = _find_value_after_keyword(lines, ["NOMBRE DEL MUNICIPIO", "MUNICIPIO", "DEMARCACION TERRITORIAL"])
        entidad = _find_value_after_keyword(lines, ["NOMBRE DE LA ENTIDAD FEDERATIVA", "ENTIDAD FEDERATIVA"])
        if entidad:
            entidad = entidad.strip()
            if len(entidad) > 4:
                entidad = entidad[:4]
        domicilio_parts = [p for p in [colonia, localidad or municipio, entidad] if p]
        if cp:
            normalized_cp = _normalize_value_for_key("cp", cp)
            if normalized_cp:
                domicilio_parts.insert(1, f"C.P.{normalized_cp}")
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
        afiliacion = _find_value_after_keyword(lines, ["NUMERO DE SEGURIDAD SOCIAL", "SEGURIDAD SOCIAL"])
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
        banco = _find_value_after_keyword(lines, ["BANCO", "INSTITUCION"])
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
                ("oficialia", "Oficialia"),
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
                    if key == "numero_acta":
                        value = _normalize_value_for_key("numero_acta", value)
                        if not value:
                            continue
                    if key == "numero_certificado":
                        value = _normalize_value_for_key("numero_certificado", value)
                        if not value:
                            continue
                    if key == "identificador_electronico":
                        value = _normalize_value_for_key("identificador_electronico", value)
                        if not value:
                            continue
                    fields.append(_make_field(key, label, value, ocr_boxes, confidence=0.7))
        for value in dates:
            fields.append(_make_field("fecha", "Fecha", _normalize_date_value(value), ocr_boxes, confidence=0.6))
        folio = _find_value_after_keyword(lines, ["FOLIO", "NO ACTA", "NUMERO DE ACTA"])
        if folio:
            folio_num = _normalize_value_for_key("folio", folio)
            if folio_num:
                fields.append(_make_field("folio", "Folio", folio_num, ocr_boxes, confidence=0.6))
        if document_type == "ACTA_NACIMIENTO":
            libro = _find_value_after_keyword(lines, ["LIBRO"])
            if libro:
                fields.append(_make_field("libro", "Libro", _normalize_alnum(libro), ocr_boxes, confidence=0.6))
            tomo = _find_value_after_keyword(lines, ["TOMO"])
            if tomo:
                fields.append(_make_field("tomo", "Tomo", _normalize_alnum(tomo), ocr_boxes, confidence=0.6))
            oficialia = _find_value_after_keyword(lines, ["OFICIALIA"])
            if oficialia:
                fields.append(_make_field("oficialia", "Oficialia", _normalize_alnum(oficialia), ocr_boxes, confidence=0.6))
            registro_civil = _find_value_after_keyword(lines, ["REGISTRO CIVIL"])
            if registro_civil:
                fields.append(_make_field("registro_civil", "Registro civil", _normalize_address(registro_civil), ocr_boxes, confidence=0.6))
            juez = _find_value_after_keyword(lines, ["JUEZ", "JUEZA"])
            if juez:
                fields.append(_make_field("juez", "Juez", _normalize_name(juez), ocr_boxes, confidence=0.6))
            numero_certificado = _find_value_after_keyword(
                lines,
                ["NUMERO DE CERTIFICADO DE NACIMIENTO", "NUMERO CERTIFICADO", "NO CERTIFICADO", "CERTIFICADO NACIMIENTO"],
            )
            if numero_certificado:
                normalized_cert = _normalize_value_for_key("numero_certificado", numero_certificado)
                if normalized_cert:
                    fields.append(
                        _make_field(
                            "numero_certificado",
                            "Numero de certificado",
                            normalized_cert,
                            ocr_boxes,
                            confidence=0.6,
                        )
                    )
            identificador = _find_value_after_keyword(lines, ["IDENTIFICADOR ELECTRONICO", "IDENTIFICADOR"])
            if identificador:
                normalized_id = _normalize_value_for_key("identificador_electronico", identificador)
                if normalized_id:
                    fields.append(
                        _make_field(
                            "identificador_electronico",
                            "Identificador electronico",
                            normalized_id,
                            ocr_boxes,
                            confidence=0.6,
                        )
                    )

    if document_type == "COMPROBANTE_DOMICILIO":
        box_lines = _lines_text_from_boxes(ocr_boxes) if ocr_boxes else None
        box_text_lines = [line["text"].upper() for line in box_lines] if box_lines else lines
        full_text = " ".join(box_text_lines) if box_text_lines else ""
        if ocr_boxes:
            svc_values = _extract_service_from_boxes(ocr_boxes)
            provider_text = _normalize_text(str(svc_values.get("proveedor", {}).get("value", ""))).upper()
            if "proveedor" in svc_values:
                fields.append(_make_field("proveedor", "Proveedor", _normalize_name(svc_values["proveedor"]["value"]), ocr_boxes, confidence=0.8))
            if "numero_servicio" in svc_values:
                fields.append(_make_field("numero_servicio", "Numero de servicio", _normalize_numeric_field(svc_values["numero_servicio"]["value"]), ocr_boxes, confidence=0.8))
            if "cuenta" in svc_values:
                fields.append(_make_field("cuenta", "Cuenta", _normalize_numeric_field(svc_values["cuenta"]["value"]), ocr_boxes, confidence=0.7))
            if "contrato" in svc_values:
                fields.append(_make_field("contrato", "Contrato", _normalize_alnum(svc_values["contrato"]["value"]), ocr_boxes, confidence=0.7))
            if "referencia" in svc_values:
                normalized_ref = _normalize_value_for_key("referencia", svc_values["referencia"]["value"])
                if normalized_ref:
                    fields.append(_make_field("referencia", "Referencia", normalized_ref, ocr_boxes, confidence=0.7))
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
                fields.append(_make_field("fecha_limite", "Fecha limite", _normalize_date_value(svc_values["fecha_limite"]["value"]), ocr_boxes, confidence=0.6))
            if "total" in svc_values:
                fields.append(_make_field("total", "Total", _normalize_text(svc_values["total"]["value"]), ocr_boxes, confidence=0.6))

            telmex_markers = ("TELMEX", "TELEFONOS DE MEXICO", "TELMEX-TEL")
            is_telmex = provider_text == "TELMEX" or any(marker in full_text for marker in telmex_markers)
            if is_telmex:
                if not any(f.get("key") == "proveedor" and str(f.get("value", "")).upper() == "TELMEX" for f in fields):
                    fields.append(_make_field("proveedor", "Proveedor", "TELMEX", ocr_boxes, confidence=0.86))

                existing_num = next((f for f in fields if f.get("key") == "numero_servicio"), None)
                num_ok = False
                if existing_num and existing_num.get("value"):
                    num_digits = _normalize_numeric_field(str(existing_num["value"]))
                    num_ok = bool(re.fullmatch(r"\d{10}", num_digits))
                if not num_ok:
                    match = re.search(
                        r"(?:NUMERO\s+TELEFONICO|NUMERO\s+DE\s+TELEFONO|TELEFONO|LINEA(?!\s+DE\s+CAPTURA)|NUMERO(?!\s+DE\s+CUENTA))\D*((?:\d[\s().-]*){10,12})",
                        full_text,
                    )
                    if match:
                        raw_num = _normalize_numeric_field(match.group(1))
                        if len(raw_num) > 10:
                            raw_num = raw_num[-10:]
                        if re.fullmatch(r"\d{10}", raw_num):
                            fields.append(_make_field("numero_servicio", "Numero de servicio", raw_num, ocr_boxes, confidence=0.88))

                existing_cuenta = next((f for f in fields if f.get("key") == "cuenta"), None)
                cuenta_ok = False
                if existing_cuenta and existing_cuenta.get("value"):
                    cuenta_norm = _normalize_alnum(str(existing_cuenta["value"]))
                    cuenta_ok = len(cuenta_norm) >= 8
                if not cuenta_ok:
                    match = re.search(
                        r"(?:NO\.?\s*DE\s*CUENTA|NUMERO\s+DE\s+CUENTA|CUENTA)\D*((?:[A-Z0-9][\s.-]*){8,24})",
                        full_text,
                    )
                    if match:
                        cuenta_value = _normalize_alnum(match.group(1))
                        bad_tokens = ("PAGAR", "LIMITE", "FECHA", "TOTAL", "IMPORTE", "SALDO")
                        if 8 <= len(cuenta_value) <= 24 and not any(token in cuenta_value for token in bad_tokens):
                            fields.append(_make_field("cuenta", "Cuenta", cuenta_value, ocr_boxes, confidence=0.86))

                existing_ref = next((f for f in fields if f.get("key") == "referencia"), None)
                ref_ok = False
                if existing_ref and existing_ref.get("value"):
                    ref_value_norm = _normalize_alnum(str(existing_ref["value"]))
                    digits = sum(1 for ch in ref_value_norm if ch.isdigit())
                    has_noise = any(token in ref_value_norm for token in ["PAGAR", "LIMITE", "FECHA"])
                    ref_ok = len(ref_value_norm) >= 10 and digits >= 6 and not has_noise
                if not ref_ok:
                    match = re.search(
                        r"(?:LINEA\s+DE\s+CAPTURA|REFERENCIA(?:\s+UNICA)?|REF(?:ERENCIA)?)\D*((?:\d[\s.-]*){10,30})(?=\s+(?:PAGAR|FECHA|TOTAL|IMPORTE|SALDO|LIMITE)\b|$)",
                        full_text,
                    )
                    if match:
                        ref_value = _normalize_value_for_key("referencia", match.group(1))
                        if ref_value:
                            fields.append(_make_field("referencia", "Referencia", ref_value, ocr_boxes, confidence=0.86))

                existing_limite = next((f for f in fields if f.get("key") == "fecha_limite"), None)
                limite_ok = False
                if existing_limite and existing_limite.get("value"):
                    limite_ok = bool(DATE_PATTERN.search(str(existing_limite["value"])) or re.search(r"\d{1,2}\s*[A-Z]{3}\s*\d{2,4}", str(existing_limite["value"])))
                if not limite_ok:
                    match = re.search(
                        r"(?:PAGAR\s+ANTES\s+DE|FECHA\s*LIMITE(?:\s*DE\s*PAGO)?)\D*([0-9]{1,2}\s*[A-Z]{3}\s*[0-9]{2,4}|\d{2}[/-]\d{2}[/-]\d{2,4})",
                        full_text,
                    )
                    if match:
                        fields.append(_make_field("fecha_limite", "Fecha limite", match.group(1), ocr_boxes, confidence=0.82))

                existing_total = next((f for f in fields if f.get("key") == "total"), None)
                total_ok = False
                if existing_total and existing_total.get("value"):
                    total_ok = bool(AMOUNT_PATTERN.search(str(existing_total["value"])))
                if not total_ok:
                    match = re.search(
                        r"(?:TOTAL\s+A\s+PAGAR|SALDO\s+TOTAL|IMPORTE\s+A\s+PAGAR)\D*(\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)",
                        full_text,
                    )
                    if match:
                        fields.append(_make_field("total", "Total", _normalize_text(match.group(1)), ocr_boxes, confidence=0.82))

        provider_is_telmex = any(
            f.get("key") == "proveedor" and "TELMEX" in _normalize_text(str(f.get("value", ""))).upper()
            for f in fields
        )
        filename_is_telmex = "TELMEX" in _normalize_text(filename or "").upper()
        telmex_in_text = any(marker in full_text for marker in ("TELMEX", "TELEFONOS DE MEXICO", "TELMEX-TEL")) or provider_is_telmex or filename_is_telmex
        if telmex_in_text:
            if not any(f.get("key") == "proveedor" and str(f.get("value", "")).upper() == "TELMEX" for f in fields):
                fields.append(_make_field("proveedor", "Proveedor", "TELMEX", ocr_boxes, confidence=0.86))

            existing_num = next((f for f in fields if f.get("key") == "numero_servicio"), None)
            num_ok = False
            if existing_num and existing_num.get("value"):
                num_digits = _normalize_numeric_field(str(existing_num["value"]))
                num_ok = bool(re.fullmatch(r"\d{10}", num_digits))
            if not num_ok:
                match = re.search(
                    r"(?:NUMERO\s+TELEFONICO|NUMERO\s+DE\s+TELEFONO|TELEFONO|LINEA(?!\s+DE\s+CAPTURA)|NUMERO(?!\s+DE\s+CUENTA))\D*((?:\d[\s().-]*){10,12})",
                    full_text,
                )
                if match:
                    raw_num = _normalize_numeric_field(match.group(1))
                    if len(raw_num) > 10:
                        raw_num = raw_num[-10:]
                    if re.fullmatch(r"\d{10}", raw_num):
                        fields.append(_make_field("numero_servicio", "Numero de servicio", raw_num, ocr_boxes, confidence=0.89))

            existing_cuenta = next((f for f in fields if f.get("key") == "cuenta"), None)
            cuenta_ok = False
            if existing_cuenta and existing_cuenta.get("value"):
                cuenta_norm = _normalize_alnum(str(existing_cuenta["value"]))
                cuenta_ok = len(cuenta_norm) >= 8
            if not cuenta_ok:
                match = re.search(
                    r"(?:NO\.?\s*DE\s*CUENTA|NUMERO\s+DE\s+CUENTA|CUENTA)\D*((?:[A-Z0-9][\s.-]*){8,24})",
                    full_text,
                )
                if match:
                    cuenta_raw = re.split(
                        r"\b(?:REFERENCIA|PAGAR|TOTAL|IMPORTE|FECHA|LIMITE|SALDO)\b",
                        match.group(1),
                        maxsplit=1,
                    )[0]
                    cuenta_value = _normalize_alnum(cuenta_raw)
                    bad_tokens = ("PAGAR", "LIMITE", "FECHA", "TOTAL", "IMPORTE", "SALDO")
                    if 8 <= len(cuenta_value) <= 24 and not any(token in cuenta_value for token in bad_tokens):
                        fields.append(_make_field("cuenta", "Cuenta", cuenta_value, ocr_boxes, confidence=0.88))

            existing_ref = next((f for f in fields if f.get("key") == "referencia"), None)
            ref_ok = False
            if existing_ref and existing_ref.get("value"):
                ref_value_norm = _normalize_alnum(str(existing_ref["value"]))
                digits = sum(1 for ch in ref_value_norm if ch.isdigit())
                has_noise = any(token in ref_value_norm for token in ("PAGAR", "LIMITE", "FECHA", "TOTAL", "IMPORTE"))
                ref_ok = len(ref_value_norm) >= 10 and digits >= 6 and not has_noise
            if not ref_ok:
                match = re.search(
                    r"(?:LINEA\s+DE\s+CAPTURA|REFERENCIA(?:\s+UNICA)?|REF(?:ERENCIA)?)\D*((?:\d[\s.-]*){10,30})(?=\s+(?:PAGAR|FECHA|TOTAL|IMPORTE|SALDO|LIMITE)\b|$)",
                    full_text,
                )
                if match:
                    ref_value = _normalize_alnum(match.group(1))
                    if ref_value.startswith("UNICA"):
                        ref_value = ref_value[5:]
                    digits = sum(1 for ch in ref_value if ch.isdigit())
                    if 10 <= len(ref_value) <= 30 and digits >= 10:
                        fields.append(_make_field("referencia", "Referencia", ref_value, ocr_boxes, confidence=0.88))

        # CFE-style documents: prefer user address block and service identifiers
        if full_text and ("CFE" in full_text or "COMISION FEDERAL" in full_text):
            def _parse_amount_local(value: str | None) -> float | None:
                if not value:
                    return None
                raw = str(value).replace("$", "").replace(" ", "").replace(",", "")
                try:
                    return float(raw)
                except (TypeError, ValueError):
                    return None

            def _recover_compact_person_name(value: str) -> str:
                cleaned = re.sub(r"[^A-Z ]", "", str(value).upper()).strip()
                cleaned = re.sub(r"\s+", " ", cleaned)
                if not cleaned:
                    return ""
                if " " in cleaned:
                    return _normalize_name(cleaned)
                if len(cleaned) < 10:
                    return cleaned
                known_names = [
                    "ALEJANDRO", "GABRIEL", "MIGUEL", "ANGEL", "DAMIAN", "JOSE", "MARIA", "CARLOS", "DANIEL",
                    "LUIS", "JAVIER", "OSCAR", "ERWIN", "JUAN", "PEDRO", "ANA",
                ]
                for first in sorted(known_names, key=len, reverse=True):
                    if not cleaned.startswith(first):
                        continue
                    rest = cleaned[len(first):]
                    if len(rest) < 4:
                        continue
                    for last in sorted(known_names, key=len, reverse=True):
                        if not rest.endswith(last):
                            continue
                        middle = rest[:-len(last)]
                        if len(middle) < 4:
                            continue
                        return _normalize_name(f"{first} {middle} {last}")
                return cleaned

            blacklist_cp = {"06600", "06500", "01210"}
            cp_match = None
            cp_index = None
            for idx, line in enumerate(box_text_lines):
                match = re.search(r"\b([0-9OIL]{5})\b", line)
                normalized_cp = _normalize_value_for_key("cp", match.group(1)) if match else ""
                if normalized_cp and normalized_cp not in blacklist_cp:
                    cp_match = normalized_cp
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
                    cp_clean = re.sub(r"[0-9OIL]{5}", "", cp_line)
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
                    normalized_ref = _normalize_value_for_key("referencia", referencia_block)
                    if normalized_ref:
                        fields.append(_make_field("referencia", "Referencia", normalized_ref, ocr_boxes, confidence=0.8))

            existing_num = next((f for f in fields if f.get("key") == "numero_servicio"), None)
            num_ok = False
            if existing_num and existing_num.get("value"):
                num_ok = bool(re.fullmatch(r"\d{10,13}", _normalize_numeric_field(existing_num["value"])))
            if not num_ok:
                match = re.search(r"(?:NO\.?\s*DE\s*SERVICI[O0]|NO\.?DESERVICI[O0]|SERVICI[O0])\D*(\d{10,13})", full_text)
                if match:
                    fields.append(_make_field("numero_servicio", "Numero de servicio", match.group(1), ocr_boxes, confidence=0.85))

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
                    fields.append(_make_field("fecha_limite", "Fecha limite", match.group(1), ocr_boxes, confidence=0.75))

            existing_total = next((f for f in fields if f.get("key") == "total"), None)
            total_ok = False
            if existing_total and existing_total.get("value"):
                parsed_existing_total = _parse_amount_local(str(existing_total["value"]))
                total_ok = parsed_existing_total is not None and parsed_existing_total > 0
            if not total_ok:
                match = re.search(
                    r"(?:TOTAL\s*A\s*PAGAR|TOTALA\s*PAGAR|IMPORTE\s*A\s*PAGAR|SALDO\s+TOTAL|TOTAL)\D*(\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)",
                    full_text,
                )
                if match:
                    fields.append(_make_field("total", "Total", _normalize_text(match.group(1)), ocr_boxes, confidence=0.9))
                else:
                    for line in box_text_lines:
                        if "TOTAL" not in line and "IMPORTE A PAGAR" not in line and "TOTALA PAGAR" not in line:
                            continue
                        amount = re.search(r"(\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)", line)
                        if amount:
                            fields.append(_make_field("total", "Total", _normalize_text(amount.group(1)), ocr_boxes, confidence=0.86))
                            break

            def _is_person_name(text: str) -> bool:
                text = re.sub(r"[^A-Z ]", " ", text.upper()).strip()
                if not text:
                    return False
                if any(tag in text for tag in ["CFE", "COMISION", "FEDERAL", "ELECTRICIDAD", "RFC", "TOTAL"]):
                    return False
                parts = [p for p in text.split() if p]
                if len(parts) < 2:
                    return False
                if len(parts) > 6:
                    return False
                if any(len(p) < 2 for p in parts):
                    return False
                return True

            if not any(f.get("key") == "titular" for f in fields):
                inline_rfc_name = re.search(
                    r"RFC[:\s]*[A-Z0-9]{12,13}\s+([A-Z ]{8,50}?)(?=\s+(?:TOTALA?\s*PAGAR|TOTAL|NO\.?\s*DE\s*SERVICI[O0]|RMU:))",
                    full_text,
                )
                if inline_rfc_name:
                    candidate = _recover_compact_person_name(inline_rfc_name.group(1))
                    if _is_person_name(candidate):
                        fields.append(_make_field("titular", "Titular", candidate, ocr_boxes, confidence=0.9))

            if not any(f.get("key") == "titular" for f in fields):
                label_match = re.search(
                    r"(?:NOMBRE(?:\s+DEL\s+(?:CLIENTE|USUARIO))?|CLIENTE|USUARIO)[^A-Z0-9]{0,8}([A-Z ]{2,}(?:\s+[A-Z ]{2,}){1,5})(?=\s+(?:RFC|DOMICILIO|TOTAL|SERVICIO|TARIFA|PERIODO)\b|$)",
                    full_text,
                )
                if label_match:
                    candidate = _normalize_name(label_match.group(1))
                    if _is_person_name(candidate):
                        fields.append(_make_field("titular", "Titular", candidate, ocr_boxes, confidence=0.9))

            if not any(f.get("key") == "titular" for f in fields):
                rfc_idx = None
                for idx, line in enumerate(box_text_lines):
                    if "RFC" in line:
                        rfc_idx = idx
                        break
                stop_words = ["CFE", "COMISION", "RFC", "TOTAL", "PAGAR", "LIMITE", "CORTE", "TARIFA", "MEDIDOR"]
                candidates = box_text_lines[rfc_idx + 1:rfc_idx + 4] if rfc_idx is not None else box_text_lines
                for line in candidates:
                    cleaned = re.sub(r"[^A-Z ]", " ", line).strip()
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
                    if len(line) > 45:
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
        referencia = _find_value_after_keyword(box_text_lines, ["REFERENCIA", "REFERENCIA DE PAGO", "LINEA DE CAPTURA"])
        if referencia:
            normalized_ref = _normalize_value_for_key("referencia", referencia)
            if normalized_ref:
                fields.append(_make_field("referencia", "Referencia", normalized_ref, ocr_boxes, confidence=0.7))

        if telmex_in_text:
            def _is_valid_telmex_field(key: str, value: str) -> bool:
                cleaned = _normalize_text(str(value or "")).upper()
                if not cleaned:
                    return False
                if key == "numero_servicio":
                    digits = _normalize_numeric_field(cleaned)
                    return bool(re.fullmatch(r"\d{10}", digits)) and digits != "0000000000"
                if key == "cuenta":
                    normalized = _normalize_alnum(cleaned)
                    if any(ch.isalpha() for ch in normalized):
                        return False
                    digits = _normalize_numeric_field(cleaned)
                    return 8 <= len(digits) <= 22
                if key == "referencia":
                    normalized = _normalize_alnum(cleaned)
                    digits = sum(1 for ch in normalized if ch.isdigit())
                    if normalized in {"S", "DE", "SDE"}:
                        return False
                    return 10 <= len(normalized) <= 30 and digits >= 8
                if key == "cp":
                    return bool(re.fullmatch(r"\d{5}", _normalize_numeric_field(cleaned)))
                if key == "fecha_limite":
                    return bool(
                        DATE_PATTERN.search(cleaned)
                        or re.search(r"\d{1,2}(?:\s+|[-/])[A-Z]{3}(?:\s+|[-/])\d{2,4}", cleaned)
                    )
                if key == "domicilio":
                    if any(token in cleaned for token in ["TELMEX", "TELEFON", "LINEA", "CAPTURA"]):
                        return False
                    address_markers = (
                        "CLL",
                        "CALLE",
                        "COL",
                        "COLONIA",
                        "AV",
                        "AVENIDA",
                        "FRACC",
                        "MZ",
                        "LT",
                        "SN",
                        "CP",
                        "C.P.",
                        "MUNICIPIO",
                        "ESTADO",
                        "ATASTA",
                        "CARMEN",
                    )
                    return len(cleaned) >= 12 and any(marker in cleaned for marker in address_markers)
                return True

            filtered = []
            for field in fields:
                key = str(field.get("key", ""))
                if key in {"numero_servicio", "cuenta", "referencia", "cp", "fecha_limite", "domicilio"}:
                    if not _is_valid_telmex_field(key, str(field.get("value", ""))):
                        continue
                filtered.append(field)
            fields = filtered

            num_match = re.search(
                r"(?:NUMERO\s+TELEFONICO|NUMERO\s+DE\s+TELEFONO|TELEFONO|LINEA(?!\s+DE\s+CAPTURA)|NUMERO(?!\s+DE\s+CUENTA))\D*((?:\d[\s().-]*){10,12})",
                full_text,
            )
            if num_match:
                num_value = _normalize_numeric_field(num_match.group(1))
                if len(num_value) > 10:
                    num_value = num_value[-10:]
                if re.fullmatch(r"\d{10}", num_value) and num_value != "0000000000":
                    fields.append(_make_field("numero_servicio", "Numero de servicio", num_value, ocr_boxes, confidence=0.96))

            cuenta_match = re.search(
                r"(?:NO\.?\s*DE\s*CUENTA|NUMERO\s+DE\s+CUENTA|CUENTA)\D*([0-9][0-9\s.-]{7,24})",
                full_text,
            )
            if cuenta_match:
                cuenta_value = _normalize_numeric_field(cuenta_match.group(1))
                if 8 <= len(cuenta_value) <= 22 and not (len(cuenta_value) == 10 and cuenta_value.startswith(("800", "900"))):
                    fields.append(_make_field("cuenta", "Cuenta", cuenta_value, ocr_boxes, confidence=0.95))

            ref_match = re.search(
                r"(?:LINEA\s+DE\s+CAPTURA|REFERENCIA(?:\s+UNICA)?|REF(?:ERENCIA)?)\D*((?:\d[\s.-]*){10,30})(?=\s+(?:PAGAR|FECHA|TOTAL|IMPORTE|SALDO|LIMITE|TELMEX)\b|$)",
                full_text,
            )
            if ref_match:
                ref_value = _normalize_value_for_key("referencia", ref_match.group(1))
                if ref_value:
                    fields.append(_make_field("referencia", "Referencia", ref_value, ocr_boxes, confidence=0.95))

            if not any(f.get("key") == "cp" for f in fields):
                cp_match = re.search(r"\b([0-9OIL]{5})\b", full_text)
                if cp_match:
                    normalized_cp = _normalize_value_for_key("cp", cp_match.group(1))
                    if normalized_cp:
                        fields.append(_make_field("cp", "CP", normalized_cp, ocr_boxes, confidence=0.9))

            if not any(f.get("key") == "fecha_limite" for f in fields):
                limit_match = re.search(
                    r"(?:PAGAR\s+ANTES\s+DE|FECHA\s*LIMITE(?:\s*DE\s*PAGO)?|VENCE)\D*([0-9]{1,2}(?:\s+|[-/])[A-Z]{3}(?:\s+|[-/])[0-9]{2,4}|\d{2}[/-]\d{2}[/-]\d{2,4})",
                    full_text,
                )
                if limit_match:
                    fields.append(_make_field("fecha_limite", "Fecha limite", limit_match.group(1), ocr_boxes, confidence=0.92))

            if not any(f.get("key") == "total" for f in fields):
                total_match = re.search(
                    r"(?:TOTAL\s+A\s+PAGAR|SALDO\s+TOTAL|IMPORTE\s+A\s+PAGAR|TOTAL)\D*(\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)",
                    full_text,
                )
                if total_match:
                    fields.append(_make_field("total", "Total", _normalize_text(total_match.group(1)), ocr_boxes, confidence=0.92))

            best_num = next((f for f in fields if f.get("key") == "numero_servicio"), None)
            if best_num and best_num.get("value"):
                num_value = _normalize_numeric_field(str(best_num["value"]))
                sanitized = []
                for field in fields:
                    if field.get("key") == "referencia" and field.get("value"):
                        ref_digits = _normalize_numeric_field(str(field["value"]))
                        if ref_digits and ref_digits == num_value:
                            continue
                    sanitized.append(field)
                fields = sanitized

            customer_idx = _pick_telmex_customer_index(box_text_lines)
            if customer_idx is not None:
                current_holder = next((f for f in fields if f.get("key") == "titular" and f.get("value")), None)
                holder_value = _normalize_text(str(current_holder.get("value", ""))).upper() if current_holder else ""
                needs_holder = not holder_value or holder_value == "PUBLICO EN GENERAL"
                if needs_holder:
                    holder_candidate = None
                    start = max(0, customer_idx - 4)
                    end = min(len(box_text_lines), customer_idx + 2)
                    for line in box_text_lines[start:end]:
                        candidate = _extract_possible_telmex_holder(line)
                        if candidate:
                            holder_candidate = _cleanup_telmex_holder(candidate)
                            break

                    if holder_candidate:
                        fields.append(_make_field("titular", "Titular", holder_candidate, ocr_boxes, confidence=0.99))
                    elif not current_holder:
                        fields.append(_make_field("titular", "Titular", "PUBLICO EN GENERAL", ocr_boxes, confidence=0.94))
                customer_address, customer_cp = _extract_telmex_customer_address_cp(box_text_lines, customer_idx)
                if customer_address:
                    fields.append(_make_field("domicilio", "Domicilio", customer_address, ocr_boxes, confidence=0.99))
                if customer_cp:
                    normalized_cp = _normalize_value_for_key("cp", customer_cp)
                    if normalized_cp:
                        fields.append(_make_field("cp", "CP", normalized_cp, ocr_boxes, confidence=1.0))

            # Final Telmex hardening for noisy OCR:
            # 1) sanitize any selected domicilio to remove payment footer text
            # 2) prefer customer CP over corporate CP 06500
            best_dom = _choose_telmex_domicilio(fields)
            fallback_dom = _extract_telmex_domicilio_from_full_text(full_text)
            if fallback_dom:
                if not best_dom:
                    best_dom = fallback_dom
                else:
                    best_has_street = ("CLL" in best_dom) or ("CALLE" in best_dom)
                    fb_has_street = ("CLL" in fallback_dom) or ("CALLE" in fallback_dom)
                    if fb_has_street and not best_has_street:
                        best_dom = fallback_dom
            if best_dom:
                best_dom = _enrich_telmex_domicilio(best_dom, full_text)
                fields = [f for f in fields if f.get("key") != "domicilio"]
                fields.append(_make_field("domicilio", "Domicilio", best_dom, ocr_boxes, confidence=1.0))

            current_cp = next((f for f in fields if f.get("key") == "cp" and f.get("value")), None)
            cp_value = _normalize_numeric_field(str(current_cp["value"])) if current_cp else ""
            if not cp_value or cp_value == "06500":
                better_cp = _choose_telmex_cp(fields, full_text)
                if better_cp:
                    fields = [f for f in fields if f.get("key") != "cp"]
                    fields.append(_make_field("cp", "CP", better_cp, ocr_boxes, confidence=1.0))

            if not any(f.get("key") == "referencia" for f in fields):
                long_numbers = re.findall(r"\b\d{18,24}\b", full_text)
                if best_num and best_num.get("value"):
                    num_value = _normalize_numeric_field(str(best_num["value"]))
                    candidate = next((n for n in long_numbers if n.startswith(num_value) and n != num_value), None)
                    if candidate:
                        fields.append(_make_field("referencia", "Referencia", candidate, ocr_boxes, confidence=0.94))
                elif long_numbers:
                    fields.append(_make_field("referencia", "Referencia", long_numbers[0], ocr_boxes, confidence=0.9))

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
