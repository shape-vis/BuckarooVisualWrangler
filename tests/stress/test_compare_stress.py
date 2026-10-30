"""
The compare panel's plots (app/db_utils/compare_sql.py, through /api/pgraph/compare) over generated graphs: both
nodes binned on shared axes, held bin for bin to the answer key, for every pair a user can compare - a node with its
parent, siblings, a node with itself, root with a grandchild and back.
"""
import random

import pytest

from tests.stress import reference
from tests.stress.conftest import seeds
from tests.stress.family import build_family

BIN_COUNTS = (1, 4, 10, 50)


def get_compare(client, a, b, kind, x, y=None, bins=10):
    params = {"a": a, "b": b, "kind": kind, "x": x, "bins": bins}
    if y is not None:
        params["y"] = y
    response = client.get("/api/pgraph/compare", query_string=params)
    body = response.get_json()
    assert response.status_code == 200 and body.get("success"), body
    return body


def bin_key(entry_type, entry_bin):
    if entry_type == "numeric":
        return ("numeric", int(entry_bin))
    return ("categorical", entry_bin)


def drawn_sides(entries, axes):
    """The payload's bins as {side: {key tuple: counts}}, empty bins left out as the answer key leaves them."""
    sides = {"a": {}, "b": {}}
    seen = set()
    for entry in entries:
        key = []
        for axis in axes:
            key.append(bin_key(entry[f"{axis}Type"], entry[f"{axis}Bin"]))
        key = tuple(key)
        assert key not in seen, f"bin {key} listed twice"
        seen.add(key)
        for side in ("a", "b"):
            counts = entry[side]
            for error_type in reference.ERROR_TYPES:
                assert counts.get(error_type, 0) <= counts["items"]
            if counts["items"]:
                sides[side][key] = counts
    return sides


def assert_axis_matches(scale, axis):
    assert scale["categorical"] == axis.labels_in_order
    if axis.is_numeric:
        assert len(scale["numeric"]) == axis.bins
        for n, edge in enumerate(scale["numeric"]):
            assert edge["x0"] == pytest.approx(axis.lo + n * axis.width, rel=1e-12, abs=1e-12)
            assert edge["x1"] == pytest.approx(axis.lo + (n + 1) * axis.width, rel=1e-12, abs=1e-12)
    else:
        assert scale["numeric"] == []


def assert_comparison_matches(payload, expected, axes):
    assert payload["rows"] == expected.rows
    entries = payload.get("bins") or payload.get("tiles") or []
    drawn = drawn_sides(entries, axes)

    for side in ("a", "b"):
        total = 0
        for counts in drawn[side].values():
            total += counts["items"]
        assert total == expected.rows[side], f"side {side}'s bins do not add up to its rows"

        if expected.borderline_rows[side]:
            continue
        assert drawn[side] == expected.sides[side], f"side {side}"


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_compare_histograms_match_the_answer_key(make_root, client, seed):
    family = build_family(make_root, client, seed)
    flags = {}
    for table in (family.root, family.child, family.sibling, family.grandchild):
        flags[table.name] = reference.detect(table)
    bin_count = BIN_COUNTS[seed % len(BIN_COUNTS)]

    for name, (table_a, table_b) in family.pairs().items():
        for column in table_a.data_columns:
            payload = get_compare(client, table_a.name, table_b.name, "histogram", column, bins=bin_count)
            expected = reference.compare(table_a, flags[table_a.name], table_b, flags[table_b.name], [column],
                                         bin_count)
            assert_axis_matches(payload["scaleX"], expected.axes[0])
            assert_comparison_matches(payload, expected, ["x"])

            # Every bin on the axis is listed, empty ones included, so a difference plot has its zeros
            listed = len(payload["bins"])
            assert listed == expected.axes[0].bins + len(expected.axes[0].labels_in_order), (name, column)


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_compare_heatmaps_match_the_answer_key(make_root, client, seed):
    rng = random.Random(seed)
    family = build_family(make_root, client, seed)
    flags = {}
    for table in (family.root, family.child, family.sibling, family.grandchild):
        flags[table.name] = reference.detect(table)

    for name, (table_a, table_b) in family.pairs().items():
        x_column = rng.choice(table_a.data_columns)
        y_column = rng.choice(table_a.data_columns)
        bin_count = rng.choice(BIN_COUNTS)
        payload = get_compare(client, table_a.name, table_b.name, "heatmap", x_column, y_column, bin_count)
        expected = reference.compare(table_a, flags[table_a.name], table_b, flags[table_b.name],
                                     [x_column, y_column], bin_count)
        assert_axis_matches(payload["scaleX"], expected.axes[0])
        assert_axis_matches(payload["scaleY"], expected.axes[1])
        assert_comparison_matches(payload, expected, ["x", "y"])
