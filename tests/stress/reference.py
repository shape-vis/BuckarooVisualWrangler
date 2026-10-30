"""
An independent answer key for the app's data operations - October 28, 2026.

Everything the app computes inside Postgres - error flags, wrangles, histograms, comparisons, drift, metrics - is
computed again here, in plain Python over a table read back from the database, from the rules as the app's docstrings
state them and as the original pandas code (git history before 56d65dd) applied them. Nothing here imports the app's
query builders, so a mistake in a query cannot hide by being copied into its answer.

Floating point: the app sums and divides in Postgres, in an order of its own, so a value computed here can differ
from the app's in the last bits. Where that can flip a decision - a cell sitting exactly on the anomaly threshold, a
number exactly on a bin edge - the answer key marks the case "borderline" and the tests do not hold the app to either
side of it.
"""
import math
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
from scipy.stats import wasserstein_distance

# ── The rules, restated ──────────────────────────────────────────────────────

MISSING_TOKENS = ("null", "undefined")
NULL_LABEL = "null"
OTHER_LABEL = "(other)"
REMOVED_LABEL = "(removed)"
MAX_LABELS = 20
STRUCTURAL_COLUMNS = ("ID", "Unnamed: 0", "index", "level_0")
ERROR_TYPES = ("missing", "mismatch", "anomaly", "incomplete")

# What a text value has to look like to be read as a number. Postgres' \s is [ \t\n\r\f\v] and its \d, under the C
# collation the database uses, is [0-9] - spelled out so Python's unicode-aware \s and \d don't widen it.
NUMBER_PATTERN = re.compile(r"[ \t\n\r\f\v]*-?[0-9]+(\.[0-9]+)?[ \t\n\r\f\v]*")
# The mismatch detector's numeric kind, after trimming: no sign, no surrounding space
MISMATCH_NUMBER_PATTERN = re.compile(r"[0-9]+(\.[0-9]+)?")
MISMATCH_TRIMMED = " \t\n\r\f\v"

# A real value spelled like the catch-all or the removed sink, give or take double quotes, gains one more pair of quotes
SENTINEL_LOOKALIKE = re.compile(r'"*(\(other\)|\(removed\))"*')

ANOMALY_Z_SCORE = 2
ANOMALY_MIN_VALUES = 10
INCOMPLETE_MAX_NUMERIC_VALUES = 10
INCOMPLETE_MIN_OCCURRENCES = 3

# How close two floats must be, relative to their size, before a decision between them is called borderline
BORDERLINE_RELATIVE = 1e-9

LOW_CONFIDENCE_N = 30


def is_null(value):
    """A database NULL, as pandas reads it back: None, or NaN in a numeric column."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def as_text(value):
    """A stored value as Postgres' ::text gives it, for the text columns the answer key reads it from."""
    return str(value)


def is_missing(value):
    """The Missing detector's rule: NULL, or exactly one of the missing tokens."""
    if is_null(value):
        return True
    return as_text(value) in MISSING_TOKENS


def text_number(value):
    """A text value as a number, when it has the numeric shape; None otherwise."""
    if is_null(value):
        return None
    text = as_text(value)
    if NUMBER_PATTERN.fullmatch(text):
        return float(text)
    return None


def stored_number(value):
    """A numeric column's value as the plots read it: finite numbers as they are, NULL, NaN and infinities None."""
    if is_null(value):
        return None
    number = float(value)
    if math.isinf(number) or math.isnan(number):
        return None
    return number


def label_of(value):
    """
    A cell as a category: its text, or the null label when it is missing. Text spelled like the catch-all or the
    removed sink is quoted, so neither label is ever a real value's.
    """
    if is_missing(value):
        return NULL_LABEL
    text = as_text(value)
    if SENTINEL_LOOKALIKE.fullmatch(text):
        return '"' + text + '"'
    return text


def near(a, b):
    """Whether two floats are close enough that which side of the other one lands on is down to rounding."""
    scale = max(abs(a), abs(b), 1.0)
    return abs(a - b) <= BORDERLINE_RELATIVE * scale


# ── The stored table ─────────────────────────────────────────────────────────

