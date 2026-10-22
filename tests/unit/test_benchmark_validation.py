"""Benchmark claims must reflect label review and key coverage."""

import pandas as pd
import pytest

from experiments.benchmark_validation import accuracy_output, benchmark_quality


def test_unreviewed_labels_only_report_provisional_agreement():
    labels = pd.DataFrame({"review_status": ["needs_review", "needs_review"]})

    quality = benchmark_quality(labels)
    result = accuracy_output(pd.Series([True, False]), quality)

    assert quality["human_reviewed_rows"] == 0
    assert quality["needs_review_rows"] == 2
    assert quality["benchmark_supports_key_recall"] is False
    assert result == {"manual_accuracy": None, "provisional_label_agreement": 0.5}


def test_all_approved_review_statuses_enable_manual_accuracy():
    labels = pd.DataFrame({"review_status": [" approved ", "HUMAN_REVIEWED", "reviewed", "verified"]})

    quality = benchmark_quality(labels)
    result = accuracy_output(pd.Series([True, True, True, False]), quality)

    assert quality["benchmark_is_fully_human_reviewed"] is True
    assert quality["benchmark_label_source"] == "human_reviewed_ground_truth"
    assert result == {"manual_accuracy": 0.75, "provisional_label_agreement": None}


def test_one_unreviewed_label_prevents_a_manual_accuracy_claim():
    quality = benchmark_quality(pd.DataFrame({"review_status": ["verified", None]}))

    assert quality["human_reviewed_rows"] == 1
    assert quality["needs_review_rows"] == 1
    assert accuracy_output(pd.Series([True, True]), quality)["manual_accuracy"] is None


def test_missing_review_status_column_is_treated_as_unreviewed():
    quality = benchmark_quality(pd.DataFrame({"column": ["value"]}))

    assert quality["benchmark_is_fully_human_reviewed"] is False
    assert quality["needs_review_rows"] == 1


@pytest.mark.parametrize("key_column", ["is_primary_key", "corrected_is_primary_key"])
def test_key_recall_requires_positive_labels_in_either_key_field(key_column):
    quality = benchmark_quality(pd.DataFrame({key_column: ["yes", "true", "1", "no", None]}))

    assert quality["positive_primary_key_rows"] == 3
    assert quality["benchmark_supports_key_recall"] is True


def test_empty_benchmark_produces_no_accuracy_or_recall_claim():
    quality = benchmark_quality(pd.DataFrame())
    result = accuracy_output(pd.Series(dtype="bool"), quality)

    assert quality["label_rows"] == 0
    assert quality["benchmark_is_fully_human_reviewed"] is False
    assert quality["benchmark_supports_key_recall"] is False
    assert result == {"manual_accuracy": None, "provisional_label_agreement": None}
