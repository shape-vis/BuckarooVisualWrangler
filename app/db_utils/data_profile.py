"""
Profiles one table's columns inside PostgreSQL, and reads the profile back - October 22, 2026.

--- DataProfile ---
Summary statistics about every column of a table, built by one multi-step CTE query and stored with CREATE TABLE AS
as the table's dp_ table, one row per column:

    numeric      mean, median, min and max of the column's numbers
    categorical  how many categories it holds, its most common one (its mode) and each category's count
    every        how many of its cells each error type flags

Which statistics a column gets is its kind, by ColumnTypes.column_kind. A value is a number by
ColumnTypes.number_expression, the rule the plots and drift read values by, and a missing cell - by the Missing
detector's own rule - is the null category, never a mode: the mode is the value an impute of the column fills with.
"""

from app.db_utils.column_types import (CATEGORICAL_KIND, NULL_LABEL, PANDAS_INDEX_COLUMNS, ColumnTypes,
                                       category_expression)
from app.db_utils.execute_sql import (errors_table_name, execute_sql, fetch_sql, profile_table_name, quote_identifier,
                                      quote_literal)

# The columns of a dp_ table: the column a row describes, then every statistic stored for it
STORED_PROFILE_COLUMNS = ("column_name", "mean", "median", "min", "max", "n_categories", "mode",
                          "error_counts", "category_counts")