@dataclass
class StoredTable:
    """
    A table as the database holds it, read back for the answer key: its rows in "ID" order, and which columns are
    stored as numbers and which as text.
    """
    name: str
    frame: object
    numeric_cols: set = field(default_factory=set)
    text_cols: set = field(default_factory=set)
    integer_cols: set = field(default_factory=set)

    @property
    def data_columns(self):
        columns = []
        for column in self.frame.columns:
            if column not in STRUCTURAL_COLUMNS:
                columns.append(column)
        return columns

    @property
    def ids(self):
        ids = []
        for row_id in self.frame["ID"]:
            ids.append(int(row_id))
        return ids

    def values(self, column):
        return list(self.frame[column])

    def rows(self):
        """(row id, {column: value}) for every row."""
        rows = []
        columns = list(self.frame.columns)
        for record in self.frame.itertuples(index=False, name=None):
            values = dict(zip(columns, record))
            rows.append((int(values["ID"]), values))
        return rows

    def number_of(self, column, value):
        """A value of this table's column as the plots and drift read it."""
        if column in self.numeric_cols:
            return stored_number(value)
        if column in self.text_cols:
            return text_number(value)
        return None

    def column_kind(self, column):
        """
        numeric or categorical: a stored number is numeric; a text column with no numbers at all, or numbers in half
        its rows or fewer, is categorical; one with numbers in most of its rows is numeric.
        """
        if column in self.numeric_cols:
            return "numeric"
        values = self.values(column)
        numbers = 0
        for value in values:
            if not is_null(value) and NUMBER_PATTERN.fullmatch(as_text(value)):
                numbers += 1
        if numbers == 0:
            return "categorical"
        if numbers > len(values) / 2:
            return "numeric"
        return "categorical"


# ── Error detection ──────────────────────────────────────────────────────────

@dataclass
class Flags:
    """The cells flagged: certain ones, and borderline anomalies the tests leave either way."""
    certain: set = field(default_factory=set)
    borderline: set = field(default_factory=set)


def _anomaly_flags(numbers_by_row, column, flags, value_count=None):
    """
    Flag the numbers further than two sample standard deviations from their mean. numbers_by_row holds (row id,
    number) for every number the column holds; value_count overrides how many there are, for a column whose numbers
    the detector counts differently from the ones it judges.
    """
    numbers = []
    for _, number in numbers_by_row:
        numbers.append(number)
    count = len(numbers) if value_count is None else value_count
    if count < ANOMALY_MIN_VALUES:
        return

    array = np.asarray(numbers, dtype=float)
    with np.errstate(invalid="ignore", over="ignore"):
        mean = float(array.mean())
        std = float(array.std(ddof=1))
    if not std > 0 or math.isnan(mean):
        return

    threshold = ANOMALY_Z_SCORE * std
    for row_id, number in numbers_by_row:
        distance = abs(number - mean)
        cell = (row_id, column, "anomaly")
        if near(distance, threshold):
            flags.borderline.add(cell)
        elif distance > threshold:
            flags.certain.add(cell)


def detect(table):
    """
    The flags the detectors raise on a table:

        missing     a NULL, or exactly "null" or "undefined", in any column
        anomaly     a number more than 2 sample standard deviations from its column's mean, in a column of at least
                    10 numbers - a numeric column's values, or a text column's numeric-shaped values
        mismatch    a text value whose kind - numeric if it is digits with an optional fraction once trimmed, text
                    otherwise - is not the kind most of the column's values are
        incomplete  a text value occurring fewer than 3 times, in a column holding at most 10 numeric-shaped values

    :param table: a StoredTable
    :return: Flags of (row id, column, error type)
    """
    flags = Flags()
    rows = table.rows()

    for column in table.data_columns:
        for row_id, values in rows:
            if is_missing(values[column]):
                flags.certain.add((row_id, column, "missing"))

        if column in table.numeric_cols:
            # Every non-NULL value counts here, infinities included, as AVG and STDDEV_SAMP see them
            numbers_by_row = []
            for row_id, values in rows:
                value = values[column]
                if not is_null(value):
                    numbers_by_row.append((row_id, float(value)))
            _anomaly_flags(numbers_by_row, column, flags)
            continue

        if column not in table.text_cols:
            continue

        _detect_text_column(rows, column, flags)

    return flags


def _majority_kind(occurrences, kinds):
    """
    The kind most of a column's values are. A tie goes to the kind holding the column's most frequent value, then to
    the kind first by name.
    """
    totals = {}
    most_frequent = {}
    for value, count in occurrences.items():
        kind = kinds[value]
        totals[kind] = totals.get(kind, 0) + count
        most_frequent[kind] = max(most_frequent.get(kind, 0), count)

    def ranking(kind):
        return -totals[kind], -most_frequent[kind], kind

    ordered = sorted(totals, key=ranking)
    if not ordered:
        return None
    return ordered[0]


