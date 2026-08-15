"""Legacy four-role manual-label experiment for dataset profiling.

This predates Buckaroo's datetime, geography, warning, and candidate-role
ontology. It is retained for historical comparison only and must not be mixed
with the corrected peer-review benchmark without an explicit legacy flag.

This experiment checks whether the profiler agrees with human labels.

In plain words:

1. We manually label real dataset columns as numeric, categorical, free_text,
   or identifier.
2. We run several profiler definitions on those same columns.
3. We count how often each definition matches the human label.
4. We also attach a simple confidence score to the current profiler's answer.

The goal is to make the profiler easier to defend in a meeting:

    "Here are the human labels, here is what the profiler predicted,
     here is the accuracy, and here is where the profiler is unsure."
"""

from __future__ import annotations

import sys
import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.profile_column_type_definition_experiment import (  # noqa: E402
    ColumnTypeDefinition,
    classify_with_definition,
    compute_column_evidence,
    named_definitions,
    threshold_sweep_definitions,
)


DATASET_DIR = ROOT / "provided_datasets"
OUT_DIR = ROOT / "experiments" / "manual_label_accuracy_outputs"

MAIN_SAMPLE_ROWS = 3000
SAMPLE_SETTINGS: list[int | None] = [200, 500, 3000, None]
ROLES = ("numeric", "categorical", "free_text", "identifier")

HUMAN_CONFIDENCE_WEIGHT = {
    "high": 1.0,
    "medium": 0.75,
    "low": 0.50,
}


@dataclass(frozen=True)
class ManualLabel:
    """One human label for one real dataset column."""

    role: str
    human_confidence: str = "high"
    edge_case: str = "normal"
    reason: str = ""


def label(role: str, confidence: str = "high", edge_case: str = "normal", reason: str = "") -> ManualLabel:
    """Small helper so the manual answer key stays readable."""

    return ManualLabel(role=role, human_confidence=confidence, edge_case=edge_case, reason=reason)


