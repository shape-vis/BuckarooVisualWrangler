"""Create research-grade manual labeling worksheets for profiler evaluation.

The worksheet is intentionally wide. It captures semantic truth, key behavior,
dependency evidence, data-quality risk, sampling fragility, and expected
profiler behavior in one place so the benchmark schema does not need to keep
changing during the paper work.
"""

from __future__ import annotations

import csv
from collections import Counter
import os
from pathlib import Path
from typing import Dict, Iterable, List


ROOT = Path(__file__).resolve().parents[1]
BASE = Path(os.environ.get("BUCKAROO_MANUAL_LABEL_DIR", ROOT / "outputs" / "manual_labeling_5_datasets"))
DATASETS = [
    "taxi_trips.csv",
    "us_airports.csv",
    "stock_prices.csv",
    "adult_census_income.csv",
    "diamonds_pricing.csv",
]

BLANK_OUT = BASE / "manual_column_labeling_research_grade_blank.csv"
FILLED_OUT = BASE / "manual_column_labeling_research_grade_with_taxi_filled.csv"
TAXI_OUT = BASE / "taxi_trips_manual_labels_research_grade_filled.csv"
CODEBOOK_OUT = BASE / "manual_labeling_research_grade_codebook.md"


FIELDNAMES = [
    # Basic provenance and measured evidence.
    "dataset_id",
    "column_name",
    "column_position",
    "row_count",
    "non_null_count",
    "null_count",
    "null_ratio",
    "unique_count",
    "unique_ratio",
    "duplicate_value_count",
    "top_value",
    "top_value_count",
    "top_value_ratio",
    "sample_values",
    "common_values",
    # Human semantic labels.
    "manual_true_role",
    "manual_secondary_role",
    "manual_physical_type",
    "semantic_group",
    "semantic_subtype",
    "unit_or_currency",
    "temporal_granularity",
    "geographic_level",
    "entity_type",
    "domain_vocabulary",
    "allowed_values_known",
    # Key and relationship labels.
    "is_primary_key",
    "is_foreign_key",
    "foreign_key_target_if_known",
    "is_surrogate_key",
    "is_natural_key",
    "is_composite_key_part",
    "possible_composite_key_with",
    "could_be_key_by_uniqueness",
    "should_be_key_candidate_for_buckaroo",
    "is_high_uniqueness_but_not_key",
    "key_rejection_reason",
    "is_identifier_like_code",
    "identifier_code_type",
    "entity_name_vs_identifier",
    "naming_evidence_strength",
    # Dependency/profiling labels inspired by Metanome-style tasks.
    "ucc_candidate_status",
    "fd_determinant_candidate",
    "fd_dependent_candidate",
    "ind_candidate_status",
    "order_dependency_candidate",
    "monotonic_or_sequence",
    "derived_or_calculated_field",
    "derived_from_columns",
    # Temporal and geography edge cases.
    "is_datetime_or_lifecycle_event",
    "lifecycle_event_type",
    "timezone_or_locale_risk",
    "seasonality_or_periodicity_risk",
    "is_geographic_or_location",
    "location_semantic_type",
    "coordinate_pair_partner",
    "coordinate_range_expected",
    "postal_or_admin_code",
    # Numeric, categorical, and text edge cases.
    "is_measure_or_metric",
    "is_money_amount",
    "is_count_or_quantity",
    "is_rate_ratio_or_percentage",
    "is_bounded_numeric",
    "expected_min",
    "expected_max",
    "zero_heavy",
    "negative_allowed",
    "outlier_sensitive",
    "ordinal_category",
    "nominal_category",
    "boolean_like",
    "free_text_or_description",
    # Data-quality and privacy labels inspired by Deequ/DataProfiler-style checks.
    "has_missing_values",
    "missingness_severity",
    "missingness_semantics",
    "invalid_value_risk",
    "standardization_risk",
    "mixed_type_risk",
    "format_consistency_risk",
    "unit_consistency_risk",
    "dirty_data_examples",
    "pii_or_sensitive",
    "pii_type",
    # Sampling/stability research labels.
    "sample_size_sensitivity",
    "small_sample_false_key_risk",
    "noise_sensitivity",
    "adaptive_sampling_priority",
    "min_recommended_sample_size",
    "confidence_interval_priority",
    "manual_label_confidence",
    "needs_second_reviewer",
    "adjudication_status",
    # Expected profiler behavior and baselines.
    "expected_buckaroo_role",
    "expected_warning_type",
    "should_buckaroo_warn",
    "expected_confidence_behavior",
    "profiler_failure_mode_to_test",
    "metanome_expected_behavior",
    "deequ_expected_constraint",
    "dataprofiler_expected_behavior",
    "llm_semantic_label_expected",
    # Meeting follow-up labels: semantic ML, adaptive sampling, UI, and paper value.
    "requires_semantic_ml",
    "semantic_ml_use_case",
    "recommended_semantic_model",
    "sbert_use_recommended",
    "sbert_input_signal",
    "sbert_expected_benefit",
    "simple_rules_enough",
    "semantic_ml_priority",
    "semantic_context_needed",
    "advanced_ml_analysis_reason",
    "expected_candidate_roles",
    "expected_candidate_confidence_pattern",
    "low_confidence_adaptive_sampling_trigger",
    "adaptive_sampling_stop_condition",
    "ui_should_show_confidence_interval",
    "ui_should_show_warning_badge",
    "ui_user_facing_explanation",
    "professor_question_to_answer",
    "benchmark_importance",
    "manual_label_priority",
    "runtime_tracking_needed",
    "compare_against_external_baseline",
    "geography_safeguard_relevance",
    "timestamp_safeguard_relevance",
    "confidence_interval_metric_to_watch",
    "row_sampling_failure_mode",
    "noise_failure_mode",
    "poster_worthy_example",
    "paper_claim_supported",
    "needs_domain_dictionary",
    "dictionary_or_reference_source",
    # Explanation fields.
    "why_this_label",
    "edge_case_or_risk",
    "research_use_case",
    "reviewer_notes",
]


