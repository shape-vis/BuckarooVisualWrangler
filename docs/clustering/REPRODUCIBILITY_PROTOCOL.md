# Reproducibility Protocol for Buckaroo Clustering Research

## 1. Purpose

This protocol defines the minimum information and procedure required to turn
Buckaroo's preliminary clustering artifacts into reproducible research results.
It is intentionally more demanding than simply rerunning a Python script.

## 2. Audited environment snapshot

The following environment was observed on 2026-07-15:

| Item | Observed value |
| --- | --- |
| Operating system | Windows 11, build reported as `10.0.26200` |
| Computer | Dell XPS 14 9440 |
| CPU | Intel Core Ultra 7 155H |
| CPU cores / logical processors | 16 / 22 |
| Physical memory | 31.46 GiB |
| Python | 3.12.10 |
| NumPy | 2.4.6 |
| Pandas | 2.2.3 |
| scikit-learn | 1.9.0 |
| HDBSCAN | 0.8.44 |
| sentence-transformers | 5.5.1 |
| PyTorch | 2.12.1 CPU build |
| CUDA | unavailable |
| Flask | 3.1.3 |
| SQLAlchemy | 2.0.50 |
| pytest | 8.4.2 |
| PostgreSQL container | PostgreSQL 15 image, host port 5433 |

This historical snapshot describes the machine at the July audit. Historical clustering
artifacts do not prove that every recorded run used this exact state.

## 3. Dependency gap that must be fixed

`requirements.txt` declares production dependencies but does not currently
declare:

- scikit-learn;
- HDBSCAN;
- sentence-transformers; or
- PyTorch.

It also declares NumPy approximately 2.0.2, while the audited interpreter had
NumPy 2.4.6. A publication artifact must use a dedicated locked experiment
environment. Do not rely on a globally installed Python environment.

Recommended artifacts:

```text
requirements-production.txt
requirements-clustering.txt
requirements-clustering-lock.txt
```

The lock file should be generated only after the final experiment environment
passes all tests and smoke runs.

## 4. Source-code state

At the historical July audit:

```text
branch = codex/frontend-improvements
HEAD   = 4f51ac3efc9e7dea3a5aafc39ff7ea437715c05c
```

The working tree then contained many modified and untracked files, including the
semantic grouping implementation and the complete `experiments/` directory.
Therefore `HEAD` is not sufficient to reproduce the audited pipeline.

Before a paper rerun:

1. remove temporary benchmark scripts and disposable artifacts;
2. commit the production clustering implementation and tests;
3. commit experiment scripts and documentation separately;
4. tag the exact experiment commit; and
5. record both commit hash and `git status --porcelain` in every run manifest.

A run must be marked invalid for publication when the working tree is dirty
unless a patch file and hash of that patch are archived with the run.

## 5. Dataset manifest requirements

Create one manifest row per physical dataset file with:

| Required field | Description |
| --- | --- |
| `dataset_id` | Stable research identifier |
| `source_name` | Original source organization/site |
| `source_url` | Download page, not an untraceable mirror |
| `license` | Redistribution and research-use terms |
| `downloaded_at_utc` | Acquisition timestamp |
| `local_filename` | File used by the script |
| `sha256` | Cryptographic hash of exact bytes |
| `bytes` | File size |
| `row_count` | Parsed data rows |
| `column_count` | Parsed columns |
| `column_names` | Ordered schema or schema-file path |
| `domain` | Finance, health, retail, geography, etc. |
| `known_variants` | Cleaned, missing-data, copied, or transformed relationships |
| `independent_dataset_group` | Identifier grouping copies/variants of one source |
| `target_or_known_class` | Ground-truth class if one exists |
| `notes` | Parsing, encoding, or source caveats |

Files that are copies or transformations of one source must not be counted as
independent datasets.

## 6. Experimental unit and repeated trials

Define one experimental unit as:

```text
dataset
x sample size
x sample seed
x feature representation
x clustering algorithm
x algorithm parameters
```

For sample-based evaluation, use at least ten independent deterministic seeds
per dataset and sample size. A reasonable initial grid is:

```text
sample sizes = 500, 1,000, 2,000, 5,000, full when feasible
seeds        = 0 through 9
```

Do not treat ten algorithms on one sample as ten repetitions. They are ten
methods evaluated on one experimental draw.

## 7. Sampling protocol

### 7.1 Required replacement for prefix sampling

For static CSV files:

