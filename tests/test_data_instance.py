import unittest
import pandas as pd

from data_management.data_instance import DataInstance


class TestDataInstance(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.sample_regular_table = pd.DataFrame({'A': [1, 2, 3], 'B': [4, 5, 6]})
        self.sample_error_table = pd.DataFrame({'error_col': ['error1', 'error2']})

        self.data_instance = DataInstance(
            wrangle_performed="filter_nulls",
            rows_affected={4,3,56,6},
            regular_table=self.sample_regular_table,
            error_table=self.sample_error_table
        )

    def test_initialization(self):
        """Test that DataInstance initializes correctly with all parameters."""
        self.assertEqual(self.data_instance.wrangle_performed, "filter_nulls")
        self.assertEqual(self.data_instance.rows_affected, {4,3,56,6})
        pd.testing.assert_frame_equal(self.data_instance.regular_table, self.sample_regular_table)
        pd.testing.assert_frame_equal(self.data_instance.error_table, self.sample_error_table)

    def test_set_wrangle_performed(self):
        """Test setting wrangle_performed with different types."""
        self.data_instance.set_wrangle_performed("remove_duplicates")
        self.assertEqual(self.data_instance.get_wrangle_performed(), "remove_duplicates")

        # Test with None
        self.data_instance.set_wrangle_performed(None)
        self.assertIsNone(self.data_instance.get_wrangle_performed())

    def test_set_rows_affected(self):
        """Test setting rows_affected with different values."""
        self.data_instance.set_rows_affected(10)
        self.assertEqual(self.data_instance.get_rows_affected(), 10)

        # Test with zero
        self.data_instance.set_rows_affected(0)
        self.assertEqual(self.data_instance.get_rows_affected(), 0)

    def test_set_regular_table(self):
        """Test setting regular_table with different DataFrames."""
        new_table = pd.DataFrame({'X': [10, 20], 'Y': [30, 40]})
        self.data_instance.set_regular_table(new_table)
        pd.testing.assert_frame_equal(self.data_instance.get_regular_table(), new_table)

        # Test with empty DataFrame
        empty_df = pd.DataFrame()
        self.data_instance.set_regular_table(empty_df)
        pd.testing.assert_frame_equal(self.data_instance.get_regular_table(), empty_df)

    def test_set_error_table(self):
        """Test setting error_table with different DataFrames."""
        new_error_table = pd.DataFrame({'error_type': ['validation'], 'message': ['invalid data']})
        self.data_instance.set_error_table(new_error_table)
        pd.testing.assert_frame_equal(self.data_instance.get_error_table(), new_error_table)

        # Test with None
        self.data_instance.set_error_table(None)
        self.assertIsNone(self.data_instance.get_error_table())

    def test_getter_methods(self):
        """Test all getter methods return correct values."""
        self.assertEqual(self.data_instance.get_wrangle_performed(), "filter_nulls")
        self.assertEqual(self.data_instance.get_rows_affected(), {4,3,56,6})
        pd.testing.assert_frame_equal(self.data_instance.get_regular_table(), self.sample_regular_table)
        pd.testing.assert_frame_equal(self.data_instance.get_error_table(), self.sample_error_table)

if __name__ == '__main__':
    unittest.main()