# Wraps up the data profile of one table into one class.
class DataProfile:
    def __init__(self, table_name: str, engine):
        """
        :arg: table_name: name of the table to profile.
        :arg: engine: SQLAlchemy engine.
        """
        self.table_name = table_name
        self.data_profile_table_name = profile_table_name(table_name)
        self.error_table_name = errors_table_name(table_name)
        self.col_types = ColumnTypes.for_table(table_name, engine)
        self.engine = engine


    def get_col_names(self) -> list:
        """
        The columns the profile covers: the table's columns in table order, less any index column to_sql left behind.
        :return: the column names.
        """

        col_names = []
        for col_name in self.col_types.column_names:
            if col_name not in PANDAS_INDEX_COLUMNS:
                col_names.append(col_name)
        return col_names


    def read_stored_profile(self, skipped_columns=()) -> list:
        """
        Every stored statistic of every column, as the dp_ table holds them.
        :arg: skipped_columns: columns to leave out, e.g. the row identifiers.
        :return: one dict per column, keyed by STORED_PROFILE_COLUMNS, in column name order. error_counts and
                 category_counts are {key: count} dicts; category_counts is None for a numeric column.
        """

        profile_table = quote_identifier(self.data_profile_table_name)
        column_list = ", ".join(STORED_PROFILE_COLUMNS)

        query = f'''
            SELECT {column_list}
            FROM {profile_table}
            WHERE NOT (column_name = ANY(:skipped_columns))
            ORDER BY column_name
        '''
        rows = fetch_sql(query, False, self.engine, params={"skipped_columns": list(skipped_columns)})

        profile_rows = []
        for row in rows or []:
            profile_rows.append(dict(zip(STORED_PROFILE_COLUMNS, row)))
        return profile_rows


    def generate_profile_table(self):
        """
        Creates the entire SQL query for the table's data profile, and executes it to the Postgres database, replacing
        the table's dp_ table with its result.
        """

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        profile_steps = [self.gather_column_cells(),
                         self.measure_numeric_columns(),
                         self.count_column_categories(),
                         self.measure_categorical_columns(),
                         self.count_column_errors(),
                         self.list_profiled_columns(),
                         self.construct_profile_rows()]

        profile_query = "".join(profile_steps)
        execute_sql(self.replace_profile_table(profile_query), self.engine)


    def gather_column_cells(self) -> str:
        """
        Reads every profiled column's cells, one branch per column: a numeric column's cells as numbers, a categorical
        column's as categories, with every missing cell the null category.
        :return: the query for the cells.
        """

        table = quote_identifier(self.table_name)

        branches = []
        for col_name in self.get_col_names():
            cell = "d." + quote_identifier(col_name)
            column_name = quote_literal(col_name)

            if self.col_types.column_kind(col_name) == CATEGORICAL_KIND:
                number = "NULL::float8"
                category = category_expression(cell)
            else:
                number = self.col_types.number_expression(cell, col_name)
                category = "NULL::text"

            branches.append(f'''SELECT {column_name}::text AS column_name, {number} AS number, {category} AS category
                FROM {table} d''')

        all_branches = "\n                UNION ALL\n                ".join(branches)

        return f'''
            WITH column_cells AS (
                {all_branches}
            )'''


    def measure_numeric_columns(self) -> str:
        """
        Measures each numeric column's numbers: their mean, median, min and max.
        :return: the query for the numeric statistics.
        """

        return ''',
            numeric_statistics AS (
                SELECT
                    column_name,
                    AVG(number) AS mean,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY number) AS median,
                    MIN(number) AS min,
                    MAX(number) AS max
                FROM column_cells
                WHERE number IS NOT NULL
                GROUP BY column_name
            )'''


    def count_column_categories(self) -> str:
        """
        Counts how many rows hold each category of each categorical column.
        :return: the query for the category counts.
        """

        return ''',
            category_counts AS (
                SELECT column_name, category, COUNT(*) AS occurrences
                FROM column_cells
                WHERE category IS NOT NULL
                GROUP BY column_name, category
            )'''


    def measure_categorical_columns(self) -> str:
        """
        Measures each categorical column's categories: how many it holds and which is most common, missing cells left
        out of both, and every category's count, missing cells included. A tie for the mode goes to the category first
        by name, as an impute's fill value does (app/db_utils/query.py).
        :return: the query for the categorical statistics.
        """

        null_label = quote_literal(NULL_LABEL)

        return f''',
            categorical_statistics AS (
                SELECT
                    column_name,
                    COUNT(*) FILTER (WHERE category <> {null_label}) AS n_categories,
                    (array_agg(category ORDER BY occurrences DESC, category)
                        FILTER (WHERE category <> {null_label}))[1] AS mode,
                    jsonb_object_agg(category, occurrences) AS category_counts
                FROM category_counts
                GROUP BY column_name
            )'''


    def count_column_errors(self) -> str:
        """
        Counts how many of each column's cells each error type flags.
        :return: the query for the error counts.
        """

        errors_table = quote_identifier(self.error_table_name)

        return f''',
            error_counts AS (
                SELECT column_id AS column_name, jsonb_object_agg(error_type, flagged) AS error_counts
                FROM (
                    SELECT column_id, error_type, COUNT(*) AS flagged
                    FROM {errors_table}
                    GROUP BY column_id, error_type
                ) AS flags
                GROUP BY column_id
            )'''


    def list_profiled_columns(self) -> str:
        """
        Lists the profiled columns, so a column with no numbers, no categories and no flags still gets its row.
        :return: the query for the column list.
        """

        column_rows = []
        for col_name in self.get_col_names():
            column_rows.append(f"({quote_literal(col_name)}::text)")
        column_list = ", ".join(column_rows)

        return f''',
            profiled_columns AS (
                SELECT column_name
                FROM (VALUES {column_list}) AS columns(column_name)
            )'''


    def construct_profile_rows(self) -> str:
        """
        Build the final rows of the profile: one per column, every statistic that does not fit its kind null, and its
        error counts an empty object when nothing is flagged.
        :return: the final SELECT of the profile rows.
        """

        return '''
            SELECT
                p.column_name,
                n.mean,
                n.median,
                n.min,
                n.max,
                c.n_categories,
                c.mode,
                COALESCE(e.error_counts, '{}'::jsonb) AS error_counts,
                c.category_counts
            FROM profiled_columns p
            LEFT JOIN numeric_statistics n USING (column_name)
            LEFT JOIN categorical_statistics c USING (column_name)
            LEFT JOIN error_counts e USING (column_name)'''


    def replace_profile_table(self, profile_query: str) -> str:
        """
        Replaces the dp_ table with the profile query's result.
        :arg: profile_query: the full profile query.
        :return: the statements that replace the table.
        """

        profile_table = quote_identifier(self.data_profile_table_name)

        return f'''
            DROP TABLE IF EXISTS {profile_table};
            CREATE TABLE {profile_table} AS
            {profile_query};
        '''
