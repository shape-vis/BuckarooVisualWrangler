from app.db_utils.column_types import ColumnTypes
from app.db_utils.detector_sql import ERROR_TYPES
from app.db_utils.execute_sql import fetch_sql, quote_identifier, quote_literal

"""
Bins two pgraph nodes' tables on shared axes, inside PostgreSQL - October 12, 2026.

--- CompareSQL ---
The compare panel plots two nodes' data against each other. DBOperations' plots cannot do that: each bins one table
across its own min and max, so once a delete trims the outliers the two nodes' bins cover different ranges and bar n
on one side is not bar n on the other. Everything here bins both tables on one shared axis instead, which is what
makes a bin-by-bin difference meaningful.

An axis is numeric when at least half the values on it, both tables together, are numbers. Its numbers are binned
linearly across the range of both tables, and everything else - nulls, text in a numeric column - becomes a
categorical label beside the bins, the split DBOperations' histograms make. On a categorical axis every value is a
label. An axis keeps at most MAX_LABELS labels: the most common, plus null whenever it occurs, since a missing-value
repair is often what a comparison is about. The rest fold into OTHER_LABEL.

Each row carries its error flags from the start - found by its integer row id - and each table is then reduced to its
distinct values, or value pairs for a heatmap, with how many rows hold each and how many of those rows each error type
flags. Every step after that works on those few values instead of the rows. Nothing ever sorts or joins the long tail
of labels by their text, which for a column of long free text would cost far more than the rest of the plot: the
labels are grouped by hashing, ranked with a hash of the text breaking ties, and only the few kept are sorted by name.
The queries build the panel's JSON themselves, as DBOperations' do.
"""

# The plots CompareSQL draws
PLOT_KINDS = ("histogram", "heatmap")

# What a null is called on a categorical axis - the label DBOperations' histograms give it
NULL_LABEL = "null"

# A categorical axis keeps this many labels, the last a catch-all for the long tail. Two states are read bar against
# bar, and past a couple of dozen bands neither side is legible.
MAX_LABELS = 20
OTHER_LABEL = "(other)"

# The two sides of a comparison: selection A and selection B
SIDES = ("a", "b")


