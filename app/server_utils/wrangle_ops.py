"""
The wrangle operations, declared once - October 29, 2026

Every wrangle the app can make - deleting the selected rows, imputing a column in them - is one WrangleOp here, and
everything that offers, runs, records or describes a wrangle reads it from this module: the repair candidates a
selection gets (app/routes/wrangler_routes_sql.py), building a candidate's table (app/server_utils/candidates.py),
the graph's labels (app/pgraph/node.py), the AI's tools and the checks on its suggestions
(app/llm/tools.py, app/server_utils/ai_wrangle.py), and the sentence the compare panel describes a node with.

Adding a wrangle is adding one WrangleOp to WRANGLE_OPS - and to AI_TOOL_OPS if the AI should be able to suggest it -
plus the SQL that runs it, in app/db_utils/query.py. Nothing else branches on an operation's name.

How a node records its wrangle: by the op's name, "delete" or "impute". An op that fills one column, applied to a
two-column selection, records which of the pair it filled with an _x or _y suffix - "impute_y" - so the graph can
say which column it acted on. parse_wrangle_op reads either form back.

An operation edits or deletes rows the node already has, and never creates one: drift, the Sankey's removed sink and
the compare views all rely on a node's rows being a subset of root's (see distortion.check_row_identity).
"""
from dataclasses import dataclass, field
from typing import Callable

# The axes of a two-column selection, in selection order: x is its first column, y its second
AXES = ("x", "y")

# Deleting cannot be undone at the table level, so an AI suggestion that would take out more than this share of the
# table is refused rather than offered
MAX_DELETE_FRACTION = 0.30


def selected_rows_phrase(row_count):
    """How a repair's reason names its rows: "the selected row", or "the 1,204 selected rows"."""
    if row_count == 1:
        return "the selected row"
    return f"the {row_count:,} selected rows"


def _joined(columns):
    return " × ".join(columns)


@dataclass(frozen=True)
class AiTool:
    """
    One of the model's tools for an operation - see app/llm/tools.py, which declares it.

    name:                the tool's name
    description:         what the model is told the tool does
    column_description:  what it is told the column, or the pair of columns, is
    """
    name: str
    description: str
    column_description: str


@dataclass(frozen=True)
class WrangleOp:
    """
    One wrangle operation.

    name:           what a node records - see the module docstring for the _x / _y suffix
    fills_column:   whether it writes one column, which a candidate then names as its imputed_column. A two-column
                    selection gets one candidate per column for such an op, and one in all for any other.
    run:            run(table, spec) - makes the wrangle on a candidate's own copy of its parent's table. spec is the
                    candidate's CandidateSpec.
    repair_label:   repair_label(column) - the candidate's title, column None for an op that fills none
    repair_reason:  repair_reason(column, rows) - why it is offered, rows as selected_rows_phrase gives them
    description:    description(columns) - a sentence for the node it makes, columns those it acted on
    ai_tools:       {columns: AiTool} for the selection sizes the AI may suggest it on, 1 and 2 - empty for an op
                    the AI never suggests
    ai_check:       ai_check(node_table, suggestion, row_count, columns_text) - why an AI suggestion of it should be
                    refused, or None to let it through. columns_text names the columns its rows were picked by.
    """
    name: str
    fills_column: bool
    run: Callable
    repair_label: Callable
    repair_reason: Callable
    description: Callable
    ai_tools: dict = field(default_factory=dict)
    ai_check: Callable = None


# ── Delete ───────────────────────────────────────────────────────────────────

def _run_delete(table, spec):
    from app.db_utils import query

    query.remove_rows_by_ids(table=table, ids=spec.row_ids)


def _delete_label(column):
    return "Delete rows"


def _delete_reason(column, rows):
    return f"Remove {rows}"


def _delete_description(columns):
    if columns:
        return f"Deleted rows selected on {_joined(columns)}"
    return "Deleted rows"


def _delete_ai_check(node_table, suggestion, row_count, columns_text):
    ids = suggestion.row_ids
    if len(ids) >= row_count:
        return f"that would delete all {row_count} rows and leave an empty table"
    share = len(ids) / row_count
    if share > MAX_DELETE_FRACTION:
        return (f"that would delete {len(ids)} of {row_count} rows "
                f"({share:.0%}); more than {MAX_DELETE_FRACTION:.0%} is refused")
    return None


DELETE = WrangleOp(
    name="delete",
    fills_column=False,
    run=_run_delete,
    repair_label=_delete_label,
    repair_reason=_delete_reason,
    description=_delete_description,
    ai_tools={
        1: AiTool(
            name="delete_rows",
            description=(
                "Remove every row whose cell in ONE column carries the given flag. Prefer this "
                "when the flagged values cannot be reconstructed - anomalies and type mismatches "
                "usually cannot - or when very few rows are affected. Never propose it when it "
                "would remove a large share of the table."),
            column_description="The column whose flagged rows are removed.",
        ),
        2: AiTool(
            name="delete_rows_2d",
            description=(
                "Remove every row carrying the given flag in EITHER of two columns, cleaning both "
                "in one step. Use it when the two columns are related and their flagged rows "
                "overlap. Never propose it when it would remove a large share of the table."),
            column_description="Exactly two distinct columns from the profile.",
        ),
    },
    ai_check=_delete_ai_check,
)


