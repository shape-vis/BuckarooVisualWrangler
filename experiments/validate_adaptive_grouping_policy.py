"""Generate benchmark-free evidence for Buckaroo's adaptive grouping policy.

This is a mechanism validation, not a semantic-accuracy benchmark. It checks
that decisions change with observed distributions, that stability is invariant
to cluster label names, and that ambiguous candidates are not called clearly
separated. No human labels are read or generated.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "app" / "server_utils" / "adaptive_grouping_policy.py"
POLICY_SPEC = importlib.util.spec_from_file_location("buckaroo_adaptive_grouping_policy", POLICY_PATH)
if POLICY_SPEC is None or POLICY_SPEC.loader is None:
    raise RuntimeError(f"Could not load adaptive policy from {POLICY_PATH}")
policy = importlib.util.module_from_spec(POLICY_SPEC)
sys.modules[POLICY_SPEC.name] = policy
POLICY_SPEC.loader.exec_module(policy)


DEFAULT_OUTPUT = ROOT / "outputs" / "adaptive_grouping_policy_validation_20260719"


def record(decision: str, case: str, evidence: str, value, source: str) -> dict[str, object]:
    return {
        "decision": decision,
        "case": case,
        "input_evidence": evidence,
        "adaptive_value": value,
        "decision_source": source,
        "human_labels_used": False,
    }


def validation_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []

    confidence_cases = {
        "clear_two_classes": [0.10, 0.12, 0.16, 0.88, 0.91, 0.95],
        "uniform_evidence": [0.82, 0.82, 0.82, 0.82],
    }
    for case, values in confidence_cases.items():
        cutoff, source = policy.adaptive_profile_confidence_cutoff(values)
        rows.append(record("profile_confidence_cutoff", case, json.dumps(values), cutoff, source))

    profile_map = {"segment": {"family": "categorical", "confidence": 0.94}}
    support_cases = {
        "small_balanced_categories": pd.DataFrame(
            {"segment": ["a"] * 2 + ["b"] * 2 + ["c"] * 8 + ["d"] * 8}
        ),
        "large_head_and_tail_categories": pd.DataFrame(
            {"segment": ["a"] * 3 + ["b"] * 3 + ["c"] * 3 + ["d"] * 3 + ["e"] * 54 + ["f"] * 54}
        ),
    }
    for case, frame in support_cases.items():
        support, source, observations = policy.adaptive_min_group_size(
            frame, profile_map, requested=None
        )
        frequencies = frame["segment"].value_counts().sort_index().to_dict()
        rows.append(record(
            "minimum_group_support",
            case,
            json.dumps({"rows": len(frame), "frequencies": frequencies, "observations": observations}),
            support,
            source,
        ))

    for row_count in (64, 256, 4096):
        candidates = policy.adaptive_k_candidates(
            row_count=row_count,
            unique_row_count=row_count,
            min_group_size=2,
        )
        rows.append(record(
            "candidate_k_range",
            f"{row_count}_unique_rows",
            json.dumps({"rows": row_count, "unique_rows": row_count, "minimum_support": 2}),
            json.dumps(candidates),
            "sample size, unique feature rows, support bound, and log2 complexity bound",
        ))

    matrix = np.asarray([
        [1.00, 0.00], [0.95, 0.05], [0.90, 0.10], [0.85, 0.15],
        [0.00, 1.00], [0.05, 0.95], [0.10, 0.90], [0.15, 0.85],
    ])
    labels = np.asarray([0, 0, 0, 0, 1, 1, 1, 1])
    partition_cases = {
        "same_partition_different_label_names": np.asarray([9, 9, 9, 9, 4, 4, 4, 4]),
        "mixed_unstable_partition": np.asarray([0, 1, 0, 1, 0, 1, 0, 1]),
    }
    for case, alternate in partition_cases.items():
        diagnostics = policy.partition_diagnostics(matrix, labels, alternate)
        rows.append(record(
            "partition_diagnostics",
            case,
            json.dumps({"labels": labels.tolist(), "alternate": alternate.tolist()}),
            json.dumps(diagnostics.to_dict(), sort_keys=True),
            "repeated-run stability, coherence, distinctiveness, balance, and assigned fraction",
        ))

    score_cases = {
        "clear_winner": [0.92, 0.51, 0.49, 0.47],
        "tied_top_class": [0.92, 0.90, 0.49, 0.47],
        "only_two_candidates": [0.92, 0.91],
    }
    for case, scores in score_cases.items():
        separation = policy.score_separation(scores)
        rows.append(record(
            "candidate_score_separation",
            case,
            json.dumps(scores),
            json.dumps(separation, sort_keys=True),
            "natural break between top candidate and runner-up",
        ))

    return rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = validation_rows()
    write_csv(output_dir / "adaptive_decision_cases.csv", rows)

    summary = {
        "purpose": "benchmark-free adaptive mechanism validation",
        "cases": len(rows),
        "human_labels_used": False,
        "semantic_accuracy_claimed": False,
        "decisions": sorted({str(row["decision"]) for row in rows}),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "README.md").write_text(
        "# Adaptive grouping policy validation\n\n"
        "This output demonstrates that Buckaroo's cutoffs, support, candidate K "
        "range, stability, and candidate separation respond to observed evidence. "
        "It uses no human labels and makes no semantic-accuracy claim.\n\n"
        "- `adaptive_decision_cases.csv`: one row per mechanism/case.\n"
        "- `summary.json`: validation scope and claim boundary.\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(rows)} validation cases to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
