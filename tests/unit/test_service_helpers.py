"""Tests for service helper functions, including incremental error updates."""

from unittest import TestCase
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from numpy.ma.testutils import assert_equal

from app.server_utils.service_helpers import generate_table_name, get_whole_table_query, run_detectors, create_error_dict, \
    get_range_of_ids_query, is_categorical, create_bins_for_a_numeric_column, get_2d_bins, \
    group_by_attribute, get_error_dist, update_errors_incrementally, DETECTOR_SCOPES
from detectors.common import infer_detector_config


DATASETS_DIR = Path(__file__).resolve().parents[2] / "provided_datasets"


def test_infer_detector_config_adapts_to_small_samples_and_preserves_overrides():
    df = pd.DataFrame({
        "ID": [1, 2, 3],
        "category": ["alpha", "beta", "gamma"],
    })

    adaptive = infer_detector_config(df)
    overridden = infer_detector_config(df, {"rare_value_min_rows": 5})

    assert adaptive["rare_value_min_rows"] > len(df)
    assert overridden["rare_value_min_rows"] == 5


def test_run_detectors_passes_explicit_config_to_detector_callers():
    df = pd.DataFrame({
        "ID": list(range(1, 11)),
        "mostly_numeric": ["1", "2", "3", "4", "5", "6", "7", "8", "bad", "worse"],
    })

    default_errors = run_detectors(df, adaptive_config=False)
    overridden_errors = run_detectors(
        df,
        detector_config={"type_confidence_threshold": 0.75},
        adaptive_config=False,
    )

    assert "mismatch" not in default_errors["error_type"].values
    mismatch_rows = overridden_errors[overridden_errors["error_type"] == "mismatch"]
    assert set(mismatch_rows["row_id"].tolist()) == {9, 10}


def test_update_errors_incrementally_impute_invalidates_only_required_scopes():
    # Impute fills selected cells. Missing-value detection can be rerun only on
    # those cells, while anomaly/mismatch/incomplete must rerun on the changed
    # column because their results depend on column-level context.
    df = pd.DataFrame({
        "ID": [1, 2, 3, 4],
        "score": [10, 20, 30, 40],
        "country": ["US", "CA", "US", "MX"],
    })
    previous_errors = pd.DataFrame({
        "row_id": [3, 2, 4, 1],
        "column_id": ["score", "score", "country", "country"],
        "error_type": ["missing", "anomaly", "missing", "anomaly"],
    })
    calls = []

    def detector_for(error_type, row_id):
        # Fake detectors record which columns/rows they received. That lets the
        # test prove the helper narrowed the recomputation scope correctly.
        def _detector(scoped_df):
            calls.append((error_type, list(scoped_df.columns), scoped_df["ID"].tolist()))
            return {"score": {row_id: error_type}}
        return _detector

    original_specs = {
        name: spec.copy()
        for name, spec in DETECTOR_SCOPES.items()
    }
    try:
        DETECTOR_SCOPES["missing"]["detector"] = lambda scoped_df: {}
        DETECTOR_SCOPES["mismatch"]["detector"] = detector_for("mismatch", 1)
        DETECTOR_SCOPES["anomaly"]["detector"] = detector_for("anomaly", 2)
        DETECTOR_SCOPES["incomplete"]["detector"] = lambda scoped_df: {}

        result = update_errors_incrementally(
            df,
            previous_errors,
            "impute",
            {"operation": "impute", "row_ids": [3], "col": "score"},
        )
    finally:
        DETECTOR_SCOPES.update(original_specs)

    result_records = set(map(tuple, result[["row_id", "column_id", "error_type"]].to_records(index=False)))
    assert (3, "score", "missing") not in result_records
    assert (2, "score", "anomaly") in result_records
    assert (4, "country", "missing") in result_records
    assert (1, "country", "anomaly") in result_records
    assert (1, "score", "mismatch") in result_records
    assert all(columns == ["ID", "score"] for _, columns, _ in calls)


def test_update_errors_incrementally_delete_column_drops_only_deleted_attribute_errors():
    # Deleting a column should remove errors for that attribute while preserving
    # errors from all columns that still exist.
    previous_errors = pd.DataFrame({
        "row_id": [1, 2],
        "column_id": ["unused", "kept"],
        "error_type": ["missing", "anomaly"],
    })

    result = update_errors_incrementally(
        pd.DataFrame({"ID": [1, 2], "kept": [1, 2]}),
        previous_errors,
        "delete-column",
        {"operation": "delete-column", "column": "unused"},
    )

    assert result.to_dict("records") == [
        {"row_id": 2, "column_id": "kept", "error_type": "anomaly"}
    ]


