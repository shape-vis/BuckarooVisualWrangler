"""
Drift from root (app/db_utils/drift_sql.py and app/pgraph/distortion.py) over generated graphs: every node's drift,
column by column, held to the answer key - scipy's Wasserstein distance over numpy's IQR, and the total variation
distance with missing cells as their own category - with the edit facts behind it, and the drill-down payloads the
compare panel's Drift views draw.
"""
import math

import numpy as np
import pytest

import app
from tests.stress import generators, reference
from tests.stress.conftest import read_stored, seeds
from tests.stress.family import build_family

# The app sums its distances in Postgres, the answer key in scipy, in different orders
DRIFT_TOLERANCE = 1e-9
# Float8's precision, times a margin for the rounding errors that pile up across a column's values
ROUNDING_PER_CONDITIONING = 1e-14


def tolerance_for(expected):
    """
    How far apart a correct app and a correct answer key can be on one column: DRIFT_TOLERANCE, or more for a column
    whose numbers dwarf its spread - values near a million that differ in the third decimal, say - where rounding in
    the numbers themselves is magnified by that ratio.
    """
    conditioned = ROUNDING_PER_CONDITIONING * expected.get("conditioning", 1.0)
    return max(DRIFT_TOLERANCE, conditioned)


def root_kinds(root):
    kinds = {}
    for column in root.data_columns:
        kinds[column] = root.column_kind(column)
    return kinds


def node_distortion(table):
    return app.pgraph_for_session.node_map[table.name].distortion


def assert_drift_matches(actual, expected, context):
    if expected["reason"] is not None:
        assert actual["degenerate"], (context, actual)
        assert actual["reason"] == expected["reason"], context
        assert actual["value"] is None, context
        return
    assert not actual["degenerate"], (context, actual)
    tolerance = tolerance_for(expected)
    assert actual["value"] == pytest.approx(expected["value"], rel=tolerance, abs=tolerance), context
    assert actual["value"] >= 0, context
    assert actual["n_root"] == expected["n_root"], context
    assert actual["n_node"] == expected["n_node"], context
    low_confidence = min(expected["n_root"], expected["n_node"]) < reference.LOW_CONFIDENCE_N
    assert actual["low_confidence"] == low_confidence, context


def assert_node_matches(root, node, kinds):
    expected = reference.node_drift(root, node, kinds)
    actual = node_distortion(node)

    for column, expected_column in expected["columns"].items():
        assert_drift_matches(actual["columns"][column], expected_column, (node.name, column))
        if root.column_kind(column) == "categorical" and expected_column["value"] is not None:
            assert actual["columns"][column]["value"] <= 1 + DRIFT_TOLERANCE, "TVD above 1"

    if expected["overall"] is None:
        assert actual["overall"] is None
    else:
        assert actual["overall"] == pytest.approx(expected["overall"], rel=DRIFT_TOLERANCE, abs=DRIFT_TOLERANCE)

    facts = actual["facts"]
    assert facts["rows_root"] == len(root.ids)
    assert facts["rows_removed"] == len(set(root.ids) - set(node.ids))
    for column in kinds:
        assert facts["cells_changed"][column] == reference.cells_changed(root, node, column), (node.name, column)


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_every_nodes_drift_matches_the_answer_key(make_root, client, seed):
    family = build_family(make_root, client, seed)
    kinds = root_kinds(family.root)

    for node in (family.child, family.sibling, family.grandchild):
        assert_node_matches(family.root, node, kinds)


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_an_unchanged_copy_has_its_parents_drift(make_root, client, seed):
    """A candidate whose selection named no rows changed nothing, so it has drifted from root as far as its parent."""
    family = build_family(make_root, client, seed)

    unknown = [max(family.root.ids, default=0) + 100]
    response = client.post("/api/wrangle/create-previews",
                           json={"row_ids": unknown, "cols": [family.child.data_columns[0]]})
    for candidate in response.get_json()["candidates"]:
        copy = read_stored(candidate["table"])
        for column, column_drift in node_distortion(copy)["columns"].items():
            if column_drift["value"] is not None:
                # Identical to the child, but measured from root - so equal to the child's own drift
                child_value = node_distortion(family.child)["columns"][column]["value"]
                assert column_drift["value"] == pytest.approx(child_value, abs=DRIFT_TOLERANCE)


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_repairing_missing_cells_registers_in_full(make_root, client, seed):
    """
    Deleting a categorical column's missing rows, or filling them, moves every one of them out of the null category:
    the drift is exactly the share of rows that were missing, less what they moved into.
    """
    dataset = generators.make_dataset(seed, personalities=["few_categories", "missing_tokens"], column_count=1,
                                      row_count=max(20, generators.row_count_for(seed)))
    root = make_root(dataset, ingest="direct")
    column = root.data_columns[0]
    if root.column_kind(column) != "categorical":
        pytest.skip("needs a categorical column")
    missing = []
    for row_id, values in root.rows():
        if reference.is_missing(values[column]):
            missing.append(row_id)
    if not missing or len(missing) == len(root.ids):
        pytest.skip("needs some missing cells and some present")

    response = client.post("/api/wrangle/create-previews", json={"row_ids": missing, "cols": [column]})
    kinds = root_kinds(root)
    for candidate in response.get_json()["candidates"]:
        node = read_stored(candidate["table"])
        assert_node_matches(root, node, kinds)
        null_share = len(missing) / len(root.ids)
        drift = node_distortion(node)["columns"][column]["value"]
        # All of null's share left; how much of it arrived elsewhere decides the rest, never more than all of it
        assert drift >= null_share * (1 - null_share) - DRIFT_TOLERANCE
        assert drift <= null_share + DRIFT_TOLERANCE


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_drift_detail_adds_up(make_root, client, seed):
    """
    The drill-down payload agrees with the node's drift and with itself: a Sankey's flows account for every one of
    root's rows, its removed sink for every deleted one; a ridgeline's curves are non-negative, on one grid, and the
    node's holds its share of root's rows.
    """
    family = build_family(make_root, client, seed)
    root = family.root

    for node in (family.child, family.grandchild):
        for column in root.data_columns:
            response = client.get("/api/pgraph/drift_detail", query_string={"node": node.name, "column": column})
            body = response.get_json()
            assert response.status_code == 200 and body["success"], body
            assert body["distortion"] == node_distortion(node)["columns"][column]
            assert body["rows_root"] == len(root.ids)
            assert body["rows_removed"] == len(set(root.ids) - set(node.ids))

            if body["kind"] == "categorical":
                assert_flows_add_up(body["flows"], root, node, column)
            else:
                assert_density_adds_up(body["density"], root, node, column)


