from datetime import datetime, timedelta
import json

import pandas as pd

from app.server_utils.multi_view_grouping import (
    analyst_signal_strength,
    build_multiview_groups_from_frames,
    build_view_matrix,
    choose_view_columns,
    humanize_quality_issue,
    run_internal_clustering,
)


def profile(role, confidence=0.95):
    return {"profileRole": role, "confidenceScore": confidence}


def multi_view_rows():
    rows = []
    base = datetime(2026, 1, 1)
    for index in range(60):
        created = base + timedelta(days=index % 15)
        rows.append({
            "ID": index + 1,
            "customer_id": f"CUS-{index + 1:04d}",
            "amount": 25 + (index % 4),
            "segment": "retail",
            "notes": "billing invoice payment question",
            "order_status": "completed",
            "created_at": created.isoformat(),
            "shipped_at": (created + timedelta(days=1)).isoformat(),
            "latitude": 40.71 + ((index % 3) * 0.001),
            "longitude": -74.00 - ((index % 3) * 0.001),
        })
    for index in range(60, 120):
        created = base + timedelta(days=90 + (index % 15))
        rows.append({
            "ID": index + 1,
            "customer_id": f"CUS-{index + 1:04d}",
            "amount": 220 + (index % 4),
            "segment": "enterprise",
            "notes": "shipment delivery delay complaint",
            "order_status": "returned",
            "created_at": created.isoformat(),
            "shipped_at": (created + timedelta(days=9)).isoformat(),
            "latitude": 34.05 + ((index % 3) * 0.001),
            "longitude": -118.24 - ((index % 3) * 0.001),
        })
    return pd.DataFrame(rows)


def profiles():
    return {
        "customer_id": profile("identifier"),
        "amount": profile("numeric_measure"),
        "segment": profile("categorical"),
        "notes": profile("free_text"),
        "order_status": profile("categorical"),
        "created_at": profile("datetime_high_uniqueness"),
        "shipped_at": profile("datetime_high_uniqueness"),
        "latitude": profile("geographic_coordinate"),
        "longitude": profile("geographic_coordinate"),
    }


def errors_in(row_ids, column, error_type="anomaly"):
    # Policy (2026-07-20): groups with no enriched data-quality issue are filtered out
    # entirely — this is a data-quality tool, not a general row-clustering tool. Fixtures
    # that assert groups appear must therefore plant a real, concentrated detector signal.
    row_ids = list(row_ids)
    return pd.DataFrame({
        "row_id": row_ids,
        "column_id": [column] * len(row_ids),
        "error_type": [error_type] * len(row_ids),
    })


def test_pipeline_combines_semantic_blocks_and_surfaces_quality_concentrated_groups():
    result = build_multiview_groups_from_frames(
        multi_view_rows(),
        errors_in(range(1, 41), "amount"),
        profiles=profiles(),
        total_rows=120,
    )

    returned_views = {group["view"] for group in result["groups"]}
    assert "semantic_quality" in returned_views
    assert not ({"business", "text", "lifecycle", "geography", "quality"} & returned_views)
    assert result["groups"], "at least one quality-concentrated group should survive"
    assert all(group["hasQualitySignal"] for group in result["groups"])
    assert result["strategy"] == "profiler_guided_semantic_quality"
    assert result["compatibilityStrategy"] == "profiler_guided_multi_view"
    assert result["errorRows"] > 0
    assert result["adaptivePolicy"]["humanLabelsUsed"] is False
    # Every surfaced group must carry a real, enriched quality issue; purely-semantic,
    # error-free clusters are dropped entirely, not merely ranked lower.
    assert result["adaptivePolicy"]["qualitySignalRequired"] is True
    assert result["adaptivePolicy"]["min_group_source"] == "natural break in repeated value frequencies"
    assert "observed" in result["adaptivePolicy"]["confidence_source"]
    assert result["representation"]["mode"] == "single_combined_semantic_quality_matrix"
    assert {"business", "text", "lifecycle", "geography", "quality"} <= set(
        result["representation"]["activeBlocks"]
    )
    assert result["representation"]["manualBlockWeights"] is False
    assert result["representation"]["qualitySignalRows"] > 0
    assert "customer_id" not in result["representation"]["semanticColumns"]
    json.dumps(result)
    assignments = result["representation"]["semanticColumnAssignments"]
    assert assignments["order_status"] == "business"
    assert assignments["created_at"] == "lifecycle"
    assert len(assignments) == len(set(assignments))

    for group in result["groups"]:
        if group["view"] != "semantic_quality":
            continue
        assert group["descriptionGrounded"] is True
        assert group["semanticCohort"].startswith("Rows")
        assert group["qualityPattern"]
        assert group["supportingFields"]
        assert group["representativeExamples"]
        group_ids = set(group["rowIds"])
        representative_ids = {item["rowId"] for item in group["representativeExamples"]}
        boundary_ids = {item["rowId"] for item in group["contradictoryExamples"]}
        assert representative_ids <= group_ids
        assert boundary_ids <= group_ids
        assert representative_ids.isdisjoint(boundary_ids)
        assert all(item["evidence"] for item in group["supportingFields"])
        assert not {"restaurant", "taxi", "airport"} & set(group["description"].lower().split())

    semantic_runs = [
        view for view in result["views"]
        if view["id"] == "semantic_quality"
        and view["status"] == "ready"
    ]
    assert semantic_runs
    for view in semantic_runs:
        diagnostics = view["adaptiveDiagnostics"]
        assert len(diagnostics["kCandidates"]) >= 1
        assert len(diagnostics["algorithmCandidates"]) >= 2
        assert diagnostics["selection"]["algorithm"]


