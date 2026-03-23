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
7. [Key Files](#7-key-files)
8. [Known Gaps](#8-Things-to-be-aware-of)
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

**Imputation logic** (`postgres_wrangling/query.py` → `impute_by_ids()`):
- Numeric columns: filled with the column mean (the column that is being imputed, so this applies to both the x and y axis in 2D charts)
- Categorical columns: filled with the column mode (same thing as numeric if it's 2D)
- Only rows that are selected by ID get imputed

**Table name length:** PostgreSQL caps identifiers at 63 characters. `_preview_name()` in `service_helpers.py` hash-truncates table names when needed so both the preview table and its `errors_` companion stay within the limit. P.S. this is kinda complicated, but works for now

**Rendering:** Preview histograms are fetched via `GET /api/plots/preview-histogram` which calls `DBOperations.generate_one_d_histogram_with_errors()` on the preview table. `PreviewCard.jsx` renders these alongside a button to execute the wrangle.

---

## 3. Wrangles

A wrangle is a committed data modification — it turns a chosen preview into the new main table.

**Three endpoints** in `app/wrangler_routes_sql.py`:

### `POST /api/wrangle/create-previews`
Creates the preview tables described above. No changes to the main table.

### `POST /api/wrangle/execute`
Promotes a chosen preview to the main table. The swap is atomic:
1. All *other* preview tables (and their `errors_` companions) are dropped
2. `ALTER TABLE "<table>" RENAME TO "<table>_old"`
3. `ALTER TABLE "<preview>" RENAME TO "<table>"`
4. `DROP TABLE "<table>_old"`
5. `db_operations.load_table()` is called — this rebuilds `ColumnTypes` and `FilteringSQL` for the new table state

### `POST /api/wrangle/delete-column`
Drops a column in-place:
1. `ALTER TABLE DROP COLUMN` (via `postgres_wrangling/query.py` → `delete_column()`)
2. `update_errors_table()` — re-runs all detectors and rewrites `errors_<table>`
3. Returns the updated column list to the frontend

**Two endpoints** in `app/plot_routes_sql.py`:
These two endpoints just fetch the wrangled tables that create-previews put in the DB by the same name

### `POST /api/plots/preview-histogram`
1. Gets the table by using the tablename that create-previews put in the DB
2. Makes a temp DBOperations object
3. Uses the helpers to generate the JSON structure required from the view to render a histogram
4. Returns that JSON
5. 
### `POST /api/plots/preview-scatterplot`
This isn't hooked up to any fetch calls yet

1. Gets the table by using the tablename that create-previews put in the DB
2. Makes a temp DBOperations object
3. Uses the helpers to generate the JSON structure required from the view to render a scatterplot
4. Returns that JSON

**SQL primitives** all live in `postgres_wrangling/query.py`:
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
| `main_table_name` | str | Currently loaded data table |
| `error_table_name` | str | Companion `errors_<table>` |
| `col_types` | `ColumnTypes` | Column classification |
| `filtering_table` | `FilteringSQL` | Active row filters |

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

`ColumnTypes` is defined in `app/db_functions_sql.py` (line 16) and instantiated inside `DBOperations.load_table()`. It classifies every column into one of three sets:

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

## 7. Key Files

| File | Role |
|------|------|
| `detectors/missing_value.py` | Missing value detector |
| `detectors/datatype_mismatch.py` | Type mismatch detector |
| `detectors/anomaly.py` | Statistical outlier detector |
| `detectors/incomplete.py` | Rare-category detector |
| `app/db_functions_sql.py` | `DBOperations` (line 109) + `ColumnTypes` (line 16) |
| `app/filtering_sql.py` | `FilteringSQL` class |
| `app/__init__.py` | Global `db_operations` instantiation |
| `app/service_helpers.py` | Preview creation, wrangle execution, detector orchestration |
| `app/wrangler_routes_sql.py` | Wrangle API endpoints |
| `app/routes.py` | Upload endpoint, initial detector run |
| `app/plot_routes.py` | Histogram and scatterplot plot endpoints |
| `postgres_wrangling/query.py` | SQL primitives: delete rows, impute, drop column |
| `ui/src/panels/RepairPanel.jsx` | Wrangle UI — bin click → create-previews request |
| `ui/src/panels/PreviewCard.jsx` | Renders preview histograms + execute button |
| `ui/src/utils/serverCalls.jsx` | Frontend API call helpers |

---

## 8. Things to be aware of

- **Preview scatterplot isn't implemented.** The frontend references `GET /api/plots/preview-scatterplot` and `GET /api/plots/preview-heatmap`, but these endpoints do not exist in `plot_routes.py`. 2D preview visualizations are currently non-functional.

- **Detectors run in Python memory. - We should fix this** All four detectors operate on the full DataFrame before writing to Postgres. For large datasets this could be slow — there is no chunking or SQL-side detection.

