"""
The main view's plots (app/db_utils/db_functions_sql.py, through /api/plots/*) over generated datasets: 1D and 2D
histograms held bin for bin to the answer key, the selection round trips a click on a bar makes (rows-in-bin,
bins-for-rows), and the scatterplot's sample.
"""
import random

import pytest

from tests.stress import generators, reference
from tests.stress.conftest import seeds

BIN_COUNTS = (1, 3, 10, 50)


def get_json(client, path, **params):
    response = client.get(path, query_string=params)
    body = response.get_json()
    assert response.status_code == 200 and body.get("success"), body
    return body


def post_json(client, path, payload):
    response = client.post(path, json=payload)
    body = response.get_json()
    assert response.status_code == 200 and body.get("success"), body
    return body


def drawn_bins(payload, two_d):
    """The payload's bins as {key tuple: {"items", error type...}}."""
    bins = {}
    for entry in payload["histograms"]:
        if two_d:
            key = (str(entry["xBin"]), str(entry["yBin"]))
        else:
            key = (str(entry["xBin"]),)
        assert key not in bins, f"bin {key} listed twice"
        bins[key] = entry["count"]
    return bins


def assert_histogram_matches(payload, expected, two_d):
    drawn = drawn_bins(payload, two_d)

    total = 0
    for counts in drawn.values():
        total += counts["items"]
        for error_type in reference.ERROR_TYPES:
            assert counts.get(error_type, 0) <= counts["items"], "a bin flags more rows than it holds"
    expected_total = 0
    for counts in expected.bins.values():
        expected_total += counts["items"]
    assert total == expected_total, "the bins do not add up to the table's rows"

    if expected.borderline_rows:
        # A row on a bin edge may land either side; the totals above still have to hold
        return
    assert drawn == expected.bins


def assert_scale_matches(payload, expected):
    scale = payload["scaleX"]
    assert scale["categorical"] == expected.labels
    assert len(scale["numeric"]) == len(expected.numeric_edges)
    for edge, (x0, x1) in zip(scale["numeric"], expected.numeric_edges):
        assert edge["x0"] == pytest.approx(x0, rel=1e-12, abs=1e-12)
        assert edge["x1"] == pytest.approx(x1, rel=1e-12, abs=1e-12)


