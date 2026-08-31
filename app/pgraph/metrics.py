"""
Quality metrics for pgraph nodes - Nicolas Baret

A node's metrics are computed once, when the node is created, and cached on the GraphNode. Nothing
recomputes them on read: the graph payload serializes the cached object, the attribute summary panel
diffs two cached objects client-side, and the sparklines do arithmetic over cached totals.

The per-column error counts are not queried here. DataProfile already computes them
(_calculate_error_count_dict) and materializes them into dp_<table>, so this module reads them back
through DataProfile.calculate_column_attribute, which carries its own look-up-then-compute fallback.
"""
import json

# The four quality dimensions from the thesis proposal. These names match the error_type values the
# detectors emit and ERROR_TYPES in ui/src/store/errorColors.js, so the front end can color them
# without a translation table.
DIMENSIONS = ("missing", "mismatch", "anomaly", "incomplete")

# Row identifiers are not data attributes, so they are never counted as columns with quality. The
# detectors already exclude them (see get_values_for_df_melt), so they could only ever contribute
# zeroes and dilute the node-level totals.
ID_COLUMNS = ("ID", "Original_ID")


def _parse_error_counts(raw):
    """
    :param raw: what DataProfile returns for 'error_counts' - a JSON string on both the computed and
                the looked-up path, or None when the column has no profile entry
    :return: a dict of {error_type: count}, empty if there is nothing to parse
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class NodeMetrics:
    """
    Error rates for one graph node, at two granularities.

    columns: {column_name: {dimension: rate, ..., "total": rate}} - a rate is the fraction of rows in
             that column carrying that error, which is the same arithmetic get_error_dist uses, so
             these numbers agree with the attribute summary panel's existing badges.
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
        :param data_profile: a DataProfile for the node's table
        :param row_count: the node table's row count, the one thing DataProfile does not provide
        :return: a NodeMetrics for that node
        """
        col_names = [col for col in data_profile.get_col_names() if col not in ID_COLUMNS]

        columns = {}
        summed_counts = {dimension: 0 for dimension in DIMENSIONS}

        for col in col_names:
            counts = _parse_error_counts(
                data_profile.calculate_column_attribute('error_counts', col)
            )

            column_rates = {}
            for dimension in DIMENSIONS:
                count = counts.get(dimension, 0) or 0
                summed_counts[dimension] += count

                # Zero-valued dimensions are left out to keep the serialized graph payload small;
                # the front end treats a missing dimension as zero
                if count:
                    column_rates[dimension] = _rate(count, row_count)

            column_rates["total"] = _rate(sum(counts.values()), row_count)
            columns[col] = column_rates

        column_count = len(col_names)
        cells = row_count * column_count

        totals = {dimension: _rate(summed_counts[dimension], cells) for dimension in DIMENSIONS}
        totals["total"] = _rate(sum(summed_counts.values()), cells)

        return cls(row_count, column_count, totals, columns)

    def dimension(self, name):
        """
        :param name: one of DIMENSIONS, or "total"
        :return: the node-level rate for that dimension, 0.0 if it was never recorded
        """
        return self.totals.get(name, 0.0)

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


def quality_trajectory(ordered_metrics):
    """
    Compute the downstream quality trajectory along one branch.

    Pure arithmetic over an already-ordered list of NodeMetrics - no graph walking and no querying, so
    this is testable without a graph or a database.

        delta_i        = q(n_i+1) - q(n_i)
        contribution_i = delta_i / sum_j |delta_j|

    q is an *error* rate, so higher is worse: a positive delta means errors increased. That is why a
    positive contribution indicates degradation and a negative one indicates improvement.

    When every delta along the branch is zero there is nothing to attribute, so the branch is reported
    as unchanged rather than dividing by zero.

    :param ordered_metrics: NodeMetrics in path order, root-most first
    :return: {dimension: {"values", "deltas", "contributions", "no_change"}}
    """
    trajectory = {}

    for dimension in DIMENSIONS:
        values = [metrics.dimension(dimension) for metrics in ordered_metrics]
        deltas = [values[i + 1] - values[i] for i in range(len(values) - 1)]

        total_absolute_change = sum(abs(delta) for delta in deltas)
        no_change = total_absolute_change == 0

        if no_change:
            contributions = [0.0] * len(deltas)
        else:
            contributions = [delta / total_absolute_change for delta in deltas]

        trajectory[dimension] = {
            "values": values,
            "deltas": deltas,
            "contributions": contributions,
            "no_change": no_change,
        }

    return trajectory


def refresh_node_metrics(table_name):
    """
    Compute a table's metrics and attach them to its GraphNode.

    Raises if the table has no node. Every caller runs right after the node is added to the graph, so
    a miss means the wiring is wrong - and a node that silently keeps null metrics is far harder to
    notice than an exception here.

    :param table_name: the node table to profile
    :return: the NodeMetrics that were attached
    """
    # The session's graph hangs off the app *package*, not the Flask object - see
    # init_pgraph_for_session in service_helpers.py
    import app as app_package
    from app import engine, db_operations
    from app.db_utils.data_profile import DataProfile

    pgraph = app_package.pgraph_for_session
    node = pgraph.node_map[table_name] if pgraph else None
    if node is None:
        raise KeyError(f"no pgraph node for table {table_name!r}, cannot attach metrics")

    metrics = NodeMetrics.from_data_profile(
        DataProfile(table_name, engine),
        db_operations.get_row_count(table_name),
    )
    node.set_metrics(metrics)

    return metrics
