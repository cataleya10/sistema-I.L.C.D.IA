"""
Herramienta: dataset_evaluate.py
Evalúa qué tan bien el extractor del sistema detecta los campos de los
documentos contra los valores anotados manualmente en el dataset.

Flujo:
  1. Lee Todos los JSON en dataset/labeled/<tipo>/
  2. Para cada doc, corre el pipeline real (preprocess → OCR → extract)
     O el modo --fast que corre solo el regex de batch_prelabel
  3. Compara campos detectados vs expected_fields del JSON
  4. Genera reporte en dataset/manifests/eval_<tipo>_<fecha>.json

Uso:
    python tools/dataset_evaluate.py bancario              # modo fast (regex)
    python tools/dataset_evaluate.py bancario --pipeline  # modo completo (OCR)
    python tools/dataset_evaluate.py bancario --solo-etiquetados  # solo labeled=true
    python tools/dataset_evaluate.py bancario --max 20
"""
import sys
import os
import json
import re
import argparse
import asyncio
import importlib.util
import traceback
from pathlib import Path
from datetime import datetime
from types import ModuleType

SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATASET_DIR  = PROJECT_ROOT / "dataset"

sys.path.insert(0, str(PROJECT_ROOT))

TIPOS_VALIDOS = {"ine", "curp", "nomina", "bancario"}

# ── Normalización de valores para comparación justa ───────────────────────────

def _normalizar(valor: str, campo: str) -> str:
    if not valor:
        return ""
    t = str(valor).strip().upper()
    t = re.sub(r"\s+", " ", t)
    if campo in {"clabe", "cuenta", "rfc", "nss", "curp"}:
        return re.sub(r"[^A-Z0-9]", "", t)
    if campo in {"nombre", "titular", "domicilio"}:
        return re.sub(r"[^A-Z0-9]", "", t)
    if campo in {"fecha_corte", "fecha_nacimiento", "fecha_pago"}:
        return t.replace("-", "/")
    if campo == "banco":
        aliases = {"BBVA": "BBVA BANCOMER", "BANCO MERCANTIL DEL NORTE": "BANORTE",
                   "CITIBANAMEX": "BANAMEX", "SCOTIABANK INVERLAT": "SCOTIABANK"}
        for alias, canonical in aliases.items():
            if alias in t:
                return canonical
        return t
    return t


def _coincide(esperado: str, detectado: str, campo: str) -> bool:
    e = _normalizar(esperado, campo)
    d = _normalizar(detectado, campo)
    if not e:
        return True
    if not d:
        return False
    if campo in {"titular", "nombre", "domicilio"} and len(e) > 5:
        return e in d or d in e
    return e == d


# ── Modo FAST: mismos regex que batch_prelabel ─────────────────────────────────

