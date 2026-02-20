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
  - Upload now computes all anomaly methods (`zscore`, `mad`, `iqr`) so users can switch methods later in the visual tool without re-uploading.
  - Initial index selection is treated as initial display filter, not detection limitation.
  - File: `app/routes.py`.

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
