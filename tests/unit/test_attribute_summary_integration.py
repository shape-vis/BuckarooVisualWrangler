import unittest
import pandas as pd
import numpy as np

from app.plot_routes import attribute_summaries
from data_management.data_attribute_summary_integration import get_categorical_stats, get_numeric_stats, \
    build_attribute_distributions, convert_error_list_to_dict, generate_complete_json


class TestGetCategoricalStats(unittest.TestCase):

    def test_categorical_stats_basic(self):
        """Test categorical stats calculation"""
        df = pd.DataFrame({'col': ['A', 'B', 'A', 'C', 'A']})
        result = get_categorical_stats(df, 'col')

        expected = {
            "categorical": {
                "categories": 3,
                "mode": "A"
            }
        }
        self.assertEqual(result, expected)

    def test_categorical_stats_single_value(self):
        """Test categorical stats with single unique value"""
        df = pd.DataFrame({'col': ['same'] * 5})
        result = get_categorical_stats(df, 'col')

        self.assertEqual(result["categorical"]["categories"], 1)
        self.assertEqual(result["categorical"]["mode"], "same")


class TestGetNumericStats(unittest.TestCase):

    def test_numeric_stats_basic(self):
        """Test numeric stats calculation"""
        df = pd.DataFrame({'col': [1, 2, 3, 4, 5]})
        result = get_numeric_stats(df, 'col')

        expected = {
            "numeric": {
                "mean": 3.0,
                "min": 1.0,
                "max": 5.0
            }
        }
        self.assertEqual(result, expected)

    def test_numeric_stats_with_floats(self):
        """Test numeric stats with float values"""
        df = pd.DataFrame({'col': [1.5, 2.7, 3.2]})
        result = get_numeric_stats(df, 'col')

        self.assertAlmostEqual(result["numeric"]["mean"], 2.4666666666666666)
        self.assertEqual(result["numeric"]["min"], 1.5)
        self.assertEqual(result["numeric"]["max"], 3.2)

    def test_numeric_stats_with_negative(self):
        """Test numeric stats with negative values"""
        df = pd.DataFrame({'col': [-5, -2, 0, 3, 10]})
        result = get_numeric_stats(df, 'col')

        self.assertEqual(result["numeric"]["mean"], 1.2)
        self.assertEqual(result["numeric"]["min"], -5.0)
        self.assertEqual(result["numeric"]["max"], 10.0)

    def test_numeric_stats_complaints_csv(self):
        df = pd.read_csv('../../provided_datasets/complaints-2025-04-21_17_31.csv').head(400)
        res = build_attribute_distributions(df)
        self.assertEqual(True,True)

class TestBuildAttributeDistributions(unittest.TestCase):

    def test_build_distributions_mixed_types(self):
        """Test building distributions for mixed data types"""
        df = pd.DataFrame({
            'numeric_col': [1, 2, 3, 4, 5],
            'string_col': ['A', 'B', 'A', 'C', 'A']
        })

        result = build_attribute_distributions(df)

        self.assertIn('numeric_col', result)
        self.assertIn('string_col', result)
        self.assertEqual(len(result), 2)

    def test_build_distributions_empty_dataframe(self):
        """Test with empty dataframe"""
        df = pd.DataFrame()
        result = build_attribute_distributions(df)

        self.assertEqual(result, {})

    def test_build_distributions_single_column(self):
        """Test with single column dataframe"""
        df = pd.DataFrame({'col': [1, 2, 3]})
        result = build_attribute_distributions(df)

        self.assertEqual(len(result), 1)
        self.assertIn('col', result)


