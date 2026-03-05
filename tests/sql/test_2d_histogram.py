"""
Tests for 2D histogram generation (generate_two_d_histogram_with_errors).
"""
import pytest
import pandas as pd
from sqlalchemy import text


@pytest.mark.sql
def test_2d_histogram_numeric_numeric(db_transaction):
    """Test 2D histogram for two numeric columns"""
    df = pd.DataFrame({
        'ID': range(1, 21),
        'temperature': range(100, 300, 10),
        'humidity': range(10, 210, 10)
    })
    df.to_sql('test_2d_nn', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [1, 5, 10],
        'column_id': ['temperature', 'humidity', 'temperature'],
        'error_type': ['missing', 'outlier', 'invalid']
    })
    error_df.to_sql('errors_test_2d_nn', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_two_d_histogram_with_errors(:table, :errors, :x_col, :y_col, :x_bins, :y_bins, :min_id, :max_id)"),
        {"table": "test_2d_nn", "errors": "errors_test_2d_nn", "x_col": "temperature", "y_col": "humidity", "x_bins": 5, "y_bins": 5, "min_id": None, "max_id": None}
    )

    histogram = result.scalar()

    assert 'histograms' in histogram
    assert 'scaleX' in histogram
    assert 'scaleY' in histogram
    assert len(histogram['scaleX']['numeric']) == 5
    assert len(histogram['scaleY']['numeric']) == 5


@pytest.mark.sql
def test_2d_histogram_numeric_categorical(db_transaction):
    """Test 2D histogram for numeric and categorical columns"""
    df = pd.DataFrame({
        'ID': range(1, 21),
        'age': range(20, 120, 5),
        'grade': ['A', 'B', 'C'] * 6 + ['A', 'B']
    })
    df.to_sql('test_2d_nc', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [2, 7],
        'column_id': ['age', 'grade'],
        'error_type': ['missing', 'invalid']
    })
    error_df.to_sql('errors_test_2d_nc', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_two_d_histogram_with_errors(:table, :errors, :x_col, :y_col, :x_bins, :y_bins, :min_id, :max_id)"),
        {"table": "test_2d_nc", "errors": "errors_test_2d_nc", "x_col": "age", "y_col": "grade", "x_bins": 4, "y_bins": 10, "min_id": None, "max_id": None}
    )

    histogram = result.scalar()

    assert 'histograms' in histogram
    assert len(histogram['scaleX']['numeric']) == 4
    assert set(histogram['scaleY']['categorical']) == {'A', 'B', 'C'}


@pytest.mark.sql
def test_2d_histogram_categorical_categorical(db_transaction):
    """Test 2D histogram for two categorical columns"""
    df = pd.DataFrame({
        'ID': range(1, 21),
        'color': ['Red', 'Blue'] * 10,
        'size': ['S', 'M', 'L'] * 6 + ['S', 'M']
    })
    df.to_sql('test_2d_cc', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [1, 10, 15],
        'column_id': ['color', 'size', 'color'],
        'error_type': ['missing', 'invalid', 'missing']
    })
    error_df.to_sql('errors_test_2d_cc', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_two_d_histogram_with_errors(:table, :errors, :x_col, :y_col, :x_bins, :y_bins, :min_id, :max_id)"),
        {"table": "test_2d_cc", "errors": "errors_test_2d_cc", "x_col": "color", "y_col": "size", "x_bins": 10, "y_bins": 10, "min_id": None, "max_id": None}
    )

    histogram = result.scalar()

    assert 'histograms' in histogram
    assert set(histogram['scaleX']['categorical']) == {'Red', 'Blue'}
    assert set(histogram['scaleY']['categorical']) == {'S', 'M', 'L'}


@pytest.mark.sql
def test_2d_histogram_with_id_filter(db_transaction):
    """Test 2D histogram with ID range filtering"""
    df = pd.DataFrame({
        'ID': range(1, 51),
        'x_val': range(1, 51),
        'y_val': range(100, 150)
    })
    df.to_sql('test_2d_filter', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [5, 15, 25, 40],
        'column_id': ['x_val'] * 4,
        'error_type': ['missing'] * 4
    })
    error_df.to_sql('errors_test_2d_filter', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_two_d_histogram_with_errors(:table, :errors, :x_col, :y_col, :x_bins, :y_bins, :min_id, :max_id)"),
        {"table": "test_2d_filter", "errors": "errors_test_2d_filter", "x_col": "x_val", "y_col": "y_val", "x_bins": 4, "y_bins": 4, "min_id": 10, "max_id": 30}
    )

    histogram = result.scalar()

    total_items = sum(bin['count']['items'] for bin in histogram['histograms'])
    assert total_items == 21


