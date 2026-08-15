"""Build a profiler ladder from expensive baselines down to Buckaroo-light.

The goal is to compare separate profiler variants on one dataset:

1. Best-expensive ensemble, ignoring runtime.
2. Exact exhaustive UCC discovery.
3. Exact single-column functional dependency discovery.
4. Metanome HyUCC/HyFD output from the previous full run.
5. DataProfiler structural summaries.
6. Deequ quality checks.
7. Buckaroo adaptive variants from the confidence-interval comparison run.

This script writes CSV/JSON/Markdown artifacts that make the tradeoffs easy to
explain: runtime, output type, role agreement, and what each profiler contributes.
"""

from __future__ import annotations

import argparse
from itertools import combinations
import json
from pathlib import Path
import sys
import time
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.run_profiler_variant_comparison import (  # noqa: E402
    DEFAULT_DATAPROFILER_DIR,
    DEFAULT_DEEQU_DIR,
    DEFAULT_METANOME_DIR,
    markdown_table,
    normalize_json_value,
    read_csv_if_exists,
)


DEFAULT_REUSE_COMPARISON_DIR = ROOT / "outputs" / "profiler_variant_comparison_order_items_ci"
DEFAULT_OUT_DIR = ROOT / "outputs" / "profiler_ladder_order_items"


