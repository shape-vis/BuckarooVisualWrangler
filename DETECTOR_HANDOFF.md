# Detector / SQL Integration Handoff

This document is a semester-spanning handoff for the detector-related work that started on the older `improve-error-detector` branch and was later integrated into the current `refactor-detector-port` branch.sthe 

## 1. High-Level Summary

This work moved Buckaroo's detector pipeline away from the older pandas/DataFrame detector path and toward a SQL-backed/PostgreSQL-driven detector flow.

The major outcomes are:

- detector execution is now primarily SQL-backed
- upload and wrangle refresh now rebuild `errors_<table>` and `rankings_<table>` from SQL
- plots, summaries, and top-error rows can be filtered by:
  - anomaly method (`zscore`, `mad`, `iqr`)
  - rarity threshold
- the Plot Settings UI was extended to support these filters with live preview behavior
- upload ingestion was moved from `pandas.read_csv(...).to_sql(...)` to a more SQL-native staged `COPY` flow
- the old runtime Python detector modules were removed from the active app path

This branch got the detector functionality working again with the current codebase and validated the main runtime path end-to-end, but there is still maintainability cleanup left to do.

## 2. Semester Timeline

## Phase A: Original `improve-error-detector` Work

The earlier branch introduced the first major detector improvements:

- anomaly method selection moved beyond a single default `zscore`
- support was added for:
  - `zscore`
  - `mad`
  - `iqr`
- users gained the ability to choose multiple anomaly methods together
- rarity detection was shifted toward a SQL-backed threshold-based model
- missing-value detection and datatype mismatch detection were migrated toward SQL-backed behavior
- on-demand recomputation for non-default detector settings was introduced
- initial docs/changelog work was added to explain the detector migration direction

That branch also pushed upload and detection closer to a SQL-first model, including staged CSV handling and database-side loading.

## Phase B: Port / Merge into `refactor-detector-port`

Because `improve-error-detector` had gotten old relative to the rest of the repo, the work was not carried over as a simple cherry-pick. Instead, the functionality was ported feature-by-feature into the current branch.

The main goal of this phase was:

- get the detector functionality working again with the current codebase
- verify the runtime path end to end
- make it usable for the current frontend / backend state

## 3. Main Features Added or Integrated

### SQL-backed detector helpers

In `app/service_helpers.py`, helper logic was added for:

- anomaly method normalization
- rarity threshold normalization
- SQL detector query assembly
- SQL-backed detector result materialization
- rebuilding `errors_<table>`
- rebuilding `rankings_<table>`

These helpers now support the detector pipeline instead of the older DataFrame detector orchestration.

### SQL-backed runtime detector flow

The active runtime path now uses SQL detector logic rather than the old Python detector modules.

This includes:

- main error table generation
- wrangle refreshes
- filtered plot/summaries/top-row analysis

The old `run_detectors(data_frame)` style runtime path was removed and replaced with a SQL-backed `run_detectors(table_name, ...)` path.

### Plot filter settings

The app now supports detector-specific plot filtering by:

- anomaly method
- rarity threshold

This affects:

- 1D histograms
- 2D histograms
- scatterplots
- attribute summaries
- top error rows

### Plot Settings UI

The frontend now has controls for:

- anomaly methods:
  - `Z-Score`
  - `MAD`
  - `IQR`
- rarity threshold via slider + presets
- live preview / Apply / Cancel behavior

The rarity control was later widened to:

- minimum: `0.10%`
- maximum: `20%`
- presets:
  - `0.10%`
  - `1%`
  - `5%`
  - `10%`
  - `20%`

### SQL-backed upload and wrangle refresh

The current branch now does the following:

- upload creates the main Postgres table
- upload rebuilds:
  - `errors_<table>`
  - `rankings_<table>`
- wrangle refresh rebuilds:
  - `errors_<table>`
  - `rankings_<table>`

This means the detector path is much more consistent across:

- upload
- wrangle / repair
- plot filtering

### More SQL-native upload ingestion

The upload flow was moved away from:

- `pandas.read_csv(...)`
- `set_id_column(...)`
- `.to_sql(...)`

and toward:

- staged CSV analysis
- SQL type inference
- transformed staged CSV generation
- direct Postgres table creation
- bulk ingest using `COPY`

