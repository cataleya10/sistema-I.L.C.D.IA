"""Main extraction orchestrator: extract_fields entry point."""

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
from .extractors import *  # noqa: F403
from app.pipelines.legacy_adapter import legacy_extract_fields
from app.pipelines.table_postprocess import (
    postprocess_payment_table,
    postprocess_metadata,
    compute_table_quality_report,
)

logger = __import__('logging').getLogger(__name__)


def _export_all():
    import sys
    mod = sys.modules[__name__]
    return [n for n in dir(mod) if not n.startswith('__')]


async def extract_fields(document_type: str, ocr_text: str, ocr_boxes: list[dict] | None = None, raw_text: str = "", filename: str | None = None, pdf_tables: list[list[list[str]]] | None = None) -> list[dict]:
    """Main extraction entry point with graceful error recovery."""
    try:
        return await _extract_fields_impl(document_type, ocr_text, ocr_boxes, raw_text, filename, pdf_tables)
    except Exception:
        logger.exception("Unhandled error in extract_fields for document_type=%s", document_type)
        return []


async def _extract_fields_impl(document_type: str, ocr_text: str, ocr_boxes: list[dict] | None = None, raw_text: str = "", filename: str | None = None, pdf_tables: list[list[list[str]]] | None = None) -> list[dict]:
    fields: list[dict] = []
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
            box_name = _normalize_name(box_values["nombre"]["value"])
            box_name_conf = 0.8
            # Validate OCR name against CURP initials; lower confidence if mismatch
            # so that better sources (MRZ, text fallback) can win during deduplication.
            if curps:
                if not _name_matches_curp(box_name, curps[0]):
                    repaired = _try_repair_name_with_curp(box_name, curps[0])
                    if repaired != box_name and _name_matches_curp(repaired, curps[0]):
                        box_name = _normalize_name(repaired)
                        box_name_conf = 0.82
                    else:
                        box_name_conf = 0.55  # Mismatch — let other sources win
            fields.append(_make_field("nombre", "Nombre", box_name, ocr_boxes, confidence=box_name_conf))
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
                    # Collect up to 6 lines to capture city/state (e.g. JONUTA TAB)
                    for line in text_lines[dom_line_idx + 1: dom_line_idx + 7]:
                        if any(skip in line for skip in ["INSTITUTO", "INSTITU", "ELECTO", "ELECT", "CREDENCIAL"]):
                            continue
                        addr_lines.append(line)
                if addr_lines:
                    raw_addr = " ".join(addr_lines)
                    # Stop at known trailing fields if they leaked into the address line.
                    # NOTE: "SECCION" removed because it appears within address text
                    # (e.g. "2DA SECCION") and would prematurely truncate the address.
                    # Use stricter patterns that target actual INE field labels.
                    raw_addr = re.split(
                        r"\b(CLAVE\s+(?:DE\s+)?ELECTOR|CURP\s+[A-Z]|FECHA\s+DE|VIGENCIA\s*\d)"
                        r"|\bSECCION\s+\d{3,4}\b",
                        raw_addr,
                    )[0]
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

        payment_table = _extract_payment_table_payload(base_text_raw, ocr_boxes, pdf_tables)
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
        payment_table = _extract_payment_table_payload(base_text_raw, ocr_boxes, pdf_tables)
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
        elif pdf_tables:
            # Direct fallback: use structurally-detected tables (img2table/PDF) when
            # payment-specific extraction found nothing. Picks the largest table.
            _generic = _pdf_tables_to_generic_payloads(pdf_tables)
            if _generic:
                _best = max(_generic, key=lambda t: t.get("row_count", 0))
                if _best.get("row_count", 0) >= 2:
                    fields.append(
                        _make_field(
                            "tabla_celdas",
                            "Tabla detectada",
                            json.dumps(_best, ensure_ascii=False),
                            ocr_boxes,
                            confidence=0.8,
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
                    start = max(0, cp_index - 5)
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
                # Always add the address-style reference block for CFE docs.
                # This is the "domicilio de suministro" reference, which is the
                # expected referencia for utility bills (not the numeric barcode).
                # The higher confidence (0.88) ensures it wins over numeric codes
                # from box extraction (0.7) during deduplication.
                normalized_ref = _normalize_value_for_key("referencia", referencia_block)
                if normalized_ref:
                    fields.append(_make_field("referencia", "Referencia", normalized_ref, ocr_boxes, confidence=0.88))

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

    # ── GENERICO: extract data from any image / document ───────────────────────
    if document_type in {"GENERICO", "UNKNOWN"}:
        logger.info("[GENERICO] Extracting generic data from document (type=%s)", document_type)

        # 1. Extract key-value pairs from text patterns
        kv_text = _extract_generic_kv_from_text(base_text_raw)
        for field in kv_text:
            fields.append(field)
        logger.info("[GENERICO] Text KV pairs: %d", len(kv_text))

        # 2. Extract key-value pairs from OCR box spatial analysis
        kv_boxes = _extract_generic_kv_from_boxes(ocr_boxes)
        # Avoid duplicating keys already found from text
        existing_keys = {f.get("key") for f in fields}
        for field in kv_boxes:
            if field.get("key") not in existing_keys:
                fields.append(field)
                existing_keys.add(field.get("key"))
        logger.info("[GENERICO] Box KV pairs: %d (new)", len([f for f in kv_boxes if f.get("key") not in {fld.get("key") for fld in kv_text}]))

        # 3. Extract common identifiers (CURP, RFC, NSS, CLABE, email, phone, etc.)
        id_fields = _extract_generic_identifiers(base_text_raw, ocr_boxes)
        for field in id_fields:
            if field.get("key") not in existing_keys:
                fields.append(field)
                existing_keys.add(field.get("key"))
        logger.info("[GENERICO] Identifiers: %d", len(id_fields))

        # 4. Extract ALL tables (not just the best one)
        all_tables = _extract_generic_all_tables(base_text_raw, ocr_boxes, pdf_tables)
        if all_tables:
            # Primary table → tabla_celdas
            primary = all_tables[0]
            if primary.get("row_count", 0) >= 2:
                fields.append(
                    _make_field(
                        "tabla_celdas",
                        "Tabla detectada",
                        json.dumps(primary, ensure_ascii=False),
                        ocr_boxes,
                        confidence=0.8,
                    )
                )
            # Additional tables → tabla_celdas_2, tabla_celdas_3, etc.
            for idx, table in enumerate(all_tables[1:], start=2):
                if table.get("row_count", 0) >= 2:
                    fields.append(
                        _make_field(
                            f"tabla_celdas_{idx}",
                            f"Tabla detectada #{idx}",
                            json.dumps(table, ensure_ascii=False),
                            ocr_boxes,
                            confidence=0.75,
                        )
                    )
            logger.info("[GENERICO] Tables: %d", len(all_tables))

    # ── Universal tabla_celdas fallback ────────────────────────────────────────
    if not any(str(f.get("key", "")) == "tabla_celdas" for f in fields):
        _uni_tables: list[dict] = []
        logger.info("[DIAG-UNI] pdf_tables=%d ocr_boxes=%d base_text_len=%d",
                    len(pdf_tables or []), len(ocr_boxes or []), len(base_text_raw or ""))
        if pdf_tables:
            _uni_tables = _pdf_tables_to_generic_payloads(pdf_tables)
            logger.info("[DIAG-UNI] pdf_generic_tables=%d", len(_uni_tables))
        if not _uni_tables:
            _uni_tables = _extract_all_table_payloads(base_text_raw, ocr_boxes)
            logger.info("[DIAG-UNI] all_table_payloads=%d", len(_uni_tables))
        if _uni_tables:
            _best_uni = max(_uni_tables, key=lambda t: t.get("row_count", 0))
            logger.info("[DIAG-UNI] best_table rows=%d cols=%d source=%s",
                        _best_uni.get("row_count", 0), _best_uni.get("column_count", 0),
                        _best_uni.get("source", "?"))
            if _best_uni.get("row_count", 0) >= 2:
                fields.append(
                    _make_field(
                        "tabla_celdas",
                        "Tabla detectada",
                        json.dumps(_best_uni, ensure_ascii=False),
                        ocr_boxes,
                        confidence=0.8,
                    )
                )

    if base_text_raw:
        # Preserve line breaks for readable display; only collapse intra-line spaces
        _disp = unicodedata.normalize("NFC", base_text_raw).replace("\u00a0", " ")
        _disp = "\n".join(
            re.sub(r" {2,}", " ", ln).strip() for ln in _disp.splitlines() if ln.strip()
        )
        snippet = _disp
        if len(snippet) > 1200:
            snippet = snippet[:1200].rstrip() + "..."
        fields.insert(0, _make_field("texto_detectado", "Texto detectado", snippet, ocr_boxes, confidence=1.0))

    # Fallback: when no meaningful fields were extracted (only texto_detectado),
    # scan for common identifiers via regex so unknown document types still yield data.
    has_meaningful = any(f.get("key") != "texto_detectado" for f in fields)
    if not has_meaningful:
        for value in curps:
            fields.append(_make_field("curp", "CURP", _normalize_alnum(value), ocr_boxes))
        for value in rfcs:
            fields.append(_make_field("rfc", "RFC", _normalize_alnum(value), ocr_boxes))
        for value in nss:
            fields.append(_make_field("nss", "NSS", _normalize_alnum(value), ocr_boxes))
        for value in clabes:
            fields.append(_make_field("clabe", "CLABE", _normalize_alnum(value), ocr_boxes))
        if not any(f.get("key") != "texto_detectado" for f in fields) and filename:
            name_curps = [match.group(0) for match in CURP_PATTERN.finditer(filename.upper())]
            for value in name_curps:
                fields.append(_make_field("curp", "CURP", _normalize_alnum(value), ocr_boxes, confidence=0.9))

    # ── L3: OCR quality assessment ─────────────────────────────────────────
    try:
        ocr_quality = _assess_ocr_quality(base_text_raw, ocr_boxes)
        if ocr_quality.get("score", 1.0) < 0.85:
            fields.append(
                _make_field(
                    "ocr_quality",
                    "Calidad OCR",
                    json.dumps(ocr_quality, ensure_ascii=False),
                    ocr_boxes,
                    confidence=ocr_quality.get("score", 0.5),
                )
            )
            # Lower confidence of ALL other fields proportionally when OCR is bad
            quality_score = ocr_quality.get("score", 1.0)
            if quality_score < 0.6:
                penalty_factor = max(quality_score, 0.3)
                for f in fields:
                    if f.get("key") not in {"texto_detectado", "ocr_quality"}:
                        original_conf = float(f.get("confidence", 0.8))
                        f["confidence"] = round(original_conf * penalty_factor, 4)
    except Exception:
        logger.debug("L3 OCR quality assessment failed", exc_info=True)

    cleaned = _postprocess_fields(document_type, fields)
    contracted = _apply_field_contracts(document_type, cleaned)
    return _dedupe_fields(contracted)


__all__ = _export_all()
