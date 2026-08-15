# Dataset-Adaptive Clustering Decision Policy

## Short answer about human labels

Human labels are **not required to implement or execute** this adaptive policy.
Every production decision is derived from the current dataset's values,
profiler confidences, candidate partitions, or repeated-run behavior.

Human labels are still required later to support claims such as:

- "the groups are semantically correct";
- "the descriptions are useful to users";
- "the selected algorithm is better than alternatives"; or
- "an 80% confidence score means about 80% correctness."

The distinction is important: a grouping can be stable and internally coherent
while still being meaningless to a person.

## What changed

| Earlier fixed decision | Current dataset-driven decision |
| --- | --- |
| Sample exactly 3,000 rows | Read all rows up to a separately declared 10,000-row resource cap |
| Minimum group size = 8 | Natural break in repeated value frequencies, with a two-row structural floor |
| Profiler confidence >= 0.55 | Maximum between-class variance split in observed profile confidences |
| At most 20/10/6 columns by view | Route every profiler-approved column into a role-specific block, then combine the blocks |
| Numeric clipping at four robust units | Tukey upper fence of the observed standardized tail |
| Fixed text token budgets | Robust upper fence of each text column's observed token counts |
| First six datetime pairs | Score every valid pair; retain the stronger observed score class under a sample-scaled budget |
| Use one coordinate pair | Match every latitude/longitude pair by column-name context |
| Fixed `k <= 8` formula | Evaluate a sample-scaled range of candidate `k` values |
| Algorithm chosen by view/type | Compare K-means, eligible agglomerative, and adaptive DBSCAN once on the combined matrix |
| DBSCAN 70th-percentile epsilon with fixed bounds | Knee of the observed k-neighbor distance curve |
| Fixed utility weights | Median empirical percentile across evidence dimensions within the combined result family |
| Utility >= 0.52 and stability >= 0.45 | Natural breaks in the current candidate distributions |
| Jaccard >= 0.92 means duplicate group | Natural break in observed overlaps |
| Three groups per view | Data-derived acceptance over one semantic-quality result family |
| Semantic-quality and near-duplicate groups ranked as two separate result families | Merged into one candidate list, ranked once (2026-07-20) |
| Cluster geometry (`utilityScore`) is the final sort key | `semanticScore` — a percentile blend of description specificity, analyst signal, distinctiveness, explainability — is the primary sort key; `utilityScore` only breaks ties (2026-07-20) |
| Group "usefulness" has no notion of combined meaning + issue | Analyst signal: geometric mean of semantic strength and enriched-quality strength, 0 if either half is missing (2026-07-20) |
| Semantically coherent but error-free clusters are shown (just ranked lower) | Hard gate: a group with no enriched data-quality issue is dropped entirely before ranking — this is a data-quality tool (2026-07-20) |
| Near-duplicate descriptions name only the matched field, e.g. "Gender, Continent, Country" | Name the matched field **and its value**, e.g. "Gender is Male, Continent is AS, Country is Israel" (2026-07-20) |
| Geography description scored as a raw great-circle angle (radians) | Scored as an offset-over-spread effect size, the same scale every other field family uses (2026-07-20) |
| Open-vocabulary categorical columns always exact-match tokenized | SBERT-embedded instead, gated by profiler role + adaptive cardinality split; on by default via `strategy=semantic_quality` (2026-07-21) |
| Group description for a semantically-embedded column falls back to exact-match concentration (or goes silent if no value dominates) | A dedicated candidate describes semantic cohesion — group's values are close together in embedding space relative to the column's own baseline spread — for embedding-routed columns with 2+ distinct present values (2026-07-21) |
| `name_tokens()` lowercases a column name before splitting on non-alphanumeric characters, so a camelCase/PascalCase name like `DevType` never splits into `dev`/`type` and permanently loses its 10-point name-hint confidence bonus | Split on camelCase/PascalCase boundaries (case-sensitive) before lowercasing, so `DevType` → `{"dev","type"}` and `RaceEthnicity` → `{"race","ethnicity"}` (2026-07-21) |
| Free-text columns always use TF-IDF | Eligible `free_text`-role columns can use SBERT embeddings instead of TF-IDF (replace, not add) — opt-in via `strategy=semantic_quality_free_text_embeddings`, off by default, unlike the categorical path (2026-07-21) |
| Bucketed-range categorical columns ("18-24 years old", "0-2 years") treated as pure equality — "18-24" is no closer to "25-34" than to "65+" | Parsed to a representative number (midpoint of a range, or the stated bound) and given genuine robust-scaled numeric distance instead of one-hot equality — always on, no flag, deterministic arithmetic with a strict eligibility gate (2026-07-21) |
| A column below the adaptive profiler-confidence cutoff is always excluded from clustering, even one with much stronger, column-specific evidence the confidence score never sees | A column that independently clears `ordinal_eligible_columns()`'s own strict per-column evidence bypasses the general cutoff for ordinal purposes — narrow exemption, not a blanket relaxation (2026-07-21) |
| Location-name columns ("Country", no paired lat/long) treated as pure equality — "India" no closer to "Pakistan" than to "Australia" | Resolved to a real capital-city coordinate via a static, offline reference table (geonamescache + pycountry) and given genuine spherical distance through the same machinery already built for explicit lat/long columns — always on, no flag, countries only for this pass (2026-07-21) |
| K-means/DBSCAN/Agglomerative decide k and eps from the full row-multiplicity matrix, so a numerically-dominant near-duplicate-dense majority can distort distinctiveness, balance, and DBSCAN's density estimate enough to bury a smaller genuine cluster | Every clustering decision is made on the matrix's distinct rows; labels are expanded back to one entry per original row afterward — unconditional, no duplication-density threshold needed, since it is a no-op wherever no duplication exists (2026-07-21) |
| A column's profiler-confidence reliability term was `min()`'d against a dataset-wide worst-case bound (an assumed 50/50 split derived from sample size alone), identical for every column regardless of how clean that specific column's own values are | Reliability now uses the column's own margin-derived value directly (`reliability_from_margin(relevant_interval["margin"])`) — already column-aware and already accounts for sample-size uncertainty, so the redundant, more-pessimistic dataset-wide floor was simply removed, not replaced (2026-07-21) |
| City-level location-name columns ("City", no paired lat/long) fell back to pure equality — city-level matching was explicitly out of scope for the first geography pass, since name collisions ("Springfield", "San Jose") have no country-level analog | Resolved to a real city coordinate via the same offline reference table, disambiguated context-first: a companion country/region column's value for that row narrows the match; population is a last resort only when no context column exists or the hint doesn't match any candidate — always on, no flag, tried only after the (unambiguous) country-level pass fails (2026-07-25) |

## Dataset-derived methods

### Natural-break threshold

For a one-dimensional set of scores, Buckaroo evaluates every gap between
observed values and chooses the split with maximum between-class variance. This
is an Otsu-style objective:

```python
score = lower_weight * upper_weight * (lower_mean - upper_mean) ** 2
```

It is used for profiler-confidence routing, candidate quality, group support,
duration-pair evidence, duplicate completeness, and overlap removal. The
threshold is therefore a property of this dataset's evidence, not a universal
number copied across datasets.

### Robust scaling and fences

Numeric columns use median and interquartile range (IQR). Standardized tails,
candidate coverage, and token lengths use a Tukey upper fence:

```text
upper fence = Q3 + 1.5 * IQR
```

The `1.5` multiplier is a documented statistical convention, not a learned
semantic threshold. It remains in the audit as a statistical-method choice and
should be stress-tested on heavy-tailed data.

### Adaptive candidate `k`

The candidate range is:

