# Buckaroo Semantic Row Grouping Documentation

This directory is the research and implementation record for Buckaroo's
semantic row-grouping work. It is intentionally stricter than a presentation:
claims are separated into deployed behavior, completed experiments, and future
work.

## Current implementation notice

The production backend includes a profiler-guided semantic-quality implementation in
`app/server_utils/multi_view_grouping.py`. Read
[ADAPTIVE_DECISION_POLICY.md](ADAPTIVE_DECISION_POLICY.md) and
[MULTI_VIEW_CLUSTERING_METHODOLOGY.md](MULTI_VIEW_CLUSTERING_METHODOLOGY.md).
The earlier K-means/error-concentration path remains available as a
compatibility baseline, but it is no longer the primary UI workflow.

## Documentation status

- Documentation refreshed: 2026-08-15
- Implementation branch: `codex/profiler-guided-clustering`
- Base branch: `codex/adaptive-profiling-core`
- Source of truth: committed implementation modules, focused unit tests, and
  the reproducibility protocol in this directory. Slide decks and verbal
  descriptions are secondary summaries.

## Read these files in order

1. [ADAPTIVE_DECISION_POLICY.md](ADAPTIVE_DECISION_POLICY.md)
   explains which decisions now adapt to the current dataset, which values are
   still fixed, and why human labels are evaluation evidence rather than a
   production input.
2. [MULTI_VIEW_CLUSTERING_METHODOLOGY.md](MULTI_VIEW_CLUSTERING_METHODOLOGY.md)
   specifies the profiler-guided combined-representation implementation and safeguards.
3. [HARD_CODED_THRESHOLD_AUDIT.md](HARD_CODED_THRESHOLD_AUDIT.md)
   inventories every fixed cutoff, weight, sample budget, cluster-count rule,
   and inherited profiler/detector threshold in the current research scope.
4. [CURRENT_PIPELINE_METHODOLOGY.md](CURRENT_PIPELINE_METHODOLOGY.md)
   records the earlier pooled/error-conditioned implementation retained as a
   baseline.
5. [EXPERIMENT_INVENTORY.md](EXPERIMENT_INVENTORY.md)
   records the completed clustering experiments, parameters, outputs, results,
   and claim limitations.
6. [REPRODUCIBILITY_PROTOCOL.md](REPRODUCIBILITY_PROTOCOL.md)
   specifies how a defensible rerun must be performed and recorded.
7. [DEFENSE_GUIDE.md](DEFENSE_GUIDE.md)
   provides concise explanations and answers to likely technical questions.

## Claim classification

| Classification | Meaning | Examples |
| --- | --- | --- |
| Primary implementation | Flask/API and current UI code path | One profiler-guided semantic-quality clustering matrix plus advisory duplicate matching |
| Compatibility baseline | Retained backend path | Pooled TF-IDF plus numeric features, deterministic local K-means, error-first, cluster-first, exact slices |
| Completed experiment | Script and output artifacts exist | Multi-dataset parameter sweep, matrix algorithm benchmark, semantic sketch comparison |
| Experimental implementation without preserved result set | Code exists, but no authoritative output directory was found | Adaptive semantic selector |
| Proposed work | Not implemented or not evaluated yet | Blinded human-rated external validity and broader cross-dataset confidence calibration |

## Five facts that must remain consistent

1. Buckaroo clusters **rows**, not columns.
2. TF-IDF is a feature representation, not a clustering algorithm.
3. Semantic-quality discovery reads all rows up to a 10,000-row resource cap and uses
   deterministic random sampling without replacement above that cap. The UI no
   longer supplies a fixed semantic sample size.
4. Profiler roles determine feature eligibility and representation. Identifier
   values do not enter semantic distance, and text/category tokens retain their
   source-column prefix.
5. Semantic groups can be returned with zero detector errors. When quality
   signals exist, they enter the same normalized representation; Buckaroo does
   not return context-free quality-only clusters.

## Primary implementation references

- `app/server_utils/semantic_grouping.py`
- `app/server_utils/adaptive_grouping_policy.py`
- `app/server_utils/multi_view_grouping.py`
- `app/routes/plot_routes.py`
- `ui/src/utils/serverCalls.jsx`
- `ui/src/panels/SemanticGroupsModal.jsx`
- `tests/unit/test_semantic_grouping.py`
- `tests/unit/test_adaptive_grouping_policy.py`
- `tests/unit/test_multi_view_grouping.py`

## Research scripts

- `experiments/semantic_grouping_real_detectors.py`
- `experiments/semantic_clustering_benchmark.py`
- `experiments/semantic_parameter_sweeps.py`
- `experiments/error_conditioned_semantic_sketch.py`
- `experiments/adaptive_semantic_selector.py`
- `experiments/audit_clustering_thresholds.py`
