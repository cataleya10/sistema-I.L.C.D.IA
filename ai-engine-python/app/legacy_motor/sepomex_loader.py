import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)


class SepomexLoader:
    def __init__(self, base_path: str | None = None):
        data_dir = self._resolve_data_dir(base_path)
        self.xml_path = str(data_dir / "sepomex.xml")
        self.json_path = str(data_dir / "sepomex.json")
        self.db = {}

        if os.path.exists(self.json_path):
            self.cargar_desde_json()
        else:
            self.cargar_desde_xml_y_convertir()

    def _resolve_data_dir(self, base_path: str | None) -> Path:
        if base_path:
            return Path(base_path)

        module_dir = Path(__file__).resolve().parent
        app_dir = module_dir.parent
        candidates = [
            app_dir / "data",
            app_dir / "models",
            app_dir.parent / "data",
            Path.cwd() / "ai-engine-python" / "app" / "data",
            Path.cwd() / "ai-engine-python" / "app" / "models",
        ]

        for folder in candidates:
            if (folder / "sepomex.json").exists() or (folder / "sepomex.xml").exists():
                return folder
        return candidates[0]

    def cargar_desde_json(self):
        try:
            inicio = time.time()
            logger.info("[SEPOMEX] Cargando cache %s...", self.json_path)
            with open(self.json_path, "r", encoding="utf-8") as f:
                self.db = json.load(f)
            fin = time.time()
            logger.info("[SEPOMEX] Cargado desde JSON en %.2f segundos. (%s CPs)", fin - inicio, len(self.db))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("[SEPOMEX] Error leyendo JSON (se intentara regenerar): %s", e)
            self.cargar_desde_xml_y_convertir()

    def cargar_desde_xml_y_convertir(self):
        if not os.path.exists(self.xml_path):
            logger.warning("[SEPOMEX] ADVERTENCIA: No se encontro %s", self.xml_path)
            return

        try:
            logger.info("[SEPOMEX] Cargando y convirtiendo XML original: %s...", self.xml_path)
            inicio = time.time()

            context = ET.iterparse(self.xml_path, events=("end",))

            for _event, elem in context:
                tag_name = elem.tag.split("}")[-1].lower()

                if tag_name in ["table", "table_data", "newdataset", "data"]:
                    cp = None
                    colonia = None
                    municipio = None
                    estado = None

                    for child in elem:
                        child_tag = child.tag.split("}")[-1].lower()
                        if child_tag == "d_codigo":
                            cp = child.text
                        elif child_tag == "d_asenta":
                            colonia = child.text
                        elif child_tag == "d_mnpio":
                            municipio = child.text
                        elif child_tag == "d_estado":
                            estado = child.text

                    if cp:
                        cp = re.sub(r"\D", "", str(cp))
                        if not cp:
                            elem.clear()
                            continue
                        if cp not in self.db:
                            self.db[cp] = {
                                "colonias": [],
                                "municipio": municipio if municipio else "",
                                "estado": estado if estado else "",
                            }
                        if colonia and colonia not in self.db[cp]["colonias"]:
                            self.db[cp]["colonias"].append(colonia.upper())

                    elem.clear()

            fin = time.time()
            logger.info("[SEPOMEX] XML procesado en %.2f segundos.", fin - inicio)

            logger.info("[SEPOMEX] Guardando archivo JSON optimizado para la proxima vez...")
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump(self.db, f, ensure_ascii=False)
            logger.info("[SEPOMEX] Conversion completada. El proximo reinicio sera instantaneo.")

        except (OSError, ET.ParseError) as e:
            logger.error("[SEPOMEX] Error critico leyendo XML: %s", e)

    def buscar_cp(self, cp):
        if cp is None:
            return None
        cp_raw = str(cp).strip()
        cp_num = re.sub(r"\D", "", cp_raw)
        if cp_num:
            return self.db.get(cp_num) or self.db.get(cp_num.zfill(5))
        return self.db.get(cp_raw)
