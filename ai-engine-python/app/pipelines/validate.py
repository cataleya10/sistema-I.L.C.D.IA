from app.utils.validators import (
    validate_clabe,
    validate_curp,
    validate_date,
    validate_nss,
    validate_rfc,
    validate_sex,
    validate_bank,
    validate_folio,
    validate_cp,
    validate_state_code,
    validate_clave_elector,
    validate_seccion,
    validate_person_name,
    validate_generic_text,
    validate_vigencia,
    validate_rfc_homoclave,
)

VALIDATORS = {
    "curp": validate_curp,
    "rfc": validate_rfc_homoclave,
    "nss": validate_nss,
    "clabe": validate_clabe,
    "fecha": validate_date,
    "fecha_nacimiento": validate_date,
    "sexo": validate_sex,
    "banco": validate_bank,
    "folio": validate_folio,
    "cp": validate_cp,
    "entidad_nacimiento": validate_state_code,
    "clave_elector": validate_clave_elector,
    "seccion": validate_seccion,
    "juez": validate_person_name,
    "registro_civil": validate_generic_text,
    "vigencia": validate_vigencia,
}


async def validate_fields(fields):
    for field in fields:
        if field.get("value") is None:
            continue
        if field.get("key") in {"nss", "clabe", "cp", "seccion"}:
            raw = str(field["value"]).upper()
            raw = raw.replace("O", "0").replace("I", "1").replace("L", "1")
            field["value"] = "".join(ch for ch in raw if ch.isdigit())
        validator = VALIDATORS.get(field["key"])
        if validator is None or field.get("value") is None:
            continue
        is_valid, errors = validator(field["value"])
        field["valid"] = is_valid
        field["validation_errors"] = errors
    return fields