class CompareSQL:
    def __init__(self, engine, table_a: str, table_b: str):
        """
        :arg: engine: SQLAlchemy engine.
        :arg: table_a: selection A's node table - from the session graph, never straight from a request.
        :arg: table_b: selection B's node table.
        """
        self.engine = engine
        self.tables = {"a": table_a, "b": table_b}
        self.col_types = {
            "a": ColumnTypes.for_table(table_a, engine),
            "b": ColumnTypes.for_table(table_b, engine),
        }


    def check_columns(self, columns: list):
        """
        Refuses a column either table lacks, before any name is put into a query.
        :arg: columns: the compared columns.
        """

        for side in SIDES:
            known_columns = self.col_types[side].column_names
            for column in columns:
                if column not in known_columns:
                    raise ValueError(f"{self.tables[side]} has no column {column!r}")


    def generate_compare_histogram(self, column: str, bin_count: int) -> dict:
        """
        Creates the entire SQL query for both tables' histograms of one column, binned on one shared axis, and
        executes it.
        :arg: column: the column to bin.
        :arg: bin_count: how many bins the numeric part of the axis is split into.
        :return: {"scaleX", "bins": [{"xType", "xBin", "a", "b"}], "rows": {"a", "b"}}. Every bin on the axis is
                 listed, empty ones included, so a difference plot has a zero to measure against.
        """

        self.check_columns([column])
        axes = [("x", column)]

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        histogram_steps = [self.gather_compared_values(axes),
                           self.gather_axis_extent("x"),
                           self.gather_shared_axis("x", bin_count),
                           self.rank_axis_labels("x"),
                           self.summarize_axis_labels("x"),
                           self.keep_axis_labels("x"),
                           self.list_axis_keys("x"),
                           self.build_axis_scale("x"),
                           self.gather_bins_compare(axes),
                           self.count_bin_items(axes),
                           self.form_final_compare_bins(axes),
                           self.construct_compare_histogram_json()]

        histogram_final_query = "".join(histogram_steps)
        return fetch_sql(histogram_final_query, True, self.engine)


    def generate_compare_heatmap(self, x_column: str, y_column: str, bin_count: int) -> dict:
        """
        Creates the entire SQL query for both tables' 2D histograms on shared axes, and executes it.
        :arg: x_column: the column on the x-axis.
        :arg: y_column: the column on the y-axis - it may be the x column again.
        :arg: bin_count: how many bins the numeric part of each axis is split into.
        :return: {"scaleX", "scaleY", "tiles": [{"xType", "xBin", "yType", "yBin", "a", "b"}], "rows": {"a", "b"}}.
                 Only tiles holding rows on at least one side are listed - a grid of empties would be most of it.
        """

        self.check_columns([x_column, y_column])
        axes = [("x", x_column), ("y", y_column)]

        # This function is made up of several sequential steps / segments to achieve the final query string
        # Keep them in order to join all together at the end.
        heatmap_steps = [self.gather_compared_values(axes),
                         self.gather_axis_extent("x"),
                         self.gather_axis_extent("y"),
                         self.gather_shared_axis("x", bin_count),
                         self.gather_shared_axis("y", bin_count),
                         self.rank_axis_labels("x"),
                         self.rank_axis_labels("y"),
                         self.summarize_axis_labels("x"),
                         self.summarize_axis_labels("y"),
                         self.keep_axis_labels("x"),
                         self.keep_axis_labels("y"),
                         self.list_axis_keys("x"),
                         self.list_axis_keys("y"),
                         self.build_axis_scale("x"),
                         self.build_axis_scale("y"),
                         self.gather_bins_compare(axes),
                         self.count_bin_items(axes),
                         self.form_final_compare_bins(axes),
                         self.construct_compare_heatmap_json()]

        heatmap_final_query = "".join(heatmap_steps)
        return fetch_sql(heatmap_final_query, True, self.engine)


    def side_rows(self, side: str, axes: list) -> str:
        """
        One table's rows, each axis's value read three ways: whether it is present, its number when it is one, and the
        label it would carry on a categorical axis. A value's label names it exactly - two values with the same label
        always land in the same bin - so the label is what the steps below group values by.

        Each row also carries the error types flagged on the compared columns, each type once however many of the
        columns carry it: a row flagged the same way on both of a heatmap's columns is one flagged row in its tile.
        :arg: side: "a" or "b".
        :arg: axes: (axis name, column) pairs, e.g. [("x", "age")].
        :return: a subquery for the rows.
        """

        col_types = self.col_types[side]
        table = quote_identifier(self.tables[side])
        errors = quote_identifier("errors_" + self.tables[side])
        null_label = quote_literal(NULL_LABEL)

        selected = ['d."ID" AS row_id', "row_flags.error_types"]
        column_names = []
        for axis, column in axes:
            value = "d." + quote_identifier(column)
            number = col_types.number_expression(value, column)
            selected.append(f"{value} IS NOT NULL AS {axis}_present")
            selected.append(f"{number} AS {axis}_number")
            selected.append(f"COALESCE({value}::text, {null_label}) AS {axis}_label")
            column_names.append(quote_literal(column))

        selected_list = ",\n                        ".join(selected)
        column_list = ", ".join(column_names)

        return f'''(
                    SELECT
                        {selected_list}
                    FROM {table} d
                    LEFT JOIN (
                        SELECT row_id, array_agg(DISTINCT error_type) AS error_types
                        FROM {errors}
                        WHERE column_id IN ({column_list})
                        GROUP BY row_id
                    ) AS row_flags ON row_flags.row_id = d."ID"
                )'''


    def gather_compared_values(self, axes: list) -> str:
        """
        Reduces both tables to their distinct values - value pairs, for a heatmap - each with how many rows hold it,
        how many of those its value is present in, and how many of those each error type flags.
        :arg: axes: (axis name, column) pairs.
        :return: the query for the compared values.
        """

        labels = ", ".join(self._label_columns(axes))

        per_side = []
        for side in SIDES:
            measured = [f"{quote_literal(side)}::text AS side", labels]
            for axis, _ in axes:
                measured.append(f"MIN({axis}_number) AS {axis}_number")
                measured.append(f"COUNT(*) FILTER (WHERE {axis}_present) AS {axis}_present_items")
            measured.append("COUNT(*) AS items")
            for error_type in ERROR_TYPES:
                error_name = quote_literal(error_type)
                flagged = self._flagged_rows_column(error_type)
                measured.append(f"COUNT(*) FILTER (WHERE {error_name} = ANY(error_types)) AS {flagged}")

            measured_list = ",\n                    ".join(measured)
            rows = self.side_rows(side, axes)
            per_side.append(f'''SELECT
                    {measured_list}
                FROM {rows} AS side_rows
                GROUP BY {labels}''')

        both_sides = "\n                UNION ALL\n                ".join(per_side)

        return f'''
            WITH compared_values AS (
                {both_sides}
            )'''


    def gather_axis_extent(self, axis: str) -> str:
        """
        Measures an axis across both tables: how many values are present, how many of them are numbers, and the
        numbers' range.
        :arg: axis: the axis name, "x" or "y".
        :return: the query for the axis extent.
        """

        return f''',
            {axis}_axis_extent AS (
                SELECT
                    SUM({axis}_present_items) AS present_count,
                    COALESCE(SUM(items) FILTER (WHERE {axis}_number IS NOT NULL), 0) AS number_count,
                    MIN({axis}_number) AS low,
                    MAX({axis}_number) AS high
                FROM compared_values
            )'''


    def gather_shared_axis(self, axis: str, bin_count: int) -> str:
        """
        Decides whether an axis is numeric - at least half its present values are numbers - and if so, its bins. A
        constant column still needs a bin with some width to draw, so it gets one bin a unit wide.
        :arg: axis: the axis name, "x" or "y".
        :arg: bin_count: how many bins the numeric part of the axis is split into.
        :return: the query for the shared axis.
        """

        return f''',
            {axis}_axis AS (
                SELECT
                    is_numeric,
                    lo,
                    bins,
                    (hi - lo) / bins AS bin_width
                FROM (
                    SELECT
                        present_count > 0 AND number_count * 2 >= present_count AS is_numeric,
                        CASE WHEN low = high THEN low - 0.5 ELSE low END AS lo,
                        CASE WHEN low = high THEN high + 0.5 ELSE high END AS hi,
                        CASE WHEN low = high THEN 1 ELSE {int(bin_count)} END AS bins
                    FROM {axis}_axis_extent
                ) AS decided
            )'''


    def rank_axis_labels(self, axis: str) -> str:
        """
        Ranks the labels an axis carries - every value on a categorical axis, the values that are not numbers on a
        numeric one - by how many rows carry them, both tables together. Ties are broken by a 64-bit hash of the
        label, then by the label itself should two hashes ever collide: an order that is the same on every request and
        stays cheap when the labels are long free text, which sorting them by name would not.
        :arg: axis: the axis name, "x" or "y".
        :return: the query for the ranked labels.
        """

        return f''',
            {axis}_label_ranks AS (
                SELECT
                    v.{axis}_label AS label,
                    ROW_NUMBER() OVER (
                        ORDER BY SUM(v.items) DESC, hashtextextended(v.{axis}_label, 0), v.{axis}_label COLLATE "C"
                    ) AS popularity
                FROM compared_values v
                CROSS JOIN {axis}_axis a
                WHERE NOT a.is_numeric OR v.{axis}_number IS NULL
                GROUP BY v.{axis}_label
            )'''


    def summarize_axis_labels(self, axis: str) -> str:
        """
        Summarizes an axis' labels: how many there are, and how far down the ranking null sits, if it occurs at all.
        :arg: axis: the axis name, "x" or "y".
        :return: the query for the label summary.
        """

        null_label = quote_literal(NULL_LABEL)

        return f''',
            {axis}_label_summary AS (
                SELECT
                    COUNT(*) AS label_count,
                    MAX(popularity) FILTER (WHERE label = {null_label}) AS null_popularity
                FROM {axis}_label_ranks
            )'''


    def keep_axis_labels(self, axis: str) -> str:
        """
        Keeps every label when there are few enough. Otherwise keeps the most common, null always among them in place
        of the least common kept, and adds the catch-all for the rest.
        :arg: axis: the axis name, "x" or "y".
        :return: the query for the kept labels.
        """

        null_label = quote_literal(NULL_LABEL)
        other_label = quote_literal(OTHER_LABEL)
        # With a catch-all taking the last place, this many of the most common labels are kept
        kept_with_catch_all = MAX_LABELS - 1

        return f''',
            {axis}_axis_labels AS (
                SELECT ranks.label, false AS is_catch_all
                FROM {axis}_label_ranks ranks
                CROSS JOIN {axis}_label_summary summary
                WHERE summary.label_count <= {MAX_LABELS}
                   -- Null is always kept
                   OR ranks.label = {null_label}
                   -- The most common, one fewer when null has to be let in from further down
                   OR ranks.popularity < {kept_with_catch_all}
                   OR (ranks.popularity = {kept_with_catch_all}
                       AND COALESCE(summary.null_popularity, 0) <= {kept_with_catch_all})
                UNION ALL
                SELECT {other_label}, true
                FROM {axis}_label_summary
                WHERE label_count > {MAX_LABELS}
            )'''


    def list_axis_keys(self, axis: str) -> str:
        """
        Lists every bin on an axis in display order: the numeric bins left to right, then the labels sorted by name
        with the catch-all last. The columns are named and filled as the binned values fill them, so the two join
        directly.
        :arg: axis: the axis name, "x" or "y".
        :return: the query for the axis keys.
        """

        return f''',
            {axis}_axis_keys AS (
                SELECT
                    'numeric'::text AS {axis}_type,
                    n AS {axis}_bin_index,
                    ''::text AS {axis}_bin_label,
                    n AS {axis}_position
                FROM {axis}_axis
                CROSS JOIN generate_series(0, {axis}_axis.bins - 1) AS n
                WHERE {axis}_axis.is_numeric
                UNION ALL
                SELECT
                    'categorical',
                    -1,
                    labels.label,
                    -- The labels come after the numeric bins, if there are any
                    COALESCE((SELECT bins FROM {axis}_axis WHERE is_numeric), 0)
                        + ROW_NUMBER() OVER (ORDER BY labels.is_catch_all, labels.label COLLATE "C") - 1
                FROM {axis}_axis_labels labels
            )'''


    def build_axis_scale(self, axis: str) -> str:
        """
        Builds the axis as the front end's hybrid scales take it, the shape DBOperations' histograms send: the numeric
        bins' edges, and the labels in display order.
        :arg: axis: the axis name, "x" or "y".
        :return: the query for the axis scale.
        """

        return f''',
            {axis}_axis_scale AS (
                SELECT json_build_object(
                    'numeric', (
                        SELECT COALESCE(json_agg(
                            json_build_object(
                                'x0', lo + n * bin_width,
                                'x1', lo + (n + 1) * bin_width
                            ) ORDER BY n
                        ), '[]'::json)
                        FROM {axis}_axis
                        CROSS JOIN generate_series(0, bins - 1) AS n
                        WHERE is_numeric
                    ),
                    'categorical', (
                        SELECT COALESCE(json_agg({axis}_bin_label ORDER BY {axis}_position), '[]'::json)
                        FROM {axis}_axis_keys
                        WHERE {axis}_type = 'categorical'
                    )
                ) AS scale
            )'''


    def gather_bins_compare(self, axes: list) -> str:
        """
        Puts each distinct value in its bin on every axis. A number goes in a numeric bin, clamped so the maximum lands
        in the last bin rather than one past it; anything else carries its label, or the catch-all's when its label was
        not kept. The bin is floor((value - lo) / width), the arithmetic the scale's edges are built with, so a value
        sitting on an edge lands in the bin those edges say it belongs to.

        A bin's key is never null, so every join on it is plain equality: a categorical bin's index is -1, and a
        numeric bin's label is empty.
        :arg: axes: (axis name, column) pairs.
        :return: the query for the binned values.
        """

        other_label = quote_literal(OTHER_LABEL)
        selected = ["v.side", "v.items"]
        for error_type in ERROR_TYPES:
            selected.append("v." + self._flagged_rows_column(error_type))
        joins = []

        for axis, _ in axes:
            is_number = f"({axis}_axis.is_numeric AND v.{axis}_number IS NOT NULL)"

            # Clamp bin number to 0..(bins-1) range
            bin_index = f'''LEAST(
                            GREATEST(
                                FLOOR((v.{axis}_number - {axis}_axis.lo) / {axis}_axis.bin_width),
                                0
                            ),
                            {axis}_axis.bins - 1
                        )::int'''

            selected.append(f"v.{axis}_label")
            selected.append(f"CASE WHEN {is_number} THEN 'numeric' ELSE 'categorical' END AS {axis}_type")
            selected.append(f"CASE WHEN {is_number} THEN {bin_index} ELSE -1 END AS {axis}_bin_index")
            selected.append(f'''CASE
                        WHEN {is_number} THEN ''
                        WHEN {axis}_kept.label IS NOT NULL THEN v.{axis}_label
                        ELSE {other_label}
                    END AS {axis}_bin_label''')

            joins.append(f"CROSS JOIN {axis}_axis")
            joins.append(f'''LEFT JOIN {axis}_axis_labels {axis}_kept
                  ON {axis}_kept.label = v.{axis}_label AND NOT {axis}_kept.is_catch_all''')

        selected_list = ",\n                    ".join(selected)
        join_list = "\n                ".join(joins)

        return f''',
            binned_values AS (
                SELECT
                    {selected_list}
                FROM compared_values v
                {join_list}
            )'''


    def count_bin_items(self, axes: list) -> str:
        """
        Counts each side's rows per bin, and how many of them each error type flags.
        :arg: axes: (axis name, column) pairs.
        :return: the query for the item counts.
        """

        bin_columns = ", ".join(self._bin_key_columns(axes))
        sums = ["SUM(items) AS items"]
        for error_type in ERROR_TYPES:
            flagged = self._flagged_rows_column(error_type)
            sums.append(f"SUM({flagged}) AS {flagged}")
        sum_list = ", ".join(sums)

        return f''',
            bin_items AS (
                SELECT side, {bin_columns}, {sum_list}
                FROM binned_values
                GROUP BY side, {bin_columns}
            )'''


    def form_final_compare_bins(self, axes: list) -> str:
        """
        Formulates each side's count object per bin: its rows as "items", plus one entry per error type flagged in
        it - the shape DBOperations' histograms give a bin.
        :arg: axes: (axis name, column) pairs.
        :return: the query for the final bins.
        """

        bin_columns = ", ".join(self._bin_key_columns(axes))

        # Each error type's flagged rows, left out where there are none - jsonb_strip_nulls drops the nulls NULLIF
        # leaves for them
        flag_entries = []
        for error_type in ERROR_TYPES:
            error_name = quote_literal(error_type)
            flagged = self._flagged_rows_column(error_type)
            flag_entries.append(f"{error_name}, NULLIF({flagged}, 0)")
        flag_entry_list = ",\n                        ".join(flag_entries)

        return f''',
            bin_counts AS (
                SELECT
                    side,
                    {bin_columns},
                    jsonb_build_object('items', items) || jsonb_strip_nulls(jsonb_build_object(
                        {flag_entry_list}
                    )) AS counts
                FROM bin_items
            )'''


    def construct_compare_histogram_json(self) -> str:
        """
        Builds the final JSON object for the histogram: every bin on the axis, in display order, with both sides'
        counts - zero items for a side with nothing in the bin.
        :return: the query for the final JSON object.
        """

        axes = [("x", None)]
        x_bin = self._bin_json("keys", "x")
        side_a_bin = self._same_bin("side_a", "keys", axes)
        side_b_bin = self._same_bin("side_b", "keys", axes)
        row_counts = self._row_counts_json()

        return f'''
            SELECT json_build_object(
                'scaleX', (SELECT scale FROM x_axis_scale),
                'bins', (
                    SELECT COALESCE(json_agg(
                        json_build_object(
                            'xType', keys.x_type,
                            'xBin', {x_bin},
                            'a', COALESCE(side_a.counts, jsonb_build_object('items', 0)),
                            'b', COALESCE(side_b.counts, jsonb_build_object('items', 0))
                        ) ORDER BY keys.x_position
                    ), '[]'::json)
                    FROM x_axis_keys keys
                    LEFT JOIN bin_counts side_a ON side_a.side = 'a' AND {side_a_bin}
                    LEFT JOIN bin_counts side_b ON side_b.side = 'b' AND {side_b_bin}
                ),
                {row_counts}
            )'''


    def construct_compare_heatmap_json(self) -> str:
        """
        Builds the final JSON object for the heatmap: every tile holding rows on either side, ordered along the x-axis
        then the y-axis, with both sides' counts.
        :return: the query for the final JSON object.
        """

        axes = [("x", None), ("y", None)]
        tile_columns = ", ".join(self._bin_key_columns(axes))
        x_bin = self._bin_json("tiles", "x")
        y_bin = self._bin_json("tiles", "y")
        x_key = self._same_bin("x_keys", "tiles", [("x", None)])
        y_key = self._same_bin("y_keys", "tiles", [("y", None)])
        side_a_tile = self._same_bin("side_a", "tiles", axes)
        side_b_tile = self._same_bin("side_b", "tiles", axes)
        row_counts = self._row_counts_json()

        return f'''
            SELECT json_build_object(
                'scaleX', (SELECT scale FROM x_axis_scale),
                'scaleY', (SELECT scale FROM y_axis_scale),
                'tiles', (
                    SELECT COALESCE(json_agg(
                        json_build_object(
                            'xType', tiles.x_type,
                            'xBin', {x_bin},
                            'yType', tiles.y_type,
                            'yBin', {y_bin},
                            'a', COALESCE(side_a.counts, jsonb_build_object('items', 0)),
                            'b', COALESCE(side_b.counts, jsonb_build_object('items', 0))
                        ) ORDER BY x_keys.x_position, y_keys.y_position
                    ), '[]'::json)
                    -- The tiles holding rows on either side
                    FROM (SELECT DISTINCT {tile_columns} FROM bin_counts) AS tiles
                    JOIN x_axis_keys x_keys ON {x_key}
                    JOIN y_axis_keys y_keys ON {y_key}
                    LEFT JOIN bin_counts side_a ON side_a.side = 'a' AND {side_a_tile}
                    LEFT JOIN bin_counts side_b ON side_b.side = 'b' AND {side_b_tile}
                ),
                {row_counts}
            )'''


    # -------------------------------------------------------------------------
    # Fragments the steps above share
    # -------------------------------------------------------------------------


    def _flagged_rows_column(self, error_type: str) -> str:
        """The column counting the rows an error type flags, e.g. missing_rows."""
        return f"{error_type}_rows"


    def _label_columns(self, axes: list, prefix: str = "") -> list:
        """
        The columns naming a distinct value: its label on every axis.
        :arg: axes: (axis name, column) pairs.
        :arg: prefix: a table alias to qualify them with, e.g. "side_rows.".
        :return: the column references.
        """

        columns = []
        for axis, _ in axes:
            columns.append(f"{prefix}{axis}_label")
        return columns


    def _bin_key_columns(self, axes: list, prefix: str = "") -> list:
        """
        The columns naming a bin: per axis, its type, its numeric bin and its label.
        :arg: axes: (axis name, column) pairs.
        :arg: prefix: a table alias to qualify them with, e.g. "b.".
        :return: the column references.
        """

        columns = []
        for axis, _ in axes:
            columns.append(f"{prefix}{axis}_type")
            columns.append(f"{prefix}{axis}_bin_index")
            columns.append(f"{prefix}{axis}_bin_label")
        return columns


    def _same_bin(self, left: str, right: str, axes: list) -> str:
        """
        The condition that two relations name the same bin.
        :arg: left: one relation's alias.
        :arg: right: the other's.
        :arg: axes: (axis name, column) pairs.
        :return: a boolean SQL expression.
        """

        conditions = []
        for column in self._bin_key_columns(axes):
            conditions.append(f"{left}.{column} = {right}.{column}")
        return " AND ".join(conditions)


    def _bin_json(self, relation: str, axis: str) -> str:
        """
        A bin as the payload names it: its index when numeric, its label when categorical.
        :arg: relation: the alias holding the bin.
        :arg: axis: the axis name, "x" or "y".
        :return: a JSON SQL expression.
        """

        return f'''CASE
                                WHEN {relation}.{axis}_type = 'numeric' THEN to_json({relation}.{axis}_bin_index)
                                ELSE to_json({relation}.{axis}_bin_label)
                            END'''


    def _row_counts_json(self) -> str:
        """Each side's row count, as the payload's "rows"."""

        return """'rows', json_build_object(
                    'a', (SELECT COALESCE(SUM(items), 0) FROM compared_values WHERE side = 'a'),
                    'b', (SELECT COALESCE(SUM(items), 0) FROM compared_values WHERE side = 'b')
                )"""
