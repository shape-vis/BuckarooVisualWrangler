"""Test different definitions for dataset column-type profiling.

Beginner-friendly overview
==========================

This file is an *experiment*, not production app code.  It answers one
practical Buckaroo question:

    Which rule set best decides whether a column is numeric, categorical,
    free_text, or identifier?

Why this matters:

- Numeric columns should be sent to numeric profiling / anomaly logic.
- Categorical columns should be treated as repeated labels or groups.
- Free-text columns may be useful for semantic grouping or SBERT embeddings.
- Identifier columns such as IDs, ZIP codes, VINs, and complaint IDs should not
  be treated as meaningful categories just because they have many unique values.

The experiment uses a small human-labeled answer key from real datasets.  Think
of that answer key as the "teacher's answer sheet."  Then the script tries many
candidate rule sets and asks:

    How many columns did each rule set classify correctly?

High-level flow:

1. Define the expected role for selected columns in real CSV files.
2. Measure simple evidence for each labeled column, such as:
   numeric ratio, unique-value ratio, average text length, and ID-like name.
3. Try several named definitions and many threshold combinations.
4. Score each definition against the manual labels.
5. Write CSV outputs and a Markdown report explaining which definition worked
   best.
"""

from __future__ import annotations

import itertools
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.profile_dataset_shape import classify_column as classify_profile_column  # noqa: E402
from experiments.profile_dataset_shape import is_missing_value  # noqa: E402
from detectors.approx_cardinality import distinct_count_profile  # noqa: E402


DATASET_DIR = ROOT / "provided_datasets"
OUT_DIR = ROOT / "experiments" / "column_type_definition_outputs"

# The experiment reads only the first SAMPLE_ROWS rows from each dataset.
# This keeps the script fast enough to run repeatedly while still giving enough
# data to estimate uniqueness, numeric-ness, and text length.
SAMPLE_ROWS = 3000

# These are the only column roles this experiment is trying to predict.
# If you add a new role here, you also need to update the classifier logic and
# the manual labels.
ROLES = ("numeric", "categorical", "free_text", "identifier")

# This is the human/common-sense answer key.  It is intentionally small enough
# to inspect by hand, but broad enough to include the tricky examples from the
# project discussion: ZIP codes, VINs, long text, dates, and IDs.
MANUAL_LABELS: dict[str, dict[str, str]] = {
    "adult.csv": {
        "age": "numeric",
        "workclass": "categorical",
        "fnlwgt": "numeric",
        "education": "categorical",
        "educational-num": "numeric",
        "marital-status": "categorical",
        "occupation": "categorical",
        "relationship": "categorical",
        "race": "categorical",
        "gender": "categorical",
        "capital-gain": "numeric",
        "capital-loss": "numeric",
        "hours-per-week": "numeric",
        "native-country": "categorical",
        "income": "categorical",
    },
    "cars.csv": {
        "Unnamed: 0": "identifier",
        "id": "identifier",
        "region": "categorical",
        "price": "numeric",
        "year": "numeric",
        "manufacturer": "categorical",
        "model": "categorical",
        "condition": "categorical",
        "cylinders": "categorical",
        "fuel": "categorical",
        "odometer": "numeric",
        "title_status": "categorical",
        "transmission": "categorical",
        "VIN": "identifier",
        "drive": "categorical",
        "size": "categorical",
        "type": "categorical",
        "paint_color": "categorical",
        "description": "free_text",
        "county": "categorical",
        "state": "categorical",
        "posting_date": "identifier",
    },
    "complaints-2025-04-21_17_31.csv": {
        "Date received": "categorical",
        "Product": "categorical",
        "Sub-product": "categorical",
        "Issue": "categorical",
        "Sub-issue": "categorical",
        "Consumer complaint narrative": "free_text",
        "Company public response": "free_text",
        "Company": "categorical",
        "State": "categorical",
        "ZIP code": "identifier",
        "Tags": "categorical",
        "Consumer consent provided?": "categorical",
        "Submitted via": "categorical",
        "Date sent to company": "categorical",
        "Company response to consumer": "categorical",
        "Timely response?": "categorical",
        "Consumer disputed?": "categorical",
        "Complaint ID": "identifier",
    },
}


