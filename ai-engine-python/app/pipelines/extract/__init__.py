"""extract package - decomposed from monolithic extract.py.

Re-exports every public AND private symbol so that existing imports
like ``from app.pipelines.extract import _payment_detect_bank`` keep
working without changes.
"""

# --- Wildcard re-exports (runtime catch-all) ---
from .constants import *    # noqa: F401,F403
from .common import *       # noqa: F401,F403
from .tables import *       # noqa: F401,F403
from .extractors import *   # noqa: F401,F403
from .orchestrator import * # noqa: F401,F403

# --- Explicit re-exports for static analysis (Pyright / Pylance) ---
# common.py
from .common import (  # noqa: F811
    _apply_cross_field_checks,
    _assess_ocr_quality,
    _clean_address_value,
    _is_garbage_value,
    _make_field,
    _name_matches_curp,
    _normalize_date_to_yymmdd,
    _normalize_payment_amount,
    _normalize_reference_value,
    _normalize_text,
    _postprocess_fields,
    _try_repair_name_with_curp,
)

# tables.py
from .tables import (  # noqa: F811
    _ALL_PAYMENT_STATUSES,
    _build_display_columns_map,
    _build_payment_mapped_fields,
    _canonical_payment_key,
    _classify_table_columns,
    _clean_metadata_from_cell,
    _DATA_TOKEN_PAT,
    _dedup_header_cell,
    _dedup_header_row,
    _extract_bbva_nomina_advanced_rows_from_text,
    _extract_bbva_payment_metadata,
    _extract_generic_bank_payment_metadata,
    _extract_generic_tables_from_text,
    _extract_generic_tables_from_text_pattern_split,
    _extract_payment_detail_payload,
    _extract_payment_table_payload,
    _extract_payment_table_rows_from_boxes,
    _extract_payment_table_rows_from_pdf_tables,
    _extract_santander_payment_metadata,
    _fix_payment_ocr_column_errors,
    _header_cell_has_repeated_tokens,
    _is_metadata_row,
    _is_summary_row,
    _merge_payment_rows_with_backup,
    _merge_row_similarity,
    _normalize_payment_table_rows,
    _parse_amount_to_cents,
    _payment_detect_bank,
    _payment_header_alias,
    _payment_header_token_index,
    _payment_rows_quality_score,
    _payment_rows_to_objects,
    _payment_to_canonical_rows,
    _pdf_tables_to_generic_payloads,
    _smart_split_narrow_line,
    _split_line_by_data_patterns,
    _STATUS_PREFIX_PAT,
    _STATUS_SEARCH_PAT,
    _validate_payment_table_cells,
    _validate_payment_table_coherence,
)

# orchestrator.py
from .orchestrator import extract_fields  # noqa: F811

# extractors.py — generic extraction
from .extractors import (  # noqa: F811
    _extract_generic_all_tables,
    _extract_generic_identifiers,
    _extract_generic_kv_from_boxes,
    _extract_generic_kv_from_text,
    _is_valid_generic_label,
    _is_valid_generic_value,
    _slugify_label,
)
