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

Missing cells are left out on both sides, by the Missing detector's own rule, so the two panels always agree
about which cells are missing. An imputed cell is no longer missing, which is how imputation still registers.

The spec is the fidelity proposal's docs 01-03. As in compare.py, the loaders touch the database and
everything else is plain pandas over frames it is handed, so it is testable without one.
"""
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde, wasserstein_distance

from detectors.missing_value import missing_mask
from app.pgraph.compare import OTHER_LABEL, _differs, _labels, _matched, _numbers, load_node_data
from app.pgraph.metrics import ID_COLUMNS

NUMERIC = "numeric"
CATEGORICAL = "categorical"
STATS = {NUMERIC: "W1/IQR", CATEGORICAL: "TVD"}

# Not data attributes: the row identifiers, and the pandas index columns DataProfile.get_col_names also
# skips. Leaving them out keeps drift over the same columns the error metrics cover.
SKIPPED_COLUMNS = (*ID_COLUMNS, "index", "level_0")

# The quantile grids for the shift view. The default oversamples the tails, because that is where a delete
# of outliers moves mass - a grid of deciles understates such a change badly.
TAIL_GRID = (0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)
UNIFORM_GRID = (0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90)
GRIDS = {"tail": TAIL_GRID, "uniform": UNIFORM_GRID}

# The most a numeric column counts for in a node's number. A guess, like the column weights - both are
# reserved decisions in doc 02, so both stay parameters rather than being settled here.
DEFAULT_CAP = 1.0

NULL_DRAWS = 500
NULL_SEED = 0
FLAG_PERCENTILE = 95

# Below this many values on either side, W1 and TVD are too noisy to lean on
LOW_CONFIDENCE_N = 30

# A share-change table names this many categories and sums the rest into one row
TOP_CHANGES = 8

# A Sankey keeps this many categories, by root share, plus a catch-all
SANKEY_TOP = 5
# Past this many categories the ribbons are unreadable even folded, so the change table opens first
SANKEY_MAX_CATEGORIES = 8
REMOVED_LABEL = "(removed)"

# Both Pareto axes are rounded to this many places, so float noise cannot make equal nodes dominate
PARETO_PRECISION = 6

# The ridgeline's smoothing, as gaussian_kde's factor on root, and how many points each curve has
KDE_FACTOR = 0.30
KDE_POINTS = 200


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
    """The column's labels, with missing cells left out by the Missing detector's own rule."""
    return values[~missing_mask(values)].astype(str)


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
    of root's, matched by "ID". The Sankey's removed sink, the null test's "random deletion of the same
    size" and the removal rates all lean on that. A node that broke it would make every one of them wrong
    without saying so, so this raises instead.
    """
    extra = set(node_frame["ID"]) - set(root_frame["ID"])
    if extra:
        raise RowIdentityError(f"the node holds {len(extra)} row(s) that root does not, e.g. ID {min(extra)}")


def summarize(columns, cap=DEFAULT_CAP, weights=None):
    """
    A node's single number: the mean of its columns' drift. A numeric column counts for at most `cap`,
    since W1/IQR has no ceiling and one wildly shifted column would otherwise swamp the rest. Columns with
    no value are left out rather than counted as unchanged.

    :param columns: {column: result}, as column_distortion returns them
    :param weights: {column: weight}, or None for every column counting the same
    :return: {"overall", "capped"} - overall is None when no column could be scored
    """
    total = weight_sum = 0.0
    capped = []
    for column, result in columns.items():
        if result["degenerate"]:
            continue
        value = result["value"]
        if result["kind"] == NUMERIC and value > cap:
            value = cap
            capped.append(column)
        weight = 1.0 if weights is None else weights.get(column, 1.0)
        total += weight * value
        weight_sum += weight
    return {"overall": total / weight_sum if weight_sum else None, "capped": capped}


