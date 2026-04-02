# Developer Notes

At this point in the project, it would be nice to have a breakdown of things. 
This document explains all the different structures that power Buckaroo Visual Wrangler. Read this before adding new files/code to be sure it fits within the architecture or adds to it congruently.

---

## Table of Contents

1. [Detectors](#1-detectors)
2. [Previews](#2-previews)
3. [Wrangles](#3-wrangles)
4. [DBOperations](#4-dboperations)
5. [ColumnTypes](#5-columntypes)
6. [FilteringSQL](#6-filteringsql)
7. [Table Name State Management](#7-table-name-state-management)
8. [Provenance Graph & Undo/Redo](#8-provenance-graph--undoredo)
9. [Key Files](#9-key-files)
10. [Known Gaps](#10-things-to-be-aware-of)
---

## 1. Detectors

Detectors are pure-Python modules that scan a pandas DataFrame for data quality problems. They run once on upload and again after every wrangle operation.

**Four detectors** live in `detectors/` as of March 17,2026 :

| Detector | File | What it catches |
|----------|------|-----------------|
| Missing Value | `missing_value.py` | NULLs, empty strings, literal `"null"` / `"undefined"` |
| Data Type Mismatch | `datatype_mismatch.py` | Cells whose type differs from the column's majority type |
| Anomaly | `anomaly.py` | Numeric values with Z-score > 2σ (requires ≥10 numeric values in the column) |
| Incomplete | `incomplete.py` | Rare categorical values appearing fewer than 3 times |

Each detector returns a dict of the form `{ column_name: { row_id: "error_type" } }`.

**Orchestration** (`app/service_helpers.py` → `run_detectors()`):
1. Runs all four detectors on the DataFrame
2. Merges their outputs and melts into a flat table
3. Writes the result to Postgres as `errors_<tablename>` with columns: `row_id`, `column_id`, `error_type`

Error types are the strings: `"missing"`, `"mismatch"`, `"anomaly"`, `"incomplete"`.

Every table in the database has a companion `errors_<table>` — this is the data that feeds the error color overlays on every histogram and scatterplot.

---

## 2. Previews

Previews are temporary Postgres tables that let users see the result of a wrangling operation before committing it. No changes to the main table happen until the user explicitly executes.

**Created by:** `POST /api/wrangle/create-previews` → `service_helpers.create_previews_1d()` or `create_previews_2d()`

For a 1D selection (single column), two preview tables are created:
- `<table>_preview_delete` — result if selected rows were deleted
- `<table>_preview_impute` — result if selected rows were imputed

For a 2D selection (two columns), four preview tables are created:
- `<table>_preview_delete`
- `<table>_preview_impute_x`
- `<table>_preview_impute_y`

Each preview table gets its own companion `errors_<preview>` — detectors are re-run on the preview data immediately after the operation so the error overlay in the preview histogram reflects the new state.

**Imputation logic** (`app/query.py` → `impute_by_ids()`):
- Numeric columns: filled with the column mean (the column that is being imputed, so this applies to both the x and y axis in 2D charts)
- Categorical columns: filled with the column mode (same thing as numeric if it's 2D)
- Only rows that are selected by ID get imputed

**Table name length:** PostgreSQL caps identifiers at 63 characters. `_preview_name()` in `service_helpers.py` hash-truncates table names when needed so both the preview table and its `errors_` companion stay within the limit. P.S. this is kinda complicated, but works for now

**Rendering:** Preview histograms are fetched via `GET /api/plots/preview-histogram` which calls `DBOperations.generate_one_d_histogram_with_errors()` on the preview table. `PreviewCard.jsx` renders these alongside a button to execute the wrangle.

---

## 3. Wrangles

A wrangle is a committed data modification — it turns a chosen preview into the new main table.

All wrangle endpoints use `db_operations.main_table_name` as the source of truth for the current table — they do **not** accept a table name from the frontend.

**Three endpoints** in `app/wrangler_routes_sql.py`:

### `POST /api/wrangle/create-previews`
Creates the preview tables described above. No changes to the main table. Body: `{ row_ids, cols }`.

### `POST /api/wrangle/execute`
Creates a new node in the provenance graph with the wrangled table. Body: `{ preview_table }`.
1. All *other* preview tables (and their `errors_` companions) are dropped from the create-previews endpoint
2. The chosen preview is renamed to a new node name (e.g. `n1_...`, `n2_...`)
3. `db_operations.load_table()` is called — this rebuilds `ColumnTypes` and `FilteringSQL` for the new table state
4. Returns `{ success: true, table: "<new_table_name>" }` — the frontend uses this to update the global table name context

### `POST /api/wrangle/delete-column`
Drops a column in-place:
1. `ALTER TABLE DROP COLUMN` (via `app/query.py` → `delete_column()`)
2. `update_errors_table()` — re-runs all detectors and rewrites `errors_<table>`
3. Returns the updated column list to the frontend

**Two endpoints** in `app/plot_routes.py`:
These two endpoints fetch the wrangled tables that create-previews put in the DB. They create a temporary `DBOperations` instance for the preview table so the global `db_operations` is unaffected.

### `GET /api/plots/preview-histogram`
1. Gets the preview table name from the `tablename` query param
2. Makes a temp DBOperations object loaded with that preview table
3. Uses the helpers to generate the JSON structure required from the view to render a histogram (supports `type=1d` and `type=2d` for heatmaps)
4. Returns that JSON

### `GET /api/plots/preview-scatterplot`
1. Gets the preview table name from the `tablename` query param
2. Makes a temp DBOperations object loaded with that preview table
3. Uses the helpers to generate the JSON structure required from the view to render a scatterplot
4. Returns that JSON

Both are called by `PreviewCard.jsx` which chooses between them based on the `chartType` prop.

**Additional endpoints** in `app/routes.py`:

### `POST /api/undo`
Navigates to the previous version of the table by decrementing the node ID in the table name (e.g. `n2_data` → `n1_data`). Checks that the target table exists in Postgres, then calls `db_operations.load_table()`. Returns `{ success: true, table_name }`.

### `POST /api/redo`
Navigates to the next version of the table by incrementing the node ID (e.g. `n1_data` → `n2_data`). Same existence check and load. Returns `{ success: true, table_name }`.

### `GET /api/tablename`
Returns the current `db_operations.main_table_name` — useful for the frontend to verify what the backend thinks the active table is.

**SQL primitives** all live in `app/query.py`:
- `remove_rows_by_ids(table, ids)` — `DELETE WHERE "ID" = ANY(:ids)`
- `impute_by_ids(table, column, ids)` — `UPDATE ... SET col = :fill_val WHERE "ID" = ANY(:ids)`
- `delete_column(table, column)` — `ALTER TABLE DROP COLUMN`

---

## 4. DBOperations

`DBOperations` is an object defined in `app/db_functions_sql.py` and instantiated once in `app/__init__.py`:

```python
db_operations = DBOperations(engine)
```

It is imported directly into `routes.py`, `plot_routes.py`, `wrangler_routes_sql.py`, and `service_helpers.py`.

**State it holds** (all `None` until `load_table()` is called):

| Attribute | Type | Purpose |
|-----------|------|---------|
| `engine` | SQLAlchemy engine | Persistent DB connection |
| `main_table_name` | str | Currently loaded data table — **the single source of truth across all endpoints** |
| `error_table_name` | str | Companion `errors_<table>` |
| `col_types` | `ColumnTypes` | Column classification |
| `filtering_table` | `FilteringSQL` | Active row filters |
| `active_hists` | dict | Cached bin↔row mappings for currently displayed histograms/heatmaps (keyed by column name or column tuple) |

**Lifecycle:**
- `load_table(table, errors_table)` — called on upload and after every wrangle execute; instantiates fresh `ColumnTypes` and `FilteringSQL` for the new table
- `reset()` — called when user navigates home; sets all attributes back to `None`

**Visualization methods** — these are where all histogram and scatterplot SQL is built:
- `generate_one_d_histogram_with_errors(column, bin_count)` — CTE-based query: bins all rows, annotates each bin with error counts per type, returns JSON
- `generate_two_d_histogram_with_errors(col_x, col_y, x_bins, y_bins)` — same for 2D heatmap
- `generate_scatterplot_with_errors(col_x, col_y, error_sample_size, total_sample_size)` — sampled scatterplot with error type per point

All three join against `errors_<table>` and, when active, the `<table>_filtering` table (see FilteringSQL below).

**Row ID helpers** — used by the frontend to map a clicked bin back to the affected rows before creating previews:
- `get_row_ids_in_1d_bin(column, bin_value, bin_count)`
- `get_row_ids_in_2d_bin(col_x, col_y, x_bin, y_bin, ...)`
- `get_1d_bins_containing_rows(column, row_ids, bin_count)` — inverse: given row IDs, which bins do they fall into?
- `get_2d_bins_containing_rows(col_x, col_y, row_ids, ...)` — same for 2D

---

## 5. ColumnTypes

`ColumnTypes` is defined in `app/db_functions_sql.py` (line 22) and instantiated inside `DBOperations.load_table()`. It classifies every column into one of three sets:

| Set | Attribute | Contents |
|-----|-----------|----------|
| Numeric | `numeric_cols` | Columns with a PostgreSQL numeric type (`integer`, `bigint`, `numeric`, `real`, `double precision`, `smallint`) |
| Pure categorical | `pure_categorical` | Non-numeric columns whose values contain no numeric-looking strings |
| Mixed | `categorical_mixed` | Non-numeric columns that contain some values matching `^\s*-?\d+(\.\d+)?\s*$` |

**How classification works:**
1. Queries `information_schema.columns` for the column's declared Postgres type - these types are originally detected and set in Postgres during the initial upload in routes.py the function that does this is `load_table` which calls `get_sqlalchemy_dtype_map`, the helper which gets the types of the columns
2. For all non-numeric columns, runs a regex check against the actual values in the table
3. Splits into `pure_categorical` vs. `categorical_mixed` based on whether any numeric-looking values exist

**Where it's used:** everywhere inside `DBOperations` that builds SQL. The classification controls whether a column gets numeric `width_bucket` binning or categorical label-group binning in the CTE queries. Helper methods — `is_numeric_col()`, `is_categorical_col()`, `is_mixed_col()` — are called throughout.

---

## 6. FilteringSQL

`FilteringSQL` is defined in `app/filtering_sql.py` and instantiated inside `DBOperations.load_table()`.

It maintains a physical Postgres table — `<table>_filtering` — that holds only the row IDs satisfying all currently active filters. When filters are active, every visualization query in `DBOperations` adds a JOIN against this table, restricting histograms and scatterplots to the filtered subset without ever modifying the main data table.

**Key state:**

| Attribute | Purpose |
|-----------|---------|
| `applied_filters` | Dict of `{ index: sql_predicate_string }` |
| `filtering_table_name` | `<table>_filtering` |
| `table_exists` | Whether the filtering table currently exists in Postgres |

**Methods:**
- `add_filters(sql_filters: list)` — appends new SQL predicates; creates or trims the filtering table to rows matching all filters
- `delete_filters(filter_indices: list)` — removes the specified predicates; recreates the filtering table if any filters remain, otherwise drops it and sets `table_exists = False`

`DBOperations` checks `filtering_table.table_exists` in `_filter_join()` and conditionally adds the JOIN to every generated query.

---

## 7. Table Name State Management

The table name (e.g. `n0_data_test_b1zjPwbZ7P`) is a critical piece of state. `db_operations.main_table_name` is the **single source of truth** on the backend. All backend endpoints that operate on the main table read from `db_operations.main_table_name` directly — they do not accept a table name from the frontend for main-table operations. (Preview endpoints are the exception: they accept a preview table name since previews are separate temporary tables.)

**Frontend:** A React context (`TableNameContext.jsx`) holds the table name globally. It is initialized from the upload response and updated after wrangle execute or undo/redo. All components consume it via `useTableName()` — there is no prop drilling.

**Flow:**
1. Upload → backend generates `n0_<name>`, calls `db_operations.load_table()`, returns name to frontend
2. Frontend stores in `TableNameContext` via `<TableNameProvider initialTableName={...}>`
3. All components use `useTableName()` to get the current name (used for cache keys and `useEffect` dependencies)
4. After wrangle execute → backend returns the new table name → frontend calls `setTableName(result.table)` → all components re-render and re-fetch
5. Undo/redo → same pattern: backend switches `db_operations`, returns new name, frontend updates context

---

## 8. Provenance Graph & Undo/Redo

Every table name is prefixed with a node ID: `n0_`, `n1_`, `n2_`, etc. The original uploaded table is always `n0_`. Each wrangle operation creates a new node with an incremented ID.

**PGraph** (`app/pgraph/pgraph.py`):
- `node_map` — dict of `{ table_name: GraphNode }`
- `wrangle_counter` — incremented on each wrangle, used to generate the next node ID
- `wrangle_map` — maps wrangle number to operation type for metadata

**GraphNode** (`app/pgraph/node.py`):
- Stores `parent_id`, `wrangle_op`, `table_name`, `error_table_name`, `children`
- Quality metrics: `anomaly_metric`, `missing_metric`, `incomplete_metric`, `mismatch_metric`

**Session state** (in `app/__init__.py`):
- `wrangle_occurred` — boolean, `False` until the first wrangle
- `pgraph_for_session` — the `PGraph` instance, `None` until the first wrangle

**Undo/Redo** (`POST /api/undo`, `POST /api/redo` in `app/routes.py`):
- Parses the current table name to extract the node ID number and base name
- Decrements (undo) or increments (redo) the node ID
- Checks if the target table exists in Postgres
- Calls `db_operations.load_table()` on the target
- The old tables are never deleted — they remain in Postgres, so navigation between versions is instant

---

## 9. Key Files

| File | Role |
|------|------|
| `detectors/missing_value.py` | Missing value detector |
| `detectors/datatype_mismatch.py` | Type mismatch detector |
| `detectors/anomaly.py` | Statistical outlier detector |
| `detectors/incomplete.py` | Rare-category detector |
| `app/db_functions_sql.py` | `DBOperations` (line 115) + `ColumnTypes` (line 22) |
| `app/filtering_sql.py` | `FilteringSQL` class |
| `app/__init__.py` | Global `db_operations` instantiation + session globals (`wrangle_occurred`, `pgraph_for_session`) |
| `app/service_helpers.py` | Preview creation, wrangle execution, detector orchestration, pgraph entry point |
| `app/wrangler_routes_sql.py` | Wrangle API endpoints (create-previews, execute, delete-column) |
| `app/routes.py` | Upload, reset, undo/redo, and tablename endpoints |
| `app/plot_routes.py` | Histogram, scatterplot, preview-histogram, and preview-scatterplot endpoints |
| `app/query.py` | SQL primitives: delete rows, impute, drop column |
| `app/pgraph/pgraph.py` | `PGraph` class — provenance DAG structure |
| `app/pgraph/node.py` | `GraphNode` class — individual wrangle node |
| `ui/src/utils/TableNameContext.jsx` | React context providing global `tableName` + `setTableName` |
| `ui/src/utils/SelectionContext.jsx` | React context for shared row/column selection state |
| `ui/src/utils/RowRangeContext.jsx` | React context for row range (filtering by ID range) |
| `ui/src/panels/RepairPanel.jsx` | Wrangle UI — create-previews, execute, undo, redo |
| `ui/src/panels/PreviewCard.jsx` | Renders preview histograms/heatmaps/scatterplots + execute button |
| `ui/src/utils/serverCalls.jsx` | Frontend API call helpers |

---

## 10. Things to be aware of

- **Detectors run in Python memory. - We should fix this** All four detectors operate on the full DataFrame before writing to Postgres. For large datasets this could be slow — there is no chunking or SQL-side detection.

