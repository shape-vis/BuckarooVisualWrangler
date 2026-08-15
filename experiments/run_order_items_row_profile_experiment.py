"""Run Buckaroo profiling across row-count slices of order_items.csv.

This harness creates deterministic first-N-row CSV slices, runs Buckaroo's
existing profiler on each slice, and writes comparison tables that can be
checked against external baselines such as Metanome, Deequ, and DataProfiler.
"""

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

from experiments.profile_dataset_shape import (  # noqa: E402
    DEFAULT_CARDINALITY_CHUNK_ROWS,
    DEFAULT_UCC_MAX_ARITY,
    DEFAULT_UCC_MAX_CANDIDATE_COLUMNS,
    DEFAULT_UCC_NEAR_UNIQUE_THRESHOLD,
    profile_dataset,
)


DEFAULT_OUT_DIR = ROOT / "outputs" / "order_items_row_experiment"
DEFAULT_ROW_LIMITS = [None, 1_000_000, 500_000, 250_000, 100_000, 10_000, 1_000, 100, 10]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Buckaroo row-count profiling experiment.")
    parser.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="Path to order_items.csv; datasets are intentionally not committed.",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--detector-rows", type=int, default=2_000)
    parser.add_argument("--profile-rows", type=int, default=None)
    parser.add_argument("--cardinality-chunk-rows", type=int, default=DEFAULT_CARDINALITY_CHUNK_ROWS)
    parser.add_argument("--ucc-max-arity", type=int, default=DEFAULT_UCC_MAX_ARITY)
    parser.add_argument("--ucc-max-candidate-columns", type=int, default=DEFAULT_UCC_MAX_CANDIDATE_COLUMNS)
    parser.add_argument("--ucc-near-unique-threshold", type=float, default=DEFAULT_UCC_NEAR_UNIQUE_THRESHOLD)
    return parser.parse_args()


def count_csv_rows(csv_path: Path) -> int:
    with csv_path.open("rb") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def condition_name(requested_rows: int | None) -> str:
    if requested_rows is None:
        return "full"
    if requested_rows >= 1_000_000:
        return f"{requested_rows // 1_000_000}m"
    if requested_rows >= 1_000:
        return f"{requested_rows // 1_000}k"
    return str(requested_rows)


def write_slice(source_csv: Path, destination_csv: Path, row_count: int) -> None:
    destination_csv.parent.mkdir(parents=True, exist_ok=True)
    reader = pd.read_csv(source_csv, chunksize=50_000, low_memory=False)
    remaining = row_count
    first = True
    for chunk in reader:
        if remaining <= 0:
            break
        output = chunk.head(remaining)
        output.to_csv(destination_csv, index=False, mode="w" if first else "a", header=first)
        remaining -= len(output)
        first = False


def normalize_json_value(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, dict):
        return {str(key): normalize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_json_value(item) for item in value]
    return value