def assert_flows_add_up(flows, root, node, column):
    total = 0
    removed = 0
    moved = 0
    for flow in flows["flows"]:
        assert flow["rows"] > 0
        total += flow["rows"]
        if flow["target"] == reference.REMOVED_LABEL:
            removed += flow["rows"]
        elif flow["source"] != flow["target"]:
            moved += flow["rows"]
    assert total == len(root.ids)
    assert removed == len(set(root.ids) - set(node.ids))
    assert len(flows["sources"]) <= reference.MAX_LABELS

    expected = reference.category_flows(root, node, column)
    expected_moved = 0
    expected_total = 0
    for (source, target), rows in expected.items():
        expected_total += rows
        if source != target:
            expected_moved += rows
    expected_churn = expected_moved / expected_total if expected_total else 0.0
    assert flows["churn"] == pytest.approx(expected_churn)
    assert flows["categories"] == len({source for source, _ in expected})

    for source, rate in flows["removal_rates"].items():
        assert 0.0 <= rate <= 1.0, source


def assert_density_adds_up(density, root, node, column):
    root_numbers = []
    for value in root.values(column):
        number = root.number_of(column, value)
        if number is not None:
            root_numbers.append(number)
    node_numbers = []
    for value in node.values(column):
        number = node.number_of(column, value)
        if number is not None:
            node_numbers.append(number)

    if len(root_numbers) < 2 or min(root_numbers) == max(root_numbers):
        assert density is None
        return
    assert density is not None

    grid = np.asarray(density["grid"], dtype=float)
    root_curve = np.asarray(density["root"], dtype=float)
    assert len(grid) == len(root_curve)
    assert np.all(np.diff(grid) > 0)
    assert np.all(root_curve >= 0)

    expected_bandwidth = 0.30 * float(np.std(np.asarray(root_numbers), ddof=1))
    assert density["bandwidth"] == pytest.approx(expected_bandwidth, rel=1e-9)

    # Root's curve is a density over a grid reaching three bandwidths past its values: nearly all its area is on it
    root_area = np.trapezoid(root_curve, grid)
    assert 0.99 <= root_area <= 1.0 + 1e-6

    if len(node_numbers) < 2:
        assert density["node"] is None
        return
    node_curve = np.asarray(density["node"], dtype=float)
    assert np.all(node_curve >= 0)
    # Scaled by the node's share of root's values, and only what lands on root's grid is drawn
    node_area = np.trapezoid(node_curve, grid)
    share = len(node_numbers) / len(root_numbers)
    assert node_area <= share + 1e-6
    if min(node_numbers) >= min(root_numbers) and max(node_numbers) <= max(root_numbers):
        assert node_area >= 0.99 * share


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_drift_from_an_ancestor_matches_the_answer_key(make_root, client, seed):
    """Measured from the child instead of root, the grandchild's drift is the answer key's between those two."""
    family = build_family(make_root, client, seed)
    kinds = root_kinds(family.root)

    for column, kind in kinds.items():
        response = client.get("/api/pgraph/drift_detail", query_string={
            "node": family.grandchild.name, "column": column, "base": family.child.name})
        body = response.get_json()
        assert response.status_code == 200 and body["success"], body

        expected = reference.column_drift(family.child, family.grandchild, column, kind)
        assert_drift_matches(body["distortion"], expected, (column, "from the child"))
        assert body["cells_changed"] == reference.cells_changed(family.child, family.grandchild, column)


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_the_sankey_keeps_what_the_panel_asks_for(make_root, client, seed):
    """keep names categories to draw as themselves; whatever else there is folds into (other)."""
    dataset = generators.make_dataset(seed, personalities=["many_categories"], column_count=1,
                                      row_count=max(200, generators.row_count_for(seed)))
    root = make_root(dataset, ingest="direct")
    column = root.data_columns[0]
    response = client.post("/api/wrangle/create-previews", json={"row_ids": root.ids[:30], "cols": [column]})
    node = response.get_json()["candidates"][0]["table"]

    labels = sorted({reference.label_of(value) for value in root.values(column)})
    keep = labels[-3:]
    body = client.get("/api/pgraph/drift_detail",
                      query_string=[("node", node), ("column", column)] + [("keep", label) for label in keep]).get_json()

    assert body["success"], body
    named = set(body["flows"]["sources"]) - {reference.OTHER_LABEL}
    assert named == set(keep)


def test_the_answer_keys_wasserstein_is_scipys():
    """A guard on the answer key itself: the distance it scales is scipy's, on a case worked by hand."""
    assert math.isclose(reference.wasserstein_distance([0, 1, 3], [5, 6, 8]), 5.0)