# ── Impute ───────────────────────────────────────────────────────────────────

def _run_impute(table, spec):
    from app.db_utils import query

    query.impute_by_ids(table=table, col=spec.imputed_column, ids=spec.row_ids)


def _impute_label(column):
    return f"Impute {column}"


def _impute_reason(column, rows):
    return f"Fill {column} in {rows} with its mean, or its most common value if it is categorical"


def _impute_description(columns):
    if columns:
        return f"Imputed {_joined(columns)}"
    return "Imputed values"


def _impute_ai_check(node_table, suggestion, row_count, columns_text):
    from app.db_utils import query

    # There has to be something clean left to derive a fill value from
    if len(suggestion.row_ids) >= row_count:
        return f"every row in {columns_text} is flagged, so imputing would set them all to one constant"

    column = suggestion.imputed_column
    try:
        # The same value impute_by_ids will fill with, so the check and the write cannot disagree
        fill = query.imputation_value(node_table, column)
    except Exception as exc:
        return f"could not compute a fill value for {column}: {exc}"

    if fill is None:
        return f"{column} has no clean values to compute a fill from"
    return None


IMPUTE = WrangleOp(
    name="impute",
    fills_column=True,
    run=_run_impute,
    repair_label=_impute_label,
    repair_reason=_impute_reason,
    description=_impute_description,
    ai_tools={
        1: AiTool(
            name="impute_rows",
            description=(
                "Fill the flagged cells of ONE column, keeping every row. The fill value is that "
                "column's mean if it is numeric or its most common value if it is categorical; "
                "the server computes it, so never state a value yourself. Only the flagged cells "
                "are written - clean values in the column are left alone. Prefer this when the "
                "flagged cells are a minority and the rest of each row is worth keeping."),
            column_description="The column to repair.",
        ),
        2: AiTool(
            name="impute_rows_2d",
            description=(
                "Fill the flagged cells of ONE column of a related pair, recording that the two "
                "were considered together. 'target' says which column is repaired: 'x' is the "
                "first entry of columns, 'y' is the second. Only that column's flagged rows are "
                "touched - the other column is left completely alone. Use this instead of "
                "impute_rows only when the pair genuinely belongs together."),
            column_description="Exactly two distinct columns, in the order [x, y].",
        ),
    },
    ai_check=_impute_ai_check,
)


# ── The registry ─────────────────────────────────────────────────────────────

# Every operation, in the order a selection's repair candidates are listed
WRANGLE_OPS = (DELETE, IMPUTE)

# The operations the AI is offered, in the order its tools are declared: every one-column tool, then every
# two-column one. Imputing comes first because the system prompt prefers it - see app/llm/prompts.py.
AI_TOOL_OPS = (IMPUTE, DELETE)


def op_named(name):
    """The operation with this name, or None when there is none."""
    for op in WRANGLE_OPS:
        if op.name == name:
            return op
    return None


def parse_wrangle_op(recorded):
    """
    A wrangle as a node records it, read back: "impute_y" is (IMPUTE, "y"), "delete" is (DELETE, None).
    :return: (the WrangleOp, the axis it filled or None), or (None, None) for anything else - "root" included
    """
    op = op_named(recorded)
    if op is not None:
        return op, None

    for axis in AXES:
        suffix = "_" + axis
        if not recorded.endswith(suffix):
            continue
        op = op_named(recorded[:-len(suffix)])
        if op is not None and op.fills_column:
            return op, axis
    return None, None


def recorded_name(op, axis=None):
    """What a node records for an operation - its name, with the axis it filled on a two-column selection."""
    if axis is None:
        return op.name
    return f"{op.name}_{axis}"


def repair_options(cols, row_count):
    """
    The ways a selection can be repaired: every operation, in WRANGLE_OPS' order. An operation that fills a column
    gives one candidate for each selected column; any other gives one.
    :param cols: the selection's one or two columns, in selection order
    :return: [(recorded op, imputed column or None, label, reason)]
    """
    rows = selected_rows_phrase(row_count)
    options = []
    for op in WRANGLE_OPS:
        if not op.fills_column:
            options.append((op.name, None, op.repair_label(None), op.repair_reason(None, rows)))
            continue

        if len(cols) == 1:
            column = cols[0]
            options.append((op.name, column, op.repair_label(column), op.repair_reason(column, rows)))
            continue

        for axis, column in zip(AXES, cols):
            recorded = recorded_name(op, axis)
            options.append((recorded, column, op.repair_label(column), op.repair_reason(column, rows)))
    return options
