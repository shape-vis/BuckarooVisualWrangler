"""
Tests for scatterplot generation (generate_scatterplot_with_errors).
"""
import pytest
import pandas as pd
from sqlalchemy import text


@pytest.mark.sql
def test_scatterplot_basic(db_transaction):
    """Test basic scatterplot generation"""
    df = pd.DataFrame({
        'ID': range(1, 21),
        'x_val': range(10, 210, 10),
        'y_val': range(20, 220, 10)
    })
    df.to_sql('test_scatter_basic', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': pd.Series(dtype='int64'),
        'column_id': pd.Series(dtype='str'),
        'error_type': pd.Series(dtype='str')
    })
    error_df.to_sql('errors_test_scatter_basic', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_scatterplot_with_errors(:table, :errors, :x_col, :y_col, :error_sample, :total_sample, :min_id, :max_id)"),
        {"table": "test_scatter_basic", "errors": "errors_test_scatter_basic", "x_col": "x_val", "y_col": "y_val", "error_sample": 10, "total_sample": 15, "min_id": None, "max_id": None}
    )

    scatterplot = result.scalar()

    assert 'data' in scatterplot
    assert 'scaleX' in scatterplot
    assert 'scaleY' in scatterplot
    assert len(scatterplot['data']) <= 15
    assert all(len(point['errors']) == 0 for point in scatterplot['data'])


@pytest.mark.sql
def test_scatterplot_sampling(db_transaction):
    """Test scatterplot sampling behavior"""
    df = pd.DataFrame({
        'ID': range(1, 101),
        'x': range(1, 101),
        'y': range(100, 200)
    })
    df.to_sql('test_scatter_sample', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': list(range(1, 41)),
        'column_id': ['x'] * 40,
        'error_type': ['missing'] * 40
    })
    error_df.to_sql('errors_test_scatter_sample', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_scatterplot_with_errors(:table, :errors, :x_col, :y_col, :error_sample, :total_sample, :min_id, :max_id)"),
        {"table": "test_scatter_sample", "errors": "errors_test_scatter_sample", "x_col": "x", "y_col": "y", "error_sample": 20, "total_sample": 50, "min_id": None, "max_id": None}
    )

    scatterplot = result.scalar()

    assert len(scatterplot['data']) <= 50
    error_points = [p for p in scatterplot['data'] if len(p['errors']) > 0]
    assert len(error_points) > 0


@pytest.mark.sql
def test_scatterplot_error_annotation(db_transaction):
    """Test error annotation on points"""
    df = pd.DataFrame({
        'ID': range(1, 21),
        'x': range(1, 21),
        'y': range(10, 30)
    })
    df.to_sql('test_scatter_errors', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [1, 5, 10, 15, 20],
        'column_id': ['x', 'y', 'x', 'y', 'x'],
        'error_type': ['missing', 'outlier', 'invalid', 'missing', 'outlier']
    })
    error_df.to_sql('errors_test_scatter_errors', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_scatterplot_with_errors(:table, :errors, :x_col, :y_col, :error_sample, :total_sample, :min_id, :max_id)"),
        {"table": "test_scatter_errors", "errors": "errors_test_scatter_errors", "x_col": "x", "y_col": "y", "error_sample": 10, "total_sample": 20, "min_id": None, "max_id": None}
    )

    scatterplot = result.scalar()

    assert all('errors' in point for point in scatterplot['data'])
    points_with_errors = [p for p in scatterplot['data'] if len(p['errors']) > 0]
    assert len(points_with_errors) > 0


@pytest.mark.sql
def test_scatterplot_with_id_filter(db_transaction):
    """Test ID range filtering"""
    df = pd.DataFrame({
        'ID': range(1, 51),
        'x': range(1, 51),
        'y': range(100, 150)
    })
    df.to_sql('test_scatter_filter', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [5, 15, 25],
        'column_id': ['x'] * 3,
        'error_type': ['missing'] * 3
    })
    error_df.to_sql('errors_test_scatter_filter', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_scatterplot_with_errors(:table, :errors, :x_col, :y_col, :error_sample, :total_sample, :min_id, :max_id)"),
        {"table": "test_scatter_filter", "errors": "errors_test_scatter_filter", "x_col": "x", "y_col": "y", "error_sample": 10, "total_sample": 20, "min_id": 10, "max_id": 30}
    )

    scatterplot = result.scalar()

    assert all(10 <= point['ID'] <= 30 for point in scatterplot['data'])


@pytest.mark.sql
def test_scatterplot_scale_generation(db_transaction):
    """Test scale generation"""
    df = pd.DataFrame({
        'ID': range(1, 21),
        'x': range(50, 250, 10),
        'y': range(100, 300, 10)
    })
    df.to_sql('test_scatter_scale', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': pd.Series(dtype='int64'),
        'column_id': pd.Series(dtype='str'),
        'error_type': pd.Series(dtype='str')
    })
    error_df.to_sql('errors_test_scatter_scale', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_scatterplot_with_errors(:table, :errors, :x_col, :y_col, :error_sample, :total_sample, :min_id, :max_id)"),
        {"table": "test_scatter_scale", "errors": "errors_test_scatter_scale", "x_col": "x", "y_col": "y", "error_sample": 10, "total_sample": 20, "min_id": None, "max_id": None}
    )

    scatterplot = result.scalar()

    assert 'numeric' in scatterplot['scaleX']
    assert 'numeric' in scatterplot['scaleY']
    assert len(scatterplot['scaleX']['numeric']) == 2
    assert len(scatterplot['scaleY']['numeric']) == 2


@pytest.mark.sql
def test_scatterplot_exact_response(db_transaction):
    """Golden test: exact JSON response for scatterplot"""
    df = pd.DataFrame({
        'ID': [1, 2, 3, 4],
        'x': [10, 20, 30, 40],
        'y': [100, 200, 300, 400]
    })
    df.to_sql('test_golden_scatter', db_transaction, if_exists='replace', index=False)

    error_df = pd.DataFrame({
        'row_id': [1, 3],
        'column_id': ['x', 'y'],
        'error_type': ['missing', 'outlier']
    })
    error_df.to_sql('errors_test_golden_scatter', db_transaction, if_exists='replace', index=False)

    result = db_transaction.execute(
        text("SELECT generate_scatterplot_with_errors(:table, :errors, :x_col, :y_col, :error_sample, :total_sample, :min_id, :max_id)"),
        {"table": "test_golden_scatter", "errors": "errors_test_golden_scatter", "x_col": "x", "y_col": "y", "error_sample": 10, "total_sample": 10, "min_id": None, "max_id": None}
    )

    scatterplot = result.scalar()

    # Order varies due to RANDOM() sampling — build lookup by ID
    data_by_id = {p['ID']: p for p in scatterplot['data']}

    # All 4 rows returned: 2 error rows + 2 clean rows filling to total_sample
    assert set(data_by_id.keys()) == {1, 2, 3, 4}

    # Error rows carry their errors
    assert data_by_id[1]['errors'] == ['missing']
    assert data_by_id[3]['errors'] == ['outlier']

    # Clean rows have empty error list
    assert data_by_id[2]['errors'] == []
    assert data_by_id[4]['errors'] == []

    # All points have correct types and values
    for point in scatterplot['data']:
        assert point['xType'] == 'numeric'
        assert point['yType'] == 'numeric'

    # Exact scales: [min, max+1] for numeric; [] for categorical (pure numeric columns)
    assert scatterplot['scaleX'] == {'numeric': [10, 41], 'categorical': []}
    assert scatterplot['scaleY'] == {'numeric': [100, 401], 'categorical': []}
