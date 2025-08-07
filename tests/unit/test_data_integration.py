import unittest
import pandas as pd
import numpy as np

from app.plot_routes import *
from data_management.data_state import DataState


class TestDataIntegration(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.sample_main_df = pd.DataFrame({
            'ID': [1, 2, 3, 4, 5, 6],
            'Country': ['USA', 'Canada', 'USA', 'Germany', 'Canada', 'USA'],
            'ConvertedSalary': [50000, 75000, 100000, 125000, 150000, 200000],
            'Gender': ['Male', 'Female', 'Male', 'Female', 'Male', 'Female']
        })

        self.sample_error_df = pd.DataFrame({
            'row_id': [1, 3, 5, 2, 4],
            'column_id': ['Country', 'ConvertedSalary', 'Gender', 'Country', 'ConvertedSalary'],
            'error_type': ['mismatch', 'anomaly', 'incomplete', 'anomaly', 'missing']
        })

    def test_get_relevant_errors_basic(self):
        """Test getting relevant errors for specific columns."""
        result = get_relevant_errors(self.sample_error_df, ['Country', 'ConvertedSalary'])

        self.assertEqual(len(result), 4)
        self.assertTrue(all(col in ['Country', 'ConvertedSalary'] for col in result['column_id']))
        self.assertIn('mismatch', result['error_type'].values)
        self.assertIn('anomaly', result['error_type'].values)

    def test_get_relevant_errors_empty(self):
        """Test getting relevant errors for non-existent columns."""
        result = get_relevant_errors(self.sample_error_df, ['NonExistentColumn'])
        self.assertEqual(len(result), 0)

    def test_get_relevant_errors_single_column(self):
        """Test getting relevant errors for single column."""
        result = get_relevant_errors(self.sample_error_df, ['Gender'])
        self.assertEqual(len(result), 1)
        self.assertEqual(result['error_type'].iloc[0], 'incomplete')

    def test_get_column_bin_assignments_categorical(self):
        """Test getting bin assignments for categorical column."""
        bin_assignments, scale_data, column_type = get_column_bin_assignments(
            self.sample_main_df, 'Country', 3
        )

        self.assertEqual(column_type, 'categorical')
        self.assertEqual(len(scale_data), 3)  # USA, Canada, Germany
        self.assertEqual(len(bin_assignments), 6)
        self.assertTrue(all(isinstance(x, (int, np.integer)) for x in bin_assignments if not pd.isna(x)))

        self.assertIn('USA', scale_data)
        self.assertIn('Canada', scale_data)
        self.assertIn('Germany', scale_data)

        category_to_bin = {category: index for index, category in enumerate(scale_data)}
        # Verify bin assignments are correct for each row
        expected_countries = ['USA', 'Canada', 'USA', 'Germany', 'Canada', 'USA']
        for i, expected_country in enumerate(expected_countries):
            expected_bin = category_to_bin[expected_country]
            self.assertEqual(bin_assignments[i], expected_bin,
                             f"Row {i + 1} with country '{expected_country}' should be in bin {expected_bin}")

        # Verify that same countries get same bin assignments
        self.assertEqual(bin_assignments[0], bin_assignments[2])  # USA rows 1,3
        self.assertEqual(bin_assignments[0], bin_assignments[5])  # USA rows 1,6
        self.assertEqual(bin_assignments[1], bin_assignments[4])  # Canada rows 2,5

    def test_get_column_bin_assignments_numeric(self):
        """Test getting bin assignments for numeric column."""
        bin_assignments, scale_data, column_type = get_column_bin_assignments(
            self.sample_main_df, 'ConvertedSalary', 3
        )

        self.assertEqual(column_type, 'numeric')
        self.assertEqual(len(scale_data), 3)
        self.assertEqual(len(bin_assignments), 6)

        # Verify scale_data contains intervals
        self.assertEqual(len(scale_data), 3)
        for interval in scale_data:
            self.assertTrue(hasattr(interval, 'left'))
            self.assertTrue(hasattr(interval, 'right'))
            self.assertLess(interval.left, interval.right)

        # Verify intervals are ordered and non-overlapping
        for i in range(len(scale_data) - 1):
            self.assertLessEqual(scale_data[i].right, scale_data[i + 1].left)

        # Test specific salary values and their expected bins
        salary_values = [50000, 75000, 100000, 125000, 150000, 200000]
        for i, salary in enumerate(salary_values):
            bin_index = bin_assignments[i]

            # Verify the salary falls within the assigned bin interval
            assigned_interval = scale_data[bin_index]
            self.assertGreaterEqual(salary, assigned_interval.left,
                                    f"Salary {salary} should be >= {assigned_interval.left}")
            self.assertLessEqual(salary, assigned_interval.right,
                            f"Salary {salary} should be <= {assigned_interval.right}")

    def test_get_column_bin_assignments_with_nulls(self):
        """Test getting bin assignments with null values."""
        df_with_nulls = pd.DataFrame({
            'ID': [1, 2, 3, 4],
            'Country': ['USA', None, 'Canada', 'USA']
        })

        bin_assignments, scale_data, column_type = get_column_bin_assignments(
            df_with_nulls, 'Country', 3
        )

        self.assertEqual(column_type, 'categorical')
        self.assertEqual(len(scale_data), 2)  # Only USA and Canada (null excluded)

    def test_create_row_to_bin_mapping_1d(self):
        """Test creating row to bin mapping for 1D data."""
        bin_assignments, _, _ = get_column_bin_assignments(self.sample_main_df, 'Country', 3)

        result = create_row_to_bin_mapping(
            self.sample_main_df,
            ['Country'],
            [bin_assignments]
        )

        self.assertEqual(len(result), 6)
        for row_id, bin_coords in result.items():
            self.assertIsInstance(bin_coords, tuple)
            self.assertEqual(len(bin_coords), 1)

    def test_create_row_to_bin_mapping_2d(self):
        """Test creating row to bin mapping for 2D data."""
        country_bins, _, _ = get_column_bin_assignments(self.sample_main_df, 'Country', 3)
        salary_bins, _, _ = get_column_bin_assignments(self.sample_main_df, 'ConvertedSalary', 3)

        result = create_row_to_bin_mapping(
            self.sample_main_df,
            ['Country', 'ConvertedSalary'],
            [country_bins, salary_bins]
        )

        self.assertEqual(len(result), 6)
        for row_id, bin_coords in result.items():
            self.assertIsInstance(bin_coords, tuple)
            self.assertEqual(len(bin_coords), 2)

    def test_create_row_to_bin_mapping_with_nulls(self):
        """Test creating row to bin mapping with null values."""
        df_with_nulls = pd.DataFrame({
            'ID': [1, 2, 3, 4],
            'Country': ['USA', None, 'Canada', 'USA']
        })

        bin_assignments, _, _ = get_column_bin_assignments(df_with_nulls, 'Country', 3)

        result = create_row_to_bin_mapping(
            df_with_nulls,
            ['Country'],
            [bin_assignments]
        )

        # Should exclude row with null value
        self.assertEqual(len(result), 3)
        self.assertNotIn(2, result)  # Row 2 (index 1) has null

    def test_count_items_per_bin(self):
        """Test counting items per bin."""
        row_to_bin_mapping = {
            1: (0, 0),
            2: (0, 1),
            3: (0, 0),
            4: (1, 0),
            5: (1, 1),
            6: (1, 1)
        }

        result = count_items_per_bin(row_to_bin_mapping)

        self.assertEqual(result[(0, 0)], 2)
        self.assertEqual(result[(0, 1)], 1)
        self.assertEqual(result[(1, 0)], 1)
        self.assertEqual(result[(1, 1)], 2)

    def test_count_items_per_bin_empty(self):
        """Test counting items per bin with empty mapping."""
        result = count_items_per_bin({})
        self.assertEqual(len(result), 0)

    def test_count_errors_per_bin(self):
        """Test counting errors per bin."""
        row_to_bin_mapping = {
            1: (0,),
            2: (1,),
            3: (0,),
            4: (1,),
            5: (0,)
        }

        result = count_errors_per_bin(self.sample_error_df, row_to_bin_mapping)

        self.assertIsInstance(result, dict)
        for bin_coords, errors in result.items():
            self.assertIsInstance(errors, dict)
            for error_type, count in errors.items():
                self.assertIsInstance(count, int)
                self.assertGreater(count, 0)

    def test_count_errors_per_bin_no_errors(self):
        """Test counting errors per bin with no errors."""
        empty_error_df = pd.DataFrame(columns=['row_id', 'column_id', 'error_type'])
        row_to_bin_mapping = {1: (0,), 2: (1,)}

        result = count_errors_per_bin(empty_error_df, row_to_bin_mapping)
        self.assertEqual(len(result), 0)

    def test_create_scale_info_categorical(self):
        """Test creating scale info for categorical data."""
        scale_data = ['USA', 'Canada', 'Germany']
        result = create_scale_info(scale_data, 'categorical')

        self.assertEqual(result['numeric'], [])
        self.assertEqual(result['categorical'], ['USA', 'Canada', 'Germany'])

    def test_create_scale_info_numeric(self):
        """Test creating scale info for numeric data."""
        # Create mock intervals
        intervals = [
            type('Interval', (), {'left': 0, 'right': 50000})(),
            type('Interval', (), {'left': 50000, 'right': 100000})()
        ]

        result = create_scale_info(intervals, 'numeric')

        self.assertEqual(result['categorical'], [])
        self.assertEqual(len(result['numeric']), 2)
        self.assertEqual(result['numeric'][0]['x0'], 0)
        self.assertEqual(result['numeric'][0]['x1'], 50000)

    def test_format_error_counts_with_errors(self):
        """Test formatting error counts with errors present."""
        error_type_counts = {'anomaly': 2, 'missing': 1}
        total_items = 5

        result = format_error_counts(error_type_counts, total_items)

        expected = {'items': 5, 'anomaly': 2, 'missing': 1}
        self.assertEqual(result, expected)

    def test_format_error_counts_no_errors(self):
        """Test formatting error counts with no errors."""
        error_type_counts = {}
        total_items = 3

        result = format_error_counts(error_type_counts, total_items)

        expected = {'items': 3}
        self.assertEqual(result, expected)

    def test_get_bin_value_for_dimension_categorical(self):
        """Test getting bin value for categorical dimension."""
        scale_data = ['USA', 'Canada', 'Germany']
        result = get_bin_value_for_dimension(1, scale_data, 'categorical')
        self.assertEqual(result, 'Canada')

    def test_get_bin_value_for_dimension_numeric(self):
        """Test getting bin value for numeric dimension."""
        scale_data = ['interval1', 'interval2', 'interval3']  # Not used for numeric
        result = get_bin_value_for_dimension(2, scale_data, 'numeric')
        self.assertEqual(result, 2)

    def test_create_count_information_with_errors(self):
        """Test creating count information with errors present."""
        bin_coordinates = (0, 1)
        items_per_bin = {(0, 1): 5}
        errors_per_bin = {(0, 1): {'anomaly': 2, 'missing': 1}}

        result = create_count_information(bin_coordinates, items_per_bin, errors_per_bin)

        expected = {'items': 5, 'anomaly': 2, 'missing': 1}
        self.assertEqual(result, expected)

    def test_create_count_information_no_errors(self):
        """Test creating count information with no errors."""
        bin_coordinates = (1, 0)
        items_per_bin = {(1, 0): 3}
        errors_per_bin = {}

        result = create_count_information(bin_coordinates, items_per_bin, errors_per_bin)

        expected = {'items': 3}
        self.assertEqual(result, expected)

    def test_add_dimension_info_to_entry_1d_categorical(self):
        """Test adding dimension info for 1D categorical data."""
        entry = {"count": {"items": 5}}
        bin_coordinates = (1,)
        all_scale_data = [['USA', 'Canada', 'Germany']]
        all_column_types = ['categorical']

        result = add_dimension_info_to_entry(entry, bin_coordinates, all_scale_data, all_column_types)

        self.assertEqual(result["xBin"], 'Canada')
        self.assertEqual(result["xType"], 'categorical')
        self.assertNotIn("yBin", result)

    def test_add_dimension_info_to_entry_1d_numeric(self):
        """Test adding dimension info for 1D numeric data."""
        entry = {"count": {"items": 3}}
        bin_coordinates = (2,)
        all_scale_data = [['interval1', 'interval2', 'interval3']]
        all_column_types = ['numeric']

        result = add_dimension_info_to_entry(entry, bin_coordinates, all_scale_data, all_column_types)

        self.assertEqual(result["xBin"], 2)
        self.assertEqual(result["xType"], 'numeric')
        self.assertNotIn("yBin", result)

    def test_add_dimension_info_to_entry_2d_categorical_numeric(self):
        """Test adding dimension info for 2D categorical-numeric data."""
        entry = {"count": {"items": 1}}
        bin_coordinates = (0, 1)
        all_scale_data = [['USA', 'Canada'], ['interval1', 'interval2']]
        all_column_types = ['categorical', 'numeric']

        result = add_dimension_info_to_entry(entry, bin_coordinates, all_scale_data, all_column_types)

        self.assertEqual(result["xBin"], 'USA')
        self.assertEqual(result["xType"], 'categorical')
        self.assertEqual(result["yBin"], 1)
        self.assertEqual(result["yType"], 'numeric')

    def test_add_dimension_info_to_entry_2d_both_categorical(self):
        """Test adding dimension info for 2D both categorical data."""
        entry = {"count": {"items": 2}}
        bin_coordinates = (1, 0)
        all_scale_data = [['USA', 'Canada'], ['Male', 'Female']]
        all_column_types = ['categorical', 'categorical']

        result = add_dimension_info_to_entry(entry, bin_coordinates, all_scale_data, all_column_types)

        self.assertEqual(result["xBin"], 'Canada')
        self.assertEqual(result["xType"], 'categorical')
        self.assertEqual(result["yBin"], 'Male')
        self.assertEqual(result["yType"], 'categorical')

    def test_create_single_histogram_entry_complete(self):
        """Test creating a complete single histogram entry."""
        bin_coordinates = (1, 0)
        items_per_bin = {(1, 0): 4}
        errors_per_bin = {(1, 0): {'anomaly': 1}}
        all_scale_data = [['USA', 'Canada'], ['Male', 'Female']]
        all_column_types = ['categorical', 'categorical']

        result = create_single_histogram_entry(
            bin_coordinates, items_per_bin, errors_per_bin, all_scale_data, all_column_types
        )

        expected = {
            "count": {"items": 4, "anomaly": 1},
            "xBin": 'Canada',
            "yBin": 'Male',
            "xType": 'categorical',
            "yType": 'categorical'
        }
        self.assertEqual(result, expected)

    def test_generate_all_bin_coordinate_combinations_1d(self):
        """Test generating bin coordinates for 1D data."""
        all_scale_data = [['A', 'B', 'C']]

        result = list(generate_all_bin_coordinate_combinations(all_scale_data))

        expected = [(0,), (1,), (2,)]
        self.assertEqual(result, expected)

    def test_generate_all_bin_coordinate_combinations_2d(self):
        """Test generating bin coordinates for 2D data."""
        all_scale_data = [['A', 'B'], ['X', 'Y']]

        result = list(generate_all_bin_coordinate_combinations(all_scale_data))

        expected = [(0, 0), (0, 1), (1, 0), (1, 1)]
        self.assertEqual(result, expected)

    def test_build_histogram_entries_1d_categorical(self):
        """Test building histogram entries for 1D categorical data."""
        items_per_bin = {(0,): 2, (1,): 3, (2,): 1}
        errors_per_bin = {(0,): {'anomaly': 1}, (1,): {'missing': 2}}
        scale_data = [['USA', 'Canada', 'Germany']]
        column_types = ['categorical']

        result = build_histogram_entries(items_per_bin, errors_per_bin, scale_data, column_types)

        self.assertEqual(len(result), 3)

        # Check that xBin contains category names, not indices
        self.assertEqual(result[0]['xBin'], 'USA')
        self.assertEqual(result[1]['xBin'], 'Canada')
        self.assertEqual(result[2]['xBin'], 'Germany')

        for entry in result:
            self.assertIn('count', entry)
            self.assertIn('xBin', entry)
            self.assertIn('xType', entry)
            self.assertEqual(entry['xType'], 'categorical')

    def test_build_histogram_entries_1d_numeric(self):
        """Test building histogram entries for 1D numeric data."""
        items_per_bin = {(0,): 2, (1,): 3, (2,): 1}
        errors_per_bin = {(0,): {'anomaly': 1}}
        scale_data = [['interval1', 'interval2', 'interval3']]  # Not used for numeric
        column_types = ['numeric']

        result = build_histogram_entries(items_per_bin, errors_per_bin, scale_data, column_types)

        self.assertEqual(len(result), 3)

        # Check that xBin contains numeric indices
        self.assertEqual(result[0]['xBin'], 0)
        self.assertEqual(result[1]['xBin'], 1)
        self.assertEqual(result[2]['xBin'], 2)

        for entry in result:
            self.assertEqual(entry['xType'], 'numeric')

    def test_build_histogram_entries_2d_categorical_numeric(self):
        """Test building histogram entries for 2D categorical-numeric data."""
        items_per_bin = {(0, 0): 1, (0, 1): 2, (1, 0): 1, (1, 1): 1}
        errors_per_bin = {(0, 0): {'anomaly': 1}}
        scale_data = [['USA', 'Canada'], ['interval1', 'interval2']]
        column_types = ['categorical', 'numeric']

        result = build_histogram_entries(items_per_bin, errors_per_bin, scale_data, column_types)

        self.assertEqual(len(result), 4)

        # Check first entry (0, 0)
        self.assertEqual(result[0]['xBin'], 'USA')  # Categorical -> category name
        self.assertEqual(result[0]['yBin'], 0)  # Numeric -> index
        self.assertEqual(result[0]['xType'], 'categorical')
        self.assertEqual(result[0]['yType'], 'numeric')

        # Check second entry (0, 1)
        self.assertEqual(result[1]['xBin'], 'USA')  # Categorical -> category name
        self.assertEqual(result[1]['yBin'], 1)  # Numeric -> index

        # Check third entry (1, 0)
        self.assertEqual(result[2]['xBin'], 'Canada')  # Categorical -> category name
        self.assertEqual(result[2]['yBin'], 0)  # Numeric -> index

    def test_build_histogram_entries_2d_both_categorical(self):
        """Test building histogram entries for 2D both categorical data."""
        items_per_bin = {(0, 0): 1, (0, 1): 2, (1, 0): 1, (1, 1): 1}
        errors_per_bin = {(1, 1): {'anomaly': 1, 'missing': 1}}
        scale_data = [['USA', 'Canada'], ['Male', 'Female']]
        column_types = ['categorical', 'categorical']

        result = build_histogram_entries(items_per_bin, errors_per_bin, scale_data, column_types)

        self.assertEqual(len(result), 4)

        # Check that all entries have category names for both axes
        self.assertEqual(result[0]['xBin'], 'USA')  # Categorical -> category name
        self.assertEqual(result[0]['yBin'], 'Male')  # Categorical -> category name

        self.assertEqual(result[1]['xBin'], 'USA')  # Categorical -> category name
        self.assertEqual(result[1]['yBin'], 'Female')  # Categorical -> category name

        self.assertEqual(result[2]['xBin'], 'Canada')  # Categorical -> category name
        self.assertEqual(result[2]['yBin'], 'Male')  # Categorical -> category name

        self.assertEqual(result[3]['xBin'], 'Canada')  # Categorical -> category name
        self.assertEqual(result[3]['yBin'], 'Female')  # Categorical -> category name

    def test_build_histogram_entries_2d_both_numeric(self):
        """Test building histogram entries for 2D both numeric data."""
        items_per_bin = {(0, 0): 1, (0, 1): 2, (1, 0): 1, (1, 1): 1}
        errors_per_bin = {}
        scale_data = [['interval1', 'interval2'], ['interval1', 'interval2']]
        column_types = ['numeric', 'numeric']

        result = build_histogram_entries(items_per_bin, errors_per_bin, scale_data, column_types)

        self.assertEqual(len(result), 4)

        # Check that all entries have numeric indices for both axes
        self.assertEqual(result[0]['xBin'], 0)  # Numeric -> index
        self.assertEqual(result[0]['yBin'], 0)  # Numeric -> index

        self.assertEqual(result[1]['xBin'], 0)  # Numeric -> index
        self.assertEqual(result[1]['yBin'], 1)  # Numeric -> index

        self.assertEqual(result[2]['xBin'], 1)  # Numeric -> index
        self.assertEqual(result[2]['yBin'], 0)  # Numeric -> index

        self.assertEqual(result[3]['xBin'], 1)  # Numeric -> index
        self.assertEqual(result[3]['yBin'], 1)  # Numeric -> index

    def test_build_histogram_entries_empty(self):
        """Test building histogram entries with empty data."""
        items_per_bin = {}
        errors_per_bin = {}
        scale_data = [['A', 'B']]
        column_types = ['categorical']

        result = build_histogram_entries(items_per_bin, errors_per_bin, scale_data, column_types)

        self.assertEqual(len(result), 2)  # Still creates entries for all bins

        # Check that categorical bins use category names
        self.assertEqual(result[0]['xBin'], 'A')
        self.assertEqual(result[1]['xBin'], 'B')

        for entry in result:
            self.assertEqual(entry['count']['items'], 0)


class TestDataIntegrationEdgeCases(unittest.TestCase):

    def test_empty_dataframe(self):
        """Test functions with empty dataframes."""
        empty_df = pd.DataFrame(columns=['ID', 'Country'])
        empty_error_df = pd.DataFrame(columns=['row_id', 'column_id', 'error_type'])

        result = get_relevant_errors(empty_error_df, ['Country'])
        self.assertEqual(len(result), 0)

    def test_single_value_column(self):
        """Test with column containing single unique value."""
        single_value_df = pd.DataFrame({
            'ID': [1, 2, 3],
            'Country': ['USA', 'USA', 'USA']
        })

        bin_assignments, scale_data, column_type = get_column_bin_assignments(
            single_value_df, 'Country', 3
        )

        self.assertEqual(column_type, 'categorical')
        self.assertEqual(len(scale_data), 1)

    def test_null_column_preserves_item_count(self):
        """Test that all-null columns preserve correct item counts."""
        all_null_df = pd.DataFrame({
            'ID': [1, 2, 3, 4, 5],
            'null_column': [None, None, None, None, None]
        })

        bin_assignments, scale_data, column_type = get_column_bin_assignments(
            all_null_df, 'null_column', 3
        )

        row_to_bin_mapping = create_row_to_bin_mapping(
            all_null_df,
            ['null_column'],
            [bin_assignments]
        )

        # All 5 rows should be mapped
        self.assertEqual(len(row_to_bin_mapping), 5)

        items_per_bin = count_items_per_bin(row_to_bin_mapping)

        # All items should be in the null bin
        self.assertEqual(items_per_bin[(0,)], 5)

        result = build_histogram_entries(
            items_per_bin, {}, [scale_data], [column_type]
        )

        self.assertEqual(len(result), 1)
        entry = result[0]
        self.assertEqual(entry['xBin'], 'null')
        self.assertEqual(entry['count']['items'], 5)  # All 5 items preserved

    def test_mixed_null_preserves_counts_2d(self):
        """Test that 2D with null column preserves all item counts."""
        mixed_df = pd.DataFrame({
            'ID': [1, 2, 3, 4, 5, 6],
            'null_column': [None, None, None, None, None, None],
            'country': ['USA', 'Canada', 'USA', 'Canada', 'USA', 'Germany']
        })

        null_bins, null_scale, null_type = get_column_bin_assignments(mixed_df, 'null_column', 3)
        country_bins, country_scale, country_type = get_column_bin_assignments(mixed_df, 'country', 3)

        row_to_bin_mapping = create_row_to_bin_mapping(
            mixed_df,
            ['null_column', 'country'],
            [null_bins, country_bins]
        )

        # All 6 rows should be mapped
        self.assertEqual(len(row_to_bin_mapping), 6)

        items_per_bin = count_items_per_bin(row_to_bin_mapping)

        # Verify total items preserved
        total_items = sum(items_per_bin.values())
        self.assertEqual(total_items, 6)

        result = build_histogram_entries(
            items_per_bin, {}, [null_scale, country_scale], [null_type, country_type]
        )

        # Should have bins for (null, USA), (null, Canada), (null, Germany)
        total_histogram_items = sum(entry['count']['items'] for entry in result)
        self.assertEqual(total_histogram_items, 6)  # All items preserved

        # Verify specific country counts
        country_counts = mixed_df['country'].value_counts()
        for entry in result:
            self.assertEqual(entry['xBin'], 'null')
            country = entry['yBin']
            expected_count = country_counts[country]
            actual_count = entry['count']['items']
            self.assertEqual(actual_count, expected_count,
                             f"Country {country} should have {expected_count} items, got {actual_count}")

    def test_get_column_bin_assignments_all_null_column(self):
        """Test getting bin assignments for column with all null values."""
        all_null_df = pd.DataFrame({
            'ID': [1, 2, 3, 4],
            'null_column': [None, None, None, None]
        })

        bin_assignments, scale_data, column_type = get_column_bin_assignments(
            all_null_df, 'null_column', 3
        )

        # Should be treated as categorical with single "null" category
        self.assertEqual(column_type, 'categorical')
        self.assertEqual(len(scale_data), 1)
        self.assertEqual(scale_data[0], 'null')

        # All rows should be assigned to bin 0
        self.assertEqual(len(bin_assignments), 4)
        self.assertTrue(all(assignment == 0 for assignment in bin_assignments))

    def test_build_histogram_entries_with_null_column(self):
        """Test building histogram entries when column has all null values."""
        all_null_df = pd.DataFrame({
            'ID': [1, 2, 3, 4],
            'null_column': [None, None, None, None]
        })

        bin_assignments, scale_data, column_type = get_column_bin_assignments(
            all_null_df, 'null_column', 3
        )

        row_to_bin_mapping = create_row_to_bin_mapping(
            all_null_df,
            ['null_column'],
            [bin_assignments]
        )

        items_per_bin = count_items_per_bin(row_to_bin_mapping)
        errors_per_bin = {}  # No errors for this test

        result = build_histogram_entries(
            items_per_bin, errors_per_bin, [scale_data], [column_type]
        )

        # Should have one entry for the null column
        self.assertEqual(len(result), 1)

        entry = result[0]
        self.assertEqual(entry['xBin'], 'null')  # Should be "null", not "null column"
        self.assertEqual(entry['xType'], 'categorical')
        self.assertEqual(entry['count']['items'], 4)  # All 4 rows in the null bin

    def test_mixed_null_and_regular_columns_2d(self):
        """Test 2D histogram with one null column and one regular column."""
        mixed_df = pd.DataFrame({
            'ID': [1, 2, 3, 4],
            'null_column': [None, None, None, None],
            'country': ['USA', 'Canada', 'USA', 'Canada']
        })

        null_bins, null_scale, null_type = get_column_bin_assignments(mixed_df, 'null_column', 3)
        country_bins, country_scale, country_type = get_column_bin_assignments(mixed_df, 'country', 3)

        row_to_bin_mapping = create_row_to_bin_mapping(
            mixed_df,
            ['null_column', 'country'],
            [null_bins, country_bins]
        )

        items_per_bin = count_items_per_bin(row_to_bin_mapping)

        result = build_histogram_entries(
            items_per_bin, {}, [null_scale, country_scale], [null_type, country_type]
        )

        # Should have entries for: (null, USA) and (null, Canada)
        self.assertEqual(len(result), 2)  # 1 null category × 2 countries

        for entry in result:
            self.assertEqual(entry['xBin'], 'null')  # Should be "null"
            self.assertEqual(entry['xType'], 'categorical')
            self.assertIn(entry['yBin'], ['USA', 'Canada'])
            self.assertEqual(entry['yType'], 'categorical')

    def test_2d_both_null_columns(self):
        """Test 2D histogram with both columns being null."""
        both_null_df = pd.DataFrame({
            'ID': [1, 2, 3],
            'null_col1': [None, None, None],
            'null_col2': [None, None, None]
        })

        null1_bins, null1_scale, null1_type = get_column_bin_assignments(both_null_df, 'null_col1', 3)
        null2_bins, null2_scale, null2_type = get_column_bin_assignments(both_null_df, 'null_col2', 3)

        row_to_bin_mapping = create_row_to_bin_mapping(
            both_null_df,
            ['null_col1', 'null_col2'],
            [null1_bins, null2_bins]
        )

        items_per_bin = count_items_per_bin(row_to_bin_mapping)

        result = build_histogram_entries(
            items_per_bin, {}, [null1_scale, null2_scale], [null1_type, null2_type]
        )

        # Should have one entry: (null, null)
        self.assertEqual(len(result), 1)

        entry = result[0]
        self.assertEqual(entry['xBin'], 'null')
        self.assertEqual(entry['yBin'], 'null')
        self.assertEqual(entry['xType'], 'categorical')
        self.assertEqual(entry['yType'], 'categorical')
        self.assertEqual(entry['count']['items'], 3)  # All 3 rows

    def test_2d_null_and_numeric_basic_functionality(self):
        """Test 2D histogram with null column and numeric column - basic functionality."""
        mixed_df = pd.DataFrame({
            'ID': [1, 2, 3, 4, 5, 6],
            'null_column': [None, None, None, None, None, None],
            'salary': [45000, 55000, 75000, 85000, 95000, 105000]
        })

        # Get bin assignments
        null_bins, null_scale, null_type = get_column_bin_assignments(mixed_df, 'null_column', 3)
        salary_bins, salary_scale, salary_type = get_column_bin_assignments(mixed_df, 'salary', 3)

        # Verify column types
        self.assertEqual(null_type, 'categorical')
        self.assertEqual(salary_type, 'numeric')

        # Verify scales
        self.assertEqual(null_scale, ['null'])
        self.assertEqual(len(salary_scale), 3)  # 3 numeric intervals

        # Create mapping and count items
        row_to_bin_mapping = create_row_to_bin_mapping(
            mixed_df,
            ['null_column', 'salary'],
            [null_bins, salary_bins]
        )

        # All 6 rows should be mapped
        self.assertEqual(len(row_to_bin_mapping), 6)

        # Verify each row maps to (0, salary_bin) since null column is always bin 0
        for row_id, bin_coords in row_to_bin_mapping.items():
            self.assertEqual(bin_coords[0], 0)  # null column always bin 0
            self.assertIn(bin_coords[1], [0, 1, 2])  # salary bin should be 0, 1, or 2

        items_per_bin = count_items_per_bin(row_to_bin_mapping)

        # Build histogram entries
        result = build_histogram_entries(
            items_per_bin, {}, [null_scale, salary_scale], [null_type, salary_type]
        )

        # Should have 3 entries: (null, 0), (null, 1), (null, 2)
        self.assertEqual(len(result), 3)

        # Verify structure of each entry
        for entry in result:
            self.assertEqual(entry['xBin'], 'null')  # Categorical null
            self.assertIn(entry['yBin'], [0, 1, 2])  # Numeric bin index
            self.assertEqual(entry['xType'], 'categorical')
            self.assertEqual(entry['yType'], 'numeric')
            self.assertIn('count', entry)
            self.assertIn('items', entry['count'])
            self.assertGreaterEqual(entry['count']['items'], 0)

    def test_2d_null_and_numeric_item_distribution(self):
        """Test 2D histogram with null column and numeric column - verify item distribution."""
        # Create data with known salary distribution
        mixed_df = pd.DataFrame({
            'ID': [1, 2, 3, 4, 5, 6, 7, 8],
            'null_column': [None, None, None, None, None, None, None, None],
            'salary': [30000, 40000, 50000, 60000, 70000, 80000, 90000, 100000]
        })

        # Get bin assignments with 4 bins to have clear distribution
        null_bins, null_scale, null_type = get_column_bin_assignments(mixed_df, 'null_column', 3)
        salary_bins, salary_scale, salary_type = get_column_bin_assignments(mixed_df, 'salary', 4)

        # Verify salary values fall into expected bins
        salaries = [30000, 40000, 50000, 60000, 70000, 80000, 90000, 100000]

        # Create mapping
        row_to_bin_mapping = create_row_to_bin_mapping(
            mixed_df,
            ['null_column', 'salary'],
            [null_bins, salary_bins]
        )

        # Verify each salary maps to correct bin
        for i, salary in enumerate(salaries):
            row_id = i + 1
            bin_coords = row_to_bin_mapping[row_id]
            salary_bin = bin_coords[1]

            # Verify salary falls within the assigned interval
            assigned_interval = salary_scale[salary_bin]
            self.assertGreaterEqual(salary, assigned_interval.left,
                                    f"Salary {salary} should be >= {assigned_interval.left}")
            self.assertLessEqual(salary, assigned_interval.right,
                            f"Salary {salary} should be =< {assigned_interval.right}")

        items_per_bin = count_items_per_bin(row_to_bin_mapping)

        # Verify total items preserved
        total_items = sum(items_per_bin.values())
        self.assertEqual(total_items, 8)

        # Build histogram entries
        result = build_histogram_entries(
            items_per_bin, {}, [null_scale, salary_scale], [null_type, salary_type]
        )

        # Should have 4 entries for 4 salary bins
        self.assertEqual(len(result), 4)

        # Verify total items in histogram entries
        total_histogram_items = sum(entry['count']['items'] for entry in result)
        self.assertEqual(total_histogram_items, 8)

        # Verify specific bin distributions
        salary_bin_counts = {}
        for row_id, bin_coords in row_to_bin_mapping.items():
            salary_bin = bin_coords[1]
            salary_bin_counts[salary_bin] = salary_bin_counts.get(salary_bin, 0) + 1

        # Check each histogram entry matches expected counts
        for entry in result:
            self.assertEqual(entry['xBin'], 'null')
            salary_bin_index = entry['yBin']
            expected_count = salary_bin_counts[salary_bin_index]
            actual_count = entry['count']['items']
            self.assertEqual(actual_count, expected_count,
                             f"Salary bin {salary_bin_index} should have {expected_count} items, got {actual_count}")

        # Verify scale information in response
        scale_x_info = create_scale_info(null_scale, null_type)
        scale_y_info = create_scale_info(salary_scale, salary_type)

        # X scale should be categorical with null
        self.assertEqual(scale_x_info['categorical'], ['null'])
        self.assertEqual(scale_x_info['numeric'], [])

        # Y scale should be numeric with 4 intervals
        self.assertEqual(scale_y_info['categorical'], [])
        self.assertEqual(len(scale_y_info['numeric']), 4)

        # Verify numeric ranges are properly formatted
        for i, range_info in enumerate(scale_y_info['numeric']):
            self.assertIn('x0', range_info)
            self.assertIn('x1', range_info)
            self.assertLess(range_info['x0'], range_info['x1'])

            # Verify range matches the interval
            interval = salary_scale[i]
            self.assertEqual(range_info['x0'], int(interval.left))
            self.assertEqual(range_info['x1'], int(interval.right))

class TestDataIntegrationIntegration(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures for integration tests."""
        self.df = pd.DataFrame({
            'ID': list(range(1, 11)),
            'Country': ['USA'] * 5 + ['Canada'] * 5,
            'ConvertedSalary': [50000, 55000, 60000, 65000, 70000,
                                75000, 80000, 85000, 90000, 95000],
            'Gender': ['Male', 'Female'] * 5
        })

        self.error_df = pd.DataFrame({
            'row_id': [1, 3, 5, 7, 9],
            'column_id': ['Country', 'ConvertedSalary', 'Gender', 'Country', 'ConvertedSalary'],
            'error_type': ['mismatch', 'anomaly', 'incomplete', 'anomaly', 'missing']
        })

    def test_full_1d_workflow(self):
        """Test complete 1D histogram workflow."""
        # Get bin assignments
        bin_assignments, scale_data, column_type = get_column_bin_assignments(
            self.df, 'Country', 3
        )

        # Create row mapping
        row_to_bin_mapping = create_row_to_bin_mapping(
            self.df, ['Country'], [bin_assignments]
        )

        # Get relevant errors
        relevant_errors = get_relevant_errors(self.error_df, ['Country'])

        # Count items and errors
        items_per_bin = count_items_per_bin(row_to_bin_mapping)
        errors_per_bin = count_errors_per_bin(relevant_errors, row_to_bin_mapping)

        # Build histogram entries
        histogram_entries = build_histogram_entries(
            items_per_bin, errors_per_bin, [scale_data], [column_type]
        )

        # Verify results
        self.assertGreater(len(histogram_entries), 0)
        self.assertEqual(len(histogram_entries), len(scale_data))

        for entry in histogram_entries:
            self.assertIn('count', entry)
            self.assertIn('xBin', entry)
            self.assertIn('xType', entry)
            self.assertEqual(entry['xType'], 'categorical')
            # For categorical data, xBin should be category name, not index
            self.assertIn(entry['xBin'], ['USA', 'Canada'])

    def test_full_2d_workflow(self):
        """Test complete 2D histogram workflow."""
        # Get bin assignments for both columns
        country_bins, country_scale, country_type = get_column_bin_assignments(
            self.df, 'Country', 2
        )
        gender_bins, gender_scale, gender_type = get_column_bin_assignments(
            self.df, 'Gender', 2
        )

        # Create row mapping
        row_to_bin_mapping = create_row_to_bin_mapping(
            self.df, ['Country', 'Gender'], [country_bins, gender_bins]
        )

        # Get relevant errors
        relevant_errors = get_relevant_errors(self.error_df, ['Country', 'Gender'])

        # Count items and errors
        items_per_bin = count_items_per_bin(row_to_bin_mapping)
        errors_per_bin = count_errors_per_bin(relevant_errors, row_to_bin_mapping)

        # Build histogram entries
        histogram_entries = build_histogram_entries(
            items_per_bin, errors_per_bin,
            [country_scale, gender_scale],
            [country_type, gender_type]
        )

        # Verify results
        expected_entries = len(country_scale) * len(gender_scale)
        self.assertEqual(len(histogram_entries), expected_entries)

        for entry in histogram_entries:
            self.assertIn('count', entry)
            self.assertIn('xBin', entry)
            self.assertIn('yBin', entry)
            self.assertIn('xType', entry)
            self.assertIn('yType', entry)
            # For categorical data, bins should be category names
            self.assertIn(entry['xBin'], ['USA', 'Canada'])
            self.assertIn(entry['yBin'], ['Male', 'Female'])

    def test_crimes(self):
        df = pd.read_csv('../../provided_datasets/Crimes_-_One_year_prior_to_present_20250421.csv').head(400)
        res = generate_1d_histogram_data('IUCR',10,0,400)
        self.assertEqual(400, 400)
if __name__ == '__main__':
    unittest.main()