@dataclass(frozen=True)
class ColumnTypeDefinition:
    """One candidate rule set for deciding a column's role.

    Each instance is one "definition" of column type.  For example, one
    definition may say "a column is numeric if 90% of values parse as numbers,"
    while another says "a column is numeric only if 99% parse as numbers."

    The experiment creates many of these definitions and scores each one.
    The fields below are thresholds used by classify_with_definition().
    """

    name: str

    # Fraction of non-missing values that must successfully parse as numbers
    # before the column can be called numeric.  Example: 0.90 means 90%.
    numeric_threshold: float

    # A numeric-looking column must have more than this many distinct values.
    # This prevents small code-like categories such as 0/1 or 1/2/3 from being
    # treated as continuous numeric measurements.
    numeric_min_unique: int

    # If the column name looks like an ID column, this is the uniqueness ratio
    # required before calling it an identifier.
    id_name_cardinality_threshold: float

    # If the column name does NOT hint at ID, this stricter uniqueness ratio can
    # still classify the column as an identifier.
    identifier_cardinality_threshold: float

    # Free-text columns usually have many distinct values.  This threshold is
    # the uniqueness ratio needed before considering a column open text.
    free_text_cardinality_threshold: float

    # Average character length needed before high-cardinality text looks like
    # free text rather than short labels.
    free_text_min_length: float

    # Average word count needed before high-cardinality text looks like free
    # text.  Word count catches text even when characters are short.
    free_text_min_words: float

    # A column can be called free_text even without high cardinality if values
    # are very wordy.  This catches repeated long comments or descriptions.
    long_text_min_words: float

    # When this is True, the definition delegates to the newer profiler rules
    # from profile_dataset_shape.py.  That lets this experiment compare the old
    # threshold-only definitions against the richer research-backed profiler.
    use_research_rules: bool = False


def compute_column_evidence(dataset: str, column: str, series: pd.Series) -> dict[str, Any]:
    """Measure the raw signals that the rule definitions use.

    This function does NOT decide the column role.  It only measures evidence.

    Example evidence:

    - How many non-missing values does the column have?
    - How many unique values are there?
    - What fraction of values parse as numbers?
    - How long are the values as text?
    - Does the column name contain hints like "id", "zip", or "vin"?

    Separating "evidence measurement" from "classification rules" is useful
    because the experiment can reuse the same evidence for thousands of
    different threshold definitions.
    """

    # Remove missing values before calculating statistics.  Missing cells should
    # not make a column look less numeric or less textual.
    non_missing = series[~series.map(is_missing_value)]
    non_missing_count = int(len(non_missing))

    if non_missing_count == 0:
        # If a column has no usable values, all evidence is zero/false.  The
        # classifier later treats this as categorical because there is not
        # enough evidence for any specialized role.
        return {
            "dataset": dataset,
            "column": column,
            "non_missing_count": 0,
            "unique_count": 0,
            "cardinality_ratio": 0.0,
            "distinct_count_method": "exact",
            "unique_count_is_estimated": False,
            "numeric_ratio": 0.0,
            "avg_text_length": 0.0,
            "avg_word_count": 0.0,
            "id_name_hint": False,
            "research_role": "categorical",
            "research_profile_role": "empty",
            "research_confidence": "low",
            "research_reason": "No non-missing values were available for profiling.",
            "research_warning": "Empty columns need manual review before detector tuning.",
        }

    # Convert values to stripped text so uniqueness and text-length checks work
    # consistently for strings, numbers, dates, and mixed object values.
    as_text = non_missing.astype(str).str.strip()

    # Try to parse values as numbers.  Non-numeric values become NaN; the ratio
    # of successful parses is the numeric evidence.
    numeric = pd.to_numeric(non_missing, errors="coerce")
    distinct_profile = distinct_count_profile(as_text)

    # A name hint is intentionally simple.  It does not prove a column is an ID,
    # but it lets columns like "Complaint ID", "VIN", and "ZIP code" use a more
    # appropriate identifier threshold.
    lower_name = str(column).strip().lower()
    id_name_hint = any(token in lower_name for token in ("id", "case", "zip", "vin", "unnamed"))

    # Run the improved profiler once and store its answer as evidence.  The
    # threshold sweep below can still test older/simple definitions, while the
    # named "research_profile_rules" definition can reuse this richer answer.
    research_profile = classify_profile_column(column, series)

    return {
        "dataset": dataset,
        "column": column,
        "non_missing_count": non_missing_count,
        "unique_count": int(distinct_profile.unique_count),
        "cardinality_ratio": float(distinct_profile.cardinality_ratio),
        "distinct_count_method": distinct_profile.method,
        "unique_count_is_estimated": bool(distinct_profile.is_estimated),
        "numeric_ratio": float(numeric.notna().mean()),
        "avg_text_length": float(as_text.str.len().mean()),
        "avg_word_count": float(as_text.str.split().str.len().mean()),
        "id_name_hint": bool(id_name_hint),
        "research_role": research_profile["role"],
        "research_profile_role": research_profile["profile_role"],
        "research_confidence": research_profile["confidence"],
        "research_reason": research_profile["reason"],
        "research_warning": research_profile["warning"],
    }


