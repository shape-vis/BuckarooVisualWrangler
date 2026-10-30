"""
Bugs the stress tests found, each reproduced on its own - October 28, 2026; fixed October 29, 2026.

Each test states what the app should do, and stays as a regression test now the bug is fixed. A bug found later is
added here as a strict expected failure (pytest.mark.xfail(strict=True, reason="BUG: ...")), with its input kept out
of the random datasets until it is fixed, so one known bug can't hide others. Once it is fixed the strict marker turns
its passing test into a failure, which is the reminder to take the marker off.
"""
import pytest

from tests.stress import generators, reference
from tests.stress.generators import Dataset
from tests.stress.test_detector_stress import assert_flags_match


@pytest.mark.sql
@pytest.mark.parametrize("value", generators.UNICODE_SPACED_NUMBERS)
def test_a_number_padded_with_a_unicode_space_does_not_break_a_build(make_root, value):
    """
    A text cell holding a number with a non-breaking space (or another unicode space) beside it - common in data
    pasted from a spreadsheet or a web page - is read as text, and doesn't crash the detectors. Postgres' \\s used to
    take it for a number, and the ::float8 cast that followed refused it, failing the upload.
    """
    values = ["1", "2", "3", value, "word", "word"]
    dataset = Dataset(seed=0, name="unicode_space", columns={"amount": values},
                      personalities={"amount": "number_lookalikes"})

    root = make_root(dataset, ingest="direct")

    assert_flags_match(root, reference.detect(root))


@pytest.mark.sql
def test_a_category_named_like_the_removed_sink_is_not_counted_as_deleted(make_root, client):
    """
    The Sankey's flows send a deleted row to a target labelled "(removed)". A row whose value is the text "(removed)",
    and is still there, used to land on the same target, so the removed sink counted it as deleted. It is now labelled
    "\"(removed)\"" instead.
    """
    values = ["(removed)"] * 10 + ["kept"] * 10
    dataset = Dataset(seed=0, name="removed_label", columns={"status": values}, personalities={"status": "weird"})
    root = make_root(dataset, ingest="direct")
    # Delete one "kept" row; the ten "(removed)" rows stay
    response = client.post("/api/wrangle/create-previews", json={"row_ids": [20], "cols": ["status"]})
    node = None
    for candidate in response.get_json()["candidates"]:
        if candidate["op"] == "delete":
            node = candidate["table"]

    body = client.get("/api/pgraph/drift_detail", query_string={"node": node, "column": "status"}).get_json()

    removed = 0
    for flow in body["flows"]["flows"]:
        if flow["target"] == reference.REMOVED_LABEL:
            removed += flow["rows"]
    assert removed == 1
    assert body["rows_removed"] == 1


@pytest.mark.sql
def test_a_category_named_like_the_catch_all_keeps_its_own_bin(make_root, client):
    """
    A categorical axis with more than 20 labels folds the rarest into "(other)". A real category spelled "(other)",
    common enough to be kept, used to get the same bin key as the catch-all, so the axis listed "(other)" twice and the
    rows were drawn twice. It is now labelled "\"(other)\"", a bin of its own.
    """
    values = ["(other)"] * 50
    for index in range(30):
        values.extend([f"label_{index:02d}"] * 2)
    dataset = Dataset(seed=0, name="other_label", columns={"answer": values}, personalities={"answer": "weird"})
    root = make_root(dataset, ingest="direct")

    body = client.get("/api/pgraph/compare", query_string={"a": root.name, "b": root.name, "kind": "histogram",
                                                          "x": "answer"}).get_json()

    total = 0
    labels = []
    for entry in body["bins"]:
        total += entry["a"]["items"]
        labels.append(entry["xBin"])
    assert len(labels) == len(set(labels)), "a bin listed twice"
    assert total == len(values)