def ratio(num: int, den: int) -> str:
    return f"{num / den:.6f}" if den else ""


def read_dataset_stats(path: Path) -> List[Dict[str, object]]:
    dataset_id = path.stem
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        stats = {c: {"null": 0, "unique": set(), "examples": [], "counter": Counter()} for c in columns}
        total = 0
        for record in reader:
            total += 1
            for column in columns:
                value = (record.get(column) or "").strip()
                if value == "":
                    stats[column]["null"] += 1
                    continue
                stats[column]["unique"].add(value)
                if len(stats[column]["examples"]) < 6 and value not in stats[column]["examples"]:
                    stats[column]["examples"].append(value)
                stats[column]["counter"][value] += 1

    rows: List[Dict[str, object]] = []
    for position, column in enumerate(columns, start=1):
        stat = stats[column]
        non_null = total - int(stat["null"])
        unique_count = len(stat["unique"])
        top_value = ""
        top_count = 0
        if stat["counter"]:
            top_value, top_count = stat["counter"].most_common(1)[0]
        row = {name: "" for name in FIELDNAMES}
        row.update(
            {
                "dataset_id": dataset_id,
                "column_name": column,
                "column_position": position,
                "row_count": total,
                "non_null_count": non_null,
                "null_count": stat["null"],
                "null_ratio": ratio(int(stat["null"]), total),
                "unique_count": unique_count,
                "unique_ratio": ratio(unique_count, non_null),
                "duplicate_value_count": max(non_null - unique_count, 0),
                "top_value": top_value,
                "top_value_count": top_count,
                "top_value_ratio": ratio(top_count, non_null),
                "sample_values": " | ".join(stat["examples"]),
                "common_values": " | ".join(f"{v} ({n})" for v, n in stat["counter"].most_common(6)),
            }
        )
        rows.append(row)
    return rows


def common_non_key() -> Dict[str, str]:
    return {
        "is_primary_key": "no",
        "is_surrogate_key": "no",
        "is_natural_key": "no",
        "should_be_key_candidate_for_buckaroo": "no",
        "is_identifier_like_code": "no",
        "manual_label_confidence": "high",
        "needs_second_reviewer": "no",
        "adjudication_status": "labeled",
    }


