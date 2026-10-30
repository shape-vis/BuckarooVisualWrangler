"""
Runs the error detectors over one table inside PostgreSQL - October 12, 2026.

--- DetectorSQL ---
Finds every flagged cell of a table - missing, anomaly, mismatch and incomplete - and writes them to the table's
errors_ table, the shape every other query in the app reads: one row per flagged cell, (row_id, column_id,
error_type). Nothing leaves the database: the flags are built by one multi-step CTE query and stored with
CREATE TABLE AS.

The rules are the ones the pandas detectors applied, and the flags they produce are the same. Each error type is one
detector: a detect_<error type> method, listed in ERROR_TYPES, that contributes its rule to the query as SELECT
branches - rules over a text column's distinct values, which flag_text_values gathers, and rules over a column's cells,
which collect_flagged_cells gathers. The measurements several rules share - each text value's count, its number and its
kind, each column's mean and spread - are steps of their own, made once. Adding a detector is adding its error type to
ERROR_TYPES and writing its method; nothing else in the query changes.

Two choices make it fast. A text column is judged by its distinct values, so each one is parsed once however often it occurs, and only
the values found wanting are joined back to the rows that hold them. And every numeric column is measured in a
single scan of the table.
"""

from dataclasses import dataclass, field

from app.db_utils.column_types import ColumnTypes, missing_cell_predicate, text_number_expression
from app.error_types import error_type_keys
from app.db_utils.execute_sql import errors_table_name, execute_sql, quote_identifier, quote_literal

# The error types the detectors raise - every error_type an errors_ table holds - from shared/error_types.json, which
# the front end reads too. Metrics, compare and the AI's tools all loop over them, in this order, and each has its
# detect_ method below.
ERROR_TYPES = error_type_keys()


