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
