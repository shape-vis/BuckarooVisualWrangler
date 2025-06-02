from unittest import TestCase

from app.service_helpers import clean_table_name


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