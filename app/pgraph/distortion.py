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

The spec is the fidelity proposal's docs 01-03. As in compare.py, the loaders touch the database and
everything else is plain pandas over frames it is handed, so it is testable without one.
"""
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde, wasserstein_distance

from detectors.missing_value import missing_mask
from app.pgraph.compare import (MAX_CATEGORIES, NULL_LABEL, OTHER_LABEL, _differs, _labels, _matched, _numbers,
                                load_node_data)
from app.pgraph.metrics import ID_COLUMNS

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

REMOVED_LABEL = "(removed)"

# How many of the categories folded into the catch-all are named back, for the modal to list and offer
OTHER_LISTED = 200
# The most bands a Sankey will draw when the modal names the categories itself
MAX_KEPT = 100

# Both Pareto axes are rounded to this many places, so float noise cannot make equal nodes dominate
PARETO_PRECISION = 6

# The ridgeline's smoothing, as gaussian_kde's factor on root, and how many points each curve has. The
# points are dense because the compare modal zooms into a slice of the grid in the browser, and a zoomed
# window still needs enough of them to draw a smooth curve.
KDE_FACTOR = 0.30
KDE_POINTS = 1000


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

def _numeric_values(values):
    """The column's numbers. Nulls, and any text in a mostly-numeric column, fall away - as they do from
    the attribute summary's mean and median."""
    numbers = _numbers(values)
    return numbers[numbers.notna()].to_numpy()


def _category_values(values):
    """The column's labels, every cell the Missing detector's rule calls missing labelled null."""
    return values.astype(str).where(~missing_mask(values), NULL_LABEL)


def _scale(root_numbers):
    """
    What a numeric drift is measured in: root's IQR. A column whose middle half is a single value has no
    IQR, so its standard deviation stands in; a column that is one value throughout has neither.

    :return: the scale, or None for a constant column
    """
    q1, q3 = np.quantile(root_numbers, [0.25, 0.75])
    if q3 > q1:
        return float(q3 - q1)
    std = float(np.std(root_numbers, ddof=1))
    return std if std > 0 else None


def _shares(root_labels, node_labels):
    """Each category's share of root and of the node, aligned, with the node's change."""
    shares = pd.DataFrame({"root": root_labels.value_counts(normalize=True),
                           "node": node_labels.value_counts(normalize=True)}).fillna(0.0)
    # assign rather than item assignment: pandas 2.2 raises a spurious chained-assignment warning for the
    # latter under Python 3.14
    return shares.assign(change=shares["node"] - shares["root"])


def _result(kind, value, n_root, n_node, reason=None):
    """
    One column's drift. A column with nothing honest to report carries a reason instead of a value - never
    a zero, which would read as "unchanged".
    """
    # Counts arrive as numpy integers, which Flask cannot encode, and which would make the flag below a
    # numpy bool
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


def column_distortion(root, node, kind):
    """
    How far one column has drifted from root.

    :param root: root's values for the column
    :param node: the node's values for it
    :param kind: NUMERIC or CATEGORICAL, decided on root
    :return: {"value", "stat", "kind", "n_root", "n_node", "degenerate", "reason", "low_confidence"}
    """
    if kind == NUMERIC:
        r, n = _numeric_values(root), _numeric_values(node)
        if len(n) == 0:
            return _result(kind, None, len(r), 0, "no values")
        if len(r) < 2 or len(n) < 2:
            return _result(kind, None, len(r), len(n), "too few values")
        scale = _scale(r)
        if scale is None:
            return _result(kind, None, len(r), len(n), "constant column")
        return _result(kind, wasserstein_distance(r, n) / scale, len(r), len(n))

    r, n = _category_values(root), _category_values(node)
    if len(r) == 0 or len(n) == 0:
        return _result(kind, None, len(r), len(n), "no values")
    # Halved because a row leaving one category arrives in another; unhalved, every move counts twice
    return _result(kind, 0.5 * _shares(r, n)["change"].abs().sum(), len(r), len(n))


# ── One node ─────────────────────────────────────────────────────────────────

