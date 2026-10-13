"""
The database half of the AI suggestion workflow.

Nothing in here talks to a model. A suggestion arrives as a plain dict - the shape a tool call
produces - and this module decides whether it is safe, which rows it touches, and how to run it
through the wrangle pipeline the manual path already uses.

The invariant everything here exists to enforce:

    An AI-suggested operation acts only on rows that errors_<table> flags for the column(s)
    that operation touches. A row with no flag in those columns is never in the id set - not
    for an impute, not for a delete.

That is what keeps this from being NLP-to-SQL. The model picks an operation and a column out of
a closed enum; it never names a row, never writes SQL, and never chooses a fill value.
resolve_ids_for is the single place an id set may be built, so there is no path around the rule.
"""
from dataclasses import dataclass, field
from typing import Any

import app
from app.db_utils import query
from app.server_utils import candidates
from app.server_utils.service_helpers import WRANGLE_LOCK, session_graph

# The four flags the detectors produce. Matches DIMENSIONS in app/pgraph/metrics.py and
# ERROR_DIMENSIONS in ui/src/store/errorColors.js.
ERROR_TYPES = ("missing", "mismatch", "anomaly", "incomplete")

# Deleting is destructive and cannot be undone at the table level, so a suggestion that would
# take out more than this share of the table is refused rather than offered.
MAX_DELETE_FRACTION = 0.30


class SuggestionError(ValueError):
    """A suggestion that cannot be run. The message is shown to the user, so keep it plain."""


@dataclass(frozen=True)
class Op:
    """
    One wrangle operation, as both the model and the pipeline see it.
    """
    kind: str               # "impute" or "delete" - also the wrangle a node records, but for a 2D impute
    dims: int               # 1 or 2 columns


TOOL_OPS: dict[str, Op] = {
    "impute_rows":    Op(kind="impute", dims=1),
    "delete_rows":    Op(kind="delete", dims=1),
    # Which column of the pair it fills is picked from `target` - see Suggestion.wrangle_op
    "impute_rows_2d": Op(kind="impute", dims=2),
    "delete_rows_2d": Op(kind="delete", dims=2),
}


@dataclass
class Suggestion:
    """A validated tool call. Only ever built by validate_suggestion."""
    op: str
    columns: list[str]                  # 1 or 2, in the order the model gave them
    error_type: str
    target: str | None = None           # "x" or "y", 2D impute only
    reason: str = ""
    row_ids: list[int] = field(default_factory=list)   # filled by resolve_ids_for

    @property
    def spec(self) -> Op:
        return TOOL_OPS[self.op]

    @property
    def imputed_column(self) -> str | None:
        """The one column an impute writes to. None for deletes."""
        if self.spec.kind != "impute":
            return None
        if self.op == "impute_rows_2d" and self.target == "y":
            return self.columns[1]
        return self.columns[0]

    @property
    def wrangle_op(self) -> str:
        """The wrangle as a node records it: delete, impute, or impute_x / impute_y for one column of a pair."""
        if self.op == "impute_rows_2d":
            return f"impute_{self.target}"
        return self.spec.kind

    def label(self) -> str:
        """Matches format_wrangle_label, so a candidate reads like the node it becomes."""
        from app.pgraph.node import format_wrangle_label
        return format_wrangle_label(self.wrangle_op, self.columns)

    def to_json(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "columns": self.columns,
            "error_type": self.error_type,
            "target": self.target,
            "reason": self.reason,
            "row_count": len(self.row_ids),
            "label": self.label(),
        }


def known_node(node_table: str) -> bool:
    """A table is addressable only if the graph knows it and it really exists."""
    graph = session_graph()
    if graph is None or node_table not in graph.node_map:
        return False
    return bool(app.db_operations.table_exists(node_table))


