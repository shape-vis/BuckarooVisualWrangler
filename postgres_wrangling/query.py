# ─────────────────────────────────────────────────────────────────────────────
# Data Wrangling Functions for Buckaroo Visual Wrangler
# ─────────────────────────────────────────────────────────────────────────────
from typing import Dict, Any, List, Tuple
from sqlalchemy import text, Engine
from app import engine


# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────

_NUMERIC_TYPES = {
    "smallint", "integer", "bigint",
    "decimal", "numeric", "real", "double precision"
}


def _is_numeric(conn, col: str, table_name: str) -> bool:
    """Check if a column is numeric."""
    sql = f"""
        SELECT data_type
        FROM information_schema.columns
        WHERE table_name = '{table_name}'
          AND column_name = :col
    """
    dtype = conn.execute(text(sql), {"col": col}).scalar_one()
    return dtype in _NUMERIC_TYPES


def _get_errors_table(table: str) -> str:
    """Get errors table name for given table."""
    return f"errors_{table}"


def _get_row_count(conn, table: str) -> int:
    """Get total row count from table."""
    return conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()


def _missing_pred(col: str) -> str:
    """Boolean SQL expression that is TRUE when column is 'missing'."""
    return (
        f"(\"{col}\" IS NULL "
        f"OR LOWER(\"{col}\"::text) IN ('', 'null', 'undefined', 'nan', 'none'))"
    )


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


def _get_numeric_bin_bounds(scale, bin_idx: int) -> Tuple[float, float]:
    """
    Extract (low, high) boundaries from numeric scale at given index.

    Parameters
    ----------
    scale : dict
        Scale dictionary with 'numeric' key containing bin boundaries
    bin_idx : int
        Index of the bin

    Returns
    -------
    Tuple[float, float]
        (low_bound, high_bound) for the bin
    """
    bounds = scale["numeric"][int(bin_idx)]
    return bounds["x0"], bounds["x1"]


# ─────────────────────────────────────────────────────────────────────────────
# ID-Based Wrangling (for scatterplot point-based selections)
# ─────────────────────────────────────────────────────────────────────────────

def remove_rows_by_ids(table: str, ids: List[int]) -> int:
    """
    Remove rows by ID in-place (for scatterplot selections).

    Only removes rows that have errors in the errors table.
    Uses errors table as single source of truth for error detection.

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

    errors_table = _get_errors_table(table)

    with engine.begin() as conn:
        # Only delete rows that are both in the ID list AND have errors
        conn.execute(
            text(f"""
                DELETE FROM "{table}"
                WHERE "ID" IN (
                    SELECT t."ID"
                    FROM "{table}" t
                    JOIN "{errors_table}" e ON t."ID" = e.row_id
                    WHERE t."ID" = ANY(:ids)
                )
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

        # Apply imputation
        result = conn.execute(
            text(f'''
                UPDATE "{table}"
                SET "{col}" = :fill_val
                WHERE "ID" = ANY(:ids)
                  AND {_missing_pred(col)}
            '''),
            {"fill_val": fill_val, "ids": ids}
        )

        return len(ids), result.rowcount


# ─────────────────────────────────────────────────────────────────────────────
# Preview-specific wrangling (unconditional — used for create-previews only)
# ─────────────────────────────────────────────────────────────────────────────

def remove_rows_by_ids_preview(table: str, ids: List[int]) -> int:
    """
    Remove ALL specified rows unconditionally (no errors-table filter).
    Used for preview tables so the user can see what deletion would look like
    regardless of whether the rows currently have detected errors.

    Parameters
    ----------
    table : str
        Preview table name to modify
    ids : List[int]
        List of row IDs to delete

    Returns
    -------
    int
        Number of rows remaining
    """
    if not ids:
        return 0

    with engine.begin() as conn:
        conn.execute(
            text(f'DELETE FROM "{table}" WHERE "ID" = ANY(:ids)'),
            {"ids": ids}
        )
        n_rows = _get_row_count(conn, table)

    return n_rows


def impute_by_ids_preview(table: str, col: str, ids: List[int]) -> Tuple[int, int]:
    """
    Impute ALL selected rows unconditionally — sets every selected row's
    column value to mean (numeric) or mode (categorical), regardless of
    whether the value is currently missing.  Used for preview tables.

    Parameters
    ----------
    table : str
        Preview table name to modify
    col : str
        Column to impute
    ids : List[int]
        List of row IDs to impute

    Returns
    -------
    Tuple[int, int]
        (rows_examined, cells_updated)
    """
    if not ids:
        return 0, 0

    with engine.begin() as conn:
        is_numeric = _is_numeric(conn, col, table)
        fill_val = _compute_imputation_value(conn, table, col, is_numeric)

        result = conn.execute(
            text(f'UPDATE "{table}" SET "{col}" = :fill_val WHERE "ID" = ANY(:ids)'),
            {"fill_val": fill_val, "ids": ids}
        )

    return len(ids), result.rowcount


