"""
app/services/evaluation_service.py
=====================================
Servicio de evaluacion de calidad de extraccion NER/campo.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Normalizacion de valores para comparacion
# ---------------------------------------------------------------------------

def _normalize(value: str) -> str:
    if not value:
        return ""
    v = str(value).strip()
    v = unicodedata.normalize("NFD", v)
    v = v.encode("ascii", "ignore").decode("ascii")
    v = v.lower()
    v = re.sub(r"\s+", " ", v).strip()
    return v


def _values_match(predicted: str, expected: str) -> bool:
    p = _normalize(predicted)
    e = _normalize(expected)
    if not p or not e:
        return False
    return p == e


def _values_partial_match(predicted: str, expected: str) -> bool:
    p = _normalize(predicted)
    e = _normalize(expected)
    if not p or not e:
        return False
    return p in e or e in p


# ---------------------------------------------------------------------------
# Dataclasses de resultado
# ---------------------------------------------------------------------------

@dataclass
class DocFieldResult:
    key: str
    expected: str
    predicted: str
    confidence: float
    exact_match: bool
    partial_match: bool
    empty_predicted: bool
    false_positive: bool
    wrong_value: bool


@dataclass
class DocEvalResult:
    document_id: str
    document_type: str
    filename: str
    field_results: list[DocFieldResult] = field(default_factory=list)
    extra_predicted_keys: list[str] = field(default_factory=list)
    predicted_doc_type: str = ""
    doc_type_correct: bool = False
    table_row_count: int = 0
    table_has_data: bool = False
    exact_match_rate: float = 0.0
    filled_rate: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0

    def finalize(self) -> None:
        expected_nonempty = [r for r in self.field_results if r.expected.strip()]
        if not expected_nonempty:
            self.exact_match_rate = 1.0
            self.filled_rate = 1.0
            self.precision = 1.0
            self.recall = 1.0
            self.f1 = 1.0
            return

        tp = sum(1 for r in expected_nonempty if r.exact_match)
        fn = sum(1 for r in expected_nonempty if r.empty_predicted)
        wrong = sum(1 for r in expected_nonempty if r.wrong_value)
        fp_extra = len(self.extra_predicted_keys)

        total_fp = fp_extra + wrong
        total_fn = fn + wrong

        P = tp / (tp + total_fp) if (tp + total_fp) > 0 else 0.0
        R = tp / (tp + total_fn) if (tp + total_fn) > 0 else 0.0

        self.precision = round(P, 4)
        self.recall = round(R, 4)
        self.f1 = round(2 * P * R / (P + R), 4) if (P + R) > 0 else 0.0
        self.exact_match_rate = round(tp / len(expected_nonempty), 4)
        filled = sum(1 for r in expected_nonempty if r.predicted.strip())
        self.filled_rate = round(filled / len(expected_nonempty), 4)


@dataclass
class FieldMetrics:
    field_key: str
    total_expected: int = 0
    total_predicted: int = 0
    exact_matches: int = 0
    partial_matches: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    wrong_values: int = 0

    @property
    def precision(self) -> float:
        denom = self.exact_matches + self.false_positives + self.wrong_values
        return round(self.exact_matches / denom, 4) if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.exact_matches + self.false_negatives + self.wrong_values
        return round(self.exact_matches / denom, 4) if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return round(2 * p * r / (p + r), 4) if (p + r) > 0 else 0.0

    @property
    def exact_match_rate(self) -> float:
        return round(self.exact_matches / self.total_expected, 4) if self.total_expected > 0 else 0.0

    @property
    def empty_rate(self) -> float:
        return round(self.false_negatives / self.total_expected, 4) if self.total_expected > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_key":        self.field_key,
            "total_expected":   self.total_expected,
            "total_predicted":  self.total_predicted,
            "exact_matches":    self.exact_matches,
            "partial_matches":  self.partial_matches,
            "false_positives":  self.false_positives,
            "false_negatives":  self.false_negatives,
            "wrong_values":     self.wrong_values,
            "precision":        self.precision,
            "recall":           self.recall,
            "f1":               self.f1,
            "exact_match_rate": self.exact_match_rate,
            "empty_rate":       self.empty_rate,
        }


@dataclass
class TableMetrics:
    docs_evaluated: int = 0
    docs_with_table: int = 0
    total_rows_detected: int = 0
    avg_rows_per_doc: float = 0.0

    def finalize(self) -> None:
        if self.docs_evaluated > 0:
            self.avg_rows_per_doc = round(
                self.total_rows_detected / self.docs_evaluated, 2
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "docs_evaluated":      self.docs_evaluated,
            "docs_with_table":     self.docs_with_table,
            "table_coverage":      round(self.docs_with_table / self.docs_evaluated, 4)
                                   if self.docs_evaluated > 0 else 0.0,
            "total_rows_detected": self.total_rows_detected,
            "avg_rows_per_doc":    self.avg_rows_per_doc,
        }


@dataclass
class EvaluationReport:
    evaluated_at: str
    manifest_path: str
    force_type_used: bool = False
    docs_evaluated: int = 0
    docs_skipped: int = 0
    type_accuracy: float = 0.0
    type_correct: int = 0
    overall_exact_match_rate: float = 0.0
    overall_filled_rate: float = 0.0
    overall_precision: float = 0.0
    overall_recall: float = 0.0
    overall_f1: float = 0.0
    per_field: dict[str, FieldMetrics] = field(default_factory=dict)
    per_doc: list[DocEvalResult] = field(default_factory=list)
    table_metrics: TableMetrics = field(default_factory=TableMetrics)

    def finalize(self) -> None:
        if not self.per_doc:
            return

        for doc in self.per_doc:
            for fr in doc.field_results:
                if fr.key not in self.per_field:
                    self.per_field[fr.key] = FieldMetrics(field_key=fr.key)
                fm = self.per_field[fr.key]
                if fr.expected.strip():
                    fm.total_expected += 1
                    if fr.exact_match:
                        fm.exact_matches += 1
                    elif fr.partial_match:
                        fm.partial_matches += 1
                    elif fr.wrong_value:
                        fm.wrong_values += 1
                    elif fr.empty_predicted:
                        fm.false_negatives += 1
                if fr.predicted.strip():
                    fm.total_predicted += 1
                    if fr.false_positive:
                        fm.false_positives += 1

            for key in doc.extra_predicted_keys:
                if key not in self.per_field:
                    self.per_field[key] = FieldMetrics(field_key=key)
                self.per_field[key].false_positives += 1
                self.per_field[key].total_predicted += 1

        n = len(self.per_doc)
        self.overall_exact_match_rate = round(sum(d.exact_match_rate for d in self.per_doc) / n, 4)
        self.overall_filled_rate = round(sum(d.filled_rate for d in self.per_doc) / n, 4)
        self.overall_precision = round(sum(d.precision for d in self.per_doc) / n, 4)
        self.overall_recall = round(sum(d.recall for d in self.per_doc) / n, 4)
        p, r = self.overall_precision, self.overall_recall
        self.overall_f1 = round(2 * p * r / (p + r), 4) if (p + r) > 0 else 0.0
        self.type_correct = sum(1 for d in self.per_doc if d.doc_type_correct)
        self.type_accuracy = round(self.type_correct / n, 4) if n > 0 else 0.0
        self.table_metrics.finalize()

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluated_at":    self.evaluated_at,
            "manifest_path":   self.manifest_path,
            "force_type_used": self.force_type_used,
            "docs_evaluated":  self.docs_evaluated,
            "docs_skipped":    self.docs_skipped,
            "summary": {
                "type_accuracy":            self.type_accuracy,
                "type_correct":             self.type_correct,
                "overall_exact_match_rate": self.overall_exact_match_rate,
                "overall_filled_rate":      self.overall_filled_rate,
                "overall_precision":        self.overall_precision,
                "overall_recall":           self.overall_recall,
                "overall_f1":               self.overall_f1,
            },
            "per_field": {
                k: v.to_dict() for k, v in sorted(
                    self.per_field.items(),
                    key=lambda x: -x[1].total_expected,
                )
            },
            "table_metrics": self.table_metrics.to_dict(),
            "per_doc": [
                {
                    "document_id":          d.document_id,
                    "document_type":        d.document_type,
                    "predicted_doc_type":   d.predicted_doc_type,
                    "doc_type_correct":     d.doc_type_correct,
                    "filename":             d.filename,
                    "exact_match_rate":     d.exact_match_rate,
                    "filled_rate":          d.filled_rate,
                    "precision":            d.precision,
                    "recall":               d.recall,
                    "f1":                   d.f1,
                    "table_rows":           d.table_row_count,
                    "fields": [
                        {
                            "key":            fr.key,
                            "expected":       fr.expected,
                            "predicted":      fr.predicted,
                            "confidence":     fr.confidence,
                            "exact_match":    fr.exact_match,
                            "partial_match":  fr.partial_match,
                            "false_positive": fr.false_positive,
                            "false_negative": fr.empty_predicted,
                            "wrong_value":    fr.wrong_value,
                        }
                        for fr in d.field_results
                    ],
                    "extra_predicted_keys": d.extra_predicted_keys,
                }
                for d in self.per_doc
            ],
        }


# ---------------------------------------------------------------------------
# Evaluacion de un documento
# ---------------------------------------------------------------------------

def _get_predicted_value(predicted_fields: list[dict], key: str) -> tuple[str, float]:
    for f in predicted_fields:
        if f.get("key") == key:
            v = f.get("value") or f.get("corrected_value") or ""
            c = float(f.get("confidence") or 0.0)
            return str(v).strip(), c
    return "", 0.0


def evaluate_document(
    predicted_fields: list[dict],
    expected_fields: dict[str, str],
    doc_id: str = "",
    doc_type: str = "",
    filename: str = "",
    table_rows: int = 0,
) -> DocEvalResult:
    result = DocEvalResult(
        document_id=doc_id,
        document_type=doc_type,
        filename=filename,
        table_row_count=table_rows,
        table_has_data=table_rows > 0,
    )

    predicted_keyset = {
        f.get("key", ""): (f.get("value") or f.get("corrected_value") or "")
        for f in predicted_fields
        if f.get("key")
    }

    for key, expected_val in expected_fields.items():
        predicted_val, confidence = _get_predicted_value(predicted_fields, key)
        e = expected_val.strip()
        p = predicted_val.strip()

        exact = _values_match(p, e)
        partial = (not exact) and _values_partial_match(p, e)
        empty_pred = bool(e and not p)
        fp = bool(p and not e)
        wrong = bool(p and e and not exact and not partial)

        result.field_results.append(DocFieldResult(
            key=key,
            expected=e,
            predicted=p,
            confidence=round(confidence, 4),
            exact_match=exact,
            partial_match=partial,
            empty_predicted=empty_pred,
            false_positive=fp,
            wrong_value=wrong,
        ))

    for pk, pv in predicted_keyset.items():
        if pk not in expected_fields and pv.strip():
            result.extra_predicted_keys.append(pk)

    result.finalize()
    return result


# ---------------------------------------------------------------------------
# Evaluacion del dataset completo (async)
# ---------------------------------------------------------------------------

async def evaluate_dataset(
    manifest_path: str,
    extractor_fn: Callable[[str, str], Awaitable[dict[str, Any]]] | None = None,
    labeled_base_dir: str | None = None,
    max_docs: int | None = None,
) -> EvaluationReport:
    from app.training.ner_data_builder import load_labeled_docs

    if extractor_fn is None:
        extractor_fn = _default_extractor

    docs = load_labeled_docs(manifest_path, labeled_base_dir)
    if max_docs:
        docs = docs[:max_docs]

    report = EvaluationReport(
        evaluated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        manifest_path=manifest_path,
    )
    report.table_metrics.docs_evaluated = len(docs)

    for doc in docs:
        doc_id   = doc.get("document_id", doc.get("filename", ""))
        doc_type = doc.get("document_type", doc.get("tipo_documento", ""))
        filename = doc.get("filename", "")
        pdf_path = doc.get("pdf_full_path", "")
        expected = doc.get("expected_fields", {})

        if not pdf_path or not os.path.exists(pdf_path):
            logger.debug("PDF no encontrado para %s: %s", doc_id, pdf_path)
            report.docs_skipped += 1
            continue

        try:
            prediction = await extractor_fn(pdf_path, filename)
        except Exception as exc:
            logger.warning("Extraccion fallo para %s: %s", doc_id, exc)
            report.docs_skipped += 1
            continue

        predicted_fields: list[dict] = prediction.get("fields", [])
        table = prediction.get("table", {})
        table_rows = len(table.get("rows") or [])
        if table_rows > 0:
            report.table_metrics.docs_with_table += 1
        report.table_metrics.total_rows_detected += table_rows

        doc_result = evaluate_document(
            predicted_fields=predicted_fields,
            expected_fields=expected,
            doc_id=str(doc_id),
            doc_type=str(doc_type),
            filename=str(filename),
            table_rows=table_rows,
        )
        report.per_doc.append(doc_result)
        report.docs_evaluated += 1

    report.finalize()
    return report


# ✅ FIX: tipo de retorno correcto y await directo sobre process_document (es async)
async def _default_extractor(pdf_path: str, filename: str) -> dict[str, Any]:
    """Extractor por defecto: usa extractor_service.process_document directamente."""
    from app.services.extractor_service import process_document as _process
    result: dict[str, Any] = await _process(pdf_path, filename)
    return result


# ---------------------------------------------------------------------------
# Evaluacion sincrona simple (para scripts CLI)
# ---------------------------------------------------------------------------

def evaluate_dataset_sync(
    manifest_path: str,
    labeled_base_dir: str | None = None,
    max_docs: int | None = None,
    force_type: bool = False,
) -> EvaluationReport:
    from app.training.ner_data_builder import load_labeled_docs
    from app.services.extractor_service import process_document as _async_extract

    docs = load_labeled_docs(manifest_path, labeled_base_dir)
    if max_docs:
        docs = docs[:max_docs]

    report = EvaluationReport(
        evaluated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        manifest_path=manifest_path,
        force_type_used=force_type,
    )
    report.table_metrics.docs_evaluated = len(docs)

    for idx, doc in enumerate(docs, 1):
        doc_id   = doc.get("document_id", doc.get("filename", ""))
        doc_type = doc.get("document_type", doc.get("tipo_documento", ""))
        filename = doc.get("filename", "")
        pdf_path = doc.get("pdf_full_path", "")
        expected = doc.get("expected_fields", {})

        if not pdf_path or not os.path.exists(pdf_path):
            report.docs_skipped += 1
            continue

        ft = doc_type if force_type else None
        try:
            prediction: dict[str, Any] = asyncio.run(_async_extract(pdf_path, filename, force_type=ft))
        except Exception as exc:
            logger.warning("Extraccion fallo para %s: %s", doc_id, exc)
            report.docs_skipped += 1
            continue

        predicted_fields: list[dict] = prediction.get("fields", [])
        predicted_type = prediction.get("tipo_documento", "") or ""
        table = prediction.get("table", {})
        table_rows = len(table.get("rows") or [])
        if table_rows > 0:
            report.table_metrics.docs_with_table += 1
        report.table_metrics.total_rows_detected += table_rows

        doc_result = evaluate_document(
            predicted_fields=predicted_fields,
            expected_fields=expected,
            doc_id=str(doc_id),
            doc_type=str(doc_type),
            filename=str(filename),
            table_rows=table_rows,
        )
        doc_result.predicted_doc_type = predicted_type
        doc_result.doc_type_correct = (
            _normalize(predicted_type) == _normalize(doc_type)
        )
        report.per_doc.append(doc_result)
        report.docs_evaluated += 1

        type_tag = "OK" if doc_result.doc_type_correct else "!!"
        print(
            f"  [{idx:>3}/{len(docs)}] [{type_tag}] {doc_type:<20} {filename[:28]:<28}"
            f"  exact={doc_result.exact_match_rate * 100:4.0f}%"
            f"  F1={doc_result.f1:.3f}"
        )

    report.finalize()
    return report


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------

def save_report(report: EvaluationReport, path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
    logger.info("Informe guardado en: %s", path)


def load_report(path: str) -> dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.error("No se pudo cargar el informe %s: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Resumen imprimible
# ---------------------------------------------------------------------------

def print_summary(report: EvaluationReport) -> None:
    mode = "force_type=SI" if report.force_type_used else "force_type=NO (end-to-end)"
    print()
    print("=" * 68)
    print("  EVALUACION DE EXTRACCION  [" + mode + "]")
    print("=" * 68)
    print(f"  Fecha         : {report.evaluated_at}")
    print(f"  Docs evaluados: {report.docs_evaluated}  (omitidos: {report.docs_skipped})")
    print()
    print("  CLASIFICACION DE TIPO DE DOCUMENTO")
    print(f"    Correcto     : {report.type_correct}/{report.docs_evaluated}"
          f"  ({report.type_accuracy * 100:.1f}%)")
    if not report.force_type_used:
        wrong_types = [
            (d.filename, d.document_type, d.predicted_doc_type)
            for d in report.per_doc if not d.doc_type_correct
        ]
        if wrong_types:
            print("    Clasificados mal:")
            for fn, exp, pred in wrong_types[:10]:
                print(f"      {fn[:30]:<30}  esperado={exp:<22} predicho={pred}")
            if len(wrong_types) > 10:
                print(f"      ... y {len(wrong_types)-10} mas")
    print()
    print("  METRICAS GLOBALES DE CAMPOS")
    print(f"    Exact match  : {report.overall_exact_match_rate * 100:.1f}%")
    print(f"    Filled rate  : {report.overall_filled_rate * 100:.1f}%")
    print(f"    Precision    : {report.overall_precision:.4f}")
    print(f"    Recall       : {report.overall_recall:.4f}")
    print(f"    F1           : {report.overall_f1:.4f}")
    print()
    print("  METRICAS POR CAMPO")
    print(f"  {'Campo':<20} {'Exacto':>7} {'Vacios':>7} {'P':>6} {'R':>6} {'F1':>6}  {'TP/Tot':>8}")
    print("  " + "-" * 60)
    for key, fm in sorted(report.per_field.items(), key=lambda x: -x[1].total_expected):
        print(
            f"  {key:<20} "
            f"{fm.exact_match_rate * 100:>6.0f}% "
            f"{fm.empty_rate * 100:>6.0f}% "
            f"{fm.precision:>6.3f} "
            f"{fm.recall:>6.3f} "
            f"{fm.f1:>6.3f}  "
            f"{fm.exact_matches}/{fm.total_expected:>4}"
        )
    print()
    print("  TABLAS")
    tm = report.table_metrics
    cov = tm.docs_with_table / tm.docs_evaluated * 100 if tm.docs_evaluated else 0
    print(f"    Docs con tabla: {tm.docs_with_table}/{tm.docs_evaluated} ({cov:.0f}%)")
    print(f"    Filas promedio: {tm.avg_rows_per_doc:.1f}")
    print("=" * 68)
    print()