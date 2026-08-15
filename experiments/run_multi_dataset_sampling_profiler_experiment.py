"""Repeated row-sampling profiler experiment across many public datasets.

This harness compares:

- old Buckaroo fixed-threshold profiling,
- new Buckaroo confidence-interval adaptive profiling,
- Buckaroo adaptive profiling plus bounded HLL/UCC-lite key discovery,
- exact bounded UCC discovery on each sample,
- exact single-column FD discovery on each sample.

For public datasets without hand labels, the script builds a full-data
reference from the current confidence-aware Buckaroo profile plus full-data
UCC-lite key evidence.  The report therefore uses the phrase "reference",
not "absolute ground truth".
"""

from __future__ import annotations

import argparse
from itertools import combinations
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

from detectors.ucc_discovery import discover_ucc_candidates  # noqa: E402
from experiments.profile_dataset_shape import (  # noqa: E402
    CATEGORY_CODE_NAME_TOKENS,
    CONFIDENCE_INTERVAL_Z,
    DEFAULT_HLL_PRECISION,
    FREE_TEXT_NAME_TOKENS,
    ID_NAME_TOKENS,
    MEASUREMENT_NAME_TOKENS,
    VECTOR_NAME_TOKENS,
    append_warning,
    boolean_like_ratio,
    date_like_ratio,
    has_name_hint,
    is_geography_signal,
    is_missing_value,
    name_tokens,
    profile_columns,
)
from experiments.run_profiler_ladder_experiment import (  # noqa: E402
    exact_functional_dependencies,
    split_columns,
)
from experiments.run_profiler_variant_comparison import markdown_table, normalize_json_value  # noqa: E402
from experiments.reproducibility import capture_reproducibility  # noqa: E402


DEFAULT_MANIFEST = ROOT / "outputs" / "public_profile_sampling_datasets" / "dataset_manifest.csv"
DEFAULT_OUT_DIR = ROOT / "outputs" / "multi_dataset_sampling_profiler_experiment"
DEFAULT_SAMPLE_SIZES = [100, 500, 1_000, 5_000, 10_000, 50_000]
DEFAULT_ITERATIONS = 10
BASE_SEED = 20260628

