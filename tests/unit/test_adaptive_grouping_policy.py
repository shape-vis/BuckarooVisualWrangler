import numpy as np
import pandas as pd

from app.server_utils import adaptive_grouping_policy as policy


def categorical_profile():
    return {"segment": {"family": "categorical", "confidence": 0.94}}


def test_natural_break_comes_from_the_observed_distribution():
    threshold = policy.natural_break_threshold([0.08, 0.11, 0.14, 0.82, 0.88, 0.93])

    assert 0.14 < threshold < 0.82
    assert policy.natural_break_threshold([0.82, 0.82, 0.82]) is None


def test_min_group_support_changes_with_the_dataset_frequency_distribution():
    small = pd.DataFrame({"segment": ["a"] * 2 + ["b"] * 2 + ["c"] * 8 + ["d"] * 8})
    large = pd.DataFrame(
        {"segment": ["a"] * 3 + ["b"] * 3 + ["c"] * 3 + ["d"] * 3 + ["e"] * 54 + ["f"] * 54}
    )

    small_support, small_source, _ = policy.adaptive_min_group_size(
        small, categorical_profile(), requested=None
    )
    large_support, large_source, _ = policy.adaptive_min_group_size(
        large, categorical_profile(), requested=None
    )

    assert small_support != large_support
    assert small_source == large_source == "natural break in repeated value frequencies"


def test_explicit_minimum_is_preserved_for_controlled_experiments():
    frame = pd.DataFrame({"segment": ["a"] * 10 + ["b"] * 10})

    support, source, observations = policy.adaptive_min_group_size(
        frame, categorical_profile(), requested=7
    )

    assert support == 7
    assert source == "explicit caller override"
    assert observations == 0


def test_candidate_cluster_counts_scale_past_the_old_fixed_ceiling():
    candidates = policy.adaptive_k_candidates(
        row_count=4096,
        unique_row_count=4096,
        min_group_size=2,
    )

    assert candidates[0] == 2
    assert candidates[-1] == 12
    assert candidates[-1] > 8


def test_partition_stability_is_label_invariant_and_detects_instability():
    matrix = np.asarray(
        [
            [1.0, 0.0],
            [0.95, 0.05],
            [0.9, 0.1],
            [0.85, 0.15],
            [0.0, 1.0],
            [0.05, 0.95],
            [0.1, 0.9],
            [0.15, 0.85],
        ]
    )
    labels = np.asarray([0, 0, 0, 0, 1, 1, 1, 1])
    relabeled_same_partition = np.asarray([9, 9, 9, 9, 4, 4, 4, 4])
    unstable_partition = np.asarray([0, 1, 0, 1, 0, 1, 0, 1])

    stable = policy.partition_diagnostics(matrix, labels, relabeled_same_partition)
    unstable = policy.partition_diagnostics(matrix, labels, unstable_partition)

    assert stable.stability == 1.0
    assert unstable.stability < stable.stability
    assert unstable.score < stable.score


def test_candidate_score_separation_requires_a_natural_gap():
    separated = policy.score_separation([0.92, 0.51, 0.49, 0.47])
    tied_top_class = policy.score_separation([0.92, 0.90, 0.49, 0.47])
    only_two_candidates = policy.score_separation([0.92, 0.91])

    assert separated["separated"] is True
    assert tied_top_class["separated"] is False
    assert only_two_candidates["separated"] is False
