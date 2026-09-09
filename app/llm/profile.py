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
from app.db_utils.execute_sql import fetch_sql
from app.pgraph.metrics import _parse_error_counts
from app.llm.tools import MAX_ENUM_COLUMNS

# Structural columns. "ID" is the row identifier and the others are pandas leftovers; none of
# them is data the user would ever want repaired.
STRUCTURAL_COLUMNS = ("ID", "Original_ID", "index", "level_0")

# A column with more distinct values than this is almost certainly free text that the profiler
# has typed as categorical. Listing its categories would flood the prompt, so only the count goes.
MAX_CATEGORIES_TO_DESCRIBE = 50
TOP_CATEGORIES = 8
MAX_LABEL_CHARS = 40

DIMENSIONS = ("missing", "mismatch", "anomaly", "incomplete")


def _fmt(value) -> str:
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


def _categories(raw) -> tuple[list[tuple[str, int]], int]:
    counts = _parse_error_counts(raw)
    if not counts:
        return [], 0
    ordered = sorted(counts.items(), key=lambda kv: -int(kv[1] or 0))
    return ordered[:TOP_CATEGORIES], max(0, len(ordered) - TOP_CATEGORIES)


def _flags_cell(counts: dict[str, Any]) -> tuple[str, int]:
    parts = [f"{d}={int(counts[d])}" for d in DIMENSIONS if int(counts.get(d, 0) or 0) > 0]
    total = sum(int(counts.get(d, 0) or 0) for d in DIMENSIONS)
    return (", ".join(parts) if parts else "(none)"), total


def _stats_cell(row: dict[str, Any]) -> tuple[str, str]:
    """Returns (kind, description). A column is numeric exactly when it has a mean."""
    if row.get("mean") is not None:
        stats = " ".join(
            f"{name}={_fmt(row.get(name))}" for name in ("mean", "median", "min", "max")
        )
        return "numeric", stats

    bits = []
    if row.get("n_categories") is not None:
        bits.append(f"{int(row['n_categories'])} categories")
    if row.get("mode") is not None:
        bits.append(f'mode="{str(row["mode"])[:MAX_LABEL_CHARS]}"')

    n_categories = row.get("n_categories")
    if n_categories is not None and int(n_categories) <= MAX_CATEGORIES_TO_DESCRIBE:
        top, remaining = _categories(row.get("category_counts"))
        if top:
            listed = ", ".join(
                f"{str(label)[:MAX_LABEL_CHARS]}={int(count)}" for label, count in top
            )
            bits.append(listed + (f" (+{remaining} more)" if remaining else ""))

    return "categorical", "; ".join(bits) if bits else "-"


def read_profile_rows(node_table: str) -> list[dict[str, Any]]:
    """One dict per real column of dp_<node_table>, structural columns dropped."""
    placeholders = ", ".join(f"'{c}'" for c in STRUCTURAL_COLUMNS)
    rows = fetch_sql(
        f'''SELECT column_name, mean, median, min, max, n_categories, mode,
                   error_counts, category_counts
            FROM "dp_{node_table}"
            WHERE column_name NOT IN ({placeholders})
            ORDER BY column_name''',
        False,
        engine,
    )
    keys = ["column_name", "mean", "median", "min", "max", "n_categories", "mode",
            "error_counts", "category_counts"]
    return [dict(zip(keys, row)) for row in (rows or [])]


def build_profile_block(node_table: str) -> tuple[str, list[str]]:
    """
    :return: (the text the model reads, the column names it may name)

    The two are kept in step on purpose: the tool enums are built from the same list, so the
    model can never name a column it was not shown.
    """
    from app import db_operations

    rows = read_profile_rows(node_table)
    row_count = int(db_operations.get_row_count(node_table))

    described = []
    for row in rows:
        counts = _parse_error_counts(row.get("error_counts"))
        flags, total = _flags_cell(counts)
        kind, stats = _stats_cell(row)
        described.append({
            "name": str(row["column_name"]),
            "kind": kind,
            "flags": flags,
            "stats": stats,
            "total": total,
        })

    # A very wide table would spend the whole prompt on its enums, so keep the columns that
    # actually carry flags and say plainly that the rest were left out.
    omitted = 0
    if len(described) > MAX_ENUM_COLUMNS:
        described.sort(key=lambda c: -c["total"])
        omitted = len(described) - MAX_ENUM_COLUMNS
        described = described[:MAX_ENUM_COLUMNS]
        described.sort(key=lambda c: c["name"])

    columns = [c["name"] for c in described]

    # Widths cover the headers too, or the header row runs wider than the rows beneath it
    name_width = max([len(c["name"]) for c in described] + [len("name")])
    flag_width = max([len(c["flags"]) for c in described] + [len("flagged cells")])
    kind_width = len("categorical")

    lines = [
        f"table: {node_table}",
        f"rows: {row_count}",
        f"columns: {len(described)} (the row identifier is not shown and cannot be repaired)",
        "",
        f"{'name'.ljust(name_width)} | {'kind'.ljust(kind_width)} | "
        f"{'flagged cells'.ljust(flag_width)} | statistics",
    ]
    for c in described:
        lines.append(
            f"{c['name'].ljust(name_width)} | {c['kind'].ljust(kind_width)} | "
            f"{c['flags'].ljust(flag_width)} | {c['stats']}"
        )

    if omitted:
        lines.append("")
        lines.append(f"({omitted} further columns omitted - they carry the fewest flagged cells.)")

    return "\n".join(lines), columns