def classify_with_definition(evidence: dict[str, Any], definition: ColumnTypeDefinition) -> str:
    """Apply one candidate definition to one column's evidence.

    This is the core decision tree of the experiment.  It reads the evidence
    from compute_column_evidence() and returns one of:

        numeric, categorical, free_text, identifier

    The order of checks matters:

    1. Identifier-by-name is checked early so obvious ID-like columns do not
       become numeric just because their values are numeric IDs.
    2. Numeric is checked before generic identifier so real measurements like
       age or price can still be numeric.
    3. High-cardinality short text can become identifier.
    4. High-cardinality long/wordy text can become free_text.
    5. Anything left over is categorical.
    """

    if definition.use_research_rules:
        # The richer profiler still returns one of the broad roles in
        # research_role, so the scoring code can use the same manual answer key.
        return str(evidence["research_role"])

    if evidence["non_missing_count"] == 0:
        return "categorical"

    # If the column name looks ID-like and most values are unique, call it an
    # identifier.  Example: "Complaint ID" or "VIN".
    if evidence["id_name_hint"] and evidence["cardinality_ratio"] >= definition.id_name_cardinality_threshold:
        return "identifier"

    # A column is numeric only if most values parse as numbers AND it has enough
    # distinct values to look like a measurement rather than a small category.
    if (
        evidence["numeric_ratio"] >= definition.numeric_threshold
        and evidence["unique_count"] > definition.numeric_min_unique
    ):
        return "numeric"

    # If nearly every value is unique and the values are short, the column is
    # probably an identifier even if the name did not include "id".
    # Example: generated case numbers with a neutral column name.
    if evidence["cardinality_ratio"] >= definition.identifier_cardinality_threshold and evidence["avg_word_count"] < 4:
        return "identifier"

    # Free text generally has many unique values and either long strings or
    # multiple words per value.
    looks_like_open_text = (
        evidence["cardinality_ratio"] >= definition.free_text_cardinality_threshold
        and (
            evidence["avg_text_length"] >= definition.free_text_min_length
            or evidence["avg_word_count"] >= definition.free_text_min_words
        )
    )

    # This catches repeated long text values.  For example, if many rows share a
    # repeated long description, cardinality may be lower, but it is still text.
    very_wordy_even_if_repeated = evidence["avg_word_count"] >= definition.long_text_min_words
    if looks_like_open_text or very_wordy_even_if_repeated:
        return "free_text"

    # Default fallback: repeated labels, short strings, booleans, dates encoded
    # as categories in this experiment, and other low-cardinality fields.
    return "categorical"