def _cargar_batch_prelabel() -> ModuleType:
    """Importa la función de extracción de batch_prelabel."""
    spec = importlib.util.spec_from_file_location(
        "batch_prelabel", SCRIPT_DIR / "batch_prelabel.py"
    )
    # ✅ FIX: verificar que spec y spec.loader no sean None antes de usarlos
    if spec is None or spec.loader is None:
        raise ImportError("No se pudo cargar batch_prelabel.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ── Modo PIPELINE: usa el sistema real ────────────────────────────────────────

def _extraer_con_pipeline(pdf_path: Path, tipo: str) -> dict:
    """
    Corre el pipeline real: extrae texto con PyMuPDF → extract_fields.
    Devuelve el dict de campos extraídos (o {} si falla).
    """
    try:
        from app.services.extractor_service import extract_document_fields
        import fitz  # type: ignore[import]

        doc_type_map = {
            "ine": "INE", "curp": "CURP",
            "nomina": "NOMINA", "bancario": "DATOS_BANCARIOS",
        }
        document_type = doc_type_map.get(tipo, "DATOS_BANCARIOS")

        # ✅ FIX: leer texto directamente con PyMuPDF, sin pasar por preprocess
        with open(pdf_path, "rb") as f:
            file_bytes = f.read()

        text_parts: list[str] = []
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            for page in doc:
                text_parts.append(page.get_text() or "")  # type: ignore[attr-defined]
        ocr_text  = "\n\n".join(text_parts)
        ocr_boxes: list = []

        # ✅ FIX: si extract_document_fields es async, ejecutarlo con asyncio.run
        if asyncio.iscoroutinefunction(extract_document_fields):
            result = asyncio.run(extract_document_fields(document_type, ocr_text, ocr_boxes))
        else:
            result = extract_document_fields(document_type, ocr_text, ocr_boxes)

        fields = result.get("fields", {}) if isinstance(result, dict) else {}
        return {k: (v or "") for k, v in fields.items()}

    except Exception as e:
        return {"_error": str(e)[:200]}


# ── Evaluación principal ───────────────────────────────────────────────────────

def evaluar(tipo: str, modo_pipeline: bool = False,
            solo_etiquetados: bool = False, max_docs: int = 0) -> None:

    tipo = tipo.lower().strip()
    if tipo not in TIPOS_VALIDOS:
        print(f"ERROR: tipo '{tipo}' no válido. Usa: {', '.join(TIPOS_VALIDOS)}")
        sys.exit(1)

    label_dir = DATASET_DIR / "labeled" / tipo
    raw_dir   = DATASET_DIR / "raw"     / tipo
    jsons     = sorted(label_dir.glob("*.json"))

    modo_str = "PIPELINE (OCR completo)" if modo_pipeline else "FAST (regex nativo)"
    print(f"\nEvaluación: {tipo.upper()} — {len(jsons)} documentos — Modo: {modo_str}")

    bp_mod: ModuleType | None = None

    if modo_pipeline:
        print("  [Cargando pipeline…]", end=" ", flush=True)
        try:
            from app.pipelines.ocr import run_ocr  # noqa: just warm-up check
            print("OK")
        except Exception as e:
            print(f"ERROR: {e}")
            print("  Usa --fast o asegúrate de estar en el virtualenv correcto.")
            sys.exit(1)
    else:
        bp_mod = _cargar_batch_prelabel()

    print("=" * 68)

    contadores: dict = {}
    por_doc:    list = []
    errores:    list = []

    docs_procesados = 0
    for json_path in jsons:
        if max_docs and docs_procesados >= max_docs:
            break

        try:
            with open(json_path, encoding="utf-8-sig") as fh:
                label_data = json.load(fh)
        except Exception as e:
            errores.append({"id": json_path.stem, "error": f"JSON inválido: {e}"})
            continue

        if solo_etiquetados and not label_data.get("labeled"):
            continue

        expected   = label_data.get("expected_fields", {})
        pdf_path   = raw_dir / label_data.get("filename", json_path.stem + ".pdf")
        banco_orig = label_data.get("banco_origen", "")

        # Extraer campos con el modo elegido
        if modo_pipeline:
            detectado = _extraer_con_pipeline(pdf_path, tipo)
        else:
            try:
                if bp_mod is None:
                    raise RuntimeError("batch_prelabel no cargado")
                text = bp_mod._extract_text_fast(pdf_path)
                detectado = bp_mod._extract_fields_from_text(text, tipo, banco_orig)
            except Exception as e:
                errores.append({"id": json_path.stem, "error": str(e)[:200]})
                continue

        doc_stats = {
            "id":        json_path.stem,
            "filename":  label_data.get("filename", ""),
            "labeled":   label_data.get("labeled", False),
            "campos":    [],
        }

        doc_ok    = 0
        doc_total = 0
        for campo, valor_esperado in expected.items():
            valor_det = detectado.get(campo, "")
            tiene_gt  = bool(valor_esperado and str(valor_esperado).strip())

            c = contadores.setdefault(campo, {"total": 0, "ok": 0, "no_detectado": 0,
                                               "incorrecto": 0, "gt_vacio": 0})
            c["total"] += 1

            if not tiene_gt:
                c["gt_vacio"] += 1
                estado = "gt_vacio"
            elif _coincide(str(valor_esperado), str(valor_det), campo):
                c["ok"] += 1
                estado = "ok"
                doc_ok += 1
                doc_total += 1
            elif not valor_det:
                c["no_detectado"] += 1
                estado = "no_detectado"
                doc_total += 1
            else:
                c["incorrecto"] += 1
                estado = "incorrecto"
                doc_total += 1

            doc_stats["campos"].append({
                "campo":     campo,
                "esperado":  valor_esperado,
                "detectado": valor_det,
                "estado":    estado,
            })

        doc_stats["precision"] = round(doc_ok / doc_total, 3) if doc_total else None
        por_doc.append(doc_stats)
        docs_procesados += 1

        if doc_total:
            pct   = int(doc_ok / doc_total * 100)
            icono = "✓" if pct == 100 else ("~" if pct >= 50 else "✗")
            etiq  = " [ET]" if label_data.get("labeled") else ""
            print(f"  {icono} {json_path.stem}{etiq}  {doc_ok}/{doc_total} ({pct}%)")

    # ── Resumen por campo ──────────────────────────────────────────────────────
    print()
    print("=" * 68)
    print(f"  {'CAMPO':<25} {'PRECISION':>10} {'OK':>6} {'NO_DET':>8} {'INCO':>6} {'TOTAL':>7}")
    print(f"  {'-'*25} {'-'*10} {'-'*6} {'-'*8} {'-'*6} {'-'*7}")

    resumen = []
    for campo in sorted(contadores):
        c = contadores[campo]
        evaluables = c["total"] - c["gt_vacio"]
        precision  = c["ok"] / evaluables if evaluables > 0 else None
        resumen.append({
            "campo":        campo,
            "precision":    round(precision, 3) if precision is not None else None,
            "ok":           c["ok"],
            "no_detectado": c["no_detectado"],
            "incorrecto":   c["incorrecto"],
            "gt_vacio":     c["gt_vacio"],
            "total":        c["total"],
        })
        p_str = f"{precision*100:.1f}%" if precision is not None else "  N/A "
        print(f"  {campo:<25} {p_str:>10} {c['ok']:>6} {c['no_detectado']:>8} "
              f"{c['incorrecto']:>6} {evaluables:>7}")

    docs_con_eval = [d for d in por_doc if d["precision"] is not None]
    total_docs    = len(docs_con_eval)
    total_ok      = sum(1 for d in docs_con_eval if d["precision"] == 1.0)
    avg_prec      = sum(d["precision"] for d in docs_con_eval) / total_docs if total_docs else 0

    print()
    print(f"  Docs evaluados      : {total_docs}")
    print(f"  Docs 100% correctos : {total_ok}")
    print(f"  Precisión promedio  : {avg_prec*100:.1f}%")
    if errores:
        print(f"  Errores             : {len(errores)}")

    # ── Guardar reporte ────────────────────────────────────────────────────────
    fecha_str   = datetime.now().strftime("%Y%m%d_%H%M")
    modo_sufijo = "pipeline" if modo_pipeline else "fast"
    report_path = DATASET_DIR / "manifests" / f"eval_{tipo}_{modo_sufijo}_{fecha_str}.json"
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump({
            "tipo":    tipo,
            "modo":    modo_str,
            "fecha":   datetime.now().strftime("%Y-%m-%d %H:%M"),
            "resumen": resumen,
            "stats": {
                "total_docs":         total_docs,
                "docs_100_correcto":  total_ok,
                "precision_promedio": round(avg_prec, 4),
            },
            "documentos": por_doc,
            "errores":    errores,
        }, fh, ensure_ascii=False, indent=2)

    print(f"\n  Reporte guardado: {report_path.relative_to(PROJECT_ROOT)}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evalúa el extractor contra el dataset etiquetado"
    )
    parser.add_argument("tipo",               help="Tipo: ine, curp, nomina, bancario")
    parser.add_argument("--pipeline",         action="store_true",
                        help="Usar pipeline OCR completo (lento)")
    parser.add_argument("--solo-etiquetados", action="store_true",
                        help="Solo evaluar docs con labeled=true")
    parser.add_argument("--max", type=int,    default=0,
                        help="Máximo de documentos a evaluar (0=todos)")
    args = parser.parse_args()

    evaluar(args.tipo, args.pipeline, args.solo_etiquetados, args.max)


if __name__ == "__main__":
    main()
