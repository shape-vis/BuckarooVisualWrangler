"""
Standalone semantic grouping playground for Buckaroo research.

This script intentionally runs outside the Buckaroo Flask/Postgres app. It loads
1000 rows from provided_datasets/adult.csv, creates row-level error labels, and
compares three grouping strategies:

1. exact_slices: SliceFinder-lite exact one/two-column groups.
2. cluster_first: Cluster all rows, then rank clusters by error concentration.
3. error_first: Filter to error rows first, then cluster those rows.

Run:
    python experiments/semantic_grouping_playground.py
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "provided_datasets" / "adult.csv"
OUT_DIR = ROOT / "experiments" / "outputs"

NUMERIC_COLUMNS = [
    "age",
    "educational-num",
    "capital-gain",
    "capital-loss",
    "hours-per-week",
]

CATEGORICAL_COLUMNS = [
    "workclass",
    "education",
    "marital-status",
    "occupation",
    "relationship",
    "race",
    "gender",
    "native-country",
    "income",
]


@dataclass(frozen=True)
class GroupSummary:
    strategy: str
    group: str
    rows: int
    error_rows: int
    error_rate: float
    baseline_error_rate: float
    lift: float
    score: float
    main_issue: str


def load_sample(n_rows: int = 1000) -> pd.DataFrame:
    df = pd.read_csv(DATASET, nrows=n_rows)
    df.insert(0, "ID", np.arange(1, len(df) + 1))
    df = df.replace("?", np.nan)
    return df


def add_error_labels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Make a simple row-level error table.

    The first two rules mimic real detector output: missing values and numeric
    outliers. The last two rules intentionally inject concentrated errors so
    the experiment has patterns you can discover and explain in a meeting.
    """
    df = df.copy()
    issues = [[] for _ in range(len(df))]

    missing_mask = df.isna().any(axis=1).to_numpy()
    for i in np.flatnonzero(missing_mask):
        issues[i].append("missing_value")

    for col in NUMERIC_COLUMNS:
        values = pd.to_numeric(df[col], errors="coerce")
        q1 = values.quantile(0.25)
        q3 = values.quantile(0.75)
        iqr = q3 - q1
        if pd.isna(iqr) or iqr == 0:
            continue
        outlier_mask = (values < q1 - 1.5 * iqr) | (values > q3 + 1.5 * iqr)
        for i in np.flatnonzero(outlier_mask.to_numpy()):
            issues[i].append(f"numeric_outlier:{col}")

    education_issue = (
        df["education"].isin(["Masters", "Doctorate"])
        & (pd.to_numeric(df["hours-per-week"], errors="coerce") >= 45)
    )
    for i in np.flatnonzero(education_issue.to_numpy()):
        issues[i].append("injected:advanced_degree_long_hours")

    occupation_issue = (
        (df["occupation"] == "Other-service")
        & (pd.to_numeric(df["age"], errors="coerce") < 30)
    )
    for i in np.flatnonzero(occupation_issue.to_numpy()):
        issues[i].append("injected:young_other_service")

    df["error_types"] = [";".join(row_issues) for row_issues in issues]
    df["error_count"] = [len(row_issues) for row_issues in issues]
    df["has_error"] = df["error_count"] > 0
    return df


def main_issue(rows: pd.DataFrame) -> str:
    counts: dict[str, int] = {}
    for value in rows["error_types"]:
        if not value:
            continue
        for issue in value.split(";"):
            counts[issue] = counts.get(issue, 0) + 1
    if not counts:
        return "none"
    return max(counts.items(), key=lambda item: item[1])[0]


def summarize_group(
    strategy: str,
    group_name: str,
    rows: pd.DataFrame,
    baseline_error_rate: float,
    min_rows: int = 20,
    min_error_rows: int = 5,
) -> GroupSummary | None:
    row_count = len(rows)
    error_rows = int(rows["has_error"].sum())
    if row_count < min_rows or error_rows < min_error_rows:
        return None

    error_rate = error_rows / row_count
    lift = error_rate / baseline_error_rate if baseline_error_rate else 0
    score = lift * np.log1p(error_rows)
    return GroupSummary(
        strategy=strategy,
        group=group_name,
        rows=row_count,
        error_rows=error_rows,
        error_rate=error_rate,
        baseline_error_rate=baseline_error_rate,
        lift=lift,
        score=score,
        main_issue=main_issue(rows),
    )


def make_bins(df: pd.DataFrame, numeric_columns: list[str], bins: int = 5) -> pd.DataFrame:
    binned = df.copy()
    for col in numeric_columns:
        values = pd.to_numeric(binned[col], errors="coerce")
        # qcut handles skew better than equal-width bins for columns like income.
        binned[f"{col}_bin"] = pd.qcut(values, q=bins, duplicates="drop").astype(str)
    return binned


def exact_slice_search(df: pd.DataFrame) -> list[GroupSummary]:
    baseline = float(df["has_error"].mean())
    binned = make_bins(df, NUMERIC_COLUMNS)
    group_columns = CATEGORICAL_COLUMNS + [f"{col}_bin" for col in NUMERIC_COLUMNS]
    summaries: list[GroupSummary] = []

    for col in group_columns:
        for value, rows in binned.groupby(col, dropna=False):
            summary = summarize_group(
                "exact_slices",
                f"{col} = {value}",
                rows,
                baseline,
            )
            if summary:
                summaries.append(summary)

    # Try pairs only among the most compact columns to avoid explosion.
    compact_columns = [
        col for col in group_columns
        if 2 <= binned[col].nunique(dropna=False) <= 12
    ]
    for i, left in enumerate(compact_columns):
        for right in compact_columns[i + 1:]:
            for values, rows in binned.groupby([left, right], dropna=False):
                summary = summarize_group(
                    "exact_slices",
                    f"{left} = {values[0]} AND {right} = {values[1]}",
                    rows,
                    baseline,
                )
                if summary:
                    summaries.append(summary)

    return sorted(summaries, key=lambda item: item.score, reverse=True)