def node_distortion(root_frame, node_frame, kinds, cap=DEFAULT_CAP, weights=None):
    """
    Every column's drift from root, and the node's single number.

    :param root_frame: root's rows, "ID" plus its columns
    :param node_frame: the node's rows
    :param kinds: {column: kind} for root's data columns - see column_kinds
    :param cap: the most a numeric column counts for in the node's number
    :param weights: {column: weight}, or None for every column counting the same
    :return: {"overall", "capped", "columns", "structural"} - structural lists columns the node dropped or
             gained, which have no drift and are reported as changes to the table's shape instead
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
    return {**summarize(columns, cap, weights), "columns": columns,
            "structural": {"removed": removed, "added": added}}


def root_distortion(root_frame, kinds):
    """Root against itself: exactly zero on every column, without computing anything."""
    columns = {}
    for column, kind in kinds.items():
        present = root_frame[column].notna().sum()
        columns[column] = _result(kind, 0.0, present, present)
    return {"overall": 0.0, "capped": [], "columns": columns, "structural": {"removed": [], "added": []}}


def edit_facts(root_frame, node_frame, columns):
    """
    What the wrangles between root and this node did, read off the data: how many of root's rows are gone,
    and per column how many of the surviving cells now hold a different value. The null test, the detail
    views and the annotations are keyed on these rather than on operation names, so a new kind of repair
    needs no change in any of them.

    :param columns: the data columns to count changed cells in
    :return: {"rows_root", "rows_removed", "cells_changed": {column: count}}
    """
    shared = [column for column in columns if column in node_frame.columns]
    matched = _matched(root_frame, node_frame, shared, "inner")
    changed = {column: int(np.count_nonzero(_differs(matched[f"{column}_base"], matched[f"{column}_other"])))
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
    shift at q is the integrand of W1 at q, so the bars and the number measure the same thing - but no
    finite grid averages back to the number, and nothing drawn from this may suggest one does.
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


def category_flows(root_frame, node_frame, column, top=SANKEY_TOP):
    """
    Where each of root's rows went in one categorical column: to a category in the node, or to the removed
    sink when the node no longer has the row. Rows are matched by "ID", and given the row-identity
    invariant a failed match can only mean a delete.

    This is the Sankey's data, and churn is the number it decomposes. TVD is the net change in shares, so
    five rows moving each way between two categories moves ten rows and leaves TVD at zero - the two answer
    different questions, and both are reported.

    :param top: categories kept by root share; the rest fold into OTHER_LABEL
    :return: {"flows": [{"source", "target", "rows"}], "sources", "targets", "churn", "removal_rates",
              "categories"}. churn and the category count are over the unfolded labels.
    """
    matched = _matched(root_frame, node_frame, [column], "left")
    source = _labels(matched[f"{column}_base"])
    target = _labels(matched[f"{column}_other"]).where(matched["ID"].isin(node_frame["ID"]), REMOVED_LABEL)
    churn = float((source != target).mean()) if len(source) else 0.0

    kept = list(source.value_counts().index[:top])

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
    }


def targeted_removals(path_nodes, column):
    """
    How many rows were deleted along a path by steps that acted on this column. Read off each step's own
    record - the columns it acted on and how many rows it removed - rather than its operation's name.

    :param path_nodes: GraphNodes from root down to the node
    :return: (rows removed by steps that acted on the column, whether any step acted on it at all)
    """
    removed, acted = 0, False
    for parent, child in zip(path_nodes, path_nodes[1:]):
        if column not in child.wrangle_summary()["columns"]:
            continue
        acted = True
        if parent.metrics is not None and child.metrics is not None:
            removed += max(0, int(parent.metrics.row_count) - int(child.metrics.row_count))
    return removed, acted


def detail_route(cells_changed, removed_by_column, n_categories):
    """
    Which categorical view opens first (doc 03 §3.7). Keyed on what happened to the column rather than on
    operation names, so a new kind of repair needs no change here.

    A Sankey draws rows moving: recoded cells, or rows deleted by a step that acted on this column. A column
    where neither happened drifted only because rows were lost to steps acting on other columns - the
    collateral case - and there is no mapping to draw, so the share-change table opens first. So does a
    column with too many categories for its ribbons to be legible. Either view can still be switched to.

    :return: "flows" or "change"
    """
    if n_categories > SANKEY_MAX_CATEGORIES:
        return "change"
    return "flows" if (cells_changed or removed_by_column) else "change"


# ── The null test ────────────────────────────────────────────────────────────

# Null draws keyed by (root table, column, rows kept, draws, seed). Computed lazily, when a view asks for
# them, and never on a graph render.
_null_cache = {}


def _draw_null(root_values, kind, n_retained, draws, seed):
    """draws random subsets of n_retained of root's rows, each scored against root like a real node."""
    rng = np.random.default_rng(seed)
    rows = len(root_values)
    samples = [rng.choice(rows, n_retained, replace=False) for _ in range(draws)]

    if kind == NUMERIC:
        numbers = _numbers(root_values).to_numpy()
        root_numbers = numbers[~np.isnan(numbers)]
        scale = _scale(root_numbers) if len(root_numbers) >= 2 else None
        if scale is None:
            return np.full(draws, np.nan)

        def score(sample):
            kept = numbers[sample]
            kept = kept[~np.isnan(kept)]
            return wasserstein_distance(root_numbers, kept) / scale if len(kept) >= 2 else np.nan
    else:
        # The labels become integer codes once, so each draw is a bincount rather than a value_counts
        present = ~missing_mask(root_values).to_numpy()
        if not present.any():
            return np.full(draws, np.nan)
        codes = pd.factorize(root_values.astype(str))[0]
        codes[~present] = -1
        categories = codes.max() + 1
        root_shares = np.bincount(codes[present], minlength=categories) / present.sum()

        def score(sample):
            kept = codes[sample]
            kept = kept[kept >= 0]
            if len(kept) == 0:
                return np.nan
            return 0.5 * np.abs(np.bincount(kept, minlength=categories) / len(kept) - root_shares).sum()

    return np.array([score(sample) for sample in samples])


