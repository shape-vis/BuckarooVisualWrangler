"""
Saved comparisons: what Comparison.from_json lets onto the graph, and how the graph keeps them.

The routes are exercised against a real graph in tests/sql/test_node_compare_route.py.
"""
import json

import pytest

import app.pgraph.pgraph as pgraph_module
from app.pgraph.comparison import Comparison, ComparisonError, MAX_CATEGORIES
from app.pgraph.node import GraphNode
from app.pgraph.pgraph import PGraph


@pytest.fixture
def graph():
    graph = PGraph()
    graph.add_root_node(GraphNode("root", "root", "n0a_t", "errors_n0a_t"))
    graph.add_node(GraphNode("n0a_t", "delete", "n0b_t", "errors_n0b_t", ["height"]))
    graph.add_node(GraphNode("n0a_t", "impute", "n0c_t", "errors_n0c_t", ["weight"]))
    return graph


def record(**overrides):
    return {"version": 1, "a": "n0a_t", "b": "n0b_t", "kind": "drift", "x": "region", "view": "flows",
            "measure": "items", "reference": "root", "hidden": ["north"], "kept": ["east"],
            "rankBy": "drift", "errorDelta": "rootB", "zoom": [0.25, 0.75], **overrides}


def test_a_valid_record_round_trips(graph):
    comparison = Comparison.from_json(record(), graph)
    body = comparison.__json__()

    assert body["anchor"] == "n0b_t"   # pinned to selection B when no anchor is named
    assert body["hidden"] == ["north"] and body["kept"] == ["east"]
    assert body["rankBy"] == "drift" and body["errorDelta"] == "rootB"
    assert body["zoom"] == [0.25, 0.75]
    assert body["y"] is None           # only a heatmap keeps a second axis
    assert Comparison.from_json(body, graph).__json__() == body


def test_unknown_keys_and_client_ids_are_ignored(graph):
    comparison = Comparison.from_json(record(id="c99", created_at="yesterday", plot={"bins": []}), graph)

    assert comparison.id is None and comparison.created_at is None
    assert "plot" not in comparison.__json__()


def test_a_heatmap_keeps_its_y_axis(graph):
    comparison = Comparison.from_json(record(kind="heatmap", view="side", y="weight"), graph)
    assert comparison.y == "weight"


@pytest.mark.parametrize("overrides, message", [
    ({"a": "n9z_nope"}, "not a node"),
    ({"anchor": "n9z_nope"}, "not a node"),
    ({"kind": "pie"}, "unknown kind"),
    ({"view": "spiral"}, "unknown view"),
    ({"x": ""}, "x must be"),
    ({"kind": "heatmap", "y": None}, "y must be"),
    ({"hidden": ["c"] * (MAX_CATEGORIES + 1)}, "hidden must be"),
    ({"kept": [1, 2]}, "kept must hold"),
    ({"zoom": [0, "1"]}, "zoom must be"),
    ({"zoom": [0, float("inf")]}, "zoom must be"),
    ({"version": 2}, "unsupported comparison version"),
])
def test_bad_records_are_refused(graph, overrides, message):
    with pytest.raises(ComparisonError, match=message):
        Comparison.from_json(record(**overrides), graph)


def test_the_graph_keeps_them_by_anchor(graph):
    first = graph.add_comparison(Comparison.from_json(record(), graph))
    second = graph.add_comparison(Comparison.from_json(record(b="n0c_t"), graph))

    assert (first.id, second.id) == ("c0", "c1")
    assert graph.comparisons_for("n0b_t") == [first]
    assert graph.comparisons_for() == [first, second]

    payload = json.loads(json.dumps(graph, default=lambda o: o.__json__() if hasattr(o, "__json__") else None))
    assert [c["id"] for c in payload["comparisons"]] == ["c0", "c1"]


def test_an_update_keeps_the_id_and_creation_time(graph):
    saved = graph.add_comparison(Comparison.from_json(record(), graph))
    created = saved.created_at

    updated = graph.update_comparison(saved.id, Comparison.from_json(record(x="height"), graph))

    assert (updated.id, updated.created_at, updated.x) == (saved.id, created, "height")
    assert graph.update_comparison("c42", Comparison.from_json(record(), graph)) is None


def test_ids_are_never_reused(graph):
    saved = graph.add_comparison(Comparison.from_json(record(), graph))
    graph.remove_comparison(saved.id)

    assert graph.add_comparison(Comparison.from_json(record(), graph)).id == "c1"
    assert graph.remove_comparison("c0") is None


def test_the_graph_refuses_past_its_cap(graph, monkeypatch):
    monkeypatch.setattr(pgraph_module, "MAX_COMPARISONS", 1)
    graph.add_comparison(Comparison.from_json(record(), graph))

    with pytest.raises(ValueError, match="at most 1"):
        graph.add_comparison(Comparison.from_json(record(), graph))
