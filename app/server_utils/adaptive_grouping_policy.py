"""Dataset-driven decision helpers for profiler-guided row grouping.

These helpers intentionally avoid semantic ground-truth labels. They use only
the current sample's distributions, repeated-run stability, and candidate-score
separation. That makes them suitable for an automatic first-stage policy, while
leaving human-rated semantic usefulness as a later external evaluation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class AdaptiveDatasetPolicy:
    """Dataset-derived cutoffs used while generating grouping candidates."""

    profile_confidence_cutoff: float
    min_group_size: int
    min_group_source: str
    confidence_source: str
    repeated_support_observations: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PartitionDiagnostics:
    """Comparable quality signals for one candidate row partition."""

    stability: float
    coherence: float
    distinctiveness: float
    balance: float
    assigned_fraction: float
    score: float
    cluster_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def finite_values(values: Iterable[float]) -> np.ndarray:
    array = np.asarray(list(values), dtype=float)
    return array[np.isfinite(array)]


def natural_break_threshold(values: Iterable[float]) -> float | None:
    """Return the one-dimensional split with maximum between-class variance.

    This is the same objective used by Otsu-style thresholding. It discovers a
    separation in the observed distribution rather than asking for a universal
    confidence, score, or similarity cutoff.
    """
    array = finite_values(values)
    if array.size == 0:
        return None
    unique = np.unique(array)
    if unique.size == 1:
        return None

    candidates = (unique[:-1] + unique[1:]) / 2.0
    best_threshold = float(candidates[0])
    best_score = -math.inf
    for threshold in candidates:
        lower = array[array <= threshold]
        upper = array[array > threshold]
        if not len(lower) or not len(upper):
            continue
        lower_weight = len(lower) / len(array)
        upper_weight = len(upper) / len(array)
        score = lower_weight * upper_weight * float((lower.mean() - upper.mean()) ** 2)
        if score > best_score:
            best_score = score
            best_threshold = float(threshold)
    return best_threshold


def robust_upper_fence(values: Iterable[float]) -> float | None:
    """Return a Tukey upper fence bounded by the observed data maximum."""
    array = finite_values(values)
    if array.size == 0:
        return None
    q1, q3 = np.quantile(array, [0.25, 0.75])
    spread = q3 - q1
    if not np.isfinite(spread) or spread <= 0:
        return float(np.max(array))
    return float(min(np.max(array), q3 + (1.5 * spread)))


def adaptive_clip_bound(standardized_values: Iterable[float]) -> float:
    """Choose robust winsorization from the observed standardized tail."""
    absolute = np.abs(finite_values(standardized_values))
    if absolute.size == 0:
        return 1.0
    fence = robust_upper_fence(absolute)
    if fence is None or not np.isfinite(fence) or fence <= 0:
        return 1.0
    return float(max(np.finfo(float).eps, fence))


def adaptive_token_limit(token_counts: Iterable[int], *, safety_cap: int = 512) -> int:
    """Keep the observed robust text-length range, with a resource-only cap."""
    counts = finite_values(token_counts)
    counts = counts[counts > 0]
    if counts.size == 0:
        return 1
    fence = robust_upper_fence(counts)
    observed_limit = int(math.ceil(fence if fence is not None else counts.max()))
    return max(1, min(int(safety_cap), observed_limit))


def adaptive_profile_confidence_cutoff(confidences: Iterable[float]) -> tuple[float, str]:
    values = finite_values(confidences)
    if values.size == 0:
        return 0.0, "no confidence distribution; retain data-derived fallback profiles"
    if np.unique(values).size == 1:
        return float(values[0]), "all observed confidences are equal"
    threshold = natural_break_threshold(values)
    if threshold is None:
        return float(values.min()), "all observed confidences retained"
    return float(threshold), "maximum between-class variance in profiler confidences"


def repeated_value_supports(
    frame: pd.DataFrame,
    profile_map: dict[str, dict],
) -> list[int]:
    supports: list[int] = []
    row_count = len(frame)
    for column, profile in profile_map.items():
        if column not in frame or profile.get("family") in {"identifier", "text"}:
            continue
        values = frame[column].dropna().astype(str).str.strip().str.lower()
        if values.empty:
            continue
        for count in values.value_counts().tolist():
            count = int(count)
            if 1 < count < row_count:
                supports.append(count)
    return supports


def adaptive_min_group_size(
    frame: pd.DataFrame,
    profile_map: dict[str, dict],
    requested: int | None,
) -> tuple[int, str, int]:
    if requested is not None:
        return max(2, int(requested)), "explicit caller override", 0
    row_count = len(frame)
    if row_count <= 2:
        return max(1, row_count), "all available rows", 0

    supports = repeated_value_supports(frame, profile_map)
    if not supports:
        return 2, "structural repeated-pattern floor", 0

    log_supports = np.log1p(np.asarray(supports, dtype=float))
    split = natural_break_threshold(log_supports)
    proposed = int(round(np.expm1(split))) if split is not None else min(supports)
    # The square-root ceiling scales with the sample and prevents a common
    # category from making every smaller but repeated pattern disappear.
    sample_ceiling = max(2, int(math.ceil(math.sqrt(row_count))))
    group_size = max(2, min(proposed, sample_ceiling, row_count // 2))
    return group_size, "natural break in repeated value frequencies", len(supports)


def adaptive_observed_group_support(group_sizes: Iterable[int], row_count: int) -> int:
    """Derive recurrence support from the observed candidate-size distribution."""
    sizes = finite_values(group_sizes)
    sizes = sizes[(sizes >= 2) & (sizes < max(2, row_count))]
    if sizes.size == 0:
        return 2
    split = natural_break_threshold(np.log1p(sizes))
    proposed = int(round(np.expm1(split))) if split is not None else int(sizes.min())
    return max(2, min(proposed, int(sizes.max())))


def build_dataset_policy(
    frame: pd.DataFrame,
    profile_map: dict[str, dict],
    *,
    requested_min_group_size: int | None,
) -> AdaptiveDatasetPolicy:
    cutoff, confidence_source = adaptive_profile_confidence_cutoff(
        profile.get("confidence", np.nan) for profile in profile_map.values()
    )
    minimum, support_source, observations = adaptive_min_group_size(
        frame,
        profile_map,
        requested_min_group_size,
    )
    return AdaptiveDatasetPolicy(
        profile_confidence_cutoff=float(np.clip(cutoff, 0.0, 1.0)),
        min_group_size=int(minimum),
        min_group_source=support_source,
        confidence_source=confidence_source,
        repeated_support_observations=int(observations),
    )


def adaptive_k_candidates(
    row_count: int,
    unique_row_count: int,
    min_group_size: int,
) -> list[int]:
    if row_count < 2 or unique_row_count < 2:
        return [1]
    support_bound = max(2, row_count // max(2, min_group_size))
    complexity_bound = max(2, int(math.ceil(math.log2(max(2, unique_row_count)))))
    upper = max(2, min(unique_row_count, support_bound, complexity_bound))
    return list(range(2, upper + 1))


def matched_partition_stability(labels: np.ndarray, alternate: np.ndarray) -> float:
    weighted = 0.0
    total = 0
    for label in set(np.asarray(labels).tolist()) - {-1}:
        members = set(np.flatnonzero(labels == label).tolist())
        if not members:
            continue
        best = 0.0
        for other in set(np.asarray(alternate).tolist()) - {-1}:
            candidate = set(np.flatnonzero(alternate == other).tolist())
            union = members | candidate
            if union:
                best = max(best, len(members & candidate) / len(union))
        weighted += len(members) * best
        total += len(members)
    return float(weighted / total) if total else 0.0


def partition_diagnostics(
    matrix: np.ndarray,
    labels: np.ndarray,
    alternate: np.ndarray,
) -> PartitionDiagnostics:
    labels = np.asarray(labels)
    real_labels = sorted(set(labels.tolist()) - {-1})
    if len(real_labels) < 2:
        return PartitionDiagnostics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, len(real_labels))

    sizes = np.asarray([int((labels == label).sum()) for label in real_labels], dtype=float)
    assigned = float(sizes.sum() / max(1, len(labels)))
    probabilities = sizes / sizes.sum()
    balance = float(-(probabilities * np.log(probabilities)).sum() / math.log(len(probabilities)))

    centroids = []
    coherence_values = []
    coherence_weights = []
    for label, size in zip(real_labels, sizes):
        members = matrix[labels == label]
        centroid = members.mean(axis=0)
        norm = np.linalg.norm(centroid)
        centroid = centroid / norm if norm else centroid
        centroids.append(centroid)
        similarities = members @ centroid
        coherence_values.append(float(np.mean((similarities + 1.0) / 2.0)))
        coherence_weights.append(size)
    coherence = float(np.average(coherence_values, weights=coherence_weights))

    centroid_matrix = np.vstack(centroids)
    similarity = centroid_matrix @ centroid_matrix.T
    np.fill_diagonal(similarity, -np.inf)
    nearest = np.max(similarity, axis=1)
    per_cluster_distinctiveness = 1.0 - ((nearest + 1.0) / 2.0)
    # Upper quantile, not the plain mean, of per-cluster distinctiveness. Found
    # live: on a duplicate-dense dataset, raising k mostly means subdividing the
    # numerically-dominant near-duplicate majority into more near-identical
    # fragments -- each new fragment sits close to its siblings by construction,
    # so the MEAN falls steeply with k almost regardless of whether a genuinely
    # separated minority cluster (e.g. a small but real high-value segment) is
    # also present in that same partition. The old formula could never reward
    # revealing that minority cluster: its high distinctiveness got diluted by
    # every mediocre near-duplicate fragment alongside it, and k=2 (one big
    # undifferentiated blob) always won on score. The upper quantile instead
    # asks "does this partition contain at least one well-separated cluster",
    # which is what actually matters for deciding whether raising k reveals real
    # structure -- while still correctly penalizing meaningless over-segmentation
    # of an ordinary, non-duplicate-dense dataset (spurious splits of one real
    # cluster are all mutually close, including the "best" one, so the upper
    # quantile stays low there too). 0.75 is a fixed quantile, not a per-dataset
    # tuned threshold -- the same category as the numeric IQR (0.75/0.25) used
    # throughout this file for robust scaling, applied here to cluster-pair
    # similarities instead of raw values.
    distinctiveness = float(np.quantile(per_cluster_distinctiveness, 0.75))
    stability = matched_partition_stability(labels, alternate)

    components = np.clip(
        np.asarray([stability, coherence, distinctiveness, balance, assigned], dtype=float),
        np.finfo(float).eps,
        1.0,
    )
    score = float(np.exp(np.log(components).mean()))
    return PartitionDiagnostics(
        stability=float(np.clip(stability, 0.0, 1.0)),
        coherence=float(np.clip(coherence, 0.0, 1.0)),
        distinctiveness=float(np.clip(distinctiveness, 0.0, 1.0)),
        balance=float(np.clip(balance, 0.0, 1.0)),
        assigned_fraction=float(np.clip(assigned, 0.0, 1.0)),
        score=float(np.clip(score, 0.0, 1.0)),
        cluster_count=len(real_labels),
    )


def empirical_percentile_scores(values: Iterable[float]) -> list[float]:
    array = finite_values(values)
    if array.size == 0:
        return []
    if np.unique(array).size == 1:
        return [1.0] * len(array)
    order = pd.Series(array).rank(method="average").to_numpy(dtype=float)
    return ((order - 1.0) / (len(array) - 1.0)).tolist()


def score_separation(values: Iterable[float]) -> dict[str, float | bool | None]:
    array = np.sort(finite_values(values))[::-1]
    if array.size == 0:
        return {"topScore": None, "runnerUpScore": None, "gap": None, "separated": False}
    if array.size == 1:
        return {"topScore": float(array[0]), "runnerUpScore": None, "gap": None, "separated": True}
    gap = float(array[0] - array[1])
    if array.size == 2:
        return {
            "topScore": float(array[0]),
            "runnerUpScore": float(array[1]),
            "gap": gap,
            "separated": False,
        }
    threshold = natural_break_threshold(array)
    separated = bool(threshold is not None and array[0] > threshold >= array[1])
    return {
        "topScore": float(array[0]),
        "runnerUpScore": float(array[1]),
        "gap": gap,
        "separated": separated,
    }
