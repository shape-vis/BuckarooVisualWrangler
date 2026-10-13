"""
The error detectors, run inside Postgres by DetectorSQL (app/db_utils/detector_sql.py).

These are the pandas detectors' unit cases - tests/unit/test_*_detector.py, deleted along with the pandas detectors -
held against the SQL ones. Each frame is stored as a table, the way an upload stores it, and the flags are read back
out of its errors_ table. The golden test pins every flag on the provided survey to the counts the pandas detectors
gave it before they were replaced.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import text as sa_text

from app import engine
from app.db_utils.column_types import ColumnTypes
from app.db_utils.detector_sql import DetectorSQL
from app.db_utils.execute_sql import copy_insert
from app.server_utils.service_helpers import get_sqlalchemy_dtype_map
from app.server_utils.set_id_column import set_id_column

TABLE = "t_detector_sql"

SURVEY = Path(__file__).resolve().parents[2] / "provided_datasets" / "stackoverflow_db_uncleaned.csv"


def _drop(table):
    with engine.begin() as conn:
        conn.execute(sa_text(f'DROP TABLE IF EXISTS "{table}"'))
        conn.execute(sa_text(f'DROP TABLE IF EXISTS "errors_{table}"'))
    ColumnTypes.forget(table)


@pytest.fixture
def detect():
    """
    Store a frame as a table, run the detectors over it, and read its flags back.
    :return: a function of a frame giving {error_type: {column: {row ids}}}
    """
    def run(frame):
        frame.to_sql(TABLE, engine, if_exists="replace", index=False)
        ColumnTypes.forget(TABLE)
        DetectorSQL(engine, TABLE).generate_errors_table()

        flags = {}
        with engine.connect() as conn:
            rows = conn.execute(sa_text(f'SELECT row_id, column_id, error_type FROM "errors_{TABLE}"'))
            for row_id, column, error_type in rows:
                flags.setdefault(error_type, {}).setdefault(column, set()).add(row_id)
        return flags

    yield run
    _drop(TABLE)


# ── anomaly ──────────────────────────────────────────────────────────────────

def _anomaly_frame(with_text_column):
    np.random.seed(12)
    data = {
        "ID": range(1, 13),
        "normal_col": np.random.normal(100, 15, 12),
        "anomaly_col": np.concatenate([np.random.normal(50, 5, 7), [2000, 300, -100, 250, 180]]),
    }
    if with_text_column:
        # Only 8 of its values are numbers - fewer than the 10 the anomaly detector needs to judge a column
        data["string_col"] = np.concatenate([np.random.normal(50, 5, 7), [2000, "hi", "hello", "bonjour", "oui"]])
    return pd.DataFrame(data)


@pytest.mark.sql
def test_anomaly_flags_values_more_than_two_deviations_out(detect):
    flags = detect(_anomaly_frame(with_text_column=False))

    assert flags.get("anomaly") == {"normal_col": {10}, "anomaly_col": {8}}


@pytest.mark.sql
def test_anomaly_skips_a_column_with_too_few_numbers(detect):
    flags = detect(_anomaly_frame(with_text_column=True))

    assert flags.get("anomaly") == {"normal_col": {10}, "anomaly_col": {8}}


# ── incomplete ───────────────────────────────────────────────────────────────

@pytest.mark.sql
def test_incomplete_flags_rare_values_and_ignores_numeric_columns(detect):
    flags = detect(pd.DataFrame({
        "ID": range(1, 6),
        "classname": ["systems", "networking", "compilers", "full-stack", "vis"],
        "day": ["M/W", "T/H", "M/W", "M/W/F", "T/H"],
        "enrollment_cap": [100, 100, 250, 250, 100],
        "professor": ["kopta", "martin", "panchekha", "johnson", "rosen"],
    }))

    every_row = {1, 2, 3, 4, 5}
    assert flags.get("incomplete") == {"classname": every_row, "day": every_row, "professor": every_row}


@pytest.mark.sql
def test_incomplete_leaves_common_values_alone(detect):
    flags = detect(pd.DataFrame({
        "ID": range(1, 6),
        "classname": ["systems"] * 5,
        "day": ["M/W"] * 5,
        "enrollment_cap": [100, 100, 250, 250, 100],
        "professor": ["kopta"] * 5,
    }))

    assert "incomplete" not in flags


# ── missing ──────────────────────────────────────────────────────────────────

@pytest.mark.sql
@pytest.mark.parametrize("animals, pets, expected", [
    (["ant", "bee", "cat"], ["dog", None, "fly"], {"pets": {2}}),
    (["ant", None, "cat"], ["dog", None, None], {"animals": {2}, "pets": {2, 3}}),
    (["ant", np.nan, "cat"], ["dog", np.nan, np.nan], {"animals": {2}, "pets": {2, 3}}),
    (["ant", "null", "cat"], ["dog", "undefined", "null"], {"animals": {2}, "pets": {2, 3}}),
    (["ant", "null", None], [np.nan, "undefined", None], {"animals": {2, 3}, "pets": {1, 2, 3}}),
])
def test_missing_is_null_or_the_text_null_or_undefined(detect, animals, pets, expected):
    flags = detect(pd.DataFrame({"ID": range(1, 4), "animals": animals, "pets": pets}))

    assert flags.get("missing") == expected


# ── mismatch ─────────────────────────────────────────────────────────────────

@pytest.mark.sql
def test_mismatch_flags_the_minority_kind(detect):
    flags = detect(pd.DataFrame({
        "ID": range(1, 11),
        "classname": ["word", "word", "systems", "networking", "compilers", "full-stack", "vis", "vis", "vis", "vis"],
        "day": ["word", "word", "M/W", "T/H", "M/W", "M/W/F", "T/H", "vis", "vis", "vis"],
        # Five numbers and five words: a tie, which the kind holding the most frequent value (100, three times) wins
        "enrollment_cap": ["word", "word", 100, 100, 250, 250, 100, "test", "adding", "words"],
        "professor": ["word", "word", "kopta", "martin", "panchekha", "johnson", "rosen", "vis", "vis", "vis"],
    }))

    assert flags.get("mismatch") == {"enrollment_cap": {1, 2, 8, 9, 10}}


@pytest.mark.sql
def test_mismatch_leaves_a_column_of_one_kind_alone(detect):
    flags = detect(pd.DataFrame({
        "ID": range(1, 6),
        "classname": ["word", "systems", "networking", "compilers", "full-stack"],
        "day": ["M/W", "T/H", "M/W", "M/W/F", "T/H"],
        "enrollment_cap": [100, 100, 250, 250, 100],
        "professor": ["kopta", "martin", "panchekha", "johnson", "rosen"],
    }))

    assert "mismatch" not in flags


# ── The errors table ─────────────────────────────────────────────────────────

@pytest.mark.sql
def test_id_is_never_flagged(detect):
    flags = detect(pd.DataFrame({"ID": [1, 2, 3], "value": [None, "a", "b"]}))

    for by_column in flags.values():
        assert "ID" not in by_column


@pytest.mark.sql
def test_the_errors_table_keeps_its_shape_and_is_indexed(detect):
    detect(pd.DataFrame({"ID": [1, 2], "value": [None, 1.0]}))

    with engine.connect() as conn:
        columns = conn.execute(sa_text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = :table ORDER BY ordinal_position"), {"table": f"errors_{TABLE}"}).fetchall()
        indexes = conn.execute(sa_text("SELECT indexdef FROM pg_indexes WHERE tablename = :table"),
                               {"table": f"errors_{TABLE}"}).fetchall()

    assert columns == [("row_id", "bigint"), ("column_id", "text"), ("error_type", "text")]
    assert any("(column_id, row_id)" in index for (index,) in indexes)


@pytest.mark.sql
@pytest.mark.parametrize("frame, expected", [
    (pd.DataFrame({"ID": [1, 2], "number": [1.0, None]}), {"missing": {"number": {2}}}),
    (pd.DataFrame({"ID": [1, 2], "word": ["a", None]}), {"missing": {"word": {2}}, "incomplete": {"word": {1}}}),
    (pd.DataFrame({"ID": [1, 2]}), {}),
])
def test_tables_without_numeric_or_text_columns(detect, frame, expected):
    assert detect(frame) == expected


# ── Golden ───────────────────────────────────────────────────────────────────

# Every flag the pandas detectors raised on the survey, by column and error type, before they were replaced
SURVEY_FLAGS = {
    "Age": {"incomplete": 4, "mismatch": 2},
    "ConvertedSalary": {"anomaly": 14, "missing": 6},
    "Country": {"incomplete": 1},
    "DevType": {"incomplete": 6},
    "EducationParents": {"incomplete": 1},
    "FormalEducation": {"incomplete": 2},
    "Gender": {"incomplete": 8},
    "HoursComputer": {"incomplete": 2},
    "RaceEthnicity": {"incomplete": 1},
    "UndergradMajor": {"incomplete": 1},
}


@pytest.mark.sql
def test_golden_survey_flags():
    table = "t_detector_sql_survey"
    frame = set_id_column(pd.read_csv(SURVEY))
    frame.to_sql(table, engine, if_exists="replace", dtype=get_sqlalchemy_dtype_map(frame), method=copy_insert)
    ColumnTypes.forget(table)

    try:
        DetectorSQL(engine, table).generate_errors_table()
        with engine.connect() as conn:
            rows = conn.execute(sa_text(
                f'SELECT column_id, error_type, COUNT(*) FROM "errors_{table}" GROUP BY column_id, error_type'))
            counts = {}
            for column, error_type, count in rows:
                counts.setdefault(column, {})[error_type] = count
    finally:
        _drop(table)

    assert counts == SURVEY_FLAGS
