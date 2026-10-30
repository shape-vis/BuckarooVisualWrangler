"""
Adversarial datasets for the stress tests - October 28, 2026.

Every dataset is built from a seed, so a failure names the seed that reproduces it. A dataset is a handful of columns,
each with a "personality": a kind of data aimed at one of the rules the app reads values by. Some aim at the
detectors' thresholds (fewer than ten numbers, a constant column, values occurring once or twice), some at how a value
is read (numbers stored as text, words that look like numbers, the missing tokens), and some at how names and labels
travel through SQL (quotes, unicode, reserved words).

The values are plain Python: str, int, float or None. How they reach the database is the test's choice - through a
CSV and the upload path, exactly as a user's file does, or stored as they are, which keeps values a CSV cannot carry
(an empty string, the text "null").
"""
import random
from dataclasses import dataclass, field

# How many rows a dataset can have. Most are small, so a run covers many seeds quickly; the rest reach the size of a
# real upload. The largest stays under the 10k rows the tests are asked to cover.
ROW_COUNTS = (1, 2, 3, 9, 10, 11, 25, 60, 150, 400, 1200, 3000)
LARGE_ROW_COUNT = 9000

# Names a column can be given. Each one has broken a query builder somewhere in some codebase: spaces, both kinds of
# quote, a reserved word, a name the missing rule would read as missing, case that only quoting keeps, unicode, and
# characters that mean something to SQL or to a URL.
COLUMN_NAMES = (
    "Critic_Count", "Critic_Score", "amount", "City", "with space", 'quote"name', "apos'name", "select", "null",
    "Ünïcödé", "%pct", "a.b", "semi;colon", "dash-name", "MixedCase", "x", "y", "group", "order by", "Original_ID",
)

# Labels with characters that have to survive SQL literals, JSON and CSV
WEIRD_LABELS = (
    "naïve", "日本語", "emoji 🙂", "quote\"d", "apos'd", "comma, inside", "percent%", "back\\slash", "tab\tinside",
    "  padded  ", "UPPER", "upper", "NULL", "None", "NaN", "true", "false",
    # Spelled like the app's own catch-all and removed sink, which the app shows quoted - see SENTINEL_LOOKALIKE_REGEX
    "(other)", "(removed)", '"(other)"',
)

# Text that looks like a number to one reader and not to another
NUMBER_LOOKALIKES = (
    "007", "1.50", "1e3", "+5", ".5", "5.", "-4", " 7 ", "1,000", "0x1F", "inf", "-0", "3.14159", "٣",
)

# Numbers padded with unicode spaces - a non-breaking space pasted from a spreadsheet - which are text, not numbers
UNICODE_SPACED_NUMBERS = ("\u00a05", "5\u00a0", "\u20035", "\u30005")

# The cells the Missing detector calls missing, and text that only looks missing
MISSING_TOKENS = ("null", "undefined")
NOT_MISSING_LOOKALIKES = ("", "none", "NULL", "None", "N/A", "nan", " ")


@dataclass
class Dataset:
    """A generated dataset: its name, its columns in order and each column's personality."""
    seed: int
    name: str
    columns: dict = field(default_factory=dict)
    personalities: dict = field(default_factory=dict)

    @property
    def row_count(self):
        for values in self.columns.values():
            return len(values)
        return 0


def _with_missing(rng, values, share):
    """Blank out roughly this share of the values, as None."""
    blanked = []
    for value in values:
        if rng.random() < share:
            blanked.append(None)
        else:
            blanked.append(value)
    return blanked


# ── Column personalities ─────────────────────────────────────────────────────
# Each takes (rng, row_count) and returns that many values.

def normal_floats(rng, n):
    mean = rng.choice([0.0, 50.0, -1000.0, 1e6])
    spread = rng.choice([0.001, 1.0, 15.0, 2500.0])
    values = []
    for _ in range(n):
        values.append(round(rng.gauss(mean, spread), 3))
    return _with_missing(rng, values, rng.choice([0.0, 0.05, 0.3]))


def integers(rng, n):
    low = rng.choice([0, -50, 1000])
    values = []
    for _ in range(n):
        values.append(rng.randint(low, low + rng.choice([5, 100, 10000])))
    return _with_missing(rng, values, rng.choice([0.0, 0.1, 0.5]))


def with_outliers(rng, n):
    """Mostly tight integers, with a few far out: the anomaly detector's case."""
    values = []
    for _ in range(n):
        if rng.random() < 0.04:
            values.append(rng.choice([10 ** 6, -(10 ** 6), 99999]))
        else:
            values.append(rng.randint(40, 60))
    return _with_missing(rng, values, 0.05)


def constant(rng, n):
    """One value throughout: no spread for the anomaly detector, no IQR for drift."""
    value = rng.choice([0, 7, 3.5, -2])
    values = []
    for _ in range(n):
        values.append(value)
    return _with_missing(rng, values, rng.choice([0.0, 0.2]))


def few_numbers(rng, n):
    """Fewer than ten numbers, the rest missing: below the anomaly detector's threshold, inside incomplete's."""
    values = []
    for index in range(n):
        if index < 9 and rng.random() < 0.8:
            values.append(rng.randint(1, 4))
        else:
            values.append(None)
    return values


def extreme_floats(rng, n):
    """Very large and very small magnitudes side by side."""
    choices = (1e15, -1e15, 1e-12, 123456789.123, 0.1, 0.2, 0.30000000000000004, 2 ** 53, -(2 ** 31))
    values = []
    for _ in range(n):
        values.append(rng.choice(choices))
    return _with_missing(rng, values, 0.1)