# This is the human answer key. It intentionally covers normal columns and
# tricky columns:
#
# - real measurements: age, sales, latitude
# - repeated labels: gender, state, platform
# - IDs: VIN, CASE#, Complaint ID
# - long text: descriptions and complaint narratives
# - numeric-looking category codes: beat, ward, IUCR, FBI CD
# - missing-heavy columns: county, Consumer disputed?
# - ordinal/range text: YearsCoding, HoursComputer, Age
MANUAL_LABELS: dict[str, dict[str, ManualLabel]] = {
    "adult.csv": {
        "age": label("numeric", reason="Real measurement."),
        "workclass": label("categorical", reason="Repeated job/work labels."),
        "fnlwgt": label("numeric", "medium", "high_cardinality_numeric", "Survey weight; numeric but very unique."),
        "education": label("categorical", reason="Repeated education names."),
        "educational-num": label("numeric", "medium", "ordinal_numeric", "Ordered education number."),
        "marital-status": label("categorical"),
        "occupation": label("categorical"),
        "relationship": label("categorical"),
        "race": label("categorical"),
        "gender": label("categorical", edge_case="binary_category"),
        "capital-gain": label("numeric"),
        "capital-loss": label("numeric"),
        "hours-per-week": label("numeric"),
        "native-country": label("categorical"),
        "income": label("categorical", edge_case="binary_category"),
    },
    "cars.csv": {
        "Unnamed: 0": label("identifier", edge_case="index_column", reason="Row index, not meaning."),
        "id": label("identifier", reason="Listing ID."),
        "region": label("categorical"),
        "price": label("numeric"),
        "year": label("numeric", "medium", "year_number", "Year can be numeric, but it is also time-like."),
        "manufacturer": label("categorical"),
        "model": label("categorical", "medium", "high_cardinality_category", "Car model is a label, not a row ID."),
        "condition": label("categorical"),
        "cylinders": label("categorical", edge_case="numeric_words", reason="Text labels like '4 cylinders'."),
        "fuel": label("categorical"),
        "odometer": label("numeric"),
        "title_status": label("categorical"),
        "transmission": label("categorical"),
        "VIN": label("identifier", edge_case="id_name_hint", reason="Vehicle identifier."),
        "drive": label("categorical"),
        "size": label("categorical"),
        "type": label("categorical"),
        "paint_color": label("categorical"),
        "description": label("free_text", edge_case="long_text", reason="Open written listing description."),
        "county": label("categorical", "low", "mostly_missing", "Column is empty in the sample, so the label is weak."),
        "state": label("categorical"),
        "posting_date": label("categorical", "medium", "datetime_missing_role", "Legacy ontology has no datetime role; never score a timestamp as a primary identifier."),
    },
    "complaints-2025-04-21_17_31.csv": {
        "Date received": label("categorical", "medium", "date_bucket", "Date-only value repeats across complaints."),
        "Product": label("categorical"),
        "Sub-product": label("categorical"),
        "Issue": label("categorical", edge_case="long_category_label"),
        "Sub-issue": label("categorical", edge_case="long_category_label"),
        "Consumer complaint narrative": label("free_text", edge_case="long_text"),
        "Company public response": label(
            "free_text",
            "medium",
            "repeated_long_text",
            "Natural-language response text, but only a few repeated templates.",
        ),
        "Company": label("categorical"),
        "State": label("categorical"),
        "ZIP code": label("categorical", "medium", "geography_missing_role", "Legacy ontology has no postal-code role; ZIP is not a row identifier."),
        "Tags": label("categorical"),
        "Consumer consent provided?": label("categorical", edge_case="question_column"),
        "Submitted via": label("categorical"),
        "Date sent to company": label("categorical", "medium", "date_bucket"),
        "Company response to consumer": label("categorical", edge_case="long_category_label"),
        "Timely response?": label("categorical", edge_case="binary_category"),
        "Consumer disputed?": label("categorical", "low", "mostly_missing"),
        "Complaint ID": label("identifier", edge_case="id_name_hint"),
    },
    "games.csv": {
        "Name": label(
            "categorical",
            "medium",
            "entity_name",
            "Legacy ontology has no entity-name role; a title is not automatically a primary key.",
        ),
        "Platform": label("categorical"),
        "Year_of_Release": label("numeric", "medium", "year_number"),
        "Genre": label("categorical"),
        "Publisher": label("categorical"),
        "NA_Sales": label("numeric"),
        "EU_Sales": label("numeric"),
        "JP_Sales": label("numeric"),
        "Other_Sales": label("numeric"),
        "Global_Sales": label("numeric"),
        "Critic_Score": label("numeric"),
        "Critic_Count": label("numeric"),
        "User_Score": label("numeric"),
        "User_Count": label("numeric"),
        "Developer": label("categorical", "medium", "high_cardinality_category"),
        "Rating": label("categorical"),
    },
    "crimes.csv": {
        "iucr": label("categorical", "medium", "numeric_code", "Crime code, not a measurement."),
        "primary description": label("categorical"),
        "secondary description": label("categorical"),
        "arrest": label("categorical", edge_case="binary_category"),
        "domestic": label("categorical", edge_case="binary_category"),
        "beat": label("categorical", "medium", "numeric_code", "Police beat code, not a measurement."),
        "ward": label("categorical", "medium", "numeric_code", "Ward code, not a measurement."),
        "x coordinate": label("numeric"),
        "y coordinate": label("numeric"),
        "latitude": label("numeric"),
        "longitude": label("numeric"),
    },
    "(original)crimes___one_year_prior_to_present_20250421.csv": {
        "CASE#": label("identifier", edge_case="id_name_hint"),
        "DATE  OF OCCURRENCE": label("categorical", "medium", "datetime_missing_role"),
        "BLOCK": label("categorical", "medium", "geography_missing_role"),
        " IUCR": label("categorical", "medium", "numeric_code"),
        " PRIMARY DESCRIPTION": label("categorical"),
        " SECONDARY DESCRIPTION": label("categorical"),
        " LOCATION DESCRIPTION": label("categorical"),
        "ARREST": label("categorical", edge_case="binary_category"),
        "DOMESTIC": label("categorical", edge_case="binary_category"),
        "BEAT": label("categorical", "medium", "numeric_code"),
        "WARD": label("categorical", "medium", "numeric_code"),
        "FBI CD": label("categorical", "medium", "numeric_code"),
        "X COORDINATE": label("numeric"),
        "Y COORDINATE": label("numeric"),
        "LATITUDE": label("numeric"),
        "LONGITUDE": label("numeric"),
        "LOCATION": label("categorical", "low", "geography_missing_role", "Lat/long pair as text; legacy ontology lacks a geography role."),
    },
    "stackoverflow_db_uncleaned.csv": {
        "ID": label("identifier", edge_case="id_name_hint"),
        "Hobby": label("categorical", edge_case="binary_category"),
        "Country": label("categorical"),
        "Student": label("categorical"),
        "FormalEducation": label("categorical", edge_case="long_category_label"),
        "UndergradMajor": label("categorical", edge_case="long_category_label"),
        "DevType": label("categorical", edge_case="multi_label_category"),
        "YearsCoding": label("categorical", edge_case="ordinal_text"),
        "HoursComputer": label("categorical", edge_case="ordinal_text"),
        "Exercise": label("categorical", edge_case="ordinal_text"),
        "Gender": label("categorical"),
        "SexualOrientation": label("categorical"),
        "EducationParents": label("categorical", edge_case="long_category_label"),
        "RaceEthnicity": label("categorical", edge_case="multi_label_category"),
        "Dependents": label("categorical", edge_case="binary_category"),
        "Continent": label("categorical"),
        "Age": label("categorical", edge_case="ordinal_text", reason="Age range text, not raw numeric age."),
        "ConvertedSalary": label("numeric"),
        "HDI": label("categorical"),
        "GDP": label("categorical"),
        "GINI": label("categorical"),
    },
}


