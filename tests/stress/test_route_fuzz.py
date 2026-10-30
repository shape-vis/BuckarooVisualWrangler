"""
Every data route given input it should refuse: unknown columns and tables, names built to break out of a query,
malformed bodies, ids of the wrong type or past bigint's range. A route may refuse with a 4xx or a {"success": false}
- what it must never do is answer 500, change the graph, or leave a table behind.
"""
import io

import pytest

import app
from app import engine
from app.db_utils.execute_sql import fetch_sql
from tests.stress import generators

INJECTIONS = (
    "nope",
    "",
    'x"; DROP TABLE "ID"; --',
    "x'); DROP TABLE pg_class; --",
    "../../etc/passwd",
    "a" * 300,
    "名前",
    "%00",
)

BAD_IDS = (
    ["1"],
    ["1; DROP TABLE x"],
    [1.5],
    [None],
    [[1, 2]],
    [True],
    [{"id": 1}],
    [2 ** 70],
    [-(2 ** 70)],
    "1,2,3",
    None,
)


def all_tables():
    rows = fetch_sql("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'", False,
                     engine) or []
    names = set()
    for (name,) in rows:
        names.add(name)
    return names


def graph_shape():
    graph = app.pgraph_for_session
    if graph is None:
        return None
    return (tuple(sorted(graph.node_map)), graph.current_node_table_name, app.db_operations.main_table_name)


@pytest.fixture
def root(make_root):
    return make_root(generators.make_dataset(11, row_count=60), ingest="direct")


@pytest.fixture
def unchanged(root):
    """Checks, after the test, that the graph and the database are as they were before it."""
    tables_before = all_tables()
    shape_before = graph_shape()
    yield
    assert graph_shape() == shape_before, "the graph changed"
    assert all_tables() - tables_before == set(), "a table was left behind"


def assert_refused_politely(response):
    assert response.status_code < 500, response.get_data(as_text=True)[:500]
    body = response.get_json(silent=True)
    if response.status_code < 400:
        assert body is not None and body.get("success") is False, body


@pytest.mark.sql
@pytest.mark.parametrize("name", INJECTIONS)
def test_plot_routes_refuse_unknown_and_hostile_columns(client, root, unchanged, name):
    real = root.data_columns[0]
    requests = [
        ("/api/plots/1-d-histogram", {"column": name}),
        ("/api/plots/2-d-histogram", {"column_x": name, "column_y": real}),
        ("/api/plots/2-d-histogram", {"column_x": real, "column_y": name}),
        ("/api/plots/scatterplot", {"x_column": name, "y_column": real}),
        ("/api/plots/preview-histogram", {"tablename": root.name, "type": "1d", "column": name}),
        ("/api/pgraph/compare", {"a": root.name, "b": root.name, "kind": "histogram", "x": name}),
        ("/api/pgraph/compare", {"a": root.name, "b": root.name, "kind": "heatmap", "x": real, "y": name}),
        ("/api/pgraph/drift_detail", {"node": root.name, "column": name}),
    ]
    for path, params in requests:
        assert_refused_politely(client.get(path, query_string=params))


@pytest.mark.sql
@pytest.mark.parametrize("name", INJECTIONS + ("pg_class", "information_schema.tables", "errors_x"))
def test_routes_refuse_tables_that_are_not_nodes(client, root, unchanged, name):
    column = root.data_columns[0]
    gets = [
        ("/api/plots/preview-histogram", {"tablename": name, "type": "1d", "column": column}),
        ("/api/plots/preview-scatterplot", {"tablename": name, "x_column": column, "y_column": column}),
        ("/api/pgraph/compare", {"a": name, "b": root.name, "kind": "histogram", "x": column}),
        ("/api/pgraph/compare", {"a": root.name, "b": name, "kind": "histogram", "x": column}),
        ("/api/pgraph/drift_detail", {"node": name, "column": column}),
    ]
    # An empty base is no base - drift measured from root - which is what the panel sends for one
    if name:
        gets.append(("/api/pgraph/drift_detail", {"node": root.name, "column": column, "base": name}))
    for path, params in gets:
        assert_refused_politely(client.get(path, query_string=params))

    posts = [
        ("/api/candidates/accept", {"table": name}),
        ("/api/candidates/discard", {"tables": [name]}),
        ("/api/setGraphToClickedNode", {"nodeId": name}),
        ("/api/pgraph/support_nodes", {"host": name, "record": {}}),
    ]
    for path, body in posts:
        assert_refused_politely(client.post(path, json=body))