def numbers_as_text_mostly(rng, n):
    """Mostly numbers written as text, with a few words: a numeric column with type mismatches."""
    values = []
    for _ in range(n):
        if rng.random() < 0.85:
            values.append(str(rng.randint(1, 30)))
        else:
            values.append(rng.choice(["abc", "n/a", "unknown", "tbd"]))
    return _with_missing(rng, values, 0.05)


def text_mostly_some_numbers(rng, n):
    """Mostly words with a few numbers: a categorical column with type mismatches."""
    values = []
    for _ in range(n):
        if rng.random() < 0.2:
            values.append(str(rng.randint(1, 9)))
        else:
            values.append(rng.choice(["red", "green", "blue", "teal"]))
    return _with_missing(rng, values, 0.05)


def even_split(rng, n):
    """Half numbers, half words: where a tie between the kinds is decided."""
    values = []
    for index in range(n):
        if index % 2 == 0:
            values.append(str(index))
        else:
            values.append("word")
    rng.shuffle(values)
    return values


def few_categories(rng, n):
    labels = ["E", "T", "M", "E10+", "AO"]
    weights = [50, 25, 15, 9, 1]
    return _with_missing(rng, rng.choices(labels, weights=weights, k=n), rng.choice([0.0, 0.1]))


def tied_categories(rng, n):
    """Categories with equal counts, so every tie-break - the mode, the label ranking - is exercised."""
    labels = ["b", "a", "B", "A", "_x"]
    values = []
    for index in range(n):
        values.append(labels[index % len(labels)])
    rng.shuffle(values)
    return values


def many_categories(rng, n):
    """More labels than any axis keeps, so the long tail folds into (other)."""
    label_count = rng.choice([21, 30, 60])
    values = []
    for _ in range(n):
        values.append(f"label_{rng.randint(1, label_count):02d}")
    return _with_missing(rng, values, rng.choice([0.0, 0.03]))


def rare_categories(rng, n):
    """Mostly values occurring once or twice: the incomplete detector's case."""
    values = []
    for _ in range(n):
        values.append(f"rare_{rng.randint(1, max(2, n))}")
    return values


def weird_labels(rng, n):
    values = []
    for _ in range(n):
        values.append(rng.choice(WEIRD_LABELS))
    return _with_missing(rng, values, 0.05)


def number_lookalikes(rng, n):
    choices = NUMBER_LOOKALIKES + UNICODE_SPACED_NUMBERS
    values = []
    for _ in range(n):
        values.append(rng.choice(choices))
    return values


def missing_tokens(rng, n):
    """The missing tokens, text that only looks missing, and real labels."""
    choices = MISSING_TOKENS + NOT_MISSING_LOOKALIKES + ("cat", "dog", "cat")
    values = []
    for _ in range(n):
        values.append(rng.choice(choices))
    return _with_missing(rng, values, 0.1)


def all_missing(rng, n):
    values = []
    for _ in range(n):
        values.append(None)
    return values


PERSONALITIES = {
    "normal_floats": normal_floats,
    "integers": integers,
    "with_outliers": with_outliers,
    "constant": constant,
    "few_numbers": few_numbers,
    "extreme_floats": extreme_floats,
    "numbers_as_text_mostly": numbers_as_text_mostly,
    "text_mostly_some_numbers": text_mostly_some_numbers,
    "even_split": even_split,
    "few_categories": few_categories,
    "tied_categories": tied_categories,
    "many_categories": many_categories,
    "rare_categories": rare_categories,
    "weird_labels": weird_labels,
    "number_lookalikes": number_lookalikes,
    "missing_tokens": missing_tokens,
    "all_missing": all_missing,
}

# Personalities whose values a CSV carries faithfully. The others hold text pandas' read_csv turns into something
# else - "null" and "" become NaN, "1e3" a float - which the upload path is tested on separately.
CSV_SAFE = ("normal_floats", "integers", "with_outliers", "constant", "few_numbers", "numbers_as_text_mostly",
            "text_mostly_some_numbers", "even_split", "few_categories", "tied_categories", "many_categories",
            "rare_categories", "all_missing")


def row_count_for(seed):
    """Every twentieth seed is large; the rest cycle through the small and mid sizes."""
    if seed % 20 == 19:
        return LARGE_ROW_COUNT
    return ROW_COUNTS[seed % len(ROW_COUNTS)]


def make_dataset(seed, personalities=None, row_count=None, column_count=None):
    """
    A dataset for one seed.

    :param personalities: the personalities to choose columns from - all of them by default
    :param row_count: how many rows - row_count_for(seed) by default
    :param column_count: how many columns - three to six by default
    :return: a Dataset
    """
    rng = random.Random(seed)
    if personalities is None:
        personalities = list(PERSONALITIES)
    if row_count is None:
        row_count = row_count_for(seed)
    if column_count is None:
        column_count = rng.randint(3, 6)

    names = rng.sample(COLUMN_NAMES, column_count)
    dataset = Dataset(seed=seed, name=f"stress_{seed}")
    for name in names:
        personality = rng.choice(personalities)
        dataset.columns[name] = PERSONALITIES[personality](rng, row_count)
        dataset.personalities[name] = personality
    return dataset


def csv_text(dataset):
    """The dataset as a CSV file's text: None as an empty field, as a spreadsheet writes it."""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(list(dataset.columns))
    for row_index in range(dataset.row_count):
        row = []
        for values in dataset.columns.values():
            value = values[row_index]
            if value is None:
                row.append("")
            else:
                row.append(value)
        writer.writerow(row)
    return buffer.getvalue()
