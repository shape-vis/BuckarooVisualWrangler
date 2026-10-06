"""
Adaptive semantic clustering selector experiment for Buckaroo.

This script turns the meeting idea into an experiment:

1. Build a small set of feature spaces for the sampled dataset.
2. Run multiple clustering candidates across those feature spaces.
3. Reject degenerate or low-usefulness outputs.
4. Score the remaining candidates with error lift, coverage, cluster quality,
   runtime, and stability penalties.
5. Select one strategy for the dataset and write an auditable report.

Run:
    python experiments/adaptive_semantic_selector.py --dataset provided_datasets/adult.csv
    python experiments/adaptive_semantic_selector.py --multi-dataset --max-files 5
"""

from __future__ import annotations

# Standard-library imports used for command-line options, reporting, paths,
# timing, and lightweight data containers.
import argparse
from collections import Counter
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Callable

# Third-party data/science libraries. Pandas holds table-shaped data, NumPy
# holds numeric matrices, and sklearn provides the clustering algorithms.
import numpy as np
import pandas as pd
from sklearn.cluster import Birch, MiniBatchKMeans, OPTICS

# BisectingKMeans is useful when available, but older sklearn versions do not
# include it. The script treats it as optional so the rest of the experiment can
# still run on machines with older dependencies.
try:
    from sklearn.cluster import BisectingKMeans
except ImportError:  # Older sklearn versions do not expose this estimator.
    BisectingKMeans = None


# Resolve stable project paths from this file's location:
# - EXPERIMENTS_DIR is the experiments/ folder.
# - ROOT is the repository root.
EXPERIMENTS_DIR = Path(__file__).resolve().parent
ROOT = EXPERIMENTS_DIR.parent

# Add local folders to Python's import search path. This lets the script import
# both experiment utilities and Buckaroo application code when it is run from
# different working directories.
if str(EXPERIMENTS_DIR) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Reuse shared benchmark/sweep helpers instead of duplicating feature-building,
# detector-running, scoring, and report-writing utilities.
import semantic_parameter_sweeps as sweep


# Default output folders. Single-dataset runs and multi-dataset runs are kept
# separate so their reports do not overwrite each other.
DEFAULT_OUT_DIR = ROOT / "experiments" / "adaptive_selector_outputs"
DEFAULT_MULTI_OUT_DIR = ROOT / "experiments" / "adaptive_selector_outputs_multi"

# A very low score used for failed candidates. It keeps failed runs visible in
# the report while making sure they cannot accidentally win.
INVALID_SELECTOR_SCORE = -1_000_000.0


@dataclass(frozen=True)
class FeatureSpace:
    """Numeric representation of a dataset used as clustering input.

    A normal CSV has text, categories, numbers, and missing values. Clustering
    algorithms need a numeric matrix, so each FeatureSpace stores one converted
    version of the same sampled rows plus metadata explaining how it was built.
    """

    # Human-readable internal name, such as "tfidf_balanced" or
    # "sbert_row_embeddings".
    name: str

    # Broad feature type, such as "tfidf" or "sbert".
    kind: str

    # Numeric matrix passed to clustering algorithms. Rows correspond to sampled
    # table rows; columns correspond to computed features.
    matrix: np.ndarray

    # Details about the generated features, such as which columns contributed
    # text features or how many TF-IDF terms were created.
    feature_info: dict[str, Any]

    # Time spent building this feature space, in seconds. This is included in
    # scoring/reporting because expensive feature spaces affect responsiveness.
    feature_time_sec: float

    # Parameters used to build this feature space. Keeping them here makes the
    # experiment auditable and easier to reproduce.
    params: dict[str, Any]


