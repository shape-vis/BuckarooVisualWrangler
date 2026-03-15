"""
Tests for 1D histogram generation (generate_one_d_histogram_with_errors).
"""
import pytest
import pandas as pd
from sqlalchemy import text


@pytest.mark.sql
def test_1d_histogram_numeric(db_transaction):
    """Test 1D histogram for numeric column"""
    df = pd.DataFrame({'ID': range(1, 21), 'amount': range(100, 300, 10)})
    df.to_sql('test_numeric', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [1, 5, 10],
        'column_id': ['amount'] * 3,
        'error_type': ['missing', 'outlier', 'invalid']
    })
    error_df.to_sql('errors_test_numeric', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_one_d_histogram_with_errors(:table, :errors, :column, :bins, :min_id, :max_id)"),
        {"table": "test_numeric", "errors": "errors_test_numeric", "column": "amount", "bins": 5, "min_id": None, "max_id": None}
    )

    histogram = result.scalar()

    assert 'histograms' in histogram
    assert 'scaleX' in histogram
    assert len(histogram['histograms']) == 5
    assert sum(b['count']['items'] for b in histogram['histograms']) == 20


@pytest.mark.sql
def test_1d_histogram_categorical(db_transaction):
    """Test 1D histogram for categorical column"""
    df = pd.DataFrame({'ID': range(1, 21), 'category': ['A', 'B', 'C'] * 6 + ['A', 'B']})
    df.to_sql('test_categorical', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [1, 5, 10],
        'column_id': ['category'] * 3,
        'error_type': ['missing', 'invalid', 'missing']
    })
    error_df.to_sql('errors_test_categorical', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_one_d_histogram_with_errors(:table, :errors, :column, :bins, :min_id, :max_id)"),
        {"table": "test_categorical", "errors": "errors_test_categorical", "column": "category", "bins": 10, "min_id": None, "max_id": None}
    )

    histogram = result.scalar()

    assert 'histograms' in histogram
    assert 'scaleX' in histogram
    assert set(histogram['scaleX']['categorical']) == {'A', 'B', 'C'}
    assert sum(b['count']['items'] for b in histogram['histograms']) == 20


@pytest.mark.sql
def test_1d_histogram_with_id_filter(db_transaction):
    """Test ID range filtering"""
    df = pd.DataFrame({'ID': range(1, 51), 'value': range(1, 51)})
    df.to_sql('test_filter', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [5, 15, 25, 40],
        'column_id': ['value'] * 4,
        'error_type': ['missing'] * 4
    })
    error_df.to_sql('errors_test_filter', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_one_d_histogram_with_errors(:table, :errors, :column, :bins, :min_id, :max_id)"),
        {"table": "test_filter", "errors": "errors_test_filter", "column": "value", "bins": 4, "min_id": 10, "max_id": 30}
    )

    histogram = result.scalar()

    assert sum(b['count']['items'] for b in histogram['histograms']) == 21
    total_errors = sum(sum(b['count'].get(k, 0) for k in b['count'] if k != 'items') for b in histogram['histograms'])
    assert total_errors == 2


@pytest.mark.sql
def test_1d_histogram_error_categorization(db_transaction):
    """Test multiple error types in bins"""
    df = pd.DataFrame({'ID': range(1, 21), 'score': range(10, 210, 10)})
    df.to_sql('test_errors', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [1, 2, 5, 10, 15],
        'column_id': ['score'] * 5,
        'error_type': ['missing', 'missing', 'outlier', 'outlier', 'missing']
    })
    error_df.to_sql('errors_test_errors', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_one_d_histogram_with_errors(:table, :errors, :column, :bins, :min_id, :max_id)"),
        {"table": "test_errors", "errors": "errors_test_errors", "column": "score", "bins": 3, "min_id": None, "max_id": None}
    )

    histogram = result.scalar()

    total_missing = sum(b['count'].get('missing', 0) for b in histogram['histograms'])
    total_outlier = sum(b['count'].get('outlier', 0) for b in histogram['histograms'])
    assert total_missing == 3
    assert total_outlier == 2


@pytest.mark.sql
def test_1d_histogram_empty_data(db_transaction):
    """Test empty result set"""
    df = pd.DataFrame({'ID': range(1, 11), 'value': range(1, 11)})
    df.to_sql('test_empty', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': pd.Series(dtype='int64'),
        'column_id': pd.Series(dtype='str'),
        'error_type': pd.Series(dtype='str')
    })
    error_df.to_sql('errors_test_empty', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_one_d_histogram_with_errors(:table, :errors, :column, :bins, :min_id, :max_id)"),
        {"table": "test_empty", "errors": "errors_test_empty", "column": "value", "bins": 5, "min_id": 100, "max_id": 200}
    )

    histogram = result.scalar()

    assert 'histograms' in histogram
    assert 'scaleX' in histogram


