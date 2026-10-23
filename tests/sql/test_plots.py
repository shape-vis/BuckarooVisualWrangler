"""
The main view's plots, built by DBOperations (app/db_utils/db_functions_sql.py) for the session's current table: the
1D and 2D histograms with their error breakdowns, the scatterplot, the top error rows, and the row and bin lookups a
selection is made with. Each table is built as a root node, through make_root, with the flags each test lays out.
"""
import pytest

from app import db_operations, engine
from app.db_utils.execute_sql import execute_sql

TABLE = "t_plots"


def _errors_in(bins):
    """Every error type's count summed over the histogram's bins."""
    totals = {}
    for entry in bins:
        for name, count in entry["count"].items():
            if name == "items":
                continue
            totals[name] = totals.get(name, 0) + count
    return totals


def _items_in(bins):
    total = 0
    for entry in bins:
        total += entry["count"]["items"]
    return total


def _bin_of(histogram, x_type, x_bin):
    for entry in histogram["histograms"]:
        if entry["xType"] == x_type and entry["xBin"] == x_bin:
            return entry
    return None


# ── 1D histograms ────────────────────────────────────────────────────────────

@pytest.mark.sql
def test_a_numeric_column_is_binned_across_its_range(make_root):
    make_root(TABLE, {"ID": list(range(1, 21)), "amount": list(range(100, 300, 10))}, flags=[])

    histogram = db_operations.generate_one_d_histogram_with_errors("amount", 5)

    numeric = histogram["scaleX"]["numeric"]
    assert len(numeric) == 5
    assert numeric[0]["x0"] == 100
    assert numeric[-1]["x1"] == 290
    assert histogram["scaleX"]["categorical"] == []
    assert _items_in(histogram["histograms"]) == 20
    for entry in histogram["histograms"]:
        assert entry["xType"] == "numeric"


@pytest.mark.sql
def test_the_maximum_lands_in_the_last_bin(make_root):
    make_root(TABLE, {"ID": [1, 2, 3], "amount": [0, 5, 10]}, flags=[])

    histogram = db_operations.generate_one_d_histogram_with_errors("amount", 2)

    assert _bin_of(histogram, "numeric", "1")["count"]["items"] == 2


@pytest.mark.sql
def test_a_histogram_counts_each_bins_flags(make_root):
    flags = [(1, "amount", "missing"), (2, "amount", "anomaly"), (20, "amount", "anomaly"), (3, "other", "anomaly")]
    make_root(TABLE, {"ID": list(range(1, 21)), "amount": list(range(100, 300, 10)), "other": [1] * 20}, flags=flags)

    histogram = db_operations.generate_one_d_histogram_with_errors("amount", 5)

    # Only the plotted column's flags count, and each lands in its row's bin
    assert _errors_in(histogram["histograms"]) == {"missing": 1, "anomaly": 2}
    assert _bin_of(histogram, "numeric", "0")["count"] == {"items": 4, "missing": 1, "anomaly": 1}
    assert _bin_of(histogram, "numeric", "4")["count"] == {"items": 4, "anomaly": 1}


@pytest.mark.sql
def test_nulls_in_a_numeric_column_get_a_bin_of_their_own(make_root):
    make_root(TABLE, {"ID": [1, 2, 3, 4], "amount": [1.0, 2.0, None, 4.0]}, flags=[])

    histogram = db_operations.generate_one_d_histogram_with_errors("amount", 3)

    assert histogram["scaleX"]["categorical"] == ["null"]
    assert _bin_of(histogram, "categorical", "null")["count"]["items"] == 1
    assert _items_in(histogram["histograms"]) == 4


@pytest.mark.sql
def test_a_constant_column_gets_one_bin(make_root):
    make_root(TABLE, {"ID": [1, 2, 3], "amount": [5, 5, 5]}, flags=[])

    histogram = db_operations.generate_one_d_histogram_with_errors("amount", 10)

    assert histogram["scaleX"]["numeric"] == [{"x0": 4.5, "x1": 5.5}]
    assert _bin_of(histogram, "numeric", "0")["count"]["items"] == 3


@pytest.mark.sql
def test_a_number_that_is_not_finite_is_a_label(make_root):
    make_root(TABLE, {"ID": [1, 2, 3, 4], "amount": [1.5e-7, 0.0, 2.0, 3.0]}, flags=[])
    # pandas stores a NaN as null, so a real one is written straight to the table
    execute_sql(f'UPDATE "{TABLE}" SET amount = \'NaN\' WHERE "ID" = 2', engine)

    histogram = db_operations.generate_one_d_histogram_with_errors("amount", 2)

    # Scientific notation is still a number; NaN is not, so it sits beside the bins
    assert histogram["scaleX"]["numeric"][0]["x0"] == pytest.approx(1.5e-7)
    assert histogram["scaleX"]["categorical"] == ["NaN"]
    assert _items_in(histogram["histograms"]) == 4


