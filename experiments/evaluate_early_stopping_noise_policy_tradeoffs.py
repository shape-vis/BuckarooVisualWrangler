"""Run early-stopping policy tradeoffs under injected data noise.

This extends the conservative / balanced / aggressive early-stopping
experiment by asking a harder question:

    If the data gets dirtier, does Buckaroo stop too early or become cautious?

The manual labels still describe the original semantic truth of the columns.
For each noisy dataset, the full noisy pass is used as the profiler baseline,
and the manual worksheet is used as the human semantic target.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any
import warnings

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.evaluate_early_stopping_policy_tradeoffs import (  # noqa: E402
    BASE_SEED,
    LABEL_DIR,
    MANUAL_LABELS,
    POLICIES,
    SAMPLE_SIZES,
    compare_profile_to_labels,
    profile_frame,
    run_policy_on_dataset,
)
from experiments.profile_dataset_shape import date_like_ratio  # noqa: E402
from experiments.benchmark_validation import accuracy_output, benchmark_quality  # noqa: E402
from experiments.reproducibility import capture_reproducibility  # noqa: E402


OUT_DIR = ROOT / "outputs" / "corrected_methodology_v2" / "early_stopping_noise_policy_tradeoff"
NOISE_LEVELS = [0.0, 0.05, 0.10, 0.20]


def noise_label(noise_level: float) -> str:
    return f"{int(round(noise_level * 100))}pct"


def stable_noise_seed(dataset_id: str, noise_level: float) -> int:
    """Use one dataset seed so lower noise levels are nested in higher ones."""
    stable_hash = int(hashlib.sha256(dataset_id.encode("utf-8")).hexdigest()[:8], 16)
    return BASE_SEED + 404_000 + (stable_hash % 1_000_000)


def stable_column_seed(dataset_id: str, column: str) -> int:
    token = f"{dataset_id}\0{column}".encode("utf-8")
    stable_hash = int(hashlib.sha256(token).hexdigest()[:8], 16)
    return stable_noise_seed(dataset_id, 0.0) + (stable_hash % 10_000_000)


def inject_noise(frame: pd.DataFrame, noise_level: float, dataset_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replace a percentage of cells in every column with controlled dirty values.

    The noise is intentionally mixed:
    - numeric/date columns get some cross-type text values;
    - text/category columns get rare synthetic labels;
    - every column gets a small amount of missingness.

    That tests whether confidence, warnings, and early stopping respond to
    degraded evidence instead of blindly trusting a small sample.
    """
    log_rows: list[dict[str, Any]] = []
    if noise_level <= 0 or frame.empty:
        return frame.copy(deep=True), pd.DataFrame(log_rows)

    noisy = frame.copy(deep=True).astype("object")

    row_count = len(noisy)

    for column in noisy.columns:
        if column == "ID":
            continue

        column_values = noisy[column]
        replace_count = int(round(row_count * noise_level))
        if replace_count <= 0:
            continue

        replace_count = min(replace_count, row_count)
        column_rng = np.random.default_rng(stable_column_seed(dataset_id, str(column)))
        row_positions = column_rng.permutation(row_count)[:replace_count]
        numeric_ratio = pd.to_numeric(column_values, errors="coerce").notna().mean()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            date_ratio = date_like_ratio(column_values.dropna().astype(str).str.strip())
        column_lower = str(column).lower()

        for offset, position in enumerate(row_positions):
            original_value = noisy.iat[int(position), noisy.columns.get_loc(column)]
            value_rng = np.random.default_rng(
                stable_column_seed(dataset_id, str(column)) + int(position) * 104729
            )
            dirty_value, dirty_kind = dirty_value_for_cell(
                column_lower,
                numeric_ratio,
                date_ratio,
                dataset_id,
                column,
                position,
                offset,
                value_rng,
            )
            noisy.iat[int(position), noisy.columns.get_loc(column)] = dirty_value
            log_rows.append(
                {
                    "dataset_id": dataset_id,
                    "noise_level": noise_level,
                    "noise_label": noise_label(noise_level),
                    "column": column,
                    "row_position": int(position),
                    "original_value": "" if pd.isna(original_value) else str(original_value),
                    "dirty_kind": dirty_kind,
                    "dirty_value": "" if pd.isna(dirty_value) else str(dirty_value),
                }
            )

    return noisy, pd.DataFrame(log_rows)