@dataclass(frozen=True)
class CandidateSpec:
    """One clustering algorithm/settings combination to test.

    The selector compares many CandidateSpec objects across each FeatureSpace.
    Each candidate knows how to turn a feature matrix into cluster labels.
    """

    # Algorithm family name, such as "MiniBatchKMeans", "Birch", or "OPTICS".
    algorithm: str

    # Specific variant label, such as "k=8" or "threshold=0.45".
    variant: str

    # Exact algorithm parameters used for this candidate. These are written to
    # reports so the selected strategy can be explained later.
    params: dict[str, Any]

    # Function that receives a numeric feature matrix and returns one cluster
    # label per row. Example output: [0, 0, 1, 2, 1].
    label_fn: Callable[[np.ndarray], np.ndarray]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run adaptive semantic clustering selector experiments.")
    parser.add_argument("--dataset", type=Path, default=sweep.DEFAULT_DATASET)
    parser.add_argument("--multi-dataset", action="store_true", help="Run the selector across multiple CSV files.")
    parser.add_argument("--dataset-dir", type=Path, default=ROOT / "provided_datasets")
    parser.add_argument("--datasets", nargs="*", default=None, help="Optional CSV files or names inside --dataset-dir.")
    parser.add_argument("--max-files", type=int, default=10)
    parser.add_argument("--rows", type=int, default=sweep.DEFAULT_ROWS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--multi-out-dir", type=Path, default=DEFAULT_MULTI_OUT_DIR)
    parser.add_argument("--min-group-size", type=int, default=sweep.MIN_GROUP_SIZE)
    parser.add_argument("--min-error-rows", type=int, default=sweep.MIN_ERROR_ROWS)
    parser.add_argument("--include-sbert", action="store_true", help="Add SBERT candidates when the dataset is rich enough.")
    parser.add_argument("--sbert-model", default=sweep.DEFAULT_SBERT_MODEL)
    parser.add_argument("--sbert-max-rows", type=int, default=sweep.DEFAULT_SBERT_MAX_ROWS)
    parser.add_argument("--sbert-min-richness-score", type=float, default=sweep.DEFAULT_SBERT_MIN_RICHNESS_SCORE)
    parser.add_argument("--include-optics", action="store_true", help="Include slower OPTICS density candidates.")
    parser.add_argument("--max-largest-cluster-fraction", type=float, default=0.90)
    parser.add_argument("--max-noise-fraction", type=float, default=0.70)
    parser.add_argument("--max-small-cluster-row-fraction", type=float, default=0.60)
    return parser.parse_args()


def minibatch_kmeans_labels(k: int, matrix: np.ndarray) -> np.ndarray:
    safe_k = safe_cluster_count(k, matrix)
    if safe_k <= 1:
        return np.zeros(len(matrix), dtype=int)
    return MiniBatchKMeans(
        n_clusters=safe_k,
        random_state=sweep.RANDOM_STATE,
        n_init=10,
        batch_size=min(1024, max(32, len(matrix))),
    ).fit_predict(matrix)


def bisecting_kmeans_labels(k: int, matrix: np.ndarray) -> np.ndarray:
    if BisectingKMeans is None:
        raise RuntimeError("BisectingKMeans is not available in this sklearn version.")
    safe_k = safe_cluster_count(k, matrix)
    if safe_k <= 1:
        return np.zeros(len(matrix), dtype=int)
    return BisectingKMeans(
        n_clusters=safe_k,
        random_state=sweep.RANDOM_STATE,
    ).fit_predict(matrix)


def birch_labels(threshold: float, matrix: np.ndarray) -> np.ndarray:
    if len(matrix) == 0:
        return np.array([], dtype=int)
    return Birch(threshold=threshold, branching_factor=50, n_clusters=None).fit_predict(matrix)


def optics_labels(min_samples: int, xi: float, matrix: np.ndarray) -> np.ndarray:
    if len(matrix) < 3:
        return np.zeros(len(matrix), dtype=int)
    safe_min_samples = max(2, min(int(min_samples), len(matrix) - 1))
    return OPTICS(
        min_samples=safe_min_samples,
        xi=float(xi),
        cluster_method="xi",
        metric="cosine",
        n_jobs=-1,
    ).fit_predict(matrix)


def safe_cluster_count(k: int, matrix: np.ndarray) -> int:
    if len(matrix) == 0:
        return 0
    unique_rows = np.unique(matrix, axis=0).shape[0]
    return max(1, min(int(k), len(matrix), unique_rows))


def feature_specs_for_dataset(richness: dict[str, Any]) -> list[dict[str, Any]]:
    text_rich = float(richness.get("score", 0.0)) >= 0.35
    specs = [
        {
            "name": "tfidf_balanced",
            "max_text_features": 350,
            "numeric_weight": 0.75,
            "min_df": 2,
            "max_df_ratio": 0.90,
        },
        {
            "name": "tfidf_numeric_heavy",
            "max_text_features": 250,
            "numeric_weight": 1.25,
            "min_df": 2,
            "max_df_ratio": 0.90,
        },
        {
            "name": "tfidf_text_heavy",
            "max_text_features": 500,
            "numeric_weight": 0.35,
            "min_df": 2,
            "max_df_ratio": 0.95,
        },
    ]
    if text_rich:
        specs.append(
            {
                "name": "tfidf_loose_rich_text",
                "max_text_features": 1000,
                "numeric_weight": 0.50,
                "min_df": 1,
                "max_df_ratio": 0.98,
            }
        )
    return specs


def build_feature_spaces(
    df: pd.DataFrame,
    roles: dict[str, list[str]],
    richness: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[list[FeatureSpace], dict[str, Any]]:
    spaces: list[FeatureSpace] = []
    for spec in feature_specs_for_dataset(richness):
        matrix, feature_info, feature_time = sweep.build_feature_matrix(
            df,
            roles,
            max_text_features=int(spec["max_text_features"]),
            numeric_weight=float(spec["numeric_weight"]),
            min_df=int(spec["min_df"]),
            max_df_ratio=float(spec["max_df_ratio"]),
        )
        spaces.append(
            FeatureSpace(
                name=str(spec["name"]),
                kind="tfidf",
                matrix=matrix,
                feature_info=feature_info,
                feature_time_sec=float(feature_time),
                params={key: value for key, value in spec.items() if key != "name"},
            )
        )

    sbert_status = build_sbert_feature_space(df, roles, richness, args, spaces)
    return spaces, sbert_status


def build_sbert_feature_space(
    df: pd.DataFrame,
    roles: dict[str, list[str]],
    richness: dict[str, Any],
    args: argparse.Namespace,
    spaces: list[FeatureSpace],
) -> dict[str, Any]:
    status = {
        "requested": bool(args.include_sbert),
        "model": str(args.sbert_model),
        "max_rows": int(args.sbert_max_rows),
        "min_richness_score": float(args.sbert_min_richness_score),
        "richness_profile": richness,
    }
    if not args.include_sbert:
        status.update({"status": "disabled", "reason": "Pass --include-sbert to add SBERT candidates."})
        return status
    if len(df) > int(args.sbert_max_rows):
        status.update({"status": "skipped", "reason": f"Sample has {len(df)} rows, above SBERT row cap."})
        return status
    if float(richness.get("score", 0.0)) < float(args.sbert_min_richness_score):
        status.update({"status": "skipped", "reason": "Semantic richness score is below SBERT threshold."})
        return status
    if not roles.get("text"):
        status.update({"status": "skipped", "reason": "Dataset has no text/category columns."})
        return status

    try:
        matrix, feature_info, feature_time = sweep.build_sbert_feature_matrix(
            df,
            roles,
            model_name=str(args.sbert_model),
            richness_profile=richness,
        )
    except Exception as exc:
        status.update({"status": "failed", "reason": f"{type(exc).__name__}: {exc}"})
        return status

    spaces.append(
        FeatureSpace(
            name="sbert_row_embeddings",
            kind="sbert",
            matrix=matrix,
            feature_info=feature_info,
            feature_time_sec=float(feature_time),
            params={"model": str(args.sbert_model), "numeric_weight": 0.35, "embedding_weight": 1.0},
        )
    )
    status.update(
        {
            "status": "ran",
            "reason": "SBERT feature space added to selector candidates.",
            "feature_time_sec": round(float(feature_time), 4),
            "matrix_features": int(matrix.shape[1]),
        }
    )
    return status


def candidate_specs(row_count: int, min_group_size: int, include_optics: bool) -> list[CandidateSpec]:
    base_k = max(2, sweep.sg.default_cluster_count(row_count, min_group_size))
    k_values = sorted({max(2, base_k - 2), base_k, min(12, base_k + 2)})
    min_samples = sorted({max(4, min_group_size // 3), max(6, min_group_size // 2), min_group_size})

    specs: list[CandidateSpec] = []
    for k in k_values:
        specs.append(
            CandidateSpec(
                algorithm="KMeans",
                variant=f"k={k}",
                params={"k": k},
                label_fn=lambda matrix, k=k: sweep.kmeans_labels(k, matrix),
            )
        )
        specs.append(
            CandidateSpec(
                algorithm="MiniBatchKMeans",
                variant=f"k={k}",
                params={"k": k},
                label_fn=lambda matrix, k=k: minibatch_kmeans_labels(k, matrix),
            )
        )
        if BisectingKMeans is not None:
            specs.append(
                CandidateSpec(
                    algorithm="BisectingKMeans",
                    variant=f"k={k}",
                    params={"k": k},
                    label_fn=lambda matrix, k=k: bisecting_kmeans_labels(k, matrix),
                )
            )

    for eps in [0.25, 0.45, 0.65]:
        for min_sample in min_samples:
            specs.append(
                CandidateSpec(
                    algorithm="DBSCAN",
                    variant=f"eps={eps},min_samples={min_sample}",
                    params={"eps": eps, "min_samples": min_sample, "metric": "cosine"},
                    label_fn=lambda matrix, eps=eps, min_sample=min_sample: sweep.dbscan_labels(eps, min_sample, matrix),
                )
            )

    for k in k_values:
        specs.append(
            CandidateSpec(
                algorithm="Agglomerative",
                variant=f"k={k},linkage=average",
                params={"n_clusters": k, "metric": "cosine", "linkage": "average"},
                label_fn=lambda matrix, k=k: sweep.agglomerative_labels(matrix, n_clusters=k),
            )
        )

    for threshold in [0.30, 0.45]:
        specs.append(
            CandidateSpec(
                algorithm="Agglomerative",
                variant=f"distance_threshold={threshold}",
                params={"distance_threshold": threshold, "metric": "cosine", "linkage": "average"},
                label_fn=lambda matrix, threshold=threshold: sweep.agglomerative_labels(
                    matrix,
                    n_clusters=None,
                    distance_threshold=threshold,
                ),
            )
        )

    for threshold in [0.20, 0.35, 0.50]:
        specs.append(
            CandidateSpec(
                algorithm="Birch",
                variant=f"threshold={threshold}",
                params={"threshold": threshold},
                label_fn=lambda matrix, threshold=threshold: birch_labels(threshold, matrix),
            )
        )

    if include_optics:
        for min_sample in [max(6, min_group_size // 2), min_group_size]:
            specs.append(
                CandidateSpec(
                    algorithm="OPTICS",
                    variant=f"min_samples={min_sample},xi=0.05",
                    params={"min_samples": min_sample, "xi": 0.05, "metric": "cosine"},
                    label_fn=lambda matrix, min_sample=min_sample: optics_labels(min_sample, 0.05, matrix),
                )
            )

    return specs


def evaluate_candidate(
    space: FeatureSpace,
    candidate: CandidateSpec,
    df: pd.DataFrame,
    errors: pd.DataFrame,
    roles: dict[str, list[str]],
    issue_labels: np.ndarray,
    args: argparse.Namespace,
) -> dict[str, Any]:
    candidate_id = f"{space.name}:{candidate.algorithm}:{candidate.variant}"
    start = time.perf_counter()
    try:
        labels = np.asarray(candidate.label_fn(space.matrix))
        cluster_time = time.perf_counter() - start
    except Exception as exc:
        return failed_candidate_record(space, candidate, candidate_id, time.perf_counter() - start, exc)

    groups = sweep.summarize_labels(
        df,
        errors,
        roles,
        labels,
        method_name=f"adaptive_selector:{space.name}:{candidate.algorithm}",
        feature_info=space.feature_info,
        min_group_size=args.min_group_size,
        min_error_rows=args.min_error_rows,
    )
    stats = sweep.cluster_size_stats(labels)
    label_stats = label_distribution_stats(labels, args.min_group_size)
    top_groups = groups[: sweep.TOP_N]
    top = top_groups[0] if top_groups else None
    silhouette = sweep.safe_silhouette(space.matrix, labels)
    homogeneity = sweep.safe_label_metric(sweep.homogeneity_score, issue_labels, labels)
    completeness = sweep.safe_label_metric(sweep.completeness_score, issue_labels, labels)
    v_measure = sweep.safe_label_metric(sweep.v_measure_score, issue_labels, labels)
    tightness = sweep.centroid_tightness(space.matrix, labels)

    largest_cluster_fraction = (
        float(stats["largest_cluster"] / len(labels))
        if len(labels)
        else 0.0
    )
    noise_fraction = (
        float(stats["noise_rows"] / len(labels))
        if len(labels)
        else 0.0
    )
    total_time = float(space.feature_time_sec + cluster_time)
    mean_top5_score = round(float(np.mean([group.score for group in top_groups])), 6) if top_groups else 0.0
    mean_top5_lift = round(float(np.mean([group.lift for group in top_groups])), 6) if top_groups else 0.0
    top5_error_coverage = round(float(sum(group.errorCoverage for group in top_groups)), 6)

    rejection_reasons = rejection_reasons_for_record(
        raw_clusters=int(stats["raw_clusters"]),
        groups_returned=len(groups),
        top_error_rows=int(top.errorRows) if top else 0,
        largest_cluster_fraction=largest_cluster_fraction,
        noise_fraction=noise_fraction,
        small_cluster_row_fraction=label_stats["small_cluster_row_fraction"],
        args=args,
    )
    accepted = not rejection_reasons
    selector_score = selector_score_for_candidate(
        accepted=accepted,
        mean_top5_score=mean_top5_score,
        top_score=float(top.score) if top else 0.0,
        mean_top5_lift=mean_top5_lift,
        top5_error_coverage=top5_error_coverage,
        silhouette=silhouette,
        issue_homogeneity=homogeneity,
        centroid_tightness=tightness,
        largest_cluster_fraction=largest_cluster_fraction,
        noise_fraction=noise_fraction,
        small_cluster_row_fraction=label_stats["small_cluster_row_fraction"],
        total_time_sec=total_time,
    )

    return {
        "candidate_id": candidate_id,
        "feature_space": space.name,
        "feature_kind": space.kind,
        "algorithm": candidate.algorithm,
        "variant": candidate.variant,
        "feature_params": json.dumps(space.params, sort_keys=True),
        "algorithm_params": json.dumps(candidate.params, sort_keys=True),
        "matrix_rows": int(space.matrix.shape[0]),
        "matrix_features": int(space.matrix.shape[1]),
        "feature_time_sec": round(float(space.feature_time_sec), 4),
        "cluster_time_sec": round(float(cluster_time), 4),
        "total_time_sec": round(total_time, 4),
        "accepted": bool(accepted),
        "rejection_reason": "accepted" if accepted else "; ".join(rejection_reasons),
        "selector_score": round(float(selector_score), 6),
        "groups_returned": int(len(groups)),
        **stats,
        **label_stats,
        "largest_cluster_fraction": round(largest_cluster_fraction, 6),
        "noise_fraction": round(noise_fraction, 6),
        "silhouette_cosine": round_or_none(silhouette),
        "issue_homogeneity": round_or_none(homogeneity),
        "issue_completeness": round_or_none(completeness),
        "issue_v_measure": round_or_none(v_measure),
        "centroid_tightness": round_or_none(tightness),
        "top_score": top.score if top else 0.0,
        "top_lift": top.lift if top else 0.0,
        "top_error_rate": top.errorRate if top else 0.0,
        "top_rows": top.rows if top else 0,
        "top_error_rows": top.errorRows if top else 0,
        "top_error_coverage": top.errorCoverage if top else 0.0,
        "mean_top5_score": mean_top5_score,
        "mean_top5_lift": mean_top5_lift,
        "top5_error_coverage": top5_error_coverage,
        "top_issue": top.mainIssue if top else "none",
        "top_description": top.description if top else "none",
        "top_groups": [sweep.asdict(group) for group in top_groups],
    }


def failed_candidate_record(
    space: FeatureSpace,
    candidate: CandidateSpec,
    candidate_id: str,
    cluster_time: float,
    exc: Exception,
) -> dict[str, Any]:
    # This function is used when one clustering option crashes or cannot finish.
    #
    # Big picture:
    #   The selector tries many combinations, such as:
    #     - one feature space, like numeric/categorical/text embeddings
    #     - one clustering algorithm, like k-means or OPTICS
    #     - one parameter setting, like k=4 or k=8
    #
    # If one of those combinations fails, we do not want the whole experiment to
    # crash.  Instead, we save a normal-looking result row that says:
    #   "This candidate failed, here is why, and its score is invalid."
    #
    # That way the CSV still proves we attempted the candidate.
    return {
        # These fields identify exactly which candidate failed.
        # In easy words: this is the candidate's name tag.
        "candidate_id": candidate_id,
        "feature_space": space.name,
        "feature_kind": space.kind,
        "algorithm": candidate.algorithm,
        "variant": candidate.variant,

        # Store the feature and algorithm settings as JSON text so they fit
        # cleanly inside one CSV cell.
        # Example: {"k": 4} or {"max_features": 500}.
        "feature_params": json.dumps(space.params, sort_keys=True),
        "algorithm_params": json.dumps(candidate.params, sort_keys=True),

        # Matrix shape tells us how much data this candidate tried to cluster.
        # matrix_rows = number of rows/items being clustered.
        # matrix_features = number of columns/features after transformation.
        "matrix_rows": int(space.matrix.shape[0]),
        "matrix_features": int(space.matrix.shape[1]),

        # Timing fields separate feature-building time from clustering time.
        # This helps us explain whether a candidate was slow because of the
        # feature space or because of the clustering algorithm.
        "feature_time_sec": round(float(space.feature_time_sec), 4),
        "cluster_time_sec": round(float(cluster_time), 4),
        "total_time_sec": round(float(space.feature_time_sec + cluster_time), 4),

        # A failed candidate is never accepted by the selector.
        # The rejection reason includes the Python error type and message so we
        # can debug it later.
        "accepted": False,
        "rejection_reason": f"failed: {type(exc).__name__}: {exc}",

        # Give failed candidates a very bad score.  This keeps them at the
        # bottom of the ranking while still keeping them visible in the CSV.
        "selector_score": INVALID_SELECTOR_SCORE,

        # Since the candidate failed, it produced no usable clusters/groups.
        # These are all set to zero as safe placeholder values.
        "groups_returned": 0,
        "raw_clusters": 0,
        "noise_rows": 0,
        "smallest_cluster": 0,
        "largest_cluster": 0,
        "median_cluster": 0.0,
        "cluster_size_cv": 0.0,

        # These fields describe bad cluster shapes.
        # singleton_cluster_fraction = how many clusters have only 1 row.
        # small_cluster_fraction = how many clusters are smaller than the
        # configured minimum group size.
        # small_cluster_row_fraction = how many total rows are stuck inside
        # those too-small clusters.
        #
        # A failed candidate has no clusters, so all of these are zero.
        "singleton_cluster_fraction": 0.0,
        "small_cluster_fraction": 0.0,
        "small_cluster_row_fraction": 0.0,

        # largest_cluster_fraction checks whether one cluster swallowed almost
        # the whole dataset.  noise_fraction checks whether too many rows were
        # marked as "noise" instead of being assigned to real clusters.
        "largest_cluster_fraction": 0.0,
        "noise_fraction": 0.0,

        # These quality metrics only make sense when clustering succeeded.
        # Because this candidate failed, they are None.
        "silhouette_cosine": None,
        "issue_homogeneity": None,
        "issue_completeness": None,
        "issue_v_measure": None,
        "centroid_tightness": None,

        # The "top" fields describe the best group found by a candidate.
        # This is the section around line 583 that usually matters in the CSV:
        #
        #   top_score = quality score of the best returned group
        #   top_lift = how much more error-heavy the group is than baseline
        #   top_error_rate = percent of rows in that group with detector errors
        #   top_rows = number of rows in that group
        #   top_error_rows = number of error rows in that group
        #
        # A failed candidate found no groups, so every top-group metric is zero.
        "top_score": 0.0,
        "top_lift": 0.0,
        "top_error_rate": 0.0,
        "top_rows": 0,
        "top_error_rows": 0,
        "top_error_coverage": 0.0,

        # These are summary stats for the best five groups.  They are useful
        # because one lucky top group is less convincing than several good
        # groups.  Again, failed candidates have no groups, so all are zero.
        "mean_top5_score": 0.0,
        "mean_top5_lift": 0.0,
        "top5_error_coverage": 0.0,

        # Human-readable description fields for the best group.
        # Failed candidates do not have a best group, so we use "none".
        "top_issue": "none",
        "top_description": "none",
        "top_groups": [],
    }


def label_distribution_stats(labels: np.ndarray, min_group_size: int) -> dict[str, float]:
    # This function looks only at the cluster labels and asks:
    #   "Did the algorithm create a healthy set of groups?"
    #
    # It does not care yet whether the groups are meaningful.  It only checks
    # whether the group sizes are reasonable.
    labels = np.asarray(labels)

    # Some algorithms use label -1 for "noise".
    # Noise means: "I could not confidently put this row into a real cluster."
    # We remove noise here because we only want to measure real clusters.
    non_noise = labels[labels != -1]

    # If every row is noise, there are no real clusters to measure.
    # Return zeros so downstream code does not divide by zero.
    if non_noise.size == 0:
        return {
            "singleton_cluster_fraction": 0.0,
            "small_cluster_fraction": 0.0,
            "small_cluster_row_fraction": 0.0,
        }

    # Count how many rows each cluster has.
    # Example labels: [0, 0, 1, 1, 1, 2]
    # Cluster sizes would be: cluster 0 has 2 rows, cluster 1 has 3 rows,
    # cluster 2 has 1 row.
    sizes = np.array(list(Counter(non_noise.tolist()).values()), dtype=float)

    # Mark clusters as "small" if they are smaller than the allowed group size.
    # max(2, min_group_size) makes sure a one-row cluster is always considered
    # too small, even if min_group_size was accidentally set below 2.
    small = sizes < max(2, int(min_group_size))
    return {
        # Fraction of clusters that contain exactly one row.
        # Too many singletons means the algorithm is fragmenting the dataset.
        "singleton_cluster_fraction": round(float((sizes == 1).sum() / len(sizes)), 6),

        # Fraction of clusters that are below the minimum useful size.
        # This is a cluster-level view: "How many groups are too tiny?"
        "small_cluster_fraction": round(float(small.sum() / len(sizes)), 6),

        # Fraction of rows that are trapped inside too-small clusters.
        # This is a row-level view: "How much of the dataset is affected?"
        "small_cluster_row_fraction": round(float(sizes[small].sum() / max(1, non_noise.size)), 6),
    }


def rejection_reasons_for_record(
    *,
    raw_clusters: int,
    groups_returned: int,
    top_error_rows: int,
    largest_cluster_fraction: float,
    noise_fraction: float,
    small_cluster_row_fraction: float,
    args: argparse.Namespace,
) -> list[str]:
    # This function creates the plain-English reasons why a candidate should
    # not be trusted.
    #
    # Think of it as the selector's quality-control checklist.
    # If any check fails, we add a readable reason to the CSV/report.
    reasons = []

    # A clustering result with fewer than 2 real clusters is not useful because
    # there is nothing to compare.
    if raw_clusters < 2:
        reasons.append("fewer than two non-noise clusters")

    # The semantic grouping step may filter out clusters that are too small or
    # do not contain enough detector errors.  If none survive, the candidate is
    # not useful for the user.
    if groups_returned == 0:
        reasons.append("no useful groups after min-size/error filters")

    # The best group must contain enough actual error rows.  Otherwise it might
    # look interesting only because of a tiny sample.
    if top_error_rows < int(args.min_error_rows):
        reasons.append("top group has too few error rows")

    # If one cluster contains almost everything, the algorithm did not really
    # separate the dataset into meaningful groups.
    if largest_cluster_fraction >= float(args.max_largest_cluster_fraction):
        reasons.append("largest cluster dominates")

    # If too many rows are labeled noise, the algorithm failed to organize much
    # of the dataset.
    if noise_fraction >= float(args.max_noise_fraction):
        reasons.append("too many rows marked as noise")

    # If too many rows are in undersized clusters, the output will be too
    # fragmented to explain cleanly in the UI.
    if small_cluster_row_fraction >= float(args.max_small_cluster_row_fraction):
        reasons.append("too many rows are in undersized clusters")
    return reasons


def selector_score_for_candidate(
    *,
    accepted: bool,
    mean_top5_score: float,
    top_score: float,
    mean_top5_lift: float,
    top5_error_coverage: float,
    silhouette: float,
    issue_homogeneity: float,
    centroid_tightness: float,
    largest_cluster_fraction: float,
    noise_fraction: float,
    small_cluster_row_fraction: float,
    total_time_sec: float,
) -> float:
    # This function turns many quality signals into one final selector score.
    #
    # Easy explanation:
    #   Higher score = better candidate.
    #   The candidate gets bonuses for useful/error-heavy groups.
    #   The candidate gets penalties for messy clusters or slow runtime.
    #
    # The final score is not a perfect truth score.  It is a practical ranking
    # score so the selector can choose the most promising option automatically.
    if not accepted:
        # If the candidate failed the usefulness checks, punish it heavily.
        # This keeps rejected candidates below accepted candidates in the rank.
        base_penalty = 50.0
    else:
        base_penalty = 0.0

    # Lift means: "Is this group more error-heavy than the dataset baseline?"
    # A lift of 1.0 means no improvement over baseline.
    # A lift above 1.0 is useful, so we reward it.
    # min(..., 5.0) prevents one extreme number from dominating everything.
    lift_bonus = 1.5 * max(0.0, min(float(mean_top5_lift), 5.0) - 1.0)

    # Reward candidates whose top groups cover more of the dataset's error rows.
    # This prefers groups that explain real detector problems, not just tiny
    # isolated examples.
    coverage_bonus = 2.0 * float(top5_error_coverage)

    # Geometry metrics reward clusters that are separated or tight in feature
    # space.  These are helpful, but weighted lower than error-based metrics
    # because this project mainly cares about finding useful error groups.
    geometry_bonus = 0.35 * max(0.0, finite_or_zero(silhouette))
    issue_bonus = 0.75 * max(0.0, finite_or_zero(issue_homogeneity))
    tightness_bonus = 0.25 * max(0.0, finite_or_zero(centroid_tightness))

    # Penalize degenerate cluster shapes:
    #   - one giant cluster
    #   - too many noise rows
    #   - too many rows in tiny clusters
    #
    # These are signs that the clustering result would be hard to explain.
    imbalance_penalty = (
        1.5 * max(0.0, float(largest_cluster_fraction) - 0.60)
        + 1.0 * max(0.0, float(noise_fraction) - 0.35)
        + 0.75 * float(small_cluster_row_fraction)
    )

    # Runtime penalty gently prefers faster candidates.
    # The cap prevents runtime from completely overpowering quality.
    runtime_penalty = 0.20 * min(float(total_time_sec) / 30.0, 2.0)

    # Final ranking formula:
    #   group quality
    # + error lift and coverage bonuses
    # + cluster geometry bonuses
    # - messy-cluster penalties
    # - runtime penalty
    # - rejected-candidate penalty
    return (
        float(mean_top5_score)
        + 0.25 * float(top_score)
        + lift_bonus
        + coverage_bonus
        + geometry_bonus
        + issue_bonus
        + tightness_bonus
        - imbalance_penalty
        - runtime_penalty
        - base_penalty
    )


def finite_or_zero(value: float | None) -> float:
    if value is None:
        return 0.0
    try:
        if not math.isfinite(float(value)):
            return 0.0
    except (TypeError, ValueError):
        return 0.0
    return float(value)


def round_or_none(value: float) -> float | None:
    if not math.isfinite(float(value)):
        return None
    return round(float(value), 6)


def select_adaptive_candidate(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {
            "selection_basis": "no_candidates",
            "accepted_count": 0,
            "rejected_count": 0,
            "selected": None,
        }

    accepted = [record for record in records if record["accepted"]]
    if accepted:
        pool = accepted
        basis = "accepted_candidates"
    else:
        pool = [
            record
            for record in records
            if record["raw_clusters"] >= 2
            and record["groups_returned"] > 0
            and not str(record["rejection_reason"]).startswith("failed:")
        ]
        basis = "non_degenerate_fallback"
        if not pool:
            pool = [record for record in records if not str(record["rejection_reason"]).startswith("failed:")]
            basis = "all_non_failed_fallback"
        if not pool:
            pool = records
            basis = "all_candidates_fallback"

    selected = max(pool, key=lambda record: (record["selector_score"], record["mean_top5_score"], record["top_score"]))
    return {
        "selection_basis": basis,
        "accepted_count": len(accepted),
        "rejected_count": len(records) - len(accepted),
        "candidate_count": len(records),
        "selected_candidate_id": selected["candidate_id"],
        "selected": selected,
    }


def rank_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(
        records,
        key=lambda record: (
            bool(record["accepted"]),
            float(record["selector_score"]),
            float(record["mean_top5_score"]),
            float(record["top_score"]),
        ),
        reverse=True,
    )
    for idx, record in enumerate(ranked, start=1):
        record["selector_rank"] = idx
    return ranked


def run_selector_on_dataset(
    dataset_path: Path,
    args: argparse.Namespace,
    out_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    dataset_path = dataset_path.resolve()
    dataset_name = sweep.slugify_dataset_name(dataset_path)

    print(f"Loading dataset {dataset_path} rows={args.rows}")
    load_start = time.perf_counter()
    df = sweep.load_dataset(dataset_path, args.rows)
    load_time = time.perf_counter() - load_start

    print("Running Buckaroo detectors...")
    detector_start = time.perf_counter()
    errors = sweep.run_detectors_direct(df)
    detector_time = time.perf_counter() - detector_start

    df = sweep.attach_error_flags(df, errors)
    roles = sweep.sg.infer_column_roles(df)
    issue_labels = sweep.dominant_issue_labels(df, errors)
    richness = sweep.semantic_richness_profile(df, roles)

    print("Building feature spaces...")
    feature_spaces, sbert_status = build_feature_spaces(df, roles, richness, args)
    specs = candidate_specs(len(df), int(args.min_group_size), bool(args.include_optics))

    print(f"Evaluating {len(feature_spaces) * len(specs)} selector candidates...")
    records = []
    for space in feature_spaces:
        for spec in specs:
            records.append(evaluate_candidate(space, spec, df, errors, roles, issue_labels, args))

    ranked_records = rank_records(records)
    selection = select_adaptive_candidate(ranked_records)
    selected = selection.get("selected")

    meta = {
        "dataset_name": dataset_name,
        "dataset": str(dataset_path),
        "source_file": dataset_path.name,
        "requested_rows": int(args.rows),
        "rows": int(len(df)),
        "error_records": int(len(errors)),
        "error_rows": int(df["_buckaroo_has_error"].sum()),
        "baseline_error_rate": float(df["_buckaroo_has_error"].mean()) if len(df) else 0.0,
        "numeric_columns": roles["numeric"],
        "text_columns": roles["text"],
        "semantic_richness": richness,
        "sbert_status": sbert_status,
        "feature_spaces": [
            {
                "name": space.name,
                "kind": space.kind,
                "matrix_features": int(space.matrix.shape[1]),
                "feature_time_sec": round(float(space.feature_time_sec), 4),
                "params": space.params,
            }
            for space in feature_spaces
        ],
        "candidate_specs": len(specs),
        "load_time_sec": round(load_time, 4),
        "detector_time_sec": round(detector_time, 4),
        "min_group_size": int(args.min_group_size),
        "min_error_rows": int(args.min_error_rows),
        "selector_thresholds": {
            "max_largest_cluster_fraction": float(args.max_largest_cluster_fraction),
            "max_noise_fraction": float(args.max_noise_fraction),
            "max_small_cluster_row_fraction": float(args.max_small_cluster_row_fraction),
        },
    }

    for record in ranked_records:
        record["dataset_name"] = dataset_name
        record["dataset_file"] = dataset_path.name
        record["dataset_path"] = str(dataset_path)

    print("Selected candidate:")
    print(
        json.dumps(
            {
                "basis": selection["selection_basis"],
                "candidate_id": selection.get("selected_candidate_id"),
                "selector_score": selected.get("selector_score") if selected else None,
                "accepted": selected.get("accepted") if selected else None,
                "top_description": selected.get("top_description") if selected else None,
            },
            indent=2,
        )
    )

    write_dataset_outputs(out_dir, meta, selection, ranked_records)
    print(f"Wrote adaptive selector outputs to: {out_dir}")
    return meta, selection, ranked_records


def write_dataset_outputs(
    out_dir: Path,
    meta: dict[str, Any],
    selection: dict[str, Any],
    records: list[dict[str, Any]],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    slim_records = [{key: value for key, value in record.items() if key != "top_groups"} for record in records]
    pd.DataFrame(slim_records).to_csv(out_dir / "adaptive_selector_candidates.csv", index=False)
    with open(out_dir / "adaptive_selector_results.json", "w", encoding="utf-8") as f:
        json.dump(sweep.json_safe({"meta": meta, "selection": selection, "candidates": records}), f, indent=2)
    (out_dir / "adaptive_selector_report.md").write_text(
        build_dataset_report(meta, selection, records),
        encoding="utf-8",
    )


def build_dataset_report(meta: dict[str, Any], selection: dict[str, Any], records: list[dict[str, Any]]) -> str:
    selected = selection.get("selected") or {}
    frame = pd.DataFrame([{key: value for key, value in record.items() if key != "top_groups"} for record in records])
    top_candidates = frame.head(15)[
        [
            "selector_rank",
            "accepted",
            "feature_space",
            "algorithm",
            "variant",
            "selector_score",
            "rejection_reason",
            "groups_returned",
            "raw_clusters",
            "noise_fraction",
            "largest_cluster_fraction",
            "top_lift",
            "mean_top5_score",
            "top5_error_coverage",
            "silhouette_cosine",
            "issue_homogeneity",
            "total_time_sec",
        ]
    ]
    top_groups = selected.get("top_groups") or []
    top_groups_frame = pd.DataFrame(
        [
            {
                "group": group.get("group"),
                "description": group.get("description"),
                "rows": group.get("rows"),
                "errorRows": group.get("errorRows"),
                "lift": group.get("lift"),
                "score": group.get("score"),
                "mainIssue": group.get("mainIssue"),
            }
            for group in top_groups
        ]
    )

    sections = [
        "# Adaptive Semantic Selector Report",
        "",
        "## Dataset",
        f"- Dataset: `{meta['source_file']}`",
        f"- Rows tested: {meta['rows']}",
        f"- Detector records: {meta['error_records']}",
        f"- Rows with at least one detector error: {meta['error_rows']}",
        f"- Baseline row error rate: {meta['baseline_error_rate']:.1%}",
        f"- Semantic richness score: {meta['semantic_richness']['score']}",
        f"- SBERT status: {meta['sbert_status']['status']} ({meta['sbert_status']['reason']})",
        "",
        "## Selected Strategy",
        f"- Selection basis: `{selection['selection_basis']}`",
        f"- Candidate: `{selected.get('candidate_id', 'none')}`",
        f"- Accepted: {selected.get('accepted', False)}",
        f"- Selector score: {selected.get('selector_score', 'n/a')}",
        f"- Rejection status: {selected.get('rejection_reason', 'n/a')}",
        f"- Top issue: `{selected.get('top_issue', 'none')}`",
        f"- Top description: {selected.get('top_description', 'none')}",
        "",
        "## Selector Rules",
        "- Reject candidates with fewer than two non-noise clusters, no useful groups, a dominating largest cluster, too much noise, too many undersized-cluster rows, or too few error rows in the top group.",
        "- Score accepted candidates using mean top-5 group score, top score, lift, error coverage, issue homogeneity, silhouette, centroid tightness, runtime, and imbalance penalties.",
        "- If every candidate is rejected, choose the best non-degenerate fallback and mark the selection basis accordingly.",
        "",
        "## Top Candidate Ranking",
        sweep.markdown_table(top_candidates),
        "",
        "## Rejection Summary",
        sweep.markdown_table(rejection_summary_frame(records)),
        "",
        "## Selected Top Groups",
        sweep.markdown_table(top_groups_frame) if not top_groups_frame.empty else "_No groups._",
        "",
    ]
    return "\n".join(sections)


def rejection_summary_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    counts: Counter[str] = Counter()
    for record in records:
        reason = str(record.get("rejection_reason", "unknown"))
        if reason == "accepted":
            counts["accepted"] += 1
            continue
        for part in reason.split("; "):
            counts[part] += 1
    return pd.DataFrame(
        [{"reason": reason, "count": count} for reason, count in counts.most_common()]
    )


def summarize_dataset(meta: dict[str, Any], selection: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    selected = selection.get("selected") or {}
    return {
        "dataset_name": meta["dataset_name"],
        "source_file": meta["source_file"],
        "rows": meta["rows"],
        "error_rows": meta["error_rows"],
        "baseline_error_rate": meta["baseline_error_rate"],
        "semantic_richness_score": meta["semantic_richness"]["score"],
        "sbert_status": meta["sbert_status"]["status"],
        "candidate_count": selection.get("candidate_count", 0),
        "accepted_count": selection.get("accepted_count", 0),
        "rejected_count": selection.get("rejected_count", 0),
        "selection_basis": selection.get("selection_basis"),
        "selected_candidate_id": selected.get("candidate_id", "none"),
        "selected_feature_space": selected.get("feature_space", "none"),
        "selected_algorithm": selected.get("algorithm", "none"),
        "selected_variant": selected.get("variant", "none"),
        "selected_selector_score": selected.get("selector_score", np.nan),
        "selected_top_lift": selected.get("top_lift", np.nan),
        "selected_mean_top5_score": selected.get("mean_top5_score", np.nan),
        "selected_top5_error_coverage": selected.get("top5_error_coverage", np.nan),
        "selected_top_issue": selected.get("top_issue", "none"),
        "selected_rejection_reason": selected.get("rejection_reason", "none"),
        "report_path": str(out_dir / "adaptive_selector_report.md"),
        "csv_path": str(out_dir / "adaptive_selector_candidates.csv"),
        "json_path": str(out_dir / "adaptive_selector_results.json"),
    }


def run_multi_dataset(args: argparse.Namespace) -> None:
    dataset_files = sweep.discover_dataset_files(args.dataset_dir, args.datasets, args.max_files)
    print("Adaptive selector multi-dataset files:")
    for idx, dataset_path in enumerate(dataset_files, start=1):
        print(f"  {idx}. {dataset_path}")

    summaries = []
    all_records = []
    per_dataset_root = args.multi_out_dir / "per_dataset"
    for idx, dataset_path in enumerate(dataset_files, start=1):
        print(f"\n=== Dataset {idx}/{len(dataset_files)}: {dataset_path.name} ===")
        dataset_out_dir = per_dataset_root / sweep.slugify_dataset_name(dataset_path)
        try:
            meta, selection, records = run_selector_on_dataset(dataset_path, args, dataset_out_dir)
            summaries.append(summarize_dataset(meta, selection, dataset_out_dir))
            all_records.extend(records)
        except Exception as exc:
            failure = {
                "dataset_name": sweep.slugify_dataset_name(dataset_path),
                "source_file": dataset_path.name,
                "error": f"{type(exc).__name__}: {exc}",
                "report_path": "",
                "csv_path": "",
                "json_path": "",
            }
            summaries.append(failure)
            print(f"FAILED {dataset_path}: {failure['error']}")

    write_multi_outputs(args.multi_out_dir, summaries, all_records, args)
    print(f"\nWrote adaptive multi-dataset outputs to: {args.multi_out_dir}")
    print(pd.DataFrame(summaries).to_string(index=False))


def write_multi_outputs(
    out_dir: Path,
    summaries: list[dict[str, Any]],
    records: list[dict[str, Any]],
    args: argparse.Namespace,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_frame = pd.DataFrame(summaries)
    candidate_frame = pd.DataFrame([{key: value for key, value in record.items() if key != "top_groups"} for record in records])
    summary_frame.to_csv(out_dir / "combined_adaptive_selector_summary.csv", index=False)
    candidate_frame.to_csv(out_dir / "combined_adaptive_selector_candidates.csv", index=False)
    with open(out_dir / "combined_adaptive_selector_results.json", "w", encoding="utf-8") as f:
        json.dump(
            sweep.json_safe(
                {
                    "run": {
                        "dataset_dir": str(args.dataset_dir),
                        "rows": int(args.rows),
                        "file_count": len(summaries),
                        "include_sbert": bool(args.include_sbert),
                        "include_optics": bool(args.include_optics),
                    },
                    "dataset_summaries": summaries,
                    "candidates": records,
                }
            ),
            f,
            indent=2,
        )
    (out_dir / "combined_adaptive_selector_report.md").write_text(
        build_multi_report(summary_frame, args),
        encoding="utf-8",
    )


def build_multi_report(summary_frame: pd.DataFrame, args: argparse.Namespace) -> str:
    successful = summary_frame[~summary_frame.get("selected_algorithm", pd.Series(dtype=object)).isna()].copy()
    if successful.empty:
        return "# Adaptive Selector Multi-Dataset Report\n\n_No successful datasets._\n"

    algorithm_counts = successful["selected_algorithm"].value_counts().reset_index()
    algorithm_counts.columns = ["algorithm", "dataset_count"]
    feature_counts = successful["selected_feature_space"].value_counts().reset_index()
    feature_counts.columns = ["feature_space", "dataset_count"]
    basis_counts = successful["selection_basis"].value_counts().reset_index()
    basis_counts.columns = ["selection_basis", "dataset_count"]

    sections = [
        "# Adaptive Selector Multi-Dataset Report",
        "",
        "## Run Scope",
        f"- Dataset directory: `{args.dataset_dir}`",
        f"- Files tested: {len(summary_frame)}",
        f"- Rows requested per file: {args.rows}",
        f"- SBERT included: {bool(args.include_sbert)}",
        f"- OPTICS included: {bool(args.include_optics)}",
        "",
        "## Dataset Selections",
        sweep.markdown_table(
            successful[
                [
                    "source_file",
                    "rows",
                    "error_rows",
                    "baseline_error_rate",
                    "semantic_richness_score",
                    "sbert_status",
                    "accepted_count",
                    "selection_basis",
                    "selected_feature_space",
                    "selected_algorithm",
                    "selected_variant",
                    "selected_selector_score",
                    "selected_top_lift",
                    "selected_top5_error_coverage",
                    "selected_top_issue",
                ]
            ]
        ),
        "",
        "## Winning Algorithms",
        sweep.markdown_table(algorithm_counts),
        "",
        "## Winning Feature Spaces",
        sweep.markdown_table(feature_counts),
        "",
        "## Selection Basis Counts",
        sweep.markdown_table(basis_counts),
        "",
        "## Notes",
        "- A different winning algorithm per dataset supports keeping the selector adaptive.",
        "- Low accepted counts indicate the rejection rules may be too strict for that dataset or that detectors produce little lift signal.",
        "- `non_degenerate_fallback` means all candidates failed at least one usefulness threshold, but the selector still chose the best diagnostic candidate.",
        "",
    ]
    return "\n".join(sections)


def main() -> None:
    args = parse_args()
    if args.multi_dataset:
        run_multi_dataset(args)
    else:
        run_selector_on_dataset(args.dataset, args, args.out_dir)


if __name__ == "__main__":
    main()