def validate_suggestion(node_table: str, raw: dict[str, Any], columns: list[str]) -> Suggestion:
    """
    Re-derive a suggestion from scratch, trusting nothing in `raw`.

    The model's output is a tool call, so nothing in it is taken on trust: every field is checked against the
    closed sets the model was offered.

    :param columns: the node's real column names - the enum the model was given
    """
    op = raw.get("op")
    if op not in TOOL_OPS:
        raise SuggestionError(f"unknown operation {op!r}")
    spec = TOOL_OPS[op]

    error_type = raw.get("error_type")
    if error_type not in ERROR_TYPES:
        raise SuggestionError(f"unknown error type {error_type!r}")

    # Accept either shape - the 1D tools use `column`, the 2D tools use `columns`
    if spec.dims == 1 and raw.get("column"):
        cols = [raw["column"]]
    else:
        cols = list(raw.get("columns") or [])

    if len(cols) != spec.dims:
        raise SuggestionError(f"{op} needs {spec.dims} column(s), got {len(cols)}")
    if len(set(cols)) != len(cols):
        raise SuggestionError(f"{op} needs distinct columns, got {cols}")

    unknown = []
    for col in cols:
        if col not in columns:
            unknown.append(str(col))
    if unknown:
        unknown_list = ", ".join(unknown)
        raise SuggestionError(f"no such column in {node_table}: {unknown_list}")

    target = raw.get("target")
    if op == "impute_rows_2d":
        if target not in ("x", "y"):
            raise SuggestionError(f"impute_rows_2d needs target 'x' or 'y', got {target!r}")
    else:
        target = None

    reason = str(raw.get("reason") or "").strip()

    return Suggestion(op=op, columns=cols, error_type=error_type, target=target, reason=reason)


def columns_for_ids(suggestion: Suggestion) -> list[str]:
    """
    Which columns' flags pick out the rows this operation touches.

    This is the invariant in one function. An impute writes exactly one column, so only that
    column's flagged rows may be in its id set - otherwise a 2D impute would overwrite a good
    value in a row whose only problem was in the *other* column. A delete removes whole rows,
    so for the 2D form the union is right: every row in it is still a flagged row.
    """
    if suggestion.spec.kind == "impute":
        return [suggestion.imputed_column]
    return list(suggestion.columns)


def resolve_ids_for(node_table: str, suggestion: Suggestion) -> list[int]:
    """
    The only place an id set is built. Returns the flagged row ids, ascending - only rows that are still in the
    table.
    """
    cols = columns_for_ids(suggestion)
    return query.flagged_row_ids(node_table, cols, suggestion.error_type)


def guard(node_table: str, suggestion: Suggestion) -> None:
    """
    Refuse a suggestion that would do more harm than good. Runs before any table is cloned.

    Raises SuggestionError with a message meant for the user.
    """
    ids = suggestion.row_ids
    columns = ", ".join(columns_for_ids(suggestion))

    if not ids:
        raise SuggestionError(f"no rows in {columns} carry a {suggestion.error_type} flag")

    row_count = int(app.db_operations.get_row_count(node_table))
    if row_count <= 0:
        raise SuggestionError(f"{node_table} has no rows")

    if suggestion.spec.kind == "delete":
        if len(ids) >= row_count:
            raise SuggestionError(
                f"that would delete all {row_count} rows and leave an empty table"
            )
        share = len(ids) / row_count
        if share > MAX_DELETE_FRACTION:
            raise SuggestionError(
                f"that would delete {len(ids)} of {row_count} rows "
                f"({share:.0%}); more than {MAX_DELETE_FRACTION:.0%} is refused"
            )
        return

    # Impute: there has to be something clean left to derive a fill value from.
    if len(ids) >= row_count:
        raise SuggestionError(
            f"every row in {columns} is flagged, so imputing would set them all to one constant"
        )

    col = suggestion.imputed_column
    try:
        # The same value impute_by_ids will fill with, so the guard and the write cannot disagree
        fill = query.imputation_value(node_table, col)
    except Exception as exc:
        raise SuggestionError(f"could not compute a fill value for {col}: {exc}") from exc

    if fill is None:
        raise SuggestionError(f"{col} has no clean values to compute a fill from")


