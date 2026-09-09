"""
The AI suggestion endpoints.

Registered automatically by the pkgutil sweep in app/__init__.py.

Two routes do the work. /suggest is read-only: it builds a node's profile, asks the model which
repairs it would make, and returns the ones that survive validation. /accept runs one for real.
Declining is purely a front-end concern and has no endpoint.

/accept re-derives the suggestion from scratch rather than trusting the payload it is given, so
a tampered request can do nothing the model could not have asked for in the first place.
"""
import traceback

from flask import request

import app
from app import app as flask_app
from app.llm import gemini_client, tools
from app.llm.profile import build_profile_block
from app.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from app.server_utils import ai_wrangle
from app.server_utils.ai_wrangle import SuggestionError


def _node_table_from_request(body) -> str:
    node_table = (body or {}).get("node_table")
    if not node_table or not isinstance(node_table, str):
        raise SuggestionError("node_table is required")
    if not ai_wrangle.known_node(node_table):
        raise SuggestionError(f"{node_table} is not a node in this session's graph")
    return node_table


@flask_app.get("/api/ai/status")
def ai_status():
    """
    Whether suggestions are available at all.

    The front end asks once and hides the AI button when the answer is no, rather than growing a
    button on every node that can only ever produce the same error.
    """
    return {
        "success": True,
        "configured": gemini_client.is_configured(),
        "model": gemini_client.model_name() if gemini_client.is_configured() else None,
    }


@flask_app.post("/api/ai/suggest")
def ai_suggest():
    """
    Ask the model what it would repair on one node.

    Body: {"node_table": "n0a_adult_x7f2q"}

    Returns {"success": true, "suggestions": [...]} - each entry carries the op, the columns, the
    flag, a server-computed row_count and the model's reason - or {"no_suggestions": "<why>"}
    when the model judged the table clean.

    Read-only: it never changes which table the session is on.
    """
    try:
        node_table = _node_table_from_request(request.get_json(force=True, silent=True))
    except SuggestionError as exc:
        return {"success": False, "error": str(exc)}, 400

    try:
        profile_block, columns = build_profile_block(node_table)
        if not columns:
            return {"success": True, "node_table": node_table,
                    "no_suggestions": "This table has no columns that can be repaired."}

        calls = gemini_client.generate(
            SYSTEM_PROMPT,
            build_user_prompt(profile_block),
            tools.build_tool_declarations(columns),
        )
    except gemini_client.GeminiUnconfigured as exc:
        return {"success": False, "error": str(exc)}, 503
    except gemini_client.GeminiError as exc:
        return {"success": False, "error": str(exc)}, 502
    except Exception as exc:
        print("ERROR in ai_suggest")
        print(traceback.format_exc())
        return {"success": False, "error": str(exc)}, 500

    suggestions = []
    seen = set()
    rejected = []

    for call in calls:
        if call["name"] == tools.NO_SUGGESTIONS:
            # The model's escape hatch. It only means anything on its own - if it arrived
            # alongside real proposals, the proposals win and this is ignored.
            if len(calls) == 1:
                reason = str(call["args"].get("reason") or "").strip()
                return {"success": True, "node_table": node_table,
                        "no_suggestions": reason or "Nothing here needs repairing."}
            continue

        raw = dict(call["args"])
        raw["op"] = call["name"]
        try:
            suggestion = ai_wrangle.prepare(node_table, raw, columns)
        except SuggestionError as exc:
            # A suggestion that cannot be run is dropped, not surfaced. The model proposing
            # something impossible is not the user's problem.
            rejected.append(f"{call['name']}: {exc}")
            continue

        key = (suggestion.op, tuple(suggestion.columns),
               suggestion.target, suggestion.error_type)
        if key in seen:
            continue
        seen.add(key)

        payload = suggestion.to_json()
        payload["id"] = f"{node_table}:{len(suggestions)}"
        suggestions.append(payload)

    if rejected:
        print(f"[ai] dropped {len(rejected)} unusable suggestion(s): {'; '.join(rejected)}")

    if not suggestions:
        return {"success": True, "node_table": node_table,
                "no_suggestions": "Nothing the model proposed could be applied to this table."}

    return {"success": True, "node_table": node_table, "suggestions": suggestions}


@flask_app.post("/api/ai/accept")
def ai_accept():
    """
    Run one suggestion for real, cementing a new node onto the graph.

    Body: {"node_table": "n0a_...", "suggestion": {op, columns/column, target?, error_type}}

    Branches from node_table whatever the current node is, so the remaining suggestions stay
    valid and can be accepted or declined afterwards in any order.
    """
    body = request.get_json(force=True, silent=True) or {}
    try:
        node_table = _node_table_from_request(body)
    except SuggestionError as exc:
        return {"success": False, "error": str(exc)}, 400

    raw = body.get("suggestion")
    if not isinstance(raw, dict):
        return {"success": False, "error": "suggestion is required"}, 400

    try:
        _, columns = build_profile_block(node_table)
        return ai_wrangle.apply_suggestion(node_table, raw, columns)
    except SuggestionError as exc:
        # Everything the guards refuse lands here, with a message meant for the user
        return {"success": False, "error": str(exc)}, 422
    except Exception as exc:
        print("ERROR in ai_accept")
        print(traceback.format_exc())
        return {"success": False, "error": str(exc)}, 500