def test_geography_descriptions_are_plain_language_and_score_on_a_comparable_scale():
    result = build_multiview_groups_from_frames(
        multi_view_rows(),
        errors_in(range(1, 41), "amount"),
        profiles=profiles(),
        total_rows=120,
    )

    geography_fields = [
        field
        for group in result["groups"]
        if group["view"] == "semantic_quality"
        for field in group["supportingFields"]
        if field["kind"] == "geography"
    ]
    assert geography_fields, "the NYC/LA split should surface at least one geography candidate"
    for field in geography_fields:
        # Raw decimal coordinates ("40.7110, -74.0010") belong in the expandable evidence
        # line, never in the short cohort phrase a reader sees first.
        assert "," not in field["evidence"].split(".")[0] or "km" in field["evidence"]
        # The score must live on the same effect-size scale as numeric/categorical/temporal
        # candidates (roughly single digits for a clean split), not a raw angle in radians
        # (which would always read near zero and get discarded as noise).
        assert field["strength"] > 0.05

    for group in result["groups"]:
        if group["view"] != "semantic_quality":
            continue
        cohort = group["semanticCohort"]
        assert "coordinates centered near" not in cohort
        # No internal/engineering vocabulary should leak into user-facing text.
        lowered = (cohort + " " + group["qualityPattern"]).lower()
        assert "profiler" not in lowered
        assert "natural break" not in lowered


def test_clusters_without_a_quality_signal_are_dropped_entirely():
    # Policy (2026-07-20): this is a data-quality tool. A semantically coherent cluster
    # that carries no enriched data-quality issue is not surfaced at all — not merely
    # ranked lower. Same two-cluster fixture, signal concentrated in ONLY the first
    # cohort: the first survives, the clean second cohort is dropped.
    from app.server_utils.multi_view_grouping import NO_QUALITY_SIGNAL_PHRASE

    result = build_multiview_groups_from_frames(
        multi_view_rows(),
        errors_in(range(1, 31), "amount"),
        profiles=profiles(),
        total_rows=120,
    )
    assert result["groups"]
    assert all(group["hasQualitySignal"] for group in result["groups"])
    assert result["adaptivePolicy"]["qualitySignalRequired"] is True
    assert all(
        group["qualityPattern"] != NO_QUALITY_SIGNAL_PHRASE for group in result["groups"]
    )

    # The all-clean case yields zero groups honestly (the empty-state UI covers it),
    # rather than surfacing error-free clusters. Candidates were generated and then
    # dropped, so the drop count is reported.
    clean_result = build_multiview_groups_from_frames(
        multi_view_rows(),
        pd.DataFrame(columns=["row_id", "column_id", "error_type"]),
        profiles=profiles(),
        total_rows=120,
    )
    assert clean_result["groups"] == []
    assert clean_result["adaptivePolicy"]["groupsDroppedWithoutQualitySignal"] > 0


def test_no_signal_fallback_text_has_no_internal_jargon():
    # The user-facing fallback phrases (used when a surviving group has a quality signal
    # but no single standout semantic field, or is a near-duplicate advisory) must never
    # leak implementation vocabulary. Asserted directly on the constants so the check is
    # non-vacuous even though error-free groups are now filtered out entirely.
    from app.server_utils.multi_view_grouping import (
        NO_QUALITY_SIGNAL_PHRASE,
        NO_STANDOUT_FIELD_COHORT,
    )

    for phrase in (NO_STANDOUT_FIELD_COHORT, NO_QUALITY_SIGNAL_PHRASE):
        lowered = phrase.lower()
        assert "profiler" not in lowered
        assert "natural break" not in lowered
        assert "no recurring detected quality issue" not in lowered


def test_analyst_signal_rewards_meaning_and_a_real_issue_together_without_requiring_either_alone():
    # The ranking should favor "this segment means something AND something is wrong
    # with it" over either half alone — a data analyst's actionable finding — while
    # never disqualifying groups that only have one half.
    combined = analyst_signal_strength([
        {"kind": "categorical", "strength": 0.6},
        {"kind": "numeric", "strength": 0.4},
        {"kind": "quality", "strength": 0.3, "enriched": True},
    ])
    semantic_only = analyst_signal_strength([
        {"kind": "categorical", "strength": 0.9},
        {"kind": "numeric", "strength": 0.8},
    ])
    quality_not_enriched = analyst_signal_strength([
        {"kind": "categorical", "strength": 0.9},
        {"kind": "quality", "strength": 0.1, "enriched": False},
    ])
    quality_only_no_story = analyst_signal_strength([
        {"kind": "quality", "strength": 0.5, "enriched": True},
    ])

    assert combined > 0.0
    assert semantic_only == 0.0
    assert quality_not_enriched == 0.0
    assert quality_only_no_story == 0.0


def test_duplicate_group_descriptions_name_the_actual_matching_fields():
    frame = pd.DataFrame({
        "ID": range(1, 21),
        "record_key": [f"K{index}" for index in range(20)],
        "region": (["west"] * 6 + ["east"] * 14),
        "tier": (["gold"] * 6 + ["silver"] * 14),
        "spend": ([500] * 6 + [10 + (index % 5) for index in range(14)]),
    })
    profile_map = {
        "record_key": profile("identifier"),
        "region": profile("categorical"),
        "tier": profile("categorical"),
        "spend": profile("numeric_measure"),
    }
    result = build_multiview_groups_from_frames(
        frame,
        errors_in(range(1, 7), "spend"),
        profiles=profile_map,
        total_rows=len(frame),
    )
    duplicate_groups = [group for group in result["groups"] if group["view"] == "duplicates"]
    assert duplicate_groups, "the 6 identical west/gold/500 rows should form a duplicate group"
    matched = next(
        group for group in duplicate_groups
        if any("west" in field.get("groupValue", "") for field in group["supportingFields"])
    )
    cohort = matched["semanticCohort"]
    # The headline must name the actual VALUES, not just the columns, so two groups that
    # both "match on Region and Tier" read as distinct cohorts.
    assert cohort != "Rows with the same normalized non-key values"
    assert "is west" in cohort
    assert "is gold" in cohort
    assert "profiler" not in cohort.lower()


