import unittest

import numpy as np
import pandas as pd

from detectors.datatype_mismatch import datatype_mismatch
from detectors.missing_value import missing_value


class TestDataTypeMismatch(unittest.TestCase):
    def test_basic_mismatch(self):
        test_data = {
            'ID': range(1, 11),
            'classname': ["word", "word", "systems", "networking", "compilers", "full-stack", "vis", "vis", "vis",
                          "vis"],
            'day': ["word", "word", "M/W", "T/H", "M/W", "M/W/F", "T/H", "vis", "vis", "vis"],
            'enrollment_cap': ["word", "word", 100, 100, 250, 250, 100, "test", "adding", "words"],
            'professor': ["word", "word", "kopta", "martin", "panchekha", "johnson", "rosen", "vis", "vis", "vis"]
        }
        expected_data = {"enrollment_cap":{1:"mismatch",2:"mismatch",8:"mismatch",9:"mismatch",10:"mismatch"}}
        df = pd.DataFrame(test_data)
        detected_df = datatype_mismatch(df)
        self.assertEqual(expected_data,detected_df)

    def test_no_mismatch(self):
        test_data = {
            'ID': range(1, 6),
            'classname': ["word", "systems", "networking", "compilers", "full-stack"],
            'day': ["M/W", "T/H", "M/W", "M/W/F", "T/H"],
            'enrollment_cap': [100, 100, 250, 250, 100],
            'professor': ["kopta", "martin", "panchekha", "johnson", "rosen"]
        }
        expected_data = {}
        df = pd.DataFrame(test_data)
        detected_df = datatype_mismatch(df)
        self.assertEqual(expected_data,detected_df)

    def test_stackoverflow(self):
        test_dataframe = pd.read_csv('../provided_datasets/stackoverflow_db_uncleaned.csv')
        detected_df = datatype_mismatch(test_dataframe)
        error_map = {"Age": {4: "mismatch", 5: "mismatch"}}
        self.assertEqual(error_map, detected_df)
if __name__ == '__main__':
    unittest.main()