DATETIME_PROFILE_ROLES = {"datetime_category", "datetime_high_uniqueness", "datetime_identifier"}
GEOGRAPHY_SEMANTIC_ROLE = "geographic_location_field"
BUCKAROO_SEMANTIC_PROFILERS = {
    "old_buckaroo_fixed_threshold",
    "buckaroo_sample_only_adaptive",
    "buckaroo_hll_ucc_lite_adaptive",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run multi-dataset repeated-sampling profiler experiment.")
    parser.add_argument("--dataset-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--sample-sizes", type=str, default=",".join(str(value) for value in DEFAULT_SAMPLE_SIZES))
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--base-seed", type=int, default=BASE_SEED)
    parser.add_argument("--max-datasets", type=int, default=0)
    parser.add_argument("--exact-ucc-max-arity", type=int, default=2)
    parser.add_argument("--exact-ucc-max-columns", type=int, default=14)
    parser.add_argument("--ucc-lite-max-arity", type=int, default=3)
    parser.add_argument("--ucc-lite-max-candidate-columns", type=int, default=12)
    return parser.parse_args()


def parse_sample_sizes(raw: str, total_rows: int) -> list[dict[str, Any]]:
    """Use feasible numeric tiers and exactly one explicit full-data endpoint."""
    plans = []
    seen_labels = set()
    for token in raw.split(","):
        token = token.strip().lower()
        if not token or token in seen_labels:
            continue
        seen_labels.add(token)
        if token == "full":
            continue
        requested = int(token.replace("_", ""))
        if 0 < requested < total_rows:
            plans.append(
                {
                    "requested_sample_label": str(requested),
                    "requested_sample_rows": requested,
                    "sample_rows": requested,
                    "requested_full_dataset": False,
                }
            )
    plans.append({
        "requested_sample_label": "full",
        "requested_sample_rows": total_rows,
        "sample_rows": total_rows,
        "requested_full_dataset": True,
    })
    return plans


def timed_call(callback) -> tuple[Any, float]:
    start = time.perf_counter()
    value = callback()
    return value, round(time.perf_counter() - start, 4)


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


def clean_column_name(column: str) -> str:
    return str(column).strip().lower().replace(" ", "_")


def is_datetime_signal(column: str, profile_role: str) -> bool:
    normalized = clean_column_name(column)
    tokens = set(name_tokens(column))
    return bool(
        profile_role in DATETIME_PROFILE_ROLES
        or normalized.endswith("_at")
        or normalized.endswith("_date")
        or normalized.endswith("_time")
        or "date" in tokens
        or "datetime" in tokens
        or "timestamp" in tokens
    )


def is_reference_name(column: str) -> bool:
    normalized = clean_column_name(column)
    tokens = set(name_tokens(column))
    return bool(
        normalized == "id"
        or normalized.endswith("_id")
        or normalized.endswith("id")
        or "id" in tokens
        or "identifier" in tokens
        or "uuid" in tokens
        or "guid" in tokens
        or "subject" in tokens
        or "account" in tokens
        or "customer" in tokens
        or "user" in tokens
    )


def profile_role_from_series(column: str, series: pd.Series) -> dict[str, Any]:
    """Small visible proxy for Buckaroo's earlier fixed-threshold behavior."""

    non_missing = series[~series.map(is_missing_value)]
    non_missing_count = int(len(non_missing))
    if non_missing_count == 0:
        return {
            "column": column,
            "role": "categorical",
            "profile_role": "empty",
            "confidence": "low",
            "confidence_score": 0.0,
            "warning": "Empty column.",
            "non_missing_count": 0,
            "unique_count": 0,
            "cardinality_ratio": 0.0,
            "decision_cardinality_ratio": 0.0,
            "numeric_ratio": 0.0,
            "date_like_ratio": 0.0,
            "cardinality_ratio_lower_bound": 0.0,
            "adaptive_thresholds_version": "legacy_fixed_threshold_proxy",
        }

    as_text = non_missing.astype(str).str.strip()
    numeric = pd.to_numeric(non_missing, errors="coerce")
    numeric_ratio = float(numeric.notna().mean())
    date_ratio = date_like_ratio(as_text)
    bool_ratio = boolean_like_ratio(as_text)
    unique_count = int(as_text.str.lower().nunique(dropna=True))
    cardinality_ratio = float(unique_count / max(1, non_missing_count))
    avg_text_length = float(as_text.str.len().mean())
    avg_word_count = float(as_text.str.split().str.len().mean())
    tokens = name_tokens(column)
    id_hint = has_name_hint(tokens, ID_NAME_TOKENS)
    category_hint = has_name_hint(tokens, CATEGORY_CODE_NAME_TOKENS)
    measurement_hint = has_name_hint(tokens, MEASUREMENT_NAME_TOKENS)
    vector_hint = has_name_hint(tokens, VECTOR_NAME_TOKENS)
    free_text_hint = has_name_hint(tokens, FREE_TEXT_NAME_TOKENS)

    role = "categorical"
    profile_role = "categorical"
    confidence = "medium"
    reason = "Legacy fixed thresholds treated repeating values as categories."
    warning = ""

    if date_ratio >= 0.70 and cardinality_ratio >= 0.75:
        role = "identifier"
        profile_role = "datetime_identifier"
        confidence = "medium"
        reason = "Legacy fixed thresholds promoted highly unique datetimes to identifier-like columns."
        warning = "Legacy behavior: timestamp uniqueness can create false primary-key evidence."
    elif date_ratio >= 0.70:
        profile_role = "datetime_category"
        reason = "Most values parse as dates."
    elif (id_hint and cardinality_ratio >= 0.80) or (
        cardinality_ratio >= 0.90 and avg_word_count < 4 and avg_text_length < 80
    ):
        role = "identifier"
        profile_role = "identifier" if id_hint else "quasi_identifier"
        confidence = "high" if id_hint else "medium"
        reason = "Legacy fixed thresholds used name hints or high uniqueness as identifier evidence."
    elif unique_count == 2 or bool_ratio >= 0.95:
        profile_role = "binary_category"
        confidence = "high"
        reason = "Only two observed values or boolean-like encodings."
    elif vector_hint and avg_word_count >= 50:
        role = "free_text"
        profile_role = "vector_blob"
        reason = "Long fixed-width vector-like text."
    elif numeric_ratio >= 0.90 and (measurement_hint or unique_count > 20):
        role = "numeric"
        profile_role = "numeric_measure"
        confidence = "high" if measurement_hint else "medium"
        reason = "Most values parse as numbers."
    elif free_text_hint or avg_word_count >= 8 or avg_text_length >= 60:
        role = "free_text"
        profile_role = "free_text"
        confidence = "medium"
        reason = "Values look like longer text."
    elif category_hint or unique_count <= 20 or cardinality_ratio <= 0.20:
        profile_role = "categorical"
        confidence = "high" if category_hint or unique_count <= 20 else "medium"
        reason = "Values repeat enough to behave like categories."

    return {
        "column": column,
        "role": role,
        "profile_role": profile_role,
        "confidence": confidence,
        "confidence_score": {"high": 0.9, "medium": 0.65, "low": 0.35}[confidence],
        "warning": warning,
        "reason": reason,
        "non_missing_count": non_missing_count,
        "unique_count": unique_count,
        "cardinality_ratio": round(cardinality_ratio, 4),
        "decision_cardinality_ratio": round(cardinality_ratio, 4),
        "numeric_ratio": round(numeric_ratio, 4),
        "date_like_ratio": round(date_ratio, 4),
        "boolean_like_ratio": round(bool_ratio, 4),
        "avg_text_length": round(avg_text_length, 2),
        "avg_word_count": round(avg_word_count, 2),
        "id_name_hint": id_hint,
        "categorical_name_hint": category_hint,
        "measurement_name_hint": measurement_hint,
        "vector_name_hint": vector_hint,
        "free_text_name_hint": free_text_hint,
        "cardinality_ratio_lower_bound": round(cardinality_ratio, 4),
        "confidence_interval_method": None,
        "confidence_interval_z": None,
        "adaptive_thresholds_version": "legacy_fixed_threshold_proxy",
    }


def legacy_profile_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    records = []
    roles = {"numeric": [], "categorical": [], "free_text": [], "identifier": []}
    for column in df.columns:
        record = profile_role_from_series(str(column), df[column])
        records.append(record)
        roles[record["role"]].append(str(column))
    return pd.DataFrame(records), roles


def primary_keys_from_legacy(profile: pd.DataFrame) -> set[str]:
    if profile.empty:
        return set()
    keys = set()
    for _, row in profile.iterrows():
        if str(row.get("profile_role", "")) in {"identifier", "quasi_identifier", "datetime_identifier"}:
            if str(row.get("confidence", "")) != "low":
                keys.add(str(row["column"]))
    return keys


def primary_keys_from_adaptive_profile(profile: pd.DataFrame) -> set[str]:
    if profile.empty:
        return set()
    keys = set()
    for _, row in profile.iterrows():
        column = str(row["column"])
        profile_role = str(row.get("profile_role", ""))
        confidence = str(row.get("confidence", ""))
        cardinality_lower = float(row.get("cardinality_ratio_lower_bound", 0.0) or 0.0)
        if profile_role in {"identifier", "quasi_identifier"} and cardinality_lower >= 0.90:
            if confidence != "low" and not is_datetime_signal(column, profile_role) and not is_geography_signal(column, profile_role):
                keys.add(column)
    return keys


def single_key_set(frame: pd.DataFrame) -> set[str]:
    if frame.empty or "arity" not in frame.columns or "columns" not in frame.columns:
        return set()
    return {
        split_columns(row["columns"])[0]
        for _, row in frame.iterrows()
        if int(row["arity"]) == 1 and split_columns(row["columns"])
    }


def semantic_role_from_profile(
    column: str,
    row: pd.Series,
    predicted_keys: set[str],
    *,
    guard_datetimes: bool,
) -> str:
    profile_role = str(row.get("profile_role", ""))
    guarded_false_key = guard_datetimes and (
        is_datetime_signal(column, profile_role) or is_geography_signal(column, profile_role)
    )
    if column in predicted_keys and not guarded_false_key:
        return "primary_identifier"
    if is_datetime_signal(column, profile_role):
        return "datetime_lifecycle_field"
    if guard_datetimes and is_geography_signal(column, profile_role):
        return GEOGRAPHY_SEMANTIC_ROLE
    if is_reference_name(column):
        return "foreign_key_or_reference"
    if profile_role == "numeric_measure":
        return "numeric_measure"
    if profile_role == "vector_blob":
        return "vector_blob"
    if profile_role == "free_text":
        return "free_text"
    if profile_role in {"categorical", "binary_category", "numeric_code_category", "datetime_category"}:
        return "low_cardinality_category"
    if profile_role in {"identifier", "quasi_identifier", "datetime_identifier", "datetime_high_uniqueness"}:
        return "high_cardinality_identifier_like"
    return "unknown"


def roles_from_profile(profile: pd.DataFrame, predicted_keys: set[str], *, guard_datetimes: bool) -> dict[str, str]:
    roles = {}
    for _, row in profile.iterrows():
        column = str(row["column"])
        roles[column] = semantic_role_from_profile(column, row, predicted_keys, guard_datetimes=guard_datetimes)
    return roles


def key_only_roles(columns: list[str], predicted_keys: set[str]) -> dict[str, str]:
    return {
        column: "primary_identifier" if column in predicted_keys else "not_primary_identifier"
        for column in columns
    }


def select_exact_ucc_columns(df: pd.DataFrame, max_columns: int) -> list[str]:
    columns = [str(column) for column in df.columns]
    if len(columns) <= max_columns:
        return columns

    row_count = max(1, len(df))
    scored = []
    for index, column in enumerate(columns):
        series = df[column]
        non_missing = series[~series.map(is_missing_value)]
        unique_ratio = float(non_missing.astype(str).str.strip().str.lower().nunique(dropna=True) / max(1, len(non_missing)))
        score = unique_ratio * 4.0
        if is_reference_name(column):
            score += 4.0
        if clean_column_name(column) in {"id", "index", "row_id"}:
            score += 2.0
        if len(non_missing) < row_count:
            score -= 0.25
        scored.append((score, index, column))

    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [column for _, _, column in scored[:max_columns]]


def exact_ucc_bounded(df: pd.DataFrame, max_arity: int, max_columns: int) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    candidate_columns = select_exact_ucc_columns(df, max_columns)
    row_count = int(len(df))
    max_width = min(max_arity, len(candidate_columns))
    evaluated_rows = []
    minimal_keys: list[tuple[str, ...]] = []
    skipped_supersets = 0

    for arity in range(1, max_width + 1):
        for combo in combinations(candidate_columns, arity):
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
                    "candidate_scope_columns": "; ".join(candidate_columns),
                    "candidate_scope_size": len(candidate_columns),
                    "candidate_scope_note": "all_columns" if len(candidate_columns) == len(df.columns) else "bounded_high_uniqueness_columns",
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
        "candidate_scope_size": int(len(candidate_columns)),
        "candidate_scope_columns": "; ".join(candidate_columns),
    }
    return all_candidates, minimal, summary


