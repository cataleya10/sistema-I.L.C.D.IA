from thefuzz import fuzz
import re


class ProcesadorCURP:
    def __init__(self, ocr_results):
        self.bloques = []
        if ocr_results and ocr_results[0]:
            for linea in ocr_results[0]:
                coords = linea[0]
                texto = linea[1][0].strip()

                x_vals = [c[0] for c in coords]
                y_vals = [c[1] for c in coords]

                self.bloques.append(
                    {
                        "texto": texto.upper(),
                        "texto_original": texto,
                        "x_min": min(x_vals),
                        "x_max": max(x_vals),
                        "y_min": min(y_vals),
                        "y_max": max(y_vals),
                        "altura": max(y_vals) - min(y_vals),
                        "centro_y": sum(y_vals) / 4,
                        "centro_x": sum(x_vals) / 4,
                    }
                )

        self.datos = {
            "clave_curp": None,
            "nombre": None,
            "entidad_registro": None,
            "fecha_emision": None,
        }

    def ejecutar(self):
        self._buscar_curp_regex()

        if not self.datos["nombre"]:
            self._buscar_relativo("NOMBRE", "nombre", direccion="abajo")

        self._buscar_relativo(["ENTIDAD DE REGISTRO", "ENTIDAD DE REGISTRE"], "entidad_registro", direccion="derecha")
        self._buscar_fecha_emision()

        return self.datos

    def _buscar_relativo(self, etiquetas_posibles, clave_json, direccion="abajo"):
        if isinstance(etiquetas_posibles, str):
            etiquetas_posibles = [etiquetas_posibles]

        etiqueta_bloque = None
        mejor_score = 0

        for bloque in self.bloques:
            for etiq in etiquetas_posibles:
                score = fuzz.ratio(bloque["texto"], etiq)
                if score > 85 and score > mejor_score:
                    mejor_score = score
                    etiqueta_bloque = bloque

        if not etiqueta_bloque:
            return

        candidatos = []
        stop_words = ["CLAVE", "NOMBRE", "ENTIDAD", "REGISTRO", "INSCRIPCION", "FOLIO", "ESTADOS", "UNIDOS", "MEXICANOS"]

        for bloque in self.bloques:
            if bloque == etiqueta_bloque:
                continue

            if any(sw in bloque["texto"] for sw in stop_words):
                continue

            distancia = 9999
            es_valido = False

            if direccion == "abajo":
                solapamiento_x = min(bloque["x_max"], etiqueta_bloque["x_max"]) - max(bloque["x_min"], etiqueta_bloque["x_min"])
                if solapamiento_x <= 0:
                    continue

                if bloque["y_min"] >= etiqueta_bloque["y_max"]:
                    distancia = bloque["y_min"] - etiqueta_bloque["y_max"]
                    es_valido = distancia < (etiqueta_bloque["altura"] * 2.5)

            elif direccion == "derecha":
                centro_bloque = bloque["centro_y"]
                centro_etiqueta = etiqueta_bloque["centro_y"]
                diferencia_y = abs(centro_bloque - centro_etiqueta)

                if diferencia_y > (etiqueta_bloque["altura"] * 0.8):
                    continue

                if bloque["x_min"] >= etiqueta_bloque["x_max"]:
                    distancia = bloque["x_min"] - etiqueta_bloque["x_max"]
                    es_valido = distancia < 500

            if es_valido:
                candidatos.append((distancia, bloque["texto_original"]))

        candidatos.sort(key=lambda x: x[0])
        if candidatos:
            self.datos[clave_json] = candidatos[0][1]

    def _buscar_curp_regex(self):
        texto_completo = " ".join([b["texto"] for b in self.bloques])
        match = re.search(r"[A-Z]{4}\d{6}[HM][A-Z]{2,5}[A-Z0-9]{2}", texto_completo)
        if match:
            self.datos["clave_curp"] = match.group(0)

    def _buscar_fecha_emision(self):
        texto_completo_original = " ".join([b["texto_original"] for b in self.bloques])

        patron_cdmx = r"(?i)(Ciudad de M.xico,? a\s+\d{1,2}\s+de\s+[a-zA-ZáéíóúÁÉÍÓÚñÑ]+\s+de\s+\d{4})"
        match = re.search(patron_cdmx, texto_completo_original)
        if match:
            self.datos["fecha_emision"] = match.group(1)
            return

        patron_generico = r"(?i)(,\s*a\s+\d{1,2}\s+de\s+[a-zA-ZáéíóúÁÉÍÓÚñÑ]+\s+de\s+\d{4})"
        match_gen = re.search(patron_generico, texto_completo_original)
        if match_gen:
            texto_fecha = match_gen.group(1).lstrip(",").strip()
            self.datos["fecha_emision"] = texto_fecha


def extraer_datos_curp(ocr_results):
    procesador = ProcesadorCURP(ocr_results)
    return procesador.ejecutar()
