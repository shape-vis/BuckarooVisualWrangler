"""
Queries and visualizes data from a PostgreSQL database table, with error annotation overlays on all chart types.
Column types come from ColumnTypes (column_types.py).

--- DBOperations ---
Wraps all core DB operations for a single primary table. Builds and executes multi-step
CTE SQL queries that produce JSON payloads for 1D histograms, 2D histograms, and scatterplots,
each annotated with per-bin/per-point error breakdowns.

A value is read as a number by ColumnTypes.number_expression, the rule the compare plots and drift read values by.
A numeric column's numbers are binned linearly across their range, and anything else in it - a null, a NaN - becomes
a categorical label beside the bins. A text column is binned by label, the numbers a mixed column holds included.
"""

from collections import defaultdict

import pandas as pd

from app.db_utils.execute_sql import (errors_table_name, execute_sql, fetch_sql, node_table_names, profile_table_name,
                                      quote_identifier, quote_literal)
from app.db_utils.column_types import ColumnTypes

# A histogram bin's label that is a numeric bin's index, rather than a category
BIN_INDEX_REGEX = r"'^\d+$'"


# Wraps up all Core DBOperations into one class using a primary main_table.
class DBOperations:
    def __init__(self, engine):
        """
        This inits the DBOperations class right after the engine is created so that it can be reloaded
        later on with a different CSV, also so that other classes can access the engine w/out this class
        being fully initialized like in the plot routes upload endpoint
        :param engine: SQLAlchemy engine
        """
        self.engine = engine
        self.main_table_name = None
        self.error_table_name = None
        self.dp_table_name = None
        self.col_types = None
        self.active_hists = {}

    def reset(self):
        """
        Resets the DBOperations state, clearing all loaded table references.
        Called when the user navigates back to the home page.
        """
        self.main_table_name = None
        self.error_table_name = None
        self.dp_table_name = None
        self.col_types = None
        self.active_hists = {}

    def load_table(self, main_table_name: str, error_table_name: str = None, dp_table_name: str = None):
        """
        Loads in the main and error tables, and inits the ColumnTypes object with the new table
        :param main_table_name: the name of the table in the database without errors detected (raw data)
        :param error_table_name: explicit errors table name; defaults to the table's own, errors_table_name
        :param dp_table_name: explicit data profile table name; defaults to the table's own, profile_table_name
        """
        self.main_table_name = main_table_name
        self.error_table_name = error_table_name if error_table_name is not None else errors_table_name(main_table_name)
        self.dp_table_name = dp_table_name if dp_table_name is not None else profile_table_name(main_table_name)
        self.col_types = ColumnTypes.for_table(main_table_name, self.engine)
        self.active_hists = {}

    def get_row_count(self, table_name: str) -> int:
        """
        Returns the actual row count of a table directly from the database.
        :arg: table_name: name of the table to count rows from.
        :return: the number of rows in the table.
        """

        table = quote_identifier(table_name)
        return fetch_sql(f'SELECT COUNT(*) FROM {table}', True, self.engine)

    def generate_top_error_rows(self, row_count=10):
        """
        Creates the SQL queries for the rows of the current table carrying the most error flags, and executes them:
        once for the rows' data and once for their flags, for the table view.
        :arg: row_count: how many rows to return.
        :return: (the rows' data, their error flags), each a DataFrame.
        """

        top_data_steps = [self.gather_top_error_row_ids(row_count),
                          self.select_top_error_data()]
        top_errors_steps = [self.gather_top_error_row_ids(row_count),
                            self.select_top_error_flags()]

        data_rows = pd.read_sql_query("".join(top_data_steps), self.engine)
        error_rows = pd.read_sql_query("".join(top_errors_steps), self.engine)
        return data_rows, error_rows

    def gather_top_error_row_ids(self, row_count: int) -> str:
        """
        Gather the IDs of the rows carrying the most error flags.
        :arg: row_count: how many rows to gather.
        :return: the query for the top row IDs.
        """

        errors_table = quote_identifier(self.error_table_name)

        return f'''WITH
            top_row_ids AS (
                SELECT row_id
                FROM {errors_table}
                GROUP BY row_id
                ORDER BY COUNT(*) DESC     -- most flagged rows first
                LIMIT {int(row_count)}
            )'''

    def select_top_error_data(self) -> str:
        """
        Select the top rows' data from the current table.
        :return: the query for the rows' data.
        """

        main_table = quote_identifier(self.main_table_name)

        return f'''
            SELECT d.*
            FROM {main_table} d
            JOIN top_row_ids t ON d."ID" = t.row_id;'''

    def select_top_error_flags(self) -> str:
        """
        Select every error flag the top rows carry.
        :return: the query for the rows' flags.
        """

        errors_table = quote_identifier(self.error_table_name)

        return f'''
            SELECT *
            FROM {errors_table}
            WHERE row_id IN (SELECT row_id FROM top_row_ids)
            ORDER BY row_id;'''

    def clone_table(self, source_table: str, dest_table: str):
        """
        Copies a table, replacing any table already under the copy's name. A candidate starts as a copy of its
        parent's table, which its wrangle then changes.
        :arg: source_table: the table to copy.
        :arg: dest_table: the copy's name.
        """

        source = quote_identifier(source_table)
        dest = quote_identifier(dest_table)

        clone_query = f'''
            DROP TABLE IF EXISTS {dest};
            CREATE TABLE {dest} AS SELECT * FROM {source};
        '''
        execute_sql(clone_query, self.engine)
        ColumnTypes.forget(dest_table)

    def drop_node_tables(self, table_name: str):
        """
        Drops a node's table and every companion table named from it - see node_table_names.
        :arg: table_name: the node's table.
        """

        drop_statements = []
        for name in node_table_names(table_name):
            quoted_name = quote_identifier(name)
            drop_statements.append(f"DROP TABLE IF EXISTS {quoted_name};")
            ColumnTypes.forget(name)

        execute_sql("\n".join(drop_statements), self.engine)

    def check_columns(self, columns: list):
        """
        Refuses a column the current table lacks, before any name is put into a query. The plot routes pass column
        names straight from the request.
        :arg: columns: the plotted columns.
        """

        known_columns = self.col_types.column_names
        for column in columns:
            if column not in known_columns:
                raise ValueError(f"{self.main_table_name} has no column {column!r}")


    def generate_one_d_histogram_with_errors(self, axis_column: str, bin_count=10):
        """
        Creates the entire SQL query for generating a 1D histogram with errors and executes it to the Postgres database.
        :arg: axis_column: name of the axis column.
        :arg: bin_count: number of bins (used for numeric data). If categorical then bins are individual labels.
        :return: the JSON object containing histogram data.
        """

        self.check_columns([axis_column])
        axes = [("x", axis_column)]

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        hist_1d_steps = [self.gather_data_rows(axes),
                         self.gather_axis_range("x", bin_count),
                         self.gather_bins(axes),
                         self.errors_per_bin(axes),
                         self.form_final_hist_bins(axes),
                         self.build_numeric_scale_data("x"),
                         self.construct_1d_hist_json(axis_column)]

        hist_1d_final_query = "".join(hist_1d_steps)
        binned_data, hist = fetch_sql(hist_1d_final_query, False, self.engine)[0]
        self.update_active_hists(binned_data, True, axis_column)
        return hist


    def update_active_hists(self, binned_data: list, one_dim: bool, col_key):
        """
        Caches viewport data in the backend for future reference.
        :arg: binned_data: A list of string tuples containing (ID, bin).
        :arg: one_dim: whether the viewport only has one dimension (column) or not.
        :arg: col_key: the column(s) name tuple or string if singular.
        """

        rows_to_bins = {}
        bins_to_rows = defaultdict(list)

        if one_dim:
            for row_id, row_bin in binned_data:
                rows_to_bins[row_id] = row_bin
                bins_to_rows[row_bin].append(row_id)
        else:
            for row_id, x_bin, y_bin in binned_data:
                joint_bin = (x_bin, y_bin)
                rows_to_bins[row_id] = joint_bin
                bins_to_rows[joint_bin].append(row_id)

        self.active_hists[col_key] = (rows_to_bins, bins_to_rows)


    def gather_data_rows(self, axes: list) -> str:
        """
        Gets each row's value on every axis, and the value as a number when the axis is a numeric column.
        :arg: axes: (axis name, column) pairs, e.g. [("x", "age")].
        :return: the query for the data rows.
        """

        main_table = quote_identifier(self.main_table_name)

        selected = ['d."ID"']
        for axis, column in axes:
            value = "d." + quote_identifier(column)
            number = self.binned_number(value, column)
            selected.append(f"{value} AS {axis}_value")
            selected.append(f"{number} AS {axis}_number")
        selected_list = ",\n                    ".join(selected)

        return f'''
            WITH data_rows AS (
                SELECT
                    {selected_list}
                FROM {main_table} d
            )'''


    def gather_axis_range(self, axis: str, bin_count: int) -> str:
        """
        Splits an axis' numbers into bins across their range. A column that holds one number throughout still needs
        a bin with some width to draw, so it gets one bin a unit wide, as CompareSQL's shared axes do; an axis with no
        numbers at all gets an empty range from 0 to 1.
        :arg: axis: the axis name, "x" or "y".
        :arg: bin_count: number of bins (used for numeric data).
        :return: the query for the axis range.
        """

        return f''',
            {axis}_axis AS (
                SELECT
                    lo,
                    bins,
                    (hi - lo) / bins AS bin_width
                FROM (
                    SELECT
                        CASE WHEN low IS NULL THEN 0 WHEN low = high THEN low - 0.5 ELSE low END AS lo,
                        CASE WHEN low IS NULL THEN 1 WHEN low = high THEN high + 0.5 ELSE high END AS hi,
                        CASE WHEN low = high THEN 1 ELSE {int(bin_count)} END AS bins
                    FROM (
                        SELECT MIN({axis}_number) AS low, MAX({axis}_number) AS high
                        FROM data_rows
                    ) AS extent
                ) AS decided
            )'''


    def gather_bins(self, axes: list) -> str:
        """
        Binning logic for the histograms, done for every axis. A numeric column's numbers go in bins split linearly
        across their range, clamped so the maximum lands in the last bin rather than one past it; a null is the null
        label, and anything else in it - a NaN - its own label. A text column's every value is its own label.
        The bin is floor((number - lo) / width), the arithmetic the scale's edges are built with, so a number sitting
        on an edge lands in the bin those edges say it belongs to.
        :arg: axes: (axis name, column) pairs.
        :return: the query for the binning.
        """

        selected = ['d."ID"']
        joins = []

        for axis, column in axes:
            if self.col_types.is_numeric_col(column):
                # Clamp bin number to 0..(bins-1) range
                bin_index = f'''LEAST(
                                GREATEST(
                                    FLOOR((d.{axis}_number - {axis}_axis.lo) / {axis}_axis.bin_width),
                                    0
                                ),
                                {axis}_axis.bins - 1
                            )::int'''
                bin_logic = f'''CASE
                            WHEN d.{axis}_value IS NULL THEN 'null'
                            WHEN d.{axis}_number IS NOT NULL THEN ({bin_index})::text
                            ELSE d.{axis}_value::text  -- A value of a numeric column that is not a number
                        END'''
            else:
                bin_logic = f"COALESCE(d.{axis}_value::text, 'null')"

            selected.append(f"{bin_logic} AS {axis}_bin")
            joins.append(f"CROSS JOIN {axis}_axis")

        selected_list = ",\n                    ".join(selected)
        join_list = "\n                ".join(joins)

        return f''',
            binned_data AS (
                SELECT
                    {selected_list}
                FROM data_rows d
                {join_list}
            )'''


    def errors_per_bin(self, axes: list) -> str:
        """
        Gathers how many of each bin's rows each error type flags, on the plotted columns. A row is counted once per
        error type, however many of the columns carry it: a row flagged the same way on both of a heatmap's columns is
        one flagged row in its tile.
        :arg: axes: (axis name, column) pairs.
        :return: the query for the error grouping.
        """

        errors_table = quote_identifier(self.error_table_name)

        bin_columns = []
        column_names = []
        for axis, column in axes:
            bin_columns.append(f"b.{axis}_bin")
            column_names.append(quote_literal(column))
        bin_list = ", ".join(bin_columns)
        column_list = ", ".join(column_names)

        return f''',
            errors_per_bin AS (
                SELECT
                    {bin_list},
                    e.error_type,
                    COUNT(DISTINCT b."ID") AS error_count
                FROM binned_data b
                JOIN {errors_table} e ON b."ID" = e.row_id
                WHERE e.column_id IN ({column_list})
                GROUP BY {bin_list}, e.error_type
            )'''


    def form_final_hist_bins(self, axes: list) -> str:
        """
        Formulates the final histogram bins by collecting each bin, total counts, and condensing error
        types for each bin into a JSON object. This also formulates final bins for bins with no errors. The rows are
        counted apart from the flags, so a bin holding several error types is not counted once per type.
        :arg: axes: (axis name, column) pairs.
        :return: the query for the final hist bins.
        """

        bin_columns = []
        for axis, _ in axes:
            bin_columns.append(f"{axis}_bin")
        bin_list = ", ".join(bin_columns)

        return f''',
            histogram_bins AS (
                SELECT
                    {bin_list},
                    bin_items.total_items,
                    bin_errors.errors
                FROM (
                    SELECT {bin_list}, COUNT(*) AS total_items
                    FROM binned_data
                    GROUP BY {bin_list}
                ) AS bin_items
                LEFT JOIN (
                    SELECT {bin_list}, jsonb_object_agg(error_type, error_count) AS errors
                    FROM errors_per_bin
                    GROUP BY {bin_list}
                ) AS bin_errors USING ({bin_list})
            )'''


    def build_numeric_scale_data(self, axis: str) -> str:
        """
        Build linear scaling data for each of the numeric bins on an axis: each bin's edges.
        :arg: axis: the axis name, "x" or "y".
        :return: the query for the numeric scaling data.
        """

        return f''',
            {axis}_numeric_scale_data AS (
                SELECT
                    n AS bin_num,
                    a.lo + n * a.bin_width AS x0,
                    a.lo + (n + 1) * a.bin_width AS x1
                FROM {axis}_axis a
                CROSS JOIN generate_series(0, a.bins - 1) AS n
            )'''


    def construct_1d_hist_json(self, axis_column: str) -> str:
        """
        Build the final JSON object: every row's bin, for selections, and the histogram.
        :arg: axis_column: name of the column to build the final JSON object for.
        :return: the query for the final JSON object
        """

        empty_errors = "'{}'::jsonb"
        x_type = self.bin_type_json("x", axis_column)
        x_order = self.bin_order("x", axis_column)
        x_scale = self.axis_scale_json("x", axis_column)

        return f'''
            SELECT
                (SELECT COALESCE(json_agg(json_build_array("ID", x_bin)), '[]'::json) FROM binned_data),
                json_build_object(
                    'histograms', (
                        SELECT COALESCE(json_agg(
                            json_build_object(
                                'xBin', x_bin,
                                'xType', {x_type},
                                'count', COALESCE(errors, {empty_errors}) || jsonb_build_object('items', total_items)
                            ) ORDER BY {x_order}
                        ), '[]'::json)
                        FROM histogram_bins
                    ),
                    'scaleX', {x_scale}
                )'''


    def generate_two_d_histogram_with_errors(self, x_axis_column: str, y_axis_column: str, x_bin_count=10, y_bin_count=10) -> str:
        """
        Creates the entire SQL query for generating a 2D histogram with errors and executes it to the Postgres database.
        :arg: x_axis_column: the column to create the x-axis for the 2D histogram.
        :arg: y_axis_column: the column to create the y-axis for the 2D histogram.
        :arg: x_bin_count: number of bins (used for numeric data) for the x-axis. If categorical then bins are individual labels.
        :arg: y_bin_count: number of bins (used for numeric data) for the y-axis. If categorical then bins are individual labels.
        :return: the JSON object containing histogram data.
        """

        self.check_columns([x_axis_column, y_axis_column])
        axes = [("x", x_axis_column), ("y", y_axis_column)]

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        hist_2d_steps = [self.gather_data_rows(axes),
                         self.gather_axis_range("x", x_bin_count),
                         self.gather_axis_range("y", y_bin_count),
                         self.gather_bins(axes),
                         self.errors_per_bin(axes),
                         self.form_final_hist_bins(axes),
                         self.build_numeric_scale_data("x"),
                         self.build_numeric_scale_data("y"),
                         self.construct_2d_hist_json(x_axis_column, y_axis_column)]

        hist_2d_final_query = "".join(hist_2d_steps)
        binned_data, hist = fetch_sql(hist_2d_final_query, False, self.engine)[0]
        self.update_active_hists(binned_data, False, (x_axis_column, y_axis_column))
        return hist


    def construct_2d_hist_json(self, x_axis_column: str, y_axis_column: str) -> str:
        """
        Build the final JSON object for the 2D histogram: every row's tile, for selections, and the histogram.
        :arg: x_axis_column: name of the x-axis column to build the final JSON object for.
        :arg: y_axis_column: name of the y-axis column to build the final JSON object for.
        :return: the query for the final JSON object
        """

        empty_errors = "'{}'::jsonb"
        x_type = self.bin_type_json("x", x_axis_column)
        y_type = self.bin_type_json("y", y_axis_column)
        x_order = self.bin_order("x", x_axis_column)
        y_order = self.bin_order("y", y_axis_column)
        x_scale = self.axis_scale_json("x", x_axis_column)
        y_scale = self.axis_scale_json("y", y_axis_column)

        return f'''
            SELECT
                (SELECT COALESCE(json_agg(json_build_array("ID", x_bin, y_bin)), '[]'::json) FROM binned_data),
                json_build_object(
                    'histograms', (
                        SELECT COALESCE(json_agg(
                            json_build_object(
                                'xBin', x_bin,
                                'yBin', y_bin,
                                'xType', {x_type},
                                'yType', {y_type},
                                'count', COALESCE(errors, {empty_errors}) || jsonb_build_object('items', total_items)
                            ) ORDER BY {x_order}, {y_order}
                        ), '[]'::json)
                        FROM histogram_bins
                    ),
                    'scaleX', {x_scale},
                    'scaleY', {y_scale}
                )'''


    def generate_scatterplot_with_errors(self, x_axis_column: str, y_axis_column: str, error_sample_size=30, total_sample_size=100):
        """
        Creates the entire SQL query for generating a scatterplot with errors and executes it to the Postgres database.
        :arg: x_axis_column: the column to create the x-axis for the 2D histogram.
        :arg: y_axis_column: the column to create the y-axis for the 2D histogram.
        :arg: error_sample_size: how many error data points to sample.
        :arg: total_sample_size: how many data points to sample total for the displayed scatter plot.
        :return: the JSON object containing scatterplot data.
        """

        self.check_columns([x_axis_column, y_axis_column])

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        scatter_steps = [self.sample_rows_scatter(x_axis_column, y_axis_column, error_sample_size, total_sample_size),
                         self.scatter_aggregate_errors(x_axis_column, y_axis_column),
                         self.collect_scatter_axis_bounds("x"),
                         self.collect_scatter_axis_bounds("y"),
                         self.construct_scatter_json(x_axis_column, y_axis_column)]

        scatter_final_query = "".join(scatter_steps)
        return fetch_sql(scatter_final_query, True, self.engine)


    def sample_rows_scatter(self, x_axis_column: str, y_axis_column: str, error_sample_size: int, total_sample_size: int) -> str:
        """
        Gathers a sample of rows: up to error_sample_size of the rows flagged on the x-axis or y-axis column, each once
        however many flags it carries, then rows with no flags there to make up total_sample_size.
        :arg: x_axis_column: the x-axis column.
        :arg: y_axis_column: the y-axis column.
        :arg: error_sample_size: how many error data points to sample.
        :arg: total_sample_size: how many data points to sample total for the displayed scatter plot.
        :return: the query for sampling the rows.
        """

        main_table = quote_identifier(self.main_table_name)
        errors_table = quote_identifier(self.error_table_name)
        column_list = quote_literal(x_axis_column) + ", " + quote_literal(y_axis_column)
        clean_sample_size = int(total_sample_size) - int(error_sample_size)

        return f'''WITH
            -- Step 1: Sample IDs (prioritize errors, then clean rows)
            all_sampled_ids AS (
                (
                    -- Sample error rows
                    SELECT row_id
                    FROM (
                        SELECT DISTINCT row_id
                        FROM {errors_table}
                        WHERE column_id IN ({column_list})
                    ) AS flagged_rows
                    ORDER BY RANDOM()
                    LIMIT {int(error_sample_size)}
                )
                UNION ALL
                (
                    -- Sample clean rows to fill quota
                    SELECT "ID" AS row_id
                    FROM {main_table}
                    WHERE "ID" NOT IN (
                          SELECT row_id
                          FROM {errors_table}
                          WHERE column_id IN ({column_list})
                    )
                    ORDER BY RANDOM()
                    LIMIT GREATEST({clean_sample_size}, 0)
                )
            )'''


    def scatter_aggregate_errors(self, x_axis_column: str, y_axis_column: str) -> str:
        """
        Gathers the sampled rows' values, as numbers where they are numbers, and the error types flagged on the
        plotted columns.
        :arg: x_axis_column: the x-axis column.
        :arg: y_axis_column: the y-axis column.
        :return: the query for aggregating scatterplot error data w/ sampled points.
        """

        main_table = quote_identifier(self.main_table_name)
        errors_table = quote_identifier(self.error_table_name)
        x_value = "m." + quote_identifier(x_axis_column)
        y_value = "m." + quote_identifier(y_axis_column)
        x_number = self.col_types.number_expression(x_value, x_axis_column)
        y_number = self.col_types.number_expression(y_value, y_axis_column)
        column_list = quote_literal(x_axis_column) + ", " + quote_literal(y_axis_column)

        return f''',
            -- Step 2: Get data for sampled IDs with error aggregation
            sampled_data AS (
                SELECT
                    m."ID",
                    {x_value} AS x_value,
                    {x_number} AS x_number,
                    {y_value} AS y_value,
                    {y_number} AS y_number,
                    COALESCE(
                        json_agg(e.error_type) FILTER (WHERE e.error_type IS NOT NULL),
                        '[]'::json
                    ) AS error_list
                FROM all_sampled_ids s
                JOIN {main_table} m ON s.row_id = m."ID"
                LEFT JOIN {errors_table} e ON s.row_id = e.row_id AND e.column_id IN ({column_list})
                GROUP BY m."ID", {x_value}, {y_value}
            )'''


    def collect_scatter_axis_bounds(self, axis: str) -> str:
        """
        Gets the numeric bounds of a scatterplot axis' sampled numbers.
        :arg: axis: the axis name, "x" or "y".
        :return: the query for the axis bounds.
        """

        return f''',
            {axis}_bounds AS (
                SELECT
                    MIN({axis}_number) AS min_val,
                    MAX({axis}_number) AS max_val
                FROM sampled_data
            )'''


    def construct_scatter_json(self, x_axis_column: str, y_axis_column: str) -> str:
        """
        Constructs the final JSON object for the scatterplot: each point is numeric where its value is a number, and
        categorical otherwise - a null, or text.
        :arg: x_axis_column: the x-axis column.
        :arg: y_axis_column: the y-axis column.
        :return: returns the final JSON query for the scatterplot.
        """

        x_scale = self.scatter_scale_json("x", x_axis_column)
        y_scale = self.scatter_scale_json("y", y_axis_column)

        return f'''
            SELECT json_build_object(
                'data', (
                    SELECT COALESCE(json_agg(
                        json_build_object(
                            'ID', "ID",
                            'xType', CASE
                                WHEN x_value IS NULL THEN 'categorical'
                                WHEN x_number IS NOT NULL THEN 'numeric'
                                ELSE 'categorical'
                            END,
                            'yType', CASE
                                WHEN y_value IS NULL THEN 'categorical'
                                WHEN y_number IS NOT NULL THEN 'numeric'
                                ELSE 'categorical'
                            END,
                            'x', CASE
                                WHEN x_value IS NULL THEN to_json('null'::text)
                                WHEN x_number IS NOT NULL THEN to_json(x_number)
                                ELSE to_json(x_value::text)
                            END,
                            'y', CASE
                                WHEN y_value IS NULL THEN to_json('null'::text)
                                WHEN y_number IS NOT NULL THEN to_json(y_number)
                                ELSE to_json(y_value::text)
                            END,
                            'errors', error_list
                        )
                    ), '[]'::json)
                    FROM sampled_data
                ),
                'scaleX', {x_scale},
                'scaleY', {y_scale}
            )'''


    # -------------------------------------------------------------------------
    # Fragments the steps above share
    # -------------------------------------------------------------------------


    def binned_number(self, column_sql: str, column: str) -> str:
        """
        A histogram axis' value as a number: a numeric column's finite values, by ColumnTypes.number_expression. A text
        column is binned by label, so it has no number.
        :arg: column_sql: the column as the query references it, already quoted, e.g. d."Age".
        :arg: column: the column.
        :return: a float8 SQL expression.
        """

        if self.col_types.is_numeric_col(column):
            return self.col_types.number_expression(column_sql, column)
        return "NULL::float8"


    def bin_type_json(self, axis: str, column: str) -> str:
        """
        A bin's type as the payload gives it: numeric for a numeric column's bin index, categorical for a label.
        :arg: axis: the axis name, "x" or "y".
        :arg: column: the axis' column.
        :return: a text SQL expression.
        """

        if self.col_types.is_numeric_col(column):
            return f"CASE WHEN {axis}_bin ~ {BIN_INDEX_REGEX} THEN 'numeric' ELSE 'categorical' END"
        return "'categorical'"


    def bin_order(self, axis: str, column: str) -> str:
        """
        The order an axis' bins are listed in: a numeric column's bins by index, then its labels by name; a text
        column's labels by name.
        :arg: axis: the axis name, "x" or "y".
        :arg: column: the axis' column.
        :return: a text SQL expression to order by.
        """

        if self.col_types.is_numeric_col(column):
            return f"CASE WHEN {axis}_bin ~ {BIN_INDEX_REGEX} THEN lpad({axis}_bin, 10, '0') ELSE {axis}_bin END"
        return f"{axis}_bin"


    def axis_scale_json(self, axis: str, column: str) -> str:
        """
        A histogram axis as the front end's hybrid scales take it: a numeric column's bin edges, and the labels. Every
        bin of a text column is a label, a number-shaped one included.
        :arg: axis: the axis name, "x" or "y".
        :arg: column: the axis' column.
        :return: a JSON SQL expression.
        """

        if self.col_types.is_numeric_col(column):
            numeric_edges = f'''(
                        SELECT COALESCE(json_agg(json_build_object('x0', x0, 'x1', x1) ORDER BY bin_num), '[]'::json)
                        FROM {axis}_numeric_scale_data
                    )'''
            # Only the labels: null, and anything else that is not a bin index
            label_filter = f"WHERE NOT ({axis}_bin ~ {BIN_INDEX_REGEX})"
        else:
            numeric_edges = "'[]'::json"
            label_filter = ""

        return f'''json_build_object(
                    'numeric', {numeric_edges},
                    'categorical', (
                        SELECT COALESCE(json_agg(DISTINCT {axis}_bin ORDER BY {axis}_bin), '[]'::json)
                        FROM histogram_bins
                        {label_filter}
                    )
                )'''


    def scatter_scale_json(self, axis: str, column: str) -> str:
        """
        A scatterplot axis' scale: the sampled numbers' range, one past the largest, for a column that can hold
        numbers, and the sampled values that are not numbers - null among them - as labels.
        :arg: axis: the axis name, "x" or "y".
        :arg: column: the axis' column.
        :return: a JSON SQL expression.
        """

        if self.col_types.is_numeric_col(column) or self.col_types.is_mixed_col(column):
            numeric_range = f'''json_build_array(
                        (SELECT COALESCE(min_val, 0) FROM {axis}_bounds),
                        (SELECT COALESCE(max_val, 1) + 1 FROM {axis}_bounds)
                    )'''
        else:
            numeric_range = "'[]'::json"

        label = f"COALESCE({axis}_value::text, 'null')"

        return f'''json_build_object(
                    'numeric', {numeric_range},
                    'categorical', (
                        SELECT COALESCE(json_agg(DISTINCT {label} ORDER BY {label}), '["null"]'::json)
                        FROM sampled_data
                        WHERE {axis}_number IS NULL
                    )
                )'''


    # -------------------------------------------------------------------------
    # Cross-chart highlighting helpers
    # -------------------------------------------------------------------------


    def del_nonactive_hists(self, nonactive_hists: list):
        """
        Given a list of now non-active attributes, remove their storage bins from the backend.

        :arg: nonative_hists: the nonactive attributes to remove from storage.
        """

        # Get rid of nonactive views that are stored, ignore ones that aren't being stored.
        for nonactive_attribute in nonactive_hists:
            self.active_hists.pop(nonactive_attribute, None)


    def get_row_ids_in_bin(self, column, bin_value: str) -> list:
        """
        Return the row IDs that fall inside the given 1-D histogram bin.

        For numeric columns bin_value is the integer bin index (0-based).
        For categorical columns bin_value is the category label (string).
        """

        bins_to_rows = self.active_hists[column][1]
        if bin_value in bins_to_rows:
            return bins_to_rows[bin_value]
        else:
            return []


    def get_1d_bins_containing_rows(self, column: str, row_ids: list) -> list:
        """
        Given a list of row IDs, return which 1-D bin indices/labels those
        rows fall into.  Returns a list of bin identifier strings.
        """
        if not row_ids:
            return []

        affected_bins = set()
        rows_to_bins = self.active_hists[column][0]
        for row_id in row_ids:
            if row_id in rows_to_bins:
                affected_bins.add(rows_to_bins[row_id])

        return list(affected_bins)


    def get_2d_bins_containing_rows(self, joint_col: str, row_ids: list) -> list:
        """
        Given a list of row IDs, return which 2-D bin coordinates (xBin, yBin)
        those rows fall into.  Returns a list of {xBin, yBin} dicts.
        """
        if not row_ids:
            return []

        affected_bins = set()
        rows_to_bins = self.active_hists[joint_col][0]
        for row_id in row_ids:
            if row_id in rows_to_bins:
                affected_bins.add(rows_to_bins[row_id])

        # Now to satisfy the front-end formatting
        affected_bins_list = []
        for x_bin, y_bin in affected_bins:
            affected_bins_list.append({"xBin": x_bin, "yBin": y_bin})

        return affected_bins_list

    def table_exists(self, name):
        """Check if a table exists in the database."""
        query = "SELECT 1 FROM information_schema.tables WHERE table_name = :name"
        result = fetch_sql(query=query, scalar=True, engine=self.engine, params={"name": name})
        return result is not None
