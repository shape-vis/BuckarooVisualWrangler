# Position Paper: The "Clear Winner" Threshold and "Equal vs. Similar" Clustering

Written in response to two questions Professor Rosen pressed on directly in the
2026-07-20 meeting and did not consider resolved. Both are recorded here as
open, honestly-scoped positions — not as solved problems — following this
project's standing rule of naming what is implemented, what is internally
verified, and what still needs external judgment.

---

## 1. "Where does it become a clear winner?"

### 1.1 The question, precisely

When comparing candidate partitions (K-means vs. agglomerative vs. DBSCAN, or
candidate values of k), Buckaroo picks the more complex/best-scoring candidate
only when it is "naturally separated" from the runner-up. Rosen's challenge:
*is 0.92 vs. 0.51 a clear winner? Is 0.92 vs. 0.9? Where exactly is the line,
and why there?* He named the two standard ways people handle multi-criteria
ranking — a deliberate fallback rule for when to stop trusting the primary
criterion, or one combined equation where a large gap in a secondary criterion
can override the primary one — and asked which one this is, and where its
threshold sits.

### 1.2 The precise mechanism (not a fixed number)

`agp.score_separation()` (`app/server_utils/adaptive_grouping_policy.py:299`)
answers this without a fixed gap threshold. Given the full set of candidate
scores being compared (not just the top two):

1. If there are only **two** candidates, the function returns
   `separated: False` **unconditionally** — regardless of how far apart the
   two scores are. This is a deliberate, hard rule, not an oversight: with
   only two data points, there is no statistical basis for saying they fall
   into "two natural classes" versus "two different numbers." A gap of 0.92
   vs. 0.01 with only two candidates is still reported as not separated, and
   the system falls back to the simpler, deterministic candidate.
2. If there are **three or more** candidates, Buckaroo computes
   `natural_break_threshold()` — the Otsu-style split point that maximizes
   *between-class variance* — **across the entire observed score
   distribution**, not just the top two values. The top candidate is
   declared the winner only if it sits strictly above that threshold **and**
   the runner-up sits at or below it.

So the answer to "where's the line" is: **the line is wherever the current
comparison's own score distribution has its widest natural gap, recomputed
every time.** It is not a quoted number like 0.85, because a fixed number
would itself be exactly the kind of arbitrary cross-dataset cutoff this
project has spent the last several weeks removing everywhere else (candidate
k range, DBSCAN epsilon, profile-confidence gate, minimum group support — all
now natural-break-derived for the same reason). This is directly why 0.92 vs.
0.9 with several other candidates clustered near 0.9 will *not* separate (the
whole cluster of high scores sits above whatever gap exists further down the
distribution), while 0.92 vs. 0.51 very plausibly will, *if there is a third
candidate for the Otsu split to anchor against* — with only two candidates,
neither case would separate, by rule 1 above.

### 1.3 Which of Rosen's two strategies this is

This is the **explicit fallback-rule strategy**, not the combined-equation
strategy — and the rule is not invented ad hoc for this one decision. The same
natural-break mechanism is reused for the profiler-confidence gate, minimum
group support, and description-evidence selection (see
`ADAPTIVE_DECISION_POLICY.md`). Reusing one consistent, data-derived rule
across every "when do I trust this signal" decision in the pipeline is the
answer to "why this rule and not some other magic number": it is not tuned
per-decision, so it cannot be quietly overfit to make any one comparison come
out the way we wanted.

### 1.4 What this does *not* claim

- It is a **mechanism-level** answer, not a semantic one. A natural break can
  appear in a noisy distribution with no real underlying structure — this is
  already a documented limitation (`MULTI_VIEW_CLUSTERING_METHODOLOGY.md`,
  Limitation 1). "Separated" means the scores form two statistically distinct
  classes, not that the winning candidate is semantically better.
- The two-candidate-always-ambiguous rule (1.2.1) has a real, honest
  consequence worth stating before Rosen finds it independently — confirmed by
  reading `run_internal_clustering()` directly, not assumed: K-means is
  always the first algorithm candidate, and agglomerative and DBSCAN are each
  appended only when they're eligible (agglomerative needs to fit the 256 MiB
  budget; DBSCAN needs a valid distance-knee). Whenever exactly **one** of
  those two is eligible — agglomerative without DBSCAN, or DBSCAN without
  agglomerative — the comparison has exactly two candidates, and rule 1.2.1
  means the alternative **can never win, no matter how much stronger its
  diagnostics are.** Only when *both* are eligible (three candidates total)
  does the natural-break rule get a chance to actually pick something other
  than K-means. This is the conservative-by-design behavior described in
  `MULTI_VIEW_CLUSTERING_METHODOLOGY.md` Section 6, but the "only wins with
  three candidates present" consequence is a real, previously-undocumented
  limitation of the current rule — flagged here so it is answered before
  asked, not discovered live.