def fd_primary_keys(fds: pd.DataFrame, columns: list[str]) -> set[str]:
    if fds.empty:
        return set()
    required_rhs_count = max(1, len(columns) - 1)
    lhs_counts = fds.groupby("lhs")["rhs"].nunique()
    return {str(lhs) for lhs, count in lhs_counts.items() if int(count) >= required_rhs_count and " + " not in str(lhs)}


def build_reference(dataset_id: str, full_df: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.DataFrame, set[str], pd.DataFrame]:
    profile, _ = profile_columns(full_df)
    ucc_rows = discover_ucc_candidates(
        full_df,
        profile,
        max_arity=args.ucc_lite_max_arity,
        max_candidate_columns=args.ucc_lite_max_candidate_columns,
    )
    ucc_frame = pd.DataFrame(ucc_rows)
    reference_keys = primary_keys_from_adaptive_profile(profile).union(single_key_set(ucc_frame))

    profile_by_column = profile.set_index("column") if not profile.empty else pd.DataFrame()
    guarded_keys = set()
    for column in reference_keys:
        if column not in profile_by_column.index:
            continue
        profile_role = str(profile_by_column.at[column, "profile_role"])
        if not is_datetime_signal(column, profile_role) and not is_geography_signal(column, profile_role):
            guarded_keys.add(column)

    rows = []
    for _, row in profile.iterrows():
        column = str(row["column"])
        semantic_role = semantic_role_from_profile(column, row, guarded_keys, guard_datetimes=True)
        warning = row.get("warning", "")
        if semantic_role == "high_cardinality_identifier_like" and column not in guarded_keys:
            warning = append_warning(
                str(warning),
                "Full-data reference saw high cardinality, but did not promote it to primary key without stronger semantic evidence.",
            )
        rows.append(
            {
                "dataset_id": dataset_id,
                "column": column,
                "reference_semantic_role": semantic_role,
                "reference_primary_key": semantic_role == "primary_identifier",
                "reference_profile_role": row.get("profile_role"),
                "reference_confidence_score": row.get("confidence_score"),
                "reference_warning": warning,
                "full_unique_count": row.get("decision_unique_count", row.get("unique_count")),
                "full_cardinality_ratio": row.get("decision_cardinality_ratio", row.get("cardinality_ratio")),
                "date_like_ratio": row.get("date_like_ratio"),
                "numeric_ratio": row.get("numeric_ratio"),
            }
        )

    return pd.DataFrame(rows), guarded_keys, ucc_frame


def profile_old_buckaroo(sample_df: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, set[str]]:
    profile, _ = legacy_profile_columns(sample_df)
    keys = primary_keys_from_legacy(profile)
    result = summarize_profile(profile)
    return result, profile, pd.DataFrame(), pd.DataFrame(), keys


def profile_new_buckaroo(sample_df: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, set[str]]:
    profile, _ = profile_columns(sample_df)
    keys = primary_keys_from_adaptive_profile(profile)
    result = summarize_profile(profile)
    return result, profile, pd.DataFrame(), pd.DataFrame(), keys


