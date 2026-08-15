"""Audit fixed decisions in Buckaroo's clustering and its direct dependencies.

The production row-grouping result is not controlled by one parameter file. It
is assembled from the multi-view implementation, API/UI request defaults, the
column profiler, and the quality detectors. Historical experiment scripts add
another layer of parameter grids. This script keeps those scopes separate while
producing one machine-readable inventory.

Run from the repository root:

    python experiments/audit_clustering_thresholds.py
    python experiments/audit_clustering_thresholds.py --check

The audit is deliberately code-backed. Every curated item contains a source
fragment that must still exist. If a refactor removes or changes that fragment,
``--check`` fails instead of silently leaving a stale line reference in the
research documentation.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "clustering_threshold_audit_20260719"


@dataclass(frozen=True)
class AuditItem:
    threshold_id: str
    scope: str
    component: str
    category: str
    value: str
    unit: str
    source_file: str
    source_pattern: str
    controls: str
    decision_kind: str
    current_basis: str
    evidence_status: str
    sensitivity_risk: str
    recommended_treatment: str
    occurrence: int = 1


def item(
    threshold_id: str,
    scope: str,
    component: str,
    category: str,
    value: object,
    unit: str,
    source_file: str,
    source_pattern: str,
    controls: str,
    decision_kind: str = "fixed_heuristic",
    current_basis: str = "Engineering choice in the current implementation.",
    evidence_status: str = "not_calibrated_on_current_multiview",
    sensitivity_risk: str = "medium",
    recommended_treatment: str = "Include in a multi-dataset sensitivity study.",
    occurrence: int = 1,
) -> AuditItem:
    return AuditItem(
        threshold_id=threshold_id,
        scope=scope,
        component=component,
        category=category,
        value=str(value),
        unit=unit,
        source_file=source_file,
        source_pattern=source_pattern,
        controls=controls,
        decision_kind=decision_kind,
        current_basis=current_basis,
        evidence_status=evidence_status,
        sensitivity_risk=sensitivity_risk,
        recommended_treatment=recommended_treatment,
        occurrence=occurrence,
    )


def pre_adaptive_production_multiview_items() -> list[AuditItem]:
    """Historical snapshot retained for comparison with the adaptive policy."""
    f = "app/server_utils/multi_view_grouping.py"
    scope = "production_multiview"
    return [
        item("mv.sample_seed", scope, "sampling", "reproducibility_seed", 20260717, "seed", f, "MULTI_VIEW_SAMPLE_SEED = 20260717", "Determines which deterministic random rows enter the clustering sample.", "reproducibility_seed", "Chosen to make UI results repeatable; it is not a quality threshold.", "methodological_choice", "low", "Keep fixed for reproducibility and add repeated seeds in experiments."),
        item("mv.default_sample_rows", scope, "sampling", "sample_size", 3000, "rows", f, "DEFAULT_SAMPLE_ROWS = 3000", "Default maximum rows inspected by the module when the caller supplies no sample size.", sensitivity_risk="high", recommended_treatment="Calibrate accuracy/stability/runtime curves and centralize the chosen default."),
        item("mv.sample_rows_hard_cap", scope, "sampling", "sample_size", 10000, "rows", f, "min(int(sample_rows or DEFAULT_SAMPLE_ROWS), 10000)", "Prevents API callers from asking the production multi-view path to cluster more than 10,000 rows.", sensitivity_risk="high", recommended_treatment="Replace with a resource budget or measured adaptive stopping rule."),
        item("mv.default_result_limit", scope, "presentation", "result_limit", 12, "groups", f, "DEFAULT_LIMIT = 12", "Default number of accepted groups returned when no caller limit is supplied.", "display_limit", sensitivity_risk="medium", recommended_treatment="Treat as a UI capacity choice and test whether users can review this many groups."),
        item("mv.result_limit_cap", scope, "presentation", "result_limit", 30, "groups", f, "min(int(limit or DEFAULT_LIMIT), 30)", "Hard upper bound on groups returned by the backend.", "display_limit", sensitivity_risk="low", recommended_treatment="Centralize with the UI and retain as a payload safeguard."),
        item("mv.default_min_group_size", scope, "candidate_generation", "minimum_support", 8, "rows", f, "DEFAULT_MIN_GROUP_SIZE = 8", "Smallest ordinary semantic cluster that can become a displayed group.", sensitivity_risk="high", recommended_treatment="Make support relative to dataset size and validate against human usefulness ratings."),
        item("mv.min_group_floor", scope, "candidate_generation", "minimum_support", 2, "rows", f, "min_group_size = max(2, int(min_group_size or DEFAULT_MIN_GROUP_SIZE))", "Absolute floor preventing singleton groups when a caller asks for a smaller minimum.", current_basis="A group needs at least two rows to be a repeated pattern.", evidence_status="structural_safeguard", sensitivity_risk="low", recommended_treatment="Keep as a structural floor; adapt the practical minimum above it."),
        item("mv.quality_support_ratio", scope, "quality_view", "minimum_support", "max(2, semantic_min // 2)", "rows", f, "min_group_size=max(2, min_group_size // 2)", "Allows quality-pattern groups to use half the support required for semantic groups.", sensitivity_risk="high", recommended_treatment="Test whether the half-size exception increases useful rare issues or false discoveries."),
        item("mv.max_columns_per_view", scope, "feature_routing", "feature_cap", 20, "columns", f, "MAX_COLUMNS_PER_VIEW = 20", "Generic cap applied when ranked profiler-approved columns are selected for a view.", sensitivity_risk="high", recommended_treatment="Use cumulative evidence/variance coverage instead of a fixed column count."),
        item("mv.max_group_row_ids", scope, "serialization", "payload_limit", 2000, "row IDs", f, "MAX_GROUP_ROW_IDS = 2000", "Maximum member row IDs returned for any group.", "display_limit", current_basis="Bounds response size and browser memory.", evidence_status="resource_safeguard", sensitivity_risk="low", recommended_treatment="Keep but expose truncation metadata and test payload size."),
        item("mv.missing_profile_confidence", scope, "feature_routing", "confidence_fallback", 0.5, "probability", f, "safe_float(profile.get(\"confidenceScore\"), 0.5)", "Confidence assigned when a profiler record lacks a confidence score.", sensitivity_risk="high", recommended_treatment="Use an explicit unknown state; do not manufacture medium confidence."),
        item("mv.fallback_numeric_rule", scope, "feature_routing", "type_cutoff", "parse >= 0.90 and distinct > 3", "ratio/count", f, "if float(numeric.notna().mean()) >= 0.9 and non_missing.nunique() > 3", "Classifies an unprofiled column as numeric for clustering fallback logic.", sensitivity_risk="high", recommended_treatment="Reuse the profiler decision API rather than maintaining a second type rule."),
        item("mv.profiler_confidence_gate", scope, "feature_routing", "confidence_cutoff", 0.55, "probability", f, "if profile[\"confidence\"] < 0.55", "Excludes low-confidence columns from semantic clustering views.", sensitivity_risk="critical", recommended_treatment="Calibrate with held-out datasets; this gate can remove the columns that define the true groups."),
        item("mv.text_column_cap", scope, "feature_routing", "feature_cap", 6, "columns", f, "TEXT_ROLES], 6)", "Maximum profiler-approved text columns entering the text view.", sensitivity_risk="high", recommended_treatment="Select by cumulative semantic contribution and test 3/6/12/all."),
        item("mv.lifecycle_column_cap", scope, "feature_routing", "feature_cap", 10, "columns", f, "lifecycle = ranked(list(dict.fromkeys([*temporal, *status])), 10)", "Maximum temporal/status columns entering the lifecycle view.", sensitivity_risk="high", recommended_treatment="Select event columns by coverage and nonredundancy."),
        item("mv.geography_column_cap", scope, "feature_routing", "feature_cap", 10, "columns", f, "geography = ranked([", "Start of a geography selection that is capped at ten profiler-ranked columns.", sensitivity_risk="medium", recommended_treatment="Replace with coordinate-pair and hierarchy-aware selection."),
        item("mv.quality_column_cap", scope, "feature_routing", "feature_cap", 30, "columns", f, "quality = ranked(list(profile_map), 30)", "Maximum columns considered while building exact quality signatures.", sensitivity_risk="high", recommended_treatment="Measure missed error signatures as width grows; prefer detector-supported columns."),
        item("mv.duplicate_column_cap", scope, "feature_routing", "feature_cap", 12, "columns", f, ")[:12]", "Maximum non-key columns used in near-duplicate signatures.", sensitivity_risk="high", recommended_treatment="Select columns by entity-resolution information gain rather than rank position."),
        item("mv.numeric_min_valid", scope, "representation", "minimum_support", 3, "parsed values", f, "if values.notna().sum() < 3", "Skips a numeric feature when fewer than three values parse.", current_basis="At least a few observations are needed for a median and scale.", sensitivity_risk="medium", recommended_treatment="Use an effective-sample-size and missingness rule."),
        item("mv.numeric_confidence_weight", scope, "representation", "feature_weight", "0.50 + 0.50 * profiler confidence", "multiplier", f, "weight = 0.5 + (0.5 * profile_map[column][\"confidence\"])", "Weights each numeric and temporal feature between 0.5 and 1.0 according to profiler confidence.", sensitivity_risk="critical", recommended_treatment="Ablate confidence weighting and learn/calibrate the mapping on held-out datasets."),
        item("mv.numeric_robust_clip", scope, "representation", "outlier_cutoff", "[-4, 4], then divide by 4", "robust scale units", f, ".clip(-4, 4) / 4", "Winsorizes robust-scaled numeric and time values before distance computation.", current_basis="Common robust engineering guard, but the four-scale cutoff is still a choice.", sensitivity_risk="high", recommended_treatment="Sweep 2/3/4/6/no clip and report cluster stability."),
        item("mv.text_missing_confidence", scope, "representation", "confidence_fallback", 0.7, "probability", f, "confidence = prefixes.get(prefix, 0.7)", "Confidence assigned to a TF-IDF term when its source prefix cannot be matched to a profile.", sensitivity_risk="high", recommended_treatment="Preserve a feature-to-column map and remove this fallback."),
        item("mv.text_confidence_weight", scope, "representation", "feature_weight", "0.45 + 0.55 * profiler confidence", "multiplier", f, "weights.append(0.45 + (0.55 * confidence))", "Weights TF-IDF dimensions between 0.45 and 1.0 using source-column confidence.", sensitivity_risk="critical", recommended_treatment="Ablate and calibrate separately from numeric weighting."),
        item("mv.text_token_budgets", scope, "representation", "feature_cap", "80 free-text; 20 category", "tokens per cell", f, "token_limit = 80 if free_text else 20", "Limits how much each row/cell contributes to the text representation.", sensitivity_risk="high", recommended_treatment="Use length-normalized sampling and test truncation sensitivity."),
        item("mv.categorical_phrase_max_tokens", scope, "representation", "feature_cutoff", 4, "tokens", f, "0 < len(value_tokens) <= 4", "Creates a compound category token only for short values of four tokens or fewer.", sensitivity_risk="medium", recommended_treatment="Validate against category phrase length distributions."),
        item("mv.temporal_min_valid", scope, "representation", "minimum_support", 3, "parsed datetimes", f, "if values.notna().sum() < 3", "Skips a temporal feature or duration when fewer than three values parse.", sensitivity_risk="medium", recommended_treatment="Base this on parse-rate uncertainty and effective support."),
        item("mv.temporal_pair_cap", scope, "representation", "feature_cap", 6, "date pairs", f, "list(combinations(parsed, 2))[:6]", "Limits pairwise lifecycle-duration features to the first six date-column pairs.", sensitivity_risk="critical", recommended_treatment="Choose event pairs semantically or by observed dependency; column order must not decide."),
        item("mv.calendar_periods", scope, "representation", "domain_constant", "12 months; 7 weekdays; 24 hours", "cycle lengths", f, "(\"month\", values.dt.month.fillna(1), 12)", "Converts calendar fields into cyclical sine/cosine features.", "structural_constant", "Calendar definitions, not tunable clustering thresholds.", "domain_standard", "none", "Keep and document as structural constants."),
        item("mv.duration_seconds_per_day", scope, "representation", "domain_constant", 86400, "seconds/day", f, ".dt.total_seconds() / 86400.0", "Converts elapsed seconds to days for readable lifecycle features.", "structural_constant", "Unit conversion, not a tunable threshold.", "domain_standard", "none", "Keep."),
        item("mv.coordinate_pair_count", scope, "representation", "feature_cap", 1, "latitude/longitude pair", f, "latitude = latitudes[0]", "Uses only the first profiler-recognized latitude/longitude pair for spherical coordinate features.", sensitivity_risk="high", recommended_treatment="Support named coordinate pairs and test datasets containing origins and destinations."),
        item("mv.algorithm_size_switch", scope, "algorithm_selection", "sample_size_cutoff", 1200, "rows", f, "len(frame) <= 1200", "Uses agglomerative clustering for text/lifecycle at or below 1,200 rows, then switches to K-means.", sensitivity_risk="critical", recommended_treatment="Benchmark quality/runtime around the boundary or select by measured resource budget."),
        item("mv.dbscan_min_samples", scope, "algorithm_selection", "density_parameter", "clip(min_group_size, 4, 12)", "rows", f, "min_samples = max(4, min(12, min_group_size, n_rows))", "Sets DBSCAN core-neighborhood support.", "partially_adaptive", current_basis="Adapts to requested group size but uses fixed floor and ceiling.", sensitivity_risk="critical", recommended_treatment="Estimate from local density and validate stability across bootstrap samples."),
        item("mv.dbscan_eps", scope, "algorithm_selection", "distance_cutoff", "70th percentile, clipped [0.05, 0.55]", "cosine distance", f, "np.quantile(distances[:, -1], 0.70), 0.05, 0.55", "Sets the DBSCAN neighborhood radius from k-neighbor distances.", "partially_adaptive", current_basis="Data-derived center with unvalidated quantile and bounds.", sensitivity_risk="critical", recommended_treatment="Compare knee detection, quantile grids, and stability-based selection."),
        item("mv.dbscan_acceptance", scope, "algorithm_selection", "cluster_count_cutoff", 2, "non-noise clusters", f, "if len(non_noise) >= 2", "Falls back to K-means unless DBSCAN finds at least two non-noise groups.", current_basis="One group is not a useful partition.", sensitivity_risk="medium", recommended_treatment="Keep the two-group floor but also test noise fraction and stability."),
        item("mv.k_heuristic", scope, "algorithm_selection", "cluster_count", "max(2, min(8, floor(n/min_group), round(sqrt(n)/2)))", "clusters", f, "k = max(2, min(8, n_rows // max(1, min_group_size), int(round(math.sqrt(n_rows) / 2))))", "Chooses K for K-means/agglomerative without optimizing a cluster-validity objective.", "partially_adaptive", current_basis="Scales with sample size but contains fixed floor, cap, and divisor.", sensitivity_risk="critical", recommended_treatment="Select K by repeated stability plus explainability, with a complexity penalty."),
        item("mv.kmeans_seeds", scope, "stability", "reproducibility_seed", "42 primary; 137 alternate", "seeds", f, "unique_labels = sg.kmeans(unique_matrix, k, random_seed=42)", "Runs two deterministic K-means initializations to estimate matched-overlap stability.", "reproducibility_seed", current_basis="Two fixed seeds provide a cheap repeatability check.", evidence_status="methodological_choice", sensitivity_risk="high", recommended_treatment="Use at least 10 seeds in experiments; production may retain two after validation."),
        item("mv.perturbation", scope, "stability", "perturbation_size", "seed 20260717; sigma 1e-4", "normalized feature units", f, "rng.normal(0.0, 1e-4, matrix.shape)", "Perturbs features for alternate DBSCAN/agglomerative stability runs.", sensitivity_risk="critical", recommended_treatment="Scale perturbation to empirical feature uncertainty and sweep multiple magnitudes."),
        item("mv.dominant_group_rejection", scope, "candidate_filter", "coverage_cutoff", 0.85, "fraction of sample", f, "if coverage >= 0.85", "Rejects semantic clusters covering 85% or more of sampled rows.", sensitivity_risk="critical", recommended_treatment="Replace with a dataset-relative triviality test and human usefulness validation."),
        item("mv.explainability_saturation", scope, "utility", "score_transform", "2 highlights -> 1.0", "highlights", f, "explainability = min(1.0, len(highlights) / 2.0)", "Turns the number of generated highlights into the explainability score.", sensitivity_risk="high", recommended_treatment="Rate explanation quality with humans; count alone is not explainability."),
        item("mv.quality_signature_support", scope, "quality_view", "coverage_cutoff", "min support and < 0.85 coverage", "rows/fraction", f, "len(positions) < min_group_size or len(positions) / len(frame) >= 0.85", "Filters exact detector-signature groups that are too small or too dominant.", sensitivity_risk="critical", recommended_treatment="Use detector prevalence uncertainty and multiple-testing control."),
        item("mv.quality_description_cap", scope, "presentation", "result_limit", 4, "signature facts", f, "highlights = list(signature[:4])", "Limits detector facts shown in a quality-group explanation.", "display_limit", sensitivity_risk="low", recommended_treatment="Keep as a UI limit but retain all evidence in expandable details."),
        item("mv.duplicate_min_rows", scope, "duplicate_view", "minimum_support", 2, "rows", f, "if len(values) >= 2", "Requires at least two rows to form a duplicate signature group.", current_basis="Duplicate means at least two records.", evidence_status="structural_safeguard", sensitivity_risk="low", recommended_treatment="Keep."),
        item("mv.duplicate_max_coverage", scope, "duplicate_view", "coverage_cutoff", 0.20, "fraction of sample", f, "if len(positions) / len(frame) >= 0.20", "Suppresses duplicate signatures shared by 20% or more of rows as likely broad categories.", sensitivity_risk="critical", recommended_treatment="Model collision probability from selected fields instead of using a universal 20%."),
        item("mv.duplicate_example_cap", scope, "presentation", "result_limit", 4, "columns", f, ") == 1][:4]", "Shows at most four fields that exactly agree inside a duplicate group.", "display_limit", sensitivity_risk="low", recommended_treatment="Keep for compact UI; expose remaining fields on demand."),
        item("mv.duplicate_numeric_precision", scope, "duplicate_view", "similarity_cutoff", 2, "decimal places", f, ".round(2)", "Rounds robust-normalized numeric values before forming duplicate signatures.", sensitivity_risk="critical", recommended_treatment="Derive tolerance from measurement precision and column scale."),
        item("mv.duplicate_nonmissing_support", scope, "duplicate_view", "minimum_support", "max(2, half selected columns)", "non-missing fields", f, "non_missing >= max(2, len(columns) // 2)", "Rejects a duplicate signature unless enough selected fields are present.", "partially_adaptive", sensitivity_risk="high", recommended_treatment="Use field reliability and match discriminativeness rather than an unweighted half."),
        item("mv.actionability_priors", scope, "utility", "feature_weight", "business=.80; text=.80; lifecycle=.90; geography=.78; quality=1; duplicates=1", "score", f, '"business": 0.80', "Assigns a fixed actionability score by view before observing a particular group.", sensitivity_risk="critical", recommended_treatment="Collect blinded user usefulness ratings or remove this prior from ranking."),
        item("mv.highlight_caps", scope, "presentation", "result_limit", "5 total; 3 in title; 4 tokens; 3 durations", "facts", f, "highlights = unique_strings(feature_highlights)[:5]", "Limits evidence used in group descriptions and detail payloads.", "display_limit", sensitivity_risk="medium", recommended_treatment="Keep display caps separate from ranking features so truncation cannot change utility."),
        item("mv.profile_caveat_cutoff", scope, "explanation", "confidence_cutoff", 0.75, "probability", f, "if profile_confidence < 0.75", "Adds a caveat when average source-column confidence is below 75%.", sensitivity_risk="high", recommended_treatment="Calibrate caveat language against observed error by confidence bin."),
        item("mv.stability_caveat_cutoff", scope, "explanation", "stability_cutoff", 0.65, "matched overlap", f, "if stability < 0.65", "Adds a warning that the group changed under the alternate clustering run.", sensitivity_risk="critical", recommended_treatment="Estimate a confidence interval over repeated seeds instead of one cutoff on two runs."),
        item("mv.lifecycle_month_highlight", scope, "explanation", "share_cutoff", 0.35, "within-group fraction", f, "if share >= 0.35", "Mentions a dominant month only when it covers at least 35% of a lifecycle group.", sensitivity_risk="medium", recommended_treatment="Compare against the dataset baseline month share and report lift/significance."),
        item("mv.coverage_score_transform", scope, "utility", "quality_threshold", "quality/duplicate saturate at 3%; semantic saturates at 8%, ideal through 20%, decays across 65%", "coverage fraction", f, "coverage_score = min(1.0, coverage / 0.03)", "Converts raw group coverage into a utility component with different hand-shaped curves by view.", sensitivity_risk="critical", recommended_treatment="Fit utility from blinded human ratings or report coverage without a learned-looking score."),
        item("mv.utility_weights", scope, "utility", "feature_weight", "stability .25; coherence .20; distinctiveness .15; explainability .15; profiler confidence .10; coverage .05; actionability .10", "weights summing to 1", f, "0.25 * stability", "Combines seven heterogeneous signals into the final utility score and rank order.", sensitivity_risk="critical", recommended_treatment="Run weight ablations and nested cross-dataset tuning; never tune and report on the same datasets."),
        item("mv.semantic_stability_filter", scope, "candidate_filter", "stability_cutoff", 0.45, "matched overlap", f, "group.stability < 0.45", "Rejects non-quality groups below 45% overlap across the two runs.", sensitivity_risk="critical", recommended_treatment="Use bootstrap stability distribution and calibrate an abstention rule."),
        item("mv.duplicate_coherence_filter", scope, "candidate_filter", "similarity_cutoff", 0.98, "mean similarity", f, "group.coherence < 0.98", "Rejects near-duplicate groups below 98% within-group similarity.", sensitivity_risk="critical", recommended_treatment="Validate against planted duplicates with varying corruption levels."),
        item("mv.utility_acceptance_filter", scope, "candidate_filter", "utility_cutoff", 0.52, "utility score", f, "group.utilityScore >= 0.52", "Drops every candidate whose weighted utility is below 0.52.", sensitivity_risk="critical", recommended_treatment="Calibrate precision/coverage against blinded human accept/reject labels."),
        item("mv.overlap_dedupe", scope, "candidate_filter", "overlap_cutoff", 0.92, "Jaccard similarity", f, ">= 0.92", "Suppresses a same-view group when its row set overlaps an accepted group by at least 92% Jaccard.", sensitivity_risk="high", recommended_treatment="Sweep overlap thresholds and measure redundant versus distinct human judgments."),
        item("mv.groups_per_view_cap", scope, "presentation", "result_limit", 3, "groups/view", f, "if counts[group.view] >= 3", "Prevents any view from contributing more than three displayed groups.", sensitivity_risk="high", recommended_treatment="Use diversity-aware ranking with a tunable/validated view-balance penalty."),
        item("mv.mean_confidence_fallback", scope, "utility", "confidence_fallback", 0.5, "probability", f, "return float(np.mean(values)) if values else 0.5", "Supplies medium profile confidence when a group has no mapped source confidences.", sensitivity_risk="high", recommended_treatment="Represent missing evidence explicitly and exclude it from weighted means."),
    ]


def production_multiview_items() -> list[AuditItem]:
    """Current multi-view decisions after the dataset-driven policy refactor."""
    f = "app/server_utils/multi_view_grouping.py"
    p = "app/server_utils/adaptive_grouping_policy.py"
    scope = "production_multiview"
    adaptive_basis = "Derived from the current dataset rather than a universal semantic cutoff."
    return [
        item("mv.sample_seed", scope, "sampling", "reproducibility_seed", 20260717, "seed", f, "MULTI_VIEW_SAMPLE_SEED = 20260717", "Chooses a repeatable random sample without changing the decision rule.", "reproducibility_seed", "Repeatability choice, not a semantic threshold.", "methodological_choice", "low", "Keep fixed in production and use repeated seeds in evaluation."),
        item("mv.sample_resource_cap", scope, "sampling", "resource_budget", 10000, "rows", f, "MAX_ADAPTIVE_SAMPLE_ROWS = 10000", "Bounds interactive memory and latency; datasets below it are read in full.", "resource_budget", "Interactive resource safeguard.", "resource_safeguard", "medium", "Benchmark the cap separately from cluster quality."),
        item("mv.full_below_resource_cap", scope, "sampling", "adaptive_sample_size", "min(total rows, resource cap)", "rows", f, "sample_rows = min(total_rows, MAX_ADAPTIVE_SAMPLE_ROWS)", "Uses all available rows unless the resource cap intervenes.", "dataset_adaptive", adaptive_basis, "implemented_not_human_validated", "medium", "Evaluate progressive sampling later; this version favors group quality over latency."),
        item("mv.default_result_limit", scope, "presentation", "result_limit", 12, "groups", f, "DEFAULT_LIMIT = 12", "Default response length when a caller supplies no display limit.", "display_limit", "UI capacity choice, not cluster membership logic.", "not_user_evaluated", "medium", "Evaluate review burden with users."),
        item("mv.result_limit_cap", scope, "presentation", "result_limit", 30, "groups", f, "min(int(limit or DEFAULT_LIMIT), 30)", "Bounds response size.", "display_limit", "Payload safeguard.", "resource_safeguard", "low", "Keep separate from scientific candidate acceptance."),
        item("mv.max_group_row_ids", scope, "serialization", "payload_limit", 2000, "row IDs", f, "MAX_GROUP_ROW_IDS = 2000", "Bounds row-ID payload size without changing group membership.", "display_limit", "Browser/payload safeguard.", "resource_safeguard", "low", "Keep and report truncation."),
        item("mv.text_token_safety_cap", scope, "representation", "resource_budget", 512, "tokens/cell", f, "TEXT_TOKEN_SAFETY_CAP = 512", "Prevents pathological text cells from dominating memory after a data-derived token budget is selected.", "resource_budget", "Safety ceiling only; the ordinary limit comes from the observed text-length distribution.", "resource_safeguard", "low", "Stress-test long-text files."),
        item("mv.agglomerative_memory_budget", scope, "algorithm_selection", "resource_budget", "256 MiB estimated pairwise matrix", "bytes", f, "AGGLOMERATIVE_MEMORY_BUDGET_BYTES = 256 * 1024 * 1024", "Skips an algorithm comparison when its estimated pairwise matrix exceeds the interactive budget.", "resource_budget", "Explicit memory safeguard, not a claim that another algorithm is semantically better.", "resource_safeguard", "medium", "Benchmark actual peak memory on target hardware."),
        item("mv.confidence_natural_break", scope, "feature_routing", "adaptive_confidence_gate", "maximum between-class variance", "observed profiler score", p, 'return float(threshold), "maximum between-class variance in profiler confidences"', "Separates the stronger observed profiler-confidence class from the weaker class.", "dataset_adaptive", adaptive_basis, "benchmark_free_internal_validation", "high", "Validate semantic retention against held-out human labels."),
        item("mv.group_support_distribution", scope, "candidate_generation", "adaptive_minimum_support", "natural break in repeated value frequencies", "rows", p, 'return group_size, "natural break in repeated value frequencies", len(supports)', "Derives minimum recurrence support from category frequencies in the current sample.", "dataset_adaptive", adaptive_basis, "benchmark_free_internal_validation", "high", "Compare accepted groups against blinded usefulness ratings."),
        item("mv.group_support_floor", scope, "candidate_generation", "structural_floor", 2, "rows", p, "group_size = max(2, min(proposed, sample_ceiling, row_count // 2))", "Prevents a singleton from being called a repeated group.", "structural_constant", "A repeated row pattern requires at least two rows.", "structural_safeguard", "low", "Keep."),
        item("mv.group_support_sample_ceiling", scope, "candidate_generation", "adaptive_support_ceiling", "ceil(sqrt(sample rows))", "rows", p, "sample_ceiling = max(2, int(math.ceil(math.sqrt(row_count))))", "Prevents one common category from suppressing all smaller repeated patterns.", "dataset_adaptive", adaptive_basis, "implemented_not_human_validated", "medium", "Ablate this complexity control on varied frequency distributions."),
        item("mv.robust_scale", scope, "representation", "robust_scaling", "median and IQR", "column scale", f, "scale = values.quantile(0.75) - values.quantile(0.25)", "Makes numeric distance resistant to units and extreme values.", "statistical_method", "Standard robust location/scale construction.", "statistical_standard", "low", "Keep; document the standard-deviation fallback for zero-IQR columns."),
        item("mv.adaptive_clip", scope, "representation", "adaptive_outlier_bound", "observed Tukey upper fence", "robust scale units", f, "clip_bound = agp.adaptive_clip_bound(standardized)", "Winsorizes numeric tails using the observed standardized distribution.", "dataset_adaptive", adaptive_basis, "benchmark_free_internal_validation", "medium", "Stress-test skewed and heavy-tailed measures."),
        item("mv.profile_confidence_weight", scope, "representation", "feature_weight", "raw profiler confidence", "multiplier", f, 'weight = max(np.finfo(float).eps, profile_map[column]["confidence"])', "Lets stronger profile evidence contribute more without a hand-shaped affine weight.", "dataset_adaptive", adaptive_basis, "requires_confidence_calibration", "high", "Calibrate profiler confidence with held-out labels."),
        item("mv.adaptive_text_budget", scope, "representation", "adaptive_feature_budget", "robust upper fence of observed token counts", "tokens/cell", f, "token_limits[column] = agp.adaptive_token_limit(", "Derives each text column's token budget from its own length distribution.", "dataset_adaptive", adaptive_basis, "benchmark_free_internal_validation", "medium", "Measure topic stability with and without truncation."),
        item("mv.duration_candidate_gate", scope, "lifecycle_view", "adaptive_feature_selection", "natural break in duration evidence", "coverage x log variation", f, "score_cutoff = agp.natural_break_threshold(candidate[0] for candidate in duration_candidates)", "Selects useful event-duration pairs without relying on column order or a fixed pair count.", "dataset_adaptive", adaptive_basis, "implemented_not_human_validated", "high", "Evaluate lifecycle explanation usefulness."),
        item("mv.duration_complexity_budget", scope, "lifecycle_view", "adaptive_feature_budget", "ceil(sqrt(sample rows))", "duration pairs", f, "duration_budget = max(1, int(math.ceil(math.sqrt(max(1, len(frame))))))", "Scales the maximum duration feature count with available evidence.", "dataset_adaptive", adaptive_basis, "implemented_not_human_validated", "medium", "Measure runtime and redundancy as table width grows."),
        item("mv.coordinate_pairing", scope, "geography_view", "semantic_pairing", "all name-matched latitude/longitude pairs", "coordinate pairs", f, "coordinate_pairs = match_coordinate_pairs(latitudes, longitudes)", "Supports origin/destination and other multiple-coordinate datasets instead of using the first pair only.", "semantic_rule", "Column-name context links coordinate components.", "implemented_not_human_validated", "medium", "Test ambiguous coordinate names and user overrides."),
        item("mv.k_candidate_range", scope, "algorithm_selection", "adaptive_cluster_count", "2 through min(unique rows, support bound, ceil(log2(unique rows)))", "clusters", p, "complexity_bound = max(2, int(math.ceil(math.log2(max(2, unique_row_count)))))", "Builds a dataset-scaled K candidate set instead of capping K at eight.", "dataset_adaptive", adaptive_basis, "benchmark_free_internal_validation", "high", "Evaluate planted-group recovery and semantic ratings."),
        item("mv.kmeans_seeds", scope, "stability", "reproducibility_seed", "42 primary; 137 alternate", "seeds", f, "unique_labels = sg.kmeans(unique_matrix, k, random_seed=42)", "Produces repeated deterministic partitions for stability measurement.", "reproducibility_seed", "Seeds make the comparison repeatable; candidate scores choose K.", "methodological_choice", "medium", "Use more seeds in offline evaluation."),
        item("mv.partition_diagnostics", scope, "algorithm_selection", "adaptive_candidate_score", "geometric mean of stability, coherence, distinctiveness, balance, assigned fraction", "score", p, "score = float(np.exp(np.log(components).mean()))", "Scores each partition on several observed properties without fixed component weights.", "dataset_adaptive", adaptive_basis, "benchmark_free_internal_validation", "high", "Ablate each diagnostic and compare with human judgments."),
        item("mv.candidate_separation", scope, "algorithm_selection", "adaptive_abstention", "natural top-versus-runner-up score class", "candidate score", p, "separated = bool(threshold is not None and array[0] > threshold >= array[1])", "Uses a candidate only when its score is naturally separated; otherwise prefers simpler K-means.", "dataset_adaptive", adaptive_basis, "benchmark_free_internal_validation", "high", "Measure how often this abstention agrees with held-out quality."),
        item("mv.algorithm_comparison", scope, "algorithm_selection", "adaptive_algorithm", "K-means vs eligible agglomerative vs distance-knee DBSCAN", "candidate algorithms", f, "algorithm_records = [selected_kmeans]", "Compares algorithms on the same diagnostics rather than routing algorithms by data type.", "dataset_adaptive", adaptive_basis, "benchmark_free_internal_validation", "high", "Benchmark candidate quality on planted and human-rated groups."),
        item("mv.dbscan_eps", scope, "algorithm_selection", "adaptive_distance", "k-distance knee", "cosine distance", f, "eps = distance_knee(distances[:, -1])", "Derives DBSCAN radius from the current feature-space density.", "dataset_adaptive", adaptive_basis, "benchmark_free_internal_validation", "high", "Compare knee stability under resampling."),
        item("mv.perturbation_scale", scope, "stability", "adaptive_perturbation", "median nearest-neighbor distance / sqrt(feature count)", "feature units", f, "sigma = local_scale / math.sqrt(max(1, matrix.shape[1]))", "Scales the stability perturbation to local data geometry.", "dataset_adaptive", adaptive_basis, "benchmark_free_internal_validation", "medium", "Repeat over several perturbation draws offline."),
        item("mv.quality_support", scope, "quality_view", "adaptive_minimum_support", "natural break in observed signature sizes", "rows", f, "agp.adaptive_observed_group_support(observed_sizes, len(frame))", "Derives recurring quality-pattern support from observed error signatures.", "dataset_adaptive", adaptive_basis, "benchmark_free_internal_validation", "high", "Evaluate planted error-pattern recovery."),
        item("mv.duplicate_numeric_bins", scope, "duplicate_view", "adaptive_tolerance", "Freedman-Diaconis width", "robust standardized units", f, "bin_width = (2.0 * standardized_iqr) / np.cbrt(len(valid))", "Derives numeric duplicate tolerance from scale and sample size.", "statistical_method", "Standard histogram-width rule used as a data-driven tolerance.", "statistical_standard", "medium", "Test against planted near-duplicates with known corruption."),
        item("mv.duplicate_nonmissing_support", scope, "duplicate_view", "adaptive_minimum_support", "natural break in observed non-missing counts", "fields", f, "support_cutoff = agp.natural_break_threshold(non_missing_counts)", "Rejects sparse signatures using the current row-completeness distribution.", "dataset_adaptive", adaptive_basis, "benchmark_free_internal_validation", "high", "Test missingness mechanisms and entity-resolution precision."),
        item("mv.coverage_outlier_filter", scope, "candidate_filter", "adaptive_coverage", "Tukey upper fence within observed candidate coverages", "sample fraction", f, "coverage_fence = agp.robust_upper_fence(group.coverage for group in view_groups)", "Suppresses unusually dominant groups relative to candidates in the same view.", "dataset_adaptive", adaptive_basis, "benchmark_free_internal_validation", "high", "Validate that large but meaningful groups are not suppressed."),
        item("mv.full_coverage_rejection", scope, "candidate_filter", "structural_cutoff", 1.0, "sample fraction", f, "if group.coverage >= 1.0", "Rejects a one-group partition because it does not segment the dataset.", "structural_constant", "A group covering every row is not a partition of the data.", "structural_safeguard", "low", "Keep."),
        item("mv.explainability_scaling", scope, "utility", "adaptive_normalization", "highlight count / sqrt(columns used)", "score", f, "len(highlights) / max(1.0, math.sqrt(len(columns)))", "Scales available explanation evidence to dataset/view width rather than saturating after two facts.", "dataset_adaptive", adaptive_basis, "implemented_not_human_validated", "medium", "Replace or calibrate with explanation ratings when available."),
        item("mv.utility_calibration", scope, "utility", "adaptive_rank", "median empirical percentile within view", "rank score", f, "score = float(np.median([values[index] for values in percentiles.values()]))", "Combines stability, coherence, distinctiveness, explainability, profile confidence, and nontrivial coverage without fixed weights.", "dataset_adaptive", adaptive_basis, "benchmark_free_internal_validation", "high", "Compare rank correlation with blinded human usefulness."),
        item("mv.acceptance_policy", scope, "candidate_filter", "adaptive_acceptance", "natural breaks and robust fences per view", "candidate metrics", f, '"source": "natural breaks and robust fences within each semantic view"', "Accepts the stronger observed candidate class separately in each semantic view.", "dataset_adaptive", adaptive_basis, "benchmark_free_internal_validation", "high", "Measure precision/coverage against human accept/reject labels."),
        item("mv.overlap_dedupe", scope, "candidate_filter", "adaptive_overlap", "natural break in observed same-view Jaccards", "Jaccard similarity", f, "overlap_cutoff = agp.natural_break_threshold(overlaps)", "Suppresses redundant explanations using the current overlap distribution.", "dataset_adaptive", adaptive_basis, "benchmark_free_internal_validation", "medium", "Evaluate redundant-versus-distinct human judgments."),
        item("mv.view_diversity", scope, "presentation", "adaptive_rank", "similarity-clusters-first, then semantic-percentile ranking across the merged group list", "groups", f, "view_tier(groups[index]),", "One merged list: semantic-quality (similarity) clusters rank above near-duplicate (exact-match) groups, then by semantic-meaningfulness percentile, with cluster geometry breaking ties.", "dataset_adaptive", "Percentile-normalizes semantic evidence across the current groups; the only fixed rule is the similarity-over-equality tier, a structural provenance ordering, not a numeric weight.", "implemented_not_user_evaluated", "medium", "Test review efficiency and semantic ordering with users."),
        item("mv.no_human_labels_runtime", scope, "methodology", "label_dependency", False, "human labels", f, '"humanLabelsUsed": False', "Records that production adaptation uses only current-dataset evidence.", "methodological_metadata", "Internal adaptation does not consume benchmark labels.", "explicitly_recorded", "low", "Use labels only for external evaluation, never to leak into held-out decisions."),
    ]


def pre_adaptive_api_ui_items() -> list[AuditItem]:
    """Historical configuration-drift snapshot retained for comparison."""
    scope = "api_ui_configuration"
    return [
        item("api.default_limit", scope, "Flask route", "result_limit", 8, "groups", "app/routes/plot_routes.py", 'request.args.get("limit", 8)', "Route fallback when a client omits the result limit.", "configuration_default", current_basis="Legacy route default; disagrees with module default 12 and modal request 18.", evidence_status="configuration_drift", sensitivity_risk="high", recommended_treatment="Define one typed configuration object and return effective settings in metadata."),
        item("api.default_sample_rows", scope, "Flask route", "sample_size", 5000, "rows", "app/routes/plot_routes.py", 'request.args.get("sample_rows", 5000)', "Route fallback sample size.", "configuration_default", current_basis="Legacy route default; disagrees with module/UI production value 3,000.", evidence_status="configuration_drift", sensitivity_risk="critical", recommended_treatment="Centralize and test the value actually used by every entry point."),
        item("api.default_min_group", scope, "Flask route", "minimum_support", 12, "rows", "app/routes/plot_routes.py", 'request.args.get("min_group_size", 12)', "Route fallback minimum group size.", "configuration_default", current_basis="Compatibility default; differs from production module/UI value 8.", evidence_status="configuration_drift", sensitivity_risk="critical", recommended_treatment="Centralize; log the effective value per run."),
        item("api.default_min_error", scope, "Flask route", "minimum_support", 2, "error rows", "app/routes/plot_routes.py", 'request.args.get("min_error_rows", 2)', "Legacy error-conditioned grouping minimum; the multi-view semantic path does not use it directly.", "configuration_default", current_basis="Retained for compatibility strategy.", evidence_status="legacy_only", sensitivity_risk="medium", recommended_treatment="Separate legacy and multi-view request schemas."),
        item("client.default_limit", scope, "generic JS client", "result_limit", 8, "groups", "ui/src/utils/serverCalls.jsx", "limit: options.limit ?? 8", "Client-side default when no panel supplies an override.", "configuration_default", current_basis="Duplicates route default.", evidence_status="configuration_drift", sensitivity_risk="medium", recommended_treatment="Remove duplicate defaults from the generic client."),
        item("client.default_sample_rows", scope, "generic JS client", "sample_size", 5000, "rows", "ui/src/utils/serverCalls.jsx", "sample_rows: options.sampleRows ?? 5000", "Client-side fallback sample request.", "configuration_default", current_basis="Differs from the active modal request and module default.", evidence_status="configuration_drift", sensitivity_risk="critical", recommended_treatment="Remove duplicate defaults from the generic client."),
        item("ui.modal_limit", scope, "semantic groups modal", "result_limit", 18, "groups", "ui/src/panels/SemanticGroupsModal.jsx", "limit: 18", "Actual limit requested by the current UI modal.", "configuration_default", current_basis="UI composition choice; overrides backend defaults.", evidence_status="not_user_evaluated", sensitivity_risk="medium", recommended_treatment="Test review burden and pagination with users."),
        item("ui.modal_sample_rows", scope, "semantic groups modal", "sample_size", 3000, "rows", "ui/src/panels/SemanticGroupsModal.jsx", "sampleRows: 3000", "Actual sample size requested by the current UI modal.", "configuration_default", current_basis="Matches module default but has no current multi-view accuracy/runtime calibration.", sensitivity_risk="critical", recommended_treatment="Run the new benchmark at multiple sample sizes and seeds."),
        item("ui.modal_min_group", scope, "semantic groups modal", "minimum_support", 8, "rows", "ui/src/panels/SemanticGroupsModal.jsx", "minGroupSize: 8", "Actual minimum group support requested by the current UI modal.", "configuration_default", current_basis="Matches module default; overrides route default 12.", sensitivity_risk="critical", recommended_treatment="Replace with an adaptive support policy and expose effective support."),
    ]


def api_ui_items() -> list[AuditItem]:
    """Current request configuration after removing UI semantic overrides."""
    scope = "api_ui_configuration"
    return [
        item("api.default_limit", scope, "Flask route", "result_limit", 8, "groups", "app/routes/plot_routes.py", 'request.args.get("limit", 8)', "Route display fallback when a client omits a result limit.", "configuration_default", current_basis="Display choice only.", evidence_status="not_user_evaluated", sensitivity_risk="medium", recommended_treatment="Centralize with UI pagination."),
        item("api.optional_sample_rows", scope, "Flask route", "adaptive_override", "none unless caller supplies it", "rows", "app/routes/plot_routes.py", 'sample_rows_arg = request.args.get("sample_rows")', "Leaves multi-view sampling adaptive by default while preserving explicit experiment controls.", "dataset_adaptive", current_basis="No multi-view sample-size default is injected by the route.", evidence_status="implemented", sensitivity_risk="low", recommended_treatment="Keep explicit overrides for controlled experiments."),
        item("api.optional_min_group", scope, "Flask route", "adaptive_override", "none unless caller supplies it", "rows", "app/routes/plot_routes.py", 'min_group_size_arg = request.args.get("min_group_size")', "Leaves support adaptive by default while preserving explicit experiment controls.", "dataset_adaptive", current_basis="No multi-view group-size default is injected by the route.", evidence_status="implemented", sensitivity_risk="low", recommended_treatment="Keep explicit overrides for sensitivity studies."),
        item("api.legacy_sample_rows", scope, "Flask compatibility route", "sample_size", 5000, "rows", "app/routes/plot_routes.py", "legacy_sample_rows = sample_rows if sample_rows is not None else 5000", "Applies only to the earlier compatibility grouping strategies.", "legacy_only", current_basis="Not used by profiler-guided multi-view clustering.", evidence_status="legacy_only", sensitivity_risk="medium", recommended_treatment="Retain only while the baseline remains callable."),
        item("api.legacy_min_group", scope, "Flask compatibility route", "minimum_support", 12, "rows", "app/routes/plot_routes.py", "legacy_min_group_size = min_group_size if min_group_size is not None else 12", "Applies only to the earlier compatibility grouping strategies.", "legacy_only", current_basis="Not used by profiler-guided multi-view clustering.", evidence_status="legacy_only", sensitivity_risk="medium", recommended_treatment="Retain only while the baseline remains callable."),
        item("api.default_min_error", scope, "Flask compatibility route", "minimum_support", 2, "error rows", "app/routes/plot_routes.py", 'request.args.get("min_error_rows", 2)', "Applies only to legacy error-conditioned grouping.", "legacy_only", current_basis="The multi-view semantic path does not condition candidate eligibility on errors.", evidence_status="legacy_only", sensitivity_risk="low", recommended_treatment="Separate the legacy request schema."),
        item("client.default_limit", scope, "generic JS client", "result_limit", 8, "groups", "ui/src/utils/serverCalls.jsx", "limit: options.limit ?? 8", "Client display fallback.", "configuration_default", current_basis="Display choice only.", evidence_status="not_user_evaluated", sensitivity_risk="medium", recommended_treatment="Centralize with pagination."),
        item("client.optional_sample_rows", scope, "generic JS client", "adaptive_override", "omitted by default", "rows", "ui/src/utils/serverCalls.jsx", 'if (options.sampleRows) params.set("sample_rows", options.sampleRows);', "Does not override adaptive sampling unless an experiment or caller asks it to.", "dataset_adaptive", current_basis="Active UI sends no fixed sample size.", evidence_status="implemented", sensitivity_risk="low", recommended_treatment="Keep."),
        item("client.optional_min_group", scope, "generic JS client", "adaptive_override", "omitted by default", "rows", "ui/src/utils/serverCalls.jsx", 'if (options.minGroupSize) params.set("min_group_size", options.minGroupSize);', "Does not override adaptive group support unless a controlled run asks it to.", "dataset_adaptive", current_basis="Active UI sends no fixed minimum support.", evidence_status="implemented", sensitivity_risk="low", recommended_treatment="Keep."),
        item("ui.modal_limit", scope, "semantic groups modal", "result_limit", 18, "groups", "ui/src/panels/SemanticGroupsModal.jsx", "limit: 18", "Maximum groups requested for the review interface.", "display_limit", current_basis="UI composition choice; does not alter candidate creation or acceptance.", evidence_status="not_user_evaluated", sensitivity_risk="medium", recommended_treatment="Test review burden and add pagination if needed."),
    ]


def profiler_dependency_items() -> list[AuditItem]:
    integration = "app/server_utils/data_attribute_summary_integration.py"
    classifier = "profiling/column_profiling.py"
    scope = "upstream_profiler"
    return [
        item("profile.full_sample_cap", scope, "profile integration", "sample_size", 10000, "rows", integration, "PROFILE_SAMPLE_ROWS = 10000", "Maximum random rows used for the column profile that routes columns into clustering views.", sensitivity_risk="critical", recommended_treatment="Evaluate profiling-to-clustering error propagation by profile sample size."),
        item("profile.review_rows", scope, "profile integration", "sample_size", 500, "rows", integration, "PROFILE_REVIEW_COMPARISON_ROWS = 500", "Minimum comparison stage used when deciding whether progressive profiling may stop.", sensitivity_risk="high", recommended_treatment="Calibrate early stopping on held-out datasets."),
        item("profile.sample_seed", scope, "profile integration", "reproducibility_seed", 20260714, "seed", integration, "PROFILE_SAMPLE_SEED = 20260714", "Selects deterministic random rows for profiling.", "reproducibility_seed", current_basis="Repeatability choice.", evidence_status="methodological_choice", sensitivity_risk="low", recommended_treatment="Keep in production; use multiple seeds in evaluation."),
        item("profile.progressive_steps", scope, "profile integration", "sample_size", "500, 1000, 5000, 10000", "rows", integration, "PROFILE_PROGRESSIVE_STEPS = (500, 1000, 5000, 10000)", "Only sample sizes considered by adaptive profiling before clustering consumes the result.", sensitivity_risk="critical", recommended_treatment="Choose the next sample from estimated uncertainty reduction and cost, not a fixed ladder."),
        item("profile.stop_avg_confidence", scope, "profile integration", "confidence_cutoff", 0.86, "mean probability", integration, "PROFILE_BALANCED_MIN_AVG_CONFIDENCE = 0.86", "Requires average column confidence of at least 86% before balanced early stopping.", sensitivity_risk="critical", recommended_treatment="Calibrate confidence first, then choose a selective-risk target."),
        item("profile.stop_min_confidence", scope, "profile integration", "confidence_cutoff", 0.80, "minimum probability", integration, "PROFILE_BALANCED_MIN_COLUMN_CONFIDENCE = 0.80", "Requires every column to reach at least 80% confidence before balanced stopping.", sensitivity_risk="critical", recommended_treatment="Calibrate per-role risk and allow abstention for unresolved columns."),
        item("profile.stop_uncertain_columns", scope, "profile integration", "count_cutoff", 2, "columns", integration, "PROFILE_BALANCED_MAX_UNCERTAIN_COLUMNS = 2", "Allows at most two uncertain columns at early stop regardless of dataset width.", sensitivity_risk="critical", recommended_treatment="Use a fraction of eligible columns plus risk-weighted exceptions."),
        item("profile.geography_high_confidence", scope, "profile integration", "confidence_cutoff", 0.80, "probability", integration, "confidence_score >= 0.80", "Determines when a geography role is considered high-confidence in the UI/review evidence.", sensitivity_risk="high", recommended_treatment="Calibrate geography separately and distinguish role family from subtype."),
        item("profile.candidate_gap_review", scope, "profile integration", "confidence_gap", 0.08, "probability points", integration, 'formatted["candidateConfidenceGap"] < 0.08', "Marks closely competing role candidates as needing review.", sensitivity_risk="critical", recommended_treatment="Use empirical error by top-two margin on held-out datasets."),
        item("profile.geography_candidate_cutoff", scope, "profile integration", "confidence_cutoff", 0.80, "probability", integration, ") >= 0.80", "Requires a geography candidate to reach 80% in additional review logic.", sensitivity_risk="high", recommended_treatment="Unify duplicate 80% checks in one calibrated policy.", occurrence=1),
        item("profile.sample_margin_review", scope, "profile integration", "uncertainty_cutoff", 0.10, "confidence interval half-width", integration, "sample_margin >= 0.10", "Explains that profiling uncertainty remains material when the interval margin is at least 10 points.", sensitivity_risk="high", recommended_treatment="Tie wording and sampling action to a user-selected risk tolerance."),
        item("classifier.default_rows", scope, "column classifier", "sample_size", 5000, "rows", classifier, "DEFAULT_PROFILE_ROWS = 5000", "CLI/default sample size for the classifier implementation used by profile integration.", sensitivity_risk="high", recommended_treatment="Centralize with integration sample policy."),
        item("classifier.detector_rows", scope, "column classifier", "sample_size", 2000, "rows", classifier, "DEFAULT_DETECTOR_ROWS = 2000", "Default detector-oriented sample size exposed by the profiler experiment CLI.", sensitivity_risk="high", recommended_treatment="Record and calibrate detector sampling separately from semantic role sampling."),
        item("classifier.chunk_rows", scope, "column classifier", "sample_size", 50000, "rows/chunk", classifier, "DEFAULT_CARDINALITY_CHUNK_ROWS = 50_000", "Chunk size used for scalable CSV processing.", "resource_budget", current_basis="Memory/performance engineering value rather than a semantic threshold.", evidence_status="resource_safeguard", sensitivity_risk="low", recommended_treatment="Benchmark memory and throughput; it should not alter predictions."),
        item("classifier.interval_z", scope, "column classifier", "confidence_interval", 1.96, "z score", classifier, "CONFIDENCE_INTERVAL_Z = 1.96", "Builds nominal 95% Wilson confidence intervals used in role evidence and sampling decisions.", "statistical_constant", current_basis="Standard normal approximation for a two-sided 95% interval.", evidence_status="statistical_standard", sensitivity_risk="low", recommended_treatment="Keep, but state assumptions and consider simultaneous/multiple-column coverage."),
        item("classifier.role_thresholds", scope, "column classifier", "type_cutoff", "numeric .85; measurement .75; date .70; identifier .90; datetime-key .75; ID-reference .10 and >=1000 unique", "ratios/count", classifier, '"numeric_parse_threshold": 0.85', "Core role cutoffs that determine the profiler labels inherited by clustering feature routing.", sensitivity_risk="critical", recommended_treatment="Estimate role-specific operating points from the reviewed benchmark with nested validation."),
        item("classifier.confidence_weights", scope, "column classifier", "feature_weight", "evidence .50; reliability .40; name hint .10", "weights", classifier, "score = (0.50 * evidence) + (0.40 * reliability) + (0.10 * name_hint_score)", "Combines evidence, sample reliability, and column-name hints into displayed role confidence.", sensitivity_risk="critical", recommended_treatment="Calibrate confidence and ablate name hints on unseen datasets."),
        item("classifier.stop_confidence", scope, "column classifier", "confidence_cutoff", 0.80, "probability", classifier, "if confidence_score < 0.80", "Requests more data when the chosen role is below 80% confidence.", sensitivity_risk="critical", recommended_treatment="Use calibrated selective-risk targets."),
        item("classifier.stop_candidate_gap", scope, "column classifier", "confidence_gap", 0.15, "probability points", classifier, "if gap < 0.15", "Requests more data when the top two role candidates are separated by less than 15 points.", sensitivity_risk="critical", recommended_treatment="Calibrate role-specific margins against prediction changes."),
        item("classifier.stop_interval_margin", scope, "column classifier", "uncertainty_cutoff", "margin >= .10 while total rows < 50,000", "probability/rows", classifier, "sample_uncertainty_margin >= 0.10 and total_rows < 50_000", "Requests more rows for wide intervals but stops requesting once the dataset reaches 50,000 rows.", sensitivity_risk="critical", recommended_treatment="Use remaining rows and compute budget explicitly rather than a universal dataset-size ceiling."),
        item("classifier.date_parse_cap", scope, "column classifier", "sample_size", 100, "values", classifier, "values_as_text.head(100)", "Limits values inspected by one date-parsing helper.", sensitivity_risk="high", recommended_treatment="Use stratified/reservoir values and quantify parse-rate error."),
        item("classifier.numeric_code_rule", scope, "column classifier", "category_cutoff", "<=20 unique and <=5% cardinality", "count/fraction", classifier, "decision_unique_count <= 20", "Treats small-domain numeric columns as category/code-like instead of measurements.", sensitivity_risk="critical", recommended_treatment="Learn the boundary by semantic role and dataset size; counts and ratios should interact adaptively."),
    ]


def detector_dependency_items() -> list[AuditItem]:
    common = "detectors/common.py"
    anomaly = "detectors/anomaly.py"
    mismatch = "detectors/datatype_mismatch.py"
    incomplete = "detectors/incomplete.py"
    scope = "upstream_quality_detectors"
    return [
        item("detector.iqr_multiplier", scope, "anomaly detector", "outlier_cutoff", 1.5, "IQR", common, '"iqr_multiplier": 1.5', "Defines Tukey lower/upper fences that generate anomaly records used by the quality view.", current_basis="Conventional Tukey exploratory rule, not universally optimal for every distribution.", evidence_status="statistical_convention", sensitivity_risk="high", recommended_treatment="Keep as a baseline and compare robust distribution-aware alternatives."),
        item("detector.mad_multiplier", scope, "anomaly detector", "outlier_cutoff", 3.5, "modified-z units", common, '"mad_multiplier": 3.5', "Threshold for MAD-based anomaly detection.", current_basis="Common robust outlier convention.", evidence_status="statistical_convention", sensitivity_risk="high", recommended_treatment="Validate precision/recall with planted anomalies."),
        item("detector.zscore", scope, "anomaly detector", "outlier_cutoff", 3.0, "standard deviations", common, '"zscore_threshold": 3.0', "Threshold for backward-compatible z-score anomaly checks.", current_basis="Three-sigma convention assumes a distributional shape.", evidence_status="statistical_convention", sensitivity_risk="high", recommended_treatment="Do not apply blindly to skewed/non-normal columns; retain only as a tested baseline."),
        item("detector.log_skew", scope, "anomaly detector", "shape_cutoff", 2.0, "absolute skew", common, '"log_skew_threshold": 2.0', "Chooses log-aware anomaly handling for strongly skewed nonnegative numeric columns.", sensitivity_risk="critical", recommended_treatment="Select transform using held-out likelihood/robustness rather than skew alone."),
        item("detector.type_confidence", scope, "type mismatch detector", "confidence_cutoff", 0.90, "dominant type fraction", common, '"type_confidence_threshold": 0.9', "Requires 90% agreement before declaring an expected physical type and flagging mismatches.", sensitivity_risk="critical", recommended_treatment="Calibrate by column width/sample size and cost of false warnings."),
        item("detector.rare_min_count", scope, "incomplete/rare detector", "frequency_cutoff", 3, "occurrences", common, '"rare_value_min_count": 3', "Values occurring at most this count are candidates for rare/incomplete warnings.", sensitivity_risk="critical", recommended_treatment="Estimate expected frequency under the column distribution and control false discoveries."),
        item("detector.rare_max_unique", scope, "incomplete/rare detector", "cardinality_cutoff", 80, "unique values", common, '"rare_value_max_unique": 80', "Disables rare-category checks for columns with more than 80 unique values.", sensitivity_risk="critical", recommended_treatment="Use sample-size-aware cardinality confidence and semantic role."),
        item("detector.rare_max_ratio", scope, "incomplete/rare detector", "cardinality_cutoff", 0.50, "unique/rows", common, '"rare_value_max_cardinality_ratio": 0.5', "Disables rare-category checks above 50% cardinality.", sensitivity_risk="critical", recommended_treatment="Calibrate separately for nominal categories, codes, and free text."),
        item("detector.rare_min_rows", scope, "incomplete/rare detector", "minimum_support", 20, "rows", common, '"rare_value_min_rows": 20', "Suppresses rare-value warnings on datasets smaller than 20 rows.", sensitivity_risk="high", recommended_treatment="Use confidence bounds instead of one row-count bucket."),
        item("detector.small_dataset_boundary", scope, "adaptive detector config", "sample_size_cutoff", 50, "rows", common, "if row_count < 50", "Disables rare-value warnings for datasets below 50 rows.", "partially_adaptive", sensitivity_risk="critical", recommended_treatment="Replace with exact/binomial uncertainty for observed category counts."),
        item("detector.large_dataset_boundary", scope, "adaptive detector config", "sample_size_cutoff", 1000, "rows", common, "elif row_count >= 1000", "Begins increasing the allowed rare-value count for large datasets.", "partially_adaptive", sensitivity_risk="critical", recommended_treatment="Use a continuous prevalence/confidence rule without a discontinuity at 1,000."),
        item("detector.rare_count_scaling", scope, "adaptive detector config", "frequency_cutoff", "0.2% of rows, clipped 3..10", "occurrences", common, "row_count * 0.002", "Scales the rare-count threshold for datasets at or above 1,000 rows.", "partially_adaptive", sensitivity_risk="critical", recommended_treatment="Calibrate prevalence and false-discovery targets by role."),
        item("detector.high_cardinality_trigger", scope, "adaptive detector config", "fraction_cutoff", 0.50, "fraction of text columns", common, 'profile["high_cardinality_text_fraction"] >= 0.5', "Tightens rare-value eligibility when at least half of text columns are high-cardinality.", "partially_adaptive", sensitivity_risk="high", recommended_treatment="Use per-column decisions; unrelated columns should not change one another's thresholds."),
        item("detector.high_cardinality_tightening", scope, "adaptive detector config", "cardinality_cutoff", "50 unique and 35% ratio", "count/fraction", common, 'result["rare_value_max_unique"] = min', "Tightened limits used after the dataset-level high-cardinality trigger fires.", "partially_adaptive", sensitivity_risk="critical", recommended_treatment="Calibrate per semantic role and sample size."),
        item("detector.skew_fraction_trigger", scope, "adaptive detector config", "fraction_cutoff", 0.50, "fraction numeric columns", common, 'profile["skewed_numeric_fraction"] >= 0.5', "Lowers the skew threshold when at least half of numeric columns appear skewed.", "partially_adaptive", sensitivity_risk="high", recommended_treatment="Select transformation per column, not from a dataset-wide majority."),
        item("detector.adaptive_log_skew", scope, "adaptive detector config", "shape_cutoff", 1.5, "absolute skew", common, 'result["log_skew_threshold"] = min', "Tightened skew cutoff used in globally skewed datasets.", "partially_adaptive", sensitivity_risk="critical", recommended_treatment="Evaluate transform choice per column."),
        item("detector.weak_type_trigger", scope, "adaptive detector config", "fraction_cutoff", 0.35, "fraction typed columns", common, 'profile["weak_type_fraction"] >= 0.35', "Raises the type-confidence requirement when at least 35% of typed columns are weak.", "partially_adaptive", sensitivity_risk="high", recommended_treatment="Use per-column confidence intervals."),
        item("detector.adaptive_type_confidence", scope, "adaptive detector config", "confidence_cutoff", 0.95, "dominant type fraction", common, 'result["type_confidence_threshold"] = max', "Tightened physical-type confidence after the weak-type trigger.", "partially_adaptive", sensitivity_risk="critical", recommended_treatment="Calibrate expected warning precision."),
        item("detector.profile_numeric_rule", scope, "adaptive detector config", "type_cutoff", "parse >=80% and >=10 values", "ratio/count", common, "numeric_ratio >= 0.8 and numeric.notna().sum() >= 10", "Decides which columns count as numeric while adapting detector settings.", sensitivity_risk="high", recommended_treatment="Reuse profiler roles and their uncertainty."),
        item("detector.skew_min_unique", scope, "adaptive detector config", "minimum_support", 10, "unique numeric values", common, "numeric_values.nunique(dropna=True) >= 10", "Requires ten distinct numeric values before estimating skew for adaptive settings.", sensitivity_risk="medium", recommended_treatment="Use estimator uncertainty/effective sample size."),
        item("detector.weak_type_floor", scope, "adaptive detector config", "confidence_cutoff", 0.50, "dominant type fraction", common, "if 0.5 <= dominant_type_confidence", "Counts a column as weakly typed only when dominant type confidence is at least 50% but below the active threshold.", sensitivity_risk="medium", recommended_treatment="Define mixed-type uncertainty continuously."),
        item("detector.ignore_first_column", scope, "all quality detectors", "column_exclusion", "columns[1:]", "column position", anomaly, "for column in data_frame.columns[1:]", "Never runs anomaly/type/rare checks on the first dataframe column, assuming it is an ID.", sensitivity_risk="critical", recommended_treatment="Exclude by profiler role or explicit row-ID metadata, not physical position."),
        item("detector.anomaly_min_numeric", scope, "anomaly detector", "minimum_support", 10, "parsed values", anomaly, "if numeric_count < 10", "Skips anomaly detection when fewer than ten numeric values are available.", sensitivity_risk="high", recommended_treatment="Use method-specific uncertainty and report not-enough-evidence state."),
        item("detector.log_min_unique", scope, "anomaly detector", "minimum_support", 10, "unique values", anomaly, "values.nunique(dropna=True) < 10", "Prevents log-aware skew handling on low-cardinality numeric columns.", sensitivity_risk="medium", recommended_treatment="Keep as safeguard until evaluated; distinguish codes from measures via profiler."),
        item("detector.mismatch_display_confidence", scope, "type mismatch detector", "confidence_cutoff", 0.95, "dominant type fraction", mismatch, 'confidence="high" if confidence >= 0.95 else "medium"', "Labels a mismatch warning high confidence at 95% or above.", sensitivity_risk="medium", recommended_treatment="Calibrate label language against observed precision."),
        item("detector.incomplete_numeric_exclusion", scope, "incomplete/rare detector", "type_cutoff", 0.80, "numeric parse ratio", incomplete, "if numeric_ratio >= 0.8", "Excludes columns that parse at least 80% numeric from rare-category detection.", sensitivity_risk="high", recommended_treatment="Use profiler role and mixed-type confidence."),
        item("detector.incomplete_min_variation", scope, "incomplete/rare detector", "cardinality_cutoff", 1, "unique value", incomplete, "if unique_count <= 1", "Skips rare-category detection for constant/empty columns.", current_basis="Rare categories are undefined without at least two categories.", evidence_status="structural_safeguard", sensitivity_risk="low", recommended_treatment="Keep."),
    ]


def legacy_baseline_items() -> list[AuditItem]:
    f = "app/server_utils/semantic_grouping.py"
    scope = "compatibility_baseline"
    return [
        item("legacy.default_limit", scope, "legacy grouping", "result_limit", 8, "groups", f, "DEFAULT_LIMIT = 8", "Default legacy groups returned.", "configuration_default", evidence_status="legacy_only", sensitivity_risk="medium"),
        item("legacy.default_min_group", scope, "legacy grouping", "minimum_support", 12, "rows", f, "DEFAULT_MIN_GROUP_SIZE = 12", "Minimum support for compatibility groups.", evidence_status="legacy_only", sensitivity_risk="high"),
        item("legacy.default_min_error", scope, "legacy grouping", "minimum_support", 2, "error rows", f, "DEFAULT_MIN_ERROR_ROWS = 2", "Minimum detector-error rows required by error-conditioned group ranking.", evidence_status="legacy_only", sensitivity_risk="high"),
        item("legacy.default_sample", scope, "legacy grouping", "sample_size", 5000, "prefix rows", f, "DEFAULT_SAMPLE_ROWS = 5000", "Number of first rows read by the legacy SQL path.", evidence_status="legacy_only_biased_sample", sensitivity_risk="critical", recommended_treatment="Use deterministic random sampling; retain prefix result only as historical baseline."),
        item("legacy.text_features", scope, "legacy representation", "feature_cap", 350, "TF-IDF terms", f, "MAX_TEXT_FEATURES = 350", "Maximum pooled text vocabulary dimensions.", evidence_status="legacy_parameter_swept", sensitivity_risk="high", recommended_treatment="Historical sweeps tested this pipeline only; rerun on multi-view representation."),
        item("legacy.row_id_cap", scope, "legacy serialization", "payload_limit", 2000, "row IDs", f, "MAX_ROW_IDS_RETURNED = 2000", "Maximum rows sent for a legacy group.", "display_limit", evidence_status="resource_safeguard", sensitivity_risk="low"),
        item("legacy.fallback_numeric", scope, "legacy representation", "type_cutoff", "parse >=.90 and distinct >3", "ratio/count", f, "if numeric_ratio >= 0.9 and distinct_count > 3", "Infers numeric columns without profiler semantics.", evidence_status="legacy_only", sensitivity_risk="high"),
        item("legacy.exact_slice_caps", scope, "legacy exact slices", "feature_cap", "first 6 columns; category <=80; first 4 numeric; 4 bins", "columns/categories/bins", f, "candidate_columns[:6]", "Bounds combinatorial exact-slice search.", evidence_status="legacy_only", sensitivity_risk="critical", recommended_treatment="Report as a computational budget and evaluate missed slices."),
        item("legacy.error_score", scope, "legacy ranking", "feature_weight", "lift * log1p(error rows) * (0.5 + error coverage)", "score", f, "lift * math.log1p(error_rows) * (0.5 + error_coverage)", "Ranks groups by detector-error concentration and support.", evidence_status="legacy_only", sensitivity_risk="critical", recommended_treatment="Do not use as semantic quality ground truth; validate error discovery separately."),
        item("legacy.numeric_description", scope, "legacy explanation", "effect_cutoff", 0.45, "robust difference", f, "if abs(diff) < 0.45", "Mentions numeric differences only above a fixed robust effect size.", evidence_status="legacy_only", sensitivity_risk="medium"),
        item("legacy.text_description", scope, "legacy explanation", "share_lift_cutoff", "share >=.35 and (lift >=1.2 or share >=.75)", "fraction/lift", f, "share < 0.35", "Selects category phrases used to describe a legacy cluster.", evidence_status="legacy_only", sensitivity_risk="high"),
        item("legacy.numeric_weight", scope, "legacy representation", "feature_weight", 0.75, "multiplier", f, "numeric_matrix * 0.75", "Weights the numeric block relative to pooled TF-IDF.", evidence_status="legacy_parameter_swept", sensitivity_risk="critical", recommended_treatment="Historical sweep is not evidence for the current per-view features."),
        item("legacy.numeric_clip", scope, "legacy representation", "outlier_cutoff", "[-4,4] / 4", "robust units", f, ".clip(-4, 4) / 4", "Clips robust numeric features before distance calculation.", evidence_status="legacy_only", sensitivity_risk="high"),
        item("legacy.token_budget", scope, "legacy representation", "feature_cap", 30, "tokens/cell", f, "tokens.extend(tokenize(value)[:30])", "Limits pooled text contribution per cell.", evidence_status="legacy_only", sensitivity_risk="high"),
        item("legacy.tfidf_df_filters", scope, "legacy representation", "frequency_cutoff", "min document frequency 2; max 90%", "documents/fraction", f, "2 <= frequency <= max(2, int(doc_count * 0.9))", "Drops extremely rare/common pooled terms.", evidence_status="legacy_parameter_swept", sensitivity_risk="critical"),
        item("legacy.kmeans_iterations", scope, "legacy algorithm", "iteration_limit", 40, "iterations", f, "max_iter: int = 40", "Maximum iterations in the local deterministic K-means implementation.", evidence_status="legacy_only", sensitivity_risk="medium"),
        item("legacy.default_k", scope, "legacy algorithm", "cluster_count", "max 8; approximately sqrt(n)/2", "clusters", f, "return max(1, min(8, by_size, by_shape))", "Chooses legacy K without optimizing validity.", "partially_adaptive", evidence_status="legacy_parameter_swept", sensitivity_risk="critical"),
        item("legacy.group_dedupe", scope, "legacy candidate filter", "overlap_cutoff", 0.95, "Jaccard similarity", f, "intersection / union >= 0.95", "Removes near-identical legacy groups.", evidence_status="legacy_only", sensitivity_risk="high"),
    ]


def experiment_protocol_items() -> list[AuditItem]:
    benchmark = "experiments/semantic_clustering_benchmark.py"
    sweep = "experiments/semantic_parameter_sweeps.py"
    selector = "experiments/adaptive_semantic_selector.py"
    scope = "historical_experiment_protocol"
    return [
        item("exp.benchmark_rows", scope, "algorithm benchmark", "sample_size", 5000, "rows", benchmark, "DEFAULT_ROWS = 5000", "Default TF-IDF/numeric benchmark sample.", "experimental_protocol", evidence_status="preserved_legacy_results", sensitivity_risk="medium"),
        item("exp.benchmark_sbert_rows", scope, "algorithm benchmark", "sample_size", 2000, "rows", benchmark, "DEFAULT_SBERT_ROWS = 2000", "Default SBERT subset, creating a non-identical comparison unless overridden.", "experimental_protocol", evidence_status="preserved_legacy_results", sensitivity_risk="high", recommended_treatment="Compare algorithms on identical rows or report the mismatch explicitly."),
        item("exp.benchmark_support", scope, "algorithm benchmark", "minimum_support", "12 group rows; 2 error rows; top 5", "rows/groups", benchmark, "MIN_GROUP_SIZE = 12", "Filters and summarizes benchmark groups.", "experimental_protocol", evidence_status="preserved_legacy_results", sensitivity_risk="high"),
        item("exp.benchmark_k", scope, "algorithm benchmark", "cluster_count", 8, "clusters", benchmark, "DEFAULT_K = 8", "Default cluster count shared by K-means and agglomerative comparisons.", "experimental_protocol", evidence_status="preserved_legacy_results", sensitivity_risk="critical"),
        item("exp.benchmark_kmeans", scope, "algorithm benchmark", "algorithm_parameter", "seed 42; n_init 10", "runs", benchmark, "random_state=42, n_init=10", "Controls K-means repeatability and initialization search.", "experimental_protocol", evidence_status="preserved_legacy_results", sensitivity_risk="medium"),
        item("exp.benchmark_minibatch", scope, "algorithm benchmark", "algorithm_parameter", "seed 42; n_init 5; batch 512", "runs/rows", benchmark, "n_init=5, batch_size=512", "Controls MiniBatchKMeans initialization and update batch.", "experimental_protocol", evidence_status="preserved_legacy_results", sensitivity_risk="medium"),
        item("exp.benchmark_dbscan", scope, "algorithm benchmark", "parameter_grid", "eps .15/.30/.45; min_samples 8", "cosine distance/rows", benchmark, "for eps in [0.15, 0.30, 0.45]", "Density-clustering grid in the historical matrix benchmark.", "experimental_grid", evidence_status="preserved_legacy_results", sensitivity_risk="high"),
        item("exp.benchmark_hdbscan", scope, "algorithm benchmark", "algorithm_parameter", "min_cluster_size 24; min_samples 8", "rows", benchmark, "min_cluster_size=24, min_samples=8", "HDBSCAN settings in the historical matrix benchmark.", "experimental_protocol", evidence_status="preserved_legacy_results", sensitivity_risk="high"),
        item("exp.sweep_rows", scope, "parameter sweep", "sample_size", 3000, "rows", sweep, "DEFAULT_ROWS = 3000", "Default row count for legacy parameter sweeps.", "experimental_protocol", evidence_status="preserved_legacy_results", sensitivity_risk="high"),
        item("exp.sweep_sbert_gate", scope, "parameter sweep", "sample_size_cutoff", "<=1500 rows and richness >=.35", "rows/score", sweep, "DEFAULT_SBERT_MAX_ROWS = 1500", "Runs SBERT only on small enough, text-rich samples.", "experimental_protocol", evidence_status="preserved_legacy_results", sensitivity_risk="critical"),
        item("exp.sweep_feature_grid", scope, "parameter sweep", "parameter_grid", "100,250,350,500,1000", "TF-IDF features", sweep, "for features in [100, 250, 350, 500, 1000]", "Vocabulary-size sensitivity grid.", "experimental_grid", evidence_status="preserved_legacy_results", sensitivity_risk="medium"),
        item("exp.sweep_numeric_weight_grid", scope, "parameter sweep", "parameter_grid", ".25,.50,.75,1.0,1.5", "multiplier", sweep, "for weight in [0.25, 0.50, 0.75, 1.00, 1.50]", "Numeric/text weight sensitivity grid for pooled representation.", "experimental_grid", evidence_status="preserved_legacy_results", sensitivity_risk="high"),
        item("exp.sweep_tfidf_df_grids", scope, "parameter sweep", "parameter_grid", "min_df 1/2/3/5; max_df .75/.90/.98", "documents/fraction", sweep, "for min_df in [1, 2, 3, 5]", "TF-IDF document-frequency sensitivity grids.", "experimental_grid", evidence_status="preserved_legacy_results", sensitivity_risk="high"),
        item("exp.sweep_k_grid", scope, "parameter sweep", "parameter_grid", "4,6,8,10,12", "clusters", sweep, "for k in [4, 6, 8, 10, 12]", "K-means and agglomerative cluster-count grid.", "experimental_grid", evidence_status="preserved_legacy_results", sensitivity_risk="high"),
        item("exp.sweep_dbscan_grid", scope, "parameter sweep", "parameter_grid", "eps .05,.10,.15,.20,.30,.45,.60,.80 x min_samples 4,8,12", "distance/rows", sweep, "for eps in [0.05, 0.10, 0.15, 0.20, 0.30, 0.45, 0.60, 0.80]", "Broad DBSCAN sensitivity grid.", "experimental_grid", evidence_status="preserved_legacy_results", sensitivity_risk="high"),
        item("exp.sweep_agglomerative_distance", scope, "parameter sweep", "parameter_grid", ".25,.35,.45,.55", "cosine distance", sweep, "for threshold in [0.25, 0.35, 0.45, 0.55]", "Agglomerative distance-threshold grid.", "experimental_grid", evidence_status="preserved_legacy_results", sensitivity_risk="high"),
        item("exp.selector_shape_filters", scope, "adaptive selector prototype", "quality_threshold", "largest cluster <.90; noise <.70; small-cluster rows <.60", "fractions", selector, 'parser.add_argument("--max-largest-cluster-fraction"', "Rejects degenerate candidate clusterings in the unvalidated adaptive selector prototype.", "experimental_protocol", evidence_status="prototype_no_authoritative_results", sensitivity_risk="critical", recommended_treatment="Validate on planted groups and human ratings before production use."),
        item("exp.selector_feature_spaces", scope, "adaptive selector prototype", "feature_weight", "four fixed TF-IDF/numeric recipes", "features/weights", selector, '"max_text_features": 350', "Defines candidate pooled feature spaces for automatic selection.", "experimental_grid", evidence_status="prototype_no_authoritative_results", sensitivity_risk="critical"),
        item("exp.selector_candidate_grids", scope, "adaptive selector prototype", "parameter_grid", "K around heuristic; DBSCAN .25/.45/.65; agglomerative .30/.45; Birch .20/.35/.50; OPTICS xi .05", "mixed", selector, "for eps in [0.25, 0.45, 0.65]", "Candidate algorithms/settings searched by the prototype selector.", "experimental_grid", evidence_status="prototype_no_authoritative_results", sensitivity_risk="critical"),
        item("exp.selector_score_weights", scope, "adaptive selector prototype", "feature_weight", "lift 1.5; silhouette .35; issue homogeneity .75; tightness .25; shape penalties 1.5/1/.75; runtime .20", "score weights", selector, "lift_bonus = 1.5", "Ranks candidate algorithms in the prototype selector.", "experimental_protocol", evidence_status="prototype_no_authoritative_results", sensitivity_risk="critical", recommended_treatment="Do not present this as validated; derive objectives from benchmark labels and user value."),
    ]


def all_items() -> list[AuditItem]:
    return [
        *production_multiview_items(),
        *api_ui_items(),
        *profiler_dependency_items(),
        *detector_dependency_items(),
        *legacy_baseline_items(),
        *experiment_protocol_items(),
    ]


SCANNED_FILES = sorted(
    {
        item.source_file
        for item in all_items()
    }
)


def resolve_source(item_: AuditItem) -> tuple[int, str]:
    path = ROOT / item_.source_file
    if not path.exists():
        raise FileNotFoundError(f"{item_.threshold_id}: missing source file {path}")
    matches = [
        (number, line.rstrip())
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if item_.source_pattern in line
    ]
    if len(matches) < item_.occurrence:
        raise ValueError(
            f"{item_.threshold_id}: source pattern not found occurrence={item_.occurrence}: "
            f"{item_.source_pattern!r} in {item_.source_file}"
        )
    return matches[item_.occurrence - 1]


def validate(items: Iterable[AuditItem]) -> list[dict[str, object]]:
    materialized = list(items)
    ids = [entry.threshold_id for entry in materialized]
    duplicates = [key for key, count in Counter(ids).items() if count > 1]
    if duplicates:
        raise ValueError(f"Duplicate threshold IDs: {duplicates}")

    rows: list[dict[str, object]] = []
    for entry in materialized:
        source_line, source_code = resolve_source(entry)
        row = asdict(entry)
        row.pop("source_pattern")
        row.pop("occurrence")
        row["source_line"] = source_line
        row["source_reference"] = f"{entry.source_file}:{source_line}"
        row["source_code"] = source_code.strip()
        rows.append(row)

    utility = next(
        (entry for entry in materialized if entry.threshold_id == "mv.utility_weights"),
        None,
    )
    if utility is not None:
        values = [float(value) for value in re.findall(r"0?\.\d+", utility.value)]
        if round(sum(values), 8) != 1.0:
            raise ValueError(f"Multi-view utility weights do not sum to 1.0: {values}")
    elif "mv.utility_calibration" not in ids:
        raise ValueError("Audit must record either fixed utility weights or adaptive calibration.")
    return rows


NUMERIC_LITERAL = re.compile(r"(?<![A-Za-z0-9_])(?:\d+(?:\.\d+)?(?:e[+-]?\d+)?)(?![A-Za-z0-9_])", re.IGNORECASE)
DECISION_HINT = re.compile(
    r"threshold|weight|sample|rows|limit|min|max|clip|quantile|confidence|coverage|"
    r"stability|coherence|unique|ratio|count|range\(|\[:|head\(|round\(|n_init|batch|eps|k\s*=",
    re.IGNORECASE,
)


def numeric_literal_scan(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_location: dict[tuple[str, int], list[str]] = defaultdict(list)
    for row in rows:
        by_location[(str(row["source_file"]), int(row["source_line"]))].append(str(row["threshold_id"]))

    scan: list[dict[str, object]] = []
    for relative in SCANNED_FILES:
        path = ROOT / relative
        for line_number, code in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            literals = NUMERIC_LITERAL.findall(code)
            if not literals:
                continue
            matched = by_location.get((relative, line_number), [])
            stripped = code.strip()
            scan.append(
                {
                    "source_file": relative,
                    "source_line": line_number,
                    "numeric_literals": " | ".join(literals),
                    "code": stripped,
                    "decision_hint": bool(DECISION_HINT.search(stripped)),
                    "curated_threshold_ids": " | ".join(matched),
                    "screening_status": "covered_by_inventory" if matched else "raw_candidate_for_future_review",
                }
            )
    return scan


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summary_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for dimension in ("scope", "category", "decision_kind", "evidence_status", "sensitivity_risk"):
        counts = Counter(str(row[dimension]) for row in rows)
        for value, count in sorted(counts.items()):
            result.append({"dimension": dimension, "value": value, "count": count})
    return result


def markdown_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def write_markdown_inventory(path: Path, rows: list[dict[str, object]]) -> None:
    by_scope: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_scope[str(row["scope"])].append(row)

    lines = [
        "# Complete hard-coded decision inventory",
        "",
        "This file is generated from live source anchors. The `controls` column",
        "explains in plain language what each fixed decision changes. See",
        "`docs/clustering/HARD_CODED_THRESHOLD_AUDIT.md` for interpretation and",
        "priorities.",
        "",
    ]
    for scope, scope_rows in by_scope.items():
        lines.extend(
            [
                f"## {scope.replace('_', ' ').title()}",
                "",
                "| ID | Category | Value | What it controls | Risk | Source | Recommended treatment |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in scope_rows:
            values = [
                row["threshold_id"],
                row["category"],
                row["value"],
                row["controls"],
                row["sensitivity_risk"],
                f"`{row['source_reference']}`",
                row["recommended_treatment"],
            ]
            lines.append("| " + " | ".join(markdown_cell(value) for value in values) + " |")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_readme(output_dir: Path, rows: list[dict[str, object]], scan: list[dict[str, object]]) -> None:
    critical = [row for row in rows if row["sensitivity_risk"] == "critical"]
    drift = [row for row in rows if row["evidence_status"] == "configuration_drift"]
    text = f"""# Generated clustering threshold audit

