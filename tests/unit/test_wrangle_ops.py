"""
The wrangle operations' registry (app/server_utils/wrangle_ops.py): what a selection is offered, how a recorded wrangle
reads back, and that a name no operation has is refused rather than run as something else.
"""
import pytest

from app.server_utils import wrangle_ops
from app.server_utils.wrangle_ops import DELETE, IMPUTE, parse_wrangle_op, recorded_name, repair_options


def test_a_one_column_selection_is_offered_delete_then_impute():
    assert repair_options(["age"], 3) == [
        ("delete", None, "Delete rows", "Remove the 3 selected rows"),
        ("impute", "age", "Impute age",
         "Fill age in the 3 selected rows with its mean, or its most common value if it is categorical"),
    ]


def test_a_two_column_selection_is_offered_an_impute_per_column():
    options = repair_options(["age", "city"], 1)

    recorded = []
    imputed = []
    for op, column, _, _ in options:
        recorded.append(op)
        imputed.append(column)
    assert recorded == ["delete", "impute_x", "impute_y"]
    assert imputed == [None, "age", "city"]
    assert options[0][3] == "Remove the selected row"


def test_large_row_counts_are_written_with_thousands_separators():
    assert repair_options(["age"], 12345)[0][3] == "Remove the 12,345 selected rows"


@pytest.mark.parametrize("recorded, op, axis", [
    ("delete", DELETE, None),
    ("impute", IMPUTE, None),
    ("impute_x", IMPUTE, "x"),
    ("impute_y", IMPUTE, "y"),
    # Only an operation that fills a column records an axis
    ("delete_x", None, None),
    ("impute_z", None, None),
    ("root", None, None),
    ("", None, None),
])
def test_a_recorded_wrangle_reads_back_as_its_operation(recorded, op, axis):
    assert parse_wrangle_op(recorded) == (op, axis)


def test_recording_and_reading_back_round_trip():
    for op in wrangle_ops.WRANGLE_OPS:
        assert parse_wrangle_op(recorded_name(op)) == (op, None)
        if op.fills_column:
            for axis in wrangle_ops.AXES:
                assert parse_wrangle_op(recorded_name(op, axis)) == (op, axis)


def test_every_operation_names_itself_once_and_its_ai_tools_once():
    names = []
    tool_names = []
    for op in wrangle_ops.WRANGLE_OPS:
        names.append(op.name)
        for tool in op.ai_tools.values():
            tool_names.append(tool.name)
    assert len(names) == len(set(names))
    assert len(tool_names) == len(set(tool_names))
    for op in wrangle_ops.AI_TOOL_OPS:
        assert op in wrangle_ops.WRANGLE_OPS


def test_descriptions_read_as_the_compare_panel_shows_them():
    assert IMPUTE.description(["age"]) == "Imputed age"
    assert DELETE.description(["age", "city"]) == "Deleted rows selected on age × city"
    assert DELETE.description([]) == "Deleted rows"


def test_an_unknown_operation_is_refused_before_anything_is_built():
    from app.server_utils import candidates

    spec = candidates.CandidateSpec(op="clip", cols=["age"], row_ids=[1])
    with pytest.raises(candidates.CandidateError):
        candidates._check(spec)


def test_an_operation_that_fills_a_column_needs_one():
    from app.server_utils import candidates

    spec = candidates.CandidateSpec(op="impute", cols=["age"], row_ids=[1])
    with pytest.raises(candidates.CandidateError):
        candidates._check(spec)


def test_an_error_type_without_a_detector_fails_when_detection_starts(monkeypatch):
    from app.db_utils import detector_sql

    # Made without __init__, so no table is needed: find_detectors is the part of it under test
    detector = detector_sql.DetectorSQL.__new__(detector_sql.DetectorSQL)
    assert len(detector.find_detectors()) == len(detector_sql.ERROR_TYPES)

    monkeypatch.setattr(detector_sql, "ERROR_TYPES", detector_sql.ERROR_TYPES + ("typo",))
    with pytest.raises(NotImplementedError):
        detector.find_detectors()
