import unittest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch

import app
from data_management.data_integration import determine_column_type_and_bins, get_optimized_error_counts_by_bins, \
    count_categorical_bins_with_error_types, count_numeric_bins_with_error_types, build_categorical_histogram, \
    build_numeric_histogram, format_error_counts, generate_1d_histogram_data


class TestDataSetup:
    @staticmethod
    def create_sample_stackoverflow_df():
        return pd.DataFrame({
            'ID': [1, 2, 3, 4, 5, 6, 7, 8],
            'ConvertedSalary': [50000, 75000, 100000, 125000, 150000, 200000, np.nan, 300000],
            'Country': ['USA', 'Canada', 'USA', 'Germany', 'Canada', 'USA', 'Germany', 'France'],
            'Age': ['25-34', '18-24', '35-44', '25-34', '45-54', '25-34', '18-24', '35-44']
        })

    @staticmethod
    def create_sample_error_df():
        return pd.DataFrame({
            'row_id': [2, 4, 6, 7, 8],
            'column_id': ['ConvertedSalary', 'ConvertedSalary', 'Country', 'ConvertedSalary', 'Age'],
            'error_type': ['anomaly', 'incomplete', 'mismatch', 'missing', 'anomaly']
        })

    class TestHelperFunctions(unittest.TestCase):

        def setUp(self):
            self.df = TestDataSetup.create_sample_stackoverflow_df()
            self.error_df = TestDataSetup.create_sample_error_df()

        def test_determine_column_type_numeric(self):
            col_type, bins = determine_column_type_and_bins(self.df, 'ConvertedSalary', 3)
            self.assertEqual(col_type, "numeric")
            self.assertIsNotNone(bins)

        def test_determine_column_type_categorical(self):
            col_type, bins = determine_column_type_and_bins(self.df, 'Country', 3)
            self.assertEqual(col_type, "categorical")
            self.assertIn('USA', bins)

    class TestOptimizedErrorCounting(unittest.TestCase):

            def setUp(self):
                self.df = TestDataSetup.create_sample_stackoverflow_df()
                self.error_df = TestDataSetup.create_sample_error_df()

            def test_get_optimized_error_counts_categorical(self):
                # Test with Country column (categorical)
                categories = self.df['Country'].dropna().unique()
                category_to_bin = {cat: i for i, cat in enumerate(categories)}
                bin_assignments = self.df['Country'].map(category_to_bin).values

                result = get_optimized_error_counts_by_bins(self.df, self.error_df, 'Country', bin_assignments)

                # Should find the mismatch error for row_id 6 (USA)
                self.assertIsInstance(result, dict)
                if len(result) > 0:
                    self.assertTrue(any('mismatch' in errors for errors in result.values()))

    class TestCategoricalCounting(unittest.TestCase):

            def setUp(self):
                self.df = TestDataSetup.create_sample_stackoverflow_df()
                self.error_df = TestDataSetup.create_sample_error_df()

            def test_count_categorical_bins_country(self):
                results, categories = count_categorical_bins_with_error_types(self.df, self.error_df, 'Country')

                # Should have 4 categories: USA, Canada, Germany, France
                self.assertEqual(len(categories), 4)
                self.assertIn('USA', categories)
                self.assertIn('Canada', categories)

                # Check USA bin has correct item count
                usa_result = next((r for r in results if r['category'] == 'USA'), None)
                self.assertIsNotNone(usa_result)
                self.assertEqual(usa_result['items'], 3)  # 3 USA entries

    class TestNumericCounting(unittest.TestCase):

            def setUp(self):
                self.df = TestDataSetup.create_sample_stackoverflow_df()
                self.error_df = TestDataSetup.create_sample_error_df()

            def test_count_numeric_bins_salary(self):
                results, bin_intervals = count_numeric_bins_with_error_types(
                    self.df, self.error_df, 'ConvertedSalary', 3
                )

                self.assertEqual(len(results), 3)  # 3 bins
                self.assertEqual(len(bin_intervals), 3)

                # Check that we have items in bins
                total_items = sum(r['items'] for r in results)
                self.assertGreater(total_items, 0)

                # Check for error types in results
                has_errors = any(len(r['error_types']) > 0 for r in results)
                self.assertTrue(has_errors)  # Should have some errors

    class TestHistogramBuilders(unittest.TestCase):

            def setUp(self):
                self.df = TestDataSetup.create_sample_stackoverflow_df()
                self.error_df = TestDataSetup.create_sample_error_df()

            def test_build_categorical_histogram_country(self):
                result = build_categorical_histogram(self.df, self.error_df, 'Country')

                self.assertIn('histograms', result)
                self.assertIn('scaleX', result)
                self.assertEqual(len(result['scaleX']['categorical']), 4)  # 4 countries
                self.assertEqual(len(result['scaleX']['numeric']), 0)

                # Check histogram structure
                first_hist = result['histograms'][0]
                self.assertIn('count', first_hist)
                self.assertIn('items', first_hist['count'])
                self.assertEqual(first_hist['xType'], 'categorical')

            def test_build_numeric_histogram_salary(self):
                result = build_numeric_histogram(self.df, self.error_df, 'ConvertedSalary', 3)

                self.assertIn('histograms', result)
                self.assertIn('scaleX', result)
                self.assertEqual(len(result['histograms']), 3)  # 3 bins
                self.assertGreater(len(result['scaleX']['numeric']), 0)

                # Check histogram structure
                first_hist = result['histograms'][0]
                self.assertIn('count', first_hist)
                self.assertIn('items', first_hist['count'])
                self.assertEqual(first_hist['xType'], 'numeric')
                self.assertIn('x0', result['scaleX']['numeric'][0])
                self.assertIn('x1', result['scaleX']['numeric'][0])

    class TestErrorFormatting(unittest.TestCase):

            def test_format_error_counts_multiple_types(self):
                error_types = {'anomaly': 2, 'incomplete': 1, 'missing': 3}
                result = format_error_counts(error_types, 10)

                expected = {'items': 10, 'anomaly': 2, 'incomplete': 1, 'missing': 3}
                self.assertEqual(result, expected)

            def test_format_error_counts_no_errors(self):
                error_types = {}
                result = format_error_counts(error_types, 5)

                expected = {'items': 5}
                self.assertEqual(result, expected)

if __name__ == '__main__':
        unittest.main(verbosity=2)