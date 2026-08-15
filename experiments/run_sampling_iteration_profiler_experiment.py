"""Repeated sampling experiment for profiler stability.

This experiment answers: if we sample K rows multiple times, do the profilers
make the same decisions each time?

It compares:
- Buckaroo sample-only adaptive profiling.
- Buckaroo adaptive profiling with HLL/UCC-lite on the sample.
- Exact exhaustive UCC on the sample.
- Exact single-column FD discovery on the sample.

The full expensive baseline from the ladder experiment is used as the semantic
reference for order_items.csv.
"""

from __future__ import annotations

import argparse
import json
from math import log2
from pathlib import Path
import sys
import time
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.profile_dataset_shape import (  # noqa: E402
    DEFAULT_CARDINALITY_CHUNK_ROWS,
    is_missing_value,
    profile_columns,
    profile_dataset,
    run_detectors_direct,
)
from experiments.run_profiler_ladder_experiment import (  # noqa: E402
    DEFAULT_DATASET,
    ORDER_ITEMS_GROUND_TRUTH,
    exact_exhaustive_ucc,
    exact_functional_dependencies,
    load_order_items_truth,
    semantic_role_from_buckaroo,
    single_key_set,
)
from experiments.run_profiler_variant_comparison import markdown_table, normalize_json_value  # noqa: E402


DEFAULT_OUT_DIR = ROOT / "outputs" / "sampling_iteration_profiler_order_items"
DEFAULT_SAMPLE_SIZES = [100, 500, 1_000, 5_000, 10_000, 50_000]
DEFAULT_ITERATIONS = 10
BASE_SEED = 20260628


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run repeated-sampling profiler stability experiment.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--sample-sizes", type=str, default=",".join(str(value) for value in DEFAULT_SAMPLE_SIZES))
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--base-seed", type=int, default=BASE_SEED)
    parser.add_argument("--cardinality-chunk-rows", type=int, default=DEFAULT_CARDINALITY_CHUNK_ROWS)
    parser.add_argument("--exact-ucc-max-arity", type=int, default=0)
    parser.add_argument("--fd-max-lhs-arity", type=int, default=1)
    parser.add_argument("--keep-sample-files", action="store_true")
    return parser.parse_args()


def parse_sample_sizes(raw: str, total_rows: int) -> list[int]:
    sizes = []
    for token in raw.split(","):
        token = token.strip().lower()
        if not token:
            continue
        if token == "full":
            sizes.append(total_rows)
        else:
            sizes.append(min(int(token.replace("_", "")), total_rows))
    return sorted(set(size for size in sizes if size > 0))


def timed_call(callback) -> tuple[Any, float]:
    start = time.perf_counter()
    value = callback()
    return value, round(time.perf_counter() - start, 3)


def truth_maps(columns: list[str]) -> tuple[dict[str, str], set[str]]:
    frame = load_order_items_truth(columns)
    role_map = frame.set_index("column")["expected_semantic_role"].to_dict()
    key_columns = {column for column, role in role_map.items() if role == "primary_identifier"}
    return role_map, key_columns


def role_entropy(roles: list[str]) -> float:
    if not roles:
        return 0.0
    counts = pd.Series(roles).value_counts()
    total = len(roles)
    entropy = 0.0
    for count in counts:
        probability = count / total
        entropy -= probability * log2(probability)
    return round(entropy, 4)


def detector_summary(profile_df: pd.DataFrame, detector_df: pd.DataFrame) -> dict[str, Any]:
    missing_cells = int(profile_df.map(is_missing_value).sum().sum())
    profiled_cells = max(1, int(profile_df.shape[0] * profile_df.shape[1]))
    errors = run_detectors_direct(detector_df)
    rows_with_errors = int(errors["row_id"].nunique()) if not errors.empty else 0
    return {
        "missing_value_rate": round(float(missing_cells / profiled_cells), 4),
        "rows_with_detector_errors": rows_with_errors,
        "detector_error_records": int(len(errors)),
        "baseline_error_rate": round(float(rows_with_errors / max(1, len(detector_df))), 4),
    }


def run_buckaroo_sample_only_timed(sample_df: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, float]:
    (result, column_profile, ucc_frame), runtime = timed_call(lambda: _run_buckaroo_sample_only_inner(sample_df))
    return result, column_profile, ucc_frame, runtime


