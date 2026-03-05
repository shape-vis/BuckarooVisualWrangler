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
        f"OR \"{col}\"::text IN ('', 'null', 'undefined'))"
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


# ─────────────────────────────────────────────────────────────────────────────
# DEPRECATED FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

import numpy as np
import pandas as pd


def _numeric_scale(lo: float, hi: float, bins: int, axis: str) -> List[Dict[str, float]]:
    """Evenly-spaced numeric bin-boundaries."""
    if lo == hi:
        hi += 1.0
    step = (hi - lo) / bins
    k0, k1 = f"{axis}0", f"{axis}1"
    return [{k0: lo + i * step, k1: lo + (i + 1) * step} for i in range(bins)]


def generate_2d_histogram_data(
    x_column: str,
    y_column: str,
    bins_x: int,
    bins_y: int,
    min_id: int,
    max_id: int,
    table_name: str,
    whole_table: bool = False,
) -> Dict[str, Any]:
    """
    DEPRECATED: Use db_functions.generate_two_d_histogram_with_errors instead.

    Build a dense 2-D histogram with quality metrics.
    """
    numeric_regex = r'^-?\d+(?:\.\d+)?$'
    NULL_NUM_BIN = 0
    NULL_CAT_BIN = '__NULL__'

    range_where = '' if whole_table else 'WHERE "index" BETWEEN :lo AND :hi'
    range_params = {} if whole_table else {"lo": min_id, "hi": max_id}

    print(x_column, y_column, bins_x, bins_y, min_id, max_id, table_name)

    with engine.connect() as conn:
        # Column types
        x_is_num = _is_numeric(conn, x_column, table_name=table_name)
        y_is_num = _is_numeric(conn, y_column, table_name=table_name)

        # Numeric bounds
        bounds_sql = f"""
            SELECT
                {'MIN("' + x_column + '")::numeric, MAX("' + x_column + '")::numeric' if x_is_num else 'NULL, NULL'},
                {'MIN("' + y_column + '")::numeric, MAX("' + y_column + '")::numeric' if y_is_num else 'NULL, NULL'}
            FROM {table_name}
            {range_where}
        """
        xmin, xmax, ymin, ymax = conn.execute(text(bounds_sql), range_params).fetchone()

        # Stats for anomaly detection
        mean_x = std_x = mean_y = std_y = None
        if x_is_num:
            mean_x, std_x = conn.execute(
                text(f"""
                    SELECT AVG("{x_column}")::numeric,
                           STDDEV_SAMP("{x_column}")::numeric
                    FROM {table_name}
                    {range_where}
                """),
                range_params,
            ).fetchone() or (0, 0)
        if y_is_num:
            mean_y, std_y = conn.execute(
                text(f"""
                    SELECT AVG("{y_column}")::numeric,
                           STDDEV_SAMP("{y_column}")::numeric
                    FROM {table_name}
                    {range_where}
                """),
                range_params,
            ).fetchone() or (0, 0)

        # Flag expressions
        anomaly_x_expr = (
            f"ABS((CAST(\"{x_column}\" AS numeric) - :mean_x) / NULLIF(:std_x,0)) > 2"
            if x_is_num else "FALSE"
        )
        anomaly_y_expr = (
            f"ABS((CAST(\"{y_column}\" AS numeric) - :mean_y) / NULLIF(:std_y,0)) > 2"
            if y_is_num else "FALSE"
        )
        mismatch_x_expr = (
            f"NOT (\"{x_column}\"::text ~ :num_re)" if x_is_num
            else f"(\"{x_column}\"::text ~ :num_re)"
        )
        mismatch_y_expr = (
            f"NOT (\"{y_column}\"::text ~ :num_re)" if y_is_num
            else f"(\"{y_column}\"::text ~ :num_re)"
        )
        incomplete_x_expr = (
            "FALSE" if x_is_num
            else f"COUNT(*) OVER (PARTITION BY COALESCE(\"{x_column}\"::text,'{NULL_CAT_BIN}')) < 10"
        )
        incomplete_y_expr = (
            "FALSE" if y_is_num
            else f"COUNT(*) OVER (PARTITION BY COALESCE(\"{y_column}\"::text,'{NULL_CAT_BIN}')) < 10"
        )
        missing_expr = (
            f"(\"{x_column}\" IS NULL OR \"{y_column}\" IS NULL "
            f"OR \"{x_column}\"::text IN ('', 'null', 'undefined') "
            f"OR \"{y_column}\"::text IN ('', 'null', 'undefined'))"
        )

        # Full x / y bin sets
        if x_is_num:
            x_vals_cte = "SELECT generate_series(:null_num_bin, :bins_x - 1) AS x_bin"
        else:
            x_vals_cte = f"""
              SELECT DISTINCT COALESCE("{x_column}"::text, '{NULL_CAT_BIN}') AS x_bin
              FROM {table_name}
              {range_where}
            """
        if y_is_num:
            y_vals_cte = "SELECT generate_series(:null_num_bin, :bins_y - 1) AS y_bin"
        else:
            y_vals_cte = f"""
              SELECT DISTINCT COALESCE("{y_column}"::text, '{NULL_CAT_BIN}') AS y_bin
              FROM {table_name}
              {range_where}
            """

        # Bin mapping
        x_sel = (
            f"COALESCE(width_bucket(\"{x_column}\", :xmin, :xmax, :bins_x) - 1, :null_num_bin)"
            if x_is_num else f"COALESCE(\"{x_column}\"::text, '{NULL_CAT_BIN}')"
        )
        y_sel = (
            f"COALESCE(width_bucket(\"{y_column}\", :ymin, :ymax, :bins_y) - 1, :null_num_bin)"
            if y_is_num else f"COALESCE(\"{y_column}\"::text, '{NULL_CAT_BIN}')"
        )

        # Main aggregation
        slice_sql = f"""
        WITH slice AS (
            SELECT
                {x_sel} AS x_bin,
                {y_sel} AS y_bin,
                ({anomaly_x_expr} OR {anomaly_y_expr})               AS anomaly,
                {missing_expr}                                        AS missing,
                ({incomplete_x_expr} OR {incomplete_y_expr})         AS incomplete,
                ({mismatch_x_expr}  OR {mismatch_y_expr})            AS mismatch
            FROM {table_name}
            {range_where}
        ),
        counts AS (
            SELECT
                x_bin, y_bin,
                COUNT(*)                 AS items,
                SUM(anomaly::int)        AS anomaly,
                SUM(missing::int)        AS missing,
                SUM(incomplete::int)     AS incomplete,
                SUM(mismatch::int)       AS mismatch
            FROM slice
            GROUP BY 1, 2
        ),
        x_vals AS ({x_vals_cte}),
        y_vals AS ({y_vals_cte})
        SELECT
            x_vals.x_bin,
            y_vals.y_bin,
            COALESCE(counts.items,      0) AS items,
            COALESCE(counts.anomaly,    0) AS anomaly,
            COALESCE(counts.missing,    0) AS missing,
            COALESCE(counts.incomplete, 0) AS incomplete,
            COALESCE(counts.mismatch,   0) AS mismatch
        FROM x_vals
        CROSS JOIN y_vals
        LEFT JOIN counts
          ON counts.x_bin = x_vals.x_bin
         AND counts.y_bin = y_vals.y_bin
        ORDER BY 1, 2;
        """

        params = {
            "bins_x": bins_x,
            "bins_y": bins_y,
            "xmin": xmin if xmin is not None else 0,
            "xmax": xmax if xmax is not None else 1,
            "ymin": ymin if ymin is not None else 0,
            "ymax": ymax if ymax is not None else 1,
            "mean_x": mean_x,
            "std_x": std_x,
            "mean_y": mean_y,
            "std_y": std_y,
            "num_re": numeric_regex,
            "null_num_bin": NULL_NUM_BIN,
            **range_params,
        }

        rows = conn.execute(text(slice_sql), params).fetchall()

        # Build axis scales
        scaleX = {"numeric": [], "categorical": []}
        scaleY = {"numeric": [], "categorical": []}

        if x_is_num:
            scaleX["numeric"] = _numeric_scale(float(params["xmin"]),
                                               float(params["xmax"]), bins_x, "x")
        else:
            scaleX["categorical"] = [
                r[0] for r in conn.execute(text(x_vals_cte), params)
            ]
        if y_is_num:
            scaleY["numeric"] = _numeric_scale(float(params["ymin"]),
                                               float(params["ymax"]), bins_y, "y")
        else:
            scaleY["categorical"] = [
                r[0] for r in conn.execute(text(y_vals_cte), params)
            ]

        # Pack result
        histograms = []
        for r in rows:
            count = {"items": int(r.items)}
            for key in ("anomaly", "missing", "incomplete", "mismatch"):
                val = getattr(r, key)
                if val:
                    count[key] = int(val)
            histograms.append(
                {
                    "count": count,
                    "xBin": int(r.x_bin) if x_is_num else r.x_bin,
                    "yBin": int(r.y_bin) if y_is_num else r.y_bin,
                    "xType": "numeric" if x_is_num else "categorical",
                    "yType": "numeric" if y_is_num else "categorical",
                }
            )

    return {"histograms": histograms, "scaleX": scaleX, "scaleY": scaleY}


