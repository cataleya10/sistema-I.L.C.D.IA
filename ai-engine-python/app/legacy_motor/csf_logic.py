from app.legacy_motor.fuzzy import fuzz
import re


class ProcesadorCSF:
    def __init__(self, ocr_results):
        self.bloques = []
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

        self.datos = {
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
        return None

    def _es_stop_word(self, texto):
        for sw in self.stop_words:
            if fuzz.partial_ratio(sw, texto) > 90:
                return True
        return False

    def _buscar_valor_tabla(self, etiquetas):
        return None

    def _encontrar_etiqueta_fuzzy(self, keyword):
        return None


def extraer_datos_csf(ocr_results):
    procesador = ProcesadorCSF(ocr_results)
    return procesador.ejecutar()
