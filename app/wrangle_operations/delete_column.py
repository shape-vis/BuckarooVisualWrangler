from typing import Any, Dict

from app.wrangle_operations.base import WrangleOperation
from app.wrangle_operations.sql_utils import quote_identifier, recreate_view, table_columns


class DeleteColumnOperation(WrangleOperation):
    def pandas_code(self, parameters: Dict[str, Any]) -> str:
        column = parameters.get("column")
        return f"df.drop(columns=['{column}'], inplace=True)"

    def create_view(self, conn, engine, source_table: str, target_view: str, parameters: Dict[str, Any]) -> bool:
        column = parameters.get("column")
        if not column:
            return False

        columns = [name for name in table_columns(engine, source_table) if name != column]
        if not columns:
            return False

        select_list = ", ".join(quote_identifier(name) for name in columns)
        source = quote_identifier(source_table)
        recreate_view(conn, target_view, f"SELECT {select_list} FROM {source}")
        return True

    def operation_result(self, engine, source_table: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        column = parameters.get("column")
        if not column:
            return {}
        remaining = [name for name in table_columns(engine, source_table) if name != column]
        return {
            "remaining_columns": len(remaining),
            "deleted_column": column,
        }
