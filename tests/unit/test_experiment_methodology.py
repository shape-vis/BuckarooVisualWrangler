"""Regression tests for the research methodology shared with production."""

from __future__ import annotations

import pandas as pd

from experiments.benchmark_validation import accuracy_output, benchmark_quality
from experiments.evaluate_early_stopping_noise_policy_tradeoffs import inject_noise
from experiments.evaluate_early_stopping_policy_tradeoffs import sample_frame, stable_seed
from experiments.profile_dataset_shape import ProfilerFeatureFlags, profile_columns
from experiments.run_profiler_ablation_study import distinct_sample_plan
from experiments.reproducibility import capture_reproducibility
from experiments.run_multi_dataset_sampling_profiler_experiment import parse_sample_sizes, summarize_runs
from experiments.run_profiler_variant_comparison import markdown_table


def test_nested_samples_are_prefixes_of_one_random_permutation():
    frame = pd.DataFrame({"value": range(1_000)})
    seed = stable_seed("nested-test", 100)

    sample_100 = sample_frame(frame, 100, seed)
    sample_500 = sample_frame(frame, 500, stable_seed("nested-test", 500))

    assert sample_100["value"].tolist() == sample_500.head(100)["value"].tolist()


def test_numeric_noise_is_not_routed_through_datetime_corruption():
    frame = pd.DataFrame({"price": list(range(200))})
    _, log = inject_noise(frame, 0.20, "numeric-noise-test")

    assert not log.empty
    assert not log["dirty_kind"].str.contains("datetime").any()
    assert set(log["dirty_kind"]).issubset(
        {"missing_value", "invalid_numeric_token", "numeric_outlier_or_text"}
    )


def test_noise_levels_use_nested_cells_and_identical_replacements():
    frame = pd.DataFrame({"price": list(range(200)), "category": [f"c-{i}" for i in range(200)]})
    _, log_5 = inject_noise(frame, 0.05, "nested-noise-test")
    _, log_10 = inject_noise(frame, 0.10, "nested-noise-test")
    _, log_20 = inject_noise(frame, 0.20, "nested-noise-test")

    five = log_5.set_index(["column", "row_position"])
    ten = log_10.set_index(["column", "row_position"])
    twenty = log_20.set_index(["column", "row_position"])
    assert set(five.index).issubset(set(ten.index))
    assert set(ten.index).issubset(set(twenty.index))
    for index, row in five.iterrows():
        assert ten.loc[index, "dirty_kind"] == row["dirty_kind"]
        assert ten.loc[index, "dirty_value"] == row["dirty_value"]
    for index, row in ten.iterrows():
        assert twenty.loc[index, "dirty_kind"] == row["dirty_kind"]
        assert twenty.loc[index, "dirty_value"] == row["dirty_value"]


def test_ablation_flags_change_real_profiler_outputs():
    frame = pd.DataFrame(
        {
            "city": [f"City-{index}" for index in range(200)],
            "created_at": pd.date_range("2026-01-01", periods=200, freq="min").astype(str),
        }
    )

    guarded, _ = profile_columns(frame)
    no_geo, _ = profile_columns(
        frame,
        features=ProfilerFeatureFlags(use_geography_safeguards=False),
    )
    no_time, _ = profile_columns(
        frame,
        features=ProfilerFeatureFlags(use_timestamp_safeguards=False),
    )
    no_candidates, _ = profile_columns(
        frame,
        features=ProfilerFeatureFlags(include_candidate_roles=False),
    )
    no_sampling, _ = profile_columns(
        frame,
        features=ProfilerFeatureFlags(enable_adaptive_sampling=False),
    )

    guarded_roles = guarded.set_index("column")["profile_role"].to_dict()
    no_geo_roles = no_geo.set_index("column")["profile_role"].to_dict()
    no_time_roles = no_time.set_index("column")["profile_role"].to_dict()
    assert guarded_roles["city"] == "high_uniqueness_location_field"
    assert no_geo_roles["city"] not in {"location_name", "high_uniqueness_location_field"}
    assert guarded_roles["created_at"] == "datetime_high_uniqueness"
    assert no_time_roles["created_at"] == "identifier"
    assert all(not candidates for candidates in no_candidates["candidate_roles"])
    assert not no_sampling["needs_more_sampling"].any()