def _detect_text_column(rows, column, flags):
    """The text rules - anomaly, mismatch and incomplete - for one text column."""
    occurrences = {}
    for _, values in rows:
        value = values[column]
        if is_null(value):
            continue
        text = as_text(value)
        occurrences[text] = occurrences.get(text, 0) + 1

    kinds = {}
    for text in occurrences:
        trimmed = text.strip(MISMATCH_TRIMMED)
        if MISMATCH_NUMBER_PATTERN.fullmatch(trimmed):
            kinds[text] = "numeric"
        else:
            kinds[text] = "text"
    majority = _majority_kind(occurrences, kinds)

    numeric_value_count = 0
    for text, count in occurrences.items():
        if NUMBER_PATTERN.fullmatch(text):
            numeric_value_count += count

    numbers_by_row = []
    for row_id, values in rows:
        value = values[column]
        number = text_number(value)
        if number is not None:
            numbers_by_row.append((row_id, number))
    _anomaly_flags(numbers_by_row, column, flags)

    for row_id, values in rows:
        value = values[column]
        if is_null(value):
            continue
        text = as_text(value)
        if kinds[text] != majority:
            flags.certain.add((row_id, column, "mismatch"))
        is_rare = occurrences[text] < INCOMPLETE_MIN_OCCURRENCES
        if is_rare and numeric_value_count <= INCOMPLETE_MAX_NUMERIC_VALUES:
            flags.certain.add((row_id, column, "incomplete"))


# ── Metrics ──────────────────────────────────────────────────────────────────

def metrics(table, flags):
    """
    A node's metrics: per column, the share of rows each error type flags; per node, the share of cells.
    Borderline anomalies are left out, so a test compares the rates only where they are certain.

    :return: {"row_count", "column_count", "columns": {column: {type: count}}, "totals": {type: count}}
    """
    columns = {}
    totals = {}
    for error_type in ERROR_TYPES:
        totals[error_type] = 0
    for column in table.data_columns:
        columns[column] = {}
        for error_type in ERROR_TYPES:
            columns[column][error_type] = 0

    for _, column, error_type in flags.certain:
        columns[column][error_type] += 1
        totals[error_type] += 1

    return {"row_count": len(table.frame), "column_count": len(table.data_columns), "columns": columns,
            "totals": totals}


# ── Wrangles ─────────────────────────────────────────────────────────────────

def _float_as_numeric(value):
    """A float8 cast to Postgres' numeric: rounded to 15 significant digits, as float8_numeric does."""
    return Decimal(format(float(value), ".15g"))


def imputation_value(table, column):
    """
    What an impute of the column fills with: the mean of a numeric column's present values, or the most common
    present value of any other column, a tie going to the first by name. None when the column has no present values.

    The mean is exact, as Postgres' AVG over numeric is, then stored in the column's type - see stored_fill.
    """
    present = []
    for value in table.values(column):
        if not is_missing(value):
            present.append(value)
    if not present:
        return None

    if column in table.numeric_cols:
        total = Decimal(0)
        for value in present:
            total += _float_as_numeric(value)
        return total / Decimal(len(present))

    counts = {}
    for value in present:
        text = as_text(value)
        counts[text] = counts.get(text, 0) + 1

    def most_common_first(text):
        return -counts[text], text.encode("utf-8")

    return sorted(counts, key=most_common_first)[0]


