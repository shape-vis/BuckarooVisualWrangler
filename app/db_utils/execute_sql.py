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

def copy_table_to_csv(table_name: str, csv_file_path: str, engine):
    """
    Copies the contents of a PostgreSQL table to a CSV file.
    :arg: table_name: name of the table to copy.
    :arg: csv_file_path: path to the CSV file to write to.
    """
    print("table_name", table_name)
    print("csv_file_path", csv_file_path)
    query = f'COPY "{table_name}" TO STDOUT WITH CSV HEADER'
    with engine.raw_connection() as conn:
        with open(csv_file_path, 'w') as f:
            cursor = conn.cursor()
            cursor.copy_expert(query, f)
            cursor.close()