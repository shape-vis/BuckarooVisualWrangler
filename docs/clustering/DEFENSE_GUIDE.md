# Clustering Defense Guide

## 1. The 60-second explanation

> Buckaroo currently clusters rows, not columns. A sampled row is converted into
> a numeric vector. Numeric columns remain separate robust-scaled coordinates.
> Text and category cells are tokenized and weighted using TF-IDF, then joined
> with the numeric block and normalized. Deterministic K-means compares each row
> vector with cluster centroids and assigns it to the nearest centroid. Buckaroo
> then describes each cluster using unusual numeric values, concentrated
> categories, and discriminative TF-IDF terms. The current product ranks and
> filters those semantic clusters using detector-error lift, support, and
> coverage. Therefore it is semantic feature clustering followed by
> error-conditioned selection, not yet a pure semantic-clustering system.

## 2. The most important correction

Do not say:

> TF-IDF creates semantic clusters.

Say:

> TF-IDF converts row text into weighted numeric features. K-means or another
> clustering algorithm forms the clusters from those features.

TF-IDF, SBERT, and robust scaling answer "how is a row represented?" KMeans,
DBSCAN, and Agglomerative answer "how are represented rows grouped?"

## 3. What is a TF-IDF matrix?

Suppose the sample contains three rows:

| Row | Country | Occupation | Salary |
| --- | --- | --- | ---: |
| 1 | India | Web developer | 70,000 |
| 2 | India | Software engineer | 75,000 |
| 3 | France | Teacher | 42,000 |

After preprocessing, a conceptual matrix could be:

| Row | scaled salary | `india` | `france` | `developer` | `engineer` | `teacher` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.4 | high | 0 | high | 0 | 0 |
| 2 | 0.5 | high | 0 | 0 | high | 0 |
| 3 | -0.6 | 0 | high | 0 | 0 | high |

The real values are continuous TF-IDF weights, not the words "high" and "low."
Each matrix row represents one table row. Each matrix column represents one
derived feature.

## 4. Does Buckaroo use all rows?

Current answer:

> Only when the table has at most 5,000 rows. The production API otherwise reads
> the first 5,000 rows ordered by internal ID. The Meta selector uses 1,500 rows
> for each candidate. This is deterministic, but it can be biased by table
> order, so the next publication-quality version should use reproducible random
> sampling and repeated seeds.

Do not call 5,000 rows "the full dataset" when the table is larger.

## 5. Does K-means compute the distance between every pair of rows?

No.

> K-means repeatedly compares every row with each of `k` centroids. If there are
> 5,000 rows and eight centroids, one assignment iteration calculates about
> 40,000 row-to-centroid distances, not a 25-million-entry row-to-row matrix.

Agglomerative and density/neighborhood methods can require more pairwise or
neighborhood computation, which is one reason they scale differently.

## 6. What distance does production use?

Production uses squared Euclidean distance after L2-normalizing row vectors and
centroids. For unit vectors:

```text
squared Euclidean distance = 2 - 2 * cosine similarity
```

Therefore the nearest-centroid ordering is cosine-like. It is accurate to say:

> Buckaroo uses normalized vectors with squared Euclidean K-means, producing a
> cosine-like comparison.

Do not simply call the implementation "cosine K-means" without this explanation.

## 7. Does TF-IDF derive real semantic meaning?

It derives **lexical and categorical similarity**, not deep language meaning.

TF-IDF is good at recognizing shared informative terms. It does not naturally
know that `car` and `automobile` are synonyms. SBERT can provide richer learned
language similarity, but it costs more time and can introduce model/domain
biases.

## 8. Does TF-IDF collapse all original features?

The professor's concern is partly correct.

- Numeric columns remain separate coordinates, so they are not collapsed.
- Text/category values are pooled into one row document.
- Column-name tokens provide context, but a value token like `india` is not
  explicitly tied to `country` in the final vocabulary.

The correct limitation statement is:

> The current pooled TF-IDF representation partially loses source-column
> identity for text values. A column-aware representation such as
> `country=india` is the appropriate ablation to test whether that information
> loss matters.

## 9. How are numeric columns handled?

Numeric values are not sent through TF-IDF. Each numeric column is:

1. parsed;
2. median-imputed;
3. centered on the median;
4. divided by IQR or standard deviation fallback;
5. clipped to four scale units;
6. divided by four; and
7. accompanied by a missingness indicator when needed.

The complete numeric block is multiplied by 0.75 before being joined with text.

## 10. How does Buckaroo decide that a column is numeric?

A column is numeric when at least 90% of its non-missing values parse as numbers
and it has more than three distinct non-missing values. Otherwise it is treated
as text/category.

This is a heuristic, not a human semantic type system. Numeric identifiers may
therefore be represented as numeric quantities.

## 11. How does TF-IDF weighting work?

- Term frequency rewards a term that appears within the current row document.
- Inverse document frequency reduces the importance of terms appearing in many
  rows.
- Terms occurring once are removed in production.
- Terms occurring in more than 90% of sampled rows are removed.
- At most 350 terms are retained.

The production formula is:

```text
tf = count in row / all retained token counts in row
idf = log((1 + number of rows) / (1 + rows containing term)) + 1
tfidf = tf * idf
```

## 12. How is the number of clusters chosen?

When the user does not set `k`, production uses a heuristic based on sample size
and minimum group size, capped at eight clusters. Approximately:

```text
k = min(8, rows / minimum group size, sqrt(rows) / 2)
```

This is a UI-oriented heuristic. It has not been proven to be the optimal
semantic cluster count.

## 13. Why K-means?

Good answer:

> K-means is deterministic in Buckaroo, fast enough for an interactive preview,
> simple to explain, and assigns every sampled row. It is the production
> baseline, not a claim that every dataset is naturally spherical or that
> K-means is universally best.

## 14. What are the alternative clustering types?

### KMeans and MiniBatchKMeans: partitioning

- Require `k`.
- Assign every row.
- Fast and scalable.
- Favor centroid-shaped groups.

### Agglomerative: hierarchical

- Repeatedly merges similar groups.
- Can use a requested cluster count or distance threshold.
- Can reveal nested structure.
- More expensive and can produce many tiny groups.

### DBSCAN/HDBSCAN/OPTICS: density-based

- Can discover irregularly shaped dense regions.
- Can label uncertain rows as noise.
- Do not always require `k`.
- Sensitive to density parameters, especially in sparse high-dimensional space.

### Exact slices: deterministic baseline

- Groups exact values or numeric bins.
- Very interpretable.
- Cannot merge approximate synonyms or near values naturally.

## 15. Are the current clusters semantic or erroneous?

Both ideas appear at different stages:

1. Similarity is created from numeric and lexical/category evidence, so cluster
   formation is semantic in that limited sense.
2. A cluster is currently returned only if it contains enough detector errors.
3. Clusters are ranked by error lift, support, and coverage.

The precise phrase is:

> semantic clustering with error-conditioned reporting.

A pure semantic mode should retain and evaluate coherent clusters even when
they contain no detected errors.

## 16. What does error lift mean?

If 10% of all sampled rows have errors but 40% of a cluster has errors:

```text
lift = 40% / 10% = 4x
```

The cluster is four times as error-heavy as the sample baseline. Lift is not
semantic accuracy.

## 17. Why is error-first always near 100% error rate?

Because error-first removes clean rows before clustering. Its input already
contains only error rows. It is a diagnostic organization method, not a fair
estimate of elevated risk relative to clean rows.

## 18. What do the experiment winners mean?

Say:

> In the 13-file parameter sweep, Agglomerative was selected for seven files,
> KMeans for four, and DBSCAN for two under the implemented error-discovery
> score. Several files were copies or variants, and the score was not human
> semantic ground truth, so this supports dataset-dependent algorithm choice but
> not universal Agglomerative superiority.

## 19. Why can a dataset with every row flagged be a problem?

If every row is erroneous, baseline error rate is 100%. Every cluster also has
at most 100% error rate, so lift is at most 1.0. Error lift cannot distinguish
useful clusters in that dataset. Semantic geometry and human interpretation must
be evaluated separately.

## 20. What did the runtime experiments reveal?

Historical CPU artifacts show that:

- TF-IDF plus numeric feature construction and KMeans commonly completed in a
  few seconds for samples from roughly 5,000 to 30,000 rows;
- MiniBatchKMeans reduced the clustering phase substantially after the same
  feature construction; and
- SBERT feature construction was tens to hundreds of seconds in preserved CPU
  runs.

These are preliminary historical timings because the original environment and
repetitions were not stored.

## 21. Why not claim SBERT is worse?

Runtime and semantic quality are different. SBERT was slower in preserved CPU
runs, but no human semantic benchmark proved it less accurate. The defensible
claim is "SBERT incurred higher feature-construction cost," not "SBERT was
worse."

## 22. What is the current strongest limitation?

A strong answer is:

> The largest methodological limitation is that semantic quality and
> detector-error utility are currently mixed. The next study must independently
> measure cluster coherence/stability and then evaluate whether those clusters
> also concentrate useful errors.

Sampling order bias and missing human cluster labels are close secondary
limitations.

## 23. What should happen next?

1. Replace first-ID sampling with seeded random sampling.
2. Add pure semantic reporting independent of detector errors.
3. Compare pooled TF-IDF against column-aware TF-IDF.
4. Repeat each sample condition across seeds.
5. Measure semantic geometry, resampling stability, runtime, and memory.
6. Add independent human ratings of cluster coherence and descriptions.
7. Tune methods on training datasets and report performance on held-out data.

## 24. Short glossary

| Term | Easy definition |
| --- | --- |
| Row vector | Numeric coordinates representing one table row |
| Feature matrix | All row vectors stacked into one table |
| TF-IDF | Weighting that emphasizes terms informative to a row and less common globally |
| Embedding | Learned numeric representation of meaning, such as SBERT output |
| L2 normalization | Scaling a vector to length one |
| Cosine similarity | Similarity based on vector direction |
| Centroid | Average vector representing a K-means cluster |
| `k` | Requested number of K-means clusters |
| Cluster | Group of similar represented rows |
| Noise row | Row a density algorithm declines to place in a cluster |
| Silhouette | Comparison of within-cluster closeness and nearest-cluster separation |
| Homogeneity | Whether each cluster mainly contains one reference label |
| Completeness | Whether rows with one reference label stay in the same cluster |
| V-measure | Harmonic combination of homogeneity and completeness |
| Lift | Group error rate divided by overall error rate |
| Coverage | Fraction of all error rows contained in a group |
| Stability | Whether similar clusters reappear across samples/seeds |
| ARI | Permutation-invariant similarity between two cluster assignments |
| Ablation | Removing one component to measure what it contributes |
| Coreset | Smaller weighted/selected subset used to approximate full-data fitting |
| Feature hashing | Mapping tokens into a fixed-width numeric representation without a vocabulary |

## 25. Phrases to avoid

Avoid these statements:

- "TF-IDF understands meaning."
- "We use every row."
- "K-means compares every row with every other row."
- "Agglomerative was proven best."
- "Thirteen independent datasets were tested."
- "The Meta strategy is the adaptive selector."
- "Error lift is clustering accuracy."
- "SBERT was less accurate."

Use the qualified explanations in this guide instead.
