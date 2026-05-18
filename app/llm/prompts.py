"""Prompt + JSON-schema definitions for LLM wrangle proposals.

The schema constrains the model to emit only ops that map 1:1 onto the existing
wrangler endpoints (see app/routes/wrangler_routes_sql.py):

  - delete-rows   (1D)  → create-previews with action=delete
  - impute-rows   (1D)  → create-previews with action=impute
  - delete-column       → /api/wrangle/delete-column
  - 2d-delete           → 2D create-previews + delete
  - 2d-impute-x / 2d-impute-y → 2D create-previews + impute

Keep the op vocabulary in sync with orchestrator.materialize().
"""

PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "proposals": {
            "type": "array",
            "minItems": 0,
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "op": {
                        "type": "string",
                        "enum": [
                            "delete-rows",
                            "impute-rows",
                            "delete-column",
                            "2d-delete",
                            "2d-impute-x",
                            "2d-impute-y",
                        ],
                    },
                    "params": {
                        "type": "object",
                        "description": (
                            "Op-specific args. For delete-rows/impute-rows: "
                            "{column: str, row_ids: [int]}. For delete-column: "
                            "{column: str}. For 2d-*: {columns: [str, str], row_ids: [int]}."
                        ),
                    },
                    "rationale": {"type": "string"},
                    "predicted_table_name": {"type": "string"},
                },
                "required": ["op", "params", "rationale"],
            },
        }
    },
    "required": ["proposals"],
}


SYSTEM_PROMPT = """You are a data-wrangling assistant for a tool called Buckaroo.
You receive table_context (schema, per-column stats, error counts) AND a list
of candidates already enumerated by the backend. Each candidate is one of:
  - "delete-rows"   params: {"column": str}   — delete all dirty rows in this column
  - "impute-rows"   params: {"column": str}   — impute all dirty rows in this column

Your job:
  1. RETURN EVERY CANDIDATE — do not drop any. The user wants both an impute
     and a delete option visible per dirty column.
  2. For each candidate, write a short rationale (one sentence) explaining
     when this op would be the right call for that column + error_type.
  3. Order proposals so that for each column, the recommended op appears first.

Do NOT invent new ops or columns outside the candidate list.
Do NOT drop candidates.
Do NOT enumerate row IDs.

Output ONLY this JSON, no commentary:
{"proposals": [
  {"op": "<from candidate>",
   "params": {"column": "<from candidate>"},
   "rationale": "one short sentence",
   "predicted_table_name": "short_snake_case_label"}
]}
"""


def build_user_prompt(table_context: dict) -> str:
    import json as _json
    return (
        "Table context follows. Propose wrangle operations.\n\n"
        + _json.dumps(table_context, indent=2, default=str)
    )