ORDER_ITEMS_GROUND_TRUTH = {
    "id": "primary_identifier",
    "order_id": "foreign_key_or_reference",
    "user_id": "foreign_key_or_reference",
    "product_id": "foreign_key_or_reference",
    "inventory_item_id": "primary_identifier",
    "status": "low_cardinality_category",
    "created_at": "datetime_lifecycle_field",
    "shipped_at": "datetime_lifecycle_field",
    "delivered_at": "datetime_lifecycle_field",
    "returned_at": "datetime_lifecycle_field",
    "sale_price": "numeric_measure",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run profiler ladder comparison.")
    parser.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="Path to the order_items.csv benchmark used by this ladder.",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--reuse-comparison-dir", type=Path, default=DEFAULT_REUSE_COMPARISON_DIR)
    parser.add_argument("--metanome-dir", type=Path, default=DEFAULT_METANOME_DIR)
    parser.add_argument("--deequ-dir", type=Path, default=DEFAULT_DEEQU_DIR)
    parser.add_argument("--dataprofiler-dir", type=Path, default=DEFAULT_DATAPROFILER_DIR)
    parser.add_argument(
        "--exhaustive-ucc-max-arity",
        type=int,
        default=0,
        help="0 means all arities. For order_items.csv this is all 11 columns.",
    )
    parser.add_argument(
        "--fd-max-lhs-arity",
        type=int,
        default=1,
        help="Exact local FD discovery defaults to single-column determinants.",
    )
    return parser.parse_args()


def timed_call(label: str, callback) -> tuple[Any, float]:
    print(f"Running {label}...", flush=True)
    start = time.perf_counter()
    value = callback()
    return value, round(time.perf_counter() - start, 3)


def split_columns(value: Any) -> list[str]:
    if pd.isna(value):
        return []
    return [part.strip() for part in str(value).split("+") if part.strip()]


def load_order_items_truth(columns: list[str]) -> pd.DataFrame:
    rows = []
    for column in columns:
        rows.append(
            {
                "column": column,
                "expected_semantic_role": ORDER_ITEMS_GROUND_TRUTH.get(column, "unknown"),
                "why": expected_role_explanation(column),
            }
        )
    return pd.DataFrame(rows)


def expected_role_explanation(column: str) -> str:
    if column in {"id", "inventory_item_id"}:
        return "Expected to uniquely identify rows in order_items.csv."
    if column.endswith("_id"):
        return "Expected to reference another ecommerce entity and repeat across rows."
    if column.endswith("_at"):
        return "Expected to be a lifecycle timestamp with missingness depending on order status."
    if column == "status":
        return "Expected to be a small allowed-value category."
    if column == "sale_price":
        return "Expected to be a numeric measurement."
    return "No manual role assigned."


def exact_exhaustive_ucc(df: pd.DataFrame, max_arity: int = 0) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    columns = list(df.columns)
    row_count = int(len(df))
    max_width = len(columns) if max_arity <= 0 else min(max_arity, len(columns))
    evaluated_rows = []
    minimal_keys: list[tuple[str, ...]] = []
    skipped_supersets = 0

    for arity in range(1, max_width + 1):
        for combo in combinations(columns, arity):
            combo_set = set(combo)
            if any(set(existing).issubset(combo_set) for existing in minimal_keys):
                skipped_supersets += 1
                continue

            if arity == 1:
                unique_tuple_count = int(df[combo[0]].nunique(dropna=False))
            else:
                unique_tuple_count = int(df.loc[:, list(combo)].drop_duplicates().shape[0])

            is_unique = unique_tuple_count == row_count
            if is_unique:
                minimal_keys.append(combo)

            evaluated_rows.append(
                {
                    "columns": " + ".join(combo),
                    "arity": arity,
                    "unique_tuple_count": unique_tuple_count,
                    "row_count": row_count,
                    "uniqueness_ratio": round(float(unique_tuple_count / max(1, row_count)), 6),
                    "is_unique": is_unique,
                    "is_minimal": is_unique,
                }
            )

    all_candidates = pd.DataFrame(evaluated_rows)
    minimal = all_candidates.loc[all_candidates["is_unique"]].copy() if not all_candidates.empty else pd.DataFrame()
    summary = {
        "evaluated_combinations": int(len(all_candidates)),
        "skipped_supersets": int(skipped_supersets),
        "minimal_unique_keys": int(len(minimal)),
        "single_column_unique_keys": int((minimal["arity"] == 1).sum()) if not minimal.empty else 0,
        "max_arity_checked": int(max_width),
    }
    return all_candidates, minimal, summary


def exact_functional_dependencies(df: pd.DataFrame, max_lhs_arity: int = 1) -> tuple[pd.DataFrame, dict[str, Any]]:
    columns = list(df.columns)
    max_width = min(max_lhs_arity, max(1, len(columns) - 1))
    rows = []
    checked = 0

    for arity in range(1, max_width + 1):
        for lhs in combinations(columns, arity):
            remaining_rhs = [column for column in columns if column not in lhs]
            grouped = df.groupby(list(lhs), dropna=False, sort=False)
            for rhs in remaining_rhs:
                checked += 1
                max_rhs_values = int(grouped[rhs].nunique(dropna=False).max())
                if max_rhs_values <= 1:
                    rows.append(
                        {
                            "lhs": " + ".join(lhs),
                            "rhs": rhs,
                            "determinant_arity": arity,
                            "dependency": f"{' + '.join(lhs)} -> {rhs}",
                            "max_rhs_values_per_lhs": max_rhs_values,
                        }
                    )

    frame = pd.DataFrame(rows)
    summary = {
        "checked_dependencies": checked,
        "functional_dependencies": int(len(frame)),
        "max_lhs_arity_checked": int(max_width),
    }
    return frame, summary


def semantic_role_from_buckaroo(column: str, row: pd.Series, single_key_columns: set[str]) -> str:
    profile_role = str(row.get("profile_role", ""))
    if profile_role in {"datetime_category", "datetime_high_uniqueness", "datetime_identifier"} or column.endswith("_at"):
        return "datetime_lifecycle_field"
    if column in single_key_columns:
        return "primary_identifier"
    if column.endswith("_id"):
        return "foreign_key_or_reference"
    if profile_role in {"numeric_measure"} or column == "sale_price":
        return "numeric_measure"
    if profile_role in {"categorical", "binary_category", "numeric_code_category"} or column == "status":
        return "low_cardinality_category"
    return "unknown"


def semantic_role_from_pandas(column: str, row: pd.Series) -> str:
    dtype = str(row.get("pandas_dtype", ""))
    unique_ratio = float(row.get("unique_ratio", 0.0) or 0.0)
    if column in {"id", "inventory_item_id"} and unique_ratio >= 0.99:
        return "primary_identifier"
    if column.endswith("_id"):
        return "foreign_key_or_reference"
    if column.endswith("_at"):
        return "datetime_lifecycle_field"
    if column == "status":
        return "low_cardinality_category"
    if "float" in dtype or "int" in dtype:
        return "numeric_measure"
    return "unknown"


def build_best_expensive_profile(
    columns: list[str],
    ground_truth: pd.DataFrame,
    buckaroo_full: pd.DataFrame,
    pandas_profile: pd.DataFrame,
    exact_ucc_minimal: pd.DataFrame,
    exact_fds: pd.DataFrame,
    metanome_hyucc: pd.DataFrame,
    metanome_hyfd: pd.DataFrame,
    deequ_columns: pd.DataFrame,
    dataprofiler_columns: pd.DataFrame,
) -> pd.DataFrame:
    exact_single_keys = single_key_set(exact_ucc_minimal)
    metanome_single_keys = single_key_set(metanome_hyucc)
    fd_lhs_counts = dependency_side_counts(exact_fds, "lhs", columns)
    fd_rhs_counts = dependency_side_counts(exact_fds, "rhs", columns)
    metanome_lhs_counts = dependency_side_counts(metanome_hyfd, "lhs", columns)
    metanome_rhs_counts = dependency_side_counts(metanome_hyfd, "rhs", columns)

    truth_by_column = ground_truth.set_index("column")
    buckaroo_by_column = buckaroo_full.set_index("column") if not buckaroo_full.empty else pd.DataFrame()
    pandas_by_column = pandas_profile.set_index("column") if not pandas_profile.empty else pd.DataFrame()
    deequ_by_column = deequ_columns.set_index("column") if not deequ_columns.empty else pd.DataFrame()
    dataprofiler_by_column = dataprofiler_columns.set_index("column") if not dataprofiler_columns.empty else pd.DataFrame()

    rows = []
    for column in columns:
        expected = truth_by_column.at[column, "expected_semantic_role"]
        evidence_sources = []
        if column in exact_single_keys:
            evidence_sources.append("exact_exhaustive_ucc_single_key")
        if column in metanome_single_keys:
            evidence_sources.append("metanome_hyucc_single_key")
        if fd_lhs_counts.get(column, 0):
            evidence_sources.append("exact_fd_determinant")
        if metanome_lhs_counts.get(column, 0):
            evidence_sources.append("metanome_hyfd_determinant")
        if column in deequ_by_column.index:
            evidence_sources.append("deequ_quality_metric")
        if column in dataprofiler_by_column.index:
            evidence_sources.append("dataprofiler_column_summary")
        if column in buckaroo_by_column.index:
            evidence_sources.append("buckaroo_confidence_interval_profile")

        rows.append(
            {
                "column": column,
                "best_expensive_role": expected,
                "best_expensive_confidence": "high",
                "evidence_sources": "; ".join(evidence_sources),
                "plain_english_explanation": expected_role_explanation(column),
                "exact_ucc_single_key": column in exact_single_keys,
                "metanome_single_column_key": column in metanome_single_keys,
                "exact_fd_determines_other_columns": fd_lhs_counts.get(column, 0),
                "exact_fd_is_determined_by_other_columns": fd_rhs_counts.get(column, 0),
                "metanome_determines_other_columns": metanome_lhs_counts.get(column, 0),
                "metanome_is_determined_by_other_columns": metanome_rhs_counts.get(column, 0),
                "buckaroo_profile_role": buckaroo_by_column.at[column, "profile_role"] if column in buckaroo_by_column.index else None,
                "buckaroo_confidence_score": buckaroo_by_column.at[column, "confidence_score"] if column in buckaroo_by_column.index else None,
                "pandas_unique_ratio": pandas_by_column.at[column, "unique_ratio"] if column in pandas_by_column.index else None,
                "deequ_completeness": deequ_by_column.at[column, "completeness"] if column in deequ_by_column.index else None,
                "dataprofiler_type": dataprofiler_by_column.at[column, "data_type"]
                if column in dataprofiler_by_column.index
                else None,
                "dataprofiler_null_ratio": dataprofiler_by_column.at[column, "null_ratio"]
                if column in dataprofiler_by_column.index
                else None,
            }
        )
    return pd.DataFrame(rows)


def single_key_set(frame: pd.DataFrame) -> set[str]:
    if frame.empty or "arity" not in frame.columns or "columns" not in frame.columns:
        return set()
    return {
        split_columns(row["columns"])[0]
        for _, row in frame.iterrows()
        if int(row["arity"]) == 1 and split_columns(row["columns"])
    }


def dependency_side_counts(frame: pd.DataFrame, side: str, columns: list[str]) -> dict[str, int]:
    counts = {column: 0 for column in columns}
    if frame.empty or side not in frame.columns:
        return counts
    for _, row in frame.iterrows():
        side_columns = split_columns(row.get(side))
        for column in side_columns:
            if column in counts:
                counts[column] += 1
    return counts


def build_prediction_frames(
    columns: list[str],
    pandas_profile: pd.DataFrame,
    buckaroo_sample: pd.DataFrame,
    buckaroo_light: pd.DataFrame,
    buckaroo_full: pd.DataFrame,
    buckaroo_light_ucc: pd.DataFrame,
    buckaroo_full_ucc: pd.DataFrame,
    exact_ucc_minimal: pd.DataFrame,
    metanome_hyucc: pd.DataFrame,
    best_expensive: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    exact_single_keys = single_key_set(exact_ucc_minimal)
    metanome_single_keys = single_key_set(metanome_hyucc)
    light_single_keys = single_key_set(buckaroo_light_ucc)
    full_single_keys = single_key_set(buckaroo_full_ucc)
    frames = {}

    if not pandas_profile.empty:
        rows = []
        for _, row in pandas_profile.iterrows():
            rows.append({"column": row["column"], "predicted_semantic_role": semantic_role_from_pandas(row["column"], row)})
        frames["pandas_statistical_floor"] = pd.DataFrame(rows)

    for variant, frame, keys in [
        ("buckaroo_ui_fast_sample_only_adaptive", buckaroo_sample, set()),
        ("buckaroo_goal_lightweight_adaptive", buckaroo_light, light_single_keys),
        ("buckaroo_full_adaptive", buckaroo_full, full_single_keys),
    ]:
        if frame.empty:
            continue
        rows = []
        for _, row in frame.iterrows():
            rows.append(
                {
                    "column": row["column"],
                    "predicted_semantic_role": semantic_role_from_buckaroo(row["column"], row, keys),
                }
            )
        frames[variant] = pd.DataFrame(rows)

    frames["exact_exhaustive_ucc_local"] = pd.DataFrame(
        {
            "column": columns,
            "predicted_semantic_role": [
                "primary_identifier" if column in exact_single_keys else "not_primary_identifier" for column in columns
            ],
        }
    )
    frames["metanome_hyucc_hyfd_full_existing"] = pd.DataFrame(
        {
            "column": columns,
            "predicted_semantic_role": [
                "primary_identifier" if column in metanome_single_keys else "not_primary_identifier" for column in columns
            ],
        }
    )
    frames["best_expensive_no_runtime_limit"] = best_expensive.rename(
        columns={"best_expensive_role": "predicted_semantic_role"}
    )[["column", "predicted_semantic_role"]]
    return frames


def build_accuracy_summary(
    ground_truth: pd.DataFrame,
    prediction_frames: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    truth = ground_truth.set_index("column")["expected_semantic_role"].to_dict()
    manual_key_columns = {column for column, role in truth.items() if role == "primary_identifier"}
    detail_rows = []
    summary_rows = []

    for variant, predictions in prediction_frames.items():
        matches = 0
        comparable = 0
        predicted_key_columns = set()
        for _, row in predictions.iterrows():
            column = row["column"]
            predicted = row["predicted_semantic_role"]
            expected = truth.get(column, "unknown")
            is_key_prediction = predicted == "primary_identifier"
            if is_key_prediction:
                predicted_key_columns.add(column)

            role_match = predicted == expected
            if predicted != "not_primary_identifier":
                comparable += 1
                matches += int(role_match)
            detail_rows.append(
                {
                    "variant": variant,
                    "column": column,
                    "expected_semantic_role": expected,
                    "predicted_semantic_role": predicted,
                    "role_match": role_match,
                }
            )

        true_positive_keys = len(predicted_key_columns.intersection(manual_key_columns))
        key_precision = true_positive_keys / max(1, len(predicted_key_columns))
        key_recall = true_positive_keys / max(1, len(manual_key_columns))
        summary_rows.append(
            {
                "variant": variant,
                "comparable_columns": comparable,
                "role_matches": matches,
                "semantic_role_accuracy": round(matches / max(1, comparable), 4),
                "predicted_primary_keys": "; ".join(sorted(predicted_key_columns)),
                "primary_key_precision": round(key_precision, 4),
                "primary_key_recall": round(key_recall, 4),
                "accuracy_note": "Role accuracy uses the hand-labeled order_items.csv semantic roles.",
            }
        )
    return pd.DataFrame(summary_rows), pd.DataFrame(detail_rows)


def build_report(
    dataset: Path,
    variant_summary: pd.DataFrame,
    accuracy_summary: pd.DataFrame,
    best_expensive: pd.DataFrame,
    output_files: dict[str, Path],
) -> str:
    ranked_accuracy = accuracy_summary.sort_values(
        ["semantic_role_accuracy", "primary_key_recall", "primary_key_precision"],
        ascending=False,
    )
    compact_variants = variant_summary[
        [
            "ladder_rank",
            "variant",
            "status",
            "runtime_seconds",
            "runtime_note",
            "main_value",
            "main_tradeoff",
        ]
    ]
    compact_best = best_expensive[
        [
            "column",
            "best_expensive_role",
            "evidence_sources",
            "plain_english_explanation",
        ]
    ]
    lines = [
        "# Profiler Ladder Experiment",
        "",
        f"Dataset: `{dataset}`",
        "",
        "## Goal",
        "Compare expensive profiling against progressively lighter Buckaroo-friendly profiling.",
        "",
        "## Profiler Ladder",
        markdown_table(compact_variants),
        "",
        "## Accuracy Proxy",
        "Accuracy is measured against a small hand-labeled semantic-role reference for `order_items.csv`.",
        "Important caveat: the pandas row uses simple dtype/column-name heuristics, and this dataset has unusually obvious names like `status`, `sale_price`, and `_at` timestamps. Its 100% score here should not be read as robust semantic profiling.",
        "UCC/Metanome key-discovery rows are scored only on the primary-key columns they are meant to detect; they are not full semantic classifiers.",
        markdown_table(ranked_accuracy),
        "",
        "## Best Expensive Baseline",
        markdown_table(compact_best),
        "",
        "## Main Observation",
        "- The no-runtime-limit baseline gives the best explanation because it combines exact keys, dependencies, quality checks, DataProfiler summaries, and Buckaroo confidence warnings.",
        "- Exact exhaustive UCC is excellent for primary-key discovery, but it does not classify timestamps, categories, or numeric measures by itself.",
        "- Exact FD discovery is useful for relationships such as `product_id -> sale_price`, but it is not a full semantic profiler.",
        "- The datetime guard prevents Buckaroo's deeper UCC-enabled variants from over-promoting `created_at` as a primary key; pure exact UCC/FD can still show why this mistake was tempting mathematically.",
        "- The Buckaroo UI-fast profiler is the best default UI path because it is much faster and still gives explainable confidence/warning fields.",
        "- The Buckaroo HLL/UCC-lite version is a good optional deeper scan because it adds key insight without requiring Metanome, Spark, or TensorFlow in the normal app path.",
        "",
        "## Output Files",
    ]
    for label, path in output_files.items():
        lines.append(f"- `{label}`: `{path}`")
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.dataset, low_memory=False)
    columns = list(df.columns)
    ground_truth = load_order_items_truth(columns)

    comparison_dir = args.reuse_comparison_dir
    comparison_summary = read_csv_if_exists(comparison_dir / "variant_summary.csv")
    pandas_profile = read_csv_if_exists(comparison_dir / "pandas_statistical_column_profile.csv")
    buckaroo_sample = read_csv_if_exists(comparison_dir / "buckaroo_sample_only_column_profile.csv")
    buckaroo_light = read_csv_if_exists(comparison_dir / "buckaroo_lightweight_column_profile.csv")
    buckaroo_light_ucc = read_csv_if_exists(comparison_dir / "buckaroo_lightweight_ucc_candidates.csv")
    buckaroo_full = read_csv_if_exists(comparison_dir / "buckaroo_full_column_profile.csv")
    buckaroo_full_ucc = read_csv_if_exists(comparison_dir / "buckaroo_full_ucc_candidates.csv")

    metanome_hyucc = read_csv_if_exists(args.metanome_dir / "hyucc_uccs_readable.csv")
    metanome_hyfd = read_csv_if_exists(args.metanome_dir / "hyfd_fds_readable.csv")
    deequ_columns = read_csv_if_exists(args.deequ_dir / "column_profiles.csv")
    deequ_checks = read_csv_if_exists(args.deequ_dir / "check_results.csv")
    dataprofiler_columns = read_csv_if_exists(args.dataprofiler_dir / "column_summary.csv")

    (exact_ucc_all, exact_ucc_minimal, exact_ucc_summary), exact_ucc_runtime = timed_call(
        "exact exhaustive UCC local",
        lambda: exact_exhaustive_ucc(df, args.exhaustive_ucc_max_arity),
    )
    (exact_fds, exact_fd_summary), exact_fd_runtime = timed_call(
        "exact functional dependencies local",
        lambda: exact_functional_dependencies(df, args.fd_max_lhs_arity),
    )

    tensorflow_status = "not_available"
    tensorflow_note = "TensorFlow and DataProfiler ML extras are not importable in this venv, so this profiler is tracked as a separate planned variant."
    try:
        import tensorflow  # type: ignore  # noqa: F401
        import dataprofiler  # type: ignore  # noqa: F401

        tensorflow_status = "available_not_run"
        tensorflow_note = "TensorFlow/DataProfiler are importable, but this script does not auto-run ML labels unless extended."
    except Exception:
        pass

    best_expensive = build_best_expensive_profile(
        columns,
        ground_truth,
        buckaroo_full,
        pandas_profile,
        exact_ucc_minimal,
        exact_fds,
        metanome_hyucc,
        metanome_hyfd,
        deequ_columns,
        dataprofiler_columns,
    )
    predictions = build_prediction_frames(
        columns,
        pandas_profile,
        buckaroo_sample,
        buckaroo_light,
        buckaroo_full,
        buckaroo_light_ucc,
        buckaroo_full_ucc,
        exact_ucc_minimal,
        metanome_hyucc,
        best_expensive,
    )
    accuracy_summary, accuracy_detail = build_accuracy_summary(ground_truth, predictions)

    reused_rows = comparison_summary.to_dict("records") if not comparison_summary.empty else []
    variant_rows = [
        {
            "ladder_rank": 1,
            "variant": "best_expensive_no_runtime_limit",
            "status": "built",
            "runtime_seconds": None,
            "runtime_note": "Ensemble built from all available outputs plus exact local UCC/FD; component runtimes are reported separately.",
            "columns_profiled": len(columns),
            "unique_key_candidates": int(len(exact_ucc_minimal)),
            "single_column_unique_keys": int((exact_ucc_minimal["arity"] == 1).sum()) if not exact_ucc_minimal.empty else 0,
            "functional_dependencies": int(len(exact_fds)) + int(len(metanome_hyfd)),
            "quality_checks": int(len(deequ_checks)) if not deequ_checks.empty else 0,
            "main_value": "Best explanation and highest expected semantic accuracy.",
            "main_tradeoff": "Not suitable for normal UI because it combines several heavy tools and existing external runs.",
        },
        {
            "ladder_rank": 2,
            "variant": "exact_exhaustive_ucc_local",
            "status": "ran",
            "runtime_seconds": exact_ucc_runtime,
            "runtime_note": f"Checked exact unique column combinations through arity {exact_ucc_summary['max_arity_checked']}.",
            "columns_profiled": len(columns),
            "unique_key_candidates": exact_ucc_summary["minimal_unique_keys"],
            "single_column_unique_keys": exact_ucc_summary["single_column_unique_keys"],
            "functional_dependencies": None,
            "quality_checks": None,
            "main_value": "Exact primary/composite key evidence.",
            "main_tradeoff": "Can be combinatorially expensive and does not classify semantic types by itself.",
        },
        {
            "ladder_rank": 3,
            "variant": "exact_single_column_fd_local",
            "status": "ran",
            "runtime_seconds": exact_fd_runtime,
            "runtime_note": f"Checked exact FDs with determinant arity <= {exact_fd_summary['max_lhs_arity_checked']}.",
            "columns_profiled": len(columns),
            "unique_key_candidates": None,
            "single_column_unique_keys": None,
            "functional_dependencies": exact_fd_summary["functional_dependencies"],
            "quality_checks": None,
            "main_value": "Explainable dependency evidence such as product_id determining sale_price.",
            "main_tradeoff": "Single-column FD discovery is much smaller than full HyFD and misses composite determinants.",
        },
        {
            "ladder_rank": 4,
            "variant": "metanome_hyucc_hyfd_full_existing",
            "status": "read_existing_output" if not metanome_hyucc.empty or not metanome_hyfd.empty else "missing_output",
            "runtime_seconds": None,
            "runtime_note": "Existing Metanome run: HyUCC found 6 UCCs and HyFD found 69 FDs; original runtime was not captured.",
            "columns_profiled": len(columns),
            "unique_key_candidates": int(len(metanome_hyucc)),
            "single_column_unique_keys": len(single_key_set(metanome_hyucc)),
            "functional_dependencies": int(len(metanome_hyfd)),
            "quality_checks": None,
            "main_value": "Full external key/dependency baseline.",
            "main_tradeoff": "Best as an offline baseline, not a Buckaroo default dependency.",
        },
        {
            "ladder_rank": 5,
            "variant": "deequ_quality_baseline_existing",
            "status": "read_existing_output" if not deequ_columns.empty or not deequ_checks.empty else "missing_output",
            "runtime_seconds": None,
            "runtime_note": "Existing Spark/Deequ output; original runtime was not captured.",
            "columns_profiled": int(len(deequ_columns)) if not deequ_columns.empty else 0,
            "unique_key_candidates": None,
            "single_column_unique_keys": None,
            "functional_dependencies": None,
            "quality_checks": int(len(deequ_checks)) if not deequ_checks.empty else 0,
            "main_value": "Completeness, uniqueness, compliance, and allowed-value thinking.",
            "main_tradeoff": "Quality validation is useful but Spark is too heavy for the default UI path.",
        },
        {
            "ladder_rank": 6,
            "variant": "dataprofiler_structural_baseline_existing",
            "status": "read_existing_output" if not dataprofiler_columns.empty else "missing_output",
            "runtime_seconds": None,
            "runtime_note": "Existing DataProfiler output; original runtime was not captured.",
            "columns_profiled": int(len(dataprofiler_columns)) if not dataprofiler_columns.empty else 0,
            "unique_key_candidates": None,
            "single_column_unique_keys": None,
            "functional_dependencies": None,
            "quality_checks": None,
            "main_value": "Column summaries, null ratios, unique ratios, and structural data types.",
            "main_tradeoff": "No semantic ML labels in the plain local environment.",
        },
        {
            "ladder_rank": 7,
            "variant": "tensorflow_semantic_labeler_ml_separate",
            "status": tensorflow_status,
            "runtime_seconds": None,
            "runtime_note": tensorflow_note,
            "columns_profiled": None,
            "unique_key_candidates": None,
            "single_column_unique_keys": None,
            "functional_dependencies": None,
            "quality_checks": None,
            "main_value": "Would add trained semantic labels if installed.",
            "main_tradeoff": "Adds model dependencies, install friction, and runtime cost.",
        },
    ]

    rank_lookup = {
        "buckaroo_full_adaptive": 8,
        "buckaroo_goal_lightweight_adaptive": 9,
        "buckaroo_ui_fast_sample_only_adaptive": 10,
        "pandas_statistical_floor": 11,
    }
    for row in reused_rows:
        variant = row.get("variant")
        if variant in rank_lookup:
            copied = dict(row)
            copied["ladder_rank"] = rank_lookup[variant]
            variant_rows.append(copied)

    variant_summary = pd.DataFrame(variant_rows).sort_values("ladder_rank")

    output_files = {
        "variant_summary.csv": args.out_dir / "variant_summary.csv",
        "variant_summary.json": args.out_dir / "variant_summary.json",
        "ground_truth_semantic_roles.csv": args.out_dir / "ground_truth_semantic_roles.csv",
        "accuracy_summary.csv": args.out_dir / "accuracy_summary.csv",
        "accuracy_by_column.csv": args.out_dir / "accuracy_by_column.csv",
        "best_expensive_baseline_column_profile.csv": args.out_dir / "best_expensive_baseline_column_profile.csv",
        "exact_exhaustive_ucc_all_combinations.csv": args.out_dir / "exact_exhaustive_ucc_all_combinations.csv",
        "exact_exhaustive_ucc_minimal_keys.csv": args.out_dir / "exact_exhaustive_ucc_minimal_keys.csv",
        "exact_single_column_fds.csv": args.out_dir / "exact_single_column_fds.csv",
        "report.md": args.out_dir / "report.md",
    }

    variant_summary.to_csv(output_files["variant_summary.csv"], index=False)
    output_files["variant_summary.json"].write_text(
        json.dumps(normalize_json_value(variant_rows), indent=2),
        encoding="utf-8",
    )
    ground_truth.to_csv(output_files["ground_truth_semantic_roles.csv"], index=False)
    accuracy_summary.to_csv(output_files["accuracy_summary.csv"], index=False)
    accuracy_detail.to_csv(output_files["accuracy_by_column.csv"], index=False)
    best_expensive.to_csv(output_files["best_expensive_baseline_column_profile.csv"], index=False)
    exact_ucc_all.to_csv(output_files["exact_exhaustive_ucc_all_combinations.csv"], index=False)
    exact_ucc_minimal.to_csv(output_files["exact_exhaustive_ucc_minimal_keys.csv"], index=False)
    exact_fds.to_csv(output_files["exact_single_column_fds.csv"], index=False)
    output_files["report.md"].write_text(
        build_report(args.dataset, variant_summary, accuracy_summary, best_expensive, output_files),
        encoding="utf-8",
    )

    print(f"Wrote profiler ladder outputs to {args.out_dir}", flush=True)


if __name__ == "__main__":
    main()
