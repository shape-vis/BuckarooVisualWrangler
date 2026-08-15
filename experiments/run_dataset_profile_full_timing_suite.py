"""Run full-row and sample-size timing experiments for dataset profiling.

This script is intentionally a "suite" around the three profiling experiments
we already ran:

1. Dataset shape + detector baseline profiling.
2. Sample-size stability + edge-case testing.
3. Column-type definition threshold testing.

The new thing here is timing.  Each output row says which experiment ran, which
dataset was used, how many rows were inspected, and how long that work took.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from detectors.common import is_missing_value  # noqa: E402
from experiments.profile_column_type_definition_experiment import (  # noqa: E402
    MANUAL_LABELS,
    classify_with_definition,
    compute_column_evidence,
    named_definitions,
    score_definition,
    threshold_sweep_definitions,
)
from experiments.profile_dataset_shape import profile_columns, run_detectors_direct  # noqa: E402
from experiments.profile_dataset_stability_experiments import edge_case_frames  # noqa: E402


DATASET_DIR = ROOT / "provided_datasets"
OUT_DIR = ROOT / "experiments" / "full_dataset_profile_timing_outputs"

EXPERIMENT1_DATASETS = [
    "(missing data)stackoverflow_db_uncleaned.csv",
    "(original)crimes___one_year_prior_to_present_20250421.csv",
    "(original)stackoverflow_db_uncleaned.csv",
    "adult.csv",
    "cars.csv",
    "complaints-2025-04-21_17_31.csv",
    "crimes.csv",
    "Crimes_-_One_year_prior_to_present_20250421.csv",
    "crimes___one_year_prior_to_present_20250421 copy.csv",
    "games.csv",
    "stackoverflow_db.csv",
    "stackoverflow_db_uncleaned.csv",
    "stackoverflow_db_uncleaned_original.csv",
]

EXPERIMENT2_DATASETS = [
    "adult.csv",
    "cars.csv",
    "complaints-2025-04-21_17_31.csv",
    "crimes.csv",
    "games.csv",
    "stackoverflow_db_uncleaned.csv",
]

SAMPLE_SIZES: list[int | str] = [50, 100, 200, 500, 1000, 3000, "all"]
RANDOM_SEEDS = [11, 23, 37]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full-row timing suite for dataset profiling experiments.")
    parser.add_argument(
        "--experiment",
        choices=["experiment1", "experiment2", "experiment3", "all"],
        default="all",
        help="Which experiment group to run.",
    )
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    return parser.parse_args()


def elapsed(start: float) -> float:
    return round(time.perf_counter() - start, 4)


def sample_label(sample_size: int | str) -> str:
    return "all" if sample_size == "all" else str(sample_size)


def markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No rows._"
    columns = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for _, row in frame.iterrows():
        lines.append("| " + " | ".join(str(row[column]) for column in frame.columns) + " |")
    return "\n".join(lines)


def read_csv_for_sample(path: Path, sample_size: int | str) -> tuple[pd.DataFrame, float]:
    start = time.perf_counter()
    if sample_size == "all":
        frame = pd.read_csv(path, low_memory=False)
    else:
        frame = pd.read_csv(path, nrows=int(sample_size), low_memory=False)
    return frame, elapsed(start)


def missing_rate(df: pd.DataFrame) -> float:
    cells = max(1, int(df.shape[0] * df.shape[1]))
    missing_cells = int(df.map(is_missing_value).sum().sum())
    return float(missing_cells / cells)


def role_count_dict(column_profile: pd.DataFrame) -> dict[str, int]:
    if column_profile.empty:
        return {}
    counts = column_profile["role"].value_counts().to_dict()
    return {str(key): int(value) for key, value in counts.items()}


def detector_baseline(df: pd.DataFrame) -> tuple[float, int, int, float]:
    start = time.perf_counter()
    errors = run_detectors_direct(df)
    runtime = elapsed(start)
    rows_with_errors = int(errors["row_id"].nunique()) if not errors.empty else 0
    baseline = rows_with_errors / max(1, len(df))
    return float(baseline), rows_with_errors, int(len(errors)), runtime


def run_experiment1(out_dir: Path) -> pd.DataFrame:
    """Time the original dataset-shape profile at many row counts."""

    rows: list[dict[str, Any]] = []
    for dataset_name in EXPERIMENT1_DATASETS:
        path = DATASET_DIR / dataset_name
        print(f"[experiment1] {dataset_name}", flush=True)

        full_df, full_read_seconds = read_csv_for_sample(path, "all")
        total_rows = int(len(full_df))
        total_columns = int(len(full_df.columns))
        del full_df

        for sample_size in SAMPLE_SIZES:
            print(f"  rows={sample_label(sample_size)}", flush=True)
            df, read_seconds = read_csv_for_sample(path, sample_size)

            shape_start = time.perf_counter()
            column_profile, roles = profile_columns(df)
            dataset_missing_rate = missing_rate(df)
            shape_seconds = elapsed(shape_start)

            baseline, rows_with_errors, detector_error_records, detector_seconds = detector_baseline(df)
            role_counts = role_count_dict(column_profile)

            rows.append(
                {
                    "experiment": "dataset_shape_profile",
                    "dataset": dataset_name,
                    "sample_label": sample_label(sample_size),
                    "requested_rows": total_rows if sample_size == "all" else int(sample_size),
                    "actual_rows": int(len(df)),
                    "total_rows": total_rows,
                    "total_columns": total_columns,
                    "csv_read_seconds": read_seconds,
                    "full_csv_read_seconds": full_read_seconds,
                    "shape_profile_seconds": shape_seconds,
                    "detector_seconds": detector_seconds,
                    "total_runtime_seconds": round(read_seconds + shape_seconds + detector_seconds, 4),
                    "numeric_columns": int(role_counts.get("numeric", 0)),
                    "categorical_columns": int(role_counts.get("categorical", 0)),
                    "free_text_columns": int(role_counts.get("free_text", 0)),
                    "identifier_columns": int(role_counts.get("identifier", 0)),
                    "missing_value_rate": round(dataset_missing_rate, 5),
                    "baseline_error_rate": round(baseline, 5),
                    "rows_with_detector_errors": rows_with_errors,
                    "detector_error_records": detector_error_records,
                    "numeric_column_names": "; ".join(roles.get("numeric", [])[:20]),
                    "categorical_column_names": "; ".join(roles.get("categorical", [])[:20]),
                    "free_text_column_names": "; ".join(roles.get("free_text", [])[:20]),
                    "identifier_column_names": "; ".join(roles.get("identifier", [])[:20]),
                }
            )

    result = pd.DataFrame(rows)
    result.to_csv(out_dir / "experiment1_dataset_shape_timing.csv", index=False)
    return result


def shape_profile_counts(df: pd.DataFrame) -> tuple[dict[str, int], float, float]:
    start = time.perf_counter()
    column_profile, _ = profile_columns(df)
    dataset_missing_rate = missing_rate(df)
    runtime = elapsed(start)
    return role_count_dict(column_profile), dataset_missing_rate, runtime


def role_distance(sample: dict[str, int], reference: dict[str, int]) -> int:
    return sum(
        abs(int(sample.get(role, 0)) - int(reference.get(role, 0)))
        for role in ("numeric", "categorical", "free_text", "identifier")
    )


def random_or_full(df: pd.DataFrame, sample_size: int | str, seed: int) -> pd.DataFrame:
    if sample_size == "all" or len(df) <= int(sample_size):
        return df.copy()
    return df.sample(n=int(sample_size), random_state=seed).copy()


def run_experiment2(out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Time the stability experiment, using full rows as the reference."""

    shape_rows: list[dict[str, Any]] = []
    detector_rows: list[dict[str, Any]] = []

    for dataset_name in EXPERIMENT2_DATASETS:
        path = DATASET_DIR / dataset_name
        print(f"[experiment2] {dataset_name}", flush=True)
        df, read_seconds = read_csv_for_sample(path, "all")
        total_rows = int(len(df))

        reference_counts, reference_missing_rate, reference_shape_seconds = shape_profile_counts(df)
        reference_baseline, reference_rows_with_errors, reference_error_records, reference_detector_seconds = detector_baseline(df)

        for sample_size in SAMPLE_SIZES:
            seeds = [0] if sample_size == "all" or total_rows <= int(sample_size) else RANDOM_SEEDS
            for seed in seeds:
                print(f"  shape rows={sample_label(sample_size)} seed={seed}", flush=True)
                sample_start = time.perf_counter()
                sample_df = random_or_full(df, sample_size, seed)
                sampling_seconds = elapsed(sample_start)
                counts, sample_missing_rate, shape_seconds = shape_profile_counts(sample_df)
                shape_rows.append(
                    {
                        "experiment": "shape_stability",
                        "dataset": dataset_name,
                        "sample_label": sample_label(sample_size),
                        "requested_rows": total_rows if sample_size == "all" else int(sample_size),
                        "actual_rows": int(len(sample_df)),
                        "total_rows": total_rows,
                        "seed": seed,
                        "csv_read_seconds": read_seconds,
                        "sampling_seconds": sampling_seconds,
                        "shape_profile_seconds": shape_seconds,
                        "total_runtime_without_read_seconds": round(sampling_seconds + shape_seconds, 4),
                        "reference_shape_profile_seconds": reference_shape_seconds,
                        "numeric_columns": int(counts.get("numeric", 0)),
                        "categorical_columns": int(counts.get("categorical", 0)),
                        "free_text_columns": int(counts.get("free_text", 0)),
                        "identifier_columns": int(counts.get("identifier", 0)),
                        "missing_value_rate": round(sample_missing_rate, 5),
                        "reference_numeric_columns": int(reference_counts.get("numeric", 0)),
                        "reference_categorical_columns": int(reference_counts.get("categorical", 0)),
                        "reference_free_text_columns": int(reference_counts.get("free_text", 0)),
                        "reference_identifier_columns": int(reference_counts.get("identifier", 0)),
                        "reference_missing_value_rate": round(reference_missing_rate, 5),
                        "role_distance_from_full": role_distance(counts, reference_counts),
                        "missing_rate_abs_error_from_full": round(abs(sample_missing_rate - reference_missing_rate), 5),
                    }
                )

        for sample_size in SAMPLE_SIZES:
            seeds = [0] if sample_size == "all" or total_rows <= int(sample_size) else RANDOM_SEEDS
            for seed in seeds:
                if sample_size == "all":
                    baseline = reference_baseline
                    rows_with_errors = reference_rows_with_errors
                    error_records = reference_error_records
                    detector_seconds = reference_detector_seconds
                    sampling_seconds = 0.0
                    actual_rows = total_rows
                else:
                    print(f"  detector rows={sample_label(sample_size)} seed={seed}", flush=True)
                    sample_start = time.perf_counter()
                    sample_df = random_or_full(df, sample_size, seed)
                    sampling_seconds = elapsed(sample_start)
                    actual_rows = int(len(sample_df))
                    baseline, rows_with_errors, error_records, detector_seconds = detector_baseline(sample_df)

                detector_rows.append(
                    {
                        "experiment": "detector_stability",
                        "dataset": dataset_name,
                        "sample_label": sample_label(sample_size),
                        "requested_rows": total_rows if sample_size == "all" else int(sample_size),
                        "actual_rows": actual_rows,
                        "total_rows": total_rows,
                        "seed": seed,
                        "csv_read_seconds": read_seconds,
                        "sampling_seconds": sampling_seconds,
                        "detector_seconds": detector_seconds,
                        "total_runtime_without_read_seconds": round(sampling_seconds + detector_seconds, 4),
                        "baseline_error_rate": round(baseline, 5),
                        "full_baseline_error_rate": round(reference_baseline, 5),
                        "baseline_abs_error_from_full": round(abs(baseline - reference_baseline), 5),
                        "rows_with_detector_errors": rows_with_errors,
                        "detector_error_records": error_records,
                    }
                )

    edge_rows: list[dict[str, Any]] = []
    for case_name, (df, expected_roles) in edge_case_frames().items():
        print(f"[experiment2-edge] {case_name}", flush=True)
        start = time.perf_counter()
        column_profile, _ = profile_columns(df)
        shape_seconds = elapsed(start)
        baseline, rows_with_errors, error_records, detector_seconds = detector_baseline(df)
        for _, record in column_profile.iterrows():
            column = str(record["column"])
            expected = expected_roles[column]
            observed = str(record["role"])
            edge_rows.append(
                {
                    "experiment": "synthetic_edge_case",
                    "case": case_name,
                    "column": column,
                    "expected_role": expected,
                    "observed_role": observed,
                    "passed": expected == observed,
                    "actual_rows": int(len(df)),
                    "shape_profile_seconds": shape_seconds,
                    "detector_seconds": detector_seconds,
                    "total_runtime_seconds": round(shape_seconds + detector_seconds, 4),
                    "baseline_error_rate": round(baseline, 5),
                    "rows_with_detector_errors": rows_with_errors,
                    "detector_error_records": error_records,
                }
            )

    shape_result = pd.DataFrame(shape_rows)
    detector_result = pd.DataFrame(detector_rows)
    edge_result = pd.DataFrame(edge_rows)
    shape_result.to_csv(out_dir / "experiment2_shape_stability_full_timing.csv", index=False)
    detector_result.to_csv(out_dir / "experiment2_detector_stability_full_timing.csv", index=False)
    edge_result.to_csv(out_dir / "experiment2_edge_case_timing.csv", index=False)
    return shape_result, detector_result, edge_result