def profile_buckaroo_hll_ucc(sample_df: pd.DataFrame, args: argparse.Namespace) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, set[str]]:
    profile, _ = profile_columns(sample_df)
    ucc_rows = discover_ucc_candidates(
        sample_df,
        profile,
        max_arity=args.ucc_lite_max_arity,
        max_candidate_columns=args.ucc_lite_max_candidate_columns,
    )
    ucc_frame = pd.DataFrame(ucc_rows)
    keys = single_key_set(ucc_frame)
    result = summarize_profile(profile)
    result["unique_key_candidates"] = int(len(ucc_frame))
    result["single_column_unique_keys"] = int((ucc_frame["arity"] == 1).sum()) if not ucc_frame.empty else 0
    return result, profile, ucc_frame, pd.DataFrame(), keys


def profile_exact_ucc(sample_df: pd.DataFrame, args: argparse.Namespace) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, set[str]]:
    all_candidates, minimal, summary = exact_ucc_bounded(
        sample_df,
        max_arity=args.exact_ucc_max_arity,
        max_columns=args.exact_ucc_max_columns,
    )
    keys = single_key_set(minimal)
    return summary, pd.DataFrame(), minimal, pd.DataFrame(), keys


def profile_exact_fd(sample_df: pd.DataFrame, args: argparse.Namespace) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, set[str]]:
    fds, summary = exact_functional_dependencies(sample_df, max_lhs_arity=1)
    keys = fd_primary_keys(fds, [str(column) for column in sample_df.columns])
    return summary, pd.DataFrame(), pd.DataFrame(), fds, keys


def summarize_profile(profile: pd.DataFrame) -> dict[str, Any]:
    if profile.empty:
        return {
            "columns_profiled": 0,
            "numeric_columns": 0,
            "categorical_columns": 0,
            "identifier_columns": 0,
            "average_profile_confidence": 0.0,
        }
    role_counts = profile["role"].value_counts().to_dict()
    confidence_counts = profile["confidence"].value_counts().to_dict()
    return {
        "columns_profiled": int(len(profile)),
        "numeric_columns": int(role_counts.get("numeric", 0)),
        "categorical_columns": int(role_counts.get("categorical", 0)),
        "identifier_columns": int(role_counts.get("identifier", 0)),
        "free_text_columns": int(role_counts.get("free_text", 0)),
        "average_profile_confidence": round(float(profile["confidence_score"].mean()), 4),
        "columns_needing_more_sampling": int(profile["needs_more_sampling"].sum())
        if "needs_more_sampling" in profile.columns
        else 0,
        "high_confidence_columns": int(confidence_counts.get("high", 0)),
        "medium_confidence_columns": int(confidence_counts.get("medium", 0)),
        "low_confidence_columns": int(confidence_counts.get("low", 0)),
    }


def build_prediction_rows(
    dataset_id: str,
    profiler: str,
    sample_rows: int,
    requested_sample_label: str,
    requested_sample_rows: int,
    iteration: int,
    seed: int,
    columns: list[str],
    reference_roles: dict[str, str],
    predicted_roles: dict[str, str],
    predicted_keys: set[str],
    profile: pd.DataFrame,
) -> list[dict[str, Any]]:
    profile_by_column = profile.set_index("column") if profile is not None and not profile.empty else pd.DataFrame()
    rows = []
    for column in columns:
        expected = reference_roles[column]
        predicted = predicted_roles.get(column, "not_predicted")
        confidence_score = None
        profile_role = None
        warning = None
        candidate_roles_json = None
        top_candidate_role = None
        top_candidate_confidence = None
        second_candidate_role = None
        second_candidate_confidence = None
        candidate_confidence_gap = None
        needs_more_sampling = None
        adaptive_sampling_action = None
        adaptive_sampling_reason = None
        if column in profile_by_column.index:
            confidence_score = profile_by_column.at[column, "confidence_score"]
            profile_role = profile_by_column.at[column, "profile_role"]
            warning = profile_by_column.at[column, "warning"]
            candidate_roles_json = profile_by_column.at[column, "candidate_roles_json"] if "candidate_roles_json" in profile_by_column.columns else None
            top_candidate_role = profile_by_column.at[column, "top_candidate_role"] if "top_candidate_role" in profile_by_column.columns else None
            top_candidate_confidence = profile_by_column.at[column, "top_candidate_confidence"] if "top_candidate_confidence" in profile_by_column.columns else None
            second_candidate_role = profile_by_column.at[column, "second_candidate_role"] if "second_candidate_role" in profile_by_column.columns else None
            second_candidate_confidence = profile_by_column.at[column, "second_candidate_confidence"] if "second_candidate_confidence" in profile_by_column.columns else None
            candidate_confidence_gap = profile_by_column.at[column, "candidate_confidence_gap"] if "candidate_confidence_gap" in profile_by_column.columns else None
            needs_more_sampling = profile_by_column.at[column, "needs_more_sampling"] if "needs_more_sampling" in profile_by_column.columns else None
            adaptive_sampling_action = profile_by_column.at[column, "adaptive_sampling_action"] if "adaptive_sampling_action" in profile_by_column.columns else None
            adaptive_sampling_reason = profile_by_column.at[column, "adaptive_sampling_reason"] if "adaptive_sampling_reason" in profile_by_column.columns else None

        rows.append(
            {
                "dataset_id": dataset_id,
                "profiler": profiler,
                "sample_rows": sample_rows,
                "requested_sample_label": requested_sample_label,
                "requested_sample_rows": requested_sample_rows,
                "sample_was_clipped_to_dataset": sample_rows < requested_sample_rows,
                "iteration": iteration,
                "seed": seed,
                "column": column,
                "reference_semantic_role": expected,
                "predicted_semantic_role": predicted,
                "role_match": predicted == expected,
                "predicted_primary_key": column in predicted_keys,
                "reference_primary_key": expected == "primary_identifier",
                "false_primary_key": column in predicted_keys and expected != "primary_identifier",
                "missed_primary_key": column not in predicted_keys and expected == "primary_identifier",
                "profile_role": profile_role,
                "confidence_score": confidence_score,
                "candidate_roles_json": candidate_roles_json,
                "top_candidate_role": top_candidate_role,
                "top_candidate_confidence": top_candidate_confidence,
                "second_candidate_role": second_candidate_role,
                "second_candidate_confidence": second_candidate_confidence,
                "candidate_confidence_gap": candidate_confidence_gap,
                "needs_more_sampling": needs_more_sampling,
                "adaptive_sampling_action": adaptive_sampling_action,
                "adaptive_sampling_reason": adaptive_sampling_reason,
                "warning": warning,
            }
        )
    return rows