def datetime_fill(column: str, subtype: str, lifecycle: str) -> Dict[str, str]:
    label = {
        **common_non_key(),
        "manual_true_role": "datetime",
        "manual_secondary_role": subtype,
        "manual_physical_type": "datetime_string",
        "semantic_group": "temporal",
        "semantic_subtype": f"{subtype}_timestamp",
        "unit_or_currency": "timestamp",
        "temporal_granularity": "second",
        "geographic_level": "not_geographic",
        "entity_type": "taxi_trip_event",
        "domain_vocabulary": "NYC taxi trip lifecycle",
        "allowed_values_known": "no",
        "is_foreign_key": "no",
        "is_composite_key_part": "maybe",
        "possible_composite_key_with": "other trip lifecycle/location fields, but not reliable as true identity",
        "could_be_key_by_uniqueness": "yes",
        "is_high_uniqueness_but_not_key": "yes",
        "key_rejection_reason": "timestamp_lifecycle_field_not_identity",
        "entity_name_vs_identifier": "neither_identifier_nor_name",
        "naming_evidence_strength": "strong_datetime_name",
        "ucc_candidate_status": "statistical_single_column_ucc_candidate_but_semantically_rejected",
        "fd_determinant_candidate": "weak_or_accidental",
        "fd_dependent_candidate": "yes_for_time_order_relationships",
        "ind_candidate_status": "not_expected",
        "order_dependency_candidate": "yes_pickup_before_dropoff",
        "monotonic_or_sequence": "no_global_sequence",
        "derived_or_calculated_field": "no",
        "is_datetime_or_lifecycle_event": "yes",
        "lifecycle_event_type": lifecycle,
        "timezone_or_locale_risk": "yes_timezone_not_explicit",
        "seasonality_or_periodicity_risk": "yes_hour_day_patterns",
        "is_geographic_or_location": "no",
        "postal_or_admin_code": "no",
        "is_measure_or_metric": "no",
        "is_money_amount": "no",
        "is_count_or_quantity": "no",
        "is_rate_ratio_or_percentage": "no",
        "is_bounded_numeric": "no",
        "zero_heavy": "no",
        "negative_allowed": "no",
        "outlier_sensitive": "yes_extreme_dates_possible",
        "ordinal_category": "no",
        "nominal_category": "no",
        "boolean_like": "no",
        "free_text_or_description": "no",
        "has_missing_values": "no",
        "missingness_severity": "none",
        "missingness_semantics": "complete_observed_event_time",
        "invalid_value_risk": "medium_bad_dates_or_wrong_order_possible",
        "standardization_risk": "medium_datetime_format_may_vary_across_sources",
        "mixed_type_risk": "low",
        "format_consistency_risk": "medium",
        "unit_consistency_risk": "medium_timezone_implicit",
        "dirty_data_examples": "invalid dates, future timestamps, pickup after dropoff, dropoff before pickup",
        "pii_or_sensitive": "quasi_sensitive",
        "pii_type": "mobility_time_when_combined_with_locations",
        "sample_size_sensitivity": "high",
        "small_sample_false_key_risk": "high",
        "noise_sensitivity": "medium",
        "adaptive_sampling_priority": "high",
        "min_recommended_sample_size": "5000_or_full_for_key_decision",
        "confidence_interval_priority": "high",
        "expected_buckaroo_role": "datetime_high_uniqueness",
        "expected_warning_type": "unique_timestamp_not_primary_key",
        "should_buckaroo_warn": "yes",
        "expected_confidence_behavior": "high_datetime_confidence_low_key_confidence",
        "profiler_failure_mode_to_test": "false_key_from_high_uniqueness_datetime",
        "metanome_expected_behavior": "may report as UCC-like due to near uniqueness; semantic rejection needed outside Metanome",
        "deequ_expected_constraint": "Completeness high; uniqueness high but not a primary-key constraint",
        "dataprofiler_expected_behavior": "datetime/string parse with high uniqueness",
        "llm_semantic_label_expected": f"{subtype} datetime",
        "why_this_label": f"Trip {subtype.replace('_', ' ')} describes a ride lifecycle event, not row identity.",
        "edge_case_or_risk": "Almost unique values can fool uniqueness-based profilers into false key detection.",
        "research_use_case": "Core evidence for separating mathematical uniqueness from semantic identity.",
    }
    if column == "pickup":
        label["reviewer_notes"] = "Excel may display this as ####### until column width is expanded."
    else:
        label["reviewer_notes"] = "Should satisfy dropoff >= pickup for most valid rows."
    return label


def numeric_fill(
    role: str,
    subtype: str,
    physical: str,
    unit: str,
    reason: str,
    failure_mode: str,
    *,
    money: bool = False,
    count: bool = False,
    zero_heavy: str = "no",
    derived: str = "no",
    derived_from: str = "",
) -> Dict[str, str]:
    return {
        **common_non_key(),
        "manual_true_role": "numeric_measure",
        "manual_secondary_role": role,
        "manual_physical_type": physical,
        "semantic_group": "measure",
        "semantic_subtype": subtype,
        "unit_or_currency": unit,
        "temporal_granularity": "not_temporal",
        "geographic_level": "not_geographic",
        "entity_type": "taxi_trip_attribute",
        "domain_vocabulary": "taxi trip metrics",
        "allowed_values_known": "no" if not count else "yes_small_range_observed",
        "is_foreign_key": "no",
        "is_composite_key_part": "no",
        "could_be_key_by_uniqueness": "no",
        "is_high_uniqueness_but_not_key": "no",
        "key_rejection_reason": "measure_not_identity",
        "entity_name_vs_identifier": "neither_identifier_nor_name",
        "naming_evidence_strength": "strong_measure_name",
        "ucc_candidate_status": "not_ucc_candidate",
        "fd_determinant_candidate": "no",
        "fd_dependent_candidate": "maybe_correlated_or_formula_dependent",
        "ind_candidate_status": "not_expected",
        "order_dependency_candidate": "no",
        "monotonic_or_sequence": "no",
        "derived_or_calculated_field": derived,
        "derived_from_columns": derived_from,
        "is_datetime_or_lifecycle_event": "no",
        "timezone_or_locale_risk": "no",
        "seasonality_or_periodicity_risk": "maybe_time_of_day_effects",
        "is_geographic_or_location": "no",
        "postal_or_admin_code": "no",
        "is_measure_or_metric": "yes",
        "is_money_amount": "yes" if money else "no",
        "is_count_or_quantity": "yes" if count else "no",
        "is_rate_ratio_or_percentage": "no",
        "is_bounded_numeric": "yes" if count else "yes_lower_bound_only",
        "expected_min": "0",
        "expected_max": "6_observed" if count else "unknown_positive",
        "zero_heavy": zero_heavy,
        "negative_allowed": "no",
        "outlier_sensitive": "yes",
        "ordinal_category": "no",
        "nominal_category": "no",
        "boolean_like": "no",
        "free_text_or_description": "no",
        "has_missing_values": "no",
        "missingness_severity": "none",
        "missingness_semantics": "complete_measure",
        "invalid_value_risk": "medium_negative_or_extreme_values_possible",
        "standardization_risk": "low",
        "mixed_type_risk": "low",
        "format_consistency_risk": "low",
        "unit_consistency_risk": "medium_unit_or_currency_assumed",
        "dirty_data_examples": "negative value, impossible high value, inconsistent total",
        "pii_or_sensitive": "no",
        "sample_size_sensitivity": "medium" if zero_heavy == "yes" or count else "low",
        "small_sample_false_key_risk": "low",
        "noise_sensitivity": "medium",
        "adaptive_sampling_priority": "low",
        "min_recommended_sample_size": "500",
        "confidence_interval_priority": "medium",
        "expected_buckaroo_role": "numeric_measure_money" if money else ("numeric_measure_count" if count else "numeric_measure"),
        "expected_warning_type": "zero_heavy_distribution_optional" if zero_heavy == "yes" else "range_outlier_optional",
        "should_buckaroo_warn": "optional",
        "expected_confidence_behavior": "high_numeric_confidence_low_key_confidence",
        "profiler_failure_mode_to_test": failure_mode,
        "metanome_expected_behavior": "not a key; may appear in numeric dependencies or correlations",
        "deequ_expected_constraint": "Completeness; non-negative; range/outlier checks",
        "dataprofiler_expected_behavior": "numeric with distribution statistics",
        "llm_semantic_label_expected": subtype,
        "why_this_label": reason,
        "edge_case_or_risk": "Can repeat or have many decimals but is still a measure, not an identifier.",
        "research_use_case": "Tests numeric semantics, quality constraints, and key rejection.",
    }