@pytest.mark.sql
@pytest.mark.parametrize("bins", ["abc", "-5", "0", "1e9", "999999999", "NaN", ""])
def test_bin_counts_out_of_range_are_refused_or_bounded(client, root, unchanged, bins):
    column = root.data_columns[0]
    for path, params in (("/api/plots/1-d-histogram", {"column": column, "bins": bins}),
                         ("/api/pgraph/compare", {"a": root.name, "b": root.name, "kind": "histogram", "x": column,
                                                  "bins": bins})):
        response = client.get(path, query_string=params)
        assert response.status_code < 500
        body = response.get_json()
        if body.get("success"):
            # Accepted, then held to the bounds rather than taken at its word
            payload = body.get("histogram") or body
            scale = payload["scaleX"]
            assert len(scale["numeric"]) <= 50


@pytest.mark.sql
@pytest.mark.parametrize("row_ids", BAD_IDS)
def test_create_previews_refuses_ids_that_are_not_row_ids(client, root, unchanged, row_ids):
    response = client.post("/api/wrangle/create-previews", json={"row_ids": row_ids, "cols": [root.data_columns[0]]})
    assert_refused_politely(response)


@pytest.mark.sql
@pytest.mark.parametrize("cols", [
    ["nope"], [""], ['x"; DROP TABLE y; --'], [None], [1], "abc", ["ID"], ["index"],
])
def test_create_previews_refuses_columns_that_are_not_data(client, root, unchanged, cols):
    response = client.post("/api/wrangle/create-previews", json={"row_ids": [1, 2], "cols": cols})
    assert_refused_politely(response)


@pytest.mark.sql
@pytest.mark.parametrize("path", ["/api/wrangle/create-previews", "/api/candidates/accept", "/api/candidates/discard",
                                  "/api/plots/rows-in-bin", "/api/plots/bins-for-rows", "/api/setGraphToClickedNode",
                                  "/api/plots/update-backend-attributes", "/api/pgraph/support_nodes"])
@pytest.mark.parametrize("raw", [b"", b"not json", b"[1, 2, 3]", b'"just a string"', b"{", b"null"])
def test_post_routes_survive_malformed_bodies(client, root, unchanged, path, raw):
    response = client.post(path, data=raw, content_type="application/json")
    assert_refused_politely(response)


@pytest.mark.sql
def test_selection_routes_refuse_bins_nobody_drew(client, root, unchanged):
    column = root.data_columns[0]
    requests = [
        ("/api/plots/rows-in-bin", {"type": "1d", "column": column, "bin": "0"}),
        ("/api/plots/rows-in-bin", {"type": "2d", "column_x": column, "column_y": column, "x_bin": "0",
                                    "y_bin": "0"}),
        ("/api/plots/bins-for-rows", {"type": "1d", "column": column, "row_ids": [1]}),
        ("/api/plots/bins-for-rows", {"type": "1d", "column": column, "row_ids": "abc"}),
    ]
    for path, body in requests:
        assert_refused_politely(client.post(path, json=body))


@pytest.mark.sql
def test_undo_at_the_root_and_redo_at_the_tip_are_refused(client, root, unchanged):
    assert_refused_politely(client.post("/api/undo"))
    assert_refused_politely(client.post("/api/redo"))


@pytest.mark.sql
@pytest.mark.parametrize("record", [
    None, {}, {"id": "nope"}, {"id": "support:x", "kind": "pie"},
    {"id": "support:x", "kind": "compare", "hostId": "someone else"},
])
def test_support_node_records_that_are_not_records_are_refused(client, root, unchanged, record):
    assert_refused_politely(client.post("/api/pgraph/support_nodes", json={"host": root.name, "record": record}))
    assert_refused_politely(client.patch("/api/pgraph/support_nodes",
                                         json={"host": root.name, "id": "support:none", "changes": record}))


@pytest.mark.sql
@pytest.mark.parametrize("name", ["../../etc/passwd", "does_not_exist.csv", "", "..", "/", None])
def test_preloaded_refuses_files_that_are_not_provided(client, session, name):
    tables_before = all_tables()

    # None sends no file at all
    params = {}
    if name is not None:
        params["file"] = name
    response = client.get("/api/preloaded", query_string=params)

    assert_refused_politely(response)
    assert all_tables() == tables_before


@pytest.mark.sql
@pytest.mark.parametrize("content", [
    b"",
    b"only,a,header\n",
    b"\x00\x01\x02\xff\xfe binary",
    b"a,a,b\n1,2,3\n4,5,6\n",
    b"a,b\n1,2,3,4\n5\n",
    b'a,b\n"unterminated,1\n',
])
def test_uploads_that_are_not_tables_are_refused(client, session, content):
    tables_before = all_tables()

    response = client.post("/api/upload", data={"file": (io.BytesIO(content), "bad.csv")},
                           content_type="multipart/form-data")

    assert response.status_code < 500, response.get_data(as_text=True)[:300]
    body = response.get_json()
    if not body.get("success"):
        assert all_tables() == tables_before, "a failed upload left a table behind"
