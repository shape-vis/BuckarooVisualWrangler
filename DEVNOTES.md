# Developer Notes

This document explains the structures that power Buckaroo Visual Wrangler. Read it before adding new files or
code, so what you add fits the architecture. Each module's own docstring goes into more depth; this is the map.

---

## Table of Contents

1. [Ground rules](#1-ground-rules)
2. [Tables and their companions](#2-tables-and-their-companions)
3. [Building a node](#3-building-a-node)
4. [Error detection](#4-error-detection)
5. [Candidates: repairs and AI suggestions](#5-candidates-repairs-and-ai-suggestions)
6. [Provenance graph and navigation](#6-provenance-graph-and-navigation)
7. [DBOperations, ColumnTypes and DataProfile](#7-dboperations-columntypes-and-dataprofile)
8. [Metrics, drift and comparing nodes](#8-metrics-drift-and-comparing-nodes)
9. [Threads](#9-threads)
10. [Endpoints](#10-endpoints)
11. [Frontend](#11-frontend)
12. [Backend package layout](#12-backend-package-layout)
13. [Tests](#13-tests)

---

## 1. Ground rules

- **SQL lives in `app/db_utils/` only.** Query builders are classes shaped like `DBOperations`
  (`db_functions_sql.py`): each public `generate_*` method lists its steps in a `*_steps = [...]` list, each step
  returns one CTE fragment (`WITH ...` for the first, `, name AS (...)` after), and the steps are run with
  `"".join(steps)` through `fetch_sql` / `execute_sql`. Payloads for the client are built in Postgres with
  `json_build_object` / `json_agg`. Python only does arithmetic on the aggregates that come back.
- **The AI never writes SQL.** The model picks an operation, a column and an error type from closed enums; the
  server resolves the rows from the error flags and runs fixed, parameterized SQL (`app/server_utils/ai_wrangle.py`).
- **Readable over clever.** No dense one-liners, nested comprehensions or chained ternaries: explicit loops and
  named intermediate values. Comments explain *why*, in plain prose.
- **Identifiers** interpolated into SQL are quoted with `quote_identifier` / `quote_literal` from `execute_sql.py`,
  and column names are checked against the table's own columns (`ColumnTypes`) first.

---

## 2. Tables and their companions

Every node's data table has companions, all named from it:

| Table | Built by | Holds |
|-------|----------|-------|
| `<table>` | upload, or a candidate's clone + wrangle | the data, with an integer `"ID"` column naming each row for good |
| `errors_<table>` | `DetectorSQL` | one row per flagged cell: `(row_id, column_id, error_type)`, `row_id` being the row's `"ID"` |
| `dp_<table>` | `DataProfile` | the data profile: per column, its statistics and its error / category counts |

**Names.** The root is `n0a_<file>_<random>`. Every node since is staged as a candidate first and keeps the
candidate's name, `c<n>_<base>`, for good; its label (`n2c`) is assigned when it is accepted, and the name never
changes. A companion's name comes only from `errors_table_name` / `profile_table_name` in `execute_sql.py`, whose
`COMPANION_PREFIXES` list every companion. `safe_pg_name` (`service_helpers.py`) hash-truncates names so the longest
companion stays within Postgres' 63-character limit.

`DBOperations.drop_node_tables(table)` drops a table with all its companions (`node_table_names`).

---

## 3. Building a node

`build_node(table, root_table)` in `app/server_utils/service_helpers.py` builds everything a node is read through,
from its stored table. Upload builds the root this way, and every candidate is built the same way, so a node's
measurements never depend on how it was made:

1. `DetectorSQL(...).generate_errors_table()` - the errors table
2. `build_data_profile_table` - the data profile, every column in one query, its error counts included
3. the table's rows, counted once for the two steps below
4. `compute_node_metrics` - error rates, read from the data profile in one read (`app/pgraph/metrics.py`)
5. `compute_node_distortion` - drift from root, its columns measured concurrently (`app/pgraph/distortion.py`)

Upload (`load_file` in `app/routes/routes.py`) reads the CSV, adds `"ID"` (`set_id_column`), picks each column's
SQL type from its values (`get_sqlalchemy_dtype_map`), writes it with `COPY` (`copy_insert`), builds it, and starts
the session's graph with it as the root (`init_pgraph_for_session`).

---

## 4. Error detection

`DetectorSQL` (`app/db_utils/detector_sql.py`) flags every cell of a table inside Postgres, in one multi-step query,
and writes the errors table with `CREATE TABLE AS`. The four error types:

| Type | Rule |
|------|------|
| `missing` | `NULL`, or text exactly `'null'` / `'undefined'` - `missing_cell_predicate` |
| `anomaly` | at least 10 numeric values, sample sd > 0, and \|x - mean\| > 2 sd |
| `mismatch` | text columns: values of the minority kind (number vs. text) |
| `incomplete` | text columns with at most 10 numeric values: values occurring fewer than 3 times |

A text column is judged by its distinct values, so each is parsed once however often it occurs. The structural
columns - `STRUCTURAL_COLUMNS` in `column_types.py`: `ID`, `Unnamed: 0`, and the `index` / `level_0` columns pandas can
leave behind - are never flagged, and metrics, drift and the AI's profile skip them too.

---

## 5. Candidates: repairs and AI suggestions

A candidate is a wrangle worked out but not yet accepted, staged as a **provisional node**: a full node of the graph
(a child of its parent, with its edge, metrics and drift, reachable by navigation and compare) that nothing may be
wrangled from until it is accepted. This is write-audit-publish. See `app/server_utils/candidates.py`.

- **Repairs.** `POST /api/wrangle/create-previews` stages every way of repairing the user's selection: delete and
  impute for one column; delete, impute x and impute y for two. They stand together, so `stage_all` stages all or
  none.
- **AI suggestions.** `POST /api/ai/suggest` builds the node's profile as text (`app/llm/profile.py`), asks Gemini
  which tools to call (`app/llm/gemini_client.py`, `app/llm/tools.py`), validates each call and resolves its rows
  from the error flags (`ai_wrangle.prepare`), and stages them with `stage_each` - each independently.
- **Accept / decline.** `POST /api/candidates/accept` publishes one (it gets its label and becomes current);
  `POST /api/candidates/discard` drops candidates and their tables. `POST /api/reset` drops every candidate.

Staging runs in three steps: **claim** table names under `WRANGLE_LOCK` (milliseconds), **build** each candidate on
`NODE_POOL` with no lock (`clone_table`, the wrangle from `query.py`, `build_node`), then **register** the nodes
under the lock. If the session's graph changed while they were building (a reset or a new upload), their tables
are dropped instead.

The wrangles themselves are `remove_rows_by_ids` and `impute_by_ids` in `app/db_utils/query.py`. An impute fills
with the column's mean, or its most common value if categorical, computed over its non-missing values.

---

## 6. Provenance graph and navigation

The graph is held in memory as `app.pgraph_for_session` (a `PGraph`, `None` before the first upload); read it
through `service_helpers.session_graph()`.

**`PGraph`** (`app/pgraph/pgraph.py`):
- `node_map` - `{table name: GraphNode}`; `root_table_name`
- `node_count` - how many nodes joined for good; it hands out labels (`node_id_for_count`: n0a ... n0z, n1a ... n9z)
- `candidate_count` - hands out candidate prefixes (`c0`, `c1`, ...), never reused
- `current_node_table_name`, `prev_node_table_name`, `next_node_table_name` - the navigation pointers

Navigation: `undo_pgraph` steps up to the current node's parent (and refuses at the root), `redo_pgraph` steps down
to the node undo left or the most recent child, and `set_clicked_node_as_current` jumps to a clicked node. The
routes that move the pointers take `WRANGLE_LOCK`, so a candidate can't be dropped mid-move. Old tables are never
deleted, so navigating between nodes is instant.

**`GraphNode`** (`app/pgraph/node.py`): `parent_table`, `wrangle_op` (`root`, `delete`, `impute`, `impute_x`,
`impute_y`), `wrangle_cols`, `children`, `metrics` (a `NodeMetrics`), `distortion`, `provisional`, `label`, and
`candidate` (where a candidate came from: repair or AI, its reason, row count, ...).

The graph is sent to the client by `GET /api/routes/update_pgraph` as `{nodes, edges, current_table, prev_table,
next_table, pareto}`.

---

## 7. DBOperations, ColumnTypes and DataProfile

**`DBOperations`** (`app/db_utils/db_functions_sql.py`) is instantiated once in `app/__init__.py` as
`db_operations`. `main_table_name` is the backend's single source of truth for the current table; `load_table(t)`
points it at a node (its errors and profile tables default to `errors_t` / `dp_t`). It builds the plots:
`generate_one_d_histogram_with_errors`, `generate_two_d_histogram_with_errors`, `generate_scatterplot_with_errors`,
plus bin/row lookups for selections, `generate_top_error_rows`, and table lifecycle helpers (`clone_table`,
`drop_node_tables`, `get_row_count`, `table_exists`). Every plotted column is checked against the table's own columns
before any name goes into a query. A numeric column's numbers are binned across their range - one bin a unit wide for
a column holding a single number - and a null or NaN in it becomes a label beside the bins; a text column is binned by
label. Plot routes for a node other than the current one make a `DBOperations` of their own, so the session's state
is untouched.

**`ColumnTypes`** (`app/db_utils/column_types.py`) classifies a table's columns, in one scan of its text columns:
`numeric_cols` (a numeric SQL type), `pure_categorical` (text with no numeric-looking values), and `mixed_cols` (text
holding some numbers), split into `numeric_mixed_cols` / `categorical_mixed_cols` by majority. `column_kind` is the
one rule for whether a column is summarized, profiled and measured as numeric or categorical. Get it through
`ColumnTypes.for_table(table, engine)`, which caches by table and oid; `ColumnTypes.forget(table)` drops a cached
entry, and a wrangle that changes rows forgets its table's.

The same module holds the rules every query builder reads a value by, so the views always agree:
`number_expression` (a value as a number), `missing_cell_predicate` (whether a cell is missing - the Missing
detector's rule) and `category_expression` (a cell as a category, missing cells as `NULL_LABEL`), plus the labels
the plots share (`NULL_LABEL`, `OTHER_LABEL`, `MAX_LABELS`, `REMOVED_LABEL`).

**`DataProfile`** (`app/db_utils/data_profile.py`) builds `dp_<table>` in one query: per column, by its kind, the mean,
median, min and max of a numeric column, or the category count, mode and category counts of a categorical one, and
every column's error counts. The mode leaves missing cells out and breaks ties by name - the value an impute fills
with. Metrics, the attribute summary and the AI's profile each read it back once (`read_stored_profile`).

---

## 8. Metrics, drift and comparing nodes

- **Metrics** (`app/pgraph/metrics.py`): per-column and node-level error rates per type, from the data profile. The
  attribute summary's error badges and default columns are read off a node's cached metrics.
- **Drift** (`app/pgraph/distortion.py`, SQL in `drift_sql.py`): how far each column has moved from root - W1/IQR
  for numeric columns, total variation distance for categorical ones - plus the facts about what the wrangles did
  (rows removed, cells changed). Column kinds are decided on root and held for every node. `drift_detail` serves the
  ridgeline and Sankey views and a plain-language annotation (`GET /api/pgraph/drift_detail`).
- **Across nodes** (`app/pgraph/pgraph.py`): `quality_trajectory` and `distortion_trajectory` give the series along a
  branch (`GET /api/pgraph/branch_trajectory`), both through `branch_deltas`. For **Pareto**, leaves carrying both an
  error total and a drift are ranked, and nodes beaten on both are marked dominated (`PGraph.pareto`,
  `pareto_frontier`). Drift measures root once - its spread per numeric column and its present cells are cached for
  every node measured from it.
- **Compare** (`app/db_utils/compare_sql.py`, `GET /api/pgraph/compare`): bins two nodes' tables on shared axes so
  their histograms and heatmaps line up. A mostly-numeric axis is binned across both states' range; anything else
  becomes labels, at most 20 with the tail folded into `(other)` - the most common kept, ties broken by name, as the
  Sankey folds its categories. Read-only, and only for tables in the graph.

---

## 9. Threads

`app/server_utils/workers.py` has two pools: `QUERY_POOL` (8) for independent queries and `NODE_POOL` (4) for whole
node builds. psycopg2 releases the GIL while Postgres works, so plain threads run in parallel. **The deadlock rule:**
a query task never submits more work or waits on a pool, and nothing waits on `NODE_POOL` from inside it. The
SQLAlchemy engine's connection pool (`pool_size=16, max_overflow=8`) is sized for both pools at once.

---

## 10. Endpoints

Route modules in `app/routes/` are imported automatically by `app/__init__.py` - a new file there is registered with
no import line.

| Module | Endpoints |
|--------|-----------|
| `routes.py` | `POST /api/upload`, `GET /api/preloaded`, `GET /api/tablename`, `POST /api/undo`, `POST /api/redo`, `POST /api/reset` |
| `plot_routes.py` | `GET /api/plots/1-d-histogram`, `2-d-histogram`, `scatterplot`, `top-error-rows`, `summaries`; `POST rows-in-bin`, `bins-for-rows`, `update-backend-attributes`; `GET preview-histogram`, `preview-scatterplot` (any node's table) |
| `wrangler_routes_sql.py` | `POST /api/wrangle/create-previews` (stages repair candidates) |
| `candidate_routes.py` | `POST /api/candidates/accept`, `POST /api/candidates/discard` |
| `ai_routes.py` | `GET /api/ai/status`, `POST /api/ai/suggest` |
| `pgraph_routes.py` | `GET /api/routes/update_pgraph`, `POST /api/setGraphToClickedNode`, `GET /api/pgraph/branch_trajectory`, `GET /api/pgraph/compare`, `GET /api/pgraph/drift_detail` |

Main-table endpoints read `db_operations.main_table_name` rather than taking a table from the client. Endpoints that
take a table name only accept nodes of the session's graph.

---

## 11. Frontend

React + Vite in `ui/src`. The graph is drawn with React Flow (`@xyflow/react`) and laid out with dagre; plots are d3.

- **`pages/`** - `Home` (upload) and `Buckaroo` (the workspace, with its view modes).
- **`store/`** - React contexts: `TableNameContext` (the current table, the frontend's source of truth),
  `PGraphContext` (graph nodes, edges, layout, selections A/B), `CandidatesContext`, `AISuggestionsContext`,
  `RepairContext`, `SelectionContext`, `CompareContext`, `PlotsWindowsContext` (the Plots view's windows, with
  `plotsWindows.js`), `LoadingContext`, `SettingsContext`, `RowRangeContext`; plus `visualizationCaches.jsx`,
  cleared whenever the backend changes table.
- **`visualizations/`** - the plots (`HistogramBarChart`, `HeatMap`, `ScatterPlot`), the graph (`PGraph`), the
  compare views (`ComparisonPlot`, ridgeline, Sankey) and the analysis plot.
- **`graph_objects/`** - custom React Flow nodes, including candidate (prospective) nodes.
- **`supportNodes/`** - supporting sub-nodes attached to a graph node (error plot and drift plot galleries, compare,
  sparkline), registered in `registry.js`. A hidden one shows as a badge on its node.
- **`panels/`, `elements/`** - the Plots view and its windows (attribute plots, compare, support nodes - all on
  `PlotsWindow`), the attribute summary and table panels, and shared UI.
- **`utils/serverCalls.jsx`** - every call to the backend.

---

## 12. Backend package layout

```
app/
├── __init__.py                  # engine, db_operations, pgraph_for_session, route auto-import
├── db_utils/                    # all SQL
│   ├── bootstrap.py             # creates the database at startup if it is missing
│   ├── db_functions_sql.py      # DBOperations: plots, table lifecycle
│   ├── column_types.py          # ColumnTypes, and the number / missing / category rules and shared labels
│   ├── data_profile.py          # DataProfile: the dp_ table
│   ├── detector_sql.py          # DetectorSQL: error detection
│   ├── compare_sql.py           # CompareSQL: two nodes on shared axes
│   ├── drift_sql.py             # DriftSQL: drift statistics
│   ├── query.py                 # wrangles by ID, flagged-row lookup, imputation value
│   └── execute_sql.py           # fetch_sql / execute_sql, companion table names, quoting, COPY insert
├── pgraph/
│   ├── pgraph.py                # PGraph, branch trajectories, Pareto
│   ├── node.py                  # GraphNode, wrangle labels
│   ├── metrics.py               # NodeMetrics
│   └── distortion.py            # drift arithmetic, annotations
├── llm/                         # prompt, tool declarations, Gemini client - no SQL, no writes
├── routes/                      # one file per endpoint group, auto-imported
└── server_utils/
    ├── service_helpers.py       # build_node, table naming, session graph access, WRANGLE_LOCK
    ├── candidates.py            # staging, accepting, declining candidates
    ├── ai_wrangle.py            # validating AI suggestions and resolving their rows
    ├── workers.py               # QUERY_POOL, NODE_POOL
    ├── set_id_column.py         # adds the "ID" column on upload
    └── data_attribute_summary_integration.py   # the attribute summary panel's payload
```

---

## 13. Tests

- `tests/unit` - pure logic, no database.
- `tests/sql` - against the local Postgres (`@pytest.mark.sql`): upload, the main view's plots, detection, compare,
  drift, data profile, candidates, AI routes, and a golden survey test of drift and Pareto.

Run both with `.venv/bin/pytest tests/unit tests/sql`.