def _run_buckaroo_sample_only_inner(sample_df: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    column_profile, roles = profile_columns(sample_df)
    summary = detector_summary(sample_df, sample_df)
    role_counts = column_profile["role"].value_counts().to_dict() if not column_profile.empty else {}
    confidence_counts = column_profile["confidence"].value_counts().to_dict() if not column_profile.empty else {}
    result = {
        **summary,
        "columns_profiled": int(len(column_profile)),
        "numeric_columns": int(role_counts.get("numeric", 0)),
        "categorical_columns": int(role_counts.get("categorical", 0)),
        "identifier_columns": int(role_counts.get("identifier", 0)),
        "average_profile_confidence": round(float(column_profile["confidence_score"].mean()), 3)
        if not column_profile.empty
        else 0.0,
        "high_confidence_columns": int(confidence_counts.get("high", 0)),
        "medium_confidence_columns": int(confidence_counts.get("medium", 0)),
        "low_confidence_columns": int(confidence_counts.get("low", 0)),
        "numeric_column_names": "; ".join(roles["numeric"]),
        "categorical_column_names": "; ".join(roles["categorical"]),
        "identifier_column_names": "; ".join(roles["identifier"]),
    }
    return result, column_profile, pd.DataFrame()


def run_buckaroo_hll_ucc_timed(
    sample_csv: Path,
    sample_rows: int,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, float]:
    (result, column_profile, ucc_frame), runtime = timed_call(
        lambda: profile_dataset(
            sample_csv,
            profile_rows=sample_rows,
            detector_rows=sample_rows,
            cardinality_chunk_rows=args.cardinality_chunk_rows,
        )
    )
    return result, column_profile, ucc_frame, runtime


def run_exact_ucc_timed(sample_df: pd.DataFrame, max_arity: int) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, float]:
    (all_candidates, minimal, summary), runtime = timed_call(lambda: exact_exhaustive_ucc(sample_df, max_arity))
    result = {
        "columns_profiled": int(sample_df.shape[1]),
        "unique_key_candidates": int(summary["minimal_unique_keys"]),
        "single_column_unique_keys": int(summary["single_column_unique_keys"]),
        "evaluated_combinations": int(summary["evaluated_combinations"]),
        "skipped_supersets": int(summary["skipped_supersets"]),
    }
    return result, minimal, all_candidates, runtime


def run_exact_fd_timed(sample_df: pd.DataFrame, max_lhs_arity: int) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, float]:
    (fds, summary), runtime = timed_call(lambda: exact_functional_dependencies(sample_df, max_lhs_arity))
    result = {
        "columns_profiled": int(sample_df.shape[1]),
        "functional_dependencies": int(summary["functional_dependencies"]),
        "checked_dependencies": int(summary["checked_dependencies"]),
    }
    return result, fds, pd.DataFrame(), runtime


def primary_keys_from_buckaroo_sample(column_profile: pd.DataFrame) -> set[str]:
    if column_profile.empty:
        return set()
    keys = set()
    for _, row in column_profile.iterrows():
        column = str(row["column"])
        profile_role = str(row.get("profile_role", ""))
        confidence = str(row.get("confidence", ""))
        cardinality_lower = float(row.get("cardinality_ratio_lower_bound", 0.0) or 0.0)
        if profile_role in {"identifier", "quasi_identifier"} and cardinality_lower >= 0.90:
            if confidence != "low":
                keys.add(column)
    return keys


def fd_primary_keys(fds: pd.DataFrame, columns: list[str]) -> set[str]:
    if fds.empty:
        return set()
    required_rhs_count = max(1, len(columns) - 1)
    lhs_counts = fds.groupby("lhs")["rhs"].nunique()
    return {lhs for lhs, count in lhs_counts.items() if int(count) >= required_rhs_count and " + " not in str(lhs)}


