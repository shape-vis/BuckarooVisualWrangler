# Semantic Clustering Experiment Inventory

## 1. Purpose

This ledger records the clustering-related experiments currently present in the
workspace. It separates scripts, preserved outputs, measured results, and valid
conclusions. It also identifies places where an artifact cannot support a
research claim because provenance, repetitions, or semantic ground truth are
missing.

## 2. Evidence levels

| Level | Evidence requirement | Interpretation |
| --- | --- | --- |
| A | Script, configuration, raw per-run output, dataset identity/hash, environment, repetitions | Suitable for a primary paper result |
| B | Script and raw output exist, but one or more provenance fields are missing | Useful preliminary evidence; rerun before publication |
| C | Script exists but no authoritative output was found | Implemented proposal, not a completed result |
| D | Slide or verbal summary without a traceable raw output | Presentation context only; do not cite as experimental evidence |

All currently preserved clustering experiments are Level B or C. None is yet
Level A because the clustering scripts do not preserve dataset hashes, Git
working-tree state, full environment metadata, or repeated random trials.

## 3. Production strategy comparison

### 3.1 Script and artifacts

- Script: `experiments/semantic_grouping_real_detectors.py`
- Primary report: `experiments/semantic_outputs/strategy_comparison.md`
- Detailed CSVs:
  - `strategy_exact_slices_semantic.csv`
  - `strategy_cluster_first_semantic.csv`
  - `strategy_error_first_semantic.csv`
  - `adult_1000_real_buckaroo_errors.csv`
  - `adult_1000_error_table.csv`

### 3.2 Experimental question

On a shared dataset and detector output, how do three grouping orders differ?

1. exact values/bins, followed by error ranking;
2. semantic/numeric clustering of all rows, followed by error ranking; and
3. filtering to error rows first, followed by semantic/numeric clustering.

### 3.3 Data and control conditions

- Dataset: first 1,000 rows of `adult.csv`
- Buckaroo detector records: 393
- Rows with one or more errors: 271
- Baseline error-row rate: 27.1%
- Historical script constants:
  - minimum group rows: 20
  - minimum error rows: 5
  - cluster-first `k`: 8
  - error-first `k`: 6

The sample was a first-row prefix, not a random sample.

### 3.4 Headline observations

- Exact slices identified missing `workclass`/`occupation` groups with 100%
  error rate and 3.69x lift.
- Cluster-first identified a capital-loss cluster with 46/46 error rows and
  3.69x lift, while also returning lower-lift clusters.
- Error-first produced groups with 100% error rate by design because only error
  rows were supplied to clustering.

### 3.5 Interpretation boundary

This experiment compares error-discovery workflows. It does not measure whether
the clusters are the correct semantic partition of Adult Census rows.

## 4. Matrix representation and algorithm benchmark

### 4.1 Script

`experiments/semantic_clustering_benchmark.py`

### 4.2 Tested representations

| Representation | Construction |
| --- | --- |
| TF-IDF plus numeric | Production pooled row TF-IDF, robust numeric features, numeric weight 0.75, final L2 normalization |
| Numeric-only | Robust numeric block, L2-normalized |
| SBERT | `sentence-transformers/all-MiniLM-L6-v2` row embeddings, normalized by the model |
| Exact slices | Exact category values and numeric bins; no vector clustering |

The benchmark SBERT row text includes both text and numeric values as
`column: value` strings. This differs from production TF-IDF, which sends only
inferred text/category columns to the text document and keeps numeric columns in
a separate numeric block.

### 4.3 Tested algorithms and parameters

| Algorithm | Parameters in benchmark |
| --- | --- |
| KMeans | `k=8` by default, random state 42, `n_init=10` |
| MiniBatchKMeans | `k=8`, random state 42, `n_init=5`, batch size 512 |
| DBSCAN | cosine distance, `min_samples=8`, `eps` in 0.15, 0.30, 0.45 |
| Agglomerative | cosine distance, average linkage, `k=8` |
| HDBSCAN | Euclidean distance on normalized vectors, `min_cluster_size=24`, `min_samples=8` |
| Exact slices | production exact-slice helper with minimum group 12 and minimum error rows 2 |

The `--fast-large` flag omits DBSCAN, Agglomerative, and HDBSCAN. The
`--full-tfidf` flag adds a full-file TF-IDF plus KMeans run. The `--skip-sbert`
flag omits SBERT.

