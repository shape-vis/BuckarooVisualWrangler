"""Create clean runtime-evidence tables for the profiler sampling experiment.

This script turns the raw repeated-sampling outputs into the exact table needed
for reporting runtime next to accuracy and false-key behavior.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = ROOT / "outputs" / "multi_dataset_sampling_profiler_30_datasets_combined"
DEFAULT_OUTPUT_DIR = DEFAULT_INPUT_DIR
SEMANTIC_AGREEMENT_PROFILERS = {
    "old_buckaroo_fixed_threshold",
    "buckaroo_sample_only_adaptive",
    "buckaroo_hll_ucc_lite_adaptive",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lock down runtime evidence for profiler experiments.")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def load_iteration_runs(input_dir: Path) -> pd.DataFrame:
    path = input_dir / "sampling_iteration_runs.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing required experiment file: {path}")

    frame = pd.read_csv(path)
    required = {
        "dataset_id",
        "profiler",
        "sample_rows",
        "iteration",
        "runtime_seconds",
        "semantic_role_accuracy",
        "false_key_rate",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"{path} is missing required columns: {', '.join(missing)}")
    return frame


def clean_runtime_table(runs: pd.DataFrame) -> pd.DataFrame:
    table = runs.copy()
    numeric_columns = [
        "sample_rows",
        "iteration",
        "runtime_seconds",
        "semantic_role_accuracy",
        "primary_key_decision_accuracy",
        "primary_key_precision",
        "primary_key_recall",
        "false_key_rate",
        "average_profile_confidence",
    ]
    for column in numeric_columns:
        if column in table.columns:
            table[column] = pd.to_numeric(table[column], errors="coerce")

    table = table.rename(
        columns={
            "sample_rows": "sample_size",
            "semantic_role_accuracy": "semantic_agreement",
        }
    )
    table["semantic_agreement_applicable"] = table["profiler"].isin(SEMANTIC_AGREEMENT_PROFILERS)
    table["semantic_agreement_status"] = "recorded"
    table.loc[
        table["semantic_agreement_applicable"] & table["semantic_agreement"].isna(),
        "semantic_agreement_status",
    ] = "missing_required"
    table.loc[
        ~table["semantic_agreement_applicable"],
        "semantic_agreement_status",
    ] = "not_applicable_key_only_profiler"

    keep_columns = [
        "dataset_id",
        "profiler",
        "sample_size",
        "iteration",
        "seed",
        "runtime_seconds",
        "semantic_agreement",
        "semantic_agreement_applicable",
        "semantic_agreement_status",
        "primary_key_decision_accuracy",
        "primary_key_precision",
        "primary_key_recall",
        "false_key_rate",
        "average_profile_confidence",
        "predicted_primary_key_count",
        "false_primary_key_count",
        "false_primary_keys",
        "missed_primary_key_count",
        "missed_primary_keys",
        "columns",
        "comparable_columns",
    ]
    present_columns = [column for column in keep_columns if column in table.columns]
    table = table[present_columns].sort_values(["dataset_id", "profiler", "sample_size", "iteration"])
    return table


def build_audit(runtime_table: pd.DataFrame) -> pd.DataFrame:
    grouped = runtime_table.groupby(["dataset_id", "profiler", "sample_size"], dropna=False)
    audit = grouped.agg(
        iterations=("iteration", "count"),
        missing_runtime_count=("runtime_seconds", lambda values: int(values.isna().sum())),
        nonpositive_runtime_count=("runtime_seconds", lambda values: int((values.fillna(-1) <= 0).sum())),
        missing_required_semantic_agreement_count=(
            "semantic_agreement_status",
            lambda values: int((values == "missing_required").sum()),
        ),
        not_applicable_semantic_agreement_count=(
            "semantic_agreement_status",
            lambda values: int((values == "not_applicable_key_only_profiler").sum()),
        ),
        missing_false_key_rate_count=("false_key_rate", lambda values: int(values.isna().sum())),
        avg_runtime_seconds=("runtime_seconds", "mean"),
        median_runtime_seconds=("runtime_seconds", "median"),
        max_runtime_seconds=("runtime_seconds", "max"),
        avg_semantic_agreement=("semantic_agreement", "mean"),
        avg_false_key_rate=("false_key_rate", "mean"),
    ).reset_index()

    audit["runtime_complete"] = (audit["missing_runtime_count"] == 0) & (audit["nonpositive_runtime_count"] == 0)
    audit["metrics_complete"] = (audit["missing_required_semantic_agreement_count"] == 0) & (
        audit["missing_false_key_rate_count"] == 0
    )
    return audit


def build_summary(runtime_table: pd.DataFrame) -> pd.DataFrame:
    return (
        runtime_table.groupby(["profiler", "sample_size"], dropna=False)
        .agg(
            datasets=("dataset_id", "nunique"),
            total_iterations=("iteration", "count"),
            avg_runtime_seconds=("runtime_seconds", "mean"),
            median_runtime_seconds=("runtime_seconds", "median"),
            p95_runtime_seconds=("runtime_seconds", lambda values: values.quantile(0.95)),
            max_runtime_seconds=("runtime_seconds", "max"),
            avg_semantic_agreement=("semantic_agreement", "mean"),
            avg_primary_key_decision_accuracy=("primary_key_decision_accuracy", "mean"),
            avg_primary_key_precision=("primary_key_precision", "mean"),
            avg_primary_key_recall=("primary_key_recall", "mean"),
            avg_false_key_rate=("false_key_rate", "mean"),
            avg_profile_confidence=("average_profile_confidence", "mean"),
        )
        .reset_index()
        .sort_values(["profiler", "sample_size"])
    )


def write_report(
    output_dir: Path,
    runtime_table: pd.DataFrame,
    audit: pd.DataFrame,
    summary: pd.DataFrame,
) -> None:
    total_runs = int(len(runtime_table))
    missing_runtime = int(runtime_table["runtime_seconds"].isna().sum())
    nonpositive_runtime = int((runtime_table["runtime_seconds"].fillna(-1) <= 0).sum())
    semantic_missing_required = int((runtime_table["semantic_agreement_status"] == "missing_required").sum())
    semantic_not_applicable = int(
        (runtime_table["semantic_agreement_status"] == "not_applicable_key_only_profiler").sum()
    )
    false_key_missing = int(runtime_table["false_key_rate"].isna().sum())
    complete_groups = int(audit["runtime_complete"].sum())
    total_groups = int(len(audit))

    fastest = summary.sort_values("median_runtime_seconds").head(10)
    most_accurate = summary.sort_values(["avg_semantic_agreement", "avg_false_key_rate"], ascending=[False, True]).head(10)

    lines = [
        "# Runtime Evidence Audit",
        "",
        "## Files Created",
        "",
        "- `runtime_evidence_by_iteration.csv`: one row per dataset/profiler/sample/iteration.",
        "- `runtime_evidence_audit.csv`: completeness audit by dataset/profiler/sample size.",
        "- `runtime_evidence_summary_by_profiler_size.csv`: aggregate runtime and accuracy summary.",
        "",
        "## Completeness",
        "",
        f"- Total experiment runs: `{total_runs}`",
        f"- Missing runtime values: `{missing_runtime}`",
        f"- Non-positive runtime values: `{nonpositive_runtime}`",
        f"- Missing required semantic agreement values: `{semantic_missing_required}`",
        f"- Semantic agreement marked not applicable for key-only profilers: `{semantic_not_applicable}`",
        f"- Missing false-key-rate values: `{false_key_missing}`",
        f"- Complete runtime groups: `{complete_groups}` of `{total_groups}`",
        "",
        "## Fastest Median Runtime Rows",
        "",
        markdown_table(fastest),
        "",
        "## Highest Semantic Agreement Rows",
        "",
        markdown_table(most_accurate),
        "",
        "## How To Use This In The Paper",
        "",
        "Report runtime beside semantic agreement and false-key rate. This proves the profiler is not only more accurate, but also fast enough to be plausible inside Buckaroo's UI.",
    ]
    (output_dir / "runtime_evidence_report.md").write_text("\n".join(lines), encoding="utf-8")


def markdown_table(frame: pd.DataFrame) -> str:
    """Render a small dataframe as Markdown without optional dependencies."""
    if frame.empty:
        return "_No rows._"

    display = frame.copy()
    for column in display.columns:
        if pd.api.types.is_float_dtype(display[column]):
            display[column] = display[column].map(lambda value: "" if pd.isna(value) else f"{float(value):.4f}")
        else:
            display[column] = display[column].map(lambda value: "" if pd.isna(value) else str(value))

    headers = [str(column) for column in display.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in display.iterrows():
        values = [str(row[column]).replace("|", "\\|") for column in display.columns]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    runs = load_iteration_runs(args.input_dir)
    runtime_table = clean_runtime_table(runs)
    audit = build_audit(runtime_table)
    summary = build_summary(runtime_table)

    runtime_table.to_csv(args.output_dir / "runtime_evidence_by_iteration.csv", index=False)
    audit.to_csv(args.output_dir / "runtime_evidence_audit.csv", index=False)
    summary.to_csv(args.output_dir / "runtime_evidence_summary_by_profiler_size.csv", index=False)
    write_report(args.output_dir, runtime_table, audit, summary)

    print(args.output_dir / "runtime_evidence_by_iteration.csv")
    print(args.output_dir / "runtime_evidence_audit.csv")
    print(args.output_dir / "runtime_evidence_summary_by_profiler_size.csv")
    print(args.output_dir / "runtime_evidence_report.md")


if __name__ == "__main__":
    main()
