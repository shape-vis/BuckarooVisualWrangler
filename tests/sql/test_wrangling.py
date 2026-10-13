"""
Tests for the ID-based wrangles in app/db_utils/query.py.
"""
import pytest
import pandas as pd

from app import engine
from app.db_utils.execute_sql import execute_sql
from app.db_utils.query import remove_rows_by_ids, impute_by_ids

TABLES = ["test_remove", "errors_test_remove", "test_impute_num", "test_impute_cat", "test_impute_rule"]


@pytest.fixture(autouse=True, scope="module")
def drop_tables_afterwards():
    yield
    for table in TABLES:
        execute_sql(f'DROP TABLE IF EXISTS "{table}"', engine)


@pytest.mark.sql
def test_remove_rows_by_ids(db_transaction):
    """Removing rows by ID removes exactly those rows, flagged or not"""
    df = pd.DataFrame({'ID': range(1, 21), 'value': range(100, 300, 10)})
    df.to_sql('test_remove', engine, if_exists='replace', index=False)

    remaining = remove_rows_by_ids('test_remove', [1, 5, 10])
    assert remaining == 17


@pytest.mark.sql
def test_impute_by_ids_numeric(db_transaction):
    """Test imputing numeric values by ID"""
    df = pd.DataFrame({
        'ID': range(1, 21),
        'amount': [100 if i % 3 != 0 else None for i in range(1, 21)]
    })
    df.to_sql('test_impute_num', engine, if_exists='replace', index=False)

    rows_examined, cells_imputed = impute_by_ids('test_impute_num', 'amount', [3, 6, 9])
    assert rows_examined == 3
    assert cells_imputed == 3


@pytest.mark.sql
def test_impute_by_ids_categorical(db_transaction):
    """Test imputing categorical values by ID"""
    df = pd.DataFrame({
        'ID': range(1, 21),
        'category': ['A' if i % 4 != 0 else None for i in range(1, 21)]
    })
    df.to_sql('test_impute_cat', engine, if_exists='replace', index=False)

    rows_examined, cells_imputed = impute_by_ids('test_impute_cat', 'category', [4, 8])
    assert rows_examined == 2
    assert cells_imputed == 2


@pytest.mark.sql
def test_impute_learns_from_every_cell_the_detectors_do_not_call_missing():
    """
    The fill value is taken over the cells that aren't missing by the detectors' rule - null, or exactly "null" or
    "undefined" - so an empty string or "none" is a value like any other, as the pandas detectors had it.
    """
    df = pd.DataFrame({
        'ID': range(1, 9),
        'category': ['', '', '', 'none', 'null', 'null', 'undefined', None],
    })
    df.to_sql('test_impute_rule', engine, if_exists='replace', index=False)

    impute_by_ids('test_impute_rule', 'category', [5, 6, 7, 8])

    filled = pd.read_sql_query('SELECT category FROM "test_impute_rule" WHERE "ID" IN (5, 6, 7, 8)', engine)
    assert set(filled['category']) == {''}