There is still Python around the upload process for CSV analysis/transformation, but the table creation and bulk load are now much more SQL-native than before.

### Removal of old runtime detector modules

The old Python detector modules were removed from the active app path. These were the older detector files in `detectors/`.

The branch also removed the old detector-specific tests that depended on that Python runtime path.

## 4. Key Files and Their Roles

### Backend detector / SQL files

- `app/service_helpers.py`
  - SQL detector helpers
  - error-table materialization
  - rankings refresh
  - SQL-backed `run_detectors(...)`

- `app/db_function_defs.py`
  - PostgreSQL detector function definitions
  - includes SQL definitions such as:
    - anomaly detection
    - rarity detection
    - missing-value detection
    - datatype mismatch detection

- `app/routes.py`
  - upload flow
  - current staged CSV + `COPY` ingestion logic
  - initial SQL-backed error/rankings rebuild

- `app/wrangler_routes_sql.py`
  - wrangle / repair endpoints
  - SQL-backed error/rankings refresh after wrangles

- `app/plot_routes.py`
  - plot endpoints
  - detector filter parsing
  - filtered request flow for plots/summaries/top rows

- `app/data_attribute_summary_integration.py`
  - attribute summary generation
  - supports alternate error-table input for filtered analysis

- `app/db_functions_sql.py`
  - `DBOperations`
  - `ColumnTypes`
  - filtered error-table lifecycle helpers added during centralization work

### Frontend files

- `ui/src/elements/SettingsModal.jsx`
  - anomaly method controls
  - rarity slider/presets
  - live preview / Apply / Cancel logic

- `ui/src/elements/SettingsModal.css`
  - layout/styling for the settings modal

- `ui/src/utils/SettingsContext.jsx`
  - settings state for anomaly methods / rarity threshold

- `ui/src/utils/serverCalls.jsx`
  - detector-filter parameters appended to plot/summaries/top-row calls

- `ui/src/panels/AttributeSummaryPanel.jsx`
- `ui/src/panels/TablePanel.jsx`
- `ui/src/visualizations/HistogramBarChart.jsx`
- `ui/src/visualizations/HeatMap.jsx`
- `ui/src/visualizations/ScatterPlot.jsx`
  - detector settings flow through these views

- `ui/src/pages/Home.jsx`
  - upload success/failure guard improved so failed uploads do not push the app into a fake `unknown_table` state

- `ui/src/pages/Buckaroo.jsx`
  - removed `"unknown_table"` fallback and now requires a real uploaded table

## 5. Current Architecture

### What is persistent

For a loaded table `<table>`:

- main data table:
  - `<table>`
- error table:
  - `errors_<table>`
- rankings table:
  - `rankings_<table>`

### What is temporary

For non-default detector filter requests, temporary filtered error tables are materialized on demand for:

- plots
- attribute summaries
- top error rows

These are created for request-scoped filtered analysis and then dropped afterward.

### What is SQL-backed now

The main runtime detector path is now SQL-backed for:

- detector execution
- upload-time errors rebuild
- wrangle-time errors rebuild
- rankings rebuild
- filtered detector views for plots/summaries/top rows

### What is not fully ideal yet

The branch is functionally integrated, but not yet in its final maintainable form.

Main maintainability concerns that remain:

- large SQL definitions in `app/db_function_defs.py`
- some logic still spread across:
  - `DBOperations`
  - `service_helpers.py`
  - routes
  - summary helpers
- `plot_routes.py` and `service_helpers.py` still contain some large functions / “God-function” style code
- more detector-related orchestration could still be moved into `DBOperations`
- SQL function setup / deployment could be made more explicit and repeatable

## 6. Important Bugs Fixed During Integration

The port/integration work uncovered and fixed several issues:

- mismatch detector falsely classifying `Yes, full-time` style values as boolean mismatches
- temporary filtered error table names / index names colliding due to PostgreSQL identifier length limits
- `NaN` values breaking top-row JSON parsing
- summaries at default `zscore + 0.05` falling back to the persisted error table instead of the filtered one
- `get_error_dist(...)` crashing due to pandas dtype assignment when dividing counts into percentages
- upload failure causing the frontend to enter Buckaroo with `unknown_table`
- mixed-column detection using regex directly on boolean columns
- staged SQL upload writing integer-typed values like `2017.0` into `BIGINT` columns without coercion
- settings slider tick marks rendering inconsistently because browser-native `datalist` ticks did not align well

