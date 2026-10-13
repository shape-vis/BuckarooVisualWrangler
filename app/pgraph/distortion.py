"""
Distortion: how far a node's data has drifted from root - September 15, 2026

The four error metrics in metrics.py all improve as a wrangle deletes or overwrites more, so on their own
they reward over-cleaning. They also cannot see a column that no operation touched shifting because the
rows removed from it were not a random sample. Distortion is the opposing axis: per column, how far the
node's distribution has moved from root's.

    numeric      W1(root, node) / IQR(root)        "moved by X IQRs"
    categorical  1/2 * sum_c |p_root - p_node|     "this fraction of the rows changed category"

It is always measured against root, never the parent. Measured step by step, drift that builds up over many
small edits would vanish, and nodes on different branches would have nothing in common to be measured
against. Root is the dirty data rather than the truth, so drift is a cost to be spent knowingly, not an
error - it is kept apart from the error metrics everywhere and never folded into their totals.

In a categorical column, missing cells - by the Missing detector's own rule, so the two panels always agree
about which cells are missing - are a category of their own, labelled null as churn labels them. Deleting the
rows with missing cells and filling those cells both move rows out of that category, so both register in
full, and a node identical to root still scores zero. A numeric column leaves its missing cells out, since a
null has no place on the number line W1 is measured along.

The spec is the fidelity proposal's docs 01-03. The rows never leave the database: DriftSQL
(app/db_utils/drift_sql.py) reduces both states to a handful of numbers per column, and everything here is plain
arithmetic over those, so it is testable without one.
"""
import threading
from functools import partial

import numpy as np

from app.db_utils.compare_sql import MAX_LABELS, NULL_LABEL, OTHER_LABEL
from app.db_utils.drift_sql import REMOVED_LABEL, DriftSQL
from app.pgraph.metrics import ID_COLUMNS
from app.server_utils.workers import run_all

NUMERIC = "numeric"
CATEGORICAL = "categorical"
STATS = {NUMERIC: "W1/IQR", CATEGORICAL: "TVD"}

# Not data attributes: the row identifiers, and the pandas index columns DataProfile.get_col_names also
# skips. Leaving them out keeps drift over the same columns the error metrics cover.
SKIPPED_COLUMNS = (*ID_COLUMNS, "index", "level_0")

# The grid the annotation reads a numeric column's movement off. It oversamples the tails, because that is
# where a delete of outliers moves mass - a grid of deciles understates such a change badly.
TAIL_GRID = (0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)

# Below this many values on either side, W1 and TVD are too noisy to lean on
LOW_CONFIDENCE_N = 30

# A share-change table names this many categories and sums the rest into one row
TOP_CHANGES = 8

# How many of the categories folded into the catch-all are named back, for the panel to list and offer
OTHER_LISTED = 200
# The most bands a Sankey will draw when the panel names the categories itself
MAX_KEPT = 100

# Both Pareto axes are rounded to this many places, so float noise cannot make equal nodes dominate
PARETO_PRECISION = 6

# The ridgeline's smoothing, as gaussian_kde's factor on root, and how many points each curve has. The
# points are dense because the compare panel zooms into a slice of the grid in the browser, and a zoomed
# window still needs enough of them to draw a smooth curve.
KDE_FACTOR = 0.30
KDE_POINTS = 1000

# The ridgeline's curves are summed over this many distinct values at a time, which bounds the memory one sum takes
DENSITY_CHUNK = 2000


class RowIdentityError(ValueError):
    """A node holds a row that root does not - see check_row_identity."""


# ── Column kinds ─────────────────────────────────────────────────────────────

def column_kind(col_types, column):
    """
    Whether a column's drift is measured as numeric or categorical. This is DataProfile's rule
    (is_valid_attribute_for_column), so drift and the attribute summary always agree about a column: text
    columns, pure or mostly text, are categorical, and everything else is numeric.

    :param col_types: root's ColumnTypes - kinds are decided on root and held for every node, so a column
                      cannot switch statistics part way down a branch
    :param column: the column
    :return: NUMERIC or CATEGORICAL
    """
    if col_types.is_categorical_col(column) or col_types.is_categorical_mixed_col(column):
        return CATEGORICAL
    return NUMERIC


def column_kinds(col_types, columns):
    """{column: kind} for every data column, the structural ones left out."""
    return {column: column_kind(col_types, column) for column in columns if column not in SKIPPED_COLUMNS}


# ── One column ───────────────────────────────────────────────────────────────

def _scale(q1, q3, std):
    """
    What a numeric drift is measured in: root's IQR. A column whose middle half is a single value has no IQR, so its
    standard deviation stands in; a column that is one value throughout has neither.

    :return: the scale, or None for a constant column
    """
    if q3 > q1:
        return float(q3 - q1)
    if std is not None and std > 0:
        return float(std)
    return None


