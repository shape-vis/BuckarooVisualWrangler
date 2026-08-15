"""CLI compatibility wrapper for Buckaroo's production column profiler.

The implementation lives in :mod:`profiling.column_profiling` so the
Flask application never imports research scripts. Public names are re-exported
to preserve existing experiment and test imports.
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from profiling.column_profiling import *  # noqa: F401,F403


if __name__ == "__main__":
    main()
