from typing import Any, Dict

from app.wrangle_operations.base import WrangleOperation
from app.wrangle_operations.sql_utils import (
    id_list,
    quote_identifier,
    quote_literal,
    recreate_view,
    table_columns,
)


class ImputeOperation(WrangleOperation):
    def pandas_code(self, parameters: Dict[str, Any]) -> str:
        col = parameters.get("col")
        row_ids = parameters.get("row_ids", [])
        if not col:
            return "# Impute operation missing column"

        return (
            f"if df['{col}'].dtype.kind in 'iufc':\n"
            f"    fill_val = df['{col}'].mean()\n"
            f"else:\n"
            f"    fill_val = df['{col}'].mode()[0] if not df['{col}'].mode().empty else None\n"
            f"df.loc[df['ID'].isin({row_ids}), '{col}'] = "
            f"df.loc[df['ID'].isin({row_ids}), '{col}'].fillna(fill_val)"
        )

    def create_view(self, conn, engine, source_table: str, target_view: str, parameters: Dict[str, Any]) -> bool:
        from app.db_utils.query import _compute_imputation_value, _is_numeric

        col = parameters.get("col")
        row_ids = parameters.get("row_ids", [])
        if not col or not row_ids:
            return False

        is_num = _is_numeric(conn, col, source_table)
        fill_val = _compute_imputation_value(conn, source_table, col, is_num)
        if fill_val is None:
            return False

        ids_sql = id_list(row_ids)
        fill_sql = str(fill_val) if is_num else quote_literal(fill_val)
        select_parts = []
        for column in table_columns(engine, source_table):
            quoted_column = quote_identifier(column)
            if column == col:
                existing_value_sql = f"{quoted_column}::numeric" if is_num else quoted_column
                select_parts.append(
                    f'CASE WHEN "ID" IN ({ids_sql}) THEN {fill_sql} ELSE {existing_value_sql} END AS {quoted_column}'
                )
            else:
                select_parts.append(quoted_column)

        source = quote_identifier(source_table)
        select_sql = f"SELECT {', '.join(select_parts)} FROM {source}"
        recreate_view(conn, target_view, select_sql)
        return True