def _result(kind, value, n_root, n_node, reason=None):
    """
    One column's drift. A column with nothing honest to report carries a reason instead of a value - never
    a zero, which would read as "unchanged".
    """
    # Counts can arrive as numpy integers, which Flask cannot encode, and which would make the flag below a numpy bool
    n_root, n_node = int(n_root), int(n_node)
    return {
        "value": None if reason else float(value),
        "stat": STATS.get(kind),
        "kind": kind,
        "n_root": n_root,
        "n_node": n_node,
        "degenerate": reason is not None,
        "reason": reason,
        "low_confidence": reason is None and min(n_root, n_node) < LOW_CONFIDENCE_N,
    }


def column_distortion(measured, kind):
    """
    How far one column has drifted from root.

    :param measured: the column's drift inputs, as DriftSQL.generate_numeric_drift or generate_categorical_drift
                     gives them
    :param kind: NUMERIC or CATEGORICAL, decided on root
    :return: {"value", "stat", "kind", "n_root", "n_node", "degenerate", "reason", "low_confidence"}
    """
    n_root = measured["n_reference"]
    n_node = measured["n_node"]

    if kind == NUMERIC:
        if n_node == 0:
            return _result(kind, None, n_root, 0, "no values")
        if n_root < 2 or n_node < 2:
            return _result(kind, None, n_root, n_node, "too few values")
        scale = _scale(measured["q1"], measured["q3"], measured["std"])
        if scale is None:
            return _result(kind, None, n_root, n_node, "constant column")
        return _result(kind, measured["wasserstein"] / scale, n_root, n_node)

    if n_root == 0 or n_node == 0:
        return _result(kind, None, n_root, n_node, "no values")
    return _result(kind, measured["tvd"], n_root, n_node)


# ── Measuring, one column per query ──────────────────────────────────────────

def measure_columns(drift):
    """
    Every column's drift inputs, in the shape node_distortion reads: root's data columns, then any column only the
    node has. Each column the two states share is measured by its own query, and each table's present cells by one
    more, all of them at once on the query pool - a query per column is what lets them run side by side.

    :param drift: a DriftSQL between root and the node
    :return: one object per column - its plan entry ({"column", "kind", "in_node"}), its present cells on either
             side, and, for a shared column, its measurement
    """
    plan = drift.column_plan()

    tasks = [partial(drift.generate_present_cells, "reference"), partial(drift.generate_present_cells, "node")]
    for entry in plan:
        if entry["kind"] is None or not entry["in_node"]:
            continue
        if entry["kind"] == NUMERIC:
            tasks.append(partial(drift.generate_numeric_drift, entry["column"]))
        else:
            tasks.append(partial(drift.generate_categorical_drift, entry["column"]))

    results = run_all(tasks)
    present_reference = results[0]
    present_node = results[1]

    measurements = {}
    for measured in results[2:]:
        measurements[measured["column"]] = measured

    column_drift = []
    for entry in plan:
        column = entry["column"]
        measured = {**entry,
                    "present_reference": present_reference.get(column, 0),
                    "present_node": present_node.get(column, 0)}
        measured.update(measurements.get(column, {}))
        column_drift.append(measured)
    return column_drift


def measure_edit_facts(drift, columns):
    """
    The edit facts between two states: their rows matched by one query, and each shared column's changed cells
    counted by a query of its own, all of them at once on the query pool.

    :param drift: a DriftSQL between the two states
    :param columns: the data columns to count changed cells in. Only those both states hold are counted.
    :return: {"rows_reference", "rows_removed", "rows_unknown", "first_unknown_id", "cells_changed": {column: n}}
    """
    shared = []
    for column in columns:
        if drift.is_shared(column):
            shared.append(column)

    tasks = [drift.generate_row_counts]
    for column in shared:
        tasks.append(partial(drift.generate_changed_cells, column))

    results = run_all(tasks)

    facts = dict(results[0])
    facts["cells_changed"] = dict(zip(shared, results[1:]))
    return facts


# ── One node ─────────────────────────────────────────────────────────────────

def check_row_identity(facts):
    """
    Every wrangle edits cells or deletes rows, and none creates one - so a node's rows are always a subset
    of root's, matched by "ID". The Sankey's removed sink and the removal rates both lean on that. A node that broke it
    would make every one of them wrong without saying so, so this raises instead.

    :param facts: the edit facts, as measure_edit_facts gives them
    """
    unknown = facts["rows_unknown"]
    if unknown:
        raise RowIdentityError(f"the node holds {unknown} row(s) that root does not, e.g. ID {facts['first_unknown_id']}")