### 4.4 Recorded metrics

The benchmark CSV records:

- feature construction time;
- clustering time;
- groups surviving error/size filters;
- raw non-noise cluster count;
- number of rows labeled noise;
- top-group error lift;
- top-group error rate, size, and error-row count;
- dominant detector issue and group description; and
- notes containing selected parameters.

It does not record silhouette, stability, peak memory, repetitions, or semantic
ground-truth agreement. Those were added in the later parameter-sweep script.

### 4.5 Preserved benchmark scopes and matrix dimensions

| Output directory | Dataset/sample | TF-IDF plus numeric shape | SBERT shape | Full TF-IDF shape |
| --- | ---: | ---: | ---: | ---: |
| `semantic_benchmark_outputs` | StackOverflow 5,000 | 5,000 x 219 | 2,000 x 384 | 38,090 x 220 |
| `semantic_benchmark_outputs_adult_large` | Adult 30,000 | 30,000 x 144 | 5,000 x 384 | 48,842 x 144 |
| `semantic_benchmark_outputs_cars` | Cars 20,000 | 20,000 x 356 | 5,000 x 384 | 20,000 x 356 |
| `semantic_benchmark_outputs_games` | Games 12,000 | 12,000 x 363 | 3,000 x 384 | 16,719 x 363 |
| `semantic_benchmark_outputs_complaints` | Complaints 6,855 | 6,855 x 351 | 3,000 x 384 | 6,855 x 351 |

Matrix feature counts include retained text features plus numeric coordinates
and numeric missingness indicators. They can exceed 350 even though the TF-IDF
vocabulary itself is capped at 350.

### 4.6 Selected historical runtimes

The following values are transcribed from preserved CSV artifacts. "Total" is
feature time plus cluster time and excludes loading, detector execution,
serialization, and UI rendering.

| Dataset/sample | Method | Feature sec | Cluster sec | Approx total sec |
| --- | --- | ---: | ---: | ---: |
| StackOverflow 5,000 | TF-IDF+numeric KMeans | 1.8432 | 2.5738 | 4.4170 |
| StackOverflow 5,000 | TF-IDF+numeric MiniBatchKMeans | 1.8432 | 0.7097 | 2.5529 |
| Adult 30,000 | TF-IDF+numeric KMeans | 2.6243 | 2.6345 | 5.2588 |
| Adult 48,842 full | TF-IDF+numeric KMeans | 6.5255 | 1.8450 | 8.3705 |
| Adult 5,000 SBERT subset | SBERT KMeans | 65.5107 | 0.5451 | 66.0558 |
| Cars 20,000 | TF-IDF+numeric KMeans | 6.3844 | 3.0248 | 9.4092 |
| Cars 5,000 SBERT subset | SBERT KMeans | 174.1371 | 0.6618 | 174.7989 |
| Games 12,000 | TF-IDF+numeric KMeans | 1.3959 | 2.6461 | 4.0420 |
| Complaints 6,855 | TF-IDF+numeric KMeans | 1.7282 | 2.5580 | 4.2862 |

### 4.7 Detector saturation caveat

Some samples had every row marked as erroneous:

- Cars 20,000: 20,000 error rows;
- Complaints 6,855: 6,855 error rows.

Games also had 10,240 error rows among 12,000 rows. When baseline error rate is
1.0, no group can have lift greater than 1.0. Runtime comparisons remain useful,
but error-lift winner claims are not informative for those data.

### 4.8 Runtime provenance caveat

The benchmark outputs do not preserve the original machine, package versions,
CPU/GPU utilization, warm-up state, or repetition count. Separate comparison
artifacts contain different timing values for apparently similar runs, for
example Cars 20,000 feature time 10.5376 seconds in
`semantic_sketch_vs_matrix_comparison.csv` versus 6.3844 seconds in the current
Cars benchmark output. These should be treated as separate historical runs, not
averaged together.

## 5. Multi-dataset parameter sweep

### 5.1 Script and outputs

- Script: `experiments/semantic_parameter_sweeps.py`
- Combined report:
  `experiments/semantic_parameter_sweep_outputs_multi/combined_semantic_parameter_sweep_report.md`
- Combined per-run table:
  `combined_semantic_parameter_sweep_results.csv`
- One-row-per-file summary:
  `combined_dataset_summary.csv`
