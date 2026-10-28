"""
Shared fixtures for the SQL tests, which run against the app's own database through its engine.

Most of these tests build a real node graph: a root table with its errors and profile, the session graph holding it,
and whatever candidates and nodes the test stages from it. make_root builds the root and session_graph tears it all
down again, so a test leaves no tables behind.
"""
import pandas as pd
import pytest

import app
from app import db_operations, engine
from app import app as flask_app
from app.db_utils.detector_sql import DetectorSQL
from app.server_utils.service_helpers import build_data_profile_table, init_pgraph_for_session


def drop_node_tables(tables):
    """Drop each node table with all its companion tables - see node_table_names."""
    for table in tables:
        db_operations.drop_node_tables(table)


def store_flags(table, flags):
    """
    Replace a table's errors with exactly these flags, so a test asserts about its own layout rather than about
    whatever the detectors happened to find.
    :param flags: (row_id, column_id, error_type) tuples
    """
    frame = pd.DataFrame(flags, columns=["row_id", "column_id", "error_type"])
    # DetectorSQL writes row_id as bigint even when it finds nothing; an empty frame built by hand would land as text
    frame = frame.astype({"row_id": "int64"})
    frame.to_sql(f"errors_{table}", engine, if_exists="replace", index=False)


@pytest.fixture
def session_graph():
    """
    Leaves the process-wide session graph as it found it: when the test is done, every node in the graph - the root,
    candidates, accepted nodes - has its tables dropped, and the graph is cleared.
    :return: a list of further tables to drop, for any a test makes outside the graph
    """
    extra_tables = []
    yield extra_tables

    tables = list(extra_tables)
    graph = app.pgraph_for_session
    if graph is not None:
        tables.extend(graph.node_map.keys())
    app.pgraph_for_session = None
    drop_node_tables(tables)


@pytest.fixture
def make_root(session_graph):
    """
    Builds a real root node the way an upload does - its table, errors, data profile and the session graph holding
    it - and makes it the current table.
    :return: a function of (table, data, flags=None); flags, when given, replace what the detectors found
    """
    def build(table, data, flags=None):
        session_graph.append(table)
        pd.DataFrame(data).to_sql(table, engine, if_exists="replace", index=False)
        DetectorSQL(engine, table).generate_errors_table()
        if flags is not None:
            store_flags(table, flags)
        build_data_profile_table(table)
        init_pgraph_for_session(table)
        db_operations.load_table(table)

    return build


@pytest.fixture
def client():
    """A test client for the Flask app."""
    return flask_app.test_client()
