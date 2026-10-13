"""
Runs the error detectors over one table inside PostgreSQL - October 12, 2026.

--- DetectorSQL ---
Finds every flagged cell of a table - missing, anomaly, mismatch and incomplete - and writes them to the table's
errors_ table, the shape every other query in the app reads: one row per flagged cell, (row_id, column_id,
error_type). Nothing leaves the database: the flags are built by one multi-step CTE query and stored with
CREATE TABLE AS.

The rules are the ones the pandas detectors applied, and the flags they produce are the same. Two choices make it
fast. A text column is judged by its distinct values, so each one is parsed once however often it occurs, and only
the values found wanting are joined back to the rows that hold them. And every numeric column is measured in a
single scan of the table.
"""

from app.db_utils.column_types import ColumnTypes, NUMERIC_TEXT_REGEX
from app.db_utils.execute_sql import execute_sql, quote_identifier, quote_literal


# Row identifiers, and the index columns pandas leaves behind: never data, so never flagged
STRUCTURAL_COLUMNS = ("ID", "index", "level_0")

# The text a cell can hold and still count as missing
MISSING_TOKENS = ("null", "undefined")

# The error types the detectors raise - every error_type an errors_ table holds
ERROR_TYPES = ("missing", "anomaly", "mismatch", "incomplete")


def missing_cell_predicate(column_sql: str) -> str:
    """
    The rule for a missing cell: null, or exactly one of MISSING_TOKENS. Drift labels a categorical column's missing
    cells by this same rule (DriftSQL), so the two panels always agree about which cells are missing.
    :arg: column_sql: the column as it is referenced in the query, already quoted, e.g. d."Age".
    :return: a boolean SQL expression.
    """

    quoted_tokens = []
    for token in MISSING_TOKENS:
        quoted_tokens.append(quote_literal(token))
    token_list = ", ".join(quoted_tokens)

    return f"({column_sql} IS NULL OR {column_sql}::text IN ({token_list}))"