def sample_label(sample_rows: int | None) -> str:
    return "all" if sample_rows is None else str(sample_rows)


def read_dataset(dataset: str, sample_rows: int | None) -> pd.DataFrame:
    csv_path = DATASET_DIR / dataset
    if sample_rows is None:
        return pd.read_csv(csv_path, low_memory=False)
    return pd.read_csv(csv_path, nrows=sample_rows, low_memory=False)


def load_labeled_evidence(sample_rows: int | None) -> pd.DataFrame:
    """Compute profiler signals for every human-labeled column."""

    rows: list[dict[str, Any]] = []
    for dataset, labels in MANUAL_LABELS.items():
        df = read_dataset(dataset, sample_rows)
        for column, manual in labels.items():
            if column not in df.columns:
                raise KeyError(f"{dataset} is missing manually labeled column {column!r}")

            evidence = compute_column_evidence(dataset, column, df[column])
            evidence.update(
                {
                    "expected_role": manual.role,
                    "human_label_confidence": manual.human_confidence,
                    "human_confidence_weight": HUMAN_CONFIDENCE_WEIGHT[manual.human_confidence],
                    "edge_case": manual.edge_case,
                    "manual_reason": manual.reason,
                    "sample_label": sample_label(sample_rows),
                    "sample_rows": len(df),
                }
            )
            rows.append(evidence)

    return pd.DataFrame(rows)