def named_definitions() -> list[ColumnTypeDefinition]:
    """Return a few human-readable baseline definitions.

    These definitions are not generated by the big threshold sweep.  They are
    named so the report can compare easy concepts:

    - current_profiler: the current rule set we want to compare against.
    - research_profile_rules: the richer profiler with numeric-code and vector
      blob handling.
    - lenient_numeric / strict_numeric: change only numeric strictness.
    - lenient_identifier / strict_identifier: change only ID strictness.
    - lenient_free_text / strict_free_text: change only free-text strictness.

    These are useful for explanation because "sweep_01423" is hard to discuss
    in a meeting, but "strict_free_text" is understandable.
    """

    # Positional parameter legend for the presets below:
    #
    # ColumnTypeDefinition(
    #     name,
    #     numeric_threshold,
    #     numeric_min_unique,
    #     id_name_cardinality_threshold,
    #     identifier_cardinality_threshold,
    #     free_text_cardinality_threshold,
    #     free_text_min_length,
    #     free_text_min_words,
    #     long_text_min_words,
    # )
    #
    # Example baseline values in plain English:
    # - 0.90 numeric_threshold: at least 90% of values must parse as numeric.
    # - 3 numeric_min_unique: numeric columns need more than 3 unique values.
    # - 0.50 id_name_cardinality_threshold: ID-name columns need at least 50%
    #   unique values before we call them identifiers.
    # - 0.90 identifier_cardinality_threshold: non-ID-name columns need at
    #   least 90% unique values before we call them identifiers.
    # - 0.20 free_text_cardinality_threshold: free text should have at least
    #   20% unique values, unless the text is very wordy.
    # - 30 free_text_min_length: free-text values should average at least
    #   30 characters.
    # - 5 free_text_min_words: free-text values should average at least 5 words.
    # - 10 long_text_min_words: repeated text can still be free text if values
    #   average at least 10 words.
    return [
        ColumnTypeDefinition("current_profiler", 0.90, 3, 0.50, 0.90, 0.20, 30, 5, 10),
        ColumnTypeDefinition(
            "research_profile_rules",
            0.90,
            3,
            0.50,
            0.90,
            0.20,
            30,
            5,
            10,
            use_research_rules=True,
        ),
        ColumnTypeDefinition("lenient_numeric", 0.80, 3, 0.50, 0.90, 0.20, 30, 5, 10),
        ColumnTypeDefinition("strict_numeric", 0.99, 3, 0.50, 0.90, 0.20, 30, 5, 10),
        ColumnTypeDefinition("lenient_identifier", 0.90, 3, 0.20, 0.80, 0.20, 30, 5, 10),
        ColumnTypeDefinition("strict_identifier", 0.90, 3, 0.80, 0.98, 0.20, 30, 5, 10),
        ColumnTypeDefinition("lenient_free_text", 0.90, 3, 0.50, 0.90, 0.05, 20, 3, 8),
        ColumnTypeDefinition("strict_free_text", 0.90, 3, 0.50, 0.90, 0.40, 80, 8, 15),
    ]


def threshold_sweep_definitions() -> list[ColumnTypeDefinition]:
    """Generate many possible definitions by trying threshold combinations.

    This is the brute-force part of the experiment.  It tries every combination
    of the threshold values below.  Each combination becomes one
    ColumnTypeDefinition named sweep_00001, sweep_00002, etc.

    The goal is not to use the generated name directly in production.  The goal
    is to discover which ranges of threshold values work well.
    """

    # Each list below is a small set of plausible values.  itertools.product()
    # tries every cross-product combination.
    values = {
        "numeric_threshold": [0.80, 0.90, 0.95, 0.99],
        "numeric_min_unique": [3, 10],
        "id_name_cardinality_threshold": [0.20, 0.50, 0.75, 0.90],
        "identifier_cardinality_threshold": [0.80, 0.90, 0.98],
        "free_text_cardinality_threshold": [0.05, 0.20, 0.40],
        "free_text_min_length": [20, 30, 50, 80],
        "free_text_min_words": [3, 5, 8, 10],
        "long_text_min_words": [8, 10, 15],
    }

    definitions = []
    keys = list(values)
    for index, combo in enumerate(itertools.product(*(values[key] for key in keys)), start=1):
        # zip(keys, combo) turns a tuple like (0.90, 3, 0.50, ...)
        # into named arguments like {"numeric_threshold": 0.90, ...}.
        kwargs = dict(zip(keys, combo, strict=True))
        definitions.append(ColumnTypeDefinition(name=f"sweep_{index:05d}", **kwargs))
    return definitions


def load_labeled_column_evidence() -> pd.DataFrame:
    """Load real datasets and compute evidence for every manually labeled column.

    MANUAL_LABELS says what each selected column *should* be.  This function
    reads those columns from the CSV files and calculates the evidence columns
    that the classifier needs.

    Output shape:

        one row per labeled column

    Example row:

        dataset=cars.csv
        column=VIN
        expected_role=identifier
        cardinality_ratio=0.99
        numeric_ratio=0.0
        avg_word_count=1.0
    """

    rows: list[dict[str, Any]] = []
    for dataset, labels in MANUAL_LABELS.items():
        csv_path = DATASET_DIR / dataset

        # low_memory=False avoids pandas guessing different dtypes for chunks of
        # the same column in larger CSV files.
        df = pd.read_csv(csv_path, nrows=SAMPLE_ROWS, low_memory=False)
        for column, expected_role in labels.items():
            if column not in df.columns:
                raise KeyError(f"{dataset} is missing labeled column {column!r}")
            evidence = compute_column_evidence(dataset, column, df[column])

            # Attach the human answer so score_definition() can compare
            # predicted_role vs expected_role.
            evidence["expected_role"] = expected_role
            rows.append(evidence)

    return pd.DataFrame(rows)


