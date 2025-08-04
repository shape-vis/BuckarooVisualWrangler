# ─────────────────────────────────────────────────────────────────────────────
# 2-D histogram with data-quality metrics
# ─────────────────────────────────────────────────────────────────────────────
from typing import Dict, Any, List
from sqlalchemy import text, Engine
from app import engine      # your existing SQLAlchemy engine

_NUMERIC_TYPES = {
    "smallint", "integer", "bigint",
    "decimal", "numeric", "real", "double precision"
}

# ───────── helpers ───────────────────────────────────────────────────────────
def _is_numeric(conn, col: str, table_name: str) -> bool:
    sql = f"""
        SELECT data_type
        FROM information_schema.columns
        WHERE table_name = '{table_name}'
          AND column_name = :col
    """
    dtype = conn.execute(text(sql), {"col": col}).scalar_one()
    return dtype in _NUMERIC_TYPES


def _numeric_scale(lo: float, hi: float, bins: int, axis: str) -> List[Dict[str, float]]:
    """Evenly-spaced numeric bin-boundaries."""
    if lo == hi:                       # avoid zero-width range
        hi += 1.0
    step = (hi - lo) / bins
    k0, k1 = f"{axis}0", f"{axis}1"
    return [{k0: lo + i * step, k1: lo + (i + 1) * step} for i in range(bins)]


def generate_2d_histogram_data(
    x_column: str,
    y_column: str,
    bins: int,
    min_id: int,
    max_id: int,
    table_name: str,
    whole_table: bool = False,          # True → ignore id range
) -> Dict[str, Any]:
    """
    Build a dense 2-D histogram for the requested slice and compute
    five quality metrics per bin (items, anomaly, missing, incomplete,
    mismatch).  Unlike the earlier version this one:
      • treats SQL NULLs as “missing”,
      • maps NULLs into a dedicated “-1” (numeric) / “__NULL__” (categorical)
        pseudo-bin so they are counted,
      • no longer drops rows whose x or y value is NULL.
    """
    numeric_regex = r'^-?\d+(?:\.\d+)?$'          # for type-mismatch detection
    NULL_NUM_BIN  = 0                             # 🔄 numeric NULLs now go to bin 0
    NULL_CAT_BIN  = '__NULL__'                    # sentinel for categorical NULL

    # ────────── helpers for id-range slicing ──────────
    range_where  = '' if whole_table else 'WHERE "index" BETWEEN :lo AND :hi'
    range_params = {} if whole_table else {"lo": min_id, "hi": max_id}

    with engine.connect() as conn:
        # 1 ‧ column types
        x_is_num = _is_numeric(conn, x_column, table_name=table_name)
        y_is_num = _is_numeric(conn, y_column, table_name=table_name)

        # 2 ‧ numeric bounds (for width_bucket)
        bounds_sql = f"""
            SELECT
                {'MIN("' + x_column + '")::numeric, MAX("' + x_column + '")::numeric' if x_is_num else 'NULL, NULL'},
                {'MIN("' + y_column + '")::numeric, MAX("' + y_column + '")::numeric' if y_is_num else 'NULL, NULL'}
            FROM {table_name}
            {range_where}
        """
        xmin, xmax, ymin, ymax = conn.execute(text(bounds_sql), range_params).fetchone()

        # 3 ‧ stats for anomaly detection (|z| > 2)
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

        # 4 ‧ flag expressions
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

        # 5 ‧ full x / y bin sets (include sentinel for NULL)
        if x_is_num:
            x_vals_cte = "SELECT generate_series(:null_num_bin, :bins - 1) AS x_bin"
        else:
            x_vals_cte = f"""
              SELECT DISTINCT COALESCE("{x_column}"::text, '{NULL_CAT_BIN}') AS x_bin
              FROM {table_name}
              {range_where}
            """
        if y_is_num:
            y_vals_cte = "SELECT generate_series(:null_num_bin, :bins - 1) AS y_bin"
        else:
            y_vals_cte = f"""
              SELECT DISTINCT COALESCE("{y_column}"::text, '{NULL_CAT_BIN}') AS y_bin
              FROM {table_name}
              {range_where}
            """

        # 6 ‧ raw→bin mapping (coalesce NULL→sentinel)
        x_sel = (
            f"COALESCE(width_bucket(\"{x_column}\", :xmin, :xmax, :bins) - 1, :null_num_bin)"
            if x_is_num else f"COALESCE(\"{x_column}\"::text, '{NULL_CAT_BIN}')"
        )
        y_sel = (
            f"COALESCE(width_bucket(\"{y_column}\", :ymin, :ymax, :bins) - 1, :null_num_bin)"
            if y_is_num else f"COALESCE(\"{y_column}\"::text, '{NULL_CAT_BIN}')"
        )

        # 7 ‧ main aggregation
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

        # 8 ‧ parameters
        params = {
            "bins":         bins,
            "xmin":         xmin if xmin is not None else 0,
            "xmax":         xmax if xmax is not None else 1,
            "ymin":         ymin if ymin is not None else 0,
            "ymax":         ymax if ymax is not None else 1,
            "mean_x":       mean_x,
            "std_x":        std_x,
            "mean_y":       mean_y,
            "std_y":        std_y,
            "num_re":       numeric_regex,
            "null_num_bin": NULL_NUM_BIN,
            **range_params,
        }

        rows = conn.execute(text(slice_sql), params).fetchall()

        # 9 ‧ build axis scales (sentinel bin intentionally omitted)
        scaleX = {"numeric": [], "categorical": []}
        scaleY = {"numeric": [], "categorical": []}

        if x_is_num:
            scaleX["numeric"] = _numeric_scale(float(params["xmin"]),
                                               float(params["xmax"]), bins, "x")
        else:
            scaleX["categorical"] = [
                r[0] for r in conn.execute(text(x_vals_cte), params)
            ]
        if y_is_num:
            scaleY["numeric"] = _numeric_scale(float(params["ymin"]),
                                               float(params["ymax"]), bins, "y")
        else:
            scaleY["categorical"] = [
                r[0] for r in conn.execute(text(y_vals_cte), params)
            ]

        # 10 ‧ pack result
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

