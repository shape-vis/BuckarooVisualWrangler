"""
Comparing the data behind two pgraph nodes - September 13, 2026

The compare modal plots two nodes' tables against each other. The ordinary plot endpoints cannot do
that: each one bins a table across its own min and max, so once a delete trims the outliers the two
nodes' bins cover different ranges and bar n on one side is not bar n on the other. Everything here
bins both states on one shared axis instead, which is what makes a bin-by-bin difference meaningful.

Row IDs survive every wrangle - previews are CREATE TABLE AS copies, deletes remove by "ID" and
imputes update in place - so rows can also be matched across two states by ID. _matched and _differs
do that, and the distortion metric reuses both - see app/pgraph/distortion.py.

The loader touches the database; everything else is plain pandas over frames it is handed, so it is
testable without one.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import text

PLOT_KINDS = ("histogram", "heatmap")

# What a null is called on a categorical axis - the same label the main histograms give it
NULL_LABEL = "null"

# A categorical axis keeps this many bands, the last being a catch-all for the long tail. Two states
# are read bar against bar, and past a couple of dozen bands neither side is legible.
MAX_CATEGORIES = 20
OTHER_LABEL = "(other)"


@dataclass
class NodeState:
    """One node's rows and error flags, cut down to the columns being compared."""
    data: pd.DataFrame      # "ID" plus the compared columns
    errors: pd.DataFrame    # row_id, column_id, error_type - only flags on a compared column


def _quote(identifier):
    """Double-quote a Postgres identifier, escaping any quote inside it."""
    return '"' + identifier.replace('"', '""') + '"'


def load_node_data(engine, table_name, columns=None):
    """
    Read one node's rows: "ID" plus the given columns, or every column when none are named.

    table_name has to come from the session graph rather than straight from a request - the routes
    check that. Columns are checked against the table's real columns before they are interpolated.

    :param engine: SQLAlchemy engine
    :param table_name: a node's table
    :param columns: the columns to read, or None for all of them
    :return: a DataFrame
    """
    existing = list(pd.read_sql_query(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = :table "
             "ORDER BY ordinal_position"),
        engine, params={"table": table_name},
    )["column_name"])

    if columns is None:
        columns = existing
    for column in columns:
        if column not in existing:
            raise ValueError(f"{table_name} has no column {column!r}")

    selected = ", ".join(_quote(column) for column in dict.fromkeys(["ID", *columns]))
    return pd.read_sql_query(f"SELECT {selected} FROM {_quote(table_name)}", engine)


def load_node_state(engine, table_name, columns):
    """
    Read one node's table and its error flags for the compared columns.

    :param engine: SQLAlchemy engine
    :param table_name: a node's table, from the session graph
    :param columns: the columns being compared
    :return: a NodeState
    """
    columns = list(dict.fromkeys(columns))
    data = load_node_data(engine, table_name, columns)

    errors = pd.read_sql_query(
        text(f"SELECT row_id, column_id, error_type FROM {_quote('errors_' + table_name)} "
             f"WHERE column_id = ANY(:columns)"),
        engine, params={"columns": columns},
    )
    return NodeState(data, errors)


def _numbers(values):
    """Each value as a finite float; NaN where it is null, text, or infinite."""
    numbers = pd.to_numeric(values, errors="coerce").astype(float)
    return numbers.where(np.isfinite(numbers))


def _labels(values):
    """Each value as the label it would carry on a categorical axis."""
    return values.map(lambda value: NULL_LABEL if pd.isna(value) else str(value))


def _kept_labels(labels):
    """
    The labels a categorical axis keeps: the most common, plus null whenever it occurs - a missing
    value repair is exactly what a comparison is often about, so null never folds into the tail.

    :param labels: every label on the axis, repeats included
    :return: the kept labels sorted as the main plots sort them, the catch-all last if one is needed
    """
    counts = labels.value_counts()
    if len(counts) <= MAX_CATEGORIES:
        return sorted(counts.index)

    kept = list(counts.index[:MAX_CATEGORIES - 1])
    if NULL_LABEL in counts.index and NULL_LABEL not in kept:
        kept[-1] = NULL_LABEL
    return sorted(kept) + [OTHER_LABEL]