def prepare(node_table: str, raw: dict[str, Any], columns: list[str]) -> Suggestion:
    """validate -> resolve -> guard. Returns a suggestion carrying its resolved row ids."""
    suggestion = validate_suggestion(node_table, raw, columns)
    suggestion.row_ids = resolve_ids_for(node_table, suggestion)
    guard(node_table, suggestion)
    return suggestion


def suggestion_spec(suggestion: Suggestion) -> candidates.CandidateSpec:
    """
    A prepared suggestion as a candidate to stage - built the same way a repair of a selection is
    (app/server_utils/candidates.py). Only where it came from differs: the model's reason and the flag it targets
    ride along, and the row count is the server's, never the model's claim.
    """
    if len(suggestion.columns) == 1:
        chart_type = "histogram"
    else:
        chart_type = "heatmap"

    meta = {
        "label": suggestion.label(),
        "reason": suggestion.reason,
        "row_count": len(suggestion.row_ids),
        "error_type": suggestion.error_type,
        "chart_type": chart_type,
        # Kept so the suggestion can be told apart from its siblings, and re-checked if ever needed
        "suggestion": {"op": suggestion.op, "columns": suggestion.columns, "target": suggestion.target,
                       "error_type": suggestion.error_type},
    }
    return candidates.CandidateSpec(
        op=suggestion.wrangle_op,
        cols=list(suggestion.columns),
        row_ids=suggestion.row_ids,
        imputed_column=suggestion.imputed_column,
        source="ai",
        meta=meta,
    )


def stage_suggestion(node_table: str, suggestion: Suggestion) -> dict[str, Any]:
    """
    Stage one prepared suggestion as a candidate - a provisional node under node_table.

    :return: the candidate, as candidates.candidate_json gives it
    """
    return candidates.stage_all(node_table, [suggestion_spec(suggestion)])[0]


def stage_suggestions(node_table: str, suggestions: list[Suggestion]):
    """
    Stage prepared suggestions as candidates, all built at once. Each is the model's own proposal, so each that
    builds is staged whether or not the others do.

    :return: (the staged candidates, in the suggestions' order, and [(suggestion, error)] for each that could not
             be built)
    """
    specs = []
    # Keyed by id() because a CandidateSpec, a plain dataclass, can't be hashed: it says which suggestion a failed
    # spec came from
    suggestion_of_spec = {}
    for suggestion in suggestions:
        spec = suggestion_spec(suggestion)
        specs.append(spec)
        suggestion_of_spec[id(spec)] = suggestion

    staged, failed_specs = candidates.stage_each(node_table, specs)

    failures = []
    for spec, error in failed_specs:
        failures.append((suggestion_of_spec[id(spec)], error))
    return staged, failures


def apply_suggestion(node_table: str, raw: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    """
    Run a suggestion for real in one step: stage it as a candidate, then accept it, leaving the session on the
    node that results. The UI stages and accepts separately; this is the two together.

    Branches from node_table whatever the current node happens to be, so accepting one suggestion does not
    invalidate the others - the parent table is never modified.

    :return: {"table": <new node table name>, "row_count": <rows the wrangle touched>, ...}
    """
    if not known_node(node_table):
        raise SuggestionError(f"{node_table} is not a node in this session's graph")

    with WRANGLE_LOCK:
        suggestion = prepare(node_table, raw, columns)
        try:
            staged = stage_suggestion(node_table, suggestion)
        except candidates.CandidateError as exc:
            raise SuggestionError(str(exc)) from exc
        result = candidates.accept(staged["table"])

    return {
        "success": True,
        "table": result["table"],
        "parent": node_table,
        "row_count": len(suggestion.row_ids),
        "label": suggestion.label(),
    }
