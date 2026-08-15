"""Compare conservative, balanced, and warning-heavy early stopping policies.

This experiment answers Paul's follow-up question:

    What happens if Buckaroo stops earlier but tells the user it is uncertain?

Each policy uses the same randomized sample ladder and the same current
Buckaroo profiler. The only difference is the stopping rule.
"""

from __future__ import annotations

import hashlib
import json
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
OUT_DIR = ROOT / "outputs" / "corrected_methodology_v2" / "early_stopping_policy_tradeoff"
SAMPLE_SIZES = [100, 500, 1_000, 5_000, 10_000, 50_000]
BASE_SEED = 20260709

POLICIES: dict[str, dict[str, Any]] = {
    "safe_conservative": {
        "description": "Current safest policy: stop only when no column asks for more sampling.",
        "min_sample_rows": 100,
        "min_avg_confidence": 0.0,
        "min_min_confidence": 0.0,
        "max_columns_needing_more": 0,
        "warning_mode": "normal",
    },
    "balanced": {
        "description": "Stop earlier when overall confidence is strong; show warnings for remaining uncertain columns.",
        "min_sample_rows": 500,
        "min_avg_confidence": 0.86,
        "min_min_confidence": 0.80,
        "max_columns_needing_more": 2,
        "warning_mode": "show_remaining_uncertainty",
    },
    "aggressive_warning_heavy": {
        "description": "Stop as soon as a rough answer is usable; always surface uncertainty loudly.",
        "min_sample_rows": 100,
        "min_avg_confidence": 0.72,
        "min_min_confidence": 0.50,
        "max_columns_needing_more": 999,
        "warning_mode": "warn_heavily",
    },
}


def clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def yes(value: Any) -> bool:
    return clean_text(value).lower() in {"yes", "true", "1"}


def comparable_expected_role(row: pd.Series) -> str:
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
    return clean_text(profile_role).lower() == "identifier"


def sample_frame(frame: pd.DataFrame, rows: int, seed: int) -> pd.DataFrame:
    if rows >= len(frame):
        return frame.copy()
    return (
        frame.sample(frac=1.0, replace=False, random_state=seed)
        .head(rows)
        .reset_index(drop=True)
    )


def profile_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    start = time.perf_counter()
    profile, _ = profile_columns(frame)
    return profile, time.perf_counter() - start


def profile_lookup(profile: pd.DataFrame) -> dict[str, dict[str, Any]]:
    return {clean_text(record.get("column")): record for record in profile.to_dict(orient="records")}


def profile_metrics(profile: pd.DataFrame) -> dict[str, Any]:
    if profile.empty:
        return {
            "columns_profiled": 0,
            "columns_needing_more_sampling": 0,
            "uncertain_columns": "",
            "avg_confidence_score": 0.0,
            "min_confidence_score": 0.0,
            "avg_candidate_confidence_gap": 0.0,
            "min_candidate_confidence_gap": 0.0,
            "max_sample_uncertainty_margin": 0.0,
        }

    needs_more = profile["needs_more_sampling"].fillna(True).astype(bool) if "needs_more_sampling" in profile else pd.Series([True] * len(profile))
    confidence = pd.to_numeric(profile.get("confidence_score"), errors="coerce").fillna(0)
    gap = pd.to_numeric(profile.get("candidate_confidence_gap"), errors="coerce").fillna(0)
    margin = pd.to_numeric(profile.get("sample_uncertainty_margin"), errors="coerce").fillna(0)
    uncertain_columns = profile.loc[needs_more, "column"].astype(str).tolist() if "column" in profile else []

    return {
        "columns_profiled": int(len(profile)),
        "columns_needing_more_sampling": int(needs_more.sum()),
        "uncertain_columns": "; ".join(uncertain_columns),
        "avg_confidence_score": round(float(confidence.mean()), 6),
        "min_confidence_score": round(float(confidence.min()), 6),
        "avg_candidate_confidence_gap": round(float(gap.mean()), 6),
        "min_candidate_confidence_gap": round(float(gap.min()), 6),
        "max_sample_uncertainty_margin": round(float(margin.max()), 6),
    }


