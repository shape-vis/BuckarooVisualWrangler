"""
The flagged-IDs-only invariant, per operation.

    An AI-suggested operation acts only on rows that errors_<table> flags for the column(s)
    that operation touches.

The case that matters most is the 2D impute. create_previews_2d writes cols[0] for every id it
is handed, and impute_by_ids has no predicate of its own, so handing it the *union* of two
columns' flagged rows would overwrite a good value in every row whose only flag was in the other
column. Scoping the id set to the imputed column is what prevents that, and these tests pin it.
"""
import pytest
import pandas as pd
from sqlalchemy import text as sa_text

from app import engine
from app.server_utils import ai_wrangle as aw
from app.server_utils.ai_wrangle import SuggestionError

COLUMNS = ["a", "b"]


def _drop(conn, *names):
    for name in names:
        conn.execute(sa_text(f'DROP TABLE IF EXISTS "{name}"'))


def _seed(table, data, errors):
    pd.DataFrame(data).to_sql(table, engine, if_exists="replace", index=False)
    frame = pd.DataFrame(errors, columns=["row_id", "column_id", "error_type"])
    # create_error_df yields an int64 row_id even when it finds nothing, so the real errors_
    # table is always bigint. An empty DataFrame built by hand would be all-object and land as
    # text, which nothing in the app ever produces - and the join would fail on the type rather
    # than on anything this test is about.
    frame = frame.astype({"row_id": "int64"})
    frame.to_sql(f"errors_{table}", engine, if_exists="replace", index=False)


def _ids(table, raw):
    """validate + resolve, without the guards."""
    suggestion = aw.validate_suggestion(table, raw, COLUMNS)
    return aw.resolve_ids_for(table, suggestion)


# Row 2 is flagged in a only, row 3 in b only, row 4 in both. Rows 1 and 5 are clean.
LAYOUT = {
    "ID": [1, 2, 3, 4, 5],
    "a": [1.0, None, 3.0, None, 5.0],
    "b": [10.0, 20.0, None, None, 50.0],
}
FLAGS = [
    (2, "a", "missing"),
    (3, "b", "missing"),
    (4, "a", "missing"),
    (4, "b", "missing"),
]


@pytest.mark.sql
def test_ids_are_scoped_per_operation(db_transaction):
    table = "t_ai_resolve"
    _seed(table, LAYOUT, FLAGS)

    try:
        assert _ids(table, {"op": "impute_rows", "column": "a", "error_type": "missing"}) == [2, 4]
        assert _ids(table, {"op": "delete_rows", "column": "b", "error_type": "missing"}) == [3, 4]

        # The invariant. Row 3 is clean in `a`, so a target="x" impute must not touch it;
        # row 2 is clean in `b`, so a target="y" impute must not touch it.
        x = _ids(table, {"op": "impute_rows_2d", "columns": ["a", "b"],
                         "target": "x", "error_type": "missing"})
        y = _ids(table, {"op": "impute_rows_2d", "columns": ["a", "b"],
                         "target": "y", "error_type": "missing"})
        assert x == [2, 4], f"target=x must be a's flagged rows only, got {x}"
        assert 3 not in x, "row 3 is clean in `a` - imputing it would destroy a good value"
        assert y == [3, 4], f"target=y must be b's flagged rows only, got {y}"
        assert 2 not in y, "row 2 is clean in `b` - imputing it would destroy a good value"

        # Deleting a row is well defined however it was flagged, so 2D delete takes the union.
        both = _ids(table, {"op": "delete_rows_2d", "columns": ["a", "b"],
                            "error_type": "missing"})
        assert both == [2, 3, 4]
    finally:
        with engine.begin() as conn:
            _drop(conn, table, f"errors_{table}")


@pytest.mark.sql
def test_error_type_partitions_the_rows(db_transaction):
    """A suggestion names one flag; rows carrying only some other flag are not its business."""
    table = "t_ai_resolve_etype"
    _seed(table, LAYOUT, [(2, "a", "missing"), (4, "a", "anomaly")])

    try:
        assert _ids(table, {"op": "impute_rows", "column": "a", "error_type": "missing"}) == [2]
        assert _ids(table, {"op": "impute_rows", "column": "a", "error_type": "anomaly"}) == [4]
        assert _ids(table, {"op": "impute_rows", "column": "a", "error_type": "mismatch"}) == []
    finally:
        with engine.begin() as conn:
            _drop(conn, table, f"errors_{table}")


@pytest.mark.sql
def test_error_rows_naming_dead_ids_are_dropped(db_transaction):
    """The join is what keeps a stale errors table from resurrecting deleted rows."""
    table = "t_ai_resolve_orphan"
    _seed(table, LAYOUT, FLAGS + [(99, "a", "missing"), (404, "a", "missing")])

    try:
        ids = _ids(table, {"op": "impute_rows", "column": "a", "error_type": "missing"})
        assert ids == [2, 4], f"ids 99/404 name no live row and must not survive, got {ids}"
    finally:
        with engine.begin() as conn:
            _drop(conn, table, f"errors_{table}")