1. Create one seeded random permutation of row positions per seed.
2. Define smaller samples as prefixes of that same permutation.
3. This makes 500-row samples nested inside 1,000-row samples for a given seed.
4. Preserve the selected source row IDs or their SHA-256 hash.

For PostgreSQL tables, use a reproducible method that does not depend on
physical row order. Options include selecting a deterministic hash of stable row
IDs or materializing a seeded permutation outside SQL.

### 7.2 Without replacement

Sample rows without replacement. Duplicate sampling would alter category
frequencies and cluster geometry.

### 7.3 Full-pass condition

The full-pass run must use every parsed data row after only the documented
schema/ID normalization. It must not be described as "full" when capped by an
SBERT or UI limit.

### 7.4 Avoiding sample leakage

When selecting algorithms or thresholds:

- tune on training datasets;
- freeze the policy;
- evaluate once on held-out datasets; and
- never choose the held-out winner and then report that same maximum as test
  performance.

Leave-one-dataset-out evaluation is appropriate when the benchmark remains
small.

## 8. Representation conditions for the next study

Use the same sampled rows for every representation within one unit.

| Representation ID | Numeric block | Text block | Purpose |
| --- | --- | --- | --- |
| `numeric_only` | robust numeric plus missingness | none | Tests contribution of numeric structure |
| `pooled_tfidf_only` | none | current pooled TF-IDF | Tests lexical/category evidence alone |
| `pooled_tfidf_numeric` | weight 0.75 | current pooled TF-IDF | Current production representation |
| `column_aware_tfidf_numeric` | weight 0.75 | tokens such as `country=india` | Tests the professor's feature-collapse concern |
| `sbert_numeric` | documented weight | row embeddings | Tests learned semantic representation |

All representations must preserve:

- actual matrix dimensions;
- number and names/hash of numeric features;
- vocabulary or vocabulary hash;
- discarded-term counts by reason;
- numeric/text weights; and
- feature-construction time and peak memory.

## 9. Algorithm conditions

Use identical feature matrices across algorithms within a representation.

Minimum comparison:

| Family | Algorithm | Required parameter record |
| --- | --- | --- |
| Partitioning | KMeans | `k`, initialization, `n_init`, seed, max iterations, tolerance |
| Scalable partitioning | MiniBatchKMeans | KMeans fields plus batch size |
| Hierarchical | Agglomerative | cluster count or distance threshold, metric, linkage |
| Density | DBSCAN | `eps`, `min_samples`, metric, noise handling |
| Hierarchical density | HDBSCAN | min cluster size, min samples, metric, selection method |
| Baseline | Exact slices | cardinality cap, binning, interaction order, support filters |

Do not compare algorithms with different representations and attribute the
difference solely to the algorithm.

## 10. Required output schema

Every per-run CSV row should contain at least:

```text
run_id
started_at_utc
git_commit
git_dirty
dataset_id
dataset_sha256
dataset_rows
dataset_columns
sample_size_requested
sample_size_actual
sample_seed
sample_row_ids_sha256
representation
numeric_columns
text_columns
matrix_rows
matrix_features
numeric_weight
text_or_embedding_weight
vocabulary_size
algorithm
algorithm_params_json
feature_time_seconds
cluster_time_seconds
description_time_seconds
total_time_seconds
peak_memory_mib
raw_cluster_count
noise_rows
largest_cluster_fraction
small_cluster_row_fraction
silhouette_cosine
davies_bouldin
calinski_harabasz
stability_ari
stability_nmi
human_coherence_score
human_label_agreement
baseline_error_rate
top_error_lift
top5_error_coverage
failure_type
failure_message
```

Use empty/null values for inapplicable metrics. Do not encode failures as zeros,
because zero can be a valid score.

## 11. Evaluation metrics

### 11.1 Intrinsic cluster geometry

Report:

- cosine silhouette;
- Davies-Bouldin index;
- Calinski-Harabasz index;
- largest-cluster fraction;
- noise fraction; and
- distribution of cluster sizes.

No one metric is sufficient. Silhouette can favor compact shapes and can be
misleading in sparse high-dimensional spaces.

### 11.2 Stability

Compare cluster assignments across seeds or sample sizes with:

- Adjusted Rand Index (ARI);
- Normalized Mutual Information (NMI); and
- assignment agreement for rows shared by both samples.

Because cluster numeric labels are arbitrary, do not compare labels with direct
equality before label alignment or a permutation-invariant metric.

### 11.3 Semantic validity