def summarize(columns, weights=None):
    """
    A node's single number: the mean of its columns' drift. Columns with no value are left out rather than
    counted as unchanged.

    A numeric column's W1/IQR goes in uncapped, though it has no ceiling. The number is tracked along a
    branch to see how bad drift is getting, and a ceiling would hide every shift past it - a column moved by
    ten IQRs would read the same as one moved by one. The price is that one wildly shifted column can
    dominate the mean, which its own value in the column breakdown shows.

    :param columns: {column: result}, as column_distortion returns them
    :param weights: {column: weight}, or None for every column counting the same - a reserved decision in
                    doc 02, so it stays a parameter rather than being settled here
    :return: {"overall"} - None when no column could be scored
    """
    total = weight_sum = 0.0
    for column, result in columns.items():
        if result["degenerate"]:
            continue
        weight = 1.0 if weights is None else weights.get(column, 1.0)
        total += weight * result["value"]
        weight_sum += weight
    return {"overall": total / weight_sum if weight_sum else None}


def node_distortion(column_drift, weights=None):
    """
    Every column's drift from root, and the node's single number.

    :param column_drift: every column's drift inputs, as measure_columns gives them - root's data columns, then any
                         column only the node has
    :param weights: {column: weight}, or None for every column counting the same
    :return: {"overall", "columns", "structural"} - structural lists columns the node dropped or gained,
             which have no drift and are reported as changes to the table's shape instead
    """
    columns = {}
    removed = []
    added = []

    for measured in column_drift:
        column = measured["column"]
        kind = measured["kind"]
        if column in SKIPPED_COLUMNS:
            continue

        if kind is None:
            added.append(column)
            columns[column] = _result(None, None, 0, measured["present_node"], "column added")
        elif not measured["in_node"]:
            removed.append(column)
            columns[column] = _result(kind, None, measured["present_reference"], 0, "column removed")
        else:
            columns[column] = column_distortion(measured, kind)

    return {**summarize(columns, weights), "columns": columns,
            "structural": {"removed": removed, "added": added}}


def root_distortion(kinds, present_cells, row_count):
    """
    Root against itself: exactly zero on every column, without measuring anything. A categorical column counts its
    missing cells, as column_distortion does; a numeric column counts its present cells.

    :param kinds: root's data columns' kinds
    :param present_cells: root's non-null cells per column, as DriftSQL.generate_present_cells gives them
    :param row_count: root's rows
    """
    columns = {}
    for column, kind in kinds.items():
        if kind == CATEGORICAL:
            present = row_count
        else:
            present = present_cells.get(column, 0)
        columns[column] = _result(kind, 0.0, present, present)
    return {"overall": 0.0, "columns": columns, "structural": {"removed": [], "added": []}}


def edit_facts(facts):
    """
    What the wrangles between root and this node did, read off the data: how many of root's rows are gone,
    and per column how many of the surviving cells now hold a different value. The detail views and the
    annotations are keyed on these rather than on operation names, so a new kind of repair needs no change
    in any of them.

    :param facts: the edit facts, as measure_edit_facts gives them
    :return: {"rows_root", "rows_removed", "cells_changed": {column: count}}
    """
    return {"rows_root": facts["rows_reference"],
            "rows_removed": facts["rows_removed"],
            "cells_changed": dict(facts["cells_changed"])}


# ── Detail: what the drill-down views draw ───────────────────────────────────

def _share_row(label, root_pct, node_pct, change_pct):
    return {"category": str(label), "root_pct": float(root_pct), "node_pct": float(node_pct),
            "change_pct": float(change_pct)}


def numeric_column_detail(numeric_detail, grid=TAIL_GRID):
    """
    The breakdown behind a numeric column's number: the node's quantiles against root's on the grid, and the shift
    between them in root IQRs. The shift at q is the integrand of W1 at q, so the shifts and the number measure the
    same thing - but no finite grid averages back to the number, and nothing said from this may suggest one does.

    :param numeric_detail: both states' measurements, as DriftSQL.generate_numeric_detail gives them for the grid
    :return: {"kind", "grid", "root", "node", "shift"}, or None when the column has nothing to break down
    """
    reference = numeric_detail.get("reference")
    node = numeric_detail.get("node")
    if reference is None or node is None:
        return None

    scale = None
    if reference["n"] >= 2:
        scale = _scale(reference["q1"], reference["q3"], reference["std"])
    if scale is None or node["n"] < 2:
        return None

    root_quantiles = np.asarray(reference["quantiles"], dtype=float)
    node_quantiles = np.asarray(node["quantiles"], dtype=float)
    shift = (node_quantiles - root_quantiles) / scale
    return {"kind": NUMERIC, "grid": list(grid), "root": root_quantiles.tolist(), "node": node_quantiles.tolist(),
            "shift": shift.tolist()}


