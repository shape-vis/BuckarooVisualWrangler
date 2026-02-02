"""
Example tests demonstrating the SQL testing framework.

These tests show how to use the fixtures and test patterns.
"""
import pytest
import pandas as pd
from sqlalchemy import text


@pytest.mark.sql
def test_database_connection_works(db_connection):
    """Verify basic database connectivity"""
    result = db_connection.execute(text("SELECT 1 AS test"))
    assert result.scalar() == 1


@pytest.mark.sql
def test_plpgsql_functions_loaded(db_connection):
    """Verify custom PL/pgSQL functions are initialized"""
    result = db_connection.execute(text("""
        SELECT COUNT(*)
        FROM pg_proc
        WHERE proname = 'generate_one_d_histogram_with_errors'
    """))
    assert result.scalar() > 0, "PL/pgSQL function not found"


@pytest.mark.sql
def test_create_table_with_pandas(db_transaction):
    """Example: Create table from DataFrame using db_transaction (auto-rollback)"""
    # Create a simple test DataFrame
    df = pd.DataFrame({
        'id': [1, 2, 3, 4, 5],
        'name': ['Alice', 'Bob', 'Charlie', 'Diana', 'Eve'],
        'age': [25, 30, 35, 28, 42],
        'city': ['NYC', 'LA', 'Chicago', 'Houston', 'Phoenix']
    })

    # Create table (note: no index column)
    df.to_sql('users', db_transaction, if_exists='replace', index=False)

    # Query the table
    result = db_transaction.execute(text("SELECT COUNT(*) FROM users"))
    assert result.scalar() == 5

    # Query with filter
    result = db_transaction.execute(
        text("SELECT name FROM users WHERE age > :min_age ORDER BY age"),
        {"min_age": 30}
    )
    names = [row[0] for row in result]
    assert names == ['Charlie', 'Eve']

    # Table will be automatically rolled back after test


@pytest.mark.sql
def test_parameterized_queries(db_transaction):
    """Example: Using parameterized queries for safety"""
    # Create test data
    df = pd.DataFrame({
        'product_id': [1, 2, 3],
        'product_name': ['Laptop', 'Mouse', 'Keyboard'],
        'price': [999.99, 25.50, 79.99],
        'in_stock': [True, True, False]
    })
    df.to_sql('products', db_transaction, if_exists='replace', index=False)

    # Parameterized query (safe from SQL injection)
    result = db_transaction.execute(
        text("SELECT product_name, price FROM products WHERE price < :max_price ORDER BY price DESC"),
        {"max_price": 100.0}
    )

    products = result.fetchall()
    assert len(products) == 2
    assert products[0][0] == 'Keyboard'  # Most expensive under $100
    assert products[1][0] == 'Mouse'


@pytest.mark.sql
def test_pandas_read_sql(db_transaction):
    """Example: Query results back into pandas DataFrame"""
    # Create test data
    df_original = pd.DataFrame({
        'employee_id': [101, 102, 103, 104],
        'department': ['Engineering', 'Sales', 'Engineering', 'HR'],
        'salary': [80000, 65000, 95000, 70000]
    })
    df_original.to_sql('employees', db_transaction, if_exists='replace', index=False)

    # Query back into DataFrame
    df_result = pd.read_sql_query(
        text("SELECT department, AVG(salary) as avg_salary FROM employees GROUP BY department"),
        db_transaction
    )

    # Verify results
    assert len(df_result) == 3
    engineering_avg = df_result[df_result['department'] == 'Engineering']['avg_salary'].iloc[0]
    assert engineering_avg == 87500.0  # (80000 + 95000) / 2


@pytest.mark.sql
def test_multiple_operations_in_transaction(db_transaction):
    """Example: Multiple operations with automatic rollback"""
    # Create initial table
    df = pd.DataFrame({'id': [1, 2, 3], 'value': [10, 20, 30]})
    df.to_sql('data', db_transaction, if_exists='replace', index=False)

    # Update some rows
    db_transaction.execute(
        text("UPDATE data SET value = value * 2 WHERE id IN (1, 3)")
    )

    # Insert new row
    db_transaction.execute(
        text("INSERT INTO data (id, value) VALUES (:id, :val)"),
        {"id": 4, "val": 40}
    )

    # Delete a row
    db_transaction.execute(text("DELETE FROM data WHERE id = 2"))

    # Verify final state
    result = db_transaction.execute(text("SELECT id, value FROM data ORDER BY id"))
    rows = result.fetchall()

    assert len(rows) == 3
    assert rows[0] == (1, 20)  # Doubled
    assert rows[1] == (3, 60)  # Doubled
    assert rows[2] == (4, 40)  # New row

    # All changes will be rolled back after test!


@pytest.mark.sql
def test_using_db_connection_with_commit(db_connection):
    """Example: Using db_connection when you need to test commits"""
    # Create table
    df = pd.DataFrame({'id': [1], 'status': ['pending']})
    df.to_sql('orders', db_connection, if_exists='replace', index=False)

    # Make changes and commit
    trans = db_connection.begin()
    db_connection.execute(
        text("UPDATE orders SET status = 'completed' WHERE id = 1")
    )
    trans.commit()

    # Verify the commit worked
    result = db_connection.execute(
        text("SELECT status FROM orders WHERE id = 1")
    )
    assert result.scalar() == 'completed'

    # Manual cleanup
    db_connection.execute(text("DROP TABLE orders"))


@pytest.mark.sql
def test_with_null_values(db_transaction):
    """Example: Handling NULL values"""
    # Create table with NULLs
    df = pd.DataFrame({
        'id': [1, 2, 3, 4],
        'email': ['alice@example.com', None, 'charlie@example.com', None],
        'phone': ['555-1234', '555-5678', None, None]
    })
    df.to_sql('contacts', db_transaction, if_exists='replace', index=False)

    # Query for rows with missing data
    result = db_transaction.execute(text("""
        SELECT id FROM contacts
        WHERE email IS NULL OR phone IS NULL
        ORDER BY id
    """))

    missing_data_ids = [row[0] for row in result]
    assert missing_data_ids == [2, 3, 4]


@pytest.mark.sql
@pytest.mark.slow
def test_large_dataset(db_transaction):
    """Example: Testing with larger datasets (marked as slow)"""
    # Generate larger test dataset
    import random

    data = {
        'id': range(1, 1001),
        'value': [random.randint(1, 100) for _ in range(1000)],
        'category': [random.choice(['A', 'B', 'C']) for _ in range(1000)]
    }
    df = pd.DataFrame(data)
    df.to_sql('large_table', db_transaction, if_exists='replace', index=False)

    # Test aggregation on large dataset
    result = db_transaction.execute(text("""
        SELECT category, COUNT(*), AVG(value), MAX(value), MIN(value)
        FROM large_table
        GROUP BY category
        ORDER BY category
    """))

    stats = result.fetchall()
    assert len(stats) == 3  # A, B, C

    # Verify all rows accounted for
    total_count = sum(row[1] for row in stats)
    assert total_count == 1000