def run_one_iteration(
    dataset_id: str,
    full_df: pd.DataFrame,
    sample_rows: int,
    requested_sample_label: str,
    requested_sample_rows: int,
    iteration: int,
    seed: int,
    args: argparse.Namespace,
    reference_roles: dict[str, str],
    reference_keys: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[pd.DataFrame], list[pd.DataFrame]]:
    sampling_start = time.perf_counter()
    sample_df = full_df.sample(n=sample_rows, replace=False, random_state=seed).reset_index(drop=True)
    sampling_runtime = time.perf_counter() - sampling_start
    columns = [str(column) for column in sample_df.columns]
    run_rows: list[dict[str, Any]] = []
    column_rows: list[dict[str, Any]] = []
    ucc_frames: list[pd.DataFrame] = []
    fd_frames: list[pd.DataFrame] = []

    profiler_callbacks = [
        ("old_buckaroo_fixed_threshold", lambda: profile_old_buckaroo(sample_df)),
        ("buckaroo_sample_only_adaptive", lambda: profile_new_buckaroo(sample_df)),
        ("buckaroo_hll_ucc_lite_adaptive", lambda: profile_buckaroo_hll_ucc(sample_df, args)),
        ("exact_bounded_ucc_sample", lambda: profile_exact_ucc(sample_df, args)),
        ("exact_single_column_fd_sample", lambda: profile_exact_fd(sample_df, args)),
    ]
    rotation = (iteration + sample_rows) % len(profiler_callbacks)
    profiler_callbacks = profiler_callbacks[rotation:] + profiler_callbacks[:rotation]

    for execution_order, (profiler, callback) in enumerate(profiler_callbacks, start=1):
        (result, profile, ucc, fds, predicted_keys), runtime = timed_call(callback)
        if profiler == "old_buckaroo_fixed_threshold":
            predicted_roles = roles_from_profile(profile, predicted_keys, guard_datetimes=False)
        elif profiler in {"buckaroo_sample_only_adaptive", "buckaroo_hll_ucc_lite_adaptive"}:
            predicted_roles = roles_from_profile(profile, predicted_keys, guard_datetimes=True)
        else:
            predicted_roles = key_only_roles(columns, predicted_keys)

        if profiler in BUCKAROO_SEMANTIC_PROFILERS:
            semantic_matches = [predicted_roles[column] == reference_roles[column] for column in columns]
            full_pass_role_agreement = round(float(sum(semantic_matches) / max(1, len(semantic_matches))), 4)
            comparable_columns = len(columns)
        else:
            full_pass_role_agreement = None
            comparable_columns = 0

        key_matches = [
            (column in predicted_keys) == (column in reference_keys)
            for column in columns
        ]
        true_positive_keys = len(predicted_keys.intersection(reference_keys))
        false_keys = sorted(predicted_keys.difference(reference_keys))
        missed_keys = sorted(reference_keys.difference(predicted_keys))
        key_precision = true_positive_keys / len(predicted_keys) if predicted_keys else None
        key_recall = true_positive_keys / len(reference_keys) if reference_keys else None
        false_key_rate = len(false_keys) / len(predicted_keys) if predicted_keys else 0.0

        run_rows.append(
            {
                "dataset_id": dataset_id,
                "profiler": profiler,
                "sample_rows": sample_rows,
                "requested_sample_label": requested_sample_label,
                "requested_sample_rows": requested_sample_rows,
                "sample_was_clipped_to_dataset": sample_rows < requested_sample_rows,
                "iteration": iteration,
                "seed": seed,
                "runtime_seconds": runtime,
                "compute_runtime_seconds": runtime,
                "sampling_runtime_seconds": round(sampling_runtime, 6),
                "end_to_end_runtime_seconds": round(runtime + sampling_runtime, 6),
                "execution_order": execution_order,
                "columns": len(columns),
                "comparable_columns": comparable_columns,
                "full_pass_role_agreement": full_pass_role_agreement,
                "primary_key_decision_accuracy": round(float(sum(key_matches) / max(1, len(key_matches))), 4),
                "predicted_primary_key_count": len(predicted_keys),
                "predicted_primary_keys": "; ".join(sorted(predicted_keys)),
                "reference_primary_key_count": len(reference_keys),
                "reference_primary_keys": "; ".join(sorted(reference_keys)),
                "true_positive_primary_keys": true_positive_keys,
                "false_primary_key_count": len(false_keys),
                "false_primary_keys": "; ".join(false_keys),
                "missed_primary_key_count": len(missed_keys),
                "missed_primary_keys": "; ".join(missed_keys),
                "primary_key_precision": round(key_precision, 4) if key_precision is not None else None,
                "primary_key_recall": round(key_recall, 4) if key_recall is not None else None,
                "made_key_prediction": bool(predicted_keys),
                "false_key_rate": round(false_key_rate, 4),
                "average_profile_confidence": result.get("average_profile_confidence"),
                "columns_needing_more_sampling": result.get("columns_needing_more_sampling"),
                "unique_key_candidates": result.get("unique_key_candidates", result.get("minimal_unique_keys")),
                "functional_dependencies": result.get("functional_dependencies"),
                "evaluated_combinations": result.get("evaluated_combinations"),
                "checked_dependencies": result.get("checked_dependencies"),
                "candidate_scope_size": result.get("candidate_scope_size"),
            }
        )

        column_rows.extend(
            build_prediction_rows(
                dataset_id,
                profiler,
                sample_rows,
                requested_sample_label,
                requested_sample_rows,
                iteration,
                seed,
                columns,
                reference_roles,
                predicted_roles,
                predicted_keys,
                profile,
            )
        )

        if not ucc.empty:
            saved_ucc = ucc.copy()
            saved_ucc.insert(0, "dataset_id", dataset_id)
            saved_ucc.insert(1, "profiler", profiler)
            saved_ucc.insert(2, "requested_sample_label", requested_sample_label)
            saved_ucc.insert(3, "requested_sample_rows", requested_sample_rows)
            saved_ucc.insert(4, "sample_rows", sample_rows)
            saved_ucc.insert(5, "iteration", iteration)
            saved_ucc.insert(6, "seed", seed)
            ucc_frames.append(saved_ucc)

        if not fds.empty:
            saved_fds = fds.copy()
            saved_fds.insert(0, "dataset_id", dataset_id)
            saved_fds.insert(1, "profiler", profiler)
            saved_fds.insert(2, "requested_sample_label", requested_sample_label)
            saved_fds.insert(3, "requested_sample_rows", requested_sample_rows)
            saved_fds.insert(4, "sample_rows", sample_rows)
            saved_fds.insert(5, "iteration", iteration)
            saved_fds.insert(6, "seed", seed)
            fd_frames.append(saved_fds)

    return run_rows, column_rows, ucc_frames, fd_frames