def confidence_for_prediction(evidence: dict[str, Any], predicted_role: str) -> tuple[float, str, str]:
    """Attach a simple confidence score to the current profiler's prediction.

    This is intentionally explainable.  It is not a machine-learning model.
    It asks: how strong is the evidence for the chosen role?
    """

    non_missing_count = int(evidence["non_missing_count"])
    unique_count = int(evidence["unique_count"])
    cardinality = float(evidence["cardinality_ratio"])
    numeric_ratio = float(evidence["numeric_ratio"])
    avg_text_length = float(evidence["avg_text_length"])
    avg_word_count = float(evidence["avg_word_count"])
    id_name_hint = bool(evidence["id_name_hint"])
    lower_name = str(evidence["column"]).strip().lower()

    if non_missing_count == 0:
        return 0.20, "low", "Column is empty or almost empty, so the profiler has little evidence."

    if predicted_role == "numeric":
        score = 0.35 + 0.55 * numeric_ratio
        reason = f"{numeric_ratio:.0%} of present values parse as numbers."
        if unique_count <= 5:
            score -= 0.25
            reason += " But it has very few unique values, so it may be a code/category."
        if any(token in lower_name for token in ("code", "cd", "iucr", "ward", "beat", "zip")):
            score -= 0.20
            reason += " The column name looks code-like."
        score = max(0.05, min(0.99, score))
    elif predicted_role == "identifier":
        score = 0.45 + 0.45 * cardinality
        reason = f"{cardinality:.0%} of present values are unique."
        if id_name_hint:
            score += 0.10
            reason += " The column name also looks ID-like."
        if avg_word_count >= 4:
            score -= 0.20
            reason += " It has several words per value, so it may be text instead of an ID."
        score = max(0.05, min(0.99, score))
    elif predicted_role == "free_text":
        word_signal = min(avg_word_count / 12.0, 1.0)
        length_signal = min(avg_text_length / 120.0, 1.0)
        score = 0.30 + 0.35 * word_signal + 0.25 * length_signal + 0.10 * min(cardinality, 1.0)
        reason = f"Values average {avg_word_count:.1f} words and {avg_text_length:.1f} characters."
        if cardinality < 0.05:
            score -= 0.15
            reason += " But there are very few repeated templates, so this is less certain."
        score = max(0.05, min(0.99, score))
    else:
        low_cardinality = 1.0 - min(cardinality, 1.0)
        score = 0.30 + 0.45 * low_cardinality
        reason = f"Only {cardinality:.0%} of present values are unique, which looks like repeated labels."
        if numeric_ratio > 0.90 and unique_count > 5:
            score -= 0.30
            reason += " But it also looks numeric, so this is ambiguous."
        if avg_word_count >= 5:
            score -= 0.15
            reason += " The labels are wordy, so they can look like free text."
        score = max(0.05, min(0.99, score))

    if score >= 0.80:
        bucket = "high"
    elif score >= 0.55:
        bucket = "medium"
    else:
        bucket = "low"

    return round(score, 4), bucket, reason