def null_distribution(cache_key, root_values, kind, n_retained, draws=NULL_DRAWS, seed=NULL_SEED):
    """
    The drift random deletion of the same size produces: n_retained of root's rows drawn uniformly without
    replacement, draws times over.

    Removing any rows at all moves every column a little by chance, so a raw drift means nothing until it is
    set against this. It depends only on root's column and how many rows survive - not on which rows, and
    not on the node - so it is cached on exactly that, and nodes that kept the same number of rows share one.

    :param cache_key: (root table, column)
    :return: each draw's drift, NaN where a draw had nothing to score
    """
    key = (*cache_key, int(n_retained), int(draws), seed)
    if key not in _null_cache:
        _null_cache[key] = _draw_null(root_values.reset_index(drop=True), kind, int(n_retained), draws, seed)
    return _null_cache[key]


def null_applicability(facts, column, result):
    """
    Whether the row-deletion null describes what happened to this column (doc 01 §1.5). It models rows
    leaving at random, so it applies when rows were removed and none of the column's surviving cells were
    edited. An edit in place - an impute, say - is a different mechanism with no null yet (reserved decision
    3 in doc 02), so those columns go untested rather than tested against the wrong thing.

    :return: (applicable, reason)
    """
    if result["degenerate"]:
        return False, result["reason"]
    if facts["rows_removed"] == 0:
        return False, "no rows removed"
    if facts["cells_changed"].get(column, 0):
        return False, "values edited in place"
    return True, None


def null_result(cache_key, root_values, kind, n_retained, observed, applicable=True, reason=None,
                draws=NULL_DRAWS, seed=NULL_SEED):
    """
    Where a column's observed drift sits among random deletions of the same size.

    :param applicable: False when the row-deletion null does not describe what happened - see
                       null_applicability. The result then has no percentile, and the UI draws nothing,
                       rather than a marker that would read as "tested and passed".
    :return: {"applicable", "reason", "percentile", "flagged", "null_mean", "null_p95", "draws"}
    """
    untested = {"applicable": False, "reason": reason, "percentile": None, "flagged": False,
                "null_mean": None, "null_p95": None, "draws": draws}
    if not applicable:
        return untested

    null = null_distribution(cache_key, root_values, kind, n_retained, draws, seed)
    null = null[~np.isnan(null)]
    if len(null) == 0:
        return {**untested, "reason": "nothing to compare against"}

    p95 = float(np.percentile(null, FLAG_PERCENTILE))
    return {"applicable": True, "reason": None,
            "percentile": float(100 * np.mean(null < observed)),
            "flagged": bool(observed > p95),
            "null_mean": float(null.mean()), "null_p95": p95, "draws": draws}


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

    null = record["null"]
    if null and null["applicable"]:
        if null["flagged"]:
            sentences.append(f"Drift exceeds {null['percentile']:.0f}% of random deletions of the same size.")
        else:
            sentences.append(f"Random deletions of the same size drift this much or more "
                             f"{100 - null['percentile']:.0f}% of the time.")
    return sentences


