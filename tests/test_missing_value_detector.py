import unittest

import numpy as np
import pandas as pd

from detectors.missing_value import missing_value


class MyTestCase(unittest.TestCase):
    def test_None(self):
        """
        Testing if it's undefined or Null
        :return:
        """
        df = pd.DataFrame({"ID": range(1,4),"animals":['ant', 'bee', 'cat'], "pets":['dog', None, 'fly']})
        detected_df = missing_value(df)
        error_map = {"pets":{2:"missing"}}
        self.assertEqual(error_map,detected_df)

    def test_many_None(self):
        df = pd.DataFrame({"ID": range(1,4),"animals":['ant', None, 'cat'], "pets":['dog', None, None]})
        detected_df = missing_value(df)
        error_map = {"animals":{2: "missing"},"pets":{2:"missing",3:"missing"}}
        self.assertEqual(error_map,detected_df)

    def test_many_NaNs(self):
        df = pd.DataFrame({"ID": range(1,4),"animals":['ant', np.nan, 'cat'], "pets":['dog', np.nan, np.nan]})
        detected_df = missing_value(df)
        error_map = {"animals":{2: "missing"},"pets":{2:"missing",3:"missing"}}
        self.assertEqual(error_map,detected_df)

    def test_missing_value_strings(self):
        df = pd.DataFrame({"ID": range(1,4),"animals":['ant', "null", 'cat'], "pets":['dog', "undefined", "null"]})
        detected_df = missing_value(df)
        error_map = {"animals":{2: "missing"},"pets":{2:"missing",3:"missing"}}
        self.assertEqual(error_map, detected_df)
    def test_missing_value_mix(self):
        df = pd.DataFrame({"ID": range(1,4),"animals":['ant', "null", None], "pets":[np.nan, "undefined", None]})
        detected_df = missing_value(df)
        error_map = {"animals":{2: "missing",3: "missing"},"pets":{1:"missing",2:"missing",3:"missing"}}
        self.assertEqual(error_map, detected_df)

if __name__ == '__main__':
    unittest.main()
