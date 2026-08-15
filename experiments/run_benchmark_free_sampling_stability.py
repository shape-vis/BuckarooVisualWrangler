"""Benchmark-free repeated-sampling stability evaluation for Buckaroo.

This experiment deliberately does *not* claim semantic accuracy: it has no
human answer key.  Instead, it asks whether the current confidence-aware
Buckaroo profiler gives the same answer when it sees different random samples
of the same dataset, and how much work each early-stopping policy avoids
relative to a full-data profile.
"""

from __future__ import annotations

import argparse
from collections import Counter
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


DEFAULT_MANIFEST = ROOT / "outputs" / "multi_dataset_sampling_profiler_30_datasets_combined" / "dataset_manifest_combined.csv"
DEFAULT_OUT_DIR = ROOT / "outputs" / "benchmark_free_sampling_stability_30_datasets"
DEFAULT_SAMPLE_SIZES = [100, 500, 1_000, 5_000, 10_000, 50_000]
DEFAULT_ITERATIONS = 10
BASE_SEED = 20260713

POLICIES: dict[str, dict[str, Any]] = {
    "safe_conservative": {
        "minimum_rows": 100,
        "minimum_average_confidence": 0.0,
        "minimum_column_confidence": 0.0,
        "maximum_columns_needing_more": 0,
        "description": "Stops only when every column says its sample evidence is sufficient.",
    },
    "balanced": {
        "minimum_rows": 500,
        "minimum_average_confidence": 0.86,
        "minimum_column_confidence": 0.80,
        "maximum_columns_needing_more": 2,
        "description": "Stops when the overall result is strong and remaining uncertainty is explainable.",
    },
    "aggressive_warning_heavy": {
        "minimum_rows": 100,
        "minimum_average_confidence": 0.72,
        "minimum_column_confidence": 0.50,
        "maximum_columns_needing_more": 999,
        "description": "Returns a preview quickly and leaves uncertainty visible as warnings.",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate current Buckaroo sampling stability without human labels."
    )
    parser.add_argument("--dataset-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--sample-sizes",
        type=str,
        default=",".join(str(value) for value in DEFAULT_SAMPLE_SIZES),
    )
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--base-seed", type=int, default=BASE_SEED)
    parser.add_argument("--max-datasets", type=int, default=0)
    return parser.parse_args()


def parse_sample_sizes(raw: str, total_rows: int) -> list[int]:
    sizes: set[int] = {total_rows}
    for token in raw.split(","):
        token = token.strip().lower().replace("_", "")
        if token:
            sizes.add(min(int(token), total_rows))
    return sorted(size for size in sizes if size > 0)


def stable_seed(base_seed: int, dataset_id: str, sample_rows: int, iteration: int) -> int:
    digest = hashlib.sha256(dataset_id.encode("utf-8")).hexdigest()
    dataset_offset = int(digest[:8], 16) % 1_000_000
    return int(base_seed + dataset_offset + sample_rows * 101 + iteration)


def profile_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    started = time.perf_counter()
    profile, _ = profile_columns(frame)
    return profile.copy(), round(time.perf_counter() - started, 6)


def bool_value(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def numeric_value(record: dict[str, Any], field: str) -> float:
    value = pd.to_numeric(record.get(field), errors="coerce")
    return 0.0 if pd.isna(value) else float(value)


def is_key_candidate(record: dict[str, Any]) -> bool:
    return clean_text(record.get("profile_role")).lower() == "identifier"


def has_warning(record: dict[str, Any]) -> bool:
    return bool(clean_text(record.get("warning")) or clean_text(record.get("adaptive_warning")))


def profile_metrics(profile: pd.DataFrame) -> dict[str, Any]:
    records = profile.to_dict(orient="records")
    if not records:
        return {
            "columns_profiled": 0,
            "average_confidence_score": 0.0,
            "minimum_confidence_score": 0.0,
            "average_candidate_gap": 0.0,
            "minimum_candidate_gap": 0.0,
            "columns_needing_more_sampling": 0,
            "warning_columns": 0,
            "key_candidate_columns": 0,
        }

    confidences = [numeric_value(record, "confidence_score") for record in records]
    gaps = [numeric_value(record, "candidate_confidence_gap") for record in records]
    return {
        "columns_profiled": len(records),
        "average_confidence_score": round(sum(confidences) / len(confidences), 6),
        "minimum_confidence_score": round(min(confidences), 6),
        "average_candidate_gap": round(sum(gaps) / len(gaps), 6),
        "minimum_candidate_gap": round(min(gaps), 6),
        "columns_needing_more_sampling": sum(bool_value(record.get("needs_more_sampling")) for record in records),
        "warning_columns": sum(has_warning(record) for record in records),
        "key_candidate_columns": sum(is_key_candidate(record) for record in records),
    }


def policy_decision(sample_rows: int, total_rows: int, metrics: dict[str, Any]) -> dict[str, bool]:
    decisions: dict[str, bool] = {}
    for policy_name, policy in POLICIES.items():
        if sample_rows >= total_rows:
            decisions[policy_name] = True
            continue
        decisions[policy_name] = bool(
            sample_rows >= int(policy["minimum_rows"])
            and metrics["average_confidence_score"] >= float(policy["minimum_average_confidence"])
            and metrics["minimum_confidence_score"] >= float(policy["minimum_column_confidence"])
            and metrics["columns_needing_more_sampling"] <= int(policy["maximum_columns_needing_more"])
        )
    return decisions


def profile_lookup(profile: pd.DataFrame) -> dict[str, dict[str, Any]]:
    return {clean_text(record.get("column")): record for record in profile.to_dict(orient="records")}


def compare_to_full(
    dataset_id: str,
    sample_rows: int,
    iteration: int,
    seed: int,
    profile: pd.DataFrame,
    full_lookup: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sampled_lookup = profile_lookup(profile)
    for column, sampled in sampled_lookup.items():
        full = full_lookup.get(column, {})
        sampled_role = clean_text(sampled.get("profile_role"))
        full_role = clean_text(full.get("profile_role"))
        sampled_candidate = clean_text(sampled.get("chosen_candidate_role"))
        full_candidate = clean_text(full.get("chosen_candidate_role"))
        sampled_key = is_key_candidate(sampled)
        full_key = is_key_candidate(full)
        sampled_warning = has_warning(sampled)
        full_warning = has_warning(full)
        rows.append(
            {
                "dataset_id": dataset_id,
                "sample_rows": sample_rows,
                "iteration": iteration,
                "seed": seed,
                "column": column,
                "sampled_profile_role": sampled_role,
                "full_profile_role": full_role,
                "profile_role_matches_full_pass": sampled_role == full_role,
                "sampled_chosen_candidate_role": sampled_candidate,
                "full_chosen_candidate_role": full_candidate,
                "candidate_role_matches_full_pass": sampled_candidate == full_candidate,
                "sampled_is_key_candidate": sampled_key,
                "full_is_key_candidate": full_key,
                "key_candidate_matches_full_pass": sampled_key == full_key,
                "key_candidate_flip_vs_full_pass": sampled_key != full_key,
                "sampled_has_warning": sampled_warning,
                "full_has_warning": full_warning,
                "warning_matches_full_pass": sampled_warning == full_warning,
                "sampled_confidence_score": round(numeric_value(sampled, "confidence_score"), 6),
                "full_confidence_score": round(numeric_value(full, "confidence_score"), 6),
                "confidence_delta_vs_full_pass": round(
                    numeric_value(sampled, "confidence_score") - numeric_value(full, "confidence_score"), 6
                ),
                "candidate_confidence_gap": round(numeric_value(sampled, "candidate_confidence_gap"), 6),
                "needs_more_sampling": bool_value(sampled.get("needs_more_sampling")),
                "warning": clean_text(sampled.get("warning")),
                "adaptive_warning": clean_text(sampled.get("adaptive_warning")),
            }
        )

    compared = pd.DataFrame(rows)
    if compared.empty:
        return rows, {
            "role_agreement_with_full_pass": 0.0,
            "candidate_agreement_with_full_pass": 0.0,
            "key_candidate_flip_rate_vs_full_pass": 0.0,
            "warning_agreement_with_full_pass": 0.0,
        }
    return rows, {
        "role_agreement_with_full_pass": round(float(compared["profile_role_matches_full_pass"].mean()), 6),
        "candidate_agreement_with_full_pass": round(float(compared["candidate_role_matches_full_pass"].mean()), 6),
        "key_candidate_flip_rate_vs_full_pass": round(float(compared["key_candidate_flip_vs_full_pass"].mean()), 6),
        "warning_agreement_with_full_pass": round(float(compared["warning_matches_full_pass"].mean()), 6),
    }


def summarize_by_dataset_size(iterations: pd.DataFrame, columns: pd.DataFrame) -> pd.DataFrame:
    if iterations.empty:
        return pd.DataFrame()
    grouped = iterations.groupby(["dataset_id", "sample_rows"], dropna=False)
    summary = grouped.agg(
        total_rows=("total_rows", "first"),
        iterations=("iteration", "count"),
        average_runtime_seconds=("runtime_seconds", "mean"),
        median_runtime_seconds=("runtime_seconds", "median"),
        average_role_agreement_with_full_pass=("role_agreement_with_full_pass", "mean"),
        minimum_role_agreement_with_full_pass=("role_agreement_with_full_pass", "min"),
        average_candidate_agreement_with_full_pass=("candidate_agreement_with_full_pass", "mean"),
        average_key_candidate_flip_rate_vs_full_pass=("key_candidate_flip_rate_vs_full_pass", "mean"),
        average_warning_agreement_with_full_pass=("warning_agreement_with_full_pass", "mean"),
        average_confidence_score=("average_confidence_score", "mean"),
        average_candidate_gap=("average_candidate_gap", "mean"),
        average_columns_needing_more_sampling=("columns_needing_more_sampling", "mean"),
        average_warning_columns=("warning_columns", "mean"),
        safe_early_stop_rate=("safe_conservative_stop", "mean"),
        balanced_early_stop_rate=("balanced_stop", "mean"),
        aggressive_early_stop_rate=("aggressive_warning_heavy_stop", "mean"),
    ).reset_index()

    if not columns.empty:
        stability = (
            columns.groupby(["dataset_id", "sample_rows", "column"], dropna=False)["sampled_profile_role"]
            .agg(lambda values: max(Counter(values).values()) / len(values))
            .rename("within_size_role_stability")
            .reset_index()
            .groupby(["dataset_id", "sample_rows"], dropna=False)["within_size_role_stability"]
            .mean()
            .reset_index()
        )
        summary = summary.merge(stability, on=["dataset_id", "sample_rows"], how="left")

    numeric_columns = summary.select_dtypes(include="number").columns
    summary[numeric_columns] = summary[numeric_columns].round(6)
    return summary.sort_values(["dataset_id", "sample_rows"]).reset_index(drop=True)


def summarize_policy_outcomes(iterations: pd.DataFrame, full_runtime: pd.DataFrame) -> pd.DataFrame:
    if iterations.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    full_runtime_lookup = full_runtime.set_index("dataset_id")["full_runtime_seconds"].to_dict()
    for (dataset_id, iteration), run in iterations.sort_values("sample_rows").groupby(["dataset_id", "iteration"]):
        total_rows = int(run["total_rows"].iloc[0])
        full_seconds = float(full_runtime_lookup.get(dataset_id, 0.0))
        for policy_name in POLICIES:
            stop_column = f"{policy_name}_stop"
            eligible = run[run[stop_column].astype(bool)]
            reached_full_pass = eligible.empty
            chosen = eligible.iloc[0] if not reached_full_pass else None
            chosen_runtime = full_seconds if reached_full_pass else float(chosen["runtime_seconds"])
            rows.append(
                {
                    "dataset_id": dataset_id,
                    "iteration": int(iteration),
                    "policy": policy_name,
                    "total_rows": total_rows,
                    "chosen_sample_rows": total_rows if reached_full_pass else int(chosen["sample_rows"]),
                    "stopped_before_full_pass": False if reached_full_pass else int(chosen["sample_rows"]) < total_rows,
                    "estimated_single_pass_runtime_seconds": round(chosen_runtime, 6),
                    "full_pass_runtime_seconds": round(full_seconds, 6),
                    "estimated_runtime_saved_fraction": round(
                        max(0.0, 1.0 - chosen_runtime / full_seconds) if full_seconds > 0 else 0.0, 6
                    ),
                    "role_agreement_with_full_pass": 1.0 if reached_full_pass else float(chosen["role_agreement_with_full_pass"]),
                    "key_candidate_flip_rate_vs_full_pass": 0.0 if reached_full_pass else float(chosen["key_candidate_flip_rate_vs_full_pass"]),
                    "warning_agreement_with_full_pass": 1.0 if reached_full_pass else float(chosen["warning_agreement_with_full_pass"]),
                    "columns_needing_more_sampling": 0 if reached_full_pass else int(chosen["columns_needing_more_sampling"]),
                }
            )
    return pd.DataFrame(rows)


def dataframe_to_markdown(frame: pd.DataFrame) -> list[str]:
    """Render small report tables without requiring pandas' optional tabulate package."""

    if frame.empty:
        return ["No rows were produced."]
    headers = [str(column) for column in frame.columns]
    rows = [[str(value) for value in record] for record in frame.itertuples(index=False, name=None)]
    divider = ["---"] * len(headers)
    return [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(divider) + " |",
        *["| " + " | ".join(row) + " |" for row in rows],
    ]


def build_report(
    manifest: pd.DataFrame,
    by_size: pd.DataFrame,
    policies: pd.DataFrame,
) -> str:
    total_datasets = len(manifest)
    lines = [
        "# Benchmark-Free Sampling Stability Report",
        "",
        f"- Datasets: `{total_datasets}` public CSV files",
        "- Profiler: current Buckaroo confidence-interval and semantic-safeguard profiler",
        "- Reference: each dataset's own full-pass Buckaroo profile",
        "- Important limitation: agreement with full pass measures stability, not semantic correctness.",
        "",
        "## What This Establishes",
        "",
        "Repeated random samples reveal whether the profiler is repeatable, whether its key suggestions flip, how warnings behave, and how much single-pass work each policy may avoid. Human-reviewed labels are still required later for correctness, false-key accuracy, and confidence calibration.",
        "",
        "## Overall Sampling Stability",
        "",
    ]
    if not by_size.empty:
        overall = (
            by_size.groupby("sample_rows", dropna=False)
            .agg(
                datasets=("dataset_id", "nunique"),
                median_runtime_seconds=("median_runtime_seconds", "median"),
                average_role_agreement_with_full_pass=("average_role_agreement_with_full_pass", "mean"),
                average_role_stability=("within_size_role_stability", "mean"),
                average_key_candidate_flip_rate=("average_key_candidate_flip_rate_vs_full_pass", "mean"),
                balanced_early_stop_rate=("balanced_early_stop_rate", "mean"),
            )
            .reset_index()
        )
        lines.extend(dataframe_to_markdown(overall.round(4)))
    lines.extend(["", "## Policy Outcomes", ""])
    if not policies.empty:
        policy_summary = (
            policies.groupby("policy", dropna=False)
            .agg(
                dataset_runs=("dataset_id", "count"),
                early_stop_rate=("stopped_before_full_pass", "mean"),
                median_runtime_saved_fraction=("estimated_runtime_saved_fraction", "median"),
                average_role_agreement_with_full_pass=("role_agreement_with_full_pass", "mean"),
                average_key_candidate_flip_rate=("key_candidate_flip_rate_vs_full_pass", "mean"),
            )
            .reset_index()
        )
        lines.extend(dataframe_to_markdown(policy_summary.round(4)))
    lines.extend(
        [
            "",
            "## Output Files",
            "",
            "- `full_pass_profiles.csv`: one current-profiler reference profile per dataset.",
            "- `sampling_iteration_runs.csv`: one aggregate row per random sample.",
            "- `sampling_column_predictions.csv`: every sampled column compared with its full-pass version.",
            "- `sampling_summary_by_dataset_size.csv`: stability, agreement, warning, runtime, and stop rates by dataset and size.",
            "- `policy_outcomes_by_seed.csv`: selected size and estimated single-pass savings for each policy and seed.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest = pd.read_csv(args.dataset_manifest)
    if args.max_datasets > 0:
        manifest = manifest.head(args.max_datasets).copy()

    full_profile_frames: list[pd.DataFrame] = []
    full_runtime_rows: list[dict[str, Any]] = []
    iteration_rows: list[dict[str, Any]] = []
    column_rows: list[dict[str, Any]] = []

    for dataset_index, dataset in manifest.reset_index(drop=True).iterrows():
        dataset_id = clean_text(dataset["dataset_id"])
        frame = pd.read_csv(Path(clean_text(dataset["local_path"])), low_memory=False)
        frame.columns = [str(column) for column in frame.columns]
        total_rows = len(frame)
        print(f"Dataset {dataset_index + 1}/{len(manifest)}: {dataset_id} ({total_rows} rows, {frame.shape[1]} columns)", flush=True)

        full_profile, full_runtime_seconds = profile_frame(frame)
        full_lookup = profile_lookup(full_profile)
        full_saved = full_profile.copy()
        full_saved.insert(0, "dataset_id", dataset_id)
        full_profile_frames.append(full_saved)
        full_runtime_rows.append(
            {
                "dataset_id": dataset_id,
                "total_rows": total_rows,
                "column_count": int(frame.shape[1]),
                "full_runtime_seconds": full_runtime_seconds,
            }
        )

        for sample_rows in parse_sample_sizes(args.sample_sizes, total_rows):
            size_iterations = 1 if sample_rows >= total_rows else args.iterations
            for iteration in range(1, size_iterations + 1):
                seed = stable_seed(args.base_seed, dataset_id, sample_rows, iteration)
                sample = frame if sample_rows >= total_rows else frame.sample(
                    n=sample_rows, replace=False, random_state=seed
                ).reset_index(drop=True)
                profile, runtime_seconds = profile_frame(sample)
                metrics = profile_metrics(profile)
                decisions = policy_decision(sample_rows, total_rows, metrics)
                comparisons, agreement = compare_to_full(
                    dataset_id, sample_rows, iteration, seed, profile, full_lookup
                )
                column_rows.extend(comparisons)
                iteration_rows.append(
                    {
                        "dataset_id": dataset_id,
                        "total_rows": total_rows,
                        "column_count": int(frame.shape[1]),
                        "sample_rows": sample_rows,
                        "sample_fraction": round(sample_rows / max(1, total_rows), 6),
                        "iteration": iteration,
                        "seed": seed,
                        "sampling_method": "full_dataset" if sample_rows >= total_rows else "random_without_replacement",
                        "runtime_seconds": runtime_seconds,
                        **metrics,
                        **agreement,
                        "safe_conservative_stop": decisions["safe_conservative"],
                        "balanced_stop": decisions["balanced"],
                        "aggressive_warning_heavy_stop": decisions["aggressive_warning_heavy"],
                    }
                )
                print(f"  {sample_rows} rows, iteration {iteration}/{size_iterations}, {runtime_seconds:.3f}s", flush=True)

    full_profiles = pd.concat(full_profile_frames, ignore_index=True) if full_profile_frames else pd.DataFrame()
    full_runtimes = pd.DataFrame(full_runtime_rows)
    iterations = pd.DataFrame(iteration_rows)
    columns = pd.DataFrame(column_rows)
    by_size = summarize_by_dataset_size(iterations, columns)
    policies = summarize_policy_outcomes(iterations, full_runtimes)
    policy_summary = (
        policies.groupby("policy", dropna=False)
        .agg(
            dataset_runs=("dataset_id", "count"),
            early_stop_rate=("stopped_before_full_pass", "mean"),
            median_runtime_saved_fraction=("estimated_runtime_saved_fraction", "median"),
            average_role_agreement_with_full_pass=("role_agreement_with_full_pass", "mean"),
            average_key_candidate_flip_rate=("key_candidate_flip_rate_vs_full_pass", "mean"),
        )
        .reset_index()
        .round(6)
    ) if not policies.empty else pd.DataFrame()

    output_files = {
        "dataset_manifest.csv": args.out_dir / "dataset_manifest.csv",
        "full_pass_profiles.csv": args.out_dir / "full_pass_profiles.csv",
        "full_pass_runtime.csv": args.out_dir / "full_pass_runtime.csv",
        "sampling_iteration_runs.csv": args.out_dir / "sampling_iteration_runs.csv",
        "sampling_column_predictions.csv": args.out_dir / "sampling_column_predictions.csv",
        "sampling_summary_by_dataset_size.csv": args.out_dir / "sampling_summary_by_dataset_size.csv",
        "policy_outcomes_by_seed.csv": args.out_dir / "policy_outcomes_by_seed.csv",
        "policy_summary.csv": args.out_dir / "policy_summary.csv",
        "experiment_config.json": args.out_dir / "experiment_config.json",
        "report.md": args.out_dir / "report.md",
    }
    manifest.to_csv(output_files["dataset_manifest.csv"], index=False)
    full_profiles.to_csv(output_files["full_pass_profiles.csv"], index=False)
    full_runtimes.to_csv(output_files["full_pass_runtime.csv"], index=False)
    iterations.to_csv(output_files["sampling_iteration_runs.csv"], index=False)
    columns.to_csv(output_files["sampling_column_predictions.csv"], index=False)
    by_size.to_csv(output_files["sampling_summary_by_dataset_size.csv"], index=False)
    policies.to_csv(output_files["policy_outcomes_by_seed.csv"], index=False)
    policy_summary.to_csv(output_files["policy_summary.csv"], index=False)
    output_files["experiment_config.json"].write_text(
        json.dumps(
            {
                "dataset_manifest": str(args.dataset_manifest),
                "dataset_count": int(len(manifest)),
                "sample_sizes": args.sample_sizes,
                "iterations_per_non_full_size": args.iterations,
                "base_seed": args.base_seed,
                "sampling_method": "random without replacement; deterministic seed per dataset, size, and iteration",
                "profiler": "current Buckaroo confidence-interval and semantic-safeguard profiler",
                "reference": "full-pass output of the same current profiler per dataset",
                "limitation": "not a human-labeled semantic-accuracy benchmark",
                "policies": POLICIES,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    output_files["report.md"].write_text(build_report(manifest, by_size, policies), encoding="utf-8")

    print(f"Wrote benchmark-free stability outputs to {args.out_dir}", flush=True)


if __name__ == "__main__":
    main()
