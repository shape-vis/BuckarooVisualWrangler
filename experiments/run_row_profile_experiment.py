"""Run Buckaroo profiling across row-count samples for one or more CSV files."""

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


DEFAULT_DATASETS = [
    ROOT / "provided_datasets" / "adult.csv",
    ROOT / "provided_datasets" / "cars.csv",
]
DEFAULT_OUT_DIR = ROOT / "outputs" / "row_profile_experiment"
FIXED_ROW_LIMITS = [100_000, 50_000, 10_000, 5_000, 1_000, 500, 100, 10]
FRACTION_LIMITS = [0.75, 0.50, 0.25, 0.10]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Buckaroo row-count profiling experiments.")
    parser.add_argument("--dataset", action="append", type=Path, dest="datasets")
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


def dataset_slug(csv_path: Path) -> str:
    return csv_path.stem.lower().replace(" ", "_")


def condition_name(kind: str, requested_rows: int | None = None, fraction: float | None = None) -> str:
    if kind == "full":
        return "full"
    if kind == "fraction":
        assert fraction is not None
        return f"{int(fraction * 100)}pct"
    assert requested_rows is not None
    if requested_rows >= 1_000:
        return f"{requested_rows // 1_000}k"
    return str(requested_rows)


def build_conditions(total_rows: int) -> list[dict[str, Any]]:
    conditions: list[dict[str, Any]] = [
        {
            "condition": "full",
            "requested_rows": "full",
            "effective_rows": total_rows,
            "source": "full",
            "sort_key": total_rows + 1,
        }
    ]

    for fraction in FRACTION_LIMITS:
        effective_rows = max(1, int(round(total_rows * fraction)))
        conditions.append(
            {
                "condition": condition_name("fraction", fraction=fraction),
                "requested_rows": f"{int(fraction * 100)}%",
                "effective_rows": effective_rows,
                "source": "fraction",
                "sort_key": effective_rows,
            }
        )

    for requested_rows in FIXED_ROW_LIMITS:
        effective_rows = min(requested_rows, total_rows)
        conditions.append(
            {
                "condition": condition_name("fixed", requested_rows=requested_rows),
                "requested_rows": requested_rows,
                "effective_rows": effective_rows,
                "source": "fixed",
                "sort_key": effective_rows,
            }
        )

    # Deduplicate by condition label first, then by effective rows. This keeps
    # both 100k and 50pct when they are meaningfully different, while avoiding
    # repeated full-size runs when a fixed sample exceeds the dataset size.
    seen_labels: set[str] = set()
    seen_effective_from_fixed: set[int] = set()
    deduped: list[dict[str, Any]] = []
    for condition in sorted(conditions, key=lambda item: item["sort_key"], reverse=True):
        label = str(condition["condition"])
        effective_rows = int(condition["effective_rows"])
        if label in seen_labels:
            continue
        if condition["source"] == "fixed" and effective_rows == total_rows:
            continue
        if condition["source"] == "fixed" and effective_rows in seen_effective_from_fixed:
            continue
        seen_labels.add(label)
        if condition["source"] == "fixed":
            seen_effective_from_fixed.add(effective_rows)
        deduped.append(condition)
    return deduped


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


