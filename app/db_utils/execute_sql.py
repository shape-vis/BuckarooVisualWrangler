from sqlalchemy import text

"""
Thin wrapper around SQLAlchemy for executing and fetching results from a PostgreSQL database.
"""

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

