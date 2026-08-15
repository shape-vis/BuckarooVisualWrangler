import time

from app import _BoundedSessionStateRegistry
from app.server_utils.data_attribute_summary_integration import resolve_detector_coverage
from app.server_utils.service_helpers import should_run_full_background_detection


def test_sampled_detector_coverage_uses_only_inspected_rows():
    rows, complete, denominator = resolve_detector_coverage(
        100_000,
        {"detector_rows": 500, "detector_is_complete": False},
    )
    assert (rows, complete, denominator) == (500, False, 500)


def test_completed_detector_coverage_uses_full_dataset():
    rows, complete, denominator = resolve_detector_coverage(
        100_000,
        {"detector_rows": 500, "detector_is_complete": True},
    )
    assert (rows, complete, denominator) == (100_000, True, 100_000)


def test_detector_coverage_clamps_invalid_metadata():
    assert resolve_detector_coverage(10, {"detector_rows": 50, "detector_is_complete": False}) == (10, False, 10)
    assert resolve_detector_coverage(10, {"detector_rows": -5, "detector_is_complete": False}) == (0, False, 0)


def test_background_detection_budget_is_inclusive_and_bounded():
    assert should_run_full_background_detection(250_000, max_rows=250_000)
    assert not should_run_full_background_detection(250_001, max_rows=250_000)
    assert not should_run_full_background_detection(-1, max_rows=250_000)


def test_session_registry_evicts_oldest_state_at_capacity():
    registry = _BoundedSessionStateRegistry(dict, max_states=2, idle_ttl_seconds=60)
    first = registry.get_or_create("first")
    registry.get_or_create("second")
    registry.get_or_create("third")

    assert len(registry) == 2
    assert registry.get_or_create("first") is not first


def test_session_registry_expires_idle_state():
    registry = _BoundedSessionStateRegistry(dict, max_states=2, idle_ttl_seconds=0.01)
    first = registry.get_or_create("first")
    time.sleep(0.02)
    assert registry.get_or_create("first") is not first