class General(TestCase):
    def test_clean_table_name_removes_csv_extension(self):
        example_table = "sales_data.csv"
        with patch("app.server_utils.service_helpers.random.choices", return_value=list("abc12")):
            cleaned = generate_table_name(example_table)
        print("test_clean_table_name_removes_csv_extension:", cleaned)
        self.assertEqual(cleaned, "sales_data_abc12")

    def test_starts_with_letter(self):
        example_table = "5table.csv"
        with patch("app.server_utils.service_helpers.random.choices", return_value=list("abc12")):
            cleaned = generate_table_name(example_table)
        print("test_starts_with_letter:", cleaned)
        self.assertEqual(cleaned, "5table_abc12")

    def test_no_special_characters(self):
        example_name = "$name.csv"
        with patch("app.server_utils.service_helpers.random.choices", return_value=list("abc12")):
            cleaned = generate_table_name(example_name)
        print("test_no_special_characters:", cleaned)
        self.assertNotIn("$",cleaned)
        self.assertEqual(cleaned, "_name_abc12")

    def test_whole_table_query(self):
        example_name = "$name.csv"
        with patch("app.server_utils.service_helpers.random.choices", return_value=list("abc12")):
            cleaned = generate_table_name(example_name)
        print(cleaned)
        query = get_whole_table_query(cleaned,False)
        print("test_whole_table_query:", query)
        self.assertEqual('SELECT * FROM "_name_abc12"', query)

    def test_run_all_detectors_stackoverflow(self):
        stackoverflow_df = pd.read_csv(DATASETS_DIR / 'stackoverflow_db_uncleaned.csv')
        actual_error_df = run_detectors(stackoverflow_df)
        self.assertIn("error_type", actual_error_df.columns)
        self.assertIn("anomaly", actual_error_df["error_type"].values)
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
        stackoverflow_df = pd.read_csv(DATASETS_DIR / 'complaints-2025-04-21_17_31.csv')
        actual_error_df = run_detectors(stackoverflow_df)

        self.assertIn("error_type", actual_error_df.columns)
        self.assertFalse(actual_error_df.empty)

    def test_create_error_dictionary(self):
        # stackoverflow_df = pd.read_csv('../provided_datasets/stackoverflow_db_uncleaned.csv')
        stackoverflow_df = pd.read_csv(DATASETS_DIR / 'stackoverflow_db_uncleaned.csv')
        res_df = run_detectors(stackoverflow_df)
        result = create_error_dict(res_df,200)
        self.assertIn("ConvertedSalary", result)
        self.assertIn(13, result["ConvertedSalary"])

    def test_get_range_of_ids_query(self):
        expected_query = 'SELECT * FROM "stackoverflow_db_uncleaned" WHERE "ID" BETWEEN 15 AND 256'
        actual_query = get_range_of_ids_query(15,256,"stackoverflow_db_uncleaned",False)
        print(expected_query, actual_query)
        assert_equal(expected_query,actual_query)

    # def test_get1d_bins_basic(self):
    #     stackoverflow_df = pd.read_csv('../../provided_datasets/stackoverflow_db_uncleaned.csv')
    #     expected_series = stackoverflow_df.value_counts(subset="ConvertedSalary")
    #     actual_series = get_1d_bins("ConvertedSalary",100,stackoverflow_df)
    #     pd.testing.assert_series_equal(expected_series,actual_series)

    def test_is_categorical(self):
        stackoverflow_df = pd.read_csv(DATASETS_DIR / 'stackoverflow_db_uncleaned.csv')
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
        stackoverflow_df = pd.read_csv(DATASETS_DIR / 'stackoverflow_db_uncleaned.csv')
        new_df = group_by_attribute(stackoverflow_df,"Age","Continent")
        other_df = stackoverflow_df.pivot_table("ID", index='Age', columns='Continent', aggfunc='count')
        pd.testing.assert_frame_equal(new_df,other_df)

    def test_get_error_dis(self):
        stackoverflow_df = pd.read_csv(DATASETS_DIR / 'stackoverflow_db_uncleaned.csv')
        error_table = run_detectors(stackoverflow_df)
        error_dist = get_error_dist(error_table,stackoverflow_df)
        self.assertIn("error_type", error_dist.columns)
        self.assertIn("ConvertedSalary", error_dist.columns)
