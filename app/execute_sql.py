from sqlalchemy import text

def execute_sql(query: str, engine):
    """
    Executes given SQL query to the postgres database.
    """

    with engine.begin() as conn:
        conn.execute(text(query))

def fetch_sql(query: str, scalar: bool, engine):
    """
    Sends a SQL query to the postgres database.
    :arg: query: SQL query to execute.
    :scalar: whether the result from the query will just be 1 row, 1 col, so return as scalar.
    :return: The result from the query.
    """

    with engine.connect() as conn:
        result = conn.execute(text(query))

        if scalar:
            return result.scalar()

        if result.returns_rows:
            return result.fetchall()

        return None