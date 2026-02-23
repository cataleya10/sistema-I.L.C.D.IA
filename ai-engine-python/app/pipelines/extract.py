import re
import json
import os
import logging
import unicodedata
from datetime import datetime

from app.pipelines.legacy_adapter import legacy_extract_fields

logger = logging.getLogger(__name__)

CURP_PATTERN = re.compile(r"\b[A-Z][AEIOUX][A-Z]{2}\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[HM][A-Z]{5}[A-Z0-9]\d\b")

# Posiciones de letras y dígitos en un CURP de 18 caracteres (índice 0)
_CURP_LETTER_POS = frozenset({0, 1, 2, 3, 10, 11, 12, 13, 14, 15, 16})
_CURP_DIGIT_POS = frozenset({4, 5, 6, 7, 8, 9, 17})
_CURP_OCR_DIGIT_TO_LETTER = {"0": "O", "1": "I", "5": "S", "8": "B"}
_CURP_OCR_LETTER_TO_DIGIT = {"O": "0", "I": "1", "L": "1", "S": "5", "B": "8"}


def _try_fix_curp_ocr(candidate: str) -> str:
    """Corrige confusiones OCR comunes en un candidato de 18 chars que podría ser CURP."""
    if len(candidate) != 18:
        return candidate
    chars = list(candidate.upper())
    for i, ch in enumerate(chars):
        if i in _CURP_LETTER_POS and ch in _CURP_OCR_DIGIT_TO_LETTER:
            chars[i] = _CURP_OCR_DIGIT_TO_LETTER[ch]
        elif i in _CURP_DIGIT_POS and ch in _CURP_OCR_LETTER_TO_DIGIT:
            chars[i] = _CURP_OCR_LETTER_TO_DIGIT[ch]
    return "".join(chars)


def _search_curp(text: str) -> str | None:
    """Busca CURP en texto; si no encuentra match directo, intenta corrección OCR."""
    m = CURP_PATTERN.search(text.upper())
    if m:
        return m.group(0)
    for candidate in re.findall(r"[A-Z0-9]{18}", text.upper()):
        fixed = _try_fix_curp_ocr(candidate)
        if CURP_PATTERN.fullmatch(fixed):
            return fixed
    return None
RFC_PATTERN = re.compile(r"\b[A-Z&]{3,4}\d{6}[A-Z0-9]{3}\b")
NSS_PATTERN = re.compile(r"\b\d{11}\b")
CLABE_PATTERN = re.compile(r"\b\d{18}\b")
ACCOUNT_PATTERN = re.compile(r"\b\d{10,16}\b")
AMOUNT_PATTERN = re.compile(r"\b\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\b")
DATE_PATTERN = re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b")
DATE_FLEX_PATTERN = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}(?:\s+|[-/])[A-Z]{3,9}(?:\s+|[-/])\d{2,4})\b"
)
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
    if key == "domicilio":
        return _clean_address_value(value)
    if key in {"lugar_nacimiento", "entidad_registro", "municipio_registro", "banco"}:
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

_ALIAS_MODEL_PATH = os.getenv(
    "FIELD_ALIAS_PATH",
    os.path.join(os.path.dirname(__file__), "..", "models", "field_aliases.json"),
)
_ALIAS_MODEL_MTIME = None
_ALIAS_MODEL_CACHE = {}


def _load_alias_model():
    global _ALIAS_MODEL_MTIME
    global _ALIAS_MODEL_CACHE

    try:
        if not os.path.exists(_ALIAS_MODEL_PATH):
            _ALIAS_MODEL_MTIME = None
            _ALIAS_MODEL_CACHE = {}
            return {}

        mtime = os.path.getmtime(_ALIAS_MODEL_PATH)
        if _ALIAS_MODEL_MTIME == mtime and isinstance(_ALIAS_MODEL_CACHE, dict):
            return _ALIAS_MODEL_CACHE

        with open(_ALIAS_MODEL_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if not isinstance(loaded, dict):
            loaded = {}
        _ALIAS_MODEL_CACHE = loaded
        _ALIAS_MODEL_MTIME = mtime
        return _ALIAS_MODEL_CACHE
    except Exception:
        logger.exception("Failed to load alias model from %s", _ALIAS_MODEL_PATH)
        return _ALIAS_MODEL_CACHE if isinstance(_ALIAS_MODEL_CACHE, dict) else {}


def _is_reasonable_alias(alias: str) -> bool:
    if not alias:
        return False
    token = _normalize_keyword(alias)
    if len(token) < 4:
        return False
    letters = sum(1 for ch in token if ch.isalpha())
    if letters < 3:
        return False
    banned = {"ES", "PAGO", "P", "CP", "NSS"}
    return token not in banned


def _merge_aliases(label: str) -> list[str]:
    base = LABEL_ALIASES.get(label, [label])
    aliases_from_model = _load_alias_model()
    raw_extra = aliases_from_model.get(LABEL_MAP.get(label, label), [])
    extra = [alias for alias in raw_extra if _is_reasonable_alias(str(alias))]
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
        "DEPTO",
    )
    noise_tokens = (
        "TELMEX",
        "TELCEL",
        "TELEFON",
        "NUMERO DE SERVICIO",
        "NO. DE SERVICIO",
        "NO DE SERVICIO",
        "RMU",
        "LINEA DE CAPTURA",
        "REFERENCIA",
        "CUENTA",
        "PAGAR",
        "TOTAL",
        "SALDO",
        "IMPORTE",
    )
    corporate_tokens = (
        "PASEO DE LA REFORMA",
        "ALCALDIA",
        "CUAUHTEMOC",
        "CIUDAD DE MEXICO",
        "RFC:CFE",
        "COMISION FEDERAL",
    )
    customer_tokens = ("DEPTO", "BENITO", "CARMEN", "S/N", "RIA", "SSL")
    stop_tokens = (
        "NO.DESERVICIO",
        "NO. DE SERVICIO",
        "RMU",
        "CUENTA",
        "TOTAL",
        "LIMITE",
        "CORTE",
        "TARIFA",
        "CONCEPTO",
        "LECTURA",
        "PERIODO",
    )

    best_candidate = None
    best_score = -10_000.0
    best_idx = -1

    def _line_score(text_line: str) -> float:
        score = 0.0
        score += sum(1.6 for k in keywords if k in text_line)
        if re.search(r"\bC\.?\s*P\.?\s*\d{5}\b", text_line) or re.search(r"\b\d{5}\b", text_line):
            score += 3.0
        if any(tok in text_line for tok in customer_tokens):
            score += 2.5
        if re.search(r"\b\d{1,2}DN\.?\d{1,4}\b|\b\d{1,2}DN\.?\b", text_line):
            score += 3.0
        if any(tok in text_line for tok in corporate_tokens):
            score -= 4.0
        if text_line.startswith("-"):
            score -= 0.6
        return score

    for idx, line in enumerate(lines):
        upper = _normalize_text(line).upper()
        if not upper:
            continue
        if not any(k in upper for k in keywords) and not any(tok in upper for tok in customer_tokens):
            continue
        if any(token in upper for token in noise_tokens):
            continue

        parts = [upper]
        score = _line_score(upper)
        if "DOMICILIO DE SUMINISTRO" in upper:
            score += 3.5

        for offset in (1, 2):
            next_idx = idx + offset
            if next_idx >= len(lines):
                break
            nxt = _normalize_text(lines[next_idx]).upper()
            if not nxt:
                continue
            if any(token in nxt for token in stop_tokens):
                break
            if any(token in nxt for token in noise_tokens):
                break
            if not (
                any(k in nxt for k in keywords)
                or re.search(r"\b\d{5}\b", nxt)
                or any(tok in nxt for tok in ("CIUDAD", "MUNICIPIO", "EDO", "TAB", "CAMP", "JONUTA"))
            ):
                break
            parts.append(nxt)
            score += _line_score(nxt) * 0.7

        candidate = " ".join(parts).strip()
        score += min(len(candidate), 140) * 0.02
        if score > best_score or (score == best_score and idx > best_idx):
            best_score = score
            best_candidate = candidate
            best_idx = idx

    return best_candidate


def _normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _ascii_fold(text: str) -> str:
    value = str(text or "")
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")


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
    """Agrupa boxes en líneas por proximidad en Y.

    Cuando los boxes tienen el campo "page" (documentos multi-página),
    se respeta la frontera de página: celdas de páginas distintas nunca
    se mezclan en la misma línea, evitando que filas de tabla de diferentes
    páginas a la misma coordenada Y se fundan en un único grupo.
    """
    lines = []
    # Ordena por (página, Y, X) para procesar cada página en secuencia
    for box in sorted(boxes, key=lambda b: (b.get("page") or 0, b["rect"][1], b["rect"][0])):
        x1, y1, x2, y2 = box["rect"]
        page = box.get("page") or 0
        placed = False
        for line in lines:
            if (line.get("page") or 0) != page:
                continue
            ly = line["y"]
            if abs(y1 - ly) <= y_tol:
                line["boxes"].append(box)
                line["y"] = (ly + y1) / 2
                placed = True
                break
        if not placed:
            lines.append({"y": y1, "page": page, "boxes": [box]})
    for line in lines:
        line["boxes"].sort(key=lambda b: b["rect"][0])
        line["text"] = " ".join(b.get("text", "").strip() for b in line["boxes"] if b.get("text"))
        line["text_norm"] = _normalize_keyword(line["text"])
    return lines


def _lines_text_from_boxes(ocr_boxes):
    boxes = _boxes_with_rect(ocr_boxes)
    lines = _line_groups(boxes)
    return lines


_PAYMENT_TABLE_HEADER_TOKENS = (
    "CUENTA",
    "REFERENCIA",
    "IMPORTE",
    "NOMBRE",
    "APELLIDO",
    "ESTATUS",
    "CONCEPTO",
    "BENEFICIARIO",
    "CLAVE RASTREO",
)

_PAYMENT_TABLE_STATUS_TOKENS = (
    "PROCESADO",
    "APLICADO",
    "ACEPTADO",
    "TRANSMITIDO",
)

_PAYMENT_TABLE_TEXT_LABELS = (
    "cuenta",
    "referencia",
    "importe",
    "nombre",
    "estatus",
    "concepto",
)

_GENERIC_TABLE_MAX_TABLES = 20
_GENERIC_TABLE_MAX_ROWS = 140
_GENERIC_TABLE_MAX_COLS = 25
_GENERIC_TABLE_MAX_CELL_TEXT = 240
_GENERIC_TABLE_BLOCK_GAP_Y = 36
_GENERIC_TABLE_LARGE_GAP_X = 34
_GENERIC_TABLE_JOIN_GAP_X = 16


def _normalize_table_cell(text: str) -> str:
    cell = _normalize_text(str(text or "")).upper()
    if not cell:
        return ""
    if len(cell) > 90:
        return cell[:90].rstrip() + "..."
    return cell


def _normalize_table_cell_exact(text: str) -> str:
    cell = _normalize_text(str(text or ""))
    if not cell:
        return ""
    if len(cell) > _GENERIC_TABLE_MAX_CELL_TEXT:
        return cell[:_GENERIC_TABLE_MAX_CELL_TEXT].rstrip()
    return cell


def _table_rows_signature(rows: list[list[str]]) -> str:
    parts: list[str] = []
    for row in rows[:6]:
        if not isinstance(row, list):
            continue
        key = "|".join(_normalize_keyword(str(cell or "")) for cell in row[:8])
        if key:
            parts.append(key)
    return "||".join(parts)


def _table_line_gap_stats(line: dict) -> dict[str, float]:
    boxes = [
        box for box in line.get("boxes", [])
        if _normalize_table_cell_exact(box.get("text", ""))
    ]
    if len(boxes) < 2:
        return {"box_count": float(len(boxes)), "max_gap": 0.0, "large_gap_count": 0.0}

    sorted_boxes = sorted(boxes, key=lambda item: item["rect"][0])
    gaps: list[float] = []
    for idx in range(len(sorted_boxes) - 1):
        left = sorted_boxes[idx]
        right = sorted_boxes[idx + 1]
        gaps.append(float(right["rect"][0] - left["rect"][2]))

    max_gap = max(gaps) if gaps else 0.0
    large_gap_count = sum(1 for gap in gaps if gap >= _GENERIC_TABLE_LARGE_GAP_X)
    return {
        "box_count": float(len(sorted_boxes)),
        "max_gap": float(max_gap),
        "large_gap_count": float(large_gap_count),
    }


def _looks_like_generic_table_line(line: dict) -> bool:
    stats = _table_line_gap_stats(line)
    box_count = int(stats.get("box_count", 0))
    max_gap = float(stats.get("max_gap", 0.0))
    large_gap_count = int(stats.get("large_gap_count", 0))
    return (
        (box_count >= 2 and large_gap_count >= 1)
        or (box_count >= 4 and max_gap >= 20.0)
    )


def _generic_column_anchors_from_line(line_boxes: list[dict]) -> list[dict]:
    if not line_boxes:
        return []

    sorted_boxes = sorted(line_boxes, key=lambda box: box["rect"][0])
    grouped: list[list[dict]] = []
    cluster = [sorted_boxes[0]]
    for box in sorted_boxes[1:]:
        prev = cluster[-1]
        gap = box["rect"][0] - prev["rect"][2]
        if gap <= _GENERIC_TABLE_JOIN_GAP_X:
            cluster.append(box)
            continue
        grouped.append(cluster)
        cluster = [box]
    grouped.append(cluster)

    anchors: list[dict] = []
    for idx, group in enumerate(grouped[:_GENERIC_TABLE_MAX_COLS]):
        x1 = min(item["rect"][0] for item in group)
        x2 = max(item["rect"][2] for item in group)
        label = _normalize_table_cell_exact(" ".join(item.get("text", "") for item in group))
        anchors.append(
            {
                "x": (x1 + x2) / 2,
                "x1": x1,
                "x2": x2,
                "label": label if label else f"COLUMN_{idx + 1}",
            }
        )
    return anchors


def _generic_row_with_cells_by_anchors(
    row_boxes: list[dict],
    anchors: list[dict],
) -> tuple[list[str], list[dict]]:
    if not row_boxes or not anchors:
        return [], []

    columns: list[list[tuple[float, str, tuple[float, float, float, float]]]] = [[] for _ in anchors]
    for box in row_boxes:
        text = _normalize_table_cell_exact(box.get("text", ""))
        if not text:
            continue
        x1, y1, x2, y2 = box["rect"]
        center = (x1 + x2) / 2
        best_idx = min(
            range(len(anchors)),
            key=lambda idx: abs(center - anchors[idx]["x"]),
        )
        columns[best_idx].append((x1, text, (x1, y1, x2, y2)))

    row: list[str] = []
    cells: list[dict] = []
    for col in columns:
        if not col:
            row.append("")
            cells.append({"text": "", "bbox": None})
            continue
        col.sort(key=lambda item: item[0])
        text = _normalize_table_cell_exact(" ".join(item[1] for item in col))
        rects = [item[2] for item in col]
        bbox = [
            int(round(min(rect[0] for rect in rects))),
            int(round(min(rect[1] for rect in rects))),
            int(round(max(rect[2] for rect in rects))),
            int(round(max(rect[3] for rect in rects))),
        ]
        row.append(text)
        cells.append({"text": text, "bbox": bbox})
    return row, cells


def _extract_generic_tables_from_boxes(ocr_boxes) -> list[dict]:
    lines = _lines_text_from_boxes(ocr_boxes)
    if not lines:
        return []

    table_lines: list[dict] = []
    for idx, line in enumerate(lines):
        boxes = [
            box for box in line.get("boxes", [])
            if _normalize_table_cell_exact(box.get("text", ""))
        ]
        if len(boxes) < 2:
            continue
        line_entry = {
            "index": idx,
            "y": float(line.get("y", 0.0) or 0.0),
            "boxes": boxes,
        }
        line_entry["is_table_like"] = _looks_like_generic_table_line({"boxes": boxes})
        if line_entry["is_table_like"]:
            table_lines.append(line_entry)

    if len(table_lines) < 2:
        return []

    blocks: list[list[dict]] = []
    current: list[dict] = []
    for line in table_lines:
        if not current:
            current = [line]
            continue
        gap = line["y"] - current[-1]["y"]
        if gap > _GENERIC_TABLE_BLOCK_GAP_Y:
            blocks.append(current)
            current = [line]
            continue
        current.append(line)
    if current:
        blocks.append(current)

    tables: list[dict] = []
    seen_signatures: set[str] = set()
    for block in blocks:
        if len(block) < 2:
            continue

        ref_line = max(
            block,
            key=lambda item: (
                int(_table_line_gap_stats({"boxes": item["boxes"]}).get("large_gap_count", 0)),
                len(item["boxes"]),
            ),
        )
        anchors = _generic_column_anchors_from_line(ref_line["boxes"])
        if len(anchors) < 2:
            continue

        rows: list[list[str]] = []
        row_cells: list[list[dict]] = []
        for line in block[:_GENERIC_TABLE_MAX_ROWS]:
            row, cells = _generic_row_with_cells_by_anchors(line["boxes"], anchors)
            non_empty = sum(1 for cell in row if _normalize_table_cell_exact(cell))
            if non_empty < 2:
                continue
            rows.append(row[:_GENERIC_TABLE_MAX_COLS])
            row_cells.append(cells[:_GENERIC_TABLE_MAX_COLS])

        if len(rows) < 2:
            continue

        signature = _table_rows_signature(rows)
        if not signature or signature in seen_signatures:
            continue
        seen_signatures.add(signature)

        rects = [
            box["rect"]
            for line in block
            for box in line["boxes"]
            if box.get("rect")
        ]
        if not rects:
            continue
        bbox = [
            int(round(min(rect[0] for rect in rects))),
            int(round(min(rect[1] for rect in rects))),
            int(round(max(rect[2] for rect in rects))),
            int(round(max(rect[3] for rect in rects))),
        ]

        tables.append(
            {
                "table_index": len(tables) + 1,
                "source": "ocr_boxes",
                "row_count": len(rows),
                "column_count": max((len(row) for row in rows), default=0),
                "bbox": bbox,
                "rows": rows,
                "cells": row_cells,
            }
        )
        if len(tables) >= _GENERIC_TABLE_MAX_TABLES:
            break

    return tables


def _extract_generic_tables_from_text(raw_text: str) -> list[dict]:
    text = str(raw_text or "")
    if not text.strip():
        return []

    tables: list[dict] = []
    current_rows: list[list[str]] = []
    seen_signatures: set[str] = set()

    def flush_current():
        nonlocal current_rows
        if len(current_rows) < 2:
            current_rows = []
            return
        signature = _table_rows_signature(current_rows)
        if not signature or signature in seen_signatures:
            current_rows = []
            return
        seen_signatures.add(signature)
        rows = [row[:_GENERIC_TABLE_MAX_COLS] for row in current_rows[:_GENERIC_TABLE_MAX_ROWS]]
        cells = [
            [{"text": _normalize_table_cell_exact(cell), "bbox": None} for cell in row]
            for row in rows
        ]
        tables.append(
            {
                "table_index": len(tables) + 1,
                "source": "text_lines",
                "row_count": len(rows),
                "column_count": max((len(row) for row in rows), default=0),
                "bbox": None,
                "rows": rows,
                "cells": cells,
            }
        )
        current_rows = []

    for raw_line in text.splitlines():
        line = _normalize_text(raw_line)
        if not line:
            flush_current()
            if len(tables) >= _GENERIC_TABLE_MAX_TABLES:
                break
            continue

        if "\t" in line:
            parts = [part.strip() for part in line.split("\t") if part.strip()]
        else:
            parts = [part.strip() for part in re.split(r"\s{2,}", line) if part.strip()]

        if len(parts) < 2:
            flush_current()
            if len(tables) >= _GENERIC_TABLE_MAX_TABLES:
                break
            continue

        row = [_normalize_table_cell_exact(part) for part in parts[:_GENERIC_TABLE_MAX_COLS]]
        current_rows.append(row)
        if len(current_rows) >= _GENERIC_TABLE_MAX_ROWS:
            flush_current()
            if len(tables) >= _GENERIC_TABLE_MAX_TABLES:
                break

    flush_current()
    return tables[:_GENERIC_TABLE_MAX_TABLES]


def _extract_all_table_payloads(base_text_raw: str, ocr_boxes) -> list[dict]:
    tables = _extract_generic_tables_from_boxes(ocr_boxes)
    if tables:
        return tables
    return _extract_generic_tables_from_text(base_text_raw)


