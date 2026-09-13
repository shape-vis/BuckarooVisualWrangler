import unittest

import pandas as pd

from app.pgraph.compare import (Axis, MAX_CATEGORIES, NULL_LABEL, NodeState, OTHER_LABEL,
                                compare_heatmap, compare_histogram, compare_scatter,
                                summarize_changes)


def state(rows, errors=()):
    """
    A NodeState built by hand, so the comparison arithmetic can be tested without a database.

    :param rows: {"ID": [...], column: [...], ...}
    :param errors: (row_id, column_id, error_type) triples
    """
    return NodeState(pd.DataFrame(rows),
                     pd.DataFrame(list(errors), columns=["row_id", "column_id", "error_type"]))


class SharedAxisTests(unittest.TestCase):
    def test_numeric_range_spans_both_states(self):
        # The comparator lost its outlier, but its bins still have to line up with the baseline's
        axis = Axis.shared(pd.Series([0, 5, 100]), pd.Series([0, 5]), bin_count=10)

        self.assertEqual((axis.lo, axis.hi), (0.0, 100.0))

    def test_nulls_and_text_in_a_numeric_column_become_labels(self):
        axis = Axis.shared(pd.Series([1, 2, None, "oops"]), pd.Series([3, 4]), bin_count=4)

        self.assertTrue(axis.is_numeric)
        self.assertEqual(axis.labels, [NULL_LABEL, "oops"])

    def test_mostly_text_column_is_categorical(self):
        axis = Axis.shared(pd.Series(["a", "b", "7"]), pd.Series(["a"]), bin_count=4)

        self.assertFalse(axis.is_numeric)
        self.assertEqual(axis.labels, ["7", "a", "b"])

    def test_long_tail_folds_into_other_but_null_survives(self):
        # Null is the rarest label here, and would be the first to fold away if it were not kept
        values = pd.Series([f"v{i:02d}" for i in range(30)] * 2 + [None])
        axis = Axis.shared(values, pd.Series([], dtype=object), bin_count=10)

        self.assertEqual(len(axis.labels), MAX_CATEGORIES)
        self.assertIn(NULL_LABEL, axis.labels)
        self.assertEqual(axis.labels[-1], OTHER_LABEL)

    def test_constant_column_gets_one_bin_with_width(self):
        axis = Axis.shared(pd.Series([7, 7]), pd.Series([7]), bin_count=10)
        numeric = axis.bin_scale()["numeric"]

        self.assertEqual(len(numeric), 1)
        self.assertLess(numeric[0]["x0"], numeric[0]["x1"])

    def test_maximum_lands_in_the_last_bin(self):
        axis = Axis.shared(pd.Series([0, 10]), pd.Series([], dtype=float), bin_count=5)
        _, bins = axis.bin(pd.Series([0, 4.9, 10]))

        self.assertEqual(list(bins), [0, 2, 4])


class CompareHistogramTests(unittest.TestCase):
    def test_every_bin_lists_both_sides(self):
        base = state({"ID": [1, 2, 3, 4], "age": [0, 0, 10, 10]},
                     [(1, "age", "missing"), (3, "age", "anomaly")])
        other = state({"ID": [1, 2], "age": [0, 0]})

        bins = compare_histogram(base, other, "age", bin_count=2)["bins"]

        self.assertEqual([(b["xType"], b["xBin"]) for b in bins], [("numeric", 0), ("numeric", 1)])
        self.assertEqual(bins[0]["base"], {"items": 2, "missing": 1})
        self.assertEqual(bins[0]["other"], {"items": 2})
        # The comparator has nothing in the top bin, but the bin is still there to measure against
        self.assertEqual(bins[1]["base"], {"items": 2, "anomaly": 1})
        self.assertEqual(bins[1]["other"], {"items": 0})

    def test_flags_on_other_columns_are_not_counted(self):
        base = state({"ID": [1], "age": [3]}, [(1, "city", "missing")])

        bins = compare_histogram(base, base, "age", bin_count=1)["bins"]

        self.assertEqual(bins[0]["base"], {"items": 1})

    def test_imputed_nulls_move_from_the_null_label_into_a_bin(self):
        base = state({"ID": [1, 2], "age": [None, 4]})
        other = state({"ID": [1, 2], "age": [4, 4]})

        bins = {(b["xType"], b["xBin"]): b for b in compare_histogram(base, other, "age", 1)["bins"]}

        self.assertEqual(bins[("categorical", NULL_LABEL)]["base"]["items"], 1)
        self.assertEqual(bins[("categorical", NULL_LABEL)]["other"]["items"], 0)
        self.assertEqual(bins[("numeric", 0)]["other"]["items"], 2)