def make(make_root, seed):
    if seed % 2 == 0:
        dataset = generators.make_dataset(seed, personalities=generators.CSV_SAFE)
        return make_root(dataset, ingest="csv")
    return make_root(generators.make_dataset(seed), ingest="direct")


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_one_d_histograms_match_the_answer_key(make_root, client, seed):
    root = make(make_root, seed)
    flags = reference.detect(root)
    bin_count = BIN_COUNTS[seed % len(BIN_COUNTS)]

    for column in root.data_columns:
        payload = get_json(client, "/api/plots/1-d-histogram", column=column, bins=bin_count)["histogram"]
        expected = reference.histogram(root, flags, [column], bin_count)
        assert_histogram_matches(payload, expected, two_d=False)
        assert_scale_matches(payload, expected)


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_two_d_histograms_match_the_answer_key(make_root, client, seed):
    rng = random.Random(seed)
    root = make(make_root, seed)
    flags = reference.detect(root)

    pairs = []
    for x_column in root.data_columns:
        pairs.append((x_column, rng.choice(root.data_columns)))
    for x_column, y_column in pairs:
        bin_count = rng.choice(BIN_COUNTS)
        payload = get_json(client, "/api/plots/2-d-histogram", column_x=x_column, column_y=y_column,
                           x_bins=bin_count, y_bins=bin_count)["histogram"]
        expected = reference.histogram(root, flags, [x_column, y_column], bin_count)
        assert_histogram_matches(payload, expected, two_d=True)


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_a_bar_click_selects_exactly_its_rows_and_back(make_root, client, seed):
    """rows-in-bin gives a bar's rows; bins-for-rows, given those rows, gives that bar back."""
    rng = random.Random(seed)
    root = make(make_root, seed)
    flags = reference.detect(root)
    column = rng.choice(root.data_columns)

    payload = get_json(client, "/api/plots/1-d-histogram", column=column)["histogram"]
    expected = reference.histogram(root, flags, [column])

    for entry in payload["histograms"]:
        bin_value = str(entry["xBin"])
        selected = post_json(client, "/api/plots/rows-in-bin",
                             {"type": "1d", "column": column, "bin": bin_value})["row_ids"]
        assert len(selected) == entry["count"]["items"]
        assert len(set(selected)) == len(selected)

        if not expected.borderline_rows:
            expected_rows = []
            for row_id, key in expected.row_bins.items():
                if key == (bin_value,):
                    expected_rows.append(row_id)
            assert sorted(selected) == sorted(expected_rows)

        bins = post_json(client, "/api/plots/bins-for-rows",
                         {"type": "1d", "column": column, "row_ids": selected})["bins"]
        assert bins == [bin_value]


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_a_tile_click_selects_exactly_its_rows_and_back(make_root, client, seed):
    rng = random.Random(seed)
    root = make(make_root, seed)
    if len(root.data_columns) < 2:
        pytest.skip("needs two columns")
    x_column, y_column = rng.sample(root.data_columns, 2)

    payload = get_json(client, "/api/plots/2-d-histogram", column_x=x_column, column_y=y_column)["histogram"]
    for entry in payload["histograms"]:
        x_bin = str(entry["xBin"])
        y_bin = str(entry["yBin"])
        selected = post_json(client, "/api/plots/rows-in-bin", {"type": "2d", "column_x": x_column,
                                                                "column_y": y_column, "x_bin": x_bin,
                                                                "y_bin": y_bin})["row_ids"]
        assert len(selected) == entry["count"]["items"]

        bins = post_json(client, "/api/plots/bins-for-rows", {"type": "2d", "column_x": x_column,
                                                              "column_y": y_column, "row_ids": selected})["bins"]
        assert bins == [{"xBin": x_bin, "yBin": y_bin}]


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_the_scatterplot_samples_flagged_rows_first_and_reads_values_faithfully(make_root, client, seed):
    rng = random.Random(seed)
    root = make(make_root, seed)
    flags = reference.detect(root)
    x_column = rng.choice(root.data_columns)
    y_column = rng.choice(root.data_columns)
    error_sample = rng.choice([0, 5, 30])
    total_sample = rng.choice([0, 10, 100, 500])

    payload = get_json(client, "/api/plots/scatterplot", x_column=x_column, y_column=y_column,
                       error_sample_count=error_sample, total_sample_count=total_sample)["scatterplot_data"]

    flagged_types = {}
    for row_id, column, error_type in flags.certain | flags.borderline:
        if column in (x_column, y_column):
            flagged_types.setdefault(row_id, set()).add(error_type)
    flagged_rows = set(flagged_types)
    clean_rows = set(root.ids) - flagged_rows

    points = payload["data"]
    ids = []
    for point in points:
        ids.append(point["ID"])
    assert len(ids) == len(set(ids)), "a row sampled twice"

    sampled_flagged = flagged_rows & set(ids)
    sampled_clean = clean_rows & set(ids)
    assert len(sampled_flagged) == min(error_sample, len(flagged_rows))
    assert len(sampled_clean) == min(max(total_sample - error_sample, 0), len(clean_rows))

    rows = dict(root.rows())
    for point in points:
        values = rows[point["ID"]]
        for axis, column in (("x", x_column), ("y", y_column)):
            number = root.number_of(column, values[column])
            if reference.is_null(values[column]):
                assert point[axis] == "null"
                assert point[f"{axis}Type"] == "categorical"
            elif number is not None:
                assert point[axis] == pytest.approx(number)
                assert point[f"{axis}Type"] == "numeric"
            else:
                assert point[f"{axis}Type"] == "categorical"
        expected_errors = flagged_types.get(point["ID"], set())
        assert set(point["errors"]) <= expected_errors
        if not flags.borderline:
            assert set(point["errors"]) == expected_errors


@pytest.mark.sql
@pytest.mark.parametrize("seed", seeds())
def test_preview_histograms_of_a_candidate_leave_the_session_where_it_was(make_root, client, seed):
    """A candidate's preview is drawn from its own table, and the session's current table does not move."""
    import app

    root = make(make_root, seed)
    column = root.data_columns[0]
    response = client.post("/api/wrangle/create-previews", json={"row_ids": root.ids[:1], "cols": [column]})
    assert response.status_code == 200, response.get_json()
    candidate = response.get_json()["candidates"][0]

    get_json(client, "/api/plots/preview-histogram", tablename=candidate["table"], type="1d", column=column)

    assert app.db_operations.main_table_name == root.name