```text
2 .. min(unique feature rows,
         rows / data-derived minimum support,
         ceil(log2(unique feature rows)))
```

This lets larger and more varied datasets consider more clusters without
allowing an exhaustive, unbounded search in the interactive application.

### Repeated-run partition evidence

Every approximate partition is assessed using:

- stability under a second initialization or data-scaled perturbation;
- within-group coherence;
- separation from the nearest other group;
- entropy balance across cluster sizes; and
- fraction of rows assigned to non-noise clusters.

The geometric mean is used so one near-zero property cannot be hidden by high
values on the others. No hand-set component weights are used.

### Candidate-score separation

Buckaroo asks whether the top candidate is in a naturally separated score
class. If it is not, the system retains the simpler deterministic K-means
partition and exposes the ambiguity in diagnostics. This is an internal
abstention rule, not proof that K-means is semantically correct.
With only two candidates, Buckaroo reports the comparison as ambiguous because
two unequal points alone cannot establish a high-score and low-score class.

### Empirical ranking within the combined result family

Business, text, lifecycle, and geography are preprocessing blocks inside one
semantic-quality representation, not separate candidate families. Buckaroo
converts each group-evidence dimension to an empirical percentile within that
combined family, then takes the median percentile. This produces `utilityScore`
— cluster geometry only, no semantic-versus-quality distinction yet.

### Analyst signal — meaning and a real issue, combined (2026-07-20)

Neither "the group has errors" nor "the group is semantically clean" alone was
treated as the ranking target a data analyst actually wants: a coherent,
nameable segment that *also* carries a real quality issue. `analyst_signal_strength`
computes this per group as a geometric mean:

```text
semantic = mean(top 2 non-quality supporting-field strengths)
quality  = max(strength for quality fields where enriched)
signal   = sqrt(semantic * quality)
```

Because it is a geometric mean, a group needs both halves present to score
above zero: semantically clean with no issue scores 0 here (not penalized on
other dimensions), an issue that isn't genuinely enriched also scores 0, and
only the combination of a real story and a real issue scores positively. All
four qualitative cases were verified directly against the function — with
hand-built inputs, not just the happy path — before being trusted in the
ranking pipeline, and are locked in as a permanent regression test.

### Quality-signal gate — drop error-free clusters entirely (2026-07-20)

This is a **hard filter, not an adaptive threshold**, and it runs before all the
ranking machinery below. Buckaroo is a data-quality tool: a semantically
coherent cluster that carries no *enriched* data-quality issue is not surfaced
at all. Each candidate group records `hasQualitySignal` (true only when a
quality field's in-group incidence is genuinely enriched over the full-sample
baseline); groups where it is false are removed from the candidate list before
`select_useful_candidates`. The response reports `qualitySignalRequired: true`
and `groupsDroppedWithoutQualitySignal: N`.

Decision context: this was asked directly by the advisor ("if you don't have
data-quality issues, then why would you need that cluster?") and confirmed as
the desired behavior. It supersedes the earlier softer stance where such
clusters were only ranked lower via a zeroed analyst signal. Honest
consequence: a dataset with no detected quality issues anywhere returns zero
groups and shows the empty state — intended, because a data-quality tool
surfacing error-free clusters is noise.

### Semantic-first ranking across the merged candidate list (2026-07-20)

Clustered (`semantic_quality`) and near-duplicate (`duplicates`) groups used to
be two separate result families, each with its own round-robin interleaving
into the UI panel. A direct challenge to this design — "there shouldn't be a
separate near-duplicate category, and semantic meaning should dominate the
ranking" — led to two changes, made explicitly rather than defaulted into:

1. **Merge.** Every candidate group, regardless of origin, enters one list
   before ranking. The `view` field is retained per group for provenance
   (shown as a small UI badge) but no longer determines a separate queue.
2. **Semantic-first sort.** A new `semanticScore` — median of empirical
   percentiles for description specificity, analyst signal, distinctiveness,
   and explainability, computed across the *entire merged list* so clustered
   and near-duplicate groups are ranked on the same normalized scale — becomes
   the primary sort key. The final order is the tuple
   `(semanticScore, utilityScore)`: `utilityScore` (cluster geometry) only
   breaks ties between equally-meaningful groups.

This is a **lexicographic priority, not a hand-tuned weighted sum** — no fixed
numeric weight was introduced inside either score. The exception is which
family of evidence is consulted first, and that is a deliberate, documented
departure from this project's own "no dominant signal" position, made on
purpose rather than left as an undocumented disagreement between the code and
these docs.

**Open risk, not yet tested:** exact near-duplicate matches always score
`strength = 1.0` (maximum specificity), so on a dataset with much higher
duplicate density than the ones used during this change, near-duplicate groups
could plausibly crowd out clustered semantic-quality groups near the top of the
merged list. This has not been observed, but it also has not been checked
against a duplicate-dense dataset.

### SBERT categorical embeddings, wired into clustering and descriptions (2026-07-21)

Two separate decisions, made in sequence:

1. **Clustering matrix.** Open-vocabulary categorical columns (job titles,
   unstructured business categories) that clear the role + adaptive
   cardinality gate in `embedding_eligible_columns()` are embedded with
   `sentence-transformers` (`all-MiniLM-L6-v2`) instead of exact-match
   tokenized, in the business view's feature matrix. Originally shipped as an
   opt-in strategy value (`semantic_quality_embeddings`) pending a benchmark
   comparison; on direct instruction ("I want it wired into the default
   semantic_quality strategy") this became the default path — the request
   for a formal before/after benchmark was explicitly not made, so this is a
   product decision, not a validated improvement, and is recorded as such.
   Still self-limiting: the two dataset-derived gates mean it is a no-op on
   any dataset without open-vocabulary categorical columns.
2. **Description gap, found by direct user challenge.** Wiring the embeddings
   into clustering did not wire them into *descriptions* — a real bug, not a
   scope choice: `build_view_matrix` set `embeddingColumns` /
   `embeddingValuesByColumn` on its per-block feature info, but
   `build_semantic_quality_matrix`'s block-merge loop dropped both keys
   before they reached the description-building phase, so even a group
   clustered by embedding similarity was described using the old exact-match
   concentration candidate (which requires one dominant repeated value and
   goes silent otherwise). Fixed by propagating the two keys through the
   merge and adding `embedding_semantic_description_candidate()`, scored the
   same way as every other candidate: the group's cohesion in embedding space
   (mean cosine similarity of its distinct values to their centroid) above
   the column's own baseline cohesion (same measure over the full sample's
   vocabulary) — not a hardcoded similarity threshold. Verified against the
   real model, not just a test double: a synthetic Back-end/Front-end/
   Full-stack developer group produced "job title values that mean the same
   thing, such as Back-end developer, Front-end developer, and Full-stack
   developer" (cohesion 0.91 vs baseline 0.72).

### `name_tokens()` camelCase/PascalCase fix (2026-07-21)

Found by asking why SBERT embeddings stayed inactive on the live
StackOverflow demo even after being wired into the default path. Traced
`score_profile_confidence()` directly (not guessed) on the loaded table and
found `DevType` (0.814), `RaceEthnicity` (0.826), and 5 similar columns
scoring just under the dataset's adaptive confidence cutoff (0.8595), while
`Gender` (0.926) — same role, same near-maximal cardinality evidence — scored
0.10 higher purely from a categorical-role name-hint bonus.

Root cause: `name_tokens()` lowercased a column name *before* splitting it
into words with `re.findall(r"[a-z0-9]+", ...)`. Lowercasing erases the only
signal camelCase/PascalCase names carry — the case transition — so `DevType`
became one fused token, `"devtype"`, which cannot match the hint keyword
`"type"` even though the column name plainly contains it. Same for
`RaceEthnicity` → `"raceethnicity"`, missing both `"race"` and `"ethnicity"`.
This is a general profiler bug, not specific to embeddings: it silently
costs any camelCase/PascalCase column a real 10-point confidence bonus,
across every role (identifier, measurement, geography, free-text), on any
dataset with that naming convention — common in real-world exports.

Fixed by inserting a boundary before an uppercase letter that follows a
lowercase/digit, and before a capitalized word that follows a run of
uppercase letters (acronym handling), before lowercasing and splitting.
`name_tokens("DevType")` now returns `{"dev", "type"}`.

**Verified against the real, live-loaded StackOverflow table, not a
synthetic case:**

| Column | Confidence before | Confidence after |
| --- | --- | --- |
| DevType | 0.814 | 0.914 |
| RaceEthnicity | 0.826 | 0.926 |
| ConvertedSalary | 0.834 | 0.934 (measurement hint, same bug) |

3 of 17 previously held-back columns flipped above the cutoff on this
dataset (14 held back now). `DevType` cleared both the profiler-confidence
gate and the embedding role/cardinality gate, so `embeddingColumns` on this
live table went from `[]` to `["DevType"]` — SBERT went from mechanically
wired-in-but-inert to genuinely active on real data, without touching the
embedding code at all. Checked that the one group where this mattered was
handled correctly, not just non-crashing: `DevType`'s distribution inside
the sole accepted `semantic_quality` group (65% Back-end developer, same
long tail) is nearly identical to the full sample's, so it correctly does
*not* appear in that group's description — there is no real job-title signal
there to report, and the ranking machinery recognized that.

Full unit suite re-run after this change: **248 of 248 passing**, including
2 new regression tests (`test_name_tokens_splits_camel_and_pascal_case_column_names`,
`test_camel_case_name_hint_raises_categorical_confidence`) locking in the fix.

**Cross-dataset sweep, run before trusting this beyond the one dataset it was
found on:** re-profiled Chicago Crime (`crimes.csv`) and Student Loan
Complaints (`complaints-2025-04-21_17_31.csv`) — the other two sample
datasets. Zero confidence-score change on either: both use space/hyphen-
separated column names (`"primary description"`, `"Sub-issue"`), which the
old regex already split correctly, so camelCase was never their problem.
Full pipeline run on both without error: Chicago Crime correctly kept
`embeddingColumns: []` (its open-vocabulary text columns are `free_text`
role, outside the embedding-eligible role set by design); Student Loan
Complaints genuinely activated embeddings (`embeddingColumns: ['Sub-issue',
'Company', 'Tags']`) on its full, un-sampled dataset (6,855/6,855 rows) with
no crash.

### Duplicate-candidate description caching (2026-07-21)

Found while sweeping datasets above: the Chicago Crime pipeline took ~9
minutes end-to-end on a 10,000-row sample. Profiled directly with
`cProfile` rather than guessed — `is_missing_value` (24.6M calls) and
`format_group_value` (12.2M calls) dominated the runtime.

Root cause, in `generate_duplicate_candidates()`: every near-duplicate
signature that repeats 2+ times gets a full `make_group()` →
`build_grounded_group_description()` call *before* any acceptance/ranking
filter narrows the list — 198 candidate groups on this dataset, though only
a handful are ever shown. Each of those calls, in turn, recomputed
`categorical_description_candidate()`'s full-sample baseline (missing-value
mask + formatted values) **from scratch per column per group**, even though
that baseline is identical for a given column across every group asking for
it. 198 groups x ~5 columns x ~10,000-row baseline recompute accounts for
essentially the entire 24.6M-call count.