def stored_fill(value, integer_column):
    """
    The fill value as the column stores it: an integer column rounds the mean half away from zero, as Postgres casts
    numeric to bigint; a float column keeps it as a float. The rounding is intended - a whole-number column stays
    whole-number after an impute (confirmed 2026-10-28).
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        if integer_column:
            return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))
        return float(value)
    return value


def delete_rows(table, row_ids):
    """The rows left after deleting these ids: {row id: {column: value}}."""
    doomed = set(row_ids)
    kept = {}
    for row_id, values in table.rows():
        if row_id not in doomed:
            kept[row_id] = values
    return kept


def impute_rows(table, column, row_ids, integer_column):
    """
    The rows after imputing this column on these ids: every selected row's cell is set to the fill value, missing or
    not - the wrangle fills the selection, which is the user's choice of rows.
    :return: ({row id: {column: value}}, the stored fill value)
    """
    fill = stored_fill(imputation_value(table, column), integer_column)
    selected = set(row_ids)
    result = {}
    for row_id, values in table.rows():
        updated = dict(values)
        if row_id in selected:
            updated[column] = fill
        result[row_id] = updated
    return result, fill


# ── Histograms (the main view's plots) ───────────────────────────────────────

def _axis(numbers, bin_count):
    """lo, bin width and bin count for an axis' numbers: a constant axis gets one bin a unit wide, an empty one 0..1."""
    if not numbers:
        return 0.0, 1.0 / bin_count, bin_count
    low = min(numbers)
    high = max(numbers)
    if low == high:
        return low - 0.5, 1.0, 1
    return low, (high - low) / bin_count, bin_count


def _bin_index(number, lo, width, bins):
    """
    floor((number - lo) / width), clamped to the bins, and whether the number sits so close to an edge that the
    database's arithmetic could put it either side.
    """
    position = (number - lo) / width
    index = math.floor(position)
    clamped = min(max(index, 0), bins - 1)
    nearest_edge = round(position)
    on_edge = 0 < nearest_edge < bins and near(position, nearest_edge)
    return clamped, on_edge


@dataclass
class Histogram:
    """Each bin's rows and flagged rows per error type, keyed by bin; and the rows whose bin is borderline."""
    bins: dict = field(default_factory=dict)
    numeric_edges: list = field(default_factory=list)
    labels: list = field(default_factory=list)
    borderline_rows: set = field(default_factory=set)
    row_bins: dict = field(default_factory=dict)


def _main_view_bin(table, column, value, axis):
    """A value's bin on one of the main view's axes, and whether that bin is borderline."""
    if column in table.numeric_cols:
        if is_null(value):
            return "null", False
        number = stored_number(value)
        if number is None:
            # A NaN or an infinity: its own label
            return _float_text(float(value)), False
        lo, width, bins = axis
        index, on_edge = _bin_index(number, lo, width, bins)
        return str(index), on_edge
    if is_null(value):
        return "null", False
    return as_text(value), False


def _float_text(number):
    """A float8 special value as Postgres writes it."""
    if math.isnan(number):
        return "NaN"
    if number > 0:
        return "Infinity"
    return "-Infinity"


def histogram(table, flags, columns, bin_count=10):
    """
    The main view's 1D or 2D histogram of these columns: a numeric column's numbers in bins across their range, with
    NULL and any other value as labels; a text column's every value its own label (NULL and "null" both "null"). Each
    bin counts its rows, and per error type the rows flagged on any of the plotted columns, each row once.

    :param columns: one column, or two for a heatmap
    :return: a Histogram whose bins are keyed by a tuple of bin keys, one per column
    """
    axes = []
    for column in columns:
        numbers = []
        if column in table.numeric_cols:
            for value in table.values(column):
                number = stored_number(value)
                if number is not None:
                    numbers.append(number)
        axes.append(_axis(numbers, bin_count))

    flagged_types_by_row = {}
    for row_id, column, error_type in flags.certain | flags.borderline:
        if column in columns:
            flagged_types_by_row.setdefault(row_id, set()).add(error_type)

    result = Histogram()
    lo, width, bins = axes[0]
    if columns[0] in table.numeric_cols:
        for n in range(bins):
            result.numeric_edges.append((lo + n * width, lo + (n + 1) * width))

    labels = set()
    for row_id, values in table.rows():
        key = []
        borderline = False
        for column, axis in zip(columns, axes):
            bin_key, on_edge = _main_view_bin(table, column, values[column], axis)
            key.append(bin_key)
            borderline = borderline or on_edge
            is_index = column in table.numeric_cols and bin_key.isdigit()
            if column == columns[0] and not is_index:
                labels.add(bin_key)
        key = tuple(key)
        result.row_bins[row_id] = key
        if borderline:
            result.borderline_rows.add(row_id)

        entry = result.bins.setdefault(key, {"items": 0})
        entry["items"] += 1
        for error_type in flagged_types_by_row.get(row_id, ()):
            entry[error_type] = entry.get(error_type, 0) + 1

    result.labels = sorted(labels)
    return result


# ── Comparisons ──────────────────────────────────────────────────────────────

