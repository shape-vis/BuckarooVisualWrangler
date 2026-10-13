"""
The compare endpoint against a real graph: two nodes whose tables live in Postgres, read through the
same Flask route the compare modal calls.

The binning itself is covered in tests/sql/test_compare_sql.py. What this pins is the part
only a database exercises - reading both tables and their error flags - and a payload that survives
Flask's JSON encoding.
"""
import pytest

import app
from app import engine, db_operations
from app.server_utils import ai_wrangle as aw

ROOT = "n0a_cmpnodes"
COLUMNS = ["height", "weight"]


@pytest.fixture
def graph(make_root):
    """A root whose row 3 is missing height, and a child node that imputed it."""
    data = {"ID": [1, 2, 3, 4, 5], "height": [10.0, 20.0, None, 60.0, 30.0], "weight": [1.0, 2.0, 3.0, 4.0, 5.0]}
    make_root(ROOT, data, flags=[(3, "height", "missing")])

    result = aw.apply_suggestion(ROOT, {"op": "impute_rows", "column": "height", "error_type": "missing"}, COLUMNS)
    assert result["success"] is True, result
    child = result["table"]

    return ROOT, child


def _compare(client, **params):
    response = client.get("/api/pgraph/compare", query_string=params)
    return response.status_code, response.get_json()


@pytest.mark.sql
def test_histogram_compares_the_two_tables(graph, client):
    root, child = graph

    status, body = _compare(client, a=root, b=child, kind="histogram", x="height", bins=5)

    assert status == 200, body
    assert body["rows"] == {"a": 5, "b": 5}

    null_bin = next(b for b in body["bins"] if b["xType"] == "categorical" and b["xBin"] == "null")
    assert null_bin["a"] == {"items": 1, "missing": 1}
    assert null_bin["b"] == {"items": 0}


@pytest.mark.sql
def test_heatmap_accounts_for_every_row(graph, client):
    root, child = graph

    status, body = _compare(client, a=root, b=child, kind="heatmap", x="height", y="weight", bins=2)

    assert status == 200, body
    assert sum(tile["a"]["items"] for tile in body["tiles"]) == 5
    assert sum(tile["b"]["items"] for tile in body["tiles"]) == 5


@pytest.mark.sql
@pytest.mark.parametrize("params, message", [
    ({"b": "n9z_not_a_node", "x": "height"}, "not a node"),
    ({"x": "nope"}, "no column"),
    ({"x": "height", "kind": "heatmap"}, "needs a y column"),
    ({"x": "height", "kind": "pie"}, "unknown plot kind"),
])
def test_bad_requests_are_refused(graph, client, params, message):
    root, child = graph

    status, body = _compare(client, **{"a": root, "b": child, **params})

    assert status == 400
    assert body["success"] is False
    assert message in body["error"]