Fixed by threading an optional `baseline_cache` dict through
`make_group()` → `build_grounded_group_description()` →
`semantic_description_candidates()` → the categorical/numeric/temporal
candidate functions (`cached_full_frame_categorical_values()` and its
numeric/temporal counterparts), computed once per column and reused across
every candidate group sharing the same frame. `generate_duplicate_candidates()`
and `groups_from_partition()` each build one cache dict before their loop
and pass it to every `make_group()` call inside it. Not threading the cache
(the default, `None`) reproduces the old per-call behavior exactly, so
nothing that doesn't opt in is affected.

**Verified, not assumed:** re-ran the identical `cProfile` capture after the
fix — Chicago Crime end-to-end time dropped from ~336s (cold) / ~203s (warm)
to **48.6s**, a roughly 4-7x improvement, with the exact same group count (1)
as before the fix. A new regression test
(`test_categorical_baseline_cache_is_reused_and_does_not_change_the_result`)
asserts both that the cache is actually populated and reused (by object
identity, since `pandas.Series.map()` always returns a new object) and that
using it produces a byte-identical result to not using it. Full suite:
**249 of 249 passing.**

### Free-text SBERT embeddings — opt-in, replaces TF-IDF (2026-07-21)

Extends the categorical SBERT path (above) to genuine prose columns
(`free_text` role — e.g. `Consumer complaint narrative`), on explicit
direction to keep it opt-in rather than default, unlike the categorical path.
Two decisions, made deliberately rather than defaulted into:

1. **Replace TF-IDF, don't run alongside it.** For an eligible free-text
   column, SBERT embeddings substitute entirely for that column's TF-IDF
   terms in the `text` view's feature matrix — the same replace-not-add
   pattern the categorical path already uses, for the same reason: running
   both would double-count the column's signal with no principled way to
   weight the two against each other.
2. **Plain role gate, not a cardinality split.** `embedding_eligible_columns()`
   (categorical) separates high- from low-cardinality candidates because low-
   cardinality categories are already well-served by exact match. That split
   carries no signal for free text — prose is high-cardinality by
   construction (cells are typically near-unique) — so
   `free_text_embedding_eligible_columns()` is a plain role check: every
   `free_text`-role column is eligible, with no 3-candidate floor (a single
   eligible free-text column is still a legitimate TF-IDF-vs-SBERT swap).

Stays behind its own flag (`use_free_text_embeddings`, wired to
`strategy=semantic_quality_free_text_embeddings`), independent of the
always-on `use_semantic_embeddings` categorical flag — requesting one must
not activate the other, verified directly by a test that opts into
categorical embeddings alone and confirms `embeddingColumns` stays empty for
the text view.