def check_row_identity(root_frame, node_frame):
    """
    Every wrangle edits cells or deletes rows, and none creates one - so a node's rows are always a subset
    of root's, matched by "ID". The Sankey's removed sink and the removal rates both lean on that. A node that broke it would make every one of them wrong
    without saying so, so this raises instead.
    """
    extra = set(node_frame["ID"]) - set(root_frame["ID"])
    if extra:
        raise RowIdentityError(f"the node holds {len(extra)} row(s) that root does not, e.g. ID {min(extra)}")


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


def node_distortion(root_frame, node_frame, kinds, weights=None):
    """
    Every column's drift from root, and the node's single number.

    :param root_frame: root's rows, "ID" plus its columns
    :param node_frame: the node's rows
    :param kinds: {column: kind} for root's data columns - see column_kinds
    :param weights: {column: weight}, or None for every column counting the same
    :return: {"overall", "columns", "structural"} - structural lists columns the node dropped or gained,
             which have no drift and are reported as changes to the table's shape instead
    """
    check_row_identity(root_frame, node_frame)

    columns = {}
    for column, kind in kinds.items():
        if column in node_frame.columns:
            columns[column] = column_distortion(root_frame[column], node_frame[column], kind)
        else:
            columns[column] = _result(kind, None, root_frame[column].notna().sum(), 0, "column removed")

    added = [column for column in node_frame.columns
             if column not in kinds and column not in SKIPPED_COLUMNS]
    for column in added:
        columns[column] = _result(None, None, 0, node_frame[column].notna().sum(), "column added")

    removed = [column for column in kinds if column not in node_frame.columns]
    return {**summarize(columns, weights), "columns": columns,
            "structural": {"removed": removed, "added": added}}


def root_distortion(root_frame, kinds):
    """Root against itself: exactly zero on every column, without computing anything."""
    columns = {}
    for column, kind in kinds.items():
        # A categorical column counts its missing cells, as column_distortion does
        present = len(root_frame) if kind == CATEGORICAL else root_frame[column].notna().sum()
        columns[column] = _result(kind, 0.0, present, present)
    return {"overall": 0.0, "columns": columns, "structural": {"removed": [], "added": []}}


def edit_facts(root_frame, node_frame, columns):
    """
    What the wrangles between root and this node did, read off the data: how many of root's rows are gone,
    and per column how many of the surviving cells now hold a different value. The detail views and the
    annotations are keyed on these rather than on operation names, so a new kind of repair needs no change
    in any of them.

    :param columns: the data columns to count changed cells in
    :return: {"rows_root", "rows_removed", "cells_changed": {column: count}}
    """
    shared = [column for column in columns if column in node_frame.columns]
    matched = _matched(root_frame, node_frame, shared, "inner")
    changed = {column: int(np.count_nonzero(_differs(matched[f"{column}_a"], matched[f"{column}_b"])))
               for column in shared}
    return {"rows_root": len(root_frame),
            "rows_removed": len(set(root_frame["ID"]) - set(node_frame["ID"])),
            "cells_changed": changed}


# ── Detail: what the drill-down views draw ───────────────────────────────────

def _share_row(label, shares):
    return {"category": str(label), "root_pct": float(shares["root"]), "node_pct": float(shares["node"]),
            "change_pct": float(shares["change"])}


def column_detail(root, node, kind, grid=TAIL_GRID):
    """
    The breakdown behind one column's number: where in the distribution its mass moved.

    Numeric: the node's quantiles against root's on the grid, and the shift between them in root IQRs. The
    shift at q is the integrand of W1 at q, so the shifts and the number measure the same thing - but no
    finite grid averages back to the number, and nothing said from this may suggest one does.
    Categorical: each category's share of root and of the node in percent, the TOP_CHANGES categories that
    moved most by name and the rest summed into one row.

    :return: numeric {"kind", "grid", "root", "node", "shift"}; categorical {"kind", "categories",
             "truncated_n"}, categories as {"category", "root_pct", "node_pct", "change_pct"}.
             None when the column has nothing to break down.
    """
    if kind == NUMERIC:
        r, n = _numeric_values(root), _numeric_values(node)
        scale = _scale(r) if len(r) >= 2 else None
        if scale is None or len(n) < 2:
            return None
        root_q, node_q = np.quantile(r, grid), np.quantile(n, grid)
        return {"kind": kind, "grid": list(grid), "root": root_q.tolist(), "node": node_q.tolist(),
                "shift": ((node_q - root_q) / scale).tolist()}

    r, n = _category_values(root), _category_values(node)
    if len(r) == 0 or len(n) == 0:
        return None
    shares = _shares(r, n) * 100
    # Largest movers first, ties broken by name so the table is the same on every render
    order = sorted(shares.index, key=lambda label: (-abs(shares.at[label, "change"]), str(label)))
    rows = [_share_row(label, shares.loc[label]) for label in order[:TOP_CHANGES]]
    rest = order[TOP_CHANGES:]
    if rest:
        rows.append(_share_row(OTHER_LABEL, shares.loc[rest].sum()))
    return {"kind": kind, "categories": rows, "truncated_n": len(rest)}