def run_dataset(csv_path: Path, args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    total_rows = count_csv_rows(csv_path)
    slug = dataset_slug(csv_path)
    dataset_out = args.out_dir / slug
    slice_dir = dataset_out / "slices"
    run_dir = dataset_out / "runs"
    slice_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict[str, Any]] = []
    column_frames: list[pd.DataFrame] = []
    ucc_frames: list[pd.DataFrame] = []

    for condition in build_conditions(total_rows):
        name = str(condition["condition"])
        effective_rows = int(condition["effective_rows"])
        if name == "full":
            input_csv = csv_path
        else:
            input_csv = slice_dir / f"{slug}_{name}.csv"
            write_slice(csv_path, input_csv, effective_rows)

        profile_rows = args.profile_rows if args.profile_rows is not None else effective_rows
        detector_rows = min(args.detector_rows, effective_rows)
        print(f"Profiling {slug}: {name} ({effective_rows} rows)", flush=True)
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
                "dataset": csv_path.name,
                "dataset_slug": slug,
                "condition": name,
                "requested_rows": condition["requested_rows"],
                "effective_rows": effective_rows,
                "source_total_rows": total_rows,
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
        column_profile.insert(0, "requested_rows", condition["requested_rows"])
        column_profile.insert(0, "condition", name)
        column_profile.insert(0, "dataset_slug", slug)
        column_profile.insert(0, "dataset", csv_path.name)
        column_profile.to_csv(condition_dir / "column_profile.csv", index=False)
        column_frames.append(column_profile)

        if not ucc_frame.empty:
            ucc_frame = ucc_frame.copy()
            ucc_frame.insert(0, "effective_rows", effective_rows)
            ucc_frame.insert(0, "requested_rows", condition["requested_rows"])
            ucc_frame.insert(0, "condition", name)
            ucc_frame.insert(0, "dataset_slug", slug)
            ucc_frame.insert(0, "dataset", csv_path.name)
        else:
            ucc_frame = pd.DataFrame(columns=["dataset", "dataset_slug", "condition", "requested_rows", "effective_rows"])
        ucc_frame.to_csv(condition_dir / "ucc_candidates.csv", index=False)
        ucc_frames.append(ucc_frame)

    summary = pd.DataFrame(summary_rows)
    columns = pd.concat(column_frames, ignore_index=True)
    uccs = pd.concat(ucc_frames, ignore_index=True)

    summary.to_csv(dataset_out / "buckaroo_profile_summary_by_rows.csv", index=False)
    columns.to_csv(dataset_out / "buckaroo_column_profiles_by_rows.csv", index=False)
    uccs.to_csv(dataset_out / "buckaroo_ucc_candidates_by_rows.csv", index=False)
    (dataset_out / "report.md").write_text(build_dataset_report(slug, total_rows, summary, columns, uccs), encoding="utf-8")
    return summary, columns, uccs


def build_dataset_report(
    slug: str,
    total_rows: int,
    summary: pd.DataFrame,
    columns: pd.DataFrame,
    uccs: pd.DataFrame,
) -> str:
    selected_summary = summary[
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
    role_table = columns.pivot_table(
        index="column",
        columns="condition",
        values="profile_role",
        aggfunc="first",
    ).reset_index()

    lines = [
        f"# {slug} row-count profiling experiment",
        "",
        f"Source rows: {total_rows}",
        "",
        "## Conditions",
        "",
        markdown_table(selected_summary),
        "",
        "## Column role changes",
        "",
        markdown_table(role_table),
    ]
    if not uccs.empty and "columns" in uccs.columns:
        compact_ucc = uccs[
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
        lines.extend(["", "## UCC candidates", "", markdown_table(compact_ucc)])
    return "\n".join(lines) + "\n"


def build_combined_report(out_dir: Path, summary: pd.DataFrame, columns: pd.DataFrame) -> None:
    overview = summary[
        [
            "dataset",
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
    full_roles = columns[columns["condition"] == "full"][
        ["dataset", "column", "role", "profile_role", "cardinality_ratio", "full_estimated_cardinality_ratio", "reason"]
    ]
    report = "\n".join(
        [
            "# Combined row-count profiling experiment",
            "",
            "## Overview",
            "",
            markdown_table(overview),
            "",
            "## Full-dataset column roles",
            "",
            markdown_table(full_roles),
            "",
        ]
    )
    (out_dir / "combined_report.md").write_text(report, encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    datasets = args.datasets or DEFAULT_DATASETS
    all_summaries: list[pd.DataFrame] = []
    all_columns: list[pd.DataFrame] = []
    all_uccs: list[pd.DataFrame] = []

    for dataset in datasets:
        summary, columns, uccs = run_dataset(dataset, args)
        all_summaries.append(summary)
        all_columns.append(columns)
        all_uccs.append(uccs)

    combined_summary = pd.concat(all_summaries, ignore_index=True)
    combined_columns = pd.concat(all_columns, ignore_index=True)
    combined_uccs = pd.concat(all_uccs, ignore_index=True)
    combined_summary.to_csv(args.out_dir / "combined_buckaroo_profile_summary_by_rows.csv", index=False)
    combined_columns.to_csv(args.out_dir / "combined_buckaroo_column_profiles_by_rows.csv", index=False)
    combined_uccs.to_csv(args.out_dir / "combined_buckaroo_ucc_candidates_by_rows.csv", index=False)
    build_combined_report(args.out_dir, combined_summary, combined_columns)
    print(f"Wrote combined outputs to {args.out_dir}")


if __name__ == "__main__":
    main()