@pytest.mark.sql
def test_gapped_ids_resolve_by_id_not_position(db_transaction):
    table = "t_ai_resolve_gapped"
    _seed(
        table,
        {"ID": [10, 20, 30, 40], "a": [1.0, None, 3.0, None], "b": [1.0, 2.0, 3.0, 4.0]},
        [(20, "a", "missing"), (40, "a", "missing")],
    )

    try:
        assert _ids(table, {"op": "impute_rows", "column": "a", "error_type": "missing"}) == [20, 40]
    finally:
        with engine.begin() as conn:
            _drop(conn, table, f"errors_{table}")


# ─── validation ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ({"op": "drop_table", "column": "a", "error_type": "missing"}, "unknown operation"),
    ({"op": "impute_rows", "column": "a", "error_type": "spicy"}, "unknown error type"),
    ({"op": "impute_rows", "column": "nope", "error_type": "missing"}, "no such column"),
    ({"op": "delete_rows_2d", "columns": ["a"], "error_type": "missing"}, "needs 2 column"),
    ({"op": "delete_rows_2d", "columns": ["a", "a"], "error_type": "missing"}, "distinct columns"),
    ({"op": "impute_rows_2d", "columns": ["a", "b"], "error_type": "missing"}, "target"),
    ({"op": "impute_rows_2d", "columns": ["a", "b"], "target": "z",
      "error_type": "missing"}, "target"),
])
def test_validation_rejects(raw, expected):
    """No table needed - validation is pure, and it runs again on whatever /accept is posted."""
    with pytest.raises(SuggestionError, match=expected):
        aw.validate_suggestion("t_any", raw, COLUMNS)


# ─── guards ──────────────────────────────────────────────────────────────────

@pytest.mark.sql
def test_guard_rejects_an_empty_id_set(db_transaction):
    table = "t_ai_guard_empty"
    _seed(table, LAYOUT, [])

    try:
        with pytest.raises(SuggestionError, match="no rows in a carry a missing flag"):
            aw.prepare(table, {"op": "impute_rows", "column": "a",
                               "error_type": "missing"}, COLUMNS)
    finally:
        with engine.begin() as conn:
            _drop(conn, table, f"errors_{table}")


@pytest.mark.sql
def test_guard_refuses_a_delete_that_takes_too_much(db_transaction):
    """3 of 5 rows is 60%, well past the ceiling."""
    table = "t_ai_guard_share"
    _seed(table, LAYOUT, [(1, "a", "missing"), (2, "a", "missing"), (3, "a", "missing")])

    try:
        with pytest.raises(SuggestionError, match="60%"):
            aw.prepare(table, {"op": "delete_rows", "column": "a",
                               "error_type": "missing"}, COLUMNS)
    finally:
        with engine.begin() as conn:
            _drop(conn, table, f"errors_{table}")


@pytest.mark.sql
def test_guard_refuses_to_empty_the_table(db_transaction):
    table = "t_ai_guard_all"
    _seed(table, LAYOUT, [(i, "a", "missing") for i in range(1, 6)])

    try:
        with pytest.raises(SuggestionError, match="leave an empty table"):
            aw.prepare(table, {"op": "delete_rows", "column": "a",
                               "error_type": "missing"}, COLUMNS)
    finally:
        with engine.begin() as conn:
            _drop(conn, table, f"errors_{table}")


@pytest.mark.sql
def test_guard_refuses_an_impute_with_nothing_to_learn_from(db_transaction):
    """Every value flagged and blank means the mean has no clean value to come from."""
    table = "t_ai_guard_nofill"
    _seed(
        table,
        {"ID": [1, 2, 3], "a": [None, None, None], "b": [1.0, 2.0, 3.0]},
        [(1, "a", "missing"), (2, "a", "missing"), (3, "a", "missing")],
    )

    try:
        with pytest.raises(SuggestionError, match="constant|no clean values"):
            aw.prepare(table, {"op": "impute_rows", "column": "a",
                               "error_type": "missing"}, COLUMNS)
    finally:
        with engine.begin() as conn:
            _drop(conn, table, f"errors_{table}")


@pytest.mark.sql
def test_a_good_suggestion_survives_prepare(db_transaction):
    table = "t_ai_guard_ok"
    _seed(table, LAYOUT, FLAGS)

    try:
        s = aw.prepare(table, {"op": "impute_rows", "column": "a",
                               "error_type": "missing"}, COLUMNS)
        assert s.row_ids == [2, 4]
        assert s.to_json()["row_count"] == 2
        assert s.to_json()["label"] == "impute · a"
    finally:
        with engine.begin() as conn:
            _drop(conn, table, f"errors_{table}")
