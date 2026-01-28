async def classify_document(image, ocr_text: str, filename: str | None = None):
    text = ocr_text.upper()
    name = (filename or "").upper()
    if "INSTITUTO NACIONAL ELECTORAL" in text or "CREDENCIAL PARA VOTAR" in text:
        return "INE", 0.88
    if "CURP" in text:
        return "CURP", 0.9
    if "ACTA DE NACIMIENTO" in text:
        return "ACTA_NACIMIENTO", 0.85
    if "INE" in name or "ELECTOR" in name:
        return "INE", 0.9
    if "CURP" in name:
        return "CURP", 0.9
    if "ACTA" in name or "NACIMIENTO" in name:
        return "ACTA_NACIMIENTO", 0.85
    if (
        "DOMICILIO" in text
        or "RECIBO" in text
        or "COMISION FEDERAL DE ELECTRICIDAD" in text
        or "CFE" in text
        or "TELMEX" in text
        or "AGUA" in text
        or "PREDIAL" in text
        or "GAS" in text
    ):
        return "COMPROBANTE_DOMICILIO", 0.75
    if "DOMICILIO" in name or "COMPROBANTE" in name or "RECIBO" in name:
        return "COMPROBANTE_DOMICILIO", 0.9
    if "NSS" in text or "IMSS" in text:
        return "NSS", 0.82
    if "CLABE" in text or "BANCO" in text:
        return "DATOS_BANCARIOS", 0.78
    if "SITUACION FISCAL" in text or "RFC" in text:
        return "CONSTANCIA_SITUACION_FISCAL", 0.86
    if "NSS" in name or "IMSS" in name:
        return "NSS", 0.85
    if "CLABE" in name or "BANCO" in name:
        return "DATOS_BANCARIOS", 0.85
    if "RFC" in name or "SITUACION" in name:
        return "CONSTANCIA_SITUACION_FISCAL", 0.85
    return "UNKNOWN", 0.5
