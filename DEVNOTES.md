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
9. [Rankings Table](#9-rankings-table)
10. [Frontend Contexts & View Modes](#10-frontend-contexts--view-modes)
11. [Backend Package Layout](#11-backend-package-layout)
12. [Key Files](#12-key-files)
13. [Known Gaps](#13-things-to-be-aware-of)
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

**Orchestration** (`app/server_utils/service_helpers.py` → `run_detectors()`):
1. Runs all four detectors on the DataFrame
2. Merges their outputs and melts into a flat table
3. Writes the result to Postgres as `errors_<tablename>` with columns: `row_id`, `column_id`, `error_type`

Error types are the strings: `"missing"`, `"mismatch"`, `"anomaly"`, `"incomplete"`.

Every table in the database has a companion `errors_<table>` — this is the data that feeds the error color overlays on every histogram and scatterplot.

---

## 2. Previews

Previews are temporary Postgres tables that let users see the result of a wrangling operation before committing it. No changes to the main table happen until the user explicitly executes.

**Created by:** `POST /api/wrangle/create-previews` → `server_utils/service_helpers.create_previews_1d()` or `create_previews_2d()`

For a 1D selection (single column), two preview tables are created:
- `<table>_preview_delete` — result if selected rows were deleted
- `<table>_preview_impute` — result if selected rows were imputed

For a 2D selection (two columns), four preview tables are created:
- `<table>_preview_delete`
- `<table>_preview_impute_x`
- `<table>_preview_impute_y`

Each preview table gets its own companion `errors_<preview>` — detectors are re-run on the preview data immediately after the operation so the error overlay in the preview histogram reflects the new state.

**Imputation logic** (`app/db_utils/query.py` → `impute_by_ids()`):
- Numeric columns: filled with the column mean (the column that is being imputed, so this applies to both the x and y axis in 2D charts)
- Categorical columns: filled with the column mode (same thing as numeric if it's 2D)
- Only rows that are selected by ID get imputed

**Table name length:** PostgreSQL caps identifiers at 63 characters. `_safe_pg_name()` in `app/server_utils/service_helpers.py` hash-truncates table names when needed so the *most* restrictive sibling — `<name>_filtering` (10-char suffix → max base length 53) — still fits. The same helper is reused for the original upload name, every preview, and every promoted node, so all derived siblings (`errors_<name>`, `rankings_<name>`, `<name>_filtering`) stay within the limit.

**Rendering:** Preview histograms are fetched via `GET /api/plots/preview-histogram` which calls `DBOperations.generate_one_d_histogram_with_errors()` on the preview table. `PreviewCard.jsx` renders these alongside a button to execute the wrangle.

---

## 3. Wrangles

A wrangle is a committed data modification — it turns a chosen preview into the new main table.

All wrangle endpoints use `db_operations.main_table_name` as the source of truth for the current table — they do **not** accept a table name from the frontend.

**Three endpoints** in `app/routes/wrangler_routes_sql.py`:

### `POST /api/wrangle/create-previews`
Creates the preview tables described above. No changes to the main table. Body: `{ row_ids, cols }`.

### `POST /api/wrangle/execute`
Creates a new node in the provenance graph with the wrangled table. Body: `{ preview_table }`. Implementation lives in `service_helpers.execute_wrangle_preview()`:
1. All *other* preview tables (and their `errors_` companions) are dropped via `db_operations.drop_preview_tables()`
2. `n_wrangle()` allocates the next node ID from `PGraph.get_new_node_id()` and inserts a `GraphNode` with `parent_table = current main table` — this happens **before** any rename so the pgraph is the canonical source of the new name
3. The chosen preview is renamed to that new node name (e.g. `n1_...`, `n2_...`) via `db_operations.rename_preview_to_new()`
4. `db_operations.load_table()` is called — this rebuilds `ColumnTypes` and `FilteringSQL` for the new table state
5. `db_operations.update_rankings()` regenerates `rankings_<new_table>` from the freshly written errors table
6. Returns `{ success: true, table: "<new_table_name>" }` — the frontend uses this to update the global table name context

### `POST /api/wrangle/delete-column`
Drops a column in-place:
1. `ALTER TABLE DROP COLUMN` (via `app/db_utils/query.py` → `delete_column()`)
2. `update_errors_table()` — re-runs all detectors and rewrites `errors_<table>`
3. Returns the updated column list to the frontend

**Two endpoints** in `app/routes/plot_routes.py`:
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

**Additional endpoints** in `app/routes/routes.py`:

### `POST /api/undo`
Calls `PGraph.undo_pgraph()` — walks one step toward the root in the provenance graph using each node's `parent_table` pointer (no more decrementing the node ID in the string). Verifies the target table still exists in Postgres, then calls `db_operations.load_table()`. Returns `{ success: true, table_name }`.

### `POST /api/redo`
Calls `PGraph.redo_pgraph()` — walks one step forward, choosing the most recently added child of the current node when a branch exists. Same existence check and load. Returns `{ success: true, table_name }`.

### `GET /api/tablename`
Returns the current `db_operations.main_table_name` — useful for the frontend to verify what the backend thinks the active table is.

**Pgraph endpoints** in `app/routes/pgraph_routes.py`:

### `GET /api/routes/update_pgraph`
Returns the serialized pgraph JSON: `{ nodes, edges, current_table, prev_table, next_table }`. The shape is tailored to React Flow / `dagre` layout — nodes have `{ id, data: { label } }` and edges have `{ id, source, target, label, animated }`. The frontend `PGraphContext` consumes this directly.

### `POST /api/setGraphToClickedNode`
Used when the user double-clicks a node in the visual graph. Body: `{ nodeId }`. Calls `PGraph.set_clicked_node_as_current(nodeId)` which:
1. Looks up the node, sets `prev_node_table_name = node.parent_table`
2. Sets `next_node_table_name` to the most recently added child if any (so subsequent redo from that point follows the latest branch)
3. Sets `current_node_table_name = nodeId`

The endpoint then calls `db_operations.load_table(nodeId)` so the backend is now operating on that table. The frontend updates `TableNameContext` and clears all visualization caches.

**Filter endpoints** in `app/routes/filter_routes.py`:
- `POST /api/filter/add` — converts a frontend selection (`viewType`, `cols`, `data`, `scaleX`, `scaleY`) into one OR-joined SQL predicate per click and forwards to `FilteringSQL.add_filters()`. One click = one filter index.
- `POST /api/filter/clear` — clears one or more filter indices, or all of them if the indices list is empty.

**SQL primitives** all live in `app/db_utils/query.py`:
- `remove_rows_by_ids(table, ids)` — `DELETE WHERE "ID" = ANY(:ids)`
- `impute_by_ids(table, column, ids)` — `UPDATE ... SET col = :fill_val WHERE "ID" = ANY(:ids)`
- `delete_column(table, column)` — `ALTER TABLE DROP COLUMN`

---

## 4. DBOperations

`DBOperations` is an object defined in `app/db_utils/db_functions_sql.py` and instantiated once in `app/__init__.py`:

```python
db_operations = DBOperations(engine)
```

It is imported directly into the route modules (`routes.py`, `plot_routes.py`, `wrangler_routes_sql.py`, `pgraph_routes.py`, `filter_routes.py`) and into `app/server_utils/service_helpers.py`.

Route modules under `app/routes/` are auto-imported in `app/__init__.py` via `pkgutil.iter_modules(...)` — adding a new file in `app/routes/` is enough to register its endpoints, no manual import line needed.

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
- `load_table(table, errors_table)` — called on upload, after every wrangle execute, on undo/redo, and on graph node double-click; instantiates fresh `ColumnTypes` and `FilteringSQL` for the new table
- `reset()` — called when user navigates home; sets all attributes back to `None`
- `update_rankings(table)` — reads `errors_<table>`, recomputes per-attribute error counts, writes `rankings_<table>`. Called after every wrangle execute.
- `drop_preview_tables(...)` / `rename_preview_to_new(...)` — preview promotion helpers used by `execute_wrangle_preview()`.

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

`ColumnTypes` is defined in `app/db_utils/column_types.py`. Instantiated inside `DBOperations.load_table()` and `DataProfile.__init__()`

It classifies every column into one of five sets: pure numeric, pure categorical, mixed numeric, mixed categorical.
This classification is used not only to determine how to bin the data for histograms, to determine how to impute missing values in previews,
and also determine how summary stats should be calculated for each column. The classification is based on the declared Postgres type and the actual values in the column.

| Set               | Attribute                | Contents                                                                                                                                                                  |
|-------------------|--------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Numeric           | `pure_numeric_cols`      | Columns with a PostgreSQL numeric type (`integer`, `bigint`, `numeric`, `real`, `double precision`, `smallint`) or with a value that can be converted into a numeric type |
| Pure categorical  | `pure_categorical_cols`  | Non-numeric columns whose values contain no numeric-looking strings                                                                                                       |
| Mixed categorical | `categorical_mixed_cols` | Non-numeric columns that contain some values matching `^\s*-?\d+(\.\d+)?\s*$` but are __majority__ categorical                                                            |
| Mixed numeric     | `numeric_mixed_cols`     | Numeric columns that contain __majority__ numeric values                                                                                                                  |
| Mixed             | `mixed_cols`             | All columns that have mixed values (categorical_mixed_cols and numeric_mixed_cols combined)                                                                               |

**How classification works:**
1. Queries `information_schema.columns` for the column's declared Postgres type — these types are originally detected and set in Postgres during the initial upload in `app/routes/routes.py`. The function `load_file()` calls `get_sqlalchemy_dtype_map()` (in `service_helpers.py`), the helper which inspects each column's actual values to pick `BigInteger` / `Float` / `Text`.
2. Categorizes into `pure_categorical_cols`, `pure_numeric_cols`, or `mixed_cols` based on the declared type
3. For all `mixed_cols`, runs a regex check against the actual values in the table and splits them into `numeric_mixed_cols` vs. `categorical_mixed_cols` based on whether the majority of values are numeric-looking or not

**Where it's used:** 
- Everywhere inside `DBOperations` that builds SQL. The classification controls whether a column gets numeric `width_bucket` binning or categorical label-group binning in the CTE queries. Helper methods — `is_numeric_col()`, `is_categorical_col()`, `is_mixed_col()` — are called throughout.
- `DataProfile` uses it to determine which summary stats to compute for each column. `DataProfile` doesnT use the column types of `DBOperations` because a preview might be modified in such a way that the column types do not match anymore.

---

## 6. DataProfile
`DataProfile` is defined in `app/server_utils/data_profile.py`.
It is instantiated inside `load_file()` in routes.py, in `update_data_profile_table()` in wrangle_routes_sql.py, and in `execute_wrangle_preview()` in service_helpers.py. 
It is used to compute summary statistics for each column in the current table. These summary statistics are primarily used to give
the AI assistant additional information about the current state of the data, which can help it make better suggestions for data wrangling operations.
The summary statistics are calculated using SQL instead of pandas functions to avoid loading the entire dataset into memory, which can be inefficient for large datasets.

There are multiple instances of `DataProfile` in the codebase because a new instance is created every time a table is updated.
The summary statistics are stored in a Postgres table called `dp_<table_name>`, where `<table_name>` is the name of the main
table for which the statistics are computed. 

The summary statistics include:

| Attribute      | Description                                              | Type of data          |
|----------------|----------------------------------------------------------|-----------------------|
| `mean`         | The mean of the column                                   | Numeric               |
| `median`       | The median of the column                                 | Numeric               |
| `min`          | The minimum value of the column                          | Numeric               |
| `max`          | The maximum value of the column                          | Numeric               |
| `n_categories` | The number of unique categories in the column            | Categorical           |
| `mode`         | The most common value in the column                      | Categorical           |
| `category_counts` | The number of occurrences of each category in the column | Categorical           |
| `error_counts` | Counts of each error in the column                       | Numeric & Categorical |

## 7. Logs
There are several logs within Buckaroo that are used to track the state of the application and to help with debugging. 
Each of these logs is stored in a Postgres table and is updated whenever a relevant event occurs. 
The logs include:

| Log Name    | Table Name  | Description             | Purpose                                                                                                                                                |
|-------------|-------------|-------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|
| `action_log` | "action_log" | Log of all user actions | Keeps track of user actions so they can be given to LLM                                                                                                |
| `preview_log` | "preview_log" | Log of all preview actions | Used for keeping track of which action is associated with the preview dataset so we know what columns & rows were selected when user chooses an action |

### Action Log
The `action_log` table is used to keep track of all user actions within the application.
The action log is kept the same regardless of the user session, so all user sessions get logged in the same log without a reset.

Here are the following actions that are tracked in the action log:

| Action Name                  | Description          |
|------------------------------|----------------------|
| `load_dataset`               | User loads a dataset |
| `<wrangle_executed>_wrangle` | User performs a wrangle |
| `delete_column`              | User deletes a column |

Here is the additional information that is tracked for each action in the action log:

| Attribute Name        | Description                                                                 |
|-----------------------|-----------------------------------------------------------------------------|
| `action_id`           | Unique identifier for the action, autoincrements by 1 for each action       |
| `dataset_id`          | Base table name that is being wrangled                                      |
| `action_name`         | Name of the action being performed                                          |
| `action_details`      | JSON string of details of the action performed (rows & cols being wrangled) |
| `timestamp`           | Timestamp of when the action was performed                                  |
| `action_duration`     | Duration of the action in seconds                                           |
| `action_successful`   | Whether or not the attempted action was performed successfully              |
| `action_error_message` | Error message if the action failed                                          |


## Preview Log
The `preview_log` table is used to keep track of all preview actions within the application.

Here are the columns of the preview log table:

| Column Name          | Description               |
|----------------------|---------------------------|
| `preview_table_name` | Name of the preview table |
| `action_name`         | Name of the action being previewed |
| `action_details`      | JSON string of details of the action being previewed (rows & cols being wrangled) |


## 8. AI Action Planning

The addition of the AI assistant to Buckaroo is a major new feature that allows users to get suggestions for data wrangling operations based on the current state of the dataset. 
The AI assistant uses a large language model (LLM) to analyze the dataset and provide recommendations for cleaning and transforming the data.

The main purpose of the AI assistant is to _guide_ users through the data wrangling process rather than replace them.
It guides the user by giving what it believes to be the best n actions given the current state of the dataset and allowing the user to act upon these suggestions, if they feel they are appropriate.

The action planning process is as follows:
1. The LLM is queried for the best n actions in _text form_ given the current state of the dataset. It is given the following information as context:
- The full, current dataset
- The full DataProfile for the current dataset
- The error log for the current dataset
- The action log for the current dataset
- The preview log for the current dataset

2. The LLM is then queried to convert the text form of the actions into _structured JSON_ that can be used to provide suggestions to the user.

### Settings Table

The settings table is used for keeping track of the settings for the AI assistant. Only one row of this table should be being used at the moment, but when we expand the system to support multiple users, we will need to have a row for each user.
Here are the columns of the settings table:

| Column Name  | Description                                                                          |
|--------------|--------------------------------------------------------------------------------------|
| `model_name` | Name of the model to query                                                           | 
| `provider`    | Provider of the model. This value is used to get the provider API key stored in .env |

## 6. FilteringSQL

`FilteringSQL` is defined in `app/db_utils/filtering_sql.py` and instantiated inside `DBOperations.load_table()`.

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
6. User double clicks a table: backend switches `db_operations`, returns new name, frontend updates context
---

## 8. Provenance Graph & Undo/Redo

Every table name is prefixed with a node ID: `n0_`, `n1_`, `n2_`, etc. The original uploaded table is always `n0_`. Each wrangle operation creates a new node with an incremented ID. Users can double click on a node in the React Flow visualization to load that node's table from the database.

The provenance graph is a real DAG held in memory (not just a node-ID convention). Undo, redo, and node-click navigation are all driven by the graph's internal pointers — the old "parse the n# out of the string" path is gone.

### PGraph (`app/pgraph/pgraph.py`)

State:
- `node_map` — dict `{ table_name: GraphNode }`
- `node_count` — used to mint the next node ID via `get_new_node_id()` → `f"n{node_count}"`
- `wrangle_map` — `{ node_count: wrangle_op_string }` for post-hoc metadata
- `root_node` — table name of the original `n0_` upload
- `current_node_table_name`, `prev_node_table_name`, `next_node_table_name` — three pointers that drive navigation

Mutators:
- `add_root_node(node)` — called once from `init_pgraph_for_session()` on upload. Sets `current = root`.
- `add_node(node)` — called by `n_wrangle()` after each wrangle execute. Appends `new_node_table_name` to its parent's `children` list, advances `current → new`, and sets `prev → previous current`.
- `undo_pgraph()` — `next ← current; current ← prev; prev ← current.parent_table`. Returns the new current table name (or `None` at the root).
- `redo_pgraph()` — `prev ← current; current ← next; next ← last child of new current` (or `None` if it's a leaf).
- `set_clicked_node_as_current(table_name)` — used by `POST /api/setGraphToClickedNode`. Jumps the three pointers so subsequent undo/redo make sense from anywhere in the graph: `prev = node.parent_table`, `next = last child if any`, `current = node`.

Serialization for the frontend (`__json__`):
```
{
  "nodes": [{ "id": <table_name>, "data": { "label": <table_name> } }, ...],
  "edges": [{ "id": "e<src><dst>", "source": <src>, "target": <dst>,
              "type": "edgeType", "animated": "true",
              "label": <child.wrangle_op> }, ...],
  "current_table": ..., "prev_table": ..., "next_table": ...
}
```
This shape is deliberately tailored to React Flow + `dagre` layout — see `ui/src/store/PGraphContext.jsx`.

### GraphNode (`app/pgraph/node.py`)

- `parent_table`, `wrangle_op`, `table_name`, `error_table_name`, `children: list[str]`
- Quality metrics on the node: `anomaly_metric`, `missing_metric`, `incomplete_metric`, `mismatch_metric` (set via `update_metrics`; not yet wired into the visualization)
- `add_child(child_table_name)` — called by `PGraph.add_node()` to keep the parent's child list in sync

### Session state (`app/__init__.py`)

- `wrangle_occurred` — boolean, kept for legacy callers
- `app.pgraph_for_session` — the `PGraph` instance. Initialized to `None`; populated by `init_pgraph_for_session(root_table)` at the end of upload, which also creates and inserts the root `GraphNode` with `parent_table = "root"` and `wrangle_op = "root"`.

### Wrangle → node creation flow (`server_utils/service_helpers.py`)

1. `execute_wrangle_preview()` calls `n_wrangle(parent_table, child_table, wrangle_executed)`
2. `n_wrangle` calls `make_new_table_name(child_table)` which builds `f"{pgraph.get_new_node_id()}{child_table[2:]}"` — i.e. swap the existing `n#_` prefix on the (already-trimmed) preview table for the next node ID
3. A fresh `GraphNode(parent_table, wrangle_op, new_table_name, errors_<new>)` is added to the pgraph **before** any DB rename, so the pgraph is the canonical source of the new name
4. The DB rename + reload + rankings update happen using that name

The `wrangle_op` string is extracted from the chosen preview's suffix via `extract_preview_action()` (e.g. `"impute_y"` from `..._preview_impute_y`) and ends up as the edge label in the graph.

### Frontend graph (`ui/src/visualizations/PGraph.jsx` + `ui/src/store/PGraphContext.jsx`)

- Built on `@xyflow/react` (React Flow) with `@dagrejs/dagre` for auto-layout
- `PGraphProvider` owns `nodes`, `edges`, `onConnect`, `onLayout`, and `onNodeDoubleClick`
- `onNodeDoubleClick(event, node)` calls `setGraphToClickedNode(node.id)` (which hits `POST /api/setGraphToClickedNode`), updates `tableName` in `TableNameContext`, clears all viz caches (`clearScatterPlotCache/HeatMap/Histogram`), and bumps `ViewContext.refreshKey` to remount panels
- `PGraph.jsx` highlights the active node green (`#64ea96`) and others white, and renders a `MiniMap` + `Controls` + `Background`
- Custom node component lives in `ui/src/graph_objects/NodeTypes.jsx` (`SelectedNode`)

### Undo/Redo navigation

- `POST /api/undo` → `get_pgraph_undo()` → `PGraph.undo_pgraph()` → if a previous table is returned and exists in Postgres, `db_operations.load_table()` reloads it
- `POST /api/redo` → `get_pgraph_redo()` → mirror of the above
- The old wrangled tables are **never** deleted — they remain in Postgres, so navigation between any two nodes is instant

---

## 9. Rankings Table

For every loaded data table there is a companion `rankings_<table>` with columns `attribute, total_errors, rank` — attributes ordered by total error count.

- Built on upload in `app/routes/routes.py` → `load_file()` via `calculate_attribute_rankings()` (in `service_helpers.py`)
- Refreshed after every wrangle execute by `DBOperations.update_rankings(new_table_name)`
- Consumed by `app/server_utils/data_attribute_summary_integration.py` → `get_default_attributes_from_rankings()` to pick the top-3 attributes that appear pre-selected in the Attribute Summary panel

It is the third sibling family next to `errors_` and `<name>_filtering`, which is why `_safe_pg_name()` budgets identifier length around all three.

---

## 10. Frontend Contexts & View Modes

The upload flow lives in `ui/src/App.jsx`. Once the user uploads, `App` wraps `Buckaroo` in `TableNameProvider` and `LoadingProvider`. `Buckaroo.jsx` then layers the rest of the providers (order matters because `RepairProvider` consumes `SelectionContext` and `LoadingContext`):

```
<ViewContext.Provider> (refreshKey, activeView)
  <SettingsProvider>
    <PGraphProvider>
      <RowRangeProvider>
        <SelectionProvider>
          <RepairProvider onWrangleExecuted={...}>
            <BuckarooHeader /> + main panels
```

| Context | File | Purpose |
|---------|------|---------|
| `TableNameContext` | `ui/src/store/TableNameContext.jsx` | Global `tableName` + `setTableName`. Single source of truth on the frontend; cache keys and `useEffect` dependencies use it. |
| `LoadingContext` | `ui/src/store/LoadingContext.jsx` | Ref-counted `addLoader` / `removeLoader` so multiple in-flight calls share one spinner. `isLoading` drives the green/yellow dot in `TableStatus`. |
| `SettingsContext` | `ui/src/store/SettingsContext.jsx` | App-level settings (currently `axisTextSize`, persisted to a CSS custom property). |
| `PGraphContext` | `ui/src/store/PGraphContext.jsx` | Owns the React Flow nodes/edges + dagre layout + `onNodeDoubleClick`. See section 8. |
| `RowRangeContext` | `ui/src/store/RowRangeContext.jsx` | Row ID range for the table panel viewport. |
| `SelectionContext` | `ui/src/store/SelectionContext.jsx` | Shared row/column selection state — drives both the highlight overlays and the repair flow's input. |
| `RepairContext` | `ui/src/store/RepairContext.jsx` | Centralizes wrangle actions (`handleUndo`, `handleRedo`, `triggerRepairSelection`) and the busy/has-selection flags consumed by the header buttons. Calls back `onWrangleExecuted` so the parent can clear viz caches and bump `refreshKey`. |
| `ViewContext` | declared in `ui/src/pages/Buckaroo.jsx` | `activeView` ("both" / "graph" / "plots") and `refreshKey` (force-remount of the panel container). |

**Three view modes** are toggled from the header (`ui/src/elements/Header.jsx` → `BuckarooHeader`):
- `"plots"` — `MatrixView` + `RepairPanel`
- `"both"` — `MatrixView` + `PGraph` + `RepairPanel`
- `"graph"` — `PGraph` only

The header also renders `TableStatus` (active-table label `n# - <basename>` plus a loading dot driven by `LoadingContext`) and the Repair / Undo / Redo / Settings / Home buttons. Repair, Undo, Redo all call into `RepairContext` rather than panel-local state, so the same buttons work regardless of which panel is open.

**Visualization caches** live in `ui/src/store/visualizationCaches.jsx` — `clearScatterPlotCache`, `clearHeatMapCache`, `clearHistogramCache`. They are cleared after every wrangle execute, undo, redo, or graph node double-click so the frontend never serves stale plots after a backend table swap.

---

## 11. Backend Package Layout

The backend was reorganized into subpackages so adding new endpoints / SQL helpers / detectors doesn't pollute the top-level `app/`.

```
app/
├── __init__.py                  # engine, db_operations, pgraph_for_session,
│                                # auto-imports app/routes/* via pkgutil
├── pgraph/
│   ├── pgraph.py                # PGraph DAG
│   └── node.py                  # GraphNode
├── routes/                      # auto-imported; one file per endpoint group
│   ├── routes.py                # upload, preloaded, tablename, undo, redo, reset
│   ├── plot_routes.py           # histograms, scatterplot, preview-*, summaries
│   ├── wrangler_routes_sql.py   # create-previews, execute, delete-column
│   ├── filter_routes.py         # /api/filter/add, /api/filter/clear
│   └── pgraph_routes.py         # /api/routes/update_pgraph, /api/setGraphToClickedNode
├── db_utils/
│   ├── db_functions_sql.py      # DBOperations + ColumnTypes
│   ├── filtering_sql.py         # FilteringSQL
│   ├── execute_sql.py           # fetch_sql / execute_sql wrappers
│   └── query.py                 # remove_rows_by_ids, impute_by_ids, delete_column
└── server_utils/
    ├── service_helpers.py       # detector orchestration, preview creation,
    │                            # wrangle execution, pgraph entry points,
    │                            # _safe_pg_name, generate_table_name
    ├── set_id_column.py         # adds the "ID" column on upload
    └── data_attribute_summary_integration.py
                                 # rankings + per-attribute distributions for the summary panel
```

When adding a new endpoint, drop a new file in `app/routes/` — `app/__init__.py` discovers and imports it on startup, no registration line required.

---

## 12. Key Files

| File | Role |
|------|------|
| `detectors/missing_value.py` | Missing value detector |
| `detectors/datatype_mismatch.py` | Type mismatch detector |
| `detectors/anomaly.py` | Statistical outlier detector |
| `detectors/incomplete.py` | Rare-category detector |
| `app/__init__.py` | Engine init, global `db_operations`, `pgraph_for_session`, route auto-import |
| `app/db_utils/db_functions_sql.py` | `DBOperations` (line 115) + `ColumnTypes` (line 22) |
| `app/db_utils/filtering_sql.py` | `FilteringSQL` class |
| `app/db_utils/query.py` | SQL primitives: delete rows, impute, drop column |
| `app/db_utils/execute_sql.py` | `fetch_sql` / `execute_sql` thin wrappers |
| `app/server_utils/service_helpers.py` | Preview creation, wrangle execution, detector orchestration, `_safe_pg_name`, pgraph entry points (`init_pgraph_for_session`, `n_wrangle`, `make_new_table_name`) |
| `app/server_utils/data_attribute_summary_integration.py` | Rankings + attribute distributions for the summary panel |
| `app/server_utils/set_id_column.py` | Adds the canonical `ID` column on upload |
| `app/routes/routes.py` | Upload, preloaded, reset, undo/redo, tablename |
| `app/routes/wrangler_routes_sql.py` | Wrangle API endpoints (create-previews, execute, delete-column) |
| `app/routes/plot_routes.py` | Histogram, scatterplot, preview-histogram, preview-scatterplot, summaries |
| `app/routes/filter_routes.py` | `/api/filter/add`, `/api/filter/clear` |
| `app/routes/pgraph_routes.py` | `/api/routes/update_pgraph`, `/api/setGraphToClickedNode` |
| `app/pgraph/pgraph.py` | `PGraph` class — provenance DAG with current/prev/next pointers |
| `app/pgraph/node.py` | `GraphNode` class — individual wrangle node |
| `ui/src/App.jsx` | Top-level: upload state, wraps `Buckaroo` in `TableNameProvider` + `LoadingProvider` |
| `ui/src/pages/Buckaroo.jsx` | Layered context providers, view mode (`plots` / `both` / `graph`), main layout |
| `ui/src/elements/Header.jsx` | `BuckarooHeader` with view toggles, `TableStatus`, Repair / Undo / Redo / Settings / Home |
| `ui/src/store/TableNameContext.jsx` | Global `tableName` + `setTableName` |
| `ui/src/store/LoadingContext.jsx` | Ref-counted spinner state |
| `ui/src/store/SettingsContext.jsx` | App-level settings (axis text size etc.) |
| `ui/src/store/RepairContext.jsx` | Wrangle action centralization (undo/redo/repair triggers) |
| `ui/src/store/SelectionContext.jsx` | Shared row/column selection state |
| `ui/src/store/RowRangeContext.jsx` | Row range (filtering by ID range) |
| `ui/src/store/PGraphContext.jsx` | React Flow nodes/edges, dagre layout, `onNodeDoubleClick` |
| `ui/src/store/visualizationCaches.jsx` | Cache + clear helpers for scatterplot / heatmap / histogram |
| `ui/src/visualizations/PGraph.jsx` | React Flow rendering of the provenance graph + active-node highlight |
| `ui/src/visualizations/HistogramBarChart.jsx` / `HeatMap.jsx` / `ScatterPlot.jsx` | Plot renderers |
| `ui/src/graph_objects/NodeTypes.jsx` | Custom React Flow node types (`SelectedNode`) |
| `ui/src/panels/RepairPanel.jsx` | Wrangle UI — create-previews, execute |
| `ui/src/panels/PreviewCard.jsx` | Renders preview histograms/heatmaps/scatterplots + execute button |
| `ui/src/panels/AttributeSummaryPanel.jsx` | Per-attribute summaries + default top-3 from rankings |
| `ui/src/utils/serverCalls.jsx` | Frontend API call helpers (now includes `getPGraph`, `setGraphToClickedNode`, `undoWrangle`, `redoWrangle`, `resetApp`) |

---

## 13. Things to be aware of

- **Detectors run in Python memory. - We should fix this** All four detectors operate on the full DataFrame before writing to Postgres. For large datasets this could be slow — there is no chunking or SQL-side detection.
- **`update_preview_error_table` is a stub.** In `app/routes/wrangler_routes_sql.py` the function is defined but its body is commented out. Previews currently rely on the real `update_errors_table` re-running detectors on the cloned preview tables in `create_previews_1d/2d`.
- **`create_minimal_preview_table` builds an invalid SQL statement.** In `service_helpers.py`, `CREATE TABLE ... (LIKE ... INCLUDING ALL)"` has a stray trailing quote. The function isn't currently called (the full `_clone_table_pair` path is used instead) but should be cleaned up before re-enabling minimal-preview behavior.
- **PGraph node IDs are never recycled.** `PGraph.node_count` only increments — undo/redo never decrement it, so a session that does many undo+new-wrangle cycles keeps minting new `n#` names rather than reusing an existing branch's number. Old tables stay in Postgres forever within a session.
- **`GraphNode.update_metrics` is plumbed but not called.** Per-node `anomaly_metric / missing_metric / incomplete_metric / mismatch_metric` exist on the class but no code path populates them yet — the visualization currently only shows table names and wrangle-op edge labels.
- **Quality metric overlay on graph nodes is not yet implemented.** `PGraph.serialize_nodes` only returns `{ id, data: { label } }`; metrics are not surfaced to the frontend.