def annotation(column, result, facts, detail=None, null=None, acted_on=False, flows=None):
    """
    Plain sentences explaining one column's drift, and the record every one of them is built from.

    Only two kinds of fact are stated (doc 03 §3.8): what the provenance records - which rows were removed,
    which cells changed, whether any step acted on the column - and what was measured - the drift, where it
    moved, the null test, the removal rates. Never why. "Shifted because younger developers earn less"
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
        "null": null,
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
        _null_cache.clear()
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


def drift_null(pgraph, node_table, columns=None, draws=NULL_DRAWS):
    """
    The null test for some of a node's columns. Read-only, like the compare endpoint.

    :param columns: the columns to test, or None for every data column
    :return: {column: null result}
    """
    root_table = pgraph.root_node
    root_frame, kinds = root_state(root_table)
    distortion = _node_distortion_of(pgraph, node_table)
    facts = distortion["facts"]
    n_retained = facts["rows_root"] - facts["rows_removed"]

    results = {}
    for column in (columns or list(kinds)):
        if column not in kinds:
            raise ValueError(f"{column!r} is not a data column of the root table")
        result = distortion["columns"][column]
        applicable, reason = null_applicability(facts, column, result)
        results[column] = null_result((root_table, column), root_frame[column], kinds[column], n_retained,
                                      result["value"], applicable, reason, draws)
    return results


def drift_detail(pgraph, node_table, column, grid="tail"):
    """
    Everything the compare modal's Drift views draw for one node and one column: the shift or share-change
    breakdown, the ridgeline curves or the Sankey flows, the null test and the annotation. Read-only.

    :param grid: "tail" or "uniform" - which quantile grid the shift view uses
    :return: the payload, with "detail" None when the column has nothing to break down
    """
    from app import engine

    root_table = pgraph.root_node
    root_frame, kinds = root_state(root_table)
    if column not in kinds:
        raise ValueError(f"{column!r} is not a data column of the root table")

    kind = kinds[column]
    distortion = _node_distortion_of(pgraph, node_table)
    result, facts = distortion["columns"][column], distortion["facts"]

    payload = {"node": node_table, "column": column, "kind": kind, "distortion": result,
               "rows_root": facts["rows_root"], "rows_removed": facts["rows_removed"],
               "cells_changed": facts["cells_changed"].get(column, 0),
               "detail": None, "null": None, "density": None, "flows": None, "route": None,
               "annotation": None}
    if column in distortion["structural"]["removed"]:
        return payload

    node_frame = (root_frame[["ID", column]] if node_table == root_table
                  else load_node_data(engine, node_table, [column]))
    root_values, node_values = root_frame[column], node_frame[column]

    detail = column_detail(root_values, node_values, kind, GRIDS.get(grid, TAIL_GRID))
    applicable, reason = null_applicability(facts, column, result)
    null = null_result((root_table, column), root_values, kind, facts["rows_root"] - facts["rows_removed"],
                       result["value"], applicable, reason)

    path = [pgraph.node_map[table] for table in pgraph.path_between(root_table, node_table)]
    removed_by_column, acted_on = targeted_removals(path, column)

    flows = None
    if kind == NUMERIC:
        params_key, curve_key = ("params", root_table, column), ("curve", node_table, column)
        if params_key not in _density_cache:
            _density_cache[params_key] = root_density_params(root_values)
        params = _density_cache[params_key]
        if params is not None:
            if curve_key not in _density_cache:
                _density_cache[curve_key] = node_density(node_values, params)
            payload["density"] = {"grid": params["grid"], "bandwidth": params["bandwidth"],
                                  "root": params["root_curve"], "node": _density_cache[curve_key]}
    else:
        flows = category_flows(root_frame, node_frame, column)
        payload["flows"] = flows
        payload["route"] = detail_route(payload["cells_changed"], removed_by_column, flows["categories"])

    payload.update(detail=detail, null=null,
                   annotation=annotation(column, result, facts, detail, null, acted_on, flows))
    return payload
