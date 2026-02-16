from app.legacy_motor.fuzzy import fuzz
import re
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ProcesadorActa:
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
                        "centro_x": sum(x_vals) / 4,
                        "centro_y": sum(y_vals) / 4,
                    }
                )

        self.datos = {
            "entidad_registro": None,
            "municipio_registro": None,
            "nombre": None,
            "primer_apellido": None,
            "segundo_apellido": None,
            "sexo": None,
            "fecha_nacimiento": None,
            "lugar_nacimiento": None,
            "anio_registro": None,
            "curp_detectada": None,
        }

    def ejecutar(self):
        self._buscar_relativo(["ENTIDAD DE REGISTRO", "ENTIDAD DE REGISTRE"], "entidad_registro", direccion="abajo")
        self._buscar_relativo(["MUNICIPIO DE REGISTRO", "MUNICIPIO"], "municipio_registro", direccion="abajo")

        self._buscar_relativo(["NOMBRE", "NOMBRE(S)", "NOMBRES"], "nombre", direccion="arriba")
        self._buscar_relativo(["PRIMER APELLIDO", "1ER APELLIDO"], "primer_apellido", direccion="arriba")
        self._buscar_relativo(["SEGUNDO APELLIDO", "2DO APELLIDO"], "segundo_apellido", direccion="arriba")
        self._buscar_relativo(["LUGAR DE NACIMIENTO"], "lugar_nacimiento", direccion="arriba")

        self._buscar_sexo_contextual()
        self._buscar_fecha_nacimiento()
        self._buscar_globales()
        self._procesar_curp()

        return self.datos

    def _buscar_relativo(self, etiquetas_posibles, clave_json, direccion="abajo"):
        if isinstance(etiquetas_posibles, str):
            etiquetas_posibles = [etiquetas_posibles]

        etiqueta_bloque = None
        mejor_score = 0

        for bloque in self.bloques:
            for etiqueta in etiquetas_posibles:
                score = fuzz.ratio(bloque["texto"], etiqueta)
                if score > 85 and score > mejor_score:
                    mejor_score = score
                    etiqueta_bloque = bloque

        if not etiqueta_bloque:
            return

        candidatos = []
        stop_words = [
            "NOMBRE",
            "APELLIDO",
            "FECHA",
            "LUGAR",
            "NACIMIENTO",
            "SEXO",
            "ENTIDAD",
            "MUNICIPIO",
            "DATOS",
            "FILIACION",
            "REGISTRADA",
            "NACIONALIDAD",
            "CURP",
            "CERTIFICADO",
            "ELECTRONICO",
            "CLAVE",
        ]

        for bloque in self.bloques:
            if bloque == etiqueta_bloque:
                continue

            es_etiqueta = False
            for sw in stop_words:
                if fuzz.partial_ratio(sw, bloque["texto"]) > 90:
                    es_etiqueta = True
                    break
            if es_etiqueta:
                continue

            solapamiento_x = min(bloque["x_max"], etiqueta_bloque["x_max"]) - max(bloque["x_min"], etiqueta_bloque["x_min"])
            if solapamiento_x <= 0:
                continue

            distancia = 9999
            es_valido = False

            tolerancia = etiqueta_bloque["altura"] * 3.5

            if direccion == "abajo":
                if bloque["y_min"] >= etiqueta_bloque["y_max"]:
                    distancia = bloque["y_min"] - etiqueta_bloque["y_max"]
                    es_valido = distancia < tolerancia

            elif direccion == "arriba":
                if bloque["y_max"] <= etiqueta_bloque["y_min"]:
                    distancia = etiqueta_bloque["y_min"] - bloque["y_max"]
                    es_valido = distancia < tolerancia

            if es_valido:
                candidatos.append((distancia, bloque["texto_original"]))

        candidatos.sort(key=lambda x: x[0])

        if candidatos:
            self.datos[clave_json] = candidatos[0][1]

    def _buscar_sexo_contextual(self):
        for bloque in self.bloques:
            if bloque["texto"] in ["HOMBRE", "MUJER", "MASCULINO", "FEMENINO"]:
                self.datos["sexo"] = bloque["texto_original"]
                return

    def _buscar_fecha_nacimiento(self):
        texto_completo = " ".join([b["texto"] for b in self.bloques])
        match = re.search(r"(\d{2}/\d{2}/\d{4})", texto_completo)
        if match:
            self.datos["fecha_nacimiento"] = match.group(1)

    def _buscar_globales(self):
        texto_completo = " ".join([b["texto"] for b in self.bloques])

        match_anio = re.search(r"DE\s+(20\d{2}|19\d{2})", texto_completo)
        if match_anio:
            self.datos["anio_registro"] = match_anio.group(1)

        match_curp = re.search(r"[A-Z]{4}\d{6}[HM][A-Z]{2,5}[A-Z0-9]{3}", texto_completo)
        if match_curp:
            self.datos["curp_detectada"] = match_curp.group(0)

    def _procesar_curp(self):
        curp = self.datos["curp_detectada"]
        if not curp:
            return

        if not self.datos["fecha_nacimiento"]:
            try:
                aa, mm, dd = curp[4:6], curp[6:8], curp[8:10]
                anio_actual = int(str(datetime.now().year)[2:])
                siglo = "20" if int(aa) <= anio_actual else "19"
                self.datos["fecha_nacimiento"] = f"{dd}/{mm}/{siglo}{aa}"
            except Exception:
                logger.exception("No se pudo inferir fecha_nacimiento desde CURP")

        if not self.datos["sexo"]:
            self.datos["sexo"] = "HOMBRE" if curp[10] == "H" else "MUJER"

        mapa_entidades = {
            "AS": "AGUASCALIENTES",
            "BC": "BAJA CALIFORNIA",
            "BS": "BAJA CALIFORNIA SUR",
            "CC": "CAMPECHE",
            "CL": "COAHUILA",
            "CM": "COLIMA",
            "CS": "CHIAPAS",
            "CH": "CHIHUAHUA",
            "DF": "CIUDAD DE MEXICO",
            "DG": "DURANGO",
            "GT": "GUANAJUATO",
            "GR": "GUERRERO",
            "HG": "HIDALGO",
            "JC": "JALISCO",
            "MC": "MEXICO",
            "MN": "MICHOACAN",
            "MS": "MORELOS",
            "NT": "NAYARIT",
            "NL": "NUEVO LEON",
            "OC": "OAXACA",
            "PL": "PUEBLA",
            "QT": "QUERETARO",
            "QR": "QUINTANA ROO",
            "SP": "SAN LUIS POTOSI",
            "SL": "SINALOA",
            "SR": "SONORA",
            "TC": "TABASCO",
            "TS": "TAMAULIPAS",
            "TL": "TLAXCALA",
            "VZ": "VERACRUZ",
            "YN": "YUCATAN",
            "ZS": "ZACATECAS",
        }
        if not self.datos["entidad_registro"]:
            clave = curp[11:13]
            if clave in mapa_entidades:
                self.datos["entidad_registro"] = mapa_entidades[clave]


def extraer_datos_acta(ocr_results):
    procesador = ProcesadorActa(ocr_results)
    return procesador.ejecutar()
