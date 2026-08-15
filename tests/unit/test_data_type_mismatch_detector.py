"""Tests for parse-based datatype mismatch detection."""

import unittest

import pandas as pd

from detectors.datatype_mismatch import datatype_mismatch


class TestDataTypeMismatch(unittest.TestCase):
    def test_mostly_numeric_column_flags_unparseable_values(self):
        df = pd.DataFrame({
            "ID": range(1, 11),
            "age": ["20", "21", "22", "23", "24", "25", "26", "27", "28", "unknown-ish"],
        })

        self.assertEqual({"age": {10: "mismatch"}}, datatype_mismatch(df))

    def test_weak_type_signal_does_not_force_a_mismatch(self):
        df = pd.DataFrame({
            "ID": range(1, 11),
            "mixed": ["word", "word", 100, 100, 250, 250, 100, "test", "adding", "words"],
        })

        self.assertEqual({}, datatype_mismatch(df))

    def test_date_like_column_flags_bad_date(self):
        df = pd.DataFrame({
            "ID": range(1, 11),
            "date": [
                "2024-01-01",
                "2024-01-02",
                "2024-01-03",
                "2024-01-04",
                "2024-01-05",
                "2024-01-06",
                "2024-01-07",
                "2024-01-08",
                "2024-01-09",
                "not-a-date",
            ],
        })

        self.assertEqual({"date": {10: "mismatch"}}, datatype_mismatch(df))

    def test_details_include_expected_type_and_confidence(self):
        df = pd.DataFrame({
            "ID": range(1, 11),
            "flag": ["yes", "no", "true", "false", "yes", "no", "true", "false", "yes", "maybe"],
        })

        result = datatype_mismatch(df, include_details=True)

        self.assertEqual("type_mismatch", result["flag"][10]["error_type"])
        self.assertEqual("mismatch", result["flag"][10]["legacy_error_type"])
        self.assertEqual("boolean", result["flag"][10]["expected_type"])


if __name__ == "__main__":
    unittest.main()