from sqlalchemy import text

def copy_without_flagged_rows(current_selection: dict,
                              cols: list[str],
                              table: str,
                              new_table_name: str,
                              ) -> int:
    """
    Build a *new* table that contains every row from `table` **except** those
    that (a) fall inside the single 2-D bin described in `current_selection`
    and (b) are flagged by any quality check
    (anomaly | missing | incomplete | mismatch).

    Parameters
    ----------
    current_selection : dict   – the object returned by the histogram endpoint
    cols              : list   – [x_col, y_col]  (x = numeric, y = categorical)
    table             : str    – source table name
    new_table_name    : str    – destination table to create
    engine            :        – SQLAlchemy engine

    Returns
    -------
    int – number of rows copied into the new table
    """
    sel   = current_selection["data"][0]
    x_bin = sel["xBin"]
    y_val = sel["yBin"]

    # numeric x-axis boundaries (lo ≤ value < hi)
    x_bounds = current_selection["scaleX"]["numeric"][x_bin]
    x_lo, x_hi = x_bounds["x0"], x_bounds["x1"]

    numeric_re = r'^-?\d+(?:\.\d+)?$'          # used for “mismatch”

    sql = f"""
    /* -------- recreate destination table -------- */
    DROP TABLE IF EXISTS {new_table_name};

    CREATE TABLE {new_table_name} AS
    WITH
        stats AS (                              -- mean / std for anomaly
            SELECT
                AVG("{cols[0]}")::numeric        AS mean_x,
                STDDEV_SAMP("{cols[0]}")::numeric AS std_x
            FROM {table}
        ),
        to_keep AS (                            -- rows that *survive*
            SELECT t.*
            FROM   {table} t, stats
            WHERE NOT (                          -- invert deletion logic
                /* ❶ bin filter  */
                "{cols[0]}" >= :x_lo
            AND "{cols[0]}" <  :x_hi
            AND "{cols[1]}"  = :y_val

                /* ❷ any quality flag */
            AND (
                    /* anomaly */
                    ABS( ( "{cols[0]}"::numeric - stats.mean_x )
                         / NULLIF(stats.std_x, 0) ) > 2

                OR  /* missing */
                    "{cols[0]}" IS NULL
                OR  "{cols[1]}" IS NULL
                OR  "{cols[0]}"::text IN ('', 'null', 'undefined')
                OR  "{cols[1]}"::text IN ('', 'null', 'undefined')

                OR  /* incomplete (low-freq category) */
                    ( SELECT COUNT(*)
                      FROM   {table}
                      WHERE  "{cols[1]}" = :y_val ) < 10

                OR  /* mismatch (type) */
                    "{cols[1]}"::text ~ :num_re
                )
            )
        )
    SELECT * FROM to_keep;
    """

    with engine.begin() as conn:
        # create the table
        conn.execute(
            text(sql),
            {"x_lo": x_lo, "x_hi": x_hi, "y_val": y_val, "num_re": numeric_re},
        )
        # count rows copied
        n_rows = conn.execute(
            text(f"SELECT COUNT(*) FROM {new_table_name}")
        ).scalar_one()

    return n_rows