def test_rarity_signal_on_a_group_defining_constant_column_is_suppressed():
    # Caught live: a near-duplicate group all sharing Country=Israel reported "unusually
    # frequent incomplete values in Country" — but every row's Country is fully present.
    # The rare-value detector flags Israel because it's globally uncommon, and the group is
    # DEFINED by Country=Israel, so 100% concentration is guaranteed by construction, not a
    # real within-cluster finding. Such a rarity signal on a constant defining column must
    # be suppressed; genuine problems (mismatch/anomaly) on the same column must not be.
    from app.server_utils.multi_view_grouping import (
        column_is_constant_present_in_group,
        quality_description_candidates,
    )

    group = pd.DataFrame({"ID": [1, 2, 3], "Country": ["Israel"] * 3})
    full = pd.DataFrame({
        "ID": list(range(1, 101)),
        "Country": ["Israel"] * 3 + ["United States"] * 97,
    })
    assert column_is_constant_present_in_group(group, "Country") is True

    rarity_df = pd.DataFrame({
        "row_id": [1, 2, 3],
        "column_id": ["Country"] * 3,
        "error_type": ["incomplete"] * 3,
    })
    rarity_candidates = quality_description_candidates(group, full, rarity_df, {})
    assert all(candidate["column"] != "Country" for candidate in rarity_candidates), (
        "a global-rarity signal on the group's own constant defining column is tautological"
    )

    mismatch_df = pd.DataFrame({
        "row_id": [1, 2, 3],
        "column_id": ["Country"] * 3,
        "error_type": ["mismatch"] * 3,
    })
    mismatch_candidates = quality_description_candidates(group, full, mismatch_df, {})
    assert any(candidate["column"] == "Country" for candidate in mismatch_candidates), (
        "a type mismatch is a real problem even on a constant column; do not suppress it"
    )


def test_rare_value_quality_phrasing_does_not_claim_missing_data():
    # detectors/incomplete.py flags statistically rare categorical values, not missing
    # data, but historically kept the error_type "incomplete" for backward compatibility
    # with the DB error schema. Caught live: a rare-but-present value concentrated in a
    # cluster was described as "incomplete values in Country", which reads as missing/
    # blank data to anyone who doesn't know the legacy label's history. The phrase must
    # describe rarity/concentration, never incompleteness, for this legacy label.
    phrase = humanize_quality_issue("incomplete", "Country")
    assert "incomplete" not in phrase
    assert "missing" not in phrase
    assert "rare" in phrase

    # A real "missing" signal (a different detector, a different error_type) must still
    # say missing — this fix must not blur the two together.
    missing_phrase = humanize_quality_issue("missing", "Country")
    assert "missing" in missing_phrase


def test_semantic_embeddings_are_opt_in_and_do_not_change_the_default_path():
    # Opt-in evidence path (docs/clustering/RANKING_AND_SIMILARITY_POSITION.md):
    # embeddings must never activate unless explicitly requested, and requesting
    # them must not touch columns outside the role+cardinality gate.
    import numpy as np

    def fake_embedder(values):
        vectors = []
        for value in values:
            vectors.append([1.0, 0.0] if "developer" in value.lower() else [0.0, 1.0])
        return np.asarray(vectors, dtype=float)

    frame = pd.DataFrame({
        "ID": range(1, 41),
        "job_title": [f"{'Back-end' if i % 2 == 0 else 'Front-end'} developer {i}" for i in range(40)],
        "country": [f"Country {i}" for i in range(35)] + ["Country 0"] * 5,
        "education": [f"Level {i}" for i in range(30)] + ["Level 0"] * 10,
        "gender": (["Male", "Female"] * 20),
    })
    profile_map = {
        "job_title": {"role": "categorical", "family": "categorical", "confidence": 0.9},
        "country": {"role": "categorical", "family": "categorical", "confidence": 0.9},
        "education": {"role": "categorical", "family": "categorical", "confidence": 0.9},
        "gender": {"role": "binary_category", "family": "categorical", "confidence": 0.9},
    }
    columns = list(profile_map)

    default_matrix, default_info = build_view_matrix(frame, "business", columns, profile_map)
    assert "embeddingColumns" not in default_info, "default path must not activate embeddings"

    opted_in_matrix, opted_in_info = build_view_matrix(
        frame, "business", columns, profile_map,
        use_semantic_embeddings=True, embedder=fake_embedder,
    )
    assert "job_title" in opted_in_info["embeddingColumns"]
    # gender is role-gated out even when embeddings are requested for the view.
    assert "gender" not in opted_in_info["embeddingColumns"]
    # The two representations are genuinely different matrices, not a no-op flag.
    assert opted_in_matrix.shape != default_matrix.shape or not np.allclose(
        opted_in_matrix[:, :default_matrix.shape[1]], default_matrix
    )


def test_parse_ordinal_bucket_value_requires_genuine_range_structure():
    from app.server_utils.multi_view_grouping import parse_ordinal_bucket_value

    # Real StackOverflow-style bucket strings -- all must parse.
    assert parse_ordinal_bucket_value("18-24 years old") == 21.0
    assert parse_ordinal_bucket_value("9 - 12 hours") == 10.5
    assert parse_ordinal_bucket_value("Under 18 years old") == 18.0
    assert parse_ordinal_bucket_value("Over 12 hours") == 12.0
    assert parse_ordinal_bucket_value("Less than 1 hour") == 1.0
    assert parse_ordinal_bucket_value("30 or more years") == 30.0
    assert parse_ordinal_bucket_value("$25,000 to $34,999") == 29999.5

    # Caught live: a bare "label + number" with no range/comparison structure
    # must NOT parse -- otherwise any coded category or ID fragment that
    # happens to contain a digit ("Country 14", "Job 7") would be mistaken
    # for a bucketed scale.
    assert parse_ordinal_bucket_value("Country 14") is None
    assert parse_ordinal_bucket_value("Job 7") is None
    assert parse_ordinal_bucket_value("SKU-2291") is None
    assert parse_ordinal_bucket_value("Some college") is None
    assert parse_ordinal_bucket_value(None) is None


def test_ordinal_eligible_columns_gates_role_parseability_and_repetition():
    from app.server_utils.multi_view_grouping import ordinal_eligible_columns

    frame = pd.DataFrame({
        # Genuine bucket scale: every value repeats across many rows.
        "years_coding": (["0-2 years", "3-5 years", "6-8 years", "9-11 years"] * 10),
        # Contains numbers but no range structure -- must not qualify.
        "country": [f"Country {i}" for i in range(35)] + ["Country 0"] * 5,
        # Purely verbal ordering with no digits at all -- documented gap.
        "education": (["Some college", "Bachelor's", "Master's", "PhD"] * 10),
        # One stray non-numeric value disqualifies the whole column.
        "hours_with_outlier": (["1 - 4 hours", "5 - 8 hours", "Prefer not to say"] * 10 + ["9 - 12 hours"] * 10),
        # Numeric family, not categorical role -- role gate excludes it.
        "amount": list(range(40)),
    })
    profile_map = {
        "years_coding": {"role": "categorical", "family": "categorical", "confidence": 0.9},
        "country": {"role": "categorical", "family": "categorical", "confidence": 0.9},
        "education": {"role": "categorical", "family": "categorical", "confidence": 0.9},
        "hours_with_outlier": {"role": "categorical", "family": "categorical", "confidence": 0.9},
        "amount": {"role": "numeric_measure", "family": "numeric", "confidence": 0.9},
    }
    columns = list(profile_map)

    eligible = ordinal_eligible_columns(columns, frame, profile_map)

    assert eligible == ["years_coding"]