@pytest.mark.sql
def test_a_text_column_is_binned_by_label(make_root):
    make_root(TABLE, {"ID": [1, 2, 3, 4, 5], "city": ["Reno", "Austin", "Reno", None, "Austin"]},
              flags=[(4, "city", "missing")])

    histogram = db_operations.generate_one_d_histogram_with_errors("city", 10)

    assert histogram["scaleX"]["numeric"] == []
    assert histogram["scaleX"]["categorical"] == ["Austin", "Reno", "null"]
    assert _bin_of(histogram, "categorical", "Reno")["count"] == {"items": 2}
    assert _bin_of(histogram, "categorical", "null")["count"] == {"items": 1, "missing": 1}


@pytest.mark.sql
def test_a_text_columns_number_shaped_labels_are_on_its_scale(make_root):
    # Mostly text with two numbers: a categorical mixed column, binned by label, numbers included
    make_root(TABLE, {"ID": [1, 2, 3, 4, 5], "hair": ["black", "brown", "2", "black", "1"]}, flags=[])

    histogram = db_operations.generate_one_d_histogram_with_errors("hair", 10)

    assert histogram["scaleX"]["categorical"] == ["1", "2", "black", "brown"]


@pytest.mark.sql
def test_an_unknown_column_is_refused_before_any_query(make_root):
    make_root(TABLE, {"ID": [1, 2], "city": ["a", "b"]}, flags=[])

    for column in ["nope", 'city" FROM pg_class --', "x'y"]:
        with pytest.raises(ValueError, match="has no column"):
            db_operations.generate_one_d_histogram_with_errors(column, 10)
        with pytest.raises(ValueError, match="has no column"):
            db_operations.generate_two_d_histogram_with_errors("city", column, 10, 10)
        with pytest.raises(ValueError, match="has no column"):
            db_operations.generate_scatterplot_with_errors(column, "city", 30, 100)


@pytest.mark.sql
def test_a_column_name_needing_quotes_is_plotted(make_root):
    flags = [(1, "it's: odd", "missing")]
    make_root(TABLE, {"ID": [1, 2], "it's: odd": [None, "b"]}, flags=flags)

    histogram = db_operations.generate_one_d_histogram_with_errors("it's: odd", 10)

    assert _bin_of(histogram, "categorical", "null")["count"] == {"items": 1, "missing": 1}


# ── 2D histograms ────────────────────────────────────────────────────────────

@pytest.mark.sql
def test_a_2d_histogram_bins_both_axes(make_root):
    data = {"ID": list(range(1, 9)), "amount": [0, 1, 2, 3, 4, 5, 6, 7], "city": ["a", "b"] * 4}
    make_root(TABLE, data, flags=[(1, "amount", "anomaly"), (1, "city", "mismatch"), (2, "city", "mismatch")])

    histogram = db_operations.generate_two_d_histogram_with_errors("amount", "city", 2, 10)

    assert len(histogram["scaleX"]["numeric"]) == 2
    assert histogram["scaleY"]["numeric"] == []
    assert histogram["scaleY"]["categorical"] == ["a", "b"]
    assert _items_in(histogram["histograms"]) == 8
    # Both columns' flags count in a tile
    assert _errors_in(histogram["histograms"]) == {"anomaly": 1, "mismatch": 2}

    tiles = {}
    for entry in histogram["histograms"]:
        tiles[(entry["xBin"], entry["yBin"])] = entry["count"]["items"]
    assert tiles == {("0", "a"): 2, ("0", "b"): 2, ("1", "a"): 2, ("1", "b"): 2}


@pytest.mark.sql
def test_a_row_flagged_on_both_columns_is_one_flagged_row(make_root):
    make_root(TABLE, {"ID": [1, 2], "x": ["a", "a"], "y": ["c", "c"]},
              flags=[(1, "x", "missing"), (1, "y", "missing")])

    histogram = db_operations.generate_two_d_histogram_with_errors("x", "y", 10, 10)

    assert histogram["histograms"][0]["count"] == {"items": 2, "missing": 1}


# ── Selections: rows in a bin, bins holding rows ─────────────────────────────

@pytest.mark.sql
def test_a_histograms_bins_know_their_rows(make_root):
    make_root(TABLE, {"ID": [1, 2, 3, 4], "city": ["a", "b", "a", None]}, flags=[])

    db_operations.generate_one_d_histogram_with_errors("city", 10)

    assert sorted(db_operations.get_row_ids_in_bin("city", "a")) == [1, 3]
    assert db_operations.get_row_ids_in_bin("city", "null") == [4]
    assert db_operations.get_row_ids_in_bin("city", "zzz") == []
    assert sorted(db_operations.get_1d_bins_containing_rows("city", [1, 2, 3])) == ["a", "b"]


