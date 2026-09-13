"""
The compare endpoint against a real graph: two nodes whose tables live in Postgres, read through the
same Flask route the compare modal calls.

The comparison arithmetic is covered in tests/unit/test_node_compare.py. What this pins is the part
only a database exercises - reading both tables and their error flags - and a payload that survives
Flask's JSON encoding.
"""
import pytest
import pandas as pd
from sqlalchemy import text as sa_text

import app
from app import engine, db_operations
from app.routes.wrangler_routes_sql import update_errors_table
from app.server_utils import ai_wrangle as aw
from app.server_utils.service_helpers import build_data_profile_table, init_pgraph_for_session

ROOT = "n0a_cmpnodes"
COLUMNS = ["a", "b"]


def _drop_all(*tables):
    with engine.begin() as conn:
        for t in tables:
            for name in (t, f"errors_{t}", f"dp_{t}", f"rankings_{t}", f"{t}_filtering"):
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "{name}"'))


@pytest.fixture
def graph():
    """A root whose row 3 is missing a, and a child node that imputed it."""
    pd.DataFrame({"ID": [1, 2, 3, 4, 5], "a": [10.0, 20.0, None, 60.0, 30.0],
                  "b": [1.0, 2.0, 3.0, 4.0, 5.0]}).to_sql(ROOT, engine, if_exists="replace", index=False)
    update_errors_table(ROOT)
    # Take control of exactly which flags exist, so the assertions are about this layout rather than
    # about whatever the detectors happened to find
    pd.DataFrame([(3, "a", "missing")], columns=["row_id", "column_id", "error_type"]).astype(
        {"row_id": "int64"}
    ).to_sql(f"errors_{ROOT}", engine, if_exists="replace", index=False)
    build_data_profile_table(ROOT)
    init_pgraph_for_session(ROOT)
    db_operations.load_table(ROOT, f"errors_{ROOT}", f"dp_{ROOT}")

    result = aw.apply_suggestion(ROOT, {"op": "impute_rows", "column": "a", "error_type": "missing"}, COLUMNS)
    assert result["success"] is True, result
    child = result["table"]

    yield ROOT, child

    app.pgraph_for_session = None
    _drop_all(ROOT, child)


@pytest.fixture
def client():
    return app.app.test_client()


def _compare(client, **params):
    response = client.get("/api/pgraph/compare", query_string=params)
    return response.status_code, response.get_json()


@pytest.mark.sql
def test_histogram_compares_the_two_tables(graph, client):
    root, child = graph

    status, body = _compare(client, base=root, other=child, kind="histogram", x="a", bins=5)

    assert status == 200, body
    assert body["rows"] == {"base": 5, "other": 5}
    # The imputed row changed; nothing was deleted
    assert body["changes"]["removed"] == 0
    assert body["changes"]["changed"] == {"a": 1}

    null_bin = next(b for b in body["bins"] if b["xType"] == "categorical" and b["xBin"] == "null")
    assert null_bin["base"] == {"items": 1, "missing": 1}
    assert null_bin["other"] == {"items": 0}


@pytest.mark.sql
def test_scatter_follows_the_imputed_row(graph, client):
    root, child = graph

    status, body = _compare(client, base=root, other=child, kind="scatter", x="a", y="b")

    assert status == 200, body
    moved = [point for point in body["points"] if point["status"] == "changed"]
    assert [point["ID"] for point in moved] == [3]
    assert moved[0]["base"]["x"] == "null"
    assert moved[0]["base"]["errors"] == ["missing"]
    assert moved[0]["other"]["xType"] == "numeric"


@pytest.mark.sql
def test_heatmap_accounts_for_every_row(graph, client):
    root, child = graph

    status, body = _compare(client, base=root, other=child, kind="heatmap", x="a", y="b", bins=2)

    assert status == 200, body
    assert sum(tile["base"]["items"] for tile in body["tiles"]) == 5
    assert sum(tile["other"]["items"] for tile in body["tiles"]) == 5


@pytest.mark.sql
@pytest.mark.parametrize("params, message", [
    ({"other": "n9z_not_a_node", "x": "a"}, "not a node"),
    ({"x": "nope"}, "no column"),
    ({"x": "a", "kind": "heatmap"}, "needs a y column"),
    ({"x": "a", "kind": "pie"}, "unknown plot kind"),
])
def test_bad_requests_are_refused(graph, client, params, message):
    root, child = graph

    status, body = _compare(client, **{"base": root, "other": child, **params})

    assert status == 400
    assert body["success"] is False
    assert message in body["error"]
