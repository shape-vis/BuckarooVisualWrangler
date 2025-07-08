import unittest
import pandas as pd
import numpy as np
from wranglers.impute_average import impute_average_on_ids


class TestImputeAverage(unittest.TestCase):
    def setUp(self):
        self.sample_dataframe = pd.DataFrame({
            'ID': [1, 2, 3, 4, 5, 6, 7, 8],
            'numeric_col': [10.0, 20.0, np.nan, 40.0, 50.0, 60.0, 70.0, 80.0],
            'categorical_col': ['A', 'B', 'A', 'C', 'A', 'B', 'C', 'A']
        })

    def test_impute_numeric_column(self):
        selected_ids = [1, 3, 5]
        result = impute_average_on_ids('numeric_col', self.sample_dataframe, selected_ids)

        # Should impute mean of positive values: (10+20+40+50+60+70+80)/7 = 47.1
        expected_mean = 47.1
        self.assertEqual(result.loc[0, 'numeric_col'], expected_mean)  # ID 1
        self.assertEqual(result.loc[2, 'numeric_col'], expected_mean)  # ID 3 (was NaN)
        self.assertEqual(result.loc[4, 'numeric_col'], expected_mean)  # ID 5

    def test_impute_numeric_column_with_str_type(self):
        selected_ids = ["1","3","5"]
        result = impute_average_on_ids('numeric_col', self.sample_dataframe, selected_ids)

        # Should impute mean of positive values: (10+20+40+50+60+70+80)/7 = 47.1
        expected_mean = 47.1
        self.assertEqual(result.loc[0, 'numeric_col'], expected_mean)  # ID 1
        self.assertEqual(result.loc[2, 'numeric_col'], expected_mean)  # ID 3 (was NaN)
        self.assertEqual(result.loc[4, 'numeric_col'], expected_mean)  # ID 5

    def test_impute_categorical_column(self):
        selected_ids = [2, 4, 6]
        result = impute_average_on_ids('categorical_col', self.sample_dataframe, selected_ids)

        # Mode should be 'A' (appears 4 times)
        self.assertEqual(result.loc[1, 'categorical_col'], 'A')  # ID 2
        self.assertEqual(result.loc[3, 'categorical_col'], 'A')  # ID 4
        self.assertEqual(result.loc[5, 'categorical_col'], 'A')  # ID 6

    def test_non_selected_ids_unchanged(self):
        selected_ids = [1, 3]
        result = impute_average_on_ids('numeric_col', self.sample_dataframe, selected_ids)

        # Non-selected IDs should remain unchanged
        self.assertEqual(result.loc[1, 'numeric_col'], 20.0)  # ID 2
        self.assertEqual(result.loc[3, 'numeric_col'], 40.0)  # ID 4

    def test_empty_selected_ids(self):
        selected_ids = []
        result = impute_average_on_ids('numeric_col', self.sample_dataframe, selected_ids)

        # Should return unchanged dataframe
        pd.testing.assert_frame_equal(result, self.sample_dataframe)

    def test_all_nan_numeric_column(self):
        df = pd.DataFrame({
            'ID': [1, 2, 3],
            'all_nan_col': [np.nan, np.nan, np.nan]
        })
        selected_ids = [1, 2]
        result = impute_average_on_ids('all_nan_col', df, selected_ids)

        # Should impute with 0 when no valid values
        self.assertEqual(result.loc[0, 'all_nan_col'], 0)
        self.assertEqual(result.loc[1, 'all_nan_col'], 0)

    def test_negative_values_excluded(self):
        df = pd.DataFrame({
            'ID': [1, 2, 3, 4],
            'mixed_col': [10.0, -5.0, 20.0, -10.0]
        })
        selected_ids = [1, 2]
        result = impute_average_on_ids('mixed_col', df, selected_ids)

        # Should only use positive values: (10+20)/2 = 15.0
        self.assertEqual(result.loc[0, 'mixed_col'], 15.0)
        self.assertEqual(result.loc[1, 'mixed_col'], 15.0)

    def test_zero_values_excluded(self):
        df = pd.DataFrame({
            'ID': [1, 2, 3, 4],
            'zero_col': [0.0, 10.0, 0.0, 20.0]
        })
        selected_ids = [1, 3]
        result = impute_average_on_ids('zero_col', df, selected_ids)

        # Should exclude zeros: (10+20)/2 = 15.0
        self.assertEqual(result.loc[0, 'zero_col'], 15.0)
        self.assertEqual(result.loc[2, 'zero_col'], 15.0)

    def test_original_dataframe_unchanged(self):
        original_copy = self.sample_dataframe.copy()
        selected_ids = [1, 2, 3]

        impute_average_on_ids('numeric_col', self.sample_dataframe, selected_ids)

        # Original dataframe should remain unchanged
        pd.testing.assert_frame_equal(self.sample_dataframe, original_copy)

    def test_nonexistent_ids(self):
        selected_ids = [999, 1000]  # IDs that don't exist
        result = impute_average_on_ids('numeric_col', self.sample_dataframe, selected_ids)

        # Should return unchanged dataframe
        pd.testing.assert_frame_equal(result, self.sample_dataframe)

    def test_mixed_data_types_categorical(self):
        df = pd.DataFrame({
            'ID': [1, 2, 3, 4],
            'mixed_str_col': ['apple', 'banana', 'apple', 'cherry']
        })
        selected_ids = [1, 2]
        result = impute_average_on_ids('mixed_str_col', df, selected_ids)

        # Mode should be 'apple' (appears twice)
        self.assertEqual(result.loc[0, 'mixed_str_col'], 'apple')
        self.assertEqual(result.loc[1, 'mixed_str_col'], 'apple')


if __name__ == '__main__':
    unittest.main()

