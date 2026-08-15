"""
Matrixless semantic grouping prototype for Buckaroo.

This experiment is intentionally separate from production Buckaroo code.

Problem:
    A normal semantic grouping pipeline builds a large row x feature matrix:

        rows x TF-IDF terms + numeric columns

    That is understandable, but it can become expensive for large datasets,
    and SBERT-style row embeddings are even more expensive.

Idea:
    Use an Error-Conditioned Semantic Sketch (ECSS).

    ECSS never builds a full TF-IDF vocabulary matrix. Instead it:
      1. streams rows and hashes text/category tokens into a small fixed-width
         signed sketch;
      2. appends robust-scaled numeric features;
      3. trains MiniBatchKMeans only on an error-aware coreset;
      4. assigns the full dataset to prototypes in batches;
      5. scores prototypes by error concentration and explains them using
         small per-cluster counters.

Theoretical ingredients:
    - Feature hashing approximates inner products without storing a vocabulary.
    - Random projection / sketching keeps dimensionality fixed.
    - MiniBatchKMeans reduces clustering cost for interactive settings.
    - Coresets summarize large datasets so clustering can train on fewer rows.
    - Error-aware sampling makes the preview useful for Buckaroo because we are
      not clustering merely for visual beauty; we are clustering to find where
      detector errors concentrate.

Run:
    python experiments/error_conditioned_semantic_sketch.py \
        --dataset provided_datasets/adult.csv \
        --rows 30000 \
        --out experiments/semantic_sketch_outputs/adult_sketch.csv
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Importing app.* can initialize database code in Buckaroo. The benchmark only
# needs pure helper behavior, so ask Buckaroo to skip DB startup when respected.
os.environ.setdefault("BUCKAROO_SKIP_DB_INIT", "1")

try:
    from sklearn.cluster import MiniBatchKMeans
    from sklearn.utils import murmurhash3_32
except Exception as exc:  # pragma: no cover - shown as a useful CLI error
    raise RuntimeError("Install scikit-learn before running this experiment.") from exc

try:
    from detectors.anomaly import anomaly
    from detectors.datatype_mismatch import datatype_mismatch
    from detectors.incomplete import incomplete
    from detectors.missing_value import missing_value
    from app.server_utils import semantic_grouping as sg
except Exception:
    anomaly = datatype_mismatch = incomplete = missing_value = None
    sg = None


MISSING_MARKERS = {"", "?", "na", "n/a", "nan", "none", "null", "undefined", "unknown"}
HELPER_COLUMNS = {"ID", "row_id", "column_id", "error_type", "Unnamed: 0"}
WORD_RE = __import__("re").compile(r"[A-Za-z][A-Za-z0-9_+\-#]{1,40}")


@dataclass(frozen=True)
class SketchGroup:
    group_id: int
    rows: int
    error_rows: int
    error_rate: float
    baseline_error_rate: float
    lift: float
    score: float
    main_issue: str
    description: str
    row_ids: list[int]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark matrixless semantic sketches.")
    parser.add_argument("--dataset", type=Path, default=ROOT / "provided_datasets" / "adult.csv")
    parser.add_argument("--rows", type=int, default=30000)
    parser.add_argument("--out", type=Path, default=ROOT / "experiments" / "semantic_sketch_outputs" / "groups.csv")
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--sketch-dim", type=int, default=128)
    parser.add_argument("--coreset-size", type=int, default=6000)
    parser.add_argument("--batch-size", type=int, default=2048)
    parser.add_argument("--text-weight", type=float, default=0.65)
    parser.add_argument("--numeric-weight", type=float, default=0.35)
    parser.add_argument("--max-row-tokens", type=int, default=48)
    return parser.parse_args()


def is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    return str(value).strip().lower() in MISSING_MARKERS


def stable_sign(text: str) -> float:
    """Return +1/-1 deterministically for signed feature hashing."""
    return 1.0 if (murmurhash3_32(text, seed=17, positive=True) & 1) else -1.0


def hash_dim(text: str, dim: int) -> int:
    """Map arbitrary text to a fixed sketch dimension."""
    return murmurhash3_32(text, seed=23, positive=True) % dim


def load_dataset(path: Path, nrows: int | None) -> pd.DataFrame:
    df = pd.read_csv(path, nrows=nrows)
    if "ID" not in df.columns:
        df.insert(0, "ID", np.arange(len(df), dtype=int))
    df["ID"] = pd.to_numeric(df["ID"], errors="coerce").fillna(0).astype(int)
    return df.replace({"?": np.nan, "": np.nan, "null": np.nan, "undefined": np.nan})


def infer_roles(df: pd.DataFrame) -> dict[str, list[str]]:
    numeric, text = [], []
    for column in df.columns:
        if column in HELPER_COLUMNS or str(column).startswith("_"):
            continue
        values = df[column]
        converted = pd.to_numeric(values, errors="coerce")
        non_missing = values.notna().sum()
        numeric_fraction = float(converted.notna().sum()) / max(1, int(non_missing))
        if pd.api.types.is_numeric_dtype(values) or numeric_fraction >= 0.85:
            numeric.append(column)
        else:
            text.append(column)
    return {"numeric": numeric, "text": text}


def detector_errors(df: pd.DataFrame) -> pd.DataFrame:
    """
    Run Buckaroo's current detectors if available.

    The sketch algorithm is independent of the detector implementation. For a
    real Buckaroo integration, this function should be replaced by the existing
    persisted errors_<tablename> table.
    """
    if any(fn is None for fn in [anomaly, incomplete, missing_value, datatype_mismatch]) or sg is None:
        return pd.DataFrame(columns=["row_id", "column_id", "error_type"])

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
    counts = errors.groupby("row_id").size() if not errors.empty else pd.Series(dtype=int)
    df["_has_error"] = df["ID"].isin(set(int(row_id) for row_id in counts.index))
    df["_error_count"] = df["ID"].map(counts).fillna(0).astype(int)
    return df


def tokenize_values(values: Iterable[object], text_columns: list[str], max_tokens: int) -> list[str]:
    """
    Produce interpretable semantic tokens without building a global vocabulary.

    Categorical values keep column context: "occupation=prof-specialty".
    Longer text also contributes word-level tokens: "description~hybrid".
    Missing values are semantic too, because Buckaroo often needs to discover
    groups like "occupation missing and workclass missing".
    """
    tokens: list[str] = []
    seen: set[str] = set()
    budget = max(1, max_tokens)
    for column, value in zip(text_columns, values):
        if len(tokens) >= budget:
            break
        if is_missing(value):
            token = f"{column}=__missing__"
            if token not in seen:
                tokens.append(token)
                seen.add(token)
            continue

        text = str(value).strip().lower()
        compact = " ".join(text.split())
        if compact and len(compact) <= 80:
            token = f"{column}={compact}"
            if token not in seen:
                tokens.append(token)
                seen.add(token)

        for word in WORD_RE.findall(text):
            if len(tokens) >= budget:
                break
            word = word.lower()
            if len(word) > 2:
                token = f"{column}~{word}"
                if token not in seen:
                    tokens.append(token)
                    seen.add(token)
    return tokens[:budget]


def tokenize_row(row: pd.Series, text_columns: list[str], max_tokens: int) -> list[str]:
    """Compatibility wrapper for one-off callers."""
    return tokenize_values((row.get(column) for column in text_columns), text_columns, max_tokens)


class MatrixlessSemanticSketcher:
    """
    Convert rows into small dense semantic sketches.

    The important part: this class does not store an n_rows x n_terms matrix.
    It stores:
      - a hashed document-frequency vector of size sketch_dim;
      - numeric medians/IQRs;
      - tiny dense vectors only for the current batch or coreset.
    """

    def __init__(
        self,
        roles: dict[str, list[str]],
        sketch_dim: int = 128,
        text_weight: float = 0.65,
        numeric_weight: float = 0.35,
        max_row_tokens: int = 48,
    ) -> None:
        self.roles = roles
        self.sketch_dim = int(sketch_dim)
        self.text_weight = float(text_weight)
        self.numeric_weight = float(numeric_weight)
        self.max_row_tokens = int(max_row_tokens)
        self.df_by_dim = np.zeros(self.sketch_dim, dtype=np.float32)
        self.idf_by_dim = np.ones(self.sketch_dim, dtype=np.float32)
        self.numeric_median = np.array([], dtype=np.float32)
        self.numeric_iqr = np.array([], dtype=np.float32)

    @property
    def output_dim(self) -> int:
        return self.sketch_dim + len(self.roles["numeric"])

    def fit_statistics(self, df: pd.DataFrame) -> None:
        n_rows = max(1, len(df))

        text_frame = df[self.roles["text"]] if self.roles["text"] else pd.DataFrame(index=df.index)
        for values in text_frame.itertuples(index=False, name=None):
            dims = {
                hash_dim(token, self.sketch_dim)
                for token in tokenize_values(values, self.roles["text"], self.max_row_tokens)
            }
            for dim in dims:
                self.df_by_dim[dim] += 1.0

        self.idf_by_dim = np.log((1.0 + n_rows) / (1.0 + self.df_by_dim)) + 1.0
        numeric = self._numeric_frame(df)
        if numeric.shape[1]:
            q75 = np.nanpercentile(numeric, 75, axis=0)
            q25 = np.nanpercentile(numeric, 25, axis=0)
            self.numeric_median = np.nanmedian(numeric, axis=0).astype(np.float32)
            self.numeric_median = np.nan_to_num(self.numeric_median, nan=0.0)
            iqr = (q75 - q25).astype(np.float32)
            iqr = np.nan_to_num(iqr, nan=1.0, posinf=1.0, neginf=1.0)
            iqr[iqr == 0] = 1.0
            self.numeric_iqr = iqr

    def transform_batch(self, df: pd.DataFrame) -> np.ndarray:
        text = np.zeros((len(df), self.sketch_dim), dtype=np.float32)
        text_frame = df[self.roles["text"]] if self.roles["text"] else pd.DataFrame(index=df.index)
        for row_index, values in enumerate(text_frame.itertuples(index=False, name=None)):
            for token in tokenize_values(values, self.roles["text"], self.max_row_tokens):
                dim = hash_dim(token, self.sketch_dim)
                text[row_index, dim] += stable_sign(token) * self.idf_by_dim[dim]

        text_norm = np.linalg.norm(text, axis=1, keepdims=True)
        text_norm[text_norm == 0] = 1.0
        text = text / text_norm

        numeric = self._scaled_numeric(df)
        if numeric.shape[1]:
            out = np.concatenate(
                [
                    math.sqrt(max(0.0, self.text_weight)) * text,
                    math.sqrt(max(0.0, self.numeric_weight)) * numeric,
                ],
                axis=1,
            )
        else:
            out = text
        return out.astype(np.float32, copy=False)

    def _numeric_frame(self, df: pd.DataFrame) -> np.ndarray:
        columns = self.roles["numeric"]
        if not columns:
            return np.zeros((len(df), 0), dtype=np.float32)
        return df[columns].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float32)

    def _scaled_numeric(self, df: pd.DataFrame) -> np.ndarray:
        raw = self._numeric_frame(df)
        if raw.shape[1] == 0:
            return raw
        filled = np.where(np.isnan(raw), self.numeric_median, raw)
        scaled = (filled - self.numeric_median) / self.numeric_iqr
        scaled = np.clip(scaled, -5.0, 5.0)
        norms = np.linalg.norm(scaled, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (scaled / norms).astype(np.float32)


def error_aware_coreset(df: pd.DataFrame, size: int, random_state: int = 42) -> pd.DataFrame:
    """
    Build a small training set biased toward Buckaroo's actual objective.

    A uniform sample can miss rare but important error regions. This coreset
    keeps many error rows and enough clean rows to preserve contrast.
    """
    rng = np.random.default_rng(random_state)
    size = min(max(1, int(size)), len(df))
    error_df = df[df["_has_error"]]
    clean_df = df[~df["_has_error"]]

    if error_df.empty or clean_df.empty:
        return df.sample(n=size, random_state=random_state)

    error_n = min(len(error_df), max(size // 2, int(size * 0.60)))
    clean_n = min(len(clean_df), size - error_n)
    if clean_n + error_n < size:
        error_n = min(len(error_df), size - clean_n)

    error_idx = rng.choice(error_df.index.to_numpy(), size=error_n, replace=False)
    clean_idx = rng.choice(clean_df.index.to_numpy(), size=clean_n, replace=False)
    return df.loc[np.concatenate([error_idx, clean_idx])].sample(frac=1.0, random_state=random_state)


def nearest_centroid_labels(matrix: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    """Assign a batch to centroids using vectorized squared Euclidean distance."""
    x2 = np.sum(matrix * matrix, axis=1, keepdims=True)
    c2 = np.sum(centroids * centroids, axis=1, keepdims=True).T
    distances = x2 + c2 - 2.0 * matrix @ centroids.T
    return np.argmin(distances, axis=1).astype(np.int32)


def fit_prototypes(
    sketcher: MatrixlessSemanticSketcher,
    coreset: pd.DataFrame,
    k: int,
    batch_size: int,
) -> tuple[np.ndarray, float]:
    start = time.perf_counter()
    matrix = sketcher.transform_batch(coreset)
    k = max(2, min(int(k), len(coreset)))
    model = MiniBatchKMeans(
        n_clusters=k,
        random_state=42,
        n_init=5,
        batch_size=min(batch_size, max(256, len(coreset))),
    )
    model.fit(matrix)
    return model.cluster_centers_.astype(np.float32), time.perf_counter() - start


def explain_token(token: str) -> str:
    if token.endswith("=__missing__"):
        return f"{token.split('=', 1)[0]} mostly missing"
    if "=" in token:
        column, value = token.split("=", 1)
        return f"{column} mostly {value}"
    if "~" in token:
        column, word = token.split("~", 1)
        return f"{column} mentions {word}"
    return token


def summarize_groups(
    df: pd.DataFrame,
    errors: pd.DataFrame,
    roles: dict[str, list[str]],
    sketcher: MatrixlessSemanticSketcher,
    centroids: np.ndarray,
    batch_size: int,
) -> tuple[list[SketchGroup], float]:
    start = time.perf_counter()
    k = len(centroids)
    rows_by_group = np.zeros(k, dtype=np.int64)
    errors_by_group = np.zeros(k, dtype=np.int64)
    row_ids_by_group: dict[int, list[int]] = defaultdict(list)
    token_counts: list[Counter[str]] = [Counter() for _ in range(k)]
    numeric_sums = np.zeros((k, len(roles["numeric"])), dtype=np.float64)
    numeric_counts = np.zeros((k, len(roles["numeric"])), dtype=np.float64)
    row_to_group: dict[int, int] = {}
    all_ids = df["ID"].to_numpy(dtype=int)
    all_has_error = df["_has_error"].to_numpy(dtype=bool)

    for start_i in range(0, len(df), batch_size):
        batch = df.iloc[start_i:start_i + batch_size]
        matrix = sketcher.transform_batch(batch)
        labels = nearest_centroid_labels(matrix, centroids)
        batch_ids = all_ids[start_i:start_i + len(batch)]
        batch_has_error = all_has_error[start_i:start_i + len(batch)]
        text_frame = batch[roles["text"]] if roles["text"] else pd.DataFrame(index=batch.index)
        text_values = list(text_frame.itertuples(index=False, name=None))
        numeric_values = (
            batch[roles["numeric"]].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=np.float64)
            if roles["numeric"]
            else np.zeros((len(batch), 0), dtype=np.float64)
        )

        for local_i in range(len(batch)):
            label = int(labels[local_i])
            row_id = int(batch_ids[local_i])
            row_to_group[row_id] = label
            rows_by_group[label] += 1
            if bool(batch_has_error[local_i]):
                errors_by_group[label] += 1
            if len(row_ids_by_group[label]) < 2000:
                row_ids_by_group[label].append(row_id)

            for token in tokenize_values(text_values[local_i], roles["text"], 16):
                token_counts[label][token] += 1

            for j in range(len(roles["numeric"])):
                value = numeric_values[local_i, j]
                if not np.isnan(value):
                    numeric_sums[label, j] += float(value)
                    numeric_counts[label, j] += 1.0

    issue_by_group: list[Counter[str]] = [Counter() for _ in range(k)]
    if not errors.empty:
        for _, error in errors.iterrows():
            label = row_to_group.get(int(error["row_id"]))
            if label is not None:
                issue = f"{error['error_type']}:{error['column_id']}"
                issue_by_group[label][issue] += 1

    baseline = float(df["_has_error"].mean()) if len(df) else 0.0
    groups: list[SketchGroup] = []
    global_numeric = {
        column: pd.to_numeric(df[column], errors="coerce").mean()
        for column in roles["numeric"]
    }

    for label in range(k):
        rows = int(rows_by_group[label])
        error_rows = int(errors_by_group[label])
        if rows == 0 or error_rows == 0:
            continue
        error_rate = error_rows / rows
        lift = error_rate / baseline if baseline else 0.0
        # Score balances severity and support. Without support, tiny 100% error
        # groups dominate; without severity, giant mediocre groups dominate.
        score = lift * math.log1p(error_rows)

        phrase_parts: list[str] = []
        for token, count in token_counts[label].most_common(3):
            pct = int(round(100.0 * count / max(1, rows)))
            phrase_parts.append(f"{explain_token(token)} ({pct}%)")

        if roles["numeric"]:
            means = np.divide(
                numeric_sums[label],
                np.maximum(numeric_counts[label], 1.0),
                out=np.zeros_like(numeric_sums[label]),
                where=numeric_counts[label] > 0,
            )
            deviations = []
            for j, column in enumerate(roles["numeric"]):
                global_mean = global_numeric.get(column)
                if pd.isna(global_mean):
                    continue
                deviations.append((abs(float(means[j] - global_mean)), column, float(means[j])))
            for _, column, mean in sorted(deviations, reverse=True)[:2]:
                phrase_parts.append(f"{column} avg {mean:.1f}")

        main_issue = issue_by_group[label].most_common(1)[0][0] if issue_by_group[label] else "unknown"
        groups.append(SketchGroup(
            group_id=label,
            rows=rows,
            error_rows=error_rows,
            error_rate=error_rate,
            baseline_error_rate=baseline,
            lift=lift,
            score=score,
            main_issue=main_issue,
            description="; ".join(phrase_parts) or f"semantic sketch group {label}",
            row_ids=row_ids_by_group[label],
        ))

    groups.sort(key=lambda group: group.score, reverse=True)
    return groups, time.perf_counter() - start


def run(args: argparse.Namespace) -> dict:
    timings: dict[str, float] = {}

    start = time.perf_counter()
    df = load_dataset(args.dataset, args.rows)
    timings["load_sec"] = time.perf_counter() - start

    start = time.perf_counter()
    errors = detector_errors(df)
    df = attach_error_flags(df, errors)
    timings["detector_sec"] = time.perf_counter() - start

    roles = infer_roles(df)
    sketcher = MatrixlessSemanticSketcher(
        roles,
        sketch_dim=args.sketch_dim,
        text_weight=args.text_weight,
        numeric_weight=args.numeric_weight,
        max_row_tokens=args.max_row_tokens,
    )

    start = time.perf_counter()
    sketcher.fit_statistics(df)
    timings["sketch_stats_sec"] = time.perf_counter() - start

    coreset = error_aware_coreset(df, args.coreset_size)
    centroids, timings["prototype_fit_sec"] = fit_prototypes(
        sketcher,
        coreset,
        args.k,
        args.batch_size,
    )
    groups, timings["assign_and_score_sec"] = summarize_groups(
        df,
        errors,
        roles,
        sketcher,
        centroids,
        args.batch_size,
    )

    meta = {
        "dataset": str(args.dataset),
        "rows": len(df),
        "error_rows": int(df["_has_error"].sum()),
        "baseline_error_rate": float(df["_has_error"].mean()) if len(df) else 0.0,
        "error_records": len(errors),
        "roles": roles,
        "sketch_dim": args.sketch_dim,
        "output_dim": sketcher.output_dim,
        "coreset_rows": len(coreset),
        "timings": timings,
    }
    return {"meta": meta, "groups": groups}


def main() -> None:
    args = parse_args()
    result = run(args)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(group) for group in result["groups"]]
    pd.DataFrame(rows).to_csv(args.out, index=False)

    json_out = args.json_out or args.out.with_suffix(".json")
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(
            {
                "meta": result["meta"],
                "groups": rows,
            },
            f,
            indent=2,
        )

    print(json.dumps(result["meta"], indent=2, default=str))
    print(pd.DataFrame(rows).head(8).to_string(index=False, max_colwidth=100))
    print(f"Wrote: {args.out}")
    print(f"Wrote: {json_out}")


if __name__ == "__main__":
    main()