class Axis:
    """
    One axis both states are drawn against.

    Numeric when most of the values are numbers: those are binned linearly across the range of *both*
    states, and everything else - nulls, text in a numeric column - becomes a categorical label beside
    the bins, the same split the main histograms make. Otherwise every value is a label.
    """

    def __init__(self, lo, hi, bin_count, labels):
        self.lo = lo                    # None on a categorical axis
        self.hi = hi
        self.bin_count = bin_count
        self.labels = labels            # the categorical labels kept, in display order

    @property
    def is_numeric(self):
        return self.lo is not None

    @classmethod
    def shared(cls, values_a, values_b, bin_count):
        """
        :param values_a: one state's values for the column
        :param values_b: the other state's
        :param bin_count: how many bins the numeric part is split into
        :return: an Axis covering both
        """
        # An empty side contributes nothing, and concatenating it only muddies the combined dtype
        values = pd.concat([side for side in (values_a, values_b) if len(side)] or [values_a],
                           ignore_index=True)
        numbers = _numbers(values)
        present = int(values.notna().sum())
        numeric = present > 0 and int(numbers.notna().sum()) * 2 >= present

        if not numeric:
            return cls(None, None, bin_count, _kept_labels(_labels(values)))

        lo, hi = float(numbers.min()), float(numbers.max())
        # A constant column still needs a bin with some width to draw
        if lo == hi:
            lo, hi, bin_count = lo - 0.5, hi + 0.5, 1

        return cls(lo, hi, bin_count, _kept_labels(_labels(values[numbers.isna()])))

    def _split(self, values):
        """(is_number, numbers, labels) per value, with labels the axis did not keep folded away."""
        if self.is_numeric:
            numbers = _numbers(values)
        else:
            numbers = pd.Series(np.nan, index=values.index)

        labels = _labels(values)
        labels = labels.where(labels.isin(self.labels), OTHER_LABEL)
        return numbers.notna().to_numpy(), numbers.to_numpy(), labels.to_numpy()

    def bin(self, values):
        """
        Which bin each value falls in. Clamped the way width_bucket is in the main histograms, so the
        maximum lands in the last bin rather than one past it.

        :return: (types, bins) Series - "numeric" with a bin index, or "categorical" with a label
        """
        is_number, numbers, labels = self._split(values)

        if self.is_numeric:
            width = (self.hi - self.lo) / self.bin_count
            index = np.clip(np.floor((numbers - self.lo) / width), 0, self.bin_count - 1)
            bins = [int(i) if number else label for i, number, label in zip(index, is_number, labels)]
        else:
            bins = list(labels)

        types = np.where(is_number, "numeric", "categorical")
        return (pd.Series(types, index=values.index, dtype=object),
                pd.Series(bins, index=values.index, dtype=object))

    def keys(self):
        """Every bin on the axis in display order: numeric bins left to right, then the labels."""
        numeric = [("numeric", i) for i in range(self.bin_count)] if self.is_numeric else []
        return numeric + [("categorical", label) for label in self.labels]

    def bin_scale(self):
        """The axis as the front end's hybrid scales take it - the shape the main histograms send."""
        numeric = []
        if self.is_numeric:
            width = (self.hi - self.lo) / self.bin_count
            numeric = [{"x0": self.lo + i * width, "x1": self.lo + (i + 1) * width}
                       for i in range(self.bin_count)]
        return {"numeric": numeric, "categorical": list(self.labels)}


def _counts(keyed, errors, key_columns):
    """
    Rows and error flags per bin.

    :param keyed: one row per data row - "ID" plus the key columns naming its bin
    :param errors: the flags that count, as row_id / error_type
    :param key_columns: the columns making up a bin's key
    :return: {key tuple: {"items": rows, <error_type>: flags, ...}}
    """
    counts = {}
    for key, size in keyed.groupby(key_columns, sort=False).size().items():
        counts[tuple(key)] = {"items": int(size)}

    # An empty flag table can come back with object-typed columns, which will not merge on an int ID
    if errors.empty:
        return counts

    flagged = errors.merge(keyed, left_on="row_id", right_on="ID")
    for key, size in flagged.groupby([*key_columns, "error_type"], sort=False).size().items():
        *bin_key, error_type = key
        counts[tuple(bin_key)][error_type] = int(size)
    return counts


def _histogram_counts(state, column, axis):
    types, bins = axis.bin(state.data[column])
    keyed = pd.DataFrame({"ID": state.data["ID"], "type": types, "bin": bins})
    return _counts(keyed, state.errors[state.errors["column_id"] == column], ["type", "bin"])


