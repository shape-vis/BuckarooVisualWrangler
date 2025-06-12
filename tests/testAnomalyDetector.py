import unittest

import numpy as np
import pandas as pd

from detectors.anomaly import anomaly
from detectors.missingValue import missing_value


class AnomalyTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
