"""Simulate confidence-driven adaptive sampling for Buckaroo profiling."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.profile_dataset_shape import profile_columns  # noqa: E402


DEFAULT_MANIFEST = ROOT / "outputs" / "multi_dataset_sampling_profiler_30_datasets_combined" / "dataset_manifest_combined.csv"
DEFAULT_OUT_DIR = ROOT / "outputs" / "adaptive_sampling_policy_30_datasets"
DEFAULT_SAMPLE_SIZES = [100, 500, 1_000, 5_000, 10_000, 50_000]
BASE_SEED = 20260702


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run adaptive sampling policy simulation.")
    parser.add_argument("--dataset-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--sample-sizes", type=str, default=",".join(str(size) for size in DEFAULT_SAMPLE_SIZES))
    parser.add_argument("--base-seed", type=int, default=BASE_SEED)
    parser.add_argument("--max-datasets", type=int, default=0)
    return parser.parse_args()


def parse_sample_sizes(raw: str, total_rows: int) -> list[int]:
    sizes = []
    for token in raw.split(","):
        token = token.strip()
        if token:
            sizes.append(min(int(token.replace("_", "")), total_rows))
    sizes.append(total_rows)
    return sorted(set(size for size in sizes if size > 0))


def profile_sample(frame: pd.DataFrame, sample_rows: int, seed: int) -> pd.DataFrame:
    if sample_rows >= len(frame):
        sample = frame.copy()
    else:
        sample = frame.sample(n=sample_rows, replace=False, random_state=seed).reset_index(drop=True)
    profile, _ = profile_columns(sample)
    return profile


def summarize_profile(dataset_id: str, sample_rows: int, profile: pd.DataFrame) -> dict[str, Any]:
    needs_more = profile[profile["needs_more_sampling"].fillna(False).astype(bool)].copy()
    low_confidence = profile[profile["confidence"] == "low"].copy()
    ambiguous = profile[pd.to_numeric(profile["candidate_confidence_gap"], errors="coerce").fillna(0) < 0.15].copy()

    return {
        "dataset_id": dataset_id,
        "sample_rows": sample_rows,
        "columns_profiled": int(len(profile)),
        "stop_recommended": bool(needs_more.empty),
        "columns_needing_more_sampling": int(len(needs_more)),
        "columns_needing_more_sampling_list": "; ".join(needs_more["column"].astype(str).tolist()),
        "low_confidence_column_count": int(len(low_confidence)),
        "low_confidence_columns": "; ".join(low_confidence["column"].astype(str).tolist()),
        "ambiguous_candidate_column_count": int(len(ambiguous)),
        "ambiguous_candidate_columns": "; ".join(ambiguous["column"].astype(str).tolist()),
        "avg_confidence_score": round(float(profile["confidence_score"].mean()), 4),
        "min_confidence_score": round(float(profile["confidence_score"].min()), 4),
        "avg_candidate_confidence_gap": round(float(profile["candidate_confidence_gap"].mean()), 4),
        "min_candidate_confidence_gap": round(float(profile["candidate_confidence_gap"].min()), 4),
        "avg_sample_uncertainty_margin": round(float(profile["sample_uncertainty_margin"].mean()), 4),
        "max_sample_uncertainty_margin": round(float(profile["sample_uncertainty_margin"].max()), 4),
        "top_candidate_role_counts": "; ".join(
            f"{role}={count}" for role, count in profile["top_candidate_role"].value_counts().items()
        ),
    }


def run_dataset(dataset_record: pd.Series, sample_sizes_raw: str, base_seed: int, dataset_index: int) -> tuple[list[dict[str, Any]], dict[str, Any], pd.DataFrame]:
    dataset_id = str(dataset_record["dataset_id"])
    path = Path(str(dataset_record["local_path"]))
    frame = pd.read_csv(path, low_memory=False)
    sample_sizes = parse_sample_sizes(sample_sizes_raw, len(frame))

    decision_rows: list[dict[str, Any]] = []
    final_profile = pd.DataFrame()
    final_decision: dict[str, Any] | None = None
    for sample_rows in sample_sizes:
        seed = int(base_seed + dataset_index * 1_000_000 + sample_rows)
        profile = profile_sample(frame, sample_rows, seed)
        final_profile = profile.copy()
        decision = summarize_profile(dataset_id, sample_rows, profile)
        decision["total_rows"] = int(len(frame))
        decision["sample_fraction"] = round(float(sample_rows / max(1, len(frame))), 4)
        decision["seed"] = seed
        decision["stop_reason"] = (
            "all_columns_confident"
            if decision["stop_recommended"]
            else "one_or_more_columns_low_confidence_or_ambiguous"
        )
        decision_rows.append(decision)
        final_decision = decision
        if decision["stop_recommended"]:
            break

    assert final_decision is not None
    summary = {
        "dataset_id": dataset_id,
        "total_rows": int(len(frame)),
        "chosen_sample_rows": int(final_decision["sample_rows"]),
        "sample_fraction": final_decision["sample_fraction"],
        "stopped_before_full_data": bool(final_decision["sample_rows"] < len(frame)),
        "stop_reason": final_decision["stop_reason"],
        "final_columns_needing_more_sampling": int(final_decision["columns_needing_more_sampling"]),
        "final_avg_confidence_score": final_decision["avg_confidence_score"],
        "final_min_confidence_score": final_decision["min_confidence_score"],
        "final_avg_candidate_confidence_gap": final_decision["avg_candidate_confidence_gap"],
        "final_max_sample_uncertainty_margin": final_decision["max_sample_uncertainty_margin"],
        "sample_path": " -> ".join(str(row["sample_rows"]) for row in decision_rows),
    }

    if not final_profile.empty:
        final_profile = final_profile.copy()
        final_profile.insert(0, "dataset_id", dataset_id)
        final_profile.insert(1, "chosen_sample_rows", int(final_decision["sample_rows"]))

    return decision_rows, summary, final_profile


def write_report(out_dir: Path, decisions: pd.DataFrame, summary: pd.DataFrame) -> None:
    stopped_early = int(summary["stopped_before_full_data"].sum()) if not summary.empty else 0
    total = int(len(summary))
    median_sample = float(summary["chosen_sample_rows"].median()) if not summary.empty else 0.0
    avg_fraction = float(summary["sample_fraction"].mean()) if not summary.empty else 0.0

    lines = [
        "# Adaptive Sampling Policy Report",
        "",
        f"- Datasets evaluated: `{total}`",
        f"- Datasets stopped before full data: `{stopped_early}`",
        f"- Median chosen sample rows: `{median_sample:.0f}`",
        f"- Average chosen sample fraction: `{avg_fraction:.4f}`",
        "",
        "## Policy",
        "",
        "For each sample size, Buckaroo profiles columns and checks candidate-role confidence. It stops when all columns have high enough chosen-role confidence, a clear gap between the top two candidate roles, and acceptable confidence-interval width. Otherwise, it samples more rows.",
        "",
        "## Files",
        "",
        "- `adaptive_sampling_decisions.csv`: every sample step tried.",
        "- `adaptive_sampling_summary.csv`: final chosen sample size per dataset.",
        "- `adaptive_sampling_final_column_profiles.csv`: final column-level candidate roles and sampling decisions.",
    ]
    (out_dir / "adaptive_sampling_policy_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest = pd.read_csv(args.dataset_manifest)
    if args.max_datasets > 0:
        manifest = manifest.head(args.max_datasets)

    decision_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    final_profiles: list[pd.DataFrame] = []
    for dataset_index, record in manifest.reset_index(drop=True).iterrows():
        rows, summary, final_profile = run_dataset(record, args.sample_sizes, args.base_seed, dataset_index)
        decision_rows.extend(rows)
        summary_rows.append(summary)
        if not final_profile.empty:
            final_profiles.append(final_profile)
        print(
            f"{summary['dataset_id']}: chose {summary['chosen_sample_rows']} rows ({summary['stop_reason']})",
            flush=True,
        )

    decisions = pd.DataFrame(decision_rows)
    summary = pd.DataFrame(summary_rows)
    final_columns = pd.concat(final_profiles, ignore_index=True) if final_profiles else pd.DataFrame()

    decisions.to_csv(args.out_dir / "adaptive_sampling_decisions.csv", index=False)
    summary.to_csv(args.out_dir / "adaptive_sampling_summary.csv", index=False)
    final_columns.to_csv(args.out_dir / "adaptive_sampling_final_column_profiles.csv", index=False)
    (args.out_dir / "adaptive_sampling_config.json").write_text(
        json.dumps(
            {
                "dataset_manifest": str(args.dataset_manifest),
                "sample_sizes": args.sample_sizes,
                "base_seed": args.base_seed,
                "policy": "stop when all columns have high enough confidence, clear candidate gaps, and acceptable interval width",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    write_report(args.out_dir, decisions, summary)

    print(args.out_dir / "adaptive_sampling_decisions.csv")
    print(args.out_dir / "adaptive_sampling_summary.csv")
    print(args.out_dir / "adaptive_sampling_final_column_profiles.csv")
    print(args.out_dir / "adaptive_sampling_policy_report.md")


if __name__ == "__main__":
    main()
