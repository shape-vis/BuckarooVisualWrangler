"""
Integration tests for POST /api/wrangle/create-previews.

Each test writes real tables to the database, calls the Flask endpoint via
test client, and verifies the preview tables are created with the correct
contents.  All tables are dropped in a finally block so the DB stays clean.
"""
import pytest
import pandas as pd
from sqlalchemy import text as sa_text
from app import app as flask_app, engine


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _drop_tables(conn, *names):
    for name in names:
        conn.execute(sa_text(f'DROP TABLE IF EXISTS "{name}"'))


def _table_exists(table_name) -> bool:
    with engine.connect() as conn:
        result = conn.execute(sa_text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :n)"
        ), {"n": table_name})
        return result.scalar()


def _row_count(table_name) -> int:
    with engine.connect() as conn:
        result = conn.execute(sa_text(f'SELECT COUNT(*) FROM "{table_name}"'))
        return result.scalar()


# ─── _preview_name table-name contract (via endpoint response) ────────────────

@pytest.mark.sql
def test_create_previews_returns_correct_1d_names(db_transaction):
    """Response keys match the names _preview_name would generate."""
    table = "tp_names_1d"
    df = pd.DataFrame({"ID": range(1, 6), "val": [1.0, None, 3.0, None, 5.0]})
    error_df = pd.DataFrame({
        "row_id": [2, 4],
        "column_id": ["val", "val"],
        "error_type": ["missing", "missing"],
    })
    df.to_sql(table, engine, if_exists="replace", index=False)
    error_df.to_sql(f"errors_{table}", engine, if_exists="replace", index=False)

    preview_delete = f"{table}_preview_delete"
    preview_impute = f"{table}_preview_impute"

    try:
        client = flask_app.test_client()
        resp = client.post("/api/wrangle/create-previews", json={
            "table": table,
            "row_ids": [2, 4],
            "cols": ["val"],
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["dims"] == 1
        assert data["preview_delete"] == preview_delete
        assert data["preview_impute"] == preview_impute
    finally:
        with engine.begin() as conn:
            _drop_tables(conn,
                table, f"errors_{table}",
                preview_delete, f"errors_{preview_delete}",
                preview_impute, f"errors_{preview_impute}",
            )


@pytest.mark.sql
def test_create_previews_returns_correct_2d_names(db_transaction):
    """2D response keys match expected names."""
    table = "tp_names_2d"
    df = pd.DataFrame({
        "ID": range(1, 6),
        "x": [1.0, None, 3.0, None, 5.0],
        "y": [10.0, 20.0, None, None, 50.0],
    })
    error_df = pd.DataFrame({
        "row_id": [2, 3, 4],
        "column_id": ["x", "y", "x"],
        "error_type": ["missing", "missing", "missing"],
    })
    df.to_sql(table, engine, if_exists="replace", index=False)
    error_df.to_sql(f"errors_{table}", engine, if_exists="replace", index=False)

    preview_delete   = f"{table}_preview_delete"
    preview_impute_x = f"{table}_preview_impute_x"
    preview_impute_y = f"{table}_preview_impute_y"

    try:
        client = flask_app.test_client()
        resp = client.post("/api/wrangle/create-previews", json={
            "table": table,
            "row_ids": [2, 3, 4],
            "cols": ["x", "y"],
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["dims"] == 2
        assert data["preview_delete"]   == preview_delete
        assert data["preview_impute_x"] == preview_impute_x
        assert data["preview_impute_y"] == preview_impute_y
    finally:
        with engine.begin() as conn:
            _drop_tables(conn,
                table, f"errors_{table}",
                preview_delete,   f"errors_{preview_delete}",
                preview_impute_x, f"errors_{preview_impute_x}",
                preview_impute_y, f"errors_{preview_impute_y}",
            )


# ─── 1D preview contents ──────────────────────────────────────────────────────

@pytest.mark.sql
def test_create_previews_1d_delete_removes_selected_rows(db_transaction):
    table = "tp_del_1d"
    df = pd.DataFrame({"ID": range(1, 11), "amount": [float(i * 10) for i in range(1, 11)]})
    error_df = pd.DataFrame({
        "row_id": [2, 5, 8],
        "column_id": ["amount"] * 3,
        "error_type": ["missing", "outlier", "invalid"],
    })
    df.to_sql(table, engine, if_exists="replace", index=False)
    error_df.to_sql(f"errors_{table}", engine, if_exists="replace", index=False)

    preview_delete = f"{table}_preview_delete"
    preview_impute = f"{table}_preview_impute"

    try:
        client = flask_app.test_client()
        resp = client.post("/api/wrangle/create-previews", json={
            "table": table,
            "row_ids": [2, 5, 8],
            "cols": ["amount"],
        })
        assert resp.status_code == 200

        # Delete preview should have 10 - 3 = 7 rows
        del_df = pd.read_sql_query(f'SELECT * FROM "{preview_delete}"', engine)
        assert len(del_df) == 7
        assert 2 not in del_df["ID"].values
        assert 5 not in del_df["ID"].values
        assert 8 not in del_df["ID"].values

        # Original table should be untouched
        orig_df = pd.read_sql_query(f'SELECT * FROM "{table}"', engine)
        assert len(orig_df) == 10
    finally:
        with engine.begin() as conn:
            _drop_tables(conn,
                table, f"errors_{table}",
                preview_delete, f"errors_{preview_delete}",
                preview_impute, f"errors_{preview_impute}",
            )


@pytest.mark.sql
def test_create_previews_1d_impute_fills_nulls(db_transaction):
    table = "tp_imp_1d"
    df = pd.DataFrame({
        "ID": range(1, 11),
        "amount": [100.0, None, 300.0, None, 500.0, 600.0, None, 800.0, 900.0, 1000.0],
    })
    error_df = pd.DataFrame({
        "row_id": [2, 4, 7],
        "column_id": ["amount"] * 3,
        "error_type": ["missing", "missing", "missing"],
    })
    df.to_sql(table, engine, if_exists="replace", index=False)
    error_df.to_sql(f"errors_{table}", engine, if_exists="replace", index=False)

    preview_delete = f"{table}_preview_delete"
    preview_impute = f"{table}_preview_impute"

    try:
        client = flask_app.test_client()
        resp = client.post("/api/wrangle/create-previews", json={
            "table": table,
            "row_ids": [2, 4, 7],
            "cols": ["amount"],
        })
        assert resp.status_code == 200

        # Impute preview should still have all 10 rows
        imp_df = pd.read_sql_query(f'SELECT * FROM "{preview_impute}"', engine)
        assert len(imp_df) == 10

        # The previously-NULL rows should now have values
        targeted = imp_df[imp_df["ID"].isin([2, 4, 7])]
        assert targeted["amount"].isna().sum() == 0

        # Original table should be untouched (nulls intact)
        orig_df = pd.read_sql_query(f'SELECT * FROM "{table}"', engine)
        assert orig_df["amount"].isna().sum() == 3
    finally:
        with engine.begin() as conn:
            _drop_tables(conn,
                table, f"errors_{table}",
                preview_delete, f"errors_{preview_delete}",
                preview_impute, f"errors_{preview_impute}",
            )


@pytest.mark.sql
def test_create_previews_1d_creates_errors_tables(db_transaction):
    table = "tp_errs_1d"
    df = pd.DataFrame({"ID": range(1, 6), "val": [1.0, None, 3.0, 4.0, 5.0]})
    error_df = pd.DataFrame({
        "row_id": [2],
        "column_id": ["val"],
        "error_type": ["missing"],
    })
    df.to_sql(table, engine, if_exists="replace", index=False)
    error_df.to_sql(f"errors_{table}", engine, if_exists="replace", index=False)

    preview_delete = f"{table}_preview_delete"
    preview_impute = f"{table}_preview_impute"

    try:
        client = flask_app.test_client()
        resp = client.post("/api/wrangle/create-previews", json={
            "table": table,
            "row_ids": [2],
            "cols": ["val"],
        })
        assert resp.status_code == 200

        assert _table_exists(f"errors_{preview_delete}")
        assert _table_exists(f"errors_{preview_impute}")
    finally:
        with engine.begin() as conn:
            _drop_tables(conn,
                table, f"errors_{table}",
                preview_delete, f"errors_{preview_delete}",
                preview_impute, f"errors_{preview_impute}",
            )


# ─── 2D preview contents ──────────────────────────────────────────────────────

@pytest.mark.sql
def test_create_previews_2d_delete_removes_selected_rows(db_transaction):
    table = "tp_del_2d"
    df = pd.DataFrame({
        "ID": range(1, 11),
        "x": [float(i) for i in range(1, 11)],
        "y": [float(i * 2) for i in range(1, 11)],
    })
    error_df = pd.DataFrame({
        "row_id": [3, 6, 9],
        "column_id": ["x", "y", "x"],
        "error_type": ["outlier", "invalid", "outlier"],
    })
    df.to_sql(table, engine, if_exists="replace", index=False)
    error_df.to_sql(f"errors_{table}", engine, if_exists="replace", index=False)

    preview_delete   = f"{table}_preview_delete"
    preview_impute_x = f"{table}_preview_impute_x"
    preview_impute_y = f"{table}_preview_impute_y"

    try:
        client = flask_app.test_client()
        resp = client.post("/api/wrangle/create-previews", json={
            "table": table,
            "row_ids": [3, 6, 9],
            "cols": ["x", "y"],
        })
        assert resp.status_code == 200

        del_df = pd.read_sql_query(f'SELECT * FROM "{preview_delete}"', engine)
        assert len(del_df) == 7
        assert set(del_df["ID"].values).isdisjoint({3, 6, 9})

        # Original unchanged
        orig_df = pd.read_sql_query(f'SELECT * FROM "{table}"', engine)
        assert len(orig_df) == 10
    finally:
        with engine.begin() as conn:
            _drop_tables(conn,
                table, f"errors_{table}",
                preview_delete,   f"errors_{preview_delete}",
                preview_impute_x, f"errors_{preview_impute_x}",
                preview_impute_y, f"errors_{preview_impute_y}",
            )


@pytest.mark.sql
def test_create_previews_2d_impute_x_fills_nulls_in_x_only(db_transaction):
    table = "tp_imp_x_2d"
    df = pd.DataFrame({
        "ID": range(1, 11),
        "x": [1.0, None, 3.0, None, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
        "y": [10.0, 20.0, None, None, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0],
    })
    error_df = pd.DataFrame({
        "row_id": [2, 3, 4],
        "column_id": ["x", "y", "x"],
        "error_type": ["missing", "missing", "missing"],
    })
    df.to_sql(table, engine, if_exists="replace", index=False)
    error_df.to_sql(f"errors_{table}", engine, if_exists="replace", index=False)

    preview_delete   = f"{table}_preview_delete"
    preview_impute_x = f"{table}_preview_impute_x"
    preview_impute_y = f"{table}_preview_impute_y"

    try:
        client = flask_app.test_client()
        resp = client.post("/api/wrangle/create-previews", json={
            "table": table,
            "row_ids": [2, 4],
            "cols": ["x", "y"],
        })
        assert resp.status_code == 200

        imp_x_df = pd.read_sql_query(f'SELECT * FROM "{preview_impute_x}"', engine)
        # x NULLs at IDs 2 and 4 should be filled
        targeted_x = imp_x_df[imp_x_df["ID"].isin([2, 4])]
        assert targeted_x["x"].isna().sum() == 0

        # y column should be untouched (impute_x only touches x)
        assert imp_x_df["y"].isna().sum() == imp_x_df["y"].isna().sum()  # structural check
    finally:
        with engine.begin() as conn:
            _drop_tables(conn,
                table, f"errors_{table}",
                preview_delete,   f"errors_{preview_delete}",
                preview_impute_x, f"errors_{preview_impute_x}",
                preview_impute_y, f"errors_{preview_impute_y}",
            )


@pytest.mark.sql
def test_create_previews_2d_creates_all_errors_tables(db_transaction):
    table = "tp_errs_2d"
    df = pd.DataFrame({
        "ID": range(1, 6),
        "x": [1.0, None, 3.0, 4.0, 5.0],
        "y": [10.0, 20.0, 30.0, None, 50.0],
    })
    error_df = pd.DataFrame({
        "row_id": [2, 4],
        "column_id": ["x", "y"],
        "error_type": ["missing", "missing"],
    })
    df.to_sql(table, engine, if_exists="replace", index=False)
    error_df.to_sql(f"errors_{table}", engine, if_exists="replace", index=False)

    preview_delete   = f"{table}_preview_delete"
    preview_impute_x = f"{table}_preview_impute_x"
    preview_impute_y = f"{table}_preview_impute_y"

    try:
        client = flask_app.test_client()
        resp = client.post("/api/wrangle/create-previews", json={
            "table": table,
            "row_ids": [2, 4],
            "cols": ["x", "y"],
        })
        assert resp.status_code == 200

        for t in [
            f"errors_{preview_delete}",
            f"errors_{preview_impute_x}",
            f"errors_{preview_impute_y}",
        ]:
            assert _table_exists(t), f"Expected table '{t}' to exist"
    finally:
        with engine.begin() as conn:
            _drop_tables(conn,
                table, f"errors_{table}",
                preview_delete,   f"errors_{preview_delete}",
                preview_impute_x, f"errors_{preview_impute_x}",
                preview_impute_y, f"errors_{preview_impute_y}",
            )


# ─── Error / edge cases ───────────────────────────────────────────────────────

@pytest.mark.sql
def test_create_previews_missing_row_ids_returns_400(db_transaction):
    client = flask_app.test_client()
    resp = client.post("/api/wrangle/create-previews", json={
        "table": "any_table",
        "row_ids": [],
        "cols": ["amount"],
    })
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["success"] is False
    assert "No rows selected" in data["error"]


@pytest.mark.sql
def test_create_previews_1d_impute_fills_nulls_categorical(db_transaction):
    """
    1D case: NULL values in a categorical column are filled with the mode.

    Setup: 'category' has 7 rows = 'A' and 3 rows = NULL.
    Mode = 'A'.  After create-previews the impute preview should have
    'A' in every targeted (previously-NULL) row.
    """
    table = "tp_cat_1d"
    df = pd.DataFrame({
        "ID": range(1, 11),
        "category": ["A"] * 7 + [None] * 3,  # mode = 'A'
    })
    error_df = pd.DataFrame({
        "row_id": [8, 9, 10],
        "column_id": ["category"] * 3,
        "error_type": ["missing"] * 3,
    })
    df.to_sql(table, engine, if_exists="replace", index=False)
    error_df.to_sql(f"errors_{table}", engine, if_exists="replace", index=False)

    preview_delete = f"{table}_preview_delete"
    preview_impute = f"{table}_preview_impute"

    try:
        client = flask_app.test_client()
        resp = client.post("/api/wrangle/create-previews", json={
            "table": table,
            "row_ids": [8, 9, 10],
            "cols": ["category"],
        })
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

        imp_df = pd.read_sql_query(f'SELECT * FROM "{preview_impute}"', engine)

        # All 10 rows should still be present
        assert len(imp_df) == 10

        # Targeted rows must now have a value (no NULLs)
        targeted = imp_df[imp_df["ID"].isin([8, 9, 10])]
        assert targeted["category"].isna().sum() == 0

        # The imputed value must be the mode ('A')
        assert (targeted["category"] == "A").all()

        # Non-targeted rows must be unchanged
        untouched = imp_df[~imp_df["ID"].isin([8, 9, 10])]
        assert (untouched["category"] == "A").all()

        # Original table must be untouched
        orig_df = pd.read_sql_query(f'SELECT * FROM "{table}"', engine)
        assert orig_df["category"].isna().sum() == 3
    finally:
        with engine.begin() as conn:
            _drop_tables(conn,
                table, f"errors_{table}",
                preview_delete, f"errors_{preview_delete}",
                preview_impute, f"errors_{preview_impute}",
            )


@pytest.mark.sql
def test_create_previews_2d_impute_x_fills_nulls_in_x_only_categorical(db_transaction):
    """
    2D case: x is categorical, y is numeric.
    preview_impute_x should fill NULL x values with the mode ('A').
    y should be completely untouched in that preview.
    """
    table = "tp_cat_x_2d"
    df = pd.DataFrame({
        "ID": range(1, 11),
        "x": ["A"] * 7 + [None] * 3,   # categorical, mode = 'A'
        "y": [float(i * 10) for i in range(1, 11)],  # numeric, no NULLs
    })
    error_df = pd.DataFrame({
        "row_id": [8, 9, 10],
        "column_id": ["x"] * 3,
        "error_type": ["missing"] * 3,
    })
    df.to_sql(table, engine, if_exists="replace", index=False)
    error_df.to_sql(f"errors_{table}", engine, if_exists="replace", index=False)

    preview_delete   = f"{table}_preview_delete"
    preview_impute_x = f"{table}_preview_impute_x"
    preview_impute_y = f"{table}_preview_impute_y"

    try:
        client = flask_app.test_client()
        resp = client.post("/api/wrangle/create-previews", json={
            "table": table,
            "row_ids": [8, 9, 10],
            "cols": ["x", "y"],
        })
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

        imp_x_df = pd.read_sql_query(f'SELECT * FROM "{preview_impute_x}"', engine)

        # All 10 rows should still be present
        assert len(imp_x_df) == 10

        # Targeted x NULLs should be filled with the mode 'A'
        targeted = imp_x_df[imp_x_df["ID"].isin([8, 9, 10])]
        assert targeted["x"].isna().sum() == 0
        assert (targeted["x"] == "A").all()

        # y column must be completely unchanged (impute_x only touches x)
        orig_y = df.set_index("ID")["y"]
        imp_y = imp_x_df.set_index("ID")["y"]
        for row_id in range(1, 11):
            assert imp_y[row_id] == orig_y[row_id]

        # Original table must be untouched
        orig_df = pd.read_sql_query(f'SELECT * FROM "{table}"', engine)
        assert orig_df["x"].isna().sum() == 3
    finally:
        with engine.begin() as conn:
            _drop_tables(conn,
                table, f"errors_{table}",
                preview_delete,   f"errors_{preview_delete}",
                preview_impute_x, f"errors_{preview_impute_x}",
                preview_impute_y, f"errors_{preview_impute_y}",
            )


@pytest.mark.sql
def test_create_previews_2d_impute_y_fills_nulls_in_y_only_categorical(db_transaction):
    """
    2D case: x is numeric, y is categorical.
    preview_impute_y should fill NULL y values with the mode ('B').
    x should be completely untouched in that preview.
    """
    table = "tp_cat_y_2d"
    df = pd.DataFrame({
        "ID": range(1, 11),
        "x": [float(i * 5) for i in range(1, 11)],   # numeric, no NULLs
        "y": ["B"] * 8 + [None] * 2,  # categorical, mode = 'B'
    })
    error_df = pd.DataFrame({
        "row_id": [9, 10],
        "column_id": ["y"] * 2,
        "error_type": ["missing"] * 2,
    })
    df.to_sql(table, engine, if_exists="replace", index=False)
    error_df.to_sql(f"errors_{table}", engine, if_exists="replace", index=False)

    preview_delete   = f"{table}_preview_delete"
    preview_impute_x = f"{table}_preview_impute_x"
    preview_impute_y = f"{table}_preview_impute_y"

    try:
        client = flask_app.test_client()
        resp = client.post("/api/wrangle/create-previews", json={
            "table": table,
            "row_ids": [9, 10],
            "cols": ["x", "y"],
        })
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

        imp_y_df = pd.read_sql_query(f'SELECT * FROM "{preview_impute_y}"', engine)

        # All 10 rows should still be present
        assert len(imp_y_df) == 10

        # Targeted y NULLs should be filled with the mode 'B'
        targeted = imp_y_df[imp_y_df["ID"].isin([9, 10])]
        assert targeted["y"].isna().sum() == 0
        assert (targeted["y"] == "B").all()

        # x column must be completely unchanged (impute_y only touches y)
        orig_x = df.set_index("ID")["x"]
        imp_x = imp_y_df.set_index("ID")["x"]
        for row_id in range(1, 11):
            assert imp_x[row_id] == orig_x[row_id]

        # Original table must be untouched
        orig_df = pd.read_sql_query(f'SELECT * FROM "{table}"', engine)
        assert orig_df["y"].isna().sum() == 2
    finally:
        with engine.begin() as conn:
            _drop_tables(conn,
                table, f"errors_{table}",
                preview_delete,   f"errors_{preview_delete}",
                preview_impute_x, f"errors_{preview_impute_x}",
                preview_impute_y, f"errors_{preview_impute_y}",
            )


@pytest.mark.sql
def test_create_previews_2d_impute_y_fills_nulls_in_y_only_numeric(db_transaction):
    """
    2D case: both x and y are numeric.
    preview_impute_y should fill NULL y values with the column mean.
    x should be completely untouched in that preview.

    y values for IDs 1-7: 10, 20, 30, 40, 50, 60, 70 → mean = 40.0
    y values for IDs 8-10: NULL (targeted)
    """
    table = "tp_num_y_2d"
    y_values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, None, None, None]
    df = pd.DataFrame({
        "ID": range(1, 11),
        "x": [float(i * 3) for i in range(1, 11)],  # numeric, no NULLs
        "y": y_values,
    })
    error_df = pd.DataFrame({
        "row_id": [8, 9, 10],
        "column_id": ["y"] * 3,
        "error_type": ["missing"] * 3,
    })
    df.to_sql(table, engine, if_exists="replace", index=False)
    error_df.to_sql(f"errors_{table}", engine, if_exists="replace", index=False)

    preview_delete   = f"{table}_preview_delete"
    preview_impute_x = f"{table}_preview_impute_x"
    preview_impute_y = f"{table}_preview_impute_y"

    # mean of [10,20,30,40,50,60,70] = 280/7 = 40.0
    expected_mean = 40

    try:
        client = flask_app.test_client()
        resp = client.post("/api/wrangle/create-previews", json={
            "table": table,
            "row_ids": [8, 9, 10],
            "cols": ["x", "y"],
        })
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

        imp_y_df = pd.read_sql_query(f'SELECT * FROM "{preview_impute_y}"', engine)

        # All 10 rows should still be present
        assert len(imp_y_df) == 10

        # Targeted y NULLs should be filled with the mean
        targeted = imp_y_df[imp_y_df["ID"].isin([8, 9, 10])]
        assert targeted["y"].isna().sum() == 0
        # assert (targeted["y"] == 40)
        assert targeted.loc[targeted['ID'] == 8, 'y'].values[0]
        assert targeted.loc[targeted['ID'] == 9, 'y'].values[0] == 40
        assert targeted.loc[targeted['ID'] == 10, 'y'].values[0] == 40

        # x column must be completely unchanged (impute_y only touches y)
        orig_x = df.set_index("ID")["x"]
        imp_x = imp_y_df.set_index("ID")["x"]
        for row_id in range(1, 11):
            assert imp_x[row_id] == pytest.approx(orig_x[row_id])

        # preview_impute_x should NOT have filled y (it only touches x)
        imp_x_df = pd.read_sql_query(f'SELECT * FROM "{preview_impute_x}"', engine)
        y_nulls_in_x_preview = imp_x_df[imp_x_df["ID"].isin([8, 9, 10])]["y"]
        assert y_nulls_in_x_preview.isna().sum() == 3

        # Original table must be untouched
        orig_df = pd.read_sql_query(f'SELECT * FROM "{table}"', engine)
        assert orig_df["y"].isna().sum() == 3
    finally:
        with engine.begin() as conn:
            _drop_tables(conn,
                table, f"errors_{table}",
                preview_delete,   f"errors_{preview_delete}",
                preview_impute_x, f"errors_{preview_impute_x}",
                preview_impute_y, f"errors_{preview_impute_y}",
            )


# ─────────────────────────────────────────────────────────────────────────────


# ─── Robust 5-column / 50-row tests ──────────────────────────────────────────
#
# Dataset layout
# ──────────────
# Columns : ID, cat_a (TEXT), cat_b (TEXT), num_1, num_2, num_3
#
# IDs  1-40 : all values filled
#   cat_a  : 'X' × 30, 'Y' × 10          →  mode  = 'X'
#   cat_b  : 'P' × 25, 'Q' × 10, 'R' × 5 →  mode  = 'P'
#   num_1  : ID × 2.0                     →  mean  = 41.0
#   num_2  : ID × 3.0                     →  mean  = 61.5
#   num_3  : ID × 5.0                     →  mean  = 102.5
#
# IDs 41-45 : TARGETED – all five data columns are NULL.
#             These are the row_ids passed to create-previews.
#             After imputation they MUST receive the column mean / mode.
#
# IDs 46-50 : NON-TARGETED – also all NULL but NOT in row_ids.
#             After imputation they MUST remain NULL to prove the
#             endpoint is ID-specific, not a blanket NULL-fill.
#
# Means verified analytically:
#   num_1: Σ(i×2, i=1..40)/40 = 2 × (40×41/2) / 40 = 41.0
#   num_2: Σ(i×3, i=1..40)/40 = 3 × (40×41/2) / 40 = 61.5
#   num_3: Σ(i×5, i=1..40)/40 = 5 × (40×41/2) / 40 = 102.5

_TARGETED     = list(range(41, 46))   # IDs in row_ids
_NONTARGET    = list(range(46, 51))   # IDs NOT in row_ids (must stay NULL)
_FILLED_IDS   = list(range(1, 41))    # IDs with real values (must be unchanged)

_EXPECTED_IMPUTE = {
    "cat_a": "X",
    "cat_b": "P",
    "num_1": 41.0,
    "num_2": 61.5,
    "num_3": 102.5,
}


def _setup_robust_table(table: str) -> None:
    """Write the 50-row, 5-column fixture and its errors table to the DB."""
    cat_a = ["X"] * 30 + ["Y"] * 10 + [None] * 10
    cat_b = ["P"] * 25 + ["Q"] * 10 + ["R"] * 5 + [None] * 10
    num_1 = [float(i * 2) for i in range(1, 41)] + [None] * 10
    num_2 = [float(i * 3) for i in range(1, 41)] + [None] * 10
    num_3 = [float(i * 5) for i in range(1, 41)] + [None] * 10

    df = pd.DataFrame({
        "ID":    list(range(1, 51)),
        "cat_a": cat_a,
        "cat_b": cat_b,
        "num_1": num_1,
        "num_2": num_2,
        "num_3": num_3,
    })
    df.to_sql(table, engine, if_exists="replace", index=False)

    # Flag every NULL cell (IDs 41-50, all five data columns) as missing
    error_rows = [
        {"row_id": rid, "column_id": col, "error_type": "missing"}
        for col in ["cat_a", "cat_b", "num_1", "num_2", "num_3"]
        for rid in range(41, 51)
    ]
    pd.DataFrame(error_rows).to_sql(
        f"errors_{table}", engine, if_exists="replace", index=False
    )


def _robust_cleanup(table: str, *extra_previews) -> None:
    """Drop the source table, its errors table, and any preview tables."""
    all_tables = [table, f"errors_{table}"]
    for p in extra_previews:
        all_tables += [p, f"errors_{p}"]
    with engine.begin() as conn:
        _drop_tables(conn, *all_tables)


# ── 1D: numeric ───────────────────────────────────────────────────────────────

@pytest.mark.sql
def test_robust_1d_impute_numeric(db_transaction):
    """
    1D numeric: imputing num_1 for IDs 41-45 sets those cells to the column
    mean (41.0).  IDs 46-50 are also NULL but NOT targeted – they must stay NULL.
    All filled rows (1-40) must be byte-identical to the original.
    """
    table = "tp_rb_1d_num"
    _setup_robust_table(table)
    preview_delete = f"{table}_preview_delete"
    preview_impute = f"{table}_preview_impute"

    try:
        resp = flask_app.test_client().post("/api/wrangle/create-previews", json={
            "table": table, "row_ids": _TARGETED, "cols": ["num_1"],
        })
        assert resp.status_code == 200

        imp = pd.read_sql_query(f'SELECT * FROM "{preview_impute}"', engine)
        assert len(imp) == 50

        targeted     = imp[imp["ID"].isin(_TARGETED)]
        non_targeted = imp[imp["ID"].isin(_NONTARGET)]
        filled       = imp[imp["ID"].isin(_FILLED_IDS)]

        # Targeted rows: num_1 filled with the column mean
        assert targeted["num_1"].isna().sum() == 0
        # assert (targeted["num_1"] == pytest.approx(_EXPECTED_IMPUTE["num_1"])).all()
        assert targeted.loc[targeted['ID'] == 41, 'num_1'].values[0] == 41.0
        assert targeted.loc[targeted['ID'] == 42, 'num_1'].values[0] == 41.0
        assert targeted.loc[targeted['ID'] == 43, 'num_1'].values[0] == 41.0
        assert targeted.loc[targeted['ID'] == 44, 'num_1'].values[0] == 41.0
        assert targeted.loc[targeted['ID'] == 45, 'num_1'].values[0] == 41.0
        # Non-targeted NULL rows: num_1 must stay NULL
        assert non_targeted["num_1"].isna().sum() == len(_NONTARGET)

        # Filled rows: num_1 values exactly as written
        orig = pd.DataFrame({"ID": _FILLED_IDS, "num_1": [float(i * 2) for i in _FILLED_IDS]})
        merged = filled.merge(orig, on="ID", suffixes=("_imp", "_orig"))
        assert merged["num_1_imp"].tolist() == pytest.approx(merged["num_1_orig"].tolist())

        # Other columns untouched for all rows (should still have NULLs at 41-50)
        for col in ["cat_a", "cat_b", "num_2", "num_3"]:
            assert imp[imp["ID"].isin(_TARGETED + _NONTARGET)][col].isna().sum() == 10

        # Original table completely unchanged
        orig_df = pd.read_sql_query(f'SELECT * FROM "{table}"', engine)
        assert orig_df["num_1"].isna().sum() == 10
    finally:
        _robust_cleanup(table, preview_delete, preview_impute)


# ── 1D: categorical ───────────────────────────────────────────────────────────

@pytest.mark.sql
def test_robust_1d_impute_categorical(db_transaction):
    """
    1D categorical: imputing cat_a for IDs 41-45 sets those cells to the
    column mode ('X').  IDs 46-50 must stay NULL.
    """
    table = "tp_rb_1d_cat"
    _setup_robust_table(table)
    preview_delete = f"{table}_preview_delete"
    preview_impute = f"{table}_preview_impute"

    try:
        resp = flask_app.test_client().post("/api/wrangle/create-previews", json={
            "table": table, "row_ids": _TARGETED, "cols": ["cat_a"],
        })
        assert resp.status_code == 200

        imp = pd.read_sql_query(f'SELECT * FROM "{preview_impute}"', engine)
        assert len(imp) == 50

        targeted     = imp[imp["ID"].isin(_TARGETED)]
        non_targeted = imp[imp["ID"].isin(_NONTARGET)]

        # Targeted rows: cat_a filled with the mode
        assert targeted["cat_a"].isna().sum() == 0
        assert targeted["cat_a"].tolist() == [_EXPECTED_IMPUTE["cat_a"]] * len(targeted)

        # Non-targeted NULL rows: cat_a must stay NULL
        assert non_targeted["cat_a"].isna().sum() == len(_NONTARGET)

        # Filled rows (1-40) preserve original values
        filled = imp[imp["ID"].isin(_FILLED_IDS)]
        x_filled = filled[filled["ID"] <= 30]
        y_filled = filled[filled["ID"] > 30]
        assert x_filled["cat_a"].tolist() == ["X"] * len(x_filled)
        assert y_filled["cat_a"].tolist() == ["Y"] * len(y_filled)

        # Other columns untouched for NULL rows
        for col in ["cat_b", "num_1", "num_2", "num_3"]:
            assert imp[imp["ID"].isin(_TARGETED + _NONTARGET)][col].isna().sum() == 10

        # Original table unchanged
        orig_df = pd.read_sql_query(f'SELECT * FROM "{table}"', engine)
        assert orig_df["cat_a"].isna().sum() == 10
    finally:
        _robust_cleanup(table, preview_delete, preview_impute)


# ── 2D impute_x: numeric ──────────────────────────────────────────────────────

@pytest.mark.sql
def test_robust_2d_impute_x_numeric(db_transaction):
    """
    2D numeric x: cols=[num_1, num_2].
    preview_impute_x fills num_1 for IDs 41-45 with the mean (41.0).
    - IDs 46-50 (non-targeted NULLs) must stay NULL for num_1.
    - num_2 must be NULL for ALL rows 41-50 in this preview (only num_1 is imputed).
    - Filled rows 1-40 must be unchanged.
    """
    table = "tp_rb_x_num"
    _setup_robust_table(table)
    preview_delete   = f"{table}_preview_delete"
    preview_impute_x = f"{table}_preview_impute_x"
    preview_impute_y = f"{table}_preview_impute_y"

    try:
        resp = flask_app.test_client().post("/api/wrangle/create-previews", json={
            "table": table, "row_ids": _TARGETED, "cols": ["num_1", "num_2"],
        })
        assert resp.status_code == 200

        imp_x = pd.read_sql_query(f'SELECT * FROM "{preview_impute_x}"', engine)
        assert len(imp_x) == 50

        targeted     = imp_x[imp_x["ID"].isin(_TARGETED)]
        non_targeted = imp_x[imp_x["ID"].isin(_NONTARGET)]

        # num_1 filled for targeted, NULL for non-targeted
        assert targeted["num_1"].isna().sum() == 0
        assert targeted["num_1"].tolist() == pytest.approx([_EXPECTED_IMPUTE["num_1"]] * len(targeted))
        assert non_targeted["num_1"].isna().sum() == len(_NONTARGET)

        # num_2 must be untouched in this preview (impute_x only touches num_1)
        assert imp_x[imp_x["ID"].isin(_TARGETED + _NONTARGET)]["num_2"].isna().sum() == 10

        # Filled rows: num_1 and num_2 exactly as written
        filled = imp_x[imp_x["ID"].isin(_FILLED_IDS)]
        assert filled["num_1"].tolist() == pytest.approx([float(i * 2) for i in _FILLED_IDS])
        assert filled["num_2"].tolist() == pytest.approx([float(i * 3) for i in _FILLED_IDS])
    finally:
        _robust_cleanup(table, preview_delete, preview_impute_x, preview_impute_y)


# ── 2D impute_x: categorical ──────────────────────────────────────────────────

@pytest.mark.sql
def test_robust_2d_impute_x_categorical(db_transaction):
    """
    2D categorical x: cols=[cat_a, cat_b].
    preview_impute_x fills cat_a for IDs 41-45 with the mode ('X').
    - IDs 46-50 must stay NULL for cat_a.
    - cat_b must be NULL for ALL rows 41-50 in this preview.
    """
    table = "tp_rb_x_cat"
    _setup_robust_table(table)
    preview_delete   = f"{table}_preview_delete"
    preview_impute_x = f"{table}_preview_impute_x"
    preview_impute_y = f"{table}_preview_impute_y"

    try:
        resp = flask_app.test_client().post("/api/wrangle/create-previews", json={
            "table": table, "row_ids": _TARGETED, "cols": ["cat_a", "cat_b"],
        })
        assert resp.status_code == 200

        imp_x = pd.read_sql_query(f'SELECT * FROM "{preview_impute_x}"', engine)
        assert len(imp_x) == 50

        targeted     = imp_x[imp_x["ID"].isin(_TARGETED)]
        non_targeted = imp_x[imp_x["ID"].isin(_NONTARGET)]

        # cat_a filled for targeted rows with the mode
        assert targeted["cat_a"].isna().sum() == 0
        assert targeted["cat_a"].tolist() == [_EXPECTED_IMPUTE["cat_a"]] * len(targeted)
        assert non_targeted["cat_a"].isna().sum() == len(_NONTARGET)

        # cat_b must be untouched in this preview (only cat_a is imputed)
        assert imp_x[imp_x["ID"].isin(_TARGETED + _NONTARGET)]["cat_b"].isna().sum() == 10

        # Filled rows preserve original category distributions
        filled = imp_x[imp_x["ID"].isin(_FILLED_IDS)]
        x_filled = filled[filled["ID"] <= 30]
        y_filled = filled[filled["ID"] > 30]
        p_filled = filled[filled["ID"] <= 25]
        assert x_filled["cat_a"].tolist() == ["X"] * len(x_filled)
        assert y_filled["cat_a"].tolist() == ["Y"] * len(y_filled)
        assert p_filled["cat_b"].tolist() == ["P"] * len(p_filled)
    finally:
        _robust_cleanup(table, preview_delete, preview_impute_x, preview_impute_y)


# ── 2D impute_y: numeric ──────────────────────────────────────────────────────

@pytest.mark.sql
def test_robust_2d_impute_y_numeric(db_transaction):
    """
    2D numeric y: cols=[num_1, num_2].
    preview_impute_y fills num_2 for IDs 41-45 with the mean (61.5).
    - IDs 46-50 must stay NULL for num_2.
    - num_1 must be NULL for ALL rows 41-50 in this preview (only num_2 is imputed).
    - Filled rows 1-40 must be unchanged.
    """
    table = "tp_rb_y_num"
    _setup_robust_table(table)
    preview_delete   = f"{table}_preview_delete"
    preview_impute_x = f"{table}_preview_impute_x"
    preview_impute_y = f"{table}_preview_impute_y"

    try:
        resp = flask_app.test_client().post("/api/wrangle/create-previews", json={
            "table": table, "row_ids": _TARGETED, "cols": ["num_1", "num_2"],
        })
        assert resp.status_code == 200

        imp_y = pd.read_sql_query(f'SELECT * FROM "{preview_impute_y}"', engine)
        assert len(imp_y) == 50

        targeted     = imp_y[imp_y["ID"].isin(_TARGETED)]
        non_targeted = imp_y[imp_y["ID"].isin(_NONTARGET)]

        # num_2 filled for targeted rows with the mean
        assert targeted["num_2"].isna().sum() == 0
        assert targeted["num_2"].tolist() == pytest.approx([_EXPECTED_IMPUTE["num_2"]] * len(targeted))
        assert non_targeted["num_2"].isna().sum() == len(_NONTARGET)

        # num_1 must be untouched in this preview (impute_y only touches num_2)
        assert imp_y[imp_y["ID"].isin(_TARGETED + _NONTARGET)]["num_1"].isna().sum() == 10

        # Filled rows: both columns exactly as written
        filled = imp_y[imp_y["ID"].isin(_FILLED_IDS)]
        assert filled["num_1"].tolist() == pytest.approx([float(i * 2) for i in _FILLED_IDS])
        assert filled["num_2"].tolist() == pytest.approx([float(i * 3) for i in _FILLED_IDS])

        # Cross-check: preview_impute_x should NOT have touched num_2
        imp_x = pd.read_sql_query(f'SELECT * FROM "{preview_impute_x}"', engine)
        assert imp_x[imp_x["ID"].isin(_TARGETED + _NONTARGET)]["num_2"].isna().sum() == 10
    finally:
        _robust_cleanup(table, preview_delete, preview_impute_x, preview_impute_y)


# ── 2D impute_y: categorical ──────────────────────────────────────────────────

@pytest.mark.sql
def test_robust_2d_impute_y_categorical(db_transaction):
    """
    2D categorical y: cols=[cat_a, cat_b].
    preview_impute_y fills cat_b for IDs 41-45 with the mode ('P').
    - IDs 46-50 must stay NULL for cat_b.
    - cat_a must be NULL for ALL rows 41-50 in this preview (only cat_b is imputed).
    """
    table = "tp_rb_y_cat"
    _setup_robust_table(table)
    preview_delete   = f"{table}_preview_delete"
    preview_impute_x = f"{table}_preview_impute_x"
    preview_impute_y = f"{table}_preview_impute_y"

    try:
        resp = flask_app.test_client().post("/api/wrangle/create-previews", json={
            "table": table, "row_ids": _TARGETED, "cols": ["cat_a", "cat_b"],
        })
        assert resp.status_code == 200

        imp_y = pd.read_sql_query(f'SELECT * FROM "{preview_impute_y}"', engine)
        assert len(imp_y) == 50

        targeted     = imp_y[imp_y["ID"].isin(_TARGETED)]
        non_targeted = imp_y[imp_y["ID"].isin(_NONTARGET)]

        # cat_b filled for targeted rows with the mode
        assert targeted["cat_b"].isna().sum() == 0
        assert targeted["cat_b"].tolist() == [_EXPECTED_IMPUTE["cat_b"]] * len(targeted)
        assert non_targeted["cat_b"].isna().sum() == len(_NONTARGET)

        # cat_a must be untouched in this preview (only cat_b is imputed)
        assert imp_y[imp_y["ID"].isin(_TARGETED + _NONTARGET)]["cat_a"].isna().sum() == 10

        # Filled rows preserve original category distributions
        filled = imp_y[imp_y["ID"].isin(_FILLED_IDS)]
        p_filled = filled[filled["ID"] <= 25]
        q_filled = filled[(filled["ID"] > 25) & (filled["ID"] <= 35)]
        r_filled = filled[(filled["ID"] > 35) & (filled["ID"] <= 40)]
        assert p_filled["cat_b"].tolist() == ["P"] * len(p_filled)
        assert q_filled["cat_b"].tolist() == ["Q"] * len(q_filled)
        assert r_filled["cat_b"].tolist() == ["R"] * len(r_filled)

        # Cross-check: preview_impute_x should NOT have touched cat_b
        imp_x = pd.read_sql_query(f'SELECT * FROM "{preview_impute_x}"', engine)
        assert imp_x[imp_x["ID"].isin(_TARGETED + _NONTARGET)]["cat_b"].isna().sum() == 10
    finally:
        _robust_cleanup(table, preview_delete, preview_impute_x, preview_impute_y)


# ── delete preview: targeted rows only ───────────────────────────────────────

@pytest.mark.sql
def test_robust_delete_targeted_rows_only(db_transaction):
    """
    Delete preview must remove exactly the 5 targeted rows (41-45) and leave
    the 5 non-targeted NULL rows (46-50) intact.

    remove_rows_by_ids only deletes rows that are BOTH in row_ids AND have
    an entry in the errors table.  Since IDs 46-50 are not in row_ids they
    must survive, even though they also have errors.
    """
    table = "tp_rb_del"
    _setup_robust_table(table)
    preview_delete   = f"{table}_preview_delete"
    preview_impute_x = f"{table}_preview_impute_x"
    preview_impute_y = f"{table}_preview_impute_y"

    try:
        resp = flask_app.test_client().post("/api/wrangle/create-previews", json={
            "table": table, "row_ids": _TARGETED, "cols": ["num_1", "num_2"],
        })
        assert resp.status_code == 200

        del_df = pd.read_sql_query(f'SELECT * FROM "{preview_delete}"', engine)

        # Exactly 45 rows remain (50 - 5 targeted)
        assert len(del_df) == 45

        # Targeted IDs are gone
        assert set(del_df["ID"].values).isdisjoint(set(_TARGETED))

        # Non-targeted NULL rows are still present
        assert set(_NONTARGET).issubset(set(del_df["ID"].values))

        # Non-targeted rows still have their NULLs (untouched)
        surviving_nulls = del_df[del_df["ID"].isin(_NONTARGET)]
        for col in ["cat_a", "cat_b", "num_1", "num_2", "num_3"]:
            assert surviving_nulls[col].isna().sum() == len(_NONTARGET)

        # Filled rows 1-40 are all present and unchanged
        assert set(_FILLED_IDS).issubset(set(del_df["ID"].values))
        filled = del_df[del_df["ID"].isin(_FILLED_IDS)]
        assert filled["num_1"].tolist() == pytest.approx([float(i * 2) for i in _FILLED_IDS])

        # Original table is completely unchanged
        orig_df = pd.read_sql_query(f'SELECT * FROM "{table}"', engine)
        assert len(orig_df) == 50
    finally:
        _robust_cleanup(table, preview_delete, preview_impute_x, preview_impute_y)