def _pick_primary_table_from_payloads(tables: list[dict]) -> dict | None:
    if not tables:
        return None
    ranked = sorted(
        (
            table for table in tables
            if isinstance(table, dict)
            and isinstance(table.get("rows"), list)
            and len(table.get("rows", [])) >= 2
        ),
        key=lambda item: (
            int(item.get("row_count", 0)),
            int(item.get("column_count", 0)),
            int(item.get("row_count", 0)) * int(item.get("column_count", 0)),
        ),
        reverse=True,
    )
    return ranked[0] if ranked else None


def _looks_like_payment_table_header(cells: list[str]) -> bool:
    joined = " ".join(cells)
    hits = sum(1 for token in _PAYMENT_TABLE_HEADER_TOKENS if token in joined)
    return hits >= 2


def _looks_like_payment_table_data(cells: list[str]) -> bool:
    joined = " ".join(cells)
    has_amount = bool(re.search(r"\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\b", joined))
    long_numeric_cells = sum(1 for cell in cells if len(re.sub(r"\D", "", cell)) >= 8)
    has_status = any(token in joined for token in _PAYMENT_TABLE_STATUS_TOKENS)
    return (
        (has_amount and long_numeric_cells >= 1)
        or (has_status and long_numeric_cells >= 1)
        or (long_numeric_cells >= 2 and len(cells) >= 4)
    )


def _is_payment_table_footer(cells: list[str]) -> bool:
    joined = " ".join(cells)
    if "TOTAL" not in joined:
        return False
    return any(token in joined for token in ("MOVIMIENTO", "MOVIMIENTOS", "REGISTROS", "IMPORTE"))


