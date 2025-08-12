import unittest
import pandas as pd

from data_management.data_scatterplot_integration import sample_scatterplot_data, build_scatterplot_data_entry, \
    get_errors_for_id


class MyTestCase(unittest.TestCase):
    def test_sample_scatterplot_data_directly_basic(self):
        """Test direct sampling with basic constraints."""
        main_df = pd.DataFrame({
            'ID': [1, 2, 3, 4, 5, 6, 7, 8],
            'col1': ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'],
            'col2': [10, 20, 30, 40, 50, 60, 70, 80]
        })

        error_df = pd.DataFrame({
            'row_id': [1, 3, 5, 7],
            'column_id': ['col1', 'col2', 'col1', 'col2'],
            'error_type': ['anomaly', 'missing', 'mismatch', 'incomplete']
        })

        # Test with error_sample_size=2, total_sample_size=5
        sampled_ids = sample_scatterplot_data(
            main_df, error_df, 'col1', 'col2', error_sample_size=2, total_sample_size=5
        )

        self.assertEqual(len(sampled_ids), 5)

        # Count error vs clean IDs
        error_ids = {1, 3, 5, 7}
        error_count = sum(1 for id in sampled_ids if id in error_ids)
        self.assertLessEqual(error_count, 2)

    def test_sample_scatterplot_data_directly_more_errors_than_limit(self):
        """Test when there are more error rows than error_sample_size."""
        main_df = pd.DataFrame({
            'ID': [1, 2, 3, 4, 5, 6],
            'col1': ['A', 'B', 'C', 'D', 'E', 'F'],
            'col2': [10, 20, 30, 40, 50, 60]
        })

        error_df = pd.DataFrame({
            'row_id': [1, 2, 3, 4],  # 4 error IDs
            'column_id': ['col1', 'col2', 'col1', 'col2'],
            'error_type': ['anomaly', 'missing', 'mismatch', 'incomplete']
        })

        sampled_ids = sample_scatterplot_data(
            main_df, error_df, 'col1', 'col2', error_sample_size=2, total_sample_size=4
        )

        self.assertEqual(len(sampled_ids), 4)

        # Should have exactly 2 error IDs
        error_ids = {1, 2, 3, 4}
        error_count = sum(1 for id in sampled_ids if id in error_ids)
        self.assertEqual(error_count, 2)

    def test_sample_scatterplot_data_directly_preserves_all_when_under_limit(self):
        """Test that all data is preserved when under the limits."""
        main_df = pd.DataFrame({
            'ID': [1, 2, 3],
            'col1': ['A', 'B', 'C'],
            'col2': [10, 20, 30]
        })

        error_df = pd.DataFrame({
            'row_id': [1],
            'column_id': ['col1'],
            'error_type': ['anomaly']
        })

        sampled_ids = sample_scatterplot_data(
            main_df, error_df, 'col1', 'col2', error_sample_size=5, total_sample_size=10
        )

        # Should preserve all 3 rows
        self.assertEqual(len(sampled_ids), 3)
        self.assertEqual(set(sampled_ids), {1, 2, 3})

    def test_multiple_errors_for_single_id_captured(self):
        """Test that when an ID has multiple errors, all are included in the JSON."""
        main_df = pd.DataFrame({
            'ID': [1, 2, 3, 4],
            'Continent': ['North America', 'EU', 'AS', 'OC'],
            'ConvertedSalary': [75000, 45000, 12000, 85000]
        })

        # ID 1 has multiple errors in both columns
        error_df = pd.DataFrame({
            'row_id': [1, 1, 1, 2],
            'column_id': ['Continent', 'Continent', 'ConvertedSalary', 'Continent'],
            'error_type': ['mismatch', 'anomaly', 'missing', 'incomplete']
        })

        # Test the get_errors_for_id function directly
        errors = get_errors_for_id(error_df, 1, 'Continent', 'ConvertedSalary')

        # Should have all 3 errors for ID 1
        self.assertEqual(len(errors), 3)
        self.assertIn('mismatch', errors)
        self.assertIn('anomaly', errors)
        self.assertIn('missing', errors)

        # Test in the complete data entry building
        entry = build_scatterplot_data_entry(
            main_df, error_df, 1, 'Continent', 'ConvertedSalary', 'categorical', 'numeric'
        )

        expected_entry = {
            "ID": 1,
            "xType": "categorical",
            "yType": "numeric",
            "x": "North America",
            "y": 75000,
            "errors": ['mismatch', 'anomaly', 'missing']
        }

        self.assertEqual(entry, expected_entry)
        self.assertEqual(len(entry['errors']), 3)


if __name__ == '__main__':
    unittest.main()
