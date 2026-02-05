"""
Basic database tests for connection, operations, and PL/pgSQL functions.
"""
import pytest
import pandas as pd
from sqlalchemy import text


@pytest.mark.sql
def test_database_connection(db_connection):
    """Verify basic database connectivity"""
    result = db_connection.execute(text("SELECT 1 AS test"))
    assert result.scalar() == 1


@pytest.mark.sql
def test_database_name(db_connection, test_db_config):
    """Verify connected to test database"""
    result = db_connection.execute(text("SELECT current_database()"))
    assert result.scalar() == test_db_config["db_name"]


@pytest.mark.sql
def test_plpgsql_functions_loaded(db_connection):
    """Verify all custom PL/pgSQL functions are initialized"""
    functions = [
        'generate_one_d_histogram_with_errors',
        'generate_two_d_histogram_with_errors',
        'generate_scatterplot_with_errors'
    ]

    for func_name in functions:
        result = db_connection.execute(text("""
            SELECT COUNT(*) FROM pg_proc
            WHERE proname = :name
        """), {"name": func_name})
        assert result.scalar() > 0, f"PL/pgSQL function '{func_name}' not found"


@pytest.mark.sql
def test_create_table_from_dataframe(db_transaction):
    """Test creating table from pandas DataFrame"""
    df = pd.DataFrame({
        'id': [1, 2, 3],
        'name': ['Alice', 'Bob', 'Charlie'],
        'value': [10, 20, 30]
    })

    df.to_sql('test_table', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(text("SELECT COUNT(*) FROM test_table"))
    assert result.scalar() == 3


@pytest.mark.sql
def test_parameterized_query(db_transaction):
    """Test parameterized queries for SQL injection safety"""
    df = pd.DataFrame({
        'id': [1, 2, 3, 4],
        'category': ['A', 'B', 'A', 'C'],
        'amount': [100, 200, 150, 300]
    })
    df.to_sql('data', db_transaction, if_exists='replace', index=False)

    # Parameterized query
    result = db_transaction.execute(
        text("SELECT SUM(amount) FROM data WHERE category = :cat"),
        {"cat": "A"}
    )
    assert result.scalar() == 250  # 100 + 150


@pytest.mark.sql
def test_query_to_dataframe(db_transaction):
    """Test querying results back into pandas DataFrame"""
    df_original = pd.DataFrame({
        'id': [1, 2, 3],
        'value': [10, 20, 30]
    })
    df_original.to_sql('test_data', db_transaction, if_exists='replace', index=False)

    # Query back to DataFrame
    df_result = pd.read_sql_query(
        text("SELECT * FROM test_data WHERE value > 15"),
        db_transaction
    )

    assert len(df_result) == 2
    assert list(df_result['value']) == [20, 30]


@pytest.mark.sql
def test_update_operation(db_transaction):
    """Test UPDATE SQL operation"""
    df = pd.DataFrame({
        'id': [1, 2, 3],
        'status': ['pending', 'pending', 'completed']
    })
    df.to_sql('orders', db_transaction, if_exists='replace', index=False)

    # Update
    db_transaction.execute(
        text("UPDATE orders SET status = 'completed' WHERE id <= 2")
    )

    # Verify
    result = db_transaction.execute(
        text("SELECT COUNT(*) FROM orders WHERE status = 'completed'")
    )
    assert result.scalar() == 3


@pytest.mark.sql
def test_delete_operation(db_transaction):
    """Test DELETE SQL operation"""
    df = pd.DataFrame({'id': [1, 2, 3, 4, 5]})
    df.to_sql('items', db_transaction, if_exists='replace', index=False)

    # Delete
    db_transaction.execute(text("DELETE FROM items WHERE id > 3"))

    # Verify
    result = db_transaction.execute(text("SELECT COUNT(*) FROM items"))
    assert result.scalar() == 3


@pytest.mark.sql
def test_transaction_rollback(db_transaction):
    """Verify automatic rollback isolates tests"""
    df = pd.DataFrame({'id': [1], 'data': ['test']})
    df.to_sql('rollback_test', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(text("SELECT COUNT(*) FROM rollback_test"))
    assert result.scalar() == 1

    # This table will be rolled back after test


@pytest.mark.sql
def test_null_handling(db_transaction):
    """Test handling of NULL values"""
    df = pd.DataFrame({
        'id': [1, 2, 3],
        'value': [10, None, 30]
    })
    df.to_sql('null_test', db_transaction, if_exists='replace', index=False)

    # Query NULLs
    result = db_transaction.execute(
        text("SELECT COUNT(*) FROM null_test WHERE value IS NULL")
    )
    assert result.scalar() == 1
