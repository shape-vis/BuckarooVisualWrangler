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

Testing Datasets
----------------

- Use ``provided_datasets/anomaly_test.csv`` for anomaly, rarity, and missing-value demos.
- Use ``provided_datasets/datatype_mismatch_test.csv`` for boolean/date mismatch demos.
- The mismatch dataset is separate on purpose so mixed-type demo rows do not interfere with the main anomaly demo workflow.
