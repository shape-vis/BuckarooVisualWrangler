"""
Distortion measured through Buckaroo's own process, on the StackOverflow survey.

tests/unit/test_distortion_fixtures.py holds the metric to doc 02's numbers, but those came from a node
Buckaroo cannot produce: the prototype called 26 salaries bad by rules of its own. This builds nodes the way a
user would. The survey is uploaded through load_file, so the real detectors flag it, and every wrangle goes
through ai_wrangle.apply_suggestion - its rows come from the errors table and its change goes through
preview and promote. Drift is then read back through the graph payload and the drift routes.

    root ─┬─ delete ConvertedSalary anomalies ── delete ConvertedSalary missing    20 rows gone
          ├─ impute ConvertedSalary missing                                        6 cells filled
          └─ delete Gender incomplete                                              rows gone, acting on Gender
"""
import json
from pathlib import Path

import pytest
from sqlalchemy import text as sa_text

import app
from app import engine
from app.pgraph.compare import load_node_data
from app.pgraph.distortion import REMOVED_LABEL, SKIPPED_COLUMNS
from app.routes.routes import load_file
from app.server_utils import ai_wrangle as aw

SURVEY = Path(__file__).resolve().parents[2] / "provided_datasets" / "stackoverflow_db_uncleaned.csv"


def build_survey_graph():
    """
    Upload the survey and make the wrangles drawn above.
    :return: {name: node table}
    """
    upload = load_file(str(SURVEY), "distortion_survey.csv")
    assert upload["success"], upload
    root = upload["table_name"]
    columns = [column for column in load_node_data(engine, root).columns if column not in SKIPPED_COLUMNS]

    def wrangle(node, **raw):
        result = aw.apply_suggestion(node, raw, columns)
        assert result["success"], result
        return result["table"]

    anomalies = wrangle(root, op="delete_rows", column="ConvertedSalary", error_type="anomaly")
    return {
        "root": root,
        "anomalies": anomalies,
        "clean": wrangle(anomalies, op="delete_rows", column="ConvertedSalary", error_type="missing"),
        "impute": wrangle(root, op="impute_rows", column="ConvertedSalary", error_type="missing"),
        "gender": wrangle(root, op="delete_rows", column="Gender", error_type="incomplete"),
    }


def drop_survey_graph(nodes):
    with engine.begin() as conn:
        for table in nodes.values():
            for name in (table, f"errors_{table}", f"dp_{table}", f"rankings_{table}", f"{table}_filtering"):
                conn.execute(sa_text(f'DROP TABLE IF EXISTS "{name}"'))
    app.pgraph_for_session = None


@pytest.fixture(scope="module")
def survey():
    nodes = build_survey_graph()
    yield nodes
    drop_survey_graph(nodes)


@pytest.fixture
def client():
    return app.app.test_client()


def _graph(client):
    # The graph route returns a JSON string it built itself, so it arrives as text
    return json.loads(client.get("/api/routes/update_pgraph").get_data(as_text=True))


def _drift(graph, table):
    return next(node for node in graph["nodes"] if node["id"] == table)["data"]["distortion"]


def _get(client, route, **params):
    response = client.get(route, query_string=params)
    return response.status_code, response.get_json()


@pytest.mark.sql
def test_root_has_no_drift(survey, client):
    drift = _drift(_graph(client), survey["root"])

    assert drift["overall"] == 0.0
    assert all(column["value"] == 0.0 for column in drift["columns"].values())


@pytest.mark.sql
def test_the_facts_follow_the_wrangles(survey, client):
    graph = _graph(client)
    clean, impute = _drift(graph, survey["clean"]), _drift(graph, survey["impute"])

    assert clean["facts"]["rows_removed"] == 20
    assert not any(clean["facts"]["cells_changed"].values())
    assert impute["facts"]["rows_removed"] == 0
    assert impute["facts"]["cells_changed"]["ConvertedSalary"] == 6
    assert impute["columns"]["ConvertedSalary"]["value"] > 0


@pytest.mark.sql
def test_only_leaves_are_ranked(survey, client):
    pareto = _graph(client)["pareto"]

    assert set(pareto["scored"]) == {survey["clean"], survey["impute"], survey["gender"]}


@pytest.mark.sql
def test_the_null_test_flags_gender_and_not_the_larger_raw_drifts(survey, client):
    """The README's key test, on the node Buckaroo's own detectors produce."""
    status, body = _get(client, "/api/pgraph/drift_null", node=survey["clean"],
                        columns=["Gender", "Country", "DevType", "YearsCoding", "Age"])

    assert status == 200, body
    assert body["columns"]["Gender"]["flagged"], body["columns"]["Gender"]
    for column in ["Country", "DevType", "YearsCoding", "Age"]:
        assert not body["columns"][column]["flagged"], (column, body["columns"][column])


