from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _to_legacy_ocr_results(ocr_boxes: list[dict] | None) -> list[list[list[Any]]]:
    pages: dict[int, list[list[Any]]] = {}
    for box in ocr_boxes or []:
        page = int(box.get("page", 1) or 1)
        bbox = box.get("bbox") or []
        text = str(box.get("text", "") or "")
        confidence = float(box.get("confidence", 0.0) or 0.0)
        pages.setdefault(page, []).append([bbox, [text, confidence]])
    return [pages[p] for p in sorted(pages.keys())]


def _lines_from_boxes(ocr_boxes: list[dict] | None) -> list[str]:
    return [str(box.get("text", "")).strip() for box in ocr_boxes or [] if str(box.get("text", "")).strip()]


def legacy_extract_fields(document_type: str, ocr_boxes: list[dict] | None) -> dict[str, Any]:
    if not ocr_boxes:
        return {}

    legacy_results = _to_legacy_ocr_results(ocr_boxes)
    if not legacy_results:
        return {}

    try:
        if document_type == "INE":
            from app.legacy_motor.ine_logic import ProcesadorINE

            lines = _lines_from_boxes(ocr_boxes)
            data = ProcesadorINE(lines).obtener_json()
            nombre = data.get("nombre_completo") or " ".join(
                [p for p in [data.get("nombres"), data.get("apellido_paterno"), data.get("apellido_materno")] if p]
            ).strip()
            return {
                "nombre": nombre or None,
                "nombres": data.get("nombres"),
                "apellido_paterno": data.get("apellido_paterno"),
                "apellido_materno": data.get("apellido_materno"),
                "sexo": data.get("sexo"),
                "domicilio": data.get("domicilio"),
                "clave_elector": data.get("clave_elector"),
                "curp": data.get("curp"),
                "anio_registro": data.get("anio_registro"),
                "fecha_nacimiento": data.get("fecha_nacimiento"),
                "seccion": data.get("seccion"),
                "vigencia": data.get("vigencia"),
            }

        if document_type == "ACTA_NACIMIENTO":
            from app.legacy_motor.acta_logic import extraer_datos_acta

            data = extraer_datos_acta(legacy_results)
            return {
                "entidad_registro": data.get("entidad_registro"),
                "municipio_registro": data.get("municipio_registro"),
                "nombre": data.get("nombre"),
                "primer_apellido": data.get("primer_apellido"),
                "segundo_apellido": data.get("segundo_apellido"),
                "sexo": data.get("sexo"),
                "fecha_nacimiento": data.get("fecha_nacimiento"),
                "lugar_nacimiento": data.get("lugar_nacimiento"),
                "anio_registro": data.get("anio_registro"),
                "curp": data.get("curp_detectada"),
            }

        if document_type == "CURP":
            from app.legacy_motor.curp_logic import extraer_datos_curp

            data = extraer_datos_curp(legacy_results)
            return {
                "curp": data.get("clave_curp"),
                "nombre": data.get("nombre"),
                "entidad_registro": data.get("entidad_registro"),
                "fecha_emision": data.get("fecha_emision"),
            }

        if document_type == "NSS":
            from app.legacy_motor.nss_logic import extraer_datos_nss

            data = extraer_datos_nss(legacy_results)
            return {
                "nss": data.get("nss"),
                "nombre": data.get("nombre"),
                "curp": data.get("curp"),
                "fecha_documento": data.get("fecha_documento"),
                "folio_solicitud": data.get("folio_solicitud"),
            }

        if document_type == "CONSTANCIA_SITUACION_FISCAL":
            from app.legacy_motor.csf_logic import extraer_datos_csf

            data = extraer_datos_csf(legacy_results)
            return {
                "rfc": data.get("rfc"),
                "curp": data.get("curp"),
                "nombre": data.get("nombre_completo"),
                "cp": data.get("codigo_postal"),
                "id_cif": data.get("id_cif"),
                "fecha_emision": data.get("fecha_emision"),
                "regimen": data.get("regimen_fiscal"),
            }

        if document_type == "DATOS_BANCARIOS":
            from app.legacy_motor.banco_logic import extraer_datos_bancarios

            data = extraer_datos_bancarios(legacy_results)
            banco = data.get("banco_detectado")
            return {
                "banco": banco if banco and banco != "GENERICO" else None,
                "titular": data.get("titular"),
                "clabe": data.get("clabe"),
                "cuenta": data.get("cuenta"),
            }

        if document_type == "COMPROBANTE_DOMICILIO":
            from app.legacy_motor.domicilio_logic import extraer_datos_domicilio

            data = extraer_datos_domicilio(legacy_results)
            return {
                "domicilio": data.get("direccion_presunta"),
                "cp": data.get("cp_detectado"),
                "proveedor": data.get("servicio_detectado"),
            }
    except Exception:
        logger.exception("legacy_extract_fields failed for document_type=%s", document_type)
        return {}

    return {}