@pytest.mark.sql
def test_a_heatmaps_tiles_know_their_rows(make_root):
    make_root(TABLE, {"ID": [1, 2, 3], "x": ["a", "a", "b"], "y": ["c", "d", "c"]}, flags=[])

    db_operations.generate_two_d_histogram_with_errors("x", "y", 10, 10)

    assert db_operations.get_row_ids_in_bin(("x", "y"), ("a", "d")) == [2]
    bins = db_operations.get_2d_bins_containing_rows(("x", "y"), [1, 3])
    assert sorted(bins, key=lambda tile: tile["xBin"]) == [{"xBin": "a", "yBin": "c"}, {"xBin": "b", "yBin": "c"}]


@pytest.mark.sql
def test_a_plot_no_longer_shown_forgets_its_rows(make_root):
    make_root(TABLE, {"ID": [1, 2], "city": ["a", "b"]}, flags=[])
    db_operations.generate_one_d_histogram_with_errors("city", 10)

    db_operations.del_nonactive_hists(["city", "never_drawn"])

    assert "city" not in db_operations.active_hists


# ── Scatterplot ──────────────────────────────────────────────────────────────

@pytest.mark.sql
def test_a_scatterplot_samples_every_row_of_a_small_table(make_root):
    data = {"ID": [1, 2, 3, 4], "amount": [1.5, 2.5, None, 10.0], "city": ["a", "b", "a", None]}
    make_root(TABLE, data, flags=[(4, "amount", "anomaly"), (4, "city", "missing")])

    scatter = db_operations.generate_scatterplot_with_errors("amount", "city", 30, 100)

    points = {}
    for point in scatter["data"]:
        points[point["ID"]] = point
    assert sorted(points) == [1, 2, 3, 4]
    assert points[1]["xType"] == "numeric" and points[1]["x"] == 1.5
    assert points[1]["yType"] == "categorical" and points[1]["y"] == "a"
    assert points[3]["xType"] == "categorical" and points[3]["x"] == "null"
    assert sorted(points[4]["errors"]) == ["anomaly", "missing"]
    assert points[1]["errors"] == []
    # The numeric axis runs from the smallest value to one past the largest
    assert scatter["scaleX"]["numeric"] == [1.5, 11.0]
    assert scatter["scaleY"]["numeric"] == []


@pytest.mark.sql
def test_a_scatterplot_samples_flagged_rows_first(make_root):
    ids = list(range(1, 51))
    flags = [(5, "amount", "anomaly"), (6, "amount", "anomaly")]
    make_root(TABLE, {"ID": ids, "amount": ids, "other": ids}, flags=flags)

    scatter = db_operations.generate_scatterplot_with_errors("amount", "other", 2, 5)

    sampled = []
    for point in scatter["data"]:
        sampled.append(point["ID"])
    assert len(sampled) == 5
    assert 5 in sampled and 6 in sampled


# ── Top error rows ───────────────────────────────────────────────────────────

@pytest.mark.sql
def test_the_top_error_rows_are_the_most_flagged(make_root):
    flags = [(2, "a", "missing"), (2, "b", "anomaly"), (2, "c", "mismatch"), (3, "a", "missing"), (3, "b", "missing")]
    make_root(TABLE, {"ID": [1, 2, 3], "a": [1, 2, 3], "b": [1, 2, 3], "c": [1, 2, 3]}, flags=flags)

    data_rows, error_rows = db_operations.generate_top_error_rows(1)

    assert list(data_rows["ID"]) == [2]
    assert sorted(error_rows["column_id"]) == ["a", "b", "c"]


# ── Routes ───────────────────────────────────────────────────────────────────

@pytest.mark.sql
def test_the_histogram_route_draws_the_current_table(make_root, client):
    make_root(TABLE, {"ID": [1, 2, 3], "city": ["a", "b", "a"]}, flags=[])

    body = client.get("/api/plots/1-d-histogram?column=city&bins=10").get_json()

    assert body["success"]
    assert body["histogram"]["scaleX"]["categorical"] == ["a", "b"]


@pytest.mark.sql
def test_a_preview_draws_any_node_but_nothing_else(make_root, client):
    make_root(TABLE, {"ID": [1, 2, 3], "x": [1, 2, 3], "y": ["a", "b", "a"]}, flags=[])

    drawn = client.get(f"/api/plots/preview-histogram?tablename={TABLE}&type=2d&column_x=x&column_y=y").get_json()
    refused = client.get("/api/plots/preview-histogram?tablename=pg_class&type=1d&column=relname").get_json()

    assert drawn["success"] and _items_in(drawn["histogram"]["histograms"]) == 3
    assert not refused["success"]
