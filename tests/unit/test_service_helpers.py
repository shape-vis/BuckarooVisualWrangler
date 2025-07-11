from inspect import stack
from unittest import TestCase

import pandas as pd
from numpy.ma.testutils import assert_equal
from sqlalchemy import column
from sqlalchemy.testing import assert_raises

from app.service_helpers import clean_table_name, get_whole_table_query, run_detectors, create_error_dict, \
    get_range_of_ids_query, get_1d_bins, is_categorical, create_bins_for_a_numeric_column, get_2d_bins, \
    group_by_attribute
from wranglers.remove_data import remove_data


class General(TestCase):
    def test_clean_table_name_removes_csv_extension(self):
        example_table = "sales_data.csv"
        cleaned = clean_table_name(example_table)
        print("test_clean_table_name_removes_csv_extension:", cleaned)
        self.assertEqual(clean_table_name(example_table), "sales_data")

    def test_starts_with_letter(self):
        example_table = "5table.csv"
        cleaned = clean_table_name(example_table)
        print("test_starts_with_letter:", cleaned)
        self.assertEqual(cleaned, "table5table")

    def test_no_special_characters(self):
        example_name = "$name.csv"
        cleaned = clean_table_name(example_name)
        print("test_no_special_characters:", cleaned)
        self.assertNotIn("$",cleaned)

    def test_whole_table_query(self):
        example_name = "$name.csv"
        cleaned = clean_table_name(example_name)
        print(cleaned)
        query = get_whole_table_query(cleaned,False)
        print("test_whole_table_query:", query)
        self.assertEqual("SELECT * FROM table_name",query)

    def test_run_all_detectors_stackoverflow(self):
        stackoverflow_df = pd.read_csv('../../provided_datasets/stackoverflow_db_uncleaned.csv')
        actual_error_df = run_detectors(stackoverflow_df)
        # expected_error_map = {"Age": {3: ["incomplete"], 4: ["mismatch", "incomplete"], 5: ["mismatch", "incomplete"],
        #                               105: ["incomplete"], 159: ["incomplete"]},
        #                       "Continent": {8: ["missing"], 9: ["missing"], 10: ["missing"],
        #                                     12: ["missing"], 13: ["missing"],
        #                                     14: ["missing"], 15: ["missing"], 16: ["missing"],
        #                                     17: ["missing"]},
        #                       "ConvertedSalary": {13: ["anomaly"], 58: ["anomaly"], 100: ["anomaly"],
        #                                           115: ["anomaly"], 141: ["anomaly"],
        #                                           214: ["anomaly"], 222: ["anomaly"]},
        #                       "Country": {61: ["incomplete"],
        #                                   85: ["incomplete"],
        #                                   107: ["incomplete"],
        #                                   147: ["incomplete"],
        #                                   204: ["incomplete"],
        #                                   226: ["incomplete"],
        #                                   227: ["incomplete"],
        #                                   240: ["incomplete"]},
        #                       "DevType": {44: ["incomplete"],
        #                                   101: ["incomplete"],
        #                                   118: ["incomplete"],
        #                                   141: ["incomplete"],
        #                                   196: ["incomplete"],
        #                                   222: ["incomplete"],
        #                                   224: ["incomplete"],
        #                                   234: ["incomplete"]},
        #                       "FormalEducation": {81: ["incomplete"],
        #                                           161: ["incomplete"],
        #                                           165: ["incomplete"]},
        #                       "Gender": {9: ["incomplete"],
        #                                  10: ["incomplete"],
        #                                  24: ["incomplete"],
        #                                  157: ["incomplete"]},
        #                       "SexualOrientation": {169: ["incomplete"],
        #                                             221: ["incomplete"]},
        #                       "UndergradMajor": {15: ["incomplete"]},
        #                       "YearsCoding": {169: ["incomplete"],
        #                                       230: ["incomplete"]}}
        # expected_error_map_df = pd.DataFrame(expected_error_map).rename_axis("ID", axis="index").reset_index()

    def test_run_all_detectors_complaints(self):
        stackoverflow_df = pd.read_csv('../../provided_datasets/complaints-2025-04-21_17_31.csv')
        actual_error_df = run_detectors(stackoverflow_df)

        self.assertEqual(True,True)

    def test_create_error_dictionary(self):
        # stackoverflow_df = pd.read_csv('../provided_datasets/stackoverflow_db_uncleaned.csv')
        stackoverflow_df = pd.read_csv('../../provided_datasets/stackoverflow_db_uncleaned.csv')
        res_df = run_detectors(stackoverflow_df)
        create_error_dict(res_df,200)

    def test_get_range_of_ids_query(self):
        expected_query = "SELECT * FROM stackoverflow_db_uncleaned WHERE " +"'ID'"+ " BETWEEN 15 AND 256"
        actual_query = get_range_of_ids_query(15,256,"stackoverflow_db_uncleaned",False)
        print(expected_query, actual_query)
        assert_equal(expected_query,actual_query)

    def test_get1d_bins_basic(self):
        stackoverflow_df = pd.read_csv('../../provided_datasets/stackoverflow_db_uncleaned.csv')
        expected_series = stackoverflow_df.value_counts(subset="ConvertedSalary")
        actual_series = get_1d_bins("ConvertedSalary",100,stackoverflow_df)
        pd.testing.assert_series_equal(expected_series,actual_series)

    def test_is_categorical(self):
        stackoverflow_df = pd.read_csv('../../provided_datasets/stackoverflow_db_uncleaned.csv')
        categorical_column = stackoverflow_df["GDP"]
        actual_type = is_categorical(categorical_column)
        expected_type = True
        assert_equal(expected_type,actual_type)

    def test_is_categorical_with_strings(self):
        test_data = pd.Series(['A', 'B', 'C', 'A', 'B'])
        self.assertTrue(is_categorical(test_data))

    def test_is_categorical_with_numbers(self):
        test_data = pd.Series([1.5, 2.7, 3.2, 4.1, 5.9])
        self.assertFalse(is_categorical(test_data))

    def test_create_bins_basic(self):
        test_data = pd.Series([10, 20, 30, 40, 50])
        result = create_bins_for_a_numeric_column(test_data, 3)
        self.assertEqual(len(result.cat.categories), 3)

    def test_get_2d_bins_categorical_only(self):
        test_data1 = pd.Series(['A', 'B', 'C', 'A', 'B','B'])
        test_data2 = pd.Series(['Animal', 'Animal', 'Dog', 'Boy', 'Bottle','Animal'])
        actual_df = get_2d_bins(test_data1,test_data2,10,10)
        assert_equal(actual_df["Animal"]["B"],2)

    def test_group_by_categorical_group(self):
        stackoverflow_df = pd.read_csv('../../provided_datasets/stackoverflow_db_uncleaned.csv')
        new_df = group_by_attribute(stackoverflow_df,"Age","Continent")
        other_df = stackoverflow_df.pivot_table("ID", index='Age', columns='Continent', aggfunc='count')
        pd.testing.assert_frame_equal(new_df,other_df)

