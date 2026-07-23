import numpy as np
import pandas as pd
import json

from pandas.core.arrays import categorical

from app.db_utils.execute_sql import fetch_sql
from app.db_utils.column_types import ColumnTypes

# TODO: is this needed? this may be a duplicate
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
    """
    Class that handles queries to get summary stats about the main data table.
    Should be able to work without using main_df and error_df at all.
    This class prioritizes SQL queries and when those don't work, the table is loaded and the pd dataframe method is used
    instead.
    """
    def __init__(self, table_name, engine):
        """
        :param table_name: name of the main data table
        :param engine:
        :param main_df:the main data table as a data frame
        :param error_df:the error data table as a data frame
        """
        self.table_name = table_name
        self.data_profile_table_name = "dp_" + table_name
        self.error_table_name = "errors_" + table_name
        self.col_types = ColumnTypes(table_name, engine)


        self.engine = engine
        # IMPORTANT: main_df and error_df are NOT guaranteed to not be None (so that they don't have to be loaded each time for efficiency)
        # Use get_main_df and get_error_df instead of accessing them directly
        self.name_to_func = {
            'mean': self._calculate_mean,
            'median': self._calculate_median,
            'min': self._calculate_min,
            'max': self._calculate_max, #TODO: add more,
            'n_categories': self._calculate_num_categories,
            'mode': self._calculate_mode,
            'error_counts': self._calculate_error_count_dict,
            'category_counts': self._calculate_category_count_dict,
        }

        self.attribute_type_assignment = {
            'numeric': ['mean', 'median', 'min', 'max', 'error_counts'],
            'categorical': ['n_categories',
                            'mode', 'error_counts', 'category_counts'],
        }


        self.dtype_dict = None

    def get_col_names(self):
        """
        self: DataProfile instance
        :return: List of column names in the main data table
        """
        try:
            query = 'SELECT column_name FROM information_schema.columns WHERE table_name = :table_name ORDER BY ordinal_position'
            params = {"table_name": self.table_name}

            result = fetch_sql(query, False, self.engine, params=params)

            col_names = []
            for row in result:
                # For some reason the SQL query returns some unwanted columns so I'm taking them out
                if row[0] not in ['index', 'level_0', ]:
                    col_names.append(row[0])

            print("COL NAMES FROM QUERY: ", col_names)


        except Exception as e:
            print(f"AHHHHHHHHHH Querying for col names unsuccessful because of error: {e}")

        return col_names

    def look_up_stat_from_profile(self, attribute_name, column_name):
        """
        Look up a summary statistic for a specific column from the data profile table.
        :param attribute_name: Name of the attribute (e.g., 'mean', 'median', 'min', 'max', etc.)
        :param column_name: Name of the column for which the statistic is being looked up.
        :return: The value of the statistic if found, otherwise None.
        """
        try:
            query = f'SELECT "{attribute_name}" FROM "{self.data_profile_table_name}" WHERE "column_name" = :column_name'
            params = {"column_name": column_name}
            stat = fetch_sql(query, True, self.engine, params)

            return stat
        except Exception as e:
            print(f"Error querying attribute from data profile table: {e}")
            return None


    def calculate_summary_stat_using_sql(self, stat_query, column_name):
        """
        :param stat_query: The SQL aggregate function to use (e.g., 'AVG', 'MIN', 'MAX', etc.)
        :param column_name: Name of the column for which the statistic is being looked up.
        :return: The value of the statistic if found, otherwise None.
        """

        # Casting to numeric values just in case there is a data type mismatch and the single string variable
        # Turns an entire numeric column into text
        query = (f'SELECT {stat_query}'
                 f'("{column_name}"::numeric) FROM '
                 f'"{self.table_name}"')

        # If its a numeric column with at least one string / categorical value, we only keep the numeric values so we
        # Can properly do calculations
        if self.col_types.is_mixed_col(column_name):
            query += f' WHERE pg_input_is_valid("{column_name}", \'numeric\')'

        stat = fetch_sql(query, True, self.engine)
        return stat

    def calculate_column_attribute(self, attribute_name, column_name, look_up_stat=True):
        """
        :param attribute_name: Name of the attribute (e.g., 'mean', 'median', 'min', 'max')
        :param column_name: Name of the column for which the statistic is being looked up.
        :param look_up_stat: If True, first attempt to look up the statistic from the data profile table. If False, calculate it directly.
        :return: The value of the statistic if found or calculated, otherwise None.
        """
        if look_up_stat:
            look_up_value = self.look_up_stat_from_profile(attribute_name, column_name)

            if look_up_value is not None:
                print("Successfully found col attribute in data profile table!")

                return to_scalar(look_up_value)

        calculate_attribute_func = self.name_to_func[attribute_name]
        # TODO: save stat off to table if newly calculated

        return to_scalar(calculate_attribute_func(column_name))

    def _calculate_mean(self, column_name):
        """
        :param column_name: Name of the column for which the mean is being calculated
        :return: The mean
        """

        # Try get the mean from SQL first, if that fails, calculate it manually using the data frame
        try:
            avg = self.calculate_summary_stat_using_sql('AVG', column_name)
        except Exception as e:
            print(f"Error fetching the mean for table {self.table_name} at column {column_name}: {e}")
            avg = None


        return avg


    def _calculate_median(self, column_name):
        """
        :param column_name: Name of the column for which the median is being calculated
        :return: The median
        """

        # Try get the median from SQL first, if it fails, calculate manually using data frame
        try:
            query = f'SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY "{column_name}"::numeric) FROM  "{self.table_name}"'

            # If its a numeric column with at least one string / categorical value, we only keep the numeric values so we
            # Can properly do calculations
            if self.col_types.is_mixed_col(column_name):
                query += f' WHERE pg_input_is_valid("{column_name}", \'numeric\')'
            median = fetch_sql(query, True, self.engine)
        except Exception as e:
            print(f"Error fetching the median for table {self.table_name} at column {column_name}: {e}")
            median = float('nan')

        return median


    def _calculate_max(self, column_name):
        """
        :param column_name: Name of the column for which the max is being calculated
        :return: The maximum
        """

        # Try using SQL query, if it fails, calculate manually using data frame
        try:
            maximum = self.calculate_summary_stat_using_sql('MAX', column_name)
        except Exception as e:
            print(f"Error fetching the maximum for table {self.table_name} at column {column_name}: {e}")

            maximum = None

        return maximum

    def _calculate_min(self, column_name):
        """
        :param column_name: Name of the column for which the minimum is being calculated
        :return: The minimum
        """

        # Try using SQL query, if it fails, calculate manually using data frame
        try:
            minimum = self.calculate_summary_stat_using_sql('MIN', column_name)
        except Exception as e:
            print(f"Error fetching the minimum for table {self.table_name} at column {column_name}: {e}")

            minimum = None

        return minimum

    def _calculate_num_categories(self, column_name):
        """
        :param column_name: Name of the column for which the number of categories is being calculated
        :return: The number of categories
        """

        # Try using SQL query, if it fails, calculate manually using data frame
        try:
            query = f'SELECT COUNT(DISTINCT "{column_name}") FROM "{self.table_name}"'
            n_categories = fetch_sql(query, True, self.engine)

        except Exception as e:
            print("AHHH SQL QUERY DIDN'T WORK")
            print(f"Error fetching the n_categories for table {self.table_name} at column {column_name}: {e}")

            n_categories = None

        return n_categories


    def _calculate_mode(self, column_name):
        """
        :param column_name: Name of the column for which the mode is being calculated
        :return: The mode
        """
        try:
            query = f"""
            SELECT "{column_name}" FROM "{self.table_name}"
            WHERE "{column_name}" IS NOT NULL
            GROUP BY "{column_name}"
            ORDER BY COUNT(*) DESC
            LIMIT 1;
            """

            mode = fetch_sql(query, True, self.engine)
            print("MODE FROM SQL QUERY: ", mode)

        except Exception as e:
            print("AHHH SQL QUERY DIDN'T WORK")
            print(f"Error fetching the mode for table {self.table_name} at column {column_name}: {e}")

            mode = None

        return mode

    # Functions relating to error info
    # Dict mapping from error type to total error count
    def _calculate_error_count_dict(self, column_name):
        """
        :param column_name: Name of the column for which the error count is being calculated
        :return: The error count dict ({"missing": 10, "mismatch": 5, ...})
        """
        try:
            query = f"""
                    SELECT error_type, COUNT(*) 
                    FROM "{self.error_table_name}" 
                    WHERE column_id = :column_name
                    GROUP BY error_type
                  """
            error_counts = dict(fetch_sql(query, False, self.engine, params={'column_name': column_name}))

            if error_counts is not None:
                error_counts = json.dumps(error_counts)
            else:
                error_counts = json.dumps({})
        except Exception as e:

            print(f"Error fetching the error counts for table {self.table_name} at column {column_name}: {e}")
            error_counts = None



        return error_counts

    # TODO: implement this later
    # # Dict mapping from class to error types to error counts
    # def _calculate_class_error_count_dict(self, column_name):
    #     """
    #     :param column_name: Name of the column for which the class error count is being calculated
    #     :return: The class error count dict ({"Male": {"missing": 10, "mismatch": 5, ...}, "Female": {"missing": 10, "mismatch": 5, ...}})
    #     """
    #
    #     try:
    #         # TODO: check if this works
    #         ry:
    #         query = f'''
    #                     SELECT "column_id", "error_type", COUNT(*) AS error_count
    #                     FROM "{self.error_table_name}"
    #                     WHERE "column_id" = :column_name
    #                     GROUP BY "column_id", "error_type"
    #                 '''
    #
    #         rows = fetch_sql(query, True, self.engine, params={"column_name": column_name})
    #
    #         counts_by_column = {}
    #         for r in (rows or []):
    #             row = dict(r)
    #             category = row[category_col]
    #             error_type = row["error_type"]
    #             count = row["error_count"]
    #             counts_by_column.setdefault(category, {})[error_type] = count
    #
    #     except Exception as e:
    #         print(f"Error fetching the error counts for table {self.table_name} at column {column_name}: {e}")
    #         counts_by_column = None
    #     if counts_by_column is not None:
    #         counts_by_column = json.dumps(counts_by_column)
    #
    #     return counts_by_column

    def _calculate_category_count_dict(self, column_name):
        """
        :param column_name: Name of the column for which the class error count is being calculated
        :return: The class error count dict ({"Male": {"missing": 10, "mismatch": 5, ...}, "Female": {"missing": 10, "mismatch": 5, ...}})
        """

        try:
            query = f"""
                    SELECT "{column_name}", COUNT(*) 
                    FROM "{self.table_name}" 
                    GROUP BY "{column_name}"
                  """

            rows = fetch_sql(query, False ,self.engine)
            category_counts = {}
            # Put the results into a dict
            for (category, count) in rows:
                category_counts[category] = count
            print("CATEGORY COUNTS DICT", category_counts)


        except Exception as e:

            print(f"Error fetching the category counts for table {self.table_name} at column {column_name}: {e}")
            category_counts = None

        if category_counts is not None:
            # Put the dict into a string so we can actually put it into a SQL table
            category_counts = json.dumps(category_counts)

        return category_counts

    # Dict mapping from class to error types to error counts
    # TODO: Implement SQL query version
    def _calculate_class_error_count_dict(self, column_name):
        """
        :param column_name: Name of the column for which the class error count is being calculated
        :return: The class error count dict ({"Male": {"missing": 10, "mismatch": 5, ...}, "Female": {"missing": 10, "mismatch": 5, ...}})
        """
        # TODO: Implement SQL query version
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
