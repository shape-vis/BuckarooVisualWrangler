# Reproducible Experiment Entrypoints

The files in this directory evaluate Buckaroo; they are not imported by UI
components. Generated results belong in an ignored output directory.

## Canonical experiment families

| Question | Primary driver |
| --- | --- |
| How does profiling change with sample size and repeated random draws? | `run_multi_dataset_sampling_profiler_experiment.py` |
| How do noise and early-stopping policies trade accuracy for runtime? | `evaluate_early_stopping_noise_policy_tradeoffs.py` |
| Which profiler feature prevents which failure? | `run_profiler_ablation_study.py` |
| How do geography safeguards change false-key behavior? | `compare_geography_safeguard_experiments.py` |
| How do profiler variants compare with exact UCC/FD-style baselines? | `run_profiler_variant_comparison.py` and `run_profiler_ladder_experiment.py` |
| Are sampling decisions stable without human labels? | `run_benchmark_free_sampling_stability.py` |
| How are clustering algorithms/features compared? | `semantic_clustering_benchmark.py` and `semantic_parameter_sweeps.py` |
| How is the semantic-quality benchmark constructed? | `build_semantic_quality_benchmark.py` |
| Where do fixed thresholds remain? | `audit_clustering_thresholds.py` |

## Minimum reproducibility record

Every run should save:

- dataset path or ID and SHA-256 hash;
- row/column shape and sampling policy;
- random seed and iteration number;
- profiler/grouping strategy and feature flags;
- runtime boundary (profiling only or end to end);
- prediction/group assignment outputs; and
- metric definition and benchmark review status.

`reproducibility.py` captures environment and input hashes. Human-label accuracy
must not be reported unless benchmark rows are marked reviewed; provisional AI
agreement must remain explicitly labeled as provisional.

## Methodology guardrails

- Draw rows without replacement and use deterministic seeds.
- Reuse one random permutation for nested sample sizes so a 100-row sample is
  the prefix of the corresponding 500-row sample.
- Keep injected-noise cells nested across 5%, 10%, and 20% conditions.
- Compare early-stopped predictions with both the full pass and the reviewed
  benchmark; agreement with the full pass alone is not semantic accuracy.
- Label ablations as controlled feature-removal experiments, not as standalone
  conclusions.
- Fit data-driven thresholds on the development partition and keep evaluation
  datasets held out from policy selection.
- Report failed and skipped runs. Do not silently remove them from averages.

## Output convention

Write each run to a new directory beneath `outputs/`. Keep a row-level run
table in addition to aggregate summaries. At minimum, the run table should
contain:

```text
dataset_id, dataset_sha256, profiler, sample_size, iteration, seed,
runtime_seconds, prediction, reference_label, warning, failure_reason
```

Aggregate tables are derived artifacts. The row-level table and configuration
are the audit trail reviewers need to recompute a reported figure.

## Example

```powershell
python experiments/run_multi_dataset_sampling_profiler_experiment.py `
  --dataset-dir provided_datasets `
  --sample-sizes 100,500,1000,5000,10000 `
  --iterations 10 `
  --out-dir outputs/sampling_run
```

Use `--help` on a driver before running it because large-dataset and optional
embedding experiments have different resource requirements.

Install workbook-generation dependencies with:

```powershell
python -m pip install -r requirements-experiments.txt
```

`run_dataprofiler_order_items.py` and `deequ_order_items.scala` are external
baseline adapters. Their heavyweight runtimes are intentionally not installed
with the Buckaroo application.
