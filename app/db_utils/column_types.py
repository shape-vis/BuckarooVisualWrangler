import threading

from app.db_utils.execute_sql import fetch_sql

# What a value has to look like to be read as a number - the pattern DBOperations' plots and the type checks below
# already use, named once for the query builders that share it. It is a SQL string literal, quotes included.
NUMERIC_TEXT_REGEX = r"'^\s*-?\d+(\.\d+)?\s*$'"

# information_schema data types read as numbers, and as text
NUMERIC_DATA_TYPES = {'integer', 'bigint', 'numeric', 'real', 'double precision', 'smallint'}
TEXT_DATA_TYPES = {'text', 'character varying', 'character'}


class ColumnTypes:
    # Built types, by (database, table, table oid) - see for_table
    _cache = {}
    _cache_lock = threading.Lock()

    @classmethod
    def for_table(cls, main_table_name: str, engine):
        """
        The table's column types, built once and shared. Building them scans every text column, and they are asked
        for on every navigation, plot, profile and summary, while a node's table never changes once it is made.
        The cache is keyed on the table's oid as well as its name, so a table dropped and made again under the same
        name is classified afresh. A column deleted in place keeps the oid, so delete-column calls forget.
        :arg: main_table_name: name of the table.
        :arg: engine: SQLAlchemy engine.
        :return: the table's ColumnTypes.
        """

        # The name is a bound value here, not query text, so it is quoted only as Postgres reads a name
        quoted_name = '"' + main_table_name.replace('"', '""') + '"'
        oid = fetch_sql("SELECT to_regclass(:name)::oid", True, engine, params={"name": quoted_name})
        key = (str(engine.url), main_table_name, oid)

        with cls._cache_lock:
            cached = cls._cache.get(key)
        if cached is not None:
            return cached

        # Built outside the lock, so one table's scan never holds up another's; two threads racing to build the
        # same table only do the work twice
        built = cls(main_table_name, engine)
        if oid is not None:
            with cls._cache_lock:
                cls._cache[key] = built
        return built

    @classmethod
    def forget(cls, main_table_name: str):
        """
        Drop a table's cached types, when the table loses a column in place or is dropped.
        :arg: main_table_name: name of the table.
        """

        with cls._cache_lock:
            stale_keys = []
            for key in cls._cache:
                cached_table_name = key[1]
                if cached_table_name == main_table_name:
                    stale_keys.append(key)

            for key in stale_keys:
                del cls._cache[key]

    def __init__(self, main_table_name: str, engine):
        self.column_names = []
        self.text_cols = set()
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
                              WHERE table_name = '{main_table_name}'
                              ORDER BY ordinal_position;'''

        fetched_rows = fetch_sql(fetch_col_types, False, self.engine)
        if fetched_rows:
            for row in fetched_rows:
                col_name = row[0]
                data_type = row[1]
                self.column_names.append(col_name)

                if data_type in TEXT_DATA_TYPES:
                    self.text_cols.add(col_name)

                if data_type in NUMERIC_DATA_TYPES:
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
                    SUM(CASE WHEN "{col}" ~ '^-?(\\d+\\.?\\d*|\\d*\\.?\\d+)([eE][+-]?\\d+)?$' THEN 1 ELSE 0 END) AS numeric_count,
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

    def number_expression(self, column_sql: str, col_name: str) -> str:
        """
        The column's values as numbers, the way the plots read them: a numeric column's finite values as they are,
        a text value of numeric shape parsed, and anything else null.
        :arg: column_sql: the column as the query references it, already quoted, e.g. d."Age".
        :arg: col_name: name of the column (assumes it is from the same table used to construct this class).
        :return: a float8 SQL expression.
        """
        if self.is_numeric_col(col_name):
            return f"""CASE
                    WHEN {column_sql}::float8 IN ('NaN', 'Infinity', '-Infinity') THEN NULL
                    ELSE {column_sql}::float8
                END"""

        if self.is_text_col(col_name):
            return f"CASE WHEN {column_sql} ~ {NUMERIC_TEXT_REGEX} THEN {column_sql}::float8 END"

        return "NULL::float8"

    def is_text_col(self, col_name: str):
        """
        Determines whether the given column is stored as text, whatever its values look like.
        :arg: col_name: name of the column (assumes it is from the same table used to construct this class).
        :return: whether the given col_name has a text data type.
        """
        return col_name in self.text_cols

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