def score_definition(definition: ColumnTypeDefinition, evidence_frame: pd.DataFrame) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Score one definition and return summary metrics plus predictions.

    In beginner terms:

    - Take one candidate rule set.
    - Use it to predict the role of every labeled column.
    - Compare each prediction to the manual answer key.
    - Count how often it was correct.

    The function returns two things:

    1. summary:
       One dictionary with overall accuracy and per-role recall.

    2. predictions:
       One row per labeled column showing expected vs predicted role.
    """

    predictions: list[dict[str, Any]] = []
    for evidence in evidence_frame.to_dict("records"):
        # Run the candidate rules on this column's evidence.
        predicted = classify_with_definition(evidence, definition)

        # This is the human-labeled answer from MANUAL_LABELS.
        expected = evidence["expected_role"]
        predictions.append(
            {
                "definition": definition.name,
                "dataset": evidence["dataset"],
                "column": evidence["column"],
                "expected_role": expected,
                "predicted_role": predicted,
                "correct": predicted == expected,
                "research_profile_role": evidence.get("research_profile_role", ""),
                "research_confidence": evidence.get("research_confidence", ""),
                "research_reason": evidence.get("research_reason", ""),
                "research_warning": evidence.get("research_warning", ""),
            }
        )

    prediction_frame = pd.DataFrame(predictions)

    # Overall accuracy answers: "What fraction of all labeled columns did this
    # definition classify correctly?"
    correct_count = int(prediction_frame["correct"].sum())
    total = int(len(prediction_frame))

    # Per-role recall answers: "For each true role, how many did we catch?"
    #
    # Example:
    # If there are 5 true identifier columns and the definition gets 4 right,
    # identifier_recall = 4/5 = 0.80.
    #
    # This matters because a definition could have decent overall accuracy just
    # by getting many easy categorical columns right while failing rare roles
    # such as identifier or free_text.
    role_recalls: dict[str, float] = {}
    role_correct: dict[str, int] = {}
    role_total: dict[str, int] = {}
    for role in ROLES:
        role_rows = prediction_frame[prediction_frame["expected_role"] == role]
        role_total[role] = int(len(role_rows))
        role_correct[role] = int(role_rows["correct"].sum()) if not role_rows.empty else 0
        role_recalls[role] = float(role_correct[role] / role_total[role]) if role_total[role] else 1.0

    summary = {
        **asdict(definition),
        "total_columns": total,
        "correct_columns": correct_count,
        "accuracy": round(correct_count / max(1, total), 4),
        "macro_recall": round(sum(role_recalls.values()) / len(role_recalls), 4),
        "worst_role_recall": round(min(role_recalls.values()), 4),
    }
    for role in ROLES:
        # Store per-role details directly in the summary CSV.  This makes it
        # easy to sort or filter later without recomputing metrics.
        summary[f"{role}_correct"] = role_correct[role]
        summary[f"{role}_total"] = role_total[role]
        summary[f"{role}_recall"] = round(role_recalls[role], 4)

    # The ranking score favors definitions that are accurate overall but do not
    # only win by getting the many easy categorical columns right.
    #
    # accuracy: rewards total correct predictions.
    # macro_recall: rewards balanced performance across all four roles.
    # worst_role_recall: penalizes definitions that completely fail one role.
    summary["ranking_score"] = round(
        summary["accuracy"] + 0.30 * summary["macro_recall"] + 0.10 * summary["worst_role_recall"],
        4,
    )

    return summary, predictions


def markdown_table(frame: pd.DataFrame) -> str:
    """Convert a small DataFrame into a plain Markdown table.

    The report is written as Markdown, so this helper lets us insert tables
    without depending on extra formatting libraries.
    """

    if frame.empty:
        return "_No rows._"
    headers = list(frame.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(str(row[column]) for column in headers) + " |")
    return "\n".join(lines)


def write_report(
    evidence_frame: pd.DataFrame,
    all_scores: pd.DataFrame,
    named_scores: pd.DataFrame,
    top_predictions: pd.DataFrame,
    named_predictions: pd.DataFrame,
) -> None:
    """Write the human-readable experiment report.

    The CSV outputs are best for filtering/sorting in spreadsheets.  The
    Markdown report is best for understanding the result quickly.

    This report explains:

    - the experiment question,
    - which threshold definition won,
    - how named baseline definitions performed,
    - what mistakes were made,
    - which threshold ranges were stable.
    """

    # all_scores is sorted before this function is called, so row 0 is the best
    # scoring threshold definition according to ranking_score.
    best = all_scores.iloc[0]

    # Pull out the current profiler's metrics so the report can compare "best
    # found in this sweep" vs "what the current/default rule set does."
    current = named_scores[named_scores["name"] == "current_profiler"].iloc[0]

    # Mistakes for the best definition are useful because "100% accurate" is
    # not guaranteed.  If there are mistakes, these rows explain exactly where.
    mistakes = top_predictions[(top_predictions["definition"] == best["name"]) & (~top_predictions["correct"])]

    # Named mistakes show which easy-to-explain definitions fail where.
    named_mistakes = named_predictions[~named_predictions["correct"]].copy()

    # "perfect" here means tied for maximum accuracy, not necessarily perfect
    # 100% accuracy.  It is used for threshold sensitivity analysis below.
    perfect = all_scores[all_scores["accuracy"] == all_scores["accuracy"].max()].copy()

    # These are the threshold columns we want to summarize.  For each threshold,
    # the report will show the lowest and highest value among the best-accuracy
    # definitions.  Wide ranges mean the result is less fragile.
    threshold_columns = [
        "numeric_threshold",
        "numeric_min_unique",
        "id_name_cardinality_threshold",
        "identifier_cardinality_threshold",
        "free_text_cardinality_threshold",
        "free_text_min_length",
        "free_text_min_words",
        "long_text_min_words",
    ]
    sensitivity_rows = []
    for column in threshold_columns:
        sensitivity_rows.append(
            {
                "threshold": column,
                "lowest_working_value": perfect[column].min(),
                "highest_working_value": perfect[column].max(),
            }
        )
    sensitivity_frame = pd.DataFrame(sensitivity_rows)

    # The report intentionally uses plain language because this file is often
    # read while preparing for meetings or explaining the profiler to someone
    # who has not been inside the code.
    report = f"""# Column-Type Definition Experiment

