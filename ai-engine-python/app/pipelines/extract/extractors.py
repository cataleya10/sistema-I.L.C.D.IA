"""Document-type extractors (INE, CURP, Acta, NSS, Financial, Service, Generic)."""

import re
import json
import os
import logging
import unicodedata
from datetime import datetime
from typing import Any

from .constants import *  # noqa: F403
from .common import *  # noqa: F403
from .tables import *  # noqa: F403

logger = logging.getLogger(__name__)


def _export_all():
    import sys
    mod = sys.modules[__name__]
    return [n for n in dir(mod) if not n.startswith('__')]



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
        # Ignore Acta table header words often captured as values.
        if cleaned in {"PRIMER", "SEGUNDO", "APELLIDO", "APELLIDOS", "NOMBRE", "NOMBRES"}:
            return None
        if "APELLIDO" in cleaned or cleaned.endswith(":"):
            return None
        return cleaned

    def _is_valid_acta_name(value: str | None) -> bool:
        if not value:
            return False
        upper = _normalize_name(value).upper()
        if not upper or re.search(r"\d", upper):
            return False
        # Reject common header/label noise that OCR merges into "nombre".
        banned_fragments = {
            "SEXO",
            "FECHA",
            "NACIMIENTO",
            "LUGAR",
            "REGISTRO",
            "PERSONA REGISTRADA",
            "DATOS DE LA",
            # valores de sexo que se cuelan cuando el extractor lee la fila debajo del label
            "HOMBRE",
            "MUJER",
        }
        if any(fragment in upper for fragment in banned_fragments):
            return False
        compact = _label_key(upper)
        return len(compact) >= 4

    # Strong path: recover all 3 pieces even when OCR merges labels
    # (e.g. SEGUNDOAPELLIDA, SEXAHOMBRE).
    if "nombre" not in result:
        structured = re.search(
            r"N[O0]MBRE(?:\(S\))?\s*[:\-]?\s*([A-Z ]+?)\s+PRIMER\s*APELLID[OA]\s*[:\-]?\s*([A-Z ]+?)\s+SEGUND[OA]\s*APELLID[OA]\s*[:\-]?\s*([A-Z ]+?)(?:\s+SEX[OA0]|\s+FECH|\s+LUGAR|$)",
            full_text,
        )
        if structured:
            parts = [
                _clean_name_piece(structured.group(1)),
                _clean_name_piece(structured.group(2)),
                _clean_name_piece(structured.group(3)),
            ]
            parts = [part for part in parts if part]
            if parts:
                candidate = " ".join(dict.fromkeys(parts))
                if _is_valid_acta_name(candidate):
                    result["nombre"] = {"value": candidate}

    # Layout invertido (actas digitales RENAPO): los valores NOMBRE/APELLIDOS aparecen
    # en la fila ENCIMA de los labels (Nombre(s):, Primer Apellido:, Segundo Apellido:).
    # Si aún no tenemos nombre, buscar la línea anterior al label row.
    if "nombre" not in result:
        nombre_label_line = _find_label_line(lines, "NOMBRE(S)") or _find_label_line(lines, "NOMBRE")
        if nombre_label_line is not None:
            label_idx = next((i for i, ln in enumerate(lines) if ln is nombre_label_line), None)
            if label_idx is not None and label_idx > 0:
                prev_line = lines[label_idx - 1]
                prev_text = prev_line.get("text", "").upper()
                _skip_words = {"DATOS DE LA PERSONA", "PERSONA REGISTRADA", "NOMBRE", "APELLIDO",
                               "DATOS", "REGISTRADA", "HOMBRE", "MUJER", "SEXO"}
                if not any(w in prev_text for w in _skip_words):
                    candidate = _clean_name_piece(prev_text)
                    if candidate and _is_valid_acta_name(candidate):
                        result["nombre"] = {"value": candidate}

    nombre = _extract_label_value(lines, "NOMBRE(S)", stop_labels=["PRIMER", "SEGUNDO", "SEXO", "FECHA"])
    if not nombre:
        nombre = _extract_label_value(lines, "NOMBRE", stop_labels=["FECHA", "FOLIO", "LIBRO", "TOMO"])
    if nombre and "nombre" not in result:
        cleaned_nombre = _clean_name_piece(nombre)
        if cleaned_nombre and _is_valid_acta_name(cleaned_nombre):
            result["nombre"] = {"value": cleaned_nombre}
    elif "nombre" not in result:
        match = re.search(r"DATOS DE LA PERSONA REGISTRADA\s+(.+?)\s+NOMBRE", full_text)
        if match:
            candidate = _clean_name_piece(match.group(1).strip())
            if _is_valid_acta_name(candidate):
                result["nombre"] = {"value": candidate}
        else:
            match = re.search(r"PERSONA REGISTRADA\s+(.+?)\s+SEXO", full_text)
            if match:
                candidate = _clean_name_piece(match.group(1).strip())
                if _is_valid_acta_name(candidate):
                    result["nombre"] = {"value": candidate}
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
                candidate = " ".join(name_lines)
                if _is_valid_acta_name(candidate):
                    result["nombre"] = {"value": candidate}
        if "nombre" not in result:
            nombre_part = _clean_name_piece(_extract_label_value(lines, "NOMBRE(S)", stop_labels=["PRIMER", "SEGUNDO", "SEXO", "FECHA"]))
            primer_apellido = _clean_name_piece(_extract_label_value(lines, "PRIMER APELLIDO", stop_labels=["SEGUNDO", "SEXO", "FECHA"]))
            segundo_apellido = _clean_name_piece(_extract_label_value(lines, "SEGUNDO APELLIDO", stop_labels=["SEXO", "FECHA"]))
            if not primer_apellido:
                primer_match = re.search(
                    r"\bPRIMER\s*APELLID[OA]\s*[:\-]?\s*([A-Z ]{2,})",
                    full_text,
                )
                if primer_match:
                    primer_apellido = _clean_name_piece(primer_match.group(1))
            if not segundo_apellido:
                segundo_match = re.search(
                    r"\bSEGUND[OA]\s*APELLID[OA]\s*[:\-]?\s*([A-Z ]{2,})",
                    full_text,
                )
                if segundo_match:
                    segundo_apellido = _clean_name_piece(segundo_match.group(1))
            parts = [p for p in [nombre_part, primer_apellido, segundo_apellido] if p]
            # Keep order but remove duplicate chunks to avoid
            # "NOMBRE APELLIDO NOMBRE APELLIDO" artifacts.
            parts = list(dict.fromkeys(parts))
            if parts:
                candidate = " ".join(parts)
                if _is_valid_acta_name(candidate):
                    result["nombre"] = {"value": candidate}
            else:
                label_line = _find_label_line(lines, "NOMBRE")
                if label_line:
                    below = _collect_below(lines, label_line, stop_labels=["SEXO", "FECHA", "LUGAR", "MUNICIPIO"], max_lines=2)
                    if below:
                        candidate = " ".join(line.get("text", "").strip() for line in below if line.get("text"))
                        candidate = _clean_name_piece(candidate.strip())
                        if _is_valid_acta_name(candidate):
                            result["nombre"] = {"value": candidate}

    sexo_inline = re.search(r"\bSEX[OA0]\s*[:\-]?\s*(HOMBRE|MUJER|H|M)\b", full_text)
    if sexo_inline:
        normalized = _normalize_sex(sexo_inline.group(1))
        if normalized in {"H", "M"}:
            result["sexo"] = {"value": normalized}
    if "sexo" not in result:
        sexo = _extract_label_value(lines, "SEXO", stop_labels=["FECHA", "LUGAR", "MUNICIPIO"])
        if sexo:
            normalized = _normalize_sex(sexo)
            if normalized in {"H", "M"}:
                result["sexo"] = {"value": normalized}

    fecha_nacimiento = None
    fecha_inline = re.search(
        r"\bFECH[A-Z]{0,10}NACIMI[A-Z]{0,12}\s*[:\-]?\s*(\d{2}[/-]\d{2}[/-]\d{4})",
        full_text,
    )
    if fecha_inline:
        fecha_nacimiento = fecha_inline.group(1)
    if not fecha_nacimiento:
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

    if "nombre" in result:
        candidate = _normalize_name(str(result["nombre"].get("value", "")))
        if _is_valid_acta_name(candidate):
            result["nombre"] = {"value": candidate}
        else:
            result.pop("nombre", None)

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
        inline = re.search(r"SEXO\s*[:\-]?\s*([HM])", sexo_line.get("text", "").upper())
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
        # NOTE: "SECCION" removed from stop labels because it appears in address
        # text (e.g. "2DA SECCION") and prematurely truncates address collection.
        value_lines = _collect_below(
            lines,
            domicilio_line,
            ["CLAVE", "CURP", "VIGENCIA", "FECHA"],
            max_lines=5,
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
    # 1. Buscar línea con el key y extraer fragmento después del key
    # 2. Si no hay match, buscar la mejor línea con marcador de dirección
    key_regex = re.compile(r"\bDOMICILIO\s+DE(?:L)?\s+SUMINISTR[O0]\b", re.IGNORECASE)
    compact_key_regex = re.compile(r"DOMICILIODE(?:L)?SUMINISTR[O0]", re.IGNORECASE)
    for i, orig_line in enumerate(lines):
        normalized_line = _normalize_text(orig_line)
        key_match = key_regex.search(normalized_line)
        if key_match:
            dom = normalized_line[key_match.end():].strip(" :.-")
        else:
            compact_line = _normalize_alnum(orig_line)
            compact_match = compact_key_regex.search(compact_line)
            if not compact_match:
                continue
            dom = compact_line[compact_match.end():].strip()
        # Si es muy corto, unir con la siguiente línea
        if len(dom) < 8 and i + 1 < len(lines):
            dom += " " + lines[i + 1].strip()
        dom = re.sub(r"\([^)]{0,200}\)", " ", dom)
        dom = re.sub(r"\bDESCARGA\s+NUESTRA\b.*$", " ", dom)
        dom = re.sub(r"\$\s*\d+[.,]?\d*", " ", dom)
        dom = re.sub(r"TOTAL\s*A\s*PAGAR.*", " ", dom, flags=re.IGNORECASE)
        dom = re.sub(r"\s+", " ", dom).strip(" .,-")
        cleaned = _clean_address_value(dom)
        if cleaned and len(cleaned) >= 8:
            return cleaned
    # Buscar la mejor línea con marcador de dirección
    address_markers = ("DN.", "DEPTO", "CALLE", "CLL", "AV", "BENITO", "COL", "SSL", "CP", "C.P.")
    best = None
    best_score = 0
    for line in lines:
        norm = _normalize_text(line).upper()
        if any(tok in norm for tok in address_markers):
            cleaned = _clean_address_value(norm)
            score = sum(tok in cleaned for tok in address_markers) + len(cleaned)
            if cleaned and len(cleaned) >= 8 and score > best_score:
                best = cleaned
                best_score = score
    if best:
        return best
    # Como último recurso, unir todas las líneas y extraer tokens de dirección
    joined = " ".join(_normalize_text(l).upper() for l in lines)
    cleaned = _clean_address_value(joined)
    if cleaned and len(cleaned) >= 8:
        return cleaned
    return None


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


# ═══════════════════════════════════════════════════════════════════════════════
# GENERICO (Generic) extractor — works on any image / document
# ═══════════════════════════════════════════════════════════════════════════════

# Labels to skip — these are noise, not useful key-value pairs
_GENERIC_SKIP_LABELS = frozenset({
    "HTTP", "HTTPS", "WWW", "COM", "MX", "GOB", "ORG", "PDF", "JPG", "PNG",
    "PAGE", "PAG", "PAGINA", "DE", "LA", "EL", "EN", "POR", "CON", "PARA",
    "QUE", "DEL", "LOS", "LAS", "UNA", "UNO", "AL", "SE", "ES", "NO", "SI",
    "SU", "SUS", "MIS", "TUS", "NOS", "LES",
})

# Regex for "Label: Value" or "Label - Value" or "Label = Value" patterns
_KV_SEPARATOR_RE = re.compile(
    r"^([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ0-9 ./#°]{2,50}?)"  # label
    r"\s*[:=\-–—]\s*"                                   # separator
    r"(.+)$",                                           # value
    re.IGNORECASE,
)

# Pattern for lines that look like "LABEL  VALUE" with large whitespace gap
_KV_SPACE_GAP_RE = re.compile(
    r"^([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ ./#°]{2,40}?)"  # label
    r"\s{3,}"                                       # 3+ spaces (gap)
    r"(\S.+)$",                                     # value
)


def _is_valid_generic_label(label: str) -> bool:
    """Check if a label is meaningful (not just stopwords or noise)."""
    clean = label.strip().upper()
    if len(clean) < 2 or len(clean) > 60:
        return False
    tokens = clean.split()
    # All tokens are stopwords → skip
    if all(t in _GENERIC_SKIP_LABELS for t in tokens):
        return False
    # Pure numbers → not a label
    if re.fullmatch(r"[\d\s.,$]+", clean):
        return False
    return True


def _is_valid_generic_value(value: str) -> bool:
    """Check if a value is meaningful."""
    clean = value.strip()
    if len(clean) < 1 or len(clean) > 500:
        return False
    return True


def _slugify_label(label: str) -> str:
    """Convert a label to a snake_case key."""
    text = _normalize_text(label).upper().strip()
    # Remove accents
    text = unicodedata.normalize("NFD", text)
    text = re.sub(r"[\u0300-\u036f]", "", text)
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_")
    return text[:50] or "campo"


def _extract_generic_kv_from_text(text: str) -> list[dict]:
    """
    Extract key-value pairs from plain text using heuristic patterns.
    Works with any document — no domain-specific logic.
    """
    fields: list[dict] = []
    seen_keys: set[str] = set()
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    for line in lines:
        upper_line = line.upper()
        # Skip very short or very long lines
        if len(line) < 4 or len(line) > 300:
            continue

        # Try separator-based KV extraction
        for pattern in (_KV_SEPARATOR_RE, _KV_SPACE_GAP_RE):
            match = pattern.match(line)
            if not match:
                continue
            label_raw = match.group(1).strip()
            value_raw = match.group(2).strip()

            if not _is_valid_generic_label(label_raw):
                continue
            if not _is_valid_generic_value(value_raw):
                continue

            key = _slugify_label(label_raw)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            # Clean up label for display
            display_label = _normalize_text(label_raw).strip()
            display_label = re.sub(r"\s+", " ", display_label)
            # Capitalize first letter of each word
            display_label = display_label.title()

            fields.append({
                "key": key,
                "label": display_label,
                "value": value_raw.strip(),
                "confidence": 0.6,
                "valid": True,
                "validation_errors": [],
                "source": None,
            })
            break  # Don't try second pattern if first matched

    return fields


def _extract_generic_kv_from_boxes(ocr_boxes: list[dict] | None) -> list[dict]:
    """
    Extract key-value pairs using spatial OCR box analysis.
    Detects label → value relationships based on position (right-of or below).
    """
    if not ocr_boxes:
        return []

    boxes = _boxes_with_rect(ocr_boxes)
    if not boxes:
        return []

    lines = _line_groups(boxes)
    fields: list[dict] = []
    seen_keys: set[str] = set()

    for line in lines:
        line_boxes = line.get("boxes", [])
        if not line_boxes:
            continue

        # Sort boxes left-to-right
        sorted_boxes = sorted(line_boxes, key=lambda b: b["rect"][0] if isinstance(b.get("rect"), (list, tuple)) and len(b["rect"]) >= 1 else 0)

        for i, box in enumerate(sorted_boxes):
            text = (box.get("text", "") or "").strip()
            if not text:
                continue

            # Check if this box looks like a label (ends with : or is all-caps keyword)
            is_label = False
            label_text = text

            if text.endswith(":") or text.endswith("=") or text.endswith("-"):
                label_text = text.rstrip(":=- ").strip()
                is_label = True
            elif (
                text.upper() == text
                and re.match(r"^[A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜ ./#°]{1,40}$", text)
                and not re.fullmatch(r"[\d\s.,$]+", text)
            ):
                is_label = True

            if not is_label or not _is_valid_generic_label(label_text):
                continue

            # Look for value in the next box to the right
            value_text = ""
            if i + 1 < len(sorted_boxes):
                next_box = sorted_boxes[i + 1]
                next_text = (next_box.get("text", "") or "").strip()
                # Ensure there's a meaningful gap (not just adjacent text)
                if next_text:
                    value_text = next_text

            if not value_text or not _is_valid_generic_value(value_text):
                continue

            key = _slugify_label(label_text)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            display_label = _normalize_text(label_text).strip()
            display_label = re.sub(r"\s+", " ", display_label).title()

            fields.append({
                "key": key,
                "label": display_label,
                "value": value_text,
                "confidence": 0.65,
                "valid": True,
                "validation_errors": [],
                "source": _find_source(value_text, ocr_boxes) if ocr_boxes else None,
            })

    return fields


def _extract_generic_identifiers(text: str, ocr_boxes: list[dict] | None = None) -> list[dict]:
    """
    Extract common identifiers (CURP, RFC, NSS, CLABE, emails, phones, amounts, dates)
    from any document regardless of type.
    """
    fields: list[dict] = []
    upper = text.upper()

    # CURP
    for match in CURP_PATTERN.finditer(upper):
        fields.append(_make_field("curp", "CURP", _normalize_alnum(match.group(0)), ocr_boxes, confidence=0.85))

    # RFC
    for match in RFC_WITH_HOMOCLAVE.finditer(upper):
        value = _normalize_alnum(match.group(0))
        # Avoid duplicating if it's also a CURP prefix
        if not any(f.get("key") == "curp" and value in f.get("value", "") for f in fields):
            fields.append(_make_field("rfc", "RFC", value, ocr_boxes, confidence=0.8))

    # NSS (11 digits)
    for match in NSS_PATTERN.finditer(upper):
        val = match.group(0)
        # Avoid matching date-like or other numbers embedded in text
        if re.search(r"(?:NSS|SEGURIDAD\s*SOCIAL|IMSS)", upper):
            fields.append(_make_field("nss", "NSS", val, ocr_boxes, confidence=0.75))

    # CLABE (18 digits)
    for match in CLABE_PATTERN.finditer(upper):
        val = match.group(0)
        if re.search(r"(?:CLABE|INTERBANCARIA|CUENTA)", upper):
            fields.append(_make_field("clabe", "CLABE", val, ocr_boxes, confidence=0.75))

    # Email addresses
    for match in re.finditer(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text):
        fields.append(_make_field("email", "Correo electrónico", match.group(0).lower(), ocr_boxes, confidence=0.9))

    # Phone numbers (Mexican format)
    for match in re.finditer(r"\b(?:\+?52\s*)?(?:\(?\d{2,3}\)?\s*)?[\d\s-]{7,10}\b", upper):
        candidate = re.sub(r"[^\d]", "", match.group(0))
        if 10 <= len(candidate) <= 13:
            formatted = candidate
            fields.append(_make_field("telefono", "Teléfono", formatted, ocr_boxes, confidence=0.6))

    # Monetary amounts
    for match in AMOUNT_PATTERN.finditer(text):
        val = match.group(0)
        # Only include if there's a currency context
        context_start = max(0, match.start() - 20)
        context = text[context_start:match.end() + 5].upper()
        if re.search(r"[$MXNUSD]|\bTOTAL\b|\bMONTO\b|\bIMPORTE\b|\bPAGO\b|\bSALDO\b|\bSUBTOTAL\b|\bIVA\b", context):
            fields.append(_make_field("monto", "Monto", f"{val}", ocr_boxes, confidence=0.65))

    # Dates
    for match in DATE_FLEX_PATTERN.finditer(upper):
        val = match.group(0)
        fields.append(_make_field("fecha", "Fecha", val, ocr_boxes, confidence=0.6))

    return fields


def _extract_generic_all_tables(
    base_text_raw: str,
    ocr_boxes: list[dict] | None,
    pdf_tables: list[list[list[str]]] | None = None,
) -> list[dict]:
    """
    Extract ALL tables from any document source (PDF structure, OCR boxes, text).
    Returns a list of field dicts with key=tabla_celdas_N for each table found.
    """
    all_tables: list[dict] = []

    # 1. PDF-extracted tables (highest quality)
    if pdf_tables:
        pdf_generic = _pdf_tables_to_generic_payloads(pdf_tables)
        all_tables.extend(pdf_generic)

    # 2. OCR box-based tables — skip if PDF already found substantial tables,
    #    since this is an expensive re-analysis of the same data.
    pdf_total_rows = sum(t.get("row_count", 0) for t in all_tables)
    if pdf_total_rows < 10:
        ocr_tables = _extract_all_table_payloads(base_text_raw, ocr_boxes)
        all_tables.extend(ocr_tables)
    else:
        ocr_tables = []

    logger.info("[DEDUP] raw tables: pdf=%d ocr=%d total=%d",
                len(pdf_generic) if pdf_tables else 0, len(ocr_tables), len(all_tables))
    for ti, t in enumerate(all_tables):
        rows = t.get("rows", [])
        first_row = " | ".join(str(c) for c in rows[0])[:120] if rows else "?"
        logger.info("[DEDUP] table[%d] src=%s rows=%d cols=%d first_row=%s",
                    ti, t.get("source", "?"), len(rows), t.get("column_count", 0), first_row)
        # Detailed row dump only at DEBUG level to avoid perf overhead
        if logger.isEnabledFor(logging.DEBUG):
            for ri, row in enumerate(rows):
                logger.debug("[DEDUP]   table[%d] row[%d]: %s", ti, ri, " | ".join(str(c) for c in row)[:200])

    # ── Deduplicate tables ──────────────────────────────────────────────
    # Phase 1: exact signature match (first 6 rows normalised content)
    seen_sigs: set[str] = set()
    phase1: list[dict] = []
    for table in all_tables:
        rows = table.get("rows", [])
        if not rows:
            continue
        sig = _table_rows_signature(rows)
        if sig and sig in seen_sigs:
            logger.info("[DEDUP] Phase1 dropped duplicate (sig match)")
            continue
        if sig:
            seen_sigs.add(sig)
        phase1.append(table)
    logger.info("[DEDUP] Phase1: %d → %d tables", len(all_tables), len(phase1))

    # Phase 2: fuzzy overlap – if ≥50% of a table's normalised rows already
    # appear in a previously-accepted table, treat it as a duplicate.
    def _row_set(tbl: dict) -> set[str]:
        return {
            "|".join(_normalize_keyword(str(c or "")) for c in row)
            for row in tbl.get("rows", [])
            if isinstance(row, list)
        }

    accepted: list[dict] = []
    accepted_rows: list[set[str]] = []
    for table in phase1:
        rs = _row_set(table)
        if not rs:
            continue
        is_dup = False
        for pi, prev_rs in enumerate(accepted_rows):
            overlap = len(rs & prev_rs)
            if overlap >= max(2, len(rs) * 0.5):
                is_dup = True
                break
        if is_dup:
            logger.debug("[DEDUP] Phase2 dropped duplicate")
            continue
        accepted.append(table)
        accepted_rows.append(rs)

    logger.info("[DEDUP] Phase2: %d → %d tables (final)", len(phase1), len(accepted))

    return accepted


__all__ = _export_all()  # pyright: ignore[reportUnsupportedDunderAll]

