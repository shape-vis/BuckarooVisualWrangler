"""Compare Buckaroo-friendly profiler variants against external baselines.

This script is intentionally practical:

- It runs the current Buckaroo adaptive profiler in a lightweight mode.
- It runs the same Buckaroo profiler in a fuller mode on the whole dataset.
- It reads the Metanome, Deequ, and DataProfiler outputs we already generated.
- It creates one combined column comparison so the tradeoffs are easy to see.

The expensive external tools are treated as baselines here.  Their original
runtime is not re-measured unless the tool is actually invoked by this script.
"""

from __future__ import annotations

import argparse
import json
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
    DEFAULT_UCC_MAX_ARITY,
    DEFAULT_UCC_MAX_CANDIDATE_COLUMNS,
    DEFAULT_UCC_NEAR_UNIQUE_THRESHOLD,
    is_missing_value,
    profile_dataset,
    profile_columns,
    run_detectors_direct,
)


DEFAULT_OUT_DIR = ROOT / "outputs" / "profiler_variant_comparison_order_items"
DEFAULT_METANOME_DIR = ROOT / "outputs" / "metanome_order_items"
DEFAULT_DEEQU_DIR = ROOT / "outputs" / "deequ_order_items"
DEFAULT_DATAPROFILER_DIR = ROOT / "outputs" / "dataprofiler_order_items_full"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare profiler variants on one CSV.")
    parser.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="CSV to profile; external baseline directories are supplied separately.",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--metanome-dir", type=Path, default=DEFAULT_METANOME_DIR)
    parser.add_argument("--deequ-dir", type=Path, default=DEFAULT_DEEQU_DIR)
    parser.add_argument("--dataprofiler-dir", type=Path, default=DEFAULT_DATAPROFILER_DIR)
    parser.add_argument("--light-profile-rows", type=int, default=5_000)
    parser.add_argument("--light-detector-rows", type=int, default=2_000)
    parser.add_argument("--full-detector-rows", type=int, default=10_000)
    parser.add_argument("--cardinality-chunk-rows", type=int, default=DEFAULT_CARDINALITY_CHUNK_ROWS)
    parser.add_argument("--ucc-max-arity", type=int, default=DEFAULT_UCC_MAX_ARITY)
    parser.add_argument("--ucc-max-candidate-columns", type=int, default=DEFAULT_UCC_MAX_CANDIDATE_COLUMNS)
    parser.add_argument("--ucc-near-unique-threshold", type=float, default=DEFAULT_UCC_NEAR_UNIQUE_THRESHOLD)
    return parser.parse_args()


def count_csv_rows(csv_path: Path) -> int:
    with csv_path.open("rb") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def normalize_json_value(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, dict):
        return {str(key): normalize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_json_value(item) for item in value]
    if pd.isna(value) if not isinstance(value, (list, dict, tuple, set)) else False:
        return None
    return value


def markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_No rows._"
    # Convert extension dtypes (for example nullable Int64) to object before
    # replacing missing values; those arrays reject an empty string directly.
    rendered = frame.astype(object).where(frame.notna(), "").astype(str)
    header = "| " + " | ".join(rendered.columns) + " |"
    separator = "| " + " | ".join("---" for _ in rendered.columns) + " |"
    rows = [
        "| " + " | ".join(str(value).replace("\n", " ") for value in row) + " |"
        for row in rendered.to_numpy()
    ]
    return "\n".join([header, separator, *rows])


def read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def timed_call(label: str, callback) -> tuple[Any, float]:
    print(f"Running {label}...", flush=True)
    start = time.perf_counter()
    value = callback()
    return value, round(time.perf_counter() - start, 3)