def test_unreviewed_benchmark_never_emits_manual_accuracy():
    labels = pd.DataFrame(
        {
            "review_status": ["needs_review", "needs_review"],
            "is_primary_key": ["no", "no"],
            "corrected_is_primary_key": ["", ""],
        }
    )
    quality = benchmark_quality(labels)
    output = accuracy_output(pd.Series([True, False]), quality)

    assert quality["benchmark_is_fully_human_reviewed"] is False
    assert quality["benchmark_supports_key_recall"] is False
    assert output["manual_accuracy"] is None
    assert output["provisional_label_agreement"] == 0.5


def test_ablation_does_not_duplicate_clipped_sample_sizes():
    assert distinct_sample_plan(560) == [(100, 100), (500, 500), ("full", 560)]


def test_reproducibility_metadata_hashes_dataset_inputs(tmp_path):
    dataset = tmp_path / "data.csv"
    dataset.write_text("value\n1\n", encoding="utf-8")

    metadata = capture_reproducibility(tmp_path, [dataset])

    assert metadata["python_version"]
    assert metadata["datasets"][0]["path"] == str(dataset.resolve())
    assert metadata["datasets"][0]["sha256"] == "70642ed436d622619e6c4cfa8d01c8cad28dbe1e904c0be3f8eedf067221196f"


def test_multi_dataset_plan_uses_feasible_tiers_and_one_full_run():
    plan = parse_sample_sizes("100,500,1000,5000,10000,50000", total_rows=891)
    assert [(item["requested_sample_label"], item["sample_rows"]) for item in plan] == [
        ("100", 100),
        ("500", 500),
        ("full", 891),
    ]


def test_overall_summary_combines_full_runs_with_different_dataset_sizes():
    run_rows = []
    column_rows = []
    for dataset_id, rows in [("small", 50), ("large", 500)]:
        run_rows.append(
            {
                "dataset_id": dataset_id,
                "profiler": "buckaroo_sample_only_adaptive",
                "requested_sample_label": "full",
                "requested_sample_rows": rows,
                "sample_rows": rows,
                "iteration": 1,
                "runtime_seconds": 0.1,
                "end_to_end_runtime_seconds": 0.11,
                "full_pass_role_agreement": 1.0,
                "primary_key_decision_accuracy": 1.0,
                "primary_key_precision": None,
                "primary_key_recall": None,
                "made_key_prediction": False,
                "true_positive_primary_keys": 0,
                "false_primary_key_count": 0,
                "missed_primary_key_count": 0,
                "false_key_rate": 0.0,
                "predicted_primary_key_count": 0,
                "average_profile_confidence": 0.9,
                "columns_needing_more_sampling": 0,
                "sample_was_clipped_to_dataset": False,
            }
        )
        column_rows.append(
            {
                "dataset_id": dataset_id,
                "profiler": "buckaroo_sample_only_adaptive",
                "requested_sample_label": "full",
                "requested_sample_rows": rows,
                "sample_rows": rows,
                "column": "value",
                "predicted_semantic_role": "numeric_measure",
                "reference_semantic_role": "numeric_measure",
                "predicted_primary_key": False,
                "false_primary_key": False,
                "missed_primary_key": False,
                "confidence_score": 0.9,
            }
        )

    _summary, _stability, _profiler_stability, overall = summarize_runs(
        pd.DataFrame(run_rows),
        pd.DataFrame(column_rows),
    )

    assert len(overall) == 1
    assert int(overall.iloc[0]["datasets"]) == 2
    assert pd.isna(overall.iloc[0]["requested_sample_rows"])


def test_markdown_table_handles_nullable_integer_cells():
    rendered = markdown_table(pd.DataFrame({"rows": pd.Series([100, pd.NA], dtype="Int64")}))
    assert "| 100 |" in rendered
    assert rendered.endswith("|  |")
