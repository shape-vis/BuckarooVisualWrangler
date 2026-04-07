"""
Unit tests for the _safe_pg_name helper in wrangler_routes_sql.py.

Tests the logic that builds PostgreSQL-safe preview table names, ensuring
both the preview name and its 'errors_<name>' sibling stay within the
63-character PostgreSQL identifier limit.
"""
import hashlib
from app.server_utils.service_helpers import _safe_pg_name

MAX_LEN = 56  # 63 - len("errors_")

ALL_SUFFIXES = [
    "_preview_delete",
    "_preview_impute",
    "_preview_impute_x",
    "_preview_impute_y",
]


# ─── Basic pass-through (name fits) ──────────────────────────────────────────

def test_short_base_returns_concatenation():
    result = _safe_pg_name("mytable", "_preview_delete")
    assert result == "mytable_preview_delete"


def test_result_is_base_plus_suffix_when_short():
    for suffix in ALL_SUFFIXES:
        result = _safe_pg_name("data", suffix)
        assert result == f"data{suffix}"


def test_exactly_56_chars_unchanged():
    suffix = "_preview_delete"          # 15 chars
    base = "x" * (MAX_LEN - len(suffix))  # 41 chars → total = 56
    result = _safe_pg_name(base, suffix)
    assert result == base + suffix
    assert len(result) == MAX_LEN


# ─── Truncation + hash (name exceeds limit) ──────────────────────────────────

def test_long_name_is_truncated_to_max_len():
    base = "a" * 100
    for suffix in ALL_SUFFIXES:
        result = _safe_pg_name(base, suffix)
        assert len(result) <= MAX_LEN, (
            f"Expected ≤{MAX_LEN} chars for suffix '{suffix}', got {len(result)}"
        )


def test_long_name_contains_md5_hash():
    base = "a" * 100
    expected_hash = hashlib.md5(base.encode()).hexdigest()[:8]
    for suffix in ALL_SUFFIXES:
        result = _safe_pg_name(base, suffix)
        assert expected_hash in result, (
            f"Expected hash '{expected_hash}' in '{result}'"
        )


def test_long_name_ends_with_suffix():
    base = "b" * 80
    for suffix in ALL_SUFFIXES:
        result = _safe_pg_name(base, suffix)
        assert result.endswith(suffix)


def test_one_char_over_limit_triggers_hash():
    suffix = "_preview_delete"  # 15 chars
    # base of 42 → candidate = 57, one over MAX_LEN (56)
    base = "y" * 42
    result = _safe_pg_name(base, suffix)
    assert len(result) <= MAX_LEN
    h = hashlib.md5(base.encode()).hexdigest()[:8]
    assert h in result


# ─── errors_ sibling always fits in 63 chars ─────────────────────────────────

def test_errors_sibling_fits_for_short_name():
    result = _safe_pg_name("sales", "_preview_delete")
    assert len(f"errors_{result}") <= 63


def test_errors_sibling_fits_for_long_name():
    base = "z" * 100
    for suffix in ALL_SUFFIXES:
        result = _safe_pg_name(base, suffix)
        errors_name = f"errors_{result}"
        assert len(errors_name) <= 63, (
            f"errors_ sibling '{errors_name}' is {len(errors_name)} chars (max 63)"
        )


# ─── Determinism ─────────────────────────────────────────────────────────────

def test_same_inputs_produce_same_output():
    base = "w" * 60
    suffix = "_preview_impute_x"
    assert _safe_pg_name(base, suffix) == _safe_pg_name(base, suffix)


def test_different_bases_produce_different_names():
    suffix = "_preview_delete"
    result_a = _safe_pg_name("a" * 60, suffix)
    result_b = _safe_pg_name("b" * 60, suffix)
    assert result_a != result_b