def build_prediction_rows(
    profiler: str,
    sample_rows: int,
    iteration: int,
    seed: int,
    columns: list[str],
    expected_roles: dict[str, str],
    predicted_roles: dict[str, str],
    predicted_keys: set[str],
    column_profile: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    profile_by_column = column_profile.set_index("column") if column_profile is not None and not column_profile.empty else pd.DataFrame()
    rows = []
    for column in columns:
        expected = expected_roles[column]
        predicted = predicted_roles.get(column, "not_predicted")
        confidence_score = None
        profile_role = None
        warning = None
        if column in profile_by_column.index:
            confidence_score = profile_by_column.at[column, "confidence_score"]
            profile_role = profile_by_column.at[column, "profile_role"]
            warning = profile_by_column.at[column, "warning"]
        rows.append(
            {
                "profiler": profiler,
                "sample_rows": sample_rows,
                "iteration": iteration,
                "seed": seed,
                "column": column,
                "expected_semantic_role": expected,
                "predicted_semantic_role": predicted,
                "role_match": predicted == expected,
                "predicted_primary_key": column in predicted_keys,
                "expected_primary_key": expected == "primary_identifier",
                "false_primary_key": column in predicted_keys and expected != "primary_identifier",
                "missed_primary_key": column not in predicted_keys and expected == "primary_identifier",
                "profile_role": profile_role,
                "confidence_score": confidence_score,
                "warning": warning,
            }
        )
    return rows


def buckaroo_roles_from_profile(column_profile: pd.DataFrame, predicted_keys: set[str]) -> dict[str, str]:
    roles = {}
    for _, row in column_profile.iterrows():
        column = str(row["column"])
        roles[column] = semantic_role_from_buckaroo(column, row, predicted_keys)
    return roles


def key_only_roles(columns: list[str], predicted_keys: set[str]) -> dict[str, str]:
    return {
        column: "primary_identifier" if column in predicted_keys else "not_primary_identifier"
        for column in columns
    }


def fd_roles(columns: list[str], predicted_keys: set[str]) -> dict[str, str]:
    return key_only_roles(columns, predicted_keys)


def run_one_iteration(
    full_df: pd.DataFrame,
    sample_rows: int,
    iteration: int,
    seed: int,
    args: argparse.Namespace,
    expected_roles: dict[str, str],
    expected_keys: set[str],
    sample_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[pd.DataFrame], list[pd.DataFrame]]:
    sample_df = full_df.sample(n=sample_rows, replace=False, random_state=seed).reset_index(drop=True)
    sample_csv = sample_dir / f"order_items_sample_{sample_rows}_iter_{iteration}.csv"
    sample_df.to_csv(sample_csv, index=False)
    columns = list(sample_df.columns)
    run_rows: list[dict[str, Any]] = []
    column_rows: list[dict[str, Any]] = []
    ucc_frames: list[pd.DataFrame] = []
    fd_frames: list[pd.DataFrame] = []

    profilers = []

    result, profile, _, runtime = run_buckaroo_sample_only_timed(sample_df)
    predicted_keys = primary_keys_from_buckaroo_sample(profile)
    profilers.append(("buckaroo_sample_only_adaptive", result, profile, pd.DataFrame(), pd.DataFrame(), runtime, predicted_keys))

    result, profile, ucc, runtime = run_buckaroo_hll_ucc_timed(sample_csv, sample_rows, args)
    predicted_keys = single_key_set(ucc)
    profilers.append(("buckaroo_hll_ucc_lite_adaptive", result, profile, ucc, pd.DataFrame(), runtime, predicted_keys))

    result, minimal_ucc, all_ucc, runtime = run_exact_ucc_timed(sample_df, args.exact_ucc_max_arity)
    predicted_keys = single_key_set(minimal_ucc)
    profilers.append(("exact_exhaustive_ucc_sample", result, pd.DataFrame(), minimal_ucc, pd.DataFrame(), runtime, predicted_keys))
    all_ucc = all_ucc.copy()
    all_ucc.insert(0, "profiler", "exact_exhaustive_ucc_sample")
    all_ucc.insert(1, "sample_rows", sample_rows)
    all_ucc.insert(2, "iteration", iteration)
    all_ucc.insert(3, "seed", seed)
    ucc_frames.append(all_ucc)

    result, fds, _, runtime = run_exact_fd_timed(sample_df, args.fd_max_lhs_arity)
    predicted_keys = fd_primary_keys(fds, columns)
    profilers.append(("exact_single_column_fd_sample", result, pd.DataFrame(), pd.DataFrame(), fds, runtime, predicted_keys))

    for profiler, result, profile, ucc, fds, runtime, predicted_keys in profilers:
        if profiler in {"buckaroo_sample_only_adaptive", "buckaroo_hll_ucc_lite_adaptive"}:
            predicted_roles = buckaroo_roles_from_profile(profile, predicted_keys)
        elif profiler == "exact_single_column_fd_sample":
            predicted_roles = fd_roles(columns, predicted_keys)
        else:
            predicted_roles = key_only_roles(columns, predicted_keys)

        role_matches = [
            predicted == expected_roles[column]
            for column, predicted in predicted_roles.items()
            if predicted != "not_primary_identifier"
        ]
        comparable_columns = len(role_matches)
        expected_key_count = len(expected_keys)
        true_positive_keys = len(predicted_keys.intersection(expected_keys))
        false_keys = sorted(predicted_keys.difference(expected_keys))
        missed_keys = sorted(expected_keys.difference(predicted_keys))
        key_precision = true_positive_keys / max(1, len(predicted_keys))
        key_recall = true_positive_keys / max(1, expected_key_count)
        false_key_rate = len(false_keys) / max(1, len(predicted_keys))

        run_rows.append(
            {
                "profiler": profiler,
                "sample_rows": sample_rows,
                "iteration": iteration,
                "seed": seed,
                "runtime_seconds": runtime,
                "comparable_columns": comparable_columns,
                "role_matches": int(sum(role_matches)),
                "semantic_role_accuracy": round(float(sum(role_matches) / max(1, comparable_columns)), 4),
                "predicted_primary_key_count": len(predicted_keys),
                "predicted_primary_keys": "; ".join(sorted(predicted_keys)),
                "true_positive_primary_keys": true_positive_keys,
                "false_primary_key_count": len(false_keys),
                "false_primary_keys": "; ".join(false_keys),
                "missed_primary_key_count": len(missed_keys),
                "missed_primary_keys": "; ".join(missed_keys),
                "primary_key_precision": round(key_precision, 4),
                "primary_key_recall": round(key_recall, 4),
                "false_key_rate": round(false_key_rate, 4),
                "average_profile_confidence": result.get("average_profile_confidence"),
                "detector_error_records": result.get("detector_error_records"),
                "unique_key_candidates": result.get("unique_key_candidates", len(ucc) if not ucc.empty else None),
                "functional_dependencies": result.get("functional_dependencies", len(fds) if not fds.empty else None),
            }
        )

        column_rows.extend(
            build_prediction_rows(
                profiler,
                sample_rows,
                iteration,
                seed,
                columns,
                expected_roles,
                predicted_roles,
                predicted_keys,
                profile,
            )
        )

        if not ucc.empty:
            saved_ucc = ucc.copy()
            saved_ucc.insert(0, "profiler", profiler)
            saved_ucc.insert(1, "sample_rows", sample_rows)
            saved_ucc.insert(2, "iteration", iteration)
            saved_ucc.insert(3, "seed", seed)
            ucc_frames.append(saved_ucc)
        if not fds.empty:
            saved_fds = fds.copy()
            saved_fds.insert(0, "profiler", profiler)
            saved_fds.insert(1, "sample_rows", sample_rows)
            saved_fds.insert(2, "iteration", iteration)
            saved_fds.insert(3, "seed", seed)
            fd_frames.append(saved_fds)

    if not args.keep_sample_files:
        sample_csv.unlink(missing_ok=True)

    return run_rows, column_rows, ucc_frames, fd_frames


def summarize_runs(run_frame: pd.DataFrame, column_frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary = (
        run_frame.groupby(["profiler", "sample_rows"], dropna=False)
        .agg(
            iterations=("iteration", "count"),
            avg_runtime_seconds=("runtime_seconds", "mean"),
            std_runtime_seconds=("runtime_seconds", "std"),
            avg_semantic_role_accuracy=("semantic_role_accuracy", "mean"),
            std_semantic_role_accuracy=("semantic_role_accuracy", "std"),
            avg_primary_key_precision=("primary_key_precision", "mean"),
            avg_primary_key_recall=("primary_key_recall", "mean"),
            avg_false_key_rate=("false_key_rate", "mean"),
            avg_predicted_primary_key_count=("predicted_primary_key_count", "mean"),
            avg_profile_confidence=("average_profile_confidence", "mean"),
        )
        .reset_index()
    )
    for column in [
        "avg_runtime_seconds",
        "std_runtime_seconds",
        "avg_semantic_role_accuracy",
        "std_semantic_role_accuracy",
        "avg_primary_key_precision",
        "avg_primary_key_recall",
        "avg_false_key_rate",
        "avg_predicted_primary_key_count",
        "avg_profile_confidence",
    ]:
        summary[column] = summary[column].round(4)

    stability_rows = []
    for (profiler, sample_rows, column), group in column_frame.groupby(["profiler", "sample_rows", "column"]):
        counts = group["predicted_semantic_role"].value_counts()
        mode_role = str(counts.index[0])
        mode_count = int(counts.iloc[0])
        total = int(len(group))
        stability_rows.append(
            {
                "profiler": profiler,
                "sample_rows": sample_rows,
                "column": column,
                "expected_semantic_role": group["expected_semantic_role"].iloc[0],
                "mode_predicted_role": mode_role,
                "mode_frequency": mode_count,
                "iterations": total,
                "role_stability_rate": round(mode_count / max(1, total), 4),
                "role_entropy": role_entropy(group["predicted_semantic_role"].tolist()),
                "role_counts": "; ".join(f"{role}={count}" for role, count in counts.items()),
                "primary_key_prediction_frequency": round(float(group["predicted_primary_key"].mean()), 4),
                "false_primary_key_frequency": round(float(group["false_primary_key"].mean()), 4),
                "missed_primary_key_frequency": round(float(group["missed_primary_key"].mean()), 4),
                "avg_confidence_score": round(float(group["confidence_score"].dropna().mean()), 4)
                if group["confidence_score"].notna().any()
                else None,
            }
        )
    stability = pd.DataFrame(stability_rows)

    profiler_stability = (
        stability.groupby(["profiler", "sample_rows"], dropna=False)
        .agg(
            avg_role_stability_rate=("role_stability_rate", "mean"),
            min_role_stability_rate=("role_stability_rate", "min"),
            avg_role_entropy=("role_entropy", "mean"),
            unstable_column_count=("role_stability_rate", lambda values: int((values < 1.0).sum())),
            false_key_column_count=("false_primary_key_frequency", lambda values: int((values > 0).sum())),
        )
        .reset_index()
    )
    for column in ["avg_role_stability_rate", "min_role_stability_rate", "avg_role_entropy"]:
        profiler_stability[column] = profiler_stability[column].round(4)

    merged_summary = summary.merge(profiler_stability, on=["profiler", "sample_rows"], how="left")
    return merged_summary, stability, profiler_stability


def build_report(
    dataset: Path,
    sample_sizes: list[int],
    iterations: int,
    summary: pd.DataFrame,
    stability: pd.DataFrame,
    output_files: dict[str, Path],
) -> str:
    display_summary = summary[
        [
            "profiler",
            "sample_rows",
            "iterations",
            "avg_runtime_seconds",
            "avg_semantic_role_accuracy",
            "avg_primary_key_precision",
            "avg_primary_key_recall",
            "avg_false_key_rate",
            "avg_role_stability_rate",
            "unstable_column_count",
            "false_key_column_count",
        ]
    ]
    most_unstable = stability.sort_values(
        ["role_stability_rate", "false_primary_key_frequency"],
        ascending=[True, False],
    ).head(20)
    lines = [
        "# Repeated Sampling Profiler Stability Experiment",
        "",
        f"Dataset: `{dataset}`",
        f"Sample sizes: `{', '.join(str(size) for size in sample_sizes)}`",
        f"Iterations per size: `{iterations}`",
        "",
        "## What This Reveals",
        "- Whether a profiler gives the same answer across different random samples of the same size.",
        "- How much runtime we save by sampling.",
        "- Which columns are fragile under sampling.",
        "- Whether sample-based key discovery creates false primary keys.",
        "",
        "## Summary By Profiler And Sample Size",
        markdown_table(display_summary),
        "",
        "## Most Unstable Column Decisions",
        markdown_table(
            most_unstable[
                [
                    "profiler",
                    "sample_rows",
                    "column",
                    "expected_semantic_role",
                    "mode_predicted_role",
                    "role_stability_rate",
                    "role_counts",
                    "false_primary_key_frequency",
                    "missed_primary_key_frequency",
                ]
            ]
        ),
        "",
        "## Beginner-Friendly Interpretation",
        "- A single sample is not enough to judge a profiler; repeated samples show stability.",
        "- High accuracy with low stability means the profiler sometimes gets lucky.",
        "- High key recall with high false-key rate means the profiler finds real keys but also invents accidental keys.",
        "- The best Buckaroo default should be the smallest sample size where roles and key decisions are stable enough.",
        "",
        "## Output Files",
    ]
    for label, path in output_files.items():
        lines.append(f"- `{label}`: `{path}`")
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    sample_dir = args.out_dir / "samples"
    sample_dir.mkdir(exist_ok=True)

    full_df = pd.read_csv(args.dataset, low_memory=False)
    sample_sizes = parse_sample_sizes(args.sample_sizes, len(full_df))
    expected_roles, expected_keys = truth_maps(list(full_df.columns))

    all_run_rows: list[dict[str, Any]] = []
    all_column_rows: list[dict[str, Any]] = []
    all_ucc_frames: list[pd.DataFrame] = []
    all_fd_frames: list[pd.DataFrame] = []

    for sample_rows in sample_sizes:
        for iteration in range(1, args.iterations + 1):
            seed = int(args.base_seed + (sample_rows * 100) + iteration)
            print(f"Sampling {sample_rows} rows, iteration {iteration}/{args.iterations}, seed={seed}", flush=True)
            run_rows, column_rows, ucc_frames, fd_frames = run_one_iteration(
                full_df,
                sample_rows,
                iteration,
                seed,
                args,
                expected_roles,
                expected_keys,
                sample_dir,
            )
            all_run_rows.extend(run_rows)
            all_column_rows.extend(column_rows)
            all_ucc_frames.extend(ucc_frames)
            all_fd_frames.extend(fd_frames)

    run_frame = pd.DataFrame(all_run_rows)
    column_frame = pd.DataFrame(all_column_rows)
    summary, stability, profiler_stability = summarize_runs(run_frame, column_frame)

    output_files = {
        "sampling_iteration_runs.csv": args.out_dir / "sampling_iteration_runs.csv",
        "sampling_column_predictions.csv": args.out_dir / "sampling_column_predictions.csv",
        "sampling_summary_by_profiler_and_size.csv": args.out_dir / "sampling_summary_by_profiler_and_size.csv",
        "sampling_column_stability.csv": args.out_dir / "sampling_column_stability.csv",
        "sampling_profiler_stability.csv": args.out_dir / "sampling_profiler_stability.csv",
        "sampling_ucc_candidates.csv": args.out_dir / "sampling_ucc_candidates.csv",
        "sampling_functional_dependencies.csv": args.out_dir / "sampling_functional_dependencies.csv",
        "experiment_config.json": args.out_dir / "experiment_config.json",
        "report.md": args.out_dir / "report.md",
    }

    run_frame.to_csv(output_files["sampling_iteration_runs.csv"], index=False)
    column_frame.to_csv(output_files["sampling_column_predictions.csv"], index=False)
    summary.to_csv(output_files["sampling_summary_by_profiler_and_size.csv"], index=False)
    stability.to_csv(output_files["sampling_column_stability.csv"], index=False)
    profiler_stability.to_csv(output_files["sampling_profiler_stability.csv"], index=False)
    if all_ucc_frames:
        pd.concat(all_ucc_frames, ignore_index=True).to_csv(output_files["sampling_ucc_candidates.csv"], index=False)
    else:
        pd.DataFrame().to_csv(output_files["sampling_ucc_candidates.csv"], index=False)
    if all_fd_frames:
        pd.concat(all_fd_frames, ignore_index=True).to_csv(output_files["sampling_functional_dependencies.csv"], index=False)
    else:
        pd.DataFrame().to_csv(output_files["sampling_functional_dependencies.csv"], index=False)
    output_files["experiment_config.json"].write_text(
        json.dumps(
            normalize_json_value(
                {
                    "dataset": str(args.dataset),
                    "sample_sizes": sample_sizes,
                    "iterations": args.iterations,
                    "base_seed": args.base_seed,
                    "profilers": [
                        "buckaroo_sample_only_adaptive",
                        "buckaroo_hll_ucc_lite_adaptive",
                        "exact_exhaustive_ucc_sample",
                        "exact_single_column_fd_sample",
                    ],
                    "ground_truth": ORDER_ITEMS_GROUND_TRUTH,
                }
            ),
            indent=2,
        ),
        encoding="utf-8",
    )
    output_files["report.md"].write_text(
        build_report(args.dataset, sample_sizes, args.iterations, summary, stability, output_files),
        encoding="utf-8",
    )

    if not args.keep_sample_files:
        for sample_file in sample_dir.glob("*.csv"):
            sample_file.unlink(missing_ok=True)

    print(f"Wrote repeated sampling outputs to {args.out_dir}", flush=True)


if __name__ == "__main__":
    main()
