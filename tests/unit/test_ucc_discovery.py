import pandas as pd

from detectors.ucc_discovery import discover_ucc_candidates


def _profile(rows):
    return pd.DataFrame(rows)


def test_ucc_lite_reports_minimal_single_and_composite_keys():
    data_frame = pd.DataFrame(
        {
            "order_id": ["O1", "O2", "O3", "O4", "O5"],
            "customer_id": ["C1", "C1", "C2", "C2", "C3"],
            "order_date": ["2024-01-01", "2024-01-02", "2024-01-01", "2024-01-02", "2024-01-01"],
            "region": ["North", "North", "South", "South", "North"],
            "amount": [10.5, 12.0, 19.5, 20.0, 8.0],
            "review": ["quick delivery", "fine", "late", "fine", "quick delivery"],
        }
    )
    column_profile = _profile(
        [
            {
                "column": "order_id",
                "role": "identifier",
                "profile_role": "identifier",
                "full_estimated_cardinality_ratio": 1.0,
                "full_estimated_unique_count": 5,
                "id_name_hint": True,
            },
            {
                "column": "customer_id",
                "role": "identifier",
                "profile_role": "identifier",
                "full_estimated_cardinality_ratio": 0.6,
                "full_estimated_unique_count": 3,
                "id_name_hint": True,
            },
            {
                "column": "order_date",
                "role": "categorical",
                "profile_role": "datetime_category",
                "full_estimated_cardinality_ratio": 0.4,
                "full_estimated_unique_count": 2,
                "id_name_hint": False,
            },
            {
                "column": "region",
                "role": "categorical",
                "profile_role": "categorical",
                "full_estimated_cardinality_ratio": 0.4,
                "full_estimated_unique_count": 2,
                "id_name_hint": False,
            },
            {
                "column": "amount",
                "role": "numeric",
                "profile_role": "numeric_measure",
                "full_estimated_cardinality_ratio": 1.0,
                "full_estimated_unique_count": 5,
                "id_name_hint": False,
            },
            {
                "column": "review",
                "role": "free_text",
                "profile_role": "free_text",
                "full_estimated_cardinality_ratio": 0.6,
                "full_estimated_unique_count": 3,
                "id_name_hint": False,
            },
        ]
    )

    candidates = discover_ucc_candidates(data_frame, column_profile, max_arity=2)
    candidate_names = {candidate["columns"] for candidate in candidates}

    assert "order_id" in candidate_names
    assert "customer_id + order_date" in candidate_names
    assert "amount" not in candidate_names
    assert "review" not in candidate_names
    assert not any(name.startswith("order_id +") for name in candidate_names)

    composite = next(candidate for candidate in candidates if candidate["columns"] == "customer_id + order_date")
    assert composite["arity"] == 2
    assert composite["uniqueness_ratio"] == 1.0
    assert composite["duplicate_count"] == 0
    assert composite["is_unique"] is True
    assert composite["is_minimal"] is True
    assert composite["confidence"] == "high"


def test_ucc_lite_checks_triples_only_after_near_unique_pairs():
    data_frame = pd.DataFrame(
        {
            "customer_id": ["C1", "C1", "C1", "C2", "C2", "C2"],
            "order_date": ["D1", "D1", "D2", "D1", "D2", "D2"],
            "line_number": [1, 2, 1, 1, 1, 2],
        }
    )
    column_profile = _profile(
        [
            {
                "column": "customer_id",
                "role": "identifier",
                "profile_role": "identifier",
                "full_estimated_cardinality_ratio": 0.33,
                "full_estimated_unique_count": 2,
                "id_name_hint": True,
            },
            {
                "column": "order_date",
                "role": "categorical",
                "profile_role": "datetime_category",
                "full_estimated_cardinality_ratio": 0.33,
                "full_estimated_unique_count": 2,
                "id_name_hint": False,
            },
            {
                "column": "line_number",
                "role": "categorical",
                "profile_role": "numeric_code_category",
                "full_estimated_cardinality_ratio": 0.33,
                "full_estimated_unique_count": 2,
                "id_name_hint": False,
            },
        ]
    )

    candidates = discover_ucc_candidates(
        data_frame,
        column_profile,
        max_arity=3,
        near_unique_threshold=0.6,
    )
    candidate_names = {candidate["columns"] for candidate in candidates}

    assert "customer_id + line_number + order_date" in candidate_names
    triple = next(
        candidate
        for candidate in candidates
        if candidate["columns"] == "customer_id + line_number + order_date"
    )
    assert triple["arity"] == 3
    assert triple["is_unique"] is True
    assert triple["is_minimal"] is True