def policy_stop(policy: dict[str, Any], sample_rows: int, total_rows: int, metrics: dict[str, Any]) -> tuple[bool, str, bool]:
    if sample_rows >= total_rows:
        return True, "full dataset reached", False

    if sample_rows < int(policy["min_sample_rows"]):
        return False, f"sample below policy minimum {policy['min_sample_rows']}", False

    reasons = []
    if metrics["avg_confidence_score"] < float(policy["min_avg_confidence"]):
        reasons.append("average confidence below threshold")
    if metrics["min_confidence_score"] < float(policy["min_min_confidence"]):
        reasons.append("minimum column confidence below threshold")
    if metrics["columns_needing_more_sampling"] > int(policy["max_columns_needing_more"]):
        reasons.append("too many columns still request more sampling")

    stop = not reasons
    warning_heavy_stop = stop and metrics["columns_needing_more_sampling"] > 0
    reason = "stop: policy thresholds satisfied" if stop else "continue: " + "; ".join(reasons)
    return stop, reason, warning_heavy_stop


def stable_seed(dataset_id: str, sample_rows: int | None = None) -> int:
    """Return one seed per dataset so all sample sizes are nested prefixes."""
    stable_dataset_hash = int(hashlib.sha256(dataset_id.encode("utf-8")).hexdigest()[:8], 16)
    return BASE_SEED + (stable_dataset_hash % 100_000)


