"""Evaluate Buckaroo adaptive early stopping against manual labels.

This experiment answers Paul's question:

    If adaptive sampling stops early, did it still get the right answer?

Outputs compare:
    early_stop_prediction vs full_pass_prediction vs manual_label

The script intentionally uses the current profiler implementation from
experiments.profile_dataset_shape.profile_columns.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import sys
import time
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.profile_dataset_shape import profile_columns  # noqa: E402
from experiments.benchmark_validation import accuracy_output, benchmark_quality  # noqa: E402
from experiments.reproducibility import capture_reproducibility  # noqa: E402


LABEL_DIR = ROOT / "outputs" / "manual_labeling_5_datasets"
MANUAL_LABELS = LABEL_DIR / "manual_labeling_peer_review_final.csv"
OUT_DIR = ROOT / "outputs" / "corrected_methodology_v2" / "early_stopping_current_profiler_labels"
SAMPLE_SIZES = [100, 500, 1_000, 5_000, 10_000, 50_000]
BASE_SEED = 20260706


def clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def yes(value: Any) -> bool:
    return clean_text(value).lower() in {"yes", "true", "1"}


def comparable_expected_role(row: pd.Series) -> str:
    """Map manual labels to the closest current Buckaroo profile role family."""
    expected = clean_text(row.get("expected_buckaroo_role")).lower()
    manual = clean_text(row.get("manual_true_role")).lower()
    role = expected or manual

    if "datetime" in role or manual == "datetime":
        return "datetime"
    if "geographic_coordinate" in role or manual == "geographic_coordinate":
        return "geographic_coordinate"
    if "location" in role or manual == "location_name":
        return "location"
    if "identifier_code" in role or manual == "identifier_code":
        return "identifier_code"
    if "numeric_measure" in role or manual == "numeric_measure":
        return "numeric_measure"
    if "ordinal" in role or manual in {"ordinal_category", "categorical"}:
        return "categorical"
    if "categorical" in role:
        return "categorical"
    if "entity_name" in role or manual == "entity_name":
        return "entity_name"
    return role or "unknown"


def comparable_predicted_role(profile_role: str, broad_role: str) -> str:
    """Map current profiler output to the same comparison families."""
    profile_role = clean_text(profile_role).lower()
    broad_role = clean_text(broad_role).lower()

    if profile_role in {"datetime_category", "datetime_high_uniqueness", "datetime_identifier"}:
        return "datetime"
    if profile_role == "geographic_coordinate":
        return "geographic_coordinate"
    if profile_role in {
        "airport_code",
        "country_code",
        "high_uniqueness_location_field",
        "location_name",
        "postal_code",
    }:
        return "location"
    if profile_role in {"identifier", "quasi_identifier"}:
        return "primary_identifier"
    if profile_role == "numeric_measure":
        return "numeric_measure"
    if profile_role in {"numeric_code_category"}:
        return "identifier_code"
    if profile_role in {"binary_category", "categorical"} or broad_role == "categorical":
        return "categorical"
    if profile_role in {"free_text", "vector_blob"}:
        return "entity_name" if profile_role == "free_text" else "free_text"
    if broad_role == "numeric":
        return "numeric_measure"
    return profile_role or broad_role or "unknown"


def predicted_primary_key(profile_role: str) -> bool:
    """Score only hard identifier as primary-key prediction."""
    return clean_text(profile_role).lower() == "identifier"


def profile_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    start = time.perf_counter()
    profile, _ = profile_columns(frame)
    runtime = time.perf_counter() - start
    return profile, runtime


def sample_frame(frame: pd.DataFrame, rows: int, seed: int) -> pd.DataFrame:
    if rows >= len(frame):
        return frame.copy()
    return (
        frame.sample(frac=1.0, replace=False, random_state=seed)
        .head(rows)
        .reset_index(drop=True)
    )


def stop_recommended(profile: pd.DataFrame) -> bool:
    if profile.empty or "needs_more_sampling" not in profile.columns:
        return False
    return not profile["needs_more_sampling"].fillna(True).astype(bool).any()


def profile_lookup(profile: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if profile.empty:
        return {}
    rows = {}
    for record in profile.to_dict(orient="records"):
        rows[clean_text(record.get("column"))] = record
    return rows


def choose_adaptive_profile(
    dataset_id: str,
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    final_profile = pd.DataFrame()
    cumulative_runtime = 0.0
    total_rows = len(frame)
    sample_sizes = sorted(set(size for size in [*SAMPLE_SIZES, total_rows] if 0 < size <= total_rows))

    for sample_rows in sample_sizes:
        stable_dataset_hash = int(hashlib.sha256(dataset_id.encode("utf-8")).hexdigest()[:8], 16)
        seed = BASE_SEED + (stable_dataset_hash % 100_000)
        sampled = sample_frame(frame, sample_rows, seed)
        profile, runtime = profile_frame(sampled)
        cumulative_runtime += runtime
        final_profile = profile
        stop = stop_recommended(profile)
        needs_more = int(profile["needs_more_sampling"].fillna(True).astype(bool).sum()) if "needs_more_sampling" in profile else len(profile)
        decisions.append(
            {
                "dataset_id": dataset_id,
                "sample_rows": int(sample_rows),
                "total_rows": int(total_rows),
                "seed": int(seed),
                "sampling_method": (
                    "full_dataset"
                    if sample_rows >= total_rows
                    else "deterministic_nested_random_prefix"
                ),
                "sample_fraction": round(sample_rows / max(1, total_rows), 6),
                "step_runtime_seconds": round(runtime, 6),
                "cumulative_runtime_seconds": round(cumulative_runtime, 6),
                "stop_recommended": bool(stop),
                "columns_needing_more_sampling": needs_more,
                "avg_confidence_score": round(float(profile["confidence_score"].mean()), 6)
                if "confidence_score" in profile and not profile.empty
                else 0.0,
                "min_confidence_score": round(float(profile["confidence_score"].min()), 6)
                if "confidence_score" in profile and not profile.empty
                else 0.0,
            }
        )
        if stop:
            break

    final_decision = {
        "dataset_id": dataset_id,
        "total_rows": int(total_rows),
        "chosen_sample_rows": int(decisions[-1]["sample_rows"]),
        "stopped_early": bool(decisions[-1]["sample_rows"] < total_rows),
        "adaptive_runtime_seconds": round(cumulative_runtime, 6),
        "sample_path": " -> ".join(str(row["sample_rows"]) for row in decisions),
        "stop_recommended": bool(decisions[-1]["stop_recommended"]),
    }
    return final_profile, decisions, final_decision


def evaluate_dataset(dataset_id: str, labels: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    csv_path = LABEL_DIR / f"{dataset_id}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing dataset CSV: {csv_path}")

    frame = pd.read_csv(csv_path, low_memory=False)
    full_profile, full_runtime = profile_frame(frame)
    early_profile, decisions, adaptive_summary = choose_adaptive_profile(dataset_id, frame)

    full_by_column = profile_lookup(full_profile)
    early_by_column = profile_lookup(early_profile)
    comparison_rows: list[dict[str, Any]] = []

    for _, label in labels.iterrows():
        column = clean_text(label["column_name"])
        if column not in frame.columns:
            continue

        manual_expected = comparable_expected_role(label)
        manual_primary_key = yes(label.get("is_primary_key")) or yes(label.get("corrected_is_primary_key"))
        early = early_by_column.get(column, {})
        full = full_by_column.get(column, {})
        early_profile_role = clean_text(early.get("profile_role"))
        full_profile_role = clean_text(full.get("profile_role"))
        early_role = comparable_predicted_role(early_profile_role, clean_text(early.get("role")))
        full_role = comparable_predicted_role(full_profile_role, clean_text(full.get("role")))
        early_pk = predicted_primary_key(early_profile_role)
        full_pk = predicted_primary_key(full_profile_role)

        comparison_rows.append(
            {
                "dataset_id": dataset_id,
                "column": column,
                "manual_true_role": clean_text(label.get("manual_true_role")),
                "expected_buckaroo_role": clean_text(label.get("expected_buckaroo_role")),
                "manual_comparable_role": manual_expected,
                "manual_is_primary_key": manual_primary_key,
                "early_sample_rows": adaptive_summary["chosen_sample_rows"],
                "stopped_early": adaptive_summary["stopped_early"],
                "early_profile_role": early_profile_role,
                "early_comparable_role": early_role,
                "early_confidence_score": early.get("confidence_score"),
                "early_warning": early.get("warning"),
                "early_adaptive_action": early.get("adaptive_sampling_action"),
                "early_matches_manual": early_role == manual_expected,
                "full_profile_role": full_profile_role,
                "full_comparable_role": full_role,
                "full_confidence_score": full.get("confidence_score"),
                "full_warning": full.get("warning"),
                "full_matches_manual": full_role == manual_expected,
                "early_matches_full": early_role == full_role,
                "early_predicted_primary_key": early_pk,
                "full_predicted_primary_key": full_pk,
                "early_false_key": early_pk and not manual_primary_key,
                "full_false_key": full_pk and not manual_primary_key,
                "early_missed_key": (not early_pk) and manual_primary_key,
                "full_missed_key": (not full_pk) and manual_primary_key,
            }
        )

    dataset_summary = {
        **adaptive_summary,
        "full_runtime_seconds": round(full_runtime, 6),
        "runtime_saved_seconds": round(full_runtime - adaptive_summary["adaptive_runtime_seconds"], 6),
        "runtime_saved_fraction": round(
            (full_runtime - adaptive_summary["adaptive_runtime_seconds"]) / full_runtime,
            6,
        )
        if full_runtime > 0
        else 0.0,
    }
    return comparison_rows, decisions, dataset_summary


def summarize(
    comparisons: pd.DataFrame,
    dataset_summary: pd.DataFrame,
    quality: dict[str, Any],
) -> dict[str, Any]:
    early_stopped = dataset_summary[dataset_summary["stopped_early"].astype(bool)]
    early_rows = comparisons[comparisons["stopped_early"].astype(bool)]
    labeled_primary_keys = int(comparisons["manual_is_primary_key"].sum()) if not comparisons.empty else 0
    early_accuracy = accuracy_output(early_rows["early_matches_manual"], quality)
    full_accuracy = accuracy_output(comparisons["full_matches_manual"], quality)
    adaptive_accuracy = accuracy_output(comparisons["early_matches_manual"], quality)
    return {
        "datasets_evaluated": int(len(dataset_summary)),
        "labeled_columns_evaluated": int(len(comparisons)),
        "datasets_stopped_early": int(len(early_stopped)),
        "early_stopped_labeled_columns": int(len(early_rows)),
        "early_stop_vs_manual_accuracy": early_accuracy["manual_accuracy"],
        "early_stop_vs_provisional_label_agreement": early_accuracy["provisional_label_agreement"],
        "early_stop_vs_full_agreement": round(float(early_rows["early_matches_full"].mean()), 6)
        if not early_rows.empty
        else None,
        "full_pass_vs_manual_accuracy": full_accuracy["manual_accuracy"],
        "full_pass_vs_provisional_label_agreement": full_accuracy["provisional_label_agreement"],
        "all_adaptive_vs_manual_accuracy": adaptive_accuracy["manual_accuracy"],
        "all_adaptive_vs_provisional_label_agreement": adaptive_accuracy["provisional_label_agreement"],
        "early_stop_false_key_errors": int(early_rows["early_false_key"].sum()) if not early_rows.empty else 0,
        "all_adaptive_false_key_errors": int(comparisons["early_false_key"].sum()) if not comparisons.empty else 0,
        "full_pass_false_key_errors": int(comparisons["full_false_key"].sum()) if not comparisons.empty else 0,
        "labeled_primary_key_columns": labeled_primary_keys,
        "median_runtime_saved_fraction_for_early_stops": round(float(early_stopped["runtime_saved_fraction"].median()), 6)
        if not early_stopped.empty
        else None,
        "median_runtime_saved_seconds_for_early_stops": round(float(early_stopped["runtime_saved_seconds"].median()), 6)
        if not early_stopped.empty
        else None,
        **quality,
    }


def write_report(summary: dict[str, Any], dataset_summary: pd.DataFrame, comparisons: pd.DataFrame) -> None:
    dataset_table = dataset_summary.to_csv(index=False).strip()
    lines = [
        "# Early Stopping Evaluation With Current Buckaroo Profiler",
        "",
        "This run compares adaptive early-stop predictions against full-pass predictions and the frozen label worksheet.",
        "",
        "## Headline Metrics",
        "",
    ]
    for key, value in summary.items():
        lines.append(f"- `{key}`: `{value}`")

    lines.extend(
        [
            "",
            "## Interpretation Notes",
            "",
            "- `early_stop_vs_manual_accuracy` only uses datasets where adaptive sampling stopped before full data.",
            "- `early_stop_vs_full_agreement` answers whether early stopping made the same semantic decision as full-pass profiling.",
            "- `false_key_errors` count columns where Buckaroo predicted a hard primary key but the manual label says it is not a primary key.",
            "- The current frozen labels contain no true primary-key columns, so this run can measure false-key behavior but not primary-key recall.",
            "",
            "## Per-Dataset Summary",
            "",
            "```csv",
            dataset_table,
            "```",
            "",
            "## Files",
            "",
            "- `early_stop_column_comparison.csv`",
            "- `early_stop_dataset_summary.csv`",
            "- `early_stop_sampling_decisions.csv`",
            "- `early_stop_summary.json`",
        ]
    )
    (OUT_DIR / "early_stop_evaluation_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    labels = pd.read_csv(MANUAL_LABELS)
    labels = labels[labels["dataset_id"].notna() & labels["column_name"].notna()].copy()
    quality = benchmark_quality(labels)

    comparison_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    dataset_summaries: list[dict[str, Any]] = []

    for dataset_id in sorted(labels["dataset_id"].unique()):
        print(f"Starting {dataset_id}...", flush=True)
        dataset_labels = labels[labels["dataset_id"] == dataset_id].copy()
        comparisons, decisions, dataset_summary = evaluate_dataset(str(dataset_id), dataset_labels)
        comparison_rows.extend(comparisons)
        decision_rows.extend(decisions)
        dataset_summaries.append(dataset_summary)
        print(
            f"{dataset_id}: chosen {dataset_summary['chosen_sample_rows']} of {dataset_summary['total_rows']} rows; "
            f"stopped_early={dataset_summary['stopped_early']}; "
            f"runtime_saved_fraction={dataset_summary['runtime_saved_fraction']}",
            flush=True,
        )

    comparisons = pd.DataFrame(comparison_rows)
    decisions = pd.DataFrame(decision_rows)
    dataset_summary = pd.DataFrame(dataset_summaries)
    summary = summarize(comparisons, dataset_summary, quality)
    dataset_paths = [LABEL_DIR / f"{dataset_id}.csv" for dataset_id in sorted(labels["dataset_id"].unique())]
    summary["methodology_version"] = "corrected_v2"
    summary["reproducibility"] = capture_reproducibility(ROOT, [MANUAL_LABELS, *dataset_paths])

    comparisons.to_csv(OUT_DIR / "early_stop_column_comparison.csv", index=False)
    decisions.to_csv(OUT_DIR / "early_stop_sampling_decisions.csv", index=False)
    dataset_summary.to_csv(OUT_DIR / "early_stop_dataset_summary.csv", index=False)
    (OUT_DIR / "early_stop_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    write_report(summary, dataset_summary, comparisons)

    print(OUT_DIR / "early_stop_column_comparison.csv")
    print(OUT_DIR / "early_stop_dataset_summary.csv")
    print(OUT_DIR / "early_stop_sampling_decisions.csv")
    print(OUT_DIR / "early_stop_evaluation_report.md")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
