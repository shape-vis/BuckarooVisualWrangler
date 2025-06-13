import unittest

import pandas as pd

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


if __name__ == '__main__':
    unittest.main()
