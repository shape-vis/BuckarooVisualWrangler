"""Tests for the numeric anomaly detector and its deterministic seed data."""

import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from app.server_utils.set_id_column import set_id_column
from detectors.anomaly import anomaly


DATASETS_DIR = Path(__file__).resolve().parents[2] / "provided_datasets"


class TestAnomalyTests(unittest.TestCase):
    def test_anomaly_all_numeric(self):
        # Create deterministic test data. The seed fixes the random numbers, so
        # row IDs 10 and 8 stay the expected anomalies every test run.
        np.random.seed(12)
        test_data = {
            'ID' : range(1,13),
            'normal_col': np.random.normal(100, 15, 12),  # Normal distribution
            'anomaly_col': np.concatenate([np.random.normal(50, 5, 7), [2000, 300, -100, 250, 180]]),
            # 1 clear anomalies
        }
        df = pd.DataFrame(test_data)
        detected_df = anomaly(set_id_column(df))
        # The detector returns {column: {row_id: error_type}}. These are row IDs
        # from the ID column, not zero-based DataFrame indexes.
        error_map = {"normal_col":{10: "anomaly"},"anomaly_col":{8:"anomaly"}}
        self.assertEqual(error_map,detected_df)

    def test_anomaly_not_all_numeric(self):
        # Create test data with anomalies
        np.random.seed(12)
        test_data = {
            'ID': range(1, 13),
            'normal_col': np.random.normal(100, 15, 12),  # Normal distribution
            'anomaly_col': np.concatenate([np.random.normal(50, 5, 7), [2000, 300, -100, 250, 180]]),
            'string_col': np.concatenate([np.random.normal(50, 5, 7), [2000, "hi","hello","bonjour","oui"]]),

            # 1 clear anomaly because the string row has some strings so doesn't meet the required threshold of numeric values
        }
        df = pd.DataFrame(test_data)
        detected_df = anomaly(set_id_column(df))
        error_map = {"normal_col":{10: "anomaly"},"anomaly_col":{8:"anomaly"}}
        self.assertDictEqual(error_map,detected_df)

    def test_anomaly_reports_skipped_columns_when_requested(self):
        np.random.seed(12)
        test_data = {
            'ID': range(1, 13),
            'normal_col': np.random.normal(100, 15, 12),
            'anomaly_col': np.concatenate([np.random.normal(50, 5, 7), [2000, 300, -100, 250, 180]]),
            'string_col': np.concatenate([np.random.normal(50, 5, 7), [2000, "hi", "hello", "bonjour", "oui"]]),
        }
        df = pd.DataFrame(test_data)

        result = anomaly(set_id_column(df), include_skipped=True)

        self.assertDictEqual(
            {"normal_col": {10: "anomaly"}, "anomaly_col": {8: "anomaly"}},
            result["errors"],
        )
        self.assertDictEqual(
            {
                "string_col": {
                    "reason": "fewer_than_10_numeric_values",
                    "numeric_count": 8,
                }
            },
            result["skipped"],
        )

    def test_uncleaned_stackoverflow_with_main_detector_result(self):
        test_dataframe = pd.read_csv(DATASETS_DIR / 'stackoverflow_db_uncleaned.csv')
        top_200_rows = test_dataframe.head(200)
        detected_df = anomaly(set_id_column(top_200_rows))
        expected_error_map = {"ConvertedSalary":{13:"anomaly",58:"anomaly",100:"anomaly",115:"anomaly",141:"anomaly", 214:"anomaly",222:"anomaly"}}
        self.assertDictEqual(expected_error_map, detected_df)

    def test_crimes_report_with_main_detector_result(self):
        test_dataframe = pd.read_csv(DATASETS_DIR / '(original)crimes___one_year_prior_to_present_20250421.csv')
        detected_df = anomaly(set_id_column(test_dataframe.head(200)))
        expected_error_map = {
            " IUCR": {
                1: "anomaly",
                2: "anomaly",
                3: "anomaly"
            },
            "BEAT": {
                14: "anomaly",
                16: "anomaly",
                44: "anomaly",
                47: "anomaly",
                70: "anomaly",
                75: "anomaly",
                88: "anomaly",
                98: "anomaly",
                103: "anomaly",
                138: "anomaly",
                188: "anomaly"
            },
            "LATITUDE": {
                14: "anomaly",
                20: "anomaly",
                44: "anomaly",
                77: "anomaly"
            },
            "WARD": {
                14: "anomaly",
                44: "anomaly",
                63: "anomaly",
                153: "anomaly",
                194: "anomaly"
            },
            "X COORDINATE": {
                19: "anomaly",
                32: "anomaly",
                98: "anomaly",
                120: "anomaly",
                155: "anomaly",
                159: "anomaly",
                164: "anomaly",
                179: "anomaly"
            },
            "Y COORDINATE": {
                14: "anomaly",
                20: "anomaly",
                44: "anomaly",
                77: "anomaly"
            },
            "LONGITUDE": {
                19: "anomaly",
                32: "anomaly",
                98: "anomaly",
                120: "anomaly",
                155: "anomaly",
                159: "anomaly",
                164: "anomaly",
                179: "anomaly"
            }
        }
        self.assertDictEqual(expected_error_map, detected_df)
    #
    def test_complaints_with_main_detector_result(self):
        test_dataframe = pd.read_csv(DATASETS_DIR / 'complaints-2025-04-21_17_31.csv')
        detected_df = anomaly(set_id_column(test_dataframe.head(200)))
        expected_error_map = {'Complaint ID': {35: 'anomaly',
                  58: 'anomaly',
                  59: 'anomaly',
                  73: 'anomaly',
                  77: 'anomaly',
                  124: 'anomaly',
                  134: 'anomaly',
                  137: 'anomaly',
                  144: 'anomaly',
                  152: 'anomaly',
                  165: 'anomaly',
                  166: 'anomaly',
                  169: 'anomaly',
                  170: 'anomaly',
                  172: 'anomaly',
                  174: 'anomaly',
                  177: 'anomaly',
                  200: 'anomaly'}}
        self.assertEqual(expected_error_map, detected_df)

if __name__ == '__main__':
    unittest.main()
