# Buckaroo Current Project Update for Professor

**Date:** July 27, 2026
**Focus:** Changes made after the July 20 clustering meeting

## The 30-second version

The clustering system no longer treats every exact match as an equally useful
result. Buckaroo now gives priority to larger, semantically meaningful groups
that also contain a genuinely enriched data-quality issue. It produces
value-specific descriptions, corrects misleading detector wording, handles
similarity for open-vocabulary categories, ordinal ranges, countries, and
cities, and shows one ranked list in the UI.

The central change is:

> Buckaroo now looks for groups that mean something and contain a real quality
> problem, rather than simply returning mathematically valid clusters.

## A short script I can say to the professor

"In the previous live demo, the clustering was technically working, but many
results were tiny exact-match groups. Their descriptions were generic, and one
quality explanation incorrectly said that Country was incomplete even when the
value was present.

I changed both the representation and the result-selection layer. Eligible
open-vocabulary categories can now use SBERT similarity, numeric ranges such as
age buckets are interpreted as ordered values, and country or city names can use
real geographic distance. The clustering decision is also protected from large
duplicate populations by making decisions on distinct feature rows and then
mapping the labels back to all original rows.

At the output stage, Buckaroo now removes groups with no enriched quality issue,
describes groups using their actual values, and prioritizes semantic-quality
clusters over exact duplicate groups. The UI shows one ranked list with the
semantic cohort, quality pattern, issue count, evidence, representative rows,
and boundary examples.

These changes are internally tested, but I am not claiming that the groups are
human-useful or superior until the blinded human benchmark is completed."

## What changed, in detail

### 1. Group descriptions now name the actual values

**Before**

> Rows with the same normalized non-key values.

or:

> Rows matching on Gender, Continent, and Country.

Those sentences did not distinguish one group from another.

**Now**

> Rows where Gender is Male, Continent is AS, and Country is Israel.

Each near-duplicate description now contains both the field name and its shared
value. If many fields match, the headline names up to four and keeps the full
evidence in the expanded details.

**Why it matters**

The user can immediately understand what makes this group different. Two
different groups should no longer receive the same generic description.

**Implementation**

- `app/server_utils/multi_view_grouping.py:2314`
- `app/server_utils/multi_view_grouping.py:3252`

### 2. The misleading "incomplete Country" result was fixed

The legacy `incomplete` detector label actually represents a rare categorical
value, not a missing value. In the live demo, a group whose Country value was
present in every row was described as having "incomplete values in Country."

Buckaroo now translates that legacy signal to:

> rare category values in Country

It also applies a tautology guard. If a group is defined by one constant,
present value, Buckaroo does not claim that the same value is an unusual quality
pattern merely because it is concentrated inside that group.

**Why it matters**

The explanation now describes what the detector actually measured. It avoids
calling a valid value missing and avoids circular evidence.

**Implementation**

- `app/server_utils/multi_view_grouping.py:3122`
- `app/server_utils/multi_view_grouping.py:3162`
- `app/server_utils/multi_view_grouping.py:3230`

### 3. Semantically clean but error-free clusters are no longer shown

The professor's criticism was correct: in a data-quality repair workflow, a
coherent group with no enriched quality issue is not a useful repair target.

Buckaroo now applies a hard quality-signal gate before final acceptance:

```python
candidates = [group for group in candidates if group.hasQualitySignal]
```

A group must contain a quality issue whose rate is higher inside the group than
in the full sample. A merely different or rare semantic segment is not enough.

**Why it matters**

The output is now aimed at repairable findings, not general-purpose market
segmentation.

**Implementation**

- `app/server_utils/multi_view_grouping.py:308`

### 4. Meaning and quality are scored together

Buckaroo now computes an analyst signal:

```text
analyst signal =
sqrt(semantic strength * enriched quality strength)
```

The semantic side uses the strongest semantic evidence. The quality side uses
the strongest genuinely enriched quality finding.

If either half is missing, this signal is zero. A zero does not crash or
invalidate the group; it simply prevents that group from being favored as an
actionable finding.

**Why use a geometric mean?**

A high score on one side cannot hide a zero on the other side. This matches the
research goal: meaning plus a real issue, not meaning or an issue alone.

**Implementation**

- `app/server_utils/multi_view_grouping.py:3663`

### 5. The UI now shows one result list

The separate "Semantic-quality" and "Near-duplicate" filter tabs were removed.
The panel now shows one list named **Useful row groups**.

Every card can show:

- semantic cohort;
- quality pattern;
- total rows and percentage of sample;
- number of rows with a detected issue;
- semantic rank;
- stability;
- cohesion;
- profiler confidence;
- important supporting fields;
- representative rows;
- contradictory or boundary rows;
- caveats; and
- a Select rows action.

The exact-match origin is still retained as provenance, but it is no longer a
separate user workflow.

**Implementation**

- `ui/src/panels/SemanticGroupsModal.jsx`

### 6. The final ranking now favors similarity over exact equality

Current code uses this sort order:

```text
1. result tier
   semantic-quality clusters before exact near-duplicate groups
2. semanticScore
3. utilityScore
```

`semanticScore` combines empirical percentile ranks for:

- description specificity;
- the analyst signal;
- distinctiveness; and
- explainability.

`utilityScore` summarizes structural evidence such as stability, cohesion,
profile confidence, and non-trivial coverage. It breaks ties after semantic
meaning.

**Why the hard result tier was added**

Exact duplicate groups trivially have maximum specificity because every
included field is equal. Without the tier, tiny exact-match groups can outrank
larger clusters that represent genuine similarity. The tier prevents exact
equality from dominating semantic similarity.

**Important research caveat**

This is a deliberate policy choice, not a human-validated truth. The benchmark
must test whether users actually prefer this ordering.

**Implementation**

- `app/server_utils/multi_view_grouping.py:3847`

### 7. Eligible open-vocabulary categories can use SBERT similarity

Previously, categories were usually compared by exact equality:

```text
India == India
India != Pakistan
India != Australia
```

That does not say whether two different values are semantically close.

Buckaroo can now replace exact-match tokens with SBERT embeddings for eligible
open-vocabulary categorical columns. The gate uses:

- the profiler role; and
- a dataset-adaptive cardinality split.

Small enumerated categories such as binary fields remain exact-match values.
Free-text SBERT is separate and opt-in; TF-IDF remains the default free-text
path.

**Why it matters**

This directly addresses the professor's "equal is not the same as similar"
criticism without applying an expensive language model to every column.

**Implementation**

- `app/server_utils/semantic_embeddings.py`
- `app/server_utils/multi_view_grouping.py`

### 8. Ordered category ranges now have real distance

Values such as:

- `18-24 years old`;
- `25-34 years old`;
- `0-2 years`; and
- `30 or more years`

are no longer treated as unrelated labels. Buckaroo parses a range midpoint or
stated bound and routes the result through robust numeric scaling.

The eligibility rule is strict:

- every distinct present value must parse;
- at least two parsed levels must exist; and
- at least one value must repeat.

That prevents IDs such as `Job 14` from being mistaken for ordinal scales.

**Current limitation**

Purely verbal orderings such as `Bachelor's`, `Master's`, and `PhD` are not yet
ordered because that would require external domain reference data.

**Implementation**

- `app/server_utils/multi_view_grouping.py:1206`

### 9. Countries and cities now use geographic distance

Location-name columns no longer have to rely only on equality.

For eligible country names, Buckaroo resolves each value to an offline
capital-city coordinate and uses spherical distance. For city names, it resolves
name collisions using a companion country or region column when available.
Population is only a last-resort fallback.

Example:

- `Paris + France` resolves to Paris, France;
- `Paris + United States` resolves to Paris, Texas.

Direct latitude and longitude columns continue to use unit-sphere coordinates,
which handle longitude wraparound correctly.

**Why not use SBERT for geographic distance?**

SBERT captures linguistic and cultural association, not physical distance.
Geography therefore uses an explicit geographic reference and spherical
geometry.

**Implementation**

- `app/server_utils/geography_reference.py`
- `app/server_utils/multi_view_grouping.py:1503`

### 10. Duplicate-heavy data no longer controls cluster selection as strongly

Previously, repeated identical rows entered the candidate-selection matrix with
their full multiplicity. A large duplicate majority could distort:

- cluster-count selection;
- DBSCAN neighborhood distances;
- balance;
- distinctiveness; and
- whether a smaller real group was discovered.

Buckaroo now makes clustering decisions using distinct feature rows. After the
partition is selected, labels are expanded back to every original row.

**Important clarification**

No original row is deleted. Deduplication is used only while deciding the
partition.

**Current limitation**

This reduces duplicate crowd-out but does not fully solve every case with
several small minority clusters competing against one dominant population.

### 11. Adaptive thresholds remain dataset-driven

The current pipeline avoids universal semantic cutoffs where possible:

- profile-confidence cutoffs use natural breaks in observed confidence;
- group support uses the observed repeated-value distribution;
- candidate `k` scales with current sample complexity;
- DBSCAN epsilon comes from the observed neighbor-distance knee;
- acceptance cutoffs use natural breaks;
- dominant coverage uses a robust upper fence; and
- overlap removal uses the observed overlap distribution.

The 10,000-row sample ceiling and 256 MiB agglomerative-memory ceiling are
declared engineering budgets, not claims about semantic correctness.

## Evidence currently available

The methodology document records the following verification state as of
July 25:

- **88 of 88 clustering-related tests passing** across 10 test files;
- **269 of 269 backend unit tests passing**; and
- **134 audited clustering decisions across 15 files** passing the threshold
  documentation audit.

During the current code review, the eight-suite core subset was independently
rerun and passed **80 of 80**.

These tests support claims about:

- deterministic behavior;
- routing invariants;
- threshold logic;
- description generation;
- quality-gate behavior;
- SBERT eligibility;
- ordinal parsing;
- geography resolution;
- duplicate-label expansion; and
- fallback behavior.

