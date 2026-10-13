import json

from app.db_utils.execute_sql import fetch_sql
from app.db_utils.column_types import ColumnTypes

# Columns information_schema lists that are not data: the index columns pandas leaves behind when it writes a table
INDEX_COLUMNS = ("index", "level_0")

# The values of a mostly-numeric text column that the numeric statistics are taken over
NUMBER_PATTERN = r"'^-?\d+(\.\d+)?$'"

# The columns of a dp_ table: the column a row describes, then every statistic stored for it
STORED_PROFILE_COLUMNS = ("column_name", "mean", "median", "min", "max", "n_categories", "mode",
                          "error_counts", "category_counts")


def to_scalar(val):
    """
    A statistic as a plain value: the first element of a one-row result, and a numpy scalar as its Python
    equivalent, so it can be stored and sent as JSON.
    """
    if val is None:
        return None
    if isinstance(val, (list, tuple)) and len(val) > 0:
        return to_scalar(val[0])
    if hasattr(val, 'item'):
        return val.item()
    return val


class DataProfile:
    """
    Summary statistics about one table's columns, each computed by a SQL query of its own: the mean, median, min
    and max of a numeric column; the number of categories, the mode and the category counts of a categorical one;
    and every column's error counts.

    Statistics are stored per column in the table's dp_ table (see build_data_profile_table), and
    calculate_column_attribute reads them from there before computing them afresh.
    """
    def __init__(self, table_name, engine):
        """
        :param table_name: name of the table to profile
        :param engine: SQLAlchemy engine
        """
        self.table_name = table_name
        self.data_profile_table_name = "dp_" + table_name
        self.error_table_name = "errors_" + table_name
        self.col_types = ColumnTypes.for_table(table_name, engine)
        self.engine = engine

        self.name_to_func = {
            'mean': self._calculate_mean,
            'median': self._calculate_median,
            'min': self._calculate_min,
            'max': self._calculate_max,
            'n_categories': self._calculate_num_categories,
            'mode': self._calculate_mode,
            'error_counts': self._calculate_error_count_dict,
            'category_counts': self._calculate_category_count_dict,
        }

        self.attribute_type_assignment = {
            'numeric': ['mean', 'median', 'min', 'max', 'error_counts'],
            'categorical': ['n_categories', 'mode', 'error_counts', 'category_counts'],
        }

        # The two dicts above have to agree: an attribute missing from attribute_type_assignment
        # would be skipped for every column, and one missing from name_to_func has no way to be
        # calculated. Catch either mistake here instead of silently producing an empty column
        assigned_attributes = set()
        for attributes in self.attribute_type_assignment.values():
            assigned_attributes.update(attributes)

        calculable_attributes = set(self.name_to_func)
        if calculable_attributes != assigned_attributes:
            mismatched = sorted(calculable_attributes ^ assigned_attributes)
            raise ValueError(
                f"name_to_func and attribute_type_assignment disagree for table {self.table_name}: {mismatched}"
            )

    def get_col_names(self):
        """
        :return: the table's data column names, in table order
        """
        query = ('SELECT column_name FROM information_schema.columns WHERE table_name = :table_name '
                 'ORDER BY ordinal_position')
        rows = fetch_sql(query, False, self.engine, params={"table_name": self.table_name})

        col_names = []
        for row in rows:
            if row[0] not in INDEX_COLUMNS:
                col_names.append(row[0])
        return col_names

    def read_stored_profile(self, skipped_columns=()):
        """
        Every stored statistic of every column, as the dp_ table holds them.
        :param skipped_columns: columns to leave out, e.g. the row identifiers
        :return: one dict per column, keyed by STORED_PROFILE_COLUMNS, in column name order
        """
        query = f'''
            SELECT {", ".join(STORED_PROFILE_COLUMNS)}
            FROM "{self.data_profile_table_name}"
            WHERE NOT (column_name = ANY(:skipped_columns))
            ORDER BY column_name
        '''
        rows = fetch_sql(query, False, self.engine, params={"skipped_columns": list(skipped_columns)})

        profile_rows = []
        for row in rows or []:
            profile_rows.append(dict(zip(STORED_PROFILE_COLUMNS, row)))
        return profile_rows

    def look_up_stat_from_profile(self, attribute_name, column_name):
        """
        Look up a summary statistic for a specific column from the data profile table.
        :param attribute_name: Name of the attribute (e.g., 'mean', 'median', 'min', 'max', etc.)
        :param column_name: Name of the column for which the statistic is being looked up.
        :return: The value of the statistic if found, otherwise None.
        """
        try:
            query = f'SELECT "{attribute_name}" FROM "{self.data_profile_table_name}" WHERE "column_name" = :column_name'
            return fetch_sql(query, True, self.engine, {"column_name": column_name})
        except Exception as e:
            print(f"Error querying attribute from data profile table: {e}")
            return None

    def numbers_only(self, column_name):
        """
        The WHERE clause that keeps only a mixed column's numeric values, so the numeric statistics can be taken over
        a column holding a stray string; empty for a column that is numeric throughout.
        :param column_name: Name of the column.
        """
        if not self.col_types.is_mixed_col(column_name):
            return ""
        return f' WHERE "{column_name}" ~ {NUMBER_PATTERN}'

    def calculate_summary_stat_using_sql(self, stat_query, column_name):
        """
        :param stat_query: The SQL aggregate function to use (e.g., 'AVG', 'MIN', 'MAX', etc.)
        :param column_name: Name of the column for which the statistic is being calculated.
        :return: The value of the statistic.
        """
        # Cast to numeric, so a numeric column stored as text because of a single stray string still aggregates
        query = f'SELECT {stat_query}("{column_name}"::numeric) FROM "{self.table_name}"'
        query += self.numbers_only(column_name)
        return fetch_sql(query, True, self.engine)

    def is_valid_attribute_for_column(self, attribute_name, column_name):
        """
        Check that an attribute applies to the type of the column, so that e.g. min / max are never
        calculated for a categorical column such as one full of country names.
        :param attribute_name: Name of the attribute (e.g., 'mean', 'median', 'min', 'max')
        :param column_name: Name of the column the attribute would be calculated for.
        :return: True if the attribute applies to this column's type.
        """
        if self.col_types.is_categorical_col(column_name) or self.col_types.is_categorical_mixed_col(column_name):
            column_type = 'categorical'
        else:
            column_type = 'numeric'

        return attribute_name in self.attribute_type_assignment[column_type]

    def calculate_column_attribute(self, attribute_name, column_name, look_up_stat=True):
        """
        :param attribute_name: Name of the attribute (e.g., 'mean', 'median', 'min', 'max')
        :param column_name: Name of the column for which the statistic is being looked up.
        :param look_up_stat: If True, first attempt to look up the statistic from the data profile table. If False, calculate it directly.
        :return: The value of the statistic if found or calculated, otherwise None.
        """
        # An attribute that doesn't apply to the column's type has no meaningful value, so don't
        # look it up or calculate it
        if not self.is_valid_attribute_for_column(attribute_name, column_name):
            return None

        if look_up_stat:
            look_up_value = self.look_up_stat_from_profile(attribute_name, column_name)
            if look_up_value is not None:
                return to_scalar(look_up_value)

        calculate_attribute_func = self.name_to_func[attribute_name]
        return to_scalar(calculate_attribute_func(column_name))

    def _calculate_mean(self, column_name):
        """
        :param column_name: Name of the column for which the mean is being calculated
        :return: The mean, or None when it cannot be calculated
        """
        try:
            return self.calculate_summary_stat_using_sql('AVG', column_name)
        except Exception as e:
            print(f"Error fetching the mean for table {self.table_name} at column {column_name}: {e}")
            return None

    def _calculate_median(self, column_name):
        """
        :param column_name: Name of the column for which the median is being calculated
        :return: The median, or None when it cannot be calculated
        """
        try:
            query = (f'SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY "{column_name}"::numeric) '
                     f'FROM "{self.table_name}"')
            query += self.numbers_only(column_name)
            return fetch_sql(query, True, self.engine)
        except Exception as e:
            print(f"Error fetching the median for table {self.table_name} at column {column_name}: {e}")
            return None

    def _calculate_max(self, column_name):
        """
        :param column_name: Name of the column for which the max is being calculated
        :return: The maximum, or None when it cannot be calculated
        """
        try:
            return self.calculate_summary_stat_using_sql('MAX', column_name)
        except Exception as e:
            print(f"Error fetching the maximum for table {self.table_name} at column {column_name}: {e}")
            return None

    def _calculate_min(self, column_name):
        """
        :param column_name: Name of the column for which the minimum is being calculated
        :return: The minimum, or None when it cannot be calculated
        """
        try:
            return self.calculate_summary_stat_using_sql('MIN', column_name)
        except Exception as e:
            print(f"Error fetching the minimum for table {self.table_name} at column {column_name}: {e}")
            return None

    def _calculate_num_categories(self, column_name):
        """
        :param column_name: Name of the column for which the number of categories is being calculated
        :return: The number of distinct values, or None when it cannot be calculated
        """
        try:
            query = f'SELECT COUNT(DISTINCT "{column_name}") FROM "{self.table_name}"'
            return fetch_sql(query, True, self.engine)
        except Exception as e:
            print(f"Error fetching the n_categories for table {self.table_name} at column {column_name}: {e}")
            return None

    def _calculate_mode(self, column_name):
        """
        :param column_name: Name of the column for which the mode is being calculated
        :return: The most common value, or None when it cannot be calculated
        """
        try:
            query = f"""
            SELECT "{column_name}" FROM "{self.table_name}"
            WHERE "{column_name}" IS NOT NULL
            GROUP BY "{column_name}"
            ORDER BY COUNT(*) DESC
            LIMIT 1;
            """
            return fetch_sql(query, True, self.engine)
        except Exception as e:
            print(f"Error fetching the mode for table {self.table_name} at column {column_name}: {e}")
            return None

    def _calculate_error_count_dict(self, column_name):
        """
        :param column_name: Name of the column for which the error count is being calculated
        :return: The error counts by error type, as a JSON string ({"missing": 10, "mismatch": 5, ...}), or None
                 when they cannot be counted
        """
        try:
            query = f"""
                    SELECT error_type, COUNT(*)
                    FROM "{self.error_table_name}"
                    WHERE column_id = :column_name
                    GROUP BY error_type
                  """
            rows = fetch_sql(query, False, self.engine, params={'column_name': column_name})
            return json.dumps(dict(rows))
        except Exception as e:
            print(f"Error fetching the error counts for table {self.table_name} at column {column_name}: {e}")
            return None

    def calculate_error_distribution(self):
        """
        The share of the table's rows each column's error types flag, for the attribute summary panel's badges.
        :return: {column_name: {error_type: fraction of rows}}, listing only error types that flag at least one row
        """
        query = f"""
                SELECT
                    e.column_id,
                    e.error_type,
                    COUNT(*)::float8 / NULLIF((SELECT COUNT(*) FROM "{self.table_name}"), 0) AS fraction
                FROM "{self.error_table_name}" e
                GROUP BY e.column_id, e.error_type
                """
        rows = fetch_sql(query, False, self.engine)

        distribution = {}
        for column_name, error_type, fraction in rows:
            # An empty table has no rows to take a share of
            if fraction is None:
                continue
            if column_name not in distribution:
                distribution[column_name] = {}
            distribution[column_name][error_type] = fraction
        return distribution

    def _calculate_category_count_dict(self, column_name):
        """
        :param column_name: Name of the column whose categories are being counted
        :return: How many rows hold each value, as a JSON string ({"Male": 342, "Female": 26, ...}) so it can be
                 stored in the data profile table, or None when they cannot be counted
        """
        try:
            query = f"""
                    SELECT "{column_name}", COUNT(*)
                    FROM "{self.table_name}"
                    GROUP BY "{column_name}"
                  """
            rows = fetch_sql(query, False, self.engine)

            category_counts = {}
            for category, count in rows:
                category_counts[category] = count
            return json.dumps(category_counts)
        except Exception as e:
            print(f"Error fetching the category counts for table {self.table_name} at column {column_name}: {e}")
            return None
