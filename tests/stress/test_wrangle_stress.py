"""
The wrangles - delete and impute on a one-column selection; delete, impute x and impute y on a two-column one - over
generated datasets. Each is staged the way the app stages a repair, through /api/wrangle/create-previews, and every
candidate's table is held to the answer key: the rows it keeps, every cell of them, and the flags rebuilt on it.
"""
import math
import random
import threading

import pytest

import app
from app import engine
from app.db_utils.execute_sql import fetch_sql
from app.server_utils import candidates
from tests.stress import generators, reference
from tests.stress.conftest import read_stored, seeds
from tests.stress.test_detector_stress import assert_flags_match

# How close a stored float must be to the answer key's. Postgres' AVG divides in numeric, the answer key in Decimal,
# and both round to the nearest float8 - they can still differ in the last bit.
FLOAT_TOLERANCE = 1e-12


# ── Helpers ──────────────────────────────────────────────────────────────────

def values_equal(expected, actual):
    """Whether a stored cell is the answer key's: both NULL, numbers within FLOAT_TOLERANCE, or the same text."""
    if reference.is_null(expected) or reference.is_null(actual):
        return reference.is_null(expected) and reference.is_null(actual)
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if math.isinf(expected) or math.isinf(actual):
            return expected == actual
        return math.isclose(expected, actual, rel_tol=FLOAT_TOLERANCE, abs_tol=FLOAT_TOLERANCE)
    return str(expected) == str(actual)


def assert_rows_match(expected_rows, table):
    """The stored table holds exactly the expected rows, cell for cell."""
    actual_rows = dict(table.rows())
    assert set(actual_rows) == set(expected_rows), (
        f"{table.name} holds rows {sorted(set(actual_rows) ^ set(expected_rows))[:10]} the answer key does not agree on")

    for row_id, expected_values in expected_rows.items():
        actual_values = actual_rows[row_id]
        for column, expected in expected_values.items():
            actual = actual_values[column]
            assert values_equal(expected, actual), f"{table.name} row {row_id} {column!r}: {actual!r} != {expected!r}"


def stage(client, row_ids, cols):
    """Stage the repairs of a selection on the current node. :return: {op: candidate json}"""
    response = client.post("/api/wrangle/create-previews", json={"row_ids": row_ids, "cols": cols})
    body = response.get_json()
    assert response.status_code == 200, body
    staged = {}
    for candidate in body["candidates"]:
        staged[candidate["op"]] = candidate
    return staged


def accept(client, table):
    response = client.post("/api/candidates/accept", json={"table": table})
    assert response.status_code == 200, response.get_json()


def discard(client, tables):
    response = client.post("/api/candidates/discard", json={"tables": tables})
    assert response.status_code == 200, response.get_json()


def imputed_column_of(op, cols):
    if op == "impute_y":
        return cols[1]
    return cols[0]


def expected_rows_for(parent, op, cols, row_ids):
    """The answer key's rows for one candidate, and the fill value when it is an impute."""
    if op == "delete":
        return reference.delete_rows(parent, row_ids), None
    column = imputed_column_of(op, cols)
    integer_column = column in parent.integer_cols
    return reference.impute_rows(parent, column, row_ids, integer_column)


def check_candidate(parent, candidate, cols, row_ids):
    """One staged candidate holds what the answer key says, and its flags are rebuilt from what it holds."""
    table = read_stored(candidate["table"])
    expected_rows, _ = expected_rows_for(parent, candidate["op"], cols, row_ids)
    assert_rows_match(expected_rows, table)

    # A wrangle never changes how a column is stored
    assert table.numeric_cols == parent.numeric_cols
    assert table.text_cols == parent.text_cols
    assert list(table.frame.columns) == list(parent.frame.columns)

    assert_flags_match(table, reference.detect(table))
    assert candidate["row_count"] == len(row_ids)
    return table