# @pytest.mark.sql
# def test_1d_histogram_single_value(db_transaction):
#     """Test all rows with same value"""
#     df = pd.DataFrame({'ID': range(1, 21), 'constant': [42] * 20})
#     df.to_sql('test_single', db_transaction, if_exists='replace', index=False)
#
#     error_df = pd.DataFrame({
#         'row_id': [1, 5, 10],
#         'column_id': ['constant'] * 3,
#         'error_type': ['missing'] * 3
#     })
#     error_df.to_sql('errors_test_single', db_transaction, if_exists='replace', index=False)
#
#     result = db_transaction.execute(
#         text("SELECT generate_one_d_histogram_with_errors(:table, :errors, :column, :bins, :min_id, :max_id)"),
#         {"table": "test_single", "errors": "errors_test_single", "column": "constant", "bins": 5, "min_id": None, "max_id": None}
#     )
#
#     histogram = result.scalar()
#
#     assert 'histograms' in histogram
#     assert sum(b['count']['items'] for b in histogram['histograms']) == 20


# @pytest.mark.sql
# def test_1d_histogram_with_nulls(db_transaction):
#     """Test NULL value handling"""
#     df = pd.DataFrame({
#         'ID': range(1, 21),
#         'nullable': [i if i % 5 != 0 else None for i in range(1, 21)]
#     })
#     df.to_sql('test_nulls', db_transaction, if_exists='replace', index=False)
#
#     error_df = pd.DataFrame({
#         'row_id': [1, 7],
#         'column_id': ['nullable'] * 2,
#         'error_type': ['missing'] * 2
#     })
#     error_df.to_sql('errors_test_nulls', db_transaction, if_exists='replace', index=False)
#
#     result = db_transaction.execute(
#         text("SELECT generate_one_d_histogram_with_errors(:table, :errors, :column, :bins, :min_id, :max_id)"),
#         {"table": "test_nulls", "errors": "errors_test_nulls", "column": "nullable", "bins": 4, "min_id": None, "max_id": None}
#     )
#
#     histogram = result.scalar()
#
#     assert 'histograms' in histogram
#     assert sum(b['count']['items'] for b in histogram['histograms']) == 20


@pytest.mark.sql
def test_1d_histogram_numeric_exact_response(db_transaction):
    """Golden test: exact JSON response for numeric 1D histogram"""
    df = pd.DataFrame({'ID': [1, 2, 3, 4], 'value': [10, 20, 30, 40]})
    df.to_sql('test_golden_1d_num', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [1],
        'column_id': ['value'],
        'error_type': ['missing']
    })
    error_df.to_sql('errors_test_golden_1d_num', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_one_d_histogram_with_errors(:table, :errors, :column, :bins, :min_id, :max_id)"),
        {"table": "test_golden_1d_num", "errors": "errors_test_golden_1d_num", "column": "value", "bins": 2, "min_id": None, "max_id": None}
    )

    histogram = result.scalar()

    # Exact expected JSON (validated against frontend contract)
    expected = {
        'histograms': [
            {
                'xBin': '0',
                'xType': 'numeric',
                'count': {
                    'items': 2,
                    'missing': 1
                }
            },
            {
                'xBin': '1',
                'xType': 'numeric',
                'count': {
                    'items': 2
                }
            }
        ],
        'scaleX': {
            'numeric': [
                {'x0': 10.0, 'x1': 25.0},
                {'x0': 25.0, 'x1': 40.0}
            ],
            'categorical': []
        }
    }

    assert histogram == expected, f"Expected: {expected}\nGot: {histogram}"


@pytest.mark.sql
def test_1d_histogram_categorical_exact_response(db_transaction):
    """Golden test: exact JSON response for categorical 1D histogram"""
    df = pd.DataFrame({'ID': [1, 2, 3, 4], 'category': ['A', 'A', 'B', 'B']})
    df.to_sql('test_golden_1d_cat', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [1],
        'column_id': ['category'],
        'error_type': ['invalid']
    })
    error_df.to_sql('errors_test_golden_1d_cat', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_one_d_histogram_with_errors(:table, :errors, :column, :bins, :min_id, :max_id)"),
        {"table": "test_golden_1d_cat", "errors": "errors_test_golden_1d_cat", "column": "category", "bins": 10, "min_id": None, "max_id": None}
    )

    histogram = result.scalar()

    # Exact expected JSON (validated against frontend contract)
    expected = {
        'histograms': [
            {
                'xBin': 'A',
                'xType': 'categorical',
                'count': {
                    'items': 2,
                    'invalid': 1
                }
            },
            {
                'xBin': 'B',
                'xType': 'categorical',
                'count': {
                    'items': 2
                }
            }
        ],
        'scaleX': {
            'numeric': [],
            'categorical': ['A', 'B']
        }
    }

    assert histogram == expected, f"Expected: {expected}\nGot: {histogram}"