def categorical_column_detail(category_counts):
    """
    The breakdown behind a categorical column's number: each category's share of root and of the node in percent,
    the TOP_CHANGES categories that moved most by name and the rest summed into one row.

    :param category_counts: each category's count in both states, as DriftSQL.generate_category_shares gives them
    :return: {"kind", "categories", "truncated_n"}, categories as {"category", "root_pct", "node_pct",
             "change_pct"}; None when the column has nothing to break down
    """
    root_total = 0
    node_total = 0
    for counted in category_counts:
        root_total += counted["reference_count"]
        node_total += counted["node_count"]
    if root_total == 0 or node_total == 0:
        return None

    # Each category's share of either state, and the node's change, in percent
    shares = {}
    for counted in category_counts:
        root_share = counted["reference_count"] / root_total
        node_share = counted["node_count"] / node_total
        shares[counted["label"]] = (root_share * 100, node_share * 100, (node_share - root_share) * 100)

    # Largest movers first, ties broken by name so the table is the same on every render
    def largest_move_first(label):
        change_pct = shares[label][2]
        return -abs(change_pct), str(label)

    order = sorted(shares, key=largest_move_first)

    rows = []
    for label in order[:TOP_CHANGES]:
        root_pct, node_pct, change_pct = shares[label]
        rows.append(_share_row(label, root_pct, node_pct, change_pct))

    rest = order[TOP_CHANGES:]
    if rest:
        rest_root = rest_node = rest_change = 0.0
        for label in rest:
            root_pct, node_pct, change_pct = shares[label]
            rest_root += root_pct
            rest_node += node_pct
            rest_change += change_pct
        rows.append(_share_row(OTHER_LABEL, rest_root, rest_node, rest_change))

    return {"kind": CATEGORICAL, "categories": rows, "truncated_n": len(rest)}


def _smoothed(value_masses, grid, bandwidth):
    """
    A sum of Gaussian kernels on the grid, one per value, each weighted by how many rows hold the value - exactly
    what a Gaussian KDE of every row sums, without repeating a value once per row.

    :param value_masses: {"numbers", "occurrences"}, as DriftSQL.generate_value_masses gives them
    :param grid: where to evaluate the sum
    :param bandwidth: the kernels' standard deviation
    :return: the sum at each grid point - the KDE's density, times the number of rows
    """
    numbers = np.asarray(value_masses["numbers"], dtype=float)
    occurrences = np.asarray(value_masses["occurrences"], dtype=float)
    grid = np.asarray(grid, dtype=float)

    curve = np.zeros(len(grid))
    for start in range(0, len(numbers), DENSITY_CHUNK):
        chunk_numbers = numbers[start:start + DENSITY_CHUNK]
        chunk_occurrences = occurrences[start:start + DENSITY_CHUNK]
        # One row per grid point, one column per value: how many bandwidths apart they are
        distances = (grid[:, np.newaxis] - chunk_numbers[np.newaxis, :]) / bandwidth
        kernels = np.exp(-0.5 * distances ** 2)
        curve += kernels @ chunk_occurrences

    return curve / (bandwidth * np.sqrt(2 * np.pi))


def root_density_params(value_masses, factor=KDE_FACTOR, points=KDE_POINTS):
    """
    Fit the ridgeline's smoothing on root, once per column.

    Every row of a ridgeline has to be smoothed identically, or the differences between rows are partly the
    smoother's doing (doc 03 §3.6b). So the bandwidth is fitted here, on root, in the column's own units, and
    node_density reuses it for every node. It is the factor times root's sample standard deviation - the bandwidth
    gaussian_kde fits for a scalar factor.

    :param value_masses: root's distinct numbers and their counts, as DriftSQL.generate_value_masses gives them
    :return: {"bandwidth", "grid", "root_curve", "n_root"}, or None when root cannot be smoothed
    """
    numbers = np.asarray(value_masses["numbers"], dtype=float)
    occurrences = np.asarray(value_masses["occurrences"], dtype=float)
    n_root = int(occurrences.sum())
    # Fewer than two values, or one value throughout, has no spread to smooth with
    if n_root < 2 or numbers.min() == numbers.max():
        return None

    mean = (occurrences * numbers).sum() / n_root
    variance = (occurrences * (numbers - mean) ** 2).sum() / (n_root - 1)
    bandwidth = float(factor * np.sqrt(variance))

    grid = np.linspace(numbers.min() - 3 * bandwidth, numbers.max() + 3 * bandwidth, points)
    root_curve = _smoothed(value_masses, grid, bandwidth) / n_root
    return {"bandwidth": bandwidth, "grid": grid.tolist(), "root_curve": root_curve.tolist(), "n_root": n_root}


