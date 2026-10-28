"""
A table's column types, and the rules every query builder reads a value by: as a number, as a category, and whether
it is missing at all.
"""
import threading

from app.db_utils.execute_sql import fetch_sql, quote_identifier, quote_literal, sql_identifier

# What a value has to look like to be read as a number - the pattern every query builder reads text values by, named
# once here. It is a SQL string literal, quotes included.
NUMERIC_TEXT_REGEX = r"'^\s*-?\d+(\.\d+)?\s*$'"

# The text a cell can hold and still count as missing
MISSING_TOKENS = ("null", "undefined")

# What a missing cell is called as a category, wherever categories are counted or drawn - the label the histograms
# give a null
NULL_LABEL = "null"

# A categorical axis keeps this many labels, the last a catch-all for the long tail. Two states are read bar against
# bar, and past a couple of dozen bands neither side is legible.
MAX_LABELS = 20
OTHER_LABEL = "(other)"

# What a row deleted before the later state is called as a flow's target
REMOVED_LABEL = "(removed)"

# information_schema data types read as numbers, and as text
NUMERIC_DATA_TYPES = {'integer', 'bigint', 'numeric', 'real', 'double precision', 'smallint'}
TEXT_DATA_TYPES = {'text', 'character varying', 'character'}

# Columns that are never data: the row identifier "ID"; "Unnamed: 0", the column pandas names a CSV's unnamed index
# column; and the index columns to_sql can leave behind. The pandas detectors skipped exactly "ID" and "Unnamed: 0" -
# an upload's original id column, renamed "Original_ID" when it can't serve as "ID", is data like any other. The
# detectors, metrics, drift and the AI's profile all skip this one list.
PANDAS_INDEX_COLUMNS = ("index", "level_0")
STRUCTURAL_COLUMNS = ("ID", "Unnamed: 0") + PANDAS_INDEX_COLUMNS

# The two kinds of column every summary, metric and drift measure tells apart
NUMERIC_KIND = "numeric"
CATEGORICAL_KIND = "categorical"


def missing_cell_predicate(column_sql: str) -> str:
    """
    The rule for a missing cell: null, or exactly one of MISSING_TOKENS. The Missing detector flags by it, and every
    category count, mode and impute reads missing cells by it, so all of them agree about which cells are missing.
    :arg: column_sql: the column as it is referenced in the query, already quoted, e.g. d."Age".
    :return: a boolean SQL expression.
    """

    quoted_tokens = []
    for token in MISSING_TOKENS:
        quoted_tokens.append(quote_literal(token))
    token_list = ", ".join(quoted_tokens)

    return f"({column_sql} IS NULL OR {column_sql}::text IN ({token_list}))"


def category_expression(column_sql: str) -> str:
    """
    A cell as a category: its value as text, or NULL_LABEL when it is missing by missing_cell_predicate.
    :arg: column_sql: the cell as the query references it, already quoted, e.g. r."Gender".
    :return: a text SQL expression.
    """

    is_missing = missing_cell_predicate(column_sql)
    null_label = quote_literal(NULL_LABEL)

    return f"CASE WHEN {is_missing} THEN {null_label} ELSE {column_sql}::text END"


