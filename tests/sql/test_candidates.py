"""
Candidates: wrangles staged as provisional pgraph nodes before they are accepted - see
app/server_utils/candidates.py.

A candidate is a full node of the graph - a child of its parent, with its edge, scored for the Pareto front,
reachable by undo and redo, navigable - with its own table, errors, profile, metrics and drift. The
one thing it cannot be is wrangled from. Accepting it renames nothing: it keeps its table and only gets its
label. These run against a real graph, through the same routes the app calls.

Replaces the old preview tests: the rows a repair removes or fills are checked here, on the candidates that
now hold them.
"""
import pytest
import pandas as pd
from sqlalchemy import text as sa_text

import app
from app import engine, db_operations
from app.db_utils.execute_sql import node_table_names
from app import app as flask_app

ROOT = "n0a_cands"


def _read(table):
    return pd.read_sql_query(f'SELECT * FROM "{table}" ORDER BY "ID"', engine)


NUMERIC = {"ID": list(range(1, 11)),
           "x": [10.0, None, 30.0, 40.0, None, 60.0, 70.0, 80.0, 90.0, 100.0],
           "y": [1.0, 2.0, None, 4.0, 5.0, 6.0, None, 8.0, 9.0, 10.0]}


@pytest.fixture
def root(make_root):
    """:return: a function building the root from its data, flagged by the detectors"""
    def build(data):
        make_root(ROOT, data)
    return build


def _stage(client, row_ids, cols, source=None):
    body = {"row_ids": row_ids, "cols": cols}
    if source:
        body["source"] = source
    resp = client.post("/api/wrangle/create-previews", json=body)
    assert resp.status_code == 200, resp.get_json()
    return {c["op"]: c for c in resp.get_json()["candidates"]}


def _graph():
    return app.pgraph_for_session


# ─── Staging ─────────────────────────────────────────────────────────────────

@pytest.mark.sql
def test_a_1d_selection_stages_a_delete_and_an_impute(root, client):
    root(NUMERIC)
    staged = _stage(client, [2, 5], ["x"])

    assert set(staged) == {"delete", "impute"}
    for candidate in staged.values():
        table = candidate["table"]
        assert table.startswith("c") and table.endswith("_cands")
        assert candidate["source"] == "repair" and candidate["chart_type"] == "histogram"
        assert candidate["row_count"] == 2

        node = _graph().node_map[table]
        assert node.provisional and node.parent_table == ROOT
        assert table in _graph().node_map[ROOT].children
        assert node.metrics is not None and node.distortion is not None
        # Everything an accepted node has, so it can be navigated to
        for companion in node_table_names(table):
            assert db_operations.table_exists(companion), companion

    # Staging takes no label and does not move the session
    assert _graph().node_count == 1
    assert _graph().current_node_table_name == ROOT
    assert db_operations.main_table_name == ROOT

    deleted = _read(staged["delete"]["table"])
    assert len(deleted) == 8 and not {2, 5} & set(deleted["ID"])
    imputed = _read(staged["impute"]["table"])
    assert imputed["x"].notna().all()
    # The parent is never touched
    assert _read(ROOT)["x"].isna().sum() == 2


@pytest.mark.sql
def test_a_2d_impute_fills_only_its_own_column(root, client):
    root(NUMERIC)
    staged = _stage(client, [2, 3, 5, 7], ["x", "y"], source="scatterplot")

    assert set(staged) == {"delete", "impute_x", "impute_y"}
    assert staged["impute_x"]["chart_type"] == "scatterplot"
    x_filled = _read(staged["impute_x"]["table"])
    assert x_filled["x"].notna().all() and x_filled["y"].isna().sum() == 2
    y_filled = _read(staged["impute_y"]["table"])
    assert y_filled["y"].notna().all() and y_filled["x"].isna().sum() == 2


@pytest.mark.sql
def test_a_categorical_impute_fills_with_the_most_common_value(root, client):
    root({"ID": [1, 2, 3, 4, 5], "c": ["a", "a", None, "b", None]})
    imputed = _read(_stage(client, [3, 5], ["c"])["impute"]["table"])
    assert list(imputed["c"]) == ["a", "a", "a", "b", "a"]


