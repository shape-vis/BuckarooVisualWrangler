"""
Doc 02's validation fixtures, reproduced from the prototype's own row selection.

The fixtures were computed on a node that dropped every row whose ConvertedSalary the prototype
(variants.py) called bad: missing, exactly zero, or outside 3x-IQR Tukey fences - 26 of the survey's 400
rows. Buckaroo's detectors pick a different 20 (tests/sql/test_distortion_survey.py covers that node), so the
selection is rebuilt here in pandas and the metric is held to the fixtures at the precision 02 states them.
"""
import unittest
from pathlib import Path

import pandas as pd

from app.pgraph.distortion import (CATEGORICAL, NUMERIC, REMOVED_LABEL, category_flows, column_detail,
                                   column_distortion, node_distortion, null_result)

SURVEY = Path(__file__).resolve().parents[2] / "provided_datasets" / "stackoverflow_db_uncleaned.csv"

# The columns the fixtures score on
KINDS = {"ConvertedSalary": NUMERIC, "Age": CATEGORICAL, "Gender": CATEGORICAL, "Continent": CATEGORICAL,
         "Country": CATEGORICAL, "DevType": CATEGORICAL, "YearsCoding": CATEGORICAL}

NON_BINARY = "Non-binary, genderqueer, or gender non-conforming"
MALE_NON_BINARY = "Male;Non-binary, genderqueer, or gender non-conforming"


def prototype_n1(root):
    """variants.v1_listwise: drop every row with a bad salary cell."""
    salary = root["ConvertedSalary"]
    q1, q3 = salary.dropna().quantile([0.25, 0.75])
    iqr = q3 - q1
    bad = salary.isna() | (salary == 0) | (salary < q1 - 3 * iqr) | (salary > q3 + 3 * iqr)
    return root[~bad]


class Doc02FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = pd.read_csv(SURVEY)
        cls.n1 = prototype_n1(cls.root)

    def test_the_selection_drops_26_rows(self):
        self.assertEqual(len(self.n1), 374)

    def test_per_column_drift(self):
        expected = {"ConvertedSalary": 0.7719, "Country": 0.0209, "YearsCoding": 0.0151, "DevType": 0.0149,
                    "Continent": 0.0133, "Gender": 0.0105, "Age": 0.0101}

        for column, value in expected.items():
            with self.subTest(column=column):
                result = column_distortion(self.root[column], self.n1[column], KINDS[column])
                self.assertAlmostEqual(result["value"], value, places=4)

    def test_node_number(self):
        self.assertAlmostEqual(node_distortion(self.root, self.n1, KINDS)["overall"], 0.1224, places=4)

    def test_salary_shift_at_the_90th_percentile(self):
        detail = column_detail(self.root["ConvertedSalary"], self.n1["ConvertedSalary"], NUMERIC)

        self.assertAlmostEqual(detail["shift"][detail["grid"].index(0.90)], -0.160, places=3)

    def test_gender_share_changes(self):
        detail = column_detail(self.root["Gender"], self.n1["Gender"], CATEGORICAL)
        change = {row["category"]: row["change_pct"] for row in detail["categories"]}

        for category, value in {"Male": 0.94, "Female": -0.55, NON_BINARY: -0.25, MALE_NON_BINARY: -0.25,
                                "Transgender": 0.03}.items():
            with self.subTest(category=category):
                self.assertAlmostEqual(change[category], value, places=2)

    def test_gender_flows(self):
        flows = category_flows(self.root, self.n1, "Gender", top=10)
        rows = {(flow["source"], flow["target"]): flow["rows"] for flow in flows["flows"]}

        self.assertEqual(rows[("Male", "Male")], 342)
        self.assertEqual(rows[("Male", REMOVED_LABEL)], 20)
        self.assertEqual(rows[("Female", "Female")], 26)
        self.assertEqual(rows[("Female", REMOVED_LABEL)], 4)
        self.assertEqual(rows[("Transgender", "Transgender")], 2)
        self.assertEqual(rows[("UNKNOWN", "UNKNOWN")], 2)
        self.assertEqual(rows[(NON_BINARY, REMOVED_LABEL)], 1)
        self.assertEqual(rows[(MALE_NON_BINARY, REMOVED_LABEL)], 1)
        self.assertAlmostEqual(flows["churn"], 0.065)

    def test_null_test_flags_gender_and_not_the_larger_raw_drifts(self):
        # The README's key test: Country has twice Gender's raw drift, and only Gender is real
        percentiles = {}
        for column in ["Gender", "Country", "DevType", "YearsCoding", "Age", "Continent"]:
            observed = column_distortion(self.root[column], self.n1[column], CATEGORICAL)["value"]
            percentiles[column] = null_result(("survey", column), self.root[column], CATEGORICAL,
                                              len(self.n1), observed)["percentile"]

        self.assertGreater(percentiles["Gender"], 95, percentiles)
        for column in ["Country", "DevType", "YearsCoding", "Age", "Continent"]:
            with self.subTest(column=column):
                self.assertLess(percentiles[column], 95, percentiles)


if __name__ == "__main__":
    unittest.main()