def categorical_fill(column: str, subtype: str, missing: bool) -> Dict[str, str]:
    return {
        **common_non_key(),
        "manual_true_role": "categorical",
        "manual_secondary_role": subtype,
        "manual_physical_type": "string",
        "semantic_group": "category",
        "semantic_subtype": subtype,
        "geographic_level": "not_geographic",
        "entity_type": "taxi_trip_attribute",
        "domain_vocabulary": "finite observed categories",
        "allowed_values_known": "yes_observed_values",
        "is_foreign_key": "no",
        "is_composite_key_part": "no",
        "could_be_key_by_uniqueness": "no",
        "is_high_uniqueness_but_not_key": "no",
        "key_rejection_reason": "low_cardinality_category",
        "entity_name_vs_identifier": "neither_identifier_nor_name",
        "naming_evidence_strength": "strong_category_name",
        "ucc_candidate_status": "not_ucc_candidate",
        "fd_determinant_candidate": "possible_grouping_attribute",
        "fd_dependent_candidate": "no",
        "ind_candidate_status": "not_expected",
        "order_dependency_candidate": "no",
        "monotonic_or_sequence": "no",
        "derived_or_calculated_field": "no",
        "is_datetime_or_lifecycle_event": "no",
        "timezone_or_locale_risk": "no",
        "seasonality_or_periodicity_risk": "no",
        "is_geographic_or_location": "no",
        "postal_or_admin_code": "no",
        "is_measure_or_metric": "no",
        "is_money_amount": "no",
        "is_count_or_quantity": "no",
        "is_rate_ratio_or_percentage": "no",
        "is_bounded_numeric": "no",
        "zero_heavy": "no",
        "negative_allowed": "no",
        "outlier_sensitive": "no",
        "ordinal_category": "no",
        "nominal_category": "yes",
        "boolean_like": "no",
        "free_text_or_description": "no",
        "has_missing_values": "yes" if missing else "no",
        "missingness_severity": "low" if missing else "none",
        "missingness_semantics": "missing category values" if missing else "complete category",
        "invalid_value_risk": "medium_unexpected_category_possible",
        "standardization_risk": "medium_case_or_spelling_variants_possible",
        "mixed_type_risk": "low",
        "format_consistency_risk": "low",
        "unit_consistency_risk": "no",
        "dirty_data_examples": "unexpected category spelling",
        "pii_or_sensitive": "no",
        "sample_size_sensitivity": "low",
        "small_sample_false_key_risk": "low",
        "noise_sensitivity": "medium",
        "adaptive_sampling_priority": "low",
        "min_recommended_sample_size": "100",
        "confidence_interval_priority": "medium",
        "expected_buckaroo_role": "categorical",
        "expected_warning_type": "low_missingness" if missing else "none",
        "should_buckaroo_warn": "yes" if missing else "no",
        "expected_confidence_behavior": "high_category_confidence_low_key_confidence",
        "profiler_failure_mode_to_test": "category_with_missingness" if missing else "standard_category",
        "metanome_expected_behavior": "not a key; low-cardinality grouping column",
        "deequ_expected_constraint": "Completeness; finite set compliance",
        "dataprofiler_expected_behavior": "string categorical low cardinality",
        "llm_semantic_label_expected": subtype,
        "why_this_label": f"{column} is a repeated nominal category.",
        "edge_case_or_risk": "Missing or unexpected categories can affect quality checks." if missing else "Clear nominal category.",
        "research_use_case": "Tests categorical recognition and missingness warning." if missing else "Tests standard categorical recognition.",
        "reviewer_notes": "Payment has 44 missing values." if column == "payment" else "",
    }


