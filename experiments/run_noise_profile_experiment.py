"""Run Buckaroo profiling across controlled noise levels for CSV datasets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import shutil
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
    ROOT / "provided_datasets" / "games.csv",
]
DEFAULT_OUT_DIR = ROOT / "outputs" / "noise_profile_experiment"
NOISE_LEVELS = [0.0, 0.05, 0.10, 0.20]
RANDOM_SEED = 42


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Buckaroo profiling across noise levels.")
    parser.add_argument("--dataset", action="append", type=Path, dest="datasets")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--noise-level", action="append", type=float, dest="noise_levels")
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    parser.add_argument("--detector-rows", type=int, default=2_000)
    parser.add_argument("--profile-rows", type=int, default=None)
    parser.add_argument("--cardinality-chunk-rows", type=int, default=DEFAULT_CARDINALITY_CHUNK_ROWS)
    parser.add_argument("--ucc-max-arity", type=int, default=DEFAULT_UCC_MAX_ARITY)
    parser.add_argument("--ucc-max-candidate-columns", type=int, default=DEFAULT_UCC_MAX_CANDIDATE_COLUMNS)
    parser.add_argument("--ucc-near-unique-threshold", type=float, default=DEFAULT_UCC_NEAR_UNIQUE_THRESHOLD)
    return parser.parse_args()


def dataset_slug(csv_path: Path) -> str:
    return csv_path.stem.lower().replace(" ", "_")


def noise_label(level: float) -> str:
    return f"{int(round(level * 100))}pct"


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


def infer_column_kinds(frame: pd.DataFrame) -> dict[str, str]:
    kinds: dict[str, str] = {}
    sample = frame.head(10_000)
    for column in frame.columns:
        values = sample[column].dropna().astype(str).str.strip()
        non_empty = values[values != ""]
        lower_name = column.lower()
        if non_empty.empty:
            kinds[column] = "text"
            continue
        numeric_ratio = pd.to_numeric(non_empty, errors="coerce").notna().mean()
        datetime_ratio = pd.to_datetime(non_empty, errors="coerce", format="mixed").notna().mean()
        unique_ratio = non_empty.nunique(dropna=True) / max(1, len(non_empty))
        if "date" in lower_name or lower_name.endswith("_at") or datetime_ratio >= 0.85:
            kinds[column] = "datetime"
        elif "id" in lower_name or lower_name in {"sku"}:
            kinds[column] = "id"
        elif numeric_ratio >= 0.90 and unique_ratio > 0.20:
            kinds[column] = "numeric"
        elif numeric_ratio >= 0.90:
            kinds[column] = "numeric_code"
        elif unique_ratio <= 0.20:
            kinds[column] = "category"
        else:
            kinds[column] = "text"
    return kinds


def noisy_value(kind: str, row_idx: int, col_idx: int) -> str:
    options_by_kind = {
        "id": ["", "NOISE_DUPLICATE_ID", "###", f"BROKEN_ID_{row_idx % 17}"],
        "numeric": ["", "not_a_number", "-999999", "9999999999"],
        "numeric_code": ["", "not_a_code", "-1", "999999"],
        "datetime": ["", "not_a_date", "3026-99-99", "13/99/9999"],
        "category": ["", "UNKNOWN_NOISE", "???", "not_applicable"],
        "text": ["", "NOISE_TEXT_VALUE", "???", f"corrupted text {col_idx}"],
    }
    options = options_by_kind.get(kind, options_by_kind["text"])
    return options[(row_idx + col_idx) % len(options)]


def inject_noise(
    source_csv: Path,
    destination_csv: Path,
    noise_level: float,
    seed: int,
) -> dict[str, Any]:
    destination_csv.parent.mkdir(parents=True, exist_ok=True)
    if noise_level <= 0:
        shutil.copyfile(source_csv, destination_csv)
        row_count = max(0, sum(1 for _ in source_csv.open("rb")) - 1)
        return {
            "noise_level": noise_level,
            "noise_label": noise_label(noise_level),
            "rows": row_count,
            "columns": None,
            "cells": None,
            "cells_replaced": 0,
            "replacement_rate": 0.0,
        }

    frame = pd.read_csv(source_csv, dtype=object, low_memory=False)
    kinds = infer_column_kinds(frame)
    row_count, column_count = frame.shape
    total_cells = row_count * column_count
    cells_to_replace = int(round(total_cells * noise_level))
    rng = random.Random(seed)
    selected = rng.sample(range(total_cells), cells_to_replace)

    replacements_by_column = {column: 0 for column in frame.columns}
    columns = list(frame.columns)
    for flat_index in selected:
        row_idx, col_idx = divmod(flat_index, column_count)
        column = columns[col_idx]
        frame.iat[row_idx, col_idx] = noisy_value(kinds[column], row_idx, col_idx)
        replacements_by_column[column] += 1

    frame.to_csv(destination_csv, index=False)
    return {
        "noise_level": noise_level,
        "noise_label": noise_label(noise_level),
        "rows": row_count,
        "columns": column_count,
        "cells": total_cells,
        "cells_replaced": cells_to_replace,
        "replacement_rate": cells_to_replace / total_cells if total_cells else 0.0,
        "column_kinds": kinds,
        "replacements_by_column": replacements_by_column,
    }


def run_dataset(csv_path: Path, args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    slug = dataset_slug(csv_path)
    dataset_out = args.out_dir / slug
    noisy_dir = dataset_out / "noisy_inputs"
    run_dir = dataset_out / "runs"
    noisy_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict[str, Any]] = []
    noise_rows: list[dict[str, Any]] = []
    column_frames: list[pd.DataFrame] = []
    ucc_frames: list[pd.DataFrame] = []

    for level in sorted(args.noise_levels if args.noise_levels is not None else NOISE_LEVELS):
        label = noise_label(level)
        noisy_csv = noisy_dir / f"{slug}_noise_{label}.csv"
        print(f"Creating {slug} noise {label}", flush=True)
        noise_meta = inject_noise(csv_path, noisy_csv, level, args.seed + int(level * 10_000))
        noise_meta.update(
            {
                "dataset": csv_path.name,
                "dataset_slug": slug,
                "source_path": str(csv_path),
                "noisy_path": str(noisy_csv),
            }
        )
        noise_rows.append(noise_meta)

        profile_rows = args.profile_rows if args.profile_rows is not None else int(noise_meta["rows"])
        detector_rows = min(args.detector_rows, int(noise_meta["rows"]))
        print(f"Profiling {slug}: noise {label} ({noise_meta['rows']} rows)", flush=True)
        result, column_profile, ucc_frame = profile_dataset(
            noisy_csv,
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
                "noise_level": level,
                "noise_label": label,
                "source_path": str(csv_path),
                "noisy_path": str(noisy_csv),
                "cells_replaced": noise_meta["cells_replaced"],
                "replacement_rate": noise_meta["replacement_rate"],
            }
        )
        summary_rows.append(result)

        condition_dir = run_dir / f"noise_{label}"
        condition_dir.mkdir(exist_ok=True)
        (condition_dir / "summary.json").write_text(
            json.dumps(normalize_json_value(result), indent=2),
            encoding="utf-8",
        )
        (condition_dir / "noise_meta.json").write_text(
            json.dumps(normalize_json_value(noise_meta), indent=2),
            encoding="utf-8",
        )

        column_profile = column_profile.copy()
        column_profile.insert(0, "noise_label", label)
        column_profile.insert(0, "noise_level", level)
        column_profile.insert(0, "dataset_slug", slug)
        column_profile.insert(0, "dataset", csv_path.name)
        column_profile.to_csv(condition_dir / "column_profile.csv", index=False)
        column_frames.append(column_profile)

        if not ucc_frame.empty:
            ucc_frame = ucc_frame.copy()
            ucc_frame.insert(0, "noise_label", label)
            ucc_frame.insert(0, "noise_level", level)
            ucc_frame.insert(0, "dataset_slug", slug)
            ucc_frame.insert(0, "dataset", csv_path.name)
        else:
            ucc_frame = pd.DataFrame(columns=["dataset", "dataset_slug", "noise_level", "noise_label"])
        ucc_frame.to_csv(condition_dir / "ucc_candidates.csv", index=False)
        ucc_frames.append(ucc_frame)

    summary = pd.DataFrame(summary_rows)
    noise = pd.DataFrame(noise_rows)
    columns = pd.concat(column_frames, ignore_index=True)
    uccs = pd.concat(ucc_frames, ignore_index=True)

    summary.to_csv(dataset_out / "buckaroo_profile_summary_by_noise.csv", index=False)
    noise.to_csv(dataset_out / "noise_injection_summary.csv", index=False)
    columns.to_csv(dataset_out / "buckaroo_column_profiles_by_noise.csv", index=False)
    uccs.to_csv(dataset_out / "buckaroo_ucc_candidates_by_noise.csv", index=False)
    (dataset_out / "report.md").write_text(build_dataset_report(slug, summary, columns, uccs), encoding="utf-8")
    return summary, noise, columns, uccs


def build_dataset_report(slug: str, summary: pd.DataFrame, columns: pd.DataFrame, uccs: pd.DataFrame) -> str:
    selected_summary = summary[
        [
            "noise_label",
            "total_rows",
            "total_columns",
            "cells_replaced",
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
        columns="noise_label",
        values="profile_role",
        aggfunc="first",
    ).reset_index()
    lines = [
        f"# {slug} noise profiling experiment",
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
                "noise_label",
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
            "noise_label",
            "total_rows",
            "total_columns",
            "cells_replaced",
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
    role_changes = columns.pivot_table(
        index=["dataset", "column"],
        columns="noise_label",
        values="profile_role",
        aggfunc="first",
    ).reset_index()
    report = "\n".join(
        [
            "# Combined noise profiling experiment",
            "",
            "Noise is injected by replacing random cells with blanks, invalid dates, invalid numbers, unknown categories, and broken IDs.",
            "",
            "## Overview",
            "",
            markdown_table(overview),
            "",
            "## Column role changes",
            "",
            markdown_table(role_changes),
            "",
        ]
    )
    (out_dir / "combined_report.md").write_text(report, encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    datasets = args.datasets or DEFAULT_DATASETS
    all_summaries: list[pd.DataFrame] = []
    all_noise: list[pd.DataFrame] = []
    all_columns: list[pd.DataFrame] = []
    all_uccs: list[pd.DataFrame] = []

    for dataset in datasets:
        summary, noise, columns, uccs = run_dataset(dataset, args)
        all_summaries.append(summary)
        all_noise.append(noise)
        all_columns.append(columns)
        all_uccs.append(uccs)

    combined_summary = pd.concat(all_summaries, ignore_index=True)
    combined_noise = pd.concat(all_noise, ignore_index=True)
    combined_columns = pd.concat(all_columns, ignore_index=True)
    combined_uccs = pd.concat(all_uccs, ignore_index=True)
    combined_summary.to_csv(args.out_dir / "combined_buckaroo_profile_summary_by_noise.csv", index=False)
    combined_noise.to_csv(args.out_dir / "combined_noise_injection_summary.csv", index=False)
    combined_columns.to_csv(args.out_dir / "combined_buckaroo_column_profiles_by_noise.csv", index=False)
    combined_uccs.to_csv(args.out_dir / "combined_buckaroo_ucc_candidates_by_noise.csv", index=False)
    build_combined_report(args.out_dir, combined_summary, combined_columns)
    print(f"Wrote combined outputs to {args.out_dir}")


if __name__ == "__main__":
    main()