def node_density(value_masses, params):
    """
    One node's curve on root's grid, smoothed with root's bandwidth.

    The curve is scaled by the node's share of root's values rather than normalised to an area of one: the rows share
    one vertical scale, and a curve normalised on its own would make a node that lost half its rows look unchanged
    (§3.6b). Where nothing moved, it lies on root's.

    :param value_masses: the node's distinct numbers and their counts
    :return: the curve, or None when the node has too few values to draw
    """
    n_node = int(np.asarray(value_masses["occurrences"], dtype=float).sum())
    if params is None or n_node < 2:
        return None
    curve = _smoothed(value_masses, params["grid"], params["bandwidth"]) / params["n_root"]
    return curve.tolist()


def category_flows(pairs, limit=MAX_LABELS, keep=None):
    """
    Where each of the earlier state's rows sits in the later one, for one categorical column: in a category,
    or in the removed sink when the later state no longer has the row. Rows are matched by "ID", and given
    the row-identity invariant a failed match can only mean a delete.

    This is the Sankey's data, and churn is the number it decomposes. TVD is the net change in shares, so
    five rows moving each way between two categories moves ten rows and leaves TVD at zero - the two answer
    different questions, and both are reported.

    :param pairs: how many rows take each path, as DriftSQL.generate_category_flows gives them - root to the node,
                  for a node's Sankey - every category listed as itself
    :param limit: the most categories kept, the compare axes' limit by default. A column with more keeps its
                  most common in the earlier state, and null whenever it occurs, as those axes do, and folds the
                  rest into OTHER_LABEL.
    :param keep: the categories to keep as themselves, naming them outright instead of by the limit - the
                 panel sends this when the reader pulls one back out of the catch-all
    :return: {"flows": [{"source", "target", "rows"}], "sources", "targets", "churn", "removal_rates",
              "categories", "other"}. Sources and targets run from the most common category down, so a plot
              can open on the top few. "other" names what the catch-all holds, so the reader can look inside
              it and take a category back out. churn and the category count are over the unfolded labels.
    """
    # How many rows start in each category, and how many end somewhere else
    source_rows = {}
    total_rows = 0
    moved_rows = 0
    for pair in pairs:
        source_rows[pair["source"]] = source_rows.get(pair["source"], 0) + pair["rows"]
        total_rows += pair["rows"]
        if pair["source"] != pair["target"]:
            moved_rows += pair["rows"]
    churn = moved_rows / total_rows if total_rows else 0.0

    # The categories most common first, ties broken by name
    def most_common_first(label):
        return -source_rows[label], label

    by_count = sorted(source_rows, key=most_common_first)

    if keep is not None:
        # The panel named them, so size does not come into it - only the order, which stays by count
        named = set(keep)
        kept = []
        for label in by_count:
            if label in named:
                kept.append(label)
        kept = kept[:MAX_KEPT]
    else:
        kept = list(by_count)
        if len(kept) > limit:
            kept = kept[:limit - 1]
            # Null is the rarest kept, so it takes the last place and the order still runs by count
            if NULL_LABEL in source_rows and NULL_LABEL not in kept:
                kept[-1] = NULL_LABEL

    # What the catch-all holds, biggest first: the panel lists these and offers them back
    kept_set = set(kept)
    tail = []
    for label in by_count:
        if label not in kept_set:
            tail.append(label)

    other = None
    if tail:
        listed = []
        tail_rows = 0
        for label in tail:
            tail_rows += source_rows[label]
        for label in tail[:OTHER_LISTED]:
            listed.append({"category": str(label), "rows": int(source_rows[label])})
        other = {"categories": listed, "more": max(0, len(tail) - OTHER_LISTED), "rows": int(tail_rows)}

    def fold(label):
        if label in kept_set or label == REMOVED_LABEL:
            return label
        return OTHER_LABEL

    # The flows between the folded categories, and each folded source's rows and removed rows
    folded_flows = {}
    folded_source_rows = {}
    folded_removed_rows = {}
    for pair in pairs:
        source = fold(pair["source"])
        target = fold(pair["target"])
        folded_flows[(source, target)] = folded_flows.get((source, target), 0) + pair["rows"]
        folded_source_rows[source] = folded_source_rows.get(source, 0) + pair["rows"]
        if target == REMOVED_LABEL:
            folded_removed_rows[source] = folded_removed_rows.get(source, 0) + pair["rows"]

    flows = []
    present_targets = set()
    for (source, target), rows in folded_flows.items():
        flows.append({"source": source, "target": target, "rows": int(rows)})
        present_targets.add(target)

    order = kept + [OTHER_LABEL]
    sources = []
    targets = []
    for label in order:
        if label in folded_source_rows:
            sources.append(label)
        if label in present_targets:
            targets.append(label)
    if REMOVED_LABEL in present_targets:
        targets.append(REMOVED_LABEL)

    removal_rates = {}
    for source in sorted(folded_source_rows):
        removed = folded_removed_rows.get(source, 0)
        removal_rates[str(source)] = float(removed / folded_source_rows[source])

    return {
        "flows": flows,
        "sources": sources,
        "targets": targets,
        "churn": float(churn),
        "removal_rates": removal_rates,
        "categories": len(source_rows),
        "other": other,
    }