def delete_column(table: str, column: str) -> int:
    """
    Delete a column from a table in-place.

    Parameters
    ----------
    table : str
        Table name to modify
    column : str
        Column name to delete

    Returns
    -------
    int
        Number of columns remaining in table
    """
    with engine.begin() as conn:
        # Drop the column
        conn.execute(
            text(f'ALTER TABLE "{table}" DROP COLUMN IF EXISTS "{column}"')
        )

        # Count remaining columns
        result = conn.execute(
            text("""
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_name = :table
            """),
            {"table": table}
        )
        n_cols = result.scalar_one()

    return n_cols


# ─────────────────────────────────────────────────────────────────────────────
# 1D Bin-Based Wrangling (for 1D histogram/barchart repair workflow)
# ─────────────────────────────────────────────────────────────────────────────

def remove_flagged_rows_in_1d_bin(
    current_selection: dict,
    col: str,
    table: str,
) -> int:
    """
    Remove rows in-place from a 1-D histogram bin that have quality flags.

    Uses errors table as single source of truth for error detection.

    Parameters
    ----------
    current_selection : dict
        The selection object from 1D histogram (barchart)
    col : str
        Column name to wrangle
    table : str
        Table name to modify in-place

    Returns
    -------
    int
        Number of rows remaining in table
    """
    sel = current_selection["data"][0]
    bin_value = sel["bin"]
    bin_type = sel["type"]

    errors_table = _get_errors_table(table)

    # Get bin boundaries from scale
    if bin_type == "numeric":
        # For numeric bins, bin value is an index into the numeric scale array
        x_lo, x_hi = _get_numeric_bin_bounds(current_selection["scaleX"], bin_value)

        sql = f"""
        DELETE FROM "{table}"
        WHERE "ID" IN (
            SELECT t."ID"
            FROM "{table}" t
            JOIN "{errors_table}" e ON t."ID" = e.row_id
            WHERE t."{col}" >= :x_lo
              AND t."{col}" <= :x_hi
              AND e.column_id = :col_name
        )
        """
        params = {"x_lo": x_lo, "x_hi": x_hi, "col_name": col}
    else:
        # Categorical - bin value IS the category value, not an index
        cat_value = bin_value

        sql = f"""
        DELETE FROM "{table}"
        WHERE "ID" IN (
            SELECT t."ID"
            FROM "{table}" t
            JOIN "{errors_table}" e ON t."ID" = e.row_id
            WHERE t."{col}" = :cat_val
              AND e.column_id = :col_name
        )
        """
        params = {"cat_val": cat_value, "col_name": col}

    with engine.begin() as conn:
        conn.execute(text(sql), params)
        n_rows = _get_row_count(conn, table)

    return n_rows


def impute_1d_bin_in_place(
    current_selection: dict,
    col: str,
    table: str,
) -> Tuple[int, int]:
    """
    Impute missing values in-place in a 1-D histogram bin.

    Strategy: mean for numeric, mode for categorical

    Parameters
    ----------
    current_selection : dict
        The selection object from 1D histogram (barchart)
    col : str
        Column name to impute
    table : str
        Table name to modify in-place

    Returns
    -------
    Tuple[int, int]
        (rows_examined, cells_imputed)
    """
    sel = current_selection["data"][0]
    bin_value = sel["bin"]
    bin_type = sel["type"]

    with engine.begin() as conn:
        is_numeric = _is_numeric(conn, col, table)

        # Build WHERE clause for the bin
        if bin_type == "numeric":
            # For numeric bins, bin value is an index into the numeric scale array
            x_lo, x_hi = _get_numeric_bin_bounds(current_selection["scaleX"], bin_value)
            bin_where_sql = f'"{col}" >= :x_lo AND "{col}" <= :x_hi'
            params = {"x_lo": x_lo, "x_hi": x_hi}
        else:
            # Categorical - bin value IS the category value, not an index
            cat_value = bin_value
            bin_where_sql = f'"{col}" = :cat_val'
            params = {"cat_val": cat_value}

        # Count rows in bin
        rows_examined = conn.execute(
            text(f'SELECT COUNT(*) FROM "{table}" WHERE {bin_where_sql}'),
            params,
        ).scalar_one()

        if rows_examined == 0:
            return 0, 0

        # Compute imputation value
        fill_val = _compute_imputation_value(conn, table, col, is_numeric)

        # Apply imputation
        upd_sql = text(f'''
            UPDATE "{table}"
            SET "{col}" = :fill_val
            WHERE {bin_where_sql}
              AND {_missing_pred(col)}
        ''')
        result = conn.execute(upd_sql, dict(params, fill_val=fill_val))
        cells_imputed = result.rowcount

    return rows_examined, cells_imputed


# ─────────────────────────────────────────────────────────────────────────────
# 2D Bin-Based Wrangling (for 2D histogram/heatmap repair workflow)
# ─────────────────────────────────────────────────────────────────────────────

