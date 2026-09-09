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
from app import engine
from app.db_utils import query
from app.db_utils.execute_sql import fetch_sql
from app.server_utils.service_helpers import (
    WRANGLE_LOCK,
    _clone_table_pair,
    _safe_pg_name,
    clicked_node_access_helper,
    execute_wrangle_preview,
)

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

    preview_suffix is the contract with execute_wrangle_preview: that function reads the
    operation back off the preview table's *name* via extract_preview_action, so naming the
    preview correctly is the only thing needed to make the promote path behave.
    """
    kind: str               # "impute" or "delete"
    dims: int               # 1 or 2 columns
    preview_suffix: str     # "_preview_delete", "_preview_impute", "_preview_impute_x", ...


OPS: dict[str, Op] = {
    "impute_rows":    Op(kind="impute", dims=1, preview_suffix="_preview_impute"),
    "delete_rows":    Op(kind="delete", dims=1, preview_suffix="_preview_delete"),
    # The _x / _y suffix is picked from `target` by Suggestion.preview_suffix.
    "impute_rows_2d": Op(kind="impute", dims=2, preview_suffix="_preview_impute_x"),
    "delete_rows_2d": Op(kind="delete", dims=2, preview_suffix="_preview_delete"),
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
        return OPS[self.op]

    @property
    def preview_suffix(self) -> str:
        if self.op == "impute_rows_2d":
            return "_preview_impute_x" if self.target == "x" else "_preview_impute_y"
        return self.spec.preview_suffix

    @property
    def imputed_column(self) -> str | None:
        """The one column an impute writes to. None for deletes."""
        if self.spec.kind != "impute":
            return None
        if self.op == "impute_rows_2d":
            return self.columns[0] if self.target == "x" else self.columns[1]
        return self.columns[0]

    def label(self) -> str:
        """Matches format_wrangle_label, so a prospective node reads like the node it becomes."""
        from app.pgraph.node import format_wrangle_label
        wrangle_op = {
            "_preview_delete": "delete",
            "_preview_impute": "impute",
            "_preview_impute_x": "impute_x",
            "_preview_impute_y": "impute_y",
        }[self.preview_suffix]
        return format_wrangle_label(wrangle_op, self.columns)

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


def session_graph():
    """
    The session's PGraph, or None before anything has been uploaded.

    getattr rather than a plain attribute read: app/__init__.py's `app.pgraph_for_session = None`
    sets that on the *Flask object*, which happens to be named `app` inside that module. The
    attribute this reads is on the app *package*, and init_pgraph_for_session is what creates it -
    so until the first upload it does not exist at all.
    """
    return getattr(app, "pgraph_for_session", None)


def known_node(node_table: str) -> bool:
    """A table is addressable only if the graph knows it and it really exists."""
    graph = session_graph()
    if graph is None or node_table not in graph.node_map:
        return False
    return bool(app.db_operations.table_exists(node_table))


def validate_suggestion(node_table: str, raw: dict[str, Any], columns: list[str]) -> Suggestion:
    """
    Re-derive a suggestion from scratch, trusting nothing in `raw`.

    Runs on the model's output *and* again on whatever the client posts back to /accept, so a
    tampered payload can do nothing the model could not have asked for in the first place.

    :param columns: the node's real column names - the enum the model was given
    """
    op = raw.get("op")
    if op not in OPS:
        raise SuggestionError(f"unknown operation {op!r}")
    spec = OPS[op]

    error_type = raw.get("error_type")
    if error_type not in ERROR_TYPES:
        raise SuggestionError(f"unknown error type {error_type!r}")

    # Accept either shape - the 1D tools use `column`, the 2D tools use `columns`
    if spec.dims == 1:
        cols = [raw["column"]] if raw.get("column") else list(raw.get("columns") or [])
    else:
        cols = list(raw.get("columns") or [])

    if len(cols) != spec.dims:
        raise SuggestionError(f"{op} needs {spec.dims} column(s), got {len(cols)}")
    if len(set(cols)) != len(cols):
        raise SuggestionError(f"{op} needs distinct columns, got {cols}")

    unknown = [c for c in cols if c not in columns]
    if unknown:
        raise SuggestionError(f"no such column in {node_table}: {', '.join(map(str, unknown))}")

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
    The only place an id set is built. Returns the flagged row ids, ascending.

    The join against the data table is the same idiom remove_flagged_rows_in_1d_bin uses, and it
    drops any error row whose row_id no longer names a live row.
    """
    cols = columns_for_ids(suggestion)
    errors_table = query._get_errors_table(node_table)

    rows = fetch_sql(
        f'''SELECT DISTINCT e.row_id
            FROM "{errors_table}" e
            JOIN "{node_table}" t ON t."ID" = e.row_id
            WHERE e.column_id = ANY(:cols) AND e.error_type = :etype
            ORDER BY e.row_id''',
        False,
        engine,
        {"cols": cols, "etype": suggestion.error_type},
    )
    # Cast explicitly - psycopg2 cannot adapt numpy integer types on the way back out
    return [int(r[0]) for r in (rows or [])]


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
    with engine.connect() as conn:
        try:
            is_numeric = query._is_numeric(conn, col, node_table)
        except Exception as exc:
            raise SuggestionError(f"could not read the type of {col}: {exc}") from exc
        # The same call impute_by_ids will make, so the guard and the write cannot disagree
        fill = query._compute_imputation_value(conn, node_table, col, is_numeric)

    if fill is None:
        raise SuggestionError(f"{col} has no clean values to compute a fill from")


