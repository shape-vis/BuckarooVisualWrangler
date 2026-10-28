"""
Makes sure the app's database exists before the SQLAlchemy engine connects to it. This runs once, at startup, on a
plain psycopg2 connection to the server, since the engine cannot connect to a database that isn't there yet.
"""

from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT


def create_database_if_not_exists(conn, db_name: str):
    """
    Create the database unless the server already has one of that name.
    :arg: conn: a psycopg2 connection to the server.
    :arg: db_name: name of the database.
    """

    # CREATE DATABASE cannot run inside a transaction
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()

    cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
    exists = cursor.fetchone()

    if not exists:
        cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))

    cursor.close()
