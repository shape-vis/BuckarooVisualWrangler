import pandas as pd

from experiments.profile_dataset_shape import classify_column, name_tokens


def test_name_tokens_splits_camel_and_pascal_case_column_names():
    # Caught live on the StackOverflow demo: name_tokens lowercased before
    # splitting, so "DevType" became one fused token "devtype" that could
    # never match the "type" hint keyword despite plainly containing it --
    # costing the column a real 10-point confidence bonus for no reason
    # related to its actual data quality. Same for "RaceEthnicity" missing
    # both "race" and "ethnicity". Case is the only signal separating the
    # words, so it must be split before lowercasing, not after.
    assert name_tokens("DevType") == {"dev", "type"}
    assert name_tokens("RaceEthnicity") == {"race", "ethnicity"}
    assert name_tokens("EducationParents") == {"education", "parents"}
    # Snake/kebab/space-separated names must keep working exactly as before.
    assert name_tokens("gender_code") == {"gender", "code"}
    assert name_tokens("gender-code") == {"gender", "code"}
    assert name_tokens("gender code") == {"gender", "code"}
    # A bare acronym column (no lowercase letters at all) must not be shredded
    # into single characters -- "GDP" stays one token, not {"g","d","p"}.
    assert name_tokens("GDP") == {"gdp"}


def test_camel_case_name_hint_raises_categorical_confidence():
    # Direct before/after: a fused-token name ("Devtype") that accidentally
    # matches nothing gets no bonus; the camelCase form of the identical
    # data ("DevType") must score strictly higher once the hint is found,
    # since only the name-hint term differs between the two calls.
    values = pd.Series(["Back-end developer", "Front-end developer"] * 20)
    unhinted = classify_column("Devtype", values)
    hinted = classify_column("DevType", values)

    assert hinted["confidence_score"] > unhinted["confidence_score"]


def test_reliability_reflects_column_cardinality_not_sample_size_alone():
    # Caught live: score_profile_confidence's reliability term used to be
    # min()'d against sample_reliability_score(n) -- a dataset-wide worst-case
    # bound built from an assumed 50/50 split (evidence_interval(n // 2, n,
    # ...)), identical for every column at a given sample size regardless of
    # how clean that specific column's own values are. At n=400 this ceiling
    # sits at ~0.837, capping a column with an extremely tight, well-
    # determined cardinality margin (5 distinct values in 400 rows) at the
    # same reliability as a genuinely ambiguous column. Fixed by using the
    # column's own margin-derived reliability directly, since it already
    # widens appropriately for small samples and HLL-estimated cardinality.
    # This test proves the fix matters, not just that it doesn't crash: a
    # clean column's own reliability must exceed what the old dataset-wide
    # floor alone would have allowed.
    from experiments.profile_dataset_shape import (
        cardinality_interval_summary,
        reliability_from_margin,
        sample_reliability_score,
    )

    n = 400
    tight_interval = cardinality_interval_summary(
        5, n, False, sample_singleton_rows=0, sample_total=n,
    )
    column_reliability = reliability_from_margin(tight_interval["margin"])
    sample_floor = sample_reliability_score(n)

    assert column_reliability > sample_floor


def test_clean_categorical_column_confidence_rises_after_reliability_fix():
    # End-to-end version of the same fix, through the real classifier: a
    # clean, low-cardinality categorical column with no name-hint match
    # (the exact situation "YearsCoding"/"HoursComputer" were caught in
    # live on the StackOverflow dataset) must score meaningfully above the
    # old dataset-wide floor-driven ceiling of ~0.82-0.83 at this sample size.
    values = pd.Series((["0-2 years", "3-5 years", "6-8 years", "9-11 years"] * 100))
    result = classify_column("tenure_bucket", values)
    assert result["confidence_score"] > 0.84


def test_numeric_code_category_is_not_treated_as_measurement():
    result = classify_column("ethnicity", pd.Series([0, 1, 2, 3, 4] * 20))

    assert result["role"] == "categorical"
    assert result["profile_role"] == "numeric_code_category"
    assert result["small_integer_domain"] is True
    assert "labels/codes" in result["warning"]


def test_measurement_hint_keeps_age_numeric():
    result = classify_column("age", pd.Series(range(18, 78)))

    assert result["role"] == "numeric"
    assert result["profile_role"] == "numeric_measure"
    assert result["measurement_name_hint"] is True
    assert result["top_candidate_role"] == "numeric_measure"
    assert result["candidate_confidence_gap"] > 0


def test_binary_category_gets_explicit_profile_role():
    result = classify_column("gender", pd.Series([0, 1] * 30))

    assert result["role"] == "categorical"
    assert result["profile_role"] == "binary_category"
    assert result["boolean_like_ratio"] == 1.0


def test_chosen_subtype_confidence_matches_chosen_candidate_confidence():
    result = classify_column("gender", pd.Series([0, 1] * 60))
    chosen_candidates = [
        candidate for candidate in result["candidate_roles"]
        if candidate.get("chosen")
    ]

    assert result["profile_role"] == "binary_category"
    assert result["chosen_candidate_role"] == "categorical"
    assert len(chosen_candidates) == 1
    assert chosen_candidates[0]["role"] == "categorical"
    assert chosen_candidates[0]["confidence"] == result["confidence_score"]
    assert result["chosen_candidate_confidence"] == result["confidence_score"]
    assert chosen_candidates[0]["confidence_basis"] == "chosen_profile_confidence"
    assert "evidence_strength" in chosen_candidates[0]


def test_two_value_numeric_measure_keeps_measurement_role():
    result = classify_column("capital-loss", pd.Series([0] * 95 + [1902] * 5))

    assert result["role"] == "numeric"
    assert result["profile_role"] == "numeric_measure"
    assert result["measurement_name_hint"] is True


