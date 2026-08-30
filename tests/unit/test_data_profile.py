import unittest
from decimal import Decimal

import pandas as pd
from app.db_utils.data_profile import DataProfile
from app import engine
import json
from app.db_utils.execute_sql import execute_sql


data_profile_df = pd.DataFrame(
         {
            'column_name': ['name', 'age', 'city', 'species', 'height', 'hair_color'],
            'mean': [None, Decimal('26.4'), None, None, Decimal('18.2'), None],
            'median': [None, Decimal('30.0'), None, None, Decimal('5.5'), None],
            'min': [None, Decimal('3'), None, None, Decimal('1.2'), None],
            'max': [None, Decimal('60'), None, None, Decimal('6.0'), None],
            'n_categories': [5, None, 4, 2, None, 3],
            'mode': ['Mari', None, 'Phoenix', 'human', None, 'black'],
            'error_counts': [json.dumps({}), json.dumps({}), json.dumps({'missing': 1}), json.dumps({}), json.dumps({'mismatch': 1}), json.dumps({'mismatch': 2})],
            'category_counts': [json.dumps({'Mari':2, 'Seb': 1, 'Zee': 1, 'Juju': 1}), None, json.dumps({'New York': 1, 'Houston': 2, 'Phoenix': 1}), json.dumps({'human': 3, 'dog': 2}), None, json.dumps({'black': 3, 'brown': 1, '2': 1, '1': 1})],
          }
)

main_df = pd.DataFrame(
       {
           'name': ['Mari', 'Seb', 'Zee', 'Juju', 'Mari'],
            'age': [30, 60, 3, 9, 30],
            'city': ['New York', 'Houston', None, 'Houston', 'Phoenix'],
            'species': ['human', 'human', 'dog', 'dog', 'human'],
            'height': [5.5, 6.0, 1.2, "one", 5.5],
            'hair_color': ['black', 'brown', 2, 'black', 1],
        }
)

error_df = pd.DataFrame(
    {
        'row_id': [3, 4, 3, 5],
        'column_id': ['city','height', 'hair_color', 'hair_color'],
        'error_type': ['missing', 'mismatch', 'mismatch', 'mismatch'],
    }
)

data_profile_table_name = 'dp_main_mari_test'
main_df_table_name = 'main_mari_test'
error_df_table_name = 'errors_main_mari_test'

main_df.to_sql('main_mari_test', con=engine, if_exists='replace', index=False)
data_profile_df.to_sql('dp_main_mari_test', con=engine, if_exists='replace', index=False)
error_df.to_sql('errors_main_mari_test', con=engine, if_exists='replace', index=False)


data_profile = DataProfile('main_mari_test', engine)

class MyTestCase(unittest.TestCase):
    def test_get_col_names(self):
        self.assertEqual(data_profile.get_col_names(), ['name', 'age', 'city', 'species', 'height', 'hair_color'])

    def test_look_up_stat_from_profile(self):
        self.assertEqual(data_profile.look_up_stat_from_profile('mean', 'age'), 26.4)
        self.assertEqual(data_profile.look_up_stat_from_profile('n_categories', 'species'), 2)
        self.assertEqual(data_profile.look_up_stat_from_profile('mode', 'species'), 'human')
        self.assertEqual(data_profile.look_up_stat_from_profile('mode', 'name'), 'Mari')
        self.assertEqual(data_profile.look_up_stat_from_profile('max', 'age'), 60)
        self.assertEqual(data_profile.look_up_stat_from_profile('error_counts', 'city'), json.dumps({'missing': 1}))
        self.assertEqual(data_profile.look_up_stat_from_profile('category_counts', 'species'), json.dumps({'human': 3, 'dog': 2}))
        # Should be None
        self.assertEqual(data_profile.look_up_stat_from_profile('category_counts', 'height'), None)
        self.assertEqual(data_profile.look_up_stat_from_profile('n_categories', 'age'), None)
        self.assertEqual(data_profile.look_up_stat_from_profile('mode', 'age'), None)

    # def test_calculate_column_attribute(self):
    #     self.assertEqual(data_profile.calculate_column_attribute('mean', 'age'), 26.4)
    #     self.assertEqual(data_profile.calculate_column_attribute('n_categories', 'species'), 2)
    #     self.assertEqual(data_profile.calculate_column_attribute('mode', 'species'), 'human')
    #     self.assertEqual(data_profile.calculate_column_attribute('mode', 'name'), 'Mari')
    #     self.assertEqual(data_profile.calculate_column_attribute('max', 'age'), 60)
    #     self.assertEqual(data_profile.calculate_column_attribute('error_counts', 'city'), json.dumps({'missing': 1}))
    #     self.assertEqual(data_profile.calculate_column_attribute('category_counts', 'species'), json.dumps({'human': 3, 'dog': 2}))
    #     # Should be None
    #     self.assertEqual(data_profile.calculate_column_attribute('category_counts', 'height'), None)
    #     self.assertEqual(data_profile.calculate_column_attribute('n_categories', 'age'), None)
    #     self.assertEqual(data_profile.calculate_column_attribute('mode', 'age'), None)

    def test_get_mixed_cols(self):
        # Height is a mixed column as well as a numeric column because although it is mostly numeric, it has one value
        # that is a string
        self.assertEqual(set(data_profile.get_mixed_cols()), set(['height', 'hair_color']))

    def test_get_numeric_cols(self):
        self.assertEqual(set(data_profile.get_numeric_cols()), set(['age', 'height']))

    def test_get_categorical_cols(self):
        self.assertEqual(set(data_profile.get_categorical_cols()), set(['name', 'city', 'species', 'hair_color']))

    def test_calculate_error_count_dict(self):
        self.assertEqual(data_profile._calculate_error_count_dict('name'), json.dumps({}))
        self.assertEqual(data_profile._calculate_error_count_dict('city'), json.dumps({'missing': 1}))
        self.assertEqual(data_profile._calculate_error_count_dict('height'), json.dumps({'mismatch': 1}))
        self.assertEqual(data_profile._calculate_error_count_dict('hair_color'), json.dumps({'mismatch': 2}))


if __name__ == '__main__':
    unittest.main()
    execute_sql(f'DROP TABLE IF EXISTS "{main_df_table_name}"', engine)
    execute_sql(f'DROP TABLE IF EXISTS "{data_profile_table_name}"', engine)
    execute_sql(f'DROP TABLE IF EXISTS "{error_df_table_name}"', engine)