@pytest.mark.sql
def test_an_imputed_node_is_not_null_tested(survey, client):
    _, body = _get(client, "/api/pgraph/drift_null", node=survey["impute"])

    assert not any(result["applicable"] for result in body["columns"].values())


@pytest.mark.sql
def test_trajectory_deltas_are_differences_of_root_referenced_values(survey, client):
    _, body = _get(client, "/api/pgraph/branch_trajectory", source=survey["root"],
                   target=survey["anomalies"], destination=survey["clean"])
    drift = body["distortion"]

    assert drift["values"][0] == 0.0
    assert drift["deltas"] == pytest.approx([b - a for a, b in zip(drift["values"], drift["values"][1:])])


@pytest.mark.sql
def test_numeric_detail_carries_the_shift_and_the_ridgeline(survey, client):
    status, body = _get(client, "/api/pgraph/drift_detail", node=survey["clean"], column="ConvertedSalary")

    assert status == 200, body
    assert len(body["detail"]["shift"]) == len(body["detail"]["grid"])
    assert body["density"]["bandwidth"] > 0
    assert len(body["density"]["node"]) == len(body["density"]["root"])
    assert body["annotation"]["sentences"]


@pytest.mark.sql
def test_collateral_drift_opens_on_the_change_table_and_a_targeted_delete_on_flows(survey, client):
    _, collateral = _get(client, "/api/pgraph/drift_detail", node=survey["clean"], column="Gender")
    _, targeted = _get(client, "/api/pgraph/drift_detail", node=survey["gender"], column="Gender")

    assert collateral["route"] == "change"
    assert targeted["route"] == "flows"
    assert REMOVED_LABEL in collateral["flows"]["targets"]


@pytest.mark.sql
@pytest.mark.parametrize("params, message", [
    ({"column": "ConvertedSalary"}, "missing node"),
    ({"node": "nope", "column": "ConvertedSalary"}, "not a node"),
    ({"node": "<root>", "column": "nope"}, "not a data column"),
    ({"node": "<root>", "column": "ConvertedSalary", "grid": "wobbly"}, "unknown grid"),
])
def test_bad_detail_requests_are_refused(survey, client, params, message):
    # The root's table name is only known once the survey is uploaded
    params = {key: survey["root"] if value == "<root>" else value for key, value in params.items()}
    status, body = _get(client, "/api/pgraph/drift_detail", **params)

    assert status == 400
    assert message in body["error"]


# Frozen on 2026-09-15 after review: what Buckaroo's own detectors and wrangles produce on the survey. These
# are numbers users see, so a change here should be a deliberate one. The node values average all 20 data
# columns, which is why they sit well below doc 02's (it averaged seven hand-picked ones).
GOLDEN_NODES = {"anomalies": 0.0441, "clean": 0.0458, "impute": 0.0012, "gender": 0.0069}
GOLDEN_COLUMNS = {
    "clean": {"ConvertedSalary": 0.7230, "Country": 0.0200, "Continent": 0.0166, "Gender": 0.0089, "Age": 0.0058},
    "impute": {"ConvertedSalary": 0.0243},
    "gender": {"ConvertedSalary": 0.0267, "Gender": 0.0200},
}
# Salary is flagged because the deletes selected on it. Continent, GDP and UndergradMajor are flagged
# because the outliers removed were the highest earners, who cluster by region and country wealth.
GOLDEN_FLAGGED = {"ConvertedSalary", "Continent", "GDP", "Gender", "UndergradMajor"}


@pytest.mark.sql
def test_golden_drift(survey, client):
    graph = _graph(client)

    for name, overall in GOLDEN_NODES.items():
        assert _drift(graph, survey[name])["overall"] == pytest.approx(overall, abs=5e-5), name
    for name, columns in GOLDEN_COLUMNS.items():
        drift = _drift(graph, survey[name])["columns"]
        for column, value in columns.items():
            assert drift[column]["value"] == pytest.approx(value, abs=5e-5), (name, column)


@pytest.mark.sql
def test_golden_null_flags(survey, client):
    _, body = _get(client, "/api/pgraph/drift_null", node=survey["clean"])

    assert {column for column, result in body["columns"].items() if result["flagged"]} == GOLDEN_FLAGGED


@pytest.mark.sql
def test_golden_pareto(survey, client):
    pareto = _graph(client)["pareto"]

    # Each leaf trades error for drift differently, so none is beaten outright
    assert set(pareto["frontier"]) == {survey["clean"], survey["impute"], survey["gender"]}
    assert pareto["dominated"] == {}
