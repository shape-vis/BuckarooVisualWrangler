#Buckaroo Project - started: June 1, 2025
#This file helps deliver on endpoint services

import hashlib
import json
import random
import string
import re
import threading
from sqlalchemy import types as sql_types
import pandas as pd

import app
from app.db_utils.detector_sql import DetectorSQL
from app.db_utils.execute_sql import COMPANION_PREFIXES, errors_table_name
from app.pgraph.node import GraphNode
from app.pgraph.pgraph import PGraph
from app.db_utils.data_profile import DataProfile
from app.pgraph.metrics import compute_node_metrics

# Node tables are named "<prefix>_<base name>". The root's prefix is its node id, n{digit}{letter} - see
# node_id_for_count in app/pgraph/pgraph.py. Every node since is staged as a candidate first and keeps the
# candidate's prefix, c{n}, for good: a table name never changes, and the node's id is its label instead.
NODE_PREFIX_PATTERN = re.compile(r'^n(\d[a-z])_(.+)$')
CANDIDATE_PREFIX_PATTERN = re.compile(r'^(c\d+)_(.+)$')

# Postgres caps identifiers at 63 characters
POSTGRES_IDENTIFIER_LIMIT = 63


def _longest_companion_prefix():
    """How many characters the longest companion table name adds to its node's table name - see COMPANION_PREFIXES."""
    longest = 0
    for prefix in COMPANION_PREFIXES:
        longest = max(longest, len(prefix))
    return longest


# A node's table name is kept to this length, so every companion table named from it fits too. See safe_pg_name.
MAX_TABLE_NAME_LENGTH = POSTGRES_IDENTIFIER_LIMIT - _longest_companion_prefix()

# Serializes the moments candidates (app/server_utils/candidates.py) touch the graph: claiming their table names,
# joining the graph, being accepted or declined. Those are not safe to run concurrently - a candidate's table name
# and an accepted node's label are both handed out by reading a counter, so two requests in flight would claim the
# same one. Flask's dev server is threaded, so this is reachable simply by clicking twice. It is held for moments
# only: the candidates' tables are built between those moments, without it. Re-entrant, since accepting an AI
# suggestion in one step stages it then accepts it.
WRANGLE_LOCK = threading.RLock()

def _to_json(value):
    """How json.dumps writes the graph's objects: through their own __json__, and anything else as null."""
    if hasattr(value, '__json__'):
        return value.__json__()
    return None


def session_graph():
    """:return: the session's PGraph, or None before anything has been uploaded"""
    return app.pgraph_for_session


def is_node(table_name):
    """:return: whether the table is a node of the session's graph - False before anything has been uploaded"""
    graph = session_graph()
    return graph is not None and table_name in graph.node_map


def require_node(table_name):
    """
    Refuse a table that is not a node of the session's graph, before anything reads it. A request names tables by
    hand, and only the graph's own may be read.
    :raises ValueError: when there is no graph yet, or the table is not one of its nodes
    """
    if session_graph() is None:
        raise ValueError("no graph in this session")
    if not is_node(table_name):
        raise ValueError(f"{table_name} is not a node in this graph")


def json_object_body():
    """
    The request's JSON body when it is an object, and {} otherwise - when there is no body, it isn't JSON, or it is some
    other JSON value, such as a list. A route can then read its fields with .get and refuse what is missing, whatever
    shape the body came in.
    """
    from flask import request

    body = request.get_json(force=True, silent=True)
    if isinstance(body, dict):
        return body
    return {}


def bounded_int(args, name, default, low, high):
    """
    An integer request parameter, clamped so a request cannot ask for an absurd amount of work.
    :param args: the request's parameters, e.g. request.args
    """
    value = int(args.get(name, default))
    return max(low, min(high, value))


def get_current_pgraph():
    """
    :return: the session's graph as a JSON string, written through each object's __json__
    """
    return json.dumps(app.pgraph_for_session, default=_to_json)

def clicked_node_access_helper(node_table_name):
    return app.pgraph_for_session.set_clicked_node_as_current(node_table_name)

def get_pgraph_redo():
    """:return: the table redo moves to, or None when there is nothing to redo - or no graph yet"""
    graph = session_graph()
    if graph is None:
        return None
    return graph.redo_pgraph()

def get_pgraph_undo():
    """:return: the table undo moves to, or None at the root - or with no graph yet"""
    graph = session_graph()
    if graph is None:
        return None
    return graph.undo_pgraph()

def safe_pg_name(base: str, suffix: str) -> str:
    """
    Build a table name guaranteed to keep both itself and every companion table named from it - errors_<name>,
    dp_<name>; see COMPANION_PREFIXES in app/db_utils/execute_sql.py - within PostgreSQL's 63-char identifier limit.

    If base+suffix already fits, use it as-is. Otherwise truncate the base
    and append an 8-char MD5 hash so the name stays unique.
    """
    name = f"{base}{suffix}"
    if len(name) <= MAX_TABLE_NAME_LENGTH:
        return name

    base_hash = hashlib.md5(base.encode()).hexdigest()[:8]
    # Room for the suffix, and for the underscore and 8 hash characters that keep a shortened name unique
    max_base_length = MAX_TABLE_NAME_LENGTH - len(suffix) - 9
    return f"{base[:max_base_length]}_{base_hash}{suffix}"