@dataclass
class CompareAxis:
    is_numeric: bool
    lo: float
    width: float
    bins: int
    kept_labels: set
    folds: bool
    labels_in_order: list


def _compare_axis(sides, column, bin_count):
    """
    One shared axis across both tables: numeric when at least half the present values, both tables together, are
    numbers; its numbers binned across both tables' range; its other values labels, the 20 most common kept - null
    always among them - and the rest folded into (other).
    """
    present = 0
    numbers = []
    label_rows = {}
    for table in sides:
        for value in table.values(column):
            if not is_missing(value):
                present += 1
            number = table.number_of(column, value)
            if number is not None:
                numbers.append(number)

    is_numeric = present > 0 and len(numbers) * 2 >= present
    lo, width, bins = 0.0, 1.0, 0
    if is_numeric:
        lo, width, bins = _axis(numbers, bin_count)

    for table in sides:
        for value in table.values(column):
            number = table.number_of(column, value)
            if is_numeric and number is not None:
                continue
            label = label_of(value)
            label_rows[label] = label_rows.get(label, 0) + 1

    def ranking(label):
        return -label_rows[label], label.encode("utf-8")

    ranked = sorted(label_rows, key=ranking)
    folds = len(ranked) > MAX_LABELS
    if not folds:
        kept = list(ranked)
    else:
        kept = ranked[:MAX_LABELS - 1]
        if NULL_LABEL in label_rows and NULL_LABEL not in kept:
            kept[-1] = NULL_LABEL

    def by_name(label):
        return label.encode("utf-8")

    in_order = sorted(kept, key=by_name)
    if folds:
        in_order.append(OTHER_LABEL)
    return CompareAxis(is_numeric, lo, width, bins, set(kept), folds, in_order)


def _compare_bin(table, column, value, axis):
    number = table.number_of(column, value)
    if axis.is_numeric and number is not None:
        index, on_edge = _bin_index(number, axis.lo, axis.width, axis.bins)
        return ("numeric", index), on_edge
    label = label_of(value)
    if label in axis.kept_labels:
        return ("categorical", label), False
    return ("categorical", OTHER_LABEL), False


@dataclass
class Comparison:
    axes: list
    sides: dict
    rows: dict
    borderline_rows: dict


def compare(table_a, flags_a, table_b, flags_b, columns, bin_count=10):
    """
    Both tables binned on shared axes. Each side's bin counts its rows, and per error type its rows flagged on any of
    the compared columns, each row once.

    :return: a Comparison: sides {"a"/"b": {bin key tuple: {"items", type...}}}, rows {"a", "b"}, and per side the
             row ids whose bin is borderline
    """
    tables = {"a": table_a, "b": table_b}
    all_flags = {"a": flags_a, "b": flags_b}
    axes = []
    for column in columns:
        axes.append(_compare_axis([table_a, table_b], column, bin_count))

    result = Comparison(axes=axes, sides={}, rows={}, borderline_rows={})
    for side, table in tables.items():
        flagged_types_by_row = {}
        flags = all_flags[side]
        for row_id, column, error_type in flags.certain | flags.borderline:
            if column in columns:
                flagged_types_by_row.setdefault(row_id, set()).add(error_type)

        bins = {}
        borderline = set()
        for row_id, values in table.rows():
            key = []
            for column, axis in zip(columns, axes):
                bin_key, on_edge = _compare_bin(table, column, values[column], axis)
                key.append(bin_key)
                if on_edge:
                    borderline.add(row_id)
            key = tuple(key)
            entry = bins.setdefault(key, {"items": 0})
            entry["items"] += 1
            for error_type in flagged_types_by_row.get(row_id, ()):
                entry[error_type] = entry.get(error_type, 0) + 1

        result.sides[side] = bins
        result.rows[side] = len(table.frame)
        result.borderline_rows[side] = borderline
    return result


# ── Drift ────────────────────────────────────────────────────────────────────

def _numbers(table, column):
    numbers = []
    for value in table.values(column):
        number = table.number_of(column, value)
        if number is not None:
            numbers.append(number)
    return numbers


def _labels(table, column):
    labels = []
    for value in table.values(column):
        labels.append(label_of(value))
    return labels