def copy_and_impute_bin_df(
    current_selection: Dict[str, Any],
    cols: List[str],
    df: pd.DataFrame,
) -> List[int]:
    """
    DEPRECATED: Pandas version - locate rows in histogram bin that need imputation.
    """
    if len(cols) != 2:
        raise ValueError("cols must be exactly [x_column, y_column]")

    x_col, y_col = cols
    sel = current_selection["data"][0]
    sentinels = {"null", "undefined"}

    def _axis_mask(col: str, axis: str) -> pd.Series:
        if sel[f"{axis}Type"] == "categorical":
            return (
                df[col]
                .astype(str)
                .str.lower()
                .eq(str(sel[f"{axis}Bin"]).lower())
                & df[col].notna()
            )
        else:  # numeric
            bins = current_selection[f"scale{axis.upper()}"]["numeric"]
            idx = sel[f"{axis}Bin"]
            lo, hi = bins[idx][f"{axis}0"], bins[idx][f"{axis}1"]

            s = pd.to_numeric(df[col], errors="coerce")
            if idx == len(bins) - 1:
                return (s >= lo) & (s <= hi)
            return (s >= lo) & (s < hi)

    in_x_bin = _axis_mask(x_col, "x")
    in_y_bin = _axis_mask(y_col, "y")
    in_bin = in_x_bin | in_y_bin

    if not in_bin.any():
        return []

    sub_df = df.loc[in_bin, cols]
    str_vals = sub_df.apply(lambda s: s.astype(str).str.lower())
    miss_mask = sub_df.isna() | str_vals.isin(sentinels)

    return sub_df.index[miss_mask.any(axis=1)].astype(int).tolist()