def robust_scale_numeric(df: pd.DataFrame, columns: list[str]) -> np.ndarray:
    matrix = df[columns].apply(pd.to_numeric, errors="coerce").fillna(0).to_numpy(dtype=float).copy()
    # Log-scale highly skewed nonnegative columns.
    for idx, col in enumerate(columns):
        if col in {"capital-gain", "capital-loss"}:
            matrix[:, idx] = np.log1p(np.maximum(matrix[:, idx], 0))

    median = np.median(matrix, axis=0)
    q1 = np.quantile(matrix, 0.25, axis=0)
    q3 = np.quantile(matrix, 0.75, axis=0)
    iqr = np.where((q3 - q1) == 0, 1, q3 - q1)
    return (matrix - median) / iqr


def kmeans_numpy(matrix: np.ndarray, k: int = 6, iterations: int = 40, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    if len(matrix) < k:
        return np.zeros(len(matrix), dtype=int)

    centers = matrix[rng.choice(len(matrix), size=k, replace=False)].copy()
    labels = np.zeros(len(matrix), dtype=int)
    for _ in range(iterations):
        distances = ((matrix[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        next_labels = distances.argmin(axis=1)
        if np.array_equal(labels, next_labels):
            break
        labels = next_labels
        for cluster_id in range(k):
            members = matrix[labels == cluster_id]
            if len(members) > 0:
                centers[cluster_id] = members.mean(axis=0)
    return labels


def describe_numeric_cluster(rows: pd.DataFrame, all_rows: pd.DataFrame) -> str:
    parts = []
    for col in NUMERIC_COLUMNS:
        group_mean = pd.to_numeric(rows[col], errors="coerce").mean()
        overall_mean = pd.to_numeric(all_rows[col], errors="coerce").mean()
        if pd.notna(group_mean) and pd.notna(overall_mean):
            delta = group_mean - overall_mean
            parts.append((abs(delta), f"{col} avg {group_mean:.1f}"))
    parts.sort(reverse=True)
    return ", ".join(part for _, part in parts[:3])


def cluster_first(df: pd.DataFrame) -> list[GroupSummary]:
    baseline = float(df["has_error"].mean())
    matrix = robust_scale_numeric(df, NUMERIC_COLUMNS)
    labels = kmeans_numpy(matrix, k=6)
    clustered = df.copy()
    clustered["cluster"] = labels

    summaries = []
    for cluster_id, rows in clustered.groupby("cluster"):
        descriptor = describe_numeric_cluster(rows, clustered)
        summary = summarize_group(
            "cluster_first",
            f"numeric_cluster_{cluster_id}: {descriptor}",
            rows,
            baseline,
        )
        if summary:
            summaries.append(summary)
    return sorted(summaries, key=lambda item: item.score, reverse=True)


def error_first(df: pd.DataFrame) -> list[GroupSummary]:
    baseline = float(df["has_error"].mean())
    error_rows = df[df["has_error"]].copy()
    if error_rows.empty:
        return []
    matrix = robust_scale_numeric(error_rows, NUMERIC_COLUMNS)
    labels = kmeans_numpy(matrix, k=min(5, len(error_rows)))
    error_rows["error_cluster"] = labels

    summaries = []
    for cluster_id, rows in error_rows.groupby("error_cluster"):
        descriptor = describe_numeric_cluster(rows, df)
        summary = summarize_group(
            "error_first",
            f"error_cluster_{cluster_id}: {descriptor}",
            rows,
            baseline,
        )
        if summary:
            summaries.append(summary)
    return sorted(summaries, key=lambda item: item.score, reverse=True)


def write_results(name: str, summaries: list[GroupSummary], limit: int = 15) -> pd.DataFrame:
    rows = [summary.__dict__ for summary in summaries[:limit]]
    result = pd.DataFrame(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT_DIR / f"{name}.csv", index=False)
    return result


def print_table(title: str, frame: pd.DataFrame) -> None:
    print(f"\n=== {title} ===")
    if frame.empty:
        print("No groups passed thresholds.")
        return
    cols = ["group", "rows", "error_rows", "error_rate", "lift", "score", "main_issue"]
    display = frame[cols].copy()
    display["error_rate"] = display["error_rate"].map(lambda value: f"{value:.1%}")
    display["lift"] = display["lift"].map(lambda value: f"{value:.2f}x")
    display["score"] = display["score"].map(lambda value: f"{value:.2f}")
    print(display.to_string(index=False))


def main() -> None:
    df = add_error_labels(load_sample())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_DIR / "adult_1000_with_error_labels.csv", index=False)

    print(f"Rows: {len(df)}")
    print(f"Baseline error rate: {df['has_error'].mean():.1%}")
    print(f"Output folder: {OUT_DIR}")

    exact = write_results("strategy_exact_slices", exact_slice_search(df))
    cluster = write_results("strategy_cluster_first", cluster_first(df))
    error = write_results("strategy_error_first", error_first(df))

    print_table("Strategy A: exact slices", exact)
    print_table("Strategy B: cluster first", cluster)
    print_table("Strategy C: error first", error)


if __name__ == "__main__":
    main()
