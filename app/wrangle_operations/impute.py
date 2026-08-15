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
    """Fill selected missing values in one column."""

    def pandas_code(self, parameters: Dict[str, Any]) -> str:
        col = parameters.get("col")
        # Coerce to plain ints so the generated literal is a clean Python list.
        # Selections can carry NumPy integers, whose repr (e.g. np.int64(2))
        # would reference an unimported name and break the exported script.
        row_ids = [int(row_id) for row_id in parameters.get("row_ids", [])]
        if not col:
            return "# Impute operation missing column"

        return f"df = buckaroo_impute_missing_by_id(df, {row_ids!r}, {col!r})"

    def create_view(self, conn, engine, source_table: str, target_view: str, parameters: Dict[str, Any]) -> bool:
        from app.db_utils.query import _compute_imputation_value, _is_numeric

        col = parameters.get("col")
        row_ids = parameters.get("row_ids", [])
        if not col:
            return False
        if not row_ids:
            recreate_view(conn, target_view, f"SELECT * FROM {quote_identifier(source_table)}")
            return True

        # The SQL path mirrors the Pandas path: row_ids are the selected cells
        # that were flagged for this column, so replace them with one fill value.
        is_num = _is_numeric(conn, col, source_table)
        fill_val = _compute_imputation_value(conn, source_table, col, is_num)
        if fill_val is None:
            recreate_view(conn, target_view, f"SELECT * FROM {quote_identifier(source_table)}")
            return True

        ids_sql = id_list(row_ids) if row_ids else ""
        row_match_sql = f'"ID" IN ({ids_sql})' if ids_sql else "FALSE"
        fill_sql = str(fill_val) if is_num else quote_literal(fill_val)
        select_parts = []
        for column in table_columns(engine, source_table):
            quoted_column = quote_identifier(column)
            if column == col:
                # For numeric columns, both CASE branches must be numeric.
                # Without this cast, PostgreSQL may treat the fill value as
                # text and reject the view for bigint/float columns.
                existing_value_sql = f"{quoted_column}::numeric" if is_num else quoted_column
                select_parts.append(
                    f"CASE WHEN {row_match_sql} "
                    f"THEN {fill_sql} ELSE {existing_value_sql} END AS {quoted_column}"
                )
            else:
                select_parts.append(quoted_column)

        source = quote_identifier(source_table)
        select_sql = f"SELECT {', '.join(select_parts)} FROM {source}"
        recreate_view(conn, target_view, select_sql)
        return True
