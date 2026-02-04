import re


def extraer_datos_domicilio(result_ocr):
    lineas_originales = []
    if result_ocr and result_ocr[0]:
        lineas_originales = [line[1][0].strip() for line in result_ocr[0] if line[1][0].strip()]

    texto_completo = " ".join(lineas_originales).upper()

    es_cfe = "CFE" in texto_completo or "SUMINISTRO ELECTRICO" in texto_completo
    es_agua = any(x in texto_completo for x in ["AGUA POTABLE", "SMAPAC", "JAPAY", "DRENAJE", "ALCANTARILLADO"])

    direccion_final = ""
    cp_final = None

    blacklist_cp = ["06600", "06500", "01210"]

    if es_agua:
        match_dom = re.search(
            r"DOMICILIO[:\.]?\s*([A-Z0-9\s\.\-]+?)(?=(ENTRE|COLONIA|C\.P|MUNICIPIO|$))", texto_completo
        )
        calle = match_dom.group(1).strip() if match_dom else ""

        match_col = re.search(r"COLONIA[:\.]?\s*([A-Z0-9\s\.\-]+?)(?=(C\.P|MUNICIPIO|ENTRE|$))", texto_completo)
        colonia = match_col.group(1).strip() if match_col else ""

        match_cp = re.search(r"C\.P[:\.]?\s*(\d{5})", texto_completo)
        codigo_postal = match_cp.group(1).strip() if match_cp else ""

        partes = [p for p in [calle, colonia, codigo_postal] if p]
        direccion_final = ", ".join(partes)
        cp_final = codigo_postal

    elif es_cfe:
        indice_cp_usuario = -1
        cp_encontrado = ""

        for i, linea in enumerate(lineas_originales):
            match_cp_linea = re.search(r"\b(\d{5})\b", linea)
            if match_cp_linea:
                posible_cp = match_cp_linea.group(1)
                if posible_cp not in blacklist_cp:
                    indice_cp_usuario = i
                    cp_encontrado = posible_cp
                    break

        if indice_cp_usuario != -1:
            cp_final = cp_encontrado

            inicio = max(0, indice_cp_usuario - 2)
            fin = indice_cp_usuario + 1

            bloque_direccion = lineas_originales[inicio:fin]

            lineas_limpias = []
            for l in bloque_direccion:
                l_upper = l.upper()
                if "NO. DE SERVICIO" in l_upper:
                    continue
                if "RMU" in l_upper:
                    continue
                if "CFE" in l_upper and len(l) < 10:
                    continue

                lineas_limpias.append(l)

            direccion_final = " ".join(lineas_limpias)

    if not direccion_final and not cp_final:
        regex_cp_gen = r"\b(\d{5})\b"
        match_gen = re.search(regex_cp_gen, texto_completo)
        if match_gen and match_gen.group(1) not in blacklist_cp:
            cp_final = match_gen.group(1)
            direccion_final = f"Dirección cerca del CP {cp_final} (Extracción manual requerida)"

    if direccion_final:
        direccion_final = re.sub(r"\s+", " ", direccion_final).strip()
        direccion_final = re.sub(r"^[\.,\-: ]+", "", direccion_final)

    return {
        "tipo_documento": "COMPROBANTE_DOMICILIO",
        "servicio_detectado": "CFE" if es_cfe else ("AGUA" if es_agua else "OTRO"),
        "cp_detectado": cp_final,
        "direccion_presunta": direccion_final,
    }
