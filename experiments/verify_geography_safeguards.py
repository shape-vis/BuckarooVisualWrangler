"""Verify geography-aware profiler safeguards on the public dataset manifest."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.profile_dataset_shape import (  # noqa: E402
    GEOGRAPHY_PROFILE_ROLES,
    geography_kind,
    profile_columns,
)
from experiments.run_multi_dataset_sampling_profiler_experiment import (  # noqa: E402
    primary_keys_from_adaptive_profile,
)


DEFAULT_MANIFEST = ROOT / "outputs" / "multi_dataset_sampling_profiler_30_datasets_combined" / "dataset_manifest_combined.csv"
DEFAULT_OUT_DIR = ROOT / "outputs" / "multi_dataset_sampling_profiler_30_datasets_combined"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify geography safeguards across public datasets.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--sample-rows", type=int, default=5000)
    return parser.parse_args()


def load_dataset(path: Path, sample_rows: int) -> pd.DataFrame:
    return pd.read_csv(path, nrows=max(1, sample_rows), low_memory=False)


def profile_geography_columns(dataset_id: str, path: Path, sample_rows: int) -> list[dict[str, Any]]:
    frame = load_dataset(path, sample_rows)
    profile, _ = profile_columns(frame)
    predicted_keys = primary_keys_from_adaptive_profile(profile)
    rows: list[dict[str, Any]] = []

    for _, row in profile.iterrows():
        column = str(row["column"])
        kind = geography_kind(column)
        profile_role = str(row.get("profile_role", ""))
        if kind is None and profile_role not in GEOGRAPHY_PROFILE_ROLES:
            continue

        rows.append(
            {
                "dataset_id": dataset_id,
                "column": column,
                "geography_kind": kind or profile_role,
                "role": row.get("role"),
                "profile_role": profile_role,
                "confidence": row.get("confidence"),
                "confidence_score": row.get("confidence_score"),
                "decision_cardinality_ratio": row.get("decision_cardinality_ratio"),
                "cardinality_ratio_lower_bound": row.get("cardinality_ratio_lower_bound"),
                "numeric_ratio": row.get("numeric_ratio"),
                "date_like_ratio": row.get("date_like_ratio"),
                "predicted_primary_key": column in predicted_keys,
                "safeguard_passed": column not in predicted_keys and profile_role in GEOGRAPHY_PROFILE_ROLES,
                "warning": row.get("warning"),
            }
        )
    return rows


def write_report(out_dir: Path, rows: list[dict[str, Any]]) -> None:
    frame = pd.DataFrame(rows)
    total = int(len(frame))
    passed = int(frame["safeguard_passed"].sum()) if not frame.empty else 0
    predicted_keys = int(frame["predicted_primary_key"].sum()) if not frame.empty else 0
    role_counts = frame["profile_role"].value_counts().to_dict() if not frame.empty else {}
    dataset_counts = frame["dataset_id"].value_counts().to_dict() if not frame.empty else {}

    lines = [
        "# Geography Safeguard Verification",
        "",
        f"- Geography/location columns found: `{total}`",
        f"- Safeguard passed rows: `{passed}`",
        f"- Geography rows still predicted as primary keys: `{predicted_keys}`",
        "",
        "## Profile Role Counts",
        "",
    ]
    for role, count in role_counts.items():
        lines.append(f"- `{role}`: `{count}`")
    lines.extend(["", "## Dataset Counts", ""])
    for dataset_id, count in dataset_counts.items():
        lines.append(f"- `{dataset_id}`: `{count}`")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The improved Buckaroo profiler now treats geography/location uniqueness as semantic location evidence, not primary-key evidence. Exact mathematical profilers can still report uniqueness separately, but Buckaroo's user-facing profiler should warn instead of promoting geography fields to row identity.",
        ]
    )
    (out_dir / "geography_safeguard_verification_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest = pd.read_csv(args.manifest)

    rows: list[dict[str, Any]] = []
    for _, record in manifest.iterrows():
        dataset_id = str(record["dataset_id"])
        path = Path(str(record["local_path"]))
        if not path.exists():
            continue
        rows.extend(profile_geography_columns(dataset_id, path, args.sample_rows))

    output = args.out_dir / "geography_safeguard_verification.csv"
    frame = pd.DataFrame(rows)
    frame.to_csv(output, index=False)
    write_report(args.out_dir, rows)

    print(output)
    print(args.out_dir / "geography_safeguard_verification_report.md")


if __name__ == "__main__":
    main()
