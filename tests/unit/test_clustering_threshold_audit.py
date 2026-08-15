from experiments.audit_clustering_thresholds import all_items, validate


def test_threshold_audit_source_anchors_resolve():
    rows = validate(all_items())

    assert len(rows) >= 130
    assert all(row["source_line"] > 0 for row in rows)


def test_threshold_audit_covers_the_production_decision_chain():
    rows = validate(all_items())
    scopes = {row["scope"] for row in rows}
    ids = {row["threshold_id"] for row in rows}

    assert {
        "production_multiview",
        "api_ui_configuration",
        "upstream_profiler",
        "upstream_quality_detectors",
        "compatibility_baseline",
        "historical_experiment_protocol",
    } <= scopes
    assert {
        "mv.sample_resource_cap",
        "mv.confidence_natural_break",
        "mv.k_candidate_range",
        "mv.utility_calibration",
        "classifier.role_thresholds",
        "detector.iqr_multiplier",
    } <= ids


def test_multiview_request_defaults_no_longer_override_adaptive_decisions():
    rows = validate(all_items())
    by_id = {row["threshold_id"]: row for row in rows}

    assert "mv.default_sample_rows" not in by_id
    assert "api.default_sample_rows" not in by_id
    assert "client.default_sample_rows" not in by_id
    assert "ui.modal_sample_rows" not in by_id
    assert by_id["api.optional_sample_rows"]["value"] == "none unless caller supplies it"
    assert by_id["client.optional_min_group"]["value"] == "omitted by default"