def test_ucc_lite_skips_high_uniqueness_timestamps_as_primary_keys():
    data_frame = pd.DataFrame(
        {
            "id": [1, 2, 3, 4],
            "created_at": [
                "2024-01-01 00:00:00",
                "2024-01-01 00:01:00",
                "2024-01-01 00:02:00",
                "2024-01-01 00:03:00",
            ],
            "status": ["new", "new", "done", "done"],
        }
    )
    column_profile = _profile(
        [
            {
                "column": "id",
                "role": "identifier",
                "profile_role": "identifier",
                "full_estimated_cardinality_ratio": 1.0,
                "full_estimated_unique_count": 4,
                "id_name_hint": True,
            },
            {
                "column": "created_at",
                "role": "categorical",
                "profile_role": "datetime_high_uniqueness",
                "full_estimated_cardinality_ratio": 1.0,
                "full_estimated_unique_count": 4,
                "id_name_hint": False,
            },
            {
                "column": "status",
                "role": "categorical",
                "profile_role": "categorical",
                "full_estimated_cardinality_ratio": 0.5,
                "full_estimated_unique_count": 2,
                "id_name_hint": False,
            },
        ]
    )

    candidates = discover_ucc_candidates(data_frame, column_profile, max_arity=2)
    candidate_names = {candidate["columns"] for candidate in candidates}

    assert "id" in candidate_names
    assert "created_at" not in candidate_names
    assert not any("created_at" in name for name in candidate_names)


def test_ucc_lite_skips_high_uniqueness_geography_fields_as_primary_keys():
    data_frame = pd.DataFrame(
        {
            "airport_id": ["A1", "A2", "A3", "A4"],
            "latitude": [40.1, 40.2, 40.3, 40.4],
            "longitude": [-73.1, -73.2, -73.3, -73.4],
            "city": ["Alpha", "Beta", "Gamma", "Delta"],
        }
    )
    column_profile = _profile(
        [
            {
                "column": "airport_id",
                "role": "identifier",
                "profile_role": "identifier",
                "full_estimated_cardinality_ratio": 1.0,
                "full_estimated_unique_count": 4,
                "id_name_hint": True,
            },
            {
                "column": "latitude",
                "role": "categorical",
                "profile_role": "geographic_coordinate",
                "full_estimated_cardinality_ratio": 1.0,
                "full_estimated_unique_count": 4,
                "id_name_hint": False,
            },
            {
                "column": "longitude",
                "role": "categorical",
                "profile_role": "geographic_coordinate",
                "full_estimated_cardinality_ratio": 1.0,
                "full_estimated_unique_count": 4,
                "id_name_hint": False,
            },
            {
                "column": "city",
                "role": "categorical",
                "profile_role": "high_uniqueness_location_field",
                "full_estimated_cardinality_ratio": 1.0,
                "full_estimated_unique_count": 4,
                "id_name_hint": False,
            },
        ]
    )

    candidates = discover_ucc_candidates(data_frame, column_profile, max_arity=2)
    candidate_names = {candidate["columns"] for candidate in candidates}

    assert "airport_id" in candidate_names
    assert "latitude" not in candidate_names
    assert "longitude" not in candidate_names
    assert "city" not in candidate_names
    assert not any("latitude" in name or "longitude" in name or "city" in name for name in candidate_names)
