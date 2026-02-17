import re
from typing import Any, Dict, List, Optional

try:
    from .fuzzy import process, fuzz
except Exception:
    from app.legacy_motor.fuzzy import process, fuzz

try:
    from names_dataset import NameDataset
except Exception:
    NameDataset = None

try:
    from .sepomex_loader import SepomexLoader
except Exception:
    SepomexLoader = None

print("--- Cargando Recursos de IA ---")
try:
    if NameDataset is not None:
        GLOBAL_NAME_DATASET: Optional[Any] = NameDataset()
    else:
        GLOBAL_NAME_DATASET = None
except Exception:
    GLOBAL_NAME_DATASET = None

try:
    if SepomexLoader:
        GLOBAL_SEPOMEX: Optional[Any] = SepomexLoader()
    else:
        GLOBAL_SEPOMEX = None
except Exception:
    GLOBAL_SEPOMEX = None
print("--- Recursos Listos ---")


class ProcesadorINE:
    def __init__(self, lista_texto: List[str]):
        self.lista_texto = [t.strip() for t in lista_texto if t.strip()]
        self.texto_completo = " ".join(self.lista_texto).upper()

    def _limpiar_mrz_nombre(self, texto_mrz: str) -> str:
        return texto_mrz.replace("<<", " ").replace("<", " ").strip()

    def _buscar_indice_difuso(self, palabra_clave: str, umbral: int = 80) -> int:
        for i, linea in enumerate(self.lista_texto):
            if palabra_clave in linea.upper():
                return i
            if fuzz.token_set_ratio(palabra_clave, linea.upper()) > umbral:
                return i
        return -1

    def _es_nombre_real_ia(self, palabra: str) -> bool:
        if not GLOBAL_NAME_DATASET:
            return False
        palabra_tit = palabra.title()
        try:
            info = GLOBAL_NAME_DATASET.search(palabra_tit)
            if not isinstance(info, dict):
                return False
            return bool(info.get("first_name") or info.get("last_name"))
        except Exception:
            return False

    def _reparar_nombres_pegados(self, texto: str) -> str:
        texto = texto.strip()
        if " " in texto or len(texto) < 5:
            return texto

        if self._es_nombre_real_ia(texto):
            return texto

        for i in range(3, len(texto) - 2):
            parte1, parte2 = texto[:i], texto[i:]
            if self._es_nombre_real_ia(parte1) and self._es_nombre_real_ia(parte2):
                return f"{parte1.upper()} {parte2.upper()}"

        return texto

    def _limpiar_direccion_inteligente(self, direccion: Optional[str]) -> Optional[str]:
        if not direccion:
            return None
        txt = direccion.upper()

        txt = re.sub(r"([A-Z])(\d)", r"\1 \2", txt)
        txt = re.sub(r"(\d)([A-Z])", r"\1 \2", txt)

        correcciones = ["COL", "AV", "CD", "FRACC", "UHAB", "CALLE", "ANDADOR", "PRIVADA"]
        for kw in correcciones:
            txt = re.sub(r"\b(" + kw + r")([A-Z])", r"\1 \2", txt)

        match_cp = re.search(r"\b(\d{5})\b", txt)
        if match_cp and GLOBAL_SEPOMEX:
            cp = match_cp.group(1)
            info = GLOBAL_SEPOMEX.buscar_cp(cp)

            if isinstance(info, dict):
                colonias = info.get("colonias")
                if isinstance(colonias, list) and colonias:
                    resultado = process.extractOne(txt, colonias, scorer=fuzz.partial_ratio)
                    if not resultado:
                        resultado = ("", 0)
                    mejor_colonia, puntaje = str(resultado[0]), int(resultado[1])

                    if puntaje > 85:
                        palabras_largas = [p for p in txt.split() if len(p) > 8]
                        for p in palabras_largas:
                            colonia_sin_espacios = mejor_colonia.replace(" ", "")
                            if fuzz.ratio(p, colonia_sin_espacios) > 80:
                                txt = txt.replace(p, mejor_colonia)

                muni = str(info.get("municipio", "")).upper()
                edo = str(info.get("estado", "")).upper()
                if muni and fuzz.partial_ratio(muni, txt) < 70:
                    txt += f" {muni}"
                if edo and fuzz.partial_ratio(edo, txt) < 70:
                    txt += f" {edo}"

        referencias = [
            "FRANCISCO I MADERO",
            "BENITO JUAREZ",
            "MIGUEL HIDALGO",
            "VENUSTIANO CARRANZA",
            "LAGO DE",
            "VALLE DE",
        ]
        for p in [x for x in txt.split() if len(x) > 10]:
            resultado = process.extractOne(p, referencias, scorer=fuzz.ratio)
            if not resultado:
                continue
            match, score = str(resultado[0]), int(resultado[1])
            if score >= 88:
                txt = txt.replace(p, match)

        txt = re.sub(r"\bC([B-DF-HJ-NP-TV-Z])", r"C \1", txt)

        palabras = txt.split()
        if len(palabras) > 2 and palabras[-1] == palabras[-2]:
            palabras.pop()

        txt = " ".join(palabras).replace(".", " ").replace("-", " ")
        return re.sub(r"\s+", " ", txt).strip()

    def _es_basura_en_nombre(self, texto: str) -> bool:
        texto = texto.upper()
        if re.search(r"\d", texto):
            return True
        palabras = [
            "FECHA",
            "NACIMIENTO",
            "SEXO",
            "DOMICILIO",
            "ELECTOR",
            "FOLIO",
            "ESTADO",
            "CREDENCIAL",
            "VOTAR",
            "EMISION",
            "VIGENCIA",
        ]
        if any(p in texto for p in palabras):
            return True
        return False

    def _es_basura_en_domicilio(self, texto: str) -> bool:
        texto = texto.upper()
        palabras = ["DOMICILIO", "COLONIA", "CURP", "FOLIO", "ESTADO", "MUNICIPIO", "LOCALIDAD", "ELECTOR", "NOMBRE", "SEXO"]
        if any(p in texto for p in palabras):
            return True
        return False

    def extraer_nombre(self) -> Optional[str]:
        for linea in self.lista_texto:
            if "<<" in linea and "<" in linea:
                if "IDMEX" not in linea and not re.search(r"\d", linea):
                    return self._limpiar_mrz_nombre(linea)

        idx_nombre = self._buscar_indice_difuso("NOMBRE")
        idx_domicilio = self._buscar_indice_difuso("DOMICILIO")

        nombres: List[str] = []
        if idx_nombre != -1 and idx_domicilio != -1:
            if idx_nombre < idx_domicilio:
                for k in range(idx_nombre + 1, idx_domicilio):
                    if not self._es_basura_en_nombre(self.lista_texto[k]):
                        nombres.append(self.lista_texto[k])
            else:
                for k in reversed(range(idx_domicilio + 1, idx_nombre)):
                    if not self._es_basura_en_nombre(self.lista_texto[k]):
                        nombres.append(self.lista_texto[k])

        elif idx_nombre != -1:
            for k in range(idx_nombre + 1, min(len(self.lista_texto), idx_nombre + 5)):
                linea = self.lista_texto[k]
                if not self._es_basura_en_nombre(linea) and len(linea) > 2:
                    nombres.append(linea)

        return " ".join(nombres) if nombres else None

    def extraer_domicilio(self) -> Optional[str]:
        idx_domicilio = self._buscar_indice_difuso("DOMICILIO")
        idx_clave = -1
        for i, linea in enumerate(self.lista_texto):
            if "CLAVE" in linea.upper() or "ELECTOR" in linea.upper() or re.search(r"[A-Z]{6}\d{8}", linea):
                idx_clave = i

        lineas: List[str] = []
        if idx_domicilio != -1 and idx_clave != -1:
            if idx_clave > idx_domicilio:
                rango = range(idx_domicilio + 1, idx_clave)
            else:
                rango = reversed(range(idx_clave + 1, idx_domicilio))
            for k in rango:
                if not self._es_basura_en_domicilio(self.lista_texto[k]):
                    lineas.append(self.lista_texto[k])
        elif idx_clave != -1:
            inicio = max(0, idx_clave - 4)
            for k in range(inicio, idx_clave):
                if not self._es_basura_en_domicilio(self.lista_texto[k]):
                    lineas.append(self.lista_texto[k])

        return " ".join(lineas) if lineas else None

    def extraer_fecha_nacimiento(self) -> Optional[str]:
        match = re.search(r"(\d{2})[:./-](\d{2})[:./-](\d{4})", self.texto_completo)
        if match:
            return f"{match.group(1)}/{match.group(2)}/{match.group(3)}"
        match_pegado = re.search(r"(\d{2})[:./-](\d{2})(\d{4})", self.texto_completo)
        if match_pegado:
            return f"{match_pegado.group(1)}/{match_pegado.group(2)}/{match_pegado.group(3)}"
        return None

    def extraer_vigencia(self) -> Optional[str]:
        match_rango = re.search(r"(\d{4})\s*-\s*(\d{4})", self.texto_completo)
        if match_rango:
            return f"{match_rango.group(1)}-{match_rango.group(2)}"
        match_solo = re.search(r"\b(20\d{2})\b", self.texto_completo)
        if match_solo:
            return match_solo.group(1)
        return None

    def extraer_seccion(self) -> Optional[str]:
        match = re.search(r"SECCI[O0]N\D*?(\d{3,4})", self.texto_completo)
        if match:
            return match.group(1)
        numeros = re.findall(r"\b\d{3,4}\b", self.texto_completo)
        ignorar = {"201", "202", "203", "204", "205"}
        for n in numeros:
            if n not in ignorar and not n.startswith("19") and not n.startswith("201"):
                return n
        return None

    def extraer_curp(self) -> Optional[str]:
        match = re.search(r"[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d", self.texto_completo)
        if match:
            return match.group(0)
        match_corto = re.search(r"([A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]+)", self.texto_completo)
        if match_corto and len(match_corto.group(1)) >= 16:
            return match_corto.group(1)
        return None

    def extraer_anio_registro(self) -> Optional[str]:
        match = re.search(r"\b((?:19|20)\d{2})\d{2}\b", self.texto_completo)
        if match:
            return match.group(1)
        match_pegado = re.search(r"REGISTRO\D*?((?:19|20)\d{2})", self.texto_completo)
        if match_pegado:
            return match_pegado.group(1)
        return None

    def extraer_clave_elector(self) -> Optional[str]:
        match = re.search(r"[A-Z]{6}\d{8}[A-Z0-9]{4}", self.texto_completo)
        if match:
            return match.group(0)
        return None

    def extraer_sexo(self) -> Optional[str]:
        match = re.search(r"SEXO\W*([HM])", self.texto_completo)
        if match:
            return match.group(1)
        curp = self.extraer_curp()
        if curp and len(curp) > 10:
            return curp[10]
        return None

    def _estructurar_nombre_completo(self, nombre_completo: Optional[str]) -> Dict[str, Optional[str]]:
        if not nombre_completo:
            return {"nombres": None, "apellido_paterno": None, "apellido_materno": None}
        partes = nombre_completo.split()
        if partes:
            ultimo = partes[-1]
            reparado = self._reparar_nombres_pegados(ultimo)
            if reparado != ultimo:
                partes = partes[:-1] + reparado.split()
        if len(partes) >= 3:
            return {"apellido_paterno": partes[0], "apellido_materno": partes[1], "nombres": " ".join(partes[2:])}
        if len(partes) == 2:
            return {"apellido_paterno": partes[0], "apellido_materno": None, "nombres": partes[1]}
        return {"apellido_paterno": None, "apellido_materno": None, "nombres": " ".join(partes)}

    def obtener_json(self) -> Dict[str, Optional[str]]:
        nombre_crudo = self.extraer_nombre()
        domicilio_crudo = self.extraer_domicilio()
        nombre_struct = self._estructurar_nombre_completo(nombre_crudo)
        domicilio_limpio = self._limpiar_direccion_inteligente(domicilio_crudo)

        return {
            "nombre_completo": nombre_crudo,
            "nombres": nombre_struct["nombres"],
            "apellido_paterno": nombre_struct["apellido_paterno"],
            "apellido_materno": nombre_struct["apellido_materno"],
            "sexo": self.extraer_sexo(),
            "domicilio": domicilio_limpio,
            "clave_elector": self.extraer_clave_elector(),
            "curp": self.extraer_curp(),
            "anio_registro": self.extraer_anio_registro(),
            "fecha_nacimiento": self.extraer_fecha_nacimiento(),
            "seccion": self.extraer_seccion(),
            "vigencia": self.extraer_vigencia(),
        }
