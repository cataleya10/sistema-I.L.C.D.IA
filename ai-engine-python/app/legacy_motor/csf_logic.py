from app.legacy_motor.fuzzy import fuzz
import re
from typing import Any


class ProcesadorCSF:
    def __init__(self, ocr_results):
        self.bloques: list[dict[str, Any]] = []
        if ocr_results and ocr_results[0]:
            for linea in ocr_results[0]:
                coords = linea[0]
                texto = linea[1][0].strip()
                texto_limpio = re.sub(r"[^a-zA-Z0-9\s]", "", texto.upper())

                x_vals = [c[0] for c in coords]
                y_vals = [c[1] for c in coords]

                self.bloques.append(
                    {
                        "texto": texto,
                        "texto_upper": texto.upper(),
                        "texto_limpio": texto_limpio,
                        "x_min": min(x_vals),
                        "x_max": max(x_vals),
                        "y_min": min(y_vals),
                        "y_max": max(y_vals),
                        "centro_x": sum(x_vals) / 4,
                        "centro_y": sum(y_vals) / 4,
                        "altura": max(y_vals) - min(y_vals),
                    }
                )

        self.datos: dict[str, str | None] = {
            "rfc": None,
            "curp": None,
            "nombre_completo": None,
            "codigo_postal": None,
            "id_cif": None,
            "fecha_emision": None,
            "regimen_fiscal": None,
        }

        self.stop_words = [
            "NOMBRE",
            "APELLIDO",
            "RFC",
            "CURP",
            "FECHA",
            "OPERACIONES",
            "ESTATUS",
            "PADRON",
            "DOMICILIO",
            "CALLE",
            "COLONIA",
            "NUMERO",
            "REGIMEN",
            "OBLIGACIONES",
            "SAT",
            "HACIENDA",
            "CONSTANCIA",
            "CEDULA",
            "IDENTIFICACION",
            "FISCAL",
            "DENOMINACION",
            "RAZON",
            "SOCIAL",
            "REGISTRO",
            "FEDERAL",
            "CONTRIBUYENTES",
            "LUGAR",
            "EMISION",
        ]

    def ejecutar(self):
        self._buscar_rfc()
        self._buscar_curp()

        self._buscar_nombre_en_cif()
        if not self.datos["nombre_completo"]:
            self._reconstruir_nombre_tabla()

        self._buscar_cp()
        self._buscar_id_cif()
        self._buscar_fecha_emision()
        self._buscar_regimen()

        return self.datos

    def _buscar_rfc(self):
        texto_unido = " ".join([b["texto_upper"] for b in self.bloques])
        match = re.search(r"[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3}", texto_unido)
        if match:
            self.datos["rfc"] = match.group(0)

    def _buscar_curp(self):
        texto_unido = " ".join([b["texto_upper"] for b in self.bloques])
        match = re.search(r"[A-Z]{4}\d{6}[HM][A-Z]{2,5}[A-Z0-9]{2}", texto_unido)
        if match:
            self.datos["curp"] = match.group(0)

    def _buscar_nombre_en_cif(self):
        techo = None
        suelo = None

        for b in self.bloques:
            if "REGISTRO" in b["texto_upper"] and "FEDERAL" in b["texto_upper"]:
                techo = b
            elif self.datos["rfc"] and self.datos["rfc"] in b["texto_upper"]:
                techo = b

            if "DENOMINACION" in b["texto_upper"] or "RAZON" in b["texto_upper"]:
                suelo = b

        if techo and suelo:
            candidatos = []
            for b in self.bloques:
                if b == techo or b == suelo:
                    continue

                if b["centro_y"] > techo["y_max"] and b["centro_y"] < suelo["y_min"]:
                    if self.datos["rfc"] and self.datos["rfc"] in b["texto_upper"]:
                        continue
                    if self._es_stop_word(b["texto_upper"]):
                        continue

                    candidatos.append(b)

            candidatos.sort(key=lambda x: x["y_min"])
            partes = [b["texto_upper"] for b in candidatos]
            if partes:
                self.datos["nombre_completo"] = " ".join(partes)

    def _reconstruir_nombre_tabla(self):
        nombres = self._buscar_valor_tabla(["NOMBRE (S)", "NOMBRE"])
        apellido1 = self._buscar_valor_tabla(["PRIMER APELLIDO"])
        apellido2 = self._buscar_valor_tabla(["SEGUNDO APELLIDO"])
        partes = [p for p in [nombres, apellido1, apellido2] if p and not self._es_stop_word(p)]
        if partes:
            self.datos["nombre_completo"] = " ".join(partes)

    def _buscar_cp(self):
        texto_unido = " ".join([b["texto_upper"] for b in self.bloques])
        match = re.search(r"(?:CP|CODIGO|POSTAL)[\s\.:]*(\d{5})", texto_unido)
        if match:
            self.datos["codigo_postal"] = match.group(1)
            return
        matches = re.findall(r"\b(\d{5})\b", texto_unido)
        for m in matches:
            if self.datos["id_cif"] and m in self.datos["id_cif"]:
                continue
            self.datos["codigo_postal"] = m
            break

    def _buscar_fecha_emision(self):
        texto_unido = " ".join([b["texto_upper"] for b in self.bloques])

        match = re.search(r"A\s*(\d{1,2})\s*[DE]*\s*([A-Z]+)\s*[DE]*\s*(\d{4})", texto_unido)

        if match:
            dia, mes, anio = match.groups()
            self.datos["fecha_emision"] = f"{dia} DE {mes} DE {anio}"
        else:
            match_normal = re.search(r"A\s+(\d{1,2}\s+DE\s+[A-Z]+\s+DE\s+\d{4})", texto_unido)
            if match_normal:
                self.datos["fecha_emision"] = match_normal.group(1)

    def _buscar_id_cif(self):
        texto_unido = " ".join([b["texto"] for b in self.bloques])
        match = re.search(r"idCIF\s*[:\.]?\s*(\d+)", texto_unido, re.IGNORECASE)
        if match:
            self.datos["id_cif"] = match.group(1)

    def _buscar_regimen(self):
        # Prefer table-like extraction first, then fallback to regex over full text.
        regimen = self._buscar_valor_tabla(["REGIMEN FISCAL", "REGIMEN", "OBLIGACIONES FISCALES"])
        if not regimen:
            texto_unido = " ".join([b["texto_upper"] for b in self.bloques])
            match = re.search(
                r"(?:REGIMEN(?:\s+FISCAL)?|OBLIGACIONES\s+FISCALES)\s*[:\-]?\s*([A-Z0-9 /,.-]{4,120})",
                texto_unido,
            )
            if match:
                regimen = match.group(1).strip()

        if not regimen:
            return

        cortes = [
            "DOMICILIO",
            "CODIGO",
            "POSTAL",
            "PAGINA",
            "CONTACTO",
            "SAT",
            "HACIENDA",
            "RFC",
            "CURP",
        ]
        regimen_limpio = regimen.upper()
        for token in cortes:
            idx = regimen_limpio.find(token)
            if idx > 0:
                regimen_limpio = regimen_limpio[:idx].strip()
                break

        regimen_limpio = re.sub(r"\s+", " ", regimen_limpio).strip(" .,:;-")
        if regimen_limpio and not self._es_stop_word(regimen_limpio):
            self.datos["regimen_fiscal"] = regimen_limpio

    def _es_stop_word(self, texto):
        for sw in self.stop_words:
            if fuzz.partial_ratio(sw, texto) > 90:
                return True
        return False

    def _buscar_valor_tabla(self, etiquetas):
        if isinstance(etiquetas, str):
            etiquetas = [etiquetas]

        etiqueta_bloque = None
        mejor_score = 0
        for etiqueta in etiquetas:
            candidato = self._encontrar_etiqueta_fuzzy(etiqueta)
            if not candidato:
                continue
            score = max(
                fuzz.ratio(candidato["texto_upper"], etiqueta.upper()),
                fuzz.partial_ratio(etiqueta.upper(), candidato["texto_upper"]),
            )
            if score > mejor_score:
                mejor_score = score
                etiqueta_bloque = candidato

        if not etiqueta_bloque:
            return None

        candidatos: list[tuple[float, str]] = []
        altura_ref = max(float(etiqueta_bloque.get("altura", 0) or 0), 10.0)
        for bloque in self.bloques:
            if bloque == etiqueta_bloque:
                continue

            texto_valor = bloque["texto_upper"].strip()
            if not texto_valor or self._es_stop_word(texto_valor):
                continue

            dy = abs(bloque["centro_y"] - etiqueta_bloque["centro_y"])
            # Same visual row, value usually to the right.
            if dy <= altura_ref * 1.5 and bloque["x_min"] >= etiqueta_bloque["x_min"]:
                distancia = abs(bloque["x_min"] - etiqueta_bloque["x_max"])
                candidatos.append((distancia, texto_valor))
                continue

            # Value right below the label with some horizontal overlap.
            overlap = min(bloque["x_max"], etiqueta_bloque["x_max"]) - max(bloque["x_min"], etiqueta_bloque["x_min"])
            if overlap > 0 and bloque["y_min"] >= etiqueta_bloque["y_max"] and (bloque["y_min"] - etiqueta_bloque["y_max"]) <= altura_ref * 4:
                distancia = (bloque["y_min"] - etiqueta_bloque["y_max"]) + 5
                candidatos.append((distancia, texto_valor))

        if not candidatos:
            return None

        candidatos.sort(key=lambda item: item[0])
        valor = candidatos[0][1]
        valor = re.sub(r"\s+", " ", valor).strip(" .,:;-")
        return valor or None

    def _encontrar_etiqueta_fuzzy(self, keyword):
        keyword_u = str(keyword or "").upper().strip()
        if not keyword_u:
            return None

        mejor_bloque = None
        mejor_score = 0
        for bloque in self.bloques:
            texto = bloque["texto_upper"]
            score = max(fuzz.ratio(texto, keyword_u), fuzz.partial_ratio(keyword_u, texto))
            if score > mejor_score:
                mejor_score = score
                mejor_bloque = bloque

        return mejor_bloque if mejor_score >= 80 else None


def extraer_datos_csf(ocr_results):
    procesador = ProcesadorCSF(ocr_results)
    return procesador.ejecutar()
