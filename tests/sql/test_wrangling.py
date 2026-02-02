"""
Tests for data wrangling operations (postgres_wrangling.query module).

TODO: Add tests for:
- remove_rows_by_ids()
- impute_by_ids() - numeric and categorical
- remove_flagged_rows_in_1d_bin()
- impute_1d_bin_in_place()
- remove_flagged_rows_in_bin() (2D)
- impute_bin_in_place() (2D)
- Edge cases (empty selections, no errors, all errors)
"""
import pytest
import pandas as pd
from sqlalchemy import text


@pytest.mark.sql
def test_remove_rows_by_ids(db_transaction):
    """Test removing rows by ID list"""
    # TODO: Implement test
    pass


@pytest.mark.sql
def test_impute_by_ids_numeric(db_transaction):
    """Test imputing numeric values by ID"""
    # TODO: Implement test
    pass


@pytest.mark.sql
def test_impute_by_ids_categorical(db_transaction):
    """Test imputing categorical values by ID"""
    # TODO: Implement test
    pass


@pytest.mark.sql
def test_remove_flagged_rows_in_1d_bin(db_transaction):
    """Test removing flagged rows in 1D histogram bin"""
    # TODO: Implement test
    pass


@pytest.mark.sql
def test_impute_1d_bin_numeric(db_transaction):
    """Test imputing values in 1D bin (numeric)"""
    # TODO: Implement test
    pass


@pytest.mark.sql
def test_remove_flagged_rows_in_2d_bin(db_transaction):
    """Test removing flagged rows in 2D histogram bin"""
    # TODO: Implement test
    pass


@pytest.mark.sql
def test_impute_2d_bin(db_transaction):
    """Test imputing values in 2D bin"""
    # TODO: Implement test
    pass
