# Hard-Coded Threshold Audit

Audit date: 2026-07-19
Branch inspected: `codex/profiler-guided-clustering`
Primary implementation: `app/server_utils/multi_view_grouping.py`

## 1. Purpose

This audit asks which numbers can change the groups Buckaroo discovers, ranks,
or displays. It separates:

1. semantic heuristics that require evidence;
2. dataset-derived decisions;
3. statistical/domain constants;
4. reproducibility seeds;
5. resource and payload safeguards;
6. UI display limits; and
7. historical or compatibility-only settings.

The inventory covers the current combined semantic-quality implementation, API/UI request
path, upstream profiler, quality detectors, compatibility baseline, and
historical experiments.

## 2. Reproducible artifacts

- `outputs/clustering_threshold_audit_20260719/hard_coded_threshold_inventory.csv`
- `outputs/clustering_threshold_audit_20260719/hard_coded_threshold_inventory.json`
- `outputs/clustering_threshold_audit_20260719/hard_coded_threshold_inventory.md`
- `outputs/clustering_threshold_audit_20260719/threshold_audit_summary.csv`
- `outputs/clustering_threshold_audit_20260719/numeric_literal_scan.csv`

Regenerate and validate:

```powershell
python experiments/audit_clustering_thresholds.py
python experiments/audit_clustering_thresholds.py --check
```

Every current record has a live source anchor. The check fails when a source
fragment disappears, which prevents stale line references from entering the
research record.

## 3. Current snapshot

| Finding | Count |
| --- | ---: |
| Curated decisions across the full research scope | 134 |
| Files with curated decisions | 15 |
| Current production multi-view decisions | 37 |
| Dataset-adaptive decisions across the audited scope | 27 |
| Critical sensitivity risks across all scopes | 36 |
| Known duplicated/default-drift records | 0 |
| Numeric-literal lines screened | 1,358 |

The remaining critical risks are not all in the new multi-view selector.
Several belong to the upstream profiler, quality detectors, compatibility
baseline, or old experiment grids. The CSV must be filtered by `scope` before a
claim is made about the production clustering policy.

## 4. Remediation completed

| Former production rule | Current rule |
| --- | --- |
| Default sample = 3,000 rows | Full data under a separately declared 10,000-row resource cap |
| Minimum group = 8 rows | Natural break in observed repeated-value support |
| Confidence gate = 0.55 | Natural break in current profiler confidences |
| Fixed per-view column caps | All profiler-approved columns enter their views |
| Numeric clip = 4 robust units | Observed robust tail fence |
| Text budgets = 80/20 tokens | Per-column observed token-length fence |
| First six datetime pairs | Stronger observed duration-evidence class under a sample-scaled budget |
| First coordinate pair | All name-matched coordinate pairs |
| K capped at 8 | Dataset-scaled K candidate range |
| Algorithm chosen from view/type and row count | Common candidate comparison using repeated-run diagnostics |
| DBSCAN 70th percentile plus fixed bounds | K-distance knee |
| Perturbation sigma = `1e-4` | Local nearest-neighbor scale divided by square root of feature count |
| Duplicate rounding = 2 decimals | Freedman-Diaconis width |
| Fixed utility weights | Median empirical percentile within each view |
| Stability >= 0.45 and utility >= 0.52 | Natural breaks in current candidates |
| Jaccard >= 0.92 | Natural break in observed same-view overlaps |
| At most three groups per view | Round-robin interleaving of available views |
| UI supplied sample/group defaults | Multi-view defaults omitted; explicit overrides remain for experiments |

The old audit inventory is preserved in Git history and in the historical
function `pre_adaptive_production_multiview_items()` for comparison. It is not
included in the current generated inventory.

## 5. Fixed values that remain in production

| Value | Classification | Justification |
| --- | --- | --- |
| Sample seed `20260717` | Reproducibility | Same table produces the same random sample |
| K-means seeds `42`, `137` | Reproducibility | Repeatable stability comparison |
| Two-row group floor | Structural | A repeated group requires at least two rows |
| 10,000 rows | Resource budget | Bounds interactive clustering cost |
| 512 tokens | Resource budget | Bounds pathological text-cell cost |
| 256 MiB pairwise estimate | Resource budget | Prevents agglomerative memory failure |
| 2,000 row IDs | Payload budget | Protects API/browser memory |
| 12/7/24 cycles | Domain constants | Calendar definitions |
| 86,400 seconds/day | Unit conversion | Physical definition |
| Tukey multiplier 1.5 | Statistical convention | Robust exploratory fence, explicitly audited |

These values need performance, stress, or usability evidence. They should not
be presented as semantically optimal thresholds.

## 6. Upstream risks still open

The clustering selector consumes profiler roles and quality-detector outputs.
Those upstream components still contain fixed role, confidence, rarity, type,
and anomaly rules. High-priority examples remain:

- profiler role cutoffs and confidence-combination weights;
- profiler early-stop confidence and candidate-gap rules;
- detector type-confidence and rare-category rules;
- anomaly method/transform choices; and
- assumptions that the first column should be skipped by detectors.

These do not justify reintroducing fixed clustering thresholds. They are a
separate calibration and ablation agenda recorded in the generated inventory.

## 7. Validation boundary

No human labels are required to calculate the new adaptive rules. Unit tests can
prove that the rules respond to different distributions and that selected
partitions are stable or separated from alternatives.

Human labels are still required to prove that the output is semantically
correct or useful. The paper should keep implementation and external validation
separate:

1. derive decisions only from the current training/input dataset;
2. freeze held-out human judgments;
3. evaluate on unseen datasets without tuning on their labels; and
4. report stable but semantically wrong failures rather than hiding them.

## 8. Interpretation

The refactor does not claim that every fixed number is bad. It removes arbitrary
cross-dataset semantic cutoffs from the active multi-view policy and makes the
remaining fixed values explicit. This is a stronger research position than
calling every number "adaptive," because it states which decisions adapt, which
do not, and what kind of evidence each still needs.
