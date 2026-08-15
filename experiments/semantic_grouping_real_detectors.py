"""
Semantic grouping experiment using Buckaroo's real detector output.

This is a research playground, not production Buckaroo code. It compares three
strategies on a small sample:

1. exact_slices:
   Human-readable exact/semantic groups, similar to Slice Finder.
2. cluster_first:
   Cluster all rows using normalized numeric features plus semantic category
   concepts, then rank clusters by error concentration.
3. error_first:
   Filter to rows with Buckaroo-detected errors, cluster those bad rows, then
   describe what the bad rows have in common.

Run:
    python experiments/semantic_grouping_real_detectors.py
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
import sys
import zlib

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from detectors.anomaly import anomaly
from detectors.datatype_mismatch import datatype_mismatch
from detectors.incomplete import incomplete
from detectors.missing_value import missing_value


DATASET = ROOT / "provided_datasets" / "adult.csv"
OUT_DIR = ROOT / "experiments" / "semantic_outputs"

SAMPLE_ROWS = 1000
MIN_GROUP_ROWS = 20
MIN_ERROR_ROWS = 5
TOP_N = 20

DISPLAY_NAMES = {
    "age": "age",
    "fnlwgt": "survey weight",
    "educational-num": "education years",
    "capital-gain": "capital gain",
    "capital-loss": "capital loss",
    "hours-per-week": "weekly work hours",
}

SEMANTIC_VALUE_MAP = {
    "workclass": {
        "Private": "private sector",
        "Self-emp-not-inc": "self employed",
        "Self-emp-inc": "self employed",
        "Federal-gov": "government",
        "Local-gov": "government",
        "State-gov": "government",
        "Without-pay": "unpaid work",
        "Never-worked": "not employed",
    },
    "education": {
        "Preschool": "early school",
        "1st-4th": "early school",
        "5th-6th": "early school",
        "7th-8th": "middle school",
        "9th": "high school incomplete",
        "10th": "high school incomplete",
        "11th": "high school incomplete",
        "12th": "high school incomplete",
        "HS-grad": "high school graduate",
        "Some-college": "some college",
        "Assoc-voc": "associate degree",
        "Assoc-acdm": "associate degree",
        "Bachelors": "bachelors degree",
        "Masters": "advanced degree",
        "Doctorate": "advanced degree",
        "Prof-school": "advanced degree",
    },
    "marital-status": {
        "Married-civ-spouse": "married",
        "Married-AF-spouse": "married",
        "Married-spouse-absent": "married spouse absent",
        "Never-married": "never married",
        "Divorced": "separated or divorced",
        "Separated": "separated or divorced",
        "Widowed": "widowed",
    },
    "occupation": {
        "Tech-support": "technical work",
        "Prof-specialty": "professional work",
        "Exec-managerial": "management work",
        "Adm-clerical": "administrative work",
        "Sales": "sales work",
        "Other-service": "service work",
        "Priv-house-serv": "service work",
        "Protective-serv": "service work",
        "Craft-repair": "manual skilled work",
        "Machine-op-inspct": "manual machine work",
        "Transport-moving": "manual transport work",
        "Handlers-cleaners": "manual labor",
        "Farming-fishing": "manual outdoor work",
        "Armed-Forces": "military work",
    },
    "relationship": {
        "Husband": "spouse",
        "Wife": "spouse",
        "Own-child": "child",
        "Not-in-family": "not in family",
        "Other-relative": "relative",
        "Unmarried": "unmarried",
    },
    "native-country": {
        "United-States": "united states",
        "Canada": "north america",
        "Mexico": "latin america",
        "Puerto-Rico": "latin america",
        "Cuba": "latin america",
        "Jamaica": "latin america",
        "Dominican-Republic": "latin america",
        "El-Salvador": "latin america",
        "Guatemala": "latin america",
        "Haiti": "latin america",
        "Honduras": "latin america",
        "Nicaragua": "latin america",
        "Columbia": "latin america",
        "Ecuador": "latin america",
        "Peru": "latin america",
        "India": "asia",
        "China": "asia",
        "Japan": "asia",
        "Cambodia": "asia",
        "Laos": "asia",
        "Philippines": "asia",
        "Thailand": "asia",
        "Vietnam": "asia",
        "Taiwan": "asia",
        "Iran": "asia",
        "England": "europe",
        "France": "europe",
        "Germany": "europe",
        "Greece": "europe",
        "Holand-Netherlands": "europe",
        "Hungary": "europe",
        "Ireland": "europe",
        "Italy": "europe",
        "Poland": "europe",
        "Portugal": "europe",
        "Scotland": "europe",
        "Yugoslavia": "europe",
        "South": "other region",
        "Outlying-US(Guam-USVI-etc)": "us territory",
        "Trinadad&Tobago": "caribbean",
    },
    "income": {
        "<=50K": "lower income",
        ">50K": "higher income",
    },
}


@dataclass(frozen=True)
class GroupSummary:
    strategy: str
    group: str
    description: str
    rows: int
    error_rows: int
    error_rate: float
    baseline_error_rate: float
    lift: float
    score: float
    error_coverage: float
    main_issue: str
    main_error_columns: str
    example_row_ids: str


def load_sample(n_rows: int = SAMPLE_ROWS) -> pd.DataFrame:
    df = pd.read_csv(DATASET, nrows=n_rows)
    df = df.replace("?", np.nan)
    if "ID" not in df.columns:
        df.insert(0, "ID", np.arange(1, len(df) + 1))
    return df


def run_buckaroo_detectors(df: pd.DataFrame) -> pd.DataFrame:
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

    records = []
    for error_map in detector_maps:
        for column_id, row_errors in error_map.items():
            for row_id, error_type in row_errors.items():
                records.append(
                    {
                        "row_id": int(row_id),
                        "column_id": str(column_id),
                        "error_type": str(error_type),
                    }
                )
    if not records:
        return pd.DataFrame(columns=["row_id", "column_id", "error_type"])
    return pd.DataFrame(records).drop_duplicates()


def attach_error_labels(df: pd.DataFrame, errors: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    grouped = errors.groupby("row_id") if not errors.empty else {}
    error_types = {}
    error_columns = {}
    error_counts = {}

    if not errors.empty:
        for row_id, rows in grouped:
            type_col_pairs = [
                f"{row.error_type}:{row.column_id}"
                for row in rows.itertuples(index=False)
            ]
            error_types[int(row_id)] = ";".join(type_col_pairs)
            error_columns[int(row_id)] = ";".join(sorted(set(rows["column_id"])))
            error_counts[int(row_id)] = len(rows)

    result["error_types"] = result["ID"].map(error_types).fillna("")
    result["error_columns"] = result["ID"].map(error_columns).fillna("")
    result["error_count"] = result["ID"].map(error_counts).fillna(0).astype(int)
    result["has_error"] = result["error_count"] > 0
    return result


def infer_columns(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    numeric_cols = []
    categorical_cols = []
    for col in df.columns:
        if col in {"ID", "error_types", "error_columns", "error_count", "has_error"}:
            continue
        numeric = pd.to_numeric(df[col], errors="coerce")
        if numeric.notna().mean() > 0.85:
            numeric_cols.append(col)
        else:
            categorical_cols.append(col)
    return numeric_cols, categorical_cols


def safe_token(text: object) -> str:
    text = "" if pd.isna(text) else str(text).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "missing"


def semantic_concept(column: str, value: object) -> str:
    if pd.isna(value):
        return "missing"
    value_text = str(value)
    mapped = SEMANTIC_VALUE_MAP.get(column, {}).get(value_text)
    if mapped:
        return mapped
    if column in {"race", "gender"}:
        return value_text.lower()
    return value_text.replace("-", " ").replace("_", " ").lower()


def add_semantic_columns(df: pd.DataFrame, categorical_cols: list[str]) -> pd.DataFrame:
    result = df.copy()
    for col in categorical_cols:
        result[f"semantic_{col}"] = result[col].map(lambda value: semantic_concept(col, value))
    return result


def token_label(token: str) -> str:
    token = token.replace("semantic_", "")
    if "=" not in token:
        return token.replace("_", " ")
    col, value = token.split("=", 1)
    return f"{col.replace('_', ' ')} is {value.replace('_', ' ')}"


def semantic_tokens_for_row(row: pd.Series, categorical_cols: list[str]) -> list[str]:
    tokens = []
    for col in categorical_cols:
        concept = semantic_concept(col, row[col])
        tokens.append(f"semantic_{col}={safe_token(concept)}")
        if pd.isna(row[col]):
            tokens.append(f"missing_{col}")
    return tokens


def build_semantic_feature_matrix(
    df: pd.DataFrame,
    numeric_cols: list[str],
    categorical_cols: list[str],
    semantic_weight: float = 1.0,
) -> tuple[np.ndarray, list[str], np.ndarray, list[str]]:
    numeric = robust_scale_numeric(df, numeric_cols) if numeric_cols else np.empty((len(df), 0))

    row_tokens = [semantic_tokens_for_row(row, categorical_cols) for _, row in df.iterrows()]
    counts: dict[str, int] = {}
    for tokens in row_tokens:
        for token in set(tokens):
            counts[token] = counts.get(token, 0) + 1

    vocab = [
        token
        for token, count in sorted(counts.items())
        if count >= 5 and count <= max(len(df) - 5, 5)
    ]
    token_to_idx = {token: idx for idx, token in enumerate(vocab)}
    semantic = np.zeros((len(df), len(vocab)), dtype=float)
    for row_idx, tokens in enumerate(row_tokens):
        for token in set(tokens):
            idx = token_to_idx.get(token)
            if idx is not None:
                semantic[row_idx, idx] = semantic_weight

    combined = np.hstack([numeric, semantic])
    return combined, vocab, semantic, row_tokens


def robust_scale_numeric(df: pd.DataFrame, columns: list[str]) -> np.ndarray:
    matrix = (
        df[columns]
        .apply(pd.to_numeric, errors="coerce")
        .fillna(0)
        .to_numpy(dtype=float)
        .copy()
    )
    for idx, col in enumerate(columns):
        nonnegative = matrix[:, idx] >= 0
        if nonnegative.all() and np.quantile(matrix[:, idx], 0.95) > 10 * max(np.median(matrix[:, idx]), 1):
            matrix[:, idx] = np.log1p(matrix[:, idx])

    median = np.median(matrix, axis=0)
    q1 = np.quantile(matrix, 0.25, axis=0)
    q3 = np.quantile(matrix, 0.75, axis=0)
    iqr = np.where((q3 - q1) == 0, 1, q3 - q1)
    return (matrix - median) / iqr


def kmeans_numpy(matrix: np.ndarray, k: int, iterations: int = 60, seed: int = 13) -> np.ndarray:
    if len(matrix) == 0:
        return np.array([], dtype=int)
    k = max(1, min(k, len(matrix)))
    rng = np.random.default_rng(seed)
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
            if len(members):
                centers[cluster_id] = members.mean(axis=0)
    return labels


def main_issue(rows: pd.DataFrame) -> str:
    counts: dict[str, int] = {}
    for value in rows["error_types"]:
        if not value:
            continue
        for issue in str(value).split(";"):
            counts[issue] = counts.get(issue, 0) + 1
    if not counts:
        return "none"
    return max(counts.items(), key=lambda item: item[1])[0]


def main_error_columns(rows: pd.DataFrame, limit: int = 3) -> str:
    counts: dict[str, int] = {}
    for value in rows["error_columns"]:
        if not value:
            continue
        for col in str(value).split(";"):
            counts[col] = counts.get(col, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return ", ".join(f"{col} ({count})" for col, count in ordered[:limit]) or "none"


def describe_rows(
    rows: pd.DataFrame,
    all_rows: pd.DataFrame,
    numeric_cols: list[str],
    categorical_cols: list[str],
) -> str:
    parts = []

    for col in numeric_cols:
        group_mean = pd.to_numeric(rows[col], errors="coerce").mean()
        all_mean = pd.to_numeric(all_rows[col], errors="coerce").mean()
        all_std = pd.to_numeric(all_rows[col], errors="coerce").std()
        if pd.notna(group_mean) and pd.notna(all_mean):
            scale = all_std if pd.notna(all_std) and all_std > 0 else 1
            strength = abs(group_mean - all_mean) / scale
            label = DISPLAY_NAMES.get(col, col)
            parts.append((strength, f"{label} avg {group_mean:.1f}"))

    group_size = max(len(rows), 1)
    all_size = max(len(all_rows), 1)
    for col in categorical_cols:
        group_concepts = rows[col].map(lambda value: semantic_concept(col, value))
        all_concepts = all_rows[col].map(lambda value: semantic_concept(col, value))
        group_freq = group_concepts.value_counts(dropna=False)
        all_freq = all_concepts.value_counts(dropna=False)
        for value, count in group_freq.head(5).items():
            group_rate = count / group_size
            all_rate = all_freq.get(value, 0) / all_size
            lift = group_rate / all_rate if all_rate else 0
            if group_rate >= 0.3 and lift >= 1.25:
                label = f"{col} mostly {value} ({group_rate:.0%})"
                parts.append((lift, label))

    parts.sort(key=lambda item: item[0], reverse=True)
    return "; ".join(part for _, part in parts[:5]) or "mixed rows"


def summarize_group(
    strategy: str,
    group_name: str,
    rows: pd.DataFrame,
    all_rows: pd.DataFrame,
    baseline_error_rate: float,
    total_error_rows: int,
    description: str | None = None,
) -> GroupSummary | None:
    row_count = len(rows)
    error_rows = int(rows["has_error"].sum())
    if row_count < MIN_GROUP_ROWS or error_rows < MIN_ERROR_ROWS:
        return None

    error_rate = error_rows / row_count
    lift = error_rate / baseline_error_rate if baseline_error_rate else 0
    score = lift * np.log1p(error_rows)
    error_coverage = error_rows / total_error_rows if total_error_rows else 0
    example_ids = ", ".join(str(int(row_id)) for row_id in rows.loc[rows["has_error"], "ID"].head(8))
    numeric_cols, categorical_cols = infer_columns(all_rows)
    return GroupSummary(
        strategy=strategy,
        group=group_name,
        description=description or describe_rows(rows, all_rows, numeric_cols, categorical_cols),
        rows=row_count,
        error_rows=error_rows,
        error_rate=error_rate,
        baseline_error_rate=baseline_error_rate,
        lift=lift,
        score=score,
        error_coverage=error_coverage,
        main_issue=main_issue(rows),
        main_error_columns=main_error_columns(rows),
        example_row_ids=example_ids,
    )


def add_numeric_bins(df: pd.DataFrame, numeric_cols: list[str], bins: int = 5) -> pd.DataFrame:
    result = df.copy()
    for col in numeric_cols:
        values = pd.to_numeric(result[col], errors="coerce")
        try:
            result[f"{col}_bin"] = pd.qcut(values, q=bins, duplicates="drop").astype(str)
        except ValueError:
            result[f"{col}_bin"] = "unbinned"
    return result


def exact_slices(df: pd.DataFrame) -> list[GroupSummary]:
    numeric_cols, categorical_cols = infer_columns(df)
    baseline = float(df["has_error"].mean())
    total_error_rows = int(df["has_error"].sum())
    enriched = add_semantic_columns(add_numeric_bins(df, numeric_cols), categorical_cols)
    semantic_cols = [f"semantic_{col}" for col in categorical_cols]
    bin_cols = [f"{col}_bin" for col in numeric_cols]
    group_cols = categorical_cols + semantic_cols + bin_cols

    summaries: list[GroupSummary] = []
    for col in group_cols:
        for value, rows in enriched.groupby(col, dropna=False):
            summary = summarize_group(
                "exact_slices",
                f"{col} = {value}",
                rows,
                enriched,
                baseline,
                total_error_rows,
            )
            if summary:
                summaries.append(summary)

    compact_cols = [
        col
        for col in semantic_cols + bin_cols
        if 2 <= enriched[col].nunique(dropna=False) <= 12
    ]
    for i, left in enumerate(compact_cols):
        for right in compact_cols[i + 1:]:
            for values, rows in enriched.groupby([left, right], dropna=False):
                summary = summarize_group(
                    "exact_slices",
                    f"{left} = {values[0]} AND {right} = {values[1]}",
                    rows,
                    enriched,
                    baseline,
                    total_error_rows,
                )
                if summary:
                    summaries.append(summary)

    return sorted(summaries, key=lambda item: item.score, reverse=True)


def cluster_first(df: pd.DataFrame) -> list[GroupSummary]:
    numeric_cols, categorical_cols = infer_columns(df)
    baseline = float(df["has_error"].mean())
    total_error_rows = int(df["has_error"].sum())
    matrix, _, _, _ = build_semantic_feature_matrix(df, numeric_cols, categorical_cols)
    labels = kmeans_numpy(matrix, k=8)
    clustered = df.copy()
    clustered["cluster_id"] = labels

    summaries = []
    for cluster_id, rows in clustered.groupby("cluster_id"):
        description = describe_rows(rows, clustered, numeric_cols, categorical_cols)
        summary = summarize_group(
            "cluster_first",
            f"semantic_numeric_cluster_{cluster_id}",
            rows,
            clustered,
            baseline,
            total_error_rows,
            description=description,
        )
        if summary:
            summaries.append(summary)
    return sorted(summaries, key=lambda item: item.score, reverse=True)


def error_first(df: pd.DataFrame) -> list[GroupSummary]:
    numeric_cols, categorical_cols = infer_columns(df)
    baseline = float(df["has_error"].mean())
    total_error_rows = int(df["has_error"].sum())
    error_rows = df[df["has_error"]].copy()
    if error_rows.empty:
        return []

    matrix, _, _, _ = build_semantic_feature_matrix(error_rows, numeric_cols, categorical_cols)
    labels = kmeans_numpy(matrix, k=6)
    error_rows["error_cluster_id"] = labels

    summaries = []
    for cluster_id, rows in error_rows.groupby("error_cluster_id"):
        description = describe_rows(rows, df, numeric_cols, categorical_cols)
        summary = summarize_group(
            "error_first",
            f"semantic_error_cluster_{cluster_id}",
            rows,
            df,
            baseline,
            total_error_rows,
            description=description,
        )
        if summary:
            summaries.append(summary)
    return sorted(summaries, key=lambda item: item.score, reverse=True)


def write_results(name: str, summaries: list[GroupSummary], limit: int = TOP_N) -> pd.DataFrame:
    rows = [asdict(summary) for summary in summaries[:limit]]
    result = pd.DataFrame(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUT_DIR / f"{name}.csv", index=False)
    return result


def write_markdown_report(frames: dict[str, pd.DataFrame], df: pd.DataFrame, errors: pd.DataFrame) -> None:
    report = [
        "# Semantic Grouping Experiment",
        "",
        f"Dataset: adult.csv first {len(df)} rows",
        f"Real Buckaroo detector records: {len(errors)}",
        f"Rows with at least one detector error: {int(df['has_error'].sum())}",
        f"Baseline row error rate: {df['has_error'].mean():.1%}",
        "",
    ]
    for name, frame in frames.items():
        report.append(f"## {name}")
        if frame.empty:
            report.append("No groups passed thresholds.")
            continue
        for row in frame.head(5).itertuples(index=False):
            report.append(
                f"- {row.group}: {row.error_rows}/{row.rows} error rows "
                f"({row.error_rate:.1%}, lift {row.lift:.2f}x). "
                f"Description: {row.description}. Main issue: {row.main_issue}."
            )
        report.append("")
    (OUT_DIR / "strategy_comparison.md").write_text("\n".join(report), encoding="utf-8")


def print_brief(title: str, frame: pd.DataFrame) -> None:
    print(f"\n=== {title} ===")
    if frame.empty:
        print("No groups passed thresholds.")
        return
    columns = [
        "group",
        "description",
        "rows",
        "error_rows",
        "error_rate",
        "lift",
        "error_coverage",
        "main_issue",
        "main_error_columns",
    ]
    display = frame[columns].head(8).copy()
    display["error_rate"] = display["error_rate"].map(lambda value: f"{value:.1%}")
    display["lift"] = display["lift"].map(lambda value: f"{value:.2f}x")
    display["error_coverage"] = display["error_coverage"].map(lambda value: f"{value:.1%}")
    print(display.to_string(index=False))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw = load_sample()
    errors = run_buckaroo_detectors(raw)
    df = attach_error_labels(raw, errors)
    df.to_csv(OUT_DIR / "adult_1000_real_buckaroo_errors.csv", index=False)
    errors.to_csv(OUT_DIR / "adult_1000_error_table.csv", index=False)

    print(f"Rows: {len(df)}")
    print(f"Detector error records: {len(errors)}")
    print(f"Rows with errors: {int(df['has_error'].sum())}")
    print(f"Baseline row error rate: {df['has_error'].mean():.1%}")
    print(f"Output folder: {OUT_DIR}")

    frames = {
        "exact_slices": write_results("strategy_exact_slices_semantic", exact_slices(df)),
        "cluster_first": write_results("strategy_cluster_first_semantic", cluster_first(df)),
        "error_first": write_results("strategy_error_first_semantic", error_first(df)),
    }
    write_markdown_report(frames, df, errors)

    print_brief("Strategy A: exact semantic slices", frames["exact_slices"])
    print_brief("Strategy B: semantic/numeric cluster first", frames["cluster_first"])
    print_brief("Strategy C: semantic/numeric error first", frames["error_first"])


if __name__ == "__main__":
    main()
