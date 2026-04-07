import unittest

import pandas as pd

from wranglers.remove_data import remove_data


class TestRemoveWranglerTests(unittest.TestCase):
    def test_basic_removal(self):
        df = pd.DataFrame({'ID': [1, 2, 3]}, index=[0, 1, 2])
        expected_df = pd.DataFrame({'ID': [2, 3]}, index=[1,2])

        result = remove_data(df, ["1"])
        pd.testing.assert_frame_equal(expected_df, result)

    def test_multiple_removal(self):
        df = pd.DataFrame({'ID': [1, 2, 3]}, index=[0, 1, 2])
        expected_df = pd.DataFrame({'ID': [3]}, index=[2])
        result = remove_data(df, ["1","2"])
        pd.testing.assert_frame_equal(expected_df, result)

    def test_nonexistent_id(self):
        df = pd.DataFrame({'ID': [1, 2, 3]}, index=[0, 1, 2])
        expected_df = pd.DataFrame({'ID': [1, 2, 3]}, index=[0, 1, 2])
        result = remove_data(df, ["999"])
        pd.testing.assert_frame_equal(expected_df, result)

if __name__ == '__main__':
    unittest.main()