def new_table_name(old_name:str):
    split_substring = "_version_"
    parts = old_name.split(split_substring)
    new_version = None
    if len(parts) == 1:
        new_version = 1
    else:
        new_version = int(parts[-1]) + 1
    
    return parts[0] + split_substring + str(new_version)

from typing import Dict, Any, List, Tuple
from sqlalchemy import text
from sqlalchemy.engine import Engine

# sentinel constants used by your histogram code
NULL_NUM_BIN  = 0
NULL_CAT_BIN  = "__NULL__"


def _missing_pred(col: str) -> str:
    """Boolean SQL expression that is TRUE when *col* is ‘missing’."""
    return (
        f"(\"{col}\" IS NULL "
        f"OR \"{col}\"::text IN ('', 'null', 'undefined'))"
    )


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
    Return a SQL WHERE-clause fragment that matches rows which fell into
    *bin_val* for column *col*.  Adds any bound parameters to *params*.
    """
    if bin_type == "numeric":
        if bin_val == NULL_NUM_BIN:                # NULL bucket
            return _missing_pred(col)
        edge = scale["numeric"][bin_val]           # {'x0', 'x1'}
        lo, hi   = edge["x0"], edge["x1"]
        lo_key   = f"{pfx}lo"
        hi_key   = f"{pfx}hi"
        params[lo_key], params[hi_key] = lo, hi
        last_bin = bin_val == len(scale["numeric"]) - 1
        return (
            f"\"{col}\" BETWEEN :{lo_key} AND :{hi_key}"
            if last_bin
            else f"\"{col}\" >= :{lo_key} AND \"{col}\" < :{hi_key}"
        )
    else:  # categorical
        if bin_val == NULL_CAT_BIN:
            return _missing_pred(col)
        key = f"{pfx}_cat"
        params[key] = bin_val
        return f"\"{col}\" = :{key}"


# def copy_and_impute_bin(
#     current_selection: Dict[str, Any],
#     cols: List[str],
#     table: str,
#     new_table_name: str,
# ) -> Tuple[int, int]:
#     """
#     Duplicate *table* into *new_table_name* and impute **only** the rows lying
#     in the single histogram bar described by *current_selection*.

#     Returns (rows_examined, cells_imputed).
#     """
#     if len(cols) != 2:
#         raise ValueError("cols must be exactly [x_column, y_column]")

#     x_col, y_col   = cols
#     sel            = current_selection["data"][0]
#     params: Dict[str, Any] = {}

#     # ------------ WHERE predicate that defines the selected bin ------------
#     where_parts = [
#         _bin_predicate(
#             bin_val   = sel["xBin"],
#             bin_type  = sel["xType"],
#             scale     = current_selection["scaleX"],
#             col       = x_col,
#             params    = params,
#             pfx       = "x",
#         ),
#         _bin_predicate(
#             bin_val   = sel["yBin"],
#             bin_type  = sel["yType"],
#             scale     = current_selection["scaleY"],
#             col       = y_col,
#             params    = params,
#             pfx       = "y",
#         ),
#     ]
#     bin_where_sql = " AND ".join(where_parts)

#     with engine.begin() as conn:

#         # 1 ─ make a plain copy of the table
#         conn.execute(text(f"DROP TABLE IF EXISTS {new_table_name}"))
#         conn.execute(text(f"CREATE TABLE {new_table_name} AS SELECT * FROM {table}"))

