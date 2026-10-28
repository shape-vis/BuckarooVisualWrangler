"""
Two nodes' tables binned on shared axes, inside Postgres, by CompareSQL (app/db_utils/compare_sql.py).

These are the pandas comparison's unit cases - tests/unit/test_node_compare.py, deleted along with app/pgraph/compare.py
- held against the SQL one. Each side is stored as a table with its own errors_ table, as a node's is.
"""
import pandas as pd
import pytest
from sqlalchemy import text as sa_text

from app import engine
from app.db_utils.column_types import ColumnTypes
from app.db_utils.compare_sql import MAX_LABELS, NULL_LABEL, OTHER_LABEL, CompareSQL

TABLE_A = "t_compare_sql_a"
TABLE_B = "t_compare_sql_b"


def _store(table, rows, errors):
    """One side: its rows, and its error flags as (row_id, column_id, error_type) triples."""
    pd.DataFrame(rows).to_sql(table, engine, if_exists="replace", index=False)
    flags = pd.DataFrame(list(errors), columns=["row_id", "column_id", "error_type"]).astype({"row_id": "int64"})
    flags.to_sql(f"errors_{table}", engine, if_exists="replace", index=False)
    ColumnTypes.forget(table)


@pytest.fixture
def compare():
    """
    Store both sides and compare them.
    :return: a function of (rows_a, rows_b, errors_a, errors_b) giving a CompareSQL over the two
    """
    def build(rows_a, rows_b, errors_a=(), errors_b=()):
        _store(TABLE_A, rows_a, errors_a)
        _store(TABLE_B, rows_b, errors_b)
        return CompareSQL(engine, TABLE_A, TABLE_B)

    yield build

    with engine.begin() as conn:
        for table in (TABLE_A, TABLE_B):
            conn.execute(sa_text(f'DROP TABLE IF EXISTS "{table}"'))
            conn.execute(sa_text(f'DROP TABLE IF EXISTS "errors_{table}"'))
            ColumnTypes.forget(table)


def _bins_by_key(histogram):
    keyed = {}
    for entry in histogram["bins"]:
        keyed[(entry["xType"], entry["xBin"])] = entry
    return keyed


# ── The shared axis ──────────────────────────────────────────────────────────

@pytest.mark.sql
def test_numeric_range_spans_both_states(compare):
    # Selection B lost its outlier, but its bins still have to line up with selection A's
    histogram = compare({"ID": [1, 2, 3], "c": [0, 5, 100]}, {"ID": [1, 2], "c": [0, 5]}).generate_compare_histogram("c", 10)

    numeric = histogram["scaleX"]["numeric"]
    assert (numeric[0]["x0"], numeric[-1]["x1"]) == (0.0, 100.0)


@pytest.mark.sql
def test_nulls_and_text_in_a_numeric_column_become_labels(compare):
    histogram = compare({"ID": [1, 2, 3, 4], "c": ["1", "2", None, "oops"]},
                        {"ID": [1, 2], "c": ["3", "4"]}).generate_compare_histogram("c", 4)

    assert len(histogram["scaleX"]["numeric"]) == 4
    assert histogram["scaleX"]["categorical"] == [NULL_LABEL, "oops"]


@pytest.mark.sql
def test_mostly_text_column_is_categorical(compare):
    histogram = compare({"ID": [1, 2, 3], "c": ["a", "b", "7"]},
                        {"ID": [1], "c": ["a"]}).generate_compare_histogram("c", 4)

    assert histogram["scaleX"]["numeric"] == []
    assert histogram["scaleX"]["categorical"] == ["7", "a", "b"]


@pytest.mark.sql
def test_long_tail_folds_into_other_but_null_survives(compare):
    # Null is the rarest label here, and would be the first to fold away if it were not kept
    values = [f"v{i:02d}" for i in range(30)] * 2 + [None]
    histogram = compare({"ID": list(range(1, len(values) + 1)), "c": values},
                        {"ID": [1], "c": ["v00"]}).generate_compare_histogram("c", 10)

    labels = histogram["scaleX"]["categorical"]
    assert len(labels) == MAX_LABELS
    assert NULL_LABEL in labels
    assert labels[-1] == OTHER_LABEL


