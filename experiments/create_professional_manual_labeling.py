"""Create a compact professional manual-labeling worksheet.

This keeps the research-critical columns from the wide benchmark file without
asking a human reviewer to fill 100+ fields per column.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = Path(os.environ.get("BUCKAROO_MANUAL_LABEL_DIR", ROOT / "outputs" / "manual_labeling_5_datasets"))
FULL_BLANK = BASE / "manual_column_labeling_research_grade_blank.csv"
FULL_FILLED = BASE / "manual_column_labeling_research_grade_with_taxi_filled.csv"

COMPACT_BLANK = BASE / "manual_column_labeling_professional_blank.csv"
COMPACT_FILLED = BASE / "manual_column_labeling_professional_with_taxi_filled.csv"
COMPACT_TAXI = BASE / "taxi_trips_manual_labels_professional_filled.csv"
CODEBOOK = BASE / "manual_labeling_professional_codebook.md"


COLUMNS = [
    # Evidence from the data.
    "dataset_id",
    "column_name",
    "row_count",
    "null_ratio",
    "unique_ratio",
    "sample_values",
    "common_values",
    # Human semantic label.
    "manual_true_role",
    "manual_secondary_role",
    "manual_physical_type",
    "semantic_group",
    "manual_label_confidence",
    # Key and false-key analysis.
    "is_primary_key",
    "is_foreign_key",
    "could_be_key_by_uniqueness",
    "should_be_key_candidate_for_buckaroo",
    "is_high_uniqueness_but_not_key",
    "key_rejection_reason",
    # Major edge-case flags.
    "is_datetime_or_lifecycle_event",
    "is_geographic_or_location",
    "is_measure_or_metric",
    "is_money_amount",
    "is_count_or_quantity",
    "nominal_category",
    "has_missing_values",
    "missingness_severity",
    # Sampling and confidence.
    "sample_size_sensitivity",
    "small_sample_false_key_risk",
    "adaptive_sampling_priority",
    "expected_candidate_roles",
    "expected_confidence_behavior",
    # SBERT / advanced semantic ML.
    "requires_semantic_ml",
    "recommended_semantic_model",
    "sbert_use_recommended",
    "simple_rules_enough",
    "advanced_ml_analysis_reason",
    # Expected Buckaroo behavior.
    "expected_buckaroo_role",
    "expected_warning_type",
    "should_buckaroo_warn",
    "ui_user_facing_explanation",
    # Research usefulness.
    "profiler_failure_mode_to_test",
    "professor_question_to_answer",
    "paper_claim_supported",
    "why_this_label",
    "edge_case_or_risk",
    "reviewer_notes",
]


def compact_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [{column: row.get(column, "") for column in COLUMNS} for row in reader]


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_codebook() -> None:
    CODEBOOK.write_text(
        """# Professional Manual Labeling Codebook

This is the practical worksheet to use for manual labeling. It keeps the core research fields while avoiding the 100+ column version.

## How to use it

Fill one row per dataset column. If you are unsure, use `maybe` and explain why in `edge_case_or_risk` or `reviewer_notes`.

## Most important columns

- `manual_true_role`: the human semantic label, such as `datetime`, `numeric_measure`, `location_name`, or `categorical`.
- `is_primary_key`: yes/no. Only yes if this column truly identifies each row.
- `could_be_key_by_uniqueness`: yes/no/maybe. Does it statistically look unique?
- `should_be_key_candidate_for_buckaroo`: yes/no/maybe. Should Buckaroo actually consider it as a key?
- `is_high_uniqueness_but_not_key`: yes/no. This is the main false-key research label.
- `requires_semantic_ml`: yes/no/maybe. Use yes or maybe when rules/statistics are not enough.
- `sbert_use_recommended`: yes/no/maybe. Good for place names, occupations, descriptions, product names, and ambiguous text.
- `adaptive_sampling_priority`: low/medium/high. Use high when Buckaroo should inspect more rows before deciding.
- `expected_buckaroo_role`: what the improved profiler should output.
- `expected_warning_type`: warning Buckaroo should show, if any.
- `profiler_failure_mode_to_test`: the specific mistake this column helps test.

## Golden rule

Do not call a column a primary key just because it is unique. A timestamp, location, price, or name can be unique without being row identity.
""",
        encoding="utf-8",
    )


def main() -> None:
    blank_rows = compact_rows(FULL_BLANK)
    filled_rows = compact_rows(FULL_FILLED)
    taxi_rows = [row for row in filled_rows if row["dataset_id"] == "taxi_trips"]

    write_csv(COMPACT_BLANK, blank_rows)
    write_csv(COMPACT_FILLED, filled_rows)
    write_csv(COMPACT_TAXI, taxi_rows)
    write_codebook()

    print(COMPACT_BLANK)
    print(COMPACT_FILLED)
    print(COMPACT_TAXI)
    print(CODEBOOK)
    print(f"columns={len(COLUMNS)} rows={len(filled_rows)}")


if __name__ == "__main__":
    main()