def column_drift(root, node, column, kind):
    """
    One column's drift from root:

        numeric      W1(root's numbers, node's numbers) / root's IQR - root's sample standard deviation when its IQR is
                     zero; no value when either side has fewer than 2 numbers, or root has no spread at all
        categorical  half the summed change in each category's share, missing cells a category of their own

    :return: {"value", "reason", "n_root", "n_node"} - value None when there is a reason instead
    """
    if kind == "numeric":
        root_numbers = _numbers(root, column)
        node_numbers = _numbers(node, column)
        n_root = len(root_numbers)
        n_node = len(node_numbers)
        if n_node == 0:
            return {"value": None, "reason": "no values", "n_root": n_root, "n_node": 0}
        if n_root < 2 or n_node < 2:
            return {"value": None, "reason": "too few values", "n_root": n_root, "n_node": n_node}
        q1, q3 = np.quantile(np.asarray(root_numbers, dtype=float), [0.25, 0.75])
        scale = None
        if q3 > q1:
            scale = float(q3 - q1)
        else:
            std = float(np.std(np.asarray(root_numbers, dtype=float), ddof=1))
            if std > 0:
                scale = std
        if scale is None:
            return {"value": None, "reason": "constant column", "n_root": n_root, "n_node": n_node}
        distance = wasserstein_distance(root_numbers, node_numbers)
        # How many times larger the numbers are than the scale: every rounding error in them is magnified this much
        # in the drift, so two correct computations can differ by about this times float8's precision
        largest = 0.0
        for number in root_numbers + node_numbers:
            largest = max(largest, abs(number))
        return {"value": float(distance / scale), "reason": None, "n_root": n_root, "n_node": n_node,
                "conditioning": largest / scale}

    root_labels = _labels(root, column)
    node_labels = _labels(node, column)
    n_root = len(root_labels)
    n_node = len(node_labels)
    if n_root == 0 or n_node == 0:
        return {"value": None, "reason": "no values", "n_root": n_root, "n_node": n_node}

    root_counts = {}
    for label in root_labels:
        root_counts[label] = root_counts.get(label, 0) + 1
    node_counts = {}
    for label in node_labels:
        node_counts[label] = node_counts.get(label, 0) + 1

    total = 0.0
    for label in set(root_counts) | set(node_counts):
        root_share = root_counts.get(label, 0) / n_root
        node_share = node_counts.get(label, 0) / n_node
        total += abs(node_share - root_share)
    return {"value": 0.5 * total, "reason": None, "n_root": n_root, "n_node": n_node, "conditioning": 1.0}


def node_drift(root, node, kinds):
    """
    Every column's drift and the node's number: the mean of the columns that have a value.
    :param kinds: {column: "numeric" or "categorical"}, decided on root
    """
    columns = {}
    values = []
    for column, kind in kinds.items():
        result = column_drift(root, node, column, kind)
        columns[column] = result
        if result["value"] is not None:
            values.append(result["value"])
    overall = None
    if values:
        overall = sum(values) / len(values)
    return {"overall": overall, "columns": columns}


def cells_changed(reference, node, column):
    """
    How many of the rows both tables hold changed their cell: two NULLs are equal, two numbers are equal within
    np.isclose's tolerances, and anything else is compared as text.
    """
    reference_rows = dict(reference.rows())
    changed = 0
    for row_id, values in node.rows():
        if row_id not in reference_rows:
            continue
        before = reference_rows[row_id][column]
        after = values[column]
        if is_null(before) and is_null(after):
            continue
        if is_null(before) or is_null(after):
            changed += 1
            continue
        before_number = reference.number_of(column, before)
        after_number = node.number_of(column, after)
        if before_number is not None and after_number is not None:
            if abs(before_number - after_number) > 1e-08 + 1e-05 * abs(after_number):
                changed += 1
            continue
        if _db_text(reference, column, before) != _db_text(node, column, after):
            changed += 1
    return changed


def _db_text(table, column, value):
    """A value as ::text, for the comparisons that fall back to text. Integers read back as floats lose their .0."""
    if column in table.numeric_cols and isinstance(value, float) and value.is_integer():
        return str(int(value))
    return as_text(value)


def category_flows(root, node, column):
    """Where each of root's rows sits in the node: {(source label, target label or (removed)): rows}."""
    node_rows = dict(node.rows())
    flows = {}
    for row_id, values in root.rows():
        source = label_of(values[column])
        if row_id in node_rows:
            target = label_of(node_rows[row_id][column])
        else:
            target = REMOVED_LABEL
        flows[(source, target)] = flows.get((source, target), 0) + 1
    return flows