# Wraps up error detection for one table into one class.
class DetectorSQL:
    # anomaly - a number further than this many sample standard deviations from its column's mean
    ANOMALY_Z_SCORE = 2
    # anomaly - a column with fewer numbers than this is not judged
    ANOMALY_MIN_VALUES = 10
    # incomplete - only columns holding at most this many numbers are judged
    INCOMPLETE_MAX_NUMERIC_VALUES = 10
    # incomplete - a value occurring fewer times than this is flagged
    INCOMPLETE_MIN_OCCURRENCES = 3
    # mismatch - what a value has to look like, once trimmed, to be of the numeric kind
    MISMATCH_NUMBER_REGEX = r"'^\d+(\.\d+)?$'"
    # mismatch - the whitespace trimmed first: Python's str.strip set, which the pandas detector trimmed with
    MISMATCH_TRIMMED = r"E' \t\n\r\f\x0B'"

    def __init__(self, engine, table_name: str):
        """
        :arg: engine: SQLAlchemy engine.
        :arg: table_name: the table to detect errors in. Its flags go to errors_<table_name>.
        """
        self.engine = engine
        self.table_name = table_name
        self.error_table_name = f"errors_{table_name}"
        self.col_types = ColumnTypes.for_table(table_name, engine)

        # The data columns, in table order, and which of them are numeric or text. A column of any other type -
        # a date, say - can only be missing.
        self.data_cols = []
        self.numeric_cols = []
        self.text_cols = []
        for col in self.col_types.column_names:
            if col in STRUCTURAL_COLUMNS:
                continue
            self.data_cols.append(col)
            if self.col_types.is_numeric_col(col):
                self.numeric_cols.append(col)
            elif self.col_types.is_text_col(col):
                self.text_cols.append(col)


    def generate_errors_table(self):
        """
        Creates the entire SQL query for detecting every error in the table, and executes it to the Postgres database,
        replacing the table's errors table with its result.
        """

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        detection_steps = [self.count_text_values(),
                           self.parse_text_values(),
                           self.average_text_numbers(),
                           self.measure_text_numbers(),
                           self.find_majority_kinds(),
                           self.flag_text_values(),
                           self.measure_numeric_columns(),
                           self.collect_flagged_cells()]

        detection_query = "".join(detection_steps)
        execute_sql(self.replace_errors_table(detection_query), self.engine)


    def count_text_values(self) -> str:
        """
        Counts how often each distinct value occurs in each text column. Every text rule below judges these values
        rather than the cells, so the regexes run once per value however many rows hold it.
        :return: the query for the value counts.
        """

        if not self.text_cols:
            return '''
            WITH text_value_counts AS (
                -- The table has no text columns, so there is nothing for the text rules to judge
                SELECT NULL::text AS column_id, NULL::text AS value, 0::bigint AS occurrences
                WHERE false
            )'''

        table = quote_identifier(self.table_name)
        per_column_counts = []
        for col in self.text_cols:
            column = quote_identifier(col)
            column_name = quote_literal(col)
            per_column_counts.append(f'''SELECT {column_name}::text AS column_id, {column}::text AS value, COUNT(*) AS occurrences
                FROM {table}
                WHERE {column} IS NOT NULL
                GROUP BY {column}''')

        all_counts = "\n                UNION ALL\n                ".join(per_column_counts)

        return f'''
            WITH text_value_counts AS (
                {all_counts}
            )'''


    def parse_text_values(self) -> str:
        """
        Reads each distinct text value two ways: as a number, where it has the shape the plots read as numeric, and
        as the mismatch detector's kind, numeric or text.
        :return: the query for the parsed values.
        """

        return f''',
            parsed_text_values AS (
                SELECT
                    column_id,
                    value,
                    occurrences,
                    CASE WHEN value ~ {NUMERIC_TEXT_REGEX} THEN value::float8 END AS number,
                    CASE
                        WHEN btrim(value, {self.MISMATCH_TRIMMED}) ~ {self.MISMATCH_NUMBER_REGEX} THEN 'numeric'
                        ELSE 'text'
                    END AS kind
                FROM text_value_counts
            )'''


    def average_text_numbers(self) -> str:
        """
        Averages the numbers in each text column, weighted by how often each occurs: how many there are and their mean.
        :return: the query for the means.
        """

        return ''',
            text_numeric_means AS (
                SELECT
                    column_id,
                    SUM(occurrences) AS value_count,
                    SUM(occurrences * number) / SUM(occurrences) AS mean_value
                FROM parsed_text_values
                WHERE number IS NOT NULL
                GROUP BY column_id
            )'''


    def measure_text_numbers(self) -> str:
        """
        Adds the sample standard deviation to each text column's numbers, measured from the mean in a second pass over
        the distinct values, as the anomaly detector reads it.
        :return: the query for the stats.
        """

        return ''',
            text_numeric_stats AS (
                SELECT
                    p.column_id,
                    m.value_count,
                    m.mean_value,
                    SQRT(SUM(p.occurrences * (p.number - m.mean_value) ^ 2) / NULLIF(m.value_count - 1, 0)) AS std_value
                FROM parsed_text_values p
                JOIN text_numeric_means m USING (column_id)
                WHERE p.number IS NOT NULL
                GROUP BY p.column_id, m.value_count, m.mean_value
            )'''


    def find_majority_kinds(self) -> str:
        """
        Finds the kind most of each text column's values are. A tie goes to the kind holding the column's most frequent value
        - the one the pandas detector met first, reading values most common first - and then to the name.
        :return: the query for the majority kinds.
        """

        return ''',
            majority_value_kinds AS (
                SELECT DISTINCT ON (column_id) column_id, kind
                FROM (
                    SELECT column_id, kind, SUM(occurrences) AS total, MAX(occurrences) AS most_frequent
                    FROM parsed_text_values
                    GROUP BY column_id, kind
                ) AS kinds
                ORDER BY column_id, total DESC, most_frequent DESC, kind
            )'''


    def flag_text_values(self) -> str:
        """
        Decides which distinct text values are flagged, and as what. Each is joined back to the rows holding it at the
        end, in collect_flagged_cells.
        :return: the query for the flagged values.
        """

        return f''',
            flagged_text_values AS (
                -- anomaly: a number far from the mean of its column's numbers
                SELECT p.column_id, p.value, 'anomaly' AS error_type
                FROM parsed_text_values p
                JOIN text_numeric_stats s USING (column_id)
                WHERE s.value_count >= {self.ANOMALY_MIN_VALUES}
                  AND s.std_value > 0
                  AND ABS(p.number - s.mean_value) > {self.ANOMALY_Z_SCORE} * s.std_value
                UNION ALL
                -- mismatch: a value of the column's minority kind
                SELECT p.column_id, p.value, 'mismatch'
                FROM parsed_text_values p
                JOIN majority_value_kinds m USING (column_id)
                WHERE p.kind <> m.kind
                UNION ALL
                -- incomplete: a rare value, in a column that holds hardly any numbers
                SELECT p.column_id, p.value, 'incomplete'
                FROM parsed_text_values p
                LEFT JOIN text_numeric_means m USING (column_id)
                WHERE p.occurrences < {self.INCOMPLETE_MIN_OCCURRENCES}
                  AND COALESCE(m.value_count, 0) <= {self.INCOMPLETE_MAX_NUMERIC_VALUES}
            )'''


    def measure_numeric_columns(self) -> str:
        """
        Measures every numeric column in one scan of the table: how many numbers it holds, their mean, and their sample
        standard deviation - what the anomaly detector reads.
        :return: the query for the numeric column stats.
        """

        if not self.numeric_cols:
            return ''',
            numeric_column_stats AS (
                -- The table has no numeric columns, so there is nothing to measure
                SELECT NULL::text AS column_id, 0::bigint AS value_count, NULL::float8 AS mean_value, NULL::float8 AS std_value
                WHERE false
            )'''

        # The scan yields one wide row - three aggregates per column, numbered by the column's position - which is
        # then unpivoted into one row per column
        aggregates = []
        per_column_rows = []
        for i, col in enumerate(self.numeric_cols):
            column = quote_identifier(col)
            aggregates.append(f"COUNT({column}) AS value_count_{i}")
            aggregates.append(f"AVG({column}::float8) AS mean_value_{i}")
            aggregates.append(f"STDDEV_SAMP({column}::float8) AS std_value_{i}")

            column_name = quote_literal(col)
            per_column_rows.append(f"({column_name}, value_count_{i}, mean_value_{i}, std_value_{i})")

        aggregate_list = ",\n                        ".join(aggregates)
        per_column_list = ",\n                    ".join(per_column_rows)
        table = quote_identifier(self.table_name)

        return f''',
            numeric_column_stats AS (
                SELECT stats.column_id, stats.value_count, stats.mean_value, stats.std_value
                FROM (
                    SELECT
                        {aggregate_list}
                    FROM {table}
                ) AS aggregates
                CROSS JOIN LATERAL (VALUES
                    {per_column_list}
                ) AS stats(column_id, value_count, mean_value, std_value)
            )'''


    def collect_flagged_cells(self) -> str:
        """
        Collects every flagged cell, one branch per column and rule: missing cells in every column, anomalies in the
        numeric columns, and the cells holding a flagged text value.
        :return: the final SELECT of (row_id, column_id, error_type).
        """

        table = quote_identifier(self.table_name)
        branches = []

        for col in self.data_cols:
            cell = "d." + quote_identifier(col)
            column_name = quote_literal(col)
            is_missing = missing_cell_predicate(cell)
            branches.append(f'''SELECT d."ID"::bigint AS row_id, {column_name}::text AS column_id, 'missing'::text AS error_type
            FROM {table} d
            WHERE {is_missing}''')

        for col in self.numeric_cols:
            cell = "d." + quote_identifier(col)
            column_name = quote_literal(col)
            branches.append(f'''SELECT d."ID"::bigint, {column_name}::text, 'anomaly'::text
            FROM {table} d
            JOIN numeric_column_stats s ON s.column_id = {column_name}
            WHERE s.value_count >= {self.ANOMALY_MIN_VALUES}
              AND s.std_value > 0
              AND ABS({cell}::float8 - s.mean_value) > {self.ANOMALY_Z_SCORE} * s.std_value''')

        for col in self.text_cols:
            cell = "d." + quote_identifier(col)
            column_name = quote_literal(col)
            branches.append(f'''SELECT d."ID"::bigint, f.column_id, f.error_type
            FROM {table} d
            JOIN flagged_text_values f ON f.column_id = {column_name} AND f.value = {cell}::text''')

        # A table with no data columns has nothing to flag, but its errors table still needs the right shape
        if not branches:
            return '''
            SELECT NULL::bigint AS row_id, NULL::text AS column_id, NULL::text AS error_type
            WHERE false'''

        all_branches = "\n            UNION ALL\n            ".join(branches)

        return f'''
            {all_branches}'''


    def replace_errors_table(self, detection_query: str) -> str:
        """
        Replaces the errors table with the detection query's result, and indexes it the way the plots read it: by
        column, then row.
        :arg: detection_query: the full detection query.
        :return: the statements that replace the table.
        """

        errors = quote_identifier(self.error_table_name)

        return f'''
            DROP TABLE IF EXISTS {errors};
            CREATE TABLE {errors} AS
            {detection_query};
            CREATE INDEX ON {errors} (column_id, row_id);
        '''
