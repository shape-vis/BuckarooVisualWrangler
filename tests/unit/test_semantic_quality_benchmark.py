"""Methodology tests for the blinded and semi-synthetic grouping benchmark."""

from __future__ import annotations

import importlib.util
import io
import sys
import zipfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "experiments" / "build_semantic_quality_benchmark.py"
SPEC = importlib.util.spec_from_file_location("semantic_quality_benchmark", SCRIPT)
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
assert SPEC.loader is not None
SPEC.loader.exec_module(benchmark)


def sample_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "benchmark_row_id": [f"sample:{index}" for index in range(120)],
            "source_row_number": list(range(120)),
            "category": ["A"] * 60 + ["B"] * 60,
            "amount": list(range(120)),
            "value": [float(index) for index in range(120)],
        }
    )


def test_semantic_cohort_uses_dataset_relative_quantile() -> None:
    frame = sample_frame()
    scenario = benchmark.ScenarioSpec(
        "sample",
        "cohort",
        "category A high values",
        (
            benchmark.ConditionSpec("category", "equals", "A"),
            benchmark.ConditionSpec("amount", "upper_quantile", quantile=0.50),
        ),
        "value",
        "malformed_numeric",
    )
    mask, details = benchmark.semantic_cohort(frame, scenario)
    assert mask.sum() > 0
    assert all(frame.loc[mask, "category"] == "A")
    quantile_details = [item for item in details if item.get("operation") == "upper_quantile"]
    assert quantile_details
    assert quantile_details[0]["boundary"] == frame["amount"].quantile(0.50)


def test_correlated_and_shuffled_cases_preserve_error_count(tmp_path: Path) -> None:
    frame = sample_frame()
    spec = benchmark.DatasetSpec(
        "sample",
        "development",
        "test",
        "test",
        "local",
        "https://example.test/sample.csv",
        "test",
        "local_csv",
    )
    scenario = benchmark.ScenarioSpec(
        "sample",
        "cohort",
        "category A",
        (benchmark.ConditionSpec("category", "equals", "A"),),
        "value",
        "malformed_numeric",
    )
    cases, memberships, injections = benchmark.build_semi_synthetic_cases(
        frame,
        spec,
        scenario,
        tmp_path,
        case_rows=120,
    )
    assert len(cases) == len(benchmark.DEFAULT_SEEDS) * len(benchmark.DEFAULT_NOISE_LEVELS) * 2
    grouped = pd.DataFrame(cases).groupby(["seed", "noise_level_within_semantic_cohort"])
    for _key, pair in grouped:
        assert set(pair["association_mode"]) == {"correlated", "shuffled_control"}
        assert pair["injected_error_rows"].nunique() == 1
    assert len(injections) == sum(item["injected_error_rows"] for item in cases)
    assert len(memberships) == len(frame) * len(cases)


def test_pairwise_tasks_are_blinded_from_sampling_stratum() -> None:
    frame = sample_frame()
    spec = benchmark.DatasetSpec(
        "sample",
        "development",
        "test",
        "test",
        "local",
        "https://example.test/sample.csv",
        "test",
        "local_csv",
        display_columns=("category", "amount", "value"),
        pair_category_column="category",
        pair_numeric_column="amount",
    )
    tasks, audit = benchmark.generate_pairwise_tasks(frame, spec, 12)
    assert len(tasks) == 12
    assert len(audit) == 12
    assert all("sampling_stratum" not in task for task in tasks)
    assert {row["sampling_stratum"] for row in audit} >= {"candidate_similar", "candidate_contrast"}


def test_nested_archive_prefers_the_requested_member(tmp_path: Path) -> None:
    inner_buffer = io.BytesIO()
    with zipfile.ZipFile(inner_buffer, "w") as inner:
        inner.writestr("bank-full.csv", "category;amount\nA;1\n")
    outer_path = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer_path, "w") as outer:
        outer.writestr("unrelated.csv", "wrong,value\n1,2\n")
        outer.writestr("bank.zip", inner_buffer.getvalue())

    data, member = benchmark.extract_archive_data(outer_path, "bank-full.csv")
    assert member == "bank.zip!bank-full.csv"
    assert b"category;amount" in data
