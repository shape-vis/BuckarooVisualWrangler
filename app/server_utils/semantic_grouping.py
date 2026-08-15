"""
Semantic row grouping for Buckaroo error analysis.

The goal is to find understandable row groups where Buckaroo detector errors
are unusually concentrated.  The implementation is deliberately self-contained:
text/category meaning comes from TF-IDF token similarity, numeric meaning comes
from robust-scaled numeric features, and clustering is deterministic k-means.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import math
import re
from typing import Iterable

import numpy as np
import pandas as pd

from detectors.common import MISSING_MARKERS, is_missing_value as shared_is_missing_value
from app.wrangle_operations.sql_utils import id_list, quote_identifier


DEFAULT_LIMIT = 8
DEFAULT_MIN_GROUP_SIZE = 12
DEFAULT_MIN_ERROR_ROWS = 2
DEFAULT_SAMPLE_ROWS = 5000
MAX_TEXT_FEATURES = 350
MAX_ROW_IDS_RETURNED = 2000
SEMANTIC_TOOL_NAME = "buckaroo_tfidf_cosine_v1"
SEMANTIC_TOOL_DESCRIPTION = (
    "TF-IDF token similarity over text/category values plus robust-scaled "
    "numeric similarity, clustered with deterministic k-means."
)

HELPER_COLUMNS = {
    "ID",
    "row_id",
    "column_id",
    "error_type",
    "Unnamed: 0",
}

STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "were",
    "with",
}


@dataclass(frozen=True)
class SemanticGroup:
    """Compatibility result from the original TF-IDF/numeric grouping path."""

    id: str
    strategy: str
    group: str
    description: str
    rows: int
    errorRows: int
    errorRate: float
    baselineErrorRate: float
    lift: float
    score: float
    errorCoverage: float
    mainIssue: str
    mainErrorColumns: list[str]
    rowIds: list[int]
    rowIdsTruncated: bool
    featureHighlights: list[str]


def generate_semantic_grouping_json(
    tablename: str,
    engine,
    strategy: str = "auto",
    limit: int = DEFAULT_LIMIT,
    sample_rows: int = DEFAULT_SAMPLE_ROWS,
    cluster_count: int | None = None,
    min_group_size: int = DEFAULT_MIN_GROUP_SIZE,
    min_error_rows: int = DEFAULT_MIN_ERROR_ROWS,
) -> dict:
    """
    Public entry point used by the Flask API route.

    Behavior:
    - The frontend requests semantic groups for the current Buckaroo table.
    - This function loads the table rows and the detector errors from Postgres.
    - Then it delegates to build_semantic_groups_from_frames(), which does the
      actual semantic feature construction, clustering/slicing, and scoring.

    Parameters:
    - tablename: current Buckaroo data table, for example "n1_stackoverflow..."
    - engine: SQLAlchemy database engine
    - strategy: "auto", "cluster_first", "error_first", or "exact_slices"
    - limit: how many groups to return to the UI
    - sample_rows: max number of table rows to analyze in this request
    - cluster_count: optional explicit k for k-means; if None we choose one
    - min_group_size: ignore groups smaller than this
    - min_error_rows: ignore groups with too few actual error rows

    Output:
    - A JSON-ready dict containing metadata plus a list of ranked groups.
    """
    main_df, error_df, total_rows = load_table_and_errors(tablename, engine, sample_rows)
    return build_semantic_groups_from_frames(
        main_df,
        error_df,
        strategy=strategy,
        limit=limit,
        sample_rows=sample_rows,
        cluster_count=cluster_count,
        min_group_size=min_group_size,
        min_error_rows=min_error_rows,
        total_rows=total_rows,
    )


def load_table_and_errors(tablename: str, engine, sample_rows: int) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """
    Load the current data rows and their Buckaroo detector errors from Postgres.

    Behavior:
    - Buckaroo stores the actual dataset in one table.
    - Buckaroo stores detector results in a matching table named
      "errors_<tablename>".
    - This function reads a sample of data rows, then fetches only the error
      records that belong to those sampled row IDs.

    Sampling rationale:
    - Some uploaded datasets can be large.
    - Semantic grouping can be expensive because it builds a feature vector for
      each row.
    - The default sample size keeps the UI responsive.

    Returns:
    - main_df: sampled table rows
    - error_df: long-form detector errors with row_id, column_id, error_type
    - total_rows: full table row count, not just sampled count
    """
    _validate_identifier(tablename)
    sample_rows = max(1, int(sample_rows or DEFAULT_SAMPLE_ROWS))

    table_sql = quote_identifier(tablename)
    errors_sql = quote_identifier(f"errors_{tablename}")

    total_rows_result = pd.read_sql_query(
        f"SELECT COUNT(*) AS count FROM {table_sql}",
        engine,
    )
    total_rows = int(total_rows_result.iloc[0]["count"]) if not total_rows_result.empty else 0

    main_df = pd.read_sql_query(
        f'SELECT * FROM {table_sql} ORDER BY "ID" LIMIT {sample_rows}',
        engine,
    )
    if main_df.empty or "ID" not in main_df.columns:
        return main_df, _empty_error_df(), total_rows

    safe_ids = [int(row_id) for row_id in main_df["ID"].dropna().tolist()]
    if not safe_ids:
        return main_df, _empty_error_df(), total_rows

    try:
        error_df = pd.read_sql_query(
            f"""
            SELECT row_id, column_id, error_type
            FROM {errors_sql}
            WHERE row_id IN ({id_list(safe_ids)})
            """,
            engine,
        )
    except Exception:
        error_df = _empty_error_df()

    return main_df, _normalize_error_df(error_df), total_rows


def _validate_identifier(name: str) -> str:
    """
    Reject unsafe SQL table names.

    Behavior:
    - We build SQL strings using table names.
    - Therefore table names are restricted to letters, numbers, and underscores.
    - If a name contains spaces, quotes, semicolons, etc., we reject it.

    This defensive check prevents invalid identifiers and reduces SQL injection risk.
    """
    if not re.fullmatch(r"[a-zA-Z0-9_]+", str(name)):
        raise ValueError(f"Unsafe SQL identifier rejected: {name!r}")
    return str(name)


def build_semantic_groups_from_frames(
    main_df: pd.DataFrame,
    error_df: pd.DataFrame,
    strategy: str = "auto",
    limit: int = DEFAULT_LIMIT,
    sample_rows: int = DEFAULT_SAMPLE_ROWS,
    cluster_count: int | None = None,
    min_group_size: int = DEFAULT_MIN_GROUP_SIZE,
    min_error_rows: int = DEFAULT_MIN_ERROR_ROWS,
    total_rows: int | None = None,
) -> dict:
    """
    Main semantic grouping pipeline after data has already been loaded.

    This function coordinates the primary semantic grouping workflow.

    Behavior:
    1. Clean the row IDs.
    2. Attach error labels to each data row.
    3. Compute the dataset baseline error rate.
    4. Decide which columns are numeric and which are text/category.
    5. Run one grouping strategy:
       - cluster_first: cluster all rows, then measure errors in each cluster.
       - error_first: keep only error rows, then cluster those error rows.
       - exact_slices: classic group-by slices such as Country = India.
    6. Sort groups by importance.
    7. Return a JSON-ready response for the frontend modal.

    Key concept:
    - baseline_error_rate is the normal error rate for the sampled dataset.
    - each group is judged by whether its error rate is higher than baseline.

    This function is "pure" in the sense that it works directly on DataFrames.
    That makes it easy to unit test without connecting to Postgres.
    """
    strategy = normalize_strategy(strategy)
    effective_strategy = "cluster_first" if strategy == "auto" else strategy
    limit = max(1, int(limit or DEFAULT_LIMIT))
    sample_rows = max(1, int(sample_rows or DEFAULT_SAMPLE_ROWS))
    min_group_size = max(1, int(min_group_size or DEFAULT_MIN_GROUP_SIZE))
    min_error_rows = max(1, int(min_error_rows or DEFAULT_MIN_ERROR_ROWS))

    if main_df is None or main_df.empty or "ID" not in main_df.columns:
        return _empty_response(strategy, effective_strategy, total_rows or 0, sample_rows)

    working_df = main_df.copy()
    working_df["ID"] = pd.to_numeric(working_df["ID"], errors="coerce").astype("Int64")
    working_df = working_df[working_df["ID"].notna()].copy()
    working_df["ID"] = working_df["ID"].astype(int)
    error_df = _normalize_error_df(error_df)

    row_error_counts = error_df.groupby("row_id").size() if not error_df.empty else pd.Series(dtype=int)
    error_row_ids = set(int(row_id) for row_id in row_error_counts.index.tolist())
    working_df["_buckaroo_has_error"] = working_df["ID"].isin(error_row_ids)
    working_df["_buckaroo_error_count"] = working_df["ID"].map(row_error_counts).fillna(0).astype(int)

    sample_total = int(len(working_df))
    error_row_total = int(working_df["_buckaroo_has_error"].sum())
    baseline_error_rate = _safe_div(error_row_total, sample_total)

    roles = infer_column_roles(working_df)
    if effective_strategy == "exact_slices":
        groups = exact_slice_groups(
            working_df,
            error_df,
            roles,
            baseline_error_rate,
            error_row_total,
            min_group_size,
            min_error_rows,
        )
    elif effective_strategy == "error_first":
        groups = cluster_groups(
            working_df,
            error_df,
            roles,
            baseline_error_rate,
            error_row_total,
            strategy="error_first",
            min_group_size=min_group_size,
            min_error_rows=min_error_rows,
            cluster_count=cluster_count,
        )
    else:
        groups = cluster_groups(
            working_df,
            error_df,
            roles,
            baseline_error_rate,
            error_row_total,
            strategy="cluster_first",
            min_group_size=min_group_size,
            min_error_rows=min_error_rows,
            cluster_count=cluster_count,
        )

    groups = dedupe_groups(sorted(groups, key=lambda item: item.score, reverse=True))
    groups = groups[:limit]

    return {
        "strategy": strategy,
        "effectiveStrategy": effective_strategy,
        "similarityTool": SEMANTIC_TOOL_NAME,
        "similarityDescription": SEMANTIC_TOOL_DESCRIPTION,
        "sampleRows": sample_total,
        "requestedSampleRows": sample_rows,
        "totalRows": int(total_rows if total_rows is not None else sample_total),
        "baselineErrorRate": float(round(baseline_error_rate, 6)),
        "errorRows": error_row_total,
        "numericColumns": roles["numeric"],
        "textColumns": roles["text"],
        "groups": [asdict(group) for group in groups],
    }


def normalize_strategy(strategy: str) -> str:
    """
    Convert user/UI strategy names into the internal strategy names.

    Behavior:
    - The UI or experiments may pass slightly different spellings.
    - This function maps those spellings to the supported internal names.

    Examples:
    - "cluster" becomes "cluster_first"
    - "error-first" becomes "error_first"
    - "slice" becomes "exact_slices"
    - anything unknown becomes "auto"
    """
    strategy = (strategy or "auto").strip().lower()
    aliases = {
        "cluster": "cluster_first",
        "cluster-first": "cluster_first",
        "error": "error_first",
        "error-first": "error_first",
        "exact": "exact_slices",
        "slice": "exact_slices",
        "slices": "exact_slices",
    }
    strategy = aliases.get(strategy, strategy)
    if strategy not in {"auto", "cluster_first", "error_first", "exact_slices"}:
        return "auto"
    return strategy


def infer_column_roles(df: pd.DataFrame) -> dict[str, list[str]]:
    """
    Decide which dataset columns should be treated as numeric vs text/category.

    Behavior:
    - Semantic grouping needs different feature construction for numbers and
      words.
    - Numeric columns become scaled numeric features.
    - Text/category columns become token/TF-IDF features.

    Rule used here:
    - If at least 90% of non-missing values can be converted to numbers, and
      the column has more than 3 distinct values, treat it as numeric.
    - Otherwise treat it as text/category.

    Example:
    - ConvertedSalary -> numeric
    - Country -> text/category
    - Age with values like "25 - 34 years old" -> text/category

    Helper columns such as ID, row_id, error_type, and internal Buckaroo columns
    are skipped because they are not real user attributes.
    """
    numeric_columns = []
    text_columns = []
    for column in df.columns:
        if column in HELPER_COLUMNS or column.startswith("_buckaroo_"):
            continue
        series = df[column]
        non_missing = series[~series.map(is_missing_value)]
        if non_missing.empty:
            text_columns.append(column)
            continue

        numeric = pd.to_numeric(non_missing, errors="coerce")
        numeric_ratio = float(numeric.notna().mean())
        distinct_count = int(non_missing.astype(str).nunique(dropna=True))

        if numeric_ratio >= 0.9 and distinct_count > 3:
            numeric_columns.append(column)
        else:
            text_columns.append(column)
    return {"numeric": numeric_columns, "text": text_columns}


def cluster_groups(
    df: pd.DataFrame,
    error_df: pd.DataFrame,
    roles: dict[str, list[str]],
    baseline_error_rate: float,
    total_error_rows: int,
    strategy: str,
    min_group_size: int,
    min_error_rows: int,
    cluster_count: int | None,
) -> list[SemanticGroup]:
    """
    Run a clustering-based grouping strategy.

    This function handles both:
    - cluster_first / All Rows
    - error_first / Errors

    In cluster_first:
    - Use every sampled row.
    - Convert rows into semantic feature vectors.
    - Cluster similar rows.
    - Then ask: which clusters have unusually concentrated errors?

    In error_first:
    - Start by keeping only rows that already have detector errors.
    - Convert only those error rows into feature vectors.
    - Cluster the error rows into themes.
    - This is useful for diagnosis, but it does not compare rows with errors against rows without errors
      as directly because every row in the input already has an error.

    Output:
    - A list of SemanticGroup objects, one per useful cluster.
    """
    source_df = df[df["_buckaroo_has_error"]].copy() if strategy == "error_first" else df.copy()
    if source_df.empty:
        return []

    feature_matrix, feature_info = build_semantic_feature_matrix(source_df, roles)
    k = cluster_count if cluster_count else default_cluster_count(len(source_df), min_group_size)
    labels = kmeans(feature_matrix, k)
    source_df["_buckaroo_cluster"] = labels

    summaries = []
    for cluster_label in sorted(set(labels.tolist())):
        rows = source_df[source_df["_buckaroo_cluster"] == cluster_label]
        if len(rows) < min_group_size:
            continue
        summary = summarize_group(
            rows,
            df,
            error_df,
            roles,
            baseline_error_rate,
            total_error_rows,
            strategy,
            group=f"semantic_cluster_{int(cluster_label)}",
            min_error_rows=min_error_rows,
            feature_info=feature_info,
        )
        if summary:
            summaries.append(summary)
    return summaries


def exact_slice_groups(
    df: pd.DataFrame,
    error_df: pd.DataFrame,
    roles: dict[str, list[str]],
    baseline_error_rate: float,
    total_error_rows: int,
    min_group_size: int,
    min_error_rows: int,
) -> list[SemanticGroup]:
    """
    Run an exact slice/group-by strategy.

    Behavior:
    - Instead of clustering approximate semantic similarity, this uses exact
      values or numeric bins.
    - It is similar to asking SQL-style questions like:
        Country = India
        EducationParents = Secondary
        ConvertedSalary bin = high salary range
        Country = India AND Employment = Full-time

    Rationale:
    - It is very interpretable.
    - It gives a baseline similar to Slice Finder papers.
    - It helps compare semantic clustering against classic exact slicing.

    Limitation:
    - It does not understand approximate meaning. "USA" and "United States"
      would be separate unless normalized elsewhere.
    """
    summaries = []
    candidate_columns = exact_candidate_columns(df, roles)

    for column in candidate_columns:
        labels = exact_group_labels_for_column(df, column, roles)
        for label, rows in df.groupby(labels, dropna=False):
            if len(rows) < min_group_size:
                continue
            group_label = f"{column} = {label}"
            summary = summarize_group(
                rows,
                df,
                error_df,
                roles,
                baseline_error_rate,
                total_error_rows,
                "exact_slices",
                group=group_label,
                min_error_rows=min_error_rows,
                exact_description=group_label,
            )
            if summary:
                summaries.append(summary)

    for first, second in column_pairs(candidate_columns[:6]):
        first_labels = exact_group_labels_for_column(df, first, roles)
        second_labels = exact_group_labels_for_column(df, second, roles)
        combined = first_labels.astype(str) + " AND " + second_labels.astype(str)
        for label, rows in df.groupby(combined, dropna=False):
            if len(rows) < min_group_size:
                continue
            group_label = f"{first} = {label.split(' AND ')[0]} AND {second} = {label.split(' AND ', 1)[1]}"
            summary = summarize_group(
                rows,
                df,
                error_df,
                roles,
                baseline_error_rate,
                total_error_rows,
                "exact_slices",
                group=group_label,
                min_error_rows=min_error_rows,
                exact_description=group_label,
            )
            if summary:
                summaries.append(summary)

    return summaries


def exact_candidate_columns(df: pd.DataFrame, roles: dict[str, list[str]]) -> list[str]:
    """
    Choose which columns are reasonable for exact slice enumeration.

    Behavior:
    - Exact slicing can explode if a column has thousands of unique values.
    - So we only use text columns with a manageable number of distinct values.
    - For numeric columns, we include only a few high-priority columns and bin
      them later.

    Current heuristic:
    - Text/category columns are allowed if they have 1 to 80 distinct values.
    - Numeric columns are prioritized by how often they appear in error rows.
    """
    candidates = []
    for column in roles["text"]:
        non_missing = df[column][~df[column].map(is_missing_value)]
        distinct = int(non_missing.astype(str).nunique(dropna=True))
        if 1 <= distinct <= 80:
            candidates.append(column)

    numeric_priority = sorted(
        roles["numeric"],
        key=lambda col: int(df.loc[df["_buckaroo_has_error"], col].notna().sum()),
        reverse=True,
    )
    candidates.extend(numeric_priority[:4])
    return candidates


def exact_group_labels_for_column(
    df: pd.DataFrame,
    column: str,
    roles: dict[str, list[str]],
) -> pd.Series:
    """
    Convert one column into exact slice labels.

    Behavior:
    - For text/category columns, the label is just the value.
        Example: Country = India
    - For numeric columns, we cannot group by every exact number because that
      would create too many tiny groups.
    - Instead, numeric columns are divided into bins.
        Example: ConvertedSalary = (50000, 100000]

    qcut tries to create equal-sized bins.
    cut is used as a fallback if qcut cannot create valid bins.
    """
    if column in roles["numeric"]:
        numeric = pd.to_numeric(df[column], errors="coerce")
        try:
            labels = pd.qcut(numeric, q=4, duplicates="drop")
        except ValueError:
            labels = pd.cut(numeric, bins=4, duplicates="drop")
        return labels.astype(str).replace("nan", "missing")
    return df[column].map(format_group_value)


def column_pairs(columns: list[str]) -> Iterable[tuple[str, str]]:
    """
    Yield every two-column combination from a list of candidate columns.

    Behavior:
    - This lets exact_slices test pairs such as:
        Country AND Employment
        EducationParents AND UndergradMajor
    - Pair slices can reveal interactions that one-column slices miss.
    """
    for i, first in enumerate(columns):
        for second in columns[i + 1 :]:
            yield first, second


def summarize_group(
    rows: pd.DataFrame,
    full_df: pd.DataFrame,
    error_df: pd.DataFrame,
    roles: dict[str, list[str]],
    baseline_error_rate: float,
    total_error_rows: int,
    strategy: str,
    group: str,
    min_error_rows: int,
    feature_info: dict | None = None,
    exact_description: str | None = None,
) -> SemanticGroup | None:
    """
    Convert a set of rows into one ranked SemanticGroup object.

    This function computes the primary group metrics.

    Behavior:
    - Given a group of rows, count how many rows are in the group.
    - Count how many of those rows have Buckaroo detector errors.
    - Compare the group's error rate to the dataset baseline.
    - Find the most common detector issue inside the group.
    - Build a readable description.
    - Return row IDs so the UI can select or filter this group.

    Metrics:
    - error_rate = error_rows / group_size
    - lift = group error rate / dataset baseline error rate
    - error_coverage = group error rows / all error rows
    - score = lift * log(1 + error_rows) * (0.5 + error_coverage)

    Score rationale:
    - lift rewards groups that are worse than average.
    - log(1 + error_rows) rewards groups with real support, not tiny groups.
    - coverage rewards groups that explain a meaningful share of all errors.

    Returns None when:
    - the group does not contain enough error rows to be useful.
    """
    row_ids = [int(row_id) for row_id in rows["ID"].tolist()]
    row_id_set = set(row_ids)
    error_rows = int(rows["_buckaroo_has_error"].sum())
    if error_rows < min_error_rows:
        return None

    group_size = int(len(rows))
    error_rate = _safe_div(error_rows, group_size)
    lift = _safe_div(error_rate, baseline_error_rate) if baseline_error_rate > 0 else 0.0
    error_coverage = _safe_div(error_rows, total_error_rows)
    score = float(lift * math.log1p(error_rows) * (0.5 + error_coverage))

    group_errors = error_df[error_df["row_id"].isin(row_id_set)] if not error_df.empty else _empty_error_df()
    main_issue, main_columns = summarize_errors(group_errors)
    feature_highlights = (
        [exact_description]
        if exact_description
        else describe_cluster(rows, full_df, roles, feature_info)
    )
    description = "; ".join(feature_highlights[:3]) if feature_highlights else f"{group_size} similar rows"

    returned_ids = row_ids[:MAX_ROW_IDS_RETURNED]
    return SemanticGroup(
        id=f"{strategy}:{group}",
        strategy=strategy,
        group=group,
        description=description,
        rows=group_size,
        errorRows=error_rows,
        errorRate=float(round(error_rate, 6)),
        baselineErrorRate=float(round(baseline_error_rate, 6)),
        lift=float(round(lift, 6)),
        score=float(round(score, 6)),
        errorCoverage=float(round(error_coverage, 6)),
        mainIssue=main_issue,
        mainErrorColumns=main_columns,
        rowIds=returned_ids,
        rowIdsTruncated=len(row_ids) > len(returned_ids),
        featureHighlights=feature_highlights,
    )


def summarize_errors(error_df: pd.DataFrame) -> tuple[str, list[str]]:
    """
    Find the dominant detector issue inside a group.

    Behavior:
    - A group may contain many detector records.
    - We combine error type and column name into strings such as:
        anomaly:ConvertedSalary
        missing:workclass
    - The most frequent pair becomes the group's main issue.

    Output:
    - main_issue: most common error_type:column_id pair
    - columns: top columns involved in errors for this group
    """
    if error_df.empty:
        return "none", []

    pairs = (
        error_df["error_type"].astype(str)
        + ":"
        + error_df["column_id"].astype(str)
    )
    main_issue = str(pairs.value_counts().index[0]) if not pairs.empty else "none"
    columns = [
        str(column)
        for column in error_df["column_id"].astype(str).value_counts().head(3).index.tolist()
    ]
    return main_issue, columns


def describe_cluster(
    rows: pd.DataFrame,
    full_df: pd.DataFrame,
    roles: dict[str, list[str]],
    feature_info: dict | None,
) -> list[str]:
    """
    Create human-readable reasons for why a cluster is interesting.

    Behavior:
    - Clustering gives us a cluster number, but "cluster 3" is not meaningful
      to a user.
    - This function turns the cluster into phrases like:
        high ConvertedSalary avg 108239.0
        EducationParents mostly Secondary (72%)
        semantic terms: web, developer, bachelor

    It combines three explanation sources:
    1. Numeric columns where this group is unusually high or low.
    2. Text/category columns where one value dominates the group.
    3. TF-IDF terms that are more important in this group than globally.
    """
    highlights = []

    for column, label in strongest_numeric_descriptions(rows, full_df, roles["numeric"]):
        highlights.append(f"{label} {friendly_name(column)} avg {safe_mean(rows[column]):.1f}")

    for column, value, share in strongest_text_descriptions(rows, full_df, roles["text"]):
        highlights.append(f"{friendly_name(column)} mostly {value} ({share:.0%})")

    token_highlights = strongest_token_descriptions(rows, feature_info)
    if token_highlights:
        highlights.append("semantic terms: " + ", ".join(token_highlights[:4]))

    return highlights[:5]


def strongest_numeric_descriptions(
    rows: pd.DataFrame,
    full_df: pd.DataFrame,
    numeric_columns: list[str],
) -> list[tuple[str, str]]:
    """
    Find numeric columns that make this group stand out.

    Behavior:
    - For each numeric column, compare the group's average value against the
      full dataset's median value.
    - If the group is meaningfully higher or lower, return a label:
        "high ConvertedSalary"
        "low hours per week"

    Median/IQR rationale:
    - Median is less sensitive to extreme outliers than mean.
    - IQR gives a robust scale for "how different is this group?"

    The function only returns the top two numeric explanations so the UI does
    not become overly verbose.
    """
    scored = []
    for column in numeric_columns:
        group_values = pd.to_numeric(rows[column], errors="coerce")
        full_values = pd.to_numeric(full_df[column], errors="coerce")
        if group_values.notna().sum() == 0 or full_values.notna().sum() < 3:
            continue
        group_mean = float(group_values.mean())
        full_median = float(full_values.median())
        q1 = full_values.quantile(0.25)
        q3 = full_values.quantile(0.75)
        scale = float(q3 - q1) if pd.notna(q3 - q1) and q3 != q1 else float(full_values.std() or 1.0)
        if not scale:
            continue
        diff = (group_mean - full_median) / scale
        if abs(diff) < 0.45:
            continue
        scored.append((abs(diff), column, "high" if diff > 0 else "low"))
    return [(column, label) for _, column, label in sorted(scored, reverse=True)[:2]]


def strongest_text_descriptions(
    rows: pd.DataFrame,
    full_df: pd.DataFrame,
    text_columns: list[str],
) -> list[tuple[str, str, float]]:
    """
    Find text/category values that dominate this group.

    Behavior:
    - For each text/category column, find the most common value inside the
      group.
    - Then compare how common that value is inside the group vs globally.

    Example:
    - In the group: 72% have EducationParents = Secondary.
    - In the full dataset: 30% have EducationParents = Secondary.
    - That value is concentrated in the group, so it helps describe the group.

    Filters:
    - Ignore values that appear in less than 35% of the group.
    - Ignore weak explanations unless the value is either strongly lifted or
      very dominant.

    Returns:
    - Up to three descriptions as (column, value, share).
    """
    scored = []
    for column in text_columns:
        group_values = rows[column].map(format_group_value)
        full_values = full_df[column].map(format_group_value)
        if group_values.empty:
            continue
        mode_counts = group_values.value_counts()
        if mode_counts.empty:
            continue
        value = str(mode_counts.index[0])
        share = float(mode_counts.iloc[0] / len(group_values))
        if share < 0.35:
            continue
        global_share = float((full_values == value).mean()) if len(full_values) else 0.0
        lift = _safe_div(share, global_share) if global_share > 0 else share
        if lift < 1.2 and share < 0.75:
            continue
        scored.append((lift * share, column, value, share))
    return [(column, value, share) for _, column, value, share in sorted(scored, reverse=True)[:3]]


def strongest_token_descriptions(rows: pd.DataFrame, feature_info: dict | None) -> list[str]:
    """
    Find TF-IDF terms that are unusually important inside this group.

    Behavior:
    - Every row has a TF-IDF vector built from its text/category values.
    - We average the TF-IDF vectors for the rows in this group.
    - We also average TF-IDF vectors for the whole dataset.
    - Terms that are much stronger in the group than globally become semantic
      explanation words.

    Example:
    - If the group contains many "web development" rows, terms like "web" and
      "development" may appear here.

    This is not used to compute the final score directly. It is used for
    making cluster descriptions easier to interpret in the UI and documentation.
    """
    if not feature_info:
        return []
    text_matrix = feature_info.get("text_matrix")
    terms = feature_info.get("terms") or []
    row_positions = feature_info.get("row_positions") or {}
    if text_matrix is None or len(terms) == 0:
        return []

    positions = [row_positions.get(int(row_id)) for row_id in rows["ID"].tolist()]
    positions = [pos for pos in positions if pos is not None]
    if not positions:
        return []
    cluster_mean = text_matrix[positions].mean(axis=0)
    global_mean = text_matrix.mean(axis=0)
    scores = np.asarray(cluster_mean - global_mean).ravel()
    if scores.size == 0:
        return []
    top_indices = np.argsort(scores)[::-1]
    result = []
    for idx in top_indices:
        if scores[idx] <= 0:
            break
        term = terms[int(idx)]
        if term not in result:
            result.append(term)
        if len(result) >= 5:
            break
    return result


def build_semantic_feature_matrix(
    df: pd.DataFrame,
    roles: dict[str, list[str]],
) -> tuple[np.ndarray, dict]:
    """
    Build the actual row feature matrix used for semantic clustering.

    This function constructs the core semantic representation.

    Behavior:
    - Each row must become a vector of numbers before clustering can happen.
    - Numeric columns become robust-scaled numeric features.
    - Text/category columns become TF-IDF token features.
    - We concatenate those two feature blocks into one matrix.

    Example conceptual row vector:
        [
          scaled ConvertedSalary,
          scaled YearsCoding,
          TF-IDF("web"),
          TF-IDF("developer"),
          TF-IDF("secondary"),
          ...
        ]

    Numeric weighting rationale:
    - It slightly reduces numeric dominance so text/category semantics still
      matter.
    - This weighting is a heuristic and can be tuned later.

    L2 normalization rationale:
    - It makes rows comparable by direction, similar to cosine similarity.
    - This helps TF-IDF-style semantic comparison.

    Returns:
    - matrix: numpy array with shape (number of rows, number of features)
    - feature_info: extra metadata used later to explain clusters
    """
    numeric_matrix, numeric_columns = build_numeric_matrix(df, roles["numeric"])
    documents = build_text_documents(df, roles["text"])
    text_matrix, terms = build_tfidf_matrix(documents)

    parts = []
    if numeric_matrix.size:
        parts.append(numeric_matrix * 0.75)
    if text_matrix.size:
        parts.append(text_matrix)

    if parts:
        matrix = np.hstack(parts)
    else:
        matrix = np.zeros((len(df), 1), dtype=float)

    matrix = l2_normalize(np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0))
    row_positions = {int(row_id): idx for idx, row_id in enumerate(df["ID"].tolist())}
    return matrix, {
        "numeric_columns": numeric_columns,
        "terms": terms,
        "text_matrix": text_matrix,
        "row_positions": row_positions,
    }


def build_numeric_matrix(df: pd.DataFrame, numeric_columns: list[str]) -> tuple[np.ndarray, list[str]]:
    """
    Convert numeric columns into clustering features.

    Behavior:
    - Raw numeric columns can have very different scales.
        Age might be 20-70.
        Salary might be 0-2,000,000.
    - If we used raw values, salary would dominate distance calculations.
    - So we robust-scale each numeric column.

    Scaling formula:
        scaled = (value - median) / IQR

    Then:
    - Missing numeric values are filled with the column median.
    - Extreme scaled values are clipped to [-4, 4].
    - Values are divided by 4 to roughly fit in [-1, 1].

    Missingness feature:
    - If a numeric column has missing values, we add a separate binary feature
      saying whether that row was missing in that column.
    - This matters because "missing salary" can itself be semantically useful.

    Returns:
    - numeric feature matrix
    - names of numeric features created
    """
    columns = []
    features = []
    for column in numeric_columns:
        values = pd.to_numeric(df[column], errors="coerce")
        if values.notna().sum() < 3:
            continue
        median = values.median()
        q1 = values.quantile(0.25)
        q3 = values.quantile(0.75)
        iqr = q3 - q1
        scale = iqr if pd.notna(iqr) and iqr != 0 else values.std()
        if pd.isna(scale) or scale == 0:
            continue
        scaled = ((values.fillna(median) - median) / scale).clip(-4, 4) / 4
        features.append(scaled.to_numpy(dtype=float))
        columns.append(column)

        missing = values.isna().astype(float)
        if missing.sum() > 0:
            features.append(missing.to_numpy(dtype=float))
            columns.append(f"{column}:missing")

    if not features:
        return np.zeros((len(df), 0), dtype=float), []
    return np.vstack(features).T, columns


def build_text_documents(df: pd.DataFrame, text_columns: list[str]) -> list[list[str]]:
    """
    Turn each row's text/category values into a list of tokens.

    Behavior:
    - TF-IDF expects documents.
    - Each table row is represented as one "document."
    - The words in that document come from:
        1. column names
        2. cell values
        3. the word "missing" when a value is missing

    Example:
        UndergradMajor = "Web development"
        Country = "United States"

    Tokens might become:
        undergrad, major, web, development, country, united, states

    Column-name token rationale:
    - The value "Secondary" alone may be ambiguous.
    - "EducationParents Secondary" is more informative than just "Secondary."
    """
    documents = []
    for _, row in df.iterrows():
        tokens = []
        for column in text_columns:
            value = row[column]
            column_tokens = tokenize(column)
            tokens.extend(column_tokens)
            if is_missing_value(value):
                tokens.append("missing")
                tokens.extend(column_tokens)
            else:
                tokens.extend(tokenize(value)[:30])
        documents.append(tokens)
    return documents


def build_tfidf_matrix(documents: list[list[str]]) -> tuple[np.ndarray, list[str]]:
    """
    Convert tokenized row documents into a TF-IDF matrix.

    Behavior:
    - TF-IDF is a standard way to represent text as numbers.
    - A term gets higher weight if it appears in this row but not in almost
      every row.
    - Common terms become less important.

    Steps:
    1. Count tokens in each row/document.
    2. Count in how many rows each token appears.
    3. Keep terms that are neither too rare nor too common.
    4. Compute IDF:
        log((1 + doc_count) / (1 + document_frequency)) + 1
    5. Fill a matrix where each row is a data row and each column is a term.
    6. L2-normalize the matrix.

    Output:
    - matrix: row-by-term TF-IDF values
    - terms: list of term names matching the matrix columns
    """
    if not documents:
        return np.zeros((0, 0), dtype=float), []

    doc_count = len(documents)
    document_frequencies = Counter()
    term_counts = []
    for tokens in documents:
        counts = Counter(token for token in tokens if token not in STOP_WORDS)
        term_counts.append(counts)
        document_frequencies.update(counts.keys())

    eligible_terms = [
        term
        for term, frequency in document_frequencies.items()
        if 2 <= frequency <= max(2, int(doc_count * 0.9))
    ]
    eligible_terms.sort(key=lambda term: (document_frequencies[term], term), reverse=True)
    terms = eligible_terms[:MAX_TEXT_FEATURES]
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

    return l2_normalize(matrix), terms


def kmeans(
    matrix: np.ndarray,
    k: int,
    max_iter: int = 40,
    random_seed: int = 42,
) -> np.ndarray:
    """
    Deterministic k-means clustering implementation.

    Behavior:
    - We have one vector per row.
    - We want to split the rows into k groups.
    - K-means repeatedly:
        1. assigns each row to the nearest cluster center
        2. recomputes each center as the average of its assigned rows
        3. stops when assignments no longer change

    Local implementation rationale:
    - The project requirements currently do not include scikit-learn.
    - This keeps the semantic grouping feature self-contained.

    Determinism:
    - We use random seed 42.
    - That makes results reproducible for the same input data.

    Returns:
    - one integer cluster label per row.
    """
    n_rows = matrix.shape[0]
    if n_rows == 0:
        return np.array([], dtype=int)
    unique_row_count = np.unique(matrix, axis=0).shape[0]
    k = max(1, min(int(k or 1), n_rows, unique_row_count))
    if k == 1:
        return np.zeros(n_rows, dtype=int)

    rng = np.random.default_rng(int(random_seed))
    centroids = initialize_centroids(matrix, k, rng)
    labels = np.zeros(n_rows, dtype=int)

    for _ in range(max_iter):
        distances = squared_distances(matrix, centroids)
        next_labels = distances.argmin(axis=1)
        if np.array_equal(labels, next_labels):
            break
        labels = next_labels
        for label in range(k):
            members = matrix[labels == label]
            if members.size:
                centroids[label] = members.mean(axis=0)
            else:
                farthest_idx = int(np.argmax(distances.min(axis=1)))
                centroids[label] = matrix[farthest_idx]
        centroids = l2_normalize(centroids)

    return labels


def initialize_centroids(matrix: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    """
    Pick starting centroids for k-means.

    Behavior:
    - K-means needs initial cluster centers.
    - Poor starting centers can produce unstable or low-quality clusters.
    - This function starts with one random row, then repeatedly chooses the row
      farthest from existing centers.

    Farthest-row rationale:
    - It spreads the initial centers across the feature space.
    - This is similar in purpose to k-means++ initialization, but simpler.

    kmeans() caps k by the number of unique row vectors before calling this
    function, so this initializer does not need to manufacture duplicate
    centroids when the data cannot support the requested k.
    """
    n_rows = matrix.shape[0]
    first_idx = int(rng.integers(0, n_rows))
    centroids = [matrix[first_idx]]
    while len(centroids) < k:
        distances = squared_distances(matrix, np.vstack(centroids))
        nearest = distances.min(axis=1)
        next_idx = int(np.argmax(nearest))
        if nearest[next_idx] <= 1e-12:
            remaining = [idx for idx in range(n_rows) if not any(np.array_equal(matrix[idx], c) for c in centroids)]
            if not remaining:
                break
            next_idx = int(rng.choice(remaining))
        centroids.append(matrix[next_idx])
    return np.vstack(centroids)


def squared_distances(matrix: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    """
    Compute squared Euclidean distances between rows and centroids.

    Behavior:
    - For every row vector, measure how far it is from every cluster center.
    - K-means assigns each row to the closest center.

    Output shape:
    - rows x centroids
    - distance[i, j] means distance from row i to centroid j

    We use a vectorized formula for speed instead of Python loops.
    """
    return (
        np.sum(matrix * matrix, axis=1, keepdims=True)
        - 2 * matrix @ centroids.T
        + np.sum(centroids * centroids, axis=1)
    )


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """
    Normalize each row vector to length 1.

    Behavior:
    - Rows can have different vector magnitudes.
    - L2 normalization scales each row so its total length is 1.
    - This makes similarity depend more on direction/pattern than raw size.

    This is useful for TF-IDF features because cosine-style
    similarity is usually better than raw Euclidean magnitude for text.
    """
    if matrix.size == 0:
        return matrix
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def default_cluster_count(row_count: int, min_group_size: int) -> int:
    """
    Choose a reasonable default number of clusters.

    Behavior:
    - K-means needs k, the number of clusters.
    - Users should not need to choose k in the default workflow.
    - This heuristic creates a small number of clusters that is large enough to
      find patterns while keeping the UI result set manageable.

    Current behavior:
    - Never less than 1.
    - Never more than 8.
    - Also respects min_group_size so we do not create many tiny clusters.
    """
    if row_count <= 0:
        return 1
    by_size = max(1, row_count // max(1, min_group_size))
    by_shape = max(1, int(round(math.sqrt(row_count) / 2)))
    return max(1, min(8, by_size, by_shape))


def dedupe_groups(groups: list[SemanticGroup]) -> list[SemanticGroup]:
    """
    Remove near-duplicate groups from the ranked result list.

    Behavior:
    - Different strategies or slices can sometimes produce almost the same set
      of rows.
    - Showing duplicates wastes UI space and confuses users.
    - This function compares row ID overlap.

    Duplicate rule:
    - If two groups overlap by at least 95% using Jaccard overlap
      intersection / union, the later one is dropped.
    """
    kept = []
    kept_sets: list[set[int]] = []
    for group in groups:
        group_set = set(group.rowIds)
        if not group_set:
            kept.append(group)
            kept_sets.append(group_set)
            continue
        duplicate = False
        for existing_set in kept_sets:
            if not existing_set:
                continue
            intersection = len(group_set & existing_set)
            union = len(group_set | existing_set)
            if union and intersection / union >= 0.95:
                duplicate = True
                break
        if not duplicate:
            kept.append(group)
            kept_sets.append(group_set)
    return kept


def tokenize(value) -> list[str]:
    """
    Split a string/value into simple semantic tokens.

    Behavior:
    - Converts values into lowercase words.
    - Splits camelCase names like ConvertedSalary into Converted + Salary.
    - Keeps only letters and numbers.
    - Removes one-character tokens and stop words.

    Examples:
    - "ConvertedSalary" -> ["converted", "salary"]
    - "Web-development" -> ["web", "development"]
    - "United States" -> ["united", "states"]
    """
    text = str(value)
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [token for token in tokens if len(token) > 1 and token not in STOP_WORDS]


def friendly_name(column: str) -> str:
    """
    Make a column name nicer for descriptions.

    Behavior:
    - Split camelCase and PascalCase boundaries.
    - Replace underscores and hyphens with spaces.
    - Used in generated text such as:
        high hours per week avg 50.0
    """
    text = str(column).replace("_", " ").replace("-", " ")
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", text)
    return " ".join(text.split())


def format_group_value(value) -> str:
    """
    Convert a raw cell value into a clean group label.

    Behavior:
    - Missing values all become the label "missing".
    - Non-missing values become strings.

    This keeps exact slices readable and consistent.
    """
    if is_missing_value(value):
        return "missing"
    return str(value)


def is_missing_value(value) -> bool:
    """
    Decide whether a cell should be treated as missing.

    Behavior:
    - Pandas null values count as missing.
    - Common string markers like "?", "null", "unknown", and "" also count.

    This matters for both:
    - grouping descriptions
    - semantic tokens, where missingness can be a meaningful pattern
    """
    return shared_is_missing_value(value)


def safe_mean(series: pd.Series) -> float:
    """
    Safely compute the numeric mean of a pandas Series.

    Behavior:
    - Convert values to numbers where possible.
    - Ignore non-numeric values.
    - If no numeric values exist, return 0.0 instead of raising an exception.

    Used for descriptions such as:
        high ConvertedSalary avg 108239.0
    """
    values = pd.to_numeric(series, errors="coerce")
    if values.notna().sum() == 0:
        return 0.0
    return float(values.mean())


def _safe_div(numerator: float, denominator: float) -> float:
    """
    Divide two numbers without raising a divide-by-zero error.

    Behavior:
    - If denominator is zero, return 0.0.
    - Otherwise return numerator / denominator.

    Used for error rates, lift, and coverage.
    """
    return float(numerator / denominator) if denominator else 0.0


def _empty_error_df() -> pd.DataFrame:
    """
    Return an empty detector-error table with the expected columns.

    Behavior:
    - Even if there are no errors, downstream code expects these columns:
        row_id, column_id, error_type
    - Returning a correctly shaped empty DataFrame avoids special-case failures.
    """
    return pd.DataFrame(columns=["row_id", "column_id", "error_type"])


def _normalize_error_df(error_df: pd.DataFrame | None) -> pd.DataFrame:
    """
    Clean detector error data into the standard Buckaroo error format.

    Behavior:
    - Detector errors should always have:
        row_id, column_id, error_type
    - This function makes sure those columns exist.
    - It drops errors with invalid row IDs.
    - It converts row IDs to integers and error metadata to strings.

    This makes the rest of the semantic grouping pipeline simpler because it can
    trust the shape and types of error_df.
    """
    if error_df is None or error_df.empty:
        return _empty_error_df()
    result = error_df.copy()
    for column in ["row_id", "column_id", "error_type"]:
        if column not in result.columns:
            result[column] = pd.Series(dtype=object)
    result = result[["row_id", "column_id", "error_type"]]
    result["row_id"] = pd.to_numeric(result["row_id"], errors="coerce")
    result = result[result["row_id"].notna()].copy()
    result["row_id"] = result["row_id"].astype(int)
    result["column_id"] = result["column_id"].astype(str)
    result["error_type"] = result["error_type"].astype(str)
    return result


def _empty_response(strategy: str, effective_strategy: str, total_rows: int, sample_rows: int) -> dict:
    """
    Return a valid API response when semantic grouping cannot run.

    Behavior:
    - If the table is empty, missing ID, or otherwise unusable, the frontend
      should still receive a predictable response shape.
    - The response says there are no groups instead of throwing an exception.

    This keeps the UI stable.
    """
    return {
        "strategy": strategy,
        "effectiveStrategy": effective_strategy,
        "similarityTool": SEMANTIC_TOOL_NAME,
        "similarityDescription": SEMANTIC_TOOL_DESCRIPTION,
        "sampleRows": 0,
        "requestedSampleRows": int(sample_rows),
        "totalRows": int(total_rows),
        "baselineErrorRate": 0.0,
        "errorRows": 0,
        "numericColumns": [],
        "textColumns": [],
        "groups": [],
    }