`embedding_semantic_description_candidate()` (already built for categorical
columns) is reused as-is for embedding-routed free-text columns — the
function only depends on `embeddingColumns`/`embeddingValuesByColumn` in
`feature_info`, not on the column's role, so no new description logic was
needed. Verified against the real model, not just a test double: three
differently-worded complaints ("never responded to my calls", "never called
me back", "would return my calls") scored 0.86 in-group cohesion vs 0.72
baseline — genuine semantic matching across sentences with no shared
vocabulary trick, not just single-word categorical matching.

**Verified live on real data:** on the Student Loan Complaints dataset,
`embeddingColumns` went from `['Sub-issue', 'Company', 'Tags']` (categorical
only) to also include `Consumer complaint narrative` and `Company public
response`, full dataset processed (6,855/6,855 rows), no crash, 3 groups
returned. None of those 3 groups happened to surface the free-text
description candidate — checked and it's the same legitimate reason as the
categorical case on this dataset: the groups' real distinguishing signal was
consent/date fields, not narrative content, for this particular partition.

Full suite after this change: **251 of 251 passing**, including 3 new tests
(`test_free_text_embedding_eligible_columns_is_a_plain_role_gate`,
`test_free_text_embeddings_are_a_separate_opt_in_from_categorical_embeddings`,
plus the existing embedding-candidate test now covering free text implicitly
since the function is shared).

### Prose headline summary instead of verbatim quoting (2026-07-21)

Follow-up to the cosmetic issue flagged above: for embedding-routed columns,
`embedding_semantic_description_candidate()` concatenated up to 3 full
distinct values into the headline. Fine for a single categorical word, but
for free-text sentences that produced ~250+ character headlines, on direct
instruction to shorten them to a summary instead.

Distinguishes prose from short label-like values by average word count
(`EMBEDDING_PROSE_WORD_THRESHOLD = 6` — a formatting cutoff, not a modeling
threshold, same category as `DESCRIPTION_VALUE_CHARACTER_CAP`). For prose,
`shared_embedding_terms()` replaces quoting with a deterministic keyword
summary: tokens (via `sg.tokenize`) that recur across 2+ of the group's own
distinct values, ranked by recurrence — not a model-generated summary, no
fabrication, same "only report what is literally present" discipline every
other description candidate in this file follows. Short label-like values
(job titles, business categories) are unaffected — still quoted, as before.

Caught and fixed along the way: `sg.STOP_WORDS` (20 words: articles,
copulas, a few prepositions) is tuned for short category tokens, not
natural-language prose — it has no pronouns, modal verbs, or common
prepositions. Real narratives surfaced "about"/"my" as the "shared theme"
ahead of actual content words. Added a separate ~70-word `PROSE_STOP_WORDS`
set scoped to `shared_embedding_terms()` only — does not touch `sg.STOP_WORDS`
or any other tokenization path in this codebase (TF-IDF, categorical
tokenizing, etc. are all unaffected).

**Verified against the real model, not just a test double:** the earlier
3-narrative "nobody called back" example went from a ~250-character headline
quoting all three sentences to:

> "3 narrative entries with similar meaning (shared language: balance,
> calls, loan)" — 81 characters, and every word in it is a real recurring
> word from the group's own text.

Full suite: **252 of 252 passing**, including a new test
(`test_embedding_semantic_description_candidate_summarizes_prose_instead_of_quoting_it`)
that verifies both directions: prose summarizes instead of quoting, and
short values still quote exactly as before (no regression to the categorical
case verified earlier in this document).

### Ordinal (bucketed-range) distance for categorical columns (2026-07-21)

Implements the "smaller, also-bounded fix" flagged in
`RANKING_AND_SIMILARITY_POSITION.md` §2.3: bucketed-range categorical strings
("18-24 years old", "0-2 years", "$25,000 to $34,999") were treated as pure
equality — "18-24" no closer to "25-34" than to "65+" — even though they
have an obvious numeric order. Unlike the SBERT paths above, this needed no
external model and ships on by default (no flag): it is deterministic
arithmetic, not a representation swap with unmeasured quality impact.

**Mechanism.** `parse_ordinal_bucket_value()` extracts a representative
number from a bucket string: the midpoint of an explicit range ("9 - 12
hours" → 10.5), or the stated bound for a one-sided range ("Under 18 years
old" → 18, "30 or more years" → 30). Eligible columns are converted to that
representative number and routed through the *same*
`build_weighted_numeric_matrix()` every other numeric column already uses —
no new distance code, no new clustering path, just reclassifying which
columns feed the existing numeric block. Replaces token/embedding treatment
entirely for eligible columns, same replace-not-add principle as the SBERT
paths.

**Eligibility gate, three parts:**
1. Role gate: only `categorical`-role columns (binary/coded categories excluded).
2. Every distinct present value must parse — deliberately the strictest
   possible bar, no partial-match fraction, so one stray "Prefer not to say"
   disqualifies the whole column rather than silently dropping it from the
   representation.
3. **Cardinality/repetition gate, added after catching a real false positive
   in testing:** distinct values must be fewer than non-missing rows — i.e.
   at least one value must repeat. A genuine bucket scheme repeats by
   definition; a column where every row's value is unique (an ID with an
   embedded digit, "Job 14", "SKU-2291") would otherwise parse cleanly too
   and get mistaken for an ordinal scale purely because it contains a
   number.

**Parser strictness, also tightened after catching the same false positive
at the regex level.** The first version matched any digit anywhere in a
string, so "Country 14" and "Job 7" parsed successfully (bare label +
incidental number). Rewritten to require genuine range structure: two
numbers joined by a separator (`-`, `to`), or a number paired with bound
vocabulary (`under`, `over`, `or more`, `at least`, ...). A bare number with
no such structure now correctly returns `None`. Verified directly: `"Country
14"` → `None`, `"Job 7"` → `None`, `"SKU-2291"` → `None`, while every real
StackOverflow bucket string (`"18-24 years old"`, `"9 - 12 hours"`, `"Under
18 years old"`, `"30 or more years"`) still parses correctly.

**Documented scope limit, not silently patched over:** purely verbal
orderings with no digits at all ("Some college" < "Bachelor's" < "Master's"
< "PhD") are out of scope — inferring that order would need an external
education-level reference table, exactly the per-domain hand-tuning this
approach exists to avoid. `RANKING_AND_SIMILARITY_POSITION.md` §2.3 already
names this as unaddressed; this fix does not change that.

**Verified against real data, not just synthetic tests.** On the live
StackOverflow table, `ordinal_eligible_columns()` correctly promotes
`YearsCoding` and `HoursComputer` and correctly excludes `Age` — Age's "0"
and "21.5" rows (a real, pre-existing data-quality issue in that column) are
bare numbers with no range structure, so they don't parse, and the
all-must-parse gate correctly declines to treat a messy column as a clean
ordinal scale. Neither column is currently reachable end-to-end on this
specific live table, though: both sit below the same pre-existing
profiler-confidence cutoff (0.8595) already documented for the embeddings
paths above, for the same reason (no recognized name-hint keyword) — a
different, already-known limitation, not a new one introduced here. Full
pipeline correctness was instead verified with a synthetic dataset that
clears that gate: `build_multiview_groups_from_frames()` produced a group
with `"kind": "ordinal"` and the description *"Rows with lower-than-typical
years coding"* with `groupValue: "0-2 years"` — a real bucket label, not a
raw parsed float, and genuine numeric clustering distance, not string
equality.

Full suite: **255 of 255 passing**, including 3 new tests covering parser
strictness, the eligibility gate (role, parseability, and the repetition
safeguard), and metadata propagation through `build_semantic_quality_matrix`
(the same merge-drop bug class fixed for embeddings earlier — checked
directly here rather than assumed fixed by analogy).

### Ordinal columns bypass the general confidence cutoff (2026-07-21)

Found by asking why `YearsCoding`/`HoursComputer` — genuinely clean bucketed-
range columns — were still excluded on the live StackOverflow table even
after the ordinal fix above shipped. Root cause: the general profiler-
confidence score (used everywhere in the app, not just clustering) is
dominated by two column-blind terms — a sample-size-only worst-case
reliability ceiling, identical for every column at a given row count, and a
binary 0.10-point name-hint bonus (does the column name contain one of ~16
recognized English words). Neither term reflects whether a column is
actually a well-formed ordinal scale.

