import hashlib

from app.server_utils.service_helpers import _safe_pg_name


MAX_LEN = 53  # 63 - len("_filtering")

ALL_SUFFIXES = [
    "_preview_delete",
    "_preview_impute",
    "_preview_impute_x",
    "_preview_impute_y",
]


def test_short_base_returns_concatenation():
    result = _safe_pg_name("mytable", "_preview_delete")
    assert result == "mytable_preview_delete"


def test_result_is_base_plus_suffix_when_short():
    for suffix in ALL_SUFFIXES:
        result = _safe_pg_name("data", suffix)
        assert result == f"data{suffix}"


def test_exactly_max_chars_unchanged():
    suffix = "_preview_delete"
    base = "x" * (MAX_LEN - len(suffix))

    result = _safe_pg_name(base, suffix)

    assert result == base + suffix
    assert len(result) == MAX_LEN


def test_long_name_is_truncated_to_max_len():
    base = "a" * 100
    for suffix in ALL_SUFFIXES:
        result = _safe_pg_name(base, suffix)
        assert len(result) <= MAX_LEN


def test_long_name_contains_md5_hash():
    base = "a" * 100
    expected_hash = hashlib.md5(base.encode()).hexdigest()[:8]
    for suffix in ALL_SUFFIXES:
        result = _safe_pg_name(base, suffix)
        assert expected_hash in result


def test_long_name_ends_with_suffix():
    base = "b" * 80
    for suffix in ALL_SUFFIXES:
        result = _safe_pg_name(base, suffix)
        assert result.endswith(suffix)


def test_one_char_over_limit_triggers_hash():
    suffix = "_preview_delete"
    base = "y" * (MAX_LEN - len(suffix) + 1)

    result = _safe_pg_name(base, suffix)

    assert len(result) <= MAX_LEN
    assert hashlib.md5(base.encode()).hexdigest()[:8] in result


def test_errors_sibling_fits_for_short_name():
    result = _safe_pg_name("sales", "_preview_delete")
    assert len(f"errors_{result}") <= 63


def test_errors_sibling_fits_for_long_name():
    base = "z" * 100
    for suffix in ALL_SUFFIXES:
        result = _safe_pg_name(base, suffix)
        assert len(f"errors_{result}") <= 63


def test_filtering_sibling_fits_for_long_name():
    base = "z" * 100
    for suffix in ALL_SUFFIXES:
        result = _safe_pg_name(base, suffix)
        assert len(f"{result}_filtering") <= 63


def test_same_inputs_produce_same_output():
    base = "w" * 60
    suffix = "_preview_impute_x"
    assert _safe_pg_name(base, suffix) == _safe_pg_name(base, suffix)


def test_different_bases_produce_different_names():
    suffix = "_preview_delete"
    result_a = _safe_pg_name("a" * 60, suffix)
    result_b = _safe_pg_name("b" * 60, suffix)
    assert result_a != result_b