@pytest.mark.sql
def test_2d_histogram_error_distribution(db_transaction):
    """Test error distribution across bins"""
    df = pd.DataFrame({
        'ID': range(1, 21),
        'x': range(10, 210, 10),
        'y': range(20, 220, 10)
    })
    df.to_sql('test_2d_errors', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [1, 2, 5, 10, 15],
        'column_id': ['x', 'x', 'y', 'x', 'y'],
        'error_type': ['missing', 'missing', 'outlier', 'outlier', 'missing']
    })
    error_df.to_sql('errors_test_2d_errors', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_two_d_histogram_with_errors(:table, :errors, :x_col, :y_col, :x_bins, :y_bins, :min_id, :max_id)"),
        {"table": "test_2d_errors", "errors": "errors_test_2d_errors", "x_col": "x", "y_col": "y", "x_bins": 3, "y_bins": 3, "min_id": None, "max_id": None}
    )

    histogram = result.scalar()

    total_missing = sum(bin['count'].get('missing', 0) for bin in histogram['histograms'])
    total_outlier = sum(bin['count'].get('outlier', 0) for bin in histogram['histograms'])
    assert total_missing == 3
    assert total_outlier == 2


@pytest.mark.sql
def test_2d_histogram_numeric_numeric_exact(db_transaction):
    """Golden test: exact JSON response for numeric×numeric 2D histogram"""
    df = pd.DataFrame({
        'ID': [1, 2, 3, 4],
        'x': [10, 20, 30, 40],
        'y': [100, 200, 300, 400]
    })
    df.to_sql('test_golden_2d_nn', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [1],
        'column_id': ['x'],
        'error_type': ['missing']
    })
    error_df.to_sql('errors_test_golden_2d_nn', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_two_d_histogram_with_errors(:table, :errors, :x_col, :y_col, :x_bins, :y_bins, :min_id, :max_id)"),
        {"table": "test_golden_2d_nn", "errors": "errors_test_golden_2d_nn", "x_col": "x", "y_col": "y", "x_bins": 2, "y_bins": 2, "min_id": None, "max_id": None}
    )

    histogram = result.scalar()

    # Exact expected JSON (validated against frontend contract)
    expected = {
        'histograms': [
            {
                'xBin': '0',
                'yBin': '0',
                'xType': 'numeric',
                'yType': 'numeric',
                'count': {
                    'items': 2,
                    'missing': 1
                }
            },
            {
                'xBin': '1',
                'yBin': '1',
                'xType': 'numeric',
                'yType': 'numeric',
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
        },
        'scaleY': {
            'numeric': [
                {'x0': 100.0, 'x1': 250.0},
                {'x0': 250.0, 'x1': 400.0}
            ],
            'categorical': []
        }
    }

    assert histogram == expected, f"Expected: {expected}\nGot: {histogram}"


@pytest.mark.sql
def test_2d_histogram_numeric_categorical_exact(db_transaction):
    """Golden test: exact JSON response for numeric×categorical 2D histogram"""
    df = pd.DataFrame({
        'ID': [1, 2, 3, 4],
        'age': [20, 30, 40, 50],
        'grade': ['A', 'A', 'B', 'B']
    })
    df.to_sql('test_golden_2d_nc', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [2],
        'column_id': ['grade'],
        'error_type': ['invalid']
    })
    error_df.to_sql('errors_test_golden_2d_nc', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_two_d_histogram_with_errors(:table, :errors, :x_col, :y_col, :x_bins, :y_bins, :min_id, :max_id)"),
        {"table": "test_golden_2d_nc", "errors": "errors_test_golden_2d_nc", "x_col": "age", "y_col": "grade", "x_bins": 2, "y_bins": 10, "min_id": None, "max_id": None}
    )

    histogram = result.scalar()

    # Exact expected JSON (validated against frontend contract)
    expected = {
        'histograms': [
            {
                'xBin': '0',
                'yBin': 'A',
                'xType': 'numeric',
                'yType': 'categorical',
                'count': {
                    'items': 2,
                    'invalid': 1
                }
            },
            {
                'xBin': '1',
                'yBin': 'B',
                'xType': 'numeric',
                'yType': 'categorical',
                'count': {
                    'items': 2
                }
            }
        ],
        'scaleX': {
            'numeric': [
                {'x0': 20.0, 'x1': 35.0},
                {'x0': 35.0, 'x1': 50.0}
            ],
            'categorical': []
        },
        'scaleY': {
            'numeric': [],
            'categorical': ['A', 'B']
        }
    }

    assert histogram == expected, f"Expected: {expected}\nGot: {histogram}"
