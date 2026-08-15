"""Tests for the shared missing-value detector semantics."""

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from detectors.missing_value import missing_value


DATASETS_DIR = Path(__file__).resolve().parents[2] / "provided_datasets"


class TestMissing(unittest.TestCase):
    def test_nulls_and_nan_values_are_missing(self):
        df = pd.DataFrame({
            "ID": range(1, 4),
            "animals": ["ant", np.nan, "cat"],
            "pets": ["dog", None, "fly"],
        })

        self.assertEqual(
            {"animals": {2: "missing"}, "pets": {2: "missing"}},
            missing_value(df),
        )

    def test_common_string_markers_are_normalized(self):
        df = pd.DataFrame({
            "ID": range(1, 9),
            "value": ["?", "N/A", " unknown ", "-", "none", "null", "undefined", "valid"],
        })

        self.assertEqual(
            {"value": {1: "missing", 2: "missing", 3: "missing", 4: "missing", 5: "missing", 6: "missing", 7: "missing"}},
            missing_value(df),
        )

    def test_details_are_available_without_changing_legacy_default(self):
        df = pd.DataFrame({"ID": [1], "value": ["?"]})

        result = missing_value(df, include_details=True)

        self.assertEqual("missing", result["value"][1]["error_type"])
        self.assertEqual("error", result["value"][1]["severity"])
        self.assertEqual("high", result["value"][1]["confidence"])

    def test_stackoverflow_question_mark_marker_is_missing(self):
        test_dataframe = pd.read_csv(DATASETS_DIR / "stackoverflow_db_uncleaned.csv")

        detected_df = missing_value(test_dataframe.head(200))

        self.assertIn("ConvertedSalary", detected_df)
        self.assertIn("Gender", detected_df)
        self.assertEqual("missing", detected_df["Gender"][157])


if __name__ == "__main__":
    unittest.main()
