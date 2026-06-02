import pandas as pd

from app.pgraph.delta import Delta


def run_delta_pandas_code(df, delta):
    namespace = {"df": df.copy()}
    exec(delta.pandas_code, namespace)
    return namespace["df"]


def test_delete_delta_pandas_code_removes_selected_row():
    df = pd.DataFrame({"ID": [1, 2, 3]}, index=[0, 1, 2])
    delta = Delta("delete", {"operation": "delete", "row_ids": [1]})

    result = run_delta_pandas_code(df, delta)

    expected_df = pd.DataFrame({"ID": [2, 3]}, index=[1, 2])
    pd.testing.assert_frame_equal(expected_df, result)


def test_delete_delta_pandas_code_removes_multiple_rows():
    df = pd.DataFrame({"ID": [1, 2, 3]}, index=[0, 1, 2])
    delta = Delta("delete", {"operation": "delete", "row_ids": [1, 2]})

    result = run_delta_pandas_code(df, delta)

    expected_df = pd.DataFrame({"ID": [3]}, index=[2])
    pd.testing.assert_frame_equal(expected_df, result)


def test_delete_delta_pandas_code_ignores_nonexistent_ids():
    df = pd.DataFrame({"ID": [1, 2, 3]}, index=[0, 1, 2])
    delta = Delta("delete", {"operation": "delete", "row_ids": [999]})

    result = run_delta_pandas_code(df, delta)

    pd.testing.assert_frame_equal(df, result)