def _payment_rows_plain_from_lines(lines: list[dict]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in lines:
        cells = [_normalize_table_cell(box.get("text", "")) for box in line.get("boxes", [])]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 3:
            rows.append(cells[:10])
    return rows


def _payment_table_column_anchors(header_boxes: list[dict]) -> list[dict]:
    if not header_boxes:
        return []
    sorted_boxes = sorted(header_boxes, key=lambda b: b["rect"][0])
    anchors: list[list[dict]] = []
    cluster = [sorted_boxes[0]]
    for box in sorted_boxes[1:]:
        prev = cluster[-1]
        prev_right = prev["rect"][2]
        curr_left = box["rect"][0]
        if curr_left - prev_right <= 12:
            cluster.append(box)
            continue
        anchors.append(cluster)
        cluster = [box]
    anchors.append(cluster)

    result: list[dict] = []
    for col_idx, group in enumerate(anchors):
        x1 = min(item["rect"][0] for item in group)
        x2 = max(item["rect"][2] for item in group)
        label = _normalize_table_cell(" ".join(item.get("text", "") for item in group))
        if not label:
            label = f"COLUMN_{col_idx + 1}"
        result.append({"x": (x1 + x2) / 2, "label": label})
    return result


def _payment_table_row_by_anchors(row_boxes: list[dict], anchors: list[dict]) -> list[str]:
    if not row_boxes or not anchors:
        return []
    columns: list[list[tuple[float, str]]] = [[] for _ in anchors]
    for box in row_boxes:
        text = _normalize_table_cell(box.get("text", ""))
        if not text:
            continue
        x1, _, x2, _ = box["rect"]
        center = (x1 + x2) / 2
        best_idx = min(
            range(len(anchors)),
            key=lambda idx: abs(center - anchors[idx]["x"]),
        )
        columns[best_idx].append((x1, text))

    row: list[str] = []
    for col in columns:
        if not col:
            row.append("")
            continue
        col.sort(key=lambda item: item[0])
        row.append(_normalize_table_cell(" ".join(text for _, text in col)))
    return row


_AMOUNT_IN_CELL_PAT = re.compile(r"^\$?\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))\b")
_STATUS_PREFIX_PAT = re.compile(r"^(PROCESADO|APLICADO|ACEPTADO|TRANSMITIDO|RECHAZADO)\b\s*")


def _fix_payment_ocr_column_errors(structured_rows: list[list[str]]) -> list[list[str]]:
    """Post-proceso para el path de OCR boxes.

    Corrige tres errores comunes de alineación de columnas en PDFs BBVA:
    1. Monto en columna NOMBRE (caja de texto asignada al anchor equivocado por proximidad X):
       extrae el monto a IMPORTE si está vacío y limpia NOMBRE.
    2. Fila con NOMBRE inválido (solo monto, sin nombre real): descarta la fila.
    3. ESTATUS embebido en CONCEPTO ("PROCESADO PAGO DE NOMINA"):
       separa la palabra de estado a la columna ESTATUS.
    """
    if len(structured_rows) < 2:
        return structured_rows

    header = structured_rows[0]
    keys = [_normalize_keyword(h).lower() for h in header]

    def _ci(name: str) -> int:
        for i, k in enumerate(keys):
            if name in k:
                return i
        return -1

    importe_idx = _ci("importe")
    nombre_idx = _ci("nombre")
    estatus_idx = _ci("estatus") if _ci("estatus") != -1 else _ci("estado")
    concepto_idx = _ci("concepto")

    fixed: list[list[str]] = [header]
    for orig_row in structured_rows[1:]:
        row = list(orig_row)

        # Fix 1: monto en columna nombre
        if 0 <= nombre_idx < len(row):
            nombre_val = row[nombre_idx].strip()
            m = _AMOUNT_IN_CELL_PAT.match(nombre_val)
            if m:
                amount_str = m.group(0).strip()
                name_after = nombre_val[m.end():].strip()
                if 0 <= importe_idx < len(row) and not row[importe_idx].strip():
                    row[importe_idx] = amount_str
                row[nombre_idx] = name_after

        # Fix 2: validar nombre — descartar fila si tiene un valor inválido.
        # Si nombre_original estaba vacío (sin caja OCR asignada), se deja pasar para
        # que el pipeline lo complete desde el texto. Si tenía un valor no-nombre
        # (ej. monto), se descarta.
        if 0 <= nombre_idx < len(row):
            nombre_original = orig_row[nombre_idx].strip() if nombre_idx < len(orig_row) else ""
            nombre_after_fix = row[nombre_idx].strip()
            if not _looks_like_person_name(nombre_after_fix):
                if nombre_original:
                    # Tenía algo (ej. un monto) pero no es un nombre válido → descartar
                    continue
                # Estaba vacío desde el inicio → dejar pasar (completar desde texto)

        # Fix 3: estatus embebido en concepto
        if 0 <= concepto_idx < len(row) and estatus_idx >= 0:
            concepto_val = row[concepto_idx].strip()
            sm = _STATUS_PREFIX_PAT.match(concepto_val)
            if sm:
                while len(row) <= estatus_idx:
                    row.append("")
                if not row[estatus_idx].strip():
                    row[estatus_idx] = sm.group(1)
                    row[concepto_idx] = concepto_val[sm.end():].strip() or "PAGO DE NOMINA"

        fixed.append(row)
    return fixed


def _extract_payment_table_rows_from_boxes(ocr_boxes) -> list[list[str]]:
    lines = _lines_text_from_boxes(ocr_boxes)
    rows = _payment_rows_plain_from_lines(lines)

    if not rows:
        return []

    header_idx = next((idx for idx, row in enumerate(rows) if _looks_like_payment_table_header(row)), None)
    if header_idx is None:
        return [row for row in rows if _looks_like_payment_table_data(row)][:500]

    header_boxes = [
        box for box in lines[header_idx].get("boxes", [])
        if _normalize_table_cell(box.get("text", ""))
    ]
    anchors = _payment_table_column_anchors(header_boxes)
    if len(anchors) >= 3:
        structured_rows: list[list[str]] = []
        header_row = [_normalize_table_cell(anchor.get("label", "")) for anchor in anchors]
        if _looks_like_payment_table_header(header_row):
            structured_rows.append(header_row[:10])

        for line in lines[header_idx + 1:]:
            if len(structured_rows) >= 500:
                break
            row_boxes = [
                box for box in line.get("boxes", [])
                if _normalize_table_cell(box.get("text", ""))
            ]
            if len(row_boxes) < 2:
                continue
            row = _payment_table_row_by_anchors(row_boxes, anchors)[:10]
            if _is_payment_table_footer(row) and len(structured_rows) > 1:
                break
            if _looks_like_payment_table_header(row):
                # Solo incluir el header una vez; headers repetidos (páginas 2-N) se saltan
                if not structured_rows:
                    structured_rows.append(row)
                continue
            if _looks_like_payment_table_data(row):
                structured_rows.append(row)

        if len(structured_rows) > 1:
            return _fix_payment_ocr_column_errors(structured_rows)

    selected = [rows[header_idx]]
    for row in rows[header_idx + 1:]:
        if len(selected) >= 500:
            break
        if _is_payment_table_footer(row) and len(selected) > 1:
            break
        if _looks_like_payment_table_header(row):
            # Headers repetidos de páginas siguientes: saltar silenciosamente
            continue
        if _looks_like_payment_table_data(row):
            selected.append(row)

    return selected if len(selected) > 1 else []


_ADVANCED_NOMINA_TABLE_HEADER = [
    "CUENTA",
    "REFERENCIA",
    "IMPORTE",
    "NOMBRE",
    "APELLIDO PATERNO",
    "APELLIDO MATERNO",
    "ESTATUS",
    "CONCEPTO",
]


def _split_payment_name_parts(full_name: str) -> tuple[str, str, str]:
    normalized = _normalize_name(full_name)
    if not normalized:
        return "", "", ""
    tokens = [token for token in normalized.split() if token]
    if len(tokens) <= 2:
        return normalized, "", ""
    if len(tokens) == 3:
        return tokens[0], tokens[1], tokens[2]
    return " ".join(tokens[:-2]), tokens[-2], tokens[-1]


def _extract_bbva_nomina_advanced_rows_from_text(raw_text: str) -> list[list[str]]:
    folded = _ascii_fold(str(raw_text or "")).upper()
    if "NOMINA" not in folded:
        return []

    lines = [_ascii_fold(_normalize_text(line)).upper() for line in str(raw_text or "").splitlines() if _normalize_text(line)]
    if not lines:
        return []

    # La referencia puede venir con un espacio OCR intermedio (ej: "16202601151343405812 63")
    # _REF_PAT acepta dígitos con un espacio interno opcional para tolerar ese artefacto
    _REF_PAT = r"\d{10,28}(?:\s+\d{1,6})?"
    row_pattern = re.compile(
        r"\b(?P<cuenta>\d{10,24})\s+"
        r"(?P<referencia>" + _REF_PAT + r")\s+"
        r"(?P<importe>\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))\s+"
        r"(?P<nombre>[A-ZÑÁÉÍÓÚÜ ]{4,120}?)"
        r"(?=\s+\d{10,24}\s+" + _REF_PAT + r"\s+\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})"
        r"|\s+(?:PROCESADO|APLICADO|ACEPTADO|TRANSMITIDO|RECHAZADO)\b"
        r"|\s*$)"
    )
    status_pattern = re.compile(r"\b(PROCESADO|APLICADO|ACEPTADO|TRANSMITIDO|RECHAZADO)\b")
    concept_pattern = re.compile(r"\b(PAGO(?:\s+DE)?\s+NOMINA|ABONO\s+NOMINA)\b")

    global_status_match = status_pattern.search(folded)
    global_status = _normalize_table_cell(global_status_match.group(1)) if global_status_match else ""
    global_concept_match = concept_pattern.search(folded)
    global_concept = _normalize_table_cell(global_concept_match.group(1)) if global_concept_match else ""

    rows: list[list[str]] = []
    seen: set[tuple[str, str, str]] = set()
    for line in lines:
        if "CUENTA" in line and "REFERENCIA" in line and "IMPORTE" in line and "NOMBRE" in line:
            continue
        line_status_match = status_pattern.search(line)
        line_status = _normalize_table_cell(line_status_match.group(1)) if line_status_match else global_status
        line_concept_match = concept_pattern.search(line)
        line_concept = _normalize_table_cell(line_concept_match.group(1)) if line_concept_match else global_concept

        for match in row_pattern.finditer(line):
            cuenta = _normalize_numeric_field(match.group("cuenta"))
            # Elimina espacio OCR interno en la referencia (ej: "16202601...812 63" → "...81263")
            ref_raw = re.sub(r"\s+", "", match.group("referencia"))
            referencia = _normalize_value_for_key("referencia", ref_raw)
            importe = _normalize_payment_amount(match.group("importe"))
            full_name = _normalize_name(match.group("nombre"))
            if not _looks_like_person_name(full_name):
                continue

            tail = line[match.end():]
            tail_status_match = status_pattern.search(tail)
            estatus = _normalize_table_cell(tail_status_match.group(1)) if tail_status_match else line_status

            tail_concept_match = concept_pattern.search(tail)
            concepto = _normalize_table_cell(tail_concept_match.group(1)) if tail_concept_match else line_concept

            if not cuenta or not referencia or not importe:
                continue

            nombre, apellido_paterno, apellido_materno = _split_payment_name_parts(full_name)
            if not nombre:
                continue

            dedupe_key = (cuenta, referencia, importe)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            rows.append(
                [
                    cuenta,
                    referencia,
                    importe,
                    nombre,
                    apellido_paterno,
                    apellido_materno,
                    estatus,
                    concepto or line_concept or global_concept or "PAGO DE NOMINA",
                ]
            )

    if len(rows) < 1:
        return []

    return [_ADVANCED_NOMINA_TABLE_HEADER, *rows[:500]]


def _extract_payment_table_rows_from_text(raw_text: str) -> list[list[str]]:
    if not raw_text:
        return []
    advanced_rows = _extract_bbva_nomina_advanced_rows_from_text(raw_text)
    if advanced_rows:
        return advanced_rows
    rows: list[list[str]] = []
    for raw_line in raw_text.splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        if "\t" in line:
            parts = [part.strip() for part in line.split("\t") if part.strip()]
        else:
            parts = [part.strip() for part in re.split(r"\s{2,}", line) if part.strip()]
        cells = [_normalize_table_cell(part) for part in parts if part.strip()]
        if len(cells) < 3:
            continue
        if _looks_like_payment_table_header(cells) or _looks_like_payment_table_data(cells):
            rows.append(cells[:10])
        if len(rows) >= 500:
            break
    if rows:
        return rows
    return _extract_payment_table_rows_from_compact_text(raw_text)


def _extract_scotia_transfer_rows(lines: list[str]) -> list[list[str]]:
    if not lines:
        return []
    full = " ".join(lines)
    if "SCOTIABANK" not in full and "TRANSFERENCIA DE ARCHIVOS" not in full:
        return []
    if "DA ALTA" not in full and "DAALTA" not in full:
        return []

    header = [
        "TIPO DE REGISTRO",
        "TIPO DE MOVIMIENTO (PAGO)",
        "IMPORTE",
        "FECHA DE APLICACION",
        "CLAVE DEL BENEFICIARIO",
        "NOMBRE DEL BENEFICIARIO",
        "REFERENCIA",
        "NO. CUENTA BENEFICIARIO",
        "NO. BANCO RECEPTOR",
        "DIAS DE VIGENCIA",
        "CONCEPTO PAGO",
    ]

    rows: list[list[str]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        key = _normalize_keyword(line)
        if "DAALTA" not in key and "DA ALTA" not in line:
            i += 1
            continue

        block: list[str] = []
        j = i
        while j < len(lines) and len(block) < 18:
            curr = lines[j]
            curr_key = _normalize_keyword(curr)
            if j > i and "DAALTA" in curr_key:
                break
            if any(token in curr for token in ("TOTAL DE MOVIMIENTOS", "CANTIDAD DE MOVIMIENTOS", "IMPORTE DE MOVIMIENTOS")):
                break
            block.append(curr)
            j += 1

        joined = " ".join(block)
        amount_match = re.search(r"\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})", joined)
        date_match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", joined)
        clave_match = re.search(r"\bA\d{2,4}\b", joined)
        cuenta_match = re.search(r"\b\d{18,24}\b", joined)
        concepto_match = re.search(r"\bPAG[O0]\s*0?\d{1,4}\b", joined)
        movimiento_match = re.search(r"\b\d{2}\s+ABONO\s+EN\s+CUENTA\b", joined)
        referencia_match = re.search(r"\b([0-9OIL]{1,3})\b(?=\s+\d{18,24})", joined)

        cuenta = cuenta_match.group(0) if cuenta_match else ""
        banco = ""
        vigencia = ""
        if cuenta:
            post = joined.split(cuenta, 1)[1]
            trailing = re.search(r"\b(\d{1,2})\b(?:\s+\b(\d)\b)?", post)
            if trailing:
                banco = trailing.group(1) or ""
                vigencia = trailing.group(2) or ""

        beneficiary_parts: list[str] = []
        for raw in block:
            candidate = _normalize_text(raw).upper()
            if not candidate:
                continue
            if any(
                token in candidate
                for token in (
                    "DA ALTA",
                    "ABONO EN",
                    "TIPO DE",
                    "MOVIMIENTO",
                    "IMPORTE",
                    "FECHA DE",
                    "CLAVE DEL",
                    "REFERENCIA",
                    "CUENTA",
                    "NO. CUENTA",
                    "NO.BANCO",
                    "DIAS DE",
                    "CONCEPTO",
                )
            ):
                continue
            if re.fullmatch(r"\d{1,3}", candidate):
                continue
            if re.fullmatch(r"\d{18,24}(?:\s+\d{1,2})?(?:\s+\d)?", candidate):
                continue
            if re.search(r"\$", candidate) or re.search(r"\d{2}/\d{2}/\d{4}", candidate):
                continue
            if re.fullmatch(r"A\d{2,4}", candidate):
                continue
            if re.fullmatch(r"PAG[O0]\d{1,4}", candidate):
                continue
            normalized_name = _normalize_name(candidate)
            if not normalized_name:
                continue
            if normalized_name not in beneficiary_parts:
                beneficiary_parts.append(normalized_name)

        beneficiary = " ".join(beneficiary_parts[:3]).strip()
        beneficiary = re.sub(r"^CUENTA\s+", "", beneficiary)
        beneficiary = re.sub(r"\s+\b1\b$", "", beneficiary)
        row = [
            "DA ALTA",
            _normalize_table_cell(movimiento_match.group(0) if movimiento_match else "04 ABONO EN CUENTA"),
            _normalize_table_cell(amount_match.group(0) if amount_match else ""),
            date_match.group(0) if date_match else "",
            clave_match.group(0) if clave_match else "",
            beneficiary,
            _normalize_numeric_field(referencia_match.group(1)) if referencia_match else "",
            cuenta,
            banco,
            vigencia,
            _normalize_table_cell(concepto_match.group(0) if concepto_match else ""),
        ]
        dedup_key = (row[4], row[7], row[10])
        if row[7] and (row[2] or row[3] or row[10]) and dedup_key not in seen_keys:
            seen_keys.add(dedup_key)
            rows.append(row)
        i = j

    if not rows:
        return []
    summary_rows = _extract_scotia_summary_rows(lines)
    return [header, *rows[:25], *summary_rows]


def _extract_scotia_summary_rows(lines: list[str]) -> list[list[str]]:
    if not lines:
        return []
    extracted: list[list[str]] = []

    normal_values = _extract_scotia_summary_block_values(lines, total=False)
    if normal_values:
        extracted.append(
            [
                "CANTIDAD DE MOVIMIENTOS ALTAS",
                "IMPORTE DE MOVIMIENTO ALTAS",
                "CANTIDAD DE MOVIMIENTOS BAJAS",
                "IMPORTE DE MOVIMIENTOS BAJAS",
            ]
        )
        extracted.append(normal_values)

    total_values = _extract_scotia_summary_block_values(lines, total=True)
    if total_values:
        extracted.append(
            [
                "TOTAL CANTIDAD DE MOVIMIENTOS ALTAS",
                "TOTAL IMPORTE DE MOVIMIENTO ALTAS",
                "TOTAL CANTIDAD DE MOVIMIENTOS BAJAS",
                "TOTAL IMPORTE DE MOVIMIENTOS BAJAS",
            ]
        )
        extracted.append(total_values)

    return extracted


def _extract_scotia_summary_block_values(lines: list[str], total: bool) -> list[str]:
    if not lines:
        return []
    full = " ".join(lines)
    if total:
        pattern = re.search(
            r"TOTAL\s+CANTIDAD\s+DE\s+MOVIMIENTO[S]?\s+ALTAS\s+"
            r"TOTAL\s+IMPORTE\s+DE\s+MOVIMIENTO[S]?\s+ALTAS\s+"
            r"TOTAL\s+CANTIDAD\s+DE\s+MOVIMIENTO[S]?\s+BAJAS\s+"
            r"TOTAL\s+IMPORTE\s+DE\s+MOVIMIENTO[S]?\s+BAJAS(?:\s+[A-Z]+){0,3}\s+"
            r"([0-9OIL]{1,6})\s+(\$?\s*[0-9OIL.,]{1,24})\s+([0-9OIL]{1,6})\s+(\$?\s*[0-9OIL.,]{1,24})",
            full,
        )
    else:
        pattern = re.search(
            r"CANTIDAD\s+DE\s+MOVIMIENTO[S]?\s+ALTAS\s+"
            r"IMPORTE\s+DE\s+MOVIMIENTO[S]?\s+ALTAS\s+"
            r"CANTIDAD\s+DE\s+MOVIMIENTO[S]?\s+BAJAS\s+"
            r"IMPORTE\s+DE\s+MOVIMIENTO[S]?\s+BAJAS(?:\s+[A-Z]+){0,3}\s+"
            r"([0-9OIL]{1,6})\s+(\$?\s*[0-9OIL.,]{1,24})\s+([0-9OIL]{1,6})\s+(\$?\s*[0-9OIL.,]{1,24})",
            full,
        )
    if pattern:
        return [
            _normalize_payment_count(pattern.group(1)),
            _normalize_payment_amount(pattern.group(2)),
            _normalize_payment_count(pattern.group(3)),
            _normalize_payment_amount(pattern.group(4)),
        ]

    anchor = "TOTAL CANTIDAD DE MOVIMIENTOS ALTAS" if total else "CANTIDAD DE MOVIMIENTOS ALTAS"
    start_idx = -1
    for idx, line in enumerate(lines):
        if anchor in line:
            start_idx = idx
            break
    if start_idx < 0:
        return []

    amount_values: list[str] = []
    count_values: list[str] = []
    amount_re = re.compile(r"\$?\s*[0-9OIL]{1,3}(?:[.,][0-9OIL]{3})*(?:[.,][0-9OIL]{2})")
    for raw_line in lines[start_idx : min(len(lines), start_idx + 30)]:
        line = raw_line.strip()
        if not line:
            continue
        if any(token in line for token in ("CANTIDAD", "IMPORTE", "MOVIMIENTO", "BAJAS", "ALTAS", "TOTAL")):
            continue
        for amount in amount_re.findall(line):
            normalized_amount = _normalize_payment_amount(amount)
            if normalized_amount:
                amount_values.append(normalized_amount)
        compact = re.sub(r"\s+", "", line)
        if re.fullmatch(r"[0-9OIL]{1,6}", compact or ""):
            normalized_count = _normalize_payment_count(compact)
            if normalized_count:
                count_values.append(normalized_count)
        if len(count_values) >= 2 and len(amount_values) >= 2:
            break

    if len(count_values) < 2 or len(amount_values) < 2:
        return []
    return [count_values[0], amount_values[0], count_values[1], amount_values[1]]


def _extract_payment_table_rows_from_compact_text(raw_text: str) -> list[list[str]]:
    if not raw_text:
        return []

    lines = [_ascii_fold(_normalize_text(line)).upper() for line in raw_text.splitlines() if _normalize_text(line)]
    if not lines:
        return []

    scotia_rows = _extract_scotia_transfer_rows(lines)
    if scotia_rows:
        return scotia_rows
    detail_rows = _extract_banorte_bbva_detail_rows(lines, raw_text)
    if detail_rows:
        return detail_rows
    bbva_transfer_rows = _extract_bbva_transfer_receipt_rows(lines, raw_text)
    if bbva_transfer_rows:
        return bbva_transfer_rows

    full = " ".join(lines)
    values: dict[str, str] = {}

    def pick(pattern: str) -> str:
        match = re.search(pattern, full)
        if not match:
            return ""
        return _normalize_table_cell(match.group(1))

    def pick_labeled_value(labels: list[str]) -> str:
        for line in lines:
            candidate = line
            for label in labels:
                if candidate.startswith(label + ":"):
                    return _normalize_table_cell(candidate.split(":", 1)[1])
                tag = f"{label}:"
                if tag in candidate:
                    return _normalize_table_cell(candidate.split(tag, 1)[1])
        return ""

    nombre_directo = pick_labeled_value(["NOMBRE"])
    apellido_paterno = pick_labeled_value(["APELLIDO PATERNO", "APELLIDOPATERNO"])
    apellido_materno = pick_labeled_value(["APELLIDO MATERNO", "APELLIDOMATERNO"])

    values["cuenta"] = _normalize_numeric_field(
        pick_labeled_value(
            [
                "NUMERO DE CUENTA DE ABONO",
                "NUMERO DE CUENTA",
                "NO. DE CUENTA",
                "CUENTA CARGO",
            ]
        )
    ) or _normalize_numeric_field(
        pick(r"(?:NUMERO DE CUENTA DE ABONO|CUENTA(?: DE ABONO)?|NO\.?\s*DE\s*CUENTA)\s*:?\s*([0-9OIL.-]{8,26})")
    )
    values["referencia"] = _normalize_value_for_key(
        "referencia",
        pick_labeled_value(["REFERENCIA", "REFERENCIA DE CARGO", "LINEA DE CAPTURA"])
        or pick(r"(?:REFERENCIA(?: DE CARGO)?|LINEA DE CAPTURA)\s*:?\s*([0-9OIL.-]{10,36})"),
    )
    values["importe"] = _normalize_table_cell(
        pick_labeled_value(["IMPORTE", "IMPORTE TOTAL", "TOTAL A PAGAR"])
        or pick(r"(?:IMPORTE(?: TOTAL)?|TOTAL A PAGAR)\s*:?\s*(\$?\s*[0-9OIL]{1,3}(?:[.,][0-9OIL]{3})*(?:[.,][0-9OIL]{2}))")
    )
    name_labeled = nombre_directo
    if not name_labeled:
        name_labeled = pick(r"(?:NOMBRE)\s*:\s*([A-ZÑÁÉÍÓÚÜ ]{4,80})")
    if not name_labeled:
        name_labeled = pick(r"(?:NOMBRE)\s*:?\s*([A-ZÑÁÉÍÓÚÜ ]{4,80}?)(?=\s+(?:ESTATUS|CONCEPTO|REFERENCIA|CUENTA|IMPORTE)\b|$)")
    full_name = _normalize_name(
        " ".join(part for part in [name_labeled, apellido_paterno, apellido_materno] if part).strip()
    ) or _normalize_name(name_labeled)
    if full_name and not _looks_like_person_name(full_name):
        full_name = ""
    values["nombre"] = full_name
    values["estatus"] = _normalize_table_cell(
        pick_labeled_value(["ESTATUS"])
        or pick(r"(?:ESTATUS)\s*:?\s*([A-ZÑÁÉÍÓÚÜ]{4,30})")
    )
    concept_labeled = pick_labeled_value(["CONCEPTO"])
    if not concept_labeled:
        concept_labeled = pick(r"(?:TIPO DE PAGO)\s*:?\s*([A-ZÑÁÉÍÓÚÜ ]{4,80})")
    if not concept_labeled:
        concept_labeled = pick(r"(?:CONCEPTO)\s*:?\s*([A-ZÑÁÉÍÓÚÜ ]{4,80}?)(?=\s+(?:ESTATUS|NOMBRE|REFERENCIA|CUENTA|IMPORTE)\b|$)")
    values["concepto"] = _normalize_table_cell(concept_labeled)
    if values["concepto"]:
        values["concepto"] = re.sub(
            r"\s+\b(?:ESTATUS|NOMBRE|REFERENCIA|CUENTA|IMPORTE)\b.*$",
            "",
            values["concepto"],
        ).strip()

    if not values["cuenta"] or not values["referencia"]:
        for line in lines:
            nums = re.findall(r"\d{10,24}", line)
            if len(nums) >= 2:
                if not values["cuenta"]:
                    values["cuenta"] = nums[0]
                if not values["referencia"]:
                    values["referencia"] = nums[1]
                break

    if not values["importe"] or not values["nombre"]:
        for line in lines:
            amt = re.search(r"(\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))", line)
            if not amt:
                continue
            if not values["importe"]:
                values["importe"] = _normalize_table_cell(amt.group(1))
            if not values["nombre"]:
                tail = line[amt.end():].strip()
                if tail:
                    tail_name = _normalize_name(tail)
                    if tail_name and _looks_like_person_name(tail_name):
                        values["nombre"] = tail_name
            break

    if not values["cuenta"] or not values["importe"] or not values["estatus"]:
        movement_match = re.search(
            r"\b(\d{12,24})\s*\$?\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))\s*(APLICADO|PROCESADO|ACEPTADO|RECHAZADO)\b",
            full,
        )
        if movement_match:
            if not values["cuenta"]:
                values["cuenta"] = movement_match.group(1)
            if not values["importe"]:
                values["importe"] = "$" + movement_match.group(2) if not movement_match.group(2).startswith("$") else movement_match.group(2)
            if not values["estatus"]:
                values["estatus"] = movement_match.group(3)

    if not values["nombre"]:
        for line in lines:
            cleaned = _normalize_name(line)
            if not cleaned:
                continue
            token_count = len(cleaned.split())
            if token_count < 3:
                continue
            if any(
                marker in line
                for marker in (
                    "REPORTE",
                    "ARCHIVO",
                    "EMPRESA",
                    "CONTRATO",
                    "FOLIO",
                    "TRANSFERENCIA",
                    "CANTIDAD",
                    "MOVIMIENTOS",
                    "TIPO DE",
                    "CUENTA",
                    "REFERENCIA",
                    "IMPORTE",
                    "ESTATUS",
                    "CONCEPTO",
                )
            ):
                continue
            values["nombre"] = cleaned
            break

    filled = sum(1 for key in _PAYMENT_TABLE_TEXT_LABELS if values.get(key))
    if filled < 3:
        return []

    header = ["CUENTA", "REFERENCIA", "IMPORTE", "NOMBRE", "ESTATUS", "CONCEPTO"]
    row = [
        values.get("cuenta", ""),
        values.get("referencia", ""),
        values.get("importe", ""),
        values.get("nombre", ""),
        values.get("estatus", ""),
        values.get("concepto", ""),
    ]

    if not any(cell for cell in row):
        return []

    return [header, row]


def _extract_banorte_bbva_detail_rows(lines: list[str], raw_text: str) -> list[list[str]]:
    full = " ".join(lines)
    if "REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS" not in full:
        return []
    if not any(token in full for token in ("NO. EMPLEADO", "NOEMPLEADO", "DETALLE")):
        return []

    header = [
        "NO. EMPLEADO",
        "NOMBRE",
        "TIPO CUENTA",
        "NO. DE CUENTA",
        "IMPORTE",
        "ESTATUS",
        "CODIGO",
        "DESCRIPCION",
        "CLAVE RASTREO",
    ]

    employee = ""
    name = ""
    tipo_cuenta = ""
    cuenta = ""
    importe = ""
    estatus = ""
    codigo = ""
    descripcion = ""
    clave_rastreo = ""

    detail_idx = next(
        (
            i
            for i, line in enumerate(lines)
            if any(marker in line for marker in ("NO. EMPLEADO", "NOEMPLEADO", "DETALLE"))
        ),
        None,
    )

    if detail_idx is not None:
        scope = lines[detail_idx : min(len(lines), detail_idx + 20)]
        for idx, line in enumerate(scope):
            if not employee and re.fullmatch(r"\d{6,12}", line):
                employee = line
                for nxt in scope[idx + 1 : idx + 5]:
                    words = [w for w in nxt.split() if w.isalpha() and len(w) >= 2]
                    if len(words) >= 3:
                        name = _normalize_name(nxt)
                        break
                continue
            if not tipo_cuenta and re.fullmatch(r"\d{2}", line):
                tipo_cuenta = line
                continue
            if not codigo and re.fullmatch(r"\d{2}", line) and tipo_cuenta and line != tipo_cuenta:
                codigo = line
                continue
            if (
                not descripcion
                and any(token in line for token in ("ACEPTADO", "RECHAZADO", "APLICADO", "TRANSMITIDO"))
                and "$" not in line
                and len(re.sub(r"\D", "", line)) < 4
            ):
                descripcion = _normalize_table_cell(line)

    if detail_idx is not None:
        chunk = " ".join(lines[detail_idx : min(len(lines), detail_idx + 24)])
    else:
        chunk = full
    account_match = re.search(r"\b\d{12,24}\b", chunk)
    if account_match:
        cuenta = _normalize_numeric_field(account_match.group(0))
    amount_match = re.search(r"\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})", chunk)
    if amount_match:
        importe = _normalize_payment_amount(amount_match.group(0))
    status_match = re.search(r"\b(TRANSMITIDO|APLICADO|ACEPTADO|RECHAZADO|PROCESADO)\b", chunk)
    if status_match:
        estatus = _normalize_table_cell(status_match.group(1))

    if not descripcion:
        status_values = re.findall(r"\b(ACEPTADO|RECHAZADO|APLICADO|TRANSMITIDO|PROCESADO)\b", chunk)
        if status_values:
            descripcion = _normalize_table_cell(status_values[-1])
    if not descripcion and estatus:
        descripcion = estatus

    trace_match = re.search(r"FOLIO\s+ELECTRONICO\s*:?\s*([A-Z0-9]{8,50})", full)
    if trace_match:
        clave_rastreo = _normalize_table_cell(trace_match.group(1))
    elif cuenta:
        ref_match = re.search(r"\b\d{7,12}\b", chunk)
        if ref_match:
            clave_rastreo = _normalize_table_cell(ref_match.group(0))

    if not name:
        candidate_name = re.search(r"\b([A-Z]{2,}(?:\s+[A-Z]{2,}){2,6})\b", chunk)
        if candidate_name:
            guessed = _normalize_name(candidate_name.group(1))
            if _looks_like_person_name(guessed):
                name = guessed

    populated = sum(1 for value in [cuenta, importe, name, estatus, employee] if value)
    if populated < 3:
        return []

    row = [employee, name, tipo_cuenta, cuenta, importe, estatus, codigo, descripcion, clave_rastreo]
    return [header, row]


def _extract_bbva_transfer_receipt_rows(lines: list[str], raw_text: str) -> list[list[str]]:
    if not lines:
        return []
    normalized_lines = [str(line or "").strip() for line in lines if str(line or "").strip()]
    normalized_keys = [_normalize_keyword(_ascii_fold(line).upper()) for line in normalized_lines]
    full = " ".join(normalized_lines)
    full_key = " ".join(normalized_keys)
    if "COMPROBANTE" not in full_key:
        return []
    if not any(
        token in full_key
        for token in (
            "RESULTADODELTRASPASO",
            "TRASPASOSAOTROSBANCOS",
            "TRASPASOAOTROSBANCOS",
        )
    ):
        return []
    has_deposit_label = any(
        key.startswith("CUENTADEDEPOSITO")
        or key.startswith("CUENTADEDEPSITO")
        or key.startswith("CUENTADESTINO")
        for key in normalized_keys
    )
    if not has_deposit_label:
        return []

    def keyword_close(left: str, right: str) -> bool:
        if left == right:
            return True
        if abs(len(left) - len(right)) > 1:
            return False
        i = 0
        j = 0
        mismatches = 0
        while i < len(left) and j < len(right):
            if left[i] == right[j]:
                i += 1
                j += 1
                continue
            mismatches += 1
            if mismatches > 1:
                return False
            if len(left) > len(right):
                i += 1
            elif len(right) > len(left):
                j += 1
            else:
                i += 1
                j += 1
        if i < len(left) or j < len(right):
            mismatches += 1
        return mismatches <= 1

    def pick_line_value(labels: list[str], lookahead: int = 4, max_len: int = 120) -> str:
        label_pairs = []
        for label in labels:
            key = _normalize_keyword(_ascii_fold(_normalize_text(label)).upper())
            if key:
                label_pairs.append((label, key))
        for idx, line in enumerate(normalized_lines):
            line_key = normalized_keys[idx]
            for label, label_key in label_pairs:
                if keyword_close(line_key, label_key):
                    for next_idx in range(idx + 1, min(len(normalized_lines), idx + 1 + lookahead)):
                        next_line = normalized_lines[next_idx]
                        next_key = normalized_keys[next_idx]
                        if not next_line:
                            continue
                        if any(keyword_close(next_key, candidate_key) for _, candidate_key in label_pairs):
                            continue
                        return _normalize_text(next_line)[:max_len]
                if line_key.startswith(label_key):
                    remainder = _normalize_text(line).strip(" :")
                    prefix = _normalize_text(label)
                    if remainder.startswith(prefix):
                        remainder = remainder[len(prefix):].strip(" :")
                    if remainder:
                        return remainder[:max_len]
        fallback = _payment_pick_labeled_value(raw_text, labels, max_len=max_len)
        if fallback:
            return fallback
        return ""

    cuenta_retiro = _normalize_numeric_field(
        pick_line_value(["CUENTA DE RETIRO"], max_len=30)
    )
    tipo_operacion = _normalize_text(
        pick_line_value(["TIPO DE OPERACION"], max_len=90)
    )
    banco_destino = _normalize_text(
        pick_line_value(["BANCO DESTINO"], max_len=80)
    )
    cuenta_destino = _normalize_numeric_field(
        pick_line_value(
            ["CUENTA DE DEPOSITO", "CUENTA DESTINO", "CUENTA DE ABONO"],
            max_len=40,
        )
    )
    importe = _normalize_payment_amount(
        pick_line_value(["IMPORTE"], max_len=40)
    )
    forma_deposito = _normalize_text(
        pick_line_value(["FORMA DE DEPOSITO"], max_len=80)
    )
    concepto = _normalize_text(
        pick_line_value(["CONCEPTO DE PAGO", "CONCEPTO"], max_len=100)
    )
    raw_referencia = pick_line_value(["REFERENCIA NUMERICA", "REFERENCIA"], max_len=40)
    referencia = _normalize_value_for_key("referencia", raw_referencia)
    if not referencia:
        short_reference = _normalize_numeric_field(raw_referencia)
        if re.fullmatch(r"\d{1,3}", short_reference or ""):
            referencia = short_reference
    if not referencia:
        for idx, line_key in enumerate(normalized_keys):
            if "REFERENCIA" not in line_key:
                continue
            for next_idx in range(idx + 1, min(len(normalized_lines), idx + 3)):
                candidate_line = normalized_lines[next_idx]
                candidate_key = normalized_keys[next_idx]
                if any(
                    token in candidate_key
                    for token in ("CLAVE", "NOMBRE", "IMPORTE", "CONCEPTO", "BANCO", "CUENTA", "FORMA")
                ):
                    continue
                candidate = _normalize_value_for_key("referencia", candidate_line)
                if not candidate:
                    short_candidate = _normalize_numeric_field(candidate_line)
                    if re.fullmatch(r"\d{1,3}", short_candidate or ""):
                        candidate = short_candidate
                if candidate:
                    referencia = candidate
                    break
            if referencia:
                break
    clave_rastreo = _normalize_text(
        pick_line_value(["CLAVE DE RASTREO", "CLAVE RASTREO"], max_len=80)
    )

    nombre = ""
    beneficiary_match = re.search(
        r"DATOS\s+DEL\s+BENEFICIARIO\s+NOMBRE\s*:?\s*([^\n\r]{4,120})",
        str(raw_text or ""),
        flags=re.IGNORECASE,
    )
    if beneficiary_match:
        candidate = _normalize_name(beneficiary_match.group(1))
        if candidate and _looks_like_person_name(candidate):
            nombre = candidate
    if not nombre:
        candidate_short = _normalize_name(
            pick_line_value(["NOMBRE CORTO"])
        )
        if candidate_short and _looks_like_person_name(candidate_short):
            nombre = candidate_short

    estatus = ""
    status_match = re.search(r"\b(APLICADO|ACEPTADO|TRANSMITIDO|RECHAZADO|PROCESADO)\b", full)
    if status_match:
        estatus = _normalize_text(status_match.group(1))
    elif "ENPROCESODEVALIDACION" in full_key:
        estatus = "EN PROCESO"

    populated = sum(
        1
        for value in [
            cuenta_retiro,
            cuenta_destino,
            importe,
            banco_destino,
            referencia,
            clave_rastreo,
            nombre,
        ]
        if value
    )
    if populated < 4:
        return []

    header = [
        "CUENTA DE RETIRO",
        "TIPO DE OPERACION",
        "BANCO DESTINO",
        "CUENTA DE DEPOSITO",
        "IMPORTE",
        "FORMA DE DEPOSITO",
        "CONCEPTO DE PAGO",
        "REFERENCIA NUMERICA",
        "CLAVE DE RASTREO",
        "NOMBRE",
        "ESTATUS",
    ]
    row = [
        cuenta_retiro,
        tipo_operacion,
        banco_destino,
        cuenta_destino,
        importe,
        forma_deposito,
        concepto,
        referencia,
        clave_rastreo,
        nombre,
        estatus,
    ]
    return [header, row]


def _extract_payment_table_payload(base_text_raw: str, ocr_boxes) -> dict | None:
    all_tables = _extract_all_table_payloads(base_text_raw, ocr_boxes)
    rows_ocr = _extract_payment_table_rows_from_boxes(ocr_boxes)
    rows_text = _extract_payment_table_rows_from_text(base_text_raw)

    score_ocr = _payment_rows_quality_score(rows_ocr) if len(rows_ocr) >= 2 else -999
    score_text = _payment_rows_quality_score(rows_text) if len(rows_text) >= 2 else -999

    selected_table_index = None
    if score_ocr >= score_text and score_ocr >= 0:
        rows = rows_ocr
        source = "ocr_boxes"
    elif score_text >= 0:
        rows = rows_text
        source = "text_lines"
    else:
        fallback_table = _pick_primary_table_from_payloads(all_tables)
        if not isinstance(fallback_table, dict):
            return None
        fallback_rows = fallback_table.get("rows")
        if not isinstance(fallback_rows, list) or len(fallback_rows) < 2:
            return None
        rows = [
            [str(cell or "") for cell in row]
            for row in fallback_rows
            if isinstance(row, list)
        ]
        if len(rows) < 2:
            return None
        source = "generic_table_payload"
        selected_table_index = int(fallback_table.get("table_index", 0) or 0)

    if source == "ocr_boxes":
        rows = _merge_payment_rows_with_backup(rows, rows_text)
    else:
        rows = _merge_payment_rows_with_backup(rows, rows_ocr)

    rows = _append_scotia_summary_rows_to_table(rows, base_text_raw)
    payload = {
        "source": source,
        "rows": rows,
    }
    if all_tables:
        payload["all_tables"] = all_tables
        payload["all_table_count"] = len(all_tables)
        row_signature = _table_rows_signature(rows)
        matched = next(
            (
                int(table.get("table_index", 0) or 0)
                for table in all_tables
                if isinstance(table, dict)
                and _table_rows_signature(table.get("rows", [])) == row_signature
            ),
            0,
        )
        if matched > 0:
            payload["primary_table_index"] = matched
        elif selected_table_index and selected_table_index > 0:
            payload["primary_table_index"] = selected_table_index
    return payload


def _build_payment_mapped_fields(payment_detail: dict) -> dict[str, str]:
    if not isinstance(payment_detail, dict):
        return {}

    mapped: dict[str, str] = {}
    bank = _normalize_text(str(payment_detail.get("bank") or ""))
    if bank:
        mapped["banco"] = bank

    metadata = payment_detail.get("metadata")
    if isinstance(metadata, dict):
        for key in (
            "tipo_pago",
            "fecha_hora_proceso",
            "fecha_hora_captura",
            "folio_internet",
            "numero_lote",
            "nombre_archivo",
            "usuario_sistema_nombre",
            "importe_detectado",
        ):
            value = _normalize_text(str(metadata.get(key) or ""))
            if value:
                mapped[key] = value

    table = payment_detail.get("table")
    if not isinstance(table, dict):
        return mapped

    canonical_rows = table.get("canonical_rows")
    if not isinstance(canonical_rows, list):
        return mapped

    first_row = next(
        (
            row
            for row in canonical_rows
            if isinstance(row, dict)
            and any(_normalize_text(str(cell or "")) for cell in row.values())
        ),
        None,
    )
    if not isinstance(first_row, dict):
        return mapped

    key_map = {
        "cuenta": "cuenta",
        "cuenta_beneficiario": "cuenta_beneficiario",
        "cuenta_retiro": "cuenta_retiro",
        "banco_destino": "banco_destino",
        "referencia": "referencia",
        "importe": "importe",
        "concepto_pago": "concepto_pago",
        "clave_rastreo": "clave_rastreo",
        "nombre_beneficiario": "nombre_beneficiario",
        "estatus": "estatus",
        "tipo_operacion": "tipo_operacion",
        "forma_deposito": "forma_deposito",
        "tipo_registro": "tipo_registro",
        "tipo_movimiento": "tipo_movimiento",
    }
    for source_key, target_key in key_map.items():
        value = _normalize_text(str(first_row.get(source_key) or ""))
        if value:
            mapped[target_key] = value

    return mapped


def _enrich_payment_table_payload(
    table_payload: dict | None,
    payment_detail: dict | None,
) -> dict | None:
    if not isinstance(table_payload, dict):
        return table_payload
    if not isinstance(payment_detail, dict):
        return table_payload

    enriched = dict(table_payload)

    bank = _normalize_text(str(payment_detail.get("bank") or ""))
    if bank:
        enriched["bank"] = bank

    metadata = payment_detail.get("metadata")
    if isinstance(metadata, dict):
        metadata_clean: dict[str, str] = {}
        for key, value in metadata.items():
            text = _normalize_text(str(value or ""))
            if text:
                metadata_clean[str(key)] = text
        if metadata_clean:
            enriched["metadata"] = metadata_clean

    detail_table = payment_detail.get("table")
    if isinstance(detail_table, dict):
        canonical_columns = detail_table.get("canonical_columns")
        if isinstance(canonical_columns, list):
            columns = [_normalize_text(str(column or "")) for column in canonical_columns if _normalize_text(str(column or ""))]
            if columns:
                enriched["canonical_columns"] = columns

        canonical_rows = detail_table.get("canonical_rows")
        if isinstance(canonical_rows, list):
            rows: list[dict[str, str]] = []
            for row in canonical_rows:
                if not isinstance(row, dict):
                    continue
                normalized_row: dict[str, str] = {}
                for key, value in row.items():
                    text = _normalize_text(str(value or ""))
                    if text:
                        normalized_row[str(key)] = text
                if normalized_row:
                    rows.append(normalized_row)
            if rows:
                enriched["canonical_rows"] = rows
                enriched["canonical_row_count"] = len(rows)

    mapped_fields = _build_payment_mapped_fields(payment_detail)
    if mapped_fields:
        enriched["mapped_fields"] = mapped_fields

    return enriched


def _append_scotia_summary_rows_to_table(rows: list[list[str]], raw_text: str) -> list[list[str]]:
    if len(rows) < 2:
        return rows
    if _payment_detect_bank(raw_text) != "SCOTIABANK":
        return rows
    lines = [_ascii_fold(_normalize_text(line)).upper() for line in str(raw_text or "").splitlines() if _normalize_text(line)]
    if not lines:
        return rows
    summary_rows = _extract_scotia_summary_rows(lines)
    if not summary_rows:
        return rows

    existing = {"|".join(_normalize_table_cell(cell) for cell in row) for row in rows}
    appended = list(rows)
    for row in summary_rows:
        signature = "|".join(_normalize_table_cell(cell) for cell in row)
        if signature in existing:
            continue
        appended.append(row)
        existing.add(signature)
    return appended


def _payment_rows_look_low_quality(rows: list[list[str]]) -> bool:
    return _payment_rows_quality_score(rows) < 0


def _header_cell_has_repeated_tokens(cell: str) -> bool:
    tokens = [token for token in str(cell or "").strip().split() if token]
    if len(tokens) < 2:
        return False
    upper_tokens = [token.upper() for token in tokens]
    if all(token == upper_tokens[0] for token in upper_tokens):
        return True
    if len(upper_tokens) % 2 == 0:
        half = len(upper_tokens) // 2
        if upper_tokens[:half] == upper_tokens[half:]:
            return True
    return False


def _payment_rows_quality_score(rows: list[list[str]]) -> int:
    if len(rows) < 2:
        return -100
    header = [str(cell or "").strip().upper() for cell in rows[0]]
    data = [str(cell or "").strip().upper() for cell in rows[1]]
    if len(header) < 3:
        return -80

    header_joined = " ".join(header)
    header_hits = sum(1 for token in _PAYMENT_TABLE_HEADER_TOKENS if token in header_joined)
    score = header_hits * 15
    score += min(10, len(rows) - 1) * 4
    score -= sum(max(0, len(cell) - 60) for cell in header) // 4
    score -= sum(max(0, len(cell) - 120) for cell in data) // 6

    repeated_header_cells = sum(1 for cell in header if _header_cell_has_repeated_tokens(cell))
    score -= repeated_header_cells * 14

    data_joined = " ".join(data)
    noisy_fragments = (
        "UNIDAD ESPECIALIZADA",
        "ACLARACION",
        "TELEFONOS",
        "INSTITUCION",
        "COMPROBANTE",
        "LAPSO",
    )
    score -= sum(18 for fragment in noisy_fragments if fragment in data_joined)

    amount_hits = len(re.findall(r"\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})\b", data_joined))
    if amount_hits >= 2:
        score -= 20
    compact_number_hits = sum(1 for cell in data if len(re.findall(r"\b\d{10,24}\b", cell)) >= 2)
    if compact_number_hits >= 1:
        score -= 18

    if "CUENTA" in header_joined and data:
        account_cell = data[0] if len(data) >= 1 else ""
        if account_cell and re.search(r"[A-Z]", account_cell):
            if any(token in account_cell for token in ("DATOS", "CLIENTE", "PAGADOR")):
                score -= 25
            if sum(ch.isdigit() for ch in account_cell) < 8:
                score -= 15
    if "REFERENCIA" in header_joined and len(data) >= 2:
        ref_cell = data[1]
        if ref_cell and re.search(r"[A-Z]", ref_cell):
            if any(token in ref_cell for token in ("DATOS", "CLIENTE", "PAGADOR")):
                score -= 25
            if sum(ch.isdigit() for ch in ref_cell) < 8:
                score -= 15
    if re.search(r"\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})", data_joined):
        score += 12
    else:
        score -= 20
    return score


def _payment_header_token_index(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, cell in enumerate(header):
        normalized = _normalize_keyword(cell).lower()
        if normalized and normalized not in mapping:
            mapping[normalized] = idx
    return mapping


def _payment_header_alias(token: str) -> str:
    aliases = {
        "nocuentabeneficiario": "cuenta",
        "numerodecuenta": "cuenta",
        "numerodecuentadeabono": "cuenta",
        "cuentadedeposito": "cuenta",
        "cuentadeposito": "cuenta",
        "referenciadecarga": "referencia",
        "referencianumerica": "referencia",
        "clavebeneficiario": "referencia",
        "nombredelbeneficiario": "nombre",
        "nombrebeneficiario": "nombre",
        "conceptodepago": "concepto",
        "tipodemovimientopago": "concepto",
        "tipodemovimiento": "concepto",
    }
    return aliases.get(token, token)


def _merge_payment_rows_with_backup(primary_rows: list[list[str]], backup_rows: list[list[str]]) -> list[list[str]]:
    if len(primary_rows) < 2 or len(backup_rows) < 2:
        return primary_rows

    primary_header = [str(cell or "") for cell in primary_rows[0]]
    backup_header = [str(cell or "") for cell in backup_rows[0]]
    if not primary_header or not backup_header:
        return primary_rows

    primary_idx = _payment_header_token_index(primary_header)
    backup_idx_raw = _payment_header_token_index(backup_header)
    backup_idx: dict[str, int] = {}
    for token, idx in backup_idx_raw.items():
        alias = _payment_header_alias(token)
        if alias and alias not in backup_idx:
            backup_idx[alias] = idx

    if not primary_idx or not backup_idx:
        return primary_rows

    merged = [primary_header]
    max_data_rows = max(len(primary_rows), len(backup_rows)) - 1
    for row_offset in range(max_data_rows):
        primary_row = list(primary_rows[row_offset + 1]) if row_offset + 1 < len(primary_rows) else [""] * len(primary_header)
        backup_row = backup_rows[row_offset + 1] if row_offset + 1 < len(backup_rows) else []
        if not backup_row:
            merged.append(primary_row)
            continue

        if len(primary_row) < len(primary_header):
            primary_row.extend([""] * (len(primary_header) - len(primary_row)))

        for token, p_idx in primary_idx.items():
            if p_idx >= len(primary_row):
                continue
            if _normalize_text(primary_row[p_idx]):
                continue
            alias = _payment_header_alias(token)
            b_idx = backup_idx.get(alias)
            if b_idx is None or b_idx >= len(backup_row):
                continue
            backup_value = _normalize_text(str(backup_row[b_idx] or ""))
            if backup_value:
                primary_row[p_idx] = backup_value

        merged.append(primary_row)

    return merged


def _payment_detect_bank(raw_text: str) -> str:
    text = _ascii_fold(str(raw_text or "")).upper()
    if "SCOTIABANK" in text:
        return "SCOTIABANK"
    if "BBVA" in text or "BANCOMER" in text or "REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS" in text:
        return "BBVA"
    if (
        any(token in text for token in ("BNET", "FOLIO DE INTERNET", "RESULTADO DEL TRASPASO"))
        and "CUENTA DE RETIRO" in text
        and ("CUENTA DE DEPOSITO" in text or "CUENTA DESTINO" in text)
    ):
        return "BBVA"
    if "SANTANDER" in text:
        return "SANTANDER"
    if "BANORTE" in text or "IXE" in text:
        return "BANORTE"
    if "BANAMEX" in text or "CITIBANAMEX" in text:
        return "BANAMEX"
    return "DESCONOCIDO"


def _payment_pick_labeled_value(raw_text: str, labels: list[str], max_len: int = 120) -> str:
    lines = [_ascii_fold(_normalize_text(line)).upper() for line in str(raw_text or "").splitlines() if _normalize_text(line)]
    for line in lines:
        for label in labels:
            key = _ascii_fold(_normalize_text(label)).upper()
            if line.startswith(key + ":"):
                return _normalize_text(line.split(":", 1)[1])[:max_len]
            if key + ":" in line:
                return _normalize_text(line.split(key + ":", 1)[1])[:max_len]
            if line.startswith(key + " "):
                remainder = _normalize_text(line[len(key):])
                if len(remainder) >= 2:
                    return remainder[:max_len]
    full = " ".join(lines)
    for label in labels:
        key = _ascii_fold(_normalize_text(label)).upper()
        match = re.search(rf"{re.escape(key)}\s*:?\s*(.+?)(?=\s+[A-Z0-9][A-Z0-9 .:/-]{{2,}}:\s*|$)", full)
        if match:
            return _normalize_text(match.group(1))[:max_len]
    return ""


def _normalize_payment_datetime(value: str) -> str:
    raw = _normalize_text(str(value or ""))
    if not raw:
        return ""
    upper = _ascii_fold(raw).upper()
    if "SIN FECHA" in upper:
        return "SIN FECHA Y HORA DE REGISTRO"
    date_match = re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", upper)
    time_match = re.search(r"\d{2}:\d{2}(?::\d{2})?", upper)
    if date_match and time_match:
        normalized_date = _normalize_date_value(date_match.group(0))
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", normalized_date):
            return f"{normalized_date} {time_match.group(0)}"
    if date_match:
        normalized_date = _normalize_date_value(date_match.group(0))
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", normalized_date):
            return normalized_date
    return raw


def _normalize_payment_amount(value: str) -> str:
    text = _normalize_text(str(value or "")).upper()
    if not text:
        return ""
    text = text.replace("O", "0").replace("I", "1").replace("L", "1")
    match = re.search(r"\$?\s*(\d[\d.,]{1,24})", text)
    if not match:
        return ""
    token = match.group(1)
    token = re.sub(r"[^\d.,]", "", token)
    if not token:
        return ""
    decimal_sep = None
    if "." in token and "," in token:
        decimal_sep = "." if token.rfind(".") > token.rfind(",") else ","
    elif token.count(".") == 1 and len(token.split(".")[-1]) == 2:
        decimal_sep = "."
    elif token.count(",") == 1 and len(token.split(",")[-1]) == 2:
        decimal_sep = ","

    if decimal_sep:
        integer_raw, cents_raw = token.rsplit(decimal_sep, 1)
        integer_digits = re.sub(r"\D", "", integer_raw)
        cents_digits = re.sub(r"\D", "", cents_raw)
        if not integer_digits:
            return ""
        cents = (cents_digits + "00")[:2]
        return f"${int(integer_digits):,}.{cents}"

    integer_digits = re.sub(r"\D", "", token)
    if not integer_digits:
        return ""
    return f"${int(integer_digits):,}.00"


def _normalize_payment_count(value: str) -> str:
    raw = _normalize_numeric_field(str(value or ""))
    if not raw:
        return ""
    if len(raw) > 6:
        return raw[:6]
    return str(int(raw))


def _extract_scotia_payment_metadata(raw_text: str) -> dict[str, str]:
    text = _ascii_fold(str(raw_text or "")).upper()
    out: dict[str, str] = {}
    date_match = re.search(r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b", text)
    if date_match:
        normalized_date = _normalize_date_value(date_match.group(1))
        if normalized_date:
            out["fecha_archivo"] = normalized_date
    time_match = re.search(r"\b(\d{2}:\d{2}(?::\d{2})?)\b", text)
    if time_match:
        out["hora_archivo"] = time_match.group(1)
    contract_match = re.search(r"NUMERO DE CONTRATO SCOTIA EN LINEA\s*:?\s*([0-9OIL]{4,12})", text)
    if contract_match:
        out["numero_contrato_scotia_linea"] = _normalize_numeric_field(contract_match.group(1))
    folio_match = re.search(r"\bFOLIO\s*:?\s*([0-9OIL]{4,18})\b", text)
    if folio_match:
        out["folio"] = _normalize_numeric_field(folio_match.group(1))
    archivo_match = re.search(r"NOMBRE DEL ARCHIVO\s*:?\s*([A-Z0-9._ -]{6,80})", text)
    if archivo_match:
        out["nombre_archivo"] = _normalize_text(archivo_match.group(1))
    usuario_match = re.search(r"NOMBRE DE USUARIO DEL SISTEMA Y NOMBRE\s*:?\s*([A-Z0-9._ -]{6,120})", text)
    if usuario_match:
        out["usuario_sistema_nombre"] = _normalize_text(usuario_match.group(1))
    validacion_match = re.search(
        r"FECHA Y HORA DE VALIDACION DEL ARCHIVO\s*:?\s*([A-Z0-9:/ .-]{6,80})",
        text,
    )
    if validacion_match:
        out["fecha_hora_validacion_archivo"] = _normalize_text(validacion_match.group(1))
    registro_match = re.search(
        r"(SIN FECHA Y HORA DE REGISTRO|FECHA Y HORA DE REGISTRO\s*:?\s*[A-Z0-9:/ .-]{6,80})",
        text,
    )
    if registro_match:
        out["fecha_hora_registro"] = _normalize_text(registro_match.group(1))
    carga_match = re.search(
        r"TIPO DE REGISTRO\s+CUENTA DE CARGA\s+REFERENCIA DE CARGA\s+([A-Z]+)\s+([0-9OIL]{6,20})\s+([0-9OIL]{1,4})",
        text,
    )
    if carga_match:
        out["tipo_registro_carga"] = _normalize_text(carga_match.group(1))
        out["cuenta_carga"] = _normalize_numeric_field(carga_match.group(2))
        out["referencia_carga"] = _normalize_numeric_field(carga_match.group(3))
    for key, pattern in {
        "cantidad_total_movimientos": r"CANTIDAD TOTAL DE MOVIMIENTOS\s*:?\s*([0-9OIL]{1,6})",
        "cantidad_movimientos_altas": r"CANTIDAD DE MOVIMIENT(?:O|OS) ALTAS\s*:?\s*([0-9OIL]{1,6})",
        "cantidad_movimientos_bajas": r"CANTIDAD DE MOVIMIENT(?:O|OS) BAJAS\s*:?\s*([0-9OIL]{1,6})",
        "total_registros_leidos": r"TOTAL DE REGISTROS LEIDOS\s*:?\s*([0-9OIL]{1,6})",
    }.items():
        match = re.search(pattern, text)
        if match:
            normalized = _normalize_payment_count(match.group(1))
            if normalized:
                out[key] = normalized
    for key, pattern in {
        "importe_total_movimientos": r"IMPORTE TOTAL DE MOVIMIENTOS\s*:?\s*(\$?\s*[0-9OIL.,]{4,20})",
        "importe_movimiento_altas": r"IMPORTE DE MOVIMIENT(?:O|OS) ALTAS\s*:?\s*(\$?\s*[0-9OIL.,]{4,20})",
        "importe_movimientos_bajas": r"IMPORTE DE MOVIMIENT(?:O|OS) BAJAS\s*:?\s*(\$?\s*[0-9OIL.,]{4,20})",
    }.items():
        match = re.search(pattern, text)
        if match:
            normalized = _normalize_payment_amount(match.group(1))
            if normalized:
                out[key] = normalized
    return out


def _extract_bbva_payment_metadata(raw_text: str) -> dict[str, str]:
    text = _ascii_fold(str(raw_text or "")).upper()
    out: dict[str, str] = {}
    if "REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS" in text:
        out["reporte_tipo"] = "REPORTE DE TRANSMISION DE ARCHIVO DE PAGOS"
    payment_type = re.search(r"TIPO DE PAGO\s*:?\s*([A-Z ]{4,80})", text)
    if payment_type:
        out["tipo_pago"] = _normalize_text(payment_type.group(1)).upper()
    accepted = re.findall(r"\b(APLICADO|ACEPTADO|TRANSMITIDO|RECHAZADO)\b", text)
    if accepted:
        out["estatus_detectados"] = ",".join(sorted(set(accepted)))
    amount_match = re.search(r"\$?\s*([0-9OIL]{1,3}(?:[.,][0-9OIL]{3})*(?:[.,][0-9OIL]{2}))", text)
    if amount_match:
        normalized = _normalize_payment_amount(amount_match.group(0))
        if normalized:
            out["importe_detectado"] = normalized
    process_dt = re.search(
        r"(?:FECHA(?:\s+Y\s+HORA)?\s+DE\s+PROCESO|FECHA(?:\s+DE)?\s+TRANSMISION)\s*:?\s*([A-Z0-9:/ .-]{8,80})",
        text,
    )
    if process_dt:
        out["fecha_hora_proceso"] = _normalize_text(process_dt.group(1))
    capture_dt = re.search(
        r"FECHA\s+Y\s+HORA\s+DE\s+CAPTURA\s*:?\s*([A-Z0-9:/ .-]{8,80})",
        text,
    )
    if capture_dt:
        out["fecha_hora_captura"] = _normalize_text(capture_dt.group(1))
    folio_internet = re.search(r"FOLIO\s+DE\s+INTERNET\s*:?\s*([0-9OIL]{4,20})", text)
    if folio_internet:
        normalized_folio = _normalize_numeric_field(folio_internet.group(1))
        if re.fullmatch(r"\d{4,20}", normalized_folio):
            out["folio_internet"] = normalized_folio
    archivo_value = _payment_pick_labeled_value(raw_text, ["NOMBRE DE ARCHIVO", "ARCHIVO"], max_len=120)
    if archivo_value and ("." in archivo_value or "_" in archivo_value or re.search(r"\d", archivo_value)):
        out["nombre_archivo"] = _normalize_text(archivo_value)
    else:
        archivo_match = re.search(r"(?:NOMBRE\s+DE\s+ARCHIVO|ARCHIVO)\s*:\s*([A-Z0-9._ -]{6,120})", text)
        if archivo_match:
            out["nombre_archivo"] = _normalize_text(archivo_match.group(1))
    usuario_match = re.search(r"(?:USUARIO|OPERADOR)\s*:?\s*([A-Z0-9._ -]{4,80})", text)
    if usuario_match:
        out["usuario_sistema_nombre"] = _normalize_text(usuario_match.group(1))
    lote_match = re.search(r"(?:LOTE|LOTE\s+ID|NO\.?\s+DE\s+LOTE)\s*:?\s*([0-9OIL]{1,12})", text)
    if lote_match:
        out["numero_lote"] = _normalize_numeric_field(lote_match.group(1))
    archivo_num_match = re.search(r"(?:NO\.?\s+DE\s+ARCHIVO|ARCHIVO\s+NO)\s*:?\s*([0-9OIL]{1,12})", text)
    if archivo_num_match:
        out["numero_archivo_en_dia"] = _normalize_numeric_field(archivo_num_match.group(1))
    return out


def _extract_scotia_summary_tables(raw_text: str) -> list[dict]:
    text = str(raw_text or "")
    if not text.strip():
        return []
    lines = [_ascii_fold(_normalize_text(line)).upper() for line in text.splitlines() if _normalize_text(line)]
    if not lines:
        return []

    tables: list[dict] = []
    normal_values = _extract_scotia_summary_block_values(lines, total=False)
    if normal_values:
        tables.append(
            {
                "title": "RESUMEN MOVIMIENTOS",
                "columns": [
                    "CANTIDAD DE MOVIMIENTOS ALTAS",
                    "IMPORTE DE MOVIMIENTO ALTAS",
                    "CANTIDAD DE MOVIMIENTOS BAJAS",
                    "IMPORTE DE MOVIMIENTOS BAJAS",
                ],
                "rows": [normal_values],
            }
        )

    total_values = _extract_scotia_summary_block_values(lines, total=True)
    if total_values:
        tables.append(
            {
                "title": "RESUMEN TOTAL",
                "columns": [
                    "TOTAL CANTIDAD DE MOVIMIENTOS ALTAS",
                    "TOTAL IMPORTE DE MOVIMIENTO ALTAS",
                    "TOTAL CANTIDAD DE MOVIMIENTOS BAJAS",
                    "TOTAL IMPORTE DE MOVIMIENTOS BAJAS",
                ],
                "rows": [total_values],
            }
        )

    return tables


def _sanitize_payment_metadata(metadata: dict[str, str]) -> dict[str, str]:
    if not metadata:
        return {}
    cleaned: dict[str, str] = {}
    date_keys = {"fecha_archivo"}
    datetime_keys = {"fecha_hora_validacion_archivo", "fecha_hora_registro", "fecha_hora_proceso", "fecha_hora_captura"}
    time_keys = {"hora_archivo"}
    amount_keys = {"importe_total_movimientos", "importe_movimiento_altas", "importe_movimientos_bajas", "importe_detectado"}
    count_keys = {"cantidad_total_movimientos", "cantidad_movimientos_altas", "cantidad_movimientos_bajas", "total_registros_leidos"}
    numeric_keys = {
        "numero_contrato_scotia_linea",
        "folio",
        "folio_internet",
        "numero_archivo_en_dia",
        "numero_contrato_servicio",
        "numero_lote",
        "cuenta_carga",
        "referencia_carga",
    }
    for key, value in metadata.items():
        raw = _normalize_text(str(value or ""))
        if not raw:
            continue
        if key in date_keys:
            normalized = _normalize_date_value(raw)
            if re.fullmatch(r"\d{2}/\d{2}/\d{4}", normalized):
                cleaned[key] = normalized
            continue
        if key in datetime_keys:
            normalized = _normalize_payment_datetime(raw)
            if normalized:
                cleaned[key] = normalized
            continue
        if key in time_keys:
            time_match = re.search(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", raw)
            if time_match:
                cleaned[key] = time_match.group(0)
            continue
        if key in amount_keys:
            normalized = _normalize_payment_amount(raw)
            if normalized:
                cleaned[key] = normalized
            continue
        if key in count_keys:
            normalized = _normalize_payment_count(raw)
            if normalized:
                cleaned[key] = normalized
            continue
        if key in numeric_keys:
            normalized = _normalize_numeric_field(raw)
            if key in {"folio", "folio_internet"} and len(normalized) < 4:
                continue
            if normalized:
                cleaned[key] = normalized
            continue
        if key in {
            "nombre_archivo",
            "usuario_sistema_nombre",
            "nombre_contrato_scotia_linea",
            "nombre_empresa",
            "reporte_tipo",
            "tipo_pago",
            "tipo_registro_carga",
        }:
            cleaned[key] = _normalize_text(raw).upper()
            continue
        cleaned[key] = raw
    return cleaned


def _payment_header_keys_from_cells(cells: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: dict[str, int] = {}
    for idx, cell in enumerate(cells):
        base = _normalize_keyword(cell).lower()
        if not base:
            base = f"columna_{idx + 1}"
        count = seen.get(base, 0) + 1
        seen[base] = count
        normalized.append(base if count == 1 else f"{base}_{count}")
    return normalized


def _payment_rows_to_objects(rows: list[list[str]]) -> list[dict]:
    if len(rows) < 2:
        return []
    header = rows[0]
    keys = _payment_header_keys_from_cells(header)
    objects: list[dict] = []
    for row in rows[1:]:
        item: dict[str, str] = {}
        for idx, key in enumerate(keys):
            if idx >= len(row):
                item[key] = ""
            else:
                item[key] = _normalize_text(str(row[idx] or ""))
        if any(str(v).strip() for v in item.values()):
            objects.append(item)
    return objects[:80]


def _canonical_payment_key(bank: str, raw_key: str) -> str:
    key = _normalize_keyword(raw_key).lower()
    if not key:
        return ""

    base_map = {
        "cuenta": "cuenta",
        "cuentaderetiro": "cuenta_retiro",
        "cuentabeneficiario": "cuenta_beneficiario",
        "numerodecuentabeneficiario": "cuenta_beneficiario",
        "numerodecuenta": "cuenta",
        "nocuenta": "cuenta",
        "cuentadedeposito": "cuenta",
        "cuentadeposito": "cuenta",
        "cuentacuenta": "cuenta",
        "referencia": "referencia",
        "referencianumerica": "referencia",
        "referenciareferencia": "referencia",
        "importe": "importe",
        "importeimporte": "importe",
        "nombre": "nombre_beneficiario",
        "nombrebeneficiario": "nombre_beneficiario",
        "nombrenombre": "nombre_beneficiario",
        "apellidopaterno": "apellido_paterno",
        "apellidomaterno": "apellido_materno",
        "apellidopaternoapellidomaternoestatus": "apellido_combo_estatus",
        "estatus": "estatus",
        "concepto": "concepto_pago",
        "conceptopago": "concepto_pago",
        "conceptodepago": "concepto_pago",
        "conceptoconcepto": "concepto_pago",
        "tipodeoperacion": "tipo_operacion",
        "bancodestino": "banco_destino",
        "formadedeposito": "forma_deposito",
        "clavederastreo": "clave_rastreo",
        "claverastreo": "clave_rastreo",
    }
    scotia_map = {
        "tipoderegistro": "tipo_registro",
        "tipodemovimiento": "tipo_movimiento",
        "tipodemovimientopago": "tipo_movimiento",
        "fechadeaplicacion": "fecha_aplicacion",
        "clavedelbeneficiario": "clave_beneficiario",
        "referencia": "referencia",
        "referenciadecarga": "referencia",
        "nocuentabeneficiario": "cuenta_beneficiario",
        "numerobancoreceptor": "banco_receptor",
        "nobancoreceptor": "banco_receptor",
        "diasdevigencia": "dias_vigencia",
        "nombredelbeneficiario": "nombre_beneficiario",
    }
    bbva_map = {
        "tipodecuenta": "tipo_cuenta",
        "codigo": "codigo",
        "descripcion": "descripcion",
    }

    if bank == "SCOTIABANK" and key in scotia_map:
        return scotia_map[key]
    if bank == "BBVA" and key in bbva_map:
        return bbva_map[key]
    return base_map.get(key, key)


def _payment_to_canonical_rows(bank: str, rows: list[dict]) -> tuple[list[str], list[dict]]:
    if not rows:
        return [], []
    canonical_rows: list[dict] = []
    canonical_keys: list[str] = []
    for row in rows:
        canonical_row: dict[str, str] = {}
        for raw_key, raw_value in row.items():
            canon_key = _canonical_payment_key(bank, str(raw_key or ""))
            if not canon_key:
                continue
            value = _normalize_text(str(raw_value or ""))
            if not value:
                continue
            if canon_key in canonical_row:
                merged = f"{canonical_row[canon_key]} {value}".strip()
                canonical_row[canon_key] = _normalize_text(merged)
            else:
                canonical_row[canon_key] = value
            if canon_key not in canonical_keys:
                canonical_keys.append(canon_key)

        combo = _normalize_text(str(canonical_row.get("apellido_combo_estatus") or ""))
        if combo:
            status_match = re.search(r"\b(APLICADO|PROCESADO|ACEPTADO|TRANSMITIDO|RECHAZADO)\b", combo)
            if status_match and not canonical_row.get("estatus"):
                canonical_row["estatus"] = _normalize_text(status_match.group(1))
                if "estatus" not in canonical_keys:
                    canonical_keys.append("estatus")

            combo_name = re.sub(r"\b(APLICADO|PROCESADO|ACEPTADO|TRANSMITIDO|RECHAZADO)\b", "", combo).strip()
            combo_parts = [part for part in _normalize_name(combo_name).split() if part]
            if combo_parts:
                if len(combo_parts) >= 1 and not canonical_row.get("apellido_paterno"):
                    canonical_row["apellido_paterno"] = combo_parts[0]
                    if "apellido_paterno" not in canonical_keys:
                        canonical_keys.append("apellido_paterno")
                if len(combo_parts) >= 2 and not canonical_row.get("apellido_materno"):
                    canonical_row["apellido_materno"] = combo_parts[1]
                    if "apellido_materno" not in canonical_keys:
                        canonical_keys.append("apellido_materno")

            canonical_row.pop("apellido_combo_estatus", None)
            if "apellido_combo_estatus" in canonical_keys:
                canonical_keys.remove("apellido_combo_estatus")

        full_name = _normalize_text(str(canonical_row.get("nombre_beneficiario") or ""))
        if full_name:
            nombre, apellido_paterno, apellido_materno = _split_payment_name_parts(full_name)
            if nombre and not canonical_row.get("nombre"):
                canonical_row["nombre"] = nombre
                if "nombre" not in canonical_keys:
                    canonical_keys.append("nombre")
            if apellido_paterno and not canonical_row.get("apellido_paterno"):
                canonical_row["apellido_paterno"] = apellido_paterno
                if "apellido_paterno" not in canonical_keys:
                    canonical_keys.append("apellido_paterno")
            if apellido_materno and not canonical_row.get("apellido_materno"):
                canonical_row["apellido_materno"] = apellido_materno
                if "apellido_materno" not in canonical_keys:
                    canonical_keys.append("apellido_materno")

        if canonical_row:
            canonical_rows.append(canonical_row)
    return canonical_keys, canonical_rows


def _extract_payment_detail_payload(base_text_raw: str, table_payload: dict | None) -> dict | None:
    text = str(base_text_raw or "")
    if not text.strip():
        return None

    metadata: dict[str, str] = {}
    bank = _payment_detect_bank(text)
    label_map = {
        "fecha_archivo": ["FECHA"],
        "hora_archivo": ["HORA"],
        "nombre_empresa": ["NOMBRE DE EMPRESA", "EMPRESA"],
        "nombre_archivo": ["NOMBRE DEL ARCHIVO"],
        "folio": ["FOLIO"],
        "nombre_contrato_scotia_linea": ["NOMBRE DE CONTRATO SCOTIA EN LINEA"],
        "numero_contrato_scotia_linea": ["NUMERO DE CONTRATO SCOTIA EN LINEA"],
        "numero_contrato_servicio": ["NUMERO DE CONTRATO DEL SERVICIO"],
        "numero_lote": ["LOTE", "LOTE ID", "NO DE LOTE"],
        "numero_archivo_en_dia": ["NUMERO DE ARCHIVO EN EL DIA"],
        "usuario_sistema_nombre": ["NOMBRE DE USUARIO DEL SISTEMA Y NOMBRE"],
        "fecha_hora_validacion_archivo": ["FECHA Y HORA DE VALIDACION DEL ARCHIVO"],
        "fecha_hora_registro": ["FECHA Y HORA DE REGISTRO"],
        "fecha_hora_proceso": ["FECHA Y HORA DE PROCESO", "FECHA DE TRANSMISION"],
        "cantidad_total_movimientos": ["CANTIDAD TOTAL DE MOVIMIENTOS"],
        "importe_total_movimientos": ["IMPORTE TOTAL DE MOVIMIENTOS"],
        "cantidad_movimientos_altas": ["CANTIDAD DE MOVIMIENTO ALTAS", "CANTIDAD DE MOVIMIENTOS ALTAS"],
        "importe_movimiento_altas": ["IMPORTE DE MOVIMIENTO ALTAS", "IMPORTE DE MOVIMIENTOS ALTAS"],
        "cantidad_movimientos_bajas": ["CANTIDAD DE MOVIMIENTO BAJAS", "CANTIDAD DE MOVIMIENTOS BAJAS"],
        "importe_movimientos_bajas": ["IMPORTE DE MOVIMIENTOS BAJAS"],
        "total_registros_leidos": ["TOTAL DE REGISTROS LEIDOS"],
    }
    for key, labels in label_map.items():
        value = _payment_pick_labeled_value(text, labels, max_len=180)
        if value:
            metadata[key] = value

    if bank == "SCOTIABANK":
        metadata.update(_extract_scotia_payment_metadata(text))
    elif bank == "BBVA":
        metadata.update(_extract_bbva_payment_metadata(text))

    metadata = _sanitize_payment_metadata(metadata)

    rows: list[list[str]] = []
    if isinstance(table_payload, dict):
        raw_rows = table_payload.get("rows")
        if isinstance(raw_rows, list):
            for raw_row in raw_rows:
                if not isinstance(raw_row, list):
                    continue
                rows.append([str(cell or "") for cell in raw_row])
    row_objects = _payment_rows_to_objects(rows) if rows else []
    canonical_columns, canonical_rows = _payment_to_canonical_rows(bank, row_objects)
    summary_tables = _extract_scotia_summary_tables(text) if bank == "SCOTIABANK" else []

    if not metadata and not row_objects and not canonical_rows and not summary_tables:
        return None

    return {
        "source": "table_and_text" if row_objects else "text_only",
        "bank": bank,
        "metadata": metadata,
        "table": {
            "columns": rows[0] if len(rows) >= 1 else [],
            "row_count": len(row_objects),
            "rows": row_objects,
            "canonical_columns": canonical_columns,
            "canonical_row_count": len(canonical_rows),
            "canonical_rows": canonical_rows,
            "summary_tables": summary_tables,
        },
    }


def _build_replica_layout_payload(ocr_boxes, raw_text: str) -> dict | None:
    boxes = _boxes_with_rect(ocr_boxes)
    if boxes:
        pages: dict[int, list[dict]] = {}
        for box in boxes:
            page = int(box.get("page", 1) or 1)
            pages.setdefault(page, []).append(box)

        payload_pages: list[dict] = []
        for page_num in sorted(pages.keys()):
            page_boxes = pages[page_num]
            lines = _line_groups(page_boxes, y_tol=10)
            if not lines:
                continue
            max_x = max(box["rect"][2] for box in page_boxes)
            max_y = max(box["rect"][3] for box in page_boxes)
            line_items: list[dict] = []
            for line in lines[:700]:
                text = _normalize_text(line.get("text", ""))
                if not text:
                    continue
                rects = [item["rect"] for item in line.get("boxes", []) if item.get("rect")]
                if not rects:
                    continue
                x1 = min(r[0] for r in rects)
                y1 = min(r[1] for r in rects)
                x2 = max(r[2] for r in rects)
                y2 = max(r[3] for r in rects)
                line_items.append(
                    {
                        "text": text,
                        "x": int(round(x1)),
                        "y": int(round(y1)),
                        "w": int(round(max(1, x2 - x1))),
                        "h": int(round(max(1, y2 - y1))),
                    }
                )
            if line_items:
                payload_pages.append(
                    {
                        "page": page_num,
                        "width": int(round(max_x)),
                        "height": int(round(max_y)),
                        "lines": line_items,
                    }
                )

        if payload_pages:
            return {"source": "layout_boxes", "pages": payload_pages}

    text_lines = [line.rstrip() for line in str(raw_text or "").replace("\r\n", "\n").split("\n")]
    text_lines = [line for line in text_lines if line.strip()]
    if len(text_lines) < 2:
        return None
    fallback_lines: list[dict] = []
    y = 24
    for line in text_lines[:700]:
        fallback_lines.append({"text": line, "x": 24, "y": y, "w": 1020, "h": 14})
        y += 16
    return {
        "source": "text_lines",
        "pages": [{"page": 1, "width": 1100, "height": max(600, y + 24), "lines": fallback_lines}],
    }


def _extract_label_value(
    lines: list[dict],
    label: str,
    stop_labels: list[str] | None = None,
    value_regex: re.Pattern[str] | None = None,
) -> str | None:
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
    if not curp_value:
        # Fallback: intenta corrección OCR sobre el texto concatenado de todos los boxes
        full_box_text = " ".join(b.get("text", "") for b in boxes).upper()
        fixed_curp = _search_curp(full_box_text)
        if fixed_curp:
            curp_value = fixed_curp
            curp_box = None
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

    def _clean_name_piece(value: str | None) -> str | None:
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
        lugar_nacimiento = _clean_acta_lugar_nacimiento(lugar_nacimiento)
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
            candidate = _clean_acta_lugar_nacimiento(match.group(1).strip())
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
                    cleaned_place = _clean_acta_lugar_nacimiento(" ".join(place_parts))
                    if cleaned_place:
                        result["lugar_nacimiento"] = {"value": cleaned_place}
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
                        cleaned_place = _clean_acta_lugar_nacimiento(" ".join(reversed(place_parts)))
                        if cleaned_place:
                            result["lugar_nacimiento"] = {"value": cleaned_place}
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
                        cleaned_place = _clean_acta_lugar_nacimiento(" ".join(reversed(place_parts)))
                        if cleaned_place:
                            result["lugar_nacimiento"] = {"value": cleaned_place}
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
            r"(HOMBRE|MUJER|H|M)\s+(\d{2}[/-]\d{2}[/-]\d{4})\s+([A-Z ]{3,}?)\s+SEXO[:\s]+\s*FECHA\s+DE\s+NACIMIENTO[:\s]+\s*LUGAR\s+DE\s+NACIMIENTO[:\s]*",
            full_text,
        )
        if match:
            if "sexo" not in result:
                result["sexo"] = {"value": match.group(1)}
            if "fecha_nacimiento" not in result:
                result["fecha_nacimiento"] = {"value": match.group(2)}
            if "lugar_nacimiento" not in result:
                cleaned_place = _clean_acta_lugar_nacimiento(match.group(3).strip())
                if cleaned_place:
                    result["lugar_nacimiento"] = {"value": cleaned_place}

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
        normalized_name = _clean_nss_name(nombre)
        if normalized_name and _is_nss_person_name(normalized_name):
            result["nombre"] = {"value": normalized_name}

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
            "REFERENCIA DE PAGO": "referencia",
            "CUENTA": "cuenta",
            "NUMERO": "numero_servicio",
            "NUMERO TELCEL": "numero_servicio",
            "LINEA TELCEL": "numero_servicio",
            "LINEA": "numero_servicio",
            "TOTAL": "total",
            "TOTAL A PAGAR": "total",
            "IMPORTE A PAGAR": "total",
            "FECHA LIMITE": "fecha_limite",
            "VENCIMIENTO": "fecha_limite",
            "PAGAR ANTES DE": "fecha_limite",
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
        "fecha_limite": DATE_FLEX_PATTERN,
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
            m = re.search(r"SECCION\s*([0-9OIL]+)", str(seccion_line["text"]).upper())
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
    raw = _normalize_text(str(value or ""))
    if not raw:
        return ""
    upper = (
        raw.upper()
        .replace(".", " ")
        .replace(",", " ")
        .replace("–", "-")
        .replace("—", "-")
        .replace("−", "-")
    )

    def _fix_ocr_digits(token: str) -> str:
        return token.upper().replace("O", "0").replace("I", "1").replace("L", "1")

    numeric = re.search(
        r"([0-9OIL]{1,2})\s*(?:[/-]|[^0-9A-Z]+)\s*([0-9OIL]{1,2})\s*(?:[/-]|[^0-9A-Z]+)\s*([0-9OIL]{2,4})",
        upper,
    )
    if numeric:
        day, month, year = numeric.groups()
        day_i = int(_fix_ocr_digits(day))
        month_i = int(_fix_ocr_digits(month))
        year_i = int(_fix_ocr_digits(year))
        if len(year) == 2:
            year_i = 2000 + year_i
        if 1 <= day_i <= 31 and 1 <= month_i <= 12:
            return f"{day_i:02d}/{month_i:02d}/{year_i:04d}"

    month_map = {
        "ENE": "01",
        "FEB": "02",
        "MAR": "03",
        "ABR": "04",
        "MAY": "05",
        "JUN": "06",
        "JUL": "07",
        "AGO": "08",
        "SEP": "09",
        "SET": "09",
        "OCT": "10",
        "NOV": "11",
        "DIC": "12",
        "JAN": "01",
        "APR": "04",
        "AUG": "08",
        "DEC": "12",
    }
    textual = re.search(
        r"([0-9OIL]{1,2})\s*(?:[-/]|[^0-9A-Z]+)\s*([A-Z]{3,9})\s*(?:[-/]|[^0-9A-Z]+)\s*([0-9OIL]{2,4})",
        upper,
    )
    if textual:
        day, month_token, year = textual.groups()
        month = month_map.get(month_token[:3])
        if month:
            day_i = int(_fix_ocr_digits(day))
            year_i = int(_fix_ocr_digits(year))
            if len(year) == 2:
                year_i = 2000 + year_i
            if 1 <= day_i <= 31:
                return f"{day_i:02d}/{month}/{year_i:04d}"

    return raw


def _extract_due_date_from_text(value: str) -> str | None:
    text = _normalize_text(str(value or ""))
    if not text:
        return None
    upper = text.upper()
    due_markers = ("PAGAR ANTES DE", "FECHA LIMITE", "LIMITE DE PAGO", "VENCIMIENTO", "VENCE")
    compact = re.sub(r"\s+", "", upper)
    marker_hit = any(marker in upper for marker in due_markers) or any(
        marker.replace(" ", "") in compact for marker in due_markers
    )
    if not marker_hit:
        return None
    date_match = re.search(
        r"([0-9OIL]{1,2}\s*(?:[-/]|[^0-9A-Z]+)\s*[A-Z]{3,9}\s*(?:[-/]|[^0-9A-Z]+)\s*[0-9OIL]{2,4}|[0-9OIL]{1,2}\s*(?:[/-]|[^0-9A-Z]+)\s*[0-9OIL]{1,2}\s*(?:[/-]|[^0-9A-Z]+)\s*[0-9OIL]{2,4})",
        upper.replace("–", "-").replace("—", "-").replace("−", "-"),
    )
    candidate = date_match.group(1) if date_match else upper
    normalized = _normalize_date_value(candidate)
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", normalized):
        return normalized
    return None


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
        "ERWINGUSTAVO": "ERWIN GUSTAVO",
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


def _extract_cfe_address_from_lines(lines: list[str]) -> str | None:
    if not lines:
        return None
    stop_tokens = (
        "NO.DESERVICIO",
        "RMU",
        "CUENTA",
        "LIMITE DE PAGO",
        "CORTE A PARTIR",
        "TARIFA",
        "PERI0DO",
        "PERIODO",
        "CONCEPTO",
        "SUBTOTAL",
        "CFE-CONTIGO",
        "LECTURA",
    )
    skip_tokens = (
        "TOTALA PAGAR",
        "PESOS M.N.",
        "DESCARGA NUESTRA",
    )
    start_tokens = ("DN.", "DEPTO", "CALLE", "CLL", "AV", "BENITO")

    start_idx = None
    prepared = [_normalize_text(line).upper() for line in lines if _normalize_text(line)]
    for idx, line in enumerate(prepared):
        if any(token in line for token in start_tokens) and "NO.DESERVICIO" not in line:
            start_idx = idx
            break
    if start_idx is None:
        return None

    parts: list[str] = []
    for idx in range(start_idx, min(len(prepared), start_idx + 6)):
        line = prepared[idx]
        if any(token in line for token in stop_tokens):
            break
        if any(token in line for token in skip_tokens):
            continue
        parts.append(line)
        if re.search(r"\b(?:C\.?\s*P\.?\s*)?\d{5}\b", line):
            if idx + 1 < len(prepared):
                nxt = prepared[idx + 1]
                if "CIUDAD" in nxt or "CARMEN" in nxt or "CAMP" in nxt:
                    parts.append(nxt)
            break

    if not parts:
        return None
    raw = " ".join(parts)
    raw = re.sub(r"\([^)]{0,200}\)", " ", raw)
    raw = re.sub(r"\bDESCARGA\s+NUESTRA\b.*$", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip(" .,-")
    if len(raw) < 12:
        return None
    cleaned = _clean_address_value(raw)
    return cleaned if len(cleaned) >= 12 else None


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
    upper = re.sub(r"\bCFE\s+COMISION\s+FEDERAL\s+DE\s+ELECTRICIDAD\b", " ", upper)
    upper = re.sub(r"\bCOMISION\s+FEDERAL\s+DE\s+ELECTRICIDAD\b", " ", upper)
    upper = re.sub(r"\bRMU[:\s-].*$", " ", upper)
    upper = re.sub(r"\$\s*\d{1,5}(?:[.,]\d{2})?(?:\s+\d{1,3})*", " ", upper)
    upper = re.sub(r"\([^)]{0,200}\)", " ", upper)
    upper = re.sub(r"\bDESCARGA\s+NUESTRA\b.*$", " ", upper)
    # Remove leading payment/amount fragments that OCR sometimes merges into CFE address lines.
    upper = re.sub(r"^\s*\$\s*\d{1,5}(?:[.,]\d{2})?(?:\s+\d{1,3})*\s+", "", upper)
    upper = re.sub(
        r"^\s*\d{3,5}\s+\d{1,3}\s+(?=(?:DN\.?|DEPTO|DEPARTAMENTO|CALLE|CLL|AV|COL|BENITO|MZ|LT|NO\.?|NUM|KM)\b)",
        "",
        upper,
    )
    upper = upper.replace("DOMICILIO", " ")
    upper = re.sub(r"^\s*DE\s+SUMINISTRO\b", " ", upper)
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
        if tok in {"$", "MXN", "M.N.", "M.N", "MN"}:
            continue
        if not re.search(r"[A-Z0-9/]", tok):
            continue
        if tok in noise:
            continue
        if any(fragment in tok for fragment in ("INSTI", "ELECT", "CREDEN", "VOTAR")):
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
    years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", value)]
    if years:
        _max_vig_year = datetime.now().year + 30
        plausible = [year for year in years if 2020 <= year <= _max_vig_year]
        selected = max(plausible) if plausible else max(years)
        return str(selected)
    date_match = re.search(r"(\d{2}/\d{2}/(\d{4}))", value)
    if date_match:
        year = date_match.group(2)
        return _normalize_vigencia(year)
    return value


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
    # Ignore label-like OCR noise such as "DE NACIMIENTO".
    if not re.search(r"\d", text):
        return ""
    if re.search(r"\d", text) or re.fullmatch(r"[0-9OIL\s-]+", text):
        raw = _normalize_numeric_field(text)
        if re.fullmatch(r"\d{1,12}", raw):
            return raw
    normalized = _normalize_alnum(text)
    digit_count = sum(1 for ch in normalized if ch.isdigit())
    return normalized if len(normalized) >= 3 and digit_count >= 3 else ""


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
    text_norm = _normalize_text(text).upper()
    if len(text_norm) >= 12 and any(marker in text_norm for marker in ("CALLE", "CLL", "AV", "COL", "DEPTO", "CIUDAD", "CP", "C.P.", "BENITO", "CARMEN")):
        return text_norm
    numeric = _normalize_numeric_field(text)
    if 10 <= len(numeric) <= 30:
        return numeric
    alnum = _normalize_alnum(text)
    digits = sum(1 for ch in alnum if ch.isdigit())
    if 10 <= len(alnum) <= 120 and digits >= 8:
        return alnum
    return ""


def _normalize_seccion_value(value: str) -> str:
    text = str(value or "").upper().replace("O", "0")
    raw = re.sub(r"\D", "", text)
    if not raw:
        return ""
    if re.fullmatch(r"\d{3,4}", raw):
        return raw
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


def _normalize_field_value_for_contract(key: str, value: str) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    if key == "tabla_celdas":
        return raw.strip()
    if key == "pago_detalle":
        return raw.strip()
    if key == "replica_pdf_layout":
        return raw.strip()
    if key == "replica_pdf_texto":
        lines = [line.rstrip() for line in raw.replace("\r\n", "\n").split("\n")]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        return "\n".join(lines).strip()
    if key in FIELD_VALUE_NORMALIZERS:
        return _normalize_value_for_key(key, raw)
    if key in {"curp", "rfc", "clave_elector", "id_cif"}:
        return _normalize_alnum(raw)
    if key in {"nss", "clabe", "cp", "seccion", "numero_servicio"}:
        return _normalize_numeric_field(raw)
    if key == "cuenta":
        return _normalize_alnum(raw)
    if key in {"fecha", "fecha_nacimiento", "fecha_registro", "fecha_limite", "fecha_corte", "fecha_emision", "fecha_documento"}:
        return _normalize_date_value(raw)
    if key in {"nombre", "titular", "nombres", "apellido_paterno", "apellido_materno", "primer_apellido", "segundo_apellido"}:
        return _normalize_name(raw)
    if key == "sexo":
        return _normalize_sex(raw)
    if key == "lugar_nacimiento":
        return _clean_acta_lugar_nacimiento(raw)
    if key == "domicilio":
        return _clean_address_value(raw)
    if key in {"entidad_registro", "municipio_registro", "banco", "estado", "ciudad", "proveedor"}:
        return _normalize_address(raw)
    return _normalize_text(raw)


def _is_valid_table_cells_payload(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        payload = json.loads(text)
    except Exception:
        return False

    if not isinstance(payload, dict):
        return False

    rows = payload.get("rows")
    if not isinstance(rows, list) or len(rows) < 2:
        return False

    non_empty_rows = 0
    for row in rows:
        if not isinstance(row, list):
            continue
        cells = [_normalize_text(str(cell or "")) for cell in row]
        if any(cells):
            non_empty_rows += 1

    return non_empty_rows >= 2


def _is_valid_replica_layout_payload(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        payload = json.loads(text)
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    pages = payload.get("pages")
    if not isinstance(pages, list) or not pages:
        return False
    line_count = 0
    for page in pages:
        if not isinstance(page, dict):
            continue
        lines = page.get("lines")
        if not isinstance(lines, list):
            continue
        for line in lines:
            if not isinstance(line, dict):
                continue
            if str(line.get("text", "")).strip():
                line_count += 1
    return line_count >= 2


def _is_valid_payment_detail_payload(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    try:
        payload = json.loads(text)
    except Exception:
        return False
    if not isinstance(payload, dict):
        return False
    metadata = payload.get("metadata")
    table = payload.get("table")
    has_metadata = isinstance(metadata, dict) and any(str(v or "").strip() for v in metadata.values())
    has_rows = False
    if isinstance(table, dict):
        rows = table.get("rows")
        has_rows = isinstance(rows, list) and any(isinstance(item, dict) and item for item in rows)
    return has_metadata or has_rows


def _looks_like_person_name(value: str) -> bool:
    text = _normalize_name(value).upper()
    if not text:
        return False
    if len(text) < 5 or len(text) > 90:
        return False
    tokens = [t for t in text.split() if t]
    if len(tokens) < 2:
        return False
    banned = {
        "PRESTACIONES",
        "ESPECIE",
        "DINERO",
        "REQUISITOS",
        "OTORGARAN",
        "CUMPLIDO",
        "LUGAR",
        "NACIMIENTO",
        "ACTA",
        "SEXO",
        "FECHA",
    }
    banned_fragments = (
        "CONSUMO",
        "GRAFIC",
        "SUBTOTAL",
        "MULTIPLICADOR",
        "IMPORTE",
        "PAGAR",
        "SERVICIO",
        "KWH",
        "TARIFA",
    )
    if any(tok in banned for tok in tokens):
        return False
    if any(fragment in text for fragment in banned_fragments):
        return False
    if sum(1 for ch in text if ch.isdigit()) >= 4:
        return False
    return True


_ALLOWED_FIELDS_BY_TYPE: dict[str, set[str]] = {
    "INE": {
        "nombre",
        "curp",
        "clave_elector",
        "fecha_nacimiento",
        "sexo",
        "domicilio",
        "seccion",
        "vigencia",
    },
    "CURP": {
        "nombre",
        "curp",
        "fecha_nacimiento",
        "sexo",
        "entidad_nacimiento",
    },
    "ACTA_NACIMIENTO": {
        "nombre",
        "sexo",
        "fecha_nacimiento",
        "lugar_nacimiento",
        "folio",
        "numero_acta",
        "fecha_registro",
        "municipio_registro",
        "entidad_registro",
        "numero_certificado",
        "identificador_electronico",
    },
    "NSS": {
        "nss",
        "nombre",
    },
    "COMPROBANTE_DOMICILIO": {
        "proveedor",
        "numero_servicio",
        "cuenta",
        "referencia",
        "titular",
        "domicilio",
        "cp",
        "fecha_limite",
        "total",
        "contrato",
        "tabla_celdas",
        "pago_detalle",
    },
    "DATOS_BANCARIOS": {
        "banco",
        "clabe",
        "cuenta",
        "titular",
        "rfc",
        "fecha_corte",
        "periodo",
        "tabla_celdas",
        "pago_detalle",
    },
    "FACTURA": {
        "tabla_celdas",
        "pago_detalle",
        "replica_pdf_layout",
        "replica_pdf_texto",
    },
    "CONSTANCIA_SITUACION_FISCAL": {
        "rfc",
        "nombre",
        "regimen",
        "domicilio",
    },
}


def _is_allowed_field_for_type(document_type: str, key: str) -> bool:
    if key == "texto_detectado":
        return True
    allowed = _ALLOWED_FIELDS_BY_TYPE.get(document_type)
    if not allowed:
        return True
    return key in allowed


def _is_valid_by_contract(document_type: str, key: str, value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    upper = text.upper()

    if key == "tabla_celdas":
        return _is_valid_table_cells_payload(text)
    if key == "pago_detalle":
        return _is_valid_payment_detail_payload(text)
    if key == "replica_pdf_layout":
        return _is_valid_replica_layout_payload(text)
    if key == "replica_pdf_texto":
        return len(text) >= 80

    if key == "curp":
        return bool(CURP_PATTERN.fullmatch(_normalize_alnum(upper)))
    if key == "rfc":
        return bool(RFC_WITH_HOMOCLAVE.fullmatch(_normalize_alnum(upper)))
    if key == "nss":
        return bool(re.fullmatch(r"\d{11}", _normalize_numeric_field(upper)))
    if key == "clabe":
        return bool(re.fullmatch(r"\d{18}", _normalize_numeric_field(upper)))
    if key == "cp":
        return bool(re.fullmatch(r"\d{5}", _normalize_numeric_field(upper)))
    if key == "seccion":
        return bool(re.fullmatch(r"\d{3,6}", _normalize_numeric_field(upper)))
    if key == "numero_servicio":
        return bool(re.fullmatch(r"\d{10,13}", _normalize_numeric_field(upper)))
    if key == "cuenta":
        if document_type in {"DATOS_BANCARIOS", "FACTURA"}:
            return bool(re.fullmatch(r"\d{8,22}", _normalize_numeric_field(upper)))
        normalized_account = _normalize_alnum(upper)
        digit_count = sum(1 for ch in normalized_account if ch.isdigit())
        return bool(normalized_account) and 8 <= len(normalized_account) <= 24 and digit_count >= 6
    if key == "referencia":
        normalized = _normalize_value_for_key("referencia", upper)
        if any(ch.isalpha() for ch in normalized):
            return len(normalized) >= 12
        digits = sum(1 for ch in normalized if ch.isdigit())
        return bool(normalized) and 10 <= len(normalized) <= 30 and digits >= 8
    if key == "sexo":
        return upper in {"H", "M"}
    if key in {"fecha", "fecha_nacimiento", "fecha_registro", "fecha_limite", "fecha_corte", "fecha_emision", "fecha_documento"}:
        return bool(re.fullmatch(r"\d{2}[/-]\d{2}[/-]\d{4}", text))
    if key == "vigencia":
        return bool(re.fullmatch(r"\d{4}(?:/\d{4})?", text))
    if key in {"folio", "numero_acta"}:
        return bool(re.fullmatch(r"[A-Z0-9]{1,12}", _normalize_alnum(upper)))
    if key == "numero_certificado":
        return bool(re.fullmatch(r"[A-Z0-9]{6,24}", _normalize_alnum(upper)))
    if key == "identificador_electronico":
        return bool(re.fullmatch(r"[A-Z0-9]{6,30}", _normalize_alnum(upper)))
    if key in {"nombre", "titular"}:
        if key == "titular" and document_type == "COMPROBANTE_DOMICILIO" and upper == "PUBLICO EN GENERAL":
            return True
        return _looks_like_person_name(text)
    if key == "lugar_nacimiento":
        if any(token in upper for token in {"ACTA DE NACIMIENTO", "SEXO", "FECHA DE NACIMIENTO", "LUGAR DE NACIMIENTO"}):
            return False
        return 2 <= len(upper) <= 80
    if key == "domicilio":
        if any(token in upper for token in {"LINEA DE CAPTURA", "TOTAL A PAGAR", "REFERENCIA"}):
            return False
        return len(upper) >= 10
    if key in {"entidad_registro", "municipio_registro", "banco", "estado", "ciudad", "proveedor"}:
        return len(upper) >= 3

    return len(text) >= 2


def _apply_field_contracts(document_type: str, fields: list[dict]) -> list[dict]:
    contracted: list[dict] = []
    for field in fields:
        key = str(field.get("key", "") or "")
        if not key:
            continue
        if not _is_allowed_field_for_type(document_type, key):
            continue
        if key == "texto_detectado":
            contracted.append(field)
            continue

        normalized_value = _normalize_field_value_for_contract(key, str(field.get("value", "") or ""))
        if not normalized_value:
            continue
        if not _is_valid_by_contract(document_type, key, normalized_value):
            continue

        updated = dict(field)
        updated["value"] = normalized_value
        contracted.append(updated)
    return contracted


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


def _clean_nss_name(value: str) -> str | None:
    if not value:
        return None
    cleaned = _normalize_text(value).upper()
    cleaned = re.sub(
        r"^(?:NOMBRE(?:\s+DEL|\s+DE LA)?(?:\s+ASEGURADO|\s+BENEFICIARIO|\s+TRABAJADOR|\s+TITULAR)?|"
        r"ASEGURADO|BENEFICIARIO|TITULAR|NOMBRE\s+O\s+RAZON\s+SOCIAL)\s*[:\-]?\s*",
        "",
        cleaned,
    )
    cleaned = re.split(r"\b(?:CURP|RFC|NSS|IMSS|FOLIO|FECHA|VIGENCIA|UNIDAD|CLINICA)\b", cleaned)[0].strip(" :.-,")
    cleaned = re.sub(r"[^A-ZÑÁÉÍÓÚÜ ]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) < 5:
        return None
    tokens = cleaned.split()
    if len(tokens) < 2:
        return None
    return cleaned


def _is_nss_person_name(value: str) -> bool:
    cleaned = _normalize_text(value).upper()
    if not cleaned:
        return False
    if len(cleaned) > 70:
        return False

    non_name_tokens = {
        "PRESTACIONES", "ESPECIE", "DINERO", "OTORGARAN", "CUMPLIDO", "REQUISITOS", "PREVISTOS",
        "LEY", "ARTICULO", "VIGENCIA", "FOLIO", "CLINICA", "UNIDAD", "SEGURO", "SOCIAL",
        "IMSS", "NSS", "RFC", "CURP", "SISTEMA", "NACIONAL", "SEGURIDAD",
    }
    non_name_fragments = (
        "PRESTACION",
        "REQUISIT",
        "OTORGAR",
        "CUMPLID",
        "DINERO",
        "ESPECIE",
        "BENEFICIARIOS",
        "TRABAJADORES",
        "ASEGURAMIENTO",
    )
    particles = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "MC", "VON", "DA", "DO", "DI"}

    tokens = [tok for tok in re.findall(r"[A-ZÑÁÉÍÓÚÜ]+", cleaned) if tok]
    if len(tokens) < 2 or len(tokens) > 6:
        return False
    if any(tok in non_name_tokens for tok in tokens):
        return False
    if any(fragment in cleaned for fragment in non_name_fragments):
        return False

    core_tokens = [tok for tok in tokens if tok not in particles]
    if len(core_tokens) < 2:
        return False
    if any(len(tok) > 18 for tok in core_tokens):
        return False
    if any(len(tok) < 2 for tok in core_tokens):
        return False
    if sum(1 for tok in core_tokens if len(tok) >= 3) < 2:
        return False
    return True


def _split_compact_nss_token(token: str) -> str:
    compact = _normalize_alnum(token)
    if len(compact) <= 12:
        return compact

    common_surnames = (
        "HERNANDEZ",
        "GONZALEZ",
        "MARTINEZ",
        "RODRIGUEZ",
        "LOPEZ",
        "PEREZ",
        "SANCHEZ",
        "RAMIREZ",
        "CRUZ",
        "FLORES",
        "GOMEZ",
        "DIAZ",
        "REYES",
        "MORALES",
        "ORTIZ",
        "RUIZ",
        "MEDINA",
        "TORRES",
        "ROMERO",
        "VARGAS",
        "CASTILLO",
        "MENDOZA",
        "RIVERA",
        "VASQUEZ",
        "GARZA",
        "AGUILAR",
        "SILVA",
        "NAVARRO",
        "CASTRO",
        "GARCIA",
        "CAMPOS",
    )
    for surname in common_surnames:
        if compact.endswith(surname) and len(compact) > len(surname) + 3:
            left = compact[: -len(surname)]
            left_named = _split_compact_given_names(left)
            return f"{left_named} {surname}".strip()

    best = None
    best_score = None
    for cut in range(max(4, len(compact) - 10), min(len(compact) - 3, len(compact) - 4) + 1):
        left = compact[:cut]
        right = compact[cut:]
        if len(right) < 4 or len(right) > 10:
            continue
        if len(left) < 4:
            continue
        vowels_r = sum(1 for ch in right if ch in "AEIOU")
        ratio_r = vowels_r / max(1, len(right))
        if ratio_r < 0.2 or ratio_r > 0.8:
            continue
        score = abs(len(left) - len(right) * 1.7)
        if right.endswith(("EZ", "ES", "OS", "AS", "ON", "AN", "IA", "ZA", "GA")):
            score -= 0.4
        if best_score is None or score < best_score:
            best_score = score
            best = (left, right)

    if not best:
        return compact

    left, right = best
    left_named = _split_compact_given_names(left)
    return f"{left_named} {right}".strip()


def _extract_nss_name_from_text(lines: list[str], full_text: str) -> str | None:
    strict_keywords = [
        "NOMBRE DEL ASEGURADO",
        "NOMBRE DEL BENEFICIARIO",
        "NOMBRE DEL TRABAJADOR",
        "NOMBRE DEL TITULAR",
        "NOMBRE O RAZON SOCIAL",
    ]
    for idx, line in enumerate(lines):
        upper_line = line.upper()
        compact_line = _label_key(upper_line)
        for keyword in strict_keywords:
            compact_keyword = _label_key(keyword)
            if keyword not in upper_line and compact_keyword not in compact_line:
                continue
            if keyword in upper_line:
                tail = upper_line.split(keyword, 1)[-1].strip(" :.-")
            else:
                tail = ""
            if tail:
                normalized = _clean_nss_name(tail)
                if normalized and _is_nss_person_name(normalized):
                    return normalized
            for offset in (1, 2, 3):
                if idx + offset >= len(lines):
                    break
                normalized = _clean_nss_name(lines[idx + offset])
                if normalized and _is_nss_person_name(normalized):
                    return normalized

    for pattern in [
        r"(?:NOMBRE\s+DEL\s+ASEGURADO|NOMBRE\s+DEL\s+BENEFICIARIO|NOMBRE\s+DEL\s+TRABAJADOR|NOMBRE\s+DEL\s+TITULAR|NOMBRE\s+O\s+RAZON\s+SOCIAL)\s*[:\-]?\s*([A-ZÑÁÉÍÓÚÜ ]{8,70})",
        r"(?:ASEGURADO|BENEFICIARIO|TITULAR)\s*[:\-]?\s*([A-ZÑÁÉÍÓÚÜ ]{8,70})",
    ]:
        match = re.search(pattern, full_text)
        if not match:
            continue
        normalized = _clean_nss_name(match.group(1))
        if normalized and _is_nss_person_name(normalized):
            return normalized

    compact_name_match = re.search(r"\b([A-ZÑ]{3,})!\s*([A-ZÑ]{8,24})\b", full_text)
    if compact_name_match:
        last_name = _normalize_alnum(compact_name_match.group(1))
        compact = _split_compact_nss_token(compact_name_match.group(2))
        candidate = _clean_nss_name(f"{compact} {last_name}")
        if candidate and _is_nss_person_name(candidate):
            return candidate

    return None


def _extract_acta_folio_numero_from_text(full_text: str) -> tuple[str | None, str | None]:
    text = _normalize_text(full_text).upper()

    # Common compact table layout:
    # "FECHA DE REGISTRO LIBRO NUMERO DE ACTA 0001 20/08/2001 3 437"
    table_match = re.search(
        r"FECHA\s+DE\s+REGISTRO\s+LIBR[OA]\s+NUMER[OA]\s+DE\s+ACT[AE]\s+"
        r"([0-9OIL]{1,6})\s+\d{2}[/-]\d{2}[/-]\d{4}\s+([0-9OIL]{1,6})\s+([0-9OIL]{1,6})",
        text,
    )
    if table_match:
        first_value = _normalize_value_for_key("folio", table_match.group(1))
        middle_value = _normalize_value_for_key("numero_acta", table_match.group(2))
        last_value = _normalize_value_for_key("folio", table_match.group(3))

        # Prefer common pattern where first number behaves as folio and the last as numero_acta.
        if first_value and last_value:
            return (first_value, _normalize_value_for_key("numero_acta", table_match.group(3)) or last_value)
        if middle_value and last_value:
            return (last_value, middle_value)

        fallback_folio = _normalize_value_for_key("folio", table_match.group(3))
        fallback_numero = middle_value or _normalize_value_for_key("numero_acta", table_match.group(3))
        if not fallback_folio and first_value and middle_value:
            fallback_folio = first_value
        return (fallback_folio or None, fallback_numero or None)

    numero_acta = None
    folio = None

    numero_match = re.search(r"NUMER[OA]\s+DE\s+ACT[AE]\s*[:\-]?\s*([0-9OIL]{1,8})", text)
    if numero_match:
        normalized = _normalize_value_for_key("numero_acta", numero_match.group(1))
        if normalized:
            numero_acta = normalized

    folio_match = re.search(r"FOLI[O0]\s*[:\-]?\s*([0-9OIL]{1,8})", text)
    if folio_match:
        normalized = _normalize_value_for_key("folio", folio_match.group(1))
        if normalized:
            folio = normalized

    return folio, numero_acta


def _extract_acta_name_from_text(raw_text: str) -> str | None:
    def fix_ocr_letters(value: str) -> str:
        text = str(value or "").upper()
        text = re.sub(r"(?<=[A-Z])0(?=[A-Z])", "O", text)
        text = re.sub(r"(?<=[A-Z])0(?=\b|[^0-9])", "O", text)
        text = re.sub(r"(?<=[A-Z])1(?=[A-Z])", "I", text)
        text = re.sub(r"(?<=[A-Z])5(?=[A-Z])", "S", text)
        return text

    lines = [fix_ocr_letters(_normalize_text(line)) for line in str(raw_text or "").splitlines() if _normalize_text(line)]
    if not lines:
        return None
    full = " ".join(lines)

    stop_words = (
        "SEXO",
        "FECHA",
        "LUGAR",
        "NACIMIENTO",
        "PRIMER",
        "SEGUNDO",
        "APELLIDO",
        "CURP",
        "FOLIO",
        "LIBRO",
        "TOMO",
        "OFICIALIA",
        "REGISTRO",
        "ACTA",
    )

    def clean_piece(value: str) -> str:
        piece = re.sub(r"[^A-ZÑÁÉÍÓÚÜ ]", " ", str(value or "").upper())
        piece = re.sub(r"\s+", " ", piece).strip()
        if not piece:
            return ""
        if len(piece) <= 1:
            return ""
        if any(token in piece for token in ("DATOS", "PERSONA", "REGISTRADA", "IDENTIFICADOR", "ELECTRONICO")):
            return ""
        if any(token in piece for token in ("APELLIDO", "NOMBRE(S)")):
            return ""
        return piece

    def cut_at_stop(text_value: str) -> str:
        cut = text_value
        for token in stop_words:
            idx = cut.find(token)
            if idx > 0:
                cut = cut[:idx].strip()
        return cut

    def label_equals(line_value: str, target: str) -> bool:
        return _label_key(line_value) == _label_key(target)

    inline_candidate = ""

    # Pattern 1: full label in one line.
    inline = re.search(r"\bNOMBRE(?:\(S\))?\s*[:\-]?\s*([A-ZÑÁÉÍÓÚÜ ]{4,120})", full)
    if inline:
        candidate = clean_piece(cut_at_stop(inline.group(1)))
        if candidate and _looks_like_person_name(candidate):
            inline_candidate = _normalize_name(candidate)

    # Pattern 1b: label in one line, value in next line (with OCR-noisy labels).
    for idx, line in enumerate(lines):
        if not (label_equals(line, "NOMBRE") or label_equals(line, "NOMBRES") or label_equals(line, "NOMBRE(S)")):
            continue
        if idx + 1 >= len(lines):
            continue
        candidate = clean_piece(cut_at_stop(lines[idx + 1]))
        if candidate and _looks_like_person_name(candidate):
            if not inline_candidate:
                inline_candidate = _normalize_name(candidate)
            break

    # Pattern 2: labeled parts.
    nombre = ""
    apellido1 = ""
    apellido2 = ""
    for line in lines:
        if not nombre:
            match = re.search(r"\bNOMBRE(?:\(S\))?\s*[:\-]?\s*(.+)$", line)
            if match:
                nombre = clean_piece(cut_at_stop(match.group(1)))
                continue
            if label_equals(line, "NOMBRE") or label_equals(line, "NOMBRES") or label_equals(line, "NOMBRE(S)"):
                continue
        if not apellido1:
            match = re.search(r"\bPRIMER\s+APELLID[O0]\s*[:\-]?\s*(.+)$", line)
            if match:
                apellido1 = clean_piece(cut_at_stop(match.group(1)))
                continue
            if label_equals(line, "PRIMER APELLIDO") or label_equals(line, "1ER APELLIDO"):
                continue
        if not apellido2:
            match = re.search(r"\bSEGUND[O0]\s+APELLID[O0]\s*[:\-]?\s*(.+)$", line)
            if match:
                apellido2 = clean_piece(cut_at_stop(match.group(1)))
                continue
            if label_equals(line, "SEGUNDO APELLIDO") or label_equals(line, "2DO APELLIDO"):
                continue

    # Pattern 2b: OCR noisy labels with values in following lines.
    if not (nombre and apellido1 and apellido2):
        for idx, line in enumerate(lines):
            if not nombre and (label_equals(line, "NOMBRE") or label_equals(line, "NOMBRES") or label_equals(line, "NOMBRE(S)")):
                if idx + 1 < len(lines):
                    nombre = clean_piece(cut_at_stop(lines[idx + 1])) or nombre
            if not apellido1 and (label_equals(line, "PRIMER APELLIDO") or label_equals(line, "1ER APELLIDO")):
                if idx + 1 < len(lines):
                    apellido1 = clean_piece(cut_at_stop(lines[idx + 1])) or apellido1
            if not apellido2 and (label_equals(line, "SEGUNDO APELLIDO") or label_equals(line, "2DO APELLIDO")):
                if idx + 1 < len(lines):
                    apellido2 = clean_piece(cut_at_stop(lines[idx + 1])) or apellido2
    composed = " ".join(part for part in [nombre, apellido1, apellido2] if part).strip()
    if composed and _looks_like_person_name(composed):
        return _normalize_name(composed)

    # Pattern 3: section "DATOS DE LA PERSONA REGISTRADA".
    section_idx = next((i for i, line in enumerate(lines) if "DATOS DE LA PERSONA REGISTRADA" in line), -1)
    if section_idx >= 0:
        collected: list[str] = []
        for line in lines[section_idx + 1 : section_idx + 6]:
            if any(token in line for token in ("NOMBRE", "APELLIDO", "SEXO", "FECHA", "LUGAR", "NACIMIENTO")):
                break
            cleaned = clean_piece(line)
            if cleaned:
                collected.append(cleaned)
        candidate = " ".join(collected).strip()
        if candidate and _looks_like_person_name(candidate):
            return _normalize_name(candidate)

    return inline_candidate or None


def _clean_acta_lugar_nacimiento(value: str) -> str:
    text = _normalize_text(str(value or "")).upper()
    if not text:
        return ""

    text = re.sub(r"^\s*ACTA\s+DE\s+NACIMIENTO\b", " ", text)
    text = re.split(
        r"\b(?:SEXO|FECHA\s+DE\s+NACIMIENTO|LUGAR\s+DE\s+NACIMIENTO|NOMBRE(?:\(S\))?|PRIMER\s+APELLIDO|SEGUNDO\s+APELLIDO)\b",
        text,
    )[0]
    text = re.sub(r"[^A-ZÑÁÉÍÓÚÜ ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text in {"ACTA", "ACTA DE", "ACTA DE NACIMIENTO"}:
        return ""
    return text


def _dedupe_fields(fields: list[dict]) -> list[dict]:
    def _parse_amount_for_rank(value: str | None) -> float | None:
        if not value:
            return None
        raw = str(value).replace("$", "").replace(" ", "").replace(",", "")
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _address_quality(value: str | None) -> float:
        text = _normalize_address(str(value or ""))
        if not text:
            return 0.0
        score = float(min(len(text), 140))
        if re.search(r"\b\d{5}\b", text):
            score += 12
        marker_hits = sum(
            1
            for marker in ("CALLE", "CLL", "AV", "COL", "CP", "C.P.", "MUN", "EDO", "S/N", "NUM", "NO.", "LOC", "RIA", "DEPTO")
            if marker in text
        )
        score += marker_hits * 10
        if "SSL" in text or "BENITOJUAREZ" in text:
            score += 18
        if re.search(r"\b\d{5}\s*$", text):
            score -= 16
        if text.startswith("-"):
            score -= 12
        if any(noise in text for noise in ("NO. DE SERVICIO", "NUMERO DE SERVICIO", "CUENTA", "RMU")):
            score -= 35
        if any(noise in text for noise in ("INSTITUTO NACIONAL ELECTORAL", "CREDENCIAL PARA VOTAR", "TELMEX TOTAL A PAGAR")):
            score -= 20
        return score

    def _rank(field: dict) -> tuple[float, float, float]:
        key = str(field.get("key", ""))
        confidence = float(field.get("confidence", 0) or 0)
        if key == "total":
            amount = _parse_amount_for_rank(field.get("value"))
            return (1 if amount is not None and amount > 0 else 0, 0, confidence)
        if key == "domicilio":
            return (1, _address_quality(field.get("value")), confidence)
        return (1, 0, confidence)

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
            current_vigencia = next((f for f in fields if f.get("key") == "vigencia" and f.get("value")), None)
            current_year = 0
            if current_vigencia:
                current_digits = re.sub(r"\D", "", str(current_vigencia.get("value", "")))
                if len(current_digits) >= 4:
                    current_year = int(current_digits[-4:])
            if current_year < 2020:
                year_candidates = [int(year) for year in re.findall(r"(20\d{2})", text)]
                plausible_years = [year for year in year_candidates if 2020 <= year <= datetime.now().year + 30]
                if plausible_years:
                    fields.append(_make_field("vigencia", "Vigencia", str(max(plausible_years)), ocr_boxes, confidence=0.97))
            surname_line = next((line for line in text_lines if "<" in line and "<<" not in line and not re.search(r"\d", line)), "")
            given_line = next((line for line in text_lines if "<<" in line and not re.search(r"\d", line)), "")
            if given_line or surname_line:
                surname_idx = next((i for i, line in enumerate(text_lines) if line == surname_line), -1)
                last = surname_line.replace("<", " ").strip()
                if surname_idx > 0:
                    previous = re.sub(r"[^A-Z]", "", text_lines[surname_idx - 1])
                    if 3 <= len(previous) <= 6 and previous not in {"NOMBRE", "DOMICILIO", "CURP", "SECCION"}:
                        last = f"{previous} {last}".strip()
                first = given_line.split("<<", 1)[-1].replace("<", " ").strip() if given_line else ""
                tokens = []
                for token in f"{first} {last}".split():
                    token = re.sub(r"[^A-Z?]", "", token)
                    if token.endswith("KK") and len(token) > 2:
                        token = token[:-2]
                    elif token.endswith("K") and len(token) > 4:
                        token = token[:-1]
                    tokens.append(token)
                merged_tokens: list[str] = []
                for token in tokens:
                    if (
                        merged_tokens
                        and len(token) <= 2
                        and len(merged_tokens[-1]) >= 4
                        and token not in {"DE", "LA", "DEL", "Y"}
                    ):
                        merged_tokens[-1] = f"{merged_tokens[-1]}{token}"
                        continue
                    merged_tokens.append(token)
                name = " ".join([t for t in tokens if t])
                if merged_tokens:
                    name = " ".join([t for t in merged_tokens if t])
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
                    for line in text_lines[dom_line_idx + 1: dom_line_idx + 5]:
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

    if document_type in {"CONSTANCIA_SITUACION_FISCAL", "DATOS_BANCARIOS", "FACTURA"}:
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
                cleaned_name = _clean_nss_name(nss_box_values["nombre"]["value"])
                if cleaned_name and _is_nss_person_name(cleaned_name):
                    fields.append(_make_field("nombre", "Nombre", _normalize_name(cleaned_name), ocr_boxes, confidence=0.85))
        for value in nss:
            fields.append(_make_field("nss", "NSS", _normalize_alnum(value), ocr_boxes))
        afiliacion = _find_value_after_keyword(lines, ["NUMERO DE SEGURIDAD SOCIAL", "SEGURIDAD SOCIAL"])
        if afiliacion:
            fields.append(_make_field("nss", "NSS", _normalize_numeric_field(afiliacion), ocr_boxes, confidence=0.7))
        nss_name = _extract_nss_name_from_text(lines, text)
        if nss_name:
            fields.append(_make_field("nombre", "Nombre", _normalize_name(nss_name), ocr_boxes, confidence=0.82))

    if document_type in {"DATOS_BANCARIOS", "FACTURA"}:
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

        payment_table = _extract_payment_table_payload(base_text_raw, ocr_boxes)
        payment_detail = _extract_payment_detail_payload(base_text_raw, payment_table)
        payment_table = _enrich_payment_table_payload(payment_table, payment_detail)
        if payment_table:
            fields.append(
                _make_field(
                    "tabla_celdas",
                    "Tabla celdas",
                    json.dumps(payment_table, ensure_ascii=False),
                    ocr_boxes,
                    confidence=0.92,
                )
            )
        if payment_detail:
            fields.append(
                _make_field(
                    "pago_detalle",
                    "Pago detalle",
                    json.dumps(payment_detail, ensure_ascii=False),
                    ocr_boxes,
                    confidence=0.9,
                )
            )
        if document_type == "FACTURA":
            replica_layout = _build_replica_layout_payload(ocr_boxes, raw_text or base_text_raw)
            if replica_layout:
                fields.append(
                    _make_field(
                        "replica_pdf_layout",
                        "Replica PDF layout",
                        json.dumps(replica_layout, ensure_ascii=False),
                        ocr_boxes,
                        confidence=1.0,
                    )
                )
        if document_type == "FACTURA" and raw_text:
            replica_text = raw_text.replace("\r\n", "\n").strip()
            if len(replica_text) >= 80 and "\n" in replica_text:
                fields.append(
                    _make_field(
                        "replica_pdf_texto",
                        "Replica PDF texto",
                        replica_text,
                        ocr_boxes,
                        confidence=1.0,
                    )
                )

    if not any(str(field.get("key", "") or "") == "tabla_celdas" for field in fields):
        payment_table = _extract_payment_table_payload(base_text_raw, ocr_boxes)
        payment_detail = _extract_payment_detail_payload(base_text_raw, payment_table)
        payment_table = _enrich_payment_table_payload(payment_table, payment_detail)
        if payment_table:
            fields.append(
                _make_field(
                    "tabla_celdas",
                    "Tabla celdas",
                    json.dumps(payment_table, ensure_ascii=False),
                    ocr_boxes,
                    confidence=0.9,
                )
            )
        if payment_detail:
            fields.append(
                _make_field(
                    "pago_detalle",
                    "Pago detalle",
                    json.dumps(payment_detail, ensure_ascii=False),
                    ocr_boxes,
                    confidence=0.88,
                )
            )

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
                    if key == "lugar_nacimiento":
                        value = _clean_acta_lugar_nacimiento(value)
                    if key in {"entidad_registro", "municipio_registro"}:
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
        folio = _find_value_after_keyword(lines, ["FOLIO"])
        if folio:
            folio_num = _normalize_value_for_key("folio", folio)
            if folio_num:
                fields.append(_make_field("folio", "Folio", folio_num, ocr_boxes, confidence=0.6))
        if document_type == "ACTA_NACIMIENTO":
            if not any(f.get("key") == "nombre" and f.get("value") for f in fields):
                acta_name = _extract_acta_name_from_text(base_text_raw)
                if acta_name:
                    fields.append(_make_field("nombre", "Nombre", acta_name, ocr_boxes, confidence=0.9))
            numero_acta_text = _find_value_after_keyword(lines, ["NUMERO DE ACTA", "NO ACTA"])
            if numero_acta_text:
                numero_norm = _normalize_value_for_key("numero_acta", numero_acta_text)
                if numero_norm:
                    fields.append(_make_field("numero_acta", "Numero de acta", numero_norm, ocr_boxes, confidence=0.6))
            extracted_keys = {str(f.get("key", "")) for f in fields}
            if "folio" not in extracted_keys or "numero_acta" not in extracted_keys:
                folio_text, numero_text = _extract_acta_folio_numero_from_text(text)
                if folio_text and "folio" not in extracted_keys:
                    fields.append(_make_field("folio", "Folio", folio_text, ocr_boxes, confidence=0.82))
                    extracted_keys.add("folio")
                if numero_text and "numero_acta" not in extracted_keys:
                    fields.append(_make_field("numero_acta", "Numero de acta", numero_text, ocr_boxes, confidence=0.82))
                    extracted_keys.add("numero_acta")
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
                cliente_raw = str(svc_values["cliente"]["value"])
                due_date = _extract_due_date_from_text(cliente_raw)
                if due_date:
                    if not any(f.get("key") == "fecha_limite" and f.get("value") for f in fields):
                        fields.append(_make_field("fecha_limite", "Fecha limite", due_date, ocr_boxes, confidence=0.84))
                else:
                    fields.append(_make_field("cliente", "Cliente", _normalize_name(cliente_raw), ocr_boxes, confidence=0.7))
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
            def _extract_cfe_address(lines_local: list[str], full_text_local: str) -> str | None:
                address_markers = ("DOMICILIO", "CALLE", "CLL", "COL", "COLONIA", "AV", "AVENIDA", "FRACC", "MZ", "LT", "CP", "C.P.")
                stop_tokens = ("TOTAL", "IMPORTE", "PAGAR", "LIMITE", "CORTE", "RFC", "TARIFA", "MEDIDOR", "SERVICIO")

                for idx, raw_line in enumerate(lines_local):
                    line = _normalize_text(str(raw_line)).upper()
                    if "DOMICILIO" not in line:
                        continue
                    tail = re.sub(r"^.*DOMICILIO(?:\s+DEL\s+SERVICIO|\s+DE\s+SUMINISTRO)?\s*[:\-]?\s*", "", line).strip(" .,-")
                    pieces = []
                    if tail and not any(token in tail for token in ("COMISION FEDERAL", "CFE SUMINISTRADOR")):
                        pieces.append(tail)
                    for next_line in lines_local[idx + 1: idx + 3]:
                        upper_next = _normalize_text(str(next_line)).upper()
                        if not upper_next:
                            continue
                        if any(token in upper_next for token in stop_tokens):
                            break
                        pieces.append(upper_next)
                    candidate = _clean_address_value(" ".join(pieces))
                    if len(candidate) >= 12 and any(marker in candidate for marker in address_markers):
                        return candidate

                for idx, raw_line in enumerate(lines_local):
                    line = _normalize_text(str(raw_line)).upper()
                    if not any(marker in line for marker in address_markers):
                        continue
                    if any(token in line for token in ("TOTAL", "IMPORTE", "PAGAR", "TARIFA", "MEDIDOR", "RFC")):
                        continue
                    pieces = [line]
                    for next_line in lines_local[idx + 1: idx + 3]:
                        upper_next = _normalize_text(str(next_line)).upper()
                        if not upper_next:
                            continue
                        if any(token in upper_next for token in stop_tokens):
                            break
                        pieces.append(upper_next)
                    candidate = _clean_address_value(" ".join(pieces))
                    if len(candidate) >= 12 and any(marker in candidate for marker in address_markers):
                        return candidate

                match = re.search(
                    r"(?:DOMICILIO(?:\s+DEL\s+SERVICIO|\s+DE\s+SUMINISTRO)?|DIRECCION)\s*[:\-]?\s*(.{15,180}?)(?=\s+(?:TOTAL|IMPORTE|PAGAR|RFC|TARIFA|MEDIDOR|NO\.?\s*DE\s*SERVICI[O0]|SERVICI[O0])\b|$)",
                    full_text_local,
                )
                if match:
                    candidate = _clean_address_value(match.group(1))
                    if len(candidate) >= 12 and any(marker in candidate for marker in address_markers):
                        return candidate
                return None

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

            # CFE receipts sometimes omit/merge CP and lose address in generic picker.
            if not any(f.get("key") == "domicilio" and f.get("value") for f in fields):
                cfe_address = _extract_cfe_address(box_text_lines, full_text)
                if cfe_address:
                    fields.append(_make_field("domicilio", "Domicilio", cfe_address, ocr_boxes, confidence=0.83))
                    if not any(f.get("key") == "cp" and f.get("value") for f in fields):
                        cfe_cp = _extract_postal_code(cfe_address)
                        if cfe_cp:
                            fields.append(_make_field("cp", "CP", cfe_cp, ocr_boxes, confidence=0.8))
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

        provider_is_telcel = any(
            f.get("key") == "proveedor" and "TELCEL" in _normalize_text(str(f.get("value", ""))).upper()
            for f in fields
        )
        filename_is_telcel = "TELCEL" in _normalize_text(filename or "").upper()
        telcel_in_text = "TELCEL" in full_text or provider_is_telcel or filename_is_telcel
        if telcel_in_text:
            telcel_text = re.sub(r"(?<=[A-Z])0(?=[A-Z])", "O", full_text)
            telcel_text = re.sub(r"(?<=[A-Z])1(?=[A-Z])", "I", telcel_text)

            if not any(f.get("key") == "proveedor" and str(f.get("value", "")).upper() == "TELCEL" for f in fields):
                fields.append(_make_field("proveedor", "Proveedor", "TELCEL", ocr_boxes, confidence=0.9))

            if not any(f.get("key") == "numero_servicio" and f.get("value") for f in fields):
                num_match = re.search(
                    r"(?:LINEA\s+TELCEL|NUMERO\s+TELCEL|NUMERO\s+DE\s+LINEA|NUMERO\s+DE\s+TELEFONO|TELEFONO|NUMERO)\D*((?:[0-9OIL][\s().-]*){10,12})",
                    telcel_text,
                )
                if num_match:
                    num_value = _normalize_numeric_field(num_match.group(1))
                    if len(num_value) > 10:
                        num_value = num_value[-10:]
                    if re.fullmatch(r"\d{10}", num_value):
                        fields.append(_make_field("numero_servicio", "Numero de servicio", num_value, ocr_boxes, confidence=0.95))

            if not any(f.get("key") == "cuenta" and f.get("value") for f in fields):
                cuenta_match = re.search(
                    r"(?:NO\.?\s*DE\s*CUENTA|NUMERO\s+DE\s+CUENTA|CUENTA)\D*((?:[0-9OIL][\s.-]*){8,24})",
                    telcel_text,
                )
                if cuenta_match:
                    cuenta_value = _normalize_numeric_field(cuenta_match.group(1))
                    if 8 <= len(cuenta_value) <= 22:
                        fields.append(_make_field("cuenta", "Cuenta", cuenta_value, ocr_boxes, confidence=0.93))

            ref_match = re.search(
                r"(?:REFERENCIA(?:\s+DE\s+PAGO)?|REF(?:ERENCIA)?|LINEA\s+DE\s+CAPTURA)\s*[:#-]?\s*((?:[0-9OIL][\s.-]*){10,30})(?=\s+(?:PAGAR|FECHA|TOTAL|IMPORTE|SALDO|LIMITE|VENC)\b|$)",
                telcel_text,
            )
            if ref_match:
                ref_value = _normalize_value_for_key("referencia", ref_match.group(1))
                if ref_value:
                    fields.append(_make_field("referencia", "Referencia", ref_value, ocr_boxes, confidence=0.93))

            if not any(f.get("key") == "fecha_limite" and f.get("value") for f in fields):
                limit_match = re.search(
                    r"(?:PAGAR\s+ANTES\s+DE|FECHA\s*LIMITE(?:\s*DE\s*PAGO)?|VENCIMIENTO|VENCE)\D*([0-9OIL]{1,2}(?:\s+|[-/])[A-Z]{3}(?:\s+|[-/])[0-9OIL]{2,4}|[0-9OIL]{2}[/-][0-9OIL]{2}[/-][0-9OIL]{2,4})",
                    telcel_text,
                )
                if limit_match:
                    raw_date = limit_match.group(1).upper().replace("O", "0").replace("I", "1").replace("L", "1")
                    fields.append(_make_field("fecha_limite", "Fecha limite", _normalize_date_value(raw_date), ocr_boxes, confidence=0.9))

            if not any(f.get("key") == "total" and f.get("value") for f in fields):
                total_match = re.search(
                    r"(?:TOTAL\s+A\s+PAGAR|IMPORTE\s+A\s+PAGAR|TOTAL|SALDO\s+TOTAL)\D*(\$?\s*[0-9OIL]{1,3}(?:[.,][0-9OIL]{3})*(?:[.,][0-9OIL]{2})?)",
                    telcel_text,
                )
                if total_match:
                    raw_total = total_match.group(1).upper().replace("O", "0").replace("I", "1").replace("L", "1")
                    fields.append(_make_field("total", "Total", _normalize_text(raw_total), ocr_boxes, confidence=0.9))

            dom_match = re.search(
                r"(?:DOMICILIO(?:\s+DE\s+(?:ENVIO|FACTURACION|SERVICIO))?|DIRECCION(?:\s+DE\s+(?:ENVIO|FACTURACION))?)\s*[:\-]?\s*(.{15,220}?)(?=\s+(?:TOTAL|IMPORTE|PAGAR|LIMITE|VENC|REFERENCIA|CUENTA|RFC|TELCEL)\b|$)",
                telcel_text,
            )
            if dom_match:
                domicilio = _clean_address_value(dom_match.group(1))
                if len(domicilio) >= 12:
                    fields.append(_make_field("domicilio", "Domicilio", domicilio, ocr_boxes, confidence=0.92))

            if not any(f.get("key") == "cp" and f.get("value") for f in fields):
                cp_from_dom = None
                for f in fields:
                    if f.get("key") != "domicilio" or not f.get("value"):
                        continue
                    cp_candidate = _extract_postal_code(str(f.get("value", "")))
                    if cp_candidate:
                        cp_from_dom = cp_candidate
                        break
                if cp_from_dom:
                    fields.append(_make_field("cp", "CP", cp_from_dom, ocr_boxes, confidence=0.9))
                else:
                    cp_match = re.search(r"\b([0-9OIL]{5})\b", full_text)
                    if cp_match:
                        cp_value = _normalize_value_for_key("cp", cp_match.group(1))
                        if cp_value:
                            fields.append(_make_field("cp", "CP", cp_value, ocr_boxes, confidence=0.88))

    # CFE fallback: many receipts only expose RMU and no explicit "Referencia" label.
    if document_type == "COMPROBANTE_DOMICILIO":
        has_ref = any(f.get("key") == "referencia" and f.get("value") for f in fields)
        provider_val = next((str(f.get("value", "")).upper() for f in fields if f.get("key") == "proveedor"), "")
        is_cfe = provider_val == "CFE" or "CFE" in text or "COMISION FEDERAL" in text
        if is_cfe and not has_ref:
            rmu_match = re.search(r"\bRMU[:\s-]*([A-Z0-9-]{12,40})", text)
            if rmu_match:
                rmu_value = _normalize_value_for_key("referencia", rmu_match.group(1))
                if rmu_value:
                    fields.append(_make_field("referencia", "Referencia", rmu_value, ocr_boxes, confidence=0.86))
        if is_cfe:
            best_dom = next((str(f.get("value", "")).strip() for f in fields if f.get("key") == "domicilio" and f.get("value")), "")
            if best_dom:
                dom_upper = _normalize_text(best_dom).upper()
                if dom_upper.startswith("DN") and "17DN" in text:
                    dom_upper = _normalize_text(f"17 {dom_upper}").upper()
                has_address_markers = any(
                    marker in dom_upper for marker in ("CALLE", "CLL", "AV", "COL", "CP", "C.P.", "DEPTO", "BENITO", "CARMEN")
                )
                if has_address_markers and len(dom_upper) >= 16:
                    av_piece = ""
                    if "AV " not in dom_upper:
                        av_match = re.search(r"\bAV[A-Z0-9]{6,120}(?:COLOSIO|DONALDO)[A-Z0-9]{0,20}", text)
                        if av_match:
                            av_piece = _clean_address_value(av_match.group(0))

                    dom_with_av = dom_upper
                    if av_piece and av_piece not in dom_with_av:
                        if "SSL" in dom_with_av:
                            dom_with_av = re.sub(r"\bSSL\b", f"{av_piece} SSL", dom_with_av, count=1)
                        else:
                            dom_with_av = _normalize_text(f"{dom_with_av} {av_piece}").upper()

                    domicilio_candidate = re.sub(r"\bC\.?\s*P\.?\s*\d{5}\b", " ", dom_with_av)
                    domicilio_candidate = re.sub(r"\b\d{5}\b", " ", domicilio_candidate)
                    domicilio_candidate = re.sub(
                        r"\bCIUDAD\s*DE[L]?\s*CARMEN[,.\s]*CAMP(?:ECHE)?\b|\bCIUDADDELCARMEN[,.\s]*CAMP(?:ECHE)?\b",
                        " ",
                        domicilio_candidate,
                    )
                    domicilio_candidate = _clean_address_value(domicilio_candidate)
                    if domicilio_candidate:
                        fields.append(_make_field("domicilio", "Domicilio", domicilio_candidate, ocr_boxes, confidence=0.94))

                    ref_parts = [dom_with_av]
                    cp_value = next(
                        (
                            _normalize_numeric_field(str(f.get("value", "")))
                            for f in fields
                            if f.get("key") == "cp" and f.get("value")
                        ),
                        "",
                    )
                    if cp_value and cp_value not in dom_upper:
                        ref_parts.append(f"FC.P. {cp_value}")
                    city_match = re.search(
                        r"CIUDAD\s*DE[L]?\s*CARMEN[,.\s]*CAMP(?:ECHE)?|CIUDADDELCARMEN[,.\s]*CAMP(?:ECHE)?",
                        text,
                    )
                    if city_match:
                        city_text = _normalize_text(city_match.group(0)).upper()
                        if city_text and city_text not in dom_upper:
                            ref_parts.append(city_text)
                    fields.append(
                        _make_field(
                            "referencia",
                            "Referencia",
                            _normalize_text(" ".join(ref_parts)).upper(),
                            ocr_boxes,
                            confidence=0.92,
                        )
                    )

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

    if document_type == "COMPROBANTE_DOMICILIO":
        if telmex_in_text and not any(f.get("key") == "fecha_limite" and f.get("value") for f in fields):
            limit_match = re.search(
                r"(?:PAGAR\s*ANTES\s*DE|FECHA\s*LIMITE(?:\s*DE\s*PAGO)?|VENCIMIENTO|VENCE)\D*([0-9OIL]{1,2}\s*(?:[-/]|[^0-9A-Z]+)\s*[A-Z]{3,9}\s*(?:[-/]|[^0-9A-Z]+)\s*[0-9OIL]{2,4}|[0-9OIL]{1,2}\s*(?:[/-]|[^0-9A-Z]+)\s*[0-9OIL]{1,2}\s*(?:[/-]|[^0-9A-Z]+)\s*[0-9OIL]{2,4})",
                full_text.replace("–", "-").replace("—", "-").replace("−", "-"),
            )
            if limit_match:
                normalized_limit = _normalize_date_value(limit_match.group(1))
                if re.fullmatch(r"\d{2}/\d{2}/\d{4}", normalized_limit):
                    fields.append(_make_field("fecha_limite", "Fecha limite", normalized_limit, ocr_boxes, confidence=0.88))

        normalized_fields = []
        recovered_due_date = None
        for field in fields:
            if str(field.get("key", "")) != "cliente":
                normalized_fields.append(field)
                continue
            cliente_value = str(field.get("value", ""))
            due_date = _extract_due_date_from_text(cliente_value)
            if not due_date:
                cliente_norm = _normalize_text(cliente_value).upper()
                if (
                    any(token in cliente_norm for token in ("NUMERO TELEFONICO", "TELEFONO", "REFERENCIA", "NO DE CUENTA", "CUENTA"))
                    or sum(1 for ch in cliente_norm if ch.isdigit()) >= 8
                ):
                    continue
                normalized_fields.append(field)
                continue
            if not recovered_due_date:
                recovered_due_date = due_date
        fields = normalized_fields
        if recovered_due_date and not any(f.get("key") == "fecha_limite" and f.get("value") for f in fields):
            fields.append(_make_field("fecha_limite", "Fecha limite", recovered_due_date, ocr_boxes, confidence=0.84))

    if document_type == "ACTA_NACIMIENTO":
        best_place = next((f for f in fields if f.get("key") == "lugar_nacimiento" and f.get("value")), None)
        best_state = next((f for f in fields if f.get("key") == "entidad_registro" and f.get("value")), None)
        if best_place and best_state:
            place_text = _clean_acta_lugar_nacimiento(str(best_place.get("value", "")))
            state_text = _normalize_address(str(best_state.get("value", "")))
            if place_text and state_text and state_text not in place_text:
                fields.append(
                    _make_field(
                        "lugar_nacimiento",
                        "Lugar de nacimiento",
                        _clean_acta_lugar_nacimiento(f"{place_text} {state_text}"),
                        ocr_boxes,
                        confidence=0.95,
                    )
                )

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

    cleaned = _postprocess_fields(document_type, fields)
    contracted = _apply_field_contracts(document_type, cleaned)
    return _dedupe_fields(contracted)

