"""Tests for the attribute summary JSON shown in the left-side UI panel."""

import unittest
from pathlib import Path

import pandas as pd

from app.server_utils.data_attribute_summary_integration import get_categorical_stats, get_numeric_stats, \
    build_attribute_distributions, build_attribute_profiles, convert_error_list_to_dict, generate_complete_json, \
    format_attribute_profile_record


DATASETS_DIR = Path(__file__).resolve().parents[2] / "provided_datasets"


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
        df = pd.read_csv(DATASETS_DIR / 'complaints-2025-04-21_17_31.csv').head(400)
        res = build_attribute_distributions(df)
        self.assertIn("Complaint ID", res)

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


class TestBuildAttributeProfiles(unittest.TestCase):

    def test_build_profiles_contains_explainability_fields(self):
        df = pd.DataFrame({
            "created_at": pd.date_range("2026-01-01", periods=120, freq="h").astype(str),
            "sale_price": [9.99, 12.50, 18.75, 12.50] * 30,
            "city": [f"City {index}" for index in range(120)],
        })

        result = build_attribute_profiles(df)

        self.assertIn("created_at", result)
        self.assertIn("sale_price", result)
        self.assertIn("city", result)
        self.assertEqual(result["created_at"]["roleLabel"], "high-uniqueness timestamp")
        self.assertIn("Timestamp uniqueness alone", result["created_at"]["warning"])
        self.assertEqual(result["sale_price"]["topCandidateRole"], "numeric_measure")
        self.assertIsInstance(result["sale_price"]["candidateRoles"], list)
        self.assertIsNotNone(result["sale_price"]["confidenceScore"])
        chosen_sale_price_candidates = [
            candidate for candidate in result["sale_price"]["candidateRoles"]
            if candidate["chosen"]
        ]
        self.assertEqual(len(chosen_sale_price_candidates), 1)
        self.assertEqual(result["sale_price"]["chosenCandidateRole"], "numeric_measure")
        self.assertEqual(
            result["sale_price"]["chosenCandidateConfidence"],
            result["sale_price"]["confidenceScore"],
        )
        self.assertEqual(
            chosen_sale_price_candidates[0]["confidence"],
            result["sale_price"]["confidenceScore"],
        )
        self.assertIsNotNone(chosen_sale_price_candidates[0]["evidenceStrength"])
        self.assertEqual(result["city"]["roleLabel"], "high-uniqueness location field")
        self.assertTrue(result["city"]["warning"])
        self.assertTrue(result["city"]["positiveEvidence"])
        self.assertTrue(result["city"]["negativeEvidence"])
        self.assertTrue(result["sale_price"]["supportingExamples"])
        self.assertEqual(result["sale_price"]["conflictingExamples"], [])
        self.assertTrue(any(
            "location" in evidence.lower()
            for evidence in result["city"]["negativeEvidence"]
        ))
        self.assertTrue(any(
            "numbers" in evidence.lower()
            for evidence in result["sale_price"]["positiveEvidence"]
        ))

    def test_chosen_candidate_stays_visible_when_not_in_top_four(self):
        result = format_attribute_profile_record({
            "column": "notes",
            "role": "free_text",
            "profile_role": "free_text",
            "confidence": "low",
            "confidence_score": 0.41,
            "chosen_candidate_role": "free_text",
            "chosen_candidate_confidence": 0.41,
            "candidate_roles": [
                {"role": "primary_key", "confidence": 0.80},
                {"role": "categorical", "confidence": 0.72},
                {"role": "datetime", "confidence": 0.68},
                {"role": "numeric_measure", "confidence": 0.62},
                {
                    "role": "free_text",
                    "confidence": 0.41,
                    "evidence_strength": 0.55,
                    "chosen": True,
                },
            ],
        })

        self.assertEqual(len(result["candidateRoles"]), 4)
        self.assertTrue(any(
            candidate["role"] == "free_text" and candidate["chosen"]
            for candidate in result["candidateRoles"]
        ))

    def test_examples_separate_matching_and_conflicting_values(self):
        result = format_attribute_profile_record({
            "column": "amount",
            "role": "numeric",
            "profile_role": "numeric_measure",
            "confidence_score": 0.82,
        }, pd.Series(["10.5", "15", "unknown", "20"]))

        self.assertIn("10.5", result["supportingExamples"])
        self.assertEqual(result["conflictingExamples"], ["unknown"])

    def test_routine_geography_uses_safeguard_without_creating_review_work(self):
        result = format_attribute_profile_record({
            "column": "country",
            "role": "location_name",
            "profile_role": "location_name",
            "confidence_score": 0.91,
            "adaptive_warning": "Location-like fields should not be used as primary keys from uniqueness alone.",
        }, pd.Series(["United States", "India", "Netherlands"]))

        self.assertTrue(result["semanticSafeguardApplied"])
        self.assertFalse(result["isSemanticallySensitive"])
        self.assertEqual(result["dataWarning"], "")
        self.assertEqual(result["reviewReasons"], [])

    def test_high_uniqueness_geography_is_a_review_item_not_a_warning(self):
        result = format_attribute_profile_record({
            "column": "location_code",
            "role": "high_uniqueness_location_field",
            "profile_role": "high_uniqueness_location_field",
            "confidence_score": 0.91,
        }, pd.Series(["LOC-001", "LOC-002", "LOC-003"]))

        self.assertTrue(result["semanticSafeguardApplied"])
        self.assertTrue(result["isSemanticallySensitive"])
        self.assertEqual(result["dataWarning"], "")
        self.assertTrue(any(
            "location" in reason.lower()
            for reason in result["reviewReasons"]
        ))

    def test_data_warning_is_distinct_from_review_reasons(self):
        result = format_attribute_profile_record({
            "column": "amount",
            "role": "numeric",
            "profile_role": "numeric_measure",
            "confidence_score": 0.82,
            "data_warning": "Values mix incompatible numeric formats.",
        }, pd.Series(["10", "unknown"]))

        self.assertEqual(result["dataWarning"], "Values mix incompatible numeric formats.")
        self.assertEqual(result["reviewReasons"], [])
        self.assertIn(
            "Values mix incompatible numeric formats.",
            result["negativeEvidence"],
        )

    def test_routine_country_profile_is_stable_after_all_rows(self):
        df = pd.DataFrame({
            "Country": ["United States", "India", "Netherlands", "United Kingdom"] * 100,
        })

        profile = build_attribute_profiles(df)["Country"]

        self.assertEqual(profile["roleFamily"], "geography")
        self.assertEqual(profile["roleSubtypeLabel"], "location name")
        self.assertFalse(profile["classificationAmbiguous"])
        self.assertFalse(profile["samplingExhausted"])
        self.assertFalse(profile["needsMoreSampling"])
        self.assertEqual(profile["reviewReasons"], [])
        self.assertEqual(profile["adaptiveSamplingAction"], "no_more_sampling_needed")
        self.assertEqual(
            profile["fullDataStateLabel"],
            "Stable after examining all rows",
        )
        self.assertTrue(any(
            "Role-family evidence for 'geography'" in evidence
            for evidence in profile["positiveEvidence"]
        ))


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
        self.test_dataframe = pd.read_csv(DATASETS_DIR / 'stackoverflow_db_uncleaned.csv')

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
