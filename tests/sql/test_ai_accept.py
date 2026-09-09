"""
Accepting a suggestion: the full path from a validated tool call to a cemented PGraph node.

Two things here are regressions waiting to happen and are pinned deliberately:

  - Branching off a node that is not the current one. add_node sets prev to whatever was current,
    which only means "parent" because every wrangle until now branched off the current node. This
    feature is the first that does not, so apply_suggestion repairs the cursor afterwards.

  - The 2D impute. If the id set were the union of both columns' flagged rows, imputing x would
    overwrite a good value in every row whose only flag was in y.
"""
import pytest
import pandas as pd
from sqlalchemy import text as sa_text

import app
from app import engine, db_operations
from app.routes.wrangler_routes_sql import update_errors_table
from app.server_utils import ai_wrangle as aw
from app.server_utils.service_helpers import (
    build_data_profile_table,
    init_pgraph_for_session,
)

ROOT = "n0a_aiacc"
COLUMNS = ["a", "b"]


def _drop_all(*tables):
    with engine.begin() as conn:
        for t in tables:
            for name in (t, f"errors_{t}", f"dp_{t}", f"rankings_{t}", f"{t}_filtering"):
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "{name}"'))
            for suffix in ("_preview_delete", "_preview_impute",
                           "_preview_impute_x", "_preview_impute_y"):
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "{t}{suffix}"'))
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "errors_{t}{suffix}"'))
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "dp_{t}{suffix}"'))


def _make_root(data, flags=None):
    """Build a real root node: table, errors_, dp_, and a PGraph holding it."""
    pd.DataFrame(data).to_sql(ROOT, engine, if_exists="replace", index=False)
    update_errors_table(ROOT)
    if flags is not None:
        # Take control of exactly which flags exist, so a test asserts about its own layout
        # rather than about whatever the detectors happened to find.
        pd.DataFrame(flags, columns=["row_id", "column_id", "error_type"]).astype(
            {"row_id": "int64"}
        ).to_sql(f"errors_{ROOT}", engine, if_exists="replace", index=False)
    build_data_profile_table(ROOT)
    init_pgraph_for_session(ROOT)
    db_operations.load_table(ROOT, f"errors_{ROOT}", f"dp_{ROOT}")


def _read(table):
    return pd.read_sql_query(f'SELECT * FROM "{table}" ORDER BY "ID"', engine)


@pytest.fixture
def clean_graph():
    """Every test here mutates the process-wide session graph, so reset it around each one."""
    created = [ROOT]
    yield created
    app.pgraph_for_session = None
    _drop_all(*created)


@pytest.mark.sql
def test_accept_creates_a_node_and_runs_the_wrangle(clean_graph):
    _make_root(
        {"ID": [1, 2, 3, 4, 5], "a": [10.0, 20.0, None, 60.0, 30.0],
         "b": [1.0, 2.0, 3.0, 4.0, 5.0]},
        flags=[(3, "a", "missing")],
    )

    result = aw.apply_suggestion(
        ROOT, {"op": "impute_rows", "column": "a", "error_type": "missing"}, COLUMNS
    )
    new_table = result["table"]
    clean_graph.append(new_table)

    assert result["success"] is True
    assert result["row_count"] == 1
    assert result["label"] == "impute · a"

    # The node exists in the graph, hangs off the parent, and records the operation
    node = app.pgraph_for_session.node_map[new_table]
    assert node.parent_table == ROOT
    assert node.wrangle_op == "impute"
    assert node.wrangle_cols == ["a"]
    assert new_table in app.pgraph_for_session.node_map[ROOT].children

    # The wrangle really ran: the blank is filled with the mean of the clean values
    after = _read(new_table)
    assert after.loc[after["ID"] == 3, "a"].iloc[0] == pytest.approx(30.0)
    assert len(after) == 5, "an impute must not change the row count"

    # ...and the parent is untouched, which is what keeps the other suggestions valid
    parent = _read(ROOT)
    assert pd.isna(parent.loc[parent["ID"] == 3, "a"].iloc[0])

    # The session now points at the new node, with its companion tables built
    assert db_operations.main_table_name == new_table
    assert db_operations.table_exists(f"errors_{new_table}")
    assert db_operations.table_exists(f"dp_{new_table}")


