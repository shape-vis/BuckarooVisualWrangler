"""
The wrangle operations, declared as callable tools.

These declarations are the safety boundary. `column` is an enum built per request from the
node's real columns, so the model cannot name a column that does not exist; `error_type` is a
fixed enum; and there is no row_ids parameter at all, so the model has no way to name a row.
What it returns is a choice among enumerated operations, never a query.

The tools themselves - one per operation and selection size - come from the operations in
app/server_utils/wrangle_ops.py (AI_TOOL_OPS), so a new operation is offered by adding it there. ai_wrangle.TOOL_OPS
is built from the same list, and validates every call against it and decides which rows an operation touches.
"""
from typing import Any

from app.error_types import ERROR_TYPE_ENTRIES
from app.server_utils.ai_wrangle import ERROR_TYPES
from app.server_utils.wrangle_ops import AI_TOOL_OPS

# Called when nothing is worth repairing. toolConfig mode ANY forces at least one call, so
# without this a clean table would get invented suggestions.
NO_SUGGESTIONS = "no_suggestions"

# Beyond this many columns the enums alone would dwarf the profile, so the prompt carries only
# the worst offenders - see app/llm/profile.py.
MAX_ENUM_COLUMNS = 25

_REASON = (
    "One or two plain sentences, at most 200 characters, for someone looking at their own data: "
    "name the column, say roughly how many rows are affected, and why this repair rather than the "
    "other one. Shown to the user verbatim. Never mention tools, functions, schemas or JSON."
)


def _reason_property() -> dict[str, Any]:
    return {"type": "STRING", "description": _REASON}


def _error_type_property() -> dict[str, Any]:
    """The error_type parameter: a closed enum, each type explained by its ai_tool_phrase in shared/error_types.json."""
    explanations = []
    for entry in ERROR_TYPE_ENTRIES:
        explanations.append(f"'{entry['key']}' is {entry['ai_tool_phrase']}")
    explained = ", ".join(explanations)

    return {
        "type": "STRING",
        "enum": list(ERROR_TYPES),
        "description": f"Which class of flagged cell this acts on. {explained}.",
    }


def _one_column_tool(tool, column_property) -> dict[str, Any]:
    """A tool acting on ONE column."""
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "column": column_property(tool.column_description),
                "error_type": _error_type_property(),
                "reason": _reason_property(),
            },
            "required": ["column", "error_type", "reason"],
        },
    }


def _two_column_tool(tool, column_property, fills_column) -> dict[str, Any]:
    """A tool acting on a pair of columns. An operation that fills a column also names which of the two, as target."""
    properties = {
        "columns": {
            "type": "ARRAY",
            "items": column_property("A column from the profile."),
            "minItems": 2,
            "maxItems": 2,
            "description": tool.column_description,
        },
    }
    required = ["columns"]
    if fills_column:
        properties["target"] = {
            "type": "STRING",
            "enum": ["x", "y"],
            "description": (
                "Which of `columns` is repaired: 'x' for the first, 'y' for the second."
            ),
        }
        required.append("target")
    properties["error_type"] = _error_type_property()
    properties["reason"] = _reason_property()
    required.append("error_type")
    required.append("reason")

    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": {"type": "OBJECT", "properties": properties, "required": required},
    }


def build_tool_declarations(columns: list[str]) -> list[dict[str, Any]]:
    """
    Build the tool list for one node: every operation's one-column tool, then every two-column one, in AI_TOOL_OPS'
    order, then no_suggestions.

    :param columns: that node's real column names, already filtered of the structural columns (STRUCTURAL_COLUMNS in app/db_utils/column_types.py)
    """
    cols = list(columns)

    def column_property(description: str) -> dict[str, Any]:
        return {"type": "STRING", "enum": cols, "description": description}

    declarations = []
    for op in AI_TOOL_OPS:
        tool = op.ai_tools.get(1)
        if tool is not None:
            declarations.append(_one_column_tool(tool, column_property))
    for op in AI_TOOL_OPS:
        tool = op.ai_tools.get(2)
        if tool is not None:
            declarations.append(_two_column_tool(tool, column_property, op.fills_column))

    declarations.append(
        {
            "name": NO_SUGGESTIONS,
            "description": (
                "Call this, and only this, when the profile shows no data-quality problem worth a "
                "repair. Proposing a repair that is not needed is worse than proposing nothing."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "reason": {
                        "type": "STRING",
                        "description": (
                            "One plain sentence, at most 200 characters, saying why this table "
                            "needs no repair. Shown to the user verbatim."
                        ),
                    }
                },
                "required": ["reason"],
            },
        }
    )
    return declarations