def score_definition(definition: ColumnTypeDefinition, evidence_frame: pd.DataFrame) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Score one profiler definition against the human answer key."""

    predictions: list[dict[str, Any]] = []
    for evidence in evidence_frame.to_dict("records"):
        predicted = classify_with_definition(evidence, definition)
        expected = evidence["expected_role"]
        correct = predicted == expected

        confidence_score = ""
        confidence_bucket = ""
        confidence_reason = ""
        if definition.name == "current_profiler":
            confidence_score, confidence_bucket, confidence_reason = confidence_for_prediction(evidence, predicted)

        predictions.append(
            {
                "definition": definition.name,
                "dataset": evidence["dataset"],
                "column": evidence["column"],
                "expected_role": expected,
                "predicted_role": predicted,
                "correct": correct,
                "human_label_confidence": evidence["human_label_confidence"],
                "human_confidence_weight": evidence["human_confidence_weight"],
                "edge_case": evidence["edge_case"],
                "manual_reason": evidence["manual_reason"],
                "profiler_confidence": confidence_score,
                "profiler_confidence_bucket": confidence_bucket,
                "profiler_confidence_reason": confidence_reason,
            }
        )

    prediction_frame = pd.DataFrame(predictions)
    total = int(len(prediction_frame))
    correct_count = int(prediction_frame["correct"].sum())

    weights = prediction_frame["human_confidence_weight"].astype(float)
    weighted_correct = (prediction_frame["correct"].astype(float) * weights).sum()
    weighted_total = weights.sum()

    summary: dict[str, Any] = {
        "name": definition.name,
        "numeric_threshold": definition.numeric_threshold,
        "numeric_min_unique": definition.numeric_min_unique,
        "id_name_cardinality_threshold": definition.id_name_cardinality_threshold,
        "identifier_cardinality_threshold": definition.identifier_cardinality_threshold,
        "free_text_cardinality_threshold": definition.free_text_cardinality_threshold,
        "free_text_min_length": definition.free_text_min_length,
        "free_text_min_words": definition.free_text_min_words,
        "long_text_min_words": definition.long_text_min_words,
        "total_columns": total,
        "correct_columns": correct_count,
        "accuracy": round(correct_count / max(1, total), 4),
        "weighted_accuracy": round(float(weighted_correct / max(1.0, weighted_total)), 4),
    }

    recalls = []
    for role in ROLES:
        role_rows = prediction_frame[prediction_frame["expected_role"] == role]
        role_total = int(len(role_rows))
        role_correct = int(role_rows["correct"].sum()) if role_total else 0
        role_recall = role_correct / role_total if role_total else 1.0
        recalls.append(role_recall)
        summary[f"{role}_correct"] = role_correct
        summary[f"{role}_total"] = role_total
        summary[f"{role}_recall"] = round(role_recall, 4)

    summary["macro_recall"] = round(sum(recalls) / len(recalls), 4)
    summary["worst_role_recall"] = round(min(recalls), 4)
    summary["ranking_score"] = round(
        summary["weighted_accuracy"] + 0.30 * summary["macro_recall"] + 0.10 * summary["worst_role_recall"],
        4,
    )
    return summary, predictions


def score_definition_summary_only(definition: ColumnTypeDefinition, evidence_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Score a definition without keeping every row-level prediction.

    The threshold sweep has thousands of candidate definitions. Keeping all
    row-level predictions for those candidates is slow and memory-heavy. For
    the sweep we only need the summary score so we can rank definitions.
    """

    total = len(evidence_records)
    correct_count = 0
    weighted_correct = 0.0
    weighted_total = 0.0
    role_total = {role: 0 for role in ROLES}
    role_correct = {role: 0 for role in ROLES}

    for evidence in evidence_records:
        predicted = classify_with_definition(evidence, definition)
        expected = evidence["expected_role"]
        weight = float(evidence["human_confidence_weight"])
        correct = predicted == expected

        correct_count += int(correct)
        weighted_correct += weight if correct else 0.0
        weighted_total += weight
        role_total[expected] += 1
        role_correct[expected] += int(correct)

    summary: dict[str, Any] = {
        "name": definition.name,
        "numeric_threshold": definition.numeric_threshold,
        "numeric_min_unique": definition.numeric_min_unique,
        "id_name_cardinality_threshold": definition.id_name_cardinality_threshold,
        "identifier_cardinality_threshold": definition.identifier_cardinality_threshold,
        "free_text_cardinality_threshold": definition.free_text_cardinality_threshold,
        "free_text_min_length": definition.free_text_min_length,
        "free_text_min_words": definition.free_text_min_words,
        "long_text_min_words": definition.long_text_min_words,
        "total_columns": total,
        "correct_columns": correct_count,
        "accuracy": round(correct_count / max(1, total), 4),
        "weighted_accuracy": round(float(weighted_correct / max(1.0, weighted_total)), 4),
    }

    recalls = []
    for role in ROLES:
        recall = role_correct[role] / role_total[role] if role_total[role] else 1.0
        recalls.append(recall)
        summary[f"{role}_correct"] = role_correct[role]
        summary[f"{role}_total"] = role_total[role]
        summary[f"{role}_recall"] = round(recall, 4)

    summary["macro_recall"] = round(sum(recalls) / len(recalls), 4)
    summary["worst_role_recall"] = round(min(recalls), 4)
    summary["ranking_score"] = round(
        summary["weighted_accuracy"] + 0.30 * summary["macro_recall"] + 0.10 * summary["worst_role_recall"],
        4,
    )
    return summary