def dirty_value_for_cell(
    column_lower: str,
    numeric_ratio: float,
    date_ratio: float,
    dataset_id: str,
    column: str,
    row_position: int,
    offset: int,
    rng: np.random.Generator,
) -> tuple[Any, str]:
    roll = float(rng.random())
    if roll < 0.20:
        return pd.NA, "missing_value"

    if date_ratio >= 0.70 or column_lower.endswith("_at") or "date" in column_lower or "time" in column_lower:
        if roll < 0.65:
            return "not-a-date", "invalid_datetime_token"
        return f"2099-99-{(offset % 28) + 1:02d}", "malformed_datetime"

    if numeric_ratio >= 0.70:
        if roll < 0.65:
            return "not_a_number", "invalid_numeric_token"
        return -999999 if roll < 0.82 else f"{dataset_id}_{column}_noise_{row_position}", "numeric_outlier_or_text"

    if "country" in column_lower:
        return "Atlantis", "synthetic_location"
    if any(token in column_lower for token in ["city", "state", "zip", "postal", "airport", "iata", "zone", "borough"]):
        return f"NoisePlace-{row_position}", "synthetic_location"
    if any(token in column_lower for token in ["id", "code", "key"]):
        return f"NOISE-ID-{row_position}", "synthetic_identifier_like_value"
    return f"__noise_value_{row_position}_{offset}__", "rare_synthetic_category"


def summarize_noise_results(
    comparisons: pd.DataFrame,
    dataset_summary: pd.DataFrame,
    quality: dict[str, Any],
) -> pd.DataFrame:
    rows = []
    group_cols = ["noise_level", "noise_label", "policy"]
    for (noise_level, label, policy), group in comparisons.groupby(group_cols, dropna=False):
        dataset_group = dataset_summary[
            (dataset_summary["noise_level"] == noise_level)
            & (dataset_summary["policy"] == policy)
        ]
        stopped_early = dataset_group[dataset_group["stopped_early"].astype(bool)]
        accuracy = accuracy_output(group["matches_manual"], quality)
        rows.append(
            {
                "noise_level": noise_level,
                "noise_label": label,
                "policy": policy,
                "datasets_evaluated": int(dataset_group["dataset_id"].nunique()),
                "datasets_stopped_early": int(len(stopped_early)),
                "labeled_columns_evaluated": int(len(group)),
                **accuracy,
                "full_pass_agreement": round(float(group["matches_full"].mean()), 6) if not group.empty else None,
                "false_key_errors": int(group["false_key"].sum()),
                "missed_key_errors": int(group["missed_key"].sum()),
                "median_chosen_sample_rows": round(float(dataset_group["chosen_sample_rows"].median()), 3),
                "median_runtime_saved_fraction": round(float(dataset_group["runtime_saved_fraction"].median()), 6),
                "median_runtime_saved_fraction_for_early_stops": round(float(stopped_early["runtime_saved_fraction"].median()), 6)
                if not stopped_early.empty
                else None,
                "avg_uncertain_columns_at_stop": round(float(dataset_group["uncertain_columns_at_stop"].mean()), 6),
                "warning_heavy_stops": int(dataset_group["warning_heavy_stop"].sum()),
                **quality,
            }
        )
    return pd.DataFrame(rows).sort_values(["noise_level", "policy"]).reset_index(drop=True)


