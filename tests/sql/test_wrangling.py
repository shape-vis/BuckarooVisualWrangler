"""
Tests for data wrangling operations (postgres_wrangling.query module).
"""
import pytest
import pandas as pd
from app.db_utils.query import (
    remove_rows_by_ids,
    impute_by_ids,
    remove_flagged_rows_in_1d_bin,
    impute_1d_bin_in_place,
    remove_flagged_rows_in_bin,
    impute_bin_in_place
)


@pytest.mark.sql
def test_remove_rows_by_ids(db_transaction):
    """Test removing rows by ID list"""
    from app import engine

    df = pd.DataFrame({'ID': range(1, 21), 'value': range(100, 300, 10)})
    df.to_sql('test_remove', engine, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [1, 5, 10],
        'column_id': ['value'] * 3,
        'error_type': ['missing', 'outlier', 'invalid']
    })
    error_df.to_sql('errors_test_remove', engine, if_exists='replace', index=False)

    remaining = remove_rows_by_ids('test_remove', [1, 5, 10])
    assert remaining == 17


@pytest.mark.sql
def test_impute_by_ids_numeric(db_transaction):
    """Test imputing numeric values by ID"""
    from app import engine

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
    from app import engine

    df = pd.DataFrame({
        'ID': range(1, 21),
        'category': ['A' if i % 4 != 0 else None for i in range(1, 21)]
    })
    df.to_sql('test_impute_cat', engine, if_exists='replace', index=False)

    rows_examined, cells_imputed = impute_by_ids('test_impute_cat', 'category', [4, 8])
    assert rows_examined == 2
    assert cells_imputed == 2


@pytest.mark.sql
def test_remove_flagged_rows_in_1d_bin(db_transaction):
    """Test removing flagged rows in 1D bin"""
    from app import engine

    df = pd.DataFrame({'ID': range(1, 21), 'amount': range(100, 300, 10)})
    df.to_sql('test_1d_remove', engine, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [5, 10, 15],
        'column_id': ['amount'] * 3,
        'error_type': ['missing', 'outlier', 'invalid']
    })
    error_df.to_sql('errors_test_1d_remove', engine, if_exists='replace', index=False)

    selection = {
        'data': [{'bin': 1, 'type': 'numeric'}],
        'scaleX': {'numeric': [{'x0': 100, 'x1': 150}, {'x0': 150, 'x1': 200}]}
    }

    remaining = remove_flagged_rows_in_1d_bin(selection, 'amount', 'test_1d_remove')
    # Bin 1 = [150, 200]: only ID 10 (amount=190) has an error → 19 remaining
    assert remaining == 19


@pytest.mark.sql
def test_impute_1d_bin_numeric(db_transaction):
    """Test imputing values in 1D bin"""
    from app import engine

    df = pd.DataFrame({
        'ID': range(1, 21),
        'amount': [i * 10 if i % 4 != 0 else None for i in range(1, 21)]
    })
    df.to_sql('test_1d_impute', engine, if_exists='replace', index=False)

    selection = {
        'data': [{'bin': 0, 'type': 'numeric'}],
        'scaleX': {'numeric': [{'x0': 0, 'x1': 50}, {'x0': 50, 'x1': 100}]}
    }

    rows_examined, cells_imputed = impute_1d_bin_in_place(selection, 'amount', 'test_1d_impute')
    # bin=0 maps to scale[0] = [x0=0, x1=50]; rows with amount in [0,50]: IDs 1,2,3,5 (amounts 10,20,30,50) = 4 rows
    # NULLs can't satisfy a numeric range comparison so cells_imputed = 0
    assert rows_examined == 4
    assert cells_imputed == 0


@pytest.mark.sql
def test_remove_flagged_rows_in_2d_bin(db_transaction):
    """Test removing flagged rows in 2D bin"""
    from app import engine

    df = pd.DataFrame({
        'ID': range(1, 21),
        'amount': range(100, 300, 10),
        'category': ['A', 'B', 'C'] * 6 + ['A', 'B']
    })
    df.to_sql('test_2d_remove', engine, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [5, 10, 15],
        'column_id': ['amount', 'category', 'amount'],
        'error_type': ['missing', 'invalid', 'outlier']
    })
    error_df.to_sql('errors_test_2d_remove', engine, if_exists='replace', index=False)

    selection = {
        'data': [{'xBin': 1, 'yBin': 'A', 'xType': 'numeric', 'yType': 'categorical'}],
        'scaleX': {'numeric': [{'x0': 100, 'x1': 150}, {'x0': 150, 'x1': 200}]},
        'scaleY': {'categorical': ['A', 'B', 'C']}
    }

    remaining = remove_flagged_rows_in_bin(selection, ['amount', 'category'], 'test_2d_remove')
    # xBin=1=[150,200] AND yBin='A': only ID 10 (amount=190, category=A) has an error → 19 remaining
    assert remaining == 19


@pytest.mark.sql
def test_impute_2d_bin(db_transaction):
    """Test imputing values in 2D bin"""
    from app import engine

    df = pd.DataFrame({
        'ID': range(1, 21),
        'amount': [i * 10 if i % 3 != 0 else None for i in range(1, 21)],
        'category': ['A' if i % 5 != 0 else None for i in range(1, 21)]
    })
    df.to_sql('test_2d_impute', engine, if_exists='replace', index=False)

    selection = {
        'data': [{'xBin': 0, 'yBin': 'A', 'xType': 'numeric', 'yType': 'categorical'}],
        'scaleX': {'numeric': [{'x0': 0, 'x1': 100}, {'x0': 100, 'x1': 200}]},
        'scaleY': {'categorical': ['A', 'B', 'C']}
    }

    rows_examined, cells_imputed = impute_bin_in_place(selection, ['amount', 'category'], 'test_2d_impute')
    # xBin=0 (NULL bucket for amount) AND yBin='A': 5 rows where amount IS NULL AND category='A'
    # Imputing amount for those 5 rows; category imputation finds 0 (NULL category fails category='A' filter)
    assert rows_examined == 5
    assert cells_imputed == 5