@pytest.mark.sql
def test_constant_column_gets_one_bin_with_width(compare):
    histogram = compare({"ID": [1, 2], "c": [7, 7]}, {"ID": [1], "c": [7]}).generate_compare_histogram("c", 10)

    numeric = histogram["scaleX"]["numeric"]
    assert len(numeric) == 1
    assert numeric[0]["x0"] < numeric[0]["x1"]


@pytest.mark.sql
def test_maximum_lands_in_the_last_bin(compare):
    histogram = compare({"ID": [1, 2, 3], "c": [0, 4.9, 10]}, {"ID": [1], "c": [0.0]}).generate_compare_histogram("c", 5)

    counts = {}
    for entry in histogram["bins"]:
        counts[entry["xBin"]] = entry["a"]["items"]
    assert counts == {0: 1, 1: 0, 2: 1, 3: 0, 4: 1}


# ── Histograms ───────────────────────────────────────────────────────────────

@pytest.mark.sql
def test_every_bin_lists_both_sides(compare):
    histogram = compare({"ID": [1, 2, 3, 4], "age": [0, 0, 10, 10]}, {"ID": [1, 2], "age": [0, 0]},
                        errors_a=[(1, "age", "missing"), (3, "age", "anomaly")]).generate_compare_histogram("age", 2)

    bins = histogram["bins"]
    assert [(entry["xType"], entry["xBin"]) for entry in bins] == [("numeric", 0), ("numeric", 1)]
    assert bins[0]["a"] == {"items": 2, "missing": 1}
    assert bins[0]["b"] == {"items": 2}
    # Selection B has nothing in the top bin, but the bin is still there to measure against
    assert bins[1]["a"] == {"items": 2, "anomaly": 1}
    assert bins[1]["b"] == {"items": 0}
    assert histogram["rows"] == {"a": 4, "b": 2}


@pytest.mark.sql
def test_flags_on_other_columns_are_not_counted(compare):
    histogram = compare({"ID": [1], "age": [3]}, {"ID": [1], "age": [3]},
                        errors_a=[(1, "city", "missing")]).generate_compare_histogram("age", 1)

    assert histogram["bins"][0]["a"] == {"items": 1}


@pytest.mark.sql
def test_imputed_nulls_move_from_the_null_label_into_a_bin(compare):
    histogram = compare({"ID": [1, 2], "age": [None, 4]}, {"ID": [1, 2], "age": [4.0, 4.0]}).generate_compare_histogram("age", 1)

    bins = _bins_by_key(histogram)
    assert bins[("categorical", NULL_LABEL)]["a"]["items"] == 1
    assert bins[("categorical", NULL_LABEL)]["b"]["items"] == 0
    assert bins[("numeric", 0)]["b"]["items"] == 2


# ── Heatmaps ─────────────────────────────────────────────────────────────────

@pytest.mark.sql
def test_only_occupied_tiles_are_listed(compare):
    node = {"ID": [1, 2], "x": [0, 10], "y": [0, 10]}
    heatmap = compare(node, node).generate_compare_heatmap("x", "y", 2)

    assert [(tile["xBin"], tile["yBin"]) for tile in heatmap["tiles"]] == [(0, 0), (1, 1)]


@pytest.mark.sql
def test_row_flagged_on_both_columns_counts_once(compare):
    node = {"ID": [1], "x": [1], "y": [1]}
    flags = [(1, "x", "missing"), (1, "y", "missing")]
    heatmap = compare(node, node, errors_a=flags, errors_b=flags).generate_compare_heatmap("x", "y", 1)

    assert heatmap["tiles"][0]["a"] == {"items": 1, "missing": 1}


@pytest.mark.sql
def test_same_column_on_both_axes(compare):
    node = {"ID": [1, 2], "x": [0, 10]}
    heatmap = compare(node, node).generate_compare_heatmap("x", "x", 2)

    assert [(tile["xBin"], tile["yBin"]) for tile in heatmap["tiles"]] == [(0, 0), (1, 1)]


@pytest.mark.sql
def test_a_column_either_table_lacks_is_refused(compare):
    with pytest.raises(ValueError, match="has no column"):
        compare({"ID": [1], "x": [1]}, {"ID": [1], "y": [1]}).generate_compare_histogram("x", 2)
