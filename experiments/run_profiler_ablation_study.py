"""Ablation study for Buckaroo's adaptive profiler.

The goal is to prove that each profiler feature is doing useful work.  Each
ablation removes one design idea and measures what breaks against the frozen
manual/AI-reviewed labels.

The variants are intentionally lightweight and explainable:
- full_buckaroo_adaptive: current profiler output.
- no_confidence_intervals: trusts observed sample uniqueness/parse ratios.
- no_geography_safeguards: allows unique-looking geography fields to become keys.
- no_timestamp_safeguards: allows unique-looking timestamp fields to become keys.
- no_candidate_roles: removes alternate-role evidence from decisions.
- no_adaptive_sampling: ignores sample-more warnings and accepts the first sample.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
from typing import Any
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.evaluate_early_stopping_policy_tradeoffs import (  # noqa: E402
    BASE_SEED,
    LABEL_DIR,
    MANUAL_LABELS,
    clean_text,
    comparable_expected_role,
    comparable_predicted_role,
    predicted_primary_key,
    sample_frame,
    stable_seed,
    yes,
)
from experiments.profile_dataset_shape import ProfilerFeatureFlags, profile_columns  # noqa: E402
from experiments.benchmark_validation import benchmark_quality  # noqa: E402
from experiments.reproducibility import capture_reproducibility  # noqa: E402


OUT_DIR = ROOT / "outputs" / "corrected_methodology_v2" / "profiler_ablation_study"
SAMPLE_SIZES = [100, 500, 1_000, 5_000, "full"]
VARIANTS = [
    "full_buckaroo_adaptive",
    "no_confidence_intervals",
    "no_geography_safeguards",
    "no_timestamp_safeguards",
    "no_candidate_roles",
    "no_adaptive_sampling",
]


def distinct_sample_plan(total_rows: int) -> list[tuple[int | str, int]]:
    """Return each real sample size once, with an explicit full-data endpoint."""
    plan = [
        (label, int(label))
        for label in SAMPLE_SIZES
        if label != "full" and int(label) < total_rows
    ]
    plan.append(("full", total_rows))
    return plan


def variant_features(variant: str) -> ProfilerFeatureFlags:
    """Return the real profiler configuration for one feature ablation."""
    options = {
        "no_confidence_intervals": {"use_confidence_intervals": False},
        "no_geography_safeguards": {"use_geography_safeguards": False},
        "no_timestamp_safeguards": {"use_timestamp_safeguards": False},
        "no_candidate_roles": {"include_candidate_roles": False},
        "no_adaptive_sampling": {"enable_adaptive_sampling": False},
    }
    if variant not in VARIANTS:
        raise ValueError(f"Unknown ablation variant: {variant}")
    return ProfilerFeatureFlags(**options.get(variant, {}))


def profile_frame(frame: pd.DataFrame, variant: str) -> tuple[pd.DataFrame, float]:
    start = time.perf_counter()
    profile, _roles = profile_columns(frame, features=variant_features(variant))
    return profile, time.perf_counter() - start


def expected_warning_required(row: pd.Series) -> str:
    value = clean_text(row.get("should_buckaroo_warn")).lower()
    if value in {"yes", "true", "required"}:
        return "yes"
    if value in {"optional", "maybe"}:
        return "optional"
    return "no"


def warning_matches(row: pd.Series, predicted_warning: str) -> bool:
    required = expected_warning_required(row)
    has_warning = bool(clean_text(predicted_warning))
    if required == "yes":
        return has_warning
    if required == "no":
        return not has_warning
    return True


def warning_missing(row: pd.Series, predicted_warning: str) -> bool:
    return expected_warning_required(row) == "yes" and not bool(clean_text(predicted_warning))


def warning_unexpected(row: pd.Series, predicted_warning: str) -> bool:
    return expected_warning_required(row) == "no" and bool(clean_text(predicted_warning))


def profile_lookup(profile: pd.DataFrame) -> dict[str, dict[str, Any]]:
    return {
        clean_text(record.get("column")): record
        for record in profile.to_dict(orient="records")
    }


def score_variant(
    dataset_id: str,
    sample_label: int | str,
    sample_rows: int,
    total_rows: int,
    labels: pd.DataFrame,
    frame: pd.DataFrame,
    profile: pd.DataFrame,
    runtime_seconds: float,
    variant: str,
) -> list[dict[str, Any]]:
    by_column = profile_lookup(profile)
    rows = []
    for _, label in labels.iterrows():
        column = clean_text(label.get("column_name"))
        if column not in frame.columns:
            continue
        predicted = by_column.get(column, {})
        predicted_profile_role = clean_text(predicted.get("profile_role"))
        predicted_role = comparable_predicted_role(predicted_profile_role, clean_text(predicted.get("role")))
        manual_role = comparable_expected_role(label)
        manual_primary_key = yes(label.get("is_primary_key")) or yes(label.get("corrected_is_primary_key"))
        predicted_key = predicted_primary_key(predicted_profile_role)
        predicted_warning = clean_text(predicted.get("warning"))
        candidates = predicted.get("candidate_roles")
        candidate_count = len(candidates) if isinstance(candidates, list) else 0

        rows.append(
            {
                "dataset_id": dataset_id,
                "sample_label": str(sample_label),
                "sample_rows": sample_rows,
                "total_rows": total_rows,
                "variant": variant,
                "column": column,
                "manual_comparable_role": manual_role,
                "predicted_comparable_role": predicted_role,
                "role_match": predicted_role == manual_role,
                "manual_is_primary_key": manual_primary_key,
                "predicted_primary_key": predicted_key,
                "false_key": predicted_key and not manual_primary_key,
                "missed_key": (not predicted_key) and manual_primary_key,
                "warning_expected": expected_warning_required(label),
                "predicted_warning": predicted_warning,
                "warning_match": warning_matches(label, predicted_warning),
                "missing_required_warning": warning_missing(label, predicted_warning),
                "unexpected_warning": warning_unexpected(label, predicted_warning),
                "confidence_score": predicted.get("confidence_score"),
                "needs_more_sampling": bool(predicted.get("needs_more_sampling")),
                "candidate_count": candidate_count,
                "has_candidate_roles": candidate_count > 0,
                "runtime_seconds": runtime_seconds,
                "ablation_note": f"end-to-end profiler run with {variant_features(variant)}",
            }
        )
    return rows


def summarize(
    rows: pd.DataFrame,
    quality: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary = (
        rows.groupby(["variant", "sample_label"], dropna=False)
        .agg(
            datasets=("dataset_id", "nunique"),
            labeled_columns=("column", "count"),
            label_agreement=("role_match", "mean"),
            warning_accuracy=("warning_match", "mean"),
            false_key_errors=("false_key", "sum"),
            missed_key_errors=("missed_key", "sum"),
            predicted_key_count=("predicted_primary_key", "sum"),
            missing_required_warnings=("missing_required_warning", "sum"),
            unexpected_warnings=("unexpected_warning", "sum"),
            avg_confidence_score=("confidence_score", "mean"),
            columns_needing_more_sampling=("needs_more_sampling", "sum"),
            columns_with_candidate_roles=("has_candidate_roles", "sum"),
            avg_runtime_seconds=("runtime_seconds", "mean"),
        )
        .reset_index()
    )
    summary["false_key_rate_per_column"] = summary["false_key_errors"] / summary["labeled_columns"]
    summary["false_key_rate_per_predicted_key"] = summary.apply(
        lambda row: row["false_key_errors"] / row["predicted_key_count"] if row["predicted_key_count"] else 0.0,
        axis=1,
    )
    for column in [
        "label_agreement",
        "warning_accuracy",
        "avg_confidence_score",
        "avg_runtime_seconds",
        "false_key_rate_per_column",
        "false_key_rate_per_predicted_key",
    ]:
        summary[column] = summary[column].astype(float).round(6)

    full_label = "full"
    full_or_largest = rows[rows["sample_label"] == full_label]
    if full_or_largest.empty:
        full_or_largest = rows
    overall = (
        full_or_largest.groupby("variant", dropna=False)
        .agg(
            datasets=("dataset_id", "nunique"),
            labeled_columns=("column", "count"),
            label_agreement=("role_match", "mean"),
            warning_accuracy=("warning_match", "mean"),
            false_key_errors=("false_key", "sum"),
            missed_key_errors=("missed_key", "sum"),
            predicted_key_count=("predicted_primary_key", "sum"),
            missing_required_warnings=("missing_required_warning", "sum"),
            unexpected_warnings=("unexpected_warning", "sum"),
            columns_needing_more_sampling=("needs_more_sampling", "sum"),
            columns_with_candidate_roles=("has_candidate_roles", "sum"),
        )
        .reset_index()
    )
    overall["false_key_rate_per_column"] = overall["false_key_errors"] / overall["labeled_columns"]
    overall["false_key_rate_per_predicted_key"] = overall.apply(
        lambda row: row["false_key_errors"] / row["predicted_key_count"] if row["predicted_key_count"] else 0.0,
        axis=1,
    )
    for column in [
        "label_agreement",
        "warning_accuracy",
        "false_key_rate_per_column",
        "false_key_rate_per_predicted_key",
    ]:
        overall[column] = overall[column].astype(float).round(6)
    for frame in (summary, overall):
        if quality["benchmark_is_fully_human_reviewed"]:
            frame["manual_accuracy"] = frame["label_agreement"]
            frame["provisional_label_agreement"] = None
        else:
            frame["manual_accuracy"] = None
            frame["provisional_label_agreement"] = frame["label_agreement"]
        for key, value in quality.items():
            frame[key] = value
    return summary, overall


def feature_removed_label(variant: str) -> str:
    labels = {
        "full_buckaroo_adaptive": "none: full Buckaroo adaptive",
        "no_confidence_intervals": "confidence intervals",
        "no_geography_safeguards": "geography safeguards",
        "no_timestamp_safeguards": "timestamp safeguards",
        "no_candidate_roles": "candidate roles",
        "no_adaptive_sampling": "adaptive sampling",
    }
    return labels.get(variant, variant)


def build_paper_table(summary: pd.DataFrame, overall: pd.DataFrame) -> pd.DataFrame:
    small_100 = summary[summary["sample_label"] == "100"].copy()
    small_100["sample_scope"] = "100-row sample"
    full = overall.copy()
    full["sample_scope"] = "full dataset"

    full = full.rename(columns={"false_key_rate_per_column": "false_key_rate"})
    small_100 = small_100.rename(columns={"false_key_rate_per_column": "false_key_rate"})

    columns = [
        "variant",
        "sample_scope",
        "manual_accuracy",
        "provisional_label_agreement",
        "warning_accuracy",
        "false_key_rate",
        "false_key_errors",
        "missing_required_warnings",
        "columns_needing_more_sampling",
        "columns_with_candidate_roles",
    ]
    table = pd.concat([small_100[columns], full[columns]], ignore_index=True)
    table.insert(0, "feature_removed", table["variant"].map(feature_removed_label))
    return table.sort_values(["sample_scope", "variant"]).reset_index(drop=True)


def write_report(
    summary: pd.DataFrame,
    overall: pd.DataFrame,
    quality: dict[str, Any],
) -> None:
    paper_table = build_paper_table(summary, overall)
    small_sample = summary[summary["sample_label"].isin(["100", "500"])].copy()
    lines = [
        "# Buckaroo Profiler Ablation Study",
        "",
        "This experiment removes one profiler feature at a time and measures what breaks.",
        "Every variant is now rerun end to end through `profile_columns` with one real feature flag disabled.",
        f"Benchmark provenance: `{quality['benchmark_label_source']}`.",
        "Manual accuracy remains blank until all labels are human-approved.",
        "",
        "## Variants",
        "",
        "- `full_buckaroo_adaptive`: current profiler.",
        "- `no_confidence_intervals`: trusts observed sample thresholds without Wilson/lower-bound uncertainty.",
        "- `no_geography_safeguards`: lets unique-looking geography/location fields become keys.",
        "- `no_timestamp_safeguards`: lets unique-looking timestamp fields become keys.",
        "- `no_candidate_roles`: hides alternate-role evidence.",
        "- `no_adaptive_sampling`: disables sample-more decisions.",
        "",
        "## Overall Full-Dataset Summary",
        "",
        "```csv",
        overall.to_csv(index=False).strip(),
        "```",
        "",
        "## Paper-Ready Table",
        "",
        "```csv",
        paper_table.to_csv(index=False).strip(),
        "```",
        "",
        "## Small-Sample Summary",
        "",
        "```csv",
        small_sample.to_csv(index=False).strip(),
        "```",
        "",
        "## Reading This",
        "",
        "- If removing geography/timestamp safeguards raises false keys, those safeguards are justified.",
        "- If removing confidence intervals hurts small samples, Wilson/confidence intervals are justified.",
        "- If removing candidate roles leaves accuracy similar but removes candidate evidence, that is an explainability loss rather than only an accuracy loss.",
        "- If removing adaptive sampling reduces columns asking for more rows, that is not a win; it means Buckaroo stopped admitting uncertainty.",
    ]
    (OUT_DIR / "ablation_study_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    labels = pd.read_csv(MANUAL_LABELS)
    labels = labels[labels["dataset_id"].notna() & labels["column_name"].notna()].copy()
    quality = benchmark_quality(labels)
    dataset_paths = [LABEL_DIR / f"{dataset_id}.csv" for dataset_id in sorted(labels["dataset_id"].unique())]

    all_rows: list[dict[str, Any]] = []
    for dataset_id in sorted(labels["dataset_id"].unique()):
        dataset_labels = labels[labels["dataset_id"] == dataset_id].copy()
        frame = pd.read_csv(LABEL_DIR / f"{dataset_id}.csv", low_memory=False)
        total_rows = len(frame)
        for sample_label, rows in distinct_sample_plan(total_rows):
            seed = stable_seed(str(dataset_id), rows)
            sampled = sample_frame(frame, rows, seed)
            for variant in VARIANTS:
                profile, runtime_seconds = profile_frame(sampled, variant)
                scored = score_variant(
                    str(dataset_id),
                    sample_label,
                    rows,
                    total_rows,
                    dataset_labels,
                    frame,
                    profile,
                    runtime_seconds,
                    variant,
                )
                all_rows.extend(scored)
            print(f"{dataset_id} sample={sample_label} rows={rows}", flush=True)

    detail = pd.DataFrame(all_rows)
    summary, overall = summarize(detail, quality)
    paper_table = build_paper_table(summary, overall)

    detail.to_csv(OUT_DIR / "ablation_column_results.csv", index=False)
    summary.to_csv(OUT_DIR / "ablation_summary_by_variant_sample.csv", index=False)
    overall.to_csv(OUT_DIR / "ablation_summary_full_dataset.csv", index=False)
    paper_table.to_csv(OUT_DIR / "ablation_paper_table.csv", index=False)
    write_report(summary, overall, quality)
    (OUT_DIR / "ablation_config.json").write_text(
        json.dumps(
            {
                "sample_sizes": SAMPLE_SIZES,
                "base_seed": BASE_SEED,
                "variants": VARIANTS,
                "manual_labels": str(MANUAL_LABELS),
                "benchmark": quality,
                "methodology_version": "true_end_to_end_ablation_v2",
                "reproducibility": capture_reproducibility(ROOT, [MANUAL_LABELS, *dataset_paths]),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(OUT_DIR / "ablation_summary_full_dataset.csv")
    print(OUT_DIR / "ablation_summary_by_variant_sample.csv")
    print(OUT_DIR / "ablation_paper_table.csv")
    print(OUT_DIR / "ablation_column_results.csv")
    print(OUT_DIR / "ablation_study_report.md")
    print(overall.to_string(index=False))


if __name__ == "__main__":
    main()
