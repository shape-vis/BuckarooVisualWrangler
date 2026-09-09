"""
Tool declarations and response parsing. No database, no network.

The declarations are the safety boundary - the enums are what stop the model naming a column
that does not exist - so they are worth pinning even though they are "just" data.
"""
import pytest

from app.llm import gemini_client, tools
from app.llm.gemini_client import GeminiError


COLUMNS = ["age", "income", "country"]


def _decl(name):
    return next(t for t in tools.build_tool_declarations(COLUMNS) if t["name"] == name)


def test_every_wrangle_operation_is_offered():
    """The model can reach every repair the UI can perform, plus the escape hatch."""
    names = [t["name"] for t in tools.build_tool_declarations(COLUMNS)]
    assert names == ["impute_rows", "delete_rows", "impute_rows_2d",
                     "delete_rows_2d", "no_suggestions"]


def test_column_enums_are_built_from_the_real_columns():
    assert _decl("impute_rows")["parameters"]["properties"]["column"]["enum"] == COLUMNS
    assert _decl("delete_rows")["parameters"]["properties"]["column"]["enum"] == COLUMNS
    for name in ("impute_rows_2d", "delete_rows_2d"):
        items = _decl(name)["parameters"]["properties"]["columns"]["items"]
        assert items["enum"] == COLUMNS


def test_the_model_is_given_no_way_to_name_a_row():
    """The anti-NLP-to-SQL guarantee, as a property of the schema rather than a promise."""
    for declaration in tools.build_tool_declarations(COLUMNS):
        properties = declaration["parameters"]["properties"]
        assert "row_ids" not in properties
        assert not any("row" in key.lower() and "id" in key.lower() for key in properties)


def test_error_type_is_a_closed_enum_everywhere():
    from app.server_utils.ai_wrangle import ERROR_TYPES
    for name in ("impute_rows", "delete_rows", "impute_rows_2d", "delete_rows_2d"):
        enum = _decl(name)["parameters"]["properties"]["error_type"]["enum"]
        assert enum == list(ERROR_TYPES)


def test_reason_is_required_so_hover_text_is_always_present():
    for name in ("impute_rows", "delete_rows", "impute_rows_2d",
                 "delete_rows_2d", "no_suggestions"):
        assert "reason" in _decl(name)["parameters"]["required"]


def test_2d_impute_declares_its_target():
    target = _decl("impute_rows_2d")["parameters"]["properties"]["target"]
    assert target["enum"] == ["x", "y"]
    assert "target" in _decl("impute_rows_2d")["parameters"]["required"]


# ─── response parsing ────────────────────────────────────────────────────────

def _body(parts, finish_reason=None):
    candidate = {"content": {"parts": parts}}
    if finish_reason:
        candidate["finishReason"] = finish_reason
    return {"candidates": [candidate]}


def test_parses_parallel_calls():
    calls = gemini_client.parse_function_calls(_body([
        {"functionCall": {"name": "impute_rows",
                          "args": {"column": "age", "error_type": "missing"}}},
        {"functionCall": {"name": "delete_rows",
                          "args": {"column": "income", "error_type": "anomaly"}}},
    ]))
    assert [c["name"] for c in calls] == ["impute_rows", "delete_rows"]
    assert calls[0]["args"]["column"] == "age"


def test_ignores_thinking_parts_and_thought_signatures():
    calls = gemini_client.parse_function_calls(_body([
        {"thought": True, "text": "considering the options"},
        {"functionCall": {"name": "impute_rows", "args": {"column": "age"},
                          "thoughtSignature": "opaque-blob"}},
        {"text": "some prose"},
    ]))
    assert len(calls) == 1
    assert calls[0] == {"name": "impute_rows", "args": {"column": "age"}}


def test_a_response_with_no_calls_parses_to_nothing():
    assert gemini_client.parse_function_calls(_body([{"text": "hello"}])) == []


def test_malformed_call_is_an_error_not_a_silent_empty():
    with pytest.raises(GeminiError, match="malformed"):
        gemini_client.parse_function_calls(_body([], finish_reason="MALFORMED_FUNCTION_CALL"))


def test_a_safety_block_is_reported():
    with pytest.raises(GeminiError, match="blocked"):
        gemini_client.parse_function_calls({"promptFeedback": {"blockReason": "SAFETY"}})


def test_no_candidates_is_reported():
    with pytest.raises(GeminiError, match="no candidates"):
        gemini_client.parse_function_calls({"candidates": []})


def test_generation_config_nests_the_thinking_level(monkeypatch):
    """
    thinkingLevel lives under thinkingConfig, not beside temperature.

    Verified against the live API: the flat form returns
    400 Unknown name "thinkingLevel" at 'generation_config'. The retry in generate() papers over
    that, but a request that has to be sent twice is a bug, so pin the shape here.
    """
    monkeypatch.delenv("GEMINI_THINKING_LEVEL", raising=False)
    config = gemini_client._generation_config()

    assert config["temperature"] == 1.0, "Gemini 3.x is documented to want its default"
    assert config["thinkingConfig"] == {"thinkingLevel": "minimal"}
    assert "thinkingLevel" not in config, "must be nested, not a direct child"

    monkeypatch.setenv("GEMINI_THINKING_LEVEL", "none")
    assert "thinkingConfig" not in gemini_client._generation_config()
