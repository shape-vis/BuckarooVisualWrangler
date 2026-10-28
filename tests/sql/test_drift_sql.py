"""
The drift metric's statistics, measured inside Postgres by DriftSQL (app/db_utils/drift_sql.py) and packaged by
app/pgraph/distortion.py.

These are the pandas metric's cases - formerly in tests/unit/test_distortion.py and test_distortion_fixtures.py - held
against the SQL one, with the same expected values. Each state is stored as a table, as a node's is. The arithmetic
on the measurements - summaries, Pareto, annotations, flow folding, ridgelines - stays in tests/unit/test_distortion.py.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text as sa_text

from app import engine
from app.db_utils.column_types import ColumnTypes
from app.db_utils.drift_sql import DriftSQL
from app.db_utils.execute_sql import copy_insert
from app.pgraph.distortion import (CATEGORICAL, NULL_LABEL, NUMERIC, OTHER_LABEL, REMOVED_LABEL, RowIdentityError, TAIL_GRID,
                                   categorical_column_detail, category_flows, check_row_identity, column_distortion,
                                   compute_node_distortion, drift_detail, edit_facts, measure_column, measure_columns,
                                   measure_edit_facts, node_density, node_distortion, numeric_column_detail,
                                   root_density_params, root_distortion)
from app.pgraph.node import GraphNode
from app.pgraph.pgraph import PGraph
from app.server_utils.service_helpers import get_sqlalchemy_dtype_map
from app.server_utils.set_id_column import set_id_column

ROOT = "t_drift_root"
NODE = "t_drift_node"

SURVEY = Path(__file__).resolve().parents[2] / "provided_datasets" / "stackoverflow_db_uncleaned.csv"


def _drop(*tables):
    with engine.begin() as conn:
        for table in tables:
            conn.execute(sa_text(f'DROP TABLE IF EXISTS "{table}"'))
            ColumnTypes.forget(table)


@pytest.fixture
def store():
    """
    Store frames as tables, dropping them all afterwards.
    :return: a function of (table, frame) that stores the frame under that name
    """
    stored = []

    def put(table, frame, dtype=None):
        frame.to_sql(table, engine, if_exists="replace", index=False, dtype=dtype, method=copy_insert)
        ColumnTypes.forget(table)
        stored.append(table)

    yield put
    _drop(*stored)


def _with_ids(values):
    return pd.DataFrame({"ID": list(range(1, len(values) + 1)), "v": pd.Series(values, dtype=object)})


@pytest.fixture
def measure(store):
    """
    Measure one column's drift between two lists of values, root's and the node's.
    :return: a function of (root values, node values, kind) giving column_distortion's result
    """
    def run(root_values, node_values, kind):
        store(ROOT, _with_ids(root_values))
        store(NODE, _with_ids(node_values))
        drift = DriftSQL(engine, ROOT, NODE, {"v": kind})
        return column_distortion(measure_column(drift, "v", kind), kind)

    return run


# ── Numeric: W1 over root's IQR ──────────────────────────────────────────────

@pytest.mark.sql
def test_identical_numeric_column_scores_zero(measure):
    assert measure([1.0, 2.0, 3.0, 4.0, 5.0], [1.0, 2.0, 3.0, 4.0, 5.0], NUMERIC)["value"] == 0.0


@pytest.mark.sql
def test_shift_is_measured_in_root_iqrs(measure):
    # Root's IQR is 3 - 1 = 2, and every value moved up by 1
    result = measure([0, 1, 2, 3, 4], [1, 2, 3, 4, 5], NUMERIC)

    assert result["value"] == pytest.approx(0.5)
    assert result["stat"] == "W1/IQR"


@pytest.mark.sql
def test_unequal_sizes(measure):
    # Worked by hand over the two quantile functions, which step at fifths and at thirds: W1 = 1
    assert measure([0, 1, 2, 3, 4], [0, 1, 2], NUMERIC)["value"] == pytest.approx(0.5)


@pytest.mark.sql
def test_nulls_are_left_out_and_imputation_registers(measure):
    root = [1.0, 2.0, 3.0, 4.0, None]

    assert measure(root, root, NUMERIC)["value"] == 0.0
    assert measure(root, [1.0, 2.0, 3.0, 4.0, 2.5], NUMERIC)["value"] > 0.0


@pytest.mark.sql
def test_text_in_a_numeric_column_is_ignored(measure):
    root = ["1", "2", "3", "4", "oops"]

    assert measure(root, root, NUMERIC)["value"] == 0.0


@pytest.mark.sql
def test_no_iqr_falls_back_to_the_standard_deviation(measure):
    # The middle half is all 5s; the standard deviation is sqrt(12.5)
    result = measure([0, 5, 5, 5, 10], [1, 6, 6, 6, 11], NUMERIC)

    assert result["value"] == pytest.approx(1 / np.sqrt(12.5))


@pytest.mark.sql
def test_constant_column_has_no_value_rather_than_zero(measure):
    result = measure([5, 5, 5], [5, 5], NUMERIC)

    assert result["degenerate"]
    assert result["value"] is None
    assert result["reason"] == "constant column"


@pytest.mark.sql
def test_an_emptied_column_has_no_value_rather_than_zero(measure):
    result = measure([1, 2, 3], [None, None], NUMERIC)

    assert result["value"] is None
    assert result["reason"] == "no values"


@pytest.mark.sql
def test_small_columns_are_low_confidence(measure):
    assert measure([1, 2, 3], [1, 2], NUMERIC)["low_confidence"]
    big = list(range(40))
    assert not measure(big, big, NUMERIC)["low_confidence"]


# ── Categorical: TVD ─────────────────────────────────────────────────────────

@pytest.mark.sql
def test_identical_categorical_column_scores_zero(measure):
    assert measure(["a", "b", "b"], ["a", "b", "b"], CATEGORICAL)["value"] == 0.0


@pytest.mark.sql
def test_disjoint_columns_score_one(measure):
    result = measure(["a", "a", "b"], ["c", "d"], CATEGORICAL)

    assert result["value"] == pytest.approx(1.0)
    assert result["stat"] == "TVD"


@pytest.mark.sql
def test_moved_mass_is_counted_once(measure):
    # a goes from half to three quarters and b the other way: 0.25 of the mass moved, not 0.5
    assert measure(["a", "a", "b", "b"], ["a", "a", "a", "b"], CATEGORICAL)["value"] == pytest.approx(0.25)


@pytest.mark.sql
def test_missing_cells_are_one_category(measure):
    # A node identical to root scores zero, and every spelling of missing is the same category
    values = ["a", "b", None, "null", "undefined"]

    assert measure(values, values, CATEGORICAL)["value"] == 0.0
    assert measure(values, ["a", "b", None, None, None], CATEGORICAL)["value"] == 0.0


@pytest.mark.sql
def test_imputation_registers_in_full(measure):
    # Root is a quarter a, a quarter b and half null; filling both gaps with a moves that half to a
    assert measure(["a", "b", None, None], ["a", "b", "a", "a"], CATEGORICAL)["value"] == pytest.approx(0.5)


@pytest.mark.sql
def test_deleting_the_missing_rows_registers(measure):
    # Null's half of root is gone, and a and b take a half each instead of a quarter
    assert measure(["a", "b", None, None], ["a", "b"], CATEGORICAL)["value"] == pytest.approx(0.5)


@pytest.mark.sql
def test_an_all_missing_column_still_has_a_value(measure):
    result = measure([None, None], [None], CATEGORICAL)

    assert result["value"] == 0.0
    assert not result["degenerate"]


# ── One node ─────────────────────────────────────────────────────────────────

ROOT_FRAME = pd.DataFrame({"ID": [1, 2, 3, 4, 5, 6], "num": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], "cat": list("aabbcc")})
KINDS = {"num": NUMERIC, "cat": CATEGORICAL}


def _node_drift(store, node_frame, root_frame=ROOT_FRAME):
    store(ROOT, root_frame)
    store(NODE, node_frame)
    return DriftSQL(engine, ROOT, NODE, KINDS)


@pytest.mark.sql
def test_node_identical_to_root_scores_zero_everywhere(store):
    result = node_distortion(measure_columns(_node_drift(store, ROOT_FRAME)))

    assert result["overall"] == 0.0
    assert {column: r["value"] for column, r in result["columns"].items()} == {"num": 0.0, "cat": 0.0}


@pytest.mark.sql
def test_root_short_circuits_to_zero(store):
    store(ROOT, ROOT_FRAME)
    present_cells = DriftSQL(engine, ROOT, ROOT, KINDS).generate_present_cells("reference")

    result = root_distortion(KINDS, present_cells, len(ROOT_FRAME))

    assert result["overall"] == 0.0
    assert not any(r["degenerate"] for r in result["columns"].values())


@pytest.mark.sql
def test_a_row_root_does_not_have_raises(store):
    grown = pd.concat([ROOT_FRAME, pd.DataFrame({"ID": [7], "num": [7.0], "cat": ["c"]})])
    facts = measure_edit_facts(_node_drift(store, grown), list(KINDS))

    with pytest.raises(RowIdentityError, match="1 row"):
        check_row_identity(facts)


@pytest.mark.sql
def test_dropped_and_added_columns_are_structural_not_scored(store):
    node = ROOT_FRAME.drop(columns="cat").assign(extra=1)

    result = node_distortion(measure_columns(_node_drift(store, node)))

    assert result["columns"]["cat"]["reason"] == "column removed"
    assert result["columns"]["extra"]["reason"] == "column added"
    assert result["structural"] == {"removed": ["cat"], "added": ["extra"]}
    assert result["overall"] == result["columns"]["num"]["value"]


@pytest.mark.sql
def test_row_identifiers_are_not_scored(store):
    with_index = ROOT_FRAME.assign(index=range(6))

    result = node_distortion(measure_columns(_node_drift(store, with_index, root_frame=with_index)))

    assert "index" not in result["columns"]
    assert "ID" not in result["columns"]


@pytest.mark.sql
def test_edit_facts_count_removed_rows_and_changed_cells(store):
    node = ROOT_FRAME[ROOT_FRAME["ID"] != 6].copy()
    node.loc[node["ID"] == 1, "cat"] = "b"

    facts = edit_facts(measure_edit_facts(_node_drift(store, node), list(KINDS)))

    assert facts["rows_root"] == 6
    assert facts["rows_removed"] == 1
    assert facts["cells_changed"] == {"num": 0, "cat": 1}


@pytest.mark.sql
def test_numbers_that_only_change_spelling_are_not_changes(store):
    root = pd.DataFrame({"ID": [1, 2], "v": ["3", "x"]})
    node = pd.DataFrame({"ID": [1, 2], "v": ["3.0", "y"]})
    store(ROOT, root)
    store(NODE, node)

    facts = measure_edit_facts(DriftSQL(engine, ROOT, NODE, {"v": CATEGORICAL}), ["v"])

    assert facts["cells_changed"] == {"v": 1}


# ── Detail: what the drill-down views draw ───────────────────────────────────

@pytest.mark.sql
def test_shift_is_read_on_the_grid_in_root_iqrs(store):
    store(ROOT, _with_ids(list(range(101))))
    store(NODE, _with_ids([value + 10 for value in range(101)]))

    detail = numeric_column_detail(DriftSQL(engine, ROOT, NODE, {"v": NUMERIC}).generate_numeric_detail("v", TAIL_GRID))

    # Root's IQR is 50, and every quantile moved up by 10
    np.testing.assert_allclose(detail["shift"], [0.2] * len(detail["grid"]))


@pytest.mark.sql
def test_mean_shift_on_a_fine_grid_matches_the_number(store):
    root = np.random.default_rng(0).normal(0, 1, 2000)
    store(ROOT, _with_ids(list(root)))
    store(NODE, _with_ids(list(root * 1.1 + 0.2)))
    drift = DriftSQL(engine, ROOT, NODE, {"v": NUMERIC})
    fine = tuple(np.linspace(0.001, 0.999, 999))

    detail = numeric_column_detail(drift.generate_numeric_detail("v", fine), grid=fine)
    value = column_distortion(measure_column(drift, "v", NUMERIC), NUMERIC)["value"]

    assert np.mean(np.abs(detail["shift"])) == pytest.approx(value, abs=0.1 * value)


@pytest.mark.sql
def test_categories_that_moved_most_are_named_and_the_rest_summed(store):
    root = []
    node = []
    for i in range(10):
        root += [f"c{i}"] * 10
        node += [f"c{i}"] * (10 + i)
    store(ROOT, _with_ids(root))
    store(NODE, _with_ids(node))

    detail = categorical_column_detail(DriftSQL(engine, ROOT, NODE, {"v": CATEGORICAL}).generate_category_shares("v"))
    rows = detail["categories"]

    assert len(rows) == 9
    assert detail["truncated_n"] == 2
    assert rows[-1]["category"] == OTHER_LABEL
    assert rows[0]["category"] == "c0"
    # Shares always sum to 100, so the changes sum to zero across every row, the summed one included
    assert sum(row["change_pct"] for row in rows) == pytest.approx(0.0)


# ── Flows ────────────────────────────────────────────────────────────────────

def _flows(store, root_frame, node_frame, column="g"):
    store(ROOT, root_frame)
    store(NODE, node_frame)
    drift = DriftSQL(engine, ROOT, NODE, {column: CATEGORICAL})
    return drift, category_flows(drift.generate_category_flows(column))


@pytest.mark.sql
def test_a_swap_leaves_tvd_at_zero_but_churn_counts_it(store):
    drift, flows = _flows(store, pd.DataFrame({"ID": [1, 2, 3, 4], "g": ["a", "a", "b", "b"]}),
                          pd.DataFrame({"ID": [1, 2, 3, 4], "g": ["b", "a", "a", "b"]}))

    assert column_distortion(drift.generate_categorical_drift("g"), CATEGORICAL)["value"] == 0.0
    assert flows["churn"] == pytest.approx(0.5)


@pytest.mark.sql
def test_deleted_rows_go_to_the_removed_sink(store):
    _, flows = _flows(store, pd.DataFrame({"ID": [1, 2, 3], "g": ["a", "a", "b"]}),
                      pd.DataFrame({"ID": [1, 2], "g": ["a", "a"]}))

    assert {"source": "b", "target": REMOVED_LABEL, "rows": 1} in flows["flows"]
    assert flows["targets"][-1] == REMOVED_LABEL
    assert flows["removal_rates"] == {"a": 0.0, "b": 1.0}
    assert flows["churn"] == pytest.approx(1 / 3)


@pytest.mark.sql
def test_flows_name_missing_cells_as_tvd_does(store):
    # Every spelling of missing is the null category, on both sides of the Sankey as in TVD, so a node identical to
    # root moves no row
    values = ["a", None, "null", "undefined"]
    drift, flows = _flows(store, pd.DataFrame({"ID": [1, 2, 3, 4], "g": values}),
                          pd.DataFrame({"ID": [1, 2, 3, 4], "g": values}))

    assert column_distortion(drift.generate_categorical_drift("g"), CATEGORICAL)["value"] == 0.0
    assert flows["churn"] == 0.0
    assert {"source": NULL_LABEL, "target": NULL_LABEL, "rows": 3} in flows["flows"]


@pytest.mark.sql
def test_flows_between_two_nodes_read_from_the_first(store):
    """Flows between any two states: the first is the source side, and its deletes are the sink."""
    _, flows = _flows(store, pd.DataFrame({"ID": [1, 2, 3, 4], "g": ["a", "a", "b", "b"]}),
                      pd.DataFrame({"ID": [1, 2, 3], "g": ["a", "b", "b"]}))

    assert {"source": "a", "target": "b", "rows": 1} in flows["flows"]
    assert {"source": "b", "target": REMOVED_LABEL, "rows": 1} in flows["flows"]
    assert flows["churn"] == pytest.approx(0.5)


# ── Drift from an ancestor ───────────────────────────────────────────────────

ANCESTOR_TABLES = {"root": "t_drift_anc_root", "mid": "t_drift_anc_mid", "left": "t_drift_anc_left",
                   "right": "t_drift_anc_right"}


@pytest.fixture
def ancestry(store):
    """
    drift_detail measured from a common ancestor rather than root, on a graph held in memory over stored tables:

        root ── mid (deletes 7, 8 on num) ─┬─ left  (deletes 1 on cat)
                                           └─ right (deletes 3, 4 on cat)
    """
    root = pd.DataFrame({"ID": list(range(1, 9)), "num": [float(i) for i in range(1, 9)], "cat": list("aabbccdd")})
    mid = root[root["ID"] <= 6]
    frames = {"root": root, "mid": mid, "left": mid[mid["ID"] != 1], "right": mid[~mid["ID"].isin([3, 4])]}
    for name, frame in frames.items():
        store(ANCESTOR_TABLES[name], frame)

    names = ANCESTOR_TABLES
    graph = PGraph()
    graph.add_root_node(GraphNode("root", "root", names["root"], f"errors_{names['root']}"))
    for name, parent, column in (("mid", "root", "num"), ("left", "mid", "cat"), ("right", "mid", "cat")):
        table = names[name]
        graph.add_node(GraphNode(names[parent], "delete", table, f"errors_{table}", [column]))

    # Root first, which decides the kinds every other node is measured with
    for name in ("root", "mid", "left", "right"):
        table = names[name]
        graph.node_map[table].set_distortion(compute_node_distortion(table, names["root"]))

    return graph, names


@pytest.mark.sql
def test_without_a_base_it_is_measured_from_root(ancestry):
    graph, names = ancestry

    detail = drift_detail(graph, names["left"], "cat")

    assert detail["base"] == names["root"]
    assert detail["distortion"] == graph.node_map[names["left"]].distortion["columns"]["cat"]
    assert detail["rows_root"] == 8
    assert detail["rows_removed"] == 3


@pytest.mark.sql
def test_from_an_ancestor_it_is_as_if_that_ancestor_were_root(ancestry):
    graph, names = ancestry
    from_mid = DriftSQL(engine, names["mid"], names["left"], {"cat": CATEGORICAL})

    detail = drift_detail(graph, names["left"], "cat", base_table=names["mid"])

    assert detail["base"] == names["mid"]
    assert detail["distortion"]["value"] == column_distortion(from_mid.generate_categorical_drift("cat"), CATEGORICAL)["value"]
    assert detail["flows"] == category_flows(from_mid.generate_category_flows("cat"))
    # Only the row deleted below mid is counted, out of mid's rows
    assert detail["rows_root"] == 6
    assert detail["rows_removed"] == 1


@pytest.mark.sql
def test_a_numeric_column_is_smoothed_on_the_ancestor(ancestry):
    graph, names = ancestry
    from_mid = DriftSQL(engine, names["mid"], names["right"], {"num": NUMERIC})

    detail = drift_detail(graph, names["right"], "num", base_table=names["mid"])

    params = root_density_params(from_mid.generate_value_masses("reference", "num"))
    assert detail["density"]["grid"] == params["grid"]
    assert detail["density"]["root"] == params["root_curve"]
    assert detail["density"]["node"] == node_density(from_mid.generate_value_masses("node", "num"), params)


@pytest.mark.sql
def test_only_the_steps_below_the_ancestor_count_as_acting_on_a_column(ancestry):
    graph, names = ancestry

    # mid's delete acted on num, but it is above the ancestor, so from there num only lost rows to cat's
    from_root = drift_detail(graph, names["left"], "num")["annotation"]["record"]
    from_mid = drift_detail(graph, names["left"], "num", base_table=names["mid"])["annotation"]["record"]

    assert from_root["acted_on"]
    assert not from_mid["acted_on"]


@pytest.mark.sql
def test_the_ancestor_against_itself_has_not_drifted(ancestry):
    graph, names = ancestry

    detail = drift_detail(graph, names["mid"], "num", base_table=names["mid"])

    assert detail["distortion"]["value"] == 0.0
    assert detail["rows_removed"] == 0


# ── Doc 02's validation fixtures ─────────────────────────────────────────────
# Reproduced from the prototype's own row selection: the node that dropped every row whose ConvertedSalary the
# prototype (variants.py) called bad - missing, exactly zero, or outside 3x-IQR Tukey fences - 26 of the survey's 400
# rows. Buckaroo's detectors pick a different 20 (tests/sql/test_distortion_survey.py covers that node), so the
# selection is rebuilt here and the metric is held to the fixtures at the precision 02 states them.

FIXTURE_KINDS = {"ConvertedSalary": NUMERIC, "Age": CATEGORICAL, "Gender": CATEGORICAL, "Continent": CATEGORICAL,
                 "Country": CATEGORICAL, "DevType": CATEGORICAL, "YearsCoding": CATEGORICAL}

NON_BINARY = "Non-binary, genderqueer, or gender non-conforming"
MALE_NON_BINARY = "Male;Non-binary, genderqueer, or gender non-conforming"

FIXTURE_ROOT = "t_drift_doc02_root"
FIXTURE_NODE = "t_drift_doc02_n1"


def prototype_n1(root):
    """variants.v1_listwise: drop every row with a bad salary cell."""
    salary = root["ConvertedSalary"]
    q1, q3 = salary.dropna().quantile([0.25, 0.75])
    iqr = q3 - q1
    bad = salary.isna() | (salary == 0) | (salary < q1 - 3 * iqr) | (salary > q3 + 3 * iqr)
    return root[~bad]


@pytest.fixture(scope="module")
def doc02():
    root = set_id_column(pd.read_csv(SURVEY))
    n1 = prototype_n1(root)
    dtype = get_sqlalchemy_dtype_map(root)
    for table, frame in ((FIXTURE_ROOT, root), (FIXTURE_NODE, n1)):
        frame.to_sql(table, engine, if_exists="replace", index=False, dtype=dtype, method=copy_insert)
        ColumnTypes.forget(table)

    yield n1, DriftSQL(engine, FIXTURE_ROOT, FIXTURE_NODE, FIXTURE_KINDS)

    _drop(FIXTURE_ROOT, FIXTURE_NODE)


@pytest.mark.sql
def test_the_selection_drops_26_rows(doc02):
    n1, _ = doc02

    assert len(n1) == 374


@pytest.mark.sql
def test_per_column_drift(doc02):
    _, drift = doc02
    expected = {"ConvertedSalary": 0.7719, "Country": 0.0209, "YearsCoding": 0.0151, "DevType": 0.0149,
                "Continent": 0.0133, "Gender": 0.0105, "Age": 0.0101}

    measured = {}
    for column_drift in measure_columns(drift):
        measured[column_drift["column"]] = column_drift

    for column, value in expected.items():
        result = column_distortion(measured[column], FIXTURE_KINDS[column])
        # Equal to the four places 02 states them to
        assert round(result["value"] - value, 4) == 0, column


@pytest.mark.sql
def test_node_number(doc02):
    _, drift = doc02

    assert node_distortion(measure_columns(drift))["overall"] == pytest.approx(0.1224, abs=5e-5)


@pytest.mark.sql
def test_salary_shift_at_the_90th_percentile(doc02):
    _, drift = doc02

    detail = numeric_column_detail(drift.generate_numeric_detail("ConvertedSalary", TAIL_GRID))

    assert detail["shift"][detail["grid"].index(0.90)] == pytest.approx(-0.160, abs=5e-4)


@pytest.mark.sql
def test_gender_share_changes(doc02):
    _, drift = doc02

    detail = categorical_column_detail(drift.generate_category_shares("Gender"))
    change = {row["category"]: row["change_pct"] for row in detail["categories"]}

    for category, value in {"Male": 0.94, "Female": -0.55, NON_BINARY: -0.25, MALE_NON_BINARY: -0.25,
                            "Transgender": 0.03}.items():
        assert change[category] == pytest.approx(value, abs=5e-3), category


@pytest.mark.sql
def test_gender_flows(doc02):
    _, drift = doc02

    flows = category_flows(drift.generate_category_flows("Gender"), limit=10)
    rows = {(flow["source"], flow["target"]): flow["rows"] for flow in flows["flows"]}

    assert rows[("Male", "Male")] == 342
    assert rows[("Male", REMOVED_LABEL)] == 20
    assert rows[("Female", "Female")] == 26
    assert rows[("Female", REMOVED_LABEL)] == 4
    assert rows[("Transgender", "Transgender")] == 2
    assert rows[("UNKNOWN", "UNKNOWN")] == 2
    assert rows[(NON_BINARY, REMOVED_LABEL)] == 1
    assert rows[(MALE_NON_BINARY, REMOVED_LABEL)] == 1
    assert flows["churn"] == pytest.approx(0.065)