def summarize_against_baselines(
    out_dir: Path,
    buckaroo_columns: pd.DataFrame,
    buckaroo_ucc: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    full_columns = buckaroo_columns[buckaroo_columns["condition"] == "full"].copy()
    if not full_columns.empty:
        rows.extend(
            {
                "source": "Buckaroo full",
                "column": row["column"],
                "type_or_role": row.get("profile_role", row.get("role", "")),
                "null_ratio": row.get("missing_ratio", row.get("null_ratio", "")),
                "unique_ratio": row.get("full_uniqueness_ratio", row.get("uniqueness_ratio", "")),
                "notes": row.get("reason", ""),
            }
            for _, row in full_columns.iterrows()
        )

    deequ_path = ROOT / "outputs" / "deequ_order_items" / "metrics.csv"
    if deequ_path.exists():
        deequ = pd.read_csv(deequ_path)
        useful = deequ[deequ["name"].isin(["Completeness", "Distinctness", "ApproxCountDistinct"])]
        pivot = useful.pivot_table(index="instance", columns="name", values="value", aggfunc="first").reset_index()
        for _, row in pivot.iterrows():
            rows.append(
                {
                    "source": "Deequ full",
                    "column": row["instance"],
                    "type_or_role": "",
                    "null_ratio": 1 - float(row["Completeness"]) if "Completeness" in row and pd.notna(row["Completeness"]) else "",
                    "unique_ratio": row.get("Distinctness", ""),
                    "notes": f"approx_distinct={row.get('ApproxCountDistinct', '')}",
                }
            )

    dataprofiler_path = ROOT / "outputs" / "dataprofiler_order_items_full" / "column_summary.csv"
    if dataprofiler_path.exists():
        data_profile = pd.read_csv(dataprofiler_path)
        for _, row in data_profile.iterrows():
            rows.append(
                {
                    "source": "DataProfiler full",
                    "column": row["column"],
                    "type_or_role": row["data_type"],
                    "null_ratio": row.get("null_ratio", ""),
                    "unique_ratio": row.get("unique_ratio", ""),
                    "notes": f"unique_count={row.get('unique_count', '')}",
                }
            )

    metanome_path = ROOT / "outputs" / "metanome_order_items" / "hyucc_uccs_readable.csv"
    if metanome_path.exists():
        metanome = pd.read_csv(metanome_path)
        for _, row in metanome.iterrows():
            rows.append(
                {
                    "source": "Metanome HyUCC full",
                    "column": row["columns"],
                    "type_or_role": f"UCC arity {row['arity']}",
                    "null_ratio": "",
                    "unique_ratio": "1.0",
                    "notes": "minimal unique column combination",
                }
            )

    comparison = pd.DataFrame(rows)
    comparison.to_csv(out_dir / "baseline_comparison_long.csv", index=False)
    return comparison


def build_markdown_report(summary: pd.DataFrame, columns: pd.DataFrame, uccs: pd.DataFrame) -> str:
    def markdown_table(frame: pd.DataFrame) -> str:
        if frame.empty:
            return "_No rows._"
        rendered = frame.fillna("").astype(str)
        header = "| " + " | ".join(rendered.columns) + " |"
        separator = "| " + " | ".join(["---"] * len(rendered.columns)) + " |"
        body = [
            "| " + " | ".join(str(value).replace("\n", " ") for value in row) + " |"
            for row in rendered.to_numpy()
        ]
        return "\n".join([header, separator, *body])

    full = summary[summary["condition"] == "full"].iloc[0]
    lines = [
        "# order_items row-count profiling experiment",
        "",
        f"Source rows: {int(full['source_total_rows'])}",
        "",
        "## Conditions",
        "",
        markdown_table(
            summary[
            [
                "condition",
                "requested_rows",
                "effective_rows",
                "identifier_columns",
                "categorical_columns",
                "numeric_columns",
                "datetime_columns",
                "ucc_candidate_count",
                "missing_value_rate",
                "baseline_error_rate",
                "runtime_seconds",
            ]
            ]
        ),
        "",
        "## Column role changes",
        "",
    ]

    role_table = columns.pivot_table(
        index="column",
        columns="condition",
        values="profile_role",
        aggfunc="first",
    ).reset_index()
    lines.append(markdown_table(role_table))

    if not uccs.empty:
        lines.extend(["", "## UCC candidates by condition", ""])
        lines.append(
            markdown_table(
            uccs[
                [
                    "condition",
                    "columns",
                    "arity",
                    "uniqueness_ratio",
                    "is_unique",
                    "confidence",
                    "reason",
                ]
            ]
            )
        )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- The source file has fewer than 250K rows, so the 1M, 500K, and 250K requested conditions use the full file.",
            "- External baseline comparisons are saved in `baseline_comparison_long.csv` when their prior outputs are present.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    slice_dir = args.out_dir / "slices"
    run_dir = args.out_dir / "runs"
    slice_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    source_total_rows = count_csv_rows(args.dataset)
    summary_rows: list[dict[str, Any]] = []
    column_frames: list[pd.DataFrame] = []
    ucc_frames: list[pd.DataFrame] = []

    for requested_rows in DEFAULT_ROW_LIMITS:
        effective_rows = source_total_rows if requested_rows is None else min(requested_rows, source_total_rows)
        name = condition_name(requested_rows)
        input_csv = args.dataset if requested_rows is None else slice_dir / f"order_items_{name}.csv"
        if requested_rows is not None:
            write_slice(args.dataset, input_csv, effective_rows)

        profile_rows = args.profile_rows if args.profile_rows is not None else effective_rows
        detector_rows = min(args.detector_rows, effective_rows)
        result, column_profile, ucc_frame = profile_dataset(
            input_csv,
            profile_rows=profile_rows,
            detector_rows=detector_rows,
            cardinality_chunk_rows=args.cardinality_chunk_rows,
            ucc_max_arity=args.ucc_max_arity,
            ucc_max_candidate_columns=args.ucc_max_candidate_columns,
            ucc_near_unique_threshold=args.ucc_near_unique_threshold,
        )

        result.update(
            {
                "condition": name,
                "requested_rows": "full" if requested_rows is None else requested_rows,
                "effective_rows": effective_rows,
                "source_total_rows": source_total_rows,
                "slice_path": str(input_csv),
            }
        )
        summary_rows.append(result)

        condition_dir = run_dir / name
        condition_dir.mkdir(exist_ok=True)
        (condition_dir / "summary.json").write_text(
            json.dumps(normalize_json_value(result), indent=2),
            encoding="utf-8",
        )

        column_profile = column_profile.copy()
        column_profile.insert(0, "effective_rows", effective_rows)
        column_profile.insert(0, "requested_rows", "full" if requested_rows is None else requested_rows)
        column_profile.insert(0, "condition", name)
        column_profile.to_csv(condition_dir / "column_profile.csv", index=False)
        column_frames.append(column_profile)

        if not ucc_frame.empty:
            ucc_frame = ucc_frame.copy()
            ucc_frame.insert(0, "effective_rows", effective_rows)
            ucc_frame.insert(0, "requested_rows", "full" if requested_rows is None else requested_rows)
            ucc_frame.insert(0, "condition", name)
        else:
            ucc_frame = pd.DataFrame(columns=["condition", "requested_rows", "effective_rows"])
        ucc_frame.to_csv(condition_dir / "ucc_candidates.csv", index=False)
        ucc_frames.append(ucc_frame)

    summary = pd.DataFrame(summary_rows)
    columns = pd.concat(column_frames, ignore_index=True)
    uccs = pd.concat(ucc_frames, ignore_index=True)

    summary.to_csv(args.out_dir / "buckaroo_profile_summary_by_rows.csv", index=False)
    columns.to_csv(args.out_dir / "buckaroo_column_profiles_by_rows.csv", index=False)
    uccs.to_csv(args.out_dir / "buckaroo_ucc_candidates_by_rows.csv", index=False)
    summarize_against_baselines(args.out_dir, columns, uccs)
    (args.out_dir / "report.md").write_text(build_markdown_report(summary, columns, uccs), encoding="utf-8")

    print(f"Wrote experiment outputs to {args.out_dir}")


if __name__ == "__main__":
    main()