- Full structured output:
  `combined_semantic_parameter_sweep_results.json`
- Per-file reports under `per_dataset/<dataset_name>/`

### 5.2 Run scope preserved in the report

- Files tested: 13
- Requested rows per file: 2,000
- One file contained only 400 rows
- Detectors: current workspace implementations imported from `detectors/`
- Minimum group size: 12
- Minimum error rows: 2
- Top groups used in aggregate metrics: 5
- Random state for scikit-learn KMeans and silhouette subsampling: 42
- SBERT: disabled in the preserved combined report

`pandas.read_csv(..., nrows=2000)` was used, so samples were file prefixes rather
than randomized samples.

### 5.3 Base parameter grid

Every file received 55 base runs:

| Block | Variable | Values | Runs |
| --- | --- | --- | ---: |
| A | Maximum TF-IDF features | 100, 250, 350, 500, 1000 with KMeans `k=8` | 5 |
| B | KMeans cluster count | 4, 6, 8, 10, 12 with 350 text features | 5 |
| C | DBSCAN | `eps` 0.05, 0.10, 0.15, 0.20, 0.30, 0.45, 0.60, 0.80 crossed with `min_samples` 4, 8, 12 | 24 |
| D | Agglomerative fixed `k` | 4, 6, 8, 10, 12, cosine/average linkage | 5 |
| E | Agglomerative distance threshold | 0.25, 0.35, 0.45, 0.55, cosine/average linkage | 4 |
| F | Numeric block weight | 0.25, 0.50, 0.75, 1.00, 1.50 with KMeans `k=8` | 5 |
| G | TF-IDF minimum document frequency | 1, 2, 3, 5 with KMeans `k=8` | 4 |
| H | TF-IDF maximum document-frequency ratio | 0.75, 0.90, 0.98 with KMeans `k=8` | 3 |

Feature matrices with identical settings were cached within one dataset run.
Feature time therefore describes one matrix construction, not repeated
construction for every algorithm using that matrix.

### 5.4 Optional SBERT grid

When `--include-sbert` is enabled, SBERT runs only when:

- at least one text/category column exists;
- sampled rows do not exceed the configured cap, default 1,500; and
- semantic richness score is at least 0.35.

Richness score is a hand-weighted combination:

```text
0.45 * min(avg tokens per text value / 5, 1)
+ 0.35 * min(long text cell fraction / 0.20, 1)
+ 0.20 * min(distinct tokens per text value / 0.75, 1)
```

SBERT documents include at most 12 text columns and 300 characters per value.
The default model is `all-MiniLM-L6-v2`, batch size is 64, embeddings are
normalized, numeric weight is 0.35, and embedding weight is 1.0.

Eligible SBERT datasets add ten runs:

- KMeans with `k` 4, 6, 8, 10;
- Agglomerative distance thresholds 0.25, 0.35, 0.45; and
- DBSCAN `eps` 0.15, 0.25, 0.35 with `min_samples=8`.

### 5.5 Geometry and structure metrics

The parameter sweep records:

- `raw_clusters`: non-noise cluster count;
- `noise_rows`: rows assigned label `-1`;
- minimum, maximum, and median cluster size;
- cluster-size coefficient of variation;
- largest-cluster fraction;
- `degenerate_clustering`: fewer than two clusters or largest fraction at least
  0.95;
- cosine silhouette, calculated on at most 1,000 non-noise rows;
- centroid tightness, the cluster-size-weighted mean cosine similarity to
  normalized centroids.

### 5.6 Detector-alignment metrics

Each row is assigned a "dominant issue" label equal to its most frequent
`error_type:column_id`, or `clean` when it has no detector error. Cluster labels
are compared with these labels using:

- homogeneity;
- completeness; and
- V-measure.

These metrics measure alignment with Buckaroo detector categories. They are not
human semantic-ground-truth metrics.

### 5.7 Error-discovery metrics

The script records top group score, lift, error rate, size, error rows, coverage,
mean top-five score, mean top-five lift, and summed top-five error coverage.

A run is called an `error_discovery_candidate` only when:

```text
groups_returned > 0
AND clustering is non-degenerate
AND top_lift >= 1.2
```

Headline selection first filters to these candidates. If none exist, it uses a
non-degenerate fallback. It then selects the largest `mean_top5_score`, breaking
ties with `top_score`.