def acted_on_column(path_nodes, column):
    """
    Whether any step along a path acted on this column. Read off each step's own record of the columns it
    acted on rather than its operation's name, so a new kind of repair needs no change here.

    :param path_nodes: GraphNodes from root down to the node
    """
    return any(column in child.wrangle_summary()["columns"] for child in path_nodes[1:])


# ── Across nodes ─────────────────────────────────────────────────────────────

def distortion_trajectory(ordered):
    """
    The node number along a branch. Every value is measured against root, and each step's delta is the
    difference of two of them - not a fresh parent-to-child measurement, which is a different number and
    would hide drift that builds up over many small steps (doc 01 §1.4).

    :param ordered: each node's distortion (or None), root-most first
    :return: {"values", "deltas"}
    """
    values = [distortion.get("overall") if distortion else None for distortion in ordered]
    deltas = [None if a is None or b is None else b - a for a, b in zip(values, values[1:])]
    return {"values": values, "deltas": deltas}


def pareto_frontier(scores):
    """
    Which nodes are beaten outright. Lower is better on both axes, and node Y is dominated by X when X is
    no worse on both and strictly better on one. A dominated node is never the right choice, whatever the
    analyst values, so it can be ruled out without asking. The rest form the frontier, which this declines
    to rank - analysts who value keeping every row and analysts who value clean flags sit at opposite ends.

    Both axes are rounded first, or float noise makes equal nodes dominate each other. When several nodes
    dominate Y, the one named is the lowest id, so the explanation does not change between renders.

    :param scores: [{"id", "error", "distortion"}]
    :return: (frontier ids, {dominated id: dominating id}), in id order
    """
    ranked = sorted((score["id"], round(score["error"], PARETO_PRECISION),
                     round(score["distortion"], PARETO_PRECISION)) for score in scores)
    dominated = {}
    for y_id, y_error, y_drift in ranked:
        for x_id, x_error, x_drift in ranked:
            if x_error <= y_error and x_drift <= y_drift and (x_error < y_error or x_drift < y_drift):
                dominated[y_id] = x_id
                break
    return [node_id for node_id, _, _ in ranked if node_id not in dominated], dominated


# ── Annotations ──────────────────────────────────────────────────────────────

def _ordinal(quantile):
    n = int(round(quantile * 100))
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _sentences(record):
    """One sentence per fact, each read straight off the record."""
    column, sentences = record["column"], []

    if record["cells_changed"]:
        sentences.append(f"{record['cells_changed']:,} of {record['rows_root']:,} values in {column} "
                         f"were changed.")
    if record["rows_removed"]:
        sentences.append(f"{record['rows_removed']:,} of {record['rows_root']:,} rows were removed.")
        if not record["acted_on"]:
            sentences.append(f"No operation acted on {column}; it changed only through rows removed "
                             f"for other columns.")

    shift = record.get("largest_shift")
    if shift and shift["shift"]:
        way = "up" if shift["shift"] > 0 else "down"
        sentences.append(f"The largest move is at the {_ordinal(shift['quantile'])} percentile: {way} "
                         f"{abs(shift['shift']):.3f} IQR.")
        if record["direction"] != "both":
            sentences.append(f"No quantile shown moved {'down' if record['direction'] == 'up' else 'up'}.")

    gained, lost = record.get("gained"), record.get("lost")
    if gained and lost and gained["change_pct"] > 0 > lost["change_pct"]:
        sentences.append(f"{gained['category']} gained {gained['change_pct']:.2f} points of share; "
                         f"{lost['category']} lost {abs(lost['change_pct']):.2f}.")

    highest, lowest = record.get("removal_highest"), record.get("removal_lowest")
    if highest and lowest and highest[1] > lowest[1]:
        sentences.append(f"{highest[0]} rows were removed at {highest[1]:.1%}, against {lowest[1]:.1%} "
                         f"of {lowest[0]}.")

    if record["drift"] is not None:
        sentences.append(f"Drift {record['drift']:.3f} ({record['stat']}).")
    if "churn" in record:
        sentences.append(f"{record['churn']:.1%} of rows changed category or were removed (churn).")
    return sentences