## 7. Validation / Testing Performed

### Dedicated filter test dataset

Created:

- `provided_datasets/plot_settings_filter_test.csv`

This dataset was intentionally designed to make detector-setting differences obvious.

It contains:

- rarity buckets:
  - `common`
  - `preset15`
  - `preset10`
  - `preset05`
  - `preset01`
- numeric columns designed to show differences between:
  - `zscore`
  - `mad`
  - `iqr`

### Terminal/API validation

The following were validated through direct API calls / SQL checks:

- summaries at `0.01` vs `0.05`
- top error rows at different detector settings
- histogram payloads under:
  - `zscore`
  - `mad`
  - `iqr`
- rarity SQL detector behavior directly via SQL function calls
- count alignment between:
  - raw data
  - errors table
  - histogram JSON

### Concrete validated examples

Examples that were checked:

- `ConvertedSalary` and `Region` on `data_test_impute_debug`
  - raw values matched the error table
  - histogram missing/error counts matched the DB rows

- `plot_settings_filter_test`
  - `0.01` only flagged the `preset01` rarity bucket
  - `0.05` flagged both `preset01` and `preset05`
  - `mad` and `zscore` produced visibly different histogram payloads

- SQL-native upload validation
  - uploaded tables were checked for:
    - main row count
    - error row count
    - rankings population

### Wrangle / refresh validation

The SQL-backed wrangle refresh path was tested by:

- performing wrangle operations
- confirming errors/rankings tables still existed afterward
- confirming error/ranking refresh continued to work

## 8. Known Caveats / Things To Be Aware Of

### High-cardinality datasets can look visually chaotic

Datasets with columns like:

- `VIN`
- `model`
- `description`
- IDs
- near-unique text

can produce very noisy or unreadable plots.

This is not always a detector bug. Often it is a dataset/default-attribute-selection problem.

Examples:

- cars dataset
- games dataset
- some real-world StackOverflow attributes

### Plot filters may work even when the visual change is subtle

On real datasets, detector settings can change:

- summaries
- top error rows
- plot payloads

without producing dramatic visual differences in the rendered plot.

This happened with StackOverflow:

- some payloads did change
- but dominant bins/categories made the visual differences hard to notice

### Provenance graph was not fully validated

Main and branch integration happened, and conflicts were resolved, but a dedicated provenance-graph-specific validation pass was not completed.

So it is not safe to overclaim that the detector branch was exhaustively verified against provenance-graph behavior.

### Some older docs are now outdated

`DEVNOTES.md` reflects an earlier architecture snapshot where detectors were still described as pure Python modules running in pandas memory.

That is no longer an accurate description of the current active runtime path.

## 9. Recommended Next Steps

If someone continues this work, the highest-value cleanup would be:

- break up long SQL definitions in `app/db_function_defs.py`
- move more detector/filter orchestration into `DBOperations`
- reduce route/helper “God-functions”
- improve default attribute selection so high-cardinality identifier/text columns are not chosen automatically for plots
- decide on a repeatable strategy for SQL function setup/deployment
- verify provenance graph behavior specifically
- add/update documentation so architecture docs match the current SQL-backed runtime path

## 10. How To Run / Test

Backend:

```powershell
python start.py
```

Frontend:

```powershell
cd ui
npm run dev
```

Useful datasets used during validation:

- `provided_datasets/plot_settings_filter_test.csv`
- `provided_datasets/stackoverflow_db_uncleaned.csv`
- `provided_datasets/data_test_impute_debug.csv`
- `provided_datasets/cars.csv`

Example checks:

- upload a dataset and confirm the app returns a real `table_name`
- verify the corresponding:
  - main table
  - `errors_<table>`
  - `rankings_<table>`
- test Plot Settings by changing:
  - anomaly method
  - rarity threshold
- compare summaries / plots / top rows before and after filter changes

## 11. Final Status

The current branch should be described as:

- functionally integrated
- detector runtime path working
- frontend-facing detector controls working
- merge-ready from a functionality perspective
- still needing maintainability/framework cleanup

That is the most accurate summary of the semester’s detector work.