def test_ordinal_columns_replace_token_treatment_and_propagate_to_feature_info():
    # Mirrors the embeddingColumns propagation regression test -- the same
    # merge-drop bug class is possible here too, so this is verified directly
    # rather than assumed to work by analogy.
    import numpy as np

    from app.server_utils.multi_view_grouping import (
        build_semantic_quality_matrix,
        ordinal_description_candidate,
    )

    frame = pd.DataFrame({
        "ID": range(1, 41),
        "years_coding": (["0-2 years", "3-5 years", "6-8 years", "9-11 years"] * 10),
        "gender": (["Male", "Female"] * 20),
    })
    profile_map = {
        "years_coding": {"role": "categorical", "family": "categorical", "confidence": 0.9},
        "gender": {"role": "binary_category", "family": "categorical", "confidence": 0.9},
    }

    default_matrix, default_info = build_view_matrix(frame, "business", list(profile_map), profile_map)
    assert default_info.get("ordinalColumns") == ["years_coding"]
    # Replace, not add: an ordinal column's raw strings must not also appear
    # as TF-IDF terms.
    assert not any(term.startswith("years_coding__") for term in default_info.get("terms", []))

    error_df = pd.DataFrame({"row_id": [], "column_id": [], "error_type": []})
    _, merged_info = build_semantic_quality_matrix(
        frame, error_df, view_columns={"business": list(profile_map)}, profile_map=profile_map,
    )
    assert merged_info["ordinalColumns"] == ["years_coding"]
    assert merged_info["representation"]["ordinalColumns"] == ["years_coding"]

    # Description reads a real bucket label ("9-11 years"), not a raw parsed
    # float ("10.0") -- readable in the dataset's own vocabulary.
    high_group = frame[frame["years_coding"].isin(["9-11 years", "6-8 years"])]
    candidate = ordinal_description_candidate(high_group, frame, "years_coding")
    assert candidate is not None
    assert candidate["direction"] == "higher-than-typical"
    assert candidate["groupValue"] in {"9-11 years", "6-8 years"}


def test_ordinal_eligible_columns_bypass_the_general_confidence_cutoff():
    # Caught live: on the real StackOverflow dataset, YearsCoding and
    # HoursComputer -- both perfectly clean bucketed-range columns -- sat just
    # under the adaptive confidence cutoff for reasons unrelated to their own
    # data quality (no profiler name-hint keyword match, same sample-size-only
    # reliability ceiling as every other column). choose_view_columns() must
    # let a column bypass the general cutoff specifically when it independently
    # clears ordinal_eligible_columns()'s own, stronger, per-column evidence --
    # but a low-confidence column that is NOT ordinal-eligible must still be
    # excluded normally; this is a narrow exemption, not a blanket override.
    frame = pd.DataFrame({
        "years_coding": (["0-2 years", "3-5 years", "6-8 years", "9-11 years"] * 10),
        "noisy_field": ([f"Value {i}" for i in range(39)] + ["Value 0"]),
    })
    profile_map = {
        "years_coding": {"role": "categorical", "family": "categorical", "confidence": 0.70},
        "noisy_field": {"role": "categorical", "family": "categorical", "confidence": 0.70},
    }

    view_columns, excluded = choose_view_columns(frame, profile_map, confidence_cutoff=0.85)

    assert "years_coding" in view_columns["business"]
    assert "years_coding" not in excluded["low_confidence"]
    # Not ordinal-eligible (no range structure in its values) -- still excluded
    # normally, proving this is a narrow, per-column exemption, not a general
    # confidence-cutoff relaxation.
    assert "noisy_field" not in view_columns["business"]
    assert "noisy_field" in excluded["low_confidence"]


def test_geography_eligible_columns_bypass_the_general_confidence_cutoff():
    # Same pattern and same reasoning as the ordinal bypass above, caught live
    # as a direct side effect of fixing score_profile_confidence's reliability
    # ceiling: raising most columns' scores shifted the adaptive cutoff itself
    # upward, and "Country" -- whose own geography-role score didn't move --
    # got left behind by columns that moved past it, even though every one of
    # its values resolves cleanly to a real place. A column that independently
    # clears geography_name_eligible_columns() bypasses the cutoff for
    # geography purposes specifically; a low-confidence column that is NOT
    # geography-eligible must still be excluded normally.
    # Distinct fake coordinate per distinct input -- proves the injected
    # resolver is actually being used (a constant return value for every
    # input would collapse to 1 distinct resolved value and fail the "at
    # least 2 distinct" gate regardless of whether it was really called).
    def fake_resolver(value):
        return {"France": (48.85, 2.35), "Germany": (52.52, 13.41), "Poland": (52.23, 21.01)}.get(str(value).strip())

    frame = pd.DataFrame({
        "country": (["France", "Germany", "Poland"] * 10),
        "noisy_field": ([f"Value {i}" for i in range(29)] + ["Value 0"]),
    })
    profile_map = {
        "country": {"role": "location_name", "family": "geography", "confidence": 0.70},
        "noisy_field": {"role": "categorical", "family": "categorical", "confidence": 0.70},
    }

    view_columns, excluded = choose_view_columns(
        frame, profile_map, confidence_cutoff=0.85, country_resolver=fake_resolver,
    )

    assert "country" in view_columns["geography"]
    assert "country" not in excluded["low_confidence"]
    assert "noisy_field" not in view_columns["business"]
    assert "noisy_field" in excluded["low_confidence"]