def impute_at_indices_copy(
    df: pd.DataFrame,
    cols: List[str],
    row_indices: List[int],
    *,
    sentinel: set = None,
) -> pd.DataFrame:
    """
    DEPRECATED: Pandas version - impute cells at specific indices.
    """
    from pandas.api.types import is_numeric_dtype

    sentinel = {s.lower() for s in (sentinel or {"null", "undefined"})}
    idx_set = set(row_indices)

    out = df.copy(deep=True)

    for col in cols:
        col_series = out[col]

        clean_col = (
            col_series
            .mask(col_series.astype(str).str.lower().isin(sentinel))
            .dropna()
        )
        if clean_col.empty:
            continue

        fill_value: Any
        if is_numeric_dtype(col_series):
            fill_value = clean_col.astype(float).mean()
        else:
            fill_value = clean_col.mode(dropna=True).iloc[0]

        target_mask = (
            out.index.to_series().isin(idx_set) &
            (
                col_series.isna() |
                col_series.astype(str).str.lower().isin(sentinel)
            )
        )

        out.loc[target_mask, col] = fill_value

    return out


def remove_anomalous_rows(
    current_selection: Dict[str, Any],
    cols: List[str],
    df: pd.DataFrame,
    *,
    z_threshold: float = 2.0,
    min_numeric_values: int = 10,
    skip_cols: List[str] | None = None,
) -> pd.DataFrame:
    """
    DEPRECATED: Pandas version - remove rows with outliers in selected bin.
    """
    if len(cols) != 2:
        raise ValueError("cols must be exactly [x_column, y_column]")
    if skip_cols is None:
        skip_cols = []

    x_col, y_col = cols
    sel = current_selection["data"][0]

    def _mask_for_axis(
        axis_col: str,
        axis_scale: Dict[str, Any],
        bin_val: Any,
        bin_type: str,
    ) -> pd.Series:
        if bin_type == "numeric":
            try:
                lo, hi = (
                    axis_scale["numeric"][bin_val]["x0"],
                    axis_scale["numeric"][bin_val]["x1"],
                )
            except (IndexError, KeyError, TypeError):
                raise ValueError(f"Cannot locate numeric bin {bin_val} "
                                 f"for column {axis_col!r}")
            col_num = pd.to_numeric(df[axis_col], errors="coerce")
            if bin_val == len(axis_scale["numeric"]) - 1:
                return (col_num >= lo) & (col_num <= hi)
            return (col_num >= lo) & (col_num < hi)

        elif bin_type == "categorical":
            return df[axis_col].astype(str) == str(bin_val)

        else:
            raise ValueError(f"Unknown bin type {bin_type!r} "
                             f"for column {axis_col!r}")

    mask_x = _mask_for_axis(
        axis_col=x_col,
        axis_scale=current_selection["scaleX"],
        bin_val=sel["xBin"],
        bin_type=sel["xType"],
    )
    mask_y = _mask_for_axis(
        axis_col=y_col,
        axis_scale=current_selection["scaleY"],
        bin_val=sel["yBin"],
        bin_type=sel["yType"],
    )

    rows_in_bin = mask_x & mask_y

    row_is_anomalous = pd.Series(False, index=df.index)

    for col in df.columns:
        if col in skip_cols:
            continue

        numeric_col = pd.to_numeric(df[col], errors="coerce")
        if numeric_col.notna().sum() < min_numeric_values:
            continue

        mean, std = numeric_col.mean(), numeric_col.std()
        if std == 0 or np.isnan(std):
            continue

        z_mask = (np.abs(numeric_col - mean) > z_threshold * std)
        row_is_anomalous |= z_mask.fillna(False)

    to_drop = row_is_anomalous & rows_in_bin
    cleaned_df = df.loc[~to_drop].copy()

    return cleaned_df