def load_labeled_evidence_for_sample(sample_size: int | str) -> tuple[pd.DataFrame, pd.DataFrame]:
    evidence_rows: list[dict[str, Any]] = []
    timing_rows: list[dict[str, Any]] = []

    for dataset, labels in MANUAL_LABELS.items():
        path = DATASET_DIR / dataset
        df, read_seconds = read_csv_for_sample(path, sample_size)
        evidence_start = time.perf_counter()
        for column, expected_role in labels.items():
            evidence = compute_column_evidence(dataset, column, df[column])
            evidence["expected_role"] = expected_role
            evidence["sample_label"] = sample_label(sample_size)
            evidence["actual_rows"] = int(len(df))
            evidence_rows.append(evidence)
        evidence_seconds = elapsed(evidence_start)
        timing_rows.append(
            {
                "experiment": "column_type_definition",
                "dataset": dataset,
                "sample_label": sample_label(sample_size),
                "actual_rows": int(len(df)),
                "labeled_columns": len(labels),
                "csv_read_seconds": read_seconds,
                "evidence_seconds": evidence_seconds,
                "total_runtime_seconds": round(read_seconds + evidence_seconds, 4),
            }
        )

    return pd.DataFrame(evidence_rows), pd.DataFrame(timing_rows)


def run_experiment3(out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Time the column-type definition experiment at many row counts."""

    definitions = named_definitions() + threshold_sweep_definitions()
    named_definition_names = {definition.name for definition in named_definitions()}
    all_score_rows: list[dict[str, Any]] = []
    named_prediction_rows: list[dict[str, Any]] = []
    timing_frames: list[pd.DataFrame] = []

    for sample_size in SAMPLE_SIZES:
        print(f"[experiment3] rows={sample_label(sample_size)}", flush=True)
        evidence_frame, timing_frame = load_labeled_evidence_for_sample(sample_size)
        timing_frames.append(timing_frame)

        scoring_start = time.perf_counter()
        for definition in definitions:
            summary, predictions = score_definition(definition, evidence_frame)
            summary["sample_label"] = sample_label(sample_size)
            summary["scoring_seconds_for_sample"] = 0.0
            all_score_rows.append(summary)
            if definition.name in named_definition_names:
                for prediction in predictions:
                    prediction["sample_label"] = sample_label(sample_size)
                    named_prediction_rows.append(prediction)
        scoring_seconds = elapsed(scoring_start)
        for row in all_score_rows:
            if row["sample_label"] == sample_label(sample_size):
                row["scoring_seconds_for_sample"] = scoring_seconds

    scores = pd.DataFrame(all_score_rows)
    named_scores = scores[scores["name"].isin(named_definition_names)].copy()
    named_predictions = pd.DataFrame(named_prediction_rows)
    timings = pd.concat(timing_frames, ignore_index=True)

    scores = scores.sort_values(
        ["sample_label", "ranking_score", "accuracy", "macro_recall", "worst_role_recall"],
        ascending=[True, False, False, False, False],
    )
    named_scores = named_scores.sort_values(
        ["sample_label", "ranking_score", "accuracy", "macro_recall", "worst_role_recall"],
        ascending=[True, False, False, False, False],
    )

    scores.to_csv(out_dir / "experiment3_column_definition_scores_by_sample.csv", index=False)
    named_scores.to_csv(out_dir / "experiment3_column_definition_named_scores_by_sample.csv", index=False)
    named_predictions.to_csv(out_dir / "experiment3_column_definition_named_predictions_by_sample.csv", index=False)
    timings.to_csv(out_dir / "experiment3_column_definition_dataset_timing.csv", index=False)
    return scores, named_scores, timings


def build_summary_report(out_dir: Path) -> None:
    lines = ["# Full Dataset Profile Timing Suite", ""]

    exp1_path = out_dir / "experiment1_dataset_shape_timing.csv"
    if exp1_path.exists():
        exp1 = pd.read_csv(exp1_path)
        latest = exp1[exp1["sample_label"].isin(["50", "200", "500", "3000", "all"])].copy()
        latest = latest[
            [
                "dataset",
                "sample_label",
                "actual_rows",
                "shape_profile_seconds",
                "detector_seconds",
                "total_runtime_seconds",
                "baseline_error_rate",
            ]
        ]
        lines.extend(["## Experiment 1: Dataset Shape + Detector Timing", markdown_table(latest), ""])

    shape_path = out_dir / "experiment2_shape_stability_full_timing.csv"
    detector_path = out_dir / "experiment2_detector_stability_full_timing.csv"
    if shape_path.exists() and detector_path.exists():
        shape = pd.read_csv(shape_path)
        detector = pd.read_csv(detector_path)
        shape_summary = (
            shape.groupby("sample_label")
            .agg(
                runs=("dataset", "count"),
                mean_shape_seconds=("shape_profile_seconds", "mean"),
                max_shape_seconds=("shape_profile_seconds", "max"),
                stable_role_runs=("role_distance_from_full", lambda values: int((values == 0).sum())),
                mean_missing_error=("missing_rate_abs_error_from_full", "mean"),
            )
            .reset_index()
        )
        detector_summary = (
            detector.groupby("sample_label")
            .agg(
                runs=("dataset", "count"),
                mean_detector_seconds=("detector_seconds", "mean"),
                max_detector_seconds=("detector_seconds", "max"),
                stable_baseline_runs=("baseline_abs_error_from_full", lambda values: int((values <= 0.05).sum())),
                mean_baseline_error=("baseline_abs_error_from_full", "mean"),
            )
            .reset_index()
        )
        lines.extend(
            [
                "## Experiment 2: Shape Stability Timing Summary",
                markdown_table(shape_summary.round(5)),
                "",
                "## Experiment 2: Detector Stability Timing Summary",
                markdown_table(detector_summary.round(5)),
                "",
            ]
        )

    exp3_named_path = out_dir / "experiment3_column_definition_named_scores_by_sample.csv"
    exp3_timing_path = out_dir / "experiment3_column_definition_dataset_timing.csv"
    if exp3_named_path.exists() and exp3_timing_path.exists():
        named = pd.read_csv(exp3_named_path)
        timing = pd.read_csv(exp3_timing_path)
        current = named[named["name"] == "current_profiler"][
            ["sample_label", "accuracy", "macro_recall", "worst_role_recall", "correct_columns", "total_columns"]
        ]
        timing_summary = (
            timing.groupby("sample_label")
            .agg(
                datasets=("dataset", "count"),
                total_read_seconds=("csv_read_seconds", "sum"),
                total_evidence_seconds=("evidence_seconds", "sum"),
                total_runtime_seconds=("total_runtime_seconds", "sum"),
            )
            .reset_index()
        )
        lines.extend(
            [
                "## Experiment 3: Current Profiler Definition Across Row Counts",
                markdown_table(current),
                "",
                "## Experiment 3: Dataset Timing",
                markdown_table(timing_summary.round(4)),
                "",
            ]
        )

    (out_dir / "full_dataset_profile_timing_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.experiment in {"experiment1", "all"}:
        run_experiment1(args.out_dir)
    if args.experiment in {"experiment2", "all"}:
        run_experiment2(args.out_dir)
    if args.experiment in {"experiment3", "all"}:
        run_experiment3(args.out_dir)

    build_summary_report(args.out_dir)
    print(f"Wrote full timing outputs to: {args.out_dir}", flush=True)


if __name__ == "__main__":
    main()