Rejected fixing this by touching the shared confidence formula or its
weights — that function is used across the entire profiler (identifier,
geography, measurement, free-text detection; adaptive sampling triggers;
"needs review" flags), so changing it would have broad, hard-to-reason-about
blast radius for the sake of one clustering feature, and risks exactly the
per-dataset overfitting this project has repeatedly guarded against
elsewhere. Instead: `choose_view_columns()` now lets a column bypass the
general cutoff specifically when it independently clears
`ordinal_eligible_columns()`'s own stronger, per-column evidence (every
value cleanly parses as a bucketed range) — a narrow, low-risk exemption
scoped to one already-verified gate, not a general relaxation. Deliberately
**not** extended to embedding eligibility: `ordinal_eligible_columns()` is a
pure per-column check with no cross-column comparison, so widening its
candidate pool has no side effects on sibling columns; `embedding_eligible_
columns()`'s cardinality tiering is a *relative* comparison across candidate
columns, so exempting it from the cutoff would shift the tiering split for
other columns too — a bigger, different decision that needs its own scoped
call, not a side effect of this one. (Turned out not to matter in practice
here: `DevType`/`RaceEthnicity` already cleared the cutoff via the earlier
camelCase name-hint fix.)

Caught and fixed a process-hygiene bug while verifying this live: repeated
backend restarts were killing the wrong PID (matching "most recently
started" instead of the actual long-running ~200-800MB backend process),
silently leaving stale code serving several verification attempts. Fixed by
filtering on process working-set size and confirming the port was fully
down before restarting; verified the fix took effect via a field that only
exists in new code (`ordinalColumns` in the API response) rather than
trusting HTTP 200 alone.

**Verified live:** on the real StackOverflow table, `excludedLowConfidenceColumns`
dropped from 14 to 12 (both `YearsCoding` and `HoursComputer` now included),
and a real accepted group's supporting fields show `"ordinal | YearsCoding |
6-8 years"` — genuine ordinal evidence in production, not just a synthetic
test. Full suite: **256 of 256 passing**, including a new test that also
asserts a low-confidence column that is *not* ordinal-eligible is still
excluded normally — proving the exemption is narrow, not a blanket cutoff
relaxation.

### Geography reference table for location-name columns (2026-07-21)

Implements the other "concrete, bounded fix" named in
`RANKING_AND_SIMILARITY_POSITION.md` §2.3, alongside the ordinal fix above:
Buckaroo already computes real spherical distance when a table has explicit
`latitude`/`longitude` columns, but location *names* without paired
coordinates ("Country=India") fell back to exact-match tokens — "India" is
mathematically no closer to "Pakistan" than to "Australia". Countries only
for this pass; city-level matching has real name-collision risk ("Springfield"
exists in dozens of countries) that needed its own scoped decision — see
"City-level geography matching: context-first, population-as-last-resort
(2026-07-25)" below for that decision.

**Verified SBERT would NOT be a substitute for this, empirically, before
building anything.** Embedded 10 real country names with the actual model
and compared similarity against known geographic distance: France scored
*closer* to Australia (0.629, ~16,700 km) than to Japan (0.546, ~9,700 km);
the UK scored closer to Australia (0.602, ~17,000 km) than to Poland (0.511,
~1,500 km). Consistent, not noise: SBERT tracks linguistic/cultural
co-occurrence (shared language, colonial history), not physical distance.
Confirms the position already in this document — geography has an exact,
computable ground truth a static reference table can encode correctly,
where a learned semantic proxy would only approximate it, unreliably.

**Mechanism.** New module `app/server_utils/geography_reference.py`, same
isolation pattern as `semantic_embeddings.py` (heavy dependency imported
lazily, only paid when the feature is actually used). Two small, static,
offline libraries, no network calls at request time: `pycountry` for
robust name/alias resolution (official names, common names, typo-tolerant
fuzzy search — ISO-sourced, not hand-curated here) and `geonamescache` for
country + capital-city coordinate data. A country name resolves to its
**capital city's** coordinates, not a computed area centroid — a standard,
unambiguous choice (every country has exactly one capital) that sidesteps
centroid ambiguity for irregularly-shaped or archipelagic countries.
Resolved columns feed the *same* spherical-projection code (`x = cos(lat)
cos(lon)`, etc.) that real lat/long columns already use — extracted into a
shared `project_lat_lon_to_unit_sphere()` helper so both paths are
guaranteed to compute distance identically, not just similarly. Replaces
exact-match tokens entirely for eligible columns, same principle as every
other feature swap in this file.

**Eligibility gate, matching the ordinal gate's posture:** role must be
`location_name`/`country_code` (not city/region roles — out of scope), and
every distinct present value must resolve to a country — same strict,
no-partial-credit bar as `ordinal_eligible_columns`, for the same reason (one
genuinely unresolvable value disqualifies the whole column rather than
silently dropping it from the representation).

**A real cross-library naming gap, caught and fixed, not glossed over.**
`pycountry`'s exact-match lookup failed on `"Turkey"` — ISO 3166 renamed the
country to `"Türkiye"` in pycountry's data, but `"Turkey"` is what virtually
every real dataset actually contains, and `pycountry`'s own fuzzy search
also failed to bridge the gap. Fixed by adding `geonamescache`'s own
(still-"Turkey") name index as a second exact-match layer before falling
back to fuzzy search. Verified directly: all 20 real `Country` values from
the live StackOverflow table resolve, including `"Turkey"` and
`"Russian Federation"` (pycountry's fuzzy search alone handles the latter).

**Dependency injection for test speed, same reasoning as `embedder`.** The
real reference-data load takes ~13 seconds on first call (parsing 32,444
cities into a capital-coordinate index) — too slow to let leak into the
committed test suite. `build_geography_matrix()` and `build_semantic_
quality_matrix()` both accept an injectable `country_resolver` parameter
(default: the real `geography_reference.country_centroid`); tests use a
small fake dict-backed resolver instead, so `tests/unit/test_geography_
reference.py` and the integration test in `test_multi_view_grouping.py` add
essentially zero time to the suite. Live verification against the real
libraries was done separately, ad hoc, matching the discipline already used
for SBERT (fast, fake-backed tests in the committed suite; real-dependency
verification run once, by hand, and reported here).

**Verified the actual geometry, not just that it runs.** Built a synthetic
120-row dataset (40 rows across 6 European countries, 80 rows scattered
globally) and measured average pairwise distance directly in the resulting
feature matrix: within-Europe pairs averaged **0.098**, while within-
scattered and Europe-to-scattered pairs both averaged **~1.21** — genuine
geographic clustering, where the old exact-match tokens would have made
every distinct-country pair equally "1.0" apart regardless of actual
proximity.

**Verified live on the real StackOverflow table.** `geographyNameColumns:
['Country']`, and an accepted group's supporting fields show `"geography_name
| Country | Spain"` with the description *"Country typically a location
about 607 km north-northwest of the sample's typical center"* — real,
computed spherical distance in a production description, alongside the
pre-existing `"Continent | EU"` categorical evidence, both independently
telling the same coherent story about the same group.

Full suite: **259 of 259 passing**, including 3 new tests (gate role/
resolvability/repetition in `test_geography_reference.py`, plus an
integration test verifying replace-not-add token treatment, metadata
propagation through `build_semantic_quality_matrix`, and a real
below-baseline description).

### Near-duplicate crowd-out risk — investigated, partially closed (2026-07-21)

Follow-up to the open risk flagged in the "Semantic-first ranking" section
above: never tested against a genuinely duplicate-dense dataset. Tested it
this session with a synthetic dataset (up to 77% of rows in near-duplicate
signature groups). Two distinct findings, kept separate rather than
conflated:

**The originally-hypothesized risk does not occur — verified, not just
argued.** The concern was that near-duplicate groups (always `strength =
1.0`, maximum specificity) might out-rank genuine semantic-quality clusters
in the final list. Read `rank_groups_semantic_first()`'s actual sort key:
`(view_tier, semanticScore, utilityScore)`, where `view_tier` gives every
`semantic_quality` group a **hard** priority over every `duplicates` group,
regardless of score. This is a structural guarantee, not a probabilistic
one. Confirmed empirically too: with 7 duplicate groups scoring 0.94–1.0
against a semantic_quality group scoring ~0, the semantic_quality group
still ranked #1. Near-duplicate groups can only fill slots a semantic
cluster didn't claim, never displace one.

**A different, real problem was found: on duplicate-dense data, genuine
minority clusters can fail to be *discovered* at all**, not out-ranked but
never generated as a candidate in the first place. Root cause, traced
precisely: `partition_diagnostics()`'s `distinctiveness` term (how separated
each cluster's centroid is from its nearest neighbor) is diluted by
averaging across every cluster uniformly, and `run_internal_clustering()`
falls back to the *smallest* k when no candidate is a clear score standout —
a deliberate, load-bearing "conservative when ambiguous" default used
throughout this codebase. On a duplicate-dense dataset, raising k mostly
subdivides the numerically-dominant near-duplicate majority into more
near-identical fragments, dragging the mean distinctiveness down almost
regardless of whether a real, separate minority cluster is also present in
that partition — so the conservative low-k fallback wins essentially every
time, burying the minority cluster inside a larger, undifferentiated one
before it ever becomes a ranking candidate.

Two complementary fixes shipped, evaluated in order of increasing risk:

1. **Distinctiveness: upper quantile instead of mean** (`adaptive_grouping_
   policy.py`). Rewards a partition that contains *at least one* well-
   separated cluster, instead of requiring *all* clusters be uniformly
   separated from each other — while still correctly penalizing meaningless
   over-segmentation of an ordinary dataset (spurious splits of one real
   cluster are all mutually close, including the "best" one, so the upper
   quantile stays low there too). Verified zero regressions: full suite
   (259/259) and the clustering threshold audit script (134 curated
   decisions) both still pass unchanged.
2. **Deduplicate before clustering, not after** (`multi_view_grouping.py`,
   `run_internal_clustering`/`adaptive_dbscan_record`). Every clustering
   decision (which k, which algorithm, eps for DBSCAN) is now made on the
   matrix's *distinct* rows, with labels expanded back to one entry per
   original row afterward. A row repeated 400 times and a row that appears
   once are structurally different information for "how many distinct kinds
   of rows exist," and only the shape of the distinct-row population should
   drive that decision — the same standard practice used broadly for
   clustering with heavy record duplication. Unconditional, not gated by a
   duplication-density threshold: on a dataset with no duplicate rows this
   is a pure no-op (every row is already unique), so it only changes
   behavior exactly where duplication is actually present. Also fixes a
   related DBSCAN-specific issue: duplicate rows contribute zero-distance
   neighbor pairs that skew its automatic epsilon selection toward an
   artificially tiny value, over-fragmenting everything (confirmed directly:
   46 clusters on the same dataset K-means merges into 2).

**Ruled out "just use a different algorithm" as a free alternative, checked
directly rather than assumed.** DBSCAN and Agglomerative are already tried
as alternatives to K-means in this pipeline. Neither independently solves
this: Agglomerative reuses whatever k K-means already selected, so it
inherits the same problem; DBSCAN (before the deduplication fix above)
produced 46 over-fragmented clusters on the adversarial test data, its
epsilon skewed tiny by the same duplicate-density distortion.

**Honest result on the most extreme case, not overclaimed.** Both fixes are
real, verified, and safely shipped. Together they measurably narrow the gap
between the "safe" low-k score and the structure-revealing high-k score —
from 0.26 (0.828 vs 0.568) down to 0.013 (0.797 vs 0.784) on the same
77%-duplicate-density synthetic test with 3 genuine minority clusters
deliberately buried in it. That did **not** fully flip the final decision in
this most-extreme case: the remaining gap is small enough that the
"conservative when ambiguous" selection rule — itself unchanged, deliberately
not touched given how broadly it's relied on — still doesn't see a clear
winner and falls back to the smaller k. On realistic duplicate density this
gap should close further or flip outright, but that has not been verified
against a real dataset, since none of the three sample datasets tested this
session came anywhere near 77% duplication. Verified as a pure no-op on
real data: `n0_stackoverflow_db_uncleaned_CD2F5`'s live output (group count,
composition, descriptions) is structurally unchanged before and after both
fixes.

Full suite after both fixes: **259 of 259 passing**, plus the clustering
threshold audit script.

**Follow-up: tested at realistic duplicate density, not just the 77%
extreme case — found the risk is narrower and rarer than the framing above
suggests, and said so plainly rather than declaring victory.** On direct
instruction to check whether this matters in practice, not just at an
engineered worst case:

*Single minority cluster, 35–75% duplicate density.* Built a 400-row dataset
(~35% near-duplicate rows) with one genuine 40-row "premium" cluster hidden
in it, real quality signal attached. Result: fully captured (40/40 rows),
ranked #1, correctly described. But checked *why*, not just *that* — running
the pre-fix (non-deduplicated) math on the same data, at densities swept up
to 75%, found it **also** isolated the single minority cluster correctly,
every time. A lone unusual segment turns out to be robust even at high
duplicate density; this specific test didn't actually depend on either fix
to succeed, so it doesn't demonstrate their necessity.

*Multiple competing minority clusters (the condition that originally
exposed the problem), swept across 55–80% density.* This is the narrower,
more specific case: several distinct, small, genuinely different clusters
all needing a higher k to be told apart, buried in a duplicate-dense
majority. Results were mixed, not a clean win. Sometimes the fixes made no
difference — old and new code produced identical partitions. Sometimes, even
with both fixes active, the underlying K-means partition still merged 2 of
the 3 minority clusters into one label instead of separating all three.

**Revised, more precise conclusion.** The crowd-out risk is not "any
duplicate-dense dataset" — it specifically requires *multiple* distinct
minority segments competing for a higher k at the same time. A single
unusual pattern is not at risk, at any density tested. And even within that
narrower condition, the shipped fixes are necessary-but-not-sufficient: some
of the residual difficulty is a separate, harder problem — K-means' general
difficulty correctly separating several small, similarly-shaped clusters
from *each other*, which is not a duplicate-density effect at all and is not
fixed by either change made here. The two fixes remain real, verified, safe
improvements (they measurably narrow the score gap that drives the
conservative low-k fallback, and they fix a genuine DBSCAN epsilon
distortion), but "does this fully solve the crowd-out risk in practice" is
answered more precisely as: *for the narrow multi-minority-cluster case,
partially — and that narrow case is rarer than duplicate density alone would
suggest.*

**Second follow-up: investigated two more candidate levers on direct
instruction, both tested to a negative or inconclusive result rather than
implemented speculatively.** With the representation and algorithm choice
both independently ruled out as the cause (see the HDBSCAN/GMM discussion
below and the distance-concentration check that found the feature space
itself is fine — inter-cluster centroid distance ~1.12–1.18 against
within-cluster spread of only ~0.16–0.23, a clean 5–6x separation the
algorithms simply aren't exploiting), the two remaining levers were the
k-selection *rule* and the score components (`stability`, `balance`) that
feed it.

*K-selection rule, tested directly, ruled out.* The hypothesis: does
"prefer smallest k when ambiguous" specifically cause this, such that
"prefer highest score, k only as a tiebreak" would fix it? Computed the
actual competitive pool for the adversarial case: `{k=2: score 0.825, k=8:
score 0.763}`. Both the current rule and the proposed rule pick k=2 from
this pool — because k=2 genuinely has the higher score, not because of a
tie-breaking artifact. Swapping the rule changes nothing here. The problem
is upstream of the rule, in the scores themselves.

*`balance` (Shannon-entropy evenness of cluster sizes), demonstrated
concretely flawed, but no fix found that helps.* Direct counter-example:
`balance([336, 40, 40, 40])` (the correct answer: one large majority plus
three genuine minority clusters) scores **0.624**, while
`balance([228, 228])` (the majority and all three minorities merged evenly
in half) scores **1.000** — the metric rewards the wrong answer over the
right one, because it assumes clusters "should" be evenly sized, which is
an assumption about shape, not something derived from the data. Tested a
principled replacement (fraction of clusters meeting a usable-size floor,
instead of size-evenness) and it does not help in practice:
  - On the adversarial synthetic case, the gap between k=2 and k=8 narrows
    from 0.062 to 0.044 but k=2 still wins (0.834 vs 0.790) — same selected
    k as before.
  - On live StackOverflow data, the selected k is identical before and
    after (k=3 both times) — zero behavior change on real data.
  - With a size floor loose enough not to over-penalize genuine minority
    clusters, balance becomes 1.0 for nearly every candidate — vacuous,
    silently discarding the real degeneracy protection it provides
    elsewhere (verified it correctly still scores 0.072 and 0.273 on two
    genuinely broken partitions, e.g. `[450, 3, 3]`).
  Net: real, demonstrated flaw: no net benefit found from the fix that was
  tried, and a real risk of quietly losing degeneracy protection used by
  every other clustering decision in the app. Not shipped.

*`stability` (repeated-run agreement), checked, found legitimately biased
rather than buggy.* Measured directly: k=2 scores a perfect 1.000 across 5
independent seed pairs; k=4/6/8 sit at 0.90–0.93. This is not an artifact —
k=2 is trivially reproducible *because it is an easier partitioning
problem*, and an unstable higher-k partition genuinely is less trustworthy
evidence. Penalizing k=2 for being reproducible would be penalizing the
metric for correctly doing its job. Left unchanged.

**Conclusion: stopped chasing this deliberately, not because the search ran
out but because the fix would stop being principled.** Even with `balance`
made fully vacuous, k=2 still wins on the remaining components. Flipping
this one synthetic case would require simultaneously re-tuning `balance`,
`stability`, and `distinctiveness` together to favor high k — which is
tuning three shared formulas against a single case *I constructed myself*,
the exact overfitting failure mode this project has repeatedly guarded
against elsewhere (the routing bug, the geography scoring bug, the
threshold audit). The honest state of this investigation: the residual gap
is not one broken metric with a clean fix. It is that a geometric mean of
five components, on data shaped like "one large spread-out majority plus
several small tight minorities," has a structural preference for coarse
partitions — and resolving that needs a real benchmark across real datasets
(the still-open item from earlier in this document), not further tuning
against a synthetic construction. Recorded here as a named, evidence-backed
limitation for that benchmark work to settle, not as an unsolved bug
awaiting a quick fix.

### Profiler-confidence reliability: column-aware, not sample-size-only (2026-07-21)

Follow-up to the "Any improvements in profiler?" question. Investigated
`score_profile_confidence()` (`experiments/profile_dataset_shape.py`)
directly, alongside its twin `score_candidate_confidence()` (which scores
the *alternative* candidate roles shown in the UI, not just the chosen one)
— both had the identical pattern.

**Root cause, traced precisely, not assumed.** A column-specific reliability
computation already existed:
`reliability_from_margin(relevant_interval["margin"])`, where
`relevant_interval` is that column's own evidence interval (`cardinality`
for categorical columns, `numeric_parse` for measures, etc.) — genuinely
column-aware, and its margin already widens correctly for small samples and
for HLL-estimated cardinality (see `cardinality_interval_summary`). But it
was being `min()`'d against `evidence_intervals["sample"]["reliability"]` —
a *dataset-wide* worst-case bound built from `evidence_interval(n // 2, n,
...)`, i.e. an assumed 50/50 split, identical for every column at a given
sample size regardless of how clean that specific column's own values are.
Measured directly: at n=400 this shared ceiling sat at 0.837, capping a
column with 11 perfectly clean, well-separated bucketed values at the same
reliability as a column that is genuinely ambiguous. This is the same
mechanism already found (and worked around, not fixed) earlier this session
via the ordinal confidence-cutoff bypass — the bypass treated one symptom;
this addresses the actual cause.

**Fix:** removed the `min()` in both functions, using
`reliability_from_margin(relevant_interval["margin"])` directly. For roles
where `relevant_interval` already *is* `evidence_intervals["sample"]`
(`vector_blob`, high-uniqueness/identifier datetime roles), this is a
verified no-op — the two values were already identical there, so nothing
changes for those roles.

**Verified impact, measured on real data, not assumed.** On the live
StackOverflow table, every previously-capped categorical column's
confidence rose:

| Column | Before | After |
| --- | --- | --- |
| YearsCoding | 0.821 | 0.850 |
| HoursComputer | 0.829 | 0.877 |
| FormalEducation | 0.822 | 0.854 |
| RaceEthnicity | 0.926 | 0.969 |
| DevType | 0.914 | 0.924 |

**One real regression, found and fixed in the same pass.** Because the
adaptive confidence cutoff is *relative* (a natural-break split over the
current distribution, not a fixed number), raising most columns' scores
shifted the cutoff itself upward (0.8595 → 0.9055 on this dataset). `Country`
— whose own geography-role score did not move — got left behind by columns
that moved past it, dropping it out of the geography view even though every
one of its values still resolves cleanly to a real place. Fixed the same way
the ordinal exemption already works: extended the identical bypass pattern
in `choose_view_columns()` to `geography_name_eligible_columns()` — a column
that independently clears that gate (a pure per-column check, no
cross-column comparison, same as ordinal) is exempted from the general
cutoff for geography purposes specifically. Not extended to embedding
eligibility, for the same reason already documented for the ordinal
exemption: its cardinality tiering is a *relative* comparison across
sibling columns, so exempting it would have a different, wider blast
radius than a pure per-column check.

**A real test-authoring bug caught and fixed along the way, not glossed
over.** The first regression test for the geography exemption used
`monkeypatch`-style reassignment of `geo_ref.country_centroid` to a fake
function, expecting it to intercept calls inside
`geography_name_eligible_columns()`. It silently did not: Python binds a
function's default argument value at *definition* time, not call time, so
`geography_name_eligible_columns(..., resolver=country_centroid)`'s default
had already captured the original function object — reassigning the module
attribute afterward changes what `geo_ref.country_centroid` *points to*
going forward, not the value already baked into that signature. The test
"passed" only by coincidence: it used real country names (France, Germany,
Poland) that the *actual* resolver also resolves correctly, so the fake was
never exercised. Caught by re-testing with fictional country names
("Atlantis", "Wakanda", "Narnia") the real resolver could never resolve —
the test still passed, proving definitively the fake was not in use. Fixed
properly by adding an injectable `country_resolver` parameter to
`choose_view_columns()` itself (the same dependency-injection pattern
already used in `build_geography_matrix`), rather than relying on module-
attribute patching — verified for real this time with the same fictional-name
test.

Full suite: **263 of 263 passing** (2 new tests: column-aware reliability
exceeds the old dataset-wide floor for a clean column, and the geography
bypass proven with dependency injection rather than a broken monkeypatch),
plus the clustering threshold audit script (134 curated decisions, still
unchanged). Verified live end-to-end on the real StackOverflow table with
exactly one backend process running the current code (not a stale one) —
`Country` correctly back in `geographyNameColumns`, `excludedLowConfidenceColumns`
back to its original 12 entries.

### City-level geography matching: context-first, population-as-last-resort (2026-07-25)

The scoped-out item from the original geography reference table
(`geography_reference.py`'s docstring): "city-level matching has real
name-collision risk (many 'Springfield's, 'San Jose's exist in multiple
countries) that needs its own scoped decision, not a side effect of this
one." Researched first whether an existing library solves the
disambiguation logic itself — conclusion: no library does; the useful part
of an existing library (`geonamescache`) is its raw per-city country and
population fields, not a ready-made disambiguation policy. Built on that
raw material instead of hand-rolling a fresh geocoding library.

**Design, in priority order:**
1. **Context.** If the same row has a companion country/region value (a
   `country_code`-role column if the dataset has one, otherwise a
   `location_name` column that itself already resolved as a country), that
   value narrows the candidate list for the city name in that row —
   `city_centroid(value, country_hint=...)` in `geography_reference.py`.
2. **Population.** Only when no context column exists, or the hint doesn't
   match any candidate for that city name, fall back to the most populous
   remaining candidate — a proxy for "more likely the intended city," never
   treated as real evidence about the specific row.

**Why city-level needed row-level eligibility, not column-level.** The
existing `geography_name_eligible_columns()` (country pass) checks each
*distinct value* once, since a bare country name has no context dependency.
A city name's resolution can genuinely differ row to row depending on which
country it's paired with (`Paris`+`France` vs. `Paris`+`United States`), so
the new `city_name_eligible_columns()` resolves and checks every *row*
instead — same strictness precedent as every other eligibility gate in this
file (one unresolvable value disqualifies the whole column), just applied
per row rather than per distinct value.

**Tried only after the country pass, not instead of it.** `build_geography_
matrix()` runs `geography_name_eligible_columns()` (country) first, then
attempts `city_name_eligible_columns()` only on whatever `location_name`-role
columns did *not* clear the country gate — country resolution is
unambiguous (no name collisions), so it stays the first, stronger attempt.
`choose_view_columns()` mirrors the same order for its confidence-cutoff
bypass: a city column that independently clears `city_name_eligible_
columns()` is exempted from the general cutoff for geography purposes,
same narrow-exemption pattern as the ordinal and country bypasses, and for
the same reason (a pure per-column-and-its-context check the confidence
score never sees).

**Verified against real data, not just fakes.** Every unit test uses an
injected fake resolver (no ~13s geonamescache/pycountry load in the test
suite, same DI pattern as `country_resolver`/`embedder`). Separately ran
`city_centroid` against the real reference data live: `Paris` + hint
`France` → real Paris (48.853, 2.349); the *same string* `Paris` + hint
`United States` → Paris, Texas (33.661, -95.556) — proof the context
disambiguation is real, not just passing injected fakes. `Springfield` with
a hint that has no matching candidate in the real data (`Australia`)
correctly fell through to the population tie-break rather than failing.

Full suite: **269 of 269 passing** (6 new tests: `city_centroid`'s
context-first and population-fallback behavior, `city_name_eligible_
columns`' role gate and per-row strictness, the `choose_view_columns`
confidence-cutoff bypass, and `build_geography_matrix`'s end-to-end feature
+ description-candidate propagation).

## What remains fixed, and why

| Fixed value | Classification | Why it remains |
| --- | --- | --- |
| Sampling seed `20260717` | Reproducibility | Makes the same table produce the same random sample |
| K-means seeds `42`, `137` | Reproducibility | Makes the stability comparison repeatable |
| Two-row group floor | Structural | A repeated pattern cannot contain only one row |
| 10,000 sampled-row cap | Resource budget | Bounds interactive latency and memory |
| 512-token ceiling | Resource budget | Protects against pathological text cells |
| 256 MiB agglomerative estimate | Resource budget | Avoids quadratic-memory failure |
| 2,000 returned row IDs | Payload budget | Protects browser/API memory; membership is not changed |
| Calendar periods 12/7/24 | Domain constants | Definitions of month, weekday, and hour cycles |
| 86,400 seconds/day | Unit conversion | Physical unit definition |

These values should be benchmarked for performance or usability. They should
not be tuned on semantic labels and then presented as general accuracy gains.

## Benchmark-free evidence available now

Without a human benchmark, we can test:

1. whether thresholds change when distributions change;
2. whether the same data and seed reproduce the same result;
3. whether resampled/perturbed partitions remain stable;
4. whether the selected candidate is separated from alternatives;
5. whether identifiers remain excluded;
6. whether planted groups and planted errors are recovered; and
7. runtime and memory behavior.

The current automated tests cover distribution-sensitive thresholds,
sample-sensitive support, candidate ranges beyond the former fixed ceiling,
label-invariant stability, candidate separation, identifier exclusion, all four
semantic preprocessing blocks inside one matrix, quality-signal integration,
and source-backed threshold-audit integrity.

## Evidence that still needs people

For publication, use the frozen human worksheet as an **external benchmark**.
Do not feed those labels into the production policy. Recommended evaluation:

1. freeze datasets and labels;
2. hold out complete datasets, not random rows only;
3. run the adaptive policy without seeing held-out labels;
4. compare returned groups and explanations with blinded human ratings;
5. report confidence intervals and per-dataset results, not only one average;
6. compare against fixed-policy and all-column baselines; and
7. include failure cases where adaptive decisions are stable but semantically
   unhelpful.

## Main limitation

"Adaptive" does not automatically mean "correct." A natural break can be found
in a noisy score distribution, and repeated runs can reproduce the same bad
representation. The implementation removes arbitrary cross-dataset cutoffs;
the human benchmark is what establishes whether the resulting behavior is
actually useful.

A second limitation was added on 2026-07-20: making `semanticScore` the
primary sort key ahead of cluster geometry is itself an unweighted, adaptive
decision (a lexicographic tuple, not a hand-tuned weight), but the *choice* of
which score family goes first is a judgment call, not something derived from
the data. It was made explicitly, in response to direct feedback that semantic
meaning should dominate, rather than discovered as an inconsistency later.
**Update (2026-07-21):** this has now been tested against duplicate-dense
data (see "Near-duplicate crowd-out risk" above) — the ranking-level risk
this note originally flagged does not occur (`view_tier` is a hard priority,
not a score-based one), but a different, clustering-level risk was found and
only partially closed; see that section for the full, honest result.

A third limitation was added on 2026-07-21: making SBERT embeddings the
default representation for eligible categorical columns is, like the
semantic-first sort above, a product decision made on direct instruction, not
a validated improvement — no benchmark yet compares cluster quality with
embeddings on versus off across multiple datasets. The eligibility gates
(role + adaptive cardinality) are dataset-derived and prevent per-dataset
hand-tuning, but "does this actually produce better groups" remains an open,
unmeasured question, same as the general "equal vs. similar" gap documented
in `RANKING_AND_SIMILARITY_POSITION.md` §2.3.

A fourth limitation was added on 2026-07-21: the K-means candidate-scoring
formula (`partition_diagnostics`) has a demonstrated, quantified structural
preference for coarse partitions on data shaped like "one large spread-out
majority plus several small tight minority clusters" — confirmed by direct
counter-example (`balance` scores the correct 4-cluster answer *lower*,
0.624, than the wrong 2-cluster merge, 1.000) and by testing two candidate
fixes (a `balance` replacement, a k-selection rule change) that both
independently failed to change the outcome, on both synthetic and real
data. This was investigated deliberately rather than patched speculatively:
see "Near-duplicate crowd-out risk" above for the full trace, including why
each fix was rejected rather than shipped. It remains open, and resolving
it properly needs the same human/benchmark evaluation as the rest of this
document's open items — not further tuning against one synthetic case,
which the investigation concluded would cross into per-case overfitting.