def location_fill(column: str, subtype: str, level: str, fk: str) -> Dict[str, str]:
    return {
        **common_non_key(),
        "manual_true_role": "location_name",
        "manual_secondary_role": "categorical",
        "manual_physical_type": "string",
        "semantic_group": "location",
        "semantic_subtype": subtype,
        "temporal_granularity": "not_temporal",
        "geographic_level": level,
        "entity_type": "place_attribute",
        "domain_vocabulary": "NYC taxi geography",
        "allowed_values_known": "yes_if_zone_lookup_available",
        "is_foreign_key": fk,
        "foreign_key_target_if_known": "NYC taxi zone lookup table possible" if fk == "maybe" else "",
        "is_composite_key_part": "no",
        "could_be_key_by_uniqueness": "no",
        "is_high_uniqueness_but_not_key": "no",
        "key_rejection_reason": "location_category_not_row_identity",
        "entity_name_vs_identifier": "entity_or_place_name",
        "naming_evidence_strength": "strong_location_name",
        "ucc_candidate_status": "not_ucc_candidate",
        "fd_determinant_candidate": "possible_grouping_or_lookup_attribute",
        "fd_dependent_candidate": "yes_borough_dependent_on_zone_possible" if level == "borough" else "no",
        "ind_candidate_status": "possible_if_external_location_lookup_exists" if fk == "maybe" else "not_expected",
        "order_dependency_candidate": "no",
        "monotonic_or_sequence": "no",
        "derived_or_calculated_field": "no",
        "is_datetime_or_lifecycle_event": "no",
        "timezone_or_locale_risk": "no",
        "seasonality_or_periodicity_risk": "no",
        "is_geographic_or_location": "yes",
        "location_semantic_type": subtype,
        "postal_or_admin_code": "no",
        "is_measure_or_metric": "no",
        "is_money_amount": "no",
        "is_count_or_quantity": "no",
        "is_rate_ratio_or_percentage": "no",
        "is_bounded_numeric": "no",
        "zero_heavy": "no",
        "negative_allowed": "no",
        "outlier_sensitive": "no",
        "ordinal_category": "no",
        "nominal_category": "yes",
        "boolean_like": "no",
        "free_text_or_description": "no",
        "has_missing_values": "yes",
        "missingness_severity": "low",
        "missingness_semantics": "unknown or unmatched taxi zone",
        "invalid_value_risk": "medium_unrecognized_location_name_possible",
        "standardization_risk": "medium_spelling_or_alias_variants_possible",
        "mixed_type_risk": "low",
        "format_consistency_risk": "medium",
        "unit_consistency_risk": "no",
        "dirty_data_examples": "misspelled zone, unknown borough, blank location",
        "pii_or_sensitive": "quasi_sensitive",
        "pii_type": "trip_location_when_combined_with_time",
        "sample_size_sensitivity": "medium",
        "small_sample_false_key_risk": "low",
        "noise_sensitivity": "medium",
        "adaptive_sampling_priority": "medium" if level == "taxi_zone" else "low",
        "min_recommended_sample_size": "1000",
        "confidence_interval_priority": "medium",
        "expected_buckaroo_role": "location_name",
        "expected_warning_type": "location_field_not_key_and_low_missingness",
        "should_buckaroo_warn": "yes",
        "expected_confidence_behavior": "high_location_confidence_low_key_confidence",
        "profiler_failure_mode_to_test": "location_category_vs_foreign_key" if fk == "maybe" else "location_category_detection",
        "metanome_expected_behavior": "not a row key; may reveal dependencies between zones and boroughs",
        "deequ_expected_constraint": "Completeness; finite set compliance if reference list available",
        "dataprofiler_expected_behavior": "string categorical with location semantics only if semantic labeler available",
        "llm_semantic_label_expected": subtype,
        "why_this_label": f"{column} is a repeated NYC place label, not the identity of a taxi trip.",
        "edge_case_or_risk": "Location fields can be misread as plain categories or foreign keys without context.",
        "research_use_case": "Tests geography/location semantic safeguards and missingness handling.",
        "reviewer_notes": "Zone fields could be foreign-key-like with an external zone lookup table; mark maybe, not yes.",
    }


