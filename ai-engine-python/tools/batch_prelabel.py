"""
Herramienta: batch_prelabel.py
Pre-etiqueta en lote todos los documentos de una carpeta del dataset.

Usa extracción de texto nativo del PDF (sin OCR completo) para mayor velocidad.
Los documentos bancarios digitales (BBVA, Santander, Banorte, Scotiabank)
tienen capa de texto embebida, por lo que no necesitan OCR.

Uso:
    python tools/batch_prelabel.py <tipo> [--max N] [--force]

Ejemplos:
    python tools/batch_prelabel.py bancario
    python tools/batch_prelabel.py bancario --max 20
    python tools/batch_prelabel.py bancario --force   # re-procesa incluso los ya etiquetados

Salida:
    - Actualiza los JSON en dataset/labeled/<tipo>/
    - Genera dataset/manifests/batch_prelabel_<tipo>_<fecha>.json con el reporte
"""

import sys
import os
import json
import re
import argparse
import traceback
from pathlib import Path
from datetime import datetime

SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATASET_DIR  = PROJECT_ROOT / "dataset"

sys.path.insert(0, str(PROJECT_ROOT))

from app.utils.regex_patterns import (
    CURP_PATTERN,
    RFC_PATTERN,
    NSS_PATTERN,
    CLABE_PATTERN,
    FOLIO_PATTERN,
    CLAVE_ELECTOR_PATTERN,
    RFC_EXCLUIR as _RFC_BANCO_EXCLUIR,
    MESES_ES as _MESES_ES,
    normalize_date as _normalizar_fecha,
)

TIPOS_VALIDOS = {"ine", "curp", "nomina", "bancario",
                 "acta_nacimiento", "nss", "csf", "comprobante_domicilio"}

DOC_TYPE_MAP = {
    "ine":                   "INE",
    "curp":                  "CURP",
    "nomina":                "NOMINA",
    "bancario":              "DATOS_BANCARIOS",
    "acta_nacimiento":       "ACTA_NACIMIENTO",
    "nss":                   "NSS",
    "csf":                   "CONSTANCIA_SITUACION_FISCAL",
    "comprobante_domicilio": "COMPROBANTE_DOMICILIO",
}

CAMPOS_ESPERADOS = {
    "ine":      ["curp", "nombre", "fecha_nacimiento", "sexo", "domicilio", "clave_elector", "seccion", "vigencia"],
    "curp":     ["curp", "nombre", "fecha_nacimiento", "sexo", "entidad_nacimiento"],
    "nomina":   ["nombre", "rfc", "nss", "curp", "empresa", "periodo", "fecha_pago", "total_percepciones", "total_deducciones", "neto_pagar"],
    "bancario": ["clabe", "cuenta", "banco", "titular", "rfc", "fecha_corte", "periodo"],
    "acta_nacimiento":       ["nombre", "sexo", "fecha_nacimiento", "lugar_nacimiento", "folio", "numero_acta", "fecha_registro", "municipio_registro", "entidad_registro"],
    "nss":                   ["nss", "nombre", "curp"],
    "csf":                   ["rfc", "nombre", "regimen", "domicilio"],
    "comprobante_domicilio": ["proveedor", "titular", "domicilio", "cp", "fecha_limite", "total", "numero_servicio"],
}


def _extract_text_fast(pdf_path: Path) -> str:
    """Extrae texto nativo del PDF con PyMuPDF (sin OCR). Muy rápido."""
    try:
        import fitz  # type: ignore[import]
        doc = fitz.open(str(pdf_path))
        pages_text = []
        for page in doc:
            # ✅ FIX: compatible con PyMuPDF 1.27.x
            pages_text.append(page.get_text())  # type: ignore[attr-defined]
        doc.close()
        return "\n".join(pages_text).upper()
    except Exception:
        return ""


