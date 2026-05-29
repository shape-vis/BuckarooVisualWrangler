from sqlalchemy import inspect
from sqlalchemy import text as sa_text


def quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def quote_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def id_list(row_ids) -> str:
    return ", ".join(str(int(row_id)) for row_id in row_ids)


def table_columns(engine, table_name: str):
    inspector = inspect(engine)
    return [column["name"] for column in inspector.get_columns(table_name)]


def recreate_view(conn, target_view: str, select_sql: str) -> None:
    target = quote_identifier(target_view)
    conn.execute(sa_text(f"DROP VIEW IF EXISTS {target} CASCADE"))
    conn.execute(sa_text(f"DROP TABLE IF EXISTS {target} CASCADE"))
    conn.execute(sa_text(f"CREATE VIEW {target} AS {select_sql}"))


def drop_view(conn, view_name: str) -> None:
    target = quote_identifier(view_name)
    conn.execute(sa_text(f"DROP VIEW IF EXISTS {target} CASCADE"))


def promote_errors_preview(conn, preview_table: str, new_table_name: str) -> None:
    """Rename errors_<preview> physical table to errors_<new_table_name>."""
    conn.execute(
        sa_text(f'ALTER TABLE "errors_{preview_table}" RENAME TO "errors_{new_table_name}"')
    )
