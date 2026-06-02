"""Tests that exported impute Pandas code fills only the selected cells."""

import numpy as np
import pandas as pd

from app.pgraph.delta import Delta


def run_delta_pandas_code(df, delta):
    """Execute a Delta's generated Pandas code against a copy of df."""
    namespace = {"df": df.copy()}
    exec(delta.pandas_code, namespace)
    return namespace["df"]


def test_impute_delta_pandas_code_fills_selected_numeric_nulls_with_mean():
    df = pd.DataFrame({
        "ID": [1, 2, 3, 4],
        "numeric_col": [10.0, 20.0, np.nan, 40.0],
    })
    delta = Delta("impute", {"operation": "impute", "row_ids": [3], "col": "numeric_col"})

    result = run_delta_pandas_code(df, delta)

    assert result.loc[2, "numeric_col"] == 23.333333333333332


def test_impute_delta_pandas_code_does_not_overwrite_selected_non_null_values():
    df = pd.DataFrame({
        "ID": [1, 2, 3],
        "numeric_col": [10.0, np.nan, 30.0],
    })
    delta = Delta("impute", {"operation": "impute", "row_ids": [1, 2], "col": "numeric_col"})

    result = run_delta_pandas_code(df, delta)

    assert result.loc[0, "numeric_col"] == 10.0
    assert result.loc[1, "numeric_col"] == 20.0


def test_impute_delta_pandas_code_fills_selected_categorical_nulls_with_mode():
    df = pd.DataFrame({
        "ID": [1, 2, 3, 4],
        "category": ["A", "B", "A", None],
    })
    delta = Delta("impute", {"operation": "impute", "row_ids": [4], "col": "category"})

    result = run_delta_pandas_code(df, delta)

    assert result.loc[3, "category"] == "A"


def test_impute_delta_pandas_code_leaves_non_selected_nulls_unchanged():
    df = pd.DataFrame({
        "ID": [1, 2, 3],
        "numeric_col": [10.0, np.nan, np.nan],
    })
    delta = Delta("impute", {"operation": "impute", "row_ids": [2], "col": "numeric_col"})

    result = run_delta_pandas_code(df, delta)

    assert result.loc[1, "numeric_col"] == 10.0
    assert pd.isna(result.loc[2, "numeric_col"])
