from flask import request
from app import app, db_operations


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
            predicates.append(f'"{table_name}"."ID" IN ({", ".join(ids)})')

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
                predicates.append(
                    f'"{table_name}"."{x_col}"::numeric >= {x0} '
                    f'AND "{table_name}"."{x_col}"::numeric <= {x1}'
                )
            else:
                # categorical — bin is the label string
                label = str(bin_val).replace("'", "''")
                predicates.append(f'"{table_name}"."{x_col}"::text = \'{label}\'')

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
                x_pred = (
                    f'"{table_name}"."{x_col}"::numeric >= {float(bx["x0"])} '
                    f'AND "{table_name}"."{x_col}"::numeric <= {float(bx["x1"])}'
                )
            else:
                label = str(x_bin).replace("'", "''")
                x_pred = f'"{table_name}"."{x_col}"::text = \'{label}\''

            # Build Y predicate
            if y_type == "numeric":
                if y_bin is None or int(y_bin) >= len(numeric_bins_y):
                    continue
                by = numeric_bins_y[int(y_bin)]
                y_pred = (
                    f'"{table_name}"."{y_col}"::numeric >= {float(by["x0"])} '
                    f'AND "{table_name}"."{y_col}"::numeric <= {float(by["x1"])}'
                )
            else:
                label = str(y_bin).replace("'", "''")
                y_pred = f'"{table_name}"."{y_col}"::text = \'{label}\''

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