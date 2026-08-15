"""Compare profiler sampling experiments before and after geography safeguards."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BEFORE_DIR = ROOT / "outputs" / "multi_dataset_sampling_profiler_30_datasets_combined"
DEFAULT_AFTER_DIR = ROOT / "outputs" / "multi_dataset_sampling_profiler_30_datasets_after_geography_safeguards"
DEFAULT_OUT_DIR = DEFAULT_AFTER_DIR / "before_after_comparison"

GEOGRAPHY_PROFILE_ROLES = {
    "airport_code",
    "country_code",
    "geographic_coordinate",
    "high_uniqueness_location_field",
    "location_name",
    "postal_code",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare before/after geography safeguard experiments.")
    parser.add_argument("--before-dir", type=Path, default=DEFAULT_BEFORE_DIR)
    parser.add_argument("--after-dir", type=Path, default=DEFAULT_AFTER_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def load_reference(after_dir: Path) -> pd.DataFrame:
    reference = pd.read_csv(after_dir / "dataset_reference_roles.csv")
    reference = reference[["dataset_id", "column", "reference_primary_key", "reference_profile_role"]].copy()
    reference["reference_primary_key"] = reference["reference_primary_key"].map(to_bool)
    reference["is_geography_reference_role"] = reference["reference_profile_role"].isin(GEOGRAPHY_PROFILE_ROLES)
    return reference


def rescore_predictions(experiment_dir: Path, reference: pd.DataFrame, label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    predictions = pd.read_csv(experiment_dir / "sampling_column_predictions.csv")
    predictions["predicted_primary_key"] = predictions["predicted_primary_key"].map(to_bool)
    predictions = predictions.drop(
        columns=[
            "reference_primary_key",
            "reference_profile_role",
            "is_geography_reference_role",
        ],
        errors="ignore",
    )
    merged = predictions.merge(reference, on=["dataset_id", "column"], how="left", validate="many_to_one")
    merged["reference_primary_key"] = merged["reference_primary_key"].fillna(False).astype(bool)
    merged["is_geography_reference_role"] = merged["is_geography_reference_role"].fillna(False).astype(bool)
    merged["false_primary_key_rescored"] = merged["predicted_primary_key"] & ~merged["reference_primary_key"]
    merged["missed_primary_key_rescored"] = ~merged["predicted_primary_key"] & merged["reference_primary_key"]
    merged["geography_false_primary_key"] = merged["false_primary_key_rescored"] & merged["is_geography_reference_role"]
    merged["experiment_version"] = label

    run_rows = []
    group_columns = ["experiment_version", "dataset_id", "profiler", "sample_rows", "iteration", "seed"]
    for key, group in merged.groupby(group_columns, dropna=False):
        predicted_keys = group.loc[group["predicted_primary_key"], "column"].astype(str).tolist()
        reference_keys = group.loc[group["reference_primary_key"], "column"].astype(str).tolist()
        false_keys = group.loc[group["false_primary_key_rescored"], "column"].astype(str).tolist()
        missed_keys = group.loc[group["missed_primary_key_rescored"], "column"].astype(str).tolist()
        geography_false_keys = group.loc[group["geography_false_primary_key"], "column"].astype(str).tolist()
        predicted_count = len(predicted_keys)
        reference_count = len(reference_keys)
        true_positive = len(set(predicted_keys).intersection(reference_keys))
        precision = true_positive / predicted_count if predicted_count else None
        recall = true_positive / reference_count if reference_count else None
        false_key_rate = len(false_keys) / predicted_count if predicted_count else 0.0
        run_rows.append(
            {
                **dict(zip(group_columns, key)),
                "columns": int(len(group)),
                "predicted_primary_key_count": predicted_count,
                "reference_primary_key_count": reference_count,
                "false_primary_key_count": len(false_keys),
                "false_primary_keys": "; ".join(false_keys),
                "missed_primary_key_count": len(missed_keys),
                "missed_primary_keys": "; ".join(missed_keys),
                "geography_false_primary_key_count": len(geography_false_keys),
                "geography_false_primary_keys": "; ".join(geography_false_keys),
                "primary_key_precision": round(precision, 4) if precision is not None else None,
                "primary_key_recall": round(recall, 4) if recall is not None else None,
                "false_key_rate": round(false_key_rate, 4),
            }
        )

    run_frame = pd.DataFrame(run_rows)
    return merged, run_frame


def summarize(run_frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    by_dataset = (
        run_frame.groupby(["experiment_version", "dataset_id", "profiler", "sample_rows"], dropna=False)
        .agg(
            iterations=("iteration", "count"),
            avg_false_key_rate=("false_key_rate", "mean"),
            avg_false_primary_key_count=("false_primary_key_count", "mean"),
            avg_geography_false_primary_key_count=("geography_false_primary_key_count", "mean"),
            avg_primary_key_precision=("primary_key_precision", "mean"),
            avg_primary_key_recall=("primary_key_recall", "mean"),
        )
        .reset_index()
    )
    overall = (
        by_dataset.groupby(["experiment_version", "profiler", "sample_rows"], dropna=False)
        .agg(
            datasets=("dataset_id", "nunique"),
            total_iterations=("iterations", "sum"),
            avg_false_key_rate=("avg_false_key_rate", "mean"),
            avg_false_primary_key_count=("avg_false_primary_key_count", "mean"),
            avg_geography_false_primary_key_count=("avg_geography_false_primary_key_count", "mean"),
            avg_primary_key_precision=("avg_primary_key_precision", "mean"),
            avg_primary_key_recall=("avg_primary_key_recall", "mean"),
        )
        .reset_index()
    )
    for frame in [by_dataset, overall]:
        for column in frame.columns:
            if column.startswith("avg_"):
                frame[column] = frame[column].round(4)
    return by_dataset, overall


def compare(before: pd.DataFrame, after: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    merged = before.merge(after, on=keys, how="outer", suffixes=("_before", "_after"))
    for metric in [
        "avg_false_key_rate",
        "avg_false_primary_key_count",
        "avg_geography_false_primary_key_count",
        "avg_primary_key_precision",
        "avg_primary_key_recall",
    ]:
        before_col = f"{metric}_before"
        after_col = f"{metric}_after"
        if before_col in merged.columns and after_col in merged.columns:
            merged[f"{metric}_change"] = (merged[after_col] - merged[before_col]).round(4)
            merged[f"{metric}_reduction"] = (merged[before_col] - merged[after_col]).round(4)
    return merged


def write_report(out_dir: Path, comparison_overall: pd.DataFrame) -> None:
    focus = comparison_overall[
        comparison_overall["profiler"].isin(["buckaroo_sample_only_adaptive", "buckaroo_hll_ucc_lite_adaptive"])
    ].copy()
    if not focus.empty:
        total_false_key_reduction = float(focus["avg_false_key_rate_reduction"].fillna(0).sum())
        total_geo_reduction = float(focus["avg_geography_false_primary_key_count_reduction"].fillna(0).sum())
    else:
        total_false_key_reduction = 0.0
        total_geo_reduction = 0.0

    lines = [
        "# Geography Safeguard Before/After Comparison",
        "",
        "Both before and after predictions were re-scored against the after-run geography-aware reference. This keeps the comparison fair: geography fields are treated as semantic locations, not primary keys.",
        "",
        f"- Sum of false-key-rate reductions for Buckaroo adaptive profilers: `{total_false_key_reduction:.4f}`",
        f"- Sum of geography false-key-count reductions for Buckaroo adaptive profilers: `{total_geo_reduction:.4f}`",
        "",
        "## Main Files",
        "",
        "- `before_after_false_key_comparison_overall.csv`",
        "- `before_after_false_key_comparison_by_dataset.csv`",
        "- `before_rescored_iteration_runs.csv`",
        "- `after_rescored_iteration_runs.csv`",
        "",
        "## Research Story",
        "",
        "The experiment found geography/location false-key risk. The profiler was updated with geography safeguards. The after-run verifies whether location-like fields stop being promoted to primary keys.",
    ]
    (out_dir / "before_after_false_key_comparison_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    reference = load_reference(args.after_dir)

    before_predictions, before_runs = rescore_predictions(args.before_dir, reference, "before_geography_safeguard")
    after_predictions, after_runs = rescore_predictions(args.after_dir, reference, "after_geography_safeguard")

    all_runs = pd.concat([before_runs, after_runs], ignore_index=True)
    before_by_dataset, before_overall = summarize(before_runs)
    after_by_dataset, after_overall = summarize(after_runs)

    comparison_by_dataset = compare(
        before_by_dataset.drop(columns=["experiment_version"]),
        after_by_dataset.drop(columns=["experiment_version"]),
        ["dataset_id", "profiler", "sample_rows"],
    )
    comparison_overall = compare(
        before_overall.drop(columns=["experiment_version"]),
        after_overall.drop(columns=["experiment_version"]),
        ["profiler", "sample_rows"],
    )

    before_predictions.to_csv(args.out_dir / "before_rescored_column_predictions.csv", index=False)
    after_predictions.to_csv(args.out_dir / "after_rescored_column_predictions.csv", index=False)
    before_runs.to_csv(args.out_dir / "before_rescored_iteration_runs.csv", index=False)
    after_runs.to_csv(args.out_dir / "after_rescored_iteration_runs.csv", index=False)
    all_runs.to_csv(args.out_dir / "combined_rescored_iteration_runs.csv", index=False)
    comparison_by_dataset.to_csv(args.out_dir / "before_after_false_key_comparison_by_dataset.csv", index=False)
    comparison_overall.to_csv(args.out_dir / "before_after_false_key_comparison_overall.csv", index=False)
    write_report(args.out_dir, comparison_overall)

    print(args.out_dir / "before_after_false_key_comparison_overall.csv")
    print(args.out_dir / "before_after_false_key_comparison_by_dataset.csv")
    print(args.out_dir / "before_after_false_key_comparison_report.md")


if __name__ == "__main__":
    main()
