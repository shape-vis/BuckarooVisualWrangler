"""
Fixtures for the stress tests, which run the app's data operations over generated datasets against the app's own
database and hold every result to the answer key in reference.py.

How many seeds each test runs over is STRESS_SEEDS (20 by default); STRESS_SEED_START moves the window, so a deep run
can go on where the last one stopped. A failure names its seed, and STRESS_SEEDS=1 STRESS_SEED_START=<seed> reruns
just that one.
"""
import os

import pandas as pd
import pytest

import app
from app import db_operations, engine
from app.db_utils.column_types import NUMERIC_DATA_TYPES, TEXT_DATA_TYPES, ColumnTypes
from app.db_utils.execute_sql import copy_insert, fetch_sql, quote_identifier
from app.pgraph.pgraph import node_id_for_count
from app.routes.routes import load_file
from app.server_utils.service_helpers import (build_node, generate_table_name, get_sqlalchemy_dtype_map,
                                              init_pgraph_for_session)
from app.server_utils.set_id_column import set_id_column
from tests.stress import generators
from tests.stress.reference import StoredTable

# information_schema data types that hold whole numbers only
INTEGER_DATA_TYPES = {"integer", "bigint", "smallint"}

SEED_COUNT = int(os.environ.get("STRESS_SEEDS", "20"))
SEED_START = int(os.environ.get("STRESS_SEED_START", "0"))


def seeds():
    """The seeds a stress test runs over."""
    return list(range(SEED_START, SEED_START + SEED_COUNT))


def read_stored(table):
    """
    A table as the database holds it, for the answer key: its rows in "ID" order, and which columns are stored as
    numbers and which as text.
    """
    rows = fetch_sql("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = :name",
                     False, engine, params={"name": table})
    numeric_cols = set()
    text_cols = set()
    integer_cols = set()
    for column_name, data_type in rows:
        if data_type in NUMERIC_DATA_TYPES:
            numeric_cols.add(column_name)
        if data_type in INTEGER_DATA_TYPES:
            integer_cols.add(column_name)
        elif data_type in TEXT_DATA_TYPES:
            text_cols.add(column_name)

    quoted = quote_identifier(table)
    frame = pd.read_sql_query(f'SELECT * FROM {quoted} ORDER BY "ID"', engine, coerce_float=True)
    return StoredTable(name=table, frame=frame, numeric_cols=numeric_cols, text_cols=text_cols,
                       integer_cols=integer_cols)


def drop_session():
    """Drop every table of the session's graph, and the graph itself."""
    graph = app.pgraph_for_session
    tables = []
    if graph is not None:
        tables = list(graph.node_map.keys())
    app.pgraph_for_session = None
    for table in tables:
        db_operations.drop_node_tables(table)
        ColumnTypes.forget(table)
    db_operations.reset()


@pytest.fixture
def session():
    """Leaves no graph and no tables behind, whatever the test made."""
    drop_session()
    yield
    drop_session()


def _store_directly(dataset):
    """
    Store a dataset's values exactly as they are - an empty string stays one - then build the root as an upload
    does. The same steps as load_file, less pandas' CSV reader.
    :return: the root's table name
    """
    frame = pd.DataFrame(dataset.columns)
    frame = set_id_column(frame)
    table = f"{node_id_for_count(0)}_{generate_table_name(dataset.name + '.csv')}"
    dtype_map = get_sqlalchemy_dtype_map(frame)
    frame.to_sql(table, engine, if_exists="replace", dtype=dtype_map, method=copy_insert, index=False)

    root_metrics, root_distortion = build_node(table, table)
    init_pgraph_for_session(table, root_metrics, root_distortion)
    db_operations.load_table(table)
    return table


@pytest.fixture
def make_root(session, tmp_path):
    """
    Builds a root from a generated dataset and makes it the session's current table.
    :return: a function of (dataset, ingest="csv" or "direct") giving the root's StoredTable. "csv" goes through the
             upload path - a CSV file read by pandas - and "direct" stores the values as they are.
    """
    def build(dataset, ingest="csv"):
        if ingest == "csv":
            path = tmp_path / f"{dataset.name}.csv"
            path.write_text(generators.csv_text(dataset), encoding="utf-8")
            result = load_file(str(path), path.name)
            assert result.get("success"), result
            table = result["table_name"]
        else:
            table = _store_directly(dataset)
        return read_stored(table)

    return build


@pytest.fixture
def client():
    return app.app.test_client()