Generated by `experiments/audit_clustering_thresholds.py`.

## Contents

- `hard_coded_threshold_inventory.csv`: curated, beginner-readable inventory.
- `hard_coded_threshold_inventory.json`: the same records for scripts/notebooks.
- `hard_coded_threshold_inventory.md`: complete human-readable appendix.
- `threshold_audit_summary.csv`: counts by scope, category, evidence, and risk.
- `numeric_literal_scan.csv`: raw line-level scan of every numeric literal in
  the scoped files. This is a completeness aid, not a claim that every number is
  a tunable threshold.

## Snapshot

- Curated decisions: **{len(rows)}**
- Critical sensitivity risks: **{len(critical)}**
- Known duplicated/default-drift entries: **{len(drift)}**
- Numeric-literal lines screened: **{len(scan)}**

The research interpretation and prioritized action plan live in
`docs/clustering/HARD_CODED_THRESHOLD_AUDIT.md`.
"""
    (output_dir / "README.md").write_text(text, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate source anchors and inventory invariants without writing outputs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = validate(all_items())
    if args.check:
        print(f"Threshold audit check passed: {len(rows)} curated decisions across {len(SCANNED_FILES)} files.")
        return 0

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    scan = numeric_literal_scan(rows)
    write_csv(output_dir / "hard_coded_threshold_inventory.csv", rows)
    (output_dir / "hard_coded_threshold_inventory.json").write_text(
        json.dumps(rows, indent=2),
        encoding="utf-8",
    )
    write_markdown_inventory(output_dir / "hard_coded_threshold_inventory.md", rows)
    write_csv(output_dir / "threshold_audit_summary.csv", summary_rows(rows))
    write_csv(output_dir / "numeric_literal_scan.csv", scan)
    write_readme(output_dir, rows, scan)
    print(f"Wrote {len(rows)} curated decisions and {len(scan)} numeric-literal lines to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