class TestConvertErrorListToDict(unittest.TestCase):

    def test_convert_error_list_basic(self):
        """Test basic error list conversion with new format"""
        error_df = pd.DataFrame({
            'error_type': ['incomplete', 'missing'],
            'Age': [0.75, 0.0],
            'Country': [0.0, 2.25],
            'ConvertedSalary': [2.5, 0.0]
        })

        result = convert_error_list_to_dict(error_df.to_dict('records'))

        expected = {
            "Age": {"incomplete": 0.75},
            "Country": {"missing": 2.25},
            "ConvertedSalary": {"incomplete": 2.5}
        }
        self.assertEqual(result, expected)

    def test_convert_error_list_ignores_zeros(self):
        """Test that zero percentages are ignored"""
        error_df = pd.DataFrame({
            'error_type': ['anomaly'],
            'ZeroCol': [0.0],
            'NonZeroCol': [1.5]
        })

        result = convert_error_list_to_dict(error_df.to_dict('records'))

        self.assertNotIn("ZeroCol", result)
        self.assertIn("NonZeroCol", result)
        self.assertEqual(result["NonZeroCol"]["anomaly"], 1.5)

    def test_convert_error_list_multiple_error_types(self):
        """Test conversion with multiple error types per column"""
        error_df = pd.DataFrame({
            'error_type': ['incomplete', 'missing', 'anomaly'],
            'Age': [0.75, 0.0, 0.5],
            'Country': [0.0, 2.25, 0.0]
        })

        result = convert_error_list_to_dict(error_df.to_dict('records'))

        expected = {
            "Age": {"incomplete": 0.75, "anomaly": 0.5},
            "Country": {"missing": 2.25}
        }
        self.assertEqual(result, expected)

    def test_convert_error_list_empty_input(self):
        """Test with empty error list"""
        result = convert_error_list_to_dict([])
        self.assertEqual(result, {})


class TestRealDataIntegration(unittest.TestCase):

    def setUp(self):
        """Set up test data"""
        self.test_dataframe = pd.read_csv('../../provided_datasets/stackoverflow_db_uncleaned.csv')

    def test_stackoverflow_categorical_column(self):
        """Test with real stackoverflow categorical data"""
        if 'Country' in self.test_dataframe.columns:
            result = get_categorical_stats(self.test_dataframe, 'Country')

            self.assertIn("categorical", result)
            self.assertIsInstance(result["categorical"]["categories"], int)
            self.assertIsInstance(result["categorical"]["mode"], str)

    def test_stackoverflow_numeric_column(self):
        """Test with real stackoverflow numeric data"""
        if 'ConvertedSalary' in self.test_dataframe.columns:
            clean_df = self.test_dataframe.dropna(subset=['ConvertedSalary'])
            if not clean_df.empty:
                result = get_numeric_stats(clean_df, 'ConvertedSalary')

                self.assertIn("numeric", result)
                self.assertIsInstance(result["numeric"]["mean"], float or int)
                self.assertIsInstance(result["numeric"]["min"], float or int)
                self.assertIsInstance(result["numeric"]["max"], float or int)

    def test_build_distributions_with_real_data(self):
        """Test building distributions with real data subset"""
        subset_df = self.test_dataframe[['ConvertedSalary', 'Country']].head(50)
        result = build_attribute_distributions(subset_df)

        self.assertEqual(len(result), 2)
        self.assertIn('ConvertedSalary', result)
        self.assertIn('Country', result)

    def test_full_json_structure_real_data(self):
        """Test complete JSON structure with real data"""
        subset_df = self.test_dataframe.head(10)
        error_list = []

        result = {
            "columnErrors": convert_error_list_to_dict(error_list),
            "attributes": list(subset_df.columns),
            "attributeDistributions": build_attribute_distributions(subset_df)
        }

        self.assertIn("columnErrors", result)
        self.assertIn("attributes", result)
        self.assertIn("attributeDistributions", result)
        self.assertIsInstance(result["attributes"], list)
        self.assertIsInstance(result["columnErrors"], dict)
        self.assertIsInstance(result["attributeDistributions"], dict)


class TestEdgeCases(unittest.TestCase):

    def test_single_row_dataframe(self):
        """Test with single row dataframe"""
        df = pd.DataFrame({'col': [42]})
        result = get_numeric_stats(df, 'col')

        expected = {
            "numeric": {
                "mean": 42.0,
                "min": 42.0,
                "max": 42.0
            }
        }
        self.assertEqual(result, expected)

    def test_categorical_with_all_unique(self):
        """Test categorical stats with all unique values"""
        df = pd.DataFrame({'col': ['A', 'B', 'C', 'D', 'E']})
        result = get_categorical_stats(df, 'col')

        self.assertEqual(result["categorical"]["categories"], 5)

    def test_numeric_with_identical_values(self):
        """Test numeric stats with identical values"""
        df = pd.DataFrame({'col': [5.0, 5.0, 5.0, 5.0]})
        result = get_numeric_stats(df, 'col')

        self.assertEqual(result["numeric"]["mean"], 5.0)
        self.assertEqual(result["numeric"]["min"], 5.0)
        self.assertEqual(result["numeric"]["max"], 5.0)


if __name__ == '__main__':
    unittest.main()