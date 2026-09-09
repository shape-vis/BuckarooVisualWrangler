"""
A small REST client for Gemini's generateContent, function-calling only.

Deliberately stdlib. run.sh installs dependencies with a hardcoded pip line and never reads
requirements.txt, so anything added there would be missing for whoever starts the app the
documented way. This is the only outbound HTTP call in the codebase and urllib covers it.
"""
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

DEFAULT_MODEL = "gemini-3.1-flash-lite"
# Picking one enumerated repair off a profile table is not a reasoning problem, and there is
# nothing for the model to reason its way into once the enums are closed.
DEFAULT_THINKING_LEVEL = "minimal"
DEFAULT_TIMEOUT = 20

# Google recommends leaving Gemini 3.x at its default; below 1.0 the documented failure mode is
# looping and degraded output. Determinism here comes from the schema, not from sampling.
TEMPERATURE = 1.0

# At most this many suggestions reach the user, however many calls the model emits.
MAX_SUGGESTIONS = 4


class GeminiUnconfigured(RuntimeError):
    """No API key. The caller turns this into a 503 rather than an error per node."""


class GeminiError(RuntimeError):
    """The model could not be reached, or answered with something unusable."""


def api_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    return key or None


def is_configured() -> bool:
    return api_key() is not None


def model_name() -> str:
    return os.environ.get("GEMINI_MODEL", "").strip() or DEFAULT_MODEL


def _generation_config() -> dict[str, Any]:
    """
    The thinking level is nested under thinkingConfig, not a direct child of generationConfig -
    verified against the live API, which rejects the flat form outright:

        generationConfig.thinkingLevel   -> 400 Unknown name "thinkingLevel"
        generationConfig.thinkingConfig.thinkingLevel -> accepted

    "minimal" really does mean no thinking: the same probe reported thoughtsTokenCount 0 for
    "minimal" against 90 for "low". Choosing between enumerated repairs off a profile table does
    not need deliberation, and the closed enums leave nothing to deliberate about.
    """
    config: dict[str, Any] = {"temperature": TEMPERATURE}
    level = os.environ.get("GEMINI_THINKING_LEVEL", DEFAULT_THINKING_LEVEL).strip()
    if level and level.lower() != "none":
        config["thinkingConfig"] = {"thinkingLevel": level}
    return config


def _post(url: str, payload: dict[str, Any], key: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _is_generation_config_complaint(body: str) -> bool:
    """
    Whether a 400 is about a generationConfig key rather than about the request as a whole.

    The shape of the thinking controls has moved between Gemini generations - thinkingBudget in
    2.5, thinkingLevel in 3.x, and nested under thinkingConfig rather than beside temperature -
    and the API rejects unknown keys outright instead of ignoring them. This keeps a bad key from
    taking the whole feature down with it, but it is a net, not a resting place: the retry logs
    loudly, and the fix is the key name.
    """
    lowered = body.lower()
    return ("generationconfig" in lowered or "generation_config" in lowered
            or "thinking" in lowered)


def generate(system_instruction: str, user_text: str,
             tool_declarations: list[dict[str, Any]],
             *, timeout: int | None = None) -> list[dict[str, Any]]:
    """
    Ask the model which tools to call. Returns the raw function calls, capped.

    Every returned dict is {"name": str, "args": dict} exactly as the model produced it - no
    validation happens here. app/server_utils/ai_wrangle.py re-derives everything from scratch.
    """
    key = api_key()
    if key is None:
        raise GeminiUnconfigured(
            "GEMINI_API_KEY is not set. Add it to .env - see .env.example."
        )

    timeout = timeout if timeout is not None else int(
        os.environ.get("GEMINI_TIMEOUT", str(DEFAULT_TIMEOUT))
    )
    url = f"{BASE_URL}/{model_name()}:generateContent"

    payload = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "tools": [{"functionDeclarations": tool_declarations}],
        # ANY forces a tool call. That is only safe because no_suggestions gives the model a
        # legal way to say "nothing here needs repairing" - see app/llm/tools.py.
        "toolConfig": {"functionCallingConfig": {"mode": "ANY"}},
        "generationConfig": _generation_config(),
    }

    started = time.time()
    try:
        body = _post(url, payload, key, timeout)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 400 and "generationConfig" in payload and _is_generation_config_complaint(detail):
            # Retry once without the tuning keys rather than failing the whole request. If this
            # ever fires in practice, fix the key name - do not settle for the fallback.
            print(
                "[gemini] generationConfig rejected, retrying without thinkingLevel. "
                f"Fix the key name. Response was: {detail[:400]}"
            )
            payload["generationConfig"] = {"temperature": TEMPERATURE}   # tuning keys dropped
            try:
                body = _post(url, payload, key, timeout)
            except urllib.error.HTTPError as retry_exc:
                raise GeminiError(
                    f"Gemini returned {retry_exc.code}: "
                    f"{retry_exc.read().decode('utf-8', errors='replace')[:400]}"
                ) from retry_exc
        elif exc.code in (401, 403):
            raise GeminiError("Gemini rejected the API key.") from exc
        elif exc.code == 429:
            raise GeminiError("Gemini rate limit reached. Try again in a moment.") from exc
        else:
            raise GeminiError(f"Gemini returned {exc.code}: {detail[:400]}") from exc
    except urllib.error.URLError as exc:
        raise GeminiError(f"Could not reach Gemini: {exc.reason}") from exc
    except TimeoutError as exc:
        raise GeminiError(f"Gemini did not answer within {timeout}s.") from exc

    calls = parse_function_calls(body)
    print(f"[gemini] {model_name()} {time.time() - started:.1f}s -> {len(calls)} call(s)")
    return calls[:MAX_SUGGESTIONS]


def parse_function_calls(body: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Pull the function calls out of a generateContent response.

    Split out from generate() so it can be tested against a canned body with no network.
    """
    feedback = body.get("promptFeedback") or {}
    if feedback.get("blockReason"):
        raise GeminiError(f"Gemini blocked the request: {feedback['blockReason']}")

    candidates = body.get("candidates") or []
    if not candidates:
        raise GeminiError("Gemini returned no candidates.")

    candidate = candidates[0]
    if candidate.get("finishReason") == "MALFORMED_FUNCTION_CALL":
        raise GeminiError("Gemini produced a malformed tool call.")

    parts = (candidate.get("content") or {}).get("parts") or []
    calls = []
    for part in parts:
        # With thinking on, parts can also carry {"thought": true, "text": ...}; function-call
        # parts can carry a thoughtSignature. Neither matters - history is never sent back.
        call = part.get("functionCall")
        if not call or not call.get("name"):
            continue
        calls.append({"name": call["name"], "args": dict(call.get("args") or {})})

    return calls
