# Buckaroo Semantic-Quality Clustering Benchmark Protocol

## Purpose

This benchmark tests whether Buckaroo discovers row groups that are both:

1. semantically coherent, meaning the rows describe a recognizable real-world
   cohort; and
2. quality-relevant, meaning the cohort has a data-quality pattern that is
   genuinely more common than in the rest of the data.

The benchmark does not assume that an internal score such as silhouette is a
substitute for usefulness. It combines blinded human judgments on real data
with exact ground truth from controlled semi-synthetic cases.

## Frozen Dataset Partitions

The partitions prevent design decisions from leaking into the final test.

- **Development:** four familiar datasets. These may be inspected while code is
  developed and debugged.
- **Validation:** four new datasets. These may be used to select between
  documented alternatives, but not repeatedly tuned after a decision is made.
- **Locked test:** four new datasets. Their labels and human ratings must remain
  unused until the implementation and evaluation protocol are frozen.

The benchmark deliberately includes transactions, demographics, geography,
time series, operational text, sensor measurements, sequential clickstream
data, and regulatory records. Source URLs, licenses, row counts, columns, and
file hashes are stored in `dataset_manifest.csv`.

| Partition | Datasets | Why they are included |
| --- | --- | --- |
| Development | `taxi_trips`, `diamonds_pricing`, `adult_census_income`, `us_airports` | Familiar mobility, retail measurement, demographic, and geography structures used for implementation debugging. |
| Validation | `bank_marketing`, `seoul_bike_demand`, `nyc_311_requests`, `usgs_earthquakes_2023` | Previously unused finance, demand time-series, civic operations, and event-geography structures used for documented design selection. |
| Locked test | `online_shoppers_intention`, `appliances_energy`, `eshop_clickstream`, `chicago_food_inspections` | Previously unused e-commerce behavior, sensors, sequential sessions, and regulatory records reserved for final evaluation. |

## Real-Data Human Evidence

### Pairwise review

For each dataset, the generator creates a blinded mixture of:

- candidate-similar row pairs;
- candidate-contrast row pairs; and
- random row pairs.

The sampling stratum is stored only in the private audit file. Reviewers see the
same fields for every task and rate:

- semantic similarity from 1 to 5;
- whether the rows could belong to one useful group;
- which fields support or contradict that judgment; and
- reviewer confidence from 1 to 5.

At least two reviewers should independently rate a shared subset. Agreement is
reported with weighted kappa for ordinal ratings and raw agreement for the
yes/no/unsure decision. Disagreements are preserved, not silently overwritten.

Version 1 generates 12 pair tasks per dataset as a review-time and variance
pilot. That count is not claimed to be universally sufficient. Before the final
paper run, use pilot completion time and rating variance to preregister the
final task count, then rebuild a new version without looking at method results.

### AI comparison fields

The review workbook places an AI comparison beside every human pairwise field.
This is a secondary baseline, not human ground truth and not an adjudication
vote. To avoid anchoring bias, reviewers complete the blue human cells before
reading the purple AI cells.

The version-1 AI reference is deliberately column-aware:

- numeric values are compared using robust, dataset-relative scales, so a
  difference of 10 is interpreted differently for fares and million-dollar
  salaries;
- datetime values are compared using dataset-relative time gaps;
- textual values use exact and lexical evidence together with MiniLM semantic
  embeddings from `sentence-transformers/all-MiniLM-L6-v2`;
- identifier-like fields are down-weighted because matching IDs do not prove
  that two records have the same real-world meaning; and
- missing or incomparable fields reduce evidence coverage instead of being
  silently treated as a match.

For each pair the workbook records the AI's 1-to-5 semantic rating, continuous
0-to-1 score, same-group decision, supporting fields, conflicting fields,
confidence, model/version, timestamp, and a plain-language reason quoting the
actual compared values. The reason is intentionally auditable: a reviewer can
see which fields moved the score up or down and can disagree with that logic.

Cluster-level AI fields are present but remain explicitly marked `Pending`
until a candidate cluster description and representative examples exist. No
cluster score is generated from an empty template.

### Cluster review

After candidate algorithms produce clusters, their method names are replaced
with random blind IDs. Reviewers should see representative rows, the proposed
description, and quality evidence, but not the algorithm name or its internal
score. Each group is rated for:

- semantic coherence;
- semantic-quality integration;
- usefulness/actionability;
- description clarity;
- whether the reviewer would use the group; and
- reviewer confidence.

Method identities are unblinded only after ratings are locked.

## Semi-Synthetic Ground Truth

Semi-synthetic cases begin with unmodified rows from a real dataset. A semantic
cohort is selected using interpretable categorical conditions and/or
dataset-relative quantiles. A controlled quality problem is then injected.
Ground-truth labels are stored outside the case CSV so the algorithm cannot use
them as features.

Every row receives three private labels:

- `is_semantic_cohort`: belongs to the planted meaningful cohort;
- `is_injected_error`: received the controlled quality problem; and
- `is_joint_target`: belongs to the cohort and received that problem.

The experiment uses 5%, 10%, and 20% error injection within the semantic cohort
and three deterministic seeds. These are experimental stress conditions, not
production decision thresholds.

## Correlated and Shuffled Controls

Each semi-synthetic case has two association modes:

- **Correlated:** errors are injected inside the semantic cohort. A useful
  method should be able to surface the cohort and its elevated error rate.
- **Shuffled control:** the same number and type of errors are spread across the
  dataset. A method should not invent a semantic-quality relationship merely
  because errors exist.

The shuffled control is essential. It distinguishes a method that discovers a
real relationship from one that simply overweights quality flags.

## Evaluation Metrics

Metrics are reported separately rather than collapsed into one hand-weighted
utility score.

### Exact semi-synthetic metrics

- best-match adjusted Rand index and normalized mutual information;
- pairwise precision, recall, and F1 for semantic cohort membership;
- recall of injected-error rows inside the matched semantic group;
- error-rate lift relative to the whole dataset;
- false association rate on shuffled controls; and
- stability across seeds and repeated row samples.

### Human metrics

- median semantic-coherence rating;
- median semantic-quality-integration rating;
- median actionability rating;
- median description-clarity rating;
- proportion that reviewers would use; and
- inter-reviewer agreement.

### Operational metrics

- runtime and peak memory;
- number of rows analyzed;
- number and size distribution of returned groups; and
- percentage of rows left unassigned, when supported by the method.

Runtime is recorded from the beginning, but semantic quality is the first-stage
selection objective.

## Statistical Comparison

All methods receive identical datasets, row samples, seeds, and output budgets.
Results are paired by dataset and seed. Report per-dataset results, paired effect
sizes, and bootstrap confidence intervals rather than only a pooled average.

A specialized algorithm is retained only when it improves held-out semantic or
human usefulness evidence without creating a worse false-association rate on
the shuffled controls. If the evidence does not show a meaningful advantage,
the simpler single-algorithm implementation is preferred.

## Reproducibility and Blinding

- Raw sources are cached; both raw sources and canonical CSVs are hashed.
- Every generated case records its seed, conditions, injection rate, and hash.
- Error injection logs and membership labels remain in `private_ground_truth`.
- Human task files do not expose algorithm identity or sampling stratum.
- Locked-test results are opened only after implementation choices are frozen.
- Any post-hoc change creates a new benchmark version rather than rewriting
  version 1 results.

## Build Command

```powershell
python experiments/build_semantic_quality_benchmark.py
```

For a quick smoke build:

```powershell
python experiments/build_semantic_quality_benchmark.py --dataset taxi_trips --case-rows 1000
```
