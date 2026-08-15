"""Helpers for generating readable Pandas export scripts.

The generated script no longer carries its own copy of the Buckaroo helper
functions. Instead it imports them from ``buckaroo_export_helpers``, a small
library module that is shipped next to the script. Keeping the boilerplate in
one importable file means every export stays short and the helpers only have to
be maintained in a single place.
"""

import os


# Name of the helper library module that generated scripts import from, and the
# file it must be saved as so the import resolves when the script is run.
EXPORT_LIBRARY_MODULE = "buckaroo_export_helpers"
EXPORT_LIBRARY_FILENAME = f"{EXPORT_LIBRARY_MODULE}.py"

# Helper functions that the generated script (and the per-operation Delta code)
# call by name. These are imported from the library at the top of every export.
EXPORTED_HELPER_NAMES = (
    "buckaroo_ensure_id",
    "buckaroo_delete_rows_by_id",
    "buckaroo_impute_missing_by_id",
    "buckaroo_delete_column",
)


def read_export_library_source():
    """Return the source of the helper library that ships with the export."""
    library_path = os.path.join(os.path.dirname(__file__), EXPORT_LIBRARY_FILENAME)
    with open(library_path, "r", encoding="utf-8") as library_file:
        return library_file.read()


def _build_helper_import():
    """Build the import statement that pulls helpers in from the library."""
    names = ",\n".join(f"    {name}" for name in EXPORTED_HELPER_NAMES)
    return f"from {EXPORT_LIBRARY_MODULE} import (\n{names},\n)"


def build_pandas_export_script(filename, path):
    """Build a complete Pandas script from a root-to-current graph path."""
    # Guard against a missing/empty source name so read_csv always gets a path.
    if not filename:
        filename = "data.csv"
    script = [
        "import pandas as pd",
        "",
        _build_helper_import(),
        "",
        f"df = pd.read_csv({filename!r})",
        "df = buckaroo_ensure_id(df)",
        "",
    ]

    for node in path:
        if node.delta:
            script.append(f"# Operation: {node.wrangle_op}")
            script.append(node.delta.pandas_code)
            script.append("")

    return "\n".join(script)
