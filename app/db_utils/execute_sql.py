"""
Thin wrapper around SQLAlchemy for executing and fetching results from a PostgreSQL database.
Also the small helpers the query builders in db_utils share: naming a node's companion tables, quoting names into SQL,
and bulk-loading a DataFrame through COPY.
"""

import csv
import io

from sqlalchemy import text
from sqlalchemy import types as sql_types


def execute_sql(query: str, engine):
    """
    Executes given SQL query to the postgres database.
    """

    with engine.begin() as conn:
        conn.execute(text(query))

def fetch_sql(query: str, scalar: bool, engine, params=None):
    """
    Sends a SQL query to the postgres database.
    :arg: query: SQL query to execute.
    :scalar: whether the result from the query will just be 1 row, 1 col, so return as scalar.
    :return: The result from the query.
    """
    if params is None:
        params = {}

    with engine.connect() as conn:
        result = conn.execute(text(query), params)

        if scalar:
            return result.scalar()

        if result.returns_rows:
            return result.fetchall()

        return None


# The tables every node's table has beside it, each named by a prefix on the node's table name
ERRORS_PREFIX = "errors_"
PROFILE_PREFIX = "dp_"
COMPANION_PREFIXES = (ERRORS_PREFIX, PROFILE_PREFIX)


def errors_table_name(table_name: str) -> str:
    """The table holding a node table's error flags, one row per flagged cell: (row_id, column_id, error_type)."""
    return ERRORS_PREFIX + table_name


def profile_table_name(table_name: str) -> str:
    """The table holding a node table's data profile, one row per column."""
    return PROFILE_PREFIX + table_name


def node_table_names(table_name: str) -> list:
    """A node's table followed by every companion table - the set dropped together."""
    names = [table_name]
    for prefix in COMPANION_PREFIXES:
        names.append(prefix + table_name)
    return names


def sql_identifier(name: str) -> str:
    """A table or column name double-quoted as Postgres reads it, with any quote inside it doubled."""
    return '"' + name.replace('"', '""') + '"'


def quote_identifier(name: str) -> str:
    """
    Double-quotes a table or column name for a query run through text(), escaping the quotes and colons inside it.
    A colon has to be escaped because text() would otherwise read ":name" as a bind parameter.
    :arg: name: the table or column name.
    :return: the name, quoted.
    """

    return sql_identifier(name).replace(":", "\\:")


def quote_literal(value: str) -> str:
    """
    Single-quotes a string literal for a query run through text(), such as a column name compared against the
    errors table's column_id. Quotes and colons inside it are escaped as quote_identifier escapes them.
    :arg: value: the string.
    :return: the string as a SQL literal.
    """

    return "'" + value.replace("'", "''").replace(":", "\\:") + "'"


# COPY's marker for a null field. Written unquoted, so a real empty string stays an empty string.
_COPY_NULL = r"\N"


def copy_insert(table, conn, keys, data_iter):
    """
    pandas' to_sql insertion method for Postgres' COPY - the one in pandas' own documentation - which loads a
    table in one stream instead of one INSERT per row.
    Usage: dataframe.to_sql(name, engine, method=copy_insert).
    :arg: table: pandas' SQLTable being written.
    :arg: conn: the SQLAlchemy connection pandas opened.
    :arg: keys: the column names, in order.
    :arg: data_iter: the rows, nulls already None.
    """

    # A float column whose values are all whole numbers is stored as an integer column. An INSERT lets Postgres
    # round 70841.0 into it, but COPY reads the text "70841.0" and refuses it, so those values are written as
    # integers.
    integer_columns = set()
    for column in table.table.columns:
        if isinstance(column.type, sql_types.Integer):
            integer_columns.add(column.name)

    # The rows, written out as CSV with nulls marked
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in data_iter:
        fields = []
        for key, value in zip(keys, row):
            if value is None:
                fields.append(_COPY_NULL)
            elif key in integer_columns and isinstance(value, float):
                fields.append(int(value))
            else:
                fields.append(value)
        writer.writerow(fields)
    buffer.seek(0)

    # COPY goes straight to the driver rather than through text(), so names are quoted without its escapes
    target = sql_identifier(table.name)
    if table.schema:
        target = sql_identifier(table.schema) + "." + target

    quoted_columns = []
    for key in keys:
        quoted_columns.append(sql_identifier(key))
    column_list = ", ".join(quoted_columns)

    copy_statement = f"COPY {target} ({column_list}) FROM STDIN WITH (FORMAT csv, NULL '{_COPY_NULL}')"
    with conn.connection.cursor() as cursor:
        cursor.copy_expert(copy_statement, buffer)
