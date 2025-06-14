import unittest

import pandas as pd

from app.set_id_column import set_id_column
from detectors.incomplete import incomplete


class IncompleteTesting(unittest.TestCase):
    def test_basic_incomplete(self):
        """
        Should report all as incomplete and ignore the enrollment cap column
        :return: none
        """
        test_data = {
            'ID': range(1, 6),
            'classname': ["systems", "networking", "compilers", "full-stack", "vis"],
            'day': ["M/W", "T/H", "M/W", "M/W/F", "T/H"],
            'enrollment_cap': [100, 100, 250, 250, 100],
            'professor': ["kopta", "martin", "panchekha", "johnson", "rosen"]
        }

        expected_dictionary = { "classname": {1: "incomplete", 2: "incomplete", 3: "incomplete", 4: "incomplete", 5: "incomplete"},
                                "day":{1: "incomplete", 2: "incomplete", 3: "incomplete", 4: "incomplete", 5: "incomplete"},
                                "professor":{1: "incomplete", 2: "incomplete", 3: "incomplete", 4: "incomplete", 5: "incomplete"}
                                }
        data_frame = pd.DataFrame(test_data)
        detected_frame = incomplete(data_frame)
        self.assertEqual(expected_dictionary, detected_frame)

    def test_none_incomplete(self):
        """
        Should report none as incomplete
        :return: none
        """
        test_data = {
            'ID': range(1, 6),
            'classname': ["systems", "systems", "systems", "systems", "systems"],
            'day': ["M/W", "M/W", "M/W", "M/W", "M/W"],
            'enrollment_cap': [100, 100, 250, 250, 100],
            'professor': ["kopta", "kopta", "kopta", "kopta", "kopta"]
        }

        expected_dictionary = {}
        data_frame = pd.DataFrame(test_data)
        detected_frame = incomplete(data_frame)
        self.assertEqual(expected_dictionary, detected_frame)

    def test_uncleaned_stackoverflow_with_main_detector_result(self):
        test_dataframe = pd.read_csv('../provided_datasets/stackoverflow_db_uncleaned.csv')
        detected_df = incomplete(test_dataframe.head(200))
        expected_error_map = {
            "Age": {3: "incomplete", 4: "incomplete", 5: "incomplete", 105: "incomplete", 159: "incomplete"},
            "Country": {61: "incomplete", 85: "incomplete", 107: "incomplete", 147: "incomplete", 204: "incomplete",
                        226: "incomplete", 227: "incomplete", 240: "incomplete"},
            "DevType": {44: "incomplete", 101: "incomplete", 118: "incomplete", 141: "incomplete", 196: "incomplete",
                        222: "incomplete", 224: "incomplete", 234: "incomplete"},
            "FormalEducation": {81: "incomplete", 161: "incomplete", 165: "incomplete"},
            "Gender": {9: "incomplete", 10: "incomplete", 24: "incomplete", 157: "incomplete"},
            "SexualOrientation": {169: "incomplete", 221: "incomplete"}, "UndergradMajor": {15: "incomplete"},
            "YearsCoding": {169: "incomplete", 230: "incomplete"}}
        self.assertEqual(expected_error_map, detected_df)

if __name__ == '__main__':
    unittest.main()