class CompareHeatmapTests(unittest.TestCase):
    def test_only_occupied_tiles_are_listed(self):
        base = state({"ID": [1, 2], "a": [0, 10], "b": [0, 10]})

        tiles = compare_heatmap(base, base, "a", "b", bin_count=2)["tiles"]

        self.assertEqual([(t["xBin"], t["yBin"]) for t in tiles], [(0, 0), (1, 1)])

    def test_row_flagged_on_both_columns_counts_once(self):
        base = state({"ID": [1], "a": [1], "b": [1]}, [(1, "a", "missing"), (1, "b", "missing")])

        tiles = compare_heatmap(base, base, "a", "b", bin_count=1)["tiles"]

        self.assertEqual(tiles[0]["base"], {"items": 1, "missing": 1})

    def test_same_column_on_both_axes(self):
        base = state({"ID": [1, 2], "a": [0, 10]})

        tiles = compare_heatmap(base, base, "a", "a", bin_count=2)["tiles"]

        self.assertEqual([(t["xBin"], t["yBin"]) for t in tiles], [(0, 0), (1, 1)])


class SummarizeChangesTests(unittest.TestCase):
    def test_rows_are_matched_by_id(self):
        base = state({"ID": [1, 2, 3], "age": [None, 20, 30]})
        other = state({"ID": [1, 2, 4], "age": [25, 20, 40]})

        changes = summarize_changes(base, other, ["age"])

        self.assertEqual(changes["removed"], 1)                # row 3
        self.assertEqual(changes["added"], 1)                  # row 4
        self.assertEqual(changes["shared"], 2)
        self.assertEqual(changes["changed"], {"age": 1})       # row 1, imputed
        self.assertEqual(changes["changed_rows"], 1)

    def test_numbers_compare_as_numbers_and_nulls_match(self):
        base = state({"ID": [1, 2], "v": [3, None]})
        other = state({"ID": [1, 2], "v": ["3.0", None]})

        self.assertEqual(summarize_changes(base, other, ["v"])["changed"], {"v": 0})

    def test_changed_rows_counts_a_row_once_across_columns(self):
        base = state({"ID": [1], "a": [1], "b": [1]})
        other = state({"ID": [1], "a": [2], "b": [2]})

        changes = summarize_changes(base, other, ["a", "b"])

        self.assertEqual(changes["changed"], {"a": 1, "b": 1})
        self.assertEqual(changes["changed_rows"], 1)


class CompareScatterTests(unittest.TestCase):
    def test_points_follow_rows_between_states(self):
        base = state({"ID": [1, 2, 3], "x": [1, 2, 3], "y": [1, 2, 3]})
        other = state({"ID": [1, 2], "x": [1, 5], "y": [1, 2]})

        points = {p["ID"]: p for p in compare_scatter(base, other, "x", "y", 50)["points"]}

        self.assertEqual(points[1]["status"], "same")
        self.assertEqual(points[2]["status"], "changed")
        self.assertEqual(points[2]["base"]["x"], 2.0)
        self.assertEqual(points[2]["other"]["x"], 5.0)
        self.assertEqual(points[3]["status"], "removed")
        self.assertIsNone(points[3]["other"])

    def test_sample_keeps_every_changed_row_and_fills_its_budget(self):
        ids = list(range(1, 201))
        base = state({"ID": ids, "x": ids, "y": ids})
        other = state({"ID": ids, "x": [i + 1000 if i <= 5 else i for i in ids], "y": ids})

        result = compare_scatter(base, other, "x", "y", sample_size=50)

        self.assertEqual(result["sampled"], 50)
        self.assertEqual(result["population"], 200)
        self.assertEqual(sum(p["status"] == "changed" for p in result["points"]), 5)

    def test_each_side_carries_its_own_errors(self):
        base = state({"ID": [1], "x": [None], "y": [1]}, [(1, "x", "missing")])
        other = state({"ID": [1], "x": [4], "y": [1]})

        point = compare_scatter(base, other, "x", "y", 50)["points"][0]

        self.assertEqual(point["base"], {"xType": "categorical", "x": NULL_LABEL,
                                         "yType": "numeric", "y": 1.0, "errors": ["missing"]})
        self.assertEqual(point["other"]["errors"], [])

    def test_same_column_on_both_axes(self):
        base = state({"ID": [1, 2], "x": [1, 2]})

        points = compare_scatter(base, base, "x", "x", 50)["points"]

        self.assertEqual([(p["base"]["x"], p["base"]["y"]) for p in points], [(1.0, 1.0), (2.0, 2.0)])


if __name__ == '__main__':
    unittest.main()
