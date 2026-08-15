"""Tests for the direct delete-column wrangle route."""

from unittest.mock import MagicMock

from app import app
from app.routes import wrangler_routes_sql


class FakeBegin:
    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeEngine:
    def begin(self):
        return FakeBegin()


class FakeDeleteColumnDelta:
    def __init__(self, operation, parameters):
        self.operation = operation
        self.parameters = parameters

    def operation_result(self, engine, table):
        return {
            "remaining_columns": 2,
            "deleted_column": self.parameters["column"],
            "column_deleted": True,
        }

    def create_view(self, conn, engine, table, new_table_name):
        return True


def test_delete_column_route_updates_errors_and_rankings(monkeypatch):
    db_operations = MagicMock()
    db_operations.main_table_name = "n0_sales"
    update_errors_table = MagicMock()

    monkeypatch.setattr(wrangler_routes_sql, "db_operations", db_operations)
    monkeypatch.setattr(wrangler_routes_sql, "engine", FakeEngine())
    monkeypatch.setattr(wrangler_routes_sql, "Delta", FakeDeleteColumnDelta)
    monkeypatch.setattr(wrangler_routes_sql, "update_errors_table", update_errors_table)
    monkeypatch.setattr(wrangler_routes_sql, "n_wrangle", lambda *args, **kwargs: "n1_sales")

    with app.test_request_context("/api/wrangle/delete-column", method="POST", json={"column": "foo"}):
        result = wrangler_routes_sql.wrangle_delete_column()

    assert result["success"] is True
    db_operations.load_table.assert_called_once_with("n1_sales", "errors_n1_sales")
    update_errors_table.assert_called_once()
    db_operations.update_rankings.assert_called_once_with("n1_sales")