@dataclass
class DetectorBranches:
    """
    What one detector adds to the detection query, as SELECT branches.

    text_values: rules over the text columns' distinct values, each a SELECT of (column_id, value, error_type) from the
                 shared measurement steps - parsed_text_values, text_numeric_means, text_numeric_stats,
                 majority_value_kinds. Every row holding a value one flags is flagged with it.
    cells:       rules over a column's cells, each a SELECT of (row_id, column_id, error_type) from the table, as d,
                 and numeric_column_stats.
    """
    text_values: list = field(default_factory=list)
    cells: list = field(default_factory=list)


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
        self.error_table_name = errors_table_name(table_name)
        self.col_types = ColumnTypes.for_table(table_name, engine)

        # The data columns, in table order, and which of them are numeric or text. A column of any other type -
        # a date, say - can only be missing. The structural columns are never data, so never flagged.
        self.data_cols = self.col_types.data_column_names()
        self.numeric_cols = []
        self.text_cols = []
        for col in self.data_cols:
            if self.col_types.is_numeric_col(col):
                self.numeric_cols.append(col)
            elif self.col_types.is_text_col(col):
                self.text_cols.append(col)

        self.detectors = self.find_detectors()


    def find_detectors(self) -> list:
        """
        Every error type's detector, in ERROR_TYPES' order. An error type without a detect_ method is a mistake made
        when it was added, so it fails here rather than silently flagging nothing.
        :return: the detect_ methods.
        """

        detectors = []
        for error_type in ERROR_TYPES:
            detector = getattr(self, f"detect_{error_type}", None)
            if detector is None:
                raise NotImplementedError(f"the {error_type!r} error type has no detect_{error_type} method")
            detectors.append(detector)
        return detectors


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

        number = text_number_expression("value")

        return f''',
            parsed_text_values AS (
                SELECT
                    column_id,
                    value,
                    occurrences,
                    {number} AS number,
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
        Decides which distinct text values are flagged, and as what: every detector's rules over text values, together.
        Each value is joined back to the rows holding it at the end, in collect_flagged_cells.
        :return: the query for the flagged values.
        """

        rules = []
        for detector in self.detectors:
            rules.extend(detector().text_values)

        if not rules:
            return ''',
            flagged_text_values AS (
                -- No detector judges text values
                SELECT NULL::text AS column_id, NULL::text AS value, NULL::text AS error_type
                WHERE false
            )'''

        all_rules = "\n                UNION ALL\n                ".join(rules)

        return f''',
            flagged_text_values AS (
                {all_rules}
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
        Collects every flagged cell: every detector's rules over cells, then the cells holding a flagged text value.
        :return: the final SELECT of (row_id, column_id, error_type).
        """

        table = quote_identifier(self.table_name)
        branches = []

        for detector in self.detectors:
            branches.extend(detector().cells)

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


    # -------------------------------------------------------------------------
    # The detectors
    # One per error type in ERROR_TYPES, each named detect_<error type>. Each gives its rule as SELECT branches - see
    # DetectorBranches - which flag_text_values and collect_flagged_cells put into the query.
    # -------------------------------------------------------------------------


    def detect_missing(self) -> DetectorBranches:
        """
        missing: a cell that is NULL, or exactly one of the missing tokens - in every data column.
        :return: the detector's branches.
        """

        table = quote_identifier(self.table_name)
        cells = []
        for col in self.data_cols:
            cell = "d." + quote_identifier(col)
            column_name = quote_literal(col)
            is_missing = missing_cell_predicate(cell)
            cells.append(f'''SELECT d."ID"::bigint AS row_id, {column_name}::text AS column_id, 'missing'::text AS error_type
            FROM {table} d
            WHERE {is_missing}''')

        return DetectorBranches(cells=cells)


    def detect_mismatch(self) -> DetectorBranches:
        """
        mismatch: a text value of its column's minority kind - text among numbers, or a number among text.
        :return: the detector's branches.
        """

        rule = '''SELECT p.column_id, p.value, 'mismatch' AS error_type
                FROM parsed_text_values p
                JOIN majority_value_kinds m USING (column_id)
                WHERE p.kind <> m.kind'''

        return DetectorBranches(text_values=[rule])


    def detect_anomaly(self) -> DetectorBranches:
        """
        anomaly: a number further than ANOMALY_Z_SCORE sample standard deviations from its column's mean, in a column
        holding at least ANOMALY_MIN_VALUES numbers - a numeric column's cells, and a text column's numeric values.
        :return: the detector's branches.
        """

        text_rule = f'''SELECT p.column_id, p.value, 'anomaly' AS error_type
                FROM parsed_text_values p
                JOIN text_numeric_stats s USING (column_id)
                WHERE s.value_count >= {self.ANOMALY_MIN_VALUES}
                  AND s.std_value > 0
                  AND ABS(p.number - s.mean_value) > {self.ANOMALY_Z_SCORE} * s.std_value'''

        table = quote_identifier(self.table_name)
        cells = []
        for col in self.numeric_cols:
            cell = "d." + quote_identifier(col)
            column_name = quote_literal(col)
            cells.append(f'''SELECT d."ID"::bigint, {column_name}::text, 'anomaly'::text
            FROM {table} d
            JOIN numeric_column_stats s ON s.column_id = {column_name}
            WHERE s.value_count >= {self.ANOMALY_MIN_VALUES}
              AND s.std_value > 0
              AND ABS({cell}::float8 - s.mean_value) > {self.ANOMALY_Z_SCORE} * s.std_value''')

        return DetectorBranches(text_values=[text_rule], cells=cells)


    def detect_incomplete(self) -> DetectorBranches:
        """
        incomplete: a text value occurring fewer than INCOMPLETE_MIN_OCCURRENCES times, in a column holding at most
        INCOMPLETE_MAX_NUMERIC_VALUES numbers.
        :return: the detector's branches.
        """

        rule = f'''SELECT p.column_id, p.value, 'incomplete' AS error_type
                FROM parsed_text_values p
                LEFT JOIN text_numeric_means m USING (column_id)
                WHERE p.occurrences < {self.INCOMPLETE_MIN_OCCURRENCES}
                  AND COALESCE(m.value_count, 0) <= {self.INCOMPLETE_MAX_NUMERIC_VALUES}'''

        return DetectorBranches(text_values=[rule])
