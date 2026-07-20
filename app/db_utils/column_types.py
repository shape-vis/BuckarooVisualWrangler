
class ColumnTypes:
    def __init__(self, main_table_name: str, engine):
        self.numeric_cols = set()
        self.mixed_cols = set()
        self.categorical_mixed_cols = set()
        self.numeric_mixed_cols = set()
        self.pure_categorical = set()
        self.engine = engine
        self.gather_numeric_cols(main_table_name)
        self.gather_mixed_cols(main_table_name)
        self.categorize_mixed_cols(main_table_name)


    def gather_numeric_cols(self, main_table_name: str):
        from app.db_utils.execute_sql import fetch_sql
        """
        Distinguishes the numeric columns from the categorical columns.
        :arg: main_table_name: name of the main table.
        """


        fetch_col_types = f'''SELECT column_name, data_type
                              FROM information_schema.columns
                              WHERE table_name = '{main_table_name}';'''

        fetched_rows = fetch_sql(fetch_col_types, False, self.engine)
        if fetched_rows:
            numeric_types = {
                'integer', 'bigint', 'numeric',
                'real', 'double precision', 'smallint'
            }

            for row in fetched_rows:
                col_name = row[0]
                data_type = row[1]

                if data_type in numeric_types:
                    self.numeric_cols.add(col_name)
                else:
                    self.mixed_cols.add(col_name)
        else:
            raise Exception(f"No rows fetched from table: {main_table_name}")


    def gather_mixed_cols(self, main_table_name: str):
        from app.db_utils.execute_sql import fetch_sql
        """
        Gather the columns that are labeled as categorical but contain numeric data as well.
        :arg: main_table_name: name of the main table.
        """

        # There are no categorical columns in the dataset.
        if len(self.mixed_cols) == 0:
            return

        numeric_regex = r"'^\s*-?\d+(\.\d+)?\s*$'"

        # Initialized in the other constructor func gather_numeric_cols. This starts as all categorical columns.
        # Stop early if a mixed type is found, since that makes the entire column of mixed type.
        queries = [
            f"""(
                SELECT '{col}' AS column_name
                FROM "{main_table_name}"
                WHERE "{col}" ~ {numeric_regex}
                LIMIT 1
            )"""
            for col in self.mixed_cols
        ]

        fetch_mixed_types = "\nUNION ALL\n".join(queries)
        mixed_cols = fetch_sql(fetch_mixed_types, False, self.engine)

        mixed_col_names = set(row[0] for row in mixed_cols) if mixed_cols else set()
        self.pure_categorical = self.mixed_cols - mixed_col_names
        self.mixed_cols = mixed_col_names

    def categorize_mixed_cols(self, main_table_name: str):
        """
        Categorizes the mixed columns into numeric and categorical based on the majority of their values.
        :arg: main_table_name: name of the main table.
        """
        from app.db_utils.execute_sql import fetch_sql

        for col in self.mixed_cols:
            query = f"""
                   SELECT
                       SUM(CASE WHEN pg_input_is_valid("{col}", \'numeric\' )THEN 1 ELSE 0 END) AS numeric_count,
                       COUNT(*) AS total_count
                   FROM "{main_table_name}";
               """
            result = fetch_sql(query, False, self.engine)
            if result:
                numeric_count, total_count = result[0]
                if numeric_count > total_count / 2:
                    self.numeric_mixed_cols.add(col)
                else:
                    self.categorical_mixed_cols.add(col)
            else:
                raise Exception(f"No rows fetched for column: {col} in table: {main_table_name}")

    def is_categorical_col(self, col_name: str):
        return col_name in self.pure_categorical

    def is_numeric_col(self, col_name: str):
            """
            Determines whether the given column from the table used to construct this class is numeric.
            :arg: col_name: name of the column (assumes it is from the same table used to construct this class).
            :return: whether the given col_name is numeric.
            """
            return col_name in self.numeric_cols


    def is_mixed_col(self, col_name: str):
        """
        Determines whether the given column from the table used to construct this class is of mixed type.
        :arg: col_name: name of the column (assumes it is from the same table used to construct this class).
        :return: whether the given col_name is of mixed type.
        """
        return col_name in self.mixed_cols


    def is_numeric_mixed_col(self, col_name: str):
        """
        Determines whether the given column from the table used to construct this class is numeric among mixed types.
        :arg: col_name: name of the column (assumes it is from the same table used to construct this class).
        :return: whether the given col_name is majority numeric among mixed types.
        """
        return col_name in self.numeric_mixed_cols

    def is_categorical_mixed_col(self, col_name: str):
        """
        Determines whether the given column from the table used to construct this class is categorical among mixed types.
        :arg: col_name: name of the column (assumes it is from the same table used to construct this class).
        :return: whether the given col_name is majority categorical among mixed types.
        """
        return col_name in self.categorical_mixed_cols