def root_density_params(root_values, factor=KDE_FACTOR, points=KDE_POINTS):
    """
    Fit the ridgeline's smoothing on root, once per column.

    Every row of a ridgeline has to be smoothed identically, or the differences between rows are partly the
    smoother's doing (doc 03 §3.6b). So the bandwidth is fitted here, on root, in the column's own units, and
    node_density reuses it for every node.

    :return: {"bandwidth", "grid", "root_curve", "n_root"}, or None when root cannot be smoothed
    """
    r = _numeric_values(root_values)
    if len(r) < 2 or np.std(r) == 0:
        return None
    kde = gaussian_kde(r, bw_method=factor)
    bandwidth = float(np.sqrt(kde.covariance[0, 0]))
    grid = np.linspace(r.min() - 3 * bandwidth, r.max() + 3 * bandwidth, points)
    return {"bandwidth": bandwidth, "grid": grid.tolist(), "root_curve": kde(grid).tolist(), "n_root": len(r)}


def node_density(node_values, params):
    """
    One node's curve on root's grid, smoothed with root's bandwidth.

    gaussian_kde takes its bandwidth as a factor on the data's own spread, so the factor is set per node to
    land on root's bandwidth exactly. The curve is scaled by the node's share of root's values rather than
    normalised to an area of one: the rows share one vertical scale, and a curve normalised on its own would
    make a node that lost half its rows look unchanged (§3.6b). Where nothing moved, it lies on root's.

    :return: the curve, or None when the node has too few values to draw
    """
    n = _numeric_values(node_values)
    if params is None or len(n) < 2:
        return None
    grid = np.asarray(params["grid"])
    bandwidth = params["bandwidth"]
    std = np.std(n, ddof=1)
    if std > 0:
        curve = gaussian_kde(n, bw_method=bandwidth / std)(grid)
    else:
        # Every value is the same, which gaussian_kde cannot fit - but the curve is just one kernel
        curve = np.exp(-0.5 * ((grid - n[0]) / bandwidth) ** 2) / (bandwidth * np.sqrt(2 * np.pi))
    return (curve * len(n) / params["n_root"]).tolist()


