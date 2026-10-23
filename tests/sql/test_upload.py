"""
Uploading a CSV through load_file (app/routes/routes.py): the table it stores, the root it builds - errors, data
profile, metrics and drift, the build every node gets - the session graph it starts, and the attribute summary the
main view opens on.
"""
import pytest

import app
from app import db_operations, engine
from app.db_utils.column_types import ColumnTypes
from app.routes.routes import load_file

# 13 rows: amount holds one far outlier, which the anomaly detector flags, and city one missing cell. city's values
# each occur often enough that none is flagged incomplete.
CSV = "amount,city\n" + "".join(f"{n},{'a' if n <= 7 else 'b'}\n" for n in range(1, 12)) + "1000,a\n13,\n"


@pytest.fixture
def uploaded(tmp_path, session_graph):
    path = tmp_path / "upload_test.csv"
    path.write_text(CSV)
    result = load_file(str(path), "upload_test.csv")
    assert result["success"], result
    return result


@pytest.mark.sql
def test_an_upload_becomes_the_root_and_the_current_table(uploaded):
    table = uploaded["table_name"]

    assert table.startswith("n0a_upload_test_")
    assert app.pgraph_for_session.root_table_name == table
    assert app.pgraph_for_session.current_node_table_name == table
    assert db_operations.main_table_name == table
    assert uploaded["rows for undetected data"] == 13
    # One anomaly and one missing cell
    assert uploaded["rows_for_detected"] == 2


@pytest.mark.sql
def test_an_upload_stores_its_companion_tables(uploaded):
    table = uploaded["table_name"]

    assert db_operations.table_exists(f"errors_{table}")
    assert db_operations.table_exists(f"dp_{table}")


@pytest.mark.sql
def test_an_upload_types_its_columns_from_their_values(uploaded):
    col_types = ColumnTypes.for_table(uploaded["table_name"], engine)

    assert col_types.column_names == ["ID", "amount", "city"]
    assert col_types.is_numeric_col("amount")
    assert col_types.is_categorical_col("city")


@pytest.mark.sql
def test_the_root_is_measured_as_every_node_is(uploaded):
    root = app.pgraph_for_session.node_map[uploaded["table_name"]]

    assert root.metrics.row_count == 13
    assert root.metrics.column_count == 2
    assert root.metrics.columns["amount"]["anomaly"] == pytest.approx(1 / 13)
    assert root.metrics.columns["city"]["missing"] == pytest.approx(1 / 13)

    # Root against itself has drifted nowhere
    assert root.distortion["overall"] == 0.0
    assert root.distortion["columns"]["amount"]["value"] == 0.0
    assert root.distortion["columns"]["city"]["value"] == 0.0
    assert root.distortion["facts"]["rows_removed"] == 0


@pytest.mark.sql
def test_the_attribute_summary_reads_the_uploaded_root(uploaded, client):
    body = client.get("/api/plots/summaries").get_json()
    assert body["success"], body
    summary = body["data"]

    assert summary["attributes"] == ["ID", "amount", "city"]
    assert summary["columnErrors"]["amount"] == {"anomaly": pytest.approx(1 / 13)}
    assert summary["columnErrors"]["city"] == {"missing": pytest.approx(1 / 13)}

    amount = summary["attributeDistributions"]["amount"]["numeric"]
    assert float(amount["min"]) == 1
    assert float(amount["max"]) == 1000
    assert float(amount["mean"]) == pytest.approx((66 + 1000 + 13) / 13)
    city = summary["attributeDistributions"]["city"]["categorical"]
    assert city == {"categories": 2, "mode": "a"}

    # Each column carries one flag, so the tie goes to the name
    assert summary["defaultAttributes"] == ["amount", "city"]
