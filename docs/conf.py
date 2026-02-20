import os
import sys

PROJECT_ROOT = os.path.abspath("..")
sys.path.insert(0, PROJECT_ROOT)

project = "Buckaroo Visual Wrangler"
author = "Buckaroo Team"
copyright = "2026, Buckaroo Team"

extensions = [
    "autoapi.extension",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "alabaster"
html_static_path = ["_static"]

# Parse source directly instead of importing modules.
autoapi_type = "python"
autoapi_dirs = [
    os.path.join(PROJECT_ROOT, "app"),
    os.path.join(PROJECT_ROOT, "data_management"),
    os.path.join(PROJECT_ROOT, "detectors"),
    os.path.join(PROJECT_ROOT, "wranglers"),
]
autoapi_ignore = ["*/__pycache__/*", "*/tests/*"]
autoapi_options = [
    "members",
    "undoc-members",
    "show-inheritance",
    "show-module-summary",
]
autoapi_keep_files = True
