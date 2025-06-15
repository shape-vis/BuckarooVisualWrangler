import unittest

import numpy as np
import pandas as pd

from app.set_id_column import set_id_column
from detectors.anomaly import anomaly
from detectors.missing_value import missing_value


class TestAnomalyTests(unittest.TestCase):
    def test_anomaly_all_numeric(self):
        # Create test data with anomalies
        np.random.seed(12)
        test_data = {
            'ID' : range(1,13),
            'normal_col': np.random.normal(100, 15, 12),  # Normal distribution
            'anomaly_col': np.concatenate([np.random.normal(50, 5, 7), [2000, 300, -100, 250, 180]]),
            # 1 clear anomalies
        }
        df = pd.DataFrame(test_data)
        detected_df = anomaly(df)
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
        detected_df = anomaly(df)
        error_map = {"normal_col":{10: "anomaly"},"anomaly_col":{8:"anomaly"}}
        self.assertEqual(error_map,detected_df)

    def test_uncleaned_stackoverflow_with_main_detector_result(self):
        test_dataframe = pd.read_csv('../provided_datasets/stackoverflow_db_uncleaned.csv')
        top_200_rows = test_dataframe.head(200)
        detected_df = anomaly(top_200_rows)
        expected_error_map = {"ConvertedSalary":{13:"anomaly",58:"anomaly",100:"anomaly",115:"anomaly",141:"anomaly", 214:"anomaly",222:"anomaly"}}
        self.assertEqual(expected_error_map, detected_df)

    #----------Should finish building these tests if full integration doesn't work down the line-------#
    # def test_crimes_report_with_main_detector_result(self):
    #     test_dataframe = pd.read_csv('../provided_datasets/Crimes_-_One_year_prior_to_present_20250421.csv')
    #     detected_df = anomaly(test_dataframe.head(200))
    #     expected_error_map = {
    #         "LOCATION DESCRIPTION": {},
    #         "PRIMARY DESCRIPTION": {},
    #         "SECONDARY DESCRIPTION": {},
    #         "BLOCK": {},
    #         "CASE#": {},
    #         "DATE OF OCCURRENCE": {},
    #         "FBI CD": {},
    #         "LOCATION": {},
    #         "LONGITUDE": {}
    #     }
    #     self.assertEqual(expected_error_map, detected_df)
    #
    # def test_complaints_with_main_detector_result(self):
    #     test_dataframe = pd.read_csv('../provided_datasets/complaints-2025-04-21_17_31.csv')
    #     detected_df = anomaly(test_dataframe.head(200))
    #     expected_error_map = {}
    #     self.assertEqual(expected_error_map, detected_df)

if __name__ == '__main__':
    unittest.main()
