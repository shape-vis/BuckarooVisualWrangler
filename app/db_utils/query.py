# ─────────────────────────────────────────────────────────────────────────────
# Data Wrangling Functions for Buckaroo Visual Wrangler
# ─────────────────────────────────────────────────────────────────────────────
from typing import List, Tuple
from sqlalchemy import text
from app import engine
from app.db_utils.detector_sql import missing_cell_predicate
from app.db_utils.execute_sql import quote_identifier

# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────

_NUMERIC_TYPES = {
    "smallint", "integer", "bigint",
    "decimal", "numeric", "real", "double precision"
}

def _is_numeric(conn, col: str, table_name: str) -> bool:
    """Check if a column is numeric."""
    sql = """
        SELECT data_type
        FROM information_schema.columns
        WHERE table_name = :table_name
          AND column_name = :col
    """
    dtype = conn.execute(text(sql), {"table_name": table_name, "col": col}).scalar_one()
    return dtype in _NUMERIC_TYPES


def _ids_in(ids_param: str) -> str:
    """
    Boolean SQL expression that is TRUE when a row's "ID" is in a bound list of IDs.

    The list is unnested into a set and matched with IN, which Postgres answers with a hash join. Matching
    with = ANY(list) instead walks the whole list for every row of the table: with a few thousand IDs on a
    quarter-million-row table, that alone took over ten seconds.

    Parameters
    ----------
    ids_param : str
        Name of the bound parameter holding the IDs, e.g. "ids"
    """
    return f'"ID" IN (SELECT unnest(CAST(:{ids_param} AS bigint[])))'


def _get_errors_table(table: str) -> str:
    """Get errors table name for given table."""
    return f"errors_{table}"


def _get_row_count(conn, table: str) -> int:
    """Get total row count from table."""
    return conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()


def _missing_pred(col: str) -> str:
    """
    Boolean SQL expression that is TRUE when a cell of the column is missing - the detectors' rule, so an impute
    never learns its fill value from a cell the Missing metric counts as missing.
    """
    return missing_cell_predicate(quote_identifier(col))


def _compute_imputation_value(conn, table: str, col: str, is_numeric: bool):
    """
    Compute imputation value: mean for numeric, mode for categorical.

    Parameters
    ----------
    conn : Connection
        Database connection
    table : str
        Table name
    col : str
        Column to compute imputation value for
    is_numeric : bool
        Whether the column is numeric

    Returns
    -------
    Any
        Mean value for numeric columns, mode (most frequent) for categorical
    """
    if is_numeric:
        return conn.execute(
            text(f'SELECT AVG("{col}"::numeric) FROM "{table}" WHERE NOT {_missing_pred(col)}')
        ).scalar()
    else:
        return conn.execute(
            text(f'''
                SELECT "{col}"
                FROM "{table}"
                WHERE NOT {_missing_pred(col)}
                GROUP BY "{col}"
                ORDER BY COUNT(*) DESC
                LIMIT 1
            ''')
        ).scalar()


def imputation_value(table: str, col: str):
    """
    The value an impute of this column would fill with - the same one impute_by_ids computes, so a check made
    before a wrangle and the wrangle itself cannot disagree.

    Returns
    -------
    Any
        Mean value for numeric columns, mode (most frequent) for categorical, or None when the column has no
        clean values to compute one from
    """
    with engine.connect() as conn:
        is_numeric = _is_numeric(conn, col, table)
        return _compute_imputation_value(conn, table, col, is_numeric)


def flagged_row_ids(table: str, columns: List[str], error_type: str) -> List[int]:
    """
    The "ID"s of the rows the errors table flags with one error type in any of the given columns, ascending.
    Joining back to the table drops any flag whose row_id no longer names a live row.

    Parameters
    ----------
    table : str
        Table name
    columns : List[str]
        The columns whose flags count
    error_type : str
        The error type the flags must carry
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(f'''
                SELECT DISTINCT e.row_id
                FROM "{_get_errors_table(table)}" e
                JOIN "{table}" t ON t."ID" = e.row_id
                WHERE e.column_id = ANY(:columns) AND e.error_type = :error_type
                ORDER BY e.row_id
            '''),
            {"columns": columns, "error_type": error_type}
        ).fetchall()

    # Cast explicitly - psycopg2 cannot adapt numpy integer types on the way back out
    row_ids = []
    for row in rows:
        row_ids.append(int(row[0]))
    return row_ids


# ─────────────────────────────────────────────────────────────────────────────
# ID-Based Wrangling (for scatterplot point-based selections)
# ─────────────────────────────────────────────────────────────────────────────

def remove_rows_by_ids(table: str, ids: List[int]) -> int:
    """
    Remove rows by ID in-place (for scatterplot selections).

    Parameters
    ----------
    table : str
        Table name to modify
    ids : List[int]
        List of row IDs to check and potentially remove

    Returns
    -------
    int
        Number of rows remaining
    """
    if not ids:
        return 0

    with engine.begin() as conn:
        conn.execute(
            text(f"""
                DELETE FROM "{table}"
                WHERE {_ids_in("ids")}
            """),
            {"ids": ids}
        )
        n_rows = _get_row_count(conn, table)

    return n_rows


def impute_by_ids(table: str, col: str, ids: List[int]) -> Tuple[int, int]:
    """
    Impute missing values by ID in-place (for scatterplot selections).

    Strategy: mean for numeric, mode for categorical

    Parameters
    ----------
    table : str
        Table name to modify
    col : str
        Column to impute
    ids : List[int]
        List of row IDs to impute

    Returns
    -------
    Tuple[int, int]
        (rows_examined, cells_imputed)
    """
    if not ids:
        return 0, 0

    with engine.begin() as conn:
        is_numeric = _is_numeric(conn, col, table)
        fill_val = _compute_imputation_value(conn, table, col, is_numeric)

        result = conn.execute(
            text(f'''
                        UPDATE "{table}"
                        SET "{col}" = :fill_val
                        WHERE {_ids_in("ids")}
                    '''),
            {"fill_val": fill_val, "ids": ids}
        )

        return len(ids), result.rowcount