def test_city_eligible_columns_bypass_the_general_confidence_cutoff():
    # Same exemption pattern as the country-level bypass test above, for the
    # city-level pass: a city-name column that independently clears
    # city_name_eligible_columns() -- using a companion country_code column
    # in the same frame to disambiguate each row -- bypasses the general
    # cutoff for geography purposes, even though its own geography-role score
    # sits below the cutoff. "country" itself resolves cleanly as a country
    # and is not the column under test here; it exists only to supply the
    # per-row disambiguation context "city" needs.
    def fake_country_resolver(value):
        return {"France": (48.85, 2.35), "Germany": (52.52, 13.41), "Poland": (52.23, 21.01)}.get(str(value).strip())

    def fake_city_resolver(value, country_hint=None):
        known = {
            ("Paris", "France"): (48.85, 2.35),
            ("Berlin", "Germany"): (52.52, 13.41),
            ("Warsaw", "Poland"): (52.23, 21.01),
        }
        return known.get((str(value).strip(), country_hint))

    frame = pd.DataFrame({
        "city": (["Paris", "Berlin", "Warsaw"] * 10),
        "country": (["France", "Germany", "Poland"] * 10),
        "noisy_field": ([f"Value {i}" for i in range(29)] + ["Value 0"]),
    })
    profile_map = {
        "city": {"role": "location_name", "family": "geography", "confidence": 0.70},
        "country": {"role": "country_code", "family": "geography", "confidence": 0.95},
        "noisy_field": {"role": "categorical", "family": "categorical", "confidence": 0.70},
    }

    view_columns, excluded = choose_view_columns(
        frame, profile_map, confidence_cutoff=0.85,
        country_resolver=fake_country_resolver, city_resolver=fake_city_resolver,
    )

    assert "city" in view_columns["geography"]
    assert "city" not in excluded["low_confidence"]
    assert "noisy_field" in excluded["low_confidence"]


def test_geography_name_columns_replace_token_treatment_and_propagate_to_feature_info():
    # Mirrors the embeddingColumns/ordinalColumns propagation regression tests
    # -- same merge-drop bug class is possible here too.
    from app.server_utils.multi_view_grouping import (
        build_geography_matrix,
        build_semantic_quality_matrix,
        geography_name_description_candidate,
    )

    def fake_resolver(value):
        return {
            "France": (48.85, 2.35),
            "Germany": (52.52, 13.41),
            "Poland": (52.23, 21.01),
            "Japan": (35.68, 139.65),
            "Australia": (-35.28, 149.13),
        }.get(str(value).strip())

    frame = pd.DataFrame({
        "ID": range(1, 21),
        # A genuine minority (6 of 20 rows) so the group median actually
        # differs from the full-sample baseline -- a group that IS most of
        # the sample trivially has ~zero offset from its own baseline.
        "country": (["France", "Germany", "Poland"] * 2 + ["Japan", "Australia"] * 7),
    })
    profile_map = {
        "country": {"role": "location_name", "family": "geography", "confidence": 0.9},
    }

    matrix, info = build_geography_matrix(frame, ["country"], profile_map, country_resolver=fake_resolver)
    assert info.get("geographyNameColumns") == ["country"]
    # Replace, not add: the location-name column's raw strings must not also
    # appear as TF-IDF terms.
    assert not any(term.startswith("country__") for term in info.get("terms", []))
    assert matrix.shape[1] > 0

    error_df = pd.DataFrame({"row_id": [], "column_id": [], "error_type": []})
    _, merged_info = build_semantic_quality_matrix(
        frame, error_df, view_columns={"geography": ["country"]}, profile_map=profile_map,
        country_resolver=fake_resolver,
    )
    assert merged_info["geographyNameColumns"] == ["country"]
    assert merged_info["representation"]["geographyNameColumns"] == ["country"]

    # A France/Germany/Poland (Europe) group must read as genuinely closer to
    # the sample baseline than the two far-flung outliers (Japan, Australia)
    # pull it -- real distance, not string equality.
    europe_group = frame[frame["country"].isin(["France", "Germany", "Poland"])]
    candidate = geography_name_description_candidate(europe_group, frame, "country", merged_info)
    assert candidate is not None
    assert candidate["kind"] == "geography_name"
    assert "km" in candidate["evidence"]


def test_city_name_columns_use_context_disambiguated_distance_and_propagate_to_feature_info():
    # Mirrors test_geography_name_columns_replace_token_treatment_and_
    # propagate_to_feature_info above, one level down: city-name matching,
    # with the companion "country" column supplying per-row disambiguation
    # context (see geography_reference.city_centroid). "city" resolves as a
    # country under the (deliberately country-blind) fake_country_resolver
    # for none of its values, so it falls through to the city-level pass.
    from app.server_utils.multi_view_grouping import (
        build_geography_matrix,
        geography_name_description_candidate,
    )

    def fake_country_resolver(value):
        return None  # no value here is a country name -- forces the city path

    def fake_city_resolver(value, country_hint=None):
        known = {
            ("Paris", "France"): (48.85, 2.35),
            ("Berlin", "Germany"): (52.52, 13.41),
            ("Tokyo", "Japan"): (35.68, 139.65),
            ("Sydney", "Australia"): (-33.87, 151.21),
        }
        return known.get((str(value).strip(), country_hint))

    frame = pd.DataFrame({
        "ID": range(1, 21),
        "city": (["Paris", "Berlin"] * 3 + ["Tokyo", "Sydney"] * 7),
        "country": (["France", "Germany"] * 3 + ["Japan", "Australia"] * 7),
    })
    profile_map = {
        "city": {"role": "location_name", "family": "geography", "confidence": 0.9},
        "country": {"role": "country_code", "family": "geography", "confidence": 0.95},
    }

    matrix, info = build_geography_matrix(
        frame, ["city", "country"], profile_map,
        country_resolver=fake_country_resolver, city_resolver=fake_city_resolver,
    )

    # "country" (role country_code) never enters the city-eligible role gate
    # itself -- CITY_NAME_ELIGIBLE_ROLES is location_name only -- so it stays
    # untouched as a raw text column, serving purely as "city"'s context.
    assert info.get("cityNameColumns") == ["city"]
    assert info.get("cityContextColumn") == "country"
    assert info.get("geographyNameColumns") == ["city"]
    assert matrix.shape[1] > 0

    europe_group = frame[frame["city"].isin(["Paris", "Berlin"])]
    candidate = geography_name_description_candidate(europe_group, frame, "city", info)
    assert candidate is not None
    assert candidate["kind"] == "geography_name"
    assert "km" in candidate["evidence"]


