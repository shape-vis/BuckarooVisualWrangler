# Developer Notes

This doc walks through how Buckaroo Visual Wrangler is put together. If you're new to the codebase, read it before
you add any files or code, so that what you build fits in with what's already here. Think of it as a map: it tells
you where things are and how they connect. Each module's docstring goes into more detail.

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
12. [Codebase layout](#12-codebase-layout)
13. [Tests](#13-tests)

---

## 1. Ground rules

- **All SQL goes in `app/db_utils/`.** Every class that builds queries follows the same pattern as `DBOperations`
  (in `db_functions_sql.py`):
  - Each public `generate_*` method keeps its steps in a list named `*_steps = [...]`.
  - Each step returns one piece of a `WITH` query (a CTE). The first piece starts with `WITH ...`, and every piece
    after that looks like `, name AS (...)`.
  - The pieces are glued together with `"".join(steps)` and run with `fetch_sql` or `execute_sql`.

  Any data sent to the client is shaped into JSON inside Postgres, using `json_build_object` and `json_agg`. Python
  only does arithmetic on the totals and other aggregates that Postgres sends back.
- **The AI never writes SQL.** The model only gets to choose an operation, a column and an error type, and each of
  those comes from a fixed list of options. The server then works out which rows to change from the error flags and
  runs SQL that's already written and parameterized (`app/server_utils/ai_wrangle.py`).
- **Readable code beats clever code.** Avoid dense one-liners, nested comprehensions and chained ternaries. Write
  the loop out, and give in-between values their own names. Comments should explain *why* the code does something,
  in plain English.
- **Column and table names** that get put into SQL must be quoted with `quote_identifier` or `quote_literal` from
  `execute_sql.py`. Before that, check that the column name is actually one of the table's columns (`ColumnTypes`).

---

## 2. Tables and their companions

Every node in the graph has its own data table, and each data table has companion tables that go with it. The
companions are named after the data table:

| Table | Created by | What's in it |
|-------|------------|--------------|
| `<table>` | an upload, or by copying a table and applying a candidate's wrangle to it | the data itself, plus an integer `"ID"` column. A row's ID never changes. |
| `errors_<table>` | `DetectorSQL` | one row for each flagged cell: `(row_id, column_id, error_type)`. `row_id` is the row's `"ID"`. |
| `dp_<table>` | `DataProfile` | the data profile: for each column, its statistics, its error counts and its category counts |

**How tables are named.** The first table (the root) is named `n0a_<file>_<random>`. Every node after the root
starts out as a candidate, and its table is named `c<n>_<base>`. That name stays the same forever, even after the
candidate is accepted. Accepting it only gives the node a label, like `n2c`.

Companion table names should only ever come from `errors_table_name` and `profile_table_name` in `execute_sql.py`.
That file's `COMPANION_PREFIXES` lists every kind of companion table. Postgres doesn't allow names longer than 63
characters, so `safe_pg_name` (in `service_helpers.py`) shortens long names using a hash, which keeps even the
longest companion name under the limit.

To delete a table along with all of its companions, use `DBOperations.drop_node_tables(table)`. It finds them with
`node_table_names`.

---

## 3. Building a node

`build_node(table, root_table)` in `app/server_utils/service_helpers.py` takes a table that's already in the
database and builds everything else a node needs. The root is built this way when a file is uploaded, and every
candidate is built exactly the same way. Because of that, a node's numbers never depend on how the node was made.

Here's what it does, in order:

1. Runs `DetectorSQL(...).generate_errors_table()` to create the errors table.
2. Runs `build_data_profile_table` to create the data profile. This covers every column, including its error
   counts, in a single query. The error counts are a dictionary of the error types broken down by what column has what error types. This is a different structure than the errors table itself which has columns: {row_id, column_id, error_type}.
3. Counts the table's rows. This happens once, and the count is reused by the next two steps.
4. Runs `compute_node_metrics` to get the error rates. It reads the data profile once to do this
   (`app/pgraph/metrics.py`).
5. Runs `compute_node_distortion` to measure how far the data has drifted from the root. Each column is measured at
   the same time as the others (`app/pgraph/distortion.py`).

When a file is uploaded, `load_file` in `app/routes/routes.py`:
1. reads the CSV,
2. adds the `"ID"` column (`set_id_column`),
3. picks a SQL type for each column by looking at its values (`get_sqlalchemy_dtype_map`),
4. writes the data to Postgres with `COPY` (`copy_insert`),
5. runs `build_node` on it,
6. and starts the session's graph with this table as the root (`init_pgraph_for_session`).

It refuses a file pandas can't read as a table, such as an empty file, a binary one, or one with a quote that's never
closed, and returns `{"success": false}` with the reason. If an upload fails partway through, the tables it had
already built are dropped. `GET /api/preloaded` answers 404 for a name that isn't one of the provided datasets.

---

## 4. Error detection

`DetectorSQL` (`app/db_utils/detector_sql.py`) checks every cell of a table for errors. All the checking happens
inside Postgres, in one query with several steps, and the results are saved as the errors table with
`CREATE TABLE AS`. There are four kinds of error:

| Type | A cell is flagged when... |
|------|---------------------------|
| `missing` | it's `NULL`, or it's text that says exactly `'null'` or `'undefined'` (see `missing_cell_predicate`) |
| `anomaly` | its column has at least 10 numbers, the sample standard deviation is above 0, and the value is more than 2 standard deviations from the mean |
| `mismatch` | it's in a text column and it's the less common kind of value. If most values in the column are numbers, the text values are flagged, and if most are text, the numbers are flagged. |
| `incomplete` | it's in a text column that has 10 or fewer numbers, and its value shows up fewer than 3 times |

For text columns, each distinct value is only checked once, no matter how many rows it appears in.

Each error type is one **detector**: a `detect_<type>` method on `DetectorSQL`. A detector doesn't add steps to the
query. It returns its rule as SELECT branches (a `DetectorBranches`), and two steps gather every detector's branches:
- `flag_text_values` gathers the rules over a text column's distinct values.
- `collect_flagged_cells` gathers the rules over cells.

The measurements several rules share are steps of their own, so they're made once: each text value's count, number
and kind, and each numeric column's mean and spread.

The error types themselves are listed once, in `shared/error_types.json`, with each one's label, colour and how the
AI is told about it. The backend reads it in `app/error_types.py`, and `ERROR_TYPES` in `detector_sql.py` is its keys
in order. The frontend reads the same file in `ui/src/store/errorColors.js`.

### Adding a detector

1. Add an entry to `shared/error_types.json`. Its position is where the type shows up in every list.
2. Write a `detect_<key>` method on `DetectorSQL` that returns its branches. `DetectorSQL` refuses to start if a
   listed type has no method, so a missing one fails straight away instead of quietly flagging nothing.
3. Add the rule to `tests/stress/reference.py`'s `detect`. Until you do, the detector stress tests fail, because the
   new flags don't match the answer key.

That's all. The node metrics, the sparklines, the compare panel's measures, the attribute list, the table colours and
the AI's prompt and tools all read the new type from the JSON.

Some columns are just bookkeeping and never get flagged. Metrics, drift and the AI's profile ignore them too. They're
listed in `STRUCTURAL_COLUMNS` in `column_types.py`: `ID`, `Unnamed: 0`, and the `index` and `level_0` columns that
pandas sometimes adds.

---

## 5. Candidates: repairs and AI suggestions

A candidate is a change to the data (a wrangle) that has been worked out but that the user hasn't accepted yet.
Each candidate is added to the graph as a **provisional node**. A provisional node is a real node in every way: it
has a parent and an edge to that parent, it has its own metrics and drift, and you can navigate to it and compare it
with other nodes. The one thing you can't do is apply a new wrangle to it until it's been accepted. This approach is
known as write-audit-publish. The code is in `app/server_utils/candidates.py`.

There are two ways candidates get made:

- **Repairs.** `POST /api/wrangle/create-previews` creates a candidate for every possible way to repair what the
  user has selected. If one column is selected, that's delete and impute. If two columns are selected, it's delete,
  impute x and impute y. These candidates belong together, so `stage_all` either adds all of them or none of them.
  The route only accepts whole-number row IDs in bigint's range, so `1.5` or `"1"` is refused instead of cast. Every
  candidate, from either source, is refused before its table is copied unless its columns are data columns of the
  node (`_check_columns`). That rules out the structural `ID` column, which an impute would otherwise overwrite.
- **AI suggestions.** `POST /api/ai/suggest` writes up the node's profile as text (`app/llm/profile.py`) and asks
  Gemini which tools it wants to call (`app/llm/gemini_client.py`, `app/llm/tools.py`). Each call Gemini makes is
  validated, and its rows are found from the error flags (`ai_wrangle.prepare`). Then `stage_each` adds each
  suggestion on its own, so one failing doesn't affect the others.

Once candidates exist, the user can accept or decline them:

- `POST /api/candidates/accept` accepts a candidate. It gets a label and becomes the current node, and the support
  nodes it inherited from its parent open. See [Support nodes](#support-nodes).
- `POST /api/candidates/discard` removes candidates and deletes their tables.
- `POST /api/reset` removes every candidate.

Adding candidates to the graph takes three steps:

1. **Claim** the table names. This happens while holding `WRANGLE_LOCK`, but only for a few milliseconds.
2. **Build** each candidate on `NODE_POOL`, without holding the lock. Building means copying the parent's table
   (`clone_table`), applying the wrangle from `query.py`, and running `build_node`.
3. **Register** the new nodes in the graph, holding the lock again.

If the session's graph changed while the candidates were being built (because the user reset or uploaded a new
file), the new tables are deleted instead of registered.

The wrangles themselves are `remove_rows_by_ids` and `impute_by_ids` in `app/db_utils/query.py`. Impute fills cells
with the column's mean. If the column is categorical, it uses the most common value instead. Either way, the value is
calculated only from the cells that aren't missing. In a whole-number column the mean is rounded, so the column stays
whole numbers. That's intended.

Each operation is declared once, as a `WrangleOp` in `app/server_utils/wrangle_ops.py`. Each entry holds:
- how the operation runs
- its candidate's title and reason
- the sentence the compare panel describes its node with
- its AI tools, and the check an AI suggestion of it has to pass

Everything that offers, runs or describes a wrangle reads that entry:
- the repair route (`repair_options`)
- `candidates._build`
- the graph's labels in `node.py`
- `ai_wrangle` and `app/llm/tools.py`

An unknown operation is refused, not run as something else.

A node records its operation by name: `delete` or `impute`. When an operation that fills a column runs on a
two-column selection, the name gets an `_x` or `_y` suffix (`impute_y`) to say which column it filled.
`parse_wrangle_op` reads either form back.

### Adding a wrangle operation

1. Write its SQL in `app/db_utils/query.py`, following DBOperations' structure.
2. Add a `WrangleOp` to `WRANGLE_OPS` in `wrangle_ops.py`, with `fills_column` set if it writes one column. Its
   position is where its candidate is listed.
3. If the AI should be able to suggest it, give it `ai_tools` and an `ai_check`, add it to `AI_TOOL_OPS`, and add a
   sentence about when to use it to the rules in `app/llm/prompts.py`.
4. Add it to `tests/stress/reference.py` and to the wrangle stress tests' `expected_rows_for`.

An operation can edit or delete rows, but it can't create them. Drift, the Sankey's removed sink and the compare views
all rely on a node's rows being a subset of root's, and `check_row_identity` raises an error when they aren't.

---

## 6. Provenance graph and navigation

The graph lives in memory, in `app.pgraph_for_session`. It's a `PGraph` object, or `None` if nothing has been
uploaded yet. Use `service_helpers.session_graph()` to get it.

**`PGraph`** (`app/pgraph/pgraph.py`) keeps track of:
- `node_map`: a dictionary from each table name to its `GraphNode`. `root_table_name` holds the root's table name.
- `node_count`: how many nodes have been accepted into the graph. It's used to give out labels in order
  (`node_id_for_count` turns it into n0a ... n0z, then n1a ... n9z).
- `candidate_count`: used to give out candidate prefixes in order (`c0`, `c1`, ...). A prefix is never used twice.
- `current_node_table_name`, `prev_node_table_name` and `next_node_table_name`: these point to the current node and
  to where undo and redo will go.

Moving around the graph:
- `undo_pgraph` moves up to the current node's parent. It does nothing at the root.
- `redo_pgraph` moves back down the path undo came up, one node at a time, so several undos are redone in order.
  Each undo adds the node it left to `_redo_path`, and each redo takes it off again. Any other move (clicking a
  node, a new node) clears the path. With no undo to retrace, redo moves to the current node's newest child.
- `set_clicked_node_as_current` jumps straight to whatever node the user clicked.

Any route that moves these pointers holds `WRANGLE_LOCK` while it does, so a candidate can't be deleted halfway
through a move. Tables for old nodes are never deleted, which is why switching between nodes is instant.

**`GraphNode`** (`app/pgraph/node.py`) stores one node's details:
- `parent_table`
- `wrangle_op`: what was done to make this node (`root`, `delete`, `impute`, `impute_x` or `impute_y`)
- `wrangle_cols`: which columns the wrangle was applied to
- `children`
- `metrics`: a `NodeMetrics` object
- `distortion`
- `provisional`: whether it's still a candidate
- `label`: the name the user sees, like `n2c`. A candidate has no label until it's accepted.
- `candidate`: where a candidate came from, such as whether it was a repair or an AI suggestion, the reason for it,
  how many rows it affects, and so on
- `support_nodes`: the support nodes attached to this node, as plain JSON records. See
  [Support nodes](#support-nodes) below.

**Table name vs. label.** A node's table name is its ID, and it never changes. The label is just a display name.
When a candidate is accepted, `PGraph.publish` sets `provisional` to `False` and gives the node the next label.
Nothing in the database is renamed: an accepted candidate keeps its `c<n>_<base>` table, and so do its `errors_`
and `dp_` tables. This is on purpose. Sub-nodes, compare windows, and undo and redo all point at a node by its
table name, so renaming the table would break them.

### Support nodes

A support node is a small plot or panel the user attaches to a graph node to help read it. The kinds are an error
plot, a drift plot, the quality metrics, a sparkline, a comparison with another node, and the wrangle diff. Each one
is stored on its host's `GraphNode.support_nodes` as a record like this:

```
{id, hostId, kind, side, config, size, inherited, startMinimized}
```

A record only holds the settings that describe the support node, such as which plot it is and which columns it
uses. It never holds plot data. The frontend fetches a support node's data when it draws it, using the record's
`hostId` as the node to read from. Because records are small, copying them is cheap, and that's what makes
inheritance work.

**Inheritance.** When a candidate is staged, `PGraph.add_candidate` gives it a copy of each of its parent's support
nodes. The copies come from `inherited_support_nodes` in `app/pgraph/support_nodes.py`, and each copy is attached
to the candidate:

- **Error plot, drift plot, quality metrics:** the same settings, on the candidate. Their settings don't name a node,
  so they show the candidate's own data.
- **Compare:** the candidate takes the parent's place in the comparison (A or B), against the same comparator. The
  copy isn't in the parent's group, so the two don't keep each other's settings in sync. Zoom and the chosen
  categories start fresh, because they belonged to the parent's pair.
- **Sparkline:** the same starting edge, but the branch now ends at the candidate. Its values are cleared, and the
  frontend measures the branch again the first time the sparkline is drawn.
- **Wrangle diff:** not copied. It describes the one edge into its host, and the candidate has a different edge.

Every copy is marked `inherited` and `startMinimized`, so a new candidate shows its inherited support nodes as
badges instead of opening them all at once. When the user changes a copy, it stops being `inherited` and counts as
the user's own.

**Accepting.** `settle_inherited` runs when a candidate is accepted. It opens the copies that are still marked
`inherited`, so the accepted node shows them. Copies the user changed, and support nodes the user added to the
candidate themselves, are left as they are. Nothing is marked `inherited` afterwards.

**Keeping the records up to date.** The frontend changes its own copy of a record first, then sends the change to
`POST`, `PATCH` or `DELETE /api/pgraph/support_nodes`. The `PATCH` requests are delayed slightly, so that a resize
sends one request when it finishes instead of one per movement. Every graph the server sends includes each node's
`support_nodes`, and the frontend reads in any records it hasn't seen before. That covers every record when the
page loads, and the copies a new candidate inherited. Which support nodes are hidden or minimised is stored only in
the frontend, because it's about how the user is looking at them, not about the support nodes themselves.

`provisional` and `label` are only stored in memory, on the `GraphNode`. The database doesn't record them. Looking
at the tables, you can't tell whether `c1_<base>` was accepted or is still waiting, because both look the same. You
can only tell that it wasn't declined, because declining a candidate deletes its tables. To find out a node's
status and label, check the graph (`GET /api/routes/update_pgraph`).

**Example.** The user uploads `test_impute_debug.csv`, then creates two new nodes:

1. The upload becomes the root. Its table is `n0a_test_impute_debug_YajJW` and its label is `n0a`. The root is the
   only node whose table name and label match.
2. The user selects some rows on the root and asks for repairs. This stages two candidates, one for delete and one
   for impute. Their tables are `c0_test_impute_debug_YajJW` and `c1_test_impute_debug_YajJW`. Neither has a label
   yet.
3. The user accepts the impute candidate. `c1_test_impute_debug_YajJW` gets the label `n0b` and becomes the current
   node. The delete candidate stays staged next to it.
4. From `n0b`, the user asks for AI suggestions and accepts one. Its table is `c2_test_impute_debug_YajJW` and it
   gets the label `n0c`.
5. The user declines the delete candidate. `c0_test_impute_debug_YajJW` and its companion tables are deleted.

At the end, the graph and the database line up like this:

| Label (shown in the app) | Table (in the database) | Status |
|---|---|---|
| `n0a` | `n0a_test_impute_debug_YajJW` | root |
| `n0b` | `c1_test_impute_debug_YajJW` | accepted |
| `n0c` | `c2_test_impute_debug_YajJW` | accepted |

The two numbers count different things, so they don't have to line up. Labels count accepted nodes (`node_count`).
Candidate prefixes count every candidate ever staged, including declined ones (`candidate_count`). Every table
keeps the root's base (`test_impute_debug_YajJW`), whichever node it was made from.

The client fetches the graph from `GET /api/routes/update_pgraph`. The response looks like
`{nodes, edges, current_table, prev_table, next_table, pareto}`.

---

## 7. DBOperations, ColumnTypes and DataProfile

### DBOperations

`DBOperations` (`app/db_utils/db_functions_sql.py`) is created once, in `app/__init__.py`, and stored as
`db_operations`. Its `main_table_name` is what the backend treats as the current table, and nothing else should be
used for that. Calling `load_table(t)` switches it to a different node. Unless told otherwise, it then uses
`errors_t` and `dp_t` as that node's errors and profile tables.

It's responsible for:
- building the plots: `generate_one_d_histogram_with_errors`, `generate_two_d_histogram_with_errors` and
  `generate_scatterplot_with_errors`
- looking up which bins and rows are in a selection
- `generate_top_error_rows`
- creating, deleting and checking tables: `clone_table`, `drop_node_tables`, `get_row_count` and `table_exists`

Before any column name goes into a query, it's checked against the table's actual columns.

How plots are binned:
- A numeric column is split into bins across its range of values. If every value in the column is the same number,
  you get a single bin that's one unit wide.
- If a numeric column has nulls or NaNs, they're shown as a separate labeled bar next to the bins.
- A text column gets one bin per label.

When a plot is requested for a node that isn't the current one, the route creates a separate `DBOperations` for it.
That way the session's current state doesn't change.

### ColumnTypes

`ColumnTypes` (`app/db_utils/column_types.py`) figures out what kind of data each column holds. It does this by
scanning the table's text columns once. The groups are:
- `numeric_cols`: columns stored as a number type in SQL
- `pure_categorical`: text columns where nothing looks like a number
- `mixed_cols`: text columns where some values are numbers. These are split again by whichever kind is in the
  majority: `numeric_mixed_cols` (mostly numbers) and `categorical_mixed_cols` (mostly text).

`column_kind` is the single place that decides whether a column is treated as numeric or categorical when it's
summarized, profiled and measured.

To get a table's column types, call `ColumnTypes.for_table(table, engine)`. The result is cached, keyed by the table
and its oid. `ColumnTypes.forget(table)` clears a table's cached entry, and any wrangle that changes rows calls it.

This module also defines the shared rules that every query uses to read a cell. Because everything uses the same
rules, all the views show consistent results:
- `number_expression`: how to read a value as a number. Text counts as a number when it's digits, with an optional
  minus sign and fraction, and only ASCII spaces around it (`NUMERIC_TEXT_REGEX`). A number padded with a unicode
  space, such as a non-breaking space pasted from a spreadsheet, is text, because Postgres can't cast it.
- `missing_cell_predicate`: how to tell if a cell is missing. This is the same rule the `missing` error check uses.
- `category_expression`: how to read a cell as a category. Missing cells come out as `NULL_LABEL`.

It also defines the labels that all the plots share: `NULL_LABEL`, `OTHER_LABEL`, `MAX_LABELS` and `REMOVED_LABEL`.

The catch-all `(other)` and the Sankey's `(removed)` sink belong to the app, so a real value can't share their names.
`category_expression` adds one more pair of double quotes to any value spelled like either of them
(`SENTINEL_LOOKALIKE_REGEX`). A real `(other)` shows as `"(other)"`, and a real `"(other)"` shows as `""(other)""`, so no
two values end up with the same label.

### DataProfile

`DataProfile` (`app/db_utils/data_profile.py`) builds the `dp_<table>` table in one query. What it stores for a
column depends on the column's kind:
- for a numeric column: the mean, median, min and max
- for a categorical column: how many categories there are, the most common one (the mode), and how many times each
  category appears

Every column also gets its error counts. When working out the mode, missing cells are ignored, and if there's a tie,
the category whose name sorts first wins. This is the same value impute uses to fill cells.

Metrics, the attribute summary and the AI's profile all read this table, each one reading it once
(`read_stored_profile`).

---

## 8. Metrics, drift and comparing nodes

- **Metrics** (`app/pgraph/metrics.py`): the error rate for each error type, both per column and for the node as a
  whole, calculated from the data profile. The error badges in the attribute summary, and which columns it shows by
  default, come from the node's cached metrics.
- **Drift** (`app/pgraph/distortion.py`, with the SQL in `drift_sql.py`): how much each column has changed compared
  to the root.
  - Numeric columns are measured with W1/IQR: the Wasserstein-1 distance, divided by the root's interquartile range.
  - Categorical columns are measured with total variation distance.
  - Drift also records what the wrangles did, like how many rows were removed and how many cells were changed.
  - Whether a column counts as numeric or categorical is decided once, on the root, and every other node uses that
    same decision.
  - `drift_detail` supplies the data for the ridgeline and Sankey views, along with a plain-English description of
    the change (`GET /api/pgraph/drift_detail`).
  - The root's measurements are only calculated once. For each numeric column, its spread is cached, along with how
    many non-missing cells each column has. Every node compared to the root reuses those cached values.
- **Comparing along a branch** (`app/pgraph/pgraph.py`): `quality_trajectory` and `distortion_trajectory` return the
  error and drift values for each node along a branch (`GET /api/pgraph/branch_trajectory`). Both are built on
  `branch_deltas`.
- **Pareto** (`PGraph.pareto`, `pareto_frontier`): leaf nodes that have both an error total and a drift value get
  ranked. If another node is better on both counts, a node is marked as dominated.
- **Compare** (`app/db_utils/compare_sql.py`, `GET /api/pgraph/compare`): bins two nodes' tables using the same axes,
  so their histograms and heatmaps line up with each other.
  - If an axis is mostly numbers, it's binned across the combined range of both nodes.
  - Otherwise, it's shown as labels. There are at most 20 labels, and everything past that is grouped into
    `(other)`. The most common labels are the ones kept, and ties go to the label whose name sorts first. The Sankey
    view groups its categories the same way.
  - Compare never changes any data, and it only works on tables that are part of the graph.

---

## 9. Threads

`app/server_utils/workers.py` sets up two thread pools:
- `QUERY_POOL` (8 threads) runs independent queries.
- `NODE_POOL` (4 threads) builds whole nodes.

### Why threads help here: the GIL

Python (CPython) has a **Global Interpreter Lock**, or GIL. Only the thread holding the GIL can run Python code, so
even on a machine with many cores, only one thread at a time runs Python. Because of this, threads usually don't
speed up work done in Python itself, like loops or building dictionaries.

A thread can give up the GIL while it waits on something outside Python. psycopg2, the Postgres driver, does this
every time it sends a query. While one thread waits for Postgres to answer, the other threads can run.

That's why threads work well here. Almost all the work is SQL, and Postgres does it, not Python. Each database
connection has its own Postgres process, and those processes run on different cores. Eight threads waiting on eight
queries means eight Postgres processes doing the work at the same time, while the Python threads mostly sit idle.

What still runs one thread at a time is any Python work done on the results. If a task does heavy work in Python or
pandas, adding threads won't make it faster.

### `QUERY_POOL`: independent queries

A task on `QUERY_POOL` is one small piece of SQL work. An **independent** query is one that:

- **doesn't need another task's result.** Every task in a batch can start at once, in any order.
- **uses its own connection.** `fetch_sql` and `execute_sql` (in `execute_sql.py`) borrow a connection from the
  engine for each call and give it back right after. Tasks never share a connection or a transaction, so each one
  runs in its own Postgres process.
- **only reads, or writes only what belongs to it.** Two tasks running at the same time must never change the same
  table.
- **doesn't submit more work or wait on anything.** It runs its query, returns the answer, and that's it.

Right now the query pool is only used for drift (`app/pgraph/distortion.py`):

- `measure_columns` measures each column's drift with its own query, and counts the present cells in the root and
  the node with one query each. One query per column is what lets the columns be measured side by side, instead of
  one big query that Postgres would run on a single core.
- `measure_edit_facts` matches the rows of two states with one query, and counts changed cells in each column with
  one query per column.

To use the pool, call `run_all(tasks)` (or `run_queries(work, items)`). It submits every task, waits for all of them,
and returns the results in the same order as the tasks. If any task fails, the others still finish, and then the
first error is raised.

### `NODE_POOL`: whole node builds

A task on `NODE_POOL` builds one whole candidate node. `_build` in `app/server_utils/candidates.py`:

1. copies the parent's table (`clone_table`),
2. applies the wrangle to the copy (delete or impute),
3. runs `build_node`: error detection, the data profile, the metrics, and then drift. Each of these steps needs the
   one before it, so they run in order. Drift then hands its column queries to `QUERY_POOL`.

When the user asks for repairs, there might be three candidates (delete, impute x, impute y). Each one is built on
its own node thread at the same time, so the wait is about as long as the slowest build, not all three added
together.

The builds don't hold `WRANGLE_LOCK`. A candidate's table belongs only to that build until it's added to the graph,
so nothing else can touch it. See the claim, build and register steps in section 5.

### The deadlock rule

**A query task must never submit more work to a pool or wait on one. And code running inside `NODE_POOL` must never
wait on `NODE_POOL`.**

A pool has a fixed number of threads. Suppose all 8 query threads each submitted another task and waited for it.
Those new tasks would sit in the queue with no free thread to run them, and the 8 waiting threads would never
finish. The server would hang. The same thing could happen to `NODE_POOL` if a node build waited on another node
build.

Waiting in one direction is safe: a node build (or a request's thread) can wait on `QUERY_POOL`. Query tasks never
wait on anything, so each one always finishes and frees its thread, and whatever is waiting on it always gets its
answer.

```
request thread ──waits on──▶ NODE_POOL ──waits on──▶ QUERY_POOL ──waits on──▶ nothing
```

### Connections

The SQLAlchemy engine's connection pool (`pool_size=16, max_overflow=8`, in `app/__init__.py`) allows up to 24
connections. That's enough for all 8 query threads and all 4 node threads to be busy at once, with room left for the
requests the dev server is handling. A node thread only holds a connection while its own query runs. While it waits
on `QUERY_POOL`, it isn't holding one.

---

## 10. Endpoints

`app/__init__.py` imports every route module in `app/routes/` automatically. To add new routes, just create a file
there. You don't need to add an import anywhere.

| Module | Endpoints |
|--------|-----------|
| `routes.py` | `POST /api/upload`, `GET /api/preloaded`, `GET /api/tablename`, `POST /api/undo`, `POST /api/redo`, `POST /api/reset` |
| `plot_routes.py` | `GET /api/plots/1-d-histogram`, `2-d-histogram`, `scatterplot`, `top-error-rows`, `summaries`; `POST rows-in-bin`, `bins-for-rows`, `update-backend-attributes`; `GET preview-histogram`, `preview-scatterplot` (these two work on any node's table) |
| `wrangler_routes_sql.py` | `POST /api/wrangle/create-previews` (creates repair candidates) |
| `candidate_routes.py` | `POST /api/candidates/accept`, `POST /api/candidates/discard` |
| `ai_routes.py` | `GET /api/ai/status`, `POST /api/ai/suggest` |
| `pgraph_routes.py` | `GET /api/routes/update_pgraph`, `POST /api/setGraphToClickedNode`, `GET /api/pgraph/branch_trajectory`, `GET /api/pgraph/compare`, `GET /api/pgraph/drift_detail`, `POST`/`PATCH`/`DELETE /api/pgraph/support_nodes` |

Endpoints that work on the current table get its name from `db_operations.main_table_name`. They don't accept a
table name from the client. Endpoints that do accept a table name will only work with tables that belong to a node
in the session's graph.

---

## 11. Frontend

The frontend is built with React and Vite, and lives in `ui/src`. The graph is drawn with React Flow
(`@xyflow/react`) and dagre decides where each node goes. The plots are drawn with d3.

- **`pages/`**: `Home`, where you upload a file, and `Buckaroo`, the main workspace with its different view modes.
- **`store/`**: the shared state, kept in React contexts.
  - `TableNameContext` holds the current table. The rest of the frontend should treat it as the source of truth.
  - `PGraphContext` holds the graph's nodes, edges and layout, and the nodes picked as A and B.
  - `PlotsWindowsContext` holds the windows open in the Plots view (it works together with `plotsWindows.js`).
  - The other contexts are described in [The other contexts](#the-other-contexts) below.
  - `visualizationCaches.jsx` is here too. Its caches are cleared every time the backend switches tables.
- **`visualizations/`**: the plots (`HistogramBarChart`, `HeatMap`, `ScatterPlot`), the graph (`PGraph`), the views
  for comparing nodes (`ComparisonPlot`, ridgeline and Sankey), and the analysis plot.
- **`graph_objects/`**: custom node types for React Flow, including the ones used for candidates (prospective nodes).
- **`supportNodes/`**: small extra nodes that attach to a graph node: the error plot gallery, the drift plot
  gallery, compare and the sparkline. Each one is registered in `registry.js`. If one is hidden, a badge appears on
  its node instead. The records are stored on the server, and a new candidate inherits its parent's (see
  [Support nodes](#support-nodes)).
- **`panels/` and `elements/`**: the Plots view and its windows (attribute plots, compare and support nodes, all
  built on `PlotsWindow`), the attribute summary panel, the table panel, and UI pieces shared across the app.
- **`utils/serverCalls.jsx`**: every request to the backend goes through this file.

### The other contexts

Each context lives in `ui/src/store/` and has a `use...` hook for reading it, like `useCandidates()`.

**Where the providers sit.** `TableNameProvider` and `LoadingProvider` wrap the whole workspace in `App.jsx`. The
rest are nested in `pages/Buckaroo.jsx` in this order, outside to inside:

```
SettingsProvider
  PlotsWindowsProvider
    PGraphProvider
      AISuggestionsProvider
        RowRangeProvider
          SelectionProvider
            CandidatesProvider
              RepairProvider
                CompareProvider
```

The order matters, because a context can only use the contexts outside it. For example, `RepairContext` reads the
selection and the graph, so it has to be inside `SelectionProvider` and `PGraphProvider`. `CompareProvider` is
outside the part of the page that gets rebuilt after a wrangle, so an open comparison stays open.

**Moving to another table: `useMoveToTable`.** This isn't a context, but several contexts share it. It's how the
app lands on a new table after any change: it sets the current table, clears the selection (because the selection
was made on the old table's rows), and tells the page to fetch its views again. Undo, redo, and accepting or
declining a candidate all go through it, so they all behave the same way.

#### `CandidatesContext`: accepting and declining candidates

This is where the user accepts or declines a candidate. It doesn't matter whether the candidate came from a repair
or from the AI. Both kinds are handled the same way here, just like on the server.

- `candidates`: the candidates currently in the graph. They come from `PGraphContext`.
- `acceptCandidate(table)`: calls `POST /api/candidates/accept`, opens the inherited support nodes on the page
  (`settleInherited`), refreshes the graph, then moves to the accepted node with `useMoveToTable`. To the rest of the
  app, an accepted candidate looks exactly like a wrangle that just ran.
- `declineCandidate(table)` and `declineAll(parent)`: call `POST /api/candidates/discard`, remove any support nodes
  attached to those candidates, and refresh the graph. If the user was on a declined candidate, the server moves
  them to its parent, and this follows along.
- `busy` and `busyId`: whether a request is running, and which candidate it's for. While `busy` is on, every
  candidate's Accept and Decline buttons are disabled, and the one matching `busyId` shows "Working…". `busyId` is
  `null` when several candidates are declined at once.
- `error` and `dismissError`: the last failure's message.

#### `AISuggestionsContext`: asking the AI for repairs

This sends the request for AI suggestions. It doesn't accept or decline them; `CandidatesContext` does that.

- `configured`: whether the server has an AI key set up. It's checked once, when the page loads
  (`GET /api/ai/status`). When it's `false`, the AI buttons are disabled, and their tooltip says to add an API
  key. `store/aiAvailability.js` decides when an AI button is disabled and what its tooltip says: AI not set up, the
  node is a candidate, the graph is in analysis mode, or a request is already running.
- `requestSuggestions(nodeTable)`: calls `POST /api/ai/suggest` for a node. The server stages each suggestion as a
  candidate, so all this has to do afterwards is refresh the graph. The suggestions then show up as candidate nodes.
- `busy` and `pendingNode`: whether a request is running, and which node it's for.
- `error`, `notice` and `dismissMessages`: `notice` holds the model's reply when it finds nothing to repair.

Only the newest request counts. If the user asks again before the first request comes back, the first one is
cancelled (with an `AbortController`), so an old answer can never show up on the wrong node.

#### `RepairContext`: repairing a selection, and undo and redo

- `triggerRepairSelection()`: used by the header's Repair button and the error-plot support node's "Repair
  selection". It opens the graph view and calls `POST /api/wrangle/create-previews` with the current selection.
  The server stages one candidate for each way to repair it (delete, impute, and so on) under the current node.
  Then it refreshes the graph so they show up.
- `handleUndo()` and `handleRedo()`: call the server's undo or redo, refresh the graph, then move to the node the
  server landed on.
- `hasSelection`: whether any rows are selected. Repair can't be used without a selection.
- `repairLocked`: `true` when the current node is still a candidate. Nothing can be wrangled from a candidate until
  it's accepted, so Repair is turned off, and `CANDIDATE_LOCKED` holds the message that explains why.
- `busy`, `repairError` and `dismissRepairError`.

#### `SelectionContext`: the rows selected across the plots

When the user brushes rows in one plot, they light up in every plot. This context holds that selection.

- `highlightedRowIds`: the IDs of the selected rows, or `null` when nothing is selected.
- `highlightedCols`: the columns the selection was made on: one column for a histogram, two for a heatmap or a
  scatterplot. Repair uses these to decide which columns to impute.
- `selectionSource`: which kind of plot the selection was made on (`"histogram"`, `"heatmap"` or
  `"scatterplot"`).
- `highlightRevision`: goes up by one every time the selection changes. A plot that's still looking up rows for an
  older selection can compare numbers and throw away its out-of-date result.
- `setHighlightedRowIds(ids, cols, source)` and `clearHighlight()`.

The selection is cleared every time the app moves to another table, because row IDs from one table don't describe
the same rows in another.

#### `CompareContext`: the open comparison

Only one comparison can be open at a time. It's shown in one of the Plots view's windows, either docked as a tab or
popped out into its own browser window.

- `openCompare(pair)`: compares the two nodes picked as A and B in the graph. If that same pair is already open, it
  just brings it to the front.
- `openCompareNode(record)`: opens a saved compare support node. Every support node from the same Save is linked
  to the comparison, so changing the settings in the panel updates all of them.
- `openDriftNode(record)`: opens a drift-plot support node as a one-node comparison (that node against the root,
  on drift). If the user picks another column there, the support node remembers it.
- `spec`: the settings of the open comparison, or `null` if none is open.
- `closeCompare()`.

Saving a comparison from the panel adds a compare support node to both of its nodes. The two are grouped, so
opening either one later changes both.

The panel can be popped out into a separate browser window. `HostWindowContext` (also in `store/`) tells code inside
the panel which window it's in. Event listeners, timers and `ResizeObserver`s have to be taken from that window, or
they stop working once the panel is popped out.

#### `LoadingContext`: the loading dot

This drives the status dot in the header: it shows "loading" while any request is running and "ready" otherwise.

- `addLoader()` before a request, and `removeLoader()` after it.
- `isLoading`: `true` while at least one request is still running.

It keeps a count, not just `true` or `false`. So if two requests overlap, the dot stays on until both are done.
Every `addLoader` needs a matching `removeLoader`, even when the request fails, or the dot never goes back to
"ready".

#### `SettingsContext`: display settings

At the moment it only holds `axisTextSize`, the font size for plot axes (8px by default). It's changed in the
Settings window (`elements/SettingsModal.jsx`). `setAxisTextSize` also sets the `--axis-text-size` CSS variable, so
the plots pick up the new size without having to be redrawn.

#### `RowRangeContext`: limiting plots to a range of row IDs

- `useRange`: whether the user turned on a row range in Settings.
- `minId` and `maxId`: the range (0 to 10,000 by default).
- `setRowRange(useRange, minId, maxId)`: set from `elements/SettingsModal.jsx`.

The plots read it through `useCachedPlotData` in `visualizations/errorPlots.js`. When `useRange` is on, a plot
skips the cache and fetches again with the range. When it's off, the plot uses its cached data.

**Known gap:** the plot endpoints don't read `min_id` or `max_id` yet. The frontend sends them, but the server
always plots the whole table. So right now, turning the range on only turns off caching.

---

## 12. Codebase layout

This is every folder in the repository and what each file is for. The backend is `app/`, the frontend is `ui/`,
and the tests are in `tests/`. Everything else is either run once by hand, or used only by the tests.

### Repository root

```
.
├── start.py                     # runs the Flask app on 127.0.0.1:5001, without the auto-reloader
├── run.sh                       # makes a venv, installs a fixed list of packages (it doesn't read requirements.txt), runs `flask run`
├── .flaskenv                    # FLASK_APP=app, debug on, port 5001 - read by `flask run`
├── .env.example                 # the database settings and GEMINI_API_KEY to copy into .env
├── requirements.txt             # Python dependencies
├── pytest.ini                   # test paths and the `sql` / `slow` markers
├── shared/
│   └── error_types.json         # the error types, their labels and colours - read by the backend and the frontend
├── README.md
├── DEVNOTES.md                  # this file
└── LICENSE
```

### `app/`: the Flask backend

```
app/
├── __init__.py                  # creates the Flask app, serves ui/dist, checks the database exists, sets up the engine,
│                                #   db_operations and pgraph_for_session, then imports every file in routes/
├── error_types.py               # reads shared/error_types.json: the error types, in order
├── db_utils/                    # all of the SQL lives here
│   ├── bootstrap.py             # creates the database on startup if it doesn't exist yet
│   ├── db_functions_sql.py      # DBOperations: the plots, plus creating, copying and deleting tables
│   ├── column_types.py          # ColumnTypes: the rules for reading a value as a number, a category or missing
│   ├── data_profile.py          # DataProfile: builds and reads the dp_ table
│   ├── detector_sql.py          # DetectorSQL: finds errors and writes the errors_ table
│   ├── compare_sql.py           # CompareSQL: bins two nodes on the same axes for the compare views
│   ├── drift_sql.py             # DriftSQL: the numbers drift is calculated from
│   ├── query.py                 # wrangles by row ID (delete, impute), finding flagged rows, working out impute values
│   └── execute_sql.py           # fetch_sql / execute_sql, companion table names, quoting, COPY insert
├── pgraph/                      # the provenance graph, kept in memory
│   ├── pgraph.py                # PGraph: nodes, labels, candidates, undo/redo, branch trajectories, Pareto
│   ├── node.py                  # GraphNode: one node's details, and how its wrangle is named
│   ├── support_nodes.py         # support node records: what a new child inherits, and what accepting does with them
│   ├── metrics.py               # NodeMetrics: error rates per column and for the whole node
│   └── distortion.py            # drift from root: the calculations, run on QUERY_POOL, and their descriptions
├── llm/                         # the model's side of AI suggestions. No SQL, and it never changes data
│   ├── profile.py               # turns a node's dp_ table into the text the model reads
│   ├── prompts.py               # the system instruction and its worked examples
│   ├── tools.py                 # the wrangle operations declared as tools - the limit on what the model can ask for
│   └── gemini_client.py         # a small Gemini client using only the standard library
├── routes/                      # one file per group of endpoints, imported automatically (see section 10)
│   ├── routes.py                # upload, sample datasets, undo, redo, reset, and serving the page
│   ├── plot_routes.py           # the attribute plots, the repair previews, rows in a bin, attribute summaries
│   ├── pgraph_routes.py         # the graph, moving to a node, branch trajectories, compare, drift detail, support nodes
│   ├── wrangler_routes_sql.py   # create-previews: stages every repair of a selection as a candidate
│   ├── candidate_routes.py      # accepting and declining candidates
│   └── ai_routes.py             # AI status, and staging AI suggestions as candidates
├── server_utils/                # the logic the routes share
│   ├── service_helpers.py       # build_node, table naming, getting the session's graph, WRANGLE_LOCK
│   ├── wrangle_ops.py           # every wrangle operation, declared once: how it runs, is offered, described and suggested
│   ├── candidates.py            # claiming, building, registering, accepting and declining candidates
│   ├── ai_wrangle.py            # the database's side of AI suggestions: checks each one and finds its rows
│   ├── workers.py               # QUERY_POOL, NODE_POOL, run_all
│   ├── set_id_column.py         # adds the "ID" column when a file is uploaded
│   └── data_attribute_summary_integration.py   # builds the data for the attribute summary panel
├── ai_utils/
│   └── ai_data_attributes.json  # saved column statistics for one dataset. Nothing reads it
└── templates/
    └── index.html               # empty. The page is served from ui/dist instead
```

### `ui/`: the React frontend

Section 11 explains how the frontend fits together. This is the full list of files.

```
ui/
├── package.json, package-lock.json
├── vite.config.js               # the Vite dev server, which forwards /api to Flask on port 5001. `npm run build` writes dist/
├── playwright.config.js         # the end-to-end tests' setup - see section 13
├── e2e/                         # the end-to-end tests: specs, fixtures, helpers, and the mock datasets in data/
├── eslint.config.js
├── index.html                   # the page Vite builds from
├── public/images/               # copied into the build as they are
│   ├── favicon/                 # favicons, the web manifest, and the home page background
│   └── icons/                   # button and nav icons: graph, plots, compare, repair, AI, support, eye, ...
├── dist/                        # the built frontend that Flask serves. It's committed, so rebuild it after frontend changes
├── .vite/                       # Vite's dependency cache. Generated, but committed
└── src/
    ├── main.jsx                 # mounts <App />
    ├── App.jsx                  # shows Home until a file is uploaded, then the workspace. Remembers the upload for the tab
    ├── pages/
    │   ├── Home.jsx             # the upload box and the sample datasets (read from provided_datasets/)
    │   └── Buckaroo.jsx         # the workspace: the providers, the open views and the split between them
    ├── store/                   # shared state (section 11 covers each context)
    │   ├── TableNameContext.jsx, PGraphContext.jsx, PlotsWindowsContext.jsx
    │   ├── CandidatesContext.jsx, AISuggestionsContext.jsx, RepairContext.jsx, SelectionContext.jsx
    │   ├── CompareContext.jsx, LoadingContext.jsx, SettingsContext.jsx, RowRangeContext.jsx
    │   ├── HostWindowContext.jsx  # which browser window a piece of the page is in (for the popped-out compare panel)
    │   ├── useMoveToTable.js    # how the app lands on a new table: set it, clear the selection, fetch the views again
    │   ├── plotsWindows.js      # the Plots view's windows: docking, popping out, showing one
    │   ├── supportNodes.js      # useSupportNodes: the support nodes' state, sending changes to the server and reading its records back in
    │   ├── aiAvailability.js    # when an AI button is disabled, and what its tooltip says
    │   ├── errorColors.js       # the error types and their colors
    │   └── visualizationCaches.jsx  # the plot caches, cleared whenever the table changes
    ├── elements/                # pieces of the page
    │   ├── Header.jsx           # the top bar: table name, loading dot, Compare, view toggles, Repair, AI, undo/redo
    │   ├── PlotsWindow.jsx      # the frame every Plots view window shares: title, actions, pop out, dock, close
    │   ├── ComparePanel.jsx     # the compare window: options on the left, the plot on the right
    │   ├── SupportNodesWindow.jsx  # the window for adding support nodes to a node, and managing its existing ones
    │   ├── SettingsModal.jsx    # the Settings window: axis text size (the row range controls are hidden)
    │   ├── FilterModal.jsx      # a modal with one attribute's histogram, opened from the attribute summary panel
    │   ├── SpinnerModal.jsx     # the full-page spinner shown while a file uploads
    │   ├── Modal.jsx            # the plain modal the others are built on
    │   ├── UploadBox.jsx        # the file picker on the home page
    │   ├── CollapsiblePanel.jsx # a side panel that folds away
    │   ├── SplitDivider.jsx     # the drag handle between the graph and the Plots view
    │   └── Buttons.jsx          # RotatedButton, StandardButton, NavButton, IconButton
    ├── panels/                  # the larger areas of the workspace
    │   ├── PlotsPane.jsx        # the Plots view: its windows as tabs, with the attribute plots always first
    │   ├── SelectionPanel.jsx   # the attribute plot matrix (MatrixView), with a magnifier to zoom into one plot
    │   ├── AttributeSummaryPanel.jsx  # the column list: error rates and summary statistics, and picking which to plot
    │   ├── TablePanel.jsx       # the data table, with each cell colored by its error
    │   └── PreviewCard.jsx      # the small plot on a candidate node
    ├── graph_objects/           # the custom React Flow nodes and edges
    │   ├── NodeTypes.jsx        # the graph's node: label, metrics, buttons, and its role in a comparison
    │   ├── ProspectiveNode.jsx  # a candidate node: its preview, why it was suggested, Accept and Decline
    │   ├── NodeMetrics.jsx      # a node's error rates and size, as the magnifier and the metrics support node show them
    │   ├── AnalysisEdge.jsx     # analysis mode's straight edges, cut off at each node's box
    │   └── supportNodes/        # support nodes: the small extras attached to a graph node
    │       ├── registry.js      # every kind of support node. Adding a kind means a new file and an entry here
    │       ├── SupportNode.jsx  # the one React Flow node type behind every kind: name, minimise, remove, link to host
    │       ├── SupportGroup.jsx # the outline drawn around a node and its support nodes
    │       ├── SupportBadges.jsx  # badges on a node for its hidden support nodes
    │       ├── supportLayout.js # where support nodes sit: beside their host, or beside the edge into it
    │       ├── supportActions.js  # the button in a support node's header, for kinds that have one
    │       ├── supportGlyphs.jsx  # a tiny picture of each kind, for its badge
    │       ├── SupportPlotCard.jsx  # the card frame the error plots and drift plots share
    │       ├── SupportPlotGallery.jsx  # the grid of ready-made plots to pick from in the support-nodes window
    │       ├── ErrorPlotSupport.jsx, ErrorPlotCard.jsx  # error plot kind: a histogram or heatmap of the host's table
    │       ├── DriftSupport.jsx, DriftPlotCard.jsx, DriftMiniature.jsx  # drift plot kind: the host against root on one column
    │       ├── CompareSupport.jsx, compareView.js  # compare kind: a saved comparison, kept on both of its nodes
    │       ├── SparklineSupport.jsx  # sparkline kind: one error type, or drift, along the branch ending at the host
    │       ├── QualityMetricsSupport.jsx  # quality metrics kind: the host's metrics
    │       └── WrangleDiffSupport.jsx, wrangleDiffRules.js  # wrangle diff kind: what the edge into the host changed
    ├── visualizations/          # the plots, drawn with d3
    │   ├── PGraph.jsx           # the provenance graph: tree and analysis modes, panning, folding, the camera
    │   ├── analysisLayout.js    # analysis mode: nodes placed on drift (x) against error rate (y)
    │   ├── AnalysisAxes.jsx     # analysis mode's axes, drawn over the graph
    │   ├── AnalysisInset.jsx    # a zoomed-in box for nodes that sit on top of each other in analysis mode
    │   ├── HistogramBarChart.jsx, HeatMap.jsx, ScatterPlot.jsx  # the attribute plots, with brushing
    │   ├── FocusedPlot.jsx      # one attribute plot drawn large, with its axis labels
    │   ├── errorPlots.js        # what the error plots share: colors, stacking, and fetching with the cache
    │   ├── previewPlots.js      # the small error plots on candidates and error plot support nodes
    │   ├── ComparisonPlot.jsx   # the compare window's plot. Picks the view from the comparison's settings
    │   ├── useComparisonData.js # fetches a comparison's data, for the compare window and the compare support node
    │   ├── binnedPlot.js        # scales, bins and colors shared by the compare histograms/heatmaps and the wrangle diff
    │   ├── compare/
    │   │   ├── binnedViews.js   # histograms and heatmaps: side by side, overlaid, or the difference
    │   │   ├── ridgeline.js     # drift on a numeric column: each node's shape against root's
    │   │   ├── flows.js         # drift on a categorical column: a Sankey of where root's rows went
    │   │   ├── driftCommon.js   # what the ridgeline and the flows share
    │   │   ├── frames.js        # panel layout, titles, axes and "nothing to plot" messages
    │   │   └── tooltip.js       # the compare plot's own tooltip (it can be in a separate window)
    │   ├── flowLayout.js        # the Sankey's geometry, worked out once and drawn twice
    │   ├── SankeyMinimap.jsx    # the strip beside the Sankey for scrolling and zooming it
    │   ├── RidgelineBrush.jsx   # root's row under the ridgelines, with a brush for zooming
    │   ├── WrangleDiffChart.jsx # the wrangle diff plot: the parent against the node
    │   ├── QualitySparkline.jsx # one error type (or drift) along a branch, with its start and end values
    │   └── Sparkline.jsx        # the line itself, with improvements in green and regressions in red
    ├── utils/
    │   ├── serverCalls.jsx      # every request to the backend
    │   ├── comparisonSpec.js    # the comparison object: everything the compare window shows, as one record
    │   ├── comparison.js        # node names and table prefixes for the compare window
    │   ├── candidates.js        # what each candidate source is called, and what its row count counts
    │   ├── graphTopology.js     # walking and folding the graph on the client
    │   ├── drift.js             # how drift values are written out
    │   ├── visCommon.jsx        # tooltip placement, shared by the plots
    │   ├── html.js              # escaping user data for tooltips, and safe ids
    │   ├── randomKey.js         # short unique keys
    │   └── textUtils.js         # truncateText
    └── styles/                  # one CSS file per component, plus main.css for the whole app
```

### `tests/`

Section 13 covers how to run them.

```
tests/
├── sql/                         # run against the real database. They need Postgres running
│   ├── conftest.py              # shared fixtures: make_root builds a root with its errors, profile and graph
│   ├── test_upload.py, test_plots.py, test_errors_row_id.py
│   ├── test_detector_sql.py, test_data_profile.py, test_drift_sql.py, test_compare_sql.py
│   ├── test_wrangling.py, test_candidates.py, test_node_compare_route.py
│   ├── test_ai_routes.py, test_ai_resolve.py, test_ai_accept.py
│   └── test_distortion_survey.py
└── unit/                        # no database needed
    ├── test_distortion.py, test_node_metrics.py, test_safe_pg_name.py, test_ai_tools.py
    ├── test_support_nodes.py    # what a child inherits, and what accepting does with it
    ├── test_wrangle_ops.py      # the wrangle operations' registry, and that a detector-less error type fails at start
    └── test_approx_cardinality.py, test_benchmark_validation.py, test_reproducibility.py   # for the folders below
└── stress/                      # the data operations over generated datasets, held to an answer key. Needs Postgres
    ├── generators.py            # seeded adversarial datasets: a "personality" per column, aimed at one rule each
    ├── reference.py             # the answer key: every rule restated in plain Python, none of the app's SQL
    ├── conftest.py              # make_root (through the upload path, or values stored as they are), the seeds
    ├── family.py                # root, an accepted child, its sibling candidate and a grandchild, built as a user would
    ├── make_e2e_expected.py     # writes the end-to-end tests' mock CSVs and their expected values, from reference.py
    ├── test_detector_stress.py, test_wrangle_stress.py, test_plots_stress.py, test_upload_stress.py
    ├── test_compare_stress.py, test_drift_stress.py
    ├── test_route_fuzz.py       # every data route given input it should refuse
    └── test_found_bugs.py       # each bug the stress tests found, reproduced on its own, now a regression test
```

### Other folders

```
detectors/
└── approx_cardinality.py        # a HyperLogLog-style distinct-value counter. Only the tests use it, not the app
experiments/
├── benchmark_validation.py      # benchmark checks for profiling experiments
└── reproducibility.py           # records the setup an experiment ran with
provided_datasets/               # the sample CSVs offered on the home page, plus copies of older versions
└── create_mari_dataset.py       # writes mari_dataset.csv, a six-row dataset with a few bad values
```

`detectors/` and `experiments/` aren't imported by the app. Only the unit tests use them.

---

## 13. Tests

- `tests/unit` tests pure logic and doesn't need a database.
- `tests/sql` runs against your local Postgres, and its tests are marked `@pytest.mark.sql`. It covers uploading,
  the main view's plots, error detection, compare, drift, the data profile, candidates (including the support
  nodes they inherit and what accepting does with them) and the AI routes. There's
  also a golden survey test that checks drift and Pareto results against known values.

To run both, use `.venv/bin/pytest tests/unit tests/sql`.

### Stress tests

`tests/stress` runs the data operations over datasets it generates, and checks every result against an answer key
instead of against hand-picked numbers. It covers:

- error detection and the node metrics
- uploads
- delete and impute, on one column and on two, through the same route the Repair button uses
- chains of accepted wrangles, and candidates built at the same time
- the main view's histograms, scatterplot and bar-click selections
- comparisons between every kind of node pair
- drift, its detail payloads, and drift measured from an ancestor
- every data route given bad input

**The answer key.** `reference.py` restates each rule in plain Python and computes the same results the app's SQL
does. It never imports the app's query builders, so a mistake in a query can't be copied into its own answer. Its rules
come from the app's docstrings and from the original pandas code (the git history before `56d65dd`), which is the gold
standard when the two disagree. Some values sit exactly on a threshold, such as a number on a bin edge or a cell at
exactly two standard deviations. The database can round those either way, so the answer key marks them
"borderline" and the tests accept either side.

**The datasets.** `generators.py` builds each dataset from a seed. Each column gets a personality that targets one
rule: fewer than ten numbers, a constant column, numbers stored as text, the missing tokens and text that only looks
missing, more labels than an axis keeps, ties, unicode, and quotes in names and values. A dataset reaches the database
in one of two ways. It goes through the real upload path as a CSV, or its values are stored exactly as they are, which
keeps values a CSV can't carry (an empty string, the text `"null"`).

**Running them.**

- `.venv/bin/pytest tests/stress` runs every test over 20 seeds, in about two minutes.
- `STRESS_SEEDS=50` is a deeper run, which is plenty before a merge. `STRESS_SEED_START` moves the window to seeds
  you haven't run yet.
- Every failure names its seed. `STRESS_SEEDS=1 STRESS_SEED_START=<seed>` reruns just that one.

**Bugs they find.** The bugs found so far were all fixed on October 29, 2026. Their tests stay in
`test_found_bugs.py` and `test_route_fuzz.py` as regression tests.

When a new bug turns up:
1. Add a test that reproduces it, marked `pytest.mark.xfail(strict=True, reason="BUG: ...")`.
2. Keep its input out of the random datasets until it's fixed, so it can't hide other bugs.

Once the bug is fixed, the test passes and the strict marker turns that into a failure. That's the reminder to take
the marker off.

### End-to-end tests

`ui/e2e` drives the real app in Chrome with Playwright. It covers uploading, the attribute plots, repairs, the graph,
comparing (docked and popped out), support nodes, AI suggestions, settings, and long random "journeys" through the
app. Every number a test reads off the screen is checked against two things: the expected values in
`ui/e2e/data/expected/*.json` and the live API response.

**Running them.**
- `cd ui && npm run e2e` runs the suite, and `npm run e2e:report` opens the HTML report.
- Playwright starts its own stack: a backend on port 5002 and Vite on 5183 (`e2e/vite.e2e.config.js`). It never
  touches the dev servers on 5001 and 5173, so you can keep using the app while the tests run.
- The tests run one at a time (one worker), because the backend keeps a single active graph.
- They use your installed Chrome, so there's no browser to download.

**The mock data.** There are four small CSVs in `ui/e2e/data/`, each built to exercise one thing:
- `e2e_tiny`: twelve rows, every value picked by hand.
- `e2e_games_small`: shaped like games.csv, with the same rows missing in Critic_Score and Critic_Count.
- `e2e_many_labels`: more categories than an axis keeps.
- `e2e_anomalies`: known outliers.

`.venv/bin/python -m tests.stress.make_e2e_expected` writes the CSVs and their expected values, using the stress
tests' answer key. Rerun it whenever a rule in `reference.py` changes.

**Rules for changing the app.**
- The plots' marks carry `data-*` attributes that the tests read (`data-bin`, `data-count`, `data-x-bin`,
  `data-row-id`, and so on). Treat them as part of the app, and keep them when you change a plot.
- A shared guard fails any test that logs a console error or gets a 5xx response.
- `/api/ai/suggest` is always mocked, so the tests never call Gemini.
- A test that captures a known bug uses `test.fail()` with a "BUG:" annotation. Take the marker off once the bug is
  fixed.
