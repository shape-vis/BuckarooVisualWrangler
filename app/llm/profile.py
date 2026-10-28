"""
Turns a node's data profile into the block of text the model reads.

Reads dp_<table>, which the app already builds for every node, rather than re-deriving anything
from the data. The profile is where the error counts and category counts live, so this is the
cheapest honest view of a node's quality.

Rendered as a plain-text table rather than JSON: the same information costs roughly a third as
many tokens, and a small model reads a column-per-line layout at least as well.
"""
from typing import Any

from app import engine
from app.db_utils.column_types import NUMERIC_KIND
from app.db_utils.data_profile import DataProfile
from app.pgraph.metrics import DIMENSIONS, SKIPPED_COLUMNS, parse_json_counts
from app.llm.tools import MAX_ENUM_COLUMNS
from app.server_utils.service_helpers import session_graph

# A column with more distinct values than this is almost certainly free text that the profiler
# has typed as categorical. Listing its categories would flood the prompt, so only the count goes.
MAX_CATEGORIES_TO_DESCRIBE = 50
TOP_CATEGORIES = 8
MAX_LABEL_CHARS = 40

# The numeric statistics a numeric column is described by, in the order they are listed
NUMERIC_STATISTICS = ("mean", "median", "min", "max")


def _format_number(value) -> str:
    """Numbers short enough to scan; Decimals from Postgres come back as objects."""
    if value is None:
        return "?"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == int(number) and abs(number) < 1e15:
        return str(int(number))
    # Plain decimals read better than scientific notation for the ranges real columns hold;
    # fall back to %g only where fixed notation would be absurd.
    if abs(number) >= 1e9 or abs(number) < 1e-4:
        return f"{number:.4g}"
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _count_of(counts: dict[str, Any], key: str) -> int:
    """One entry of a counts dict as an int, with a missing or null entry read as 0."""
    return int(counts.get(key) or 0)


def _categories(raw) -> tuple[list[tuple[str, int]], int]:
    """
    :return: (the most common categories with their counts, most common first, and how many more there are)
    """
    counts = parse_json_counts(raw)
    if not counts:
        return [], 0

    def rows_holding(item):
        return _count_of(counts, item[0])

    ordered = sorted(counts.items(), key=rows_holding, reverse=True)
    remaining = max(0, len(ordered) - TOP_CATEGORIES)
    return ordered[:TOP_CATEGORIES], remaining


def _flags_cell(counts: dict[str, Any]) -> tuple[str, int]:
    """
    :return: (the column's flag counts per error type, e.g. "missing=3, anomaly=1", and their total)
    """
    parts = []
    total = 0
    for dimension in DIMENSIONS:
        count = _count_of(counts, dimension)
        total += count
        if count > 0:
            parts.append(f"{dimension}={count}")

    if not parts:
        return "(none)", total
    return ", ".join(parts), total


def _numeric_description(row: dict[str, Any]) -> str:
    """A numeric column's statistics, e.g. "mean=4.2 median=4 min=0 max=12"."""
    parts = []
    for name in NUMERIC_STATISTICS:
        parts.append(f"{name}={_format_number(row.get(name))}")
    return " ".join(parts)


def _category_listing(raw_counts) -> str | None:
    """The most common categories with their counts, e.g. "Male=342, Female=26 (+3 more)", or None if none."""
    top, remaining = _categories(raw_counts)
    if not top:
        return None

    entries = []
    for label, count in top:
        entries.append(f"{str(label)[:MAX_LABEL_CHARS]}={int(count)}")
    listing = ", ".join(entries)

    if remaining:
        listing += f" (+{remaining} more)"
    return listing


def _categorical_description(row: dict[str, Any]) -> str:
    """A categorical column's category count, mode and - for a column with few enough - its top categories."""
    parts = []

    n_categories = row.get("n_categories")
    if n_categories is not None:
        parts.append(f"{int(n_categories)} categories")

    mode = row.get("mode")
    if mode is not None:
        parts.append(f'mode="{str(mode)[:MAX_LABEL_CHARS]}"')

    if n_categories is not None and int(n_categories) <= MAX_CATEGORIES_TO_DESCRIBE:
        listing = _category_listing(row.get("category_counts"))
        if listing is not None:
            parts.append(listing)

    if not parts:
        return "-"
    return "; ".join(parts)


def _stats_cell(kind: str, row: dict[str, Any]) -> str:
    """The column's statistics, as its kind - by ColumnTypes.column_kind - describes it."""
    if kind == NUMERIC_KIND:
        return _numeric_description(row)
    return _categorical_description(row)


def _keep_most_flagged(described: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """
    A very wide table would spend the whole prompt on its enums, so keep the columns that actually carry flags.
    :return: (at most MAX_ENUM_COLUMNS columns, back in name order, and how many were left out)
    """
    if len(described) <= MAX_ENUM_COLUMNS:
        return described, 0

    def flagged_cells(column):
        return column["total"]

    def name_of(column):
        return column["name"]

    most_flagged = sorted(described, key=flagged_cells, reverse=True)
    kept = most_flagged[:MAX_ENUM_COLUMNS]
    kept.sort(key=name_of)
    return kept, len(described) - MAX_ENUM_COLUMNS


def _render_table(described: list[dict[str, Any]]) -> list[str]:
    """The columns as aligned text rows: name | kind | flagged cells | statistics, with a header row."""
    # Widths cover the headers too, or the header row runs wider than the rows beneath it
    name_width = len("name")
    flag_width = len("flagged cells")
    for column in described:
        name_width = max(name_width, len(column["name"]))
        flag_width = max(flag_width, len(column["flags"]))
    kind_width = len("categorical")

    header = " | ".join(["name".ljust(name_width), "kind".ljust(kind_width), "flagged cells".ljust(flag_width),
                         "statistics"])
    lines = [header]
    for column in described:
        cells = [column["name"].ljust(name_width), column["kind"].ljust(kind_width),
                 column["flags"].ljust(flag_width), column["stats"]]
        lines.append(" | ".join(cells))
    return lines


def build_profile_block(node_table: str) -> tuple[str, list[str]]:
    """
    :return: (the text the model reads, the column names it may name)

    The two are kept in step on purpose: the tool enums are built from the same list, so the
    model can never name a column it was not shown.
    """
    data_profile = DataProfile(node_table, engine)
    # A node's table never changes once built, so its row count is the one its metrics were measured over
    row_count = session_graph().node_map[node_table].metrics.row_count

    described = []
    for row in data_profile.read_stored_profile(SKIPPED_COLUMNS):
        counts = parse_json_counts(row.get("error_counts"))
        flags, total = _flags_cell(counts)
        kind = data_profile.col_types.column_kind(row["column_name"])
        stats = _stats_cell(kind, row)
        described.append({
            "name": str(row["column_name"]),
            "kind": kind,
            "flags": flags,
            "stats": stats,
            "total": total,
        })

    described, omitted = _keep_most_flagged(described)

    columns = []
    for column in described:
        columns.append(column["name"])

    lines = [
        f"table: {node_table}",
        f"rows: {row_count}",
        f"columns: {len(described)} (the row identifier is not shown and cannot be repaired)",
        "",
    ]
    lines.extend(_render_table(described))

    if omitted:
        lines.append("")
        lines.append(f"({omitted} further columns omitted - they carry the fewest flagged cells.)")

    return "\n".join(lines), columns
