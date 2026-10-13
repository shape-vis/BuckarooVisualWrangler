"""
Unit tests for safe_pg_name in app/server_utils/service_helpers.py: a node's table name is kept short enough that
every table derived from it - errors_<name>, rankings_<name>, dp_<name> and, the longest, <name>_filtering - stays
within PostgreSQL's 63-character identifier limit.
"""
import hashlib

from app.server_utils.service_helpers import MAX_TABLE_NAME_LENGTH, safe_pg_name

# The suffixes the app builds names with: an upload's random suffix, a candidate's bare name, and the staging copy
SUFFIXES = ["_x7f2q", "", "_staging"]

POSTGRES_IDENTIFIER_LIMIT = 63


# ─── Basic pass-through (name fits) ──────────────────────────────────────────

def test_a_short_name_is_base_plus_suffix():
    for suffix in SUFFIXES:
        assert safe_pg_name("data", suffix) == f"data{suffix}"


def test_a_name_exactly_at_the_limit_is_unchanged():
    suffix = "_staging"
    base = "x" * (MAX_TABLE_NAME_LENGTH - len(suffix))
    result = safe_pg_name(base, suffix)
    assert result == base + suffix
    assert len(result) == MAX_TABLE_NAME_LENGTH


# ─── Truncation + hash (name exceeds limit) ──────────────────────────────────

def test_a_long_name_is_cut_to_the_limit():
    base = "a" * 100
    for suffix in SUFFIXES:
        result = safe_pg_name(base, suffix)
        assert len(result) <= MAX_TABLE_NAME_LENGTH, f"{len(result)} characters for suffix {suffix!r}"


def test_a_long_name_keeps_its_suffix_and_carries_the_base_hash():
    base = "b" * 80
    expected_hash = hashlib.md5(base.encode()).hexdigest()[:8]
    for suffix in SUFFIXES:
        result = safe_pg_name(base, suffix)
        assert result.endswith(suffix)
        assert expected_hash in result


def test_one_character_over_the_limit_is_hashed():
    suffix = "_staging"
    base = "y" * (MAX_TABLE_NAME_LENGTH - len(suffix) + 1)
    result = safe_pg_name(base, suffix)
    assert len(result) <= MAX_TABLE_NAME_LENGTH
    assert hashlib.md5(base.encode()).hexdigest()[:8] in result


# ─── Every derived table fits ────────────────────────────────────────────────

def test_the_filtering_table_fits_for_any_name():
    for base in ["sales", "z" * 100]:
        for suffix in SUFFIXES:
            filtering_name = f"{safe_pg_name(base, suffix)}_filtering"
            assert len(filtering_name) <= POSTGRES_IDENTIFIER_LIMIT, filtering_name


# ─── Determinism ─────────────────────────────────────────────────────────────

def test_the_same_inputs_give_the_same_name():
    base = "w" * 60
    assert safe_pg_name(base, "_staging") == safe_pg_name(base, "_staging")


def test_different_long_bases_give_different_names():
    result_a = safe_pg_name("a" * 60, "_staging")
    result_b = safe_pg_name("b" * 60, "_staging")
    assert result_a != result_b