Therefore the "winning algorithm" is the best candidate under the implemented
error-discovery score, not the best semantic clustering under human judgment.

### 5.8 Preserved headline results

| File | Rows | Baseline error rate | Selection basis | Reported winner | Selected configuration |
| --- | ---: | ---: | --- | --- | --- |
| Adult | 2,000 | 0.3445 | error discovery | KMeans | numeric weight 1.0, `k=8` |
| Cars | 2,000 | 1.0000 | non-degenerate fallback | DBSCAN | `eps=0.60`, `min_samples=12` |
| Complaints | 2,000 | 1.0000 | non-degenerate fallback | DBSCAN | `eps=0.45`, `min_samples=4` |
| Crimes | 2,000 | 0.2850 | error discovery | Agglomerative | distance threshold 0.45 |
| Crimes one-year file | 2,000 | 0.2885 | error discovery | KMeans | `k=12` |
| Crimes copy | 2,000 | 0.2850 | error discovery | Agglomerative | distance threshold 0.45 |
| Games | 2,000 | 0.4885 | error discovery | Agglomerative | `k=4`, average linkage |
| Missing-data StackOverflow | 2,000 | 0.1170 | error discovery | Agglomerative | distance threshold 0.55 |
| Original crimes file | 2,000 | 0.2885 | error discovery | KMeans | `k=12` |
| Original StackOverflow | 2,000 | 0.1140 | error discovery | Agglomerative | distance threshold 0.45 |
| StackOverflow DB | 2,000 | 0.1105 | error discovery | Agglomerative | distance threshold 0.45 |
| StackOverflow uncleaned | 400 | 0.2100 | error discovery | KMeans | `k=12` |
| StackOverflow original | 2,000 | 0.1140 | error discovery | Agglomerative | distance threshold 0.45 |

Algorithm winner counts were Agglomerative 7, KMeans 4, and DBSCAN 2.

### 5.9 Independence caveat

The 13 files are not 13 independent semantic domains. They include copies,
original/modified versions, and several StackOverflow and crime variants. The
headline count therefore measures **files**, not independent datasets. It should
not be reported as broad 13-domain generalization.

### 5.10 Multiple-comparison caveat

Fifty-five configurations were compared per file and the maximum result was
reported without a held-out validation set. This creates selection bias. A
publication rerun needs nested evaluation or leave-one-dataset-out selection:
tune on training datasets, then evaluate the selected policy once on held-out
datasets.

## 6. Matrixless semantic sketch experiment

### 6.1 Script and question

- Script: `experiments/error_conditioned_semantic_sketch.py`
- Comparison table: `experiments/semantic_sketch_vs_matrix_comparison.csv`

The Error-Conditioned Semantic Sketch (ECSS) asks whether Buckaroo can avoid a
large row-by-vocabulary matrix while retaining useful error-focused groups.

### 6.2 Method

The prototype:

1. hashes column-aware text/category tokens into a fixed 128-dimensional signed
   sketch by default;
2. appends robust numeric features;
3. weights text by 0.65 and numeric features by 0.35;
4. caps each row at 48 tokens;
5. builds an error-aware coreset of at most 6,000 rows;
6. trains MiniBatchKMeans with default `k=8` and batch size 2,048;
7. assigns the full loaded data to learned prototypes in batches; and
8. describes and scores groups with small per-cluster summaries.

Unlike production pooled TF-IDF, sketch text tokens explicitly preserve column
context with forms such as `occupation=prof-specialty` and
`description~hybrid`.

### 6.3 Preserved comparison

| Dataset | Matrix KMeans total sec | Matrix MiniBatch total sec | Sketch total sec | Matrix KMeans top lift | Sketch top lift |
| --- | ---: | ---: | ---: | ---: | ---: |
| Adult 30k | 5.2588 | 3.2872 | 6.7228 | 3.8900 | 3.8304 |
| StackOverflow 10k | 5.4487 | 3.0897 | 5.0929 | 17.4721 | 1.9176 |
| Games 12k | 4.1239 | 1.9471 | 5.3797 | 1.1719 | 1.1553 |
| Cars 20k | 14.2303 | 10.7889 | 20.4867 | 1.0000 | 1.0000 |
| Complaints 6.9k | 4.4482 | 2.5783 | 5.2738 | 1.0000 | 1.0000 |

