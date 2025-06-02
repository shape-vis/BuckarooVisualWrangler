from unittest import TestCase

from app.service_helpers import clean_table_name


class General(TestCase):
    def test_clean_table_name_removes_csv_extension(self):
        example_table = "sales_data.csv"
        self.assertEqual(clean_table_name(example_table), "sales_data")

    def test_starts_with_letter(self):
        example_name = "5table.csv"
        self.assertEqual(clean_table_name(example_name), "table_5table")
