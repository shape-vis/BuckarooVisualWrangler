"""
The AI suggestion endpoints.

Registered automatically by the pkgutil sweep in app/__init__.py.

/suggest builds a node's profile, asks the model which repairs it would make, and stages each one that
survives validation as a candidate: a provisional node under that node, its wrangle run on a copy of the
table, exactly as a repair of the user's selection is staged. Accepting and declining a candidate is the
same for both, and lives in candidate_routes.py.

The model only ever picks an operation and a column from a closed set; the rows a wrangle touches are
resolved by the server from the flags (see ai_wrangle), so nothing the model says reaches a table directly.
"""
import traceback

from app import app as flask_app
from app.llm import gemini_client, tools
from app.llm.profile import build_profile_block
from app.llm.prompts import SYSTEM_PROMPT, build_user_prompt
from app.server_utils import ai_wrangle, candidates
from app.server_utils.ai_wrangle import SuggestionError
from app.server_utils.service_helpers import json_object_body


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
    configured = gemini_client.is_configured()

    model = None
    if configured:
        model = gemini_client.model_name()

    return {"success": True, "configured": configured, "model": model}


def _no_suggestions_reason(calls):
    """
    The model's escape hatch: a lone no-suggestions call, giving its reason. It only means anything on its own - if
    it arrived alongside real proposals, the proposals win and it is ignored.
    :return: the reason, or None when the model proposed something
    """
    if len(calls) != 1 or calls[0]["name"] != tools.NO_SUGGESTIONS:
        return None
    reason = str(calls[0]["args"].get("reason") or "").strip()
    return reason or "Nothing here needs repairing."


def _prepare_calls(node_table, calls, columns):
    """
    Turn the model's tool calls into prepared suggestions: validated, their rows resolved from the flags, and
    checked as safe to run. A call that cannot be run is dropped, not surfaced - the model proposing something
    impossible is not the user's problem - and so is a repeat of one already kept.
    :return: (the prepared suggestions, in the model's order, and a note per dropped call)
    """
    prepared = []
    seen = set()
    rejected = []

    for call in calls:
        if call["name"] == tools.NO_SUGGESTIONS:
            continue

        raw = dict(call["args"])
        raw["op"] = call["name"]
        try:
            suggestion = ai_wrangle.prepare(node_table, raw, columns)
        except SuggestionError as exc:
            rejected.append(f"{call['name']}: {exc}")
            continue

        key = (suggestion.op, tuple(suggestion.columns), suggestion.target, suggestion.error_type)
        if key in seen:
            continue
        seen.add(key)
        prepared.append(suggestion)

    return prepared, rejected


@flask_app.post("/api/ai/suggest")
def ai_suggest():
    """
    Ask the model what it would repair on one node.

    Body: {"node_table": "n0a_adult_x7f2q"}

    Returns {"success": true, "candidates": [...]} - each a staged candidate (see
    candidates.candidate_json) carrying its op, columns, flag, a server-computed row_count and the
    model's reason - or {"no_suggestions": "<why>"} when the model judged the table clean.

    It never changes which table the session is on: the candidates are staged under node_table, and
    the user accepts or declines them through candidate_routes.py.
    """
    try:
        node_table = _node_table_from_request(json_object_body())
    except SuggestionError as exc:
        return {"success": False, "error": str(exc)}, 400
    try:
        # A candidate must be accepted before anything is wrangled from it - suggestions included
        candidates.require_accepted(node_table)
    except candidates.CandidateError as exc:
        return {"success": False, "error": str(exc)}, 409

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

    no_suggestions_reason = _no_suggestions_reason(calls)
    if no_suggestions_reason is not None:
        return {"success": True, "node_table": node_table, "no_suggestions": no_suggestions_reason}

    prepared, rejected = _prepare_calls(node_table, calls, columns)

    # Every suggestion that survived is built at once. One that cannot be staged is dropped like one that
    # cannot be run.
    suggestions = []
    if prepared:
        try:
            suggestions, failures = ai_wrangle.stage_suggestions(node_table, prepared)
        except candidates.CandidateError as exc:
            return {"success": False, "error": str(exc)}, 409
        for suggestion, exc in failures:
            rejected.append(f"{suggestion.op}: {exc}")

    if rejected:
        rejected_list = "; ".join(rejected)
        print(f"[ai] dropped {len(rejected)} unusable suggestion(s): {rejected_list}")

    if not suggestions:
        return {"success": True, "node_table": node_table,
                "no_suggestions": "Nothing the model proposed could be applied to this table."}

    return {"success": True, "node_table": node_table, "candidates": suggestions}