@pytest.mark.sql
def test_delete_removes_only_the_flagged_rows(clean_graph):
    _make_root(
        {"ID": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
         "a": [1.0, None, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
         "b": [1.0] * 10},
        flags=[(2, "a", "missing")],
    )

    result = aw.apply_suggestion(
        ROOT, {"op": "delete_rows", "column": "a", "error_type": "missing"}, COLUMNS
    )
    clean_graph.append(result["table"])

    after = _read(result["table"])
    assert sorted(after["ID"]) == [1, 3, 4, 5, 6, 7, 8, 9, 10]
    assert app.pgraph_for_session.node_map[result["table"]].wrangle_op == "delete"


@pytest.mark.sql
def test_2d_impute_leaves_the_other_column_s_rows_alone(clean_graph):
    """
    The corruption regression.

    Row 4 is clean in `a` and flagged in `b`. A target="x" impute writes `a`, so row 4 must not
    be in its id set. The fill value (30.0) differs from row 4's own value (60.0), so an
    overwrite would be plainly visible - picking values that way is the whole point.
    """
    _make_root(
        {"ID": [1, 2, 3, 4, 5], "a": [10.0, 20.0, None, 60.0, 30.0],
         "b": [1.0, 2.0, 3.0, None, 5.0]},
        flags=[(3, "a", "missing"), (4, "b", "missing")],
    )

    before = _read(ROOT)
    assert before.loc[before["ID"] == 4, "a"].iloc[0] == 60.0

    result = aw.apply_suggestion(
        ROOT,
        {"op": "impute_rows_2d", "columns": ["a", "b"], "target": "x",
         "error_type": "missing"},
        COLUMNS,
    )
    clean_graph.append(result["table"])

    assert result["row_count"] == 1, "only row 3 is flagged in `a`"

    after = _read(result["table"])
    assert after.loc[after["ID"] == 4, "a"].iloc[0] == 60.0, (
        "row 4 was clean in `a` - a 2D impute must not overwrite it"
    )
    assert after.loc[after["ID"] == 3, "a"].iloc[0] == pytest.approx(30.0)
    # b was never the target, so it is untouched throughout
    assert pd.isna(after.loc[after["ID"] == 4, "b"].iloc[0])

    node = app.pgraph_for_session.node_map[result["table"]]
    assert node.wrangle_op == "impute_x"
    assert node.wrangle_cols == ["a", "b"], "provenance records the pair"


@pytest.mark.sql
def test_second_accept_branches_off_the_same_parent(clean_graph):
    """
    Accept, then accept again off the *original* node - the sibling case, and the one that
    exposes the undo cursor.
    """
    _make_root(
        {"ID": [1, 2, 3, 4, 5], "a": [10.0, 20.0, None, 60.0, 30.0],
         "b": [1.0, 2.0, 3.0, None, 5.0]},
        flags=[(3, "a", "missing"), (4, "b", "missing")],
    )
    parent_rows_before = len(_read(ROOT))

    first = aw.apply_suggestion(
        ROOT, {"op": "impute_rows", "column": "a", "error_type": "missing"}, COLUMNS
    )
    clean_graph.append(first["table"])
    assert db_operations.main_table_name == first["table"]

    # ROOT is no longer the current node. Accepting off it must still work, and must leave the
    # cursors describing the tree rather than the order things happened in.
    second = aw.apply_suggestion(
        ROOT, {"op": "impute_rows", "column": "b", "error_type": "missing"}, COLUMNS
    )
    clean_graph.append(second["table"])

    graph = app.pgraph_for_session
    assert second["table"] != first["table"]
    assert graph.node_map[second["table"]].parent_table == ROOT
    assert set(graph.node_map[ROOT].children) == {first["table"], second["table"]}

    # prev must be the parent, not "whatever was current a moment ago" (which was first["table"],
    # a sibling - undo would have walked sideways across the tree).
    assert graph.current_node_table_name == second["table"]
    assert graph.prev_node_table_name == ROOT, (
        f"prev should be the parent {ROOT}, got {graph.prev_node_table_name}"
    )

    # The parent is untouched by either accept, so the second suggestion's ids were still valid
    assert len(_read(ROOT)) == parent_rows_before
    assert pd.isna(_read(ROOT).set_index("ID").loc[3, "a"])

    # Both siblings are real, and each did its own repair
    assert _read(first["table"]).set_index("ID").loc[3, "a"] == pytest.approx(30.0)
    assert _read(second["table"]).set_index("ID").loc[4, "b"] == pytest.approx(2.75)


@pytest.mark.sql
def test_accept_refuses_a_table_that_is_not_a_node(clean_graph):
    _make_root({"ID": [1, 2], "a": [1.0, None], "b": [1.0, 2.0]}, flags=[(2, "a", "missing")])

    with pytest.raises(aw.SuggestionError, match="not a node"):
        aw.apply_suggestion(
            "some_other_table",
            {"op": "impute_rows", "column": "a", "error_type": "missing"},
            COLUMNS,
        )


@pytest.mark.sql
def test_a_guarded_suggestion_never_touches_the_table(clean_graph):
    """A refusal must leave the graph and the data exactly as they were."""
    _make_root(
        {"ID": [1, 2, 3], "a": [1.0, None, 3.0], "b": [1.0, 2.0, 3.0]},
        flags=[(1, "a", "missing"), (2, "a", "missing"), (3, "a", "missing")],
    )
    nodes_before = dict(app.pgraph_for_session.node_map)
    count_before = app.pgraph_for_session.node_count

    with pytest.raises(aw.SuggestionError):
        aw.apply_suggestion(
            ROOT, {"op": "delete_rows", "column": "a", "error_type": "missing"}, COLUMNS
        )

    assert app.pgraph_for_session.node_map.keys() == nodes_before.keys()
    assert app.pgraph_for_session.node_count == count_before
    assert len(_read(ROOT)) == 3