They do **not** prove that a human finds the groups meaningful or useful.

## What has not changed

These core ideas were already implemented before the latest meeting:

- one feature vector remains associated with each row;
- semantic and quality blocks are concatenated horizontally;
- TF-IDF is only one optional text block, not one document for the whole table;
- identifiers and primary-key candidates are excluded from semantic distance;
- numeric values use robust scaling;
- timestamps use lifecycle and duration features;
- candidate algorithms are compared on one combined representation; and
- explanations expose evidence instead of only returning a cluster label.

## Claims I can safely make

I can say:

- "The implementation now distinguishes semantic similarity from exact
  duplicate matching."
- "Groups without an enriched quality issue are filtered from the repair
  workflow."
- "The Country quality explanation bug found in the live demo is covered by a
  regression test."
- "Open-vocabulary categories, ordinal ranges, countries, and cities now have
  more appropriate similarity representations."
- "The UI shows one ranked list with grounded values and evidence."
- "The mechanism is internally tested and reproducible."

## Claims I should not make yet

I should **not** say:

- "These are the best possible clusters."
- "The groups are proven useful to analysts."
- "Buckaroo is more accurate than every other clustering system."
- "The semantic rank is a probability of correctness."
- "SBERT solves semantic understanding for every data type."
- "The system universally generalizes to unseen domains."
- "Adaptive thresholds guarantee meaningful clusters."

Those claims require the frozen human benchmark, held-out datasets, and a
comparison against controlled baselines.

## Questions the professor may ask

### Is everything being collapsed into one TF-IDF vector?

No. The final representation has one row vector per original data row. TF-IDF
is only one possible block for free text. Numeric, categorical, ordinal,
temporal, geographic, embedding, and quality features have separate
transformations before their blocks are concatenated.

### Why compare multiple clustering algorithms if there is one matrix?

The representation and the algorithm are separate decisions. The same combined
matrix is supplied to K-means, eligible agglomerative clustering, and adaptive
DBSCAN. The system compares their repeated-run evidence instead of assigning an
algorithm based on data type.

### Why are duplicate groups still present?

Exact duplicates are useful as record-linkage evidence, but they are advisory
and secondary. They remain visible with provenance, but semantic-quality
clusters are ranked above them.

### Why require a quality issue?

This UI is for data repair, not general segmentation. A group must therefore
help identify a concentrated problem. Pure semantic segmentation can be a
separate future mode.

### Is semantic rank a confidence score?

No. It is a relative rank within the current candidate pool. It summarizes
specificity, analyst signal, distinctiveness, and explainability. It is not a
calibrated probability.

### Do human labels affect production decisions?

No. The current adaptive policy uses dataset values, profile evidence, and
repeated clustering behavior. Human labels are reserved for evaluation, not
fed into the production decision.

### What is the biggest unresolved scientific question?

Whether human reviewers agree that the semantic-first ordering is more useful
than alternatives. That is the purpose of the frozen real plus semi-synthetic
benchmark.

## Recommended live demo

1. Load a dataset with semantic categories and real quality signals.
2. Open **Useful row groups**.
3. Point out that there is one list rather than separate result-type tabs.
4. Open one large semantic-quality group.
5. Show the actual values used in the description.
6. Show the quality rate inside the group versus the full sample.
7. Show representative and boundary rows.
8. Select the rows and show that the group becomes actionable in Buckaroo.
9. Briefly show an exact duplicate group lower in the list and explain why it
   remains useful but secondary.

## Internal cleanup before publication or handoff

1. **Commit the implementation.** Most clustering, profiler, experiment, and UI
   changes are currently present locally but remain uncommitted.
2. **Align ranking documentation and API metadata with current code.** The
   current code's true final sort key is:

   ```text
   (semantic-quality tier above duplicates, semanticScore, utilityScore)
   ```

   Some older wording describes only `(semanticScore, utilityScore)`.
3. **Run and archive the complete benchmark.** Human usefulness is still the
   main unvalidated claim.
4. **Record clustering runtime on multiple dataset sizes.** The professor
   suggested roughly 10-15 seconds as a potentially acceptable interactive
   delay, but the current hardware/runtime evidence must be measured.
5. **Test selected-column clustering.** The current production path generally
   profiles and routes all eligible columns. The meeting raised whether the
   user should be able to focus grouping on selected columns.

## Current code and methodology references

- `app/server_utils/multi_view_grouping.py`
- `app/server_utils/adaptive_grouping_policy.py`
- `app/server_utils/semantic_embeddings.py`
- `app/server_utils/geography_reference.py`
- `ui/src/panels/SemanticGroupsModal.jsx`
- `docs/clustering/MULTI_VIEW_CLUSTERING_METHODOLOGY.md`
- `docs/clustering/ADAPTIVE_DECISION_POLICY.md`
- `docs/clustering/RANKING_AND_SIMILARITY_POSITION.md`
- `tests/unit/test_multi_view_grouping.py`
- `tests/unit/test_semantic_embeddings.py`
- `tests/unit/test_geography_reference.py`