def annotation(column, result, facts, detail=None, acted_on=False, flows=None):
    """
    Plain sentences explaining one column's drift, and the record every one of them is built from.

    Only two kinds of fact are stated (doc 03 §3.8): what the provenance records - which rows were removed,
    which cells changed, whether any step acted on the column - and what was measured - the drift, where it
    moved, the removal rates. Never why. "Shifted because younger developers earn less"
    asserts a mechanism nothing measured, and in a tool for auditing a wrangle an invented explanation is
    worse than none. Every sentence reads fields of the record. If an LLM is ever asked to phrase these
    instead, it gets this record and nothing else, and every clause it writes has to trace to a field here.

    :return: {"record", "sentences"}
    """
    record = {
        "column": column,
        "kind": result["kind"],
        "stat": result["stat"],
        "drift": result["value"],
        "rows_root": facts["rows_root"],
        "rows_removed": facts["rows_removed"],
        "cells_changed": facts["cells_changed"].get(column, 0),
        "acted_on": acted_on,
    }

    if detail and detail["kind"] == NUMERIC:
        shifts = detail["shift"]
        largest = max(range(len(shifts)), key=lambda i: abs(shifts[i]))
        record["largest_shift"] = {"quantile": detail["grid"][largest], "shift": shifts[largest]}
        record["direction"] = ("up" if all(s >= 0 for s in shifts)
                               else "down" if all(s <= 0 for s in shifts) else "both")
    elif detail and detail["kind"] == CATEGORICAL:
        named = [row for row in detail["categories"] if row["category"] != OTHER_LABEL]
        if named:
            record["gained"] = max(named, key=lambda row: row["change_pct"])
            record["lost"] = min(named, key=lambda row: row["change_pct"])

    if flows:
        record["churn"] = flows["churn"]
        rates = {label: rate for label, rate in flows["removal_rates"].items() if label != OTHER_LABEL}
        if facts["rows_removed"] and len(rates) > 1:
            record["removal_highest"] = max(rates.items(), key=lambda item: item[1])
            record["removal_lowest"] = min(rates.items(), key=lambda item: item[1])

    return {"record": record, "sentences": _sentences(record)}


# ── Reading from the session ─────────────────────────────────────────────────

# Root's data columns' kinds, decided once per root. Every node's drift is measured against them, and root's table
# never changes; a new upload brings a new root.
_root_kinds = {"table": None, "kinds": None}

# Ridgeline curves: each reference's fit per (reference table, column), and each node's curve per (reference table,
# node table, column)
_density_cache = {}

# Node builds run on several threads at once, so the caches above are only changed under this
_cache_lock = threading.Lock()


def root_kinds(root_table, reload=False):
    """
    Root's data columns' kinds, decided once per root.

    :param reload: decide them again even if they are cached - a session's start asks for this, since tests and
                   re-uploads can reuse a table name for different data
    :return: {column: kind}
    """
    with _cache_lock:
        if not reload and _root_kinds["table"] == root_table:
            return _root_kinds["kinds"]

    from app import engine
    from app.db_utils.column_types import ColumnTypes

    col_types = ColumnTypes.for_table(root_table, engine)
    kinds = column_kinds(col_types, col_types.column_names)

    with _cache_lock:
        _root_kinds.update(table=root_table, kinds=kinds)
        _density_cache.clear()
    return kinds


def compute_node_distortion(table_name, root_table):
    """
    Measure a node's drift from root, with the facts about what its wrangles did. It needs no graph node, so a node
    can be measured before it joins the graph. Its columns are measured at the same time on the query pool, so this
    must not itself run there - see app/server_utils/workers.py.

    :param table_name: the node's table
    :param root_table: root's table
    :return: the distortion, facts included
    """
    from app import engine, db_operations

    # Root's own measurement runs once, as a session starts, so that is where stale cached kinds are let go
    is_root = table_name == root_table
    kinds = root_kinds(root_table, reload=is_root)

    if is_root:
        row_count = db_operations.get_row_count(root_table)
        present_cells = DriftSQL(engine, root_table, root_table, kinds).generate_present_cells("reference")
        distortion = root_distortion(kinds, present_cells, row_count)
        facts = {"rows_root": row_count, "rows_removed": 0, "cells_changed": {column: 0 for column in kinds}}
    else:
        drift = DriftSQL(engine, root_table, table_name, kinds)
        measured_facts = measure_edit_facts(drift, list(kinds))
        check_row_identity(measured_facts)
        distortion = node_distortion(measure_columns(drift))
        facts = edit_facts(measured_facts)

    return {**distortion, "facts": facts}


def refresh_node_distortion(table_name):
    """
    Compute a node's drift from root and attach it to its GraphNode, with the facts about what its wrangles
    did. Called from refresh_node_metrics, so every path that creates a node gets it, once, when the node is made.

    :return: the distortion that was attached
    """
    import app as app_package

    pgraph = app_package.pgraph_for_session
    node = pgraph.node_map[table_name] if pgraph else None
    if node is None:
        raise KeyError(f"no pgraph node for table {table_name!r}, cannot attach distortion")

    node.set_distortion(compute_node_distortion(table_name, pgraph.root_node))
    return node.distortion


