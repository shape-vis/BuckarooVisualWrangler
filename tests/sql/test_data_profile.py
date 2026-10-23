"""
Tests for DataProfile (app/db_utils/data_profile.py) and the column types it reads through ColumnTypes, on a small
table holding a numeric column, plain text columns and two text columns that mix numbers in. The profile is built the
way every node's is, in one query, from the table and its errors_ table.
"""
import pandas as pd
import pytest

from app import engine
from app.db_utils import query
from app.db_utils.column_types import ColumnTypes
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
    # Every spelling of missing is the null category, never the mode, however common
    'pet': ['cat', 'undefined', 'undefined', None, 'cat'],
    # Two categories tie for the mode
    'tie': ['b', 'a', 'b', 'a', None],
})

ERROR_ROWS = pd.DataFrame({
    'row_id': [3, 4, 3, 5],
    'column_id': ['city', 'height', 'hair_color', 'hair_color'],
    'error_type': ['missing', 'mismatch', 'mismatch', 'mismatch'],
})


@pytest.fixture(scope="module")
def data_profile():
    MAIN_ROWS.to_sql(TABLE, con=engine, if_exists='replace', index=False)
    ERROR_ROWS.to_sql(f"errors_{TABLE}", con=engine, if_exists='replace', index=False)
    ColumnTypes.forget(TABLE)

    profile = DataProfile(TABLE, engine)
    profile.generate_profile_table()
    yield profile

    for name in [TABLE, f"dp_{TABLE}", f"errors_{TABLE}"]:
        execute_sql(f'DROP TABLE IF EXISTS "{name}"', engine)
    ColumnTypes.forget(TABLE)


@pytest.fixture(scope="module")
def stored(data_profile):
    """The stored profile, by column."""
    rows = {}
    for row in data_profile.read_stored_profile():
        rows[row["column_name"]] = row
    return rows


@pytest.mark.sql
def test_col_names_are_the_data_columns_in_table_order(data_profile):
    assert data_profile.get_col_names() == ['name', 'age', 'city', 'species', 'height', 'hair_color', 'pet', 'tie']


@pytest.mark.sql
def test_every_column_has_one_stored_row(stored):
    assert sorted(stored) == sorted(MAIN_ROWS.columns)


@pytest.mark.sql
def test_a_numeric_column_is_measured(stored):
    age = stored['age']
    assert age['mean'] == pytest.approx(26.4)
    assert (age['median'], age['min'], age['max']) == (30, 3, 60)


@pytest.mark.sql
def test_a_mostly_numeric_text_column_is_measured_over_its_numbers(stored):
    height = stored['height']
    assert height['mean'] == pytest.approx((5.5 + 6.0 + 1.2 + 5.5) / 4)
    assert (height['median'], height['min'], height['max']) == (5.5, 1.2, 6.0)


@pytest.mark.sql
def test_a_categorical_column_is_counted(stored):
    city = stored['city']
    assert city['n_categories'] == 3
    assert city['mode'] == 'Houston'
    assert city['category_counts'] == {'New York': 1, 'Houston': 2, 'Phoenix': 1, 'null': 1}

    hair_color = stored['hair_color']
    assert hair_color['n_categories'] == 4
    assert hair_color['category_counts'] == {'black': 2, 'brown': 1, '2': 1, '1': 1}


@pytest.mark.sql
def test_missing_cells_are_one_category_and_never_the_mode(stored):
    pet = stored['pet']
    assert pet['category_counts'] == {'cat': 2, 'null': 3}
    assert pet['n_categories'] == 1
    assert pet['mode'] == 'cat'


@pytest.mark.sql
def test_the_mode_is_what_an_impute_fills_with(data_profile, stored):
    for column in ['name', 'city', 'species', 'pet', 'tie']:
        assert query.imputation_value(TABLE, column) == stored[column]['mode'], column
    # A tie goes to the first by name
    assert stored['tie']['mode'] == 'a'


@pytest.mark.sql
def test_a_statistic_that_does_not_fit_the_column_is_stored_as_none(stored):
    assert stored['height']['category_counts'] is None
    assert stored['age']['n_categories'] is None
    assert stored['age']['mode'] is None
    assert stored['city']['mean'] is None


@pytest.mark.sql
def test_error_counts_are_counted_per_error_type(stored):
    assert stored['name']['error_counts'] == {}
    assert stored['city']['error_counts'] == {'missing': 1}
    assert stored['height']['error_counts'] == {'mismatch': 1}
    assert stored['hair_color']['error_counts'] == {'mismatch': 2}


@pytest.mark.sql
def test_skipped_columns_are_left_out_of_the_read(data_profile):
    names = []
    for row in data_profile.read_stored_profile(['name', 'age']):
        names.append(row['column_name'])
    assert 'name' not in names and 'age' not in names


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
    assert categorical == {'name', 'city', 'species', 'hair_color', 'pet', 'tie'}
