# Changelog

## 2026-02-20 - Branch `improve-error-detector`

### Summary
Improvements made to error detection part of the project.
This entry starts with anomaly detection improvements; upcoming work will continue improving the broader error detection logic.

### Previous Behavior (Before This Branch)
- The UI did not provide a way to select anomaly detection methods.
- Anomaly detection effectively ran with a single default method (`zscore`) during upload.
- Users could not choose `mad` or `iqr`, and could not run multiple anomaly methods together.

### Changed
- Removed anomaly method selection UI from the home page (`app/templates/index.html`):
  - Datasets/uploads now initialize anomaly methods to the default method (`zscore`).
  - Filtering is now done only in the visual tool page.

- Updated anomaly method selection behavior on the home page (`app/templates/index.html`):
  - Replaced old broken select-based logic with checkbox-based logic.
  - `All` now checks/unchecks all anomaly methods (`zscore`, `mad`, `iqr`).
  - `All` auto-checks when all individual methods are checked.
  - Default load state now syncs `All` and individual checkboxes.

- Updated anomaly method control layout:
  - Moved anomaly method options to render to the right of the label text.
  - Added layout classes and CSS rules:
    - `app/templates/index.html`
    - `app/static/styles.css`

- Updated upload payload to include multi-method selection:
  - Upload now sends `anomaly_methods` (JSON list) and legacy `anomaly_method` fallback.
  - File: `app/templates/index.html`.

- Added anomaly method controls inside the visual tool page:
  - Added method toggles in `data_cleaning_vis_tool` header.
  - Added `All` toggle in the visual tool UI, synced with method checkboxes.
  - Files:
    - `app/templates/data_cleaning_vis_tool.html`
    - `app/static/js/dataSelection.js`
    - `app/static/styles.css`

- Enforced at least one anomaly method selected at all times:
  - Guard added on index page controls.
  - Guard added on visual tool controls.
  - Safety fallback added in request helper to prevent empty method payloads.
  - Files:
    - `app/templates/index.html`
    - `app/static/js/dataSelection.js`
    - `app/static/js/serverCalls.js`

### Backend
- Extended upload route to support multi-method anomaly detection:
  - Parses and validates `anomaly_methods` from form data.
  - Falls back safely to `["zscore"]` when missing/invalid.
  - Passes selected methods into detector pipeline.
  - File: `app/routes.py`.

- Extended detector pipeline to run multiple anomaly methods and merge results:
  - Added method normalization helper.
  - Runs SQL anomaly detector once per selected method.
  - Unions anomaly results and deduplicates by `(row_id, column_name)`.
  - Keeps other detectors (missing, incomplete, datatype mismatch) unchanged.
  - File: `app/service_helpers.py`.

- Updated upload-time anomaly detection behavior:
  - Upload now persists only the default detector state (`zscore` anomaly + default rarity threshold).
  - Additional anomaly methods (`mad`, `iqr`) and alternate rarity thresholds are computed on demand when the user changes filters in the visual tool.
  - Files:
    - `app/routes.py`
    - `app/service_helpers.py`
    - `app/plot_routes.py`

- Added method-aware filtering in data/plot endpoints:
  - `/api/get-errors` filters anomaly rows by selected methods.
  - Histogram and scatterplot endpoints now apply selected method filters to error tables before generating plot data.
  - `/api/plots/summaries` now applies selected method filters for Attribute Summaries.
  - Files:
    - `app/routes.py`
    - `app/plot_routes.py`
    - `data_management/data_attribute_summary_integration.py`
    - `app/service_helpers.py`

- Added visual refresh wiring for method toggles:
  - When toggles change, the app now refreshes:
    - graph error overlays/data
    - top dirty rows table
    - attribute summaries
  - Files:
    - `app/static/js/dataSelection.js`
    - `app/static/js/serverCalls.js`

- Fixed post-repair error recomputation to use the current detector pipeline:
  - SQL wrangler repair endpoints now rebuild the persisted default error state (`zscore` + default rarity threshold) through the SQL detector path.
  - When users choose non-default anomaly methods or rarity thresholds later, the backend computes those selected views on demand for plots, summaries, and error retrieval.
  - Recomputed errors are normalized to include `raw_error_type` and UI-friendly `error_type = "anomaly"` rows.
  - File: `app/wrangler_routes_sql.py`

- Migrated incomplete detector behavior to SQL rarity detection:
  - Added PostgreSQL function `detect_rarity(table_name, threshold_pct)` to flag low-frequency categorical values.
  - SQL rarity now trims whitespace and ignores blank-string values during rarity counting.
  - Runtime detector pipeline now uses SQL rarity instead of Python `detectors/incomplete.py` in active routes.
  - Added `rarity_score` to error rows so UI/API filtering can apply dynamic thresholds.
  - Default processing computes broad rarity coverage, then UI applies selected threshold filter.
  - Files:
    - `app/db_functions.py`
    - `app/service_helpers.py`
    - `app/routes.py`
    - `app/plot_routes.py`
    - `data_management/data_attribute_summary_integration.py`

