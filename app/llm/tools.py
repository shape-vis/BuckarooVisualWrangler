"""
The wrangle operations, declared as callable tools.

These declarations are the safety boundary. `column` is an enum built per request from the
node's real columns, so the model cannot name a column that does not exist; `error_type` is a
fixed enum; and there is no row_ids parameter at all, so the model has no way to name a row.
What it returns is a choice among enumerated operations, never a query.

Keep the names in step with OPS in app/server_utils/ai_wrangle.py - that module validates every
call against them and is what actually decides which rows an operation touches.
"""
from typing import Any

from app.server_utils.ai_wrangle import ERROR_TYPES

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


def _error_type_property(allowed=ERROR_TYPES) -> dict[str, Any]:
    return {
        "type": "STRING",
        "enum": list(allowed),
        "description": (
            "Which class of flagged cell this acts on. 'missing' is empty or null, 'mismatch' is "
            "the wrong data type for the column, 'anomaly' is a statistical outlier, 'incomplete' "
            "is a partial or truncated value."
        ),
    }


def build_tool_declarations(columns: list[str]) -> list[dict[str, Any]]:
    """
    Build the tool list for one node.

    :param columns: that node's real column names, already filtered of ID/Original_ID/index
    """
    cols = list(columns)

    def column_property(description: str) -> dict[str, Any]:
        return {"type": "STRING", "enum": cols, "description": description}

    return [
        {
            "name": "impute_rows",
            "description": (
                "Fill the flagged cells of ONE column, keeping every row. The fill value is that "
                "column's mean if it is numeric or its most common value if it is categorical; "
                "the server computes it, so never state a value yourself. Only the flagged cells "
                "are written - clean values in the column are left alone. Prefer this when the "
                "flagged cells are a minority and the rest of each row is worth keeping."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "column": column_property("The column to repair."),
                    "error_type": _error_type_property(),
                    "reason": _reason_property(),
                },
                "required": ["column", "error_type", "reason"],
            },
        },
        {
            "name": "delete_rows",
            "description": (
                "Remove every row whose cell in ONE column carries the given flag. Prefer this "
                "when the flagged values cannot be reconstructed - anomalies and type mismatches "
                "usually cannot - or when very few rows are affected. Never propose it when it "
                "would remove a large share of the table."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "column": column_property("The column whose flagged rows are removed."),
                    "error_type": _error_type_property(),
                    "reason": _reason_property(),
                },
                "required": ["column", "error_type", "reason"],
            },
        },
        {
            "name": "impute_rows_2d",
            "description": (
                "Fill the flagged cells of ONE column of a related pair, recording that the two "
                "were considered together. 'target' says which column is repaired: 'x' is the "
                "first entry of columns, 'y' is the second. Only that column's flagged rows are "
                "touched - the other column is left completely alone. Use this instead of "
                "impute_rows only when the pair genuinely belongs together."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "columns": {
                        "type": "ARRAY",
                        "items": column_property("A column from the profile."),
                        "minItems": 2,
                        "maxItems": 2,
                        "description": "Exactly two distinct columns, in the order [x, y].",
                    },
                    "target": {
                        "type": "STRING",
                        "enum": ["x", "y"],
                        "description": (
                            "Which of `columns` is repaired: 'x' for the first, 'y' for the second."
                        ),
                    },
                    "error_type": _error_type_property(),
                    "reason": _reason_property(),
                },
                "required": ["columns", "target", "error_type", "reason"],
            },
        },
        {
            "name": "delete_rows_2d",
            "description": (
                "Remove every row carrying the given flag in EITHER of two columns, cleaning both "
                "in one step. Use it when the two columns are related and their flagged rows "
                "overlap. Never propose it when it would remove a large share of the table."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "columns": {
                        "type": "ARRAY",
                        "items": column_property("A column from the profile."),
                        "minItems": 2,
                        "maxItems": 2,
                        "description": "Exactly two distinct columns from the profile.",
                    },
                    "error_type": _error_type_property(),
                    "reason": _reason_property(),
                },
                "required": ["columns", "error_type", "reason"],
            },
        },
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
        },
    ]
