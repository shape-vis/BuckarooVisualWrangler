"""Tests for robust numeric anomaly detection."""

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from app.server_utils.set_id_column import set_id_column
from detectors.anomaly import anomaly


DATASETS_DIR = Path(__file__).resolve().parents[2] / "provided_datasets"


class TestAnomalyTests(unittest.TestCase):
    def test_iqr_flags_clear_numeric_outlier(self):
        df = pd.DataFrame({
            "ID": range(1, 13),
            "num": [10, 11, 12, 10, 11, 12, 10, 11, 12, 10, 11, 1000],
        })

        self.assertEqual({"num": {12: "anomaly"}}, anomaly(df))

    def test_details_expose_numeric_outlier_metadata(self):
        df = pd.DataFrame({
            "ID": range(1, 13),
            "num": [10, 11, 12, 10, 11, 12, 10, 11, 12, 10, 11, 1000],
        })

        result = anomaly(df, include_details=True)

        self.assertEqual("numeric_outlier", result["num"][12]["error_type"])
        self.assertEqual("anomaly", result["num"][12]["legacy_error_type"])
        self.assertEqual("warning", result["num"][12]["severity"])
        self.assertIn(result["num"][12]["method"], {"iqr", "mad"})

    def test_skipped_columns_are_reported_when_requested(self):
        df = pd.DataFrame({
            "ID": range(1, 6),
            "mostly_text": [1, 2, "x", "y", "z"],
        })

        result = anomaly(df, include_skipped=True)

        self.assertEqual({}, result["errors"])
        self.assertEqual("fewer_than_10_numeric_values", result["skipped"]["mostly_text"]["reason"])

    def test_real_dataset_still_returns_legacy_anomaly_labels(self):
        test_dataframe = pd.read_csv(DATASETS_DIR / "stackoverflow_db_uncleaned.csv")

        detected_df = anomaly(set_id_column(test_dataframe.head(200)))

        self.assertIn("ConvertedSalary", detected_df)
        self.assertTrue(all(error_type == "anomaly" for error_type in detected_df["ConvertedSalary"].values()))
        self.assertGreaterEqual(len(detected_df["ConvertedSalary"]), 1)


if __name__ == "__main__":
    unittest.main()
