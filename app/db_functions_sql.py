from collections import defaultdict

from .filtering_sql import FilteringSQL
from .execute_sql import fetch_sql
import uuid
from sqlalchemy import text as sa_text
"""
Provides two classes for querying and visualizing data from a PostgreSQL database table,
with support for data filtering and error annotation overlays on all chart types.

--- ColumnTypes ---
Inspects a table's schema to classify each column as numeric, categorical, or mixed-type.

--- DBOperations ---
Wraps all core DB operations for a single primary table. Builds and executes multi-step
CTE SQL queries that produce JSON payloads for 1D histograms, 2D histograms, and scatterplots,
each annotated with per-bin/per-point error breakdowns. Also manages row-level data filters.
"""

class ColumnTypes:
    def __init__(self, main_table_name: str, engine):
        self.numeric_cols = set()
        self.categorical_mixed = set()
        self.pure_categorical = set()
        self.engine = engine
        self.gather_numeric_cols(main_table_name)
        self.gather_mixed_cols(main_table_name)


    def gather_numeric_cols(self, main_table_name: str):
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
                    self.categorical_mixed.add(col_name)
        else:
            raise Exception(f"No rows fetched from table: {main_table_name}")


    def gather_mixed_cols(self, main_table_name: str):
        """
        Gather the columns that are labeled as categorical but contain numeric data as well.
        :arg: main_table_name: name of the main table.
        """

        # There are no categorical columns in the dataset.
        if len(self.categorical_mixed) == 0:
            return

        numeric_regex = r"'^\s*-?\d+(\.\d+)?\s*$'"

        # Initialized in the other constructor func gather_numeric_cols. This starts as all categorical columns.
        # Stop early if a mixed type is found, since that makes the entire column of mixed type.
        queries = [
            f"""(
                SELECT '{col}' AS column_name
                FROM "{main_table_name}"
                WHERE "{col}"::text ~ {numeric_regex}
                LIMIT 1
            )"""
            for col in self.categorical_mixed
        ]

        fetch_mixed_types = "\nUNION ALL\n".join(queries)
        mixed_cols = fetch_sql(fetch_mixed_types, False, self.engine)

        mixed_col_names = set(row[0] for row in mixed_cols) if mixed_cols else set()
        self.pure_categorical = self.categorical_mixed - mixed_col_names
        self.categorical_mixed = mixed_col_names

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
        return col_name in self.categorical_mixed


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
        self.col_types = None
        self.filtering_table = None
        self.active_hists = {}
        self._cached_filtered_error_key = None
        self._cached_filtered_error_table = None

    def _clear_cached_filtered_error_table(self):
        """
        Drop any cached temporary filtered error table owned by this DBOperations instance.
        """
        if not self._cached_filtered_error_table:
            self._cached_filtered_error_key = None
            return

        with self.engine.begin() as conn:
            conn.execute(sa_text(f'DROP TABLE IF EXISTS "{self._cached_filtered_error_table}"'))

        self._cached_filtered_error_key = None
        self._cached_filtered_error_table = None

    def reset(self):
        """
        Resets the DBOperations state, clearing all loaded table references.
        Called when the user navigates back to the home page.
        """
        self._clear_cached_filtered_error_table()
        self.main_table_name = None
        self.error_table_name = None
        self.col_types = None
        self.filtering_table = None
        self.active_hists = {}

    def _ensure_table_metadata_loaded(self):
        """
        Lazily initialize metadata tied to the active main table.
        """
        if not self.main_table_name:
            raise ValueError("Cannot load table metadata before a main table is set.")

        if self.col_types is None:
            self.col_types = ColumnTypes(self.main_table_name, self.engine)

        if self.filtering_table is None or self.filtering_table.main_table_name != self.main_table_name:
            self.filtering_table = FilteringSQL(self.main_table_name, self.engine)

    def prewarm_table_metadata(self, table_name: str, error_table_name: str | None = None):
        """
        Best-effort metadata warmup for the current active table.
        Used after upload so the first plot request doesn't pay the full metadata cost.
        """
        if self.main_table_name != table_name:
            return

        if error_table_name is not None:
            self.error_table_name = error_table_name

        self._ensure_table_metadata_loaded()

    def load_table(self, main_table_name: str, error_table_name: str = None, initialize_col_types: bool = True):
        """
        Loads in the main and error tables and initializes backend helpers for the new table.
        :param main_table_name: the name of the table in the database without errors detected (raw data)
        :param error_table_name: explicit errors table name; defaults to "errors_" + main_table_name
        :param initialize_col_types: whether to eagerly build ColumnTypes now or lazily on first plot request
        """
        if self.main_table_name != main_table_name:
            self._clear_cached_filtered_error_table()

        self.main_table_name = main_table_name
        self.error_table_name = error_table_name if error_table_name is not None else "errors_" + main_table_name
        self.filtering_table = FilteringSQL(main_table_name, self.engine)
        self.col_types = None
        if initialize_col_types:
            self.col_types = ColumnTypes(main_table_name, self.engine)
        self.active_hists = {}

    def _clone_loaded_state(self, error_table_name: str):
        """
        Create a lightweight DBOperations view over the currently loaded main table
        while reusing already-computed metadata such as ColumnTypes and FilteringSQL.
        This avoids rebuilding table metadata when only the active error table changes.
        """
        if not self.main_table_name or self.col_types is None or self.filtering_table is None:
            raise ValueError("Cannot clone DBOperations state before a table is loaded.")

        request_ops = self.__class__(self.engine)
        request_ops.main_table_name = self.main_table_name
        request_ops.error_table_name = error_table_name
        request_ops.col_types = self.col_types
        request_ops.filtering_table = self.filtering_table
        request_ops.active_hists = {}
        return request_ops

    def create_filtered_error_table(self, selected_anomaly_methods=None, rarity_threshold: float = 0.05):
        """
        Resolve the effective error table for the currently loaded main table.
        Reuses the persisted default error table when possible and caches one
        non-default filtered error table for repeated plot requests.
        """
        if not self.main_table_name:
            raise ValueError("No main table is loaded in DBOperations.")

        from app import service_helpers

        normalized_methods = set(
            service_helpers._normalize_anomaly_methods(
                anomaly_methods=selected_anomaly_methods,
                allow_empty=False,
            )
        )
        normalized_rarity = service_helpers._normalize_rarity_threshold(rarity_threshold, default=0.05)

        cache_key = (tuple(sorted(normalized_methods)), normalized_rarity)

        # The persisted runtime detector state is already built for zscore + 0.05.
        # Reuse it directly instead of creating a temporary filtered table.
        if cache_key == (("zscore",), 0.05):
            if self._cached_filtered_error_table:
                self._clear_cached_filtered_error_table()
            return f"errors_{self.main_table_name}", False

        if self._cached_filtered_error_key == cache_key and self._cached_filtered_error_table:
            return self._cached_filtered_error_table, False

        self._clear_cached_filtered_error_table()

        filtered_table_name = service_helpers._safe_pg_name(
            f"errors_{self.main_table_name}",
            f"_filtered_{uuid.uuid4().hex[:10]}"
        )
        service_helpers.materialize_selected_errors_table(
            self.main_table_name,
            filtered_table_name,
            anomaly_methods=list(normalized_methods),
            rarity_threshold=normalized_rarity,
        )
        self._cached_filtered_error_key = cache_key
        self._cached_filtered_error_table = filtered_table_name
        return filtered_table_name, False

    def drop_error_table(self, table_name: str | None):
        """
        Drop a temporary error table if one was created for a request.
        """
        if not table_name:
            return

        if table_name == self._cached_filtered_error_table:
            self._cached_filtered_error_key = None
            self._cached_filtered_error_table = None

        with self.engine.begin() as conn:
            conn.execute(sa_text(f'DROP TABLE IF EXISTS "{table_name}"'))

    def build_filtered_request_ops(self, request_table_name=None, selected_anomaly_methods=None, rarity_threshold: float = 0.05):
        """
        Create a request-scoped DBOperations object pointed at the effective
        filtered error table for the requested or currently loaded main table.
        Returns the request ops, resolved table name, error table name, and cleanup table name.
        """
        table_name = request_table_name or self.main_table_name
        if not table_name:
            raise ValueError("No table name provided and no main table is loaded.")

        if self.main_table_name == table_name:
            self._ensure_table_metadata_loaded()
            base_ops = self
        else:
            base_ops = self.__class__(self.engine)
            base_ops.load_table(table_name)

        error_table_name, should_cleanup = base_ops.create_filtered_error_table(
            selected_anomaly_methods=selected_anomaly_methods,
            rarity_threshold=rarity_threshold,
        )
        request_ops = base_ops._clone_loaded_state(error_table_name=error_table_name)
        cleanup_table_name = error_table_name if should_cleanup else None
        return request_ops, table_name, error_table_name, cleanup_table_name

    def get_row_count(self, table_name: str) -> int:
        """
        Returns the actual row count of a table directly from the database.
        :arg: table_name: name of the table to count rows from.
        :return: the number of rows in the table.
        """
        return fetch_sql(f'SELECT COUNT(*) FROM "{table_name}"', True, self.engine)


    def add_data_filters(self, sql_filters) -> dict:
        """
        Adds a list of new filters to the set of filters and updates the table of satisfying indices.
        :return: a success message and the internal indices of added filters.
        """

        return self.filtering_table.add_filters(sql_filters)


    def remove_data_filters(self, sql_filters) -> dict:
        """
        Deletes one or more filters from the filter table and updates the table of satisfying indices.
        For efficiency, gives the option to delete multiple filters at once to not need to recreate the filter
        table several times if the user knows they want to delete more than 1 filter.
        :return: the index of the new filter if success.
        """

        return self.filtering_table.delete_filters(sql_filters)


    def generate_one_d_histogram_with_errors(self, axis_column: str, bin_count=10):
        """
        Creates the entire SQL query for generating a 1D histogram with errors and executes it to the Postgres database.
        :arg: axis_column: name of the axis column.
        :arg: bin_count: number of bins (used for numeric data). If categorical then bins are individual labels.
        :return: the JSON object containing histogram data.
        """

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        hist_1d_steps = [self.gather_filtered_rows(axis_column, None),
                         self.gather_bins_1d_hist(axis_column, bin_count),
                         self.errors_per_bin_1d_hist(axis_column),
                         self.form_final_1d_hist_bins(),
                         self.build_numeric_scale_data_1d_hist(axis_column, bin_count),
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


    def gather_filtered_rows(self, x_axis_column: str, y_axis_column: object) -> str:
        """
        Gets the rows of a column with filtering applied if applicable.
        :arg: x_axis_column: name of the x-axis column to retrieve rows from.
        :arg: y_axis_column: name of the y-axis column to retrieve rows from.
        :return: the query for the data rows.
        """

        if self.filtering_table.table_exists:
            data_row_filtering = f'''
                JOIN "{self.filtering_table.filtering_table_name}"
                  ON "{self.main_table_name}"."ID" =
                     "{self.filtering_table.filtering_table_name}"."ID"
            '''
        else:
            data_row_filtering = ""

        # 1D hist case
        if y_axis_column is None:
            cols_to_gather = f"\"{x_axis_column}\" AS value"
        # 2D hist case
        else:
            cols_to_gather = f"\"{x_axis_column}\" AS x_value, \"{y_axis_column}\" AS y_value"

        data_rows = f'''
            WITH data_rows AS (
                SELECT "ID", {cols_to_gather}
                FROM "{self.main_table_name}"
                {data_row_filtering}
            )
        '''

        return data_rows


    def gather_bins_1d_hist(self, axis_column: str, bin_count: int) -> str:
        """
        Binning logic for 1D histogram. Bins numeric columns into a specified number of bins linearly across
        the range of the data. If numeric values in a numeric column fail to parse, then they fall back to categorical.
        If the column is categorical then each 'bin' is just an individual label value.
        :arg: axis_column: name of the column to bin from.
        :arg: bin_count: number of bins (used for numeric data).
        :return: the query for the binning.
        """

        if self.col_types.is_numeric_col(axis_column):
            numeric_regex = r"'^\s*-?\d+(\.\d+)?\s*$'"
            bin_logic = f'''CASE
                                WHEN d.value::text ~ {numeric_regex} THEN
                                    -- Clamp bin number to 0..(bin_count-1) range
                                    LEAST(
                                        GREATEST(
                                            COALESCE(
                                                width_bucket(
                                                    d.value::numeric,
                                                    (SELECT MIN(value::numeric) FROM data_rows WHERE value::text ~ {numeric_regex}),
                                                    (SELECT MAX(value::numeric) FROM data_rows WHERE value::text ~ {numeric_regex}),
                                                    {bin_count}
                                                ) - 1,
                                                0
                                            ),
                                            0
                                        ),
                                        {bin_count - 1}
                                    )::text
                                ELSE
                                    d.value::text  -- Non-numeric value in numeric column
                            END '''
        else:
            bin_logic = f'''COALESCE(d.value::text, 'null')'''

        gather_bins = f''',
            binned_data AS (
                SELECT
                    d."ID",
                    CASE
                        WHEN d.value IS NULL THEN 'null'  -- Handle NULL values first
                        ELSE {bin_logic}
                    END as bin
                FROM data_rows d
            ),'''

        return gather_bins


    def errors_per_bin_1d_hist(self, axis_column: str) -> str:
        """
        Gathers error types for the 1D histogram per bin.
        :arg: axis_column: name of the column to get error types form.
        :return: the query for the error grouping.
        """

        return f''' errors_per_bin AS (
                SELECT
                    b.bin,
                    e.error_type,
                    COUNT(*) as error_count
                FROM binned_data b
                JOIN "{self.error_table_name}" e ON b."ID" = e.row_id
                WHERE e.column_id = '{axis_column}'
                GROUP BY b.bin, e.error_type
            ),'''


    def form_final_1d_hist_bins(self) -> str:
        """
        Formulates the final histogram bins by collecting each bin, total counts, and condensing error
        types for each bin into a JSON object. This also formulates final bins for bins with no errors.
        :return: the query for the final 1d hist bins.
        """

        return ''' histogram_bins AS (
                SELECT
                    b.bin,
                    COUNT(*) as total_items,
                    jsonb_object_agg(
                        e.error_type,
                        e.error_count
                    ) FILTER (WHERE e.error_type IS NOT NULL) as errors
                FROM binned_data b
                LEFT JOIN errors_per_bin e ON b.bin = e.bin
                GROUP BY b.bin
            ) '''


    def build_numeric_scale_data_1d_hist(self, axis_column: str, bin_count: int) -> str:
        """
        Build linear scaling data for each of the numeric bins using the given column to build the 1d histogram.
        :arg: axis_column: name of the column to build numeric scaling data for.
        :arg: bin_count: number of bins to build the 1d histogram.
        :return: the query for the numeric scaling data.
        """

        if not self.col_types.is_numeric_col(axis_column):
            return ""
        else:
            return f''', range_data AS (
                SELECT
                    MIN(value::numeric) AS min_val,
                    CASE
                        WHEN MAX(value::numeric) = MIN(value::numeric)
                        THEN 0
                        ELSE (MAX(value::numeric) - MIN(value::numeric)) / {bin_count}::numeric
                    END AS bin_width
                FROM data_rows
            ),
            numeric_scale_data AS (
                SELECT
                    n AS bin_num,
                    r.min_val + n * r.bin_width     AS x0,
                    r.min_val + (n + 1) * r.bin_width AS x1
                FROM range_data r
                CROSS JOIN generate_series(0, {bin_count} - 1) n
            )'''


    def construct_1d_hist_json(self, axis_column: str) -> str:
        """
        Build the final JSON object.
        :arg: axis_column: name of the column to build the final JSON object for.
        :return: the query for the final JSON object
        """

        numeric_regex = r"'^\d+$'"
        empty_set = r"'{}'"
        binned_data = '''SELECT (SELECT json_agg(json_build_array("ID", bin)) FROM binned_data),'''


        if self.col_types.is_numeric_col(axis_column):
            return f'''{binned_data} (SELECT json_build_object(
                'histograms',
                    -- For numeric: handle mixed bins (numeric and "null") - keep bins as text
                    (SELECT COALESCE(json_agg(
                        json_build_object(
                            'xBin', bin,
                            'xType', CASE WHEN bin ~ {numeric_regex} THEN 'numeric' ELSE 'categorical' END,
                            'count', COALESCE(errors, {empty_set}::jsonb) || jsonb_build_object('items', total_items)
                        ) ORDER BY CASE WHEN bin ~ {numeric_regex} THEN lpad(bin, 10, '0') ELSE bin END
                    ), '[]'::json) FROM histogram_bins),
                    'scaleX',
                json_build_object(
                    'numeric',
                        (SELECT COALESCE(json_agg(json_build_object('x0', x0, 'x1', x1) ORDER BY bin_num), '[]'::json) FROM numeric_scale_data),
                    'categorical', (
                        -- Always include categorical values (null and non-numeric values in numeric columns)
                        SELECT COALESCE(
                            json_agg(DISTINCT bin ORDER BY bin),
                            '[]'::json
                        )
                        FROM histogram_bins
                        WHERE NOT (bin ~ {numeric_regex})  -- Only non-numeric bin labels
                    )
                )
            ))'''
        else:
            return f'''{binned_data} (SELECT json_build_object(
                'histograms',
                    -- For categorical: keep bin as text
                    (SELECT COALESCE(json_agg(
                        json_build_object(
                            'xBin', bin,
                            'xType', 'categorical',
                            'count', COALESCE(errors, {empty_set}::jsonb) || jsonb_build_object('items', total_items)
                        ) ORDER BY bin
                    ), '[]'::json) FROM histogram_bins),
                    'scaleX',
                json_build_object(
                    'numeric',
                        '[]'::json,
                    'categorical', (
                        -- Always include categorical values (null and non-numeric values in numeric columns)
                        SELECT COALESCE(
                            json_agg(DISTINCT bin ORDER BY bin),
                            '[]'::json
                        )
                        FROM histogram_bins
                        WHERE NOT (bin ~ {numeric_regex})  -- Only non-numeric bin labels
                    )
                )
            ))'''


    def generate_two_d_histogram_with_errors(self, x_axis_column: str, y_axis_column: str, x_bin_count=10, y_bin_count=10) -> str:
        """
        Creates the entire SQL query for generating a 2D histogram with errors and executes it to the Postgres database.
        :arg: x_axis_column: the column to create the x-axis for the 2D histogram.
        :arg: y_axis_column: the column to create the y-axis for the 2D histogram.
        :arg: x_bin_count: number of bins (used for numeric data) for the x-axis. If categorical then bins are individual labels.
        :arg: y_bin_count: number of bins (used for numeric data) for the y-axis. If categorical then bins are individual labels.
        :return: the JSON object containing histogram data.
        """

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        x_alias            = "x_value"
        y_alias            = "y_value"
        x_bound_table      = "x_bounds"
        y_bound_table      = "y_bounds"
        x_scale_table_name = "x_numeric_scale_data"
        y_scale_table_name = "y_numeric_scale_data"

        hist_2d_steps = [self.gather_filtered_rows(x_axis_column, y_axis_column),
                         self.generate_2d_hist_bounds(x_bound_table, x_axis_column, x_alias),
                         self.generate_2d_hist_bounds(y_bound_table, y_axis_column, y_alias),
                         self.gather_bins_2d_hist(x_axis_column, y_axis_column, x_bin_count, y_bin_count, x_alias, y_alias, x_bound_table, y_bound_table),
                         self.errors_per_bin_2d_hist(x_axis_column, y_axis_column),
                         self.form_final_2d_hist_bins(),
                         self.build_numeric_scale_data_2d_hist(x_bound_table, x_axis_column, x_scale_table_name, x_bin_count),
                         self.build_numeric_scale_data_2d_hist(y_bound_table, y_axis_column, y_scale_table_name, y_bin_count),
                         self.construct_2d_hist_json(x_axis_column, y_axis_column, x_scale_table_name, y_scale_table_name)]

        hist_2d_final_query = "".join(hist_2d_steps)
        binned_data, hist = fetch_sql(hist_2d_final_query, False, self.engine)[0]
        self.update_active_hists(binned_data, False, (x_axis_column, y_axis_column))
        return hist


    def generate_2d_hist_bounds(self, bound_table_name: str, axis_column: str, col_alias: str) -> str:
        """
        Generates the min and max value boundaries for a histogram column.
        :arg: bound_table_name: what the name of the bound table should be.
        :arg: axis_column: name of the axis column.
        :arg: col_alias: alias of the axis column (could be the same name as the axis column).
        :return: the query to generate the bound tables.
        """

        if self.col_types.is_numeric_col(axis_column):
            numeric_regex = r"'^\s*-?\d+(\.\d+)?\s*$'"
            return f''', {bound_table_name} AS (
                    SELECT
                        COALESCE(MIN({col_alias}::numeric), 0) as min_val,
                        COALESCE(MAX({col_alias}::numeric), 1) as max_val
                    FROM data_rows
                    WHERE {col_alias}::text ~ {numeric_regex}  -- only numeric values
                )'''
        else:
            return ""


    def gather_bins_2d_hist(self, x_axis_column: str, y_axis_column: str, x_bin_count: int, y_bin_count: int, x_alias: str, y_alias: str, x_bound_table: str, y_bound_table: str) -> str:
        """
        Binning logic for 2D histogram. Bins numeric columns into a specified number of bins linearly across
        the range of the data. If numeric values in a numeric column fail to parse, then they fall back to categorical.
        If the column is categorical then each 'bin' is just an individual label value. Done for both axes.
        :arg: x_axis_column: name of the x-axis column to bin from.
        :arg: y_axis_column: name of the y-axis column to bin from.
        :arg: x_bin_count: number of bins on the x-axis (used for numeric data).
        :arg: y_bin_count: number of bins on the y-axis (used for numeric data).
        :arg: x_alias: alias of the x-axis column.
        :arg: y_alias: alias of the y-axis column.
        :arg: x_bound_table: name of the table that contains x bounding information.
        :arg: y_bound_table: name of the table that contains y bounding information.
        :return: the query for the 2D histogram binning.
        """
        axis_info = [(x_axis_column, x_bin_count, x_alias, x_bound_table), (y_axis_column, y_bin_count, y_alias, y_bound_table)]
        axis_queries = []

        for axis_column, bin_count, axis_alias, bounding_table in axis_info:
            numeric_regex = r"'^\s*-?\d+(\.\d+)?\s*$'"

            if self.col_types.is_numeric_col(axis_column):
                bin_logic = f'''CASE
                                    WHEN d.{axis_alias}::text ~ {numeric_regex} THEN
                                        -- Clamp bin number to 0..(bin_count-1) range
                                        LEAST(
                                            GREATEST(
                                                COALESCE(
                                                    width_bucket(
                                                        d.{axis_alias}::numeric,
                                                        (SELECT min_val FROM {bounding_table}),
                                                        (SELECT max_val FROM {bounding_table}),
                                                        {bin_count}
                                                    ) - 1,
                                                    0
                                                ),
                                                0
                                            ),
                                            {bin_count - 1}
                                        )::text
                                    ELSE
                                        d.{axis_alias}::text  -- Non-numeric value in numeric column
                                END '''
            else:
                bin_logic = f'''COALESCE(d.{axis_alias}::text, 'null')'''

            axis_queries.append(bin_logic)

        gather_bins = f''',
            binned_data AS (
                SELECT
                    d."ID",
                    CASE
                        WHEN d.x_value IS NULL THEN 'null'
                        ELSE {axis_queries[0]}
                    END as x_bin,
                    CASE
                        WHEN d.y_value IS NULL THEN 'null'
                        ELSE {axis_queries[1]}
                    END as y_bin
                FROM data_rows d
            )'''

        return gather_bins


    def errors_per_bin_2d_hist(self, x_axis_column: str, y_axis_column: str) -> str:
        """
        Gathers error types for the 2d histogram per bin.
        :arg: x_axis_column: name of the x-axis column to collect error information from.
        :arg: y_axis_column: name of the y-axis column to collect error information from.
        :return: the query for the error grouping.
        """

        return f''',
            errors_per_bin AS (
                SELECT
                    b.x_bin,
                    b.y_bin,
                    e.error_type,
                    COUNT(*) as error_count
                FROM binned_data b
                JOIN "{self.error_table_name}" e ON b."ID" = e.row_id
                WHERE e.column_id IN ('{x_axis_column}', '{y_axis_column}')
                GROUP BY b.x_bin, b.y_bin, e.error_type
            )'''


    def form_final_2d_hist_bins(self) -> str:
        """
        Formulates the final histogram bins by collecting each bin, total counts, and condensing error
        types for each bin into a JSON object. This also formulates final bins for bins with no errors.
        :return: the query for the final 2d hist bins.
        """

        return ''',
            histogram_bins AS (
                SELECT
                    b.x_bin,
                    b.y_bin,
                    COUNT(*) as total_items,
                    jsonb_object_agg(
                        e.error_type,
                        e.error_count
                    ) FILTER (WHERE e.error_type IS NOT NULL) as errors
                FROM binned_data b
                LEFT JOIN errors_per_bin e ON b.x_bin = e.x_bin AND b.y_bin = e.y_bin
                GROUP BY b.x_bin, b.y_bin
            )'''


    def build_numeric_scale_data_2d_hist(self, bound_table_name: str, axis_column: str, scale_table_name: str, bin_count: int) -> str:
        """
        Build linear scaling data for each of the numeric bins using the given column to build the 1d histogram.
        :arg: bound_table_name: name of the table with bounding information for the chosen axis column.
        :arg: axis_column: name of the column to build numeric scaling data for.
        :arg: scale_table_name: what the name of the table should be that scaling data was built for.
        :arg: bin_count: the number of histogram binds for the column.
        :return: the query for the numeric scaling data.
        """

        if self.col_types.is_numeric_col(axis_column):
            return f''', {scale_table_name}_range_data AS (
                SELECT
                    min_val,
                    (max_val::numeric - min_val::numeric) / {bin_count}::numeric as bin_width
                FROM {bound_table_name}
            ),
            {scale_table_name} AS (
                SELECT
                    n AS bin_num,
                    r.min_val + n * r.bin_width     AS x0,
                    r.min_val + (n + 1) * r.bin_width AS x1
                FROM {scale_table_name}_range_data r
                CROSS JOIN generate_series(0, {bin_count} - 1) n
            )'''
        else:
            return ""


    def construct_2d_hist_json(self, x_axis_column: str, y_axis_column: str, x_scale_table_name: str, y_scale_table_name: str) -> str:
        """
        Build the final JSON object for the 2D histogram.
        :arg: x_axis_column: name of the x-axis column to build the final JSON object for.
        :arg: y_axis_column: name of the y-axis column to build the final JSON object for.
        :arg: x_scale_table_name: the name of the table that contains x-axis numeric scaling info.
        :arg: y_scale_table_name: the name of the table that contains y-axis numeric scaling info.
        :return: the query for the final JSON object
        """

        numeric_regex = r"'^\d+$'"
        empty_set = r"'{}'"

        # Handles mixed types in x-axis.
        if self.col_types.is_numeric_col(x_axis_column):
            json_x_type = f'''CASE WHEN x_bin ~ {numeric_regex} THEN 'numeric' ELSE 'categorical' END'''
            json_order_by_x = f'''CASE WHEN x_bin ~ {numeric_regex} THEN lpad(x_bin, 10, '0') ELSE x_bin END'''
        else:
            json_x_type = "'categorical'"
            json_order_by_x = "x_bin"

        # Handles mixed types in y-axis.
        if self.col_types.is_numeric_col(y_axis_column):
            json_y_type = f'''CASE WHEN y_bin ~ {numeric_regex} THEN 'numeric' ELSE 'categorical' END'''
            json_order_by_y = f'''CASE WHEN y_bin ~ {numeric_regex} THEN lpad(y_bin, 10, '0') ELSE y_bin END'''
        else:
            json_y_type = "'categorical'"
            json_order_by_y = "y_bin"

        json_order_by = ", ".join([json_order_by_x, json_order_by_y])

        binned_data = '''SELECT (SELECT json_agg(json_build_array("ID", x_bin, y_bin)) FROM binned_data),'''

        json_hist_data = f'''{binned_data} (SELECT json_build_object(
                        'histograms',
                            (SELECT COALESCE(json_agg(
                                json_build_object(
                                    'xBin', x_bin,
                                    'yBin', y_bin,
                                    'xType', {json_x_type},
                                    'yType', {json_y_type},
                                    'count', COALESCE(errors, {empty_set}::jsonb) || jsonb_build_object('items', total_items)
                                ) ORDER BY {json_order_by}
                            ), '[]'::json) FROM histogram_bins)'''

        json_query_components = [json_hist_data]
        json_scale_data = [("scaleX", x_axis_column, x_scale_table_name, "x_bin"),
                           ("scaleY", y_axis_column, y_scale_table_name, "y_bin")]

        for i in range(len(json_scale_data)):
            scale_label, axis_column, scale_table_name, axis_bin = json_scale_data[i]
            if self.col_types.is_numeric_col(axis_column):
                axis_numeric_info = f'''(SELECT COALESCE(json_agg(json_build_object('x0', x0, 'x1', x1) ORDER BY bin_num),
                                        '[]'::json) FROM {scale_table_name})'''
            else:
                axis_numeric_info = "'[]'::json"

            # The final scale data needs to close the entire encapsulating JSON object and SELECT.
            ending_parenthesis = "))" if i == len(json_scale_data) - 1 else ""

            scale_query_component = f'''
            '{scale_label}', json_build_object(
                'numeric', {axis_numeric_info},
                'categorical', (
                    -- Always include categorical values (null and non-numeric values in numeric columns)
                    SELECT COALESCE(
                        json_agg(DISTINCT {axis_bin} ORDER BY {axis_bin}),
                        '[]'::json
                    )
                    FROM histogram_bins
                    WHERE NOT ({axis_bin} ~ {numeric_regex})  -- Only non-numeric bin labels
                )
            ){ending_parenthesis}'''

            json_query_components.append(scale_query_component)

        return ",\n".join(json_query_components)


    def generate_scatterplot_with_errors(self, x_axis_column: str, y_axis_column: str, error_sample_size=30, total_sample_size=100):
        """
        Creates the entire SQL query for generating a scatterplot with errors and executes it to the Postgres database.
        :arg: x_axis_column: the column to create the x-axis for the 2D histogram.
        :arg: y_axis_column: the column to create the y-axis for the 2D histogram.
        :arg: error_sample_size: how many error data points to sample.
        :arg: total_sample_size: how many data points to sample total for the displayed scatter plot.
        :return: the JSON object containing scatterplot data.
        """

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        x_alias            = "x_value"
        y_alias            = "y_value"
        x_bound_table      = "x_bounds"
        y_bound_table      = "y_bounds"

        scatter_steps = [self.sample_rows_scatter(x_axis_column, y_axis_column, error_sample_size, total_sample_size),
                         self.scatter_aggregate_errors(x_axis_column, y_axis_column),
                         self.collect_scatter_axis_bounds(x_bound_table, x_axis_column, x_alias),
                         self.collect_scatter_axis_bounds(y_bound_table, y_axis_column, y_alias),
                         self.construct_scatter_json(x_axis_column, y_axis_column, x_alias, y_alias, x_bound_table, y_bound_table)]

        scatter_final_query = "".join(scatter_steps)
        return fetch_sql(scatter_final_query, True, self.engine)


    def sample_rows_scatter(self, x_axis_column: str, y_axis_column: str, error_sample_size: int, total_sample_size: int) -> str:
        """
        Gathers a sample of data points that exist in the x-axis and y-axis columns that have errors according to
        error_sample_size and that don't have errors according to total_sample_size - error_sample_size. This must
        follow prior filtering, so that may make it smaller than specified params.
        :arg: x_axis_column: the x-axis column.
        :arg: y_axis_column: the y-axis column.
        :arg: error_sample_size: how many error data points to sample.
        :arg: total_sample_size: how many data points to sample total for the displayed scatter plot.
        :return: the query for sampling the rows.
        """

        if self.filtering_table.table_exists:
            data_row_filtering_main = f'''
                JOIN "{self.filtering_table.filtering_table_name}"
                  ON "{self.main_table_name}"."ID" =
                     "{self.filtering_table.filtering_table_name}"."ID"
            '''

            data_row_filtering_error = f'''
                JOIN "{self.filtering_table.filtering_table_name}"
                  ON e.row_id =
                     "{self.filtering_table.filtering_table_name}"."ID"
            '''
        else:
            data_row_filtering_main = ""
            data_row_filtering_error = ""

        return f'''WITH
            -- Step 1: Sample IDs (prioritize errors, then clean rows)
            all_sampled_ids AS (
                (
                    -- Sample error rows
                    SELECT e.row_id
                    FROM "{self.error_table_name}" e
                    {data_row_filtering_error}
                    WHERE e.column_id IN ('{x_axis_column}', '{y_axis_column}')
                    ORDER BY RANDOM()
                    LIMIT {error_sample_size}
                )
                UNION ALL
                (
                    -- Sample clean rows to fill quota
                    SELECT "ID" as row_id
                    FROM "{self.main_table_name}"
                    {data_row_filtering_main}
                    WHERE "ID" NOT IN (
                          SELECT DISTINCT row_id
                          FROM "{self.error_table_name}"
                          WHERE column_id IN ('{x_axis_column}', '{y_axis_column}')
                    )
                    ORDER BY RANDOM()
                    LIMIT GREATEST({total_sample_size - error_sample_size}, 0)
                )
            )'''


    def scatter_aggregate_errors(self, x_axis_column: str, y_axis_column: str) -> str:
        """
        Gathers the associated errors / non-errors with each of the sampled data points.
        :arg: x_axis_column: the x-axis column.
        :arg: y_axis_column: the y-axis column.
        :return: the query for aggregating scatterplot error data w/ sampled points.
        """

        return f''',
            -- Step 2: Get data for sampled IDs with error aggregation
            sampled_data AS (
                SELECT
                    m."ID",
                    m."{x_axis_column}" as x_value,
                    m."{y_axis_column}" as y_value,
                    COALESCE(
                        json_agg(e.error_type) FILTER (WHERE e.error_type IS NOT NULL),
                        '[]'::json
                    ) as error_list
                FROM all_sampled_ids s
                JOIN "{self.main_table_name}" m ON s.row_id = m."ID"
                LEFT JOIN "{self.error_table_name}" e ON s.row_id = e.row_id AND e.column_id IN ('{x_axis_column}', '{y_axis_column}')
                GROUP BY m."ID", m."{x_axis_column}", m."{y_axis_column}"
            )'''


    def collect_scatter_axis_bounds(self, bound_table_name: str, axis_column: str, col_alias: str) -> str:
        """
        Gets the numeric bounds for a scatterplot axis.
        :arg: bound_table_name: the name to assign to the axis bounding table.
        :arg: axis_column: the column to get the bounding data of.
        :arg: col_alias: the alias of the axis_column.
        :return: the query for aggregating scatterplot error data w/ sampled points.
        """

        if self.col_types.is_numeric_col(axis_column):
            return f''',
                {bound_table_name} AS (
                    SELECT
                        MIN({col_alias}::numeric) as min_val,
                        MAX({col_alias}::numeric) as max_val
                    FROM sampled_data
                )'''
        else:
            return ""


    def construct_scatter_json(self, x_axis_column: str, y_axis_column: str, x_col_alias: str, y_col_alias: str, x_bound_table: str, y_bound_table: str) -> str:
        """
        Constructs the final JSON object for the scatterplot
        :arg: x_axis_column: the x-axis column.
        :arg: y_axis_column: the y-axis column.
        :arg: x_col_alias: the alias of the x column.
        :arg: y_col_alias: the alias of the y column.
        :arg: x_bound_table: the name of the table that contains bounding information for x.
        :arg: y_bound_table: the name of the table that contains bounding information for y.
        :return: returns the final JSON query for the scatterplot.
        """

        numeric_regex = r"'^\s*-?\d+(\.\d+)?\s*$'"


        # Helper function to determine axis type
        def determine_axis_type(axis_column: str, col_alias: str) -> str:
            if self.col_types.is_numeric_col(axis_column):
                return "ELSE 'numeric'"
            elif self.col_types.is_mixed_col(axis_column):
                return f"WHEN ({col_alias}::text ~ {numeric_regex}) THEN 'numeric' ELSE 'categorical'"
            else:
                return "ELSE 'categorical'"


        # Helper function to determine JSON axis type
        def determine_json_axis_type(axis_column: str, col_alias: str) -> str:
            if self.col_types.is_numeric_col(axis_column):
                return f"ELSE to_json({col_alias}::numeric)"
            elif self.col_types.is_mixed_col(axis_column):
                return f"WHEN ({col_alias}::text ~ {numeric_regex}) THEN to_json({col_alias}::numeric) ELSE to_json({col_alias}::text)"
            else:
                return f"ELSE to_json({col_alias}::text)"


        xType = determine_axis_type(x_axis_column, x_col_alias)
        yType = determine_axis_type(y_axis_column, y_col_alias)
        xTypeJSON = determine_json_axis_type(x_axis_column, x_col_alias)
        yTypeJSON = determine_json_axis_type(y_axis_column, y_col_alias)

        json_data = f'''
            SELECT json_build_object(
                'data', (
                    SELECT COALESCE(json_agg(
                        json_build_object(
                            'ID', "ID",
                            'xType', CASE
                                WHEN x_value IS NULL THEN 'categorical'
                                {xType}
                            END,
                            'yType', CASE
                                WHEN y_value IS NULL THEN 'categorical'
                                {yType}
                            END,
                            'x', CASE
                                WHEN x_value IS NULL THEN to_json('null'::text)
                                {xTypeJSON}
                            END,
                            'y', CASE
                                WHEN y_value IS NULL THEN to_json('null'::text)
                                {yTypeJSON}
                            END,
                            'errors', error_list
                        )
                    ), '[]'::json)
                    FROM sampled_data
                )'''

        json_query_components = [json_data]
        json_scale_data = [("scaleX", x_axis_column, x_bound_table, x_col_alias),
                           ("scaleY", y_axis_column, y_bound_table, y_col_alias)]

        for i in range(len(json_scale_data)):
            scale_label, axis_column, bounding_table, axis_alias = json_scale_data[i]

            if self.col_types.is_numeric_col(axis_column):
                axis_numeric_info = f'''json_build_array(
                    (SELECT min_val FROM {bounding_table}),
                    (SELECT max_val + 1 FROM {bounding_table})
                )'''
            elif self.col_types.is_mixed_col(axis_column):
                axis_numeric_info = f'''json_build_array(
                            (SELECT COALESCE(MIN({axis_alias}::numeric), 0) FROM sampled_data
                             WHERE {axis_alias}::text ~ {numeric_regex}),
                            (SELECT COALESCE(MAX({axis_alias}::numeric), 1) + 1 FROM sampled_data
                             WHERE {axis_alias}::text ~ {numeric_regex})
                        )'''
            else:
                axis_numeric_info = "'[]'::json"

            ending_parenthesis = ")" if i == len(json_scale_data) - 1 else ""

            json_component = f'''
                '{scale_label}', json_build_object(
                        'numeric', {axis_numeric_info},
                        'categorical', (
                            SELECT COALESCE(
                                json_agg(DISTINCT COALESCE({axis_alias}::text, 'null') ORDER BY COALESCE({axis_alias}::text, 'null')),
                                '["null"]'::json
                            ) FROM sampled_data
                            WHERE NOT ({axis_alias}::text ~ {numeric_regex}) OR {axis_alias} IS NULL
                        )
                    ){ending_parenthesis}'''

            json_query_components.append(json_component)

        return ",\n".join(json_query_components)


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
