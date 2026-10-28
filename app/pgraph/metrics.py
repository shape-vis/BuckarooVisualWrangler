"""
Quality metrics for pgraph nodes - Nicolas Baret

A node's metrics are computed once, when the node is created, and cached on the GraphNode. Nothing
recomputes them on read: the graph payload serializes the cached object, the attribute summary panel
reads its error rates and default columns from it, and the sparklines do arithmetic over cached totals.

The per-column error counts are not queried here. DataProfile already counts them into dp_<table>, so this
module reads them back from there, in one read of the stored profile.
"""
import json

from app.db_utils.column_types import STRUCTURAL_COLUMNS
from app.db_utils.detector_sql import ERROR_TYPES

# The four quality dimensions from the thesis proposal: exactly the error types the detectors emit, in the order
# ERROR_DIMENSIONS in ui/src/store/errorColors.js lists them, so the front end can color them without a translation
# table.
DIMENSIONS = ERROR_TYPES

# Not data attributes, so never counted as columns with quality: exactly the columns the detectors never flag, which
# could only contribute zeroes and dilute the node-level totals. Drift and the AI's profile skip the same columns.
SKIPPED_COLUMNS = STRUCTURAL_COLUMNS


def parse_json_counts(raw):
    """
    Read a dp_ table's counts column - 'error_counts' or 'category_counts'.
    :param raw: a JSON string; a dict already parsed, as the dp_ table's jsonb columns come back; or None when the
                column has no profile entry
    :return: a dict of {key: count}, empty if there is nothing to parse
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


class NodeMetrics:
    """
    Error rates for one graph node, at two granularities.

    columns: {column_name: {dimension: rate, ..., "total": rate}} - a rate is the fraction of rows in
             that column carrying that error, the share the attribute summary panel's badges show.
    totals:  {dimension: rate, "total": rate} - the fraction of *cells* carrying that error, which is
             the right normalization for a node-level scalar and for a sparkline's y axis.
    """

    def __init__(self, row_count, column_count, totals, columns):
        self.row_count = row_count
        self.column_count = column_count
        self.totals = totals
        self.columns = columns

    @classmethod
    def from_data_profile(cls, data_profile, row_count):
        """
        :param data_profile: a DataProfile for the node's table, its profile already stored
        :param row_count: the node table's row count, the one thing DataProfile does not provide
        :return: a NodeMetrics for that node
        """
        counts_by_column = {}
        for row in data_profile.read_stored_profile(SKIPPED_COLUMNS):
            counts_by_column[row["column_name"]] = parse_json_counts(row["error_counts"])

        # The table's own column order, which the stored profile does not keep
        col_names = []
        for col in data_profile.get_col_names():
            if col not in SKIPPED_COLUMNS:
                col_names.append(col)

        columns = {}
        summed_counts = {}
        for dimension in DIMENSIONS:
            summed_counts[dimension] = 0

        for col in col_names:
            counts = counts_by_column.get(col, {})

            column_rates = {}
            column_total = 0
            for dimension in DIMENSIONS:
                count = counts.get(dimension, 0) or 0
                summed_counts[dimension] += count
                column_total += count

                # Zero-valued dimensions are left out to keep the serialized graph payload small;
                # the front end treats a missing dimension as zero
                if count:
                    column_rates[dimension] = _rate(count, row_count)

            column_rates["total"] = _rate(column_total, row_count)
            columns[col] = column_rates

        column_count = len(col_names)
        cells = row_count * column_count

        totals = {}
        grand_total = 0
        for dimension in DIMENSIONS:
            totals[dimension] = _rate(summed_counts[dimension], cells)
            grand_total += summed_counts[dimension]
        totals["total"] = _rate(grand_total, cells)

        return cls(row_count, column_count, totals, columns)

    def dimension(self, name):
        """
        :param name: one of DIMENSIONS, or "total"
        :return: the node-level rate for that dimension, 0.0 if it was never recorded
        """
        return self.totals.get(name, 0.0)

    def column_error_rates(self):
        """
        Each column's error rates without its total, listing only the columns something flags - the attribute summary
        panel draws a badge per entry.
        :return: {column_name: {dimension: rate}}
        """
        rates = {}
        for column, column_rates in self.columns.items():
            flagged = {}
            for dimension in DIMENSIONS:
                if dimension in column_rates:
                    flagged[dimension] = column_rates[dimension]
            if flagged:
                rates[column] = flagged
        return rates

    def most_flagged_columns(self, count):
        """
        The columns carrying the most error flags, most first, ties broken by name - the attribute summary panel opens
        on these. Only columns something flags are listed.
        :param count: how many columns to return
        :return: the column names
        """
        def most_flagged_first(column):
            return -self.columns[column]["total"], column

        flagged = []
        for column, column_rates in self.columns.items():
            if column_rates["total"] > 0:
                flagged.append(column)
        flagged.sort(key=most_flagged_first)
        return flagged[:count]

    def __json__(self):
        return {
            "row_count": self.row_count,
            "column_count": self.column_count,
            "totals": self.totals,
            "columns": self.columns,
        }


def _rate(count, denominator):
    """Guarded division so an empty table reports zero instead of raising."""
    if not denominator:
        return 0.0
    return count / denominator


def compute_node_metrics(table_name, row_count=None):
    """
    Compute a table's metrics. It needs no graph node, so a node can be measured before it joins the graph - a
    candidate is, while it is being built.

    :param table_name: the node table to profile; its data profile has to be built already
    :param row_count: the table's rows, when the caller has counted them already
    :return: a NodeMetrics for the table
    """
    from app import engine, db_operations
    from app.db_utils.data_profile import DataProfile

    if row_count is None:
        row_count = db_operations.get_row_count(table_name)

    return NodeMetrics.from_data_profile(DataProfile(table_name, engine), row_count)
