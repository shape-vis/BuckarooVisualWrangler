from detectors.approx_cardinality import distinct_count_profile


def test_distinct_count_profile_uses_exact_mode_for_small_inputs():
    profile = distinct_count_profile(["USA", "usa", " Canada ", "Canada", None, ""])

    assert profile.method == "exact"
    assert profile.is_estimated is False
    assert profile.non_missing_count == 4
    assert profile.unique_count == 2
    assert profile.cardinality_ratio == 0.5


def test_distinct_count_profile_switches_to_hyperloglog_for_large_inputs():
    values = [f"user-{index}" for index in range(25_000)]

    profile = distinct_count_profile(values, exact_limit=1_000, precision=12)
    relative_error = abs(profile.unique_count - 25_000) / 25_000

    assert profile.method == "hyperloglog"
    assert profile.is_estimated is True
    assert relative_error < 0.08
