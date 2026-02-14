from thefuzz import fuzz
import re


class ProcesadorNSS:
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
                        "texto": texto,
                        "texto_upper": texto.upper(),
                        "x_min": min(x_vals),
                        "x_max": max(x_vals),
                        "y_min": min(y_vals),
                        "y_max": max(y_vals),
                        "centro_x": sum(x_vals) / 4,
                        "centro_y": sum(y_vals) / 4,
                    }
                )

        self.datos = {
            "nss": None,
            "nombre": None,
            "curp": None,
            "fecha_documento": None,
            "folio_solicitud": None,
        }

    def ejecutar(self):
        self._procesar_cadena_original()

        if not self.datos["nss"]:
            self._buscar_nss_visual()
        if not self.datos["curp"]:
            self._buscar_curp_regex()

        return self.datos

    def _procesar_cadena_original(self):
        texto_sucio = " ".join([b["texto"] for b in self.bloques])

        texto_limpio = texto_sucio.replace("_", " ").replace("/", " ").replace("|", " ")
        texto_limpio = re.sub(r"\b[lI]{2,}\b", " ", texto_limpio)
        texto_limpio = re.sub(r"\s+", " ", texto_limpio)

        match_fecha = re.search(r"Fecha[\s\.:]*([^,]+20\d{2})", texto_limpio, re.IGNORECASE)
        if match_fecha:
            self.datos["fecha_documento"] = match_fecha.group(1).strip()

        match_folio = re.search(r"Folio[\s\.:]*(\d+)", texto_limpio, re.IGNORECASE)
        if match_folio:
            self.datos["folio_solicitud"] = match_folio.group(1).strip()

        match_nombre = re.search(
            r"(?:Nombre(?:\s+del|\s+de la)?\s+(?:Asegurado|Beneficiario|Trabajador|Titular)|Nombre\s+o\s+Razon\s+Social|Nombre)"
            r"[\s\.:-]*((?:(?!(?:Curp|RFC|NSS|IMSS|Folio|Fecha)).)+)",
            texto_limpio,
            re.IGNORECASE,
        )

        if match_nombre:
            nombre_raw = match_nombre.group(1).strip().upper()
            nombre_raw = (
                nombre_raw
                .replace("RFC", "")
                .replace("CURP", "")
                .replace("NSS", "")
                .replace("IMSS", "")
                .strip()
            )
            nombre_raw = nombre_raw.rstrip(".:,")
            self.datos["nombre"] = nombre_raw

        if not self.datos["curp"]:
            match_curp = re.search(r"[A-Z]{4}\d{6}[HM][A-Z]{2,5}[A-Z0-9]{2}", texto_limpio)
            if match_curp:
                self.datos["curp"] = match_curp.group(0)

        match_nss = re.search(r"Social[\s\.:]*(\d{10,11})", texto_limpio, re.IGNORECASE)
        if match_nss:
            self.datos["nss"] = match_nss.group(1).strip()

    def _buscar_nss_visual(self):
        texto_completo = " ".join([b["texto_upper"] for b in self.bloques])
        match = re.search(r"\b(\d{11})\b", texto_completo)
        if match:
            self.datos["nss"] = match.group(1)

    def _buscar_curp_regex(self):
        texto_completo = " ".join([b["texto_upper"] for b in self.bloques])
        match = re.search(r"[A-Z]{4}\d{6}[HM][A-Z]{2,5}[A-Z0-9]{2}", texto_completo)
        if match:
            self.datos["curp"] = match.group(0)


def extraer_datos_nss(ocr_results):
    procesador = ProcesadorNSS(ocr_results)
    return procesador.ejecutar()