def _node_distortion_of(pgraph, node_table):
    """A node's distortion, computed now if the node somehow predates it."""
    node = pgraph.node_map[node_table]
    if node.distortion is None:
        refresh_node_distortion(node_table)
    return node.distortion


def _density(drift, base_table, node_table, column):
    """
    The ridgeline for one node and column: the reference's curve and the node's, both on the grid fitted to the
    reference. Both are cached - the reference's fit per reference, the node's curve per reference and node.

    :return: {"grid", "bandwidth", "root", "node"}, or None when the reference cannot be smoothed
    """
    params_key = ("params", base_table, column)
    curve_key = ("curve", base_table, node_table, column)

    with _cache_lock:
        params = _density_cache.get(params_key, False)
    if params is False:
        params = root_density_params(drift.generate_value_masses("reference", column))
        with _cache_lock:
            _density_cache[params_key] = params
    if params is None:
        return None

    with _cache_lock:
        curve = _density_cache.get(curve_key, False)
    if curve is False:
        curve = node_density(drift.generate_value_masses("node", column), params)
        with _cache_lock:
            _density_cache[curve_key] = curve

    return {"grid": params["grid"], "bandwidth": params["bandwidth"], "root": params["root_curve"], "node": curve}


def drift_detail(pgraph, node_table, column, keep=None, base_table=None):
    """
    Everything the compare panel's Drift views draw for one node and one column: the ridgeline curves or the
    Sankey flows, and the annotation. Read-only.

    The reference is root unless a base is named. A base is one of the node's ancestors - the two selections'
    common ancestor, when the panel is asked to leave out the history they share - and every number here is
    then measured from it exactly as it would be from root: the node's rows are a subset of any ancestor's,
    for the same reason they are of root's. The payload's "root" keys (rows_root, density.root) name that
    reference state, whichever it is.

    :param keep: for a categorical column, the categories to keep out of the catch-all - see category_flows
    :param base_table: the ancestor to measure from, or None for root. The route checks it is an ancestor.
    :return: the payload, with "density", "flows" and "annotation" None when the column was dropped
    """
    from app import engine

    root_table = pgraph.root_node
    base_table = base_table or root_table
    kinds = root_kinds(root_table)
    if column not in kinds:
        raise ValueError(f"{column!r} is not a data column of the root table")

    # Kinds stay root's for every reference, so a column cannot switch statistics with the reference
    kind = kinds[column]
    distortion = _node_distortion_of(pgraph, node_table)
    dropped = (column in distortion["structural"]["removed"]
               or column in _node_distortion_of(pgraph, base_table)["structural"]["removed"])

    drift = DriftSQL(engine, base_table, node_table, {column: kind})
    if base_table == root_table:
        # Read off what the node already carries, so these match the drift shown everywhere else
        result, facts = distortion["columns"][column], distortion["facts"]
    elif dropped:
        result = _result(kind, None, 0, 0, "column removed")
        facts = {"rows_root": 0, "rows_removed": 0, "cells_changed": {}}
    else:
        measured_facts = measure_edit_facts(drift, [column])
        check_row_identity(measured_facts)
        if node_table == base_table:
            # Measured against itself: exactly zero, as root is against root
            present = drift.generate_present_cells("reference").get(column, 0)
            result = _result(kind, 0.0, present, present)
        elif kind == NUMERIC:
            result = column_distortion(drift.generate_numeric_drift(column), kind)
        else:
            result = column_distortion(drift.generate_categorical_drift(column), kind)
        facts = edit_facts(measured_facts)

    payload = {"node": node_table, "base": base_table, "column": column, "kind": kind, "distortion": result,
               "rows_root": facts["rows_root"], "rows_removed": facts["rows_removed"],
               "cells_changed": facts["cells_changed"].get(column, 0),
               "density": None, "flows": None, "annotation": None}
    if dropped:
        return payload

    if kind == NUMERIC:
        detail = numeric_column_detail(drift.generate_numeric_detail(column, TAIL_GRID))
    else:
        detail = categorical_column_detail(drift.generate_category_shares(column))

    path = [pgraph.node_map[table] for table in pgraph.path_between(base_table, node_table)]
    acted_on = acted_on_column(path, column)

    flows = None
    if kind == NUMERIC:
        payload["density"] = _density(drift, base_table, node_table, column)
    else:
        flows = category_flows(drift.generate_category_flows(column), keep=keep)
        payload["flows"] = flows

    # The breakdown is what the annotation is written from; no view draws it, so it never travels
    payload["annotation"] = annotation(column, result, facts, detail, acted_on, flows)
    return payload
