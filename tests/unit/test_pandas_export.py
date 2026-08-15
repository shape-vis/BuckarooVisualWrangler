"""Tests for complete generated Pandas export scripts."""

import os
import sys
import tempfile
from unittest.mock import patch

import numpy as np
import pandas as pd

from app.pgraph.delta import Delta
from app.pgraph.node import GraphNode
from app.pgraph.pgraph import PGraph
from app.server_utils.pandas_export import (
    EXPORT_LIBRARY_FILENAME,
    build_pandas_export_script,
    read_export_library_source,
)


def build_graph_with_deltas(*deltas, source_filename=None):
    graph = PGraph(source_filename=source_filename)
    previous = GraphNode("root", "root", "n0_sales", "errors_n0_sales")
    graph.add_root_node(previous)

    parent = "n0_sales"
    for idx, delta in enumerate(deltas, start=1):
        table = f"n{idx}_sales"
        node = GraphNode(parent, delta.operation, table, f"errors_{table}", delta=delta)
        graph.add_node(node)
        parent = table
    return graph, parent


def run_export_script(script):
    # The generated script imports its helpers from the external library, so the
    # library has to be importable. Reproduce the user's setup by writing the
    # library next to the script (on sys.path) before running it.
    tmpdir = tempfile.mkdtemp()
    with open(os.path.join(tmpdir, EXPORT_LIBRARY_FILENAME), "w", encoding="utf-8") as f:
        f.write(read_export_library_source())
    sys.path.insert(0, tmpdir)
    try:
        namespace = {}
        exec(script, namespace)
        return namespace["df"]
    finally:
        sys.path.remove(tmpdir)
        sys.modules.pop("buckaroo_export_helpers", None)


def test_export_with_stable_id_tolerates_reordered_inserted_and_missing_rows(tmp_path):
    csv_path = tmp_path / "sales.csv"
    pd.DataFrame({
        "ID": [99, 3, 1],
        "score": [100.0, None, 10.0],
        "unused": ["new", "old-3", "old-1"],
    }).to_csv(csv_path, index=False)
    graph, current = build_graph_with_deltas(
        Delta("delete", {"operation": "delete", "row_ids": [2]}),
        Delta("impute", {"operation": "impute", "row_ids": [3], "col": "score"}),
        Delta("delete-column", {"operation": "delete-column", "column": "unused"}),
    )

    graph.source_filename = str(csv_path)
    result = run_export_script(graph.get_script_to_node(current))

    assert result["ID"].tolist() == [99, 3, 1]
    assert result.loc[result["ID"] == 3, "score"].iloc[0] == 55.0
    assert "unused" not in result.columns


def test_export_without_id_supports_rows_appended_after_original_data(tmp_path):
    csv_path = tmp_path / "sales.csv"
    pd.DataFrame({
        "score": [10, 20, 30, 40],
    }).to_csv(csv_path, index=False)
    graph, current = build_graph_with_deltas(
        Delta("delete", {"operation": "delete", "row_ids": [2]}),
        source_filename=str(csv_path),
    )
    result = run_export_script(graph.get_script_to_node(current))

    assert result["ID"].tolist() == [1, 3, 4]
    assert result["score"].tolist() == [10, 30, 40]


def test_export_script_imports_helpers_from_external_library():
    graph, current = build_graph_with_deltas(
        Delta("delete", {"operation": "delete", "row_ids": [2]}),
    )

    script = graph.get_script_to_node(current)

    # The boilerplate now lives in the library, so the script just imports it
    # instead of redefining the helpers inline.
    assert "from buckaroo_export_helpers import (" in script
    assert "buckaroo_ensure_id" in script
    assert "buckaroo_delete_rows_by_id" in script
    assert "def buckaroo_ensure_id" not in script


def test_export_library_documents_supported_input_changes():
    library = read_export_library_source()

    assert "If the input CSV already has a stable ID column" in library
    assert "appending rows after the original data is" in library
    assert "supported, but inserting/deleting/reordering rows before edited rows" in library
    assert "inserting/deleting/reordering rows before edited rows" in library


def test_export_emits_plain_int_row_ids_for_numpy_selections(tmp_path):
    # Selections derived from the database can carry NumPy integers. Their repr
    # (e.g. np.int64(2)) references an unimported name, so the export must emit
    # plain Python ints to keep the generated script runnable.
    csv_path = tmp_path / "sales.csv"
    pd.DataFrame({
        "ID": [1, 2, 3],
        "score": [10.0, 20.0, 30.0],
    }).to_csv(csv_path, index=False)
    graph, current = build_graph_with_deltas(
        Delta("delete", {"operation": "delete", "row_ids": [np.int64(2)]}),
        Delta("impute", {"operation": "impute", "row_ids": [np.int64(3)], "col": "score"}),
        source_filename=str(csv_path),
    )
    script = graph.get_script_to_node(current)
    result = run_export_script(script)

    assert "np.int64" not in script
    assert "df = buckaroo_delete_rows_by_id(df, [2])" in script
    assert "df = buckaroo_impute_missing_by_id(df, [3], 'score')" in script
    assert result["ID"].tolist() == [1, 3]


def test_export_impute_leaves_cells_untouched_when_no_valid_fill_value(tmp_path):
    # If the whole column is missing there is no value to impute from. The
    # script should leave the selected cells alone instead of writing NaN.
    csv_path = tmp_path / "sales.csv"
    pd.DataFrame({
        "ID": [1, 2, 3],
        "score": ["", "null", None],
        "keep": [1, 2, 3],
    }).to_csv(csv_path, index=False)
    graph, current = build_graph_with_deltas(
        Delta("impute", {"operation": "impute", "row_ids": [1, 2, 3], "col": "score"}),
        source_filename=str(csv_path),
    )
    result = run_export_script(graph.get_script_to_node(current))

    assert result["score"].isna().all()
    assert result["keep"].tolist() == [1, 2, 3]


def test_export_with_empty_filename_falls_back_to_default():
    script = build_pandas_export_script("", [])

    assert "df = pd.read_csv('data.csv')" in script

    script_none = build_pandas_export_script(None, [])

    assert "df = pd.read_csv('data.csv')" in script_none


def test_export_with_unknown_operation_emits_comment_not_broken_code(tmp_path):
    # Unknown operations should degrade to a harmless comment so the rest of the
    # exported script still runs.
    csv_path = tmp_path / "sales.csv"
    pd.DataFrame({"ID": [1, 2], "score": [10.0, 20.0]}).to_csv(csv_path, index=False)
    graph, current = build_graph_with_deltas(
        Delta("totally-unknown-op", {"operation": "totally-unknown-op"}),
        Delta("delete", {"operation": "delete", "row_ids": [1]}),
        source_filename=str(csv_path),
    )
    script = graph.get_script_to_node(current)
    result = run_export_script(script)

    assert "# Unknown operation: totally-unknown-op" in script
    assert result["ID"].tolist() == [2]