def _extract_fields_from_text(text: str, tipo: str, banco_origen: str = "") -> dict:
    """
    Extrae campos bancarios usando regex sobre el texto nativo del PDF.
    Mucho más rápido que el pipeline completo de OCR.
    Soporta formatos: BBVA NetCash, Banorte SPEI, Santander dispersión/SPEI,
    Scotiabank archivo y listas de nómina.
    """
    result = {c: "" for c in CAMPOS_ESPERADOS.get(tipo, [])}

    if not text:
        return result

    # ── CLABE (18 dígitos) ─────────────────────────────────────────────────────
    clabe_m = re.search(
        r'(?:CUENTA[/\s]*CLABE\s*BENEFICIARIO|CUENTA\s*DE\s*RETIRO|CUENTA\s*CLABE'
        r'|NO\.\s*CUENTA\s*BENEFICIARIO)[:\s]+(\d{18})',
        text
    )
    if not clabe_m:
        clabe_m = re.search(r'RETIRO[:\s]+(\d{18})', text)
    if not clabe_m:
        for m in re.finditer(r'\b(\d{18})\b', text):
            if not m.group(1).startswith("000000001"):
                clabe_m = m
                break
    if not clabe_m:
        clabe_m = re.search(r'\b(\d{18})\b', text)
    if clabe_m:
        result["clabe"] = clabe_m.group(1)

    # ── Cuenta ordenante (10-13 dígitos) ───────────────────────────────────────
    clabe_val = result.get("clabe", "")
    cuenta_m = re.search(
        r'(?:CUENTA[/\s]*CLABE\s*ORDENANTE|CUENTA\s*DE\s*DEP[OÓ]SITO'
        r'|CUENTA\s*CARGO[:\s]+|N[UÚ]MERO\s*DE\s*CONTRATO\s*ENLACE)[:\s]+(\d{10,13})',
        text
    )
    if not cuenta_m:
        cuenta_m = re.search(r'CUENTA\s*CARGO[:\s]+(\d{10,13})\s*(?:-|$|\n)', text)
    if not cuenta_m:
        for c in re.findall(r'\b(\d{10,13})\b', text):
            if c != clabe_val:
                result["cuenta"] = c
                break
    if cuenta_m:
        result["cuenta"] = cuenta_m.group(1)

    # ── Titular (empresa pagadora / ordenante) ─────────────────────────────────
    for patron in [
        r'NOMBRE\s*DEL\s*CLIENTE[:\s\n]+([A-ZÁÉÍÓÚÜÑ&][A-ZÁÉÍÓÚÜÑ&\s,\.]{4,70}?)(?:\n|RFC|CLABE|BBVA|$)',
        r'NOMBRE\s*DEL\s*ORDENANTE[:\s\n]+([A-ZÁÉÍÓÚÜÑ&][A-ZÁÉÍÓÚÜÑ&\s,\.]{4,70}?)(?:\n|RFC|CLABE|$)',
        r'NOMBRE\s*DE\s*LA\s*EMPRESA[:\s\n]+([A-ZÁÉÍÓÚÜÑ&][A-ZÁÉÍÓÚÜÑ&\s,\.]{4,70}?)(?:\n|RFC|CLABE|$)',
        r'CONTRATO[:\s]+([A-ZÁÉÍÓÚÜÑ&][A-ZÁÉÍÓÚÜÑ&\s,\.]{4,70}?)\s*\d{8,}',
        r'CUENTA\s*CARGO[:\s]+\d+\s*[-–]\s*([A-ZÁÉÍÓÚÜÑ&][A-ZÁÉÍÓÚÜÑ&\s,\.]{4,70}?)(?:\n|CUENTA|$)',
    ]:
        m = re.search(patron, text, re.IGNORECASE)
        if m:
            nombre = re.sub(r'\s+', ' ', m.group(1)).strip().rstrip(",.")
            if len(nombre) >= 5:
                result["titular"] = nombre
                break

    # ── RFC del ordenante ──────────────────────────────────────────────────────
    for patron in [
        r'RFC\s*O\s*CURP\s*DEL\s*ORDENANTE[:\s]+([A-Z&]{3,4}\d{6}[A-Z0-9]{3,4})',
        r'RFC\s*ORDENANTE[:\s]+([A-Z&]{3,4}\d{6}[A-Z0-9]{3,4})',
        r'RFC\s*(?:DEL\s*ORDENANTE|EMPRESA)[:\s]+([A-Z&]{3,4}\d{6}[A-Z0-9]{3,4})',
    ]:
        m = re.search(patron, text, re.IGNORECASE)
        if m:
            rfc = re.sub(r'[\s-]', '', m.group(1)).upper()
            if rfc not in _RFC_BANCO_EXCLUIR:
                result["rfc"] = rfc
                break
    if not result["rfc"]:
        for m in re.finditer(r'\b([A-Z&]{3,4}\d{6}[A-Z0-9]{3,4})\b', text):
            rfc = re.sub(r'[\s-]', '', m.group(1)).upper()
            if rfc not in _RFC_BANCO_EXCLUIR:
                result["rfc"] = rfc
                break

    # ── Banco ──────────────────────────────────────────────────────────────────
    if banco_origen:
        result["banco"] = banco_origen
    else:
        for nombre_banco, palabras in [
            ("BBVA BANCOMER",  ["BBVA NET CASH", "BBVANETCASH", "BBVA MEXICO"]),
            ("BANORTE",        ["BANCO MERCANTIL DEL NORTE", "BANORTE"]),
            ("SANTANDER",      ["SANTANDER"]),
            ("SCOTIABANK",     ["SCOTIABANK INVERLAT", "SCOTIABANK", "SCOTIA EN LINEA"]),
            ("HSBC",           ["HSBC"]),
            ("BANAMEX",        ["BANAMEX", "CITIBANAMEX"]),
            ("INBURSA",        ["INBURSA"]),
            ("AZTECA",         ["BANCO AZTECA"]),
            ("BANCOPPEL",      ["BANCOPPEL"]),
        ]:
            if any(p in text for p in palabras):
                result["banco"] = nombre_banco
                break

    # ── Fecha de aplicación / operación ──────────────────────────────────────
    for patron in [
        r'FECHA\s*DE\s*APLICACI[OÓ]N[:\s]+(\d{2}[-/][A-Z0-9]{2,3}[-/]\d{4})',
        r'FECHA\s*APLICACI[OÓ]N[:\s]+(\d{2}[-/][A-Z0-9]{2,3}[-/]\d{4})',
        r'FECHA\s*DE\s*ENV[IÍ]O\s*DE\s*PAGO[:\s]+(\d{2}[-/]\d{2}[-/]\d{4})',
        r'FECHA\s*(?:Y\s*HORA\s*DE\s*)?ALTA[:\s]+(\d{2}[-/]\d{2}[-/]\d{4})',
        r'FECHA\s*(?:Y\s*HORA\s*DE\s*)?CONSULTA[:\s]+(\d{2}[-/]\d{2}[-/]\d{4})',
        r'FECHA\s*DE\s*CREACI[OÓ]N[:\s]+(\d{2}[-/]\d{2}[-/]\d{4})',
        r'\b(\d{2}[-/]\d{2}[-/]\d{4})\b',
    ]:
        m = re.search(patron, text, re.IGNORECASE)
        if m:
            result["fecha_corte"] = _normalizar_fecha(m.group(1))
            break

    # ── Período ─────────────────────────────────────────────────────────────
    periodo_m = re.search(
        r'(\d{2}[-/]\d{2}[-/]\d{4})\s*(?:AL?|A)\s*(\d{2}[-/]\d{2}[-/]\d{4})',
        text, re.IGNORECASE
    )
    if periodo_m:
        f1 = _normalizar_fecha(periodo_m.group(1))
        f2 = _normalizar_fecha(periodo_m.group(2))
        result["periodo"] = f"{f1} al {f2}"

    return result


