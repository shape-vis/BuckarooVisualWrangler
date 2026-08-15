import pandas as pd
import pytest

from app.server_utils.semantic_grouping import build_semantic_groups_from_frames, friendly_name


def sample_customer_rows():
    rows = []
    for row_id in range(1, 13):
        rows.append({
            "ID": row_id,
            "product": "Student Loan",
            "issue": "deferment payment loan",
            "state": "CA",
            "amount": 1200 + row_id,
        })
    for row_id in range(13, 25):
        rows.append({
            "ID": row_id,
            "product": "Credit Card",
            "issue": "cashback rewards credit card",
            "state": "NY",
            "amount": 100 + row_id,
        })
    return pd.DataFrame(rows)


def sample_error_rows():
    return pd.DataFrame({
        "row_id": list(range(1, 11)),
        "column_id": ["company_response"] * 10,
        "error_type": ["missing"] * 10,
    })


def test_cluster_first_finds_semantic_error_concentration():
    result = build_semantic_groups_from_frames(
        sample_customer_rows(),
        sample_error_rows(),
        strategy="cluster_first",
        min_group_size=4,
        min_error_rows=2,
    )

    assert result["similarityTool"] == "buckaroo_tfidf_cosine_v1"
    assert result["baselineErrorRate"] == pytest.approx(10 / 24)
    assert result["groups"]
    assert any(
        group["mainIssue"] == "missing:company_response" and group["lift"] > 1.5
        for group in result["groups"]
    )


def test_error_first_groups_only_error_rows():
    result = build_semantic_groups_from_frames(
        sample_customer_rows(),
        sample_error_rows(),
        strategy="error_first",
        min_group_size=4,
        min_error_rows=2,
    )

    assert result["effectiveStrategy"] == "error_first"
    assert result["groups"]
    assert all(group["errorRate"] == 1.0 for group in result["groups"])


def test_exact_slices_return_understandable_group_labels():
    result = build_semantic_groups_from_frames(
        sample_customer_rows(),
        sample_error_rows(),
        strategy="exact_slices",
        min_group_size=4,
        min_error_rows=2,
    )

    labels = [group["description"] for group in result["groups"]]
    assert any("product = Student Loan" in label for label in labels)


def test_friendly_name_preserves_source_words_while_splitting_camel_case():
    assert friendly_name("ConvertedSalary") == "Converted Salary"
    assert friendly_name("pickup_zone") == "pickup zone"
