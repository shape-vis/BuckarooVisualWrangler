import unittest

import numpy as np
import pandas as pd

from detectors.missingValue import missing_value


class MyTestCase(unittest.TestCase):
    def test_None(self):
        """
        Testing if it's undefined or Null
        :return:
        """
        df = pd.DataFrame([['ant', 'bee', 'cat'], ['dog', None, 'fly']])
        detected_df = missing_value(df)
        error_map = {1:{1:"missing"}}
        self.assertEqual(error_map,detected_df)

    def test_many_None(self):
        df = pd.DataFrame([['ant',None, 'cat'], ['dog', None, None]])
        detected_df = missing_value(df)
        error_map = {1:{0: "missing",1:"missing"},2:{1:"missing"}}
        self.assertEqual(error_map,detected_df)

    def test_many_NaNs(self):
        df = pd.DataFrame([['ant',np.nan, 'cat'], ['dog', np.nan, np.nan]])
        detected_df = missing_value(df)
        error_map = {1:{0: "missing",1:"missing"},2:{1:"missing"}}
        self.assertEqual(error_map,detected_df)

    def test_missing_value_strings(self):
        df = pd.DataFrame([['ant', "null", 'cat'], ['dog', "undefined", "null"]])
        detected_df = missing_value(df)
        error_map = {1: {0: "missing", 1: "missing"}, 2: {1: "missing"}}
        self.assertEqual(error_map, detected_df)
    def test_missing_value_mix(self):
        df = pd.DataFrame([['ant', "null", None], [np.nan, "undefined", None]])
        detected_df = missing_value(df)
        error_map = {0: {1:"missing"}, 1: {0: "missing", 1: "missing"}, 2: {0: "missing",1: "missing"}}
        self.assertEqual(error_map, detected_df)

if __name__ == '__main__':
    unittest.main()