- Separately, the **semantic-first group ranking** (`semanticScore`,
  `utilityScore`) added this week does *not* use `score_separation` at all —
  it is a strict lexicographic tuple sort with no ambiguity band. That
  ranking question ("how much does semantic score have to win by") does not
  arise there by construction, which is a different, simpler answer than the
  algorithm-selection case Rosen's example was drawn from — worth
  distinguishing explicitly if he raises both in the same breath.
- **A fourth, previously-undocumented consequence, found 2026-07-21 and worth
  stating before it's found independently: the separation mechanism is only
  as good as the scores it separates, and one of those scores has a
  demonstrated bias.** `score_separation()` itself is sound — verified above
  and unchanged. But `partition_diagnostics()`'s `balance` component (normalized
  entropy of cluster sizes) scores a genuinely correct partition (one large
  cohort plus several small, real minority clusters) *lower* than a
  demonstrably wrong one (that same population merged evenly in half) — direct
  counter-example: `balance([336, 40, 40, 40])` = 0.624 vs.
  `balance([228, 228])` = 1.000. On data shaped that way, the higher-`k`
  candidate that actually reveals the minority clusters can lose on score
  before `score_separation` ever gets a chance to compare it fairly — not
  because the separation *mechanism* failed, but because the input to it was
  already tilted. Tested two candidate fixes directly (a `balance`
  replacement, reordering the k-selection tie-break toward score instead of
  smallest-`k`) — neither changed the outcome, on either the adversarial
  synthetic case or real StackOverflow data. This is a different, more
  precise finding than "the threshold might be wrong": the threshold logic
  checks out; the scores feeding it do not always. See
  `ADAPTIVE_DECISION_POLICY.md`'s "Near-duplicate crowd-out risk" (second
  follow-up) for the full investigation and why neither candidate fix was
  shipped.

---

## 2. "Equal is not the same as similar"

### 2.1 The critique, precisely

Watching the live demo, Rosen's sharpest point: several groups clustered rows
that share **identical** categorical values (same `Country`, same `Gender`),
not rows that are merely *similar*. "Equal is the most precise form of
similarity... but what you want are clusters that have some similarity to
them" — e.g., European countries clustering near each other even when their
`Country` values differ.

### 2.2 Where this is already false, and where it's true

This critique does **not** apply uniformly across the system, and it matters
to say precisely where it does and doesn't:

- **Numeric fields** (`ConvertedSalary`, `Age`-as-number, etc.): already
  genuine distance, not equality — robust-scaled by median/IQR
  (`multi_view_grouping.py`, business block).
- **Datetime fields**: already genuine distance — absolute time plus cyclical
  month/weekday/hour coordinates, so December and January are already close,
  23:00 and 00:00 are already close.
- **Coordinate pairs** (explicit `latitude`/`longitude` columns): already
  genuine distance — unit-sphere features, handling longitude wraparound
  correctly (Section 5.4 of `MULTI_VIEW_CLUSTERING_METHODOLOGY.md`).
- **Plain categorical/nominal fields with no attached coordinates**
  (`Country`, `Continent`, `DevType`, `Gender`, location *names* and codes
  without a paired lat/long column): **this is exactly where the critique is
  correct.** These become column-qualified one-hot-style tokens
  (`country__india`). The distance between `Country=India` and
  `Country=Pakistan` is mathematically identical to the distance between
  `Country=India` and `Country=Australia` — both are simply "not equal." No
  notion of which countries are geographically or culturally closer exists
  today for value types without an explicit coordinate column.

### 2.3 Position: what to do next, scoped honestly

**Geography (location names/codes without coordinates) — implemented
(2026-07-21), countries only.** Buckaroo already computes real spherical
distance when a table has explicit `latitude`/`longitude` columns. The gap
was specifically for location *names* (country, city, region strings) that
arrive without paired coordinates. Rosen's own suggestion is what shipped:
`app/server_utils/geography_reference.py` resolves a country name to its
capital city's coordinates via two small, static, offline reference
libraries (`pycountry` for name/alias resolution, `geonamescache` for the
coordinate data — no network calls, no per-dataset tuning), feeding that
into the exact same spherical-distance machinery already built for the
coordinate case.