def test_free_text_embeddings_are_a_separate_opt_in_from_categorical_embeddings():
    # Free-text embeddings replace TF-IDF for eligible columns and must stay
    # behind their own flag -- distinct from use_semantic_embeddings (the
    # categorical path, on by default via plot_routes.py) -- since TF-IDF vs
    # SBERT for genuine prose is a different, less-tested representation swap
    # per the user's explicit "opt-in first" decision.
    import numpy as np

    def fake_embedder(values):
        vectors = []
        for value in values:
            angle = (sum(ord(char) for char in value) % 100) / 100.0 * 2 * np.pi
            vectors.append([np.cos(angle), np.sin(angle)])
        return np.asarray(vectors, dtype=float)

    frame = pd.DataFrame({
        "ID": range(1, 11),
        "complaint_narrative": [
            "The lender never responded to my calls about the loan balance.",
            "My servicer applied my payment to the wrong account entirely.",
            "I was charged a late fee despite paying on the due date.",
            "The company refuses to correct an error on my credit report.",
            "My loan was transferred without any notice being sent to me.",
            "I have been on hold for hours trying to reach a representative.",
            "The website shows an incorrect balance that support cannot explain.",
            "My autopay was cancelled without my consent or knowledge.",
            "I submitted documents twice but they claim nothing was received.",
            "The interest rate changed without any explanation provided to me.",
        ],
    })
    profile_map = {"complaint_narrative": {"role": "free_text", "family": "text", "confidence": 0.9}}
    columns = list(profile_map)

    default_matrix, default_info = build_view_matrix(frame, "text", columns, profile_map)
    assert "embeddingColumns" not in default_info

    # Requesting only the categorical flag must not activate free-text embeddings.
    categorical_only_matrix, categorical_only_info = build_view_matrix(
        frame, "text", columns, profile_map, use_semantic_embeddings=True, embedder=fake_embedder,
    )
    assert "embeddingColumns" not in categorical_only_info
    np.testing.assert_array_equal(categorical_only_matrix, default_matrix)

    opted_in_matrix, opted_in_info = build_view_matrix(
        frame, "text", columns, profile_map, use_free_text_embeddings=True, embedder=fake_embedder,
    )
    assert opted_in_info["embeddingColumns"] == ["complaint_narrative"]
    # Replace, not add: the embedded column must not also appear in the TF-IDF
    # terms, and the resulting matrix must be a genuinely different representation.
    assert not any(term.startswith("complaint_narrative__") for term in opted_in_info.get("terms", []))
    assert opted_in_matrix.shape != default_matrix.shape or not np.allclose(
        opted_in_matrix[:, :default_matrix.shape[1]], default_matrix
    )


def test_categorical_baseline_cache_is_reused_and_does_not_change_the_result():
    # Caught profiling the Chicago Crime dataset: build_grounded_group_description
    # runs once per candidate group (198 near-duplicate candidates before acceptance
    # trims them down on that dataset), and categorical_description_candidate
    # recomputed the full-sample missing/format baseline for a column from scratch
    # every single call -- identical work redone up to 198 times per column. Fixed
    # by threading a shared baseline_cache through so it's computed once per column
    # and reused. Two things must hold: the cache actually gets populated and reused
    # (not silently bypassed), and using it must not change what a group returns.
    from app.server_utils.multi_view_grouping import (
        cached_full_frame_categorical_values,
        categorical_description_candidate,
    )

    full_frame = pd.DataFrame({
        "ID": range(1, 21),
        "segment": ["retail"] * 15 + ["wholesale"] * 5,
    })
    group_rows = full_frame.iloc[:5]

    cache: dict = {}
    first_call = cached_full_frame_categorical_values(full_frame, "segment", cache)
    assert "segment" in cache["categorical"]
    cached_object = cache["categorical"]["segment"]
    second_call = cached_full_frame_categorical_values(full_frame, "segment", cache)
    # Same object identity -- proof the second call reused the cache instead of
    # recomputing (pandas .map() always returns a new Series, so identity can only
    # match if the cached one was returned as-is).
    assert second_call is cached_object
    pd.testing.assert_series_equal(first_call, second_call)

    uncached_result = categorical_description_candidate(group_rows, full_frame, "segment")
    cached_result = categorical_description_candidate(group_rows, full_frame, "segment", cache)
    assert uncached_result == cached_result


def test_embedding_semantic_description_candidate_fires_on_meaning_not_exact_match():
    # Caught live: SBERT embeddings changed which columns fed the clustering matrix
    # (build_view_matrix), but embeddingColumns/embeddingValuesByColumn were dropped
    # during the block-merge in build_semantic_quality_matrix, so the description
    # phase never knew embeddings were used -- descriptions stayed exact-match-only
    # (categorical_description_candidate) even for groups clustered by meaning.
    import numpy as np

    from app.server_utils.multi_view_grouping import embedding_semantic_description_candidate

    # Group is 3 different job titles that are all "developer" roles -- no single
    # value dominates, so categorical_description_candidate would find no concentration
    # and go silent. The embedding cache makes "developer" titles close together and
    # a random other value ("Sales manager") sit apart, matching real SBERT behavior.
    def fake_embed(values):
        return np.asarray(
            [[1.0, 0.0] if "developer" in v.lower() else [0.0, 1.0] for v in values],
            dtype=float,
        )

    rows = pd.DataFrame({
        "ID": [1, 2, 3],
        "job_title": ["Back-end developer", "Front-end developer", "Full-stack developer"],
    })
    all_values = [
        "Back-end developer", "Front-end developer", "Full-stack developer",
        "Sales manager", "Product manager",
    ]
    cache = dict(zip(all_values, fake_embed(all_values)))
    feature_info = {
        "embeddingColumns": ["job_title"],
        "embeddingValuesByColumn": {"job_title": cache},
    }

    candidate = embedding_semantic_description_candidate(rows, "job_title", feature_info)

    assert candidate is not None
    assert candidate["kind"] == "embedding_semantic"
    assert candidate["distinctValueCount"] == 3
    assert "developer" in candidate["cohortPhrase"]
    assert candidate["groupCohesion"] > candidate["baselineCohesion"]

    # A single-value group is exact match, not a semantic-cohesion story -- must
    # defer to categorical_description_candidate instead of firing here.
    single_value_rows = pd.DataFrame({"ID": [1, 2], "job_title": ["Back-end developer"] * 2})
    assert embedding_semantic_description_candidate(single_value_rows, "job_title", feature_info) is None

    # No embedding cache for this column -> not reachable, must return None quietly.
    assert embedding_semantic_description_candidate(rows, "other_column", feature_info) is None


