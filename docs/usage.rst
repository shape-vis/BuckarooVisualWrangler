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
