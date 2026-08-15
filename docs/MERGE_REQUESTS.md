# Merge-Request Stack

The current working tree spans several independently reviewable systems. It is
split into stacked merge requests so reviewers can validate one behavioral
contract at a time. Merge them in the order below.

## 1. `codex/adaptive-profiling-core`

Base: `codex/frontend-improvements`

Scope:

- adaptive detector configuration and consistent detailed outputs;
- confidence-aware column profiling and semantic safeguards;
- exact/HLL cardinality and bounded UCC discovery;
- detector coverage metadata and backend upload/query hardening;
- provenance-safe repair and Pandas export helpers; and
- backend/unit tests for those contracts.

It deliberately excludes semantic grouping, new grouping UI, and research
result files.

## 2. `codex/profiler-guided-clustering`

Base: `codex/adaptive-profiling-core`

Scope:

- dataset-driven grouping policy;
- type-aware semantic and quality feature blocks;
- deterministic candidate generation and stability diagnostics;
- optional SBERT and offline geography references;
- grounded group descriptions and examples; and
- clustering unit tests and implementation documentation.

## 3. `codex/profiling-review-ui`

Base: `codex/profiler-guided-clustering`

Scope:

- compact profile cards and detail inspector;
- warning/review separation, filters, overrides, and examples-first evidence;
- profiler-guided grouping modal and row selection;
- repair safeguards, filter/delete-column actions, and export visibility;
- responsive styling and regenerated Vite distribution assets.

## 4. `codex/research-evaluation-pipeline`

Base: `codex/profiling-review-ui`

Scope:

- canonical sampling, noise, ablation, early-stopping, runtime, and grouping
  experiment drivers;
- reproducibility and benchmark validation helpers;
- methodology, threshold audit, benchmark protocol, and defense documentation;
- tests that prevent metric leakage and methodological regressions.

Generated outputs are excluded. A reviewer can rerun the experiment from the
committed driver and provide a dataset path explicitly.

## Review rule

Each merge request must report its own verification commands and known
limitations. A stacked child should not be merged before its base. If the host
repository prefers independent merge requests, rebase each child onto `main`
only after the preceding layer merges.
