"""Tests for the column-menu row filtering API."""

from unittest.mock import MagicMock

from app import app
from app.routes import filter_routes


def test_numeric_column_filter_guards_dirty_values_and_quotes_identifiers():
    predicates = filter_routes._build_sql_predicate(
        "n0_sales",
        {
            "viewType": "barchart",
            "cols": ["Sale Price"],
            "data": [{"bin": 0, "type": "numeric"}],
            "scaleX": {"numeric": [{"x0": 10, "x1": 20}]},
            "scaleY": None,
        },
    )

    assert len(predicates) == 1
    assert '"n0_sales"."Sale Price"::text ~' in predicates[0]
    assert 'THEN "n0_sales"."Sale Price"::numeric END' in predicates[0]
    assert ">= 10.0" in predicates[0]
    assert "<= 20.0" in predicates[0]


def test_categorical_filter_handles_quotes_and_nulls():
    quoted = filter_routes._build_sql_predicate(
        "n0_sales",
        {
            "viewType": "barchart",
            "cols": ["Country"],
            "data": [{"bin": "Cote d'Ivoire", "type": "categorical"}],
            "scaleX": {},
            "scaleY": None,
        },
    )
    null_value = filter_routes._build_sql_predicate(
        "n0_sales",
        {
            "viewType": "barchart",
            "cols": ["Country"],
            "data": [{"bin": "null", "type": "categorical"}],
            "scaleX": {},
            "scaleY": None,
        },
    )

    assert quoted == ['"n0_sales"."Country"::text = \'Cote d\'\'Ivoire\'']
    assert null_value == ['"n0_sales"."Country" IS NULL']


def test_filter_add_applies_one_backend_filter_for_selected_bins(monkeypatch):
    operations = MagicMock()
    operations.main_table_name = "n0_sales"
    operations.add_data_filters.return_value = {"Success": True, "Index": [4]}
    monkeypatch.setattr(filter_routes, "db_operations", operations)

    with app.test_request_context(
        "/api/filter/add",
        method="POST",
        json={
            "table": "n0_sales",
            "selection": {
                "viewType": "barchart",
                "cols": ["Country"],
                "data": [
                    {"bin": "India", "type": "categorical"},
                    {"bin": "Netherlands", "type": "categorical"},
                ],
                "scaleX": {},
                "scaleY": None,
            },
        },
    ):
        result = filter_routes.filter_add()

    assert result == {"success": True, "filterIndices": [4]}
    predicate = operations.add_data_filters.call_args.args[0][0]
    assert "India" in predicate
    assert "Netherlands" in predicate
    assert " OR " in predicate