def _extract_fields_ine(text: str) -> dict:
    result = {c: "" for c in CAMPOS_ESPERADOS["ine"]}
    m = CURP_PATTERN.search(text)
    if m: result["curp"] = m.group(0)
    m = CLAVE_ELECTOR_PATTERN.search(text)
    if m: result["clave_elector"] = m.group(0)
    m = re.search(r'SECCI[OÓ]N[:\s]+(\d{4})', text)
    if m: result["seccion"] = m.group(1)
    m = re.search(r'VIGENCIA[:\s]+(\d{4})', text, re.IGNORECASE)
    if m: result["vigencia"] = m.group(1)
    m = re.search(r'FECHA\s*(?:DE\s*)?NACIMIENTO[:\s]+(\d{2}[-/]\d{2}[-/]\d{4})', text, re.IGNORECASE)
    if not m: m = re.search(r'\b(\d{2}[-/]\d{2}[-/]\d{4})\b', text)
    if m: result["fecha_nacimiento"] = _normalizar_fecha(m.group(1))
    m = re.search(r'\b(HOMBRE|MUJER|MASCULINO|FEMENINO)\b', text)
    if m:
        result["sexo"] = "H" if m.group(1) in {"HOMBRE", "MASCULINO"} else "M"
    elif re.search(r'\bH\b', text): result["sexo"] = "H"
    elif re.search(r'\bM\b', text): result["sexo"] = "M"
    return result