def test_embedding_semantic_description_candidate_summarizes_prose_instead_of_quoting_it():
    # Free-text embedded values are full sentences, not single words/phrases --
    # quoting up to 3 of them verbatim (the short-value behavior, tested above)
    # produced 250+ character headlines. For prose, this must summarize via
    # shared recurring words instead of quoting the sentences.
    import numpy as np

    from app.server_utils.multi_view_grouping import embedding_semantic_description_candidate

    def fake_embed(values):
        return np.asarray(
            [[1.0, 0.0] if "call" in v.lower() else [0.0, 1.0] for v in values],
            dtype=float,
        )

    narratives = [
        "The lender never returned any of my calls about the balance",
        "Nobody from the company would return my calls about my account",
        "My servicer never called me back about the loan balance either",
    ]
    other_narratives = [
        "The interest rate changed without any explanation being provided",
        "My documents were lost and nobody could explain what happened",
    ]
    rows = pd.DataFrame({"ID": [1, 2, 3], "narrative": narratives})
    all_values = narratives + other_narratives
    cache = dict(zip(all_values, fake_embed(all_values)))
    feature_info = {
        "embeddingColumns": ["narrative"],
        "embeddingValuesByColumn": {"narrative": cache},
    }

    candidate = embedding_semantic_description_candidate(rows, "narrative", feature_info)

    assert candidate is not None
    # No sentence quoted verbatim in the headline -- summarized, not quoted.
    for sentence in narratives:
        assert sentence not in candidate["cohortPhrase"]
    # "calls"/"call" and "return"/"returned" recur across the group's own
    # wording -- a grounded summary, not a fabricated one.
    assert "call" in candidate["cohortPhrase"] or "calls" in candidate["cohortPhrase"]
    assert len(candidate["cohortPhrase"]) < 150

    # Short label-like values must still be quoted, not summarized -- this is
    # a prose-only behavior change, verified against the existing short-value
    # test's exact assertion style.
    def fake_embed_by_developer(values):
        return np.asarray(
            [[1.0, 0.0] if "developer" in v.lower() else [0.0, 1.0] for v in values],
            dtype=float,
        )

    short_rows = pd.DataFrame({
        "ID": [1, 2, 3],
        "job_title": ["Back-end developer", "Front-end developer", "Full-stack developer"],
    })
    short_values = ["Back-end developer", "Front-end developer", "Full-stack developer", "Sales manager"]
    short_cache = dict(zip(short_values, fake_embed_by_developer(short_values)))
    short_candidate = embedding_semantic_description_candidate(
        short_rows, "job_title", {"embeddingColumns": ["job_title"], "embeddingValuesByColumn": {"job_title": short_cache}},
    )
    assert "Back-end developer" in short_candidate["cohortPhrase"]


def test_build_semantic_quality_matrix_propagates_embedding_metadata_for_descriptions():
    # Regression for the merge-drop bug above: build_view_matrix sets embeddingColumns
    # per block, but build_semantic_quality_matrix merges block info into one dict for
    # the whole group -- that merge must not silently lose the embedding keys.
    import numpy as np

    from app.server_utils.multi_view_grouping import build_semantic_quality_matrix

    def fake_embedder(values):
        # Deterministic but value-varying (unlike a single-keyword split) so every
        # distinct string gets a genuinely different vector -- otherwise the whole
        # block has zero variance, gets dropped by normalize_evidence_block before
        # the merge step even runs, and this test can't tell "correctly filtered
        # out" apart from "the metadata propagation bug this test targets".
        vectors = []
        for value in values:
            angle = (sum(ord(char) for char in value) % 100) / 100.0 * 2 * np.pi
            vectors.append([np.cos(angle), np.sin(angle)])
        return np.asarray(vectors, dtype=float)

    frame = pd.DataFrame({
        "ID": range(1, 31),
        "job_title": [f"{'Back-end' if i % 2 == 0 else 'Front-end'} developer {i}" for i in range(30)],
        "country": [f"Country {i}" for i in range(25)] + ["Country 0"] * 5,
        "education": [f"Level {i}" for i in range(20)] + ["Level 0"] * 10,
    })
    profile_map = {
        "job_title": {"role": "categorical", "family": "categorical", "confidence": 0.9},
        "country": {"role": "categorical", "family": "categorical", "confidence": 0.9},
        "education": {"role": "categorical", "family": "categorical", "confidence": 0.9},
    }
    error_df = pd.DataFrame({"row_id": [], "column_id": [], "error_type": []})

    _, feature_info = build_semantic_quality_matrix(
        frame,
        error_df,
        view_columns={"business": list(profile_map)},
        profile_map=profile_map,
        use_semantic_embeddings=True,
        embedder=fake_embedder,
    )

    assert "job_title" in feature_info["embeddingColumns"]
    assert "job_title" in feature_info["embeddingValuesByColumn"]
    assert feature_info["representation"]["embeddingColumns"] == feature_info["embeddingColumns"]


def test_identifier_columns_are_excluded_from_every_semantic_distance_view():
    identifier_errors = pd.DataFrame({
        "row_id": list(range(1, 11)),
        "column_id": ["customer_id"] * 10,
        "error_type": ["format mismatch"] * 10,
    })
    result = build_multiview_groups_from_frames(
        multi_view_rows(),
        identifier_errors,
        profiles=profiles(),
        total_rows=120,
    )

    assert result["profileSummary"]["excludedIdentifierColumns"] == ["customer_id"]
    assert "customer_id" not in result["representation"]["semanticColumns"]
    assert "customer_id" not in result["representation"]["qualityColumns"]
    assert result["representation"]["qualitySignalRows"] == 0
    assert all("customer_id" not in group["columnsUsed"] for group in result["groups"])


