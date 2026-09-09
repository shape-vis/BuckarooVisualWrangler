"""
The two endpoints, with the model stubbed out.

The network call is the only part of the workflow that cannot be tested offline, so it is the
only part replaced here: everything downstream of "the model said to call these tools" is real -
validation, id resolution, the guards, the wrangle, the new node.
"""
import json
import pytest
import pandas as pd
from sqlalchemy import text as sa_text

import app
from app import engine, db_operations
from app import app as flask_app
from app.llm import gemini_client
from app.routes.wrangler_routes_sql import update_errors_table
from app.server_utils.service_helpers import build_data_profile_table, init_pgraph_for_session

ROOT = "n0a_airoute"


def _drop_all(*tables):
    with engine.begin() as conn:
        for t in tables:
            for name in (t, f"errors_{t}", f"dp_{t}", f"rankings_{t}", f"{t}_filtering"):
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "{name}"'))
            for suffix in ("_preview_delete", "_preview_impute",
                           "_preview_impute_x", "_preview_impute_y"):
                for prefix in ("", "errors_", "dp_"):
                    conn.execute(sa_text(f'DROP TABLE IF EXISTS "{prefix}{t}{suffix}"'))


def _make_root(flags):
    pd.DataFrame({
        "ID": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "a": [10.0, 20.0, None, 60.0, 30.0, 40.0, 50.0, 70.0, 80.0, 90.0],
        "b": [1.0, 2.0, 3.0, None, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
    }).to_sql(ROOT, engine, if_exists="replace", index=False)
    update_errors_table(ROOT)
    pd.DataFrame(flags, columns=["row_id", "column_id", "error_type"]).astype(
        {"row_id": "int64"}
    ).to_sql(f"errors_{ROOT}", engine, if_exists="replace", index=False)
    build_data_profile_table(ROOT)
    init_pgraph_for_session(ROOT)
    db_operations.load_table(ROOT, f"errors_{ROOT}", f"dp_{ROOT}")


@pytest.fixture
def graph():
    created = [ROOT]
    yield created
    app.pgraph_for_session = None
    _drop_all(*created)


@pytest.fixture
def stub_model(monkeypatch):
    """Replace only the network call. Everything it feeds is the real thing."""
    def install(calls):
        monkeypatch.setattr(gemini_client, "api_key", lambda: "test-key")
        monkeypatch.setattr(
            gemini_client, "generate",
            lambda system, user, tools, **kw: [dict(c) for c in calls],
        )
    return install


@pytest.mark.sql
def test_suggest_returns_validated_suggestions(graph, stub_model):
    _make_root([(3, "a", "missing"), (4, "b", "missing")])
    stub_model([
        {"name": "impute_rows",
         "args": {"column": "a", "error_type": "missing", "reason": "One blank age."}},
        {"name": "delete_rows",
         "args": {"column": "b", "error_type": "missing", "reason": "One blank b."}},
    ])

    resp = flask_app.test_client().post("/api/ai/suggest", json={"node_table": ROOT})
    assert resp.status_code == 200
    body = resp.get_json()

    assert body["success"] is True
    assert len(body["suggestions"]) == 2
    first = body["suggestions"][0]
    assert first["op"] == "impute_rows"
    assert first["columns"] == ["a"]
    assert first["row_count"] == 1, "the count is resolved server-side, not taken from the model"
    assert first["label"] == "impute · a"
    assert first["reason"] == "One blank age."


@pytest.mark.sql
def test_suggest_drops_what_it_cannot_run(graph, stub_model):
    """A hallucinated column, and a delete that would gut the table, are dropped silently."""
    _make_root([(i, "a", "missing") for i in range(1, 8)] + [(3, "b", "missing")])
    stub_model([
        {"name": "impute_rows",
         "args": {"column": "not_a_column", "error_type": "missing", "reason": "nope"}},
        {"name": "delete_rows",
         "args": {"column": "a", "error_type": "missing", "reason": "70% of the table"}},
        {"name": "impute_rows",
         "args": {"column": "b", "error_type": "missing", "reason": "one blank"}},
    ])

    body = flask_app.test_client().post(
        "/api/ai/suggest", json={"node_table": ROOT}
    ).get_json()

    assert [s["op"] for s in body["suggestions"]] == ["impute_rows"]
    assert body["suggestions"][0]["columns"] == ["b"]


@pytest.mark.sql
def test_suggest_honours_no_suggestions(graph, stub_model):
    _make_root([])
    stub_model([{"name": "no_suggestions", "args": {"reason": "Everything looks clean."}}])

    body = flask_app.test_client().post(
        "/api/ai/suggest", json={"node_table": ROOT}
    ).get_json()

    assert body["no_suggestions"] == "Everything looks clean."
    assert "suggestions" not in body


@pytest.mark.sql
def test_suggest_does_not_move_the_session(graph, stub_model):
    """Asking for suggestions must not change which table the app is on."""
    _make_root([(3, "a", "missing")])
    stub_model([{"name": "impute_rows",
                 "args": {"column": "a", "error_type": "missing", "reason": "x"}}])

    flask_app.test_client().post("/api/ai/suggest", json={"node_table": ROOT})
    assert db_operations.main_table_name == ROOT
    assert app.pgraph_for_session.current_node_table_name == ROOT


@pytest.mark.sql
def test_accept_runs_the_wrangle(graph, stub_model):
    _make_root([(3, "a", "missing")])

    body = flask_app.test_client().post("/api/ai/accept", json={
        "node_table": ROOT,
        "suggestion": {"op": "impute_rows", "column": "a", "error_type": "missing"},
    }).get_json()
    graph.append(body["table"])

    assert body["success"] is True
    assert app.pgraph_for_session.node_map[body["table"]].parent_table == ROOT
    after = pd.read_sql_query(f'SELECT * FROM "{body["table"]}" ORDER BY "ID"', engine)
    assert after.loc[after["ID"] == 3, "a"].iloc[0] == pytest.approx(50.0)


@pytest.mark.sql
def test_accept_revalidates_instead_of_trusting_the_client(graph):
    """A payload the model could never have produced is refused, not run."""
    _make_root([(3, "a", "missing")])
    client = flask_app.test_client()

    forged = client.post("/api/ai/accept", json={
        "node_table": ROOT,
        "suggestion": {"op": "impute_rows", "column": "a; DROP TABLE students",
                       "error_type": "missing"},
    })
    assert forged.status_code == 422
    assert "no such column" in forged.get_json()["error"]

    bad_op = client.post("/api/ai/accept", json={
        "node_table": ROOT,
        "suggestion": {"op": "truncate_everything", "column": "a", "error_type": "missing"},
    })
    assert bad_op.status_code == 422

    # The table is untouched by either attempt
    assert len(pd.read_sql_query(f'SELECT * FROM "{ROOT}"', engine)) == 10


@pytest.mark.sql
def test_unknown_node_is_refused(graph):
    _make_root([])
    resp = flask_app.test_client().post("/api/ai/suggest", json={"node_table": "../etc/passwd"})
    assert resp.status_code == 400
    assert "not a node" in resp.get_json()["error"]


@pytest.mark.sql
def test_status_reports_configuration(graph, monkeypatch):
    monkeypatch.setattr(gemini_client, "api_key", lambda: None)
    assert flask_app.test_client().get("/api/ai/status").get_json()["configured"] is False

    monkeypatch.setattr(gemini_client, "api_key", lambda: "k")
    assert flask_app.test_client().get("/api/ai/status").get_json()["configured"] is True


@pytest.mark.sql
def test_suggest_reports_a_missing_key_as_503(graph, monkeypatch):
    _make_root([(3, "a", "missing")])
    monkeypatch.setattr(gemini_client, "api_key", lambda: None)

    resp = flask_app.test_client().post("/api/ai/suggest", json={"node_table": ROOT})
    assert resp.status_code == 503
    assert "GEMINI_API_KEY" in resp.get_json()["error"]


@pytest.mark.sql
def test_endpoints_survive_a_session_with_no_graph_yet(monkeypatch):
    """
    Before the first upload there is no graph at all - and the attribute does not merely hold
    None, it does not exist.

    app/__init__.py's `app.pgraph_for_session = None` sets that on the Flask object, which is
    what `app` names inside that module. The attribute the rest of the code reads lives on the
    app *package* and is created by init_pgraph_for_session. Reading it directly turns a fresh
    server's first click into a 500.
    """
    monkeypatch.delattr(app, "pgraph_for_session", raising=False)
    assert not hasattr(app, "pgraph_for_session")

    from app.server_utils import ai_wrangle
    assert ai_wrangle.session_graph() is None
    assert ai_wrangle.known_node("anything") is False

    client = flask_app.test_client()
    for route, payload in (
        ("/api/ai/suggest", {"node_table": "anything"}),
        ("/api/ai/accept", {"node_table": "anything",
                            "suggestion": {"op": "impute_rows", "column": "a",
                                           "error_type": "missing"}}),
    ):
        resp = client.post(route, json=payload)
        assert resp.status_code == 400, f"{route} returned {resp.status_code}"
        assert "not a node" in resp.get_json()["error"]