def _extract_fields_curp(text: str) -> dict:
    result = {c: "" for c in CAMPOS_ESPERADOS["curp"]}
    m = CURP_PATTERN.search(text)
    if m: result["curp"] = m.group(0)
    m = re.search(r'FECHA\s*(?:DE\s*)?NACIMIENTO[:\s]+(\d{2}[-/]\d{2}[-/]\d{4})', text, re.IGNORECASE)
    if not m: m = re.search(r'\b(\d{2}[-/]\d{2}[-/]\d{4})\b', text)
    if m: result["fecha_nacimiento"] = _normalizar_fecha(m.group(1))
    m = re.search(r'\b(HOMBRE|MUJER|MASCULINO|FEMENINO)\b', text)
    if m: result["sexo"] = "H" if m.group(1) in {"HOMBRE", "MASCULINO"} else "M"
    m = re.search(r'ENTIDAD[:\s]+([A-ZÁÉÍÓÚÑ ]{4,30}?)(?:\n|$)', text, re.IGNORECASE)
    if m: result["entidad_nacimiento"] = m.group(1).strip()
    return result


def _extract_fields_nomina(text: str) -> dict:
    result = {c: "" for c in CAMPOS_ESPERADOS["nomina"]}
    rfcs = re.findall(r'\b([A-Z&]{3,4}\d{6}[A-Z0-9]{3,4})\b', text)
    if rfcs: result["rfc"] = rfcs[0]
    m = re.search(r'\b(\d{11})\b', text)
    if m: result["nss"] = m.group(1)
    m = re.search(r'\b([A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d)\b', text)
    if m: result["curp"] = m.group(1)
    m = re.search(r'FECHA\s*(?:DE\s*)?PAGO[:\s]+(\d{2}[-/]\d{2}[-/]\d{4})', text, re.IGNORECASE)
    if not m: m = re.search(r'\b(\d{2}[-/]\d{2}[-/]\d{4})\b', text)
    if m: result["fecha_pago"] = _normalizar_fecha(m.group(1))
    for campo, patron in [
        ("total_percepciones", r'(?:TOTAL\s*PERCEPCIONES|PERCEPCIONES)[:\s]+\$?([\d,]+\.?\d*)'),
        ("total_deducciones",  r'(?:TOTAL\s*DEDUCCIONES|DEDUCCIONES)[:\s]+\$?([\d,]+\.?\d*)'),
        ("neto_pagar",         r'(?:NETO\s*A\s*PAGAR|NETO\s*PAGAR|NETO)[:\s]+\$?([\d,]+\.?\d*)'),
    ]:
        m = re.search(patron, text, re.IGNORECASE)
        if m: result[campo] = m.group(1).replace(",", "")
    return result


def _extract_fields_acta(text: str) -> dict:
    result = {c: "" for c in CAMPOS_ESPERADOS["acta_nacimiento"]}
    m = re.search(r'(?:FOLIO|N[UÚ]MERO\s*DE\s*ACTA)[:\s]+([A-Z0-9/\-]+)', text, re.IGNORECASE)
    if m: result["folio"] = m.group(1).strip()
    m = re.search(r'(?:NACI[OÓ]|NACIMIENTO)[^.]*?(\d{1,2}[\s/\-]+(?:DE\s)?[A-Z]+[\s/\-]+\d{4})', text, re.IGNORECASE)
    if m: result["fecha_nacimiento"] = re.sub(r'\s+', ' ', m.group(1)).strip()
    m = re.search(r'REGISTRO[:\s]+(\d{2}[-/]\d{2}[-/]\d{4})', text, re.IGNORECASE)
    if m: result["fecha_registro"] = _normalizar_fecha(m.group(1))
    m = re.search(r'\b(MASCULINO|FEMENINO|HOMBRE|MUJER)\b', text)
    if m: result["sexo"] = "H" if m.group(1) in {"MASCULINO", "HOMBRE"} else "M"
    return result