## Question

Which definition of dataset profiling best classifies columns as `numeric`,
`categorical`, `free_text`, or `identifier`?

In easy words: I tested different rules for deciding what kind of column each
dataset column is.  The named `research_profile_rules` row also tests the
newer profiler logic with richer internal roles such as `numeric_code_category`,
`binary_category`, `datetime_category`, and `vector_blob`.

## Data used

- Real datasets: `adult.csv`, `cars.csv`, and `complaints-2025-04-21_17_31.csv`
- Labeled columns: {len(evidence_frame)}
- Sample rows per dataset: {SAMPLE_ROWS}

## Best threshold definition found

| Setting | Best value |
| --- | --- |
| numeric_threshold | {best['numeric_threshold']} |
| numeric_min_unique | {best['numeric_min_unique']} |
| id_name_cardinality_threshold | {best['id_name_cardinality_threshold']} |
| identifier_cardinality_threshold | {best['identifier_cardinality_threshold']} |
| free_text_cardinality_threshold | {best['free_text_cardinality_threshold']} |
| free_text_min_length | {best['free_text_min_length']} |
| free_text_min_words | {best['free_text_min_words']} |
| long_text_min_words | {best['long_text_min_words']} |

Best score:

- Accuracy: {best['accuracy']}
- Macro recall: {best['macro_recall']}
- Worst role recall: {best['worst_role_recall']}
- Correct columns: {best['correct_columns']} / {best['total_columns']}

## Named definitions

{markdown_table(named_scores[['name', 'accuracy', 'macro_recall', 'worst_role_recall', 'correct_columns', 'total_columns']])}

## Best definition mistakes

{markdown_table(mistakes[['dataset', 'column', 'expected_role', 'predicted_role']] if not mistakes.empty else pd.DataFrame())}

## What threshold ranges worked?

There was not only one magic threshold.  Several nearby definitions worked on
the real labeled columns.  This is useful because it means the profiler is not
fragile.

Perfect-scoring definitions found: {len(perfect)}

{markdown_table(sensitivity_frame)}

## Named definition mistakes

{markdown_table(named_mistakes[['definition', 'dataset', 'column', 'expected_role', 'predicted_role']] if not named_mistakes.empty else pd.DataFrame())}