def test_quality_signals_join_semantics_instead_of_creating_quality_only_groups():
    frame = multi_view_rows()
    error_rows = pd.DataFrame({
        "row_id": list(range(1, 21)),
        "column_id": ["notes"] * 20,
        "error_type": ["missing"] * 20,
    })
    result = build_multiview_groups_from_frames(
        frame,
        error_rows,
        profiles=profiles(),
        total_rows=120,
        min_group_size=8,
    )

    assert "quality" in result["representation"]["activeBlocks"]
    assert result["representation"]["qualitySignalRows"] == 20
    assert result["representation"]["qualitySignalTypes"] == ["missing"]
    assert result["representation"]["qualityColumns"] == ["notes"]
    json.dumps(result)
    assert any(group["view"] == "semantic_quality" for group in result["groups"])
    assert all(group["view"] != "quality" for group in result["groups"])
    assert any(
        field["kind"] == "quality" and "notes" in field["column"]
        for group in result["groups"]
        for field in group["supportingFields"]
    )


def test_user_override_changes_the_columns_used_by_views():
    result = build_multiview_groups_from_frames(
        multi_view_rows(),
        pd.DataFrame(columns=["row_id", "column_id", "error_type"]),
        profiles=profiles(),
        overrides={"segment": {"role": "identifier"}},
        total_rows=120,
    )

    assert "segment" in result["profileSummary"]["excludedIdentifierColumns"]
    assert "segment" in result["profileSummary"]["userOverridesApplied"]
    assert all("segment" not in group["columnsUsed"] for group in result["groups"])


def test_low_confidence_feature_gate_is_derived_from_observed_profile_scores():
    frame = multi_view_rows()
    frame["weak_code"] = [f"code-{index % 5}" for index in range(len(frame))]
    profiled = profiles()
    profiled["weak_code"] = profile("categorical", confidence=0.12)

    result = build_multiview_groups_from_frames(
        frame,
        pd.DataFrame(columns=["row_id", "column_id", "error_type"]),
        profiles=profiled,
        total_rows=len(frame),
    )

    cutoff = result["adaptivePolicy"]["profile_confidence_cutoff"]
    assert 0.12 < cutoff < 0.95
    assert "weak_code" in result["profileSummary"]["excludedLowConfidenceColumns"]
    assert all("weak_code" not in group["columnsUsed"] for group in result["groups"])


def test_unfamiliar_roles_use_value_driven_generic_fallback_without_name_rules():
    frame = pd.DataFrame({
        "ID": range(1, 81),
        "zxq_flux": [1.0 + (index % 3) for index in range(40)]
        + [100.0 + (index % 3) for index in range(40)],
        "glyph_bundle": ["amber form"] * 40 + ["cyan form"] * 40,
        "known_measure": [10 + (index % 2) for index in range(40)]
        + [90 + (index % 2) for index in range(40)],
        "event_time": [
            (datetime(2026, 1, 1) + timedelta(days=index)).isoformat()
            for index in range(80)
        ],
    })
    profiled = {
        "zxq_flux": profile("previously_unseen_numeric_role"),
        "glyph_bundle": profile("previously_unseen_symbolic_role"),
        "known_measure": profile("numeric_measure"),
        "event_time": profile("datetime_high_uniqueness"),
    }

    result = build_multiview_groups_from_frames(
        frame,
        errors_in(range(1, 21), "known_measure"),
        profiles=profiled,
        total_rows=len(frame),
    )

    representation = result["representation"]
    assert "generic" in representation["activeBlocks"]
    assert representation["routingPolicy"].startswith("mutually exclusive")
    assignments = representation["semanticColumnAssignments"]
    assert assignments["zxq_flux"] == "generic"
    assert assignments["glyph_bundle"] == "generic"
    assert assignments["known_measure"] == "business"
    assert assignments["event_time"] == "lifecycle"
    generic_block = next(block for block in representation["blocks"] if block["id"] == "generic")
    assert generic_block["observedValueFallbackRoles"]["zxq_flux"] == "numeric_measure"
    assert generic_block["observedValueFallbackRoles"]["glyph_bundle"] == "categorical"
    assert set(assignments) == set(representation["semanticColumns"])
    assert all(
        len([
            block for block in representation["blocks"]
            if column in block["routedColumns"] and block["id"] != "quality"
        ]) == 1
        for column in representation["semanticColumns"]
    )
    assert any(group["view"] == "semantic_quality" for group in result["groups"])


def test_clustering_deduplicates_before_selecting_k():
    # Caught live on a duplicate-dense synthetic dataset (documented in
    # ADAPTIVE_DECISION_POLICY.md's "Near-duplicate crowd-out risk" section):
    # a numerically-dominant near-duplicate-dense majority distorted k-
    # selection and DBSCAN's epsilon enough to bury a smaller, genuine
    # minority cluster before it ever became a candidate. Fixed by making
    # every clustering decision on the matrix's distinct rows, expanding
    # labels back to one entry per original row afterward. This test locks
    # in the mechanical correctness of that expansion -- not the full
    # end-to-end k-selection outcome, which is sensitive to many interacting
    # factors and already verified separately, ad hoc, against a realistic
    # adversarial dataset.
    import numpy as np

    # 60 rows collapsing to 6 distinct duplicate-signature points (10 rows
    # each, tight around 6 well-separated centers) plus 12 minority rows
    # that are each their own distinct point (small random jitter).
    rng = np.random.default_rng(7)
    centers = np.eye(6, dtype=float) * 5.0
    majority_rows = np.repeat(centers, 10, axis=0)
    minority_rows = np.array([[10.0, 10.0, 0, 0, 0, 0]] * 6) + rng.normal(0, 1e-6, (6, 6))
    minority_rows = np.vstack([minority_rows, np.array([[0, 0, 10.0, 10.0, 0, 0]] * 6) + rng.normal(0, 1e-6, (6, 6))])
    matrix = np.vstack([majority_rows, minority_rows])
    n_rows = matrix.shape[0]

    labels, alternate, algorithm_label, diagnostics = run_internal_clustering(matrix, min_group_size=3)

    # Labels must be expanded back to one entry per original row -- every
    # downstream consumer (groups_from_partition, row counts) needs this.
    assert len(labels) == n_rows
    assert len(alternate) == n_rows

    # Every one of the 6 exact-duplicate majority groups (10 identical rows
    # each) must share a single label -- they are literally the same point,
    # so splitting them would mean the expansion step is wrong.
    for group_index in range(6):
        group_labels = labels[group_index * 10:(group_index + 1) * 10]
        assert len(set(group_labels.tolist())) == 1, (
            f"duplicate-signature group {group_index} split across multiple labels: {group_labels}"
        )

    assert diagnostics["kCandidates"], "expected at least one k candidate"
