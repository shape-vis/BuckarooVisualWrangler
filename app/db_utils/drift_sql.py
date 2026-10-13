from app.db_utils.column_types import ColumnTypes
from app.db_utils.compare_sql import NULL_LABEL
from app.db_utils.detector_sql import missing_cell_predicate
from app.db_utils.execute_sql import fetch_sql, quote_identifier, quote_literal

"""
Measures how far one node's data has drifted from a reference state, inside PostgreSQL - October 12, 2026.

--- DriftSQL ---
Gathers the numbers app/pgraph/distortion.py's drift metric is computed from, for one node against one reference -
root, or one of the node's ancestors. Every row stays in the database; what comes back is a handful of numbers per
column, each column measured by a query of its own so a table's columns can be measured all at once:

    numeric      the Wasserstein-1 distance between the two states' values, and the reference's quartiles and sample
                 standard deviation, which scale it
    categorical  the total variation distance between the two states' category shares

and, for the drill-down views, the edit facts (rows removed, cells changed), quantiles, category shares, category
flows and the value masses a ridgeline is smoothed from.

The definitions are distortion.py's, computed the way numpy and scipy compute them: quantiles interpolate linearly,
as percentile_cont and np.quantile both do, and the Wasserstein distance is scipy's - the area between the two
states' cumulative distributions, summed over the gaps between consecutive distinct values.

A value is a number by ColumnTypes.number_expression, the rule the plots read values by. In a categorical column a
missing cell - by the Missing detector's own rule - is a category of its own, labelled null.
"""

NUMERIC = "numeric"
CATEGORICAL = "categorical"

# What a row deleted before the later state is called as a flow's target. A missing cell is called NULL_LABEL, as the
# compare plots call it.
REMOVED_LABEL = "(removed)"

# np.isclose's tolerances, which decide whether two numbers in a cell are the same value
RELATIVE_TOLERANCE = 1e-05
ABSOLUTE_TOLERANCE = 1e-08


