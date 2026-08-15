"""Bounded unique-column-combination discovery for Buckaroo profiling.

This module borrows the useful part of Metanome-style UCC discovery without
porting the full lattice/random-walk engine.  Buckaroo only needs key evidence
for profiling decisions, so we deliberately check a small, explainable search
space:

1. likely key/category/date/code columns as singles,
2. pairs among the non-unique likely columns,
3. optional triples only when a pair is already near-unique.

Final validation is exact over deterministic row tuple hashes.  Approximate
cardinality estimates are used only to choose which columns are worth testing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

from detectors.common import is_missing_value


DEFAULT_UCC_MAX_ARITY = 3
DEFAULT_UCC_MAX_CANDIDATE_COLUMNS = 12
DEFAULT_UCC_NEAR_UNIQUE_THRESHOLD = 0.98
DEFAULT_UCC_MIN_REPORT_UNIQUENESS_RATIO = 0.95
DEFAULT_UCC_MAX_TRIPLE_CANDIDATES = 30

MISSING_TOKEN = "<buckaroo_missing>"

ALLOWED_PROFILE_ROLES = {
    "identifier",
    "quasi_identifier",
    "datetime_identifier",
    "datetime_category",
    "categorical",
    "numeric_code_category",
    "binary_category",
}

SKIPPED_PROFILE_ROLES = {
    "empty",
    "airport_code",
    "country_code",
    "datetime_high_uniqueness",
    "free_text",
    "geographic_coordinate",
    "high_uniqueness_location_field",
    "location_name",
    "vector_blob",
    "numeric_measure",
    "postal_code",
}


@dataclass(frozen=True)
class UCCCandidate:
    """Evidence for one possible unique column combination."""

    columns: tuple[str, ...]
    row_count: int
    unique_tuple_count: int
    duplicate_count: int
    missing_rows: int
    uniqueness_ratio: float
    is_unique: bool
    is_minimal: bool
    confidence: str
    reason: str

    @property
    def arity(self) -> int:
        return len(self.columns)

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": " + ".join(self.columns),
            "arity": self.arity,
            "uniqueness_ratio": round(self.uniqueness_ratio, 6),
            "duplicate_count": self.duplicate_count,
            "is_unique": self.is_unique,
            "is_minimal": self.is_minimal,
            "confidence": self.confidence,
            "reason": self.reason,
            "row_count": self.row_count,
            "unique_tuple_count": self.unique_tuple_count,
            "missing_rows": self.missing_rows,
        }


@dataclass
class _CombinationTracker:
    columns: tuple[str, ...]
    row_count: int = 0
    missing_rows: int = 0
    seen_hashes: set[int] | None = None

    def __post_init__(self) -> None:
        self.seen_hashes = set()


def discover_ucc_candidates(
    data_frame: pd.DataFrame,
    column_profile: pd.DataFrame,
    *,
    max_arity: int = DEFAULT_UCC_MAX_ARITY,
    max_candidate_columns: int = DEFAULT_UCC_MAX_CANDIDATE_COLUMNS,
    near_unique_threshold: float = DEFAULT_UCC_NEAR_UNIQUE_THRESHOLD,
    min_report_uniqueness_ratio: float = DEFAULT_UCC_MIN_REPORT_UNIQUENESS_RATIO,
    max_triple_candidates: int = DEFAULT_UCC_MAX_TRIPLE_CANDIDATES,
) -> list[dict[str, Any]]:
    """Discover minimal UCC candidates in an in-memory dataframe."""

    candidate_columns = select_ucc_candidate_columns(
        column_profile,
        available_columns=data_frame.columns,
        max_candidate_columns=max_candidate_columns,
    )
    if not candidate_columns or data_frame.empty:
        return []

    single_results = validate_ucc_combinations(data_frame, [(column,) for column in candidate_columns])
    unique_single_columns = {
        candidate.columns[0]
        for candidate in single_results
        if candidate.is_unique
    }

    pair_columns = [column for column in candidate_columns if column not in unique_single_columns]
    pair_combinations = list(combinations(pair_columns, 2))
    pair_results = validate_ucc_combinations(data_frame, pair_combinations)

    triple_results: list[UCCCandidate] = []
    if max_arity >= 3 and pair_results:
        unique_pair_sets = {
            frozenset(candidate.columns)
            for candidate in pair_results
            if candidate.is_unique
        }
        near_unique_pairs = [
            candidate.columns
            for candidate in pair_results
            if not candidate.is_unique and candidate.uniqueness_ratio >= near_unique_threshold
        ]
        triple_combinations = _build_triple_combinations(
            pair_columns,
            near_unique_pairs,
            unique_pair_sets,
            max_triple_candidates=max_triple_candidates,
        )
        triple_results = validate_ucc_combinations(data_frame, triple_combinations)

    return _finalize_candidates(
        [*single_results, *pair_results, *triple_results],
        min_report_uniqueness_ratio=min_report_uniqueness_ratio,
    )


def discover_ucc_candidates_in_csv(
    csv_path: str | Path,
    column_profile: pd.DataFrame,
    *,
    chunk_rows: int = 50_000,
    max_arity: int = DEFAULT_UCC_MAX_ARITY,
    max_candidate_columns: int = DEFAULT_UCC_MAX_CANDIDATE_COLUMNS,
    near_unique_threshold: float = DEFAULT_UCC_NEAR_UNIQUE_THRESHOLD,
    min_report_uniqueness_ratio: float = DEFAULT_UCC_MIN_REPORT_UNIQUENESS_RATIO,
    max_triple_candidates: int = DEFAULT_UCC_MAX_TRIPLE_CANDIDATES,
) -> list[dict[str, Any]]:
    """Discover minimal UCC candidates by streaming a CSV exactly."""

    header = pd.read_csv(csv_path, nrows=0)
    candidate_columns = select_ucc_candidate_columns(
        column_profile,
        available_columns=header.columns,
        max_candidate_columns=max_candidate_columns,
    )
    if not candidate_columns:
        return []

    single_results = validate_ucc_combinations_in_csv(
        csv_path,
        [(column,) for column in candidate_columns],
        chunk_rows=chunk_rows,
    )
    unique_single_columns = {
        candidate.columns[0]
        for candidate in single_results
        if candidate.is_unique
    }

    pair_columns = [column for column in candidate_columns if column not in unique_single_columns]
    pair_results = validate_ucc_combinations_in_csv(
        csv_path,
        list(combinations(pair_columns, 2)),
        chunk_rows=chunk_rows,
    )

    triple_results: list[UCCCandidate] = []
    if max_arity >= 3 and pair_results:
        unique_pair_sets = {
            frozenset(candidate.columns)
            for candidate in pair_results
            if candidate.is_unique
        }
        near_unique_pairs = [
            candidate.columns
            for candidate in pair_results
            if not candidate.is_unique and candidate.uniqueness_ratio >= near_unique_threshold
        ]
        triple_combinations = _build_triple_combinations(
            pair_columns,
            near_unique_pairs,
            unique_pair_sets,
            max_triple_candidates=max_triple_candidates,
        )
        triple_results = validate_ucc_combinations_in_csv(
            csv_path,
            triple_combinations,
            chunk_rows=chunk_rows,
        )

    return _finalize_candidates(
        [*single_results, *pair_results, *triple_results],
        min_report_uniqueness_ratio=min_report_uniqueness_ratio,
    )


def select_ucc_candidate_columns(
    column_profile: pd.DataFrame,
    *,
    available_columns: Iterable[str],
    max_candidate_columns: int = DEFAULT_UCC_MAX_CANDIDATE_COLUMNS,
) -> list[str]:
    """Choose likely key/category/date/code columns for bounded UCC checks."""

    available = set(available_columns)
    if column_profile.empty:
        return []

    scored_columns: list[tuple[float, int, str]] = []
    for index, row in column_profile.reset_index(drop=True).iterrows():
        column = str(row.get("column", ""))
        if not column or column not in available or column == "ID":
            continue

        role = str(row.get("role", ""))
        profile_role = str(row.get("profile_role", ""))
        if profile_role in SKIPPED_PROFILE_ROLES:
            continue
        if role not in {"identifier", "categorical"} and profile_role not in ALLOWED_PROFILE_ROLES:
            continue

        score = _candidate_score(row)
        scored_columns.append((score, index, column))

    scored_columns.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [column for _, _, column in scored_columns[:max_candidate_columns]]


def validate_ucc_combinations(
    data_frame: pd.DataFrame,
    combinations_to_check: Sequence[Sequence[str]],
) -> list[UCCCandidate]:
    """Validate combinations exactly over an in-memory dataframe."""

    normalized = _normalize_columns(data_frame, _columns_needed(combinations_to_check))
    trackers = [_CombinationTracker(tuple(columns)) for columns in combinations_to_check]
    _update_trackers(trackers, normalized)
    return [_tracker_to_candidate(tracker) for tracker in trackers]


def validate_ucc_combinations_in_csv(
    csv_path: str | Path,
    combinations_to_check: Sequence[Sequence[str]],
    *,
    chunk_rows: int = 50_000,
) -> list[UCCCandidate]:
    """Validate combinations exactly by streaming a CSV in chunks."""

    if not combinations_to_check:
        return []

    trackers = [_CombinationTracker(tuple(columns)) for columns in combinations_to_check]
    needed_columns = _columns_needed(combinations_to_check)

    for chunk in pd.read_csv(csv_path, chunksize=max(1, chunk_rows), low_memory=False):
        normalized = _normalize_columns(chunk, needed_columns)
        _update_trackers(trackers, normalized)

    return [_tracker_to_candidate(tracker) for tracker in trackers]


def _candidate_score(row: pd.Series) -> float:
    profile_role = str(row.get("profile_role", ""))
    ratio = _float_value(
        row.get(
            "full_estimated_cardinality_ratio",
            row.get("decision_cardinality_ratio", row.get("cardinality_ratio", 0.0)),
        )
    )
    unique_count = _float_value(row.get("full_estimated_unique_count", row.get("unique_count", 0)))

    score = ratio * 4.0
    if bool(row.get("id_name_hint", False)) or profile_role in {"identifier", "quasi_identifier"}:
        score += 4.0
    if profile_role in {"datetime_identifier", "datetime_category"}:
        score += 2.0
    if profile_role in {"numeric_code_category", "binary_category", "categorical"}:
        score += 1.0
    if unique_count >= 1000:
        score += 1.0
    return score


def _build_triple_combinations(
    candidate_columns: Sequence[str],
    near_unique_pairs: Sequence[Sequence[str]],
    unique_pair_sets: set[frozenset[str]],
    *,
    max_triple_candidates: int,
) -> list[tuple[str, str, str]]:
    triples: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for pair in near_unique_pairs:
        pair_set = set(pair)
        for column in candidate_columns:
            if column in pair_set:
                continue
            triple = tuple(sorted((*pair, column)))
            if triple in seen:
                continue
            if any(unique_pair.issubset(triple) for unique_pair in unique_pair_sets):
                continue
            seen.add(triple)
            triples.append(triple)
            if len(triples) >= max_triple_candidates:
                return triples

    return triples


def _finalize_candidates(
    candidates: Sequence[UCCCandidate],
    *,
    min_report_uniqueness_ratio: float,
) -> list[dict[str, Any]]:
    marked = _mark_minimal(candidates)
    reportable = [
        candidate
        for candidate in marked
        if candidate.is_minimal
        and (candidate.is_unique or candidate.uniqueness_ratio >= min_report_uniqueness_ratio)
    ]
    reportable.sort(
        key=lambda candidate: (
            not candidate.is_unique,
            -candidate.uniqueness_ratio,
            candidate.arity,
            candidate.columns,
        )
    )
    return [candidate.to_dict() for candidate in reportable]


def _mark_minimal(candidates: Sequence[UCCCandidate]) -> list[UCCCandidate]:
    unique_sets = [
        frozenset(candidate.columns)
        for candidate in candidates
        if candidate.is_unique
    ]

    marked: list[UCCCandidate] = []
    for candidate in candidates:
        columns = frozenset(candidate.columns)
        has_unique_subset = any(
            len(unique_set) < len(columns) and unique_set.issubset(columns)
            for unique_set in unique_sets
        )
        marked.append(replace(candidate, is_minimal=not has_unique_subset))
    return marked


def _update_trackers(
    trackers: Sequence[_CombinationTracker],
    normalized_columns: dict[str, pd.Series],
) -> None:
    if not trackers:
        return

    for tracker in trackers:
        if any(column not in normalized_columns for column in tracker.columns):
            continue

        subset = pd.DataFrame({column: normalized_columns[column] for column in tracker.columns})
        missing_mask = subset.eq(MISSING_TOKEN).any(axis=1)
        hashes = pd.util.hash_pandas_object(subset, index=False).to_numpy()

        tracker.row_count += int(len(subset))
        tracker.missing_rows += int(missing_mask.sum())
        tracker.seen_hashes.update(int(value) for value in hashes)


def _tracker_to_candidate(tracker: _CombinationTracker) -> UCCCandidate:
    unique_tuple_count = len(tracker.seen_hashes or set())
    duplicate_count = max(0, tracker.row_count - unique_tuple_count)
    uniqueness_ratio = float(unique_tuple_count / tracker.row_count) if tracker.row_count else 0.0
    is_unique = bool(tracker.row_count > 0 and duplicate_count == 0 and tracker.missing_rows == 0)
    confidence = _confidence(is_unique, uniqueness_ratio, tracker.missing_rows)
    reason = _reason(tracker.columns, is_unique, uniqueness_ratio, duplicate_count, tracker.missing_rows)

    return UCCCandidate(
        columns=tracker.columns,
        row_count=tracker.row_count,
        unique_tuple_count=unique_tuple_count,
        duplicate_count=duplicate_count,
        missing_rows=tracker.missing_rows,
        uniqueness_ratio=uniqueness_ratio,
        is_unique=is_unique,
        is_minimal=True,
        confidence=confidence,
        reason=reason,
    )


def _normalize_columns(data_frame: pd.DataFrame, columns: Iterable[str]) -> dict[str, pd.Series]:
    normalized: dict[str, pd.Series] = {}
    for column in columns:
        if column not in data_frame.columns:
            continue
        normalized[column] = data_frame[column].map(_normalize_value)
    return normalized


def _normalize_value(value: Any) -> str:
    if is_missing_value(value):
        return MISSING_TOKEN
    return str(value).strip().lower()


def _columns_needed(combinations_to_check: Sequence[Sequence[str]]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for combination in combinations_to_check:
        for column in combination:
            if column not in seen:
                seen.add(column)
                columns.append(column)
    return columns


def _confidence(is_unique: bool, uniqueness_ratio: float, missing_rows: int) -> str:
    if is_unique:
        return "high"
    if missing_rows:
        return "low"
    if uniqueness_ratio >= DEFAULT_UCC_NEAR_UNIQUE_THRESHOLD:
        return "medium"
    return "low"


def _reason(
    columns: tuple[str, ...],
    is_unique: bool,
    uniqueness_ratio: float,
    duplicate_count: int,
    missing_rows: int,
) -> str:
    if is_unique and len(columns) == 1:
        return "Single column has one distinct non-missing value per row."
    if is_unique:
        return "Column combination uniquely identifies rows and no smaller unique subset was found."
    if missing_rows:
        return "Candidate has missing key parts, so it is not treated as a reliable key."
    return (
        "Near-unique candidate with "
        f"{duplicate_count} duplicate row(s); uniqueness_ratio={uniqueness_ratio:.4f}."
    )


def _float_value(value: Any) -> float:
    try:
        if value is None or value != value:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
