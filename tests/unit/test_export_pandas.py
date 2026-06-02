from unittest.mock import MagicMock

import app as app_module
from app import app
from app.pgraph.delta import Delta
from app.pgraph.node import GraphNode
from app.pgraph.pgraph import PGraph
from app.routes import routes


def build_export_graph():
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
    db_operations = MagicMock()
    db_operations.main_table_name = None
    monkeypatch.setattr(routes, "db_operations", db_operations)

    response = app.test_client().get("/api/export/pandas")

    assert response.status_code == 400
    assert response.get_json() == {"success": False, "error": "No table loaded"}


def test_export_pandas_returns_error_when_graph_missing(monkeypatch):
    db_operations = MagicMock()
    db_operations.main_table_name = "n1_sales"
    monkeypatch.setattr(routes, "db_operations", db_operations)
    monkeypatch.setattr(app_module, "pgraph_for_session", None)

    response = app.test_client().get("/api/export/pandas")

    assert response.status_code == 400
    assert response.get_json() == {
        "success": False,
        "error": "No provenance graph loaded",
    }


def test_export_pandas_returns_script_for_current_table(monkeypatch):
    db_operations = MagicMock()
    db_operations.main_table_name = "n1_sales"
    monkeypatch.setattr(routes, "db_operations", db_operations)
    monkeypatch.setattr(app_module, "pgraph_for_session", build_export_graph())
    monkeypatch.setattr(app_module, "original_table_name", "sales.csv")

    response = app.test_client().get("/api/export/pandas")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert "df = pd.read_csv('sales.csv')" in payload["script"]
    assert "df = df[~df['ID'].isin([2])]" in payload["script"]