- Added visual rarity threshold control:
  - New `Rarity threshold` selector in visual tool header.
  - Threshold is passed on API requests for:
    - error map (`/api/get-errors`)
    - 1D/2D histograms
    - scatterplot
    - attribute summaries
  - UI labels now describe this detector as `Rarity (Low-Frequency Values)` while keeping internal key `incomplete` for compatibility.
  - Files:
    - `app/templates/data_cleaning_vis_tool.html`
    - `app/static/js/dataSelection.js`
    - `app/static/js/serverCalls.js`
    - `app/static/visualizations/attributesummaryview.js`
    - `app/static/visualizations/matrixview.js`
    - `app/static/visualizations/repairpanel.js`

- Fixed rarity visibility bug in error reshaping:
  - `perform_melt` now consistently emits `column_id` for all detector outputs.
  - This restored per-attribute rendering of rarity errors in summaries/plots/table.
  - File: `app/service_helpers.py`

- Migrated missing-value detection to SQL:
  - Added PostgreSQL function `detect_missing_values(table_name)` to replace the active Python missing-value path.
  - Missing values are now normalized more robustly and include:
    - `NULL`
    - empty strings
    - whitespace-only strings
    - case-insensitive `null`
    - case-insensitive `undefined`
  - Runtime detector pipeline now uses the SQL missing detector in active routes and recomputation.
  - Shared wrangling-side missing predicate was updated to match the same normalization logic so detection and repair stay aligned.
  - Files:
    - `app/db_functions.py`
    - `app/service_helpers.py`
    - `postgres_wrangling/query.py`
    - `detectors/missing_value.py`

- Migrated datatype mismatch detection to SQL and expanded semantic type handling:
  - Added PostgreSQL function `detect_datatype_mismatch(table_name)` to replace the active Python mismatch path.
  - The SQL detector now classifies non-missing values into:
    - `numeric`
    - `boolean`
    - `datetime`
    - `text`
  - Majority type is computed per column, and non-matching rows are emitted as `error_type = "mismatch"`.
  - Missing-like values are excluded before mismatch classification so they stay owned by the missing-value detector.
  - Runtime detector pipeline now uses the SQL mismatch detector in upload detection and wrangle recomputation.
  - Files:
    - `app/db_functions.py`
    - `app/service_helpers.py`
    - `detectors/datatype_mismatch.py`

- Added detector-specific demo data for safer testing:
  - Reworked `provided_datasets/anomaly_test.csv` into a simpler clustered demo dataset so plots and repair selections are easier to inspect visually.
  - The anomaly demo now emphasizes:
    - repeated clean numeric clusters
    - obvious anomaly rows
    - simple missing-value cases
    - one-off rarity categories
  - Added `provided_datasets/datatype_mismatch_test.csv` for boolean/date mismatch demos so mismatch testing does not interfere with the main anomaly demo file.

- Continued SQL-first backend migration around detector infrastructure:
  - Upload now stores CSV data directly in PostgreSQL with inferred SQL column types and SQL-side ID handling instead of relying on pandas-first table materialization.
  - Detector result assembly is now largely SQL-built rather than pivoted/melted repeatedly in pandas.
  - Errors table rebuilds are now created directly in SQL for both upload and post-repair recomputation.
  - Rankings are rebuilt directly in SQL from the persisted errors table.
  - Attribute summaries now use SQL queries for per-column stats, error percentages, and default ranking lookup.
  - `/api/get-errors` now performs backend filtering closer to SQL/data source rather than loading the full persisted errors table into pandas first.
  - Files:
    - `app/routes.py`
    - `app/service_helpers.py`
    - `app/plot_routes.py`
    - `app/wrangler_routes_sql.py`
    - `data_management/data_attribute_summary_integration.py`

- Added on-demand detector execution for non-default filter selections:
  - Persisted backend state now stores the default detector view (`zscore` + default rarity threshold) instead of precomputing all anomaly methods up front.
  - When users enable `mad`/`iqr` or change the rarity threshold in the visual tool, the backend materializes the selected detector/error state on demand and refreshes:
    - plots
    - attribute summaries
    - error table / error map
  - This keeps repair recomputation and initial upload lightweight while still supporting interactive filter-driven analysis.
  - Files:
    - `app/service_helpers.py`
    - `app/routes.py`
    - `app/plot_routes.py`
    - `app/wrangler_routes_sql.py`
    - `data_management/data_attribute_summary_integration.py`
    - `app/templates/index.html`
    - `app/static/js/dataSelection.js`
    - `app/static/js/serverCalls.js`

### Documentation
- Added automated Python API docs setup using Sphinx + AutoAPI:
  - `docs/conf.py`
  - `docs/index.rst`
  - `docs/usage.rst`
  - `docs/requirements.txt`
  - README usage section update

- Added docstrings for the recent anomaly-method backend changes:
  - `upload_csv` in `app/routes.py`
  - `_normalize_anomaly_methods` in `app/service_helpers.py`
  - `run_detectors` in `app/service_helpers.py`

### Notes for Teammates
- Keep `docs/requirements.txt` separate from root `requirements.txt`:
  - Root file remains app/runtime/test dependencies.
  - Docs file remains documentation tooling dependencies.

- Build docs locally:
  1. `pip install -r docs/requirements.txt`
  2. `sphinx-build -b html docs docs/_build/html`
  3. Open `docs/_build/html/index.html`