def prepare(node_table: str, raw: dict[str, Any], columns: list[str]) -> Suggestion:
    """validate -> resolve -> guard. Returns a suggestion carrying its resolved row ids."""
    suggestion = validate_suggestion(node_table, raw, columns)
    suggestion.row_ids = resolve_ids_for(node_table, suggestion)
    guard(node_table, suggestion)
    return suggestion


def create_preview_for_op(node_table: str, suggestion: Suggestion) -> str:
    """
    Build the single preview table this suggestion needs, and return its name.

    create_previews_1d/2d build every preview a user *might* pick - two tables for 1D, three for
    2D - and re-run detection over each. An accept has already picked one, so the rest is waste:
    detection walks the whole table per preview. This builds just the one.

    The name is the contract. execute_wrangle_preview reads the operation back off the preview's
    name, so as long as it is <parent><suffix> the promote path is unchanged.
    """
    preview = _safe_pg_name(node_table, suggestion.preview_suffix)
    errors_src = query._get_errors_table(node_table)

    with engine.begin() as conn:
        _clone_table_pair(conn, node_table, preview, errors_src)

    if suggestion.spec.kind == "delete":
        query.remove_rows_by_ids(table=preview, ids=suggestion.row_ids)
    else:
        query.impute_by_ids(
            table=preview, col=suggestion.imputed_column, ids=suggestion.row_ids
        )

    # Imported here rather than at module scope: routes are auto-imported alphabetically, so
    # ai_routes loads before wrangler_routes_sql.
    from app.routes.wrangler_routes_sql import update_errors_table
    update_errors_table(preview)

    return preview


def apply_suggestion(node_table: str, raw: dict[str, Any], columns: list[str]) -> dict[str, Any]:
    """
    Run a suggestion for real: build its preview, promote it, and leave the session pointing at
    the node that results.

    Branches from node_table whatever the current node happens to be, so accepting one suggestion
    does not invalidate the others - the parent table is never modified.

    :return: {"table": <new node table name>, "row_count": <rows the wrangle touched>, ...}
    """
    if not known_node(node_table):
        raise SuggestionError(f"{node_table} is not a node in this session's graph")

    # Everything from here to the promote has to be serialized: preview names are derived from
    # the parent and node ids are handed out by reading a counter. See WRANGLE_LOCK.
    with WRANGLE_LOCK:
        suggestion = prepare(node_table, raw, columns)

        try:
            preview = create_preview_for_op(node_table, suggestion)
            result = execute_wrangle_preview(
                node_table, preview, _safe_pg_name, app.db_operations, suggestion.columns
            )
        except Exception:
            # A throw between add_node and the rename leaves a node for a table that does not
            # exist. Put the session back on the parent so the graph and the DB agree again.
            _restore_to(node_table)
            raise

        new_table = result.get("table")

        # add_node sets prev to whatever was current, which only means "parent" when the wrangle
        # branched off the current node. This one branches off an arbitrary node, so the undo
        # cursor has to be set from the tree instead.
        clicked_node_access_helper(new_table)
        app.db_operations.load_table(
            new_table, f"errors_{new_table}", f"dp_{new_table}"
        )

    return {
        "success": True,
        "table": new_table,
        "parent": node_table,
        "row_count": len(suggestion.row_ids),
        "label": suggestion.label(),
    }


def _restore_to(node_table: str) -> None:
    """Best-effort: leave the session consistent on `node_table` after a failed accept."""
    try:
        graph = session_graph()
        if graph is not None and node_table in graph.node_map:
            clicked_node_access_helper(node_table)
        app.db_operations.load_table(
            node_table, f"errors_{node_table}", f"dp_{node_table}"
        )
    except Exception as exc:  # never mask the original failure
        print(f"[ai] could not restore session to {node_table}: {exc}")
