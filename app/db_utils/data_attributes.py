import numpy as np
import pandas as pd
import json

from pandas.core.arrays import categorical

from app.db_utils.execute_sql import fetch_sql



#TODO: add documentation

def to_scalar(val):
    if val is None:
        return None
    if isinstance(val, pd.DataFrame):
        if val.empty:
            return None
        return to_scalar(val.iloc[0, 0])  # first row, first column
    if isinstance(val, pd.Series):
        return None if val.empty else to_scalar(val.iloc[0])
    if isinstance(val, (list, tuple)) and len(val) > 0:
        return to_scalar(val[0])
    if hasattr(val, 'item'):
        return val.item()
    return val

class DataProfile:
    def __init__(self, table_name, engine=None, main_df=None, error_df=None):
        self.table_name = table_name
        self.data_profile_table_name = "dp" + table_name
        self.engine = engine
        # IMPORTANT: main_df and error_df are NOT guaranteed to not be None (so that they don't have to be loaded each time for efficiency)
        # Use get_main_df and get_error_df instead of accessing them directly
        self._main_df = main_df
        self._error_df = error_df
        self.default_attributes = ['mean', 'median', 'min', 'max', 'n_categories', 'mode', 'error_counts', 'class_error_counts']
        self.name_to_func = {
            'mean': self._calculate_mean,
            'median': self._calculate_median,
            'min': self._calculate_min,
            'max': self._calculate_max, #TODO: add more,
            'n_categories': self._calculate_num_categories,
            'mode': self._calculate_mode,
            'error_counts': self._calculate_error_count_dict,
            'class_error_counts': self._calculate_class_error_count_dict,
        }

        self.attribute_type_assignment = {
            'numeric': ['mean', 'median', 'min', 'max', 'err', 'error_counts'],
            'categorical': ['n_categories',
                            'mode', 'error_counts', 'class_error_counts'],
        }

    def get_error_df(self):
        self.load_error_df()

        return self._error_df

    def get_main_df(self):
        self.load_main_df()

        return self._main_df


    def load_error_df(self):
        if self._error_df is None:
            assert self.engine is not None, f"engine cannot be None if error_df is None"
            #self.error_df = load_table_to_df(f"errors_{self.table_name}", self.engine)
            self._error_df = pd.read_sql_query(f'SELECT * FROM "{"errors_" + self.table_name}"', self.engine)

    def load_main_df(self):
        if self._main_df is None:
            assert self.engine is not None, f"engine cannot be None if main_df is None"
            #self.main_df = load_table_to_df(self.table_name, self.engine)
            self._main_df = pd.read_sql_query(f'SELECT * FROM "{self.table_name}"', self.engine)



    def get_col_data(self, column_name, attribute_name):
        assert (attribute_name in self.attribute_type_assignment['categorical'] or attribute_name in self.attribute_type_assignment['numeric']), f"Invalid attribute name {attribute_name}"

        if attribute_name in self.attribute_type_assignment['categorical']:
            col_data = self._main_df[column_name].fillna('N/A')
        if attribute_name in self.attribute_type_assignment['numeric']:
            col_data = pd.to_numeric(self._main_df[column_name], errors='coerce').dropna()

        return col_data

    # TODO: Make the sql query for this work
    def get_col_names(self):
        try:
            query = 'SELECT column_name FROM information_schema.columns WHERE table_name = :table_name ORDER BY ordinal_position'
            params = {"table_name": self.table_name}

            result = fetch_sql(query, False, self.engine, params=params)

            col_names = []
            for row in result:
                if row[0] not in ['index', 'level_0', ]:
                    col_names.append(row[0])

            print("COL NAMES FROM QUERY: ", col_names)


        except Exception as e:
            print(f"AHHHHHHHHHH Querying for col names unsuccessful because of error: {e}")
            print("Getting col names from Data frame instead")
        self.load_main_df()
        print("COL NAMES FROM main_df.columns:", self._main_df.columns)

        col_names = self._main_df.columns

        return col_names

    def look_up_stat_from_profile(self, attribute_name, column_name):
        data_profile_table_name = "dp_" + self.table_name
        try:
            query = f'SELECT "{attribute_name}" FROM "{data_profile_table_name}" WHERE "column_name" = :column_name'
            params = {"column_name": column_name}
            stat = fetch_sql(query, True, self.engine, params)

            return stat
        except Exception as e:
            print(f"Error querying attribute from data profile table: {e}")

    def calculate_summary_stat_using_sql(self, stat_query, column_name):
        query = f'SELECT {stat_query}("{column_name}") FROM "{self.table_name}"'
        stat = fetch_sql(query, True, self.engine)
        return stat

    def calculate_column_attribute(self, attribute_name, column_name, look_up_stat=True):
        if look_up_stat:
            look_up_value = self.look_up_stat_from_profile(attribute_name, column_name)

            if look_up_value is not None:
                print("Successfully found col attribute in data profile table!")
                return to_scalar(look_up_value)

        calculate_attribute_func = self.name_to_func[attribute_name]
        return to_scalar(calculate_attribute_func(column_name))

    # TODO: save stat off to table if newly calculated
    def _calculate_mean(self, column_name):
        col_data = self.get_col_data(column_name, 'mean')
        try:
            avg = self.calculate_summary_stat_using_sql('AVG', column_name)
        except Exception as e:
            print(f"Error fetching the mean for table {self.table_name} at column {column_name}: {e}")

            print("Calculating mean manually using data...")
            self.load_main_df()

            avg = col_data.mean()
            print(f"Updating mean value for column {column_name} in data profile")

        return avg


    def _calculate_median(self, column_name):
        col_data = self.get_col_data(column_name, 'median')

        try:
            query = f'SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY "{column_name}") FROM  "{self.table_name}"'
            median = fetch_sql(query, True, self.engine)
        except Exception as e:
            self.load_main_df()
            print(f"Error fetching the median for table {self.table_name} at column {column_name}: {e}")

            print("Calculating median manually using data...")

            median = col_data.median()

            print(f"Updating median value for column {column_name} in data profile")

        return median


    def _calculate_max(self, column_name):
        col_data = self.get_col_data(column_name, 'max')
        try:
            maximum = self.calculate_summary_stat_using_sql('MAX', column_name)
        except Exception as e:
            print(f"Error fetching the maximum for table {self.table_name} at column {column_name}: {e}")

            print("Calculating maximum manually using data...")
            self.load_main_df()

            maximum = col_data.max()

            print(f"Updating maximum value for column {column_name} in data profile")

        return maximum

    def _calculate_min(self, column_name):

        col_data = self.get_col_data(column_name, 'min')
        try:
            minimum = self.calculate_summary_stat_using_sql('MIN', column_name)
        except Exception as e:
            print(f"Error fetching the minimum for table {self.table_name} at column {column_name}: {e}")

            print("Calculating minimum manually using data...")
            self.load_main_df()

            minimum = col_data.min()

            print(f"Updating minimum value for column {column_name} in data profile")

        return minimum

    def _calculate_num_categories(self, column_name):
        col_data = self.get_col_data(column_name, 'n_categories')
        try:
            query = f'SELECT COUNT(DISTINCT "{column_name}") FROM "{self.table_name}"'
            n_categories = fetch_sql(query, True, self.engine)

        except Exception as e:
            print("AHHH SQL QUERY DIDN'T WORK")
            print(f"Error fetching the n_categories for table {self.table_name} at column {column_name}: {e}")

            print("Calculating n_categories manually using data...")
            self.load_main_df()

            n_categories = col_data.nunique()

            print(f"Updating n_categories value for column {column_name} in data profile")

        return n_categories


    def _calculate_mode(self, column_name):
        print("Calculating mode manually using data...")
        self.load_main_df()
        col_data = self.get_col_data(column_name, 'mode')
        mode = col_data.mode()

        return mode

    # Functions relating to error info
    # Dict mapping from error type to total error count
    def _calculate_error_count_dict(self, column_name):
        try:
            query = f'SELECT {column_name}, COUNT(*) as cnt FROM {self.table_name} GROUP BY {column_name}  ORDER BY cnt DESC'
            category_counts = dict(fetch_sql(query, True, self.engine))
        except Exception as e:

            print(f"Error fetching the error counts for table {self.table_name} at column {column_name}: {e}")

            print("Calculating error counts manually using data...")
            self.load_error_df()

            category_counts = {}
            if not self._error_df.empty: # If error_df is empty (no errors in data selection)
                category_counts = self._error_df["error_type"].value_counts().to_dict()

        if category_counts is not None:
            category_counts = json.dumps(category_counts)

        return category_counts

    # Dict mapping from class to error types to error counts
    # TODO: Implement SQL query version
    def _calculate_class_error_count_dict(self, column_name):
        print("Calculating class error counts manually using data...")

        self.load_error_df()

        counts_by_column = {}
        if not self._error_df.empty:  # If error_df is empty (no errors in data selection)
            counts_by_column = (
                self._error_df.groupby(['column_id', 'error_type'])
                .size()
                .unstack(fill_value=0)
                .to_dict(orient='index')
            )

        if counts_by_column is not None:
            counts_by_column = json.dumps(counts_by_column)


        return counts_by_column