def test_duration_unit_name_keeps_small_integer_domain_numeric():
    result = classify_column("delivery_time_days", pd.Series([1, 2, 3, 4, 5, 6, 7] * 20))

    assert result["role"] == "numeric"
    assert result["profile_role"] == "numeric_measure"
    assert result["small_integer_domain"] is True
    assert result["measurement_name_hint"] is True


def test_numeric_text_blob_is_not_semantic_free_text():
    pixel_rows = [
        " ".join(str((index + offset) % 256) for index in range(64))
        for offset in range(30)
    ]

    result = classify_column("pixels", pd.Series(pixel_rows))

    assert result["role"] == "free_text"
    assert result["profile_role"] == "vector_blob"
    assert result["semantic_text_candidate"] is False
    assert result["numeric_token_fraction"] == 1.0


def test_large_high_cardinality_column_reports_estimated_unique_count():
    result = classify_column("session_id", pd.Series([f"session-{index}" for index in range(12_500)]))

    assert result["role"] == "identifier"
    assert result["distinct_count_method"] == "hyperloglog"
    assert result["unique_count_is_estimated"] is True
    assert abs(result["unique_count"] - 12_500) / 12_500 < 0.08


def test_repeated_id_column_still_profiles_as_identifier():
    values = [f"CUST-{index % 2000:05d}" for index in range(10_000)]

    result = classify_column("customer_id", pd.Series(values))

    assert result["role"] == "identifier"
    assert result["profile_role"] == "identifier"
    assert result["id_name_hint"] is True


def test_small_sample_unique_values_get_low_confidence_warning():
    result = classify_column("sku", pd.Series([f"SKU-{index}" for index in range(10)]))

    assert result["role"] == "identifier"
    assert result["profile_role"] == "quasi_identifier"
    assert result["confidence"] == "low"
    assert result["sample_reliability"] < 0.2
    assert result["cardinality_ratio_lower_bound"] < result["identifier_ratio_threshold"]
    assert result["adaptive_thresholds_version"] == "evidence_interval_v2"
    assert result["top_candidate_role"] == "primary_key"
    assert result["needs_more_sampling"] is True
    assert result["adaptive_sampling_action"] == "sample_more"
    assert "worst-case 95% evidence margin is wide" in result["warning"]
    assert "lower confidence bound is below the identifier threshold" in result["warning"]


def test_noisy_datetime_keeps_warning_and_confidence_score():
    values = pd.Series(["2024-01-01"] * 85 + ["not-a-date"] * 15)

    result = classify_column("shipped_at", values)

    assert result["profile_role"] == "datetime_category"
    assert result["date_parse_threshold"] == 0.7
    assert result["date_parse_lower_bound"] >= result["date_parse_threshold"]
    assert result["confidence_score"] < 0.9
    assert "confidence-interval bounds failed date parsing evidence" in result["warning"]


def test_high_uniqueness_datetime_does_not_become_identifier():
    values = pd.Series(pd.date_range("2024-01-01", periods=250, freq="min").astype(str))

    result = classify_column("created_at", values)

    assert result["role"] == "categorical"
    assert result["profile_role"] == "datetime_high_uniqueness"
    assert result["decision_cardinality_ratio"] == 1.0
    assert "Timestamp uniqueness alone is not enough primary-key evidence" in result["warning"]


def test_latitude_longitude_do_not_become_identifiers():
    latitude = classify_column("latitude", pd.Series([40.0 + (index / 1000) for index in range(250)]))
    longitude = classify_column("longitude", pd.Series([-73.0 - (index / 1000) for index in range(250)]))

    assert latitude["role"] == "categorical"
    assert latitude["profile_role"] == "geographic_coordinate"
    assert latitude["geography_name_hint"] is True
    assert latitude["geography_kind"] == "latitude"
    assert latitude["top_candidate_role"] == "geography_location"
    assert latitude["second_candidate_role"] == "numeric_measure"
    assert "location uniqueness is not row identity" in latitude["warning"]

    assert longitude["role"] == "categorical"
    assert longitude["profile_role"] == "geographic_coordinate"
    assert longitude["geography_kind"] == "longitude"


def test_location_names_and_codes_get_geography_roles():
    city = classify_column("city", pd.Series([f"City {index}" for index in range(250)]))
    postal = classify_column("zip_code", pd.Series([f"{90000 + index}" for index in range(250)]))
    airport = classify_column("iata", pd.Series([f"A{index:02d}" for index in range(250)]))

    assert city["role"] == "categorical"
    assert city["profile_role"] == "high_uniqueness_location_field"
    assert "geography/name uniqueness alone is not primary-key evidence" in city["warning"]

    assert postal["role"] == "categorical"
    assert postal["profile_role"] == "postal_code"
    assert postal["id_name_hint"] is True

    assert airport["role"] == "categorical"
    assert airport["profile_role"] == "airport_code"
    assert airport["geography_kind"] == "airport_code"


def test_measurement_hint_can_preserve_noisy_numeric_column():
    values = pd.Series([*range(80), *["bad-value"] * 20])

    result = classify_column("sale_price", values)

    assert result["role"] == "numeric"
    assert result["profile_role"] == "numeric_measure"
    assert result["top_candidate_role"] == "numeric_measure"
    assert result["second_candidate_role"] == "primary_key"
    assert result["needs_more_sampling"] is False
    assert result["numeric_parse_threshold"] == 0.85
    assert result["measurement_parse_threshold"] == 0.75
    assert result["numeric_parse_lower_bound"] < result["measurement_parse_threshold"]
    assert "lower confidence bounds failed numeric parsing" in result["warning"]