def category_flows(before_frame, after_frame, column, limit=MAX_CATEGORIES, keep=None):
    """
    Where each of the earlier state's rows sits in the later one, for one categorical column: in a category,
    or in the removed sink when the later state no longer has the row. Rows are matched by "ID", and given
    the row-identity invariant a failed match can only mean a delete.

    This is the Sankey's data, and churn is the number it decomposes. TVD is the net change in shares, so
    five rows moving each way between two categories moves ten rows and leaves TVD at zero - the two answer
    different questions, and both are reported.

    :param before_frame: the state the rows start in - root, for a node's Sankey - as a frame with "ID" and
                         the column
    :param after_frame: the state they end in
    :param limit: the most categories kept, the compare axes' limit by default. A column with more keeps its
                  most common in before_frame, and null whenever it occurs, as those axes do, and folds the
                  rest into OTHER_LABEL.
    :param keep: the categories to keep as themselves, naming them outright instead of by the limit - the
                 modal sends this when the reader pulls one back out of the catch-all
    :return: {"flows": [{"source", "target", "rows"}], "sources", "targets", "churn", "removal_rates",
              "categories", "other"}. Sources and targets run from the most common category down, so a plot
              can open on the top few. "other" names what the catch-all holds, so the reader can look inside
              it and take a category back out. churn and the category count are over the unfolded labels.
    """
    matched = _matched(before_frame, after_frame, [column], "left")
    source = _labels(matched[f"{column}_a"])
    target = _labels(matched[f"{column}_b"]).where(matched["ID"].isin(after_frame["ID"]), REMOVED_LABEL)
    churn = float((source != target).mean()) if len(source) else 0.0

    counts = source.value_counts()
    if keep is not None:
        # The modal named them, so size does not come into it - only the order, which stays by count
        kept = [label for label in counts.index if label in set(keep)][:MAX_KEPT]
    else:
        kept = list(counts.index)
        if len(kept) > limit:
            kept = kept[:limit - 1]
            # Null is the rarest kept, so it takes the last place and the order still runs by count
            if NULL_LABEL in counts.index and NULL_LABEL not in kept:
                kept[-1] = NULL_LABEL

    # What the catch-all holds, biggest first: the modal lists these and offers them back
    tail = [label for label in counts.index if label not in set(kept)]
    other = None if not tail else {
        "categories": [{"category": str(label), "rows": int(counts[label])} for label in tail[:OTHER_LISTED]],
        "more": max(0, len(tail) - OTHER_LISTED),
        "rows": int(counts[tail].sum()),
    }

    def fold(labels):
        return labels.where(labels.isin(kept) | (labels == REMOVED_LABEL), OTHER_LABEL)

    folded = pd.DataFrame({"source": fold(source), "target": fold(target)})
    flows = [{"source": s, "target": t, "rows": int(rows)}
             for (s, t), rows in folded.value_counts(sort=False).items()]

    order = kept + [OTHER_LABEL]
    present_sources, present_targets = set(folded["source"]), set(folded["target"])
    removed = folded["target"] == REMOVED_LABEL

    return {
        "flows": flows,
        "sources": [label for label in order if label in present_sources],
        "targets": [label for label in order if label in present_targets]
                   + ([REMOVED_LABEL] if removed.any() else []),
        "churn": churn,
        "removal_rates": {str(label): float(rate)
                          for label, rate in removed.groupby(folded["source"]).mean().items()},
        "categories": int(source.nunique()),
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

# The root being measured against, read once. Every node's drift, null and detail needs it, and root's table
# never changes; a new upload brings a new root.
_root_cache = {"table": None, "frame": None, "kinds": None}

# Ridgeline curves: root's fit per (root table, column), and each node's curve per (node table, column)
_density_cache = {}


def root_state(root_table, reload=False):
    """
    Root's rows and its data columns' kinds, read once per root.

    :param reload: read root again even if it is cached - a session's start asks for this, since tests and
                   re-uploads can reuse a table name for different data
    :return: (frame, kinds)
    """
    if reload or _root_cache["table"] != root_table:
        from app import engine
        from app.db_utils.column_types import ColumnTypes

        frame = load_node_data(engine, root_table)
        _root_cache.update(table=root_table, frame=frame,
                           kinds=column_kinds(ColumnTypes(root_table, engine), frame.columns))
        _density_cache.clear()
    return _root_cache["frame"], _root_cache["kinds"]


def refresh_node_distortion(table_name):
    """
    Compute a node's drift from root and attach it to its GraphNode, with the facts about what its wrangles
    did. Called from refresh_node_metrics, so every path that creates a node - upload, a wrangle executed
    from the repair panel, an accepted AI suggestion - gets it, once, when the node is made.

    :return: the distortion that was attached
    """
    import app as app_package
    from app import engine

    pgraph = app_package.pgraph_for_session
    node = pgraph.node_map[table_name] if pgraph else None
    if node is None:
        raise KeyError(f"no pgraph node for table {table_name!r}, cannot attach distortion")

    root_table = pgraph.root_node
    # Root's own refresh runs once, as a session starts, so that is where a stale cached root is let go
    root_frame, kinds = root_state(root_table, reload=table_name == root_table)

    if table_name == root_table:
        distortion = root_distortion(root_frame, kinds)
        facts = {"rows_root": len(root_frame), "rows_removed": 0,
                 "cells_changed": {column: 0 for column in kinds}}
    else:
        node_frame = load_node_data(engine, table_name)
        distortion = node_distortion(root_frame, node_frame, kinds)
        facts = edit_facts(root_frame, node_frame, kinds)

    node.set_distortion({**distortion, "facts": facts})
    return node.distortion


def _node_distortion_of(pgraph, node_table):
    """A node's distortion, computed now if the node somehow predates it."""
    node = pgraph.node_map[node_table]
    if node.distortion is None:
        refresh_node_distortion(node_table)
    return node.distortion


def drift_detail(pgraph, node_table, column, keep=None, base_table=None):
    """
    Everything the compare modal's Drift views draw for one node and one column: the ridgeline curves or the
    Sankey flows, and the annotation. Read-only.

    The reference is root unless a base is named. A base is one of the node's ancestors - the two selections'
    common ancestor, when the modal is asked to leave out the history they share - and every number here is
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
    root_frame, kinds = root_state(root_table)
    if column not in kinds:
        raise ValueError(f"{column!r} is not a data column of the root table")

    def column_frame(table):
        """One table's "ID" and the column - root's out of the cache, any other read from the database."""
        return root_frame[["ID", column]] if table == root_table else load_node_data(engine, table, [column])

    # Kinds stay root's for every reference, so a column cannot switch statistics with the reference
    kind = kinds[column]
    distortion = _node_distortion_of(pgraph, node_table)
    dropped = (column in distortion["structural"]["removed"]
               or column in _node_distortion_of(pgraph, base_table)["structural"]["removed"])

    base_frame = node_frame = None
    if base_table == root_table:
        # Read off what the node already carries, so these match the drift shown everywhere else
        result, facts = distortion["columns"][column], distortion["facts"]
    elif dropped:
        result = _result(kind, None, 0, 0, "column removed")
        facts = {"rows_root": 0, "rows_removed": 0, "cells_changed": {}}
    else:
        base_frame = column_frame(base_table)
        node_frame = base_frame if node_table == base_table else column_frame(node_table)
        check_row_identity(base_frame, node_frame)
        if node_table == base_table:
            # Measured against itself: exactly zero, as root is against root
            present = base_frame[column].notna().sum()
            result = _result(kind, 0.0, present, present)
        else:
            result = column_distortion(base_frame[column], node_frame[column], kind)
        facts = edit_facts(base_frame, node_frame, [column])

    payload = {"node": node_table, "base": base_table, "column": column, "kind": kind, "distortion": result,
               "rows_root": facts["rows_root"], "rows_removed": facts["rows_removed"],
               "cells_changed": facts["cells_changed"].get(column, 0),
               "density": None, "flows": None, "annotation": None}
    if dropped:
        return payload

    if base_frame is None:
        base_frame, node_frame = root_frame, column_frame(node_table)
    base_values, node_values = base_frame[column], node_frame[column]

    detail = column_detail(base_values, node_values, kind)

    path = [pgraph.node_map[table] for table in pgraph.path_between(base_table, node_table)]
    acted_on = acted_on_column(path, column)

    flows = None
    if kind == NUMERIC:
        # The curve is drawn on the grid fitted to its reference, so it is cached per reference too
        params_key, curve_key = ("params", base_table, column), ("curve", base_table, node_table, column)
        if params_key not in _density_cache:
            _density_cache[params_key] = root_density_params(base_values)
        params = _density_cache[params_key]
        if params is not None:
            if curve_key not in _density_cache:
                _density_cache[curve_key] = node_density(node_values, params)
            payload["density"] = {"grid": params["grid"], "bandwidth": params["bandwidth"],
                                  "root": params["root_curve"], "node": _density_cache[curve_key]}
    else:
        flows = category_flows(base_frame, node_frame, column, keep=keep)
        payload["flows"] = flows

    # The breakdown is what the annotation is written from; no view draws it, so it never travels
    payload["annotation"] = annotation(column, result, facts, detail, acted_on, flows)
    return payload