Create a human evaluation form for each returned cluster containing:

- representative rows nearest the centroid;
- boundary or low-confidence rows;
- cluster description;
- discriminating columns/terms; and
- neighboring cluster descriptions.

Reviewers should independently rate:

1. within-cluster coherence;
2. distinction from neighboring clusters;
3. description faithfulness;
4. domain usefulness; and
5. whether the cluster is primarily semantic or merely a missingness/error
   pattern.

Report inter-rater agreement and adjudication procedure.

### 11.4 Error-discovery utility

Keep detector-based metrics as a separate evaluation layer:

- error rate;
- lift over baseline;
- error coverage;
- dominant detector issue homogeneity; and
- number of actionable groups.

Do not combine semantic and error metrics into one headline score unless weights
were selected and validated independently.

## 12. Runtime protocol

### 12.1 Timing boundaries

Measure and report separately:

1. file/database loading;
2. detector execution;
3. role inference;
4. feature construction;
5. clustering fit;
6. full-data assignment, when separate;
7. explanation generation;
8. serialization; and
9. end-to-end execution.

Use `time.perf_counter()` for elapsed wall time.

### 12.2 Warm-up and repetitions

- Record one cold run separately.
- Perform at least five timed warm runs for lightweight methods.
- Use enough repeats for expensive methods to estimate variance without wasting
  the full budget.
- Report median, interquartile range, minimum, and maximum.
- Do not report only the fastest run.

### 12.3 Resource conditions

Record:

- CPU model and logical processor count;
- physical memory;
- GPU model or CPU-only status;
- process concurrency;
- thread environment variables;
- whether other Meta candidates ran concurrently;
- model cache state; and
- peak resident memory.

SBERT cold-start model loading/download must be separated from warm embedding
time.

## 13. Commands for auditing the current implementation

Run from `C:\BuckarooVisualWrangler`.

### 13.1 Unit tests

```powershell
python -m pytest tests/unit/test_semantic_grouping.py -q
```

### 13.2 Single-dataset benchmark

```powershell
python experiments/semantic_clustering_benchmark.py `
  --dataset provided_datasets/stackoverflow_db_uncleaned_original.csv `
  --rows 5000 `
  --sbert-rows 2000 `
  --k 8 `
  --full-tfidf `
  --out-dir experiments/semantic_benchmark_outputs_rerun
```

### 13.3 Multi-file parameter sweep

The historical invocation was not preserved. This command reconstructs the
scope reported by the existing combined report but is not evidence of the exact
original shell invocation:

```powershell
python experiments/semantic_parameter_sweeps.py `
  --multi-dataset `
  --dataset-dir provided_datasets `
  --max-files 13 `
  --rows 2000 `
  --multi-out-dir experiments/semantic_parameter_sweep_outputs_multi_rerun
```

### 13.4 Adaptive selector smoke run

```powershell
python experiments/adaptive_semantic_selector.py `
  --dataset provided_datasets/adult.csv `
  --rows 2000 `
  --out-dir experiments/adaptive_selector_outputs_rerun
```

The adaptive selector currently has no preserved authoritative output folder.
A successful command is therefore a new run, not a reproduction of an existing
result.

## 14. Required artifact directory for each run

```text
run_<UTC timestamp>_<short commit>/
  run_config.json
  environment.json
  dataset_manifest.csv
  sample_manifest.csv
  per_run_metrics.csv
  cluster_assignments.parquet
  cluster_descriptions.json
  failures.csv
  stdout.log
  stderr.log
  summary.md
```

The cluster-assignment artifact is necessary for stability analysis. Summary
tables alone cannot reconstruct ARI/NMI or inspect individual rows.

## 15. Publication checklist

- [ ] Source code committed and tagged.
- [ ] Working tree clean.
- [ ] Experiment dependencies locked.
- [ ] Dataset sources and licenses recorded.
- [ ] Every input file hashed.
- [ ] Copies/variants grouped as non-independent.
- [ ] Seeded random sampling used.
- [ ] Repeated trials completed.
- [ ] Algorithm selection separated from held-out evaluation.
- [ ] Matrix shapes and feature settings preserved.
- [ ] Cluster assignments archived.
- [ ] Runtime boundaries and hardware recorded.
- [ ] Semantic human evaluation completed.
- [ ] Error-discovery evaluation reported separately.
- [ ] Failed runs retained and explained.
- [ ] Tables regenerated directly from raw outputs.
- [ ] Claims checked against the limitations section.