def remove_problematic_rows(
    current_selection: Dict[str, Any],
    cols: List[str],
    df: pd.DataFrame,
    *,
    z_threshold: float = 2.0,
    min_numeric_values: int = 10,
    skip_cols: List[str] | None = None,
    rare_category_threshold: int = 3,
) -> pd.DataFrame:
    """
    DEPRECATED: Pandas version - remove rows with any quality issues in selected bin.
    """
    if len(cols) != 2:
        raise ValueError("cols must be exactly [x_column, y_column]")
    if skip_cols is None:
        skip_cols = []

    x_col, y_col = cols
    sel = current_selection["data"][0]

    def _mask_for_axis(axis_col, axis_scale, bin_val, bin_type):
        if bin_type == "numeric":
            lo, hi = axis_scale["numeric"][bin_val]["x0"], axis_scale["numeric"][bin_val]["x1"]
            col_num = pd.to_numeric(df[axis_col], errors="coerce")
            return (col_num >= lo) & ((col_num <= hi) if bin_val == len(axis_scale["numeric"])-1 else (col_num < hi))
        elif bin_type == "categorical":
            return df[axis_col].astype(str) == str(bin_val)
        raise ValueError(f"Unknown bin type {bin_type!r} for {axis_col!r}")

    rows_in_bin = (
        _mask_for_axis(x_col, current_selection["scaleX"], sel["xBin"], sel["xType"])
        & _mask_for_axis(y_col, current_selection["scaleY"], sel["yBin"], sel["yType"])
    )

    # Numeric outliers
    row_anomaly = pd.Series(False, index=df.index)
    for col in df.columns.drop(skip_cols):
        numeric = pd.to_numeric(df[col], errors="coerce")
        if numeric.notna().sum() < min_numeric_values:
            continue
        std = numeric.std()
        if std == 0 or np.isnan(std):
            continue
        row_anomaly |= (np.abs(numeric - numeric.mean()) > z_threshold * std).fillna(False)

    # Missing values
    sentinel = {"null", "undefined", ""}
    str_df = df.astype(str).apply(lambda s: s.str.lower())
    row_missing = (df.isna() | str_df.isin(sentinel)).any(axis=1)

    # Type mismatches
    row_mismatch = pd.Series(False, index=df.index)
    for col in df.columns.drop(skip_cols):
        num_mask = pd.to_numeric(df[col], errors="coerce").notna()
        majority_is_numeric = num_mask.sum() > (~num_mask).sum()
        row_mismatch |= (~num_mask) if majority_is_numeric else num_mask

    # Rare categories
    row_incomplete = pd.Series(False, index=df.index)
    for col in df.select_dtypes(include=["object", "category"]).columns.drop(skip_cols):
        rare_vals = df[col].value_counts(dropna=False).loc[lambda s: s < rare_category_threshold].index
        if len(rare_vals):
            row_incomplete |= df[col].isin(rare_vals)

    row_has_issue = row_anomaly | row_missing | row_mismatch | row_incomplete
    to_drop = rows_in_bin & row_has_issue

    cleaned_df = df.loc[~to_drop].copy()

    return cleaned_df


def build_composite_index(table_name: str, column1: str, column2: str) -> str:
    """
    DEPRECATED: Create a composite index on two columns.
    """
    from sqlalchemy import MetaData, Table, Index
    from sqlalchemy.exc import NoSuchTableError

    metadata = MetaData()
    try:
        table = Table(table_name, metadata, autoload_with=engine)
    except NoSuchTableError as err:
        raise ValueError(f"Table '{table_name}' not found") from err

    missing = [col for col in (column1, column2) if col not in table.c]
    if missing:
        raise ValueError(f"Column(s) {', '.join(missing)} not found in '{table_name}'")

    index_name = f"idx_{table_name.replace('.', '_')}_{column1}_{column2}"
    idx = Index(index_name, table.c[column1], table.c[column2])

    idx.create(bind=engine, checkfirst=True)
    return idx.name