The sketch did not consistently outperform dense matrix MiniBatchKMeans in
these historical runs. Its main potential benefit is bounded representation
width and streaming compatibility, not demonstrated speed superiority here.

## 7. Adaptive semantic selector

### 7.1 Evidence status

- Script: `experiments/adaptive_semantic_selector.py`
- Expected output directories:
  - `experiments/adaptive_selector_outputs`
  - `experiments/adaptive_selector_outputs_multi`
- Audit result: neither output directory existed on 2026-07-15.
- Evidence level: C, implemented experiment design without preserved completed
  result set.

### 7.2 Feature spaces encoded in the script

| Feature space | Text features | Numeric weight | `min_df` | max DF ratio |
| --- | ---: | ---: | ---: | ---: |
| balanced TF-IDF | 350 | 0.75 | 2 | 0.90 |
| numeric-heavy TF-IDF | 250 | 1.25 | 2 | 0.90 |
| text-heavy TF-IDF | 500 | 0.35 | 2 | 0.95 |
| loose rich-text TF-IDF | 1,000 | 0.50 | 1 | 0.98 |
| optional SBERT | model embedding plus numeric | 0.35 | n/a | n/a |

The loose rich-text space is added only when richness score is at least 0.35.
SBERT also obeys row and richness limits.

### 7.3 Candidate algorithms

The script can test KMeans, MiniBatchKMeans, BisectingKMeans when available,
DBSCAN, Agglomerative, Birch, and optionally OPTICS. It derives three values of
`k` around the production heuristic, three DBSCAN `eps` values, several
`min_samples` values, two agglomerative distance thresholds, and three Birch
thresholds.

### 7.4 Rejection thresholds

Defaults reject a candidate when it has fewer than two non-noise clusters, no
groups after error/size filtering, too few top-group error rows, largest cluster
fraction at least 0.90, noise fraction at least 0.70, or fraction of rows in
undersized clusters at least 0.60.

### 7.5 Selector score

The implemented selector combines group score, lift, coverage, cosine
silhouette, detector-issue homogeneity, centroid tightness, cluster imbalance,
runtime, and a 50-point rejection penalty. This is an error-discovery policy and
is not a calibrated estimate of semantic correctness.

No performance claim should be made until the script is rerun with preserved
metadata and outputs.

## 8. Frontend Meta selector experiment in the product

The UI's Meta option is a much smaller selector than
`adaptive_semantic_selector.py`. It tests only five production API
configurations on 1,500 first-ID rows. Its exact score is documented in
`CURRENT_PIPELINE_METHODOLOGY.md`.

The two selectors must not be described as the same system:

- frontend Meta is deployed but narrow;
- adaptive selector is broad but experimental and lacks preserved outputs.

## 9. Current research conclusions

### 9.1 Conclusions supported as preliminary findings

- Numeric/text weighting and clustering parameters affect returned groups.
- No single tested algorithm won every file under the error-discovery objective.
- MiniBatchKMeans was generally faster than full KMeans after sharing the same
  feature-construction cost in preserved benchmark runs.
- SBERT feature creation was substantially slower than TF-IDF in preserved CPU
  runs.
- Density methods can mark many rows as noise or collapse into one dominant
  cluster depending on `eps`.
- Agglomerative distance thresholds can produce dozens or hundreds of clusters,
  creating a downstream ranking and explanation burden.
- Detector saturation makes error lift unusable as a discriminator.

### 9.2 Conclusions not supported

- "Agglomerative is the best semantic clustering algorithm."
- "Thirteen independent datasets prove generalization."
- "TF-IDF discovers ground-truth meaning."
- "SBERT is less accurate than TF-IDF."
- "The adaptive selector has been validated."
- "The current production sample represents the full table."
- "High error lift means high semantic coherence."

## 10. Required publication-grade reruns

Before these experiments become paper results:

1. Commit the exact code and dependency lock file.
2. Hash and version every input dataset.
3. Replace prefix sampling with seeded random sampling.
4. Use multiple seeds and report distributions, not one runtime/value.
5. Separate semantic quality from detector-error utility.
6. Add human cluster-coherence judgments or a dataset with known semantic
   classes.
7. Use train/held-out datasets for algorithm/parameter selection.
8. Add stability metrics such as Adjusted Rand Index across resamples.
9. Measure peak memory and end-to-end runtime on recorded hardware.
10. Preserve raw labels, sampled row IDs, configuration JSON, logs, and failures.
