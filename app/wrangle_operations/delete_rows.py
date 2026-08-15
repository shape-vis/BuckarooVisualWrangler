from typing import Any, Dict

from app.wrangle_operations.base import WrangleOperation
from app.wrangle_operations.sql_utils import id_list, quote_identifier, recreate_view


class DeleteRowsOperation(WrangleOperation):
    """Delete selected row IDs from both the SQL view and exported Pandas script."""

    def pandas_code(self, parameters: Dict[str, Any]) -> str:
        # Coerce to plain ints so the generated literal is a clean Python list.
        # Selections can carry NumPy integers, whose repr (e.g. np.int64(2))
        # would reference an unimported name and break the exported script.
        row_ids = [int(row_id) for row_id in parameters.get("row_ids", [])]
        return f"df = buckaroo_delete_rows_by_id(df, {row_ids!r})"

    def create_view(self, conn, engine, source_table: str, target_view: str, parameters: Dict[str, Any]) -> bool:
        row_ids = parameters.get("row_ids", [])
        if not row_ids:
            return False

        # The SQL view is the database equivalent of the Pandas filter above.
        source = quote_identifier(source_table)
        ids_sql = id_list(row_ids)
        recreate_view(
            conn,
            target_view,
            f'SELECT * FROM {source} WHERE "ID" NOT IN ({ids_sql})',
        )
        return True
