"""Tests for rare-value warning behavior behind the incomplete detector."""

import unittest
from pathlib import Path

import pandas as pd

from detectors.incomplete import incomplete


DATASETS_DIR = Path(__file__).resolve().parents[2] / "provided_datasets"


class TestIncompleteTesting(unittest.TestCase):
    def test_small_samples_are_not_forced_into_rare_value_errors(self):
        df = pd.DataFrame({
            "ID": range(1, 6),
            "classname": ["systems", "networking", "compilers", "full-stack", "vis"],
            "day": ["M/W", "T/H", "M/W", "M/W/F", "T/H"],
        })

        self.assertEqual({}, incomplete(df))

    def test_common_values_are_not_incomplete(self):
        df = pd.DataFrame({
            "ID": range(1, 31),
            "classname": ["systems"] * 30,
        })

        self.assertEqual({}, incomplete(df))

    def test_rare_values_in_categorical_column_are_warnings(self):
        df = pd.DataFrame({
            "ID": range(1, 31),
            "status": ["common"] * 27 + ["rare-a", "rare-b", "rare-c"],
        })

        self.assertEqual(
            {"status": {28: "incomplete", 29: "incomplete", 30: "incomplete"}},
            incomplete(df),
        )

    def test_details_use_rare_value_error_type(self):
        df = pd.DataFrame({
            "ID": range(1, 31),
            "status": ["common"] * 27 + ["rare-a", "rare-b", "rare-c"],
        })

        result = incomplete(df, include_details=True)

        self.assertEqual("rare_value", result["status"][28]["error_type"])
        self.assertEqual("incomplete", result["status"][28]["legacy_error_type"])
        self.assertEqual("warning", result["status"][28]["severity"])

    def test_real_dataset_still_returns_legacy_incomplete_labels(self):
        test_dataframe = pd.read_csv(DATASETS_DIR / "stackoverflow_db_uncleaned.csv")

        detected_df = incomplete(test_dataframe.head(200))

        self.assertIn("Country", detected_df)
        self.assertTrue(all(error_type == "incomplete" for error_type in detected_df["Country"].values()))


if __name__ == "__main__":
    unittest.main()