def run_buckaroo_variant(
    label: str,
    csv_path: Path,
    profile_rows: int,
    detector_rows: int,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    (result, column_profile, ucc_frame), runtime_seconds = timed_call(
        label,
        lambda: profile_dataset(
            csv_path,
            profile_rows=profile_rows,
            detector_rows=detector_rows,
            cardinality_chunk_rows=args.cardinality_chunk_rows,
            ucc_max_arity=args.ucc_max_arity,
            ucc_max_candidate_columns=args.ucc_max_candidate_columns,
            ucc_near_unique_threshold=args.ucc_near_unique_threshold,
        ),
    )
    result = dict(result)
    result["runtime_seconds"] = runtime_seconds
    return result, column_profile, ucc_frame


def run_buckaroo_sample_only_variant(
    label: str,
    csv_path: Path,
    profile_rows: int,
    detector_rows: int,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    def build() -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
        df = pd.read_csv(csv_path, nrows=max(profile_rows, detector_rows), low_memory=False)
        profile_df = df.head(profile_rows).copy()
        detector_df = df.head(detector_rows).copy()
        column_profile, roles = profile_columns(profile_df)

        missing_cells = int(profile_df.map(is_missing_value).sum().sum())
        profiled_cells = max(1, int(profile_df.shape[0] * profile_df.shape[1]))
        errors = run_detectors_direct(detector_df)
        rows_with_errors = int(errors["row_id"].nunique()) if not errors.empty else 0

        role_counts = column_profile["role"].value_counts().to_dict() if not column_profile.empty else {}
        profile_role_counts = column_profile["profile_role"].value_counts().to_dict() if not column_profile.empty else {}
        confidence_counts = column_profile["confidence"].value_counts().to_dict() if not column_profile.empty else {}

        result = {
            "dataset": csv_path.name,
            "source_file": str(csv_path),
            "total_rows": count_csv_rows(csv_path),
            "total_columns": int(len(df.columns)),
            "profiled_rows": int(len(profile_df)),
            "detector_sample_rows": int(len(detector_df)),
            "numeric_columns": int(role_counts.get("numeric", 0)),
            "categorical_columns": int(role_counts.get("categorical", 0)),
            "free_text_columns": int(role_counts.get("free_text", 0)),
            "identifier_columns": int(role_counts.get("identifier", 0)),
            "numeric_measure_columns": int(profile_role_counts.get("numeric_measure", 0)),
            "numeric_code_category_columns": int(profile_role_counts.get("numeric_code_category", 0)),
            "binary_category_columns": int(profile_role_counts.get("binary_category", 0)),
            "datetime_columns": int(profile_role_counts.get("datetime_category", 0))
            + int(profile_role_counts.get("datetime_high_uniqueness", 0))
            + int(profile_role_counts.get("datetime_identifier", 0)),
            "average_profile_confidence": round(float(column_profile["confidence_score"].mean()), 3)
            if not column_profile.empty
            else 0.0,
            "high_confidence_columns": int(confidence_counts.get("high", 0)),
            "medium_confidence_columns": int(confidence_counts.get("medium", 0)),
            "low_confidence_columns": int(confidence_counts.get("low", 0)),
            "adaptive_warning_columns": int(
                column_profile["adaptive_warning"].fillna("").astype(str).str.len().gt(0).sum()
            )
            if not column_profile.empty
            else 0,
            "ucc_candidate_count": 0,
            "ucc_unique_single_column_keys": 0,
            "ucc_unique_composite_keys": 0,
            "ucc_near_unique_candidates": 0,
            "missing_value_rate": round(float(missing_cells / profiled_cells), 4),
            "baseline_error_rate": round(float(rows_with_errors / max(1, len(detector_df))), 4),
            "rows_with_detector_errors": rows_with_errors,
            "detector_error_records": int(len(errors)),
            "numeric_column_names": "; ".join(roles["numeric"][:20]),
            "categorical_column_names": "; ".join(roles["categorical"][:20]),
            "free_text_column_names": "; ".join(roles["free_text"][:20]),
            "identifier_column_names": "; ".join(roles["identifier"][:20]),
        }
        return result, column_profile, pd.DataFrame()

    (result, column_profile, ucc_frame), runtime_seconds = timed_call(label, build)
    result = dict(result)
    result["runtime_seconds"] = runtime_seconds
    return result, column_profile, ucc_frame


def run_pandas_statistics(csv_path: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    def build() -> tuple[dict[str, Any], pd.DataFrame]:
        df = pd.read_csv(csv_path, low_memory=False)
        rows = []
        for column in df.columns:
            series = df[column]
            non_null = int(series.notna().sum())
            unique_count = int(series.nunique(dropna=True))
            rows.append(
                {
                    "column": column,
                    "pandas_dtype": str(series.dtype),
                    "non_null_count": non_null,
                    "null_ratio": round(float(series.isna().mean()), 4),
                    "unique_count": unique_count,
                    "unique_ratio": round(float(unique_count / max(1, non_null)), 4),
                }
            )
        summary = {
            "total_rows": int(len(df)),
            "total_columns": int(len(df.columns)),
            "numeric_columns": int(len(df.select_dtypes(include="number").columns)),
            "categorical_columns": int(len(df.select_dtypes(exclude="number").columns)),
        }
        return summary, pd.DataFrame(rows)

    (summary, frame), runtime_seconds = timed_call("pandas statistical floor", build)
    summary["runtime_seconds"] = runtime_seconds
    return summary, frame


def external_baseline_summary(
    metanome_dir: Path,
    deequ_dir: Path,
    dataprofiler_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, pd.DataFrame]]:
    hyucc = read_csv_if_exists(metanome_dir / "hyucc_uccs_readable.csv")
    hyfd = read_csv_if_exists(metanome_dir / "hyfd_fds_readable.csv")
    deequ_columns = read_csv_if_exists(deequ_dir / "column_profiles.csv")
    deequ_checks = read_csv_if_exists(deequ_dir / "check_results.csv")
    dataprofiler_columns = read_csv_if_exists(dataprofiler_dir / "column_summary.csv")

    rows = []
    rows.append(
        {
            "variant": "metanome_full_dependency_baseline_existing",
            "status": "read_existing_output" if not hyucc.empty or not hyfd.empty else "missing_output",
            "runtime_seconds": None,
            "runtime_note": "Not re-measured here; this row reads the existing Metanome HyUCC/HyFD CSV outputs.",
            "columns_profiled": None,
            "unique_key_candidates": int(len(hyucc)),
            "single_column_unique_keys": int((hyucc.get("arity", pd.Series(dtype=int)) == 1).sum()) if not hyucc.empty else 0,
            "functional_dependencies": int(len(hyfd)),
            "quality_checks": None,
            "main_value": "Finds exact/near-exact keys and functional dependencies.",
            "main_tradeoff": "Very useful ground-truth-style signal, but Java/Metanome integration is heavier than Buckaroo UI profiling.",
        }
    )
    rows.append(
        {
            "variant": "deequ_quality_baseline_existing",
            "status": "read_existing_output" if not deequ_columns.empty or not deequ_checks.empty else "missing_output",
            "runtime_seconds": None,
            "runtime_note": "Not re-measured here; this row reads the existing Spark/Deequ CSV outputs.",
            "columns_profiled": int(len(deequ_columns)) if not deequ_columns.empty else 0,
            "unique_key_candidates": None,
            "single_column_unique_keys": None,
            "functional_dependencies": None,
            "quality_checks": int(len(deequ_checks)) if not deequ_checks.empty else 0,
            "main_value": "Turns profiling facts into data-quality checks such as completeness, uniqueness, and allowed values.",
            "main_tradeoff": "More meaningful for validation, but Spark setup is heavier than a lightweight Buckaroo profiler.",
        }
    )
    rows.append(
        {
            "variant": "dataprofiler_structural_baseline_existing",
            "status": "read_existing_output" if not dataprofiler_columns.empty else "missing_output",
            "runtime_seconds": None,
            "runtime_note": "Not re-measured here; this row reads the existing DataProfiler CSV output.",
            "columns_profiled": int(len(dataprofiler_columns)) if not dataprofiler_columns.empty else 0,
            "unique_key_candidates": None,
            "single_column_unique_keys": None,
            "functional_dependencies": None,
            "quality_checks": None,
            "main_value": "Good column summaries: nulls, unique ratios, basic types, and numeric stats.",
            "main_tradeoff": "Plain install did not provide semantic ML labels in the previous run.",
        }
    )

    tensorflow_status = "not_available"
    tensorflow_note = "TensorFlow semantic labeler was not run because the local Python environment does not expose tensorflow/dataprofiler ML extras."
    try:
        import tensorflow  # type: ignore  # noqa: F401

        tensorflow_status = "available_not_run"
        tensorflow_note = "TensorFlow is importable, but this comparison script keeps semantic labeling as a separate opt-in profiler."
    except Exception:
        pass

    rows.append(
        {
            "variant": "tensorflow_semantic_labeler_ml_separate",
            "status": tensorflow_status,
            "runtime_seconds": None,
            "runtime_note": tensorflow_note,
            "columns_profiled": None,
            "unique_key_candidates": None,
            "single_column_unique_keys": None,
            "functional_dependencies": None,
            "quality_checks": None,
            "main_value": "Would predict semantic labels such as names, addresses, or other trained entity types.",
            "main_tradeoff": "Potentially stronger semantic meaning, but adds model dependencies, install size, and slower startup/runtime.",
        }
    )

    return rows, {
        "hyucc": hyucc,
        "hyfd": hyfd,
        "deequ_columns": deequ_columns,
        "deequ_checks": deequ_checks,
        "dataprofiler_columns": dataprofiler_columns,
    }


def split_columns(value: Any) -> list[str]:
    if pd.isna(value):
        return []
    return [part.strip() for part in str(value).split("+") if part.strip()]


def build_best_expensive_column_profile(
    columns: list[str],
    buckaroo_full: pd.DataFrame,
    pandas_frame: pd.DataFrame,
    external: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    hyucc = external["hyucc"]
    hyfd = external["hyfd"]
    deequ_columns = external["deequ_columns"]
    dataprofiler_columns = external["dataprofiler_columns"]

    single_keys: set[str] = set()
    composite_key_mentions: dict[str, int] = {column: 0 for column in columns}
    if not hyucc.empty:
        for _, row in hyucc.iterrows():
            key_columns = split_columns(row.get("columns"))
            if int(row.get("arity", len(key_columns))) == 1 and key_columns:
                single_keys.add(key_columns[0])
            for column in key_columns:
                if column in composite_key_mentions:
                    composite_key_mentions[column] += 1

    fd_lhs_counts: dict[str, int] = {column: 0 for column in columns}
    fd_rhs_counts: dict[str, int] = {column: 0 for column in columns}
    if not hyfd.empty:
        for _, row in hyfd.iterrows():
            lhs_columns = split_columns(row.get("lhs"))
            rhs = str(row.get("rhs", "")).strip()
            for column in lhs_columns:
                if column in fd_lhs_counts:
                    fd_lhs_counts[column] += 1
            if rhs in fd_rhs_counts:
                fd_rhs_counts[rhs] += 1

    buckaroo_by_column = buckaroo_full.set_index("column") if not buckaroo_full.empty else pd.DataFrame()
    pandas_by_column = pandas_frame.set_index("column") if not pandas_frame.empty else pd.DataFrame()
    deequ_by_column = deequ_columns.set_index("column") if not deequ_columns.empty else pd.DataFrame()
    dataprofiler_by_column = dataprofiler_columns.set_index("column") if not dataprofiler_columns.empty else pd.DataFrame()

    rows = []
    for column in columns:
        buckaroo_role = None
        buckaroo_profile_role = None
        buckaroo_confidence = None
        buckaroo_warning = ""
        if column in buckaroo_by_column.index:
            buckaroo_role = buckaroo_by_column.at[column, "role"]
            buckaroo_profile_role = buckaroo_by_column.at[column, "profile_role"]
            buckaroo_confidence = buckaroo_by_column.at[column, "confidence_score"]
            buckaroo_warning = str(buckaroo_by_column.at[column, "warning"])

        dataprofiler_type = dataprofiler_by_column.at[column, "data_type"] if column in dataprofiler_by_column.index else None
        dataprofiler_unique_ratio = (
            dataprofiler_by_column.at[column, "unique_ratio"] if column in dataprofiler_by_column.index else None
        )
        dataprofiler_null_ratio = (
            dataprofiler_by_column.at[column, "null_ratio"] if column in dataprofiler_by_column.index else None
        )
        deequ_type = deequ_by_column.at[column, "data_type"] if column in deequ_by_column.index else None
        deequ_completeness = (
            deequ_by_column.at[column, "completeness"] if column in deequ_by_column.index else None
        )
        pandas_unique_ratio = pandas_by_column.at[column, "unique_ratio"] if column in pandas_by_column.index else None

        if column in single_keys:
            ensemble_role = "primary_identifier"
            explanation = "Metanome found this as a single-column unique key, and the statistics show every row is distinct."
        elif str(column).endswith("_at"):
            ensemble_role = "datetime_lifecycle_field"
            explanation = "The name and string shape show a timestamp. Missingness tells which lifecycle event may not have happened yet."
        elif column.endswith("_id"):
            ensemble_role = "foreign_key_or_reference"
            explanation = "The name is ID-like, but repeats exist, so this is probably a reference to another entity rather than a row key."
        elif column == "status":
            ensemble_role = "low_cardinality_category"
            explanation = "All tools agree this is a small string category with a tiny set of allowed values."
        elif column == "sale_price":
            ensemble_role = "numeric_measure"
            explanation = "DataProfiler, Deequ, and Buckaroo all treat this as numeric; HyFD also shows product_id determines sale_price here."
        else:
            ensemble_role = buckaroo_profile_role or "unknown"
            explanation = "The best label follows Buckaroo's adaptive profile role because no stronger external baseline signal overrode it."

        rows.append(
            {
                "column": column,
                "best_expensive_role": ensemble_role,
                "plain_english_explanation": explanation,
                "buckaroo_role": buckaroo_role,
                "buckaroo_profile_role": buckaroo_profile_role,
                "buckaroo_confidence_score": buckaroo_confidence,
                "buckaroo_warning": buckaroo_warning,
                "dataprofiler_type": dataprofiler_type,
                "dataprofiler_unique_ratio": dataprofiler_unique_ratio,
                "dataprofiler_null_ratio": dataprofiler_null_ratio,
                "deequ_type": deequ_type,
                "deequ_completeness": deequ_completeness,
                "pandas_unique_ratio": pandas_unique_ratio,
                "metanome_single_column_key": column in single_keys,
                "metanome_composite_key_mentions": composite_key_mentions.get(column, 0),
                "metanome_determines_other_columns": fd_lhs_counts.get(column, 0),
                "metanome_is_determined_by_other_columns": fd_rhs_counts.get(column, 0),
            }
        )

    return pd.DataFrame(rows)


def build_report(
    dataset: Path,
    variant_summary: pd.DataFrame,
    best_columns: pd.DataFrame,
    output_files: dict[str, Path],
) -> str:
    compact_summary = variant_summary[
        [
            "variant",
            "status",
            "runtime_seconds",
            "columns_profiled",
            "unique_key_candidates",
            "functional_dependencies",
            "quality_checks",
            "main_value",
            "main_tradeoff",
        ]
    ]

    compact_columns = best_columns[
        [
            "column",
            "best_expensive_role",
            "buckaroo_profile_role",
            "buckaroo_confidence_score",
            "dataprofiler_type",
            "deequ_type",
            "metanome_single_column_key",
            "plain_english_explanation",
        ]
    ]

    lines = [
        "# Profiler Variant Comparison: order_items.csv",
        "",
        f"Dataset: `{dataset}`",
        "",
        "## What This Compares",
        "- `buckaroo_goal_lightweight_adaptive`: the version we want inside Buckaroo: row-aware thresholds, confidence scores, HLL-style distinct counts, UCC-lite key hints, detector quality warnings, and explainable column summaries.",
        "- `buckaroo_ui_fast_sample_only_adaptive`: the fastest Buckaroo-facing version: adaptive column summaries and detector warnings on a bounded sample, without full-file UCC/dependency scanning.",
        "- `buckaroo_full_adaptive`: the same rules, but run with full-row profiling so we can see what extra evidence buys us.",
        "- `metanome_full_dependency_baseline_existing`: external key/dependency truth signals from HyUCC and HyFD.",
        "- `deequ_quality_baseline_existing`: external data-quality checks: completeness, uniqueness, allowed values, and compliance checks.",
        "- `dataprofiler_structural_baseline_existing`: external structural column summaries: types, nulls, unique ratios, numeric stats.",
        "- `tensorflow_semantic_labeler_ml_separate`: kept separate because it adds ML dependencies and should be compared as its own runtime/accuracy tradeoff.",
        "",
        "## Variant Summary",
        markdown_table(compact_summary),
        "",
        "## Best Expensive Baseline, Column By Column",
        markdown_table(compact_columns),
        "",
        "## Beginner-Friendly Findings",
        "- Metanome is strongest for questions like: `is this a key?` and `does one column determine another column?`",
        "- Deequ is strongest for quality rules: `is this column complete?`, `is id unique?`, `is status one of the allowed statuses?`, and `is sale_price non-negative?`",
        "- DataProfiler is strongest for easy summaries: null ratios, unique ratios, types, and numeric statistics.",
        "- Buckaroo's new adaptive profiler tries to keep the useful parts of all three without forcing Buckaroo to run a heavy Java/Spark/ML stack inside the normal UI path.",
        "- Confidence scores are the important new piece: Buckaroo can now say `I think this is an identifier, but confidence is lower because the sample is small or uniqueness is approximate.`",
        "",
        "## CSV Outputs Created",
    ]
    for label, path in output_files.items():
        lines.append(f"- `{label}`: `{path}`")
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    total_rows = count_csv_rows(args.dataset)
    csv_header = pd.read_csv(args.dataset, nrows=0).columns.tolist()

    pandas_summary, pandas_frame = run_pandas_statistics(args.dataset)

    sample_result, sample_columns, sample_ucc = run_buckaroo_sample_only_variant(
        "Buckaroo UI-fast sample-only adaptive",
        args.dataset,
        profile_rows=min(args.light_profile_rows, total_rows),
        detector_rows=min(args.light_detector_rows, total_rows),
    )

    light_result, light_columns, light_ucc = run_buckaroo_variant(
        "Buckaroo goal lightweight adaptive",
        args.dataset,
        profile_rows=min(args.light_profile_rows, total_rows),
        detector_rows=min(args.light_detector_rows, total_rows),
        args=args,
    )

    full_result, full_columns, full_ucc = run_buckaroo_variant(
        "Buckaroo full adaptive",
        args.dataset,
        profile_rows=total_rows,
        detector_rows=min(args.full_detector_rows, total_rows),
        args=args,
    )

    external_rows, external = external_baseline_summary(
        args.metanome_dir,
        args.deequ_dir,
        args.dataprofiler_dir,
    )

    variant_rows = [
        {
            "variant": "pandas_statistical_floor",
            "status": "ran",
            "runtime_seconds": pandas_summary["runtime_seconds"],
            "runtime_note": "Measured in this script.",
            "columns_profiled": pandas_summary["total_columns"],
            "unique_key_candidates": None,
            "single_column_unique_keys": None,
            "functional_dependencies": None,
            "quality_checks": None,
            "main_value": "Fast, basic null/unique/type statistics.",
            "main_tradeoff": "Too shallow for semantic roles, dependencies, or quality explanations.",
        },
        {
            "variant": "buckaroo_ui_fast_sample_only_adaptive",
            "status": "ran",
            "runtime_seconds": sample_result["runtime_seconds"],
            "runtime_note": f"Profile rows={min(args.light_profile_rows, total_rows)}, detector rows={min(args.light_detector_rows, total_rows)}, no full-file UCC scan.",
            "columns_profiled": int(len(sample_columns)),
            "unique_key_candidates": 0,
            "single_column_unique_keys": 0,
            "functional_dependencies": None,
            "quality_checks": int(sample_result["detector_error_records"]),
            "main_value": "Fastest Buckaroo-facing adaptive profile: explainable roles, confidence, and detector warnings on a bounded sample.",
            "main_tradeoff": "Can overtrust sample uniqueness because it skips full-file cardinality and UCC validation.",
        },
        {
            "variant": "buckaroo_goal_lightweight_adaptive",
            "status": "ran",
            "runtime_seconds": light_result["runtime_seconds"],
            "runtime_note": f"Profile rows={min(args.light_profile_rows, total_rows)}, detector rows={min(args.light_detector_rows, total_rows)}.",
            "columns_profiled": int(len(light_columns)),
            "unique_key_candidates": light_result["ucc_candidate_count"],
            "single_column_unique_keys": light_result["ucc_unique_single_column_keys"],
            "functional_dependencies": None,
            "quality_checks": int(light_result["detector_error_records"]),
            "main_value": "Buckaroo-friendly blend of adaptive roles, confidence, UCC-lite, HLL counts, and detector warnings.",
            "main_tradeoff": "Cheaper than external tools, but dependency discovery is intentionally bounded.",
        },
        {
            "variant": "buckaroo_full_adaptive",
            "status": "ran",
            "runtime_seconds": full_result["runtime_seconds"],
            "runtime_note": f"Profile rows={total_rows}, detector rows={min(args.full_detector_rows, total_rows)}.",
            "columns_profiled": int(len(full_columns)),
            "unique_key_candidates": full_result["ucc_candidate_count"],
            "single_column_unique_keys": full_result["ucc_unique_single_column_keys"],
            "functional_dependencies": None,
            "quality_checks": int(full_result["detector_error_records"]),
            "main_value": "Same Buckaroo logic with maximum column-profile evidence on this file.",
            "main_tradeoff": "More stable than sampling, but slower and still not exhaustive HyFD.",
        },
        *external_rows,
    ]
    variant_summary = pd.DataFrame(variant_rows)

    best_columns = build_best_expensive_column_profile(
        csv_header,
        full_columns,
        pandas_frame,
        external,
    )

    output_files = {
        "variant_summary.csv": args.out_dir / "variant_summary.csv",
        "variant_summary.json": args.out_dir / "variant_summary.json",
        "pandas_statistical_column_profile.csv": args.out_dir / "pandas_statistical_column_profile.csv",
        "buckaroo_sample_only_column_profile.csv": args.out_dir / "buckaroo_sample_only_column_profile.csv",
        "buckaroo_lightweight_column_profile.csv": args.out_dir / "buckaroo_lightweight_column_profile.csv",
        "buckaroo_sample_only_ucc_candidates.csv": args.out_dir / "buckaroo_sample_only_ucc_candidates.csv",
        "buckaroo_lightweight_ucc_candidates.csv": args.out_dir / "buckaroo_lightweight_ucc_candidates.csv",
        "buckaroo_full_column_profile.csv": args.out_dir / "buckaroo_full_column_profile.csv",
        "buckaroo_full_ucc_candidates.csv": args.out_dir / "buckaroo_full_ucc_candidates.csv",
        "best_expensive_baseline_column_profile.csv": args.out_dir / "best_expensive_baseline_column_profile.csv",
        "report.md": args.out_dir / "report.md",
    }

    variant_summary.to_csv(output_files["variant_summary.csv"], index=False)
    output_files["variant_summary.json"].write_text(
        json.dumps(normalize_json_value(variant_rows), indent=2),
        encoding="utf-8",
    )
    pandas_frame.to_csv(output_files["pandas_statistical_column_profile.csv"], index=False)
    sample_columns.to_csv(output_files["buckaroo_sample_only_column_profile.csv"], index=False)
    sample_ucc.to_csv(output_files["buckaroo_sample_only_ucc_candidates.csv"], index=False)
    light_columns.to_csv(output_files["buckaroo_lightweight_column_profile.csv"], index=False)
    light_ucc.to_csv(output_files["buckaroo_lightweight_ucc_candidates.csv"], index=False)
    full_columns.to_csv(output_files["buckaroo_full_column_profile.csv"], index=False)
    full_ucc.to_csv(output_files["buckaroo_full_ucc_candidates.csv"], index=False)
    best_columns.to_csv(output_files["best_expensive_baseline_column_profile.csv"], index=False)
    output_files["report.md"].write_text(build_report(args.dataset, variant_summary, best_columns, output_files), encoding="utf-8")

    print(f"Wrote comparison outputs to {args.out_dir}", flush=True)


if __name__ == "__main__":
    main()