def _extract_fields_nss(text: str) -> dict:
    result = {c: "" for c in CAMPOS_ESPERADOS["nss"]}
    m = NSS_PATTERN.search(text)
    if m: result["nss"] = m.group(0)
    m = CURP_PATTERN.search(text)
    if m: result["curp"] = m.group(0)
    return result


def _extract_fields_csf(text: str) -> dict:
    result = {c: "" for c in CAMPOS_ESPERADOS["csf"]}
    m = re.search(r'\b([A-Z&]{3,4}\d{6}[A-Z0-9]{3,4})\b', text)
    if m: result["rfc"] = m.group(1)
    m = re.search(r'R[EÉ]GIMEN[:\s]+([A-ZÁÉÍÓÚÑ\s]{5,60}?)(?:\n|RFC|DOMICILIO|$)', text, re.IGNORECASE)
    if m: result["regimen"] = re.sub(r'\s+', ' ', m.group(1)).strip()
    return result


def _extract_fields_comprobante(text: str) -> dict:
    result = {c: "" for c in CAMPOS_ESPERADOS["comprobante_domicilio"]}
    m = re.search(r'\bC\.?P\.?[:\s]+(\d{5})\b', text, re.IGNORECASE)
    if not m: m = re.search(r'\b(\d{5})\b', text)
    if m: result["cp"] = m.group(1)
    m = re.search(r'(?:FECHA\s*L[IÍ]MITE|FECHA\s*VENCIMIENTO|VENCE)[:\s]+(\d{2}[-/]\d{2}[-/]\d{4})', text, re.IGNORECASE)
    if not m: m = re.search(r'\b(\d{2}[-/]\d{2}[-/]\d{4})\b', text)
    if m: result["fecha_limite"] = _normalizar_fecha(m.group(1))
    m = re.search(r'(?:TOTAL\s*A\s*PAGAR|IMPORTE\s*TOTAL|TOTAL)[:\s]+\$?([\d,]+\.?\d*)', text, re.IGNORECASE)
    if m: result["total"] = m.group(1).replace(",", "")
    m = re.search(r'(?:N[UÚ]MERO\s*DE\s*SERVICIO|N[UÚ]MERO\s*DE\s*CUENTA|CUENTA)[:\s]+([A-Z0-9\-]{6,20})', text, re.IGNORECASE)
    if m: result["numero_servicio"] = m.group(1)
    return result


_EXTRACTORES_ESPECIALIZADOS = {
    "ine":                   _extract_fields_ine,
    "curp":                  _extract_fields_curp,
    "nomina":                _extract_fields_nomina,
    "acta_nacimiento":       _extract_fields_acta,
    "nss":                   _extract_fields_nss,
    "csf":                   _extract_fields_csf,
    "comprobante_domicilio": _extract_fields_comprobante,
}


def _load_label_json(path: Path) -> dict:
    with open(path, encoding="utf-8-sig") as fh:
        return json.load(fh)