def taxi_labels() -> Dict[str, Dict[str, str]]:
    labels = {
        "pickup": datetime_fill("pickup", "pickup", "start_event"),
        "dropoff": datetime_fill("dropoff", "dropoff", "end_event"),
        "passengers": numeric_fill(
            "discrete_count",
            "person_count",
            "integer",
            "passengers",
            "Number of passengers is a count measure, even though it has few unique values.",
            "numeric_count_vs_category",
            count=True,
            zero_heavy="low",
        ),
        "distance": numeric_fill(
            "continuous_measure",
            "trip_distance",
            "float",
            "miles_likely",
            "Distance is a physical measurement of the ride.",
            "standard_numeric_measure_with_outliers",
        ),
        "fare": numeric_fill(
            "money_amount",
            "base_fare",
            "float",
            "USD",
            "Base fare is a money amount for the taxi ride.",
            "standard_money_measure",
            money=True,
        ),
        "tip": numeric_fill(
            "money_amount",
            "tip_amount",
            "float",
            "USD",
            "Tip is a money amount and many rides have zero tip.",
            "zero_heavy_money_measure",
            money=True,
            zero_heavy="yes",
        ),
        "tolls": numeric_fill(
            "money_amount",
            "toll_amount",
            "float",
            "USD",
            "Tolls are money amounts with many zeros and few unique values.",
            "low_cardinality_money_measure",
            money=True,
            zero_heavy="yes",
        ),
        "total": numeric_fill(
            "money_amount",
            "total_paid",
            "float",
            "USD",
            "Total is a derived-looking money amount for the ride.",
            "derived_total_measure_not_key",
            money=True,
            derived="yes",
            derived_from="fare, tip, tolls, taxes/fees not all present",
        ),
        "color": categorical_fill("color", "vehicle_type", False),
        "payment": categorical_fill("payment", "payment_method", True),
        "pickup_zone": location_fill("pickup_zone", "pickup_zone_name", "taxi_zone", "maybe"),
        "dropoff_zone": location_fill("dropoff_zone", "dropoff_zone_name", "taxi_zone", "maybe"),
        "pickup_borough": location_fill("pickup_borough", "pickup_borough_name", "borough", "no"),
        "dropoff_borough": location_fill("dropoff_borough", "dropoff_borough_name", "borough", "no"),
    }
    return labels