def text_number_expression(column_sql: str) -> str:
    """
    A text value as a number when it has the shape NUMERIC_TEXT_REGEX reads as one, and null otherwise.
    :arg: column_sql: the text value as the query references it, already quoted.
    :return: a float8 SQL expression.
    """
    return f"CASE WHEN {column_sql} ~ {NUMERIC_TEXT_REGEX} THEN {column_sql}::float8 END"


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
        oid = fetch_sql("SELECT to_regclass(:name)::oid", True, engine, params={"name": sql_identifier(main_table_name)})
        key = (str(engine.url), main_table_name, oid)

        with cls._cache_lock:
            cached = cls._cache.get(key)
        if cached is not None:
            return cached

        # Built outside the lock, so one table's scan never holds up another's; two threads racing to build the
        # same table only do the work twice
        built = cls(main_table_name, engine)
        built.table_oid = oid
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
        # The table's oid, set by for_table: with the name, it tells a table apart from one made again under its name
        self.table_oid = None
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


    def gather_numeric_cols(self, main_table_name: str):
        """
        Distinguishes the numeric columns from the categorical columns.
        :arg: main_table_name: name of the main table.
        """

        fetch_col_types = '''SELECT column_name, data_type
                             FROM information_schema.columns
                             WHERE table_name = :table_name
                             ORDER BY ordinal_position;'''

        fetched_rows = fetch_sql(fetch_col_types, False, self.engine, params={"table_name": main_table_name})
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
            raise LookupError(f"No rows fetched from table: {main_table_name}")


    def gather_mixed_cols(self, main_table_name: str):
        """
        Sorts the columns that are not of a numeric type, in one scan of the table, by how many of their values have
        the shape of a number: none makes a column purely categorical; some make it mixed, and numeric among mixed
        types when they are the majority of its rows, categorical otherwise.
        :arg: main_table_name: name of the main table.
        """

        # Initialized in gather_numeric_cols. This starts as all the columns that are not of a numeric type.
        candidates = sorted(self.mixed_cols)
        if not candidates:
            return

        counts = ["COUNT(*) AS total_count"]
        for i, col in enumerate(candidates):
            column = quote_identifier(col)
            counts.append(f"COUNT(*) FILTER (WHERE {column}::text ~ {NUMERIC_TEXT_REGEX}) AS numeric_count_{i}")
        count_list = ",\n                    ".join(counts)
        table = quote_identifier(main_table_name)

        fetch_number_counts = f'''
            SELECT
                {count_list}
            FROM {table}'''

        result = fetch_sql(fetch_number_counts, False, self.engine)
        total_count = result[0][0]
        numeric_counts = result[0][1:]

        self.mixed_cols = set()
        for col, numeric_count in zip(candidates, numeric_counts):
            if numeric_count == 0:
                self.pure_categorical.add(col)
                continue

            self.mixed_cols.add(col)
            if numeric_count > total_count / 2:
                self.numeric_mixed_cols.add(col)
            else:
                self.categorical_mixed_cols.add(col)

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
            return text_number_expression(column_sql)

        return "NULL::float8"

    def column_kind(self, col_name: str) -> str:
        """
        Whether a column is summarized, profiled and measured as numeric or categorical: text columns, purely text or
        mostly text, are categorical, and everything else is numeric.
        :arg: col_name: name of the column (assumes it is from the same table used to construct this class).
        :return: NUMERIC_KIND or CATEGORICAL_KIND.
        """
        if self.is_categorical_col(col_name) or self.is_categorical_mixed_col(col_name):
            return CATEGORICAL_KIND
        return NUMERIC_KIND

    def data_column_names(self) -> list:
        """
        :return: the table's columns in table order, the structural ones left out.
        """
        data_columns = []
        for col_name in self.column_names:
            if col_name not in STRUCTURAL_COLUMNS:
                data_columns.append(col_name)
        return data_columns

    def is_text_col(self, col_name: str):
        """
        Determines whether the given column is stored as text, whatever its values look like.
        :arg: col_name: name of the column (assumes it is from the same table used to construct this class).
        :return: whether the given col_name has a text data type.
        """
        return col_name in self.text_cols

    def is_categorical_col(self, col_name: str):
        """
        Determines whether the given column is text that holds no numeric values at all.
        :arg: col_name: name of the column (assumes it is from the same table used to construct this class).
        :return: whether the given col_name is purely categorical.
        """
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


    def is_categorical_mixed_col(self, col_name: str):
        """
        Determines whether the given column from the table used to construct this class is categorical among mixed types.
        :arg: col_name: name of the column (assumes it is from the same table used to construct this class).
        :return: whether the given col_name is majority categorical among mixed types.
        """
        return col_name in self.categorical_mixed_cols
