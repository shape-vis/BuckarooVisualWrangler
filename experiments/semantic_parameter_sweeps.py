"""
Run systematic semantic clustering parameter sweeps for Buckaroo.

This is a research/meeting-prep script, not production app code. It tests the
specific questions raised in the semantic clustering meeting:

- How sensitive are results to TF-IDF feature count?
- How sensitive is K-means to the chosen number of clusters?
- Can DBSCAN avoid forcing outliers into clusters, and which eps/min_samples
  values are useful?
- How does agglomerative clustering compare?
- How sensitive are results to numeric/text weighting and TF-IDF filtering?

Outputs:
    experiments/semantic_parameter_sweep_outputs/semantic_parameter_sweep_results.csv
    experiments/semantic_parameter_sweep_outputs/semantic_parameter_sweep_results.json
    experiments/semantic_parameter_sweep_outputs/semantic_parameter_sweep_report.md

Run:
    python experiments/semantic_parameter_sweeps.py
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

os.environ.setdefault("BUCKAROO_SKIP_DB_INIT", "1")

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, DBSCAN, KMeans
from sklearn.metrics import (
    completeness_score,
    homogeneity_score,
    silhouette_score,
    v_measure_score,
)


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.server_utils import semantic_grouping as sg
from detectors.anomaly import anomaly
from detectors.datatype_mismatch import datatype_mismatch
from detectors.incomplete import incomplete
from detectors.missing_value import missing_value


DEFAULT_DATASET = ROOT / "provided_datasets" / "adult.csv"
DEFAULT_OUT_DIR = ROOT / "experiments" / "semantic_parameter_sweep_outputs"
DEFAULT_MULTI_OUT_DIR = ROOT / "experiments" / "semantic_parameter_sweep_outputs_multi"
DEFAULT_ROWS = 3000
MIN_GROUP_SIZE = 12
MIN_ERROR_ROWS = 2
TOP_N = 5
RANDOM_STATE = 42
DEFAULT_SBERT_MODEL = "all-MiniLM-L6-v2"
DEFAULT_SBERT_MAX_ROWS = 1500
DEFAULT_SBERT_MIN_RICHNESS_SCORE = 0.35


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run semantic clustering parameter sweeps.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--multi-dataset", action="store_true", help="Run the sweep across several CSV files.")
    parser.add_argument("--dataset-dir", type=Path, default=ROOT / "provided_datasets")
    parser.add_argument(
        "--datasets",
        nargs="*",
        default=None,
        help="Optional explicit CSV file paths or names inside --dataset-dir for multi-dataset mode.",
    )
    parser.add_argument("--max-files", type=int, default=10, help="Maximum dataset files to run in multi-dataset mode.")
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--multi-out-dir", type=Path, default=DEFAULT_MULTI_OUT_DIR)
    parser.add_argument("--min-group-size", type=int, default=MIN_GROUP_SIZE)
    parser.add_argument("--min-error-rows", type=int, default=MIN_ERROR_ROWS)
    parser.add_argument(
        "--include-sbert",
        action="store_true",
        help="Run optional SBERT embedding strategies when a dataset has enough semantic text signal.",
    )
    parser.add_argument(
        "--sbert-model",
        default=DEFAULT_SBERT_MODEL,
        help="SentenceTransformer model name used when --include-sbert is enabled.",
    )
    parser.add_argument(
        "--sbert-max-rows",
        type=int,
        default=DEFAULT_SBERT_MAX_ROWS,
        help="Skip SBERT above this sampled row count to keep meeting-prep sweeps responsive.",
    )
    parser.add_argument(
        "--sbert-min-richness-score",
        type=float,
        default=DEFAULT_SBERT_MIN_RICHNESS_SCORE,
        help="Minimum semantic richness score required before SBERT runs.",
    )
    return parser.parse_args()


def load_dataset(path: Path, nrows: int) -> pd.DataFrame:
    df = pd.read_csv(path, nrows=nrows)
    if "ID" not in df.columns:
        df.insert(0, "ID", np.arange(1, len(df) + 1))
    df["ID"] = pd.to_numeric(df["ID"], errors="coerce").fillna(0).astype(int)
    return df.replace({"?": np.nan, "": np.nan, "null": np.nan, "undefined": np.nan})


def slugify_dataset_name(path: Path) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", path.stem).strip("_").lower()
    return slug[:80] or "dataset"


def discover_dataset_files(dataset_dir: Path, requested: list[str] | None, max_files: int) -> list[Path]:
    dataset_dir = dataset_dir.resolve()
    if requested:
        files = []
        for item in requested:
            candidate = Path(item)
            if not candidate.is_absolute():
                candidate = dataset_dir / item
            if candidate.suffix.lower() != ".csv" and not candidate.exists():
                candidate = candidate.with_suffix(".csv")
            files.append(candidate.resolve())
    else:
        files = sorted(dataset_dir.glob("*.csv"), key=lambda path: path.name.lower())

    if max_files and max_files > 0:
        files = files[:max_files]
    if not files:
        raise ValueError(f"No CSV files found for multi-dataset run in {dataset_dir}")

    missing = [str(path) for path in files if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing dataset files: " + ", ".join(missing))
    return files


def detector_error_type(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("legacy_error_type") or value.get("error_type") or "detector_error")
    return str(value)


def run_detectors_direct(df: pd.DataFrame) -> pd.DataFrame:
    numeric_cache = {
        column: pd.to_numeric(df[column], errors="coerce")
        for column in df.columns
        if column != "ID"
    }
    detector_maps = [
        anomaly(df, numeric_cache=numeric_cache),
        incomplete(df, numeric_cache=numeric_cache),
        missing_value(df),
        datatype_mismatch(df),
    ]

    rows = []
    for error_map in detector_maps:
        for column_id, row_errors in (error_map or {}).items():
            for row_id, error_type in row_errors.items():
                rows.append(
                    {
                        "row_id": int(row_id),
                        "column_id": str(column_id),
                        "error_type": detector_error_type(error_type),
                    }
                )
    return sg._normalize_error_df(pd.DataFrame(rows, columns=["row_id", "column_id", "error_type"]))


def attach_error_flags(df: pd.DataFrame, errors: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    row_error_counts = errors.groupby("row_id").size() if not errors.empty else pd.Series(dtype=int)
    error_row_ids = {int(row_id) for row_id in row_error_counts.index.tolist()}
    df["_buckaroo_has_error"] = df["ID"].isin(error_row_ids)
    df["_buckaroo_error_count"] = df["ID"].map(row_error_counts).fillna(0).astype(int)
    return df


def dominant_issue_labels(df: pd.DataFrame, errors: pd.DataFrame) -> np.ndarray:
    issue_by_row: dict[int, str] = {}
    if not errors.empty:
        for row_id, row_errors in errors.groupby("row_id"):
            pairs = row_errors["error_type"].astype(str) + ":" + row_errors["column_id"].astype(str)
            issue_by_row[int(row_id)] = str(pairs.value_counts().index[0])
    return np.array([issue_by_row.get(int(row_id), "clean") for row_id in df["ID"].tolist()], dtype=object)


def build_tfidf_matrix(
    documents: list[list[str]],
    max_features: int,
    min_df: int = 2,
    max_df_ratio: float = 0.90,
) -> tuple[np.ndarray, list[str]]:
    if not documents:
        return np.zeros((0, 0), dtype=float), []

    doc_count = len(documents)
    document_frequencies: Counter[str] = Counter()
    term_counts = []
    for tokens in documents:
        counts = Counter(token for token in tokens if token not in sg.STOP_WORDS)
        term_counts.append(counts)
        document_frequencies.update(counts.keys())

    max_df = max(min_df, int(doc_count * max_df_ratio))
    eligible_terms = [
        term
        for term, frequency in document_frequencies.items()
        if min_df <= frequency <= max_df
    ]
    eligible_terms.sort(key=lambda term: (document_frequencies[term], term), reverse=True)
    terms = eligible_terms[: max(1, int(max_features))]
    if not terms:
        return np.zeros((doc_count, 0), dtype=float), []

    term_to_index = {term: idx for idx, term in enumerate(terms)}
    matrix = np.zeros((doc_count, len(terms)), dtype=float)
    idf = np.array(
        [math.log((1 + doc_count) / (1 + document_frequencies[term])) + 1 for term in terms],
        dtype=float,
    )

    for row_idx, counts in enumerate(term_counts):
        total_terms = sum(counts.values()) or 1
        for term, count in counts.items():
            idx = term_to_index.get(term)
            if idx is not None:
                matrix[row_idx, idx] = (count / total_terms) * idf[idx]

    return sg.l2_normalize(matrix), terms


def build_feature_matrix(
    df: pd.DataFrame,
    roles: dict[str, list[str]],
    max_text_features: int,
    numeric_weight: float = 0.75,
    min_df: int = 2,
    max_df_ratio: float = 0.90,
) -> tuple[np.ndarray, dict[str, Any], float]:
    start = time.perf_counter()
    numeric_matrix, numeric_columns = sg.build_numeric_matrix(df, roles["numeric"])
    documents = sg.build_text_documents(df, roles["text"])
    text_matrix, terms = build_tfidf_matrix(
        documents,
        max_features=max_text_features,
        min_df=min_df,
        max_df_ratio=max_df_ratio,
    )

    parts = []
    if numeric_matrix.size:
        parts.append(numeric_matrix * float(numeric_weight))
    if text_matrix.size:
        parts.append(text_matrix)

    if parts:
        matrix = np.hstack(parts)
    else:
        matrix = np.zeros((len(df), 1), dtype=float)

    matrix = sg.l2_normalize(np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0))
    feature_info = {
        "numeric_columns": numeric_columns,
        "terms": terms,
        "text_matrix": text_matrix,
        "row_positions": {int(row_id): idx for idx, row_id in enumerate(df["ID"].tolist())},
        "params": {
            "max_text_features": max_text_features,
            "actual_text_features": len(terms),
            "numeric_weight": numeric_weight,
            "min_df": min_df,
            "max_df_ratio": max_df_ratio,
        },
    }
    return matrix, feature_info, time.perf_counter() - start


def semantic_richness_profile(df: pd.DataFrame, roles: dict[str, list[str]]) -> dict[str, Any]:
    """Estimate whether row text is rich enough to justify SBERT cost."""
    text_columns = roles.get("text", [])
    row_token_counts = []
    distinct_tokens: set[str] = set()
    non_missing_text_values = 0
    long_text_values = 0

    for _, row in df.iterrows():
        row_token_count = 0
        for column in text_columns:
            value = row[column]
            if sg.is_missing_value(value):
                continue
            tokens = [token for token in sg.tokenize(value) if token not in sg.STOP_WORDS]
            row_token_count += len(tokens)
            distinct_tokens.update(tokens)
            non_missing_text_values += 1
            if len(tokens) >= 4 or len(str(value).strip()) >= 40:
                long_text_values += 1
        row_token_counts.append(row_token_count)

    rows = int(len(df))
    total_value_tokens = int(sum(row_token_counts))
    avg_tokens_per_row = float(np.mean(row_token_counts)) if row_token_counts else 0.0
    median_tokens_per_row = float(np.median(row_token_counts)) if row_token_counts else 0.0
    avg_tokens_per_text_value = (
        float(total_value_tokens / non_missing_text_values)
        if non_missing_text_values
        else 0.0
    )
    long_text_cell_fraction = (
        float(long_text_values / non_missing_text_values)
        if non_missing_text_values
        else 0.0
    )
    distinct_tokens_per_text_value = (
        float(len(distinct_tokens) / non_missing_text_values)
        if non_missing_text_values
        else 0.0
    )
    distinct_tokens_per_100_rows = (
        float(len(distinct_tokens) / max(1, rows) * 100)
        if rows
        else 0.0
    )
    score = (
        0.45 * min(avg_tokens_per_text_value / 5.0, 1.0)
        + 0.35 * min(long_text_cell_fraction / 0.20, 1.0)
        + 0.20 * min(distinct_tokens_per_text_value / 0.75, 1.0)
    )

    return {
        "rows": rows,
        "text_columns": len(text_columns),
        "non_missing_text_values": int(non_missing_text_values),
        "avg_tokens_per_row": round(avg_tokens_per_row, 6),
        "median_tokens_per_row": round(median_tokens_per_row, 6),
        "avg_tokens_per_text_value": round(avg_tokens_per_text_value, 6),
        "long_text_cell_fraction": round(long_text_cell_fraction, 6),
        "distinct_token_count": int(len(distinct_tokens)),
        "distinct_tokens_per_text_value": round(distinct_tokens_per_text_value, 6),
        "distinct_tokens_per_100_rows": round(distinct_tokens_per_100_rows, 6),
        "score": round(float(score), 6),
    }


def build_sbert_documents(
    df: pd.DataFrame,
    text_columns: list[str],
    max_columns: int = 12,
    max_value_chars: int = 300,
) -> list[str]:
    """Create compact row-level text prompts for sentence embedding."""
    selected_columns = text_columns[:max_columns]
    documents = []
    for _, row in df.iterrows():
        parts = []
        for column in selected_columns:
            value = row[column]
            if sg.is_missing_value(value):
                continue
            text = re.sub(r"\s+", " ", str(value)).strip()
            if not text:
                continue
            if len(text) > max_value_chars:
                text = text[:max_value_chars].rstrip()
            label = str(column).replace("_", " ")
            parts.append(f"{label}: {text}")
        documents.append(". ".join(parts) if parts else "empty row")
    return documents


def build_sbert_feature_matrix(
    df: pd.DataFrame,
    roles: dict[str, list[str]],
    model_name: str,
    richness_profile: dict[str, Any],
    numeric_weight: float = 0.35,
    embedding_weight: float = 1.0,
) -> tuple[np.ndarray, dict[str, Any], float]:
    start = time.perf_counter()
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is not installed. Install it with "
            "`pip install sentence-transformers` to run SBERT sweeps."
        ) from exc

    numeric_matrix, numeric_columns = sg.build_numeric_matrix(df, roles["numeric"])
    documents = build_sbert_documents(df, roles["text"])
    model = SentenceTransformer(model_name)
    embeddings = model.encode(
        documents,
        batch_size=64,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    embedding_matrix = np.asarray(embeddings, dtype=float)

    parts = []
    if numeric_matrix.size:
        parts.append(numeric_matrix * float(numeric_weight))
    if embedding_matrix.size:
        parts.append(embedding_matrix * float(embedding_weight))

    if parts:
        matrix = np.hstack(parts)
    else:
        matrix = np.zeros((len(df), 1), dtype=float)

    matrix = sg.l2_normalize(np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0))
    feature_info = {
        "numeric_columns": numeric_columns,
        "terms": [],
        "text_matrix": np.zeros((len(df), 0), dtype=float),
        "row_positions": {int(row_id): idx for idx, row_id in enumerate(df["ID"].tolist())},
        "params": {
            "max_text_features": 0,
            "actual_text_features": int(embedding_matrix.shape[1]) if embedding_matrix.ndim == 2 else 0,
            "numeric_weight": numeric_weight,
            "min_df": 0,
            "max_df_ratio": 1.0,
            "embedding_weight": embedding_weight,
            "sbert_model": model_name,
            "semantic_richness_score": richness_profile.get("score", 0.0),
        },
    }
    return matrix, feature_info, time.perf_counter() - start


def summarize_labels(
    df: pd.DataFrame,
    errors: pd.DataFrame,
    roles: dict[str, list[str]],
    labels: np.ndarray,
    method_name: str,
    feature_info: dict[str, Any],
    min_group_size: int,
    min_error_rows: int,
) -> list[sg.SemanticGroup]:
    labels = np.asarray(labels)
    baseline = float(df["_buckaroo_has_error"].mean()) if len(df) else 0.0
    total_error_rows = int(df["_buckaroo_has_error"].sum())
    groups = []

    for label in sorted(set(labels.tolist()), key=lambda item: str(item)):
        if label == -1:
            continue
        rows = df[labels == label]
        if len(rows) < min_group_size:
            continue
        summary = sg.summarize_group(
            rows,
            df,
            errors,
            roles,
            baseline,
            total_error_rows,
            method_name,
            group=f"cluster_{label}",
            min_error_rows=min_error_rows,
            feature_info=feature_info,
        )
        if summary:
            groups.append(summary)

    return sorted(groups, key=lambda group: group.score, reverse=True)


def cluster_size_stats(labels: np.ndarray) -> dict[str, float | int]:
    labels = np.asarray(labels)
    non_noise = labels[labels != -1]
    if non_noise.size == 0:
        return {
            "raw_clusters": 0,
            "noise_rows": int((labels == -1).sum()),
            "smallest_cluster": 0,
            "largest_cluster": 0,
            "median_cluster": 0.0,
            "cluster_size_cv": 0.0,
        }
    sizes = np.array(list(Counter(non_noise.tolist()).values()), dtype=float)
    return {
        "raw_clusters": int(len(sizes)),
        "noise_rows": int((labels == -1).sum()),
        "smallest_cluster": int(sizes.min()),
        "largest_cluster": int(sizes.max()),
        "median_cluster": float(np.median(sizes)),
        "cluster_size_cv": float(sizes.std() / sizes.mean()) if sizes.mean() else 0.0,
    }


def safe_silhouette(matrix: np.ndarray, labels: np.ndarray) -> float:
    labels = np.asarray(labels)
    keep = labels != -1
    unique = set(labels[keep].tolist())
    if keep.sum() < 3 or len(unique) < 2 or len(unique) >= keep.sum():
        return float("nan")
    try:
        sample_size = min(1000, int(keep.sum()))
        return float(
            silhouette_score(
                matrix[keep],
                labels[keep],
                metric="cosine",
                sample_size=sample_size,
                random_state=RANDOM_STATE,
            )
        )
    except Exception:
        return float("nan")


def safe_label_metric(metric_fn, truth: np.ndarray, labels: np.ndarray) -> float:
    labels = np.asarray(labels)
    keep = labels != -1
    if keep.sum() < 2 or len(set(labels[keep].tolist())) < 1:
        return float("nan")
    try:
        return float(metric_fn(truth[keep], labels[keep]))
    except Exception:
        return float("nan")


def centroid_tightness(matrix: np.ndarray, labels: np.ndarray) -> float:
    labels = np.asarray(labels)
    values = []
    weights = []
    for label in sorted(set(labels.tolist())):
        if label == -1:
            continue
        members = matrix[labels == label]
        if len(members) == 0:
            continue
        centroid = members.mean(axis=0, keepdims=True)
        centroid = sg.l2_normalize(centroid)
        similarities = (members @ centroid.T).ravel()
        values.append(float(np.mean(similarities)))
        weights.append(len(members))
    if not values:
        return float("nan")
    return float(np.average(values, weights=weights))


def run_algorithm(
    experiment: str,
    variant: str,
    algorithm: str,
    params: dict[str, Any],
    matrix: np.ndarray,
    feature_info: dict[str, Any],
    feature_time: float,
    label_fn,
    df: pd.DataFrame,
    errors: pd.DataFrame,
    roles: dict[str, list[str]],
    issue_labels: np.ndarray,
    min_group_size: int,
    min_error_rows: int,
) -> dict[str, Any]:
    start = time.perf_counter()
    labels = np.asarray(label_fn())
    cluster_time = time.perf_counter() - start
    groups = summarize_labels(
        df,
        errors,
        roles,
        labels,
        method_name=f"{experiment}:{algorithm}",
        feature_info=feature_info,
        min_group_size=min_group_size,
        min_error_rows=min_error_rows,
    )
    top = groups[0] if groups else None
    top_groups = groups[:TOP_N]
    stats = cluster_size_stats(labels)
    largest_cluster_fraction = (
        float(stats["largest_cluster"] / matrix.shape[0])
        if matrix.shape[0]
        else 0.0
    )
    degenerate_clustering = bool(stats["raw_clusters"] < 2 or largest_cluster_fraction >= 0.95)
    record = {
        "experiment": experiment,
        "variant": variant,
        "algorithm": algorithm,
        "params": json.dumps(params, sort_keys=True),
        "requested_text_features": feature_info["params"]["max_text_features"],
        "actual_text_features": feature_info["params"]["actual_text_features"],
        "numeric_weight": feature_info["params"]["numeric_weight"],
        "min_df": feature_info["params"]["min_df"],
        "max_df_ratio": feature_info["params"]["max_df_ratio"],
        "matrix_rows": int(matrix.shape[0]),
        "matrix_features": int(matrix.shape[1]),
        "feature_time_sec": round(float(feature_time), 4),
        "cluster_time_sec": round(float(cluster_time), 4),
        "groups_returned": int(len(groups)),
        **stats,
        "largest_cluster_fraction": round(largest_cluster_fraction, 6),
        "degenerate_clustering": degenerate_clustering,
        "silhouette_cosine": round(safe_silhouette(matrix, labels), 6),
        "issue_homogeneity": round(safe_label_metric(homogeneity_score, issue_labels, labels), 6),
        "issue_completeness": round(safe_label_metric(completeness_score, issue_labels, labels), 6),
        "issue_v_measure": round(safe_label_metric(v_measure_score, issue_labels, labels), 6),
        "centroid_tightness": round(centroid_tightness(matrix, labels), 6),
        "top_score": top.score if top else 0.0,
        "top_lift": top.lift if top else 0.0,
        "top_error_rate": top.errorRate if top else 0.0,
        "top_rows": top.rows if top else 0,
        "top_error_rows": top.errorRows if top else 0,
        "top_error_coverage": top.errorCoverage if top else 0.0,
        "mean_top5_score": round(float(np.mean([group.score for group in top_groups])), 6) if top_groups else 0.0,
        "mean_top5_lift": round(float(np.mean([group.lift for group in top_groups])), 6) if top_groups else 0.0,
        "top5_error_coverage": round(float(sum(group.errorCoverage for group in top_groups)), 6),
        "top_issue": top.mainIssue if top else "none",
        "top_description": top.description if top else "none",
        "top_groups": [asdict(group) for group in top_groups],
    }
    record["error_discovery_candidate"] = bool(
        record["groups_returned"] > 0
        and not record["degenerate_clustering"]
        and record["top_lift"] >= 1.2
    )
    return record


def kmeans_labels(k: int, matrix: np.ndarray) -> np.ndarray:
    safe_k = max(1, min(int(k), len(matrix)))
    return KMeans(n_clusters=safe_k, random_state=RANDOM_STATE, n_init=10).fit_predict(matrix)


def dbscan_labels(eps: float, min_samples: int, matrix: np.ndarray) -> np.ndarray:
    return DBSCAN(eps=eps, min_samples=min_samples, metric="cosine", n_jobs=-1).fit_predict(matrix)


def agglomerative_labels(
    matrix: np.ndarray,
    *,
    n_clusters: int | None = None,
    distance_threshold: float | None = None,
    linkage: str = "average",
) -> np.ndarray:
    model = AgglomerativeClustering(
        n_clusters=n_clusters,
        distance_threshold=distance_threshold,
        metric="cosine",
        linkage=linkage,
    )
    return model.fit_predict(matrix)


def make_feature_cache(
    df: pd.DataFrame,
    roles: dict[str, list[str]],
    configs: list[dict[str, Any]],
) -> dict[tuple[int, float, int, float], tuple[np.ndarray, dict[str, Any], float]]:
    cache = {}
    for config in configs:
        key = (
            int(config["max_text_features"]),
            float(config.get("numeric_weight", 0.75)),
            int(config.get("min_df", 2)),
            float(config.get("max_df_ratio", 0.90)),
        )
        if key not in cache:
            cache[key] = build_feature_matrix(
                df,
                roles,
                max_text_features=key[0],
                numeric_weight=key[1],
                min_df=key[2],
                max_df_ratio=key[3],
            )
    return cache


def run_sweeps(
    df: pd.DataFrame,
    errors: pd.DataFrame,
    roles: dict[str, list[str]],
    issue_labels: np.ndarray,
    min_group_size: int,
    min_error_rows: int,
    *,
    include_sbert: bool = False,
    sbert_model: str = DEFAULT_SBERT_MODEL,
    sbert_max_rows: int = DEFAULT_SBERT_MAX_ROWS,
    sbert_min_richness_score: float = DEFAULT_SBERT_MIN_RICHNESS_SCORE,
    sbert_richness_profile: dict[str, Any] | None = None,
    sbert_status: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    feature_configs = []

    for features in [100, 250, 350, 500, 1000]:
        feature_configs.append({"max_text_features": features, "numeric_weight": 0.75, "min_df": 2, "max_df_ratio": 0.90})
    for weight in [0.25, 0.50, 0.75, 1.00, 1.50]:
        feature_configs.append({"max_text_features": 350, "numeric_weight": weight, "min_df": 2, "max_df_ratio": 0.90})
    for min_df in [1, 2, 3, 5]:
        feature_configs.append({"max_text_features": 350, "numeric_weight": 0.75, "min_df": min_df, "max_df_ratio": 0.90})
    for max_df_ratio in [0.75, 0.90, 0.98]:
        feature_configs.append({"max_text_features": 350, "numeric_weight": 0.75, "min_df": 2, "max_df_ratio": max_df_ratio})

    feature_cache = make_feature_cache(df, roles, feature_configs)

    def get_features(max_text_features: int, numeric_weight: float = 0.75, min_df: int = 2, max_df_ratio: float = 0.90):
        return feature_cache[(max_text_features, numeric_weight, min_df, max_df_ratio)]

    results = []

    for features in [100, 250, 350, 500, 1000]:
        matrix, feature_info, feature_time = get_features(features)
        results.append(
            run_algorithm(
                "A_feature_count_sensitivity",
                f"features={features},k=8",
                "KMeans",
                {"k": 8},
                matrix,
                feature_info,
                feature_time,
                lambda matrix=matrix: kmeans_labels(8, matrix),
                df,
                errors,
                roles,
                issue_labels,
                min_group_size,
                min_error_rows,
            )
        )

    matrix350, info350, time350 = get_features(350)
    for k in [4, 6, 8, 10, 12]:
        results.append(
            run_algorithm(
                "B_kmeans_cluster_count",
                f"k={k},features=350",
                "KMeans",
                {"k": k},
                matrix350,
                info350,
                time350,
                lambda k=k, matrix=matrix350: kmeans_labels(k, matrix),
                df,
                errors,
                roles,
                issue_labels,
                min_group_size,
                min_error_rows,
            )
        )

    for eps in [0.05, 0.10, 0.15, 0.20, 0.30, 0.45, 0.60, 0.80]:
        for min_samples in [4, 8, 12]:
            results.append(
                run_algorithm(
                    "C_dbscan_eps_min_samples",
                    f"eps={eps},min_samples={min_samples}",
                    "DBSCAN",
                    {"eps": eps, "min_samples": min_samples, "metric": "cosine"},
                    matrix350,
                    info350,
                    time350,
                    lambda eps=eps, min_samples=min_samples, matrix=matrix350: dbscan_labels(eps, min_samples, matrix),
                    df,
                    errors,
                    roles,
                    issue_labels,
                    min_group_size,
                    min_error_rows,
                )
            )

    for k in [4, 6, 8, 10, 12]:
        results.append(
            run_algorithm(
                "D_agglomerative_cluster_count",
                f"k={k},linkage=average",
                "Agglomerative",
                {"n_clusters": k, "metric": "cosine", "linkage": "average"},
                matrix350,
                info350,
                time350,
                lambda k=k, matrix=matrix350: agglomerative_labels(matrix, n_clusters=k),
                df,
                errors,
                roles,
                issue_labels,
                min_group_size,
                min_error_rows,
            )
        )

    for threshold in [0.25, 0.35, 0.45, 0.55]:
        results.append(
            run_algorithm(
                "E_agglomerative_distance_threshold",
                f"distance_threshold={threshold}",
                "Agglomerative",
                {"distance_threshold": threshold, "metric": "cosine", "linkage": "average"},
                matrix350,
                info350,
                time350,
                lambda threshold=threshold, matrix=matrix350: agglomerative_labels(
                    matrix,
                    n_clusters=None,
                    distance_threshold=threshold,
                ),
                df,
                errors,
                roles,
                issue_labels,
                min_group_size,
                min_error_rows,
            )
        )

    for weight in [0.25, 0.50, 0.75, 1.00, 1.50]:
        matrix, feature_info, feature_time = get_features(350, numeric_weight=weight)
        results.append(
            run_algorithm(
                "F_numeric_text_weight",
                f"numeric_weight={weight},k=8",
                "KMeans",
                {"k": 8},
                matrix,
                feature_info,
                feature_time,
                lambda matrix=matrix: kmeans_labels(8, matrix),
                df,
                errors,
                roles,
                issue_labels,
                min_group_size,
                min_error_rows,
            )
        )

    for min_df in [1, 2, 3, 5]:
        matrix, feature_info, feature_time = get_features(350, min_df=min_df)
        results.append(
            run_algorithm(
                "G_tfidf_min_df_filter",
                f"min_df={min_df},k=8",
                "KMeans",
                {"k": 8},
                matrix,
                feature_info,
                feature_time,
                lambda matrix=matrix: kmeans_labels(8, matrix),
                df,
                errors,
                roles,
                issue_labels,
                min_group_size,
                min_error_rows,
            )
        )

    for max_df_ratio in [0.75, 0.90, 0.98]:
        matrix, feature_info, feature_time = get_features(350, max_df_ratio=max_df_ratio)
        results.append(
            run_algorithm(
                "H_tfidf_max_df_filter",
                f"max_df_ratio={max_df_ratio},k=8",
                "KMeans",
                {"k": 8},
                matrix,
                feature_info,
                feature_time,
                lambda matrix=matrix: kmeans_labels(8, matrix),
                df,
                errors,
                roles,
                issue_labels,
                min_group_size,
                min_error_rows,
            )
        )

    results.extend(
        run_sbert_sweeps(
            df,
            errors,
            roles,
            issue_labels,
            min_group_size,
            min_error_rows,
            include_sbert=include_sbert,
            sbert_model=sbert_model,
            sbert_max_rows=sbert_max_rows,
            sbert_min_richness_score=sbert_min_richness_score,
            richness_profile=sbert_richness_profile,
            status=sbert_status,
        )
    )

    return results


def run_sbert_sweeps(
    df: pd.DataFrame,
    errors: pd.DataFrame,
    roles: dict[str, list[str]],
    issue_labels: np.ndarray,
    min_group_size: int,
    min_error_rows: int,
    *,
    include_sbert: bool,
    sbert_model: str,
    sbert_max_rows: int,
    sbert_min_richness_score: float,
    richness_profile: dict[str, Any] | None,
    status: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if status is None:
        status = {}
    profile = richness_profile or semantic_richness_profile(df, roles)
    status.update(
        {
            "requested": bool(include_sbert),
            "model": sbert_model,
            "max_rows": int(sbert_max_rows),
            "min_richness_score": float(sbert_min_richness_score),
            "richness_profile": profile,
        }
    )

    if not include_sbert:
        status.update({"status": "disabled", "reason": "Pass --include-sbert to run SBERT embedding sweeps."})
        return []
    if not roles.get("text"):
        status.update({"status": "skipped", "reason": "Dataset has no text/category columns."})
        return []
    if len(df) > int(sbert_max_rows):
        status.update(
            {
                "status": "skipped",
                "reason": f"Sample has {len(df)} rows, above --sbert-max-rows={sbert_max_rows}.",
            }
        )
        return []
    if float(profile["score"]) < float(sbert_min_richness_score):
        status.update(
            {
                "status": "skipped",
                "reason": (
                    f"Semantic richness score {profile['score']} is below "
                    f"--sbert-min-richness-score={sbert_min_richness_score}."
                ),
            }
        )
        return []

    try:
        matrix, feature_info, feature_time = build_sbert_feature_matrix(
            df,
            roles,
            model_name=sbert_model,
            richness_profile=profile,
        )
    except Exception as exc:
        status.update({"status": "failed", "reason": f"{type(exc).__name__}: {exc}"})
        return []

    status.update(
        {
            "status": "ran",
            "reason": "SBERT embedding matrix built and clustered.",
            "matrix_features": int(matrix.shape[1]),
            "feature_time_sec": round(float(feature_time), 4),
        }
    )

    results = []
    for k in [4, 6, 8, 10]:
        results.append(
            run_algorithm(
                "I_sbert_embeddings",
                f"model={sbert_model},k={k}",
                "SBERT+KMeans",
                {"model": sbert_model, "k": k, "metric": "cosine"},
                matrix,
                feature_info,
                feature_time,
                lambda k=k, matrix=matrix: kmeans_labels(k, matrix),
                df,
                errors,
                roles,
                issue_labels,
                min_group_size,
                min_error_rows,
            )
        )

    for threshold in [0.25, 0.35, 0.45]:
        results.append(
            run_algorithm(
                "I_sbert_embeddings",
                f"model={sbert_model},distance_threshold={threshold}",
                "SBERT+Agglomerative",
                {"model": sbert_model, "distance_threshold": threshold, "metric": "cosine", "linkage": "average"},
                matrix,
                feature_info,
                feature_time,
                lambda threshold=threshold, matrix=matrix: agglomerative_labels(
                    matrix,
                    n_clusters=None,
                    distance_threshold=threshold,
                ),
                df,
                errors,
                roles,
                issue_labels,
                min_group_size,
                min_error_rows,
            )
        )

    for eps in [0.15, 0.25, 0.35]:
        results.append(
            run_algorithm(
                "I_sbert_embeddings",
                f"model={sbert_model},eps={eps},min_samples=8",
                "SBERT+DBSCAN",
                {"model": sbert_model, "eps": eps, "min_samples": 8, "metric": "cosine"},
                matrix,
                feature_info,
                feature_time,
                lambda eps=eps, matrix=matrix: dbscan_labels(eps, 8, matrix),
                df,
                errors,
                roles,
                issue_labels,
                min_group_size,
                min_error_rows,
            )
        )

    return results


def safe_nan(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        if pd.isna(value):
            return "n/a"
    except TypeError:
        pass
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def best_row(
    frame: pd.DataFrame,
    subset: str,
    metric: str,
    *,
    require_error_discovery_candidate: bool = False,
) -> pd.Series | None:
    rows = frame[frame["experiment"] == subset].copy()
    if require_error_discovery_candidate and "error_discovery_candidate" in rows:
        rows = rows[rows["error_discovery_candidate"]]
    if rows.empty:
        return None
    rows = rows.sort_values(metric, ascending=False)
    return rows.iloc[0]


def compact_table(frame: pd.DataFrame, experiment: str, columns: list[str]) -> str:
    rows = frame[frame["experiment"] == experiment][columns].copy()
    if rows.empty:
        return "_No rows._"
    return markdown_table(rows)


def markdown_table(frame: pd.DataFrame) -> str:
    headers = [str(column) for column in frame.columns]
    body = []
    for _, row in frame.iterrows():
        body.append([markdown_cell(row[column]) for column in frame.columns])

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for cells in body:
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def markdown_cell(value: Any) -> str:
    if isinstance(value, float):
        if pd.isna(value):
            return "n/a"
        return f"{value:.3f}"
    if pd.isna(value):
        return "n/a"
    text = str(value).replace("\n", " ").replace("|", "\\|")
    return text[:220] + "..." if len(text) > 220 else text


def conclusion_line(row: pd.Series | None, metric: str) -> str:
    if row is None:
        return "No non-degenerate error-discovery run was recorded for this metric."
    return (
        f"Best by `{metric}`: `{row['variant']}` using `{row['algorithm']}` "
        f"(top_score={safe_nan(row['top_score'])}, top_lift={safe_nan(row['top_lift'])}, "
        f"silhouette={safe_nan(row['silhouette_cosine'])}, "
        f"issue_homogeneity={safe_nan(row['issue_homogeneity'])}, "
        f"clusters={row['raw_clusters']}, noise={row['noise_rows']})."
    )


def select_headline_rows(frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    candidates = (
        frame[frame["error_discovery_candidate"]].copy()
        if "error_discovery_candidate" in frame
        else frame.iloc[0:0].copy()
    )
    if not candidates.empty:
        return candidates, "error_discovery_candidate"

    non_degenerate = frame.copy()
    if "degenerate_clustering" in non_degenerate:
        non_degenerate = non_degenerate[~non_degenerate["degenerate_clustering"].astype(bool)]
    if "raw_clusters" in non_degenerate:
        non_degenerate = non_degenerate[non_degenerate["raw_clusters"] >= 2]
    if "largest_cluster_fraction" in non_degenerate:
        non_degenerate = non_degenerate[non_degenerate["largest_cluster_fraction"] < 0.95]
    if not non_degenerate.empty:
        return non_degenerate, "non_degenerate_fallback"

    return frame, "all_runs_fallback"


def selection_basis_description(selection_basis: str) -> str:
    descriptions = {
        "error_discovery_candidate": "non-degenerate runs with useful error lift",
        "non_degenerate_fallback": "non-degenerate fallback rows because no run improved error lift enough",
        "all_runs_fallback": "all rows because every run collapsed or failed the non-degenerate filter",
    }
    return descriptions.get(selection_basis, selection_basis)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def write_outputs(out_dir: Path, results: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    full_json = json_safe({"meta": meta, "results": results})
    with open(out_dir / "semantic_parameter_sweep_results.json", "w", encoding="utf-8") as f:
        json.dump(full_json, f, indent=2, allow_nan=False)

    slim_rows = [{key: value for key, value in row.items() if key != "top_groups"} for row in results]
    frame = pd.DataFrame(slim_rows)
    frame.to_csv(out_dir / "semantic_parameter_sweep_results.csv", index=False)

    report = build_report(frame, meta)
    (out_dir / "semantic_parameter_sweep_report.md").write_text(report, encoding="utf-8")


def build_report(frame: pd.DataFrame, meta: dict[str, Any]) -> str:
    ranking_frame, selection_basis = select_headline_rows(frame)
    best_overall = ranking_frame.sort_values(["mean_top5_score", "top_score"], ascending=False).iloc[0]
    best_silhouette = (
        ranking_frame.dropna(subset=["silhouette_cosine"])
        .sort_values("silhouette_cosine", ascending=False)
    )
    best_silhouette_row = best_silhouette.iloc[0] if not best_silhouette.empty else None

    sections = [
        "# Semantic Parameter Sweep Report",
        "",
        "## Dataset",
        f"- Dataset: `{meta['dataset']}`",
        f"- Rows tested: {meta['rows']}",
        f"- Detector records: {meta['error_records']}",
        f"- Rows with at least one detector error: {meta['error_rows']}",
        f"- Baseline row error rate: {meta['baseline_error_rate']:.1%}",
        f"- Numeric columns: {', '.join(meta['numeric_columns']) or 'none'}",
        f"- Text/category columns: {', '.join(meta['text_columns']) or 'none'}",
        "",
        "## Overall Conclusions",
        (
            f"- Headline ranking basis: {selection_basis_description(selection_basis)}."
        ),
        (
            f"- Strongest headline setting by mean top-5 score: `{best_overall['experiment']}` / "
            f"`{best_overall['variant']}` / `{best_overall['algorithm']}` "
            f"(mean_top5_score={safe_nan(best_overall['mean_top5_score'])}, "
            f"top_lift={safe_nan(best_overall['top_lift'])})."
        ),
        (
            "- Best geometric tightness by silhouette: "
            + (
                f"`{best_silhouette_row['experiment']}` / `{best_silhouette_row['variant']}` "
                f"(silhouette={safe_nan(best_silhouette_row['silhouette_cosine'])})."
                if best_silhouette_row is not None
                else "not available."
            )
        ),
        "- Degenerate runs are excluded from headline conclusions when they collapse nearly all rows into one cluster or produce only one cluster.",
        "- Treat high lift alone carefully: a very small cluster can look strong but explain few total errors.",
        "- DBSCAN should be judged by both cluster quality and how many rows become noise/outliers.",
        "- Agglomerative clustering is useful as a comparison because it exposes sensitivity to the requested cluster count or distance threshold.",
        "",
        "## Experiment A: TF-IDF Feature Count Sensitivity",
        conclusion_line(best_row(frame, "A_feature_count_sensitivity", "mean_top5_score"), "mean_top5_score"),
        "",
        compact_table(
            frame,
            "A_feature_count_sensitivity",
            [
                "variant",
                "matrix_features",
                "cluster_time_sec",
                "top_score",
                "top_lift",
                "mean_top5_score",
                "silhouette_cosine",
                "issue_homogeneity",
                "top_description",
            ],
        ),
        "",
        "## Experiment B: K-means Cluster Count",
        conclusion_line(best_row(frame, "B_kmeans_cluster_count", "mean_top5_score"), "mean_top5_score"),
        "",
        compact_table(
            frame,
            "B_kmeans_cluster_count",
            [
                "variant",
                "raw_clusters",
                "smallest_cluster",
                "largest_cluster",
                "top_score",
                "top_lift",
                "mean_top5_score",
                "silhouette_cosine",
                "issue_homogeneity",
            ],
        ),
        "",
        "## Experiment C: DBSCAN eps/min_samples",
        conclusion_line(
            best_row(
                frame,
                "C_dbscan_eps_min_samples",
                "mean_top5_score",
                require_error_discovery_candidate=True,
            ),
            "mean_top5_score",
        ),
        "",
        compact_table(
            frame,
            "C_dbscan_eps_min_samples",
            [
                "variant",
                "raw_clusters",
                "noise_rows",
                "degenerate_clustering",
                "smallest_cluster",
                "largest_cluster",
                "largest_cluster_fraction",
                "top_score",
                "top_lift",
                "mean_top5_score",
                "silhouette_cosine",
                "issue_homogeneity",
            ],
        ),
        "",
        "## Experiment D/E: Agglomerative Clustering",
        conclusion_line(
            best_row(
                frame,
                "D_agglomerative_cluster_count",
                "mean_top5_score",
                require_error_discovery_candidate=True,
            ),
            "mean_top5_score",
        ),
        conclusion_line(
            best_row(
                frame,
                "E_agglomerative_distance_threshold",
                "mean_top5_score",
                require_error_discovery_candidate=True,
            ),
            "mean_top5_score",
        ),
        "",
        compact_table(
            frame,
            "D_agglomerative_cluster_count",
            [
                "variant",
                "raw_clusters",
                "smallest_cluster",
                "largest_cluster",
                "top_score",
                "top_lift",
                "mean_top5_score",
                "silhouette_cosine",
                "issue_homogeneity",
            ],
        ),
        "",
        compact_table(
            frame,
            "E_agglomerative_distance_threshold",
            [
                "variant",
                "raw_clusters",
                "smallest_cluster",
                "largest_cluster",
                "top_score",
                "top_lift",
                "mean_top5_score",
                "silhouette_cosine",
                "issue_homogeneity",
            ],
        ),
        "",
        "## Experiment F: Numeric/Text Weight",
        conclusion_line(best_row(frame, "F_numeric_text_weight", "mean_top5_score"), "mean_top5_score"),
        "",
        compact_table(
            frame,
            "F_numeric_text_weight",
            [
                "variant",
                "top_score",
                "top_lift",
                "mean_top5_score",
                "silhouette_cosine",
                "issue_homogeneity",
                "top_description",
            ],
        ),
        "",
        "## Experiment G/H: TF-IDF Filtering Thresholds",
        conclusion_line(best_row(frame, "G_tfidf_min_df_filter", "mean_top5_score"), "mean_top5_score"),
        conclusion_line(best_row(frame, "H_tfidf_max_df_filter", "mean_top5_score"), "mean_top5_score"),
        "",
        compact_table(
            frame,
            "G_tfidf_min_df_filter",
            [
                "variant",
                "actual_text_features",
                "top_score",
                "top_lift",
                "mean_top5_score",
                "silhouette_cosine",
                "issue_homogeneity",
            ],
        ),
        "",
        compact_table(
            frame,
            "H_tfidf_max_df_filter",
            [
                "variant",
                "actual_text_features",
                "top_score",
                "top_lift",
                "mean_top5_score",
                "silhouette_cosine",
                "issue_homogeneity",
            ],
        ),
        "",
        "## Experiment I: Optional SBERT Embeddings",
        (
            f"- Status: {meta.get('sbert_status', {}).get('status', 'disabled')} "
            f"({meta.get('sbert_status', {}).get('reason', 'not requested')})."
        ),
        (
            f"- Semantic richness score: {meta.get('semantic_richness', {}).get('score', 'n/a')} "
            f"(threshold {meta.get('sbert_min_richness_score', 'n/a')})."
        ),
        "",
        compact_table(
            frame,
            "I_sbert_embeddings",
            [
                "variant",
                "algorithm",
                "matrix_features",
                "feature_time_sec",
                "cluster_time_sec",
                "raw_clusters",
                "noise_rows",
                "top_score",
                "top_lift",
                "mean_top5_score",
                "silhouette_cosine",
                "issue_homogeneity",
            ],
        ),
        "",
        "## Suggested Next Steps",
        "- Discuss whether the score should prioritize concentrated error lift, total error coverage, or interpretability.",
        "- Repeat the same sweeps on at least one more dataset because these parameters are data-dependent.",
        "- Consider exposing important thresholds as config/defaults instead of burying them in helper functions.",
        "- Keep DBSCAN as an option when outlier handling matters, but do not treat its default parameters as meaningful.",
        "- Use SBERT selectively as a slower quality baseline on semantically rich datasets; cache repeated row/text embeddings before considering it for the live app.",
        "",
    ]
    return "\n".join(sections)


def run_one_dataset(dataset_path: Path, args: argparse.Namespace, out_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dataset_path = dataset_path.resolve()
    dataset_name = slugify_dataset_name(dataset_path)

    print(f"Loading dataset {dataset_path} rows={args.rows}")
    start = time.perf_counter()
    df = load_dataset(dataset_path, args.rows)
    load_time = time.perf_counter() - start

    print("Running Buckaroo detectors...")
    detector_start = time.perf_counter()
    errors = run_detectors_direct(df)
    detector_time = time.perf_counter() - detector_start

    df = attach_error_flags(df, errors)
    roles = sg.infer_column_roles(df)
    issue_labels = dominant_issue_labels(df, errors)
    sbert_richness = semantic_richness_profile(df, roles)
    sbert_status: dict[str, Any] = {}

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
        "load_time_sec": round(load_time, 4),
        "detector_time_sec": round(detector_time, 4),
        "min_group_size": int(args.min_group_size),
        "min_error_rows": int(args.min_error_rows),
        "semantic_richness": sbert_richness,
        "sbert_requested": bool(args.include_sbert),
        "sbert_model": str(args.sbert_model),
        "sbert_max_rows": int(args.sbert_max_rows),
        "sbert_min_richness_score": float(args.sbert_min_richness_score),
    }
    print(json.dumps(meta, indent=2))

    print("Running parameter sweeps...")
    results = run_sweeps(
        df,
        errors,
        roles,
        issue_labels,
        min_group_size=args.min_group_size,
        min_error_rows=args.min_error_rows,
        include_sbert=args.include_sbert,
        sbert_model=args.sbert_model,
        sbert_max_rows=args.sbert_max_rows,
        sbert_min_richness_score=args.sbert_min_richness_score,
        sbert_richness_profile=sbert_richness,
        sbert_status=sbert_status,
    )
    meta["sbert_status"] = sbert_status
    print("SBERT status:")
    print(json.dumps(sbert_status, indent=2))

    print("Writing CSV, JSON, and Markdown report...")
    for row in results:
        row["dataset_name"] = dataset_name
        row["dataset_file"] = dataset_path.name
        row["dataset_path"] = str(dataset_path)
    write_outputs(out_dir, results, meta)

    slim_rows = [{key: value for key, value in row.items() if key != "top_groups"} for row in results]
    frame = pd.DataFrame(slim_rows)
    print("\nTop 10 runs by mean_top5_score:")
    print(
        frame.sort_values(["mean_top5_score", "top_score"], ascending=False)
        .head(10)[
            [
                "experiment",
                "variant",
                "algorithm",
                "mean_top5_score",
                "top_lift",
                "raw_clusters",
                "noise_rows",
                "silhouette_cosine",
                "issue_homogeneity",
            ]
        ]
        .to_string(index=False)
    )
    print(f"\nWrote outputs to: {out_dir}")
    return meta, results


def summarize_dataset(meta: dict[str, Any], results: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    frame = pd.DataFrame([{key: value for key, value in row.items() if key != "top_groups"} for row in results])
    ranking_frame, selection_basis = select_headline_rows(frame)
    best = ranking_frame.sort_values(["mean_top5_score", "top_score"], ascending=False).iloc[0]
    best_silhouette = ranking_frame.dropna(subset=["silhouette_cosine"]).sort_values("silhouette_cosine", ascending=False)
    silhouette_row = best_silhouette.iloc[0] if not best_silhouette.empty else None
    return {
        "dataset_name": meta["dataset_name"],
        "source_file": meta["source_file"],
        "rows": meta["rows"],
        "error_records": meta["error_records"],
        "error_rows": meta["error_rows"],
        "baseline_error_rate": meta["baseline_error_rate"],
        "numeric_columns": len(meta["numeric_columns"]),
        "text_columns": len(meta["text_columns"]),
        "semantic_richness_score": meta.get("semantic_richness", {}).get("score", np.nan),
        "sbert_requested": meta.get("sbert_requested", False),
        "sbert_status": meta.get("sbert_status", {}).get("status", "disabled"),
        "best_selection_basis": selection_basis,
        "best_experiment": best["experiment"],
        "best_variant": best["variant"],
        "best_algorithm": best["algorithm"],
        "best_mean_top5_score": best["mean_top5_score"],
        "best_top_score": best["top_score"],
        "best_top_lift": best["top_lift"],
        "best_raw_clusters": best["raw_clusters"],
        "best_noise_rows": best["noise_rows"],
        "best_largest_cluster_fraction": best["largest_cluster_fraction"],
        "best_issue_homogeneity": best["issue_homogeneity"],
        "best_silhouette_experiment": silhouette_row["experiment"] if silhouette_row is not None else "none",
        "best_silhouette_variant": silhouette_row["variant"] if silhouette_row is not None else "none",
        "best_silhouette_cosine": silhouette_row["silhouette_cosine"] if silhouette_row is not None else np.nan,
        "report_path": str(out_dir / "semantic_parameter_sweep_report.md"),
        "csv_path": str(out_dir / "semantic_parameter_sweep_results.csv"),
        "json_path": str(out_dir / "semantic_parameter_sweep_results.json"),
    }


def build_multi_report(summary_frame: pd.DataFrame, combined_frame: pd.DataFrame, args: argparse.Namespace) -> str:
    algorithm_counts = summary_frame["best_algorithm"].value_counts().reset_index()
    algorithm_counts.columns = ["algorithm", "dataset_count"]

    experiment_counts = summary_frame["best_experiment"].value_counts().reset_index()
    experiment_counts.columns = ["experiment", "dataset_count"]

    selection_counts = summary_frame["best_selection_basis"].value_counts().reset_index()
    selection_counts.columns = ["selection_basis", "dataset_count"]

    sections = [
        "# Multi-Dataset Semantic Parameter Sweep Report",
        "",
        "## Run Scope",
        f"- Dataset directory: `{args.dataset_dir}`",
        f"- Files tested: {len(summary_frame)}",
        f"- Rows requested per file: {args.rows}",
        "- Detector implementation: current workspace Buckaroo detectors imported from `detectors/`.",
        "- Per file, the script runs the same sweeps over K-means, DBSCAN, agglomerative clustering, TF-IDF feature count, numeric/text weight, min_df, and max_df_ratio.",
        (
            "- Optional SBERT sweeps are "
            + (
                f"enabled for semantically rich datasets using `{args.sbert_model}`."
                if args.include_sbert
                else "disabled; pass `--include-sbert` to test sentence-transformer embeddings."
            )
        ),
        "",
        "## File-by-File Headline Results",
        markdown_table(
            summary_frame[
                [
                    "source_file",
                    "rows",
                    "error_rows",
                    "baseline_error_rate",
                    "semantic_richness_score",
                    "sbert_status",
                    "best_selection_basis",
                    "best_algorithm",
                    "best_experiment",
                    "best_variant",
                    "best_mean_top5_score",
                    "best_top_lift",
                    "best_raw_clusters",
                    "best_noise_rows",
                    "best_largest_cluster_fraction",
                ]
            ]
        ),
        "",
        "## Headline Selection Basis",
        markdown_table(selection_counts),
        "",
        "## Which Algorithms Won Most Often?",
        markdown_table(algorithm_counts),
        "",
        "## Which Parameter Blocks Won Most Often?",
        markdown_table(experiment_counts),
        "",
        "## Cross-Dataset Notes",
        "- If different datasets prefer different algorithms or parameter blocks, that supports an adaptive mixed strategy instead of one fixed clustering setting.",
        "- DBSCAN wins should be checked for noise rows and largest-cluster fraction; density methods can over-filter or collapse depending on `eps`.",
        "- Agglomerative wins should be checked for cluster count; distance thresholds can produce many candidate clusters that need UI ranking and filtering.",
        "- K-means wins indicate the stable baseline remains useful, especially when fast preview behavior is important.",
        "- TF-IDF and numeric-weight wins show feature construction is dataset-dependent, not merely an implementation detail.",
        "- When a dataset has a baseline error-row rate of 100%, lift is capped at 1.0, so the report uses a non-degenerate fallback as a diagnostic comparison rather than a true improvement claim.",
        "",
        "## Output Structure",
        "- `combined_semantic_parameter_sweep_results.csv`: every run across every dataset.",
        "- `combined_dataset_summary.csv`: one best-result row per dataset.",
        "- `combined_semantic_parameter_sweep_results.json`: metadata, summaries, and every run.",
        "- `per_dataset/<dataset_name>/semantic_parameter_sweep_report.md`: detailed per-file report.",
        "",
    ]
    return "\n".join(sections)


def write_multi_outputs(
    out_dir: Path,
    dataset_summaries: list[dict[str, Any]],
    all_results: list[dict[str, Any]],
    args: argparse.Namespace,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_frame = pd.DataFrame(dataset_summaries)
    combined_frame = pd.DataFrame([{key: value for key, value in row.items() if key != "top_groups"} for row in all_results])

    summary_frame.to_csv(out_dir / "combined_dataset_summary.csv", index=False)
    combined_frame.to_csv(out_dir / "combined_semantic_parameter_sweep_results.csv", index=False)
    with open(out_dir / "combined_semantic_parameter_sweep_results.json", "w", encoding="utf-8") as f:
        json.dump(
            json_safe(
                {
                    "run": {
                        "dataset_dir": str(args.dataset_dir),
                        "rows": args.rows,
                        "file_count": len(dataset_summaries),
                        "include_sbert": bool(args.include_sbert),
                        "sbert_model": str(args.sbert_model),
                        "sbert_max_rows": int(args.sbert_max_rows),
                        "sbert_min_richness_score": float(args.sbert_min_richness_score),
                    },
                    "dataset_summaries": dataset_summaries,
                    "results": all_results,
                }
            ),
            f,
            indent=2,
            allow_nan=False,
        )
    (out_dir / "combined_semantic_parameter_sweep_report.md").write_text(
        build_multi_report(summary_frame, combined_frame, args),
        encoding="utf-8",
    )


def run_multi_dataset(args: argparse.Namespace) -> None:
    dataset_files = discover_dataset_files(args.dataset_dir, args.datasets, args.max_files)
    print("Multi-dataset run files:")
    for idx, dataset_path in enumerate(dataset_files, start=1):
        print(f"  {idx}. {dataset_path}")

    dataset_summaries = []
    all_results = []
    per_dataset_root = args.multi_out_dir / "per_dataset"
    for idx, dataset_path in enumerate(dataset_files, start=1):
        print(f"\n=== Dataset {idx}/{len(dataset_files)}: {dataset_path.name} ===")
        dataset_out_dir = per_dataset_root / slugify_dataset_name(dataset_path)
        try:
            meta, results = run_one_dataset(dataset_path, args, dataset_out_dir)
            dataset_summaries.append(summarize_dataset(meta, results, dataset_out_dir))
            all_results.extend(results)
        except Exception as exc:
            failure = {
                "dataset_name": slugify_dataset_name(dataset_path),
                "source_file": dataset_path.name,
                "error": f"{type(exc).__name__}: {exc}",
                "report_path": "",
                "csv_path": "",
                "json_path": "",
            }
            dataset_summaries.append(failure)
            print(f"FAILED {dataset_path}: {failure['error']}")

    write_multi_outputs(args.multi_out_dir, dataset_summaries, all_results, args)
    print(f"\nWrote multi-dataset outputs to: {args.multi_out_dir}")
    print("\nCombined dataset summary:")
    print(pd.DataFrame(dataset_summaries).to_string(index=False))


def main() -> None:
    args = parse_args()
    if args.multi_dataset:
        run_multi_dataset(args)
    else:
        run_one_dataset(args.dataset, args, args.out_dir)


if __name__ == "__main__":
    main()