def selections(table, column, rng):
    """
    Ways a user can select rows on one column, each named: its missing cells, a histogram bar's rows, a random sample,
    one row, every row, and ids that name no row at all mixed with ones that do.
    """
    ids = table.ids
    chosen = {}

    missing = []
    for row_id, values in table.rows():
        if reference.is_missing(values[column]):
            missing.append(row_id)
    if missing:
        chosen["missing"] = missing

    flags = reference.detect(table)
    plot = reference.histogram(table, flags, [column])
    fullest = None
    fullest_rows = []
    for bin_key in plot.bins:
        rows_in_bin = []
        for row_id, row_bin in plot.row_bins.items():
            if row_bin == bin_key:
                rows_in_bin.append(row_id)
        if fullest is None or len(rows_in_bin) > len(fullest_rows):
            fullest = bin_key
            fullest_rows = rows_in_bin
    if fullest_rows:
        chosen["fullest_bar"] = sorted(fullest_rows)

    sample_size = max(1, len(ids) // 3)
    chosen["random_third"] = sorted(rng.sample(ids, sample_size))
    chosen["one_row"] = [rng.choice(ids)]
    chosen["every_row"] = list(ids)
    chosen["with_unknown_ids"] = [ids[0], max(ids) + 1000, max(ids) + 1001]
    return chosen


def leftover_candidate_tables(before):
    """Tables named like a candidate's that were not there before, and that no graph node owns."""
    rows = fetch_sql("SELECT table_name FROM information_schema.tables WHERE table_name ~ '^c[0-9]+_'", False,
                     engine) or []
    owned = set()
    if app.pgraph_for_session is not None:
        owned = set(app.pgraph_for_session.node_map)
    leftover = []
    for (name,) in rows:
        if name in before or name in owned:
            continue
        leftover.append(name)
    return leftover


def candidate_tables_now():
    rows = fetch_sql("SELECT table_name FROM information_schema.tables WHERE table_name ~ '^c[0-9]+_'", False,
                     engine) or []
    names = set()
    for (name,) in rows:
        names.add(name)
    return names


def ingest_for(seed):
    """Alternate between the upload path and values stored as they are."""
    if seed % 2 == 0:
        return "csv"
    return "direct"


def personalities_for(seed):
    if ingest_for(seed) == "csv":
        return generators.CSV_SAFE
    return None


# ── One-column and two-column repairs ────────────────────────────────────────

@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_one_column_repairs_match_the_answer_key(make_root, client, seed):
    rng = random.Random(seed)
    dataset = generators.make_dataset(seed, personalities=personalities_for(seed))
    root = make_root(dataset, ingest=ingest_for(seed))
    column = rng.choice(root.data_columns)

    for name, row_ids in selections(root, column, rng).items():
        staged = stage(client, row_ids, [column])
        assert set(staged) == {"delete", "impute"}, name
        for candidate in staged.values():
            check_candidate(root, candidate, [column], row_ids)

        tables = []
        for candidate in staged.values():
            tables.append(candidate["table"])
        discard(client, tables)


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_two_column_repairs_match_the_answer_key(make_root, client, seed):
    rng = random.Random(seed)
    dataset = generators.make_dataset(seed, personalities=personalities_for(seed))
    root = make_root(dataset, ingest=ingest_for(seed))
    if len(root.data_columns) < 2:
        pytest.skip("needs two columns")
    cols = rng.sample(root.data_columns, 2)

    for name, row_ids in selections(root, cols[0], rng).items():
        staged = stage(client, row_ids, cols)
        assert set(staged) == {"delete", "impute_x", "impute_y"}, name
        for candidate in staged.values():
            check_candidate(root, candidate, cols, row_ids)

        tables = []
        for candidate in staged.values():
            tables.append(candidate["table"])
        discard(client, tables)


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_the_same_column_on_both_axes(make_root, client, seed):
    """A heatmap of a column against itself: impute x and impute y fill the same column the same way."""
    dataset = generators.make_dataset(seed, personalities=personalities_for(seed))
    root = make_root(dataset, ingest=ingest_for(seed))
    column = root.data_columns[0]
    row_ids = root.ids[: max(1, len(root.ids) // 2)]

    staged = stage(client, row_ids, [column, column])
    for candidate in staged.values():
        check_candidate(root, candidate, [column, column], row_ids)


# ── Chains of accepted wrangles ──────────────────────────────────────────────

@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_a_chain_of_accepted_wrangles_stays_consistent(make_root, client, seed):
    """
    Five wrangles in a row, each accepted and the next staged from it, each held to the answer key run on the table
    before it. Every node's rows stay a subset of root's, and the session follows along.
    """
    rng = random.Random(seed)
    dataset = generators.make_dataset(seed, personalities=personalities_for(seed))
    root = make_root(dataset, ingest=ingest_for(seed))
    root_ids = set(root.ids)
    parent = root

    for step in range(5):
        if not parent.ids:
            break
        cols = rng.sample(parent.data_columns, min(len(parent.data_columns), rng.choice([1, 2])))
        choices = selections(parent, cols[0], rng)
        row_ids = choices[rng.choice(sorted(choices))]

        staged = stage(client, row_ids, cols)
        op = rng.choice(sorted(staged))
        candidate = staged[op]
        child = check_candidate(parent, candidate, cols, row_ids)
        accept(client, candidate["table"])

        assert set(child.ids) <= root_ids, f"step {step} made rows root never had"
        assert app.db_operations.main_table_name == candidate["table"]
        assert app.pgraph_for_session.current_node_table_name == candidate["table"]
        parent = child


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_imputing_missing_cells_twice_changes_nothing_the_second_time(make_root, client, seed):
    """A float column's missing cells filled with its mean: filling them again uses the same mean."""
    dataset = generators.make_dataset(seed, personalities=["normal_floats"], column_count=2)
    root = make_root(dataset, ingest="direct")
    column = root.data_columns[0]
    if column not in root.numeric_cols or column in root.integer_cols:
        pytest.skip("needs a float column")
    missing = []
    for row_id, values in root.rows():
        if reference.is_null(values[column]):
            missing.append(row_id)
    present = len(root.ids) - len(missing)
    if not missing or present == 0:
        pytest.skip("needs missing and present cells")

    first = stage(client, missing, [column])["impute"]
    accept(client, first["table"])
    once = read_stored(first["table"])

    second = stage(client, missing, [column])["impute"]
    twice = read_stored(second["table"])

    once_rows = dict(once.rows())
    assert_rows_match(once_rows, twice)


# ── Edges of the selection ───────────────────────────────────────────────────

@pytest.mark.sql
def test_an_empty_selection_is_refused(make_root, client):
    root = make_root(generators.make_dataset(1, row_count=10), ingest="direct")

    response = client.post("/api/wrangle/create-previews", json={"row_ids": [], "cols": [root.data_columns[0]]})

    assert response.status_code == 400
    assert len(app.pgraph_for_session.node_map) == 1


@pytest.mark.sql
@pytest.mark.parametrize("cols", [[], ["a", "b", "c"]])
def test_a_selection_on_no_columns_or_three_is_refused(make_root, client, cols):
    make_root(generators.make_dataset(2, row_count=10), ingest="direct")

    response = client.post("/api/wrangle/create-previews", json={"row_ids": [1], "cols": cols})

    assert response.status_code == 400


@pytest.mark.sql
def test_deleting_every_row_leaves_an_empty_node_that_still_builds(make_root, client):
    root = make_root(generators.make_dataset(3, row_count=25), ingest="direct")

    staged = stage(client, root.ids, [root.data_columns[0]])
    accept(client, staged["delete"]["table"])
    empty = read_stored(staged["delete"]["table"])

    assert empty.ids == []
    node = app.pgraph_for_session.node_map[empty.name]
    assert node.metrics.row_count == 0
    # An empty node can still be plotted and wrangled from without raising
    response = client.get("/api/plots/1-d-histogram", query_string={"column": root.data_columns[0]})
    assert response.status_code == 200, response.get_json()


@pytest.mark.sql
def test_ids_that_name_no_row_change_nothing(make_root, client):
    root = make_root(generators.make_dataset(4, row_count=40), ingest="direct")
    unknown = [max(root.ids) + 1, max(root.ids) + 2]

    staged = stage(client, unknown, [root.data_columns[0]])

    for candidate in staged.values():
        table = read_stored(candidate["table"])
        assert_rows_match(dict(root.rows()), table)


@pytest.mark.sql
def test_a_huge_selection_of_ids_is_handled(make_root, client):
    """Every row, plus a hundred thousand ids that name none - the hash join has to take it in its stride."""
    root = make_root(generators.make_dataset(5, row_count=generators.LARGE_ROW_COUNT), ingest="direct")
    row_ids = list(root.ids) + list(range(10 ** 7, 10 ** 7 + 100000))

    staged = stage(client, row_ids, [root.data_columns[0]])

    assert read_stored(staged["delete"]["table"]).ids == []


# ── Building candidates at once ──────────────────────────────────────────────

@pytest.mark.sql
def test_candidates_built_at_the_same_time_do_not_collide(make_root):
    """Six selections staged from six threads at once: every candidate gets its own table, and each is right."""
    rng = random.Random(7)
    root = make_root(generators.make_dataset(7, row_count=400), ingest="direct")

    requests = []
    for _ in range(6):
        cols = rng.sample(root.data_columns, 1)
        row_ids = sorted(rng.sample(root.ids, 50))
        requests.append((cols, row_ids))

    results = [None] * len(requests)
    errors = []

    def run(index, cols, row_ids):
        specs = [
            candidates.CandidateSpec(op="delete", cols=cols, row_ids=row_ids, meta={"row_count": len(row_ids)}),
            candidates.CandidateSpec(op="impute", cols=cols, row_ids=row_ids, imputed_column=cols[0],
                                     meta={"row_count": len(row_ids)}),
        ]
        try:
            results[index] = candidates.stage_all(root.name, specs)
        except Exception as error:
            errors.append(error)

    threads = []
    for index, (cols, row_ids) in enumerate(requests):
        thread = threading.Thread(target=run, args=(index, cols, row_ids))
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    tables = set()
    for (cols, row_ids), staged in zip(requests, results):
        for candidate in staged:
            assert candidate["table"] not in tables
            tables.add(candidate["table"])
            check_candidate(root, candidate, cols, row_ids)


@pytest.mark.sql
def test_a_failed_build_standing_alone_leaves_no_tables_behind(make_root):
    """
    Staged each on its own, the good one is staged and only the bad one's tables go. Staged together, one failure
    stages none of them - test_candidates.py's test_if_one_build_fails_none_of_its_set_is_staged checks that.
    """
    root = make_root(generators.make_dataset(8, row_count=30), ingest="direct")
    before = candidate_tables_now()
    column = root.data_columns[0]
    good = candidates.CandidateSpec(op="delete", cols=[column], row_ids=[1], meta={"row_count": 1})
    bad = candidates.CandidateSpec(op="impute", cols=[column], row_ids=[1], imputed_column="no such column",
                                   meta={"row_count": 1})

    staged, failures = candidates.stage_each(root.name, [good, bad])
    assert len(staged) == 1
    assert len(failures) == 1
    assert leftover_candidate_tables(before) == []
