"""
Tests for DataProfile (app/db_utils/data_profile.py) and the column types it reads through ColumnTypes, on a small
table holding a numeric column, plain text columns and two text columns that mix numbers in.
"""
import json

import pandas as pd
import pytest

from app import engine
from app.db_utils.data_profile import DataProfile
from app.db_utils.execute_sql import execute_sql

TABLE = "main_mari_test"

MAIN_ROWS = pd.DataFrame({
    'name': ['Mari', 'Seb', 'Zee', 'Juju', 'Mari'],
    'age': [30, 60, 3, 9, 30],
    'city': ['New York', 'Houston', None, 'Houston', 'Phoenix'],
    'species': ['human', 'human', 'dog', 'dog', 'human'],
    # Mostly numbers with one stray string, so it is stored as text and classed as a numeric mixed column
    'height': [5.5, 6.0, 1.2, "one", 5.5],
    # Mostly text with two numbers, so it is classed as a categorical mixed column
    'hair_color': ['black', 'brown', 2, 'black', 1],
})

# A stored profile, as build_data_profile_table writes one. Floats, so to_sql stores the statistics as numbers
PROFILE_ROWS = pd.DataFrame({
    'column_name': ['name', 'age', 'city', 'species', 'height', 'hair_color'],
    'mean': [None, 26.4, None, None, 18.2, None],
    'median': [None, 30.0, None, None, 5.5, None],
    'min': [None, 3.0, None, None, 1.2, None],
    'max': [None, 60.0, None, None, 6.0, None],
    'n_categories': [5, None, 4, 2, None, 3],
    'mode': ['Mari', None, 'Phoenix', 'human', None, 'black'],
    'error_counts': [
        json.dumps({}),
        json.dumps({}),
        json.dumps({'missing': 1}),
        json.dumps({}),
        json.dumps({'mismatch': 1}),
        json.dumps({'mismatch': 2}),
    ],
    'category_counts': [
        json.dumps({'Mari': 2, 'Seb': 1, 'Zee': 1, 'Juju': 1}),
        None,
        json.dumps({'New York': 1, 'Houston': 2, 'Phoenix': 1}),
        json.dumps({'human': 3, 'dog': 2}),
        None,
        json.dumps({'black': 3, 'brown': 1, '2': 1, '1': 1}),
    ],
})

ERROR_ROWS = pd.DataFrame({
    'row_id': [3, 4, 3, 5],
    'column_id': ['city', 'height', 'hair_color', 'hair_color'],
    'error_type': ['missing', 'mismatch', 'mismatch', 'mismatch'],
})


@pytest.fixture(scope="module")
def data_profile():
    MAIN_ROWS.to_sql(TABLE, con=engine, if_exists='replace', index=False)
    PROFILE_ROWS.to_sql(f"dp_{TABLE}", con=engine, if_exists='replace', index=False)
    ERROR_ROWS.to_sql(f"errors_{TABLE}", con=engine, if_exists='replace', index=False)

    yield DataProfile(TABLE, engine)

    for name in [TABLE, f"dp_{TABLE}", f"errors_{TABLE}"]:
        execute_sql(f'DROP TABLE IF EXISTS "{name}"', engine)


@pytest.mark.sql
def test_col_names_are_the_data_columns_in_table_order(data_profile):
    assert data_profile.get_col_names() == ['name', 'age', 'city', 'species', 'height', 'hair_color']


@pytest.mark.sql
def test_stored_statistics_are_looked_up_from_the_profile(data_profile):
    assert data_profile.look_up_stat_from_profile('mean', 'age') == 26.4
    assert data_profile.look_up_stat_from_profile('n_categories', 'species') == 2
    assert data_profile.look_up_stat_from_profile('mode', 'species') == 'human'
    assert data_profile.look_up_stat_from_profile('mode', 'name') == 'Mari'
    assert data_profile.look_up_stat_from_profile('max', 'age') == 60
    assert data_profile.look_up_stat_from_profile('error_counts', 'city') == json.dumps({'missing': 1})
    assert data_profile.look_up_stat_from_profile('category_counts', 'species') == json.dumps({'human': 3, 'dog': 2})


@pytest.mark.sql
def test_a_statistic_that_does_not_fit_the_column_is_stored_as_none(data_profile):
    assert data_profile.look_up_stat_from_profile('category_counts', 'height') is None
    assert data_profile.look_up_stat_from_profile('n_categories', 'age') is None
    assert data_profile.look_up_stat_from_profile('mode', 'age') is None


@pytest.mark.sql
def test_text_columns_holding_numbers_are_mixed(data_profile):
    assert data_profile.col_types.mixed_cols == {'height', 'hair_color'}


@pytest.mark.sql
def test_numeric_columns_include_the_mostly_numeric_mixed_one(data_profile):
    col_types = data_profile.col_types
    assert col_types.numeric_cols | col_types.numeric_mixed_cols == {'age', 'height'}


@pytest.mark.sql
def test_categorical_columns_include_the_mostly_text_mixed_one(data_profile):
    col_types = data_profile.col_types
    categorical = col_types.pure_categorical | col_types.categorical_mixed_cols
    assert categorical == {'name', 'city', 'species', 'hair_color'}


@pytest.mark.sql
def test_error_counts_are_counted_per_error_type(data_profile):
    assert data_profile._calculate_error_count_dict('name') == json.dumps({})
    assert data_profile._calculate_error_count_dict('city') == json.dumps({'missing': 1})
    assert data_profile._calculate_error_count_dict('height') == json.dumps({'mismatch': 1})
    assert data_profile._calculate_error_count_dict('hair_color') == json.dumps({'mismatch': 2})