def generate_table_name(csv_name):
    """
    Turn an uploaded file's name into a table name: the .csv extension dropped, anything but letters, digits and
    underscores replaced with an underscore, lower-cased, and a random suffix added so two uploads of the same file
    get tables of their own.
    :param csv_name: csv name from user upload
    :return: the table name
    """
    if ".csv" in csv_name:
        csv_name = csv_name[0:len(csv_name)-4]

    clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', csv_name).lower()
    random_string = "".join(random.choices(string.ascii_letters + string.digits, k=5))
    return safe_pg_name(clean_name, "_" + random_string)


def build_data_profile_table(table_name):
    """
    Build a table's data profile from scratch, covering every column, as its dp_ table.
    :param table_name: the table to profile
    """
    from app import engine

    DataProfile(table_name, engine).generate_profile_table()


def build_node(table_name, root_table):
    """
    Build everything a node's table is read through, from the table itself: its errors and data profile tables, and
    its quality metrics and drift from root. The root is built this way at upload, and so is every candidate - so a
    node's measurements never depend on how it was made.

    Each step is SQL, and the drift measures its columns at the same time on the query pool. The metrics read the data
    profile, which counts the errors, so each comes after the one before. The table's rows are counted once, for both
    the metrics and the drift.

    :param table_name: the node's table, already holding its data
    :param root_table: the session's root table - the table itself, for the root
    :return: (metrics, distortion)
    """
    from app import engine
    from app.pgraph.distortion import compute_node_distortion

    DetectorSQL(engine, table_name).generate_errors_table()
    build_data_profile_table(table_name)
    row_count = app.db_operations.get_row_count(table_name)
    metrics = compute_node_metrics(table_name, row_count)
    distortion = compute_node_distortion(table_name, root_table, row_count)
    return metrics, distortion


def is_categorical(column):
    """
    Whether an uploaded column is mostly text. Each value is classed by its Python type, except that a string
    holding a plain number counts as numeric; the class covering the most rows decides. A column with no values at
    all counts as categorical.
    :param column: the column, as a pandas Series
    :return: True if the column is categorical, False otherwise
    """
    rows_by_value_type = {}
    for value, count in column.value_counts().items():
        value_type = type(value).__name__
        if isinstance(value, str) and re.fullmatch(r'^\d+(\.\d+)?$', value.strip()):
            value_type = "numeric"
        rows_by_value_type[value_type] = rows_by_value_type.get(value_type, 0) + count

    # The first type to reach the largest count wins a tie, as value_counts orders the values
    majority_type = None
    majority_rows = 0
    for value_type, rows in rows_by_value_type.items():
        if rows > majority_rows:
            majority_rows = rows
            majority_type = value_type

    return majority_type in ("str", None)

def get_sqlalchemy_dtype_map(df):
    """
    Builds a dtype map for .to_sql() by inspecting the actual values in each column
    to find the majority type, so messy/mixed columns get cast correctly in PostgreSQL.
    :param df: the dataframe to inspect
    :return: dict mapping column name to SQLAlchemy type
    """
    dtype_map = {}
    for col in df.columns:
        if is_categorical(df[col]):
            dtype_map[col] = sql_types.Text()
        else:
            non_null = df[col].dropna()
            numeric_series = pd.to_numeric(non_null, errors='coerce')
            # If any non-null values failed numeric coercion, the column has true mixed
            # values (e.g. "N/A" strings alongside numbers). Store as Text to preserve
            # all values; gather_mixed_cols() will classify it as categorical_mixed.
            if numeric_series.isna().any() or numeric_series.empty:
                dtype_map[col] = sql_types.Text()
            else:
                try:
                    if (numeric_series == numeric_series.astype(int)).all():
                        dtype_map[col] = sql_types.BigInteger()
                    else:
                        dtype_map[col] = sql_types.Float()
                except (OverflowError, ValueError):
                    dtype_map[col] = sql_types.Float()
    return dtype_map

def init_pgraph_for_session(root_table, metrics=None, distortion=None):
    """
    Start the session's graph, with the root as its only node.
    :param root_table: the uploaded table, with its errors and data profile tables already built
    :param metrics: the root's metrics, when build_node has just measured them; measured here otherwise
    :param distortion: the root's drift - zero throughout - likewise
    """
    from app.pgraph.distortion import compute_node_distortion

    if metrics is None:
        metrics = compute_node_metrics(root_table)
    if distortion is None:
        distortion = compute_node_distortion(root_table, root_table)

    app.pgraph_for_session = PGraph()

    root_node = GraphNode("root", "root", root_table, errors_table_name(root_table))
    root_node.set_metrics(metrics)
    root_node.set_distortion(distortion)
    app.pgraph_for_session.add_root_node(root_node)

def parse_node_id(table_name):
    """
    Parse a node table's name into its prefix and base: 'n0c_rest_of_name' into ('0c', 'rest_of_name'), and a
    candidate's 'c7_rest_of_name' into ('c7', 'rest_of_name'). Returns None for anything else.
    """
    match = NODE_PREFIX_PATTERN.match(table_name)
    if match is None:
        match = CANDIDATE_PREFIX_PATTERN.match(table_name)
    if match is None:
        return None
    return match.group(1), match.group(2)
