from unittest import TestCase

from app.service_helpers import clean_table_name, get_whole_table_query


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
        query = get_whole_table_query(cleaned)
        print("test_whole_table_query:", query)
        self.assertEqual("SELECT TOP * FROM table_name",query)