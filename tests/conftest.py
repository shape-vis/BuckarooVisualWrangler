"""Pytest bootstrap: unit tests must not require a live Postgres at import time."""
import os

os.environ.setdefault("BUCKAROO_SKIP_DB_INIT", "1")
