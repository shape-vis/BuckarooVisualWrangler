Build Documentation
===================

1. Install docs dependencies:

   .. code-block:: bash

      pip install -r docs/requirements.txt

2. Build HTML docs:

   .. code-block:: bash

      sphinx-build -b html docs docs/_build/html

3. Open the output:

   - Main page: ``docs/_build/html/index.html``

Notes
-----

- The API reference is generated from source by ``sphinx-autoapi``.
- Add or update Python docstrings, then rebuild docs to refresh output.
- The backend is now SQL-first for the main detector pipeline, but Python still serves as orchestration/API glue.

Detector Execution Model
------------------------

- On initial upload, the persisted backend error state is intentionally lightweight:
  - anomaly detection is stored using the default method ``zscore``
  - rarity is stored using the default threshold ``0.01``
- When the user later changes anomaly-method filters or the rarity threshold in the visual tool, the backend computes the selected detector state on demand and refreshes:
  - error map / error table
  - histogram and scatterplot overlays
  - attribute summaries
- This design avoids precomputing every anomaly-method combination at upload time while still supporting interactive analysis.

Rarity Detector (Formerly Incomplete)
-------------------------------------

- Active app routes now use SQL rarity detection rather than the legacy Python ``detectors/incomplete.py`` implementation.
- The SQL function computes low-frequency categorical values and emits:
  - ``error_type = "incomplete"`` (kept for UI/backward compatibility)
  - ``rarity_score`` (frequency ratio used for threshold filtering)
- The visual tool includes a ``Rarity threshold`` selector (for example: 0.5%, 1%, 2%, 5%, 10%).
- Changing threshold updates:
  - error overlays/maps
  - histogram/scatterplot error views
  - attribute summaries
- The persisted default backend state uses the default rarity threshold; non-default thresholds are materialized on demand when requested by the frontend.
- If testing with an older uploaded table, re-upload or recompute errors so ``rarity_score`` exists in the ``errors*`` table.

Missing Value Detector
----------------------

- Active app routes now use SQL missing-value detection rather than the legacy Python ``detectors/missing_value.py`` implementation.
- The SQL function ``detect_missing_values`` flags a value as missing when it is:
  - ``NULL``
  - an empty string
  - a whitespace-only string
  - ``null`` (case-insensitive)
  - ``undefined`` (case-insensitive)
- The shared missing-value predicate used by wrangling/repair logic was updated to match the same normalization rules.
- This keeps upload detection, recomputation, and repair behavior aligned.

Datatype Mismatch Detector
--------------------------

- Active app routes now use SQL datatype mismatch detection rather than the legacy Python ``detectors/datatype_mismatch.py`` implementation.
- The SQL function ``detect_datatype_mismatch`` ignores missing-like values first, then classifies remaining values into:
  - ``numeric``
  - ``boolean``
  - ``datetime``
  - ``text``
- For each column, the detector computes a majority semantic type and flags rows whose value type differs from that majority as ``error_type = "mismatch"``.
- This expands the old mismatch logic, which was mostly numeric-vs-not-numeric, and makes boolean/date mismatches visible in the same pipeline as the other SQL detectors.

SQL-First Backend Changes
-------------------------

- Uploaded CSVs are now stored directly in PostgreSQL with inferred SQL column types and SQL-side ID handling.
- Detector result assembly is now mostly SQL-built before the final Python/API handoff.
- The persisted ``errors*`` table is rebuilt in SQL on upload and after repairs.
- Attribute rankings are rebuilt in SQL from the persisted errors table.
- Attribute summaries now query SQL directly for:
  - per-column error percentages
  - numeric stats
  - categorical mode/count
  - default ranked attributes

Repair / Recompute
------------------

- After a repair action, the wrangling pipeline rebuilds the persisted default error state through the SQL detector path.
- That means repair-triggered recomputation now stays aligned with the SQL-backed detector implementation.
- If the user is viewing non-default anomaly methods or a non-default rarity threshold, those selections are recalculated on demand for the current visual refresh rather than being permanently stored as the new persisted default.

Testing Datasets
----------------

- Use ``provided_datasets/anomaly_test.csv`` for anomaly, rarity, and missing-value demos.
- The anomaly demo dataset was simplified to make the visual tool easier to read and easier to use for repair selections.
- Use ``provided_datasets/datatype_mismatch_test.csv`` for boolean/date mismatch demos.
- The mismatch dataset is separate on purpose so mixed-type demo rows do not interfere with the main anomaly demo workflow.
