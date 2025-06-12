import unittest

import numpy as np
import pandas as pd

from detectors.missingValue import missing_value


# class MyTestCase(unittest.TestCase):
#     def test_None(self):
#
#         df = pd.DataFrame([['ant', 'bee', 'cat'], ['dog', None, 'fly']])
#         detected_df = missing_value(df)
#         error_map = {1:{1:"missing"}}
#         self.assertEqual(error_map,detected_df)
#
#
# if __name__ == '__main__':
#     unittest.main()
