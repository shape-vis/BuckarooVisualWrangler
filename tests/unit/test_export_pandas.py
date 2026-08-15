"""Tests for the /api/export/pandas endpoint used by the Export button."""

import io
import zipfile
from unittest.mock import MagicMock

import app as app_module
from app import app
from app.pgraph.delta import Delta
from app.pgraph.node import GraphNode
from app.pgraph.pgraph import PGraph
from app.routes import routes
from app.server_utils.pandas_export import EXPORT_LIBRARY_FILENAME


def build_export_graph():
    """Build a tiny graph: original sales table -> delete row 2."""
    graph = PGraph()
    root = GraphNode("root", "root", "n0_sales", "errors_n0_sales")
    delete_node = GraphNode(
        "n0_sales",
        "delete",
        "n1_sales",
        "errors_n1_sales",
        delta=Delta("delete", {"operation": "delete", "row_ids": [2]}),
    )

    graph.add_root_node(root)
    graph.add_node(delete_node)
    return graph


def test_export_pandas_returns_error_when_no_table_loaded(monkeypatch):
    # monkeypatch replaces the real DBOperations with a fake object so this unit
    # test does not need a database or uploaded CSV.
    db_operations = MagicMock()
    db_operations.main_table_name = None
    monkeypatch.setattr(routes, "db_operations", db_operations)

    response = app.test_client().get("/api/export/pandas")

    assert response.status_code == 400
    assert response.get_json() == {"success": False, "error": "No table loaded"}


def test_export_pandas_returns_error_when_graph_missing(monkeypatch):
    # A current table without a provenance graph cannot be exported, because
    # the graph is where the replayable Deltas live.
    db_operations = MagicMock()
    db_operations.main_table_name = "n1_sales"
    monkeypatch.setattr(routes, "db_operations", db_operations)
    monkeypatch.setattr(app_module.get_session_state(), "pgraph_for_session", None)

    response = app.test_client().get("/api/export/pandas")

    assert response.status_code == 400
    assert response.get_json() == {
        "success": False,
        "error": "No provenance graph loaded",
    }


def test_export_pandas_returns_bundle_for_current_table(monkeypatch):
    # This is the success case: the route finds the current table, walks the
    # graph to n1_sales, and returns a zip bundle with a script that loads
    # sales.csv then deletes row ID 2, plus the helper library it imports.
    db_operations = MagicMock()
    db_operations.main_table_name = "n1_sales"
    monkeypatch.setattr(routes, "db_operations", db_operations)
    graph = build_export_graph()
    graph.source_filename = "sales.csv"
    monkeypatch.setattr(app_module.get_session_state(), "pgraph_for_session", graph)
    monkeypatch.setattr(app_module.get_session_state(), "original_table_name", "sales.csv")

    response = app.test_client().get("/api/export/pandas")

    assert response.status_code == 200
    assert response.mimetype == "application/zip"

    with zipfile.ZipFile(io.BytesIO(response.data)) as bundle:
        names = bundle.namelist()
        assert "buckaroo_export.py" in names
        assert EXPORT_LIBRARY_FILENAME in names

        script = bundle.read("buckaroo_export.py").decode("utf-8")
        library = bundle.read(EXPORT_LIBRARY_FILENAME).decode("utf-8")

    # The script imports its helpers from the bundled library instead of
    # defining them inline.
    assert "from buckaroo_export_helpers import (" in script
    assert "df = pd.read_csv('sales.csv')" in script
    assert "df = buckaroo_ensure_id(df)" in script
    assert "df = buckaroo_delete_rows_by_id(df, [2])" in script
    assert "def buckaroo_ensure_id" not in script

    # The boilerplate now lives in the library file.
    assert "def buckaroo_ensure_id" in library
    assert "def buckaroo_delete_rows_by_id" in library
