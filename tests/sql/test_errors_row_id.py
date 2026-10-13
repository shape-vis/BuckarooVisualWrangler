"""
Regression tests for the errors-table contract: errors_<t>.row_id names a row by its "ID",
never by its position in the table.

Everything that reads errors_<t> joins it back to the data on t."ID" = e.row_id - the plots, the
metrics and the AI suggestion path all do. That join is only meaningful if row_id really is an "ID".
On a freshly uploaded table an "ID" and a position agree, so a mix-up only shows on a table with gaps
in its IDs - which is what every table is once rows have been deleted.
"""
import pytest
import pandas as pd
from sqlalchemy import text as sa_text

from app import engine
from app.db_utils.detector_sql import DetectorSQL


def _drop_tables(conn, *names):
    for name in names:
        conn.execute(sa_text(f'DROP TABLE IF EXISTS "{name}"'))


@pytest.mark.sql
def test_row_id_is_the_id_not_the_position(db_transaction):
    """A gapped ID sequence: row_id must be the "ID", not the row's 0-based-plus-one position."""
    table = "t_errid_gapped"
    # IDs deliberately not 1..N, so position and ID can never be confused.
    # The blank amount sits at position 3 but carries ID 30.
    df = pd.DataFrame({
        "ID": [10, 20, 30, 40, 50],
        "amount": [1.0, 2.0, None, 4.0, 5.0],
    })
    df.to_sql(table, engine, if_exists="replace", index=False)

    try:
        DetectorSQL(engine, table).generate_errors_table()

        errors = pd.read_sql_query(f'SELECT * FROM "errors_{table}"', engine)
        missing = errors[(errors["column_id"] == "amount") & (errors["error_type"] == "missing")]

        assert len(missing) == 1, f"expected one missing flag on amount, got:\n{errors}"
        assert int(missing.iloc[0]["row_id"]) == 30, (
            "row_id is the row's position, not its ID. "
            f'Got {missing.iloc[0]["row_id"]}, expected 30.'
        )
    finally:
        with engine.begin() as conn:
            _drop_tables(conn, table, f"errors_{table}")


@pytest.mark.sql
def test_every_row_id_joins_back_to_a_real_row(db_transaction):
    """After rows are deleted, no error row may reference an ID that is gone."""
    table = "t_errid_orphan"
    df = pd.DataFrame({
        "ID": [1, 2, 3, 4, 5, 6],
        "amount": [1.0, None, 3.0, None, 5.0, 6.0],
        "label": ["a", "b", None, "d", "e", "f"],
    })
    df.to_sql(table, engine, if_exists="replace", index=False)

    try:
        DetectorSQL(engine, table).generate_errors_table()

        # Drop the two rows carrying the blank amounts, then re-detect.
        with engine.begin() as conn:
            conn.execute(sa_text(f'DELETE FROM "{table}" WHERE "ID" IN (2, 4)'))
        DetectorSQL(engine, table).generate_errors_table()

        orphans = pd.read_sql_query(
            f'SELECT e.row_id FROM "errors_{table}" e '
            f'LEFT JOIN "{table}" t ON t."ID" = e.row_id WHERE t."ID" IS NULL',
            engine,
        )
        assert orphans.empty, (
            f"errors_{table} still references deleted rows: {orphans['row_id'].tolist()}"
        )
    finally:
        with engine.begin() as conn:
            _drop_tables(conn, table, f"errors_{table}")


@pytest.mark.sql
def test_flags_survive_on_the_columns_not_wrangled(db_transaction):
    """A full rebuild keeps flags for every column, not just the one just wrangled."""
    table = "t_errid_allcols"
    df = pd.DataFrame({
        "ID": [1, 2, 3, 4],
        "amount": [1.0, None, 3.0, 4.0],
        "label": ["a", None, "c", "d"],
    })
    df.to_sql(table, engine, if_exists="replace", index=False)

    try:
        DetectorSQL(engine, table).generate_errors_table()

        errors = pd.read_sql_query(f'SELECT * FROM "errors_{table}"', engine)
        flagged_columns = set(errors["column_id"])
        assert {"amount", "label"} <= flagged_columns, (
            f"expected flags on both columns, got {flagged_columns}"
        )
        # "ID" is structural - DetectorSQL skips it - so it must never be flagged.
        assert "ID" not in flagged_columns
    finally:
        with engine.begin() as conn:
            _drop_tables(conn, table, f"errors_{table}")