## Top 10 threshold definitions

{markdown_table(all_scores.head(10)[['name', 'accuracy', 'macro_recall', 'worst_role_recall', 'ranking_score', 'numeric_threshold', 'id_name_cardinality_threshold', 'identifier_cardinality_threshold', 'free_text_cardinality_threshold', 'free_text_min_length', 'free_text_min_words', 'long_text_min_words']])}

## Easy conclusion

The strongest definition is the one that balances all four column roles.  A
profiler that only gets common categorical columns right is not enough; it also
needs to protect the project from treating IDs like real meaning and from
missing long text columns where SBERT or text embeddings might matter.

For Buckaroo, the best definition of dataset profiling should be:

> A quick, sample-based description of each column's role, using numeric-ness,
> uniqueness, text length, word count, and ID-name hints together.

"""
    (OUT_DIR / "column_type_definition_report.md").write_text(report, encoding="utf-8")


def main() -> None:
    """Run the full experiment and write all output files.

    This is the script entry point.  It does the experiment in this order:

    1. Create the output folder.
    2. Load manual labels and compute evidence for each labeled column.
    3. Build candidate definitions:
       - named easy-to-explain definitions,
       - many generated threshold-sweep definitions.
    4. Score every definition.
    5. Sort definitions from best to worst.
    6. Save CSVs and Markdown report.
    7. Print a short terminal summary.
    """

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # One row per manually labeled column, with evidence such as numeric_ratio,
    # cardinality_ratio, average length, and expected_role.
    evidence_frame = load_labeled_column_evidence()

    # The experiment compares hand-named baselines against a brute-force
    # threshold sweep.  The named definitions make the report easy to discuss;
    # the sweep helps find better parameter values.
    definitions = named_definitions() + threshold_sweep_definitions()

    score_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    for definition in definitions:
        # Score this one candidate definition and collect both summary metrics
        # and individual column predictions.
        summary, predictions = score_definition(definition, evidence_frame)
        score_rows.append(summary)
        prediction_rows.extend(predictions)

    # Sort best to worst.  ranking_score is primary, then the individual metric
    # columns break ties in a predictable way.
    scores = pd.DataFrame(score_rows).sort_values(
        ["ranking_score", "accuracy", "macro_recall", "worst_role_recall"],
        ascending=False,
    )

    # Keep just the human-readable named definitions for the named report CSV.
    named_scores = scores[scores["name"].isin([definition.name for definition in named_definitions()])].copy()

    predictions = pd.DataFrame(prediction_rows)

    # The full prediction table can be huge because it contains every generated
    # sweep definition.  For easier inspection, save predictions for the top 20
    # definitions and for the named definitions.
    top_definition_names = scores.head(20)["name"].tolist()
    top_predictions = predictions[predictions["definition"].isin(top_definition_names)].copy()
    named_predictions = predictions[predictions["definition"].isin([definition.name for definition in named_definitions()])].copy()

    # Write machine-readable outputs.  These are useful in Excel, notebooks, or
    # later scripts.
    evidence_frame.to_csv(OUT_DIR / "manual_label_column_evidence.csv", index=False)
    scores.to_csv(OUT_DIR / "column_type_definition_scores.csv", index=False)
    named_scores.to_csv(OUT_DIR / "named_column_type_definition_scores.csv", index=False)
    top_predictions.to_csv(OUT_DIR / "top_column_type_definition_predictions.csv", index=False)
    named_predictions.to_csv(OUT_DIR / "named_column_type_definition_predictions.csv", index=False)

    # Write the human-readable summary report.
    write_report(evidence_frame, scores, named_scores, top_predictions, named_predictions)

    # Print a tiny summary so a user running the script knows where to look next.
    best = scores.iloc[0]
    current = named_scores[named_scores["name"] == "current_profiler"].iloc[0]
    print("Column-type definition experiment complete.")
    print(f"Labeled columns tested: {len(evidence_frame)}")
    print(
        "Best definition: "
        f"{best['name']} accuracy={best['accuracy']} macro_recall={best['macro_recall']} "
        f"worst_role_recall={best['worst_role_recall']}"
    )
    print(
        "Current profiler: "
        f"accuracy={current['accuracy']} macro_recall={current['macro_recall']} "
        f"worst_role_recall={current['worst_role_recall']}"
    )
    print(f"Outputs written to: {OUT_DIR}")


if __name__ == "__main__":
    main()
