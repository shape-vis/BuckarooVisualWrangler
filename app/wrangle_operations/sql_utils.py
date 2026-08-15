from sqlalchemy import inspect
from sqlalchemy import text as sa_text


def quote_identifier(name: str) -> str:
    """Quote a SQL table/column name safely for PostgreSQL."""
    return '"' + str(name).replace('"', '""') + '"'


def quote_literal(value) -> str:
    """Convert a Python value into a SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def id_list(row_ids) -> str:
    """Convert row IDs into a comma-separated SQL list."""
    return ", ".join(str(int(row_id)) for row_id in row_ids)


def table_columns(engine, table_name: str):
    """Ask SQLAlchemy for the current column order of a table/view."""
    inspector = inspect(engine)
    return [column["name"] for column in inspector.get_columns(table_name)]


def recreate_view(conn, target_view: str, select_sql: str) -> None:
    """Drop any old object with this name, then create the new SQL view."""
    target = quote_identifier(target_view)
    conn.execute(sa_text(f"DROP VIEW IF EXISTS {target} CASCADE"))
    conn.execute(sa_text(f"DROP TABLE IF EXISTS {target} CASCADE"))
    conn.execute(sa_text(f"CREATE VIEW {target} AS {select_sql}"))


def drop_view(conn, view_name: str) -> None:
    target = quote_identifier(view_name)
    conn.execute(sa_text(f"DROP VIEW IF EXISTS {target} CASCADE"))


def promote_errors_preview(conn, preview_table: str, new_table_name: str) -> None:
    """Rename errors_<preview> physical table to errors_<new_table_name>.

    A stale errors_<new_table_name> can be left behind by an earlier execute,
    an undo/redo that reused a node id, or a partially failed run. Renaming onto
    an existing relation raises DuplicateTable, which surfaces in the UI as the
    opaque "not able to execute" error, so we clear any leftover target first.
    """
    target = f"errors_{new_table_name}"
    # errors_<target> is always a physical table (built by the Pandas detectors
    # via to_sql and moved with ALTER TABLE), so a plain DROP TABLE is the right
    # clear. DROP VIEW IF EXISTS would raise WrongObjectType on a real table.
    conn.execute(sa_text(f'DROP TABLE IF EXISTS "{target}" CASCADE'))
    conn.execute(
        sa_text(f'ALTER TABLE "errors_{preview_table}" RENAME TO "{target}"')
    )
