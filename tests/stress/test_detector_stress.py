"""
The error detectors (app/db_utils/detector_sql.py) and the node metrics read from them, over generated datasets,
held to the answer key's flags - every cell, every error type, no duplicates.
"""
import pytest

import app
from app import engine
from app.db_utils.execute_sql import errors_table_name, fetch_sql, quote_identifier
from tests.stress import generators, reference
from tests.stress.conftest import seeds


def stored_flags(table):
    """The errors table's rows as (row id, column, error type), duplicates kept so a test can see them."""
    errors = quote_identifier(errors_table_name(table))
    rows = fetch_sql(f"SELECT row_id, column_id, error_type FROM {errors}", False, engine) or []
    flags = []
    for row_id, column, error_type in rows:
        flags.append((int(row_id), column, error_type))
    return flags


def assert_flags_match(table, expected):
    """The app's flags are the answer key's: none missing, none extra, none twice. Borderline cells may go either way."""
    actual = stored_flags(table.name)
    assert len(actual) == len(set(actual)), f"duplicate flags in {table.name}"

    actual_set = set(actual)
    missing = expected.certain - actual_set
    extra = actual_set - expected.certain - expected.borderline
    assert not missing, f"flags the app did not raise: {sorted(missing)[:10]}"
    assert not extra, f"flags the app raised that it should not have: {sorted(extra)[:10]}"


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_flags_match_the_answer_key_after_an_upload(make_root, seed):
    dataset = generators.make_dataset(seed, personalities=generators.CSV_SAFE)
    root = make_root(dataset, ingest="csv")

    assert_flags_match(root, reference.detect(root))


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_flags_match_the_answer_key_for_values_stored_as_they_are(make_root, seed):
    # Every personality, the empty string, "null" and the lookalikes among them
    dataset = generators.make_dataset(seed)
    root = make_root(dataset, ingest="direct")

    assert_flags_match(root, reference.detect(root))


@pytest.mark.sql
@pytest.mark.parametrize("personality", sorted(generators.PERSONALITIES))
@pytest.mark.parametrize("row_count", [1, 2, 9, 10, 11, 300])
def test_each_personality_alone_at_the_thresholds(make_root, personality, row_count):
    """One column of each personality, at the row counts either side of the detectors' thresholds."""
    dataset = generators.make_dataset(row_count * 1000 + len(personality), personalities=[personality],
                                      row_count=row_count, column_count=1)
    root = make_root(dataset, ingest="direct")

    assert_flags_match(root, reference.detect(root))


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_metrics_count_exactly_the_flags(make_root, seed):
    dataset = generators.make_dataset(seed)
    root = make_root(dataset, ingest="direct")
    expected = reference.detect(root)
    if expected.borderline:
        pytest.skip("a borderline anomaly makes the exact rates undecidable")
    expected_metrics = reference.metrics(root, expected)

    node = app.pgraph_for_session.node_map[root.name]
    actual = node.metrics.__json__()

    assert actual["row_count"] == expected_metrics["row_count"]
    assert actual["column_count"] == expected_metrics["column_count"]
    rows = expected_metrics["row_count"]
    cells = rows * expected_metrics["column_count"]

    for column, counts in expected_metrics["columns"].items():
        column_total = 0
        for error_type, count in counts.items():
            column_total += count
            expected_rate = count / rows if rows else 0.0
            assert actual["columns"][column].get(error_type, 0.0) == pytest.approx(expected_rate), (column, error_type)
        expected_total = column_total / rows if rows else 0.0
        assert actual["columns"][column]["total"] == pytest.approx(expected_total), column

    for error_type, count in expected_metrics["totals"].items():
        expected_rate = count / cells if cells else 0.0
        assert actual["totals"][error_type] == pytest.approx(expected_rate), error_type
