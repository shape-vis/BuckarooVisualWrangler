"""
The AI endpoints, with the model stubbed out. A suggestion is staged as a candidate - a provisional node - and
accepted through /api/candidates/accept, as a repair of the user's selection is.

The network call is the only part of the workflow that cannot be tested offline, so it is the
only part replaced here: everything downstream of "the model said to call these tools" is real -
validation, id resolution, the guards, the wrangle, the new node.
"""
import pytest
import pandas as pd

import app
from app import engine, db_operations
from app import app as flask_app
from app.llm import gemini_client

ROOT = "n0a_airoute"


# Ten rows over two columns; each test names which of their cells are flagged
DATA = {
    "ID": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "a": [10.0, 20.0, None, 60.0, 30.0, 40.0, 50.0, 70.0, 80.0, 90.0],
    "b": [1.0, 2.0, 3.0, None, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
}


@pytest.fixture
def root(make_root):
    """:return: a function building the root from DATA, flagged exactly as given"""
    def build(flags):
        make_root(ROOT, DATA, flags)
    return build


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
def test_suggest_returns_validated_suggestions(root, stub_model):
    root([(3, "a", "missing"), (4, "b", "missing")])
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
    assert len(body["candidates"]) == 2
    first = body["candidates"][0]
    assert first["source"] == "ai"
    assert first["suggestion"]["op"] == "impute_rows"
    assert first["cols"] == ["a"]
    assert first["row_count"] == 1, "the count is resolved server-side, not taken from the model"
    assert first["label"] == "impute · a"
    assert first["reason"] == "One blank age."
    assert first["chart_type"] == "histogram"
    # Staged as a provisional node under the root, its wrangle already run on its own table
    node = app.pgraph_for_session.node_map[first["table"]]
    assert node.provisional and node.parent_table == ROOT


@pytest.mark.sql
def test_suggest_drops_what_it_cannot_run(root, stub_model):
    """A hallucinated column, and a delete that would gut the table, are dropped silently."""
    root([(i, "a", "missing") for i in range(1, 8)] + [(3, "b", "missing")])
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

    assert [c["suggestion"]["op"] for c in body["candidates"]] == ["impute_rows"]
    assert body["candidates"][0]["cols"] == ["b"]


@pytest.mark.sql
def test_suggest_honours_no_suggestions(root, stub_model):
    root([])
    stub_model([{"name": "no_suggestions", "args": {"reason": "Everything looks clean."}}])

    body = flask_app.test_client().post(
        "/api/ai/suggest", json={"node_table": ROOT}
    ).get_json()

    assert body["no_suggestions"] == "Everything looks clean."
    assert "candidates" not in body


@pytest.mark.sql
def test_suggest_does_not_move_the_session(root, stub_model):
    """Asking for suggestions must not change which table the app is on."""
    root([(3, "a", "missing")])
    stub_model([{"name": "impute_rows",
                 "args": {"column": "a", "error_type": "missing", "reason": "x"}}])

    flask_app.test_client().post("/api/ai/suggest", json={"node_table": ROOT})
    assert db_operations.main_table_name == ROOT
    assert app.pgraph_for_session.current_node_table_name == ROOT


@pytest.mark.sql
def test_accepting_a_suggestion_runs_the_wrangle(root, stub_model):
    root([(3, "a", "missing")])
    stub_model([{"name": "impute_rows",
                 "args": {"column": "a", "error_type": "missing", "reason": "x"}}])
    client = flask_app.test_client()

    staged = client.post("/api/ai/suggest", json={"node_table": ROOT}).get_json()["candidates"][0]
    body = client.post("/api/candidates/accept", json={"table": staged["table"]}).get_json()

    assert body["success"] is True
    assert body["table"] == staged["table"], "accepting renames nothing"
    assert body["label"] == "n0b"
    assert not app.pgraph_for_session.node_map[body["table"]].provisional
    after = pd.read_sql_query(f'SELECT * FROM "{body["table"]}" ORDER BY "ID"', engine)
    assert after.loc[after["ID"] == 3, "a"].iloc[0] == pytest.approx(50.0)


@pytest.mark.sql
def test_accept_only_takes_a_candidate(root):
    """Nothing but a staged candidate can be accepted - not a node that already is one, not a stranger."""
    root([(3, "a", "missing")])
    client = flask_app.test_client()

    assert client.post("/api/candidates/accept", json={"table": ROOT}).status_code == 409
    assert client.post("/api/candidates/accept", json={"table": "c99_nothing"}).status_code == 409
    # The table is untouched by either attempt
    assert len(pd.read_sql_query(f'SELECT * FROM "{ROOT}"', engine)) == 10


@pytest.mark.sql
def test_unknown_node_is_refused(root):
    root([])
    resp = flask_app.test_client().post("/api/ai/suggest", json={"node_table": "../etc/passwd"})
    assert resp.status_code == 400
    assert "not a node" in resp.get_json()["error"]


@pytest.mark.sql
def test_status_reports_configuration(root, monkeypatch):
    monkeypatch.setattr(gemini_client, "api_key", lambda: None)
    assert flask_app.test_client().get("/api/ai/status").get_json()["configured"] is False

    monkeypatch.setattr(gemini_client, "api_key", lambda: "k")
    assert flask_app.test_client().get("/api/ai/status").get_json()["configured"] is True


@pytest.mark.sql
def test_suggest_reports_a_missing_key_as_503(root, monkeypatch):
    root([(3, "a", "missing")])
    monkeypatch.setattr(gemini_client, "api_key", lambda: None)

    resp = flask_app.test_client().post("/api/ai/suggest", json={"node_table": ROOT})
    assert resp.status_code == 503
    assert "GEMINI_API_KEY" in resp.get_json()["error"]


@pytest.mark.sql
def test_endpoints_survive_a_session_with_no_graph_yet(monkeypatch):
    """
    Before the first upload there is no graph: the app package's pgraph_for_session holds None. Every endpoint
    that reads the graph has to answer that with an error of its own, not a 500.
    """
    monkeypatch.setattr(app, "pgraph_for_session", None)

    from app.server_utils import ai_wrangle
    from app.server_utils.service_helpers import session_graph
    assert session_graph() is None
    assert ai_wrangle.known_node("anything") is False

    client = flask_app.test_client()
    resp = client.post("/api/ai/suggest", json={"node_table": "anything"})
    assert resp.status_code == 400
    assert "not a node" in resp.get_json()["error"]

    resp = client.post("/api/candidates/accept", json={"table": "anything"})
    assert resp.status_code == 409
    assert "no graph" in resp.get_json()["error"]

    resp = client.get("/api/pgraph/drift_detail", query_string={"node": "anything", "column": "a"})
    assert resp.status_code == 400
    assert "no graph" in resp.get_json()["error"]