#         # 2 ─ how many rows does that bin actually hold?
#         rows_examined = conn.execute(
#             text(f"SELECT COUNT(*) FROM {new_table_name} WHERE {bin_where_sql}"),
#             params,
#         ).scalar()

#         if rows_examined == 0:
#             print("⚠️  No rows fell into the chosen bin – nothing to impute.")
#             return 0, 0

#         # 3 ─ mode (most-common non-missing value) for each target column
#         modes: Dict[str, Any] = {}
#         for col in cols:
#             mode_val = conn.execute(
#                 text(
#                     f"""
#                     SELECT "{col}"
#                     FROM   {table}
#                     WHERE  NOT {_missing_pred(col)}
#                     GROUP  BY "{col}"
#                     ORDER  BY COUNT(*) DESC
#                     LIMIT  1
#                     """
#                 )
#             ).scalar()

#             # If the whole column is missing, pick the first non-NULL value
#             if mode_val is None:
#                 mode_val = conn.execute(
#                     text(f'SELECT "{col}" FROM {table} WHERE "{col}" IS NOT NULL LIMIT 1')
#                 ).scalar()
#             modes[col] = mode_val

#         # 4 ─ impute column-by-column
#         cells_imputed = 0
#         for col in cols:
#             upd_sql = text(
#                 f"""
#                 UPDATE {new_table_name}
#                 SET    "{col}" = :mode_val
#                 WHERE  {bin_where_sql}
#                   AND  {_missing_pred(col)}
#                 """
#             )
#             rc = conn.execute(upd_sql, dict(params, mode_val=modes[col])).rowcount
#             cells_imputed += rc

#     return rows_examined, cells_imputed

def copy_and_impute_bin(
    current_selection: Dict[str, Any],
    cols: List[str],
    table: str,
    new_table_name: str,
) -> Tuple[int, int]:
    """
    Duplicate *table* into *new_table_name* and, **only** for rows that fall
    into the selected 2-D histogram bin, impute missing values:

        • numeric columns  →  mean (AVG)
        • categorical      →  mode (most-common non-NULL)

    Returns (rows_examined, cells_imputed).
    """
    if len(cols) != 2:
        raise ValueError("cols must be exactly [x_column, y_column]")

    x_col, y_col   = cols
    sel            = current_selection["data"][0]
    params: Dict[str, Any] = {}

    # ------------ WHERE predicate that defines the selected bin ------------
    where_parts = [
        _bin_predicate(
            bin_val   = sel["xBin"],
            bin_type  = sel["xType"],
            scale     = current_selection["scaleX"],
            col       = x_col,
            params    = params,
            pfx       = "x",
        ),
        _bin_predicate(
            bin_val   = sel["yBin"],
            bin_type  = sel["yType"],
            scale     = current_selection["scaleY"],
            col       = y_col,
            params    = params,
            pfx       = "y",
        ),
    ]
    bin_where_sql = " AND ".join(where_parts)

    with engine.begin() as conn:

        # 1 ─ plain copy of the table
        conn.execute(text(f'DROP TABLE IF EXISTS "{new_table_name}"'))
        conn.execute(text(f'CREATE TABLE "{new_table_name}" AS SELECT * FROM "{table}"'))

        # 2 ─ how many rows does that bin hold?
        rows_examined = conn.execute(
            text(f'SELECT COUNT(*) FROM "{new_table_name}" WHERE {bin_where_sql}'),
            params,
        ).scalar_one()

        if rows_examined == 0:
            print("⚠️  No rows fell into the chosen bin – nothing to impute.")
            return 0, 0

        # 3 ─ choose a fill-value for each column
        modes_or_means: Dict[str, Any] = {}
        for col in cols:
            is_numeric = _is_numeric(conn, col, table)   # helper already exists
            if is_numeric:
                # Mean of non-missing cells
                val = conn.execute(
                    text(
                        f'''
                        SELECT AVG("{col}")::numeric
                        FROM   "{table}"
                        WHERE  NOT {_missing_pred(col)}
                        '''
                    )
                ).scalar()
            else:
                # Mode (most common) of non-missing cells
                val = conn.execute(
                    text(
                        f'''
                        SELECT "{col}"
                        FROM   "{table}"
                        WHERE  NOT {_missing_pred(col)}
                        GROUP  BY "{col}"
                        ORDER  BY COUNT(*) DESC
                        LIMIT  1
                        '''
                    )
                ).scalar()

            # Fallback if the whole column is NULL
            if val is None:
                val = conn.execute(
                    text(f'SELECT "{col}" FROM "{table}" WHERE "{col}" IS NOT NULL LIMIT 1')
                ).scalar()

            modes_or_means[col] = val

        # 4 ─ impute column-by-column
        cells_imputed = 0
        for col in cols:
            upd_sql = text(
                f'''
                UPDATE "{new_table_name}"
                SET    "{col}" = :fill_val
                WHERE  {bin_where_sql}
                  AND  {_missing_pred(col)}
                '''
            )
            rc = conn.execute(upd_sql, dict(params, fill_val=modes_or_means[col])).rowcount
            cells_imputed += rc

    return rows_examined, cells_imputed