@pytest.mark.sql
def test_its_edge_is_marked_provisional(root, client):
    root(NUMERIC)
    table = _stage(client, [2], ["x"])["delete"]["table"]

    edge = next(e for e in _graph().serialize_edges() if e["target"] == table)
    assert edge["data"]["provisional"] is True
    node = next(n for n in _graph().serialize_nodes() if n["id"] == table)
    assert node["data"]["provisional"] is True
    assert node["data"]["label"] == table.split("_")[0]


@pytest.mark.sql
def test_the_compare_endpoints_take_a_candidate(root, client):
    root(NUMERIC)
    table = _stage(client, [2, 5], ["x"])["impute"]["table"]

    compare = client.get("/api/pgraph/compare", query_string={"a": ROOT, "b": table, "kind": "histogram", "x": "x"})
    assert compare.status_code == 200, compare.get_json()
    drift = client.get("/api/pgraph/drift_detail", query_string={"node": table, "column": "x"})
    assert drift.status_code == 200, drift.get_json()


# ─── Accepting and declining ─────────────────────────────────────────────────

@pytest.mark.sql
def test_accepting_publishes_it_and_leaves_its_siblings(root, client):
    root(NUMERIC)
    staged = _stage(client, [2, 5], ["x"])
    table = staged["impute"]["table"]

    body = client.post("/api/candidates/accept", json={"table": table}).get_json()

    assert body == {"success": True, "table": table, "label": "n0b", "parent": ROOT}
    node = _graph().node_map[table]
    assert not node.provisional and node.label == "n0b"
    assert _graph().node_count == 2
    assert _graph().current_node_table_name == table
    assert db_operations.main_table_name == table
    # The sibling is still staged under the same parent
    assert _graph().node_map[staged["delete"]["table"]].provisional


@pytest.mark.sql
def test_declining_drops_it_and_its_name_is_never_reused(root, client):
    root(NUMERIC)
    first = _stage(client, [2], ["x"])
    table = first["delete"]["table"]

    body = client.post("/api/candidates/discard", json={"tables": [table]}).get_json()

    assert body["success"] is True
    assert table not in _graph().node_map
    assert table not in _graph().node_map[ROOT].children
    assert not db_operations.table_exists(table) and not db_operations.table_exists(f"errors_{table}")

    later = _stage(client, [2], ["x"])
    assert table not in {c["table"] for c in later.values()}


@pytest.mark.sql
def test_declining_the_current_node_moves_the_session_to_its_parent(root, client):
    root(NUMERIC)
    table = _stage(client, [2], ["x"])["delete"]["table"]
    client.post("/api/setGraphToClickedNode", json={"nodeId": table})
    assert db_operations.main_table_name == table

    body = client.post("/api/candidates/discard", json={"tables": [table]}).get_json()

    assert body["current"] == ROOT
    assert _graph().current_node_table_name == ROOT
    assert db_operations.main_table_name == ROOT


@pytest.mark.sql
def test_reset_drops_every_candidate(root, client):
    root(NUMERIC)
    tables = [c["table"] for c in _stage(client, [2], ["x"]).values()]

    client.post("/api/reset")

    for table in tables:
        assert not db_operations.table_exists(table)


# ─── A node like any other ───────────────────────────────────────────────────

@pytest.mark.sql
def test_pareto_scores_it_as_a_leaf_and_its_parent_stops_being_one(root, client):
    root(NUMERIC)
    tables = {c["table"] for c in _stage(client, [2], ["x"]).values()}

    scored = set(_graph().pareto()["scored"])
    assert tables <= scored
    assert ROOT not in scored


@pytest.mark.sql
def test_navigating_to_it_and_back(root, client):
    root(NUMERIC)
    table = _stage(client, [2], ["x"])["impute"]["table"]

    resp = client.post("/api/setGraphToClickedNode", json={"nodeId": table})
    assert resp.status_code == 200, resp.get_json()
    assert _graph().current_node_table_name == table
    assert _graph().prev_node_table_name == ROOT
    assert _graph().next_node_table_name is None
    assert db_operations.main_table_name == table

    undo = client.post("/api/undo").get_json()
    assert undo["success"] is True and db_operations.main_table_name == ROOT

    # Redo from the parent steps into its last child, candidate or not
    redo = client.post("/api/redo").get_json()
    assert redo["success"] is True and db_operations.main_table_name == table