def write_report(
    summary_by_noise_policy: pd.DataFrame,
    dataset_summary: pd.DataFrame,
    comparisons: pd.DataFrame,
    quality: dict[str, Any],
) -> None:
    disagreements = comparisons[comparisons["matches_full"] == False].copy()  # noqa: E712
    lines = [
        "# Early Stopping With Noise Policy Tradeoff",
        "",
        "This experiment injects controlled cell-level noise into each dataset and reruns the safe, balanced, and aggressive early-stopping policies.",
        "",
        "## Noise Design",
        "",
        "- Noise levels: 0%, 5%, 10%, 20%.",
        "- Each non-zero noise level replaces that percentage of cells in each column.",
        "- Numeric/date columns receive invalid cross-type values plus missingness.",
        "- Category/location/id-like columns receive rare synthetic labels plus missingness.",
        f"- Benchmark provenance: `{quality['benchmark_label_source']}`.",
        "- Manual accuracy is blank while labels remain pending human review; provisional agreement is reported separately.",
        "- The full noisy pass is a stability baseline, not semantic ground truth.",
        "",
        "## Summary By Noise And Policy",
        "",
        "```csv",
        summary_by_noise_policy.to_csv(index=False).strip(),
        "```",
        "",
        "## Per-Dataset Stops",
        "",
        "```csv",
        dataset_summary[
            [
                "dataset_id",
                "noise_label",
                "policy",
                "chosen_sample_rows",
                "total_rows",
                "stopped_early",
                "warning_heavy_stop",
                "uncertain_columns_at_stop",
                "runtime_saved_fraction",
                "sample_path",
            ]
        ].to_csv(index=False).strip(),
        "```",
        "",
        "## Full-Pass Disagreements",
        "",
        "```csv",
        disagreements[
            [
                "dataset_id",
                "noise_label",
                "policy",
                "column",
                "manual_comparable_role",
                "predicted_comparable_role",
                "full_comparable_role",
                "predicted_confidence_score",
                "full_confidence_score",
                "matches_manual",
                "false_key",
                "missed_key",
            ]
        ].to_csv(index=False).strip()
        if not disagreements.empty
        else "none",
        "```",
        "",
        "## Reading The Result",
        "",
        "- Safe should become more cautious as noise increases.",
        "- Balanced is the candidate default if it saves runtime while preserving full-pass agreement and zero false keys.",
        "- Aggressive is acceptable only when the UI makes uncertainty obvious; noise should expose where it becomes unstable.",
    ]
    (OUT_DIR / "noise_policy_tradeoff_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    labels = pd.read_csv(MANUAL_LABELS)
    labels = labels[labels["dataset_id"].notna() & labels["column_name"].notna()].copy()
    quality = benchmark_quality(labels)
    dataset_paths = [LABEL_DIR / f"{dataset_id}.csv" for dataset_id in sorted(labels["dataset_id"].unique())]

    comparison_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    dataset_summary_rows: list[dict[str, Any]] = []
    noise_log_rows: list[dict[str, Any]] = []

    for dataset_id in sorted(labels["dataset_id"].unique()):
        dataset_labels = labels[labels["dataset_id"] == dataset_id].copy()
        frame = pd.read_csv(LABEL_DIR / f"{dataset_id}.csv", low_memory=False)

        for noise_level in NOISE_LEVELS:
            current_noise_label = noise_label(noise_level)
            noisy_frame, noise_log = inject_noise(frame, noise_level, str(dataset_id))
            if not noise_log.empty:
                noise_log_rows.extend(noise_log.to_dict("records"))

            total_rows = len(noisy_frame)
            sample_sizes = sorted(set(size for size in [*SAMPLE_SIZES, total_rows] if 0 < size <= total_rows))
            profiled_samples: dict[int, tuple[pd.DataFrame, float]] = {}
            for sample_rows in sample_sizes:
                from experiments.evaluate_early_stopping_policy_tradeoffs import stable_seed, sample_frame

                seed = stable_seed(str(dataset_id), sample_rows)
                sampled = sample_frame(noisy_frame, sample_rows, seed)
                profiled_samples[sample_rows] = profile_frame(sampled)

            full_profile, full_runtime = profiled_samples[total_rows]
            for policy_name, policy in POLICIES.items():
                policy_profile, decisions, policy_summary = run_policy_on_dataset(
                    str(dataset_id),
                    noisy_frame,
                    policy_name,
                    policy,
                    profiled_samples,
                )

                for row in decisions:
                    row["dataset_id"] = str(dataset_id)
                    row["noise_level"] = noise_level
                    row["noise_label"] = current_noise_label
                policy_summary["dataset_id"] = str(dataset_id)
                policy_summary["noise_level"] = noise_level
                policy_summary["noise_label"] = current_noise_label
                policy_summary["full_runtime_seconds"] = round(float(full_runtime), 6)
                policy_summary["runtime_saved_seconds"] = round(float(full_runtime - policy_summary["adaptive_runtime_seconds"]), 6)
                policy_summary["runtime_saved_fraction"] = (
                    round(float((full_runtime - policy_summary["adaptive_runtime_seconds"]) / full_runtime), 6)
                    if full_runtime > 0
                    else 0.0
                )

                comparison = compare_profile_to_labels(
                    str(dataset_id),
                    dataset_labels,
                    noisy_frame,
                    policy_summary,
                    policy_profile,
                    full_profile,
                )
                for row in comparison:
                    row["noise_level"] = noise_level
                    row["noise_label"] = current_noise_label

                decision_rows.extend(decisions)
                dataset_summary_rows.append(policy_summary)
                comparison_rows.extend(comparison)
                print(
                    f"{dataset_id} {current_noise_label} / {policy_name}: "
                    f"chose {policy_summary['chosen_sample_rows']} of {total_rows}; "
                    f"stopped_early={policy_summary['stopped_early']}; "
                    f"uncertain={policy_summary['uncertain_columns_at_stop']}",
                    flush=True,
                )

    comparisons = pd.DataFrame(comparison_rows)
    decisions = pd.DataFrame(decision_rows)
    dataset_summary = pd.DataFrame(dataset_summary_rows)
    noise_log = pd.DataFrame(noise_log_rows)
    summary_by_noise_policy = summarize_noise_results(comparisons, dataset_summary, quality)

    comparisons.to_csv(OUT_DIR / "noise_policy_column_comparison.csv", index=False)
    decisions.to_csv(OUT_DIR / "noise_policy_sampling_decisions.csv", index=False)
    dataset_summary.to_csv(OUT_DIR / "noise_policy_dataset_summary.csv", index=False)
    summary_by_noise_policy.to_csv(OUT_DIR / "noise_policy_summary_by_noise_policy.csv", index=False)
    noise_log.to_csv(OUT_DIR / "noise_injection_log.csv", index=False)
    noise_examples = (
        noise_log.groupby(["dataset_id", "noise_level", "column"], group_keys=False)
        .head(3)
        .reset_index(drop=True)
        if not noise_log.empty
        else noise_log.copy()
    )
    noise_examples.to_csv(OUT_DIR / "noise_injection_examples.csv", index=False)
    (OUT_DIR / "noise_policy_config.json").write_text(
        json.dumps(
            {
                "noise_levels": NOISE_LEVELS,
                "sample_sizes": SAMPLE_SIZES,
                "base_seed": BASE_SEED,
                "policies": POLICIES,
                "noise_method": "cell replacement per column with missing, invalid numeric/date, synthetic category/location/id-like values",
                "sampling_method": "deterministic_nested_random_prefix",
                "benchmark": quality,
                "methodology_version": "corrected_v2",
                "reproducibility": capture_reproducibility(ROOT, [MANUAL_LABELS, *dataset_paths]),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    write_report(summary_by_noise_policy, dataset_summary, comparisons, quality)

    print(OUT_DIR / "noise_policy_summary_by_noise_policy.csv")
    print(OUT_DIR / "noise_policy_dataset_summary.csv")
    print(OUT_DIR / "noise_policy_column_comparison.csv")
    print(OUT_DIR / "noise_policy_sampling_decisions.csv")
    print(OUT_DIR / "noise_injection_log.csv")
    print(OUT_DIR / "noise_injection_examples.csv")
    print(OUT_DIR / "noise_policy_tradeoff_report.md")
    print(summary_by_noise_policy.to_string(index=False))


if __name__ == "__main__":
    main()