import pandas as pd
from typing import Dict, Any, List, Tuple

def copy_and_impute_bin_df(
    current_selection: Dict[str, Any],
    cols: List[str],
    df: pd.DataFrame,
) -> List[int]:
    """
    Locate rows inside the histogram bin given by *current_selection*
    that still hold a NULL / NaN / “null” / “undefined” in any column
    listed in *cols*.

    Parameters
    ----------
    current_selection : Dict[str, Any]
        Same structure produced by your front-end (see example above).
    cols : List[str]   – must be [x_column, y_column].
    df   : pd.DataFrame

    Returns
    -------
    List[int]          – index labels (as int) of rows that need imputation.
    """
    if len(cols) != 2:
        raise ValueError("cols must be exactly [x_column, y_column]")

    x_col, y_col = cols
    sel          = current_selection["data"][0]    # only one bin is sent
    sentinels    = {"null", "undefined"}

    # ── build a boolean mask for rows that fall into the selected bin ──
    def _axis_mask(col: str, axis: str) -> pd.Series:
        """Mask of rows that fall into the selected x or y bin."""
        if sel[f"{axis}Type"] == "categorical":
            # exact category match (case-insensitive, treat NA as no-match)
            return (
                df[col]
                .astype(str)
                .str.lower()
                .eq(str(sel[f"{axis}Bin"]).lower())
                & df[col].notna()
            )
        else:  # numeric
            bins   = current_selection[f"scale{axis.upper()}"]["numeric"]
            idx    = sel[f"{axis}Bin"]
            lo, hi = bins[idx][f"{axis}0"], bins[idx][f"{axis}1"]

            s = pd.to_numeric(df[col], errors="coerce")  # NaNs → no-match
            # last bin is inclusive on the right edge
            if idx == len(bins) - 1:
                return (s >= lo) & (s <= hi)
            return (s >= lo) & (s < hi)

    in_x_bin = _axis_mask(x_col, "x")
    in_y_bin = _axis_mask(y_col, "y")
    in_bin   = in_x_bin | in_y_bin

    if not in_bin.any():
        return []                                     # nothing to impute

    # ── detect missing values only inside the selected bin ─────────────
    sub_df    = df.loc[in_bin, cols]
    str_vals  = sub_df.apply(lambda s: s.astype(str).str.lower())
    miss_mask = sub_df.isna() | str_vals.isin(sentinels)

    return sub_df.index[miss_mask.any(axis=1)].astype(int).tolist()

import pandas as pd
from typing import Sequence, List, Set, Any
from pandas.api.types import is_numeric_dtype


