"""Run DataProfiler on a CSV and save a comparable external-baseline report."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
from dataprofiler import Data, Profiler


INPUT_PATH = Path(os.environ.get("DATAPROFILER_INPUT", "/data/order_items.csv"))
OUTPUT_DIR = Path(os.environ.get("DATAPROFILER_OUTPUT", "/out/dataprofiler_order_items"))


def _safe_json(value):
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_json(item) for item in value]
    if hasattr(value, "item"):
        return value.item()
    return value


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    row_count = sum(1 for _ in INPUT_PATH.open("rb")) - 1
    data = Data(str(INPUT_PATH))
    profiler = Profiler(data, samples_per_update=row_count)
    report = profiler.report(report_options={"output_format": "compact"})

    raw_report_path = OUTPUT_DIR / "profile_report.json"
    raw_report_path.write_text(json.dumps(_safe_json(report), indent=2), encoding="utf-8")

    global_stats = report.get("global_stats", {})
    column_stats = report.get("data_stats", [])

    rows = []
    for column in column_stats:
        stats = column.get("statistics", {})
        sample_size = stats.get("sample_size")
        null_count = stats.get("null_count")
        null_ratio = None
        if sample_size:
            null_ratio = null_count / sample_size
        rows.append(
            {
                "column": column.get("column_name"),
                "data_type": column.get("data_type"),
                "data_label": column.get("data_label"),
                "null_count": null_count,
                "null_ratio": null_ratio,
                "unique_count": stats.get("unique_count"),
                "unique_ratio": stats.get("unique_ratio"),
                "min": stats.get("min"),
                "max": stats.get("max"),
                "mean": stats.get("mean"),
                "stddev": stats.get("stddev"),
                "sample_size": sample_size,
            }
        )

    pd.DataFrame(rows).to_csv(OUTPUT_DIR / "column_summary.csv", index=False)

    summary_lines = [
        f"# DataProfiler run: {INPUT_PATH.name}",
        "",
        f"Source CSV: {INPUT_PATH}",
        f"Rows in file: {global_stats.get('row_count')}",
        f"Rows profiled: {global_stats.get('samples_used')}",
        f"Columns: {global_stats.get('column_count')}",
        f"Null cells: {global_stats.get('null_count')}",
        f"Duplicate rows: {global_stats.get('duplicate_row_count')}",
        "",
        "## Column summary",
        "",
    ]

    for row in rows:
        null_ratio = row["null_ratio"]
        unique_ratio = row["unique_ratio"]
        null_text = "" if null_ratio is None else f", null_ratio={null_ratio:.4f}"
        unique_text = "" if unique_ratio is None else f", unique_ratio={unique_ratio:.4f}"
        summary_lines.append(
            f"- {row['column']}: type={row['data_type']}, label={row['data_label']}"
            f"{null_text}{unique_text}"
        )

    (OUTPUT_DIR / "summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