def enrich_meeting_followups(row: Dict[str, object]) -> None:
    """Fill labels that came from professor/meeting follow-up questions."""

    role = str(row.get("manual_true_role", ""))
    group = str(row.get("semantic_group", ""))
    column = str(row.get("column_name", ""))
    warning = str(row.get("expected_warning_type", "none"))

    defaults = {
        "runtime_tracking_needed": "yes",
        "compare_against_external_baseline": "yes",
        "ui_should_show_confidence_interval": "yes",
        "ui_should_show_warning_badge": "yes" if warning not in {"", "none"} else "no",
        "manual_label_priority": "medium",
        "benchmark_importance": "medium",
        "poster_worthy_example": "no",
        "needs_domain_dictionary": "no",
        "dictionary_or_reference_source": "",
    }
    row.update({k: row.get(k, "") or v for k, v in defaults.items()})

    if role == "datetime":
        row.update(
            {
                "requires_semantic_ml": "no",
                "semantic_ml_use_case": "not_needed_for_type_detection",
                "recommended_semantic_model": "datetime_parser_plus_column_name_rules",
                "sbert_use_recommended": "no",
                "sbert_input_signal": "not_applicable",
                "sbert_expected_benefit": "low; parser and timestamp safeguard are enough",
                "simple_rules_enough": "yes",
                "semantic_ml_priority": "low",
                "semantic_context_needed": "column name plus parseable datetime values",
                "advanced_ml_analysis_reason": "No advanced ML is needed to detect datetime; the important part is semantic key rejection.",
                "expected_candidate_roles": "datetime_high_uniqueness:high; primary_key:low; categorical:low",
                "expected_candidate_confidence_pattern": "high datetime confidence, high uniqueness evidence, low semantic key confidence",
                "low_confidence_adaptive_sampling_trigger": "high uniqueness plus small sample plus datetime role",
                "adaptive_sampling_stop_condition": "datetime parse interval remains high and key confidence remains low after larger sample",
                "ui_user_facing_explanation": "This column is almost unique, but it is a lifecycle timestamp, not a row identifier.",
                "professor_question_to_answer": "Why is a nearly unique timestamp not a primary key?",
                "benchmark_importance": "high",
                "manual_label_priority": "high",
                "geography_safeguard_relevance": "no",
                "timestamp_safeguard_relevance": "yes",
                "confidence_interval_metric_to_watch": "datetime_parse_ratio and uniqueness_ratio",
                "row_sampling_failure_mode": "small samples can make timestamps look like perfect keys",
                "noise_failure_mode": "date corruption can reduce parse confidence or create mixed-type behavior",
                "poster_worthy_example": "yes",
                "paper_claim_supported": "confidence-aware Buckaroo separates uniqueness from semantic identity",
            }
        )
        return

    if group == "location":
        use_sbert = "yes" if "zone" in column else "maybe"
        simple_rules = "maybe" if "zone" in column else "yes"
        model = "dictionary_lookup_plus_sbert_or_llm" if "zone" in column else "location_dictionary_or_rules"
        row.update(
            {
                "requires_semantic_ml": "maybe" if "zone" in column else "no",
                "semantic_ml_use_case": "place_name_semantic_detection",
                "recommended_semantic_model": model,
                "sbert_use_recommended": use_sbert,
                "sbert_input_signal": "column header plus distinct location-name values",
                "sbert_expected_benefit": "helps recognize place names and zone labels when dictionaries are incomplete",
                "simple_rules_enough": simple_rules,
                "semantic_ml_priority": "medium" if "zone" in column else "low",
                "semantic_context_needed": "location vocabulary, column name, and repeated place values",
                "advanced_ml_analysis_reason": "Useful when names are not obvious geographic tokens or when zone names look like generic text.",
                "expected_candidate_roles": "location_name:high; categorical:medium; foreign_key:maybe; primary_key:low",
                "expected_candidate_confidence_pattern": "high location confidence if names match place vocabulary; low key confidence",
                "low_confidence_adaptive_sampling_trigger": "ambiguous string category with location-like names and missing values",
                "adaptive_sampling_stop_condition": "location confidence stabilizes and key confidence remains low",
                "ui_user_facing_explanation": "This column is a repeated location label; it may link to a lookup table but should not identify taxi-trip rows.",
                "professor_question_to_answer": "Is this just a category, a foreign key, or a semantic location field?",
                "benchmark_importance": "high" if "zone" in column else "medium",
                "manual_label_priority": "high" if "zone" in column else "medium",
                "geography_safeguard_relevance": "yes",
                "timestamp_safeguard_relevance": "no",
                "confidence_interval_metric_to_watch": "location distinctness, missingness, and key confidence",
                "row_sampling_failure_mode": "small samples may miss rare locations and understate domain size",
                "noise_failure_mode": "misspellings or replaced values can break dictionary matching",
                "poster_worthy_example": "yes" if "zone" in column else "maybe",
                "paper_claim_supported": "geography-aware semantics prevent location fields from being misread as row identity",
                "needs_domain_dictionary": "yes",
                "dictionary_or_reference_source": "NYC taxi zone lookup or geographic place-name dictionary",
            }
        )
        return

    if role == "numeric_measure":
        is_count = str(row.get("is_count_or_quantity", "")) == "yes"
        is_money = str(row.get("is_money_amount", "")) == "yes"
        row.update(
            {
                "requires_semantic_ml": "no",
                "semantic_ml_use_case": "not_needed_for_basic_numeric_detection",
                "recommended_semantic_model": "numeric_statistics_plus_column_name_rules",
                "sbert_use_recommended": "no",
                "sbert_input_signal": "not_applicable",
                "sbert_expected_benefit": "low for pure numeric values; column-name embeddings may help subtype only",
                "simple_rules_enough": "yes",
                "semantic_ml_priority": "low",
                "semantic_context_needed": "column name, numeric distribution, units/ranges",
                "advanced_ml_analysis_reason": "Advanced ML is usually unnecessary; range, units, and constraints matter more.",
                "expected_candidate_roles": "numeric_measure:high; categorical:medium_if_low_cardinality; primary_key:low",
                "expected_candidate_confidence_pattern": "high numeric confidence, key confidence low, category confidence possible for low-cardinality counts",
                "low_confidence_adaptive_sampling_trigger": "low-cardinality numeric values or zero-heavy distribution",
                "adaptive_sampling_stop_condition": "numeric confidence remains high and outlier/range estimates stabilize",
                "ui_user_facing_explanation": "This column is a numeric measure; repeated or rounded values do not make it categorical by default.",
                "professor_question_to_answer": "Why are low-cardinality numbers like passenger counts still numeric measures?",
                "geography_safeguard_relevance": "no",
                "timestamp_safeguard_relevance": "no",
                "confidence_interval_metric_to_watch": "numeric_parse_ratio, cardinality, zero_ratio, range stability",
                "row_sampling_failure_mode": "small samples may miss outliers or make numeric counts look categorical",
                "noise_failure_mode": "replaced values can create mixed-type numeric columns",
                "paper_claim_supported": "Buckaroo should report candidate roles instead of forcing one brittle label",
                "needs_domain_dictionary": "no",
                "dictionary_or_reference_source": "optional units/currency dictionary" if is_money else "",
            }
        )
        if is_count or is_money:
            row["poster_worthy_example"] = "maybe"
            row["benchmark_importance"] = "medium"
        return

    if role == "categorical":
        row.update(
            {
                "requires_semantic_ml": "no",
                "semantic_ml_use_case": "not_needed_for_simple_low_cardinality_category",
                "recommended_semantic_model": "dictionary_lookup_or_value_set_rules",
                "sbert_use_recommended": "no",
                "sbert_input_signal": "column header and distinct category values only if labels become ambiguous",
                "sbert_expected_benefit": "low for simple categories like payment or color",
                "simple_rules_enough": "yes",
                "semantic_ml_priority": "low",
                "semantic_context_needed": "distinct values and column name",
                "advanced_ml_analysis_reason": "Simple category detection and value-set checks are enough.",
                "expected_candidate_roles": "categorical:high; boolean:low_or_medium_if_two_values; primary_key:low",
                "expected_candidate_confidence_pattern": "high categorical confidence and low key confidence",
                "low_confidence_adaptive_sampling_trigger": "rare categories or missing values appear in larger samples",
                "adaptive_sampling_stop_condition": "category domain and missingness estimate stabilize",
                "ui_user_facing_explanation": "This column contains repeated category values.",
                "professor_question_to_answer": "Can Buckaroo separate simple categories from semantic location/entity fields?",
                "geography_safeguard_relevance": "no",
                "timestamp_safeguard_relevance": "no",
                "confidence_interval_metric_to_watch": "distinct_ratio and top_value_ratio",
                "row_sampling_failure_mode": "small samples may miss rare categories",
                "noise_failure_mode": "value replacement can introduce invalid categories",
                "paper_claim_supported": "confidence-aware profiling can warn when category coverage is incomplete",
                "needs_domain_dictionary": "yes",
                "dictionary_or_reference_source": "known allowed value set if available",
            }
        )