Before building this, tested whether SBERT (the mechanism used for §2's
arbitrary nominal categories, below) could substitute — empirically, not
just by reasoning about it. It cannot: embedding real country names showed
France scoring *closer* to Australia (~16,700 km away) than to Japan
(~9,700 km away), and the UK scoring closer to Australia than to Poland
(~1,500 km away) — SBERT tracks linguistic/cultural co-occurrence, not
physical distance. This confirms the reasoning below: geography has an
exact, computable ground truth a reference table encodes correctly, where a
learned semantic proxy only approximates it, unreliably. Verified directly
in the resulting feature matrix, not just asserted: a synthetic
Europe-vs-scattered-world dataset showed within-Europe pairwise distance
averaging 0.098 against ~1.21 for scattered pairs — genuine geographic
structure, confirmed live on the real StackOverflow `Country` column too.

City-level matching was out of scope for this initial pass: city names
collide across countries ("Springfield", "San Jose") in a way country names
essentially don't. Built on 2026-07-25 as its own scoped decision — context
first (a companion country/region column's value per row), population as a
last resort only when context is absent or doesn't match — see
`ADAPTIVE_DECISION_POLICY.md`'s "City-level geography matching" section.
See the "Geography reference table" section just above it in that same
file for the country-level eligibility gate, the `pycountry`/`geonamescache`
naming-divergence bug found and fixed (ISO renamed Turkey to "Türkiye";
`geonamescache` still uses "Turkey" and real datasets do too), and the full
live verification.

**Ordinal categories (bucketed-range experience/hours/age fields) —
implemented (2026-07-21), narrower in scope than first framed here.** Some
categorical fields have a natural order even though they're stored as
strings. What shipped covers *bucketed-range* strings specifically —
`"18-24 years old"`, `"0-2 years"`, `"$25,000 to $34,999"` — parsed to a
representative number (a range's midpoint, or a one-sided bound's stated
value) and given real numeric distance via the same machinery every other
numeric column already uses. No external reference data, no per-dataset
tuning, exactly as hoped here. It does **not** cover purely verbal orderings
with no digits at all (`"Some college"` < `"Bachelor's"` < `"Master's"` <
`"PhD"`) — inferring that order needs an external education-level reference
table, which is exactly the per-domain hand-tuning this document argues
against elsewhere. That gap remains open; see
`ADAPTIVE_DECISION_POLICY.md`'s "Ordinal (bucketed-range) distance" section
for the eligibility gates, the false-positive the parser had to be tightened
against (bare numbers in ID-like values, e.g. `"Job 14"`), and live
verification against the StackOverflow dataset.

**Arbitrary nominal categories (`DevType`, unordered business categories) —
addressed via SBERT sentence embeddings, shipped into the default path
(2026-07-21), with the overfitting risk contained by construction rather
than argued away.** Rosen's own suggestion here — an embedding-based
distance — is what was built: `app/server_utils/semantic_embeddings.py`
embeds unique categorical values with `all-MiniLM-L6-v2` and substitutes
that vector for exact-match tokens in the business-view feature matrix.
This is not a per-dataset hand-tuned notion of "similar" (the failure mode
this project has caught twice already) because eligibility is gated purely
by dataset-derived signals: profiler role (`categorical` only — binary/coded
categories are excluded because equality is already correct there) and an
adaptive cardinality split (`natural_break_threshold`, the same Otsu-style
method used elsewhere, requiring >=3 eligible candidates or nothing is
promoted). No column names or values are special-cased. Verified against
the live model, not just tests: on synthetic job-title data the real model
correctly ranked Back-end<->Front-end (0.60) above Back-end<->Database-admin
(0.40) above Back-end<->QA-engineer (0.38); on the real StackOverflow sample
it correctly promoted nothing, because only one column on that sample
clears the pre-existing role/cardinality gates. Rosen's own caveat about
LLM-based distances hallucinating does not apply here — this is a fixed,
deterministic sentence-embedding model, not a generative one, so the same
input always produces the same vector. What remains genuinely open: no
formal benchmark yet compares embedding-based clustering quality against
the token-based baseline across multiple datasets, so "does this improve
cluster quality" is still a judgment call from spot-checking, not a
measured result.

### 2.4 Why this framing, not a broader rewrite

The instinct to fix "equal vs. similar" everywhere at once should be resisted.
The project's repeated, hard-won lesson (geography scoring bug, generic
fallback, threshold audit) is that a fix that works by construction across
every dataset is worth far more than a fix that works well on the one dataset
being demoed. A general geography-distance table clears that bar. A
hand-tuned notion of "similar" for arbitrary nominal categories, invented from
looking at the StackOverflow demo, would not — it would be the exact kind of
per-dataset overfitting this project has already caught and fixed twice this
month (the routing bug and the geography scoring bug). Better to name the gap
honestly than to close it with something that only looks solved on one
dataset.
