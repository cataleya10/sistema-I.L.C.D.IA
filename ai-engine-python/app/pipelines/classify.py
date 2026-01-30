async def classify_document(image, ocr_text: str, filename: str | None = None):
    text = ocr_text.upper()
    name = (filename or "").upper()
    text = text.replace("\u00a0", " ")
    text = " ".join(text.split())
    compact_text = text.replace(" ", "")
    if (
        "INSTITUTO NACIONAL ELECTORAL" in text
        or "CREDENCIAL PARA VOTAR" in text
        or "INSTITUTONACIONALELECTORAL" in compact_text
        or "CREDENCIALPARAVOTAR" in compact_text
    ):
        return "INE", 0.88
    if "ACTA DE NACIMIENTO" in text or "REGISTRO CIVIL" in text:
        return "ACTA_NACIMIENTO", 0.85
    if (
        "CERTIFICADO DE NACIMIENTO" in text
        or "NUMERO DE CERTIFICADO DE NACIMIENTO" in text
        or "DATOS DE LA PERSONA REGISTRADA" in text
        or "ENTIDAD DE REGISTRO" in text
        or "NUMERO DE ACTA" in text
        or "OFICIALIA" in text
        or "LIBRO" in text
        or "TOMO" in text
    ):
        return "ACTA_NACIMIENTO", 0.85
    if "CLAVE UNICA DE REGISTRO DE POBLACION" in text or "CURP" in text:
        return "CURP", 0.9
    if "INE" in name or "ELECTOR" in name:
        return "INE", 0.9
    if "ACTA" in name or "NACIMIENTO" in name:
        return "ACTA_NACIMIENTO", 0.85
    if "CURP" in name:
        return "CURP", 0.9
    if "NSS" in text or "IMSS" in text or "SEGURIDAD SOCIAL" in text:
        return "NSS", 0.82
    if "CLABE" in text or "BANCO" in text or "CUENTA" in text:
        return "DATOS_BANCARIOS", 0.78
    if (
        "ESTADO DE CUENTA" in text
        or "ESTADODECUENTA" in text
        or "ACCOUNT STATEMENT" in text
        or "BBVA" in text
        or "BANCOMER" in text
        or "BANAMEX" in text
        or "SANTANDER" in text
        or "SCOTIABANK" in text
        or "HSBC" in text
        or "BANORTE" in text
        or "AZTECA" in text
    ):
        return "DATOS_BANCARIOS", 0.8
    if (
        "DOMICILIO" in text
        or "RECIBO" in text
        or "COMISION FEDERAL DE ELECTRICIDAD" in text
        or "CFE" in text
        or "TELMEX" in text
        or "TELCEL" in text
        or "AT&T" in text
        or "TOTALPLAY" in text
        or "IZZI" in text
        or "MEGACABLE" in text
        or "AGUA" in text
        or "PREDIAL" in text
        or "GAS" in text
    ):
        return "COMPROBANTE_DOMICILIO", 0.75
    if "DOMICILIO" in name or "COMPROBANTE" in name or "RECIBO" in name:
        return "COMPROBANTE_DOMICILIO", 0.9
    if "SITUACION FISCAL" in text or "RFC" in text:
        return "CONSTANCIA_SITUACION_FISCAL", 0.86
    if "NSS" in name or "IMSS" in name:
        return "NSS", 0.85
    if "CLABE" in name or "BANCO" in name:
        return "DATOS_BANCARIOS", 0.85
    if "ESTADO DE CUENTA" in name or "ESTADO_CUENTA" in name or "CUENTA" in name:
        return "DATOS_BANCARIOS", 0.8
    if "RFC" in name or "SITUACION" in name:
        return "CONSTANCIA_SITUACION_FISCAL", 0.85
    return "UNKNOWN", 0.5