def write_csv(path: Path, rows: Iterable[Dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def write_codebook() -> None:
    CODEBOOK_OUT.write_text(
        """# Research-Grade Manual Labeling Codebook

This is the final expanded annotation schema for the Buckaroo profiler benchmark. It is intentionally broad: the goal is to support semantic role accuracy, false-key analysis, dependency analysis, data-quality checks, sampling fragility, and profiler-specific expected behavior without redesigning the worksheet again.

## Files

- `manual_column_labeling_research_grade_blank.csv`: all five datasets, computed evidence filled, human labels blank.
- `manual_column_labeling_research_grade_with_taxi_filled.csv`: all five datasets, taxi labels filled.
- `taxi_trips_manual_labels_research_grade_filled.csv`: taxi-only review file.

## Research Inspirations

- Data profiling survey: structural metadata, statistics, UCCs, FDs, INDs, and conditional properties.
- Metanome: UCC, FD, IND, order dependency, and runtime comparison mindset.
- Deequ: completeness, uniqueness, compliance, non-negativity, and constraint-style quality checks.
- Sherlock/Sato/Pythagoras: semantic type detection should use values, column names, context, and numerical semantics.
- Buckaroo-specific contribution: separate mathematical uniqueness from semantic identity, especially for timestamps and geographic/location fields.

## Most Important Fields

- `manual_true_role`: the human semantic answer.
- `could_be_key_by_uniqueness`: whether the column looks key-like statistically.
- `should_be_key_candidate_for_buckaroo`: whether Buckaroo should actually consider it as a key.
- `is_high_uniqueness_but_not_key`: critical for timestamps, coordinates, names, prices, and codes.
- `key_rejection_reason`: why a key-looking column should not be a key.
- `ucc_candidate_status`, `fd_determinant_candidate`, `fd_dependent_candidate`, `ind_candidate_status`: what dependency profilers may find.
- `sample_size_sensitivity`, `small_sample_false_key_risk`, `adaptive_sampling_priority`: whether Buckaroo should sample more rows.
- `expected_buckaroo_role`, `expected_warning_type`, `expected_confidence_behavior`: turns the manual label into a test assertion.
- `requires_semantic_ml`, `recommended_semantic_model`, `sbert_use_recommended`: whether the column deserves advanced semantic ML such as SBERT, an LLM, or a semantic type model.
- `simple_rules_enough`: whether lightweight rules/statistics are enough for this column.
- `expected_candidate_roles`, `expected_candidate_confidence_pattern`: the multi-candidate output Buckaroo should eventually expose.
- `low_confidence_adaptive_sampling_trigger`, `adaptive_sampling_stop_condition`: when Buckaroo should sample more rows and when it can stop.
- `ui_user_facing_explanation`, `ui_should_show_warning_badge`: what the interface should explain to users.
- `professor_question_to_answer`, `poster_worthy_example`, `paper_claim_supported`: why the column matters for the research story.

## Golden Rule

A column can be mathematically unique and still not be semantically a primary key. Preserve that distinction.

## SBERT / Semantic ML Rule

Use SBERT or similar semantic ML only when value meaning is textual and not obvious from simple parsing. Good candidates are place names, organization names, product names, occupations, descriptions, and ambiguous codes. Bad candidates are plain datetimes, pure numbers, money amounts, simple booleans, and tiny value sets where rules or dictionaries are enough.
""",
        encoding="utf-8",
    )


def main() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, object]] = []
    for dataset in DATASETS:
        rows.extend(read_dataset_stats(BASE / dataset))

    blank_rows = [dict(row) for row in rows]
    filled_rows = [dict(row) for row in rows]
    labels = taxi_labels()
    for row in filled_rows:
        if row["dataset_id"] == "taxi_trips":
            row.update(labels.get(str(row["column_name"]), {}))
            enrich_meeting_followups(row)

    write_csv(BLANK_OUT, blank_rows)
    write_csv(FILLED_OUT, filled_rows)
    write_csv(TAXI_OUT, [row for row in filled_rows if row["dataset_id"] == "taxi_trips"])
    write_codebook()

    print(BLANK_OUT)
    print(FILLED_OUT)
    print(TAXI_OUT)
    print(CODEBOOK_OUT)
    print(f"columns={len(FIELDNAMES)} rows={len(rows)}")


if __name__ == "__main__":
    main()
