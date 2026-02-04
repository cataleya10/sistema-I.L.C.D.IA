import xml.etree.ElementTree as ET
import os
import json
import time


class SepomexLoader:
    def __init__(self, base_path="app/data"):
        self.xml_path = os.path.join(base_path, "sepomex.xml")
        self.json_path = os.path.join(base_path, "sepomex.json")
        self.db = {}

        if os.path.exists(self.json_path):
            self.cargar_desde_json()
        else:
            self.cargar_desde_xml_y_convertir()

    def cargar_desde_json(self):
        try:
            inicio = time.time()
            print(f"⚡ Cargando caché {self.json_path}...")
            with open(self.json_path, "r", encoding="utf-8") as f:
                self.db = json.load(f)
            fin = time.time()
            print(f"✅ SEPOMEX cargado desde JSON en {fin - inicio:.2f} segundos. ({len(self.db)} CPs)")
        except Exception as e:
            print(f"❌ Error leyendo JSON (se intentará regenerar): {e}")
            self.cargar_desde_xml_y_convertir()

    def cargar_desde_xml_y_convertir(self):
        if not os.path.exists(self.xml_path):
            print(f"⚠️ ADVERTENCIA: No se encontró {self.xml_path}")
            return

        try:
            print(f"🐢 Cargando (y convirtiendo) XML original: {self.xml_path}...")
            inicio = time.time()

            context = ET.iterparse(self.xml_path, events=("end",))

            for event, elem in context:
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
            print(f"✅ XML procesado en {fin - inicio:.2f} segundos.")

            print("💾 Guardando archivo JSON optimizado para la próxima vez...")
            with open(self.json_path, "w", encoding="utf-8") as f:
                json.dump(self.db, f, ensure_ascii=False)
            print("✨ ¡Conversión completada! El próximo reinicio será instantáneo.")

        except Exception as e:
            print(f"❌ Error crítico leyendo XML: {e}")

    def buscar_cp(self, cp):
        return self.db.get(str(cp))