def summarize_runs(run_frame: pd.DataFrame, column_frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    group_keys = [
        "dataset_id",
        "profiler",
        "requested_sample_label",
        "requested_sample_rows",
        "sample_rows",
    ]
    summary = (
        run_frame.groupby(group_keys, dropna=False)
        .agg(
            iterations=("iteration", "count"),
            avg_runtime_seconds=("runtime_seconds", "mean"),
            median_runtime_seconds=("runtime_seconds", "median"),
            max_runtime_seconds=("runtime_seconds", "max"),
            std_runtime_seconds=("runtime_seconds", "std"),
            avg_end_to_end_runtime_seconds=("end_to_end_runtime_seconds", "mean"),
            median_end_to_end_runtime_seconds=("end_to_end_runtime_seconds", "median"),
            avg_full_pass_role_agreement=("full_pass_role_agreement", "mean"),
            std_full_pass_role_agreement=("full_pass_role_agreement", "std"),
            avg_primary_key_decision_accuracy=("primary_key_decision_accuracy", "mean"),
            avg_primary_key_precision=("primary_key_precision", "mean"),
            avg_primary_key_recall=("primary_key_recall", "mean"),
            key_prediction_coverage=("made_key_prediction", "mean"),
            total_true_positive_keys=("true_positive_primary_keys", "sum"),
            total_false_keys=("false_primary_key_count", "sum"),
            total_missed_keys=("missed_primary_key_count", "sum"),
            avg_false_key_rate=("false_key_rate", "mean"),
            avg_predicted_primary_key_count=("predicted_primary_key_count", "mean"),
            avg_profile_confidence=("average_profile_confidence", "mean"),
            avg_columns_needing_more_sampling=("columns_needing_more_sampling", "mean"),
            sample_was_clipped_to_dataset=("sample_was_clipped_to_dataset", "max"),
        )
        .reset_index()
    )
    for column in [
        "avg_runtime_seconds",
        "median_runtime_seconds",
        "max_runtime_seconds",
        "std_runtime_seconds",
        "avg_end_to_end_runtime_seconds",
        "median_end_to_end_runtime_seconds",
        "avg_full_pass_role_agreement",
        "std_full_pass_role_agreement",
        "avg_primary_key_decision_accuracy",
        "avg_primary_key_precision",
        "avg_primary_key_recall",
        "key_prediction_coverage",
        "avg_false_key_rate",
        "avg_predicted_primary_key_count",
        "avg_profile_confidence",
        "avg_columns_needing_more_sampling",
    ]:
        summary[column] = summary[column].round(4)
    summary["micro_primary_key_precision"] = (
        summary["total_true_positive_keys"]
        / (summary["total_true_positive_keys"] + summary["total_false_keys"]).replace(0, pd.NA)
    ).astype("Float64").round(4)
    summary["micro_primary_key_recall"] = (
        summary["total_true_positive_keys"]
        / (summary["total_true_positive_keys"] + summary["total_missed_keys"]).replace(0, pd.NA)
    ).astype("Float64").round(4)

    stability_rows = []
    for (dataset_id, profiler, requested_label, requested_rows, sample_rows, column), group in column_frame.groupby(
        [
            "dataset_id",
            "profiler",
            "requested_sample_label",
            "requested_sample_rows",
            "sample_rows",
            "column",
        ]
    ):
        counts = group["predicted_semantic_role"].value_counts()
        mode_role = str(counts.index[0])
        mode_count = int(counts.iloc[0])
        total = int(len(group))
        stability_rows.append(
            {
                "dataset_id": dataset_id,
                "profiler": profiler,
                "requested_sample_label": requested_label,
                "requested_sample_rows": requested_rows,
                "sample_rows": sample_rows,
                "column": column,
                "reference_semantic_role": group["reference_semantic_role"].iloc[0],
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
        stability.groupby(group_keys, dropna=False)
        .agg(
            avg_role_stability_rate=("role_stability_rate", "mean"),
            min_role_stability_rate=("role_stability_rate", "min"),
            avg_role_entropy=("role_entropy", "mean"),
            unstable_column_count=("role_stability_rate", lambda values: int((values < 1.0).sum())),
            false_key_column_count=("false_primary_key_frequency", lambda values: int((values > 0).sum())),
            missed_key_column_count=("missed_primary_key_frequency", lambda values: int((values > 0).sum())),
        )
        .reset_index()
    )
    for column in ["avg_role_stability_rate", "min_role_stability_rate", "avg_role_entropy"]:
        profiler_stability[column] = profiler_stability[column].round(4)

    summary = summary.merge(profiler_stability, on=group_keys, how="left")

    overall_input = summary.copy()
    overall_input["sample_tier_rows"] = overall_input["requested_sample_rows"].astype("Int64")
    overall_input.loc[overall_input["requested_sample_label"] == "full", "sample_tier_rows"] = pd.NA
    overall = (
        overall_input.groupby(
            ["profiler", "requested_sample_label", "sample_tier_rows"],
            dropna=False,
        )
        .agg(
            datasets=("dataset_id", "nunique"),
            avg_actual_sample_rows=("sample_rows", "mean"),
            min_actual_sample_rows=("sample_rows", "min"),
            max_actual_sample_rows=("sample_rows", "max"),
            clipped_dataset_fraction=("sample_was_clipped_to_dataset", "mean"),
            total_iterations=("iterations", "sum"),
            avg_runtime_seconds=("avg_runtime_seconds", "mean"),
            median_runtime_seconds=("median_runtime_seconds", "median"),
            max_runtime_seconds=("max_runtime_seconds", "max"),
            avg_end_to_end_runtime_seconds=("avg_end_to_end_runtime_seconds", "mean"),
            median_end_to_end_runtime_seconds=("median_end_to_end_runtime_seconds", "median"),
            avg_full_pass_role_agreement=("avg_full_pass_role_agreement", "mean"),
            avg_primary_key_decision_accuracy=("avg_primary_key_decision_accuracy", "mean"),
            avg_primary_key_precision=("avg_primary_key_precision", "mean"),
            avg_primary_key_recall=("avg_primary_key_recall", "mean"),
            avg_key_prediction_coverage=("key_prediction_coverage", "mean"),
            total_true_positive_keys=("total_true_positive_keys", "sum"),
            total_false_keys=("total_false_keys", "sum"),
            total_missed_keys=("total_missed_keys", "sum"),
            avg_false_key_rate=("avg_false_key_rate", "mean"),
            avg_columns_needing_more_sampling=("avg_columns_needing_more_sampling", "mean"),
            avg_role_stability_rate=("avg_role_stability_rate", "mean"),
            avg_unstable_column_count=("unstable_column_count", "mean"),
            avg_false_key_column_count=("false_key_column_count", "mean"),
        )
        .reset_index()
        .rename(columns={"sample_tier_rows": "requested_sample_rows"})
    )
    for column in overall.columns:
        if column.startswith("avg_") or column in {
            "median_runtime_seconds",
            "median_end_to_end_runtime_seconds",
            "max_runtime_seconds",
        }:
            overall[column] = overall[column].round(4)
    overall["micro_primary_key_precision"] = (
        overall["total_true_positive_keys"]
        / (overall["total_true_positive_keys"] + overall["total_false_keys"]).replace(0, pd.NA)
    ).astype("Float64").round(4)
    overall["micro_primary_key_recall"] = (
        overall["total_true_positive_keys"]
        / (overall["total_true_positive_keys"] + overall["total_missed_keys"]).replace(0, pd.NA)
    ).astype("Float64").round(4)

    return summary, stability, profiler_stability, overall


def build_report(
    manifest: pd.DataFrame,
    sample_sizes: str,
    iterations: int,
    summary: pd.DataFrame,
    overall: pd.DataFrame,
    stability: pd.DataFrame,
    output_files: dict[str, Path],
) -> str:
    manifest_display = manifest[
        ["dataset_id", "topic", "row_count", "column_count", "source_name"]
    ].copy()

    overall_display = overall[
        [
            "profiler",
            "requested_sample_label",
            "requested_sample_rows",
            "avg_actual_sample_rows",
            "clipped_dataset_fraction",
            "datasets",
            "total_iterations",
            "median_runtime_seconds",
            "avg_runtime_seconds",
            "avg_full_pass_role_agreement",
            "avg_primary_key_precision",
            "avg_primary_key_recall",
            "avg_false_key_rate",
            "avg_role_stability_rate",
        ]
    ].copy()

    fragile = summary.sort_values(
        ["avg_false_key_rate", "avg_role_stability_rate"],
        ascending=[False, True],
    ).head(25)
    unstable_columns = stability.sort_values(
        ["role_stability_rate", "false_primary_key_frequency"],
        ascending=[True, False],
    ).head(25)

    lines = [
        "# Multi-Dataset Repeated Sampling Profiler Experiment",
        "",
        f"Datasets: `{len(manifest)}` public CSV files",
        f"Requested sample sizes: `{sample_sizes}`",
        f"Iterations per non-full sample size: `{iterations}`",
        "",
        "## Why This Experiment Exists",
        "- One random sample can lie. Repeated samples show whether a profiler is stable or just lucky.",
        "- Old Buckaroo is included as a fixed-threshold control.",
        "- New Buckaroo adaptive uses confidence intervals and semantic guards.",
        "- HLL/UCC-lite adds lightweight Metanome-style key evidence.",
        "- Exact UCC and exact FD are diagnostic baselines: they are mathematically useful, but they can over-trust accidental uniqueness.",
        "",
        "## Dataset Mix",
        markdown_table(manifest_display),
        "",
        "## Overall Results",
        markdown_table(overall_display),
        "",
        "## Highest False-Key / Fragile Dataset Runs",
        markdown_table(
            fragile[
                [
                    "dataset_id",
                    "profiler",
                    "requested_sample_label",
                    "requested_sample_rows",
                    "sample_rows",
                    "iterations",
                    "median_runtime_seconds",
                    "avg_runtime_seconds",
                    "avg_full_pass_role_agreement",
                    "avg_primary_key_precision",
                    "avg_primary_key_recall",
                    "avg_false_key_rate",
                    "avg_role_stability_rate",
                    "false_key_column_count",
                ]
            ]
        ),
        "",
        "## Most Unstable Column Decisions",
        markdown_table(
            unstable_columns[
                [
                    "dataset_id",
                    "profiler",
                    "sample_rows",
                    "column",
                    "reference_semantic_role",
                    "mode_predicted_role",
                    "role_stability_rate",
                    "role_counts",
                    "false_primary_key_frequency",
                    "missed_primary_key_frequency",
                ]
            ]
        ),
        "",
        "## Beginner-Friendly Reading",
        "- High role stability means repeated random samples gave the same label.",
        "- High key precision means columns called primary keys were usually reference primary keys.",
        "- High key recall means the profiler found the reference primary keys when they existed.",
        "- High false-key rate means the profiler was inventing keys from accidental uniqueness.",
        "- Exact UCC/FD can be correct mathematically and still semantically wrong, especially for unique timestamps or small samples.",
        "",
        "## Output Files",
    ]
    for label, path in output_files.items():
        lines.append(f"- `{label}`: `{path}`")
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    manifest = pd.read_csv(args.dataset_manifest)
    if args.max_datasets > 0:
        manifest = manifest.head(args.max_datasets).copy()

    all_run_rows: list[dict[str, Any]] = []
    all_column_rows: list[dict[str, Any]] = []
    all_ucc_frames: list[pd.DataFrame] = []
    all_fd_frames: list[pd.DataFrame] = []
    all_reference_rows: list[pd.DataFrame] = []
    reference_ucc_frames: list[pd.DataFrame] = []

    for dataset_index, item in manifest.reset_index(drop=True).iterrows():
        dataset_id = str(item["dataset_id"])
        dataset_path = Path(str(item["local_path"]))
        full_df = pd.read_csv(dataset_path, low_memory=False)
        full_df.columns = [str(column) for column in full_df.columns]
        sample_plans = parse_sample_sizes(args.sample_sizes, len(full_df))

        print(
            f"Dataset {dataset_index + 1}/{len(manifest)}: {dataset_id} "
            f"({len(full_df)} rows, {full_df.shape[1]} columns)",
            flush=True,
        )

        reference_frame, reference_keys, reference_ucc = build_reference(dataset_id, full_df, args)
        all_reference_rows.append(reference_frame)
        if not reference_ucc.empty:
            saved_reference_ucc = reference_ucc.copy()
            saved_reference_ucc.insert(0, "dataset_id", dataset_id)
            saved_reference_ucc.insert(1, "profiler", "full_data_reference_ucc_lite")
            reference_ucc_frames.append(saved_reference_ucc)

        reference_roles = reference_frame.set_index("column")["reference_semantic_role"].to_dict()

        for sample_plan in sample_plans:
            sample_rows = int(sample_plan["sample_rows"])
            requested_sample_label = str(sample_plan["requested_sample_label"])
            requested_sample_rows = int(sample_plan["requested_sample_rows"])
            size_iterations = 1 if sample_rows == len(full_df) else args.iterations
            for iteration in range(1, size_iterations + 1):
                seed = int(args.base_seed + dataset_index * 1_000_000 + sample_rows * 100 + iteration)
                print(
                    f"  sample_rows={sample_rows}, iteration={iteration}/{size_iterations}, seed={seed}",
                    flush=True,
                )
                run_rows, column_rows, ucc_frames, fd_frames = run_one_iteration(
                    dataset_id,
                    full_df,
                    sample_rows,
                    requested_sample_label,
                    requested_sample_rows,
                    iteration,
                    seed,
                    args,
                    reference_roles,
                    reference_keys,
                )
                all_run_rows.extend(run_rows)
                all_column_rows.extend(column_rows)
                all_ucc_frames.extend(ucc_frames)
                all_fd_frames.extend(fd_frames)

    run_frame = pd.DataFrame(all_run_rows)
    column_frame = pd.DataFrame(all_column_rows)
    reference_frame = pd.concat(all_reference_rows, ignore_index=True) if all_reference_rows else pd.DataFrame()
    summary, stability, profiler_stability, overall = summarize_runs(run_frame, column_frame)

    output_files = {
        "dataset_reference_roles.csv": args.out_dir / "dataset_reference_roles.csv",
        "sampling_iteration_runs.csv": args.out_dir / "sampling_iteration_runs.csv",
        "sampling_column_predictions.csv": args.out_dir / "sampling_column_predictions.csv",
        "sampling_summary_by_dataset_profiler_size.csv": args.out_dir / "sampling_summary_by_dataset_profiler_size.csv",
        "sampling_summary_overall.csv": args.out_dir / "sampling_summary_overall.csv",
        "sampling_column_stability.csv": args.out_dir / "sampling_column_stability.csv",
        "sampling_profiler_stability.csv": args.out_dir / "sampling_profiler_stability.csv",
        "sampling_ucc_candidates.csv": args.out_dir / "sampling_ucc_candidates.csv",
        "sampling_functional_dependencies.csv": args.out_dir / "sampling_functional_dependencies.csv",
        "experiment_config.json": args.out_dir / "experiment_config.json",
        "report.md": args.out_dir / "report.md",
    }

    reference_frame.to_csv(output_files["dataset_reference_roles.csv"], index=False)
    run_frame.to_csv(output_files["sampling_iteration_runs.csv"], index=False)
    column_frame.to_csv(output_files["sampling_column_predictions.csv"], index=False)
    summary.to_csv(output_files["sampling_summary_by_dataset_profiler_size.csv"], index=False)
    overall.to_csv(output_files["sampling_summary_overall.csv"], index=False)
    stability.to_csv(output_files["sampling_column_stability.csv"], index=False)
    profiler_stability.to_csv(output_files["sampling_profiler_stability.csv"], index=False)

    ucc_frames = [*reference_ucc_frames, *all_ucc_frames]
    if ucc_frames:
        pd.concat(ucc_frames, ignore_index=True).to_csv(output_files["sampling_ucc_candidates.csv"], index=False)
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
                    "dataset_manifest": str(args.dataset_manifest),
                    "out_dir": str(args.out_dir),
                    "sample_sizes": args.sample_sizes,
                    "sample_tier_policy": "feasible_requested_tiers_plus_one_full_dataset_run",
                    "iterations": args.iterations,
                    "base_seed": args.base_seed,
                    "confidence_interval_z": CONFIDENCE_INTERVAL_Z,
                    "hll_precision": DEFAULT_HLL_PRECISION,
                    "exact_ucc_max_arity": args.exact_ucc_max_arity,
                    "exact_ucc_max_columns": args.exact_ucc_max_columns,
                    "ucc_lite_max_arity": args.ucc_lite_max_arity,
                    "ucc_lite_max_candidate_columns": args.ucc_lite_max_candidate_columns,
                    "profilers": [
                        "old_buckaroo_fixed_threshold",
                        "buckaroo_sample_only_adaptive",
                        "buckaroo_hll_ucc_lite_adaptive",
                        "exact_bounded_ucc_sample",
                        "exact_single_column_fd_sample",
                    ],
                    "reference_note": "Full-data confidence-aware Buckaroo profile plus UCC-lite key evidence; not human-labeled ground truth.",
                    "methodology_version": "corrected_v2",
                    "reproducibility": capture_reproducibility(
                        ROOT,
                        [args.dataset_manifest, *(Path(str(path)) for path in manifest["local_path"].tolist())],
                    ),
                }
            ),
            indent=2,
        ),
        encoding="utf-8",
    )
    output_files["report.md"].write_text(
        build_report(manifest, args.sample_sizes, args.iterations, summary, overall, stability, output_files),
        encoding="utf-8",
    )

    print(f"Wrote multi-dataset sampling outputs to {args.out_dir}", flush=True)


if __name__ == "__main__":
    main()