@pytest.mark.sql
def test_nothing_is_wrangled_from_a_candidate_until_it_is_accepted(root, client):
    root(NUMERIC)
    table = _stage(client, [2, 5], ["x"])["impute"]["table"]
    client.post("/api/setGraphToClickedNode", json={"nodeId": table})

    refused = client.post("/api/wrangle/create-previews", json={"row_ids": [1], "cols": ["x"]})
    assert refused.status_code == 409
    assert "Accept this candidate" in refused.get_json()["error"]
    assert client.post("/api/ai/suggest", json={"node_table": table}).status_code == 409

    client.post("/api/candidates/accept", json={"table": table})
    assert client.post("/api/wrangle/create-previews", json={"row_ids": [1], "cols": ["x"]}).status_code == 200


# ─── Staging several at once ─────────────────────────────────────────────────
# A request's candidates are built at the same time, each on its own node-build thread, and join the graph together.

def _candidate_tables():
    """Every candidate table in the database for this root, whether or not it made it into the graph."""
    with engine.connect() as conn:
        rows = conn.execute(sa_text(
            "SELECT table_name FROM information_schema.tables WHERE table_name ~ '^c[0-9]+_cands$'"))
        return {row[0] for row in rows}


@pytest.mark.sql
def test_a_2d_selection_stages_three_at_once_named_in_order(root, client):
    root(NUMERIC)

    resp = client.post("/api/wrangle/create-previews", json={"row_ids": [2, 3, 5], "cols": ["x", "y"]})
    assert resp.status_code == 200, resp.get_json()
    staged = resp.get_json()["candidates"]

    # Named in the order the repairs were asked for, whichever finished building first
    assert [candidate["op"] for candidate in staged] == ["delete", "impute_x", "impute_y"]
    assert [candidate["table"] for candidate in staged] == ["c0_cands", "c1_cands", "c2_cands"]
    for candidate in staged:
        node = _graph().node_map[candidate["table"]]
        assert node.provisional and node.metrics is not None and node.distortion is not None


@pytest.mark.sql
def test_if_one_build_fails_none_of_its_set_is_staged(root):
    from app.server_utils import candidates
    root(NUMERIC)
    specs = [candidates.CandidateSpec(op="delete", cols=["x"], row_ids=[2]),
             candidates.CandidateSpec(op="impute", cols=["x"], row_ids=[2], imputed_column="no_such_column")]

    with pytest.raises(Exception):
        candidates.stage_all(ROOT, specs)

    assert not any(node.provisional for node in _graph().node_map.values())
    assert _candidate_tables() == set()
    # The names it claimed are spent all the same, so none is ever handed out twice
    assert _graph().candidate_count == 2


@pytest.mark.sql
def test_a_reset_while_building_stages_nothing(root, monkeypatch):
    from app.pgraph.pgraph import PGraph
    from app.server_utils import candidates
    root(NUMERIC)
    session_graph = _graph()
    build_node = candidates.build_node

    def build_then_reset(table, root_table):
        built = build_node(table, root_table)
        # The user went Home and uploaded again while the candidate was being built
        app.pgraph_for_session = PGraph()
        return built

    monkeypatch.setattr(candidates, "build_node", build_then_reset)

    with pytest.raises(candidates.CandidateError, match="session changed"):
        candidates.stage_all(ROOT, [candidates.CandidateSpec(op="delete", cols=["x"], row_ids=[2])])

    assert _candidate_tables() == set()
    assert app.pgraph_for_session.node_map == {}
    app.pgraph_for_session = session_graph


@pytest.mark.sql
def test_builds_run_without_holding_the_graph_lock(root, monkeypatch):
    from app.server_utils import candidates
    from app.server_utils.service_helpers import WRANGLE_LOCK
    root(NUMERIC)
    build_node = candidates.build_node
    lock_was_free = []

    def build_and_check_the_lock(table, root_table):
        # Another request - accepting or declining a candidate, say - must not have to wait for a build to finish
        acquired = WRANGLE_LOCK.acquire(timeout=5)
        lock_was_free.append(acquired)
        if acquired:
            WRANGLE_LOCK.release()
        return build_node(table, root_table)

    monkeypatch.setattr(candidates, "build_node", build_and_check_the_lock)

    candidates.stage_all(ROOT, [candidates.CandidateSpec(op="delete", cols=["x"], row_ids=[2])])

    assert lock_was_free == [True]