def remove_flagged_rows_in_bin(
    current_selection: dict,
    cols: list[str],
    table: str,
) -> int:
    """
    Remove rows in-place from a 2-D bin that have quality flags.

    Removes rows that:
    1. Fall inside the selected 2-D histogram bin
    2. Have any error in the errors table for either X or Y column

    Uses errors table as single source of truth for error detection.

    Parameters
    ----------
    current_selection : dict
        The object returned by the histogram endpoint
    cols : list[str]
        [x_col, y_col] (x = numeric, y = categorical)
    table : str
        Table name to modify in-place

    Returns
    -------
    int
        Number of rows remaining in table
    """
    sel   = current_selection["data"][0]
    x_bin = sel["xBin"]
    y_val = sel["yBin"]

    # Numeric x-axis boundaries (lo ≤ value < hi)
    x_lo, x_hi = _get_numeric_bin_bounds(current_selection["scaleX"], x_bin)

    errors_table = _get_errors_table(table)

    # Delete rows that are in the bin AND have errors in the errors table
    sql = f"""
    DELETE FROM "{table}"
    WHERE "ID" IN (
        SELECT t."ID"
        FROM "{table}" t
        JOIN "{errors_table}" e ON t."ID" = e.row_id
        WHERE
            /* Bin filter */
            t."{cols[0]}" >= :x_lo
            AND t."{cols[0]}" <= :x_hi
            AND t."{cols[1]}" = :y_val

            /* Has error in either X or Y column */
            AND e.column_id IN (:col_x, :col_y)
    )
    """

    with engine.begin() as conn:
        conn.execute(
            text(sql),
            {
                "x_lo": x_lo,
                "x_hi": x_hi,
                "y_val": y_val,
                "col_x": cols[0],
                "col_y": cols[1]
            }
        )
        n_rows = _get_row_count(conn, table)

    return n_rows


def _bin_predicate(
    *,
    bin_val: Any,
    bin_type: str,
    scale: Dict[str, Any],
    col: str,
    params: Dict[str, Any],
    pfx: str,
) -> str:
    """
    Return a SQL WHERE-clause fragment that matches rows in a histogram bin.
    Adds bound parameters to params dict.
    """
    if bin_type == "numeric":
        if bin_val == 0:  # NULL bucket
            return _missing_pred(col)
        edge = scale["numeric"][bin_val]
        lo, hi = edge["x0"], edge["x1"]
        lo_key = f"{pfx}lo"
        hi_key = f"{pfx}hi"
        params[lo_key], params[hi_key] = lo, hi
        # Use inclusive upper bound for all bins to match width_bucket behavior
        return f"\"{col}\" >= :{lo_key} AND \"{col}\" <= :{hi_key}"
    else:  # categorical
        if bin_val == "__NULL__":
            return _missing_pred(col)
        key = f"{pfx}_cat"
        params[key] = bin_val
        return f"\"{col}\" = :{key}"


def impute_bin_in_place(
    current_selection: Dict[str, Any],
    cols: List[str],
    table: str,
) -> Tuple[int, int]:
    """
    Impute missing values in-place in a selected 2-D histogram bin.

    Imputation strategy:
    - Numeric columns: mean (AVG)
    - Categorical columns: mode (most-common non-NULL)

    Parameters
    ----------
    current_selection : Dict[str, Any]
        Histogram bin selection from frontend
    cols : List[str]
        [x_column, y_column]
    table : str
        Table name to modify in-place

    Returns
    -------
    Tuple[int, int]
        (rows_examined, cells_imputed)
    """
    if len(cols) != 2:
        raise ValueError("cols must be exactly [x_column, y_column]")

    x_col, y_col = cols
    sel = current_selection["data"][0]
    params: Dict[str, Any] = {}

    # Build WHERE predicate for selected bin
    where_parts = [
        _bin_predicate(
            bin_val=sel["xBin"],
            bin_type=sel["xType"],
            scale=current_selection["scaleX"],
            col=x_col,
            params=params,
            pfx="x",
        ),
        _bin_predicate(
            bin_val=sel["yBin"],
            bin_type=sel["yType"],
            scale=current_selection["scaleY"],
            col=y_col,
            params=params,
            pfx="y",
        ),
    ]
    bin_where_sql = " AND ".join(where_parts)

    with engine.begin() as conn:
        # Count rows in bin
        rows_examined = conn.execute(
            text(f'SELECT COUNT(*) FROM "{table}" WHERE {bin_where_sql}'),
            params,
        ).scalar_one()

        if rows_examined == 0:
            return 0, 0

        # Compute imputation values for each column
        modes_or_means: Dict[str, Any] = {}
        for col in cols:
            is_numeric = _is_numeric(conn, col, table)
            val = _compute_imputation_value(conn, table, col, is_numeric)

            # Fallback if whole column is NULL
            if val is None:
                val = conn.execute(
                    text(f'SELECT "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL LIMIT 1')
                ).scalar()

            modes_or_means[col] = val

        # Apply imputation column-by-column
        cells_imputed = 0
        for col in cols:
            upd_sql = text(
                f'''
                UPDATE "{table}"
                SET    "{col}" = :fill_val
                WHERE  {bin_where_sql}
                  AND  {_missing_pred(col)}
                '''
            )
            rc = conn.execute(upd_sql, dict(params, fill_val=modes_or_means[col])).rowcount
            cells_imputed += rc

    return rows_examined, cells_imputed