def impute_at_indices_copy(
    df: pd.DataFrame,
    cols: Sequence[str],
    row_indices: Sequence[int] | List[int],
    *,
    sentinel: Set[str] | None = None,
) -> pd.DataFrame:
    """
    Return a **new** dataframe where the cells in `cols` and `row_indices`
    are imputed as follows:
        • numeric column  → mean of its non-missing values
        • non-numeric     → mode (most frequent value)

    “Missing” = NaN / NaT **or** any value in *sentinel*
               (default {"null", "undefined"}, case-insensitive).

    Parameters
    ----------
    df          : pd.DataFrame
    cols        : iterable[str]   – target columns
    row_indices : iterable[int]   – index labels of rows to patch
    sentinel    : set[str] | None – extra strings marking missingness

    Returns
    -------
    pd.DataFrame
        A deep copy of *df* with the requested imputations applied.
    """
    sentinel = {s.lower() for s in (sentinel or {"null", "undefined"})}
    idx_set  = set(row_indices)

    # work on a deep copy so the caller’s df is untouched
    out = df.copy(deep=True)

    for col in cols:
        col_series = out[col]

        # derive statistic (mean or mode) from *non-missing* values
        clean_col = (
            col_series
            .mask(col_series.astype(str).str.lower().isin(sentinel))
            .dropna()
        )
        if clean_col.empty:      # cannot impute if everything is missing
            continue

        fill_value: Any
        if is_numeric_dtype(col_series):
            fill_value = clean_col.astype(float).mean()
        else:
            fill_value = clean_col.mode(dropna=True).iloc[0]

        # mask for cells to replace: (row in idx_set) & (cell is missing)
        target_mask = (
            out.index.to_series().isin(idx_set) &
            (
                col_series.isna() |
                col_series.astype(str).str.lower().isin(sentinel)
            )
        )

        out.loc[target_mask, col] = fill_value

    return out


import numpy as np

import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple

import numpy as np
import pandas as pd
from typing import Any, Dict, List, Tuple


def remove_anomalous_rows(
    current_selection: Dict[str, Any],
    cols: List[str],                 # [x_column, y_column]
    df: pd.DataFrame,    *,
    z_threshold: float = 2.0,
    min_numeric_values: int = 10,
    skip_cols: List[str] | None = None,
) -> Tuple[pd.DataFrame, pd.Index]:
    """
    Remove every row that is (a) inside the selected 2-D histogram bin and
    (b) contains at least one numeric-column outlier
        |value − mean| > z_threshold · std.

    Parameters
    ----------
    current_selection : front-end structure shown in the question.
    cols : [x_column, y_column] – must correspond to the two plotted axes.
    df : original DataFrame.
    z_threshold, min_numeric_values, skip_cols : see original docstring.

    Returns
    -------
    cleaned_df : copy of *df* with the offending rows removed.
    dropped_rows : index labels of the discarded rows.
    """
    if len(cols) != 2:
        raise ValueError("cols must be exactly [x_column, y_column]")
    if skip_cols is None:
        skip_cols = []

    x_col, y_col = cols
    sel          = current_selection["data"][0]

    # ─────────────────── 1. mask: rows located in the selected bin ──────────────────
    def _mask_for_axis(
        axis_col: str,
        axis_scale: Dict[str, Any],
        bin_val: Any,
        bin_type: str,
    ) -> pd.Series:
        """Boolean mask for *axis_col* matching the chosen bin."""
        if bin_type == "numeric":
            # bin_val is an *index* into scale["numeric"]
            try:
                lo, hi = (
                    axis_scale["numeric"][bin_val]["x0"],
                    axis_scale["numeric"][bin_val]["x1"],
                )
            except (IndexError, KeyError, TypeError):
                raise ValueError(f"Cannot locate numeric bin {bin_val} "
                                 f"for column {axis_col!r}")
            # Convert column to numeric (silently making non-numerics NaN)
            col_num = pd.to_numeric(df[axis_col], errors="coerce")
            # Left-inclusive, right-exclusive except for the last bin
            if bin_val == len(axis_scale["numeric"]) - 1:
                return (col_num >= lo) & (col_num <= hi)
            return (col_num >= lo) & (col_num < hi)

        elif bin_type == "categorical":
            # bin_val is the category name itself
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

    # ─────────────────── 2. mask: rows containing numeric outliers ──────────────────
    row_is_anomalous = pd.Series(False, index=df.index)

    for col in df.columns:
        if col in skip_cols:
            continue

        numeric_col = pd.to_numeric(df[col], errors="coerce")
        if numeric_col.notna().sum() < min_numeric_values:
            continue

        mean, std = numeric_col.mean(), numeric_col.std()
        if std == 0 or np.isnan(std):
            continue  # uniform column → no anomalies

        z_mask = (np.abs(numeric_col - mean) > z_threshold * std)
        row_is_anomalous |= z_mask.fillna(False)

    # ─────────────────── 3. drop rows that satisfy BOTH masks ───────────────────────
    to_drop     = row_is_anomalous & rows_in_bin
    dropped_idx = to_drop[to_drop].index
    cleaned_df  = df.loc[~to_drop].copy()

    return cleaned_df, dropped_idx