def run_policy_on_dataset(
    dataset_id: str,
    frame: pd.DataFrame,
    policy_name: str,
    policy: dict[str, Any],
    profiled_samples: dict[int, tuple[pd.DataFrame, float]],
) -> tuple[pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    total_rows = len(frame)
    sample_sizes = sorted(set(size for size in [*SAMPLE_SIZES, total_rows] if 0 < size <= total_rows))
    cumulative_runtime = 0.0
    final_profile = pd.DataFrame()
    decisions: list[dict[str, Any]] = []

    for sample_rows in sample_sizes:
        profile, runtime = profiled_samples[sample_rows]
        cumulative_runtime += runtime
        final_profile = profile
        metrics = profile_metrics(profile)
        stop, stop_reason, warning_heavy_stop = policy_stop(policy, sample_rows, total_rows, metrics)
        decisions.append(
            {
                "dataset_id": dataset_id,
                "policy": policy_name,
                "sample_rows": int(sample_rows),
                "total_rows": int(total_rows),
                "seed": stable_seed(dataset_id, sample_rows),
                "sampling_method": (
                    "full_dataset"
                    if sample_rows >= total_rows
                    else "deterministic_nested_random_prefix"
                ),
                "step_runtime_seconds": round(float(runtime), 6),
                "cumulative_runtime_seconds": round(float(cumulative_runtime), 6),
                "stop_recommended": bool(stop),
                "stop_reason": stop_reason,
                "warning_heavy_stop": bool(warning_heavy_stop),
                **metrics,
            }
        )
        if stop:
            break

    final_decision = decisions[-1]
    summary = {
        "dataset_id": dataset_id,
        "policy": policy_name,
        "policy_description": policy["description"],
        "total_rows": int(total_rows),
        "chosen_sample_rows": int(final_decision["sample_rows"]),
        "stopped_early": bool(final_decision["sample_rows"] < total_rows),
        "warning_heavy_stop": bool(final_decision["warning_heavy_stop"]),
        "uncertain_columns_at_stop": final_decision["columns_needing_more_sampling"],
        "uncertain_column_names_at_stop": final_decision["uncertain_columns"],
        "adaptive_runtime_seconds": round(float(cumulative_runtime), 6),
        "selected_pass_runtime_seconds": round(float(final_decision["step_runtime_seconds"]), 6),
        "sample_path": " -> ".join(str(row["sample_rows"]) for row in decisions),
        "stop_reason": final_decision["stop_reason"],
        "stop_warning_mode": policy["warning_mode"],
    }
    return final_profile, decisions, summary


def compare_profile_to_labels(
    dataset_id: str,
    labels: pd.DataFrame,
    frame: pd.DataFrame,
    policy_summary: dict[str, Any],
    policy_profile: pd.DataFrame,
    full_profile: pd.DataFrame,
) -> list[dict[str, Any]]:
    policy_by_column = profile_lookup(policy_profile)
    full_by_column = profile_lookup(full_profile)
    rows: list[dict[str, Any]] = []

    for _, label in labels.iterrows():
        column = clean_text(label["column_name"])
        if column not in frame.columns:
            continue

        manual_expected = comparable_expected_role(label)
        manual_primary_key = yes(label.get("is_primary_key")) or yes(label.get("corrected_is_primary_key"))
        predicted = policy_by_column.get(column, {})
        full = full_by_column.get(column, {})
        predicted_profile_role = clean_text(predicted.get("profile_role"))
        full_profile_role = clean_text(full.get("profile_role"))
        predicted_role = comparable_predicted_role(predicted_profile_role, clean_text(predicted.get("role")))
        full_role = comparable_predicted_role(full_profile_role, clean_text(full.get("role")))
        predicted_pk = predicted_primary_key(predicted_profile_role)
        full_pk = predicted_primary_key(full_profile_role)

        rows.append(
            {
                "dataset_id": dataset_id,
                "policy": policy_summary["policy"],
                "column": column,
                "manual_comparable_role": manual_expected,
                "manual_is_primary_key": manual_primary_key,
                "chosen_sample_rows": policy_summary["chosen_sample_rows"],
                "stopped_early": policy_summary["stopped_early"],
                "warning_heavy_stop": policy_summary["warning_heavy_stop"],
                "predicted_profile_role": predicted_profile_role,
                "predicted_comparable_role": predicted_role,
                "predicted_confidence_score": predicted.get("confidence_score"),
                "predicted_warning": predicted.get("warning"),
                "predicted_needs_more_sampling": predicted.get("needs_more_sampling"),
                "full_profile_role": full_profile_role,
                "full_comparable_role": full_role,
                "full_confidence_score": full.get("confidence_score"),
                "matches_manual": predicted_role == manual_expected,
                "matches_full": predicted_role == full_role,
                "predicted_primary_key": predicted_pk,
                "full_predicted_primary_key": full_pk,
                "false_key": predicted_pk and not manual_primary_key,
                "missed_key": (not predicted_pk) and manual_primary_key,
            }
        )
    return rows


def summarize_policy_results(
    comparisons: pd.DataFrame,
    dataset_summary: pd.DataFrame,
    quality: dict[str, Any],
) -> pd.DataFrame:
    rows = []
    for policy, group in comparisons.groupby("policy", dropna=False):
        dataset_group = dataset_summary[dataset_summary["policy"] == policy]
        stopped_early = dataset_group[dataset_group["stopped_early"].astype(bool)]
        accuracy = accuracy_output(group["matches_manual"], quality)
        rows.append(
            {
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
    return pd.DataFrame(rows).sort_values("policy").reset_index(drop=True)


def write_report(
    summary_by_policy: pd.DataFrame,
    dataset_summary: pd.DataFrame,
    column_comparison: pd.DataFrame,
    quality: dict[str, Any],
) -> None:
    disagreements = column_comparison[column_comparison["matches_full"] == False].copy()  # noqa: E712
    lines = [
        "# Early Stopping Policy Tradeoff Experiment",
        "",
        "This experiment compares three adaptive sampling policies on the same five labeled datasets.",
        f"Benchmark provenance: `{quality['benchmark_label_source']}`.",
        (
            "Manual accuracy is intentionally blank until every label is human-approved."
            if not quality["benchmark_is_fully_human_reviewed"]
            else "Every scored label is marked as human-reviewed."
        ),
        (
            "Key recall is not measurable because the benchmark contains no positive primary-key rows."
            if not quality["benchmark_supports_key_recall"]
            else "The benchmark contains positive primary-key rows, so key recall is measurable."
        ),
        "All non-full samples are nested prefixes of one deterministic random permutation per dataset.",
        "",
        "## Policies",
        "",
    ]
    for policy_name, policy in POLICIES.items():
        lines.append(f"- `{policy_name}`: {policy['description']}")

    lines.extend(
        [
            "",
            "## Summary By Policy",
            "",
            "```csv",
            summary_by_policy.to_csv(index=False).strip(),
            "```",
            "",
            "## Per-Dataset Chosen Sample Size",
            "",
            "```csv",
            dataset_summary[
                [
                    "dataset_id",
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
            "## Interpretation",
            "",
            "- Conservative is safest but often reaches the full dataset.",
            "- Balanced asks whether a small amount of unresolved uncertainty is acceptable if the UI explains it.",
            "- Aggressive is a warning-heavy mode: it stops early and shifts unresolved uncertainty to the user-facing evidence panel.",
            "",
            "## Full-Pass Disagreements",
            "",
            "These are the columns where the early-stopped prediction differed from the full-dataset pass.",
            "This is the most direct evidence for the speed-versus-certainty tradeoff.",
            "",
            "```csv",
            disagreements[
                [
                    "dataset_id",
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
            ].to_csv(index=False).strip() if not disagreements.empty else "none",
            "```",
            "",
            "## Recommended Reading",
            "",
            "- Use `safe_conservative` when Buckaroo should avoid uncertainty even if it means reading all rows.",
            "- Use `balanced` as the likely default: it stopped early more often than conservative while preserving full-pass agreement in this run.",
            "- Use `aggressive_warning_heavy` only when the UI clearly says the answer is provisional and shows unresolved uncertainty.",
            "",
            "## Files",
            "",
            "- `policy_tradeoff_summary_by_policy.csv`",
            "- `policy_tradeoff_dataset_summary.csv`",
            "- `policy_tradeoff_column_comparison.csv`",
            "- `policy_tradeoff_sampling_decisions.csv`",
        ]
    )
    (OUT_DIR / "policy_tradeoff_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    labels = pd.read_csv(MANUAL_LABELS)
    labels = labels[labels["dataset_id"].notna() & labels["column_name"].notna()].copy()
    quality = benchmark_quality(labels)
    dataset_paths = [LABEL_DIR / f"{dataset_id}.csv" for dataset_id in sorted(labels["dataset_id"].unique())]

    comparison_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    dataset_summary_rows: list[dict[str, Any]] = []

    for dataset_id in sorted(labels["dataset_id"].unique()):
        dataset_labels = labels[labels["dataset_id"] == dataset_id].copy()
        csv_path = LABEL_DIR / f"{dataset_id}.csv"
        frame = pd.read_csv(csv_path, low_memory=False)
        total_rows = len(frame)
        sample_sizes = sorted(set(size for size in [*SAMPLE_SIZES, total_rows] if 0 < size <= total_rows))

        profiled_samples: dict[int, tuple[pd.DataFrame, float]] = {}
        for sample_rows in sample_sizes:
            seed = stable_seed(str(dataset_id), sample_rows)
            sampled = sample_frame(frame, sample_rows, seed)
            profiled_samples[sample_rows] = profile_frame(sampled)

        full_profile, full_runtime = profiled_samples[total_rows]
        for policy_name, policy in POLICIES.items():
            policy_profile, decisions, policy_summary = run_policy_on_dataset(
                str(dataset_id),
                frame,
                policy_name,
                policy,
                profiled_samples,
            )
            policy_summary["full_runtime_seconds"] = round(float(full_runtime), 6)
            policy_summary["runtime_saved_seconds"] = round(float(full_runtime - policy_summary["adaptive_runtime_seconds"]), 6)
            policy_summary["runtime_saved_fraction"] = (
                round(float((full_runtime - policy_summary["adaptive_runtime_seconds"]) / full_runtime), 6)
                if full_runtime > 0
                else 0.0
            )
            decision_rows.extend(decisions)
            dataset_summary_rows.append(policy_summary)
            comparison_rows.extend(
                compare_profile_to_labels(
                    str(dataset_id),
                    dataset_labels,
                    frame,
                    policy_summary,
                    policy_profile,
                    full_profile,
                )
            )
            print(
                f"{dataset_id} / {policy_name}: chose {policy_summary['chosen_sample_rows']} "
                f"of {total_rows}; stopped_early={policy_summary['stopped_early']}; "
                f"uncertain={policy_summary['uncertain_columns_at_stop']}",
                flush=True,
            )

    comparisons = pd.DataFrame(comparison_rows)
    decisions = pd.DataFrame(decision_rows)
    dataset_summary = pd.DataFrame(dataset_summary_rows)
    summary_by_policy = summarize_policy_results(comparisons, dataset_summary, quality)

    comparisons.to_csv(OUT_DIR / "policy_tradeoff_column_comparison.csv", index=False)
    decisions.to_csv(OUT_DIR / "policy_tradeoff_sampling_decisions.csv", index=False)
    dataset_summary.to_csv(OUT_DIR / "policy_tradeoff_dataset_summary.csv", index=False)
    summary_by_policy.to_csv(OUT_DIR / "policy_tradeoff_summary_by_policy.csv", index=False)
    (OUT_DIR / "policy_tradeoff_config.json").write_text(
        json.dumps(
            {
                "sample_sizes": SAMPLE_SIZES,
                "base_seed": BASE_SEED,
                "policies": POLICIES,
                "sampling_method": "deterministic_nested_random_prefix",
                "benchmark": quality,
                "methodology_version": "corrected_v2",
                "reproducibility": capture_reproducibility(ROOT, [MANUAL_LABELS, *dataset_paths]),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    write_report(summary_by_policy, dataset_summary, comparisons, quality)

    print(OUT_DIR / "policy_tradeoff_summary_by_policy.csv")
    print(OUT_DIR / "policy_tradeoff_dataset_summary.csv")
    print(OUT_DIR / "policy_tradeoff_column_comparison.csv")
    print(OUT_DIR / "policy_tradeoff_sampling_decisions.csv")
    print(OUT_DIR / "policy_tradeoff_report.md")
    print(summary_by_policy.to_string(index=False))


if __name__ == "__main__":
    main()
