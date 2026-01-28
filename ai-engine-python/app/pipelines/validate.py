from app.utils.validators import (
    validate_clabe,
    validate_curp,
    validate_date,
    validate_nss,
    validate_rfc,
)

VALIDATORS = {
    "curp": validate_curp,
    "rfc": validate_rfc,
    "nss": validate_nss,
    "clabe": validate_clabe,
    "fecha": validate_date,
}


async def validate_fields(fields):
    for field in fields:
        validator = VALIDATORS.get(field["key"])
        if validator is None or field.get("value") is None:
            continue
        is_valid, errors = validator(field["value"])
        field["valid"] = is_valid
        field["validation_errors"] = errors
    return fields