# Wraps up the drift measurements between one reference table and one node table into one class.
class DriftSQL:
    def __init__(self, engine, reference_table: str, node_table: str, kinds: dict):
        """
        :arg: engine: SQLAlchemy engine.
        :arg: reference_table: the state drift is measured from - root, or one of the node's ancestors.
        :arg: node_table: the node's table.
        :arg: kinds: {column: NUMERIC or CATEGORICAL} for root's data columns. Kinds are decided on root and held for
                     every node, so a column cannot switch statistics part way down a branch.
        """
        self.engine = engine
        self.reference_table = reference_table
        self.node_table = node_table
        self.kinds = kinds
        self.reference_types = ColumnTypes.for_table(reference_table, engine)
        self.node_types = ColumnTypes.for_table(node_table, engine)


    def is_shared(self, column: str) -> bool:
        """
        Determines whether both tables hold the column - a column dropped along the way is held by only one.
        :arg: column: name of the column.
        :return: whether both the reference and the node have the column.
        """
        return column in self.reference_types.column_names and column in self.node_types.column_names


    # -------------------------------------------------------------------------
    # One column's drift
    # Each column is measured by its own query, so a caller can measure a table's columns all at once - see
    # measure_columns in app/pgraph/distortion.py.
    # -------------------------------------------------------------------------


    def column_plan(self) -> list:
        """
        Lists the columns a node's drift covers: root's data columns, in root's order, then any column only the node
        has.
        :return: one {"column", "kind", "in_node"} per column - kind None for a column only the node has, in_node False
                 for one the node dropped.
        """

        plan = []
        for col, kind in self.kinds.items():
            in_node = col in self.node_types.column_names
            plan.append({"column": col, "kind": kind, "in_node": in_node})

        for col in self.node_types.column_names:
            added_by_node = col not in self.kinds and col not in self.reference_types.column_names
            if added_by_node:
                plan.append({"column": col, "kind": None, "in_node": True})

        return plan


    def generate_numeric_drift(self, column: str) -> dict:
        """
        Creates the entire SQL query for one numeric column's drift inputs and executes it to the Postgres database:
        the Wasserstein-1 distance between the two states' numbers, and the reference's quartiles and sample standard
        deviation, which scale it.
        :arg: column: a numeric column both tables hold.
        :return: {"column", "n_reference", "n_node", "wasserstein", "q1", "q3", "std"}
        """

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        numeric_drift_steps = [self.gather_value_masses(column),
                               self.count_values(),
                               self.accumulate_distributions(),
                               self.measure_wasserstein(),
                               self.measure_reference_spread(column),
                               self.construct_numeric_drift_json(column)]

        numeric_drift_query = "".join(numeric_drift_steps)
        return fetch_sql(numeric_drift_query, True, self.engine)


    def gather_value_masses(self, column: str) -> str:
        """
        Counts each distinct number in the column, in the reference and in the node. The distance is measured over
        these distinct values, so the column's repeated values cost nothing extra.
        :arg: column: the column.
        :return: the query for the value masses.
        """

        reference_numbers = self.side_numbers(self.reference_table, self.reference_types, column)
        node_numbers = self.side_numbers(self.node_table, self.node_types, column)

        return f'''
            WITH value_masses AS (
                SELECT
                    number,
                    COUNT(*) FILTER (WHERE side = 'reference') AS reference_count,
                    COUNT(*) FILTER (WHERE side = 'node') AS node_count
                FROM (
                    SELECT 'reference' AS side, number FROM {reference_numbers} AS reference_side
                    UNION ALL
                    SELECT 'node', number FROM {node_numbers} AS node_side
                ) AS both_sides
                WHERE number IS NOT NULL
                GROUP BY number
            )'''


    def count_values(self) -> str:
        """
        Counts the column's numbers in the reference and in the node.
        :return: the query for the value counts.
        """

        return ''',
            value_counts AS (
                SELECT SUM(reference_count) AS n_reference, SUM(node_count) AS n_node
                FROM value_masses
            )'''


    def accumulate_distributions(self) -> str:
        """
        Walks the column's distinct numbers in order: the share of the reference's values and of the node's at or below
        each one - the two cumulative distributions - and the gap up to the next number.
        :return: the query for the cumulative distributions.
        """

        return ''',
            distributions AS (
                SELECT
                    SUM(m.reference_count) OVER running / NULLIF(c.n_reference, 0)::float8 AS reference_cdf,
                    SUM(m.node_count) OVER running / NULLIF(c.n_node, 0)::float8 AS node_cdf,
                    LEAD(m.number) OVER running - m.number AS gap
                FROM value_masses m
                CROSS JOIN value_counts c
                WINDOW running AS (ORDER BY m.number)
            )'''


    def measure_wasserstein(self) -> str:
        """
        Measures the Wasserstein-1 distance: the area between the two cumulative distributions. The last number has no
        gap after it, so it adds nothing.
        :return: the query for the distance.
        """

        return ''',
            wasserstein AS (
                SELECT COALESCE(SUM(ABS(reference_cdf - node_cdf) * gap), 0) AS distance
                FROM distributions
                WHERE gap IS NOT NULL
            )'''


    def measure_reference_spread(self, column: str) -> str:
        """
        Measures the reference's spread in the column - its quartiles, and its sample standard deviation for a column
        whose middle half is a single value - which the distance is measured in.
        :arg: column: the column.
        :return: the query for the spread.
        """

        reference_numbers = self.side_numbers(self.reference_table, self.reference_types, column)

        return f''',
            reference_spread AS (
                SELECT
                    percentile_cont(0.25) WITHIN GROUP (ORDER BY number) AS q1,
                    percentile_cont(0.75) WITHIN GROUP (ORDER BY number) AS q3,
                    STDDEV_SAMP(number) AS std
                FROM {reference_numbers} AS reference_side
                WHERE number IS NOT NULL
            )'''


    def construct_numeric_drift_json(self, column: str) -> str:
        """
        Build the final JSON object for one numeric column's drift inputs.
        :arg: column: the column.
        :return: the query for the final JSON object.
        """

        column_name = quote_literal(column)

        return f'''
            SELECT json_build_object(
                'column', {column_name}::text,
                'n_reference', COALESCE(c.n_reference, 0),
                'n_node', COALESCE(c.n_node, 0),
                'wasserstein', w.distance,
                'q1', s.q1,
                'q3', s.q3,
                'std', s.std
            )
            FROM value_counts c, wasserstein w, reference_spread s'''


    def generate_categorical_drift(self, column: str) -> dict:
        """
        Creates the entire SQL query for one categorical column's drift inputs and executes it to the Postgres
        database: the total variation distance between the two states' category shares. Missing cells are a category
        of their own.
        :arg: column: a categorical column both tables hold.
        :return: {"column", "n_reference", "n_node", "tvd"}
        """

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        categorical_drift_steps = [self.gather_column_categories(column),
                                   self.count_column_categories(),
                                   self.count_category_rows(),
                                   self.measure_category_tvd(),
                                   self.construct_categorical_drift_json(column)]

        categorical_drift_query = "".join(categorical_drift_steps)
        return fetch_sql(categorical_drift_query, True, self.engine)


    def count_category_rows(self) -> str:
        """
        Counts the column's rows in the reference and in the node.
        :return: the query for the row counts.
        """

        return ''',
            category_row_counts AS (
                SELECT SUM(reference_count) AS n_reference, SUM(node_count) AS n_node
                FROM column_category_counts
            )'''


    def measure_category_tvd(self) -> str:
        """
        Measures the total variation distance: half the summed change in each category's share. Halved because a row
        leaving one category arrives in another; unhalved, every move would count twice.
        :return: the query for the distance.
        """

        return ''',
            category_tvd AS (
                SELECT
                    0.5 * SUM(ABS(
                        c.node_count / NULLIF(r.n_node, 0)::float8 - c.reference_count / NULLIF(r.n_reference, 0)::float8
                    )) AS distance
                FROM column_category_counts c
                CROSS JOIN category_row_counts r
            )'''


    def construct_categorical_drift_json(self, column: str) -> str:
        """
        Build the final JSON object for one categorical column's drift inputs.
        :arg: column: the column.
        :return: the query for the final JSON object.
        """

        column_name = quote_literal(column)

        return f'''
            SELECT json_build_object(
                'column', {column_name}::text,
                'n_reference', COALESCE(r.n_reference, 0),
                'n_node', COALESCE(r.n_node, 0),
                'tvd', t.distance
            )
            FROM category_row_counts r, category_tvd t'''


    def generate_present_cells(self, side: str) -> dict:
        """
        Creates the entire SQL query for one table's non-null cells per column, counted in one scan of it, and executes
        it to the Postgres database: root's data columns, and any column only the node has.
        :arg: side: "reference" or "node".
        :return: {column: non-null cells}
        """

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        present_cell_steps = [self.count_present_cells(side),
                              self.construct_present_cells_json()]

        present_cells_query = "".join(present_cell_steps)
        return fetch_sql(present_cells_query, True, self.engine)


    def count_present_cells(self, side: str) -> str:
        """
        Counts each column's non-null cells in one table, in one scan of it.
        :arg: side: "reference" or "node".
        :return: the query for the presence counts.
        """

        if side == "reference":
            table_name, col_types = self.reference_table, self.reference_types
        else:
            table_name, col_types = self.node_table, self.node_types

        counted = []
        for col in col_types.column_names:
            added_by_node = col not in self.reference_types.column_names
            if col in self.kinds or added_by_node:
                counted.append(col)

        if not counted:
            return '''
            WITH presence AS (
                SELECT NULL::text AS column_id, 0::bigint AS present
                WHERE false
            )'''

        counts = []
        per_column_rows = []
        for i, col in enumerate(counted):
            column = quote_identifier(col)
            column_name = quote_literal(col)
            counts.append(f"COUNT({column}) AS present_{i}")
            per_column_rows.append(f"({column_name}, present_{i})")

        count_list = ",\n                        ".join(counts)
        per_column_list = ",\n                    ".join(per_column_rows)
        table = quote_identifier(table_name)

        return f'''
            WITH presence AS (
                SELECT cells.column_id, cells.present
                FROM (
                    SELECT
                        {count_list}
                    FROM {table}
                ) AS counts
                CROSS JOIN LATERAL (VALUES
                    {per_column_list}
                ) AS cells(column_id, present)
            )'''


    def construct_present_cells_json(self) -> str:
        """
        Build the final JSON object for the presence counts.
        :return: the query for the final JSON object.
        """

        return '''
            SELECT COALESCE(json_object_agg(column_id, present), '{}'::json)
            FROM presence'''


    # -------------------------------------------------------------------------
    # What the wrangles between the two states did
    # Measured row by row once, and cell by cell one column per query, so the columns can be counted all at once.
    # -------------------------------------------------------------------------


    def generate_row_counts(self) -> dict:
        """
        Creates the entire SQL query for how the two states' rows match up, and executes it to the Postgres database:
        the reference's rows, those of them the node no longer holds, and those of the node's the reference never held -
        which no wrangle can create, so any at all means the two are not reference and descendant.
        :return: {"rows_reference", "rows_removed", "rows_unknown", "first_unknown_id"}
        """

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        row_count_steps = [self.match_row_ids(),
                           self.construct_row_counts_json()]

        row_counts_query = "".join(row_count_steps)
        return fetch_sql(row_counts_query, True, self.engine)


    def match_row_ids(self) -> str:
        """
        Matches the two states' rows by "ID" in one full join, and counts the matches.
        :return: the query for the row matches.
        """

        reference = quote_identifier(self.reference_table)
        node = quote_identifier(self.node_table)

        return f'''
            WITH row_matches AS (
                SELECT
                    COUNT(r."ID") AS rows_reference,
                    COUNT(*) FILTER (WHERE n."ID" IS NULL) AS rows_removed,
                    COUNT(*) FILTER (WHERE r."ID" IS NULL) AS rows_unknown,
                    MIN(n."ID") FILTER (WHERE r."ID" IS NULL) AS first_unknown_id
                FROM (SELECT "ID" FROM {reference}) r
                FULL OUTER JOIN (SELECT "ID" FROM {node}) n ON n."ID" = r."ID"
            )'''


    def construct_row_counts_json(self) -> str:
        """
        Build the final JSON object for the row counts.
        :return: the query for the final JSON object.
        """

        return '''
            SELECT json_build_object(
                'rows_reference', rows_reference,
                'rows_removed', rows_removed,
                'rows_unknown', rows_unknown,
                'first_unknown_id', first_unknown_id
            )
            FROM row_matches'''


    def generate_changed_cells(self, column: str) -> int:
        """
        Creates the entire SQL query for how many of the rows both states hold changed their cell in one column, and
        executes it to the Postgres database. Two nulls are the same value, and two numbers are compared as numbers -
        within np.isclose's tolerances - so 3 on one side and 3.0 on the other is not a change. Anything else is
        compared as text.
        :arg: column: a column both tables hold.
        :return: the number of changed cells.
        """

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        changed_cell_steps = [self.count_changed_cells(column),
                              self.construct_changed_cells_count()]

        changed_cells_query = "".join(changed_cell_steps)
        return fetch_sql(changed_cells_query, True, self.engine)


    def count_changed_cells(self, column: str) -> str:
        """
        Pairs each row both states hold with itself, by "ID", and counts those whose cell changed.
        :arg: column: the column.
        :return: the query for the changed cells.
        """

        changed = self.cell_changed(column)
        value = quote_identifier(column)
        reference = quote_identifier(self.reference_table)
        node = quote_identifier(self.node_table)

        return f'''
            WITH changed_cells AS (
                SELECT COUNT(*) FILTER (WHERE {changed}) AS changed
                FROM (SELECT "ID", {value} FROM {reference}) r
                JOIN (SELECT "ID", {value} FROM {node}) n ON n."ID" = r."ID"
            )'''


    def construct_changed_cells_count(self) -> str:
        """
        Read the changed cells' count.
        :return: the final SELECT of the count.
        """

        return '''
            SELECT changed
            FROM changed_cells'''


    # -------------------------------------------------------------------------
    # One column's breakdown, for the drill-down views
    # -------------------------------------------------------------------------


    def generate_numeric_detail(self, column: str, grid: list) -> dict:
        """
        Creates the entire SQL query for a numeric column's breakdown and executes it to the Postgres database: each
        state's quantiles on the grid, how many values each holds, and its spread.
        :arg: column: a numeric column both tables hold.
        :arg: grid: the quantiles to read, as fractions.
        :return: {"reference": {...}, "node": {...}}, each {"n", "quantiles" (in grid order), "q1", "q3", "std"}. A side
                 holding no numbers is left out.
        """

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        numeric_detail_steps = [self.gather_column_numbers(column),
                                self.measure_column_numbers(grid),
                                self.construct_numeric_detail_json()]

        numeric_detail_query = "".join(numeric_detail_steps)
        return fetch_sql(numeric_detail_query, True, self.engine)


    def gather_column_numbers(self, column: str) -> str:
        """
        Gathers one column's numbers from both states, tagged with their side.
        :arg: column: the column.
        :return: the query for the numbers.
        """

        reference_numbers = self.side_numbers(self.reference_table, self.reference_types, column)
        node_numbers = self.side_numbers(self.node_table, self.node_types, column)

        return f'''
            WITH column_numbers AS (
                SELECT 'reference' AS side, number FROM {reference_numbers} AS reference_side
                WHERE number IS NOT NULL
                UNION ALL
                SELECT 'node', number FROM {node_numbers} AS node_side
                WHERE number IS NOT NULL
            )'''


    def measure_column_numbers(self, grid: list) -> str:
        """
        Measures each side's numbers: how many, their quantiles on the grid, their quartiles and their sample standard
        deviation.
        :arg: grid: the quantiles to read, as fractions.
        :return: the query for the measurements.
        """

        grid_values = []
        for quantile in grid:
            grid_values.append(repr(float(quantile)))
        grid_array = ", ".join(grid_values)

        return f''',
            column_measurements AS (
                SELECT
                    side,
                    COUNT(*) AS n,
                    percentile_cont(ARRAY[{grid_array}]::float8[]) WITHIN GROUP (ORDER BY number) AS quantiles,
                    percentile_cont(0.25) WITHIN GROUP (ORDER BY number) AS q1,
                    percentile_cont(0.75) WITHIN GROUP (ORDER BY number) AS q3,
                    STDDEV_SAMP(number) AS std
                FROM column_numbers
                GROUP BY side
            )'''


    def construct_numeric_detail_json(self) -> str:
        """
        Build the final JSON object for the numeric breakdown, keyed by side.
        :return: the query for the final JSON object.
        """

        return '''
            SELECT COALESCE(json_object_agg(
                side,
                json_build_object('n', n, 'quantiles', quantiles, 'q1', q1, 'q3', q3, 'std', std)
            ), '{}'::json)
            FROM column_measurements'''


    def generate_category_shares(self, column: str) -> list:
        """
        Creates the entire SQL query for a categorical column's category counts in both states, and executes it to the
        Postgres database. Missing cells are a category of their own.
        :arg: column: a categorical column both tables hold.
        :return: one object per category: {"label", "reference_count", "node_count"}.
        """

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        category_share_steps = [self.gather_column_categories(column),
                                self.count_column_categories(),
                                self.construct_category_shares_json()]

        category_shares_query = "".join(category_share_steps)
        return fetch_sql(category_shares_query, True, self.engine)


    def gather_column_categories(self, column: str) -> str:
        """
        Gathers one column's categories from both states, tagged with their side.
        :arg: column: the column.
        :return: the query for the categories.
        """

        reference_labels = self.side_categories(self.reference_table, column)
        node_labels = self.side_categories(self.node_table, column)

        return f'''
            WITH column_categories AS (
                SELECT 'reference' AS side, label FROM {reference_labels} AS reference_side
                UNION ALL
                SELECT 'node', label FROM {node_labels} AS node_side
            )'''


    def count_column_categories(self) -> str:
        """
        Counts each category in each state.
        :return: the query for the category counts.
        """

        return ''',
            column_category_counts AS (
                SELECT
                    label,
                    COUNT(*) FILTER (WHERE side = 'reference') AS reference_count,
                    COUNT(*) FILTER (WHERE side = 'node') AS node_count
                FROM column_categories
                GROUP BY label
            )'''


    def construct_category_shares_json(self) -> str:
        """
        Build the final JSON object for the category counts.
        :return: the query for the final JSON object.
        """

        return '''
            SELECT COALESCE(json_agg(
                json_build_object('label', label, 'reference_count', reference_count, 'node_count', node_count)
            ), '[]'::json)
            FROM column_category_counts'''


    def generate_category_flows(self, column: str) -> list:
        """
        Creates the entire SQL query for where each of the reference's rows sits in the node, for one categorical
        column, and executes it to the Postgres database: in a category, or in the removed sink when the node no longer
        holds the row. Rows are matched by "ID". Every category is listed as itself; the caller folds the long tail.
        :arg: column: a categorical column both tables hold.
        :return: one object per (source, target) pair: {"source", "target", "rows"}.
        """

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        category_flow_steps = [self.gather_matched_categories(column),
                               self.count_category_flows(),
                               self.construct_category_flows_json()]

        category_flows_query = "".join(category_flow_steps)
        return fetch_sql(category_flows_query, True, self.engine)


    def gather_matched_categories(self, column: str) -> str:
        """
        Pairs each of the reference's rows with its row in the node. A row's category is its value, or null when it has
        none - the label the compare plots give it.
        :arg: column: the column.
        :return: the query for the matched categories.
        """

        value = quote_identifier(column)
        null_label = quote_literal(NULL_LABEL)
        removed_label = quote_literal(REMOVED_LABEL)
        reference = quote_identifier(self.reference_table)
        node = quote_identifier(self.node_table)

        return f'''
            WITH matched_categories AS (
                SELECT
                    COALESCE(r.{value}::text, {null_label}) AS source,
                    CASE
                        WHEN n."ID" IS NULL THEN {removed_label}
                        ELSE COALESCE(n.{value}::text, {null_label})
                    END AS target
                FROM {reference} r
                LEFT JOIN {node} n ON n."ID" = r."ID"
            )'''


    def count_category_flows(self) -> str:
        """
        Counts the rows taking each path from a source category to a target.
        :return: the query for the flows.
        """

        return ''',
            category_flows AS (
                SELECT source, target, COUNT(*) AS rows
                FROM matched_categories
                GROUP BY source, target
            )'''


    def construct_category_flows_json(self) -> str:
        """
        Build the final JSON object for the flows.
        :return: the query for the final JSON object.
        """

        return '''
            SELECT COALESCE(json_agg(
                json_build_object('source', source, 'target', target, 'rows', rows)
            ), '[]'::json)
            FROM category_flows'''


    def generate_value_masses(self, side: str, column: str) -> dict:
        """
        Creates the entire SQL query for one state's distinct numbers in a column, each with how many rows hold it, and
        executes it to the Postgres database. A ridgeline is smoothed from these.
        :arg: side: "reference" or "node".
        :arg: column: the column.
        :return: {"numbers": [...], "occurrences": [...]}, in increasing order of number.
        """

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        value_mass_steps = [self.gather_side_value_masses(side, column),
                            self.construct_value_masses_json()]

        value_masses_query = "".join(value_mass_steps)
        return fetch_sql(value_masses_query, True, self.engine)


    def gather_side_value_masses(self, side: str, column: str) -> str:
        """
        Counts each distinct number in one state's column.
        :arg: side: "reference" or "node".
        :arg: column: the column.
        :return: the query for the value masses.
        """

        if side == "reference":
            numbers = self.side_numbers(self.reference_table, self.reference_types, column)
        else:
            numbers = self.side_numbers(self.node_table, self.node_types, column)

        return f'''
            WITH side_value_masses AS (
                SELECT number, COUNT(*) AS occurrences
                FROM {numbers} AS side_numbers
                WHERE number IS NOT NULL
                GROUP BY number
            )'''


    def construct_value_masses_json(self) -> str:
        """
        Build the final JSON object for the value masses: the numbers and their counts as two parallel arrays, in
        increasing order of number.
        :return: the query for the final JSON object.
        """

        return '''
            SELECT json_build_object(
                'numbers', COALESCE(json_agg(number ORDER BY number), '[]'::json),
                'occurrences', COALESCE(json_agg(occurrences ORDER BY number), '[]'::json)
            )
            FROM side_value_masses'''


    # -------------------------------------------------------------------------
    # Fragments the steps above share
    # -------------------------------------------------------------------------


    def side_numbers(self, table_name: str, col_types, column: str) -> str:
        """
        One table's values of a column as numbers, null where a value is not one.
        :arg: table_name: the table.
        :arg: col_types: the table's ColumnTypes.
        :arg: column: the column.
        :return: a subquery with one column, number.
        """

        value = quote_identifier(column)
        number = col_types.number_expression(value, column)
        table = quote_identifier(table_name)

        return f'''(
                    SELECT {number} AS number
                    FROM {table}
                )'''


    def side_categories(self, table_name: str, column: str) -> str:
        """
        One table's values of a column as categories: each value as text, and every missing cell - by the Missing
        detector's rule - as null.
        :arg: table_name: the table.
        :arg: column: the column.
        :return: a subquery with one column, label.
        """

        value = quote_identifier(column)
        is_missing = missing_cell_predicate(value)
        null_label = quote_literal(NULL_LABEL)
        table = quote_identifier(table_name)

        return f'''(
                    SELECT CASE WHEN {is_missing} THEN {null_label} ELSE {value}::text END AS label
                    FROM {table}
                )'''


    def cell_changed(self, column: str) -> str:
        """
        Whether one matched row's cell changed between the reference (r) and the node (n), as _differs decided it.
        :arg: column: the column.
        :return: a boolean SQL expression.
        """

        value = quote_identifier(column)
        reference_cell = "r." + value
        node_cell = "n." + value
        reference_number = self.reference_types.number_expression(reference_cell, column)
        node_number = self.node_types.number_expression(node_cell, column)

        return f'''CASE
                            WHEN {reference_cell} IS NULL AND {node_cell} IS NULL THEN false
                            WHEN {reference_cell} IS NULL OR {node_cell} IS NULL THEN true
                            WHEN ({reference_number}) IS NOT NULL AND ({node_number}) IS NOT NULL THEN
                                ABS(({reference_number}) - ({node_number}))
                                    > {ABSOLUTE_TOLERANCE} + {RELATIVE_TOLERANCE} * ABS({node_number})
                            ELSE {reference_cell}::text <> {node_cell}::text
                        END'''
