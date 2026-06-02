from unittest.mock import MagicMock, patch

from app.pgraph.delta import Delta
from app.server_utils.pandas_mapper import map_to_pandas


class RecordingConnection:
    def __init__(self):
        self.sql = []

    def execute(self, statement, parameters=None):
        self.sql.append(str(statement))


def test_delta_generates_pandas_code_from_delete():
    delta = Delta("delete", {"operation": "delete", "row_ids": [1, 3]})
    assert delta.pandas_code == "df = df[~df['ID'].isin([1, 3])]"


def test_delta_json_stores_operation_parameters_and_pandas_code():
    delta = Delta("delete-column", {"operation": "delete-column", "column": "foo"})

    data = delta.__json__()

    assert data == {
        "operation": "delete-column",
        "parameters": {"operation": "delete-column", "column": "foo"},
        "pandas_code": "df.drop(columns=['foo'], inplace=True)",
    }


def test_delta_from_dict_preserves_stored_pandas_code():
    data = {
        "operation": "delete",
        "parameters": {"operation": "delete", "row_ids": [1, 2]},
        "pandas_code": "df = custom_export(df)",
    }

    delta = Delta.from_dict(data)

    assert delta.operation == "delete"
    assert delta.parameters == {"operation": "delete", "row_ids": [1, 2]}
    assert delta.pandas_code == "df = custom_export(df)"


def test_delta_from_dict_generates_pandas_code_when_not_stored():
    delta = Delta.from_dict({
        "operation": "delete",
        "parameters": {"operation": "delete", "row_ids": [9]},
    })

    assert delta.pandas_code == "df = df[~df['ID'].isin([9])]"


def test_map_to_pandas_delegates_to_delta():
    code = map_to_pandas("delete", {"row_ids": [2]})
    assert code == "df = df[~df['ID'].isin([2])]"


def test_delete_delta_creates_view_without_caller_knowing_sql_shape():
    conn = RecordingConnection()
    delta = Delta("delete", {"operation": "delete", "row_ids": [1, 3]})

    created = delta.create_view(conn, object(), "n0_sales", "n0_sales_preview_delete")

    assert created is True
    assert conn.sql[-1] == (
        'CREATE VIEW "n0_sales_preview_delete" AS '
        'SELECT * FROM "n0_sales" WHERE "ID" NOT IN (1, 3)'
    )


def test_delete_delta_returns_false_without_row_ids():
    conn = RecordingConnection()
    delta = Delta("delete", {"operation": "delete", "row_ids": []})
    assert delta.create_view(conn, object(), "n0_sales", "preview") is False
    assert conn.sql == []


def test_impute_delta_pandas_code():
    delta = Delta("impute", {"operation": "impute", "row_ids": [1], "col": "age"})
    assert "df['age']" in delta.pandas_code
    assert "[1]" in delta.pandas_code


@patch("app.db_utils.query._compute_imputation_value", return_value=42)
@patch("app.db_utils.query._is_numeric", return_value=True)
def test_impute_delta_creates_view_with_case_expression(mock_is_num, mock_fill):
    conn = RecordingConnection()
    engine = MagicMock()

    with patch(
        "app.wrangle_operations.impute.table_columns",
        return_value=["ID", "age"],
    ):
        delta = Delta("impute", {"operation": "impute", "row_ids": [1, 2], "col": "age"})
        created = delta.create_view(conn, engine, "n0_sales", "n0_sales_preview_impute")

    assert created is True
    create_sql = conn.sql[-1]
    assert 'CASE WHEN "ID" IN (1, 2) THEN 42' in create_sql
    assert '"age"' in create_sql


def test_delete_column_delta_pandas_code():
    delta = Delta("delete-column", {"operation": "delete-column", "column": "foo"})
    assert "df.drop(columns=['foo']" in delta.pandas_code


@patch("app.wrangle_operations.delete_column.table_columns", return_value=["ID", "foo", "bar"])
def test_delete_column_delta_creates_projected_view(mock_cols):
    conn = RecordingConnection()
    delta = Delta("delete-column", {"operation": "delete-column", "column": "foo"})
    created = delta.create_view(conn, object(), "n0_sales", "n0_sales_col_del")

    assert created is True
    assert conn.sql[-1] == (
        'CREATE VIEW "n0_sales_col_del" AS SELECT "ID", "bar" FROM "n0_sales"'
    )


@patch("app.wrangle_operations.delete_column.table_columns", return_value=["ID", "foo", "bar"])
def test_delete_column_operation_result(mock_cols):
    delta = Delta("delete-column", {"operation": "delete-column", "column": "foo"})
    meta = delta.operation_result(object(), "n0_sales")
    assert meta["remaining_columns"] == 2
    assert meta["deleted_column"] == "foo"


def test_promote_from_preview_creates_view_promotes_errors_and_drops_preview():
    conn = RecordingConnection()
    delta = Delta("delete", {"operation": "delete", "row_ids": [5]})

    with patch.object(delta, "create_view", return_value=True) as mock_create:
        promoted = delta.promote_from_preview(
            conn, object(), "n0_src", "n0_src_preview_delete", "n1_src"
        )

    assert promoted is True
    mock_create.assert_called_once()
    assert mock_create.call_args[0][2:] == ("n0_src", "n1_src")
    assert any('RENAME TO "errors_n1_src"' in s for s in conn.sql)
    assert any('DROP VIEW IF EXISTS "n0_src_preview_delete"' in s for s in conn.sql)


def test_unknown_operation_returns_safe_defaults():
    delta = Delta("nonexistent", {"operation": "nonexistent"})
    assert "# Unknown operation" in delta.pandas_code
    assert delta.create_view(RecordingConnection(), object(), "t", "v") is False
    assert delta.operation_result(object(), "t") == {}