def compare_histogram(a, b, column, bin_count):
    """
    Both states' histograms of one column, binned on one shared axis.

    :param a: selection A's NodeState
    :param b: selection B's NodeState
    :param column: the column to bin
    :param bin_count: how many bins its numeric part is split into
    :return: {"scaleX", "bins": [{"xType", "xBin", "a", "b"}]}. Every bin on the axis is
             listed, empty ones included, so a difference plot has a zero to measure against.
    """
    axis = Axis.shared(a.data[column], b.data[column], bin_count)
    counts_a = _histogram_counts(a, column, axis)
    counts_b = _histogram_counts(b, column, axis)

    return {
        "scaleX": axis.bin_scale(),
        "bins": [{"xType": x_type, "xBin": x_bin,
                  "a": counts_a.get((x_type, x_bin), {"items": 0}),
                  "b": counts_b.get((x_type, x_bin), {"items": 0})}
                 for x_type, x_bin in axis.keys()],
    }


def _heatmap_counts(state, x_column, y_column, x_axis, y_axis):
    x_types, x_bins = x_axis.bin(state.data[x_column])
    y_types, y_bins = y_axis.bin(state.data[y_column])
    keyed = pd.DataFrame({"ID": state.data["ID"], "xType": x_types, "xBin": x_bins,
                          "yType": y_types, "yBin": y_bins})

    # A row flagged the same way on both columns is one flagged row in its tile, not two
    flags = state.errors[state.errors["column_id"].isin([x_column, y_column])]
    flags = flags.drop_duplicates(["row_id", "error_type"])
    return _counts(keyed, flags, ["xType", "xBin", "yType", "yBin"])


def compare_heatmap(a, b, x_column, y_column, bin_count):
    """
    Both states' 2D histograms on shared axes.

    :return: {"scaleX", "scaleY", "tiles": [{"xType", "xBin", "yType", "yBin", "a", "b"}]}.
             Only tiles holding rows on at least one side are listed - a grid of empties would be
             most of the payload.
    """
    x_axis = Axis.shared(a.data[x_column], b.data[x_column], bin_count)
    y_axis = Axis.shared(a.data[y_column], b.data[y_column], bin_count)
    counts_a = _heatmap_counts(a, x_column, y_column, x_axis, y_axis)
    counts_b = _heatmap_counts(b, x_column, y_column, x_axis, y_axis)

    x_order = {key: i for i, key in enumerate(x_axis.keys())}
    y_order = {key: i for i, key in enumerate(y_axis.keys())}
    keys = sorted(set(counts_a) | set(counts_b),
                  key=lambda key: (x_order[key[:2]], y_order[key[2:]]))

    tiles = []
    for key in keys:
        x_type, x_bin, y_type, y_bin = key
        tiles.append({"xType": x_type, "xBin": x_bin, "yType": y_type, "yBin": y_bin,
                      "a": counts_a.get(key, {"items": 0}),
                      "b": counts_b.get(key, {"items": 0})})

    return {"scaleX": x_axis.bin_scale(), "scaleY": y_axis.bin_scale(), "tiles": tiles}


def _differs(before, after):
    """
    Whether each value changed, element-wise. Two nulls are the same value, and numbers compare as
    numbers, so 3 on one side and "3" or 3.0 on the other is not a change.

    :return: a boolean array
    """
    before_null = before.isna().to_numpy()
    after_null = after.isna().to_numpy()
    before_numbers = _numbers(before).to_numpy()
    after_numbers = _numbers(after).to_numpy()

    both_numbers = ~np.isnan(before_numbers) & ~np.isnan(after_numbers)
    numbers_differ = both_numbers & ~np.isclose(np.nan_to_num(before_numbers), np.nan_to_num(after_numbers))
    text_differs = ~both_numbers & (before.astype(str).to_numpy() != after.astype(str).to_numpy())

    return (before_null != after_null) | (~before_null & ~after_null & (numbers_differ | text_differs))


def _matched(data_a, data_b, columns, how):
    """Two states' rows side by side, one row per ID, the compared columns suffixed _a and _b."""
    columns = list(dict.fromkeys(columns))
    selected = list(dict.fromkeys(["ID", *columns]))
    return data_a[selected].merge(data_b[selected], on="ID", how=how, suffixes=("_a", "_b"))
