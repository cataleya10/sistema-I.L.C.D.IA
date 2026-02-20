import re
from typing import Any


def extraer_datos_bancarios(result_ocr: Any) -> dict[str, str | None]:
    lineas: list[str] = []
    if result_ocr and result_ocr[0]:
        lineas = [line[1][0].strip() for line in result_ocr[0]]

    datos: dict[str, str | None] = {
        "banco_detectado": "GENERICO",
        "titular": None,
        "clabe": None,
        "cuenta": None,
    }

    texto_completo = " ".join(lineas).upper()

    match_clabe = re.search(r"\b(\d{18})\b", texto_completo.replace(" ", ""))

    if match_clabe:
        datos["clabe"] = match_clabe.group(1)
    else:
        for i, linea in enumerate(lineas):
            linea_upper = linea.upper()
            if "CLABE" in linea_upper:
                numeros = re.findall(r"\d{18}", linea)
                if numeros:
                    datos["clabe"] = numeros[0]
                    break
                if i + 1 < len(lineas):
                    siguiente = lineas[i + 1].replace(" ", "")
                    numeros_sig = re.findall(r"\d{18}", siguiente)
                    if numeros_sig:
                        datos["clabe"] = numeros_sig[0]
                        break

    for i, linea in enumerate(lineas):
        linea_upper = linea.upper()

        if ("CUENTA" in linea_upper or "CONTRATO" in linea_upper) and "ESTADO" not in linea_upper:
            texto_a_analizar = linea + " " + (lineas[i + 1] if i + 1 < len(lineas) else "")

            numeros = re.findall(r"\b\d{10,12}\b", texto_a_analizar)

            for num in numeros:
                if num != datos["clabe"]:
                    datos["cuenta"] = num
                    break
            if datos["cuenta"]:
                break

    for i, linea in enumerate(lineas):
        linea_upper = linea.upper()

        if "NOMBRE" in linea_upper or "TITULAR" in linea_upper or "CLIENTE" in linea_upper:
            if len(linea) < 15:
                if i + 1 < len(lineas):
                    datos["titular"] = lineas[i + 1]
                    break
            else:
                limpia = re.sub(r"(NOMBRE|TITULAR|CLIENTE|DEL|:|\.)", "", linea_upper).strip()
                if len(limpia) > 3:
                    datos["titular"] = limpia
                    break

    return datos