def _save_label_json(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def batch_prelabel(tipo: str, max_docs: int = 0, force: bool = False) -> None:
    tipo = tipo.lower().strip()
    if tipo not in TIPOS_VALIDOS:
        print(f"ERROR: tipo '{tipo}' no válido.")
        sys.exit(1)

    raw_dir   = DATASET_DIR / "raw"     / tipo
    label_dir = DATASET_DIR / "labeled" / tipo

    pdfs = sorted(raw_dir.glob("*.pdf"))
    if max_docs > 0:
        pdfs = pdfs[:max_docs]

    total     = len(pdfs)
    ok        = 0
    parcial   = 0
    sin_texto = 0
    errores   = []
    reporte   = []

    print(f"\nBatch pre-etiquetado: {tipo.upper()} — {total} documentos")
    print("=" * 65)

    for i, pdf in enumerate(pdfs, 1):
        stem       = pdf.stem
        label_path = label_dir / f"{stem}.json"

        if label_path.exists() and not force:
            existing = _load_label_json(label_path)
            if existing.get("labeled") is True:
                print(f"  [{i:03d}/{total}]  SKIP (ya etiquetado)  {stem}")
                reporte.append({"id": stem, "status": "skip_labeled"})
                ok += 1
                continue

        banco_origen = ""
        label_data   = {}
        if label_path.exists():
            label_data   = _load_label_json(label_path)
            banco_origen = label_data.get("banco_origen", "")

        try:
            text = _extract_text_fast(pdf)

            if len(text.strip()) < 20:
                sin_texto += 1
                status = "sin_texto"
                detectados = 0
                campos = {c: "" for c in CAMPOS_ESPERADOS.get(tipo, [])}
                print(f"  [{i:03d}/{total}]  SIN TEXTO  {stem}")
            else:
                extractor_fn = _EXTRACTORES_ESPECIALIZADOS.get(tipo)
                if extractor_fn:
                    campos = extractor_fn(text)
                else:
                    campos = _extract_fields_from_text(text, tipo, banco_origen)
                detectados = sum(1 for v in campos.values() if v)
                total_campos = len(campos)

                if detectados == total_campos:
                    status = "completo"
                    ok += 1
                    icono = "✓"
                elif detectados > 0:
                    status = "parcial"
                    parcial += 1
                    icono = "~"
                else:
                    status = "vacio"
                    errores.append({"id": stem, "error": "sin campos detectados"})
                    icono = "✗"

                print(f"  [{i:03d}/{total}]  {icono}  {stem}  ({detectados}/{total_campos} campos)")

            already_labeled = label_data.get("labeled", False)
            label_data.update({
                "prelabeled_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "labeled":         already_labeled,
                "notes":           "REVISAR: corrige los campos incorrectos y cambia labeled a true",
                "prelabel_campos": f"{detectados}/{len(campos)}",
                "expected_fields": campos,
            })
            _save_label_json(label_path, label_data)

            reporte.append({
                "id":         stem,
                "status":     status,
                "detectados": detectados,
                "total":      len(campos),
                "filename":   pdf.name,
            })

        except Exception as e:
            err_msg = str(e)
            print(f"  [{i:03d}/{total}]  ERROR  {stem}: {err_msg[:80]}")
            errores.append({"id": stem, "error": err_msg, "traceback": traceback.format_exc()})
            reporte.append({"id": stem, "status": "error", "error": err_msg})

    fecha_str   = datetime.now().strftime("%Y%m%d_%H%M")
    report_path = DATASET_DIR / "manifests" / f"batch_prelabel_{tipo}_{fecha_str}.json"
    report_data = {
        "tipo":       tipo,
        "fecha":      datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total":      total,
        "completos":  ok,
        "parciales":  parcial,
        "sin_texto":  sin_texto,
        "errores":    len(errores),
        "detalle_errores": errores,
        "documentos": reporte,
    }
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report_data, fh, ensure_ascii=False, indent=2)

    print()
    print("=" * 65)
    print(f"  Total procesados : {total}")
    print(f"  Completos  (✓)   : {ok}")
    print(f"  Parciales  (~)   : {parcial}")
    print(f"  Sin texto  (-)   : {sin_texto}")
    print(f"  Errores    (✗)   : {len(errores)}")
    print(f"  Reporte guardado : {report_path.relative_to(PROJECT_ROOT)}")
    print()

    if errores:
        print("DOCUMENTOS CON ERROR (necesitan revisión manual):")
        for e in errores[:20]:
            print(f"  - {e['id']}: {e['error'][:80]}")
        if len(errores) > 20:
            print(f"  ... y {len(errores)-20} más. Ver el reporte completo.")


def main():
    parser = argparse.ArgumentParser(description="Pre-etiqueta en lote documentos del dataset")
    parser.add_argument("tipo",         help="Tipo de documento: ine, curp, nomina, bancario")
    parser.add_argument("--max",  type=int, default=0,     help="Máximo de documentos a procesar (0=todos)")
    parser.add_argument("--force",      action="store_true", help="Re-procesar incluso los ya etiquetados")
    args = parser.parse_args()

    batch_prelabel(args.tipo, args.max, args.force)


if __name__ == "__main__":
    main()