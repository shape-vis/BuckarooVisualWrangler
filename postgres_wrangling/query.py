# ─────────────────────────────────────────────────────────────────────────────
# 2-D histogram with data-quality metrics
# ─────────────────────────────────────────────────────────────────────────────
from typing import Dict, Any, List
from sqlalchemy import text
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


# ───────── main entry-point ──────────────────────────────────────────────────
def generate_2d_histogram_data(
    x_column: str,
    y_column: str,
    bins: int,
    min_id: int,
    max_id: int,
    table_name: str,
    whole_table: bool = False,          # NEW ── set True to ignore id range
) -> Dict[str, Any]:
    """
    Build a dense 2-D histogram for the requested slice and compute
    five quality metrics per bin …   (docstring left exactly as before)
    """
    numeric_regex = r'^-?\d+(?:\.\d+)?$'   # used for type-mismatch detection

    # ─────────── helpers added for the whole-table mode ───────────
    range_where  = '' if whole_table else 'WHERE "index" BETWEEN :lo AND :hi'
    kw_filter    = 'WHERE' if whole_table else 'AND'      # NEW ←────────────
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

        # 3 ‧ stats for anomaly detection (z-score > 2)
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

        # 4 ‧ pre-build expressions so the f-string contains **no back-slashes**
        anomaly_x_expr = (
            f"ABS((CAST(\"{x_column}\" AS numeric) - :mean_x) "
            f"/ NULLIF(:std_x,0)) > 2"
            if x_is_num else "FALSE"
        )
        anomaly_y_expr = (
            f"ABS((CAST(\"{y_column}\" AS numeric) - :mean_y) "
            f"/ NULLIF(:std_y,0)) > 2"
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
            else f"COUNT(*) OVER (PARTITION BY \"{x_column}\"::text) < 10"
        )
        incomplete_y_expr = (
            "FALSE" if y_is_num
            else f"COUNT(*) OVER (PARTITION BY \"{y_column}\"::text) < 10"
        )
        missing_expr = (
            f"(\"{x_column}\"::text IN ('', 'null', 'undefined') "
            f"OR \"{y_column}\"::text IN ('', 'null', 'undefined'))"
        )

        # 5 ‧ CTEs for complete x/y bin sets
        if x_is_num:
            x_vals_cte = "SELECT generate_series(0, :bins - 1) AS x_bin"
        else:
            x_vals_cte = f"""
              SELECT DISTINCT "{x_column}"::text AS x_bin
              FROM {table_name}
              {range_where}
                {kw_filter} "{x_column}" IS NOT NULL
            """

        if y_is_num:
            y_vals_cte = "SELECT generate_series(0, :bins - 1) AS y_bin"
        else:
            y_vals_cte = f"""
              SELECT DISTINCT "{y_column}"::text AS y_bin
              FROM {table_name}
              {range_where}
                {kw_filter} "{y_column}" IS NOT NULL
            """

        # 6 ‧ expressions that map raw values → bin indices
        x_sel = (
            f"width_bucket(\"{x_column}\", :xmin, :xmax, :bins) - 1"
            if x_is_num else f"\"{x_column}\"::text"
        )
        y_sel = (
            f"width_bucket(\"{y_column}\", :ymin, :ymax, :bins) - 1"
            if y_is_num else f"\"{y_column}\"::text"
        )

        # 7 ‧ main query – slice + flags + aggregation
        slice_sql = f"""
        WITH slice AS (
            SELECT
                {x_sel} AS x_bin,
                {y_sel} AS y_bin,
                /* ───────── flags ───────── */
                ({anomaly_x_expr} OR {anomaly_y_expr})               AS anomaly,
                {missing_expr}                                        AS missing,
                ({incomplete_x_expr} OR {incomplete_y_expr})         AS incomplete,
                ({mismatch_x_expr}  OR {mismatch_y_expr})            AS mismatch
            FROM {table_name}
            {range_where}
              {kw_filter} "{x_column}" IS NOT NULL
              AND "{y_column}" IS NOT NULL
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
        x_vals AS (
            {x_vals_cte}
        ),
        y_vals AS (
            {y_vals_cte}
        )
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

        #  ── parameters ───────────────────────────────────────────
        params = {
            "bins":   bins,
            "xmin":   xmin if xmin is not None else 0,
            "xmax":   xmax if xmax is not None else 1,
            "ymin":   ymin if ymin is not None else 0,
            "ymax":   ymax if ymax is not None else 1,
            "mean_x": mean_x,
            "std_x":  std_x,
            "mean_y": mean_y,
            "std_y":  std_y,
            "num_re": numeric_regex,
            **range_params                   # empty when whole_table=True
        }

        rows = conn.execute(text(slice_sql), params).fetchall()

        # 8 ‧ build scales
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

        # 9 ‧ pack result – every x–y pair present
        histograms = []
        for r in rows:
            # always include total items
            count = {"items": int(r.items)}

            # add optional metrics only when > 0
            for key in ("anomaly", "missing", "incomplete", "mismatch"):
                val = getattr(r, key)
                if val:                          # truthy means non-zero
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