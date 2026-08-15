"""
Benchmark semantic grouping feature/clustering choices for Buckaroo.

This is an experiment script, not production app code. It compares:

- Buckaroo TF-IDF + numeric features with K-means, MiniBatch K-means, DBSCAN,
  agglomerative clustering, HDBSCAN, and exact slices.
- SBERT row embeddings with K-means, MiniBatch K-means, DBSCAN,
  agglomerative clustering, and HDBSCAN.
- Simple ablations such as numeric-only K-means.

Outputs:
    experiments/semantic_benchmark_outputs/semantic_clustering_results.csv
    experiments/semantic_benchmark_outputs/semantic_clustering_results.json

Run:
    python experiments/semantic_clustering_benchmark.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

# Importing app.* normally initializes the database from app/__init__.py.
# This benchmark only needs pure helper functions, so skip DB startup.
os.environ.setdefault("BUCKAROO_SKIP_DB_INIT", "1")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from detectors.anomaly import anomaly
from detectors.datatype_mismatch import datatype_mismatch
from detectors.incomplete import incomplete
from detectors.missing_value import missing_value
from app.server_utils import semantic_grouping as sg


DEFAULT_DATASET = ROOT / "provided_datasets" / "stackoverflow_db_uncleaned_original.csv"
DEFAULT_OUT_DIR = ROOT / "experiments" / "semantic_benchmark_outputs"

DEFAULT_ROWS = 5000
DEFAULT_SBERT_ROWS = 2000
MIN_GROUP_SIZE = 12
MIN_ERROR_ROWS = 2
TOP_N = 5
DEFAULT_K = 8
SBERT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare semantic grouping algorithms.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    parser.add_argument("--sbert-rows", type=int, default=DEFAULT_SBERT_ROWS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--skip-sbert", action="store_true")
    parser.add_argument(
        "--fast-large",
        action="store_true",
        help="Skip DBSCAN, agglomerative, and HDBSCAN for larger datasets.",
    )
    parser.add_argument("--full-tfidf", action="store_true", help="Also run TF-IDF K-means on the full dataset.")
    return parser.parse_args()


def load_dataset(path: Path, nrows: int | None) -> pd.DataFrame:
    df = pd.read_csv(path, nrows=nrows)
    if "ID" not in df.columns:
        df.insert(0, "ID", np.arange(len(df)))
    df["ID"] = pd.to_numeric(df["ID"], errors="coerce").fillna(0).astype(int)
    return df.replace({"?": np.nan, "": np.nan, "null": np.nan, "undefined": np.nan})


def run_detectors_direct(df: pd.DataFrame) -> pd.DataFrame:
    numeric_cache = {
        col: pd.to_numeric(df[col], errors="coerce")
        for col in df.columns
        if col != "ID"
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
                rows.append({
                    "row_id": int(row_id),
                    "column_id": str(column_id),
                    "error_type": str(error_type),
                })
    return sg._normalize_error_df(pd.DataFrame(rows, columns=["row_id", "column_id", "error_type"]))


def attach_error_flags(df: pd.DataFrame, errors: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    row_error_counts = errors.groupby("row_id").size() if not errors.empty else pd.Series(dtype=int)
    error_row_ids = set(int(row_id) for row_id in row_error_counts.index.tolist())
    df["_buckaroo_has_error"] = df["ID"].isin(error_row_ids)
    df["_buckaroo_error_count"] = df["ID"].map(row_error_counts).fillna(0).astype(int)
    return df


def build_row_texts(df: pd.DataFrame, roles: dict[str, list[str]]) -> list[str]:
    texts = []
    columns = roles["text"] + roles["numeric"]
    for _, row in df.iterrows():
        parts = []
        for column in columns:
            value = row[column]
            if sg.is_missing_value(value):
                parts.append(f"{column}: missing")
            else:
                parts.append(f"{column}: {value}")
        texts.append(" ; ".join(parts))
    return texts


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def summarize_labels(
    df: pd.DataFrame,
    errors: pd.DataFrame,
    roles: dict[str, list[str]],
    labels: np.ndarray,
    strategy: str,
    feature_info: dict | None = None,
) -> list[sg.SemanticGroup]:
    labels = np.asarray(labels)
    baseline = float(df["_buckaroo_has_error"].mean()) if len(df) else 0.0
    total_error_rows = int(df["_buckaroo_has_error"].sum())
    groups = []

    for label in sorted(set(labels.tolist()), key=lambda item: str(item)):
        if label == -1:
            continue
        rows = df[labels == label]
        if len(rows) < MIN_GROUP_SIZE:
            continue
        summary = sg.summarize_group(
            rows,
            df,
            errors,
            roles,
            baseline,
            total_error_rows,
            strategy,
            group=f"{strategy}_group_{label}",
            min_error_rows=MIN_ERROR_ROWS,
            feature_info=feature_info,
        )
        if summary:
            groups.append(summary)

    return sorted(groups, key=lambda group: group.score, reverse=True)


def method_record(
    method: str,
    feature_type: str,
    cluster_time: float,
    groups: list[sg.SemanticGroup],
    labels: np.ndarray | None = None,
    feature_time: float | None = None,
    notes: str = "",
) -> dict:
    top = groups[0] if groups else None
    labels_arr = np.asarray(labels) if labels is not None else np.array([])
    non_noise_labels = set(labels_arr.tolist()) - {-1}
    return {
        "method": method,
        "feature_type": feature_type,
        "feature_time_sec": round(float(feature_time or 0.0), 4),
        "cluster_time_sec": round(float(cluster_time), 4),
        "groups_returned": len(groups),
        "raw_clusters": len(non_noise_labels),
        "noise_rows": int((labels_arr == -1).sum()) if labels is not None else 0,
        "top_lift": round(top.lift, 6) if top else 0.0,
        "top_error_rate": round(top.errorRate, 6) if top else 0.0,
        "top_error_rows": top.errorRows if top else 0,
        "top_rows": top.rows if top else 0,
        "top_issue": top.mainIssue if top else "none",
        "top_description": top.description if top else "none",
        "notes": notes,
        "top_groups": [asdict(group) for group in groups[:TOP_N]],
    }


def timed_method(
    method: str,
    feature_type: str,
    labels_fn: Callable[[], np.ndarray],
    df: pd.DataFrame,
    errors: pd.DataFrame,
    roles: dict[str, list[str]],
    feature_info: dict | None,
    feature_time: float,
    notes: str = "",
) -> dict:
    start = time.perf_counter()
    labels = labels_fn()
    cluster_time = time.perf_counter() - start
    groups = summarize_labels(df, errors, roles, labels, method, feature_info)
    return method_record(method, feature_type, cluster_time, groups, labels, feature_time, notes)


def safe_run(method: str, fallback: dict, fn: Callable[[], dict]) -> dict:
    try:
        return fn()
    except Exception as exc:
        row = dict(fallback)
        row.update({
            "method": method,
            "cluster_time_sec": 0.0,
            "groups_returned": 0,
            "raw_clusters": 0,
            "noise_rows": 0,
            "top_lift": 0.0,
            "top_error_rate": 0.0,
            "top_error_rows": 0,
            "top_rows": 0,
            "top_issue": "failed",
            "top_description": "failed",
            "notes": f"FAILED: {type(exc).__name__}: {exc}",
            "top_groups": [],
        })
        return row


def build_tfidf_numeric_features(df: pd.DataFrame, roles: dict[str, list[str]]) -> tuple[np.ndarray, dict, float]:
    start = time.perf_counter()
    matrix, feature_info = sg.build_semantic_feature_matrix(df, roles)
    return matrix, feature_info, time.perf_counter() - start


def build_numeric_only_features(df: pd.DataFrame, roles: dict[str, list[str]]) -> tuple[np.ndarray, dict | None, float]:
    start = time.perf_counter()
    matrix, _columns = sg.build_numeric_matrix(df, roles["numeric"])
    if not matrix.size:
        matrix = np.zeros((len(df), 1), dtype=float)
    return l2_normalize(matrix), None, time.perf_counter() - start


def build_sbert_features(df: pd.DataFrame, roles: dict[str, list[str]]) -> tuple[np.ndarray, dict | None, float]:
    start = time.perf_counter()
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(SBERT_MODEL)
    texts = build_row_texts(df, roles)
    embeddings = model.encode(
        texts,
        batch_size=64,
        show_progress_bar=True,
        normalize_embeddings=True,
    )
    return np.asarray(embeddings, dtype=float), None, time.perf_counter() - start


def run_cluster_suite(
    df: pd.DataFrame,
    errors: pd.DataFrame,
    roles: dict[str, list[str]],
    matrix: np.ndarray,
    feature_info: dict | None,
    feature_type: str,
    feature_time: float,
    k: int,
    include_density: bool = True,
    include_agglomerative: bool = True,
    include_expensive: bool = True,
) -> list[dict]:
    from sklearn.cluster import AgglomerativeClustering, DBSCAN, KMeans, MiniBatchKMeans
    import hdbscan

    results = []
    fallback = {"feature_type": feature_type, "feature_time_sec": round(feature_time, 4)}

    results.append(safe_run(
        f"{feature_type} + KMeans",
        fallback,
        lambda: timed_method(
            f"{feature_type} + KMeans",
            feature_type,
            lambda: KMeans(n_clusters=k, random_state=42, n_init=10).fit_predict(matrix),
            df,
            errors,
            roles,
            feature_info,
            feature_time,
            notes=f"k={k}",
        ),
    ))

    results.append(safe_run(
        f"{feature_type} + MiniBatchKMeans",
        fallback,
        lambda: timed_method(
            f"{feature_type} + MiniBatchKMeans",
            feature_type,
            lambda: MiniBatchKMeans(n_clusters=k, random_state=42, n_init=5, batch_size=512).fit_predict(matrix),
            df,
            errors,
            roles,
            feature_info,
            feature_time,
            notes=f"k={k}",
        ),
    ))

    if include_density:
        for eps in [0.15, 0.30, 0.45]:
            results.append(safe_run(
                f"{feature_type} + DBSCAN eps={eps}",
                fallback,
                lambda eps=eps: timed_method(
                    f"{feature_type} + DBSCAN eps={eps}",
                    feature_type,
                    lambda: DBSCAN(eps=eps, min_samples=8, metric="cosine", n_jobs=-1).fit_predict(matrix),
                    df,
                    errors,
                    roles,
                    feature_info,
                    feature_time,
                    notes="metric=cosine,min_samples=8",
                ),
            ))

    if include_agglomerative:
        results.append(safe_run(
            f"{feature_type} + Agglomerative average/cosine",
            fallback,
            lambda: timed_method(
                f"{feature_type} + Agglomerative average/cosine",
                feature_type,
                lambda: AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average").fit_predict(matrix),
                df,
                errors,
                roles,
                feature_info,
                feature_time,
                notes=f"k={k}",
            ),
        ))

    if include_expensive:
        results.append(safe_run(
            f"{feature_type} + HDBSCAN",
            fallback,
            lambda: timed_method(
                f"{feature_type} + HDBSCAN",
                feature_type,
                lambda: hdbscan.HDBSCAN(min_cluster_size=24, min_samples=8, metric="euclidean").fit_predict(matrix),
                df,
                errors,
                roles,
                feature_info,
                feature_time,
                notes="min_cluster_size=24,min_samples=8",
            ),
        ))

    return results


def run_exact_slices(df: pd.DataFrame, errors: pd.DataFrame, roles: dict[str, list[str]]) -> dict:
    start = time.perf_counter()
    groups = sg.exact_slice_groups(
        df,
        errors,
        roles,
        float(df["_buckaroo_has_error"].mean()) if len(df) else 0.0,
        int(df["_buckaroo_has_error"].sum()),
        MIN_GROUP_SIZE,
        MIN_ERROR_ROWS,
    )
    return method_record("Exact semantic slices", "exact_slices", time.perf_counter() - start, groups)


def prepare_dataset(path: Path, nrows: int | None) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, list[str]], dict]:
    start = time.perf_counter()
    df = load_dataset(path, nrows)
    load_time = time.perf_counter() - start
    detector_start = time.perf_counter()
    errors = run_detectors_direct(df)
    detector_time = time.perf_counter() - detector_start
    df = attach_error_flags(df, errors)
    roles = sg.infer_column_roles(df)
    meta = {
        "rows": len(df),
        "error_rows": int(df["_buckaroo_has_error"].sum()),
        "baseline_error_rate": float(df["_buckaroo_has_error"].mean()) if len(df) else 0.0,
        "error_records": len(errors),
        "load_time_sec": load_time,
        "detector_time_sec": detector_time,
        "numeric_columns": roles["numeric"],
        "text_columns": roles["text"],
    }
    return df, errors, roles, meta


def write_outputs(out_dir: Path, results: list[dict], meta: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    slim_rows = []
    for row in results:
        slim = {key: value for key, value in row.items() if key != "top_groups"}
        slim_rows.append(slim)
    pd.DataFrame(slim_rows).to_csv(out_dir / "semantic_clustering_results.csv", index=False)
    with open(out_dir / "semantic_clustering_results.json", "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "results": results}, f, indent=2)


def main() -> None:
    args = parse_args()
    results = []
    run_meta = {
        "dataset": str(args.dataset),
        "rows_arg": args.rows,
        "sbert_rows_arg": args.sbert_rows,
        "sbert_model": SBERT_MODEL,
    }

    print(f"Loading sample dataset: {args.dataset} rows={args.rows}")
    df, errors, roles, meta = prepare_dataset(args.dataset, args.rows)
    run_meta["sample"] = meta
    print(json.dumps(meta, indent=2, default=str))

    k = max(2, min(args.k, len(df)))
    run_slow_methods = not args.fast_large

    print("Building TF-IDF + numeric features...")
    tfidf_matrix, tfidf_info, tfidf_time = build_tfidf_numeric_features(df, roles)
    run_meta["tfidf_numeric_shape"] = list(tfidf_matrix.shape)
    print(f"TF-IDF+numeric matrix shape={tfidf_matrix.shape}, feature_time={tfidf_time:.3f}s")
    results.extend(run_cluster_suite(
        df,
        errors,
        roles,
        tfidf_matrix,
        tfidf_info,
        "TF-IDF+numeric",
        tfidf_time,
        k,
        include_density=run_slow_methods,
        include_agglomerative=run_slow_methods,
        include_expensive=run_slow_methods,
    ))

    print("Running numeric-only baseline...")
    numeric_matrix, numeric_info, numeric_time = build_numeric_only_features(df, roles)
    results.extend(run_cluster_suite(
        df,
        errors,
        roles,
        numeric_matrix,
        numeric_info,
        "numeric-only",
        numeric_time,
        k,
        include_density=run_slow_methods,
        include_agglomerative=run_slow_methods,
        include_expensive=False,
    ))

    print("Running exact slices baseline...")
    results.append(run_exact_slices(df, errors, roles))

    if not args.skip_sbert:
        sbert_rows = min(args.sbert_rows, len(df))
        print(f"Preparing SBERT subset rows={sbert_rows}...")
        sbert_df = df.head(sbert_rows).copy()
        sbert_errors = errors[errors["row_id"].isin(set(sbert_df["ID"].astype(int).tolist()))].copy()
        sbert_roles = sg.infer_column_roles(sbert_df)
        print("Building SBERT embeddings...")
        sbert_matrix, sbert_info, sbert_time = build_sbert_features(sbert_df, sbert_roles)
        run_meta["sbert"] = {
            "rows": len(sbert_df),
            "error_rows": int(sbert_df["_buckaroo_has_error"].sum()),
            "baseline_error_rate": float(sbert_df["_buckaroo_has_error"].mean()) if len(sbert_df) else 0.0,
            "shape": list(sbert_matrix.shape),
            "feature_time_sec": sbert_time,
        }
        print(f"SBERT matrix shape={sbert_matrix.shape}, feature_time={sbert_time:.3f}s")
        sbert_k = max(2, min(k, len(sbert_df)))
        results.extend(run_cluster_suite(
            sbert_df,
            sbert_errors,
            sbert_roles,
            sbert_matrix,
            sbert_info,
            "SBERT",
            sbert_time,
            sbert_k,
            include_density=run_slow_methods,
            include_agglomerative=run_slow_methods,
            include_expensive=run_slow_methods,
        ))

    if args.full_tfidf:
        print("Running full-dataset TF-IDF+numeric KMeans...")
        full_df, full_errors, full_roles, full_meta = prepare_dataset(args.dataset, None)
        full_matrix, full_info, full_feature_time = build_tfidf_numeric_features(full_df, full_roles)
        full_k = max(2, min(args.k, len(full_df)))
        full_result = safe_run(
            "FULL TF-IDF+numeric + KMeans",
            {"feature_type": "FULL TF-IDF+numeric", "feature_time_sec": round(full_feature_time, 4)},
            lambda: timed_method(
                "FULL TF-IDF+numeric + KMeans",
                "FULL TF-IDF+numeric",
                lambda: __import__("sklearn.cluster").cluster.KMeans(
                    n_clusters=full_k,
                    random_state=42,
                    n_init=10,
                ).fit_predict(full_matrix),
                full_df,
                full_errors,
                full_roles,
                full_info,
                full_feature_time,
                notes=f"rows={len(full_df)},k={full_k}",
            ),
        )
        results.append(full_result)
        run_meta["full_tfidf"] = {
            **full_meta,
            "feature_shape": list(full_matrix.shape),
            "feature_time_sec": full_feature_time,
        }

    write_outputs(args.out_dir, results, run_meta)

    printable = [{key: value for key, value in row.items() if key != "top_groups"} for row in results]
    print("RESULTS_JSON_START")
    print(json.dumps(printable, indent=2))
    print("RESULTS_JSON_END")
    print(f"Wrote outputs to: {args.out_dir}")


if __name__ == "__main__":
    main()
