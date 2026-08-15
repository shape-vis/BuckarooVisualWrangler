from flask import request
from app import app, db_operations
from app.wrangle_operations.sql_utils import quote_identifier, quote_literal


NUMERIC_VALUE_PATTERN = r"'^\s*-?\d+(\.\d+)?\s*$'"


def _qualified_column(table_name, column_name):
    return f"{quote_identifier(table_name)}.{quote_identifier(column_name)}"


def _safe_numeric_expression(table_name, column_name):
    column_sql = _qualified_column(table_name, column_name)
    return (
        f"CASE WHEN {column_sql}::text ~ {NUMERIC_VALUE_PATTERN} "
        f"THEN {column_sql}::numeric END"
    )


def _categorical_predicate(table_name, column_name, value):
    column_sql = _qualified_column(table_name, column_name)
    if value is None or str(value).strip().lower() in {"null", "none", "nan"}:
        return f"{column_sql} IS NULL"
    return f"{column_sql}::text = {quote_literal(value)}"


def _build_sql_predicate(table_name, selection):
    """
    Translates a frontend selection payload (the points in the plots the
     user clicks on, into one or more SQL predicate strings
    that can be used with FilteringSQL.add_filters().

    Selection shape:
      {
        viewType: "heatmap" | "barchart" | "scatterplot",
        cols: [xCol] | [xCol, yCol],
        data: [
          # barchart:   { bin: <int|str>, type: "numeric"|"categorical" }
          # heatmap:    { xBin, xType, yBin, yType }
          # scatterplot: { ID: <int>, ... }
        ],
        scaleX: { numeric: [{x0, x1}, ...], categorical: [...] },
        scaleY: { numeric: [...], categorical: [...] } | null
      }

    Returns a list of SQL predicate strings, one per selected bin/point,
    combined with OR so that adding multiple bins broadens the filter.
    The caller wraps the whole list in a single add_filters() call so they
    share one filter index and can be cleared together.
    """
    view_type = selection.get("viewType")
    data = selection.get("data", [])
    cols = selection.get("cols", [])
    scale_x = selection.get("scaleX", {})
    scale_y = selection.get("scaleY", {})

    predicates = []

    if view_type == "scatterplot":
        ids = [str(int(d["ID"])) for d in data if d.get("ID") is not None]
        if ids:
            predicates.append(
                f"{_qualified_column(table_name, 'ID')} IN ({', '.join(ids)})"
            )

    elif view_type == "barchart":
        x_col = cols[0]
        numeric_bins = scale_x.get("numeric", [])

        for item in data:
            bin_val = item.get("bin")
            bin_type = item.get("type")

            if bin_type == "numeric":
                if bin_val is None or int(bin_val) >= len(numeric_bins):
                    continue
                b = numeric_bins[int(bin_val)]
                x0, x1 = float(b["x0"]), float(b["x1"])
                numeric_value = _safe_numeric_expression(table_name, x_col)
                predicates.append(
                    f"({numeric_value}) >= {x0} "
                    f"AND ({numeric_value}) <= {x1}"
                )
            else:
                # categorical — bin is the label string
                predicates.append(_categorical_predicate(table_name, x_col, bin_val))

    elif view_type == "heatmap":
        x_col = cols[0]
        y_col = cols[1]
        numeric_bins_x = scale_x.get("numeric", [])
        numeric_bins_y = scale_y.get("numeric", []) if scale_y else []

        for item in data:
            x_bin = item.get("xBin")
            x_type = item.get("xType")
            y_bin = item.get("yBin")
            y_type = item.get("yType")

            # Build X predicate
            if x_type == "numeric":
                if x_bin is None or int(x_bin) >= len(numeric_bins_x):
                    continue
                bx = numeric_bins_x[int(x_bin)]
                numeric_x = _safe_numeric_expression(table_name, x_col)
                x_pred = (
                    f"({numeric_x}) >= {float(bx['x0'])} "
                    f"AND ({numeric_x}) <= {float(bx['x1'])}"
                )
            else:
                x_pred = _categorical_predicate(table_name, x_col, x_bin)

            # Build Y predicate
            if y_type == "numeric":
                if y_bin is None or int(y_bin) >= len(numeric_bins_y):
                    continue
                by = numeric_bins_y[int(y_bin)]
                numeric_y = _safe_numeric_expression(table_name, y_col)
                y_pred = (
                    f"({numeric_y}) >= {float(by['x0'])} "
                    f"AND ({numeric_y}) <= {float(by['x1'])}"
                )
            else:
                y_pred = _categorical_predicate(table_name, y_col, y_bin)

            predicates.append(f'({x_pred}) AND ({y_pred})')

    return predicates


@app.post("/api/filter/add")
def filter_add():
    """
    Adds a selection as a filter to FilteringSQL so that all subsequent plot
    queries are scoped to the matching rows.

    Request body:
      { table: str, selection: { viewType, cols, data, scaleX, scaleY } }

    Response:
      { success: bool, filterIndices: [int, ...] }
      filterIndices lets the frontend clear exactly these filters later.
    """
    body = request.get_json(force=True)
    table = body.get("table")
    selection = body.get("selection")

    if not table or not selection:
        return {"success": False, "error": "Missing table or selection"}, 400

    if db_operations.main_table_name != table:
        return {"success": False, "error": f"Table '{table}' is not the active table"}, 400

    predicates = _build_sql_predicate(table, selection)

    if not predicates:
        return {"success": False, "error": "Could not build any SQL predicates from selection"}, 400

    # Combine all bins in this selection into one OR-joined predicate string.
    # This means one click (even with multiple bins) = one filter index to clear.
    combined = "(" + " OR ".join(f"({p})" for p in predicates) + ")"

    result = db_operations.add_data_filters([combined])

    if not result.get("Success"):
        return {"success": False, "error": result.get("Error", "Unknown error")}, 500

    return {"success": True, "filterIndices": result.get("Index", [])}


@app.post("/api/filter/clear")
def filter_clear():
    """
    Removes specific filter indices (or all filters if none specified).

    Request body:
      { filterIndices: [int, ...] }   — clear specific indices
      { filterIndices: [] }           — clear all active filters

    Response:
      { success: bool }
    """
    body = request.get_json(force=True)
    indices = body.get("filterIndices", [])

    # If no indices provided, clear everything
    if not indices:
        all_indices = list(db_operations.filtering_table.applied_filters.keys())
        if not all_indices:
            return {"success": True}  # nothing to clear
        indices = all_indices

    result = db_operations.remove_data_filters(indices)

    if not result.get("Success"):
        return {"success": False, "error": result.get("Error", "Unknown error")}, 500

    return {"success": True}