def markdown_table(frame: pd.DataFrame) -> str:
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
    evidence: pd.DataFrame,
    named_scores: pd.DataFrame,
    all_scores: pd.DataFrame,
    current_predictions: pd.DataFrame,
    sample_scores: pd.DataFrame,
) -> None:
    best_named = named_scores.iloc[0]
    best_any = all_scores.iloc[0]
    mistakes = current_predictions[~current_predictions["correct"]].copy()
    confidence_summary = (
        current_predictions.groupby("profiler_confidence_bucket", dropna=False)
        .agg(total=("correct", "size"), correct=("correct", "sum"))
        .reset_index()
    )
    confidence_summary["accuracy"] = (confidence_summary["correct"] / confidence_summary["total"]).round(4)

    role_summary_rows = []
    for role in ROLES:
        role_rows = current_predictions[current_predictions["expected_role"] == role]
        role_summary_rows.append(
            {
                "role": role,
                "correct": int(role_rows["correct"].sum()),
                "total": int(len(role_rows)),
                "accuracy": round(float(role_rows["correct"].mean()), 4) if len(role_rows) else 1.0,
            }
        )
    role_summary = pd.DataFrame(role_summary_rows)

    edge_summary = (
        current_predictions.groupby("edge_case")
        .agg(total=("correct", "size"), correct=("correct", "sum"))
        .reset_index()
        .sort_values(["correct", "total"], ascending=[True, False])
    )
    edge_summary["accuracy"] = (edge_summary["correct"] / edge_summary["total"]).round(4)

    report = f"""# Legacy Manual-Label Accuracy Experiment

> Historical four-role result only. Do not report this as current Buckaroo
> accuracy; it lacks datetime, geography, confidence, and warning semantics.

## Question

Does the dataset profiler agree with human labels?

In easy words: I manually labeled real columns, then checked whether the
profiler guessed the same type.

## Data used

- Real datasets: {evidence['dataset'].nunique()}
- Manually labeled columns: {len(evidence)}
- Main sample size: {MAIN_SAMPLE_ROWS} rows per dataset
- Roles: numeric, categorical, free_text, identifier
- Human labels also have confidence: high, medium, or low

## Best named definition

The best easy-to-explain named definition was `{best_named['name']}`.

- Accuracy: {best_named['accuracy']} ({int(best_named['correct_columns'])}/{int(best_named['total_columns'])})
- Weighted accuracy: {best_named['weighted_accuracy']}
- Macro recall: {best_named['macro_recall']}
- Worst role recall: {best_named['worst_role_recall']}

## Current profiler result

{markdown_table(named_scores[['name', 'accuracy', 'weighted_accuracy', 'macro_recall', 'worst_role_recall', 'correct_columns', 'total_columns']])}

## Current profiler accuracy by role

{markdown_table(role_summary)}

## Current profiler confidence buckets

{markdown_table(confidence_summary)}

In easy words: confidence is useful only if high-confidence predictions are
usually right and low-confidence predictions contain most of the risky cases.

## Current profiler mistakes

{markdown_table(mistakes[['dataset', 'column', 'expected_role', 'predicted_role', 'human_label_confidence', 'edge_case', 'profiler_confidence_bucket']])}

## Edge-case summary

{markdown_table(edge_summary.head(20))}

## Sample-size check for current profiler

{markdown_table(sample_scores[['sample_label', 'accuracy', 'weighted_accuracy', 'correct_columns', 'total_columns', 'macro_recall', 'worst_role_recall']])}

## Best threshold definition from the sweep

The best definition from the larger threshold search was `{best_any['name']}`.

- Accuracy: {best_any['accuracy']} ({int(best_any['correct_columns'])}/{int(best_any['total_columns'])})
- Weighted accuracy: {best_any['weighted_accuracy']}
- Macro recall: {best_any['macro_recall']}
- Worst role recall: {best_any['worst_role_recall']}

Best threshold settings:

| setting | value |
| --- | --- |
| numeric_threshold | {best_any['numeric_threshold']} |
| numeric_min_unique | {best_any['numeric_min_unique']} |
| id_name_cardinality_threshold | {best_any['id_name_cardinality_threshold']} |
| identifier_cardinality_threshold | {best_any['identifier_cardinality_threshold']} |
| free_text_cardinality_threshold | {best_any['free_text_cardinality_threshold']} |
| free_text_min_length | {best_any['free_text_min_length']} |
| free_text_min_words | {best_any['free_text_min_words']} |
| long_text_min_words | {best_any['long_text_min_words']} |

## Easy conclusion

The profiler is strong on normal numeric columns, normal categories, real IDs,
and obvious long text. The weak spots are columns that need domain meaning:
numeric-looking codes, dates/times, address-like values, and entity names.

The best next improvement is to keep the predicted role, but also return a
confidence label plus an ambiguity reason. That lets the UI say:

> "This looks numeric, but it may be a code/category."

"""
    (OUT_DIR / "manual_label_accuracy_report.md").write_text(report, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    evidence = load_labeled_evidence(MAIN_SAMPLE_ROWS)
    named_definition_list = named_definitions()
    sweep_definition_list = threshold_sweep_definitions()
    named_names = {definition.name for definition in named_definition_list}
    evidence_records = evidence.to_dict("records")

    score_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    for definition in named_definition_list:
        summary, predictions = score_definition(definition, evidence)
        score_rows.append(summary)
        prediction_rows.extend(predictions)

    for definition in sweep_definition_list:
        score_rows.append(score_definition_summary_only(definition, evidence_records))

    all_scores = pd.DataFrame(score_rows).sort_values(
        ["ranking_score", "weighted_accuracy", "accuracy", "macro_recall", "worst_role_recall"],
        ascending=False,
    )
    named_scores = all_scores[all_scores["name"].isin(named_names)].copy()
    predictions = pd.DataFrame(prediction_rows)
    named_predictions = predictions[predictions["definition"].isin(named_names)].copy()
    current_predictions = predictions[predictions["definition"] == "current_profiler"].copy()

    sample_score_rows = []
    for sample_rows in SAMPLE_SETTINGS:
        sample_evidence = load_labeled_evidence(sample_rows)
        current = next(definition for definition in named_definition_list if definition.name == "current_profiler")
        summary, _ = score_definition(current, sample_evidence)
        summary["sample_label"] = sample_label(sample_rows)
        sample_score_rows.append(summary)
    sample_scores = pd.DataFrame(sample_score_rows)

    confusion = pd.crosstab(
        current_predictions["expected_role"],
        current_predictions["predicted_role"],
        rownames=["human_label"],
        colnames=["profiler_prediction"],
    )

    answer_key_rows = []
    for dataset, labels in MANUAL_LABELS.items():
        for column, manual in labels.items():
            answer_key_rows.append(
                {
                    "dataset": dataset,
                    "column": column,
                    "expected_role": manual.role,
                    "human_label_confidence": manual.human_confidence,
                    "edge_case": manual.edge_case,
                    "manual_reason": manual.reason,
                }
            )

    pd.DataFrame(answer_key_rows).to_csv(OUT_DIR / "manual_label_answer_key.csv", index=False)
    evidence.to_csv(OUT_DIR / "manual_label_column_evidence.csv", index=False)
    all_scores.to_csv(OUT_DIR / "manual_label_all_definition_scores.csv", index=False)
    named_scores.to_csv(OUT_DIR / "manual_label_named_definition_scores.csv", index=False)
    named_predictions.to_csv(OUT_DIR / "manual_label_named_predictions.csv", index=False)
    current_predictions.to_csv(OUT_DIR / "manual_label_current_profiler_predictions.csv", index=False)
    sample_scores.to_csv(OUT_DIR / "manual_label_sample_size_current_scores.csv", index=False)
    confusion.to_csv(OUT_DIR / "manual_label_current_confusion_matrix.csv")
    write_report(evidence, named_scores, all_scores, current_predictions, sample_scores)

    current_row = named_scores[named_scores["name"] == "current_profiler"].iloc[0]
    best_named = named_scores.iloc[0]
    best_any = all_scores.iloc[0]

    print("Manual-label accuracy experiment complete.")
    print(f"Datasets labeled: {evidence['dataset'].nunique()}")
    print(f"Manual labels tested: {len(evidence)}")
    print(
        "Current profiler: "
        f"accuracy={current_row['accuracy']} "
        f"weighted_accuracy={current_row['weighted_accuracy']} "
        f"correct={int(current_row['correct_columns'])}/{int(current_row['total_columns'])}"
    )
    print(
        "Best named definition: "
        f"{best_named['name']} accuracy={best_named['accuracy']} "
        f"weighted_accuracy={best_named['weighted_accuracy']}"
    )
    print(
        "Best sweep definition: "
        f"{best_any['name']} accuracy={best_any['accuracy']} "
        f"weighted_accuracy={best_any['weighted_accuracy']}"
    )
    print(f"Outputs written to: {OUT_DIR}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-legacy-ontology",
        action="store_true",
        help="Acknowledge that this historical four-role result is not the current benchmark.",
    )
    args = parser.parse_args()
    if not args.allow_legacy_ontology:
        parser.error("This is a legacy experiment. Re-run only with --allow-legacy-ontology.")
    main()
