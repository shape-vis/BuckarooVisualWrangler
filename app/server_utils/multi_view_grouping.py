"""Profiler-guided semantic-quality row grouping for Buckaroo.

Column profile roles decide which fields are safe and how each field is
transformed. Those role-specific semantic blocks and row-level quality signals
enter one normalized representation before Buckaroo compares candidate
partitions. Exact duplicate matching remains a separate advisory operation.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from itertools import combinations
import math
import re
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering, DBSCAN
from sklearn.neighbors import NearestNeighbors

from app.server_utils import adaptive_grouping_policy as agp
from app.server_utils import geography_reference as geo_ref
from app.server_utils import semantic_embeddings as se
from app.server_utils import semantic_grouping as sg
from app.server_utils.data_attribute_summary_integration import (
    build_attribute_profiles,
    get_profile_role_overrides,
    profile_role_family,
)
from app.wrangle_operations.sql_utils import id_list, quote_identifier


MULTI_VIEW_TOOL_NAME = "buckaroo_profiler_guided_semantic_quality_v2"
MULTI_VIEW_SAMPLE_SEED = 20260717
DEFAULT_LIMIT = 12
MAX_GROUP_ROW_IDS = 2000
MAX_ADAPTIVE_SAMPLE_ROWS = 10000
TEXT_TOKEN_SAFETY_CAP = 512
AGGLOMERATIVE_MEMORY_BUDGET_BYTES = 256 * 1024 * 1024
DESCRIPTION_SUPPORT_FIELD_CAP = 6
DESCRIPTION_EXAMPLE_FIELD_CAP = 5
REPRESENTATIVE_EXAMPLE_CAP = 3
CONTRADICTORY_EXAMPLE_CAP = 2
DESCRIPTION_VALUE_CHARACTER_CAP = 96
# User-facing fallback text: no internal jargon ("profiler", "natural break", column-role
# names), and phrased as an honest absence of signal rather than padding with filler.
NO_STANDOUT_FIELD_COHORT = (
    "Rows placed together without any single field standing out from the rest of the sample"
)
NO_QUALITY_SIGNAL_PHRASE = "no unusual concentration of data-quality issues in this group"

IDENTIFIER_ROLES = {"identifier", "primary_key", "quasi_identifier"}
TEMPORAL_ROLES = {
    "datetime",
    "datetime_category",
    "datetime_high_uniqueness",
    "datetime_identifier",
}
TEXT_ROLES = {"free_text"}
STRUCTURED_TEXT_ROLES = {"vector_blob"}
GEOGRAPHY_ROLES = {
    "geographic_coordinate",
    "geography_location",
    "high_uniqueness_location_field",
    "location_name",
    "postal_code",
    "airport_code",
    "country_code",
}
CATEGORICAL_ROLES = {"categorical", "binary_category", "numeric_code_category"}
SEMANTIC_BLOCK_ORDER = ("business", "text", "lifecycle", "geography", "generic")


VIEW_DEFINITIONS = {
    "semantic_quality": {
        "label": "Semantic-quality groups",
        "description": (
            "Groups rows using one representation that combines what the rows mean "
            "with detector and missingness evidence about what may be wrong."
        ),
        "why": (
            "Useful for inspecting meaningful cohorts together with their quality context, "
            "without turning errors into isolated, context-free clusters."
        ),
    },
    "business": {
        "label": "Business segments",
        "description": "Groups with similar measurements and categorical characteristics.",
        "why": "Useful for comparing meaningful cohorts and selecting a segment for inspection.",
    },
    "text": {
        "label": "Text themes",
        "description": "Groups sharing vocabulary in columns profiled as free text.",
        "why": "Useful for finding recurring topics without treating IDs or short codes as language.",
    },
    "lifecycle": {
        "label": "Lifecycle groups",
        "description": "Groups sharing statuses, event timing, and durations between events.",
        "why": "Useful for comparing process stages, delays, and event sequences.",
    },
    "geography": {
        "label": "Geographic groups",
        "description": "Groups sharing coordinates or location hierarchy.",
        "why": "Useful for regional inspection while preventing locations from becoming false row IDs.",
    },
    "generic": {
        "label": "General semantic evidence",
        "description": (
            "Profiler-approved fields with unfamiliar roles, represented from their observed "
            "values without dataset- or column-name-specific rules."
        ),
        "why": "Useful for previously unseen domains while preserving source-column identity.",
    },
    "quality": {
        "label": "Quality patterns",
        "description": "Rows sharing missingness and detector-error signatures.",
        "why": "Useful for repairing one recurring data-quality pattern at a time.",
    },
    "duplicates": {
        "label": "Near-duplicate groups",
        "description": "Rows nearly identical after identifier columns are removed.",
        "why": "Useful for finding repeated entities or records without grouping by their IDs.",
    },
}


@dataclass(frozen=True)
class MultiViewGroup:
    """JSON-ready, evidence-grounded row group returned to the UI.

    A group keeps semantic description, quality context, stability evidence,
    representative rows, and selection IDs together so ranking and explanation
    cannot silently refer to different partitions.
    """

    id: str
    view: str
    viewLabel: str
    groupType: str
    algorithm: str
    description: str
    semanticCohort: str
    qualityPattern: str
    hasQualitySignal: bool
    supportingFields: list[dict[str, Any]]
    representativeExamples: list[dict[str, Any]]
    contradictoryExamples: list[dict[str, Any]]
    descriptionGrounded: bool
    whyUseful: str
    rows: int
    coverage: float
    utilityScore: float
    semanticScore: float
    stability: float
    coherence: float
    distinctiveness: float
    explainability: float
    profileConfidence: float
    errorRows: int
    errorRate: float
    baselineErrorRate: float
    lift: float
    errorCoverage: float
    mainIssue: str
    mainErrorColumns: list[str]
    columnsUsed: list[str]
    rowIds: list[int]
    rowIdsTruncated: bool
    featureHighlights: list[str]
    caveats: list[str]


def generate_multiview_grouping_json(
    tablename: str,
    engine,
    *,
    limit: int = DEFAULT_LIMIT,
    sample_rows: int | None = None,
    min_group_size: int | None = None,
    use_semantic_embeddings: bool = False,
    use_free_text_embeddings: bool = False,
) -> dict[str, Any]:
    """Load one deterministic random sample and run semantic-quality grouping."""
    main_df, error_df, total_rows = load_multiview_sample(
        tablename,
        engine,
        sample_rows=sample_rows,
    )
    feature_frame = main_df[
        [column for column in main_df.columns if column not in sg.HELPER_COLUMNS]
    ].copy()
    profile_frame = feature_frame.drop(columns=["ID"], errors="ignore")
    profiles = build_attribute_profiles(profile_frame, total_rows=total_rows)
    overrides = get_profile_role_overrides(tablename, engine)
    return build_multiview_groups_from_frames(
        main_df,
        error_df,
        profiles=profiles,
        overrides=overrides,
        total_rows=total_rows,
        limit=limit,
        min_group_size=min_group_size,
        use_semantic_embeddings=use_semantic_embeddings,
        use_free_text_embeddings=use_free_text_embeddings,
    )


def load_multiview_sample(
    tablename: str,
    engine,
    *,
    sample_rows: int | None,
) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    """Read repeatable random rows so appended file sections are represented."""
    sg._validate_identifier(tablename)
    table_sql = quote_identifier(tablename)
    errors_sql = quote_identifier(f"errors_{tablename}")
    count_df = pd.read_sql_query(f"SELECT COUNT(*) AS count FROM {table_sql}", engine)
    total_rows = int(count_df.iloc[0]["count"]) if not count_df.empty else 0
    if sample_rows is None:
        sample_rows = min(total_rows, MAX_ADAPTIVE_SAMPLE_ROWS)
    else:
        sample_rows = max(1, min(int(sample_rows), MAX_ADAPTIVE_SAMPLE_ROWS))
    main_df = pd.read_sql_query(
        f"""
        SELECT *
        FROM {table_sql}
        ORDER BY md5(COALESCE({quote_identifier('ID')}::text, '') || '{MULTI_VIEW_SAMPLE_SEED}')
        LIMIT {sample_rows}
        """,
        engine,
    )
    if main_df.empty or "ID" not in main_df.columns:
        return main_df, sg._empty_error_df(), total_rows
    row_ids = [int(value) for value in pd.to_numeric(main_df["ID"], errors="coerce").dropna()]
    if not row_ids:
        return main_df, sg._empty_error_df(), total_rows
    try:
        error_df = pd.read_sql_query(
            f"""
            SELECT row_id, column_id, error_type
            FROM {errors_sql}
            WHERE row_id IN ({id_list(row_ids)})
            """,
            engine,
        )
    except Exception:
        error_df = sg._empty_error_df()
    return main_df, sg._normalize_error_df(error_df), total_rows


def build_multiview_groups_from_frames(
    main_df: pd.DataFrame,
    error_df: pd.DataFrame | None,
    *,
    profiles: dict[str, dict] | None = None,
    overrides: dict[str, dict] | None = None,
    total_rows: int | None = None,
    limit: int = DEFAULT_LIMIT,
    min_group_size: int | None = None,
    use_semantic_embeddings: bool = False,
    use_free_text_embeddings: bool = False,
) -> dict[str, Any]:
    """Build, rank, diversify, and serialize useful groups from all views."""
    limit = max(1, min(int(limit or DEFAULT_LIMIT), 30))
    if main_df is None or main_df.empty or "ID" not in main_df.columns:
        return empty_multiview_response(total_rows or 0)

    working_df = prepare_working_frame(main_df, error_df)
    error_df = sg._normalize_error_df(error_df)
    profile_map = resolve_profile_map(
        working_df,
        profiles=profiles,
        overrides=overrides,
        total_rows=total_rows,
    )
    adaptive_policy = agp.build_dataset_policy(
        working_df,
        profile_map,
        requested_min_group_size=min_group_size,
    )
    effective_min_group_size = adaptive_policy.min_group_size
    view_columns, excluded = choose_view_columns(
        working_df,
        profile_map,
        confidence_cutoff=adaptive_policy.profile_confidence_cutoff,
    )
    baseline_error_rate = float(working_df["_buckaroo_has_error"].mean())
    total_error_rows = int(working_df["_buckaroo_has_error"].sum())

    semantic_quality_groups, semantic_quality_run = generate_semantic_quality_candidates(
        working_df,
        error_df,
        view_columns=view_columns,
        profile_map=profile_map,
        baseline_error_rate=baseline_error_rate,
        total_error_rows=total_error_rows,
        min_group_size=effective_min_group_size,
        use_semantic_embeddings=use_semantic_embeddings,
        use_free_text_embeddings=use_free_text_embeddings,
    )
    duplicate_groups, duplicate_run = generate_duplicate_candidates(
        working_df,
        error_df,
        columns=view_columns["duplicates"],
        profile_map=profile_map,
        baseline_error_rate=baseline_error_rate,
        total_error_rows=total_error_rows,
    )
    candidates = [*semantic_quality_groups, *duplicate_groups]
    view_runs = [semantic_quality_run, duplicate_run]

    # This is a data-quality tool: a cluster with no enriched data-quality issue is not a
    # finding a user of this tool needs, however semantically clean it is. Groups whose
    # quality pattern is the "no unusual concentration of data-quality issues" fallback are
    # dropped entirely here (not merely ranked lower) — a deliberate policy choice to keep
    # only clusters that concentrate a real quality problem. See ADAPTIVE_DECISION_POLICY.md.
    quality_candidates_total = len(candidates)
    candidates = [group for group in candidates if group.hasQualitySignal]
    quality_filtered_out = quality_candidates_total - len(candidates)

    accepted, acceptance_policy = select_useful_candidates(candidates)
    deduplicated, overlap_cutoff = dedupe_candidate_groups(accepted)
    ranked = rank_groups_semantic_first(deduplicated, limit=limit)
    counts = Counter(group.view for group in ranked)
    view_summaries = []
    run_by_view = {run["id"]: run for run in view_runs}
    for view_id in ("semantic_quality", "duplicates"):
        definition = VIEW_DEFINITIONS[view_id]
        run = run_by_view.get(view_id, {"status": "unavailable", "algorithm": "none", "candidates": 0})
        view_summary = {
            "id": view_id,
            "label": definition["label"],
            "description": definition["description"],
            "status": run["status"],
            "algorithm": run["algorithm"],
            "columns": run.get("columns", view_columns.get(view_id, [])),
            "candidatesGenerated": int(run["candidates"]),
            "groupsShown": int(counts.get(view_id, 0)),
            "note": run.get("note", ""),
        }
        if run.get("adaptiveDiagnostics"):
            view_summary["adaptiveDiagnostics"] = run["adaptiveDiagnostics"]
        view_summaries.append(view_summary)

    role_counts = Counter(profile["role"] for profile in profile_map.values())
    return {
        "strategy": "profiler_guided_semantic_quality",
        "effectiveStrategy": "profiler_guided_semantic_quality",
        "compatibilityStrategy": "profiler_guided_multi_view",
        "similarityTool": MULTI_VIEW_TOOL_NAME,
        "similarityDescription": (
            "Profiler roles transform measurements, categories, text, lifecycle, and geography "
            "appropriately, then combine those semantic signals with detector and missingness "
            "evidence in one row representation. Identifiers never enter the distance matrix."
        ),
        "sampleRows": int(len(working_df)),
        "requestedSampleRows": int(len(main_df)),
        "totalRows": int(total_rows if total_rows is not None else len(working_df)),
        "samplingMethod": "deterministic_random_without_replacement",
        "samplingSeed": MULTI_VIEW_SAMPLE_SEED,
        "baselineErrorRate": round(baseline_error_rate, 6),
        "errorRows": total_error_rows,
        "groups": [asdict(group) for group in ranked],
        "views": view_summaries,
        "representation": semantic_quality_run.get("representation", {}),
        "profileSummary": {
            "columnsProfiled": len(profile_map),
            "roleCounts": dict(sorted(role_counts.items())),
            "excludedIdentifierColumns": excluded["identifier"],
            "excludedLowConfidenceColumns": excluded["low_confidence"],
            "excludedStructuredTextColumns": excluded["structured_text"],
            "userOverridesApplied": sorted(
                column for column, profile in profile_map.items() if profile["source"] == "user_override"
            ),
        },
        "adaptivePolicy": {
            **adaptive_policy.to_dict(),
            "effectiveSampleRows": int(len(working_df)),
            "sampleResourceCap": MAX_ADAPTIVE_SAMPLE_ROWS,
            "acceptance": acceptance_policy,
            "sameViewOverlapCutoff": overlap_cutoff,
            "qualitySignalRequired": True,
            "groupsDroppedWithoutQualitySignal": int(quality_filtered_out),
            "humanLabelsUsed": False,
        },
        "rankingMethod": {
            "name": "adaptive_semantic_quality_empirical_percentile_v3",
            "components": [
                "stability",
                "coherence",
                "distinctiveness",
                "explainability",
                "profileConfidence",
                "nontrivialCoverage",
            ],
            "combination": "median empirical percentile inside the combined semantic-quality view; no fixed utility weights",
            "adaptiveFilters": [
                "identifier columns do not enter semantic distance",
                "semantic and quality signals enter one normalized representation",
                "each active evidence block is normalized before concatenation so feature count cannot dominate",
                "confidence and candidate cutoffs use natural breaks in observed values",
                "dominant coverage uses the observed robust upper fence",
                "algorithm and cluster count are selected from repeated-run evidence",
                "same-view overlap deduplication uses the observed overlap distribution",
            ],
        },
    }


def prepare_working_frame(main_df: pd.DataFrame, error_df: pd.DataFrame | None) -> pd.DataFrame:
    frame = main_df.copy().reset_index(drop=True)
    frame["ID"] = pd.to_numeric(frame["ID"], errors="coerce").astype("Int64")
    frame = frame[frame["ID"].notna()].copy().reset_index(drop=True)
    frame["ID"] = frame["ID"].astype(int)
    normalized_errors = sg._normalize_error_df(error_df)
    counts = normalized_errors.groupby("row_id").size() if not normalized_errors.empty else pd.Series(dtype=int)
    error_ids = set(int(value) for value in counts.index.tolist())
    frame["_buckaroo_has_error"] = frame["ID"].isin(error_ids)
    frame["_buckaroo_error_count"] = frame["ID"].map(counts).fillna(0).astype(int)
    return frame


def resolve_profile_map(
    frame: pd.DataFrame,
    *,
    profiles: dict[str, dict] | None,
    overrides: dict[str, dict] | None,
    total_rows: int | None,
) -> dict[str, dict]:
    real_columns = [
        column for column in frame.columns
        if column not in sg.HELPER_COLUMNS and not column.startswith("_buckaroo_")
    ]
    feature_columns = [column for column in real_columns if column != "ID"]
    if profiles is None:
        profiles = build_attribute_profiles(frame[feature_columns], total_rows=total_rows)
    overrides = overrides or {}
    result = {}
    for column in feature_columns:
        profile = dict((profiles or {}).get(column) or {})
        override = overrides.get(column)
        fallback_role_name, fallback_confidence = fallback_profile(frame[column])
        role = str(
            (override or {}).get("role")
            or profile.get("userOverrideRole")
            or profile.get("profileRole")
            or fallback_role_name
        )
        source = "user_override" if override or profile.get("userOverrideRole") else "profiler"
        reported_confidence = safe_float(profile.get("confidenceScore"), math.nan)
        if source == "user_override":
            confidence = 1.0
            confidence_source = "user_override"
        elif math.isfinite(reported_confidence):
            confidence = reported_confidence
            confidence_source = "profiler"
        else:
            confidence = role_evidence_confidence(frame[column], role, fallback_confidence)
            confidence_source = "column_distribution"
        result[column] = {
            "role": role,
            "family": profile_role_family(role),
            "confidence": float(np.clip(confidence, 0.0, 1.0)),
            "confidence_source": confidence_source,
            "source": source,
            "warning": str(profile.get("dataWarning") or ""),
            "ambiguous": bool(profile.get("classificationAmbiguous")),
        }
    return result


def fallback_profile(series: pd.Series) -> tuple[str, float]:
    non_missing = series[~series.map(sg.is_missing_value)]
    if non_missing.empty:
        return "categorical", 1.0
    numeric = pd.to_numeric(non_missing, errors="coerce")
    numeric_ratio = float(numeric.notna().mean())
    dates = pd.to_datetime(non_missing, errors="coerce", format="mixed", utc=True)
    date_ratio = float(dates.notna().mean())
    unique_ratio = float(non_missing.astype(str).nunique(dropna=True) / max(1, len(non_missing)))
    candidates = {
        "numeric_measure": numeric_ratio,
        "datetime": date_ratio,
        "categorical": 1.0 - unique_ratio,
        "free_text": unique_ratio,
    }
    role, confidence = max(candidates.items(), key=lambda candidate: candidate[1])
    return role, float(confidence)


def fallback_role(series: pd.Series) -> str:
    """Compatibility wrapper retained for callers that only need the role."""
    return fallback_profile(series)[0]


def role_evidence_confidence(series: pd.Series, role: str, fallback: float) -> float:
    non_missing = series[~series.map(sg.is_missing_value)]
    if non_missing.empty:
        return 1.0
    unique_ratio = float(non_missing.astype(str).nunique(dropna=True) / max(1, len(non_missing)))
    if role in TEMPORAL_ROLES or role == "datetime":
        parsed = pd.to_datetime(non_missing, errors="coerce", format="mixed", utc=True)
        return float(parsed.notna().mean())
    if role in GEOGRAPHY_ROLES and role == "geographic_coordinate":
        return float(pd.to_numeric(non_missing, errors="coerce").notna().mean())
    family = profile_role_family(role)
    if family == "numeric":
        return float(pd.to_numeric(non_missing, errors="coerce").notna().mean())
    if family == "categorical":
        return float(1.0 - unique_ratio)
    if family == "text":
        return unique_ratio
    return float(np.clip(fallback, 0.0, 1.0))


def _pick_city_context_column(
    geography_candidates: list[str],
    profile_map: dict[str, dict],
    geography_rescued: set[str],
) -> str | None:
    """Best-effort companion country/region column for city-name
    disambiguation.

    Prefers an explicit country_code-role column -- the clearest per-row
    country signal a dataset can offer -- then falls back to a location_name
    column that already resolved cleanly as a country itself (geography_
    rescued). Returns None if neither exists; city_centroid still works
    without a hint, just via population-only tie-breaking.
    """
    for column in geography_candidates:
        if profile_map.get(column, {}).get("role") == "country_code":
            return column
    return next(iter(geography_rescued), None)


def choose_view_columns(
    frame: pd.DataFrame,
    profile_map: dict[str, dict],
    *,
    confidence_cutoff: float,
    country_resolver=geo_ref.country_centroid,
    city_resolver=geo_ref.city_centroid,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    # country_resolver/city_resolver are injectable so tests never need to
    # load the real geonamescache/pycountry reference data -- same reasoning
    # as build_geography_matrix's identically-named parameters.
    # The general profiler-confidence score is dominated by two column-blind
    # terms -- a sample-size-only worst-case reliability ceiling (identical
    # for every column at a given row count) and a binary name-hint bonus (does
    # the column name literally contain one of ~16 English words) -- so a
    # genuinely clean bucketed-range column like "YearsCoding" can sit just
    # under the cutoff for reasons that have nothing to do with whether it is
    # actually a well-formed ordinal scale. ordinal_eligible_columns() is a
    # much stronger, column-specific, per-column-only signal (every distinct
    # value must cleanly parse as a bucketed range) that the confidence score
    # never sees, so a column that clears it is exempted from the general
    # cutoff -- for ordinal purposes specifically, not a blanket confidence
    # override. Safe to compute ahead of the eligible/excluded split below
    # because it is a pure per-column check with no cross-column comparison,
    # unlike embedding_eligible_columns' cardinality tiering (deliberately not
    # given the same exemption -- widening its candidate pool would shift the
    # tiering split for sibling columns too, a real behavioral change that
    # needs its own scoped decision, not a side effect of this one).
    categorical_columns = [
        column for column, profile in profile_map.items()
        if profile.get("role") == "categorical"
    ]
    ordinal_rescued = set(ordinal_eligible_columns(categorical_columns, frame, profile_map))

    # Same reasoning and same exemption pattern as ordinal_rescued above, for
    # the same reason: geography_name_eligible_columns() requires every
    # distinct value to independently resolve to a real place, a stronger,
    # column-specific signal the general confidence score doesn't see. Also a
    # pure per-column check with no cross-column comparison, so safe to
    # compute here the same way. Found live: fixing the reliability-formula
    # ceiling (see score_profile_confidence) raised most columns' scores,
    # which shifted the adaptive confidence_cutoff itself upward -- and
    # "Country" (whose own geography-role score didn't move) got left behind
    # by columns that moved past it, even though every one of its values
    # resolves cleanly to a real country.
    geography_candidates = [
        column for column, profile in profile_map.items()
        if profile.get("role") in geo_ref.GEOGRAPHY_NAME_ELIGIBLE_ROLES
    ]
    geography_rescued = set(geo_ref.geography_name_eligible_columns(
        geography_candidates, frame, profile_map, resolver=country_resolver,
    ))

    # City-name columns get the same narrow exemption, for the same reason,
    # once they independently clear city_name_eligible_columns' per-row,
    # context-first, population-as-last-resort resolution (see
    # geography_reference.py). Only candidates that geography_rescued did
    # NOT already claim -- a column that resolves cleanly as a country
    # should stay on the country path, not be re-tried as a city.
    city_candidates = [
        column for column in geography_candidates
        if column not in geography_rescued
        and profile_map[column].get("role") in geo_ref.CITY_NAME_ELIGIBLE_ROLES
    ]
    city_context_column = _pick_city_context_column(
        geography_candidates, profile_map, geography_rescued,
    )
    city_rescued = set(geo_ref.city_name_eligible_columns(
        city_candidates, frame, profile_map,
        context_column=city_context_column, resolver=city_resolver,
    ))

    excluded = {"identifier": [], "low_confidence": [], "structured_text": []}
    eligible = []
    for column, profile in profile_map.items():
        if profile["role"] in IDENTIFIER_ROLES:
            excluded["identifier"].append(column)
            continue
        if profile["role"] in STRUCTURED_TEXT_ROLES:
            excluded["structured_text"].append(column)
            continue
        if (
            profile["confidence"] < confidence_cutoff
            and column not in ordinal_rescued
            and column not in geography_rescued
            and column not in city_rescued
        ):
            excluded["low_confidence"].append(column)
            continue
        eligible.append(column)

    def ranked(columns: list[str]) -> list[str]:
        return sorted(columns, key=lambda column: profile_map[column]["confidence"], reverse=True)

    text = ranked([column for column in eligible if profile_map[column]["role"] in TEXT_ROLES])
    # Semantic routing follows profiler roles, not dataset-specific name lists.
    # Ordinary categorical status fields still participate through the business
    # block; only columns profiled as temporal enter lifecycle transformations.
    lifecycle = ranked([
        column for column in eligible
        if profile_map[column]["role"] in TEMPORAL_ROLES
    ])
    geography = ranked([
        column for column in eligible
        if profile_map[column]["family"] == "geography" or profile_map[column]["role"] in GEOGRAPHY_ROLES
    ])
    specialized = set([*text, *lifecycle, *geography])
    business = ranked([
        column for column in eligible
        if column not in specialized
        and profile_map[column]["family"] in {"numeric", "categorical"}
    ])
    specialized.update(business)
    generic = ranked([column for column in eligible if column not in specialized])
    quality = ranked([
        column for column, profile in profile_map.items()
        if profile["role"] not in IDENTIFIER_ROLES
        and profile["role"] not in STRUCTURED_TEXT_ROLES
    ])
    duplicate_priority = {
        "categorical": 0,
        "numeric": 1,
        "geography": 2,
        "text": 3,
        "temporal": 4,
    }
    duplicate_candidates = [
        column for column in eligible
        if profile_map[column]["role"] not in TEMPORAL_ROLES
    ]
    duplicates = sorted(
        duplicate_candidates,
        key=lambda column: (
            duplicate_priority.get(profile_map[column]["family"], 9),
            -profile_map[column]["confidence"],
        ),
    )
    return {
        "business": business,
        "text": text,
        "lifecycle": lifecycle,
        "geography": geography,
        "generic": generic,
        "quality": quality,
        "duplicates": duplicates,
    }, excluded


def generate_semantic_quality_candidates(
    frame: pd.DataFrame,
    error_df: pd.DataFrame,
    *,
    view_columns: dict[str, list[str]],
    profile_map: dict[str, dict],
    baseline_error_rate: float,
    total_error_rows: int,
    min_group_size: int,
    use_semantic_embeddings: bool = False,
    use_free_text_embeddings: bool = False,
) -> tuple[list[MultiViewGroup], dict]:
    """Cluster one matrix containing semantic meaning and quality evidence."""
    matrix, feature_info = build_semantic_quality_matrix(
        frame,
        error_df,
        view_columns=view_columns,
        profile_map=profile_map,
        use_semantic_embeddings=use_semantic_embeddings,
        use_free_text_embeddings=use_free_text_embeddings,
    )
    representation = feature_info["representation"]
    active_semantic_blocks = [
        block for block in representation["activeBlocks"]
        if block != "quality"
    ]
    if not active_semantic_blocks:
        run = view_run(
            "semantic_quality",
            "unavailable",
            "none",
            0,
            "No profiler-approved semantic features have usable variation.",
        )
        run["columns"] = feature_info["columns_used"]
        run["representation"] = representation
        return [], run
    if matrix.shape[1] == 0 or np.unique(matrix, axis=0).shape[0] < 2:
        run = view_run(
            "semantic_quality",
            "unavailable",
            "none",
            0,
            "The combined semantic-quality representation has no usable variation.",
        )
        run["columns"] = feature_info["columns_used"]
        run["representation"] = representation
        return [], run

    labels, alternate_labels, algorithm_label, selection_diagnostics = run_internal_clustering(
        matrix,
        min_group_size=min_group_size,
    )
    groups = groups_from_partition(
        frame,
        error_df,
        view="semantic_quality",
        columns=feature_info["columns_used"],
        profile_map=profile_map,
        matrix=matrix,
        feature_info=feature_info,
        labels=labels,
        alternate_labels=alternate_labels,
        algorithm=algorithm_label,
        baseline_error_rate=baseline_error_rate,
        total_error_rows=total_error_rows,
        min_group_size=min_group_size,
    )
    status = "ready" if groups else "no_useful_groups"
    note = "" if groups else "Candidates were generated but did not pass usefulness safeguards."
    selection_diagnostics["representation"] = representation
    run = view_run(
        "semantic_quality",
        status,
        algorithm_label,
        len(groups),
        note,
        diagnostics=selection_diagnostics,
    )
    run["columns"] = feature_info["columns_used"]
    run["representation"] = representation
    return groups, run


def build_semantic_quality_matrix(
    frame: pd.DataFrame,
    error_df: pd.DataFrame,
    *,
    view_columns: dict[str, list[str]],
    profile_map: dict[str, dict],
    use_semantic_embeddings: bool = False,
    use_free_text_embeddings: bool = False,
    embedder=None,
    country_resolver=geo_ref.country_centroid,
    city_resolver=geo_ref.city_centroid,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Build one row representation from normalized semantic and quality blocks.

    Role-specific transformations remain separate preprocessing operations, but
    they no longer produce separate clusterings. Every active block is row-L2
    normalized before concatenation so a wide text block cannot win merely by
    having more columns. No hand-tuned block weights are applied.
    """
    block_matrices: list[np.ndarray] = []
    block_diagnostics = []
    active_blocks = []
    inactive_blocks = []
    semantic_columns = []
    merged_numeric_columns = []
    merged_terms = []
    merged_text_matrices = []
    merged_parsed_dates: dict[str, pd.Series] = {}
    merged_durations = []
    merged_coordinate_pairs = []
    merged_embedding_columns: list[str] = []
    merged_embedding_values_by_column: dict[str, dict[str, Any]] = {}
    merged_ordinal_columns: list[str] = []
    merged_geography_name_columns: list[str] = []
    merged_geography_centroids_by_column: dict[str, dict[str, Any]] = {}

    for block_name in SEMANTIC_BLOCK_ORDER:
        columns = view_columns.get(block_name, [])
        if not columns:
            inactive_blocks.append(block_name)
            continue
        raw_matrix, info = build_view_matrix(
            frame,
            block_name,
            columns,
            profile_map,
            use_semantic_embeddings=use_semantic_embeddings,
            use_free_text_embeddings=use_free_text_embeddings,
            embedder=embedder,
            country_resolver=country_resolver,
            city_resolver=city_resolver,
        )
        block_matrix = normalize_evidence_block(raw_matrix)
        if block_matrix.shape[1] == 0 or np.unique(block_matrix, axis=0).shape[0] < 2:
            inactive_blocks.append(block_name)
            continue
        block_matrices.append(block_matrix)
        active_blocks.append(block_name)
        semantic_columns.extend(columns)
        block_diagnostic = {
            "id": block_name,
            "purpose": VIEW_DEFINITIONS[block_name]["description"],
            "dimensions": int(block_matrix.shape[1]),
            "nonZeroRows": int(np.count_nonzero(np.linalg.norm(block_matrix, axis=1))),
            "routedColumns": list(columns),
        }
        if info.get("generic_inferred_roles"):
            block_diagnostic["observedValueFallbackRoles"] = info["generic_inferred_roles"]
        block_diagnostics.append(block_diagnostic)
        merged_numeric_columns.extend(info.get("numeric_columns", []))
        text_matrix = info.get("text_matrix")
        terms = list(info.get("terms") or [])
        if text_matrix is not None and getattr(text_matrix, "size", 0) and terms:
            merged_text_matrices.append(np.asarray(text_matrix, dtype=float))
            merged_terms.extend(terms)
        merged_parsed_dates.update(info.get("parsed_dates", {}))
        merged_durations.extend(info.get("durations", []))
        merged_coordinate_pairs.extend(info.get("coordinate_pairs", []))
        merged_embedding_columns.extend(info.get("embeddingColumns", []))
        merged_embedding_values_by_column.update(info.get("embeddingValuesByColumn") or {})
        merged_ordinal_columns.extend(info.get("ordinalColumns", []))
        merged_geography_name_columns.extend(info.get("geographyNameColumns", []))
        merged_geography_centroids_by_column.update(info.get("geographyCentroidsByColumn") or {})

    quality_matrix, quality_info = build_quality_signal_matrix(
        frame,
        error_df,
        columns=view_columns.get("quality", []),
    )
    quality_matrix = normalize_evidence_block(quality_matrix)
    if quality_matrix.shape[1] and np.unique(quality_matrix, axis=0).shape[0] >= 2:
        block_matrices.append(quality_matrix)
        active_blocks.append("quality")
        block_diagnostics.append({
            "id": "quality",
            "purpose": "Detector and missingness evidence describing what may be wrong.",
            "dimensions": int(quality_matrix.shape[1]),
            "nonZeroRows": int(np.count_nonzero(np.linalg.norm(quality_matrix, axis=1))),
            "routedColumns": quality_info["quality_columns"],
        })
    else:
        inactive_blocks.append("quality")

    combined = (
        sg.l2_normalize(np.hstack(block_matrices))
        if block_matrices
        else np.zeros((len(frame), 0), dtype=float)
    )
    semantic_text_matrix = (
        np.hstack(merged_text_matrices)
        if merged_text_matrices
        else np.zeros((len(frame), 0), dtype=float)
    )
    columns_used = unique_strings([
        *semantic_columns,
        *quality_info["quality_columns"],
    ])
    representation = {
        "mode": "single_combined_semantic_quality_matrix",
        "activeBlocks": active_blocks,
        "inactiveBlocks": unique_strings(inactive_blocks),
        "blocks": block_diagnostics,
        "featureDimensions": int(combined.shape[1]),
        "semanticColumns": unique_strings(semantic_columns),
        "semanticColumnAssignments": {
            column: block["id"]
            for block in block_diagnostics
            if block["id"] != "quality"
            for column in block["routedColumns"]
        },
        "routingPolicy": "mutually exclusive profiler-role routing with a value-driven generic fallback",
        "embeddingColumns": unique_strings(merged_embedding_columns),
        "ordinalColumns": unique_strings(merged_ordinal_columns),
        "geographyNameColumns": unique_strings(merged_geography_name_columns),
        "qualityColumns": quality_info["quality_columns"],
        "qualitySignalRows": quality_info["signal_rows"],
        "qualitySignalRate": round(quality_info["signal_rate"], 6),
        "qualitySignalTypes": quality_info["signal_types"],
        "normalization": "row L2 within each evidence block, then row L2 after concatenation",
        "manualBlockWeights": False,
        "humanLabelsUsed": False,
    }
    return combined, {
        "numeric_columns": unique_strings(merged_numeric_columns),
        "terms": merged_terms,
        "text_matrix": semantic_text_matrix,
        "parsed_dates": merged_parsed_dates,
        "durations": merged_durations,
        "coordinate_pairs": merged_coordinate_pairs,
        "quality_terms": quality_info["terms"],
        "quality_matrix": quality_info["text_matrix"],
        "quality_row_tokens": quality_info["row_tokens"],
        "row_positions": {int(row_id): index for index, row_id in enumerate(frame["ID"].tolist())},
        "columns_used": columns_used,
        "semantic_columns": unique_strings(semantic_columns),
        "representation": representation,
        "embeddingColumns": unique_strings(merged_embedding_columns),
        "embeddingValuesByColumn": merged_embedding_values_by_column,
        "ordinalColumns": unique_strings(merged_ordinal_columns),
        "geographyNameColumns": unique_strings(merged_geography_name_columns),
        "geographyCentroidsByColumn": merged_geography_centroids_by_column,
    }


def normalize_evidence_block(matrix: np.ndarray) -> np.ndarray:
    """Remove non-discriminating dimensions and give each active block equal scale."""
    matrix = np.asarray(matrix, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] == 0:
        rows = matrix.shape[0] if matrix.ndim == 2 else 0
        return np.zeros((rows, 0), dtype=float)
    matrix = np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0)
    varying = np.ptp(matrix, axis=0) > np.finfo(float).eps
    matrix = matrix[:, varying]
    if matrix.shape[1] == 0:
        return matrix
    return sg.l2_normalize(matrix)


def build_quality_signal_matrix(
    frame: pd.DataFrame,
    error_df: pd.DataFrame,
    *,
    columns: list[str],
) -> tuple[np.ndarray, dict[str, Any]]:
    """Represent recurring detector findings and missingness without identifiers."""
    row_positions = {
        int(row_id): position
        for position, row_id in enumerate(frame["ID"].tolist())
    }
    row_tokens: list[set[str]] = [set() for _ in range(len(frame))]
    quality_columns = set()
    signal_types = set()

    for record in error_df.itertuples(index=False):
        position = row_positions.get(int(record.row_id))
        column = str(record.column_id)
        if position is None or column not in columns:
            continue
        error_type = str(record.error_type or "detected issue")
        row_tokens[position].add(
            f"quality__{column_token(error_type)}__{column_token(column)}"
        )
        quality_columns.add(column)
        signal_types.add(error_type)

    for column in columns:
        if column not in frame:
            continue
        missing = frame[column].map(sg.is_missing_value).to_numpy(dtype=bool)
        if not missing.any():
            continue
        token = f"quality__missing__{column_token(column)}"
        for position in np.flatnonzero(missing):
            row_tokens[int(position)].add(token)
        quality_columns.add(column)
        signal_types.add("missing")

    token_documents = [sorted(tokens) for tokens in row_tokens]
    text_matrix, terms = sg.build_tfidf_matrix(token_documents)
    signal_counts = np.asarray([len(tokens) for tokens in row_tokens], dtype=float)
    count_features = []
    if np.unique(signal_counts).size > 1:
        median = float(np.median(signal_counts))
        q1, q3 = np.quantile(signal_counts, [0.25, 0.75])
        scale = float(q3 - q1)
        if not math.isfinite(scale) or scale <= 0:
            scale = float(np.std(signal_counts))
        if math.isfinite(scale) and scale > 0:
            standardized = (signal_counts - median) / scale
            clip_bound = agp.adaptive_clip_bound(standardized)
            count_features.append(np.clip(standardized, -clip_bound, clip_bound) / clip_bound)
        count_features.append((signal_counts > 0).astype(float))
    count_matrix = (
        np.vstack(count_features).T
        if count_features
        else np.zeros((len(frame), 0), dtype=float)
    )
    matrix = combine_and_normalize(count_matrix, text_matrix, len(frame))
    signal_rows = int(np.count_nonzero(signal_counts))
    return matrix, {
        "terms": terms,
        "text_matrix": text_matrix,
        "row_tokens": token_documents,
        "quality_columns": sorted(quality_columns),
        "signal_types": sorted(signal_types),
        "signal_rows": signal_rows,
        "signal_rate": signal_rows / max(1, len(frame)),
    }


def generate_semantic_view_candidates(
    frame: pd.DataFrame,
    error_df: pd.DataFrame,
    *,
    view: str,
    columns: list[str],
    profile_map: dict[str, dict],
    baseline_error_rate: float,
    total_error_rows: int,
    min_group_size: int,
) -> tuple[list[MultiViewGroup], dict]:
    if not columns:
        return [], view_run(view, "unavailable", "none", 0, "No profiler-approved columns for this view.")
    matrix, feature_info = build_view_matrix(frame, view, columns, profile_map)
    if matrix.shape[1] == 0 or np.unique(matrix, axis=0).shape[0] < 2:
        return [], view_run(view, "unavailable", "none", 0, "The approved columns have no usable variation.")

    labels, alternate_labels, algorithm_label, selection_diagnostics = run_internal_clustering(
        matrix,
        min_group_size=min_group_size,
    )
    groups = groups_from_partition(
        frame,
        error_df,
        view=view,
        columns=columns,
        profile_map=profile_map,
        matrix=matrix,
        feature_info=feature_info,
        labels=labels,
        alternate_labels=alternate_labels,
        algorithm=algorithm_label,
        baseline_error_rate=baseline_error_rate,
        total_error_rows=total_error_rows,
        min_group_size=min_group_size,
    )
    status = "ready" if groups else "no_useful_groups"
    note = "" if groups else "Candidates were generated but did not pass usefulness safeguards."
    return groups, view_run(
        view,
        status,
        algorithm_label,
        len(groups),
        note,
        diagnostics=selection_diagnostics,
    )


def build_view_matrix(
    frame: pd.DataFrame,
    view: str,
    columns: list[str],
    profile_map: dict[str, dict],
    *,
    use_semantic_embeddings: bool = False,
    use_free_text_embeddings: bool = False,
    embedder=None,
    country_resolver=geo_ref.country_centroid,
    city_resolver=geo_ref.city_centroid,
) -> tuple[np.ndarray, dict]:
    if view == "lifecycle":
        return build_lifecycle_matrix(frame, columns, profile_map)
    if view == "geography":
        return build_geography_matrix(
            frame, columns, profile_map,
            country_resolver=country_resolver, city_resolver=city_resolver,
        )
    if view == "generic":
        return build_generic_matrix(frame, columns, profile_map)

    numeric_columns = [column for column in columns if profile_map[column]["family"] == "numeric"]
    text_columns = [column for column in columns if column not in numeric_columns]

    # Ordinal columns are resolved first and removed from the text_columns pool:
    # a bucketed-range column like "YearsCoding" ("0-2 years" ... "9-11 years")
    # would also pass the categorical role gate for embeddings, but genuine
    # numeric distance is exact where embedding similarity is only approximate
    # for magnitude -- always on, no flag, since it is deterministic arithmetic
    # with a strict eligibility gate (RANKING_AND_SIMILARITY_POSITION.md Sec 2.3).
    ordinal_columns: list[str] = []
    if view == "business" and text_columns:
        ordinal_columns = ordinal_eligible_columns(text_columns, frame, profile_map)
    text_columns = [column for column in text_columns if column not in ordinal_columns]

    embedding_columns: list[str] = []
    if use_semantic_embeddings and view == "business" and text_columns:
        embedding_columns = se.embedding_eligible_columns(
            text_columns, frame, profile_map, agp.natural_break_threshold,
        )
    elif use_free_text_embeddings and view == "text" and text_columns:
        # Opt-in and separately gated from the always-on categorical path above --
        # see free_text_embedding_eligible_columns for why this replaces TF-IDF
        # for eligible columns instead of running alongside it.
        embedding_columns = se.free_text_embedding_eligible_columns(text_columns, profile_map)
    token_columns = [column for column in text_columns if column not in embedding_columns]

    numeric_source_frame = (
        ordinal_numeric_frame(frame, ordinal_columns) if ordinal_columns else frame
    )
    numeric, numeric_names = build_weighted_numeric_matrix(
        numeric_source_frame, numeric_columns + ordinal_columns, profile_map,
    )
    text, terms = build_weighted_text_matrix(frame, token_columns, profile_map, free_text=view == "text")
    embedding_matrix, embedding_names, embedding_values_by_column = (
        se.build_embedding_matrix(frame, embedding_columns, profile_map, embedder=embedder)
        if embedding_columns
        else (np.zeros((len(frame), 0), dtype=float), [], {})
    )
    matrix = combine_many_and_normalize([numeric, text, embedding_matrix], len(frame))
    info = feature_metadata(frame, numeric_names, terms, text)
    if ordinal_columns:
        info["ordinalColumns"] = ordinal_columns
    if embedding_columns:
        info["embeddingColumns"] = embedding_columns
        info["embeddingDimensions"] = len(embedding_names)
        info["embeddingValuesByColumn"] = embedding_values_by_column
    return matrix, info


def build_generic_matrix(
    frame: pd.DataFrame,
    columns: list[str],
    profile_map: dict[str, dict],
) -> tuple[np.ndarray, dict[str, Any]]:
    """Represent unfamiliar profiler roles from values without domain rules.

    This is the open-world fallback. It does not assume a fixed catalogue of
    business domains or column names. Instead, it asks whether each unfamiliar
    field behaves numerically, temporally, or symbolically in the current
    sample, then applies the corresponding standard Buckaroo transformation.
    """
    inferred_profiles: dict[str, dict[str, Any]] = {}
    for column in columns:
        inferred_role, observed_confidence = fallback_profile(frame[column])
        source_confidence = max(
            np.finfo(float).eps,
            float(profile_map[column].get("confidence", 0.0)),
        )
        inferred_profiles[column] = {
            **profile_map[column],
            "role": inferred_role,
            "family": profile_role_family(inferred_role),
            "confidence": math.sqrt(
                source_confidence * max(np.finfo(float).eps, observed_confidence)
            ),
            "fallbackSource": "observed value distribution",
        }

    temporal_columns = [
        column for column in columns
        if inferred_profiles[column]["role"] in TEMPORAL_ROLES
        or inferred_profiles[column]["role"] == "datetime"
    ]
    numeric_columns = [
        column for column in columns
        if column not in temporal_columns
        and inferred_profiles[column]["family"] == "numeric"
    ]
    symbolic_columns = [
        column for column in columns
        if column not in temporal_columns and column not in numeric_columns
    ]

    numeric_matrix, numeric_names = build_weighted_numeric_matrix(
        frame,
        numeric_columns,
        inferred_profiles,
    )
    symbolic_matrix, terms = build_weighted_text_matrix(
        frame,
        symbolic_columns,
        inferred_profiles,
        free_text=False,
    )
    temporal_matrix, temporal_info = build_lifecycle_matrix(
        frame,
        temporal_columns,
        inferred_profiles,
    )
    matrix = combine_many_and_normalize(
        [numeric_matrix, symbolic_matrix, temporal_matrix],
        len(frame),
    )
    info = feature_metadata(frame, numeric_names, terms, symbolic_matrix)
    info["parsed_dates"] = temporal_info.get("parsed_dates", {})
    info["durations"] = temporal_info.get("durations", [])
    info["generic_inferred_roles"] = {
        column: inferred_profiles[column]["role"] for column in columns
    }
    return matrix, info


# Deliberately NOT "any string with a digit in it" -- a bare label-plus-number
# like "Country 14" or "Job 7" must never parse, or any high-cardinality coded
# category with an incidental number would be mistaken for a bucketed scale.
# Every pattern below requires actual range/comparison structure: two numbers
# joined by a range separator, or a number paired with bound vocabulary
# ("under", "or more", ...). A bare number with no such structure is rejected.
_NUM = r"\$?(\d[\d,]*\.?\d*)"
ORDINAL_RANGE_PATTERN = re.compile(rf"{_NUM}\s*(?:-|–|—|to)\s*{_NUM}")
ORDINAL_WORD_FIRST_BOUND_PATTERN = re.compile(
    rf"(?:under|less than|fewer than|below|over|more than|greater than|at least|above)\s+{_NUM}",
    re.IGNORECASE,
)
ORDINAL_NUMBER_FIRST_BOUND_PATTERN = re.compile(
    rf"{_NUM}\s*(?:\+|or more|or older|or higher|or above|or greater|and (?:up|above|older))",
    re.IGNORECASE,
)


def parse_ordinal_bucket_value(value: Any) -> float | None:
    """Extract a representative number from a bucketed-range string, or None.

    Dataset-general and reference-data-free by design (RANKING_AND_SIMILARITY_
    POSITION.md Sec 2.3): a range like "18-24 years old" becomes its midpoint
    (21.0); a single-bound string like "Under 18 years old", "Over 12 hours",
    or "30 or more years" becomes that one bound. Deliberately strict about
    what counts as a range (see the patterns above) -- and intentionally does
    not cover purely verbal orderings with no digits at all ("Some college" <
    "Bachelor's" < "Master's"), since inferring that order would require an
    external education-level reference table, which is exactly the per-domain
    hand-tuning this approach is meant to avoid. Both gaps are documented,
    known limitations, not silently patched over.
    """
    if sg.is_missing_value(value):
        return None
    text = str(value).replace(",", "")

    range_match = ORDINAL_RANGE_PATTERN.search(text)
    if range_match:
        low, high = float(range_match.group(1)), float(range_match.group(2))
        return (low + high) / 2.0

    word_first = ORDINAL_WORD_FIRST_BOUND_PATTERN.search(text)
    if word_first:
        return float(word_first.group(1))

    number_first = ORDINAL_NUMBER_FIRST_BOUND_PATTERN.search(text)
    if number_first:
        return float(number_first.group(1))

    return None


def ordinal_eligible_columns(
    columns: list[str],
    frame: pd.DataFrame,
    profile_map: dict[str, dict],
) -> list[str]:
    """Which categorical columns should use ordinal (bucketed-numeric) distance
    instead of exact-match equality.

    Three gates:
    1. Role gate: only plain `categorical` columns -- binary categories have no
       meaningful ordinal distance beyond equality, and numeric-code categories
       already have their own treatment.
    2. Every distinct present value must parse via parse_ordinal_bucket_value.
       Deliberately the strictest possible bar (no partial-match fraction, no
       hardcoded "80% must parse" cutoff) -- a single non-numeric stray value
       ("Prefer not to say") disqualifies the whole column. This trades missing
       some real-world columns with one outlier category for zero risk of
       treating a column that merely happens to contain a few numbers (an ID
       fragment, a product code) as if it were a genuine ordinal scale.
    3. Cardinality gate: distinct present values must be fewer than non-missing
       rows -- i.e. at least one value must repeat. A genuine bucket scheme
       ("0-2 years", "3-5 years", ...) is repeated across many rows by
       definition; a column where every row's value is unique (a ticket number,
       an auto-incrementing ID with an embedded digit, a per-row label like
       "Job 14") would otherwise parse cleanly too and get mistaken for an
       ordinal scale purely because it contains numbers. Caught live: a test
       fixture using "developer 0".."developer 39" (one distinct value per
       row) tripped exactly this false positive before this gate existed.
    """
    eligible = []
    for column in columns:
        if profile_map.get(column, {}).get("role") != "categorical":
            continue
        series = frame[column]
        non_missing = series[~series.map(sg.is_missing_value)]
        distinct_values = non_missing.map(sg.format_group_value).unique()
        if len(distinct_values) < 2:
            continue
        if len(distinct_values) >= len(non_missing):
            continue
        parsed = [parse_ordinal_bucket_value(value) for value in distinct_values]
        if any(value is None for value in parsed):
            continue
        if len(set(parsed)) < 2:
            continue
        eligible.append(column)
    return eligible


def ordinal_numeric_frame(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """A copy of frame with ordinal columns replaced by their parsed numeric
    representative, so they can flow through build_weighted_numeric_matrix
    unchanged instead of needing a second, parallel numeric pipeline.
    """
    if not columns:
        return frame
    ordinal_frame = frame.copy()
    for column in columns:
        ordinal_frame[column] = frame[column].map(parse_ordinal_bucket_value)
    return ordinal_frame


def build_weighted_numeric_matrix(
    frame: pd.DataFrame,
    columns: list[str],
    profile_map: dict[str, dict],
) -> tuple[np.ndarray, list[str]]:
    features = []
    names = []
    for column in columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.nunique(dropna=True) < 2:
            continue
        median = values.median()
        scale = values.quantile(0.75) - values.quantile(0.25)
        if pd.isna(scale) or scale == 0:
            scale = values.std()
        if pd.isna(scale) or scale == 0:
            continue
        weight = max(np.finfo(float).eps, profile_map[column]["confidence"])
        standardized = (values.fillna(median) - median) / scale
        clip_bound = agp.adaptive_clip_bound(standardized)
        scaled = (standardized.clip(-clip_bound, clip_bound) / clip_bound) * weight
        features.append(scaled.to_numpy(dtype=float))
        names.append(column)
        if values.isna().any():
            features.append(values.isna().astype(float).to_numpy() * weight)
            names.append(f"{column}:missing")
    if not features:
        return np.zeros((len(frame), 0), dtype=float), []
    return np.vstack(features).T, names


def build_weighted_text_matrix(
    frame: pd.DataFrame,
    columns: list[str],
    profile_map: dict[str, dict],
    *,
    free_text: bool,
) -> tuple[np.ndarray, list[str]]:
    documents = build_column_aware_documents(frame, columns, free_text=free_text)
    matrix, terms = sg.build_tfidf_matrix(documents)
    if matrix.size == 0:
        return matrix, terms
    prefixes = {column_token(column): profile_map[column]["confidence"] for column in columns}
    observed_confidences = [value for value in prefixes.values() if math.isfinite(value)]
    fallback_confidence = float(np.median(observed_confidences)) if observed_confidences else 1.0
    weights = []
    for term in terms:
        prefix = term.split("__", 1)[0]
        confidence = prefixes.get(prefix, fallback_confidence)
        weights.append(max(np.finfo(float).eps, confidence))
    return matrix * np.asarray(weights, dtype=float), terms


def build_column_aware_documents(
    frame: pd.DataFrame,
    columns: list[str],
    *,
    free_text: bool,
) -> list[list[str]]:
    token_limits: dict[str, int] = {}
    repeated_values: dict[str, set[str]] = {}
    for column in columns:
        tokenized = [sg.tokenize(value) for value in frame[column].tolist() if not sg.is_missing_value(value)]
        token_limits[column] = agp.adaptive_token_limit(
            (len(tokens) for tokens in tokenized),
            safety_cap=TEXT_TOKEN_SAFETY_CAP,
        )
        normalized = frame[column].map(
            lambda value: "" if sg.is_missing_value(value) else "_".join(sg.tokenize(value))
        )
        repeated_values[column] = set(
            normalized[normalized.ne("")].value_counts().loc[lambda counts: counts > 1].index.tolist()
        )

    documents = []
    for _, row in frame.iterrows():
        tokens = []
        for column in columns:
            prefix = column_token(column)
            value = row[column]
            if sg.is_missing_value(value):
                tokens.append(f"{prefix}__missing")
                continue
            value_tokens = sg.tokenize(value)
            token_limit = token_limits[column]
            tokens.extend(f"{prefix}__{token}" for token in value_tokens[:token_limit])
            compound = "_".join(value_tokens)
            if not free_text and compound in repeated_values[column]:
                tokens.append(f"{prefix}__{compound}")
        documents.append(tokens)
    return documents


def build_lifecycle_matrix(
    frame: pd.DataFrame,
    columns: list[str],
    profile_map: dict[str, dict],
) -> tuple[np.ndarray, dict]:
    temporal = [column for column in columns if profile_map[column]["role"] in TEMPORAL_ROLES]
    status = [column for column in columns if column not in temporal]
    features = []
    names = []
    parsed = {}
    for column in temporal:
        values = pd.to_datetime(frame[column], errors="coerce", format="mixed", utc=True)
        if values.nunique(dropna=True) < 2:
            continue
        parsed[column] = values
        weight = max(np.finfo(float).eps, profile_map[column]["confidence"])
        seconds = values.map(lambda value: value.timestamp() if pd.notna(value) else np.nan)
        median = seconds.median()
        scale = seconds.quantile(0.75) - seconds.quantile(0.25)
        if pd.isna(scale) or scale == 0:
            scale = seconds.std() or 1.0
        standardized = (seconds.fillna(median) - median) / scale
        clip_bound = agp.adaptive_clip_bound(standardized)
        features.append((standardized.clip(-clip_bound, clip_bound) / clip_bound).to_numpy() * weight)
        names.append(column)
        for label, values_part, period in (
            ("month", values.dt.month.fillna(1), 12),
            ("weekday", values.dt.weekday.fillna(0), 7),
            ("hour", values.dt.hour.fillna(0), 24),
        ):
            angle = 2 * math.pi * values_part.to_numpy(dtype=float) / period
            features.extend([np.sin(angle) * weight, np.cos(angle) * weight])
            names.extend([f"{column}:{label}:sin", f"{column}:{label}:cos"])
        features.append(values.isna().astype(float).to_numpy() * weight)
        names.append(f"{column}:missing")

    duration_candidates = []
    for first, second in combinations(parsed, 2):
        duration = (parsed[second] - parsed[first]).dt.total_seconds() / 86400.0
        if duration.nunique(dropna=True) < 2:
            continue
        coverage = float(duration.notna().mean())
        variation = int(duration.nunique(dropna=True))
        evidence_score = coverage * math.log1p(variation)
        duration_candidates.append((evidence_score, first, second, duration))

    score_cutoff = agp.natural_break_threshold(candidate[0] for candidate in duration_candidates)
    selected_durations = [
        candidate
        for candidate in duration_candidates
        if score_cutoff is None or candidate[0] >= score_cutoff
    ]
    duration_budget = max(1, int(math.ceil(math.sqrt(max(1, len(frame))))))
    selected_durations = sorted(
        selected_durations,
        key=lambda candidate: candidate[0],
        reverse=True,
    )[:duration_budget]

    duration_labels = []
    for _score, first, second, duration in selected_durations:
        median = duration.median()
        scale = duration.quantile(0.75) - duration.quantile(0.25)
        if pd.isna(scale) or scale == 0:
            scale = duration.std() or 1.0
        standardized = (duration.fillna(median) - median) / scale
        clip_bound = agp.adaptive_clip_bound(standardized)
        confidence_weight = math.sqrt(
            max(np.finfo(float).eps, profile_map[first]["confidence"])
            * max(np.finfo(float).eps, profile_map[second]["confidence"])
        )
        features.append(
            (standardized.clip(-clip_bound, clip_bound) / clip_bound).to_numpy()
            * confidence_weight
        )
        label = f"{first} to {second} days"
        names.append(label)
        duration_labels.append((first, second, duration))

    temporal_matrix = np.vstack(features).T if features else np.zeros((len(frame), 0), dtype=float)
    status_matrix, terms = build_weighted_text_matrix(frame, status, profile_map, free_text=False)
    matrix = combine_and_normalize(temporal_matrix, status_matrix, len(frame))
    info = feature_metadata(frame, names, terms, status_matrix)
    info["parsed_dates"] = parsed
    info["durations"] = duration_labels
    info["duration_pair_candidates"] = len(duration_candidates)
    info["duration_pair_score_cutoff"] = score_cutoff
    return matrix, info


def project_lat_lon_to_unit_sphere(lat_radians: pd.Series, lon_radians: pd.Series) -> tuple[list[np.ndarray], np.ndarray]:
    """x/y/z unit-sphere coordinates plus a missing-value mask, shared by
    real coordinate-pair columns and reference-table-derived country
    centroids so both use the exact same distance geometry.
    """
    valid = lat_radians.notna() & lon_radians.notna()
    lat = lat_radians.fillna(lat_radians[valid].median() if valid.any() else 0.0)
    lon = lon_radians.fillna(lon_radians[valid].median() if valid.any() else 0.0)
    return [
        np.cos(lat) * np.cos(lon),
        np.cos(lat) * np.sin(lon),
        np.sin(lat),
        (~valid).astype(float),
    ], valid.to_numpy()


def build_geography_matrix(
    frame: pd.DataFrame,
    columns: list[str],
    profile_map: dict[str, dict],
    *,
    country_resolver=geo_ref.country_centroid,
    city_resolver=geo_ref.city_centroid,
) -> tuple[np.ndarray, dict]:
    # country_resolver/city_resolver are injectable so tests never need to
    # load the real ~13s-on-first-call geonamescache/pycountry reference data
    # (see geography_reference.py) -- same reasoning as build_embedding_
    # matrix's embedder parameter.
    coordinate_columns = [
        column for column in columns if profile_map[column]["role"] == "geographic_coordinate"
    ]
    location_columns = [column for column in columns if column not in coordinate_columns]

    # Location-name columns (e.g. "Country") that clear the reference-table
    # gate use real spherical distance via a looked-up capital-city
    # coordinate instead of exact-match tokens -- replace, not add, same
    # principle as every other feature swap in this file. Tried first,
    # before city-level matching below, since country resolution is
    # unambiguous (no name collisions) while city resolution needs
    # disambiguation.
    geography_name_columns = geo_ref.geography_name_eligible_columns(
        location_columns, frame, profile_map, resolver=country_resolver,
    )
    location_columns = [column for column in location_columns if column not in geography_name_columns]

    # City-name columns that failed the country-level gate above (because
    # their values are city names, not country names) get a second try at
    # real spherical distance, disambiguating name collisions ("Springfield",
    # "San Jose") via a companion country/region column in the same row
    # where one exists, and population as a last resort otherwise -- see
    # geography_reference.py's module docstring and city_centroid.
    city_context_column = _pick_city_context_column(
        columns, profile_map, set(geography_name_columns),
    )
    city_name_columns = geo_ref.city_name_eligible_columns(
        location_columns, frame, profile_map,
        context_column=city_context_column, resolver=city_resolver,
    )
    location_columns = [column for column in location_columns if column not in city_name_columns]

    latitudes = [column for column in coordinate_columns if "lat" in str(column).lower()]
    longitudes = [column for column in coordinate_columns if re.search(r"lon|lng|long", str(column), re.I)]
    features = []
    names = []
    coordinate_pairs = match_coordinate_pairs(latitudes, longitudes)
    for latitude, longitude in coordinate_pairs:
        lat = np.radians(pd.to_numeric(frame[latitude], errors="coerce"))
        lon = np.radians(pd.to_numeric(frame[longitude], errors="coerce"))
        projected, _valid = project_lat_lon_to_unit_sphere(lat, lon)
        features.extend(projected)
        names.extend(["geo:x", "geo:y", "geo:z", "geo:missing"])

    geography_centroids_by_column: dict[str, dict[str, tuple[float, float]]] = {}
    for column in geography_name_columns:
        value_cache: dict[str, tuple[float, float] | None] = {}
        row_lats: list[float] = []
        row_lons: list[float] = []
        for raw_value in frame[column].tolist():
            if sg.is_missing_value(raw_value):
                row_lats.append(np.nan)
                row_lons.append(np.nan)
                continue
            key = sg.format_group_value(raw_value)
            if key not in value_cache:
                value_cache[key] = country_resolver(key)
            centroid = value_cache[key]
            row_lats.append(centroid[0] if centroid else np.nan)
            row_lons.append(centroid[1] if centroid else np.nan)
        lat = np.radians(pd.Series(row_lats, index=frame.index))
        lon = np.radians(pd.Series(row_lons, index=frame.index))
        projected, _valid = project_lat_lon_to_unit_sphere(lat, lon)
        features.extend(projected)
        names.extend([f"{column}:geo:x", f"{column}:geo:y", f"{column}:geo:z", f"{column}:geo:missing"])
        geography_centroids_by_column[column] = {
            value: centroid for value, centroid in value_cache.items() if centroid is not None
        }

    # City-name columns follow the same feature-building shape as the
    # country-name loop above, but the resolver takes a per-row context hint
    # (the companion country/region value in city_context_column, if any),
    # so the cache key and lookup loop are per-row rather than per-distinct-
    # value -- the same city string can legitimately resolve to a different
    # coordinate on a different row when paired with a different country.
    for column in city_name_columns:
        value_cache: dict[tuple[str, str | None], tuple[float, float] | None] = {}
        row_lats = []
        row_lons = []
        context_series = frame[city_context_column] if city_context_column is not None else None
        for index in frame.index:
            raw_value = frame.at[index, column]
            if sg.is_missing_value(raw_value):
                row_lats.append(np.nan)
                row_lons.append(np.nan)
                continue
            key = sg.format_group_value(raw_value)
            hint = None
            if context_series is not None and not sg.is_missing_value(context_series[index]):
                hint = sg.format_group_value(context_series[index])
            cache_key = (key, hint)
            if cache_key not in value_cache:
                value_cache[cache_key] = city_resolver(key, hint)
            centroid = value_cache[cache_key]
            row_lats.append(centroid[0] if centroid else np.nan)
            row_lons.append(centroid[1] if centroid else np.nan)
        lat = np.radians(pd.Series(row_lats, index=frame.index))
        lon = np.radians(pd.Series(row_lons, index=frame.index))
        projected, _valid = project_lat_lon_to_unit_sphere(lat, lon)
        features.extend(projected)
        names.extend([f"{column}:geo:x", f"{column}:geo:y", f"{column}:geo:z", f"{column}:geo:missing"])
        # Keyed by the plain city string, same shape as the country loop's
        # cache, so geography_name_description_candidate's lookup-by-value
        # works unchanged for city columns too. When the same city string
        # resolved differently under different row contexts, the first
        # resolution seen wins -- a description-only display concern, not a
        # per-row feature accuracy one (the actual feature vector above
        # already used each row's own context-aware coordinate).
        column_centroids: dict[str, tuple[float, float]] = {}
        for (value, _hint), centroid in value_cache.items():
            if centroid is not None:
                column_centroids.setdefault(value, centroid)
        geography_centroids_by_column[column] = column_centroids

    remaining_coordinates = [
        column for column in coordinate_columns
        if all(column not in pair for pair in coordinate_pairs)
    ]
    numeric, numeric_names = build_weighted_numeric_matrix(frame, remaining_coordinates, profile_map)
    if numeric.size:
        features.extend(numeric.T)
        names.extend(numeric_names)
    coordinate_matrix = np.vstack(features).T if features else np.zeros((len(frame), 0), dtype=float)
    text, terms = build_weighted_text_matrix(frame, location_columns, profile_map, free_text=False)
    matrix = combine_and_normalize(coordinate_matrix, text, len(frame))
    info = feature_metadata(frame, names, terms, text)
    info["coordinate_pairs"] = coordinate_pairs
    if geography_name_columns or city_name_columns:
        info["geographyNameColumns"] = geography_name_columns + city_name_columns
        info["geographyCentroidsByColumn"] = geography_centroids_by_column
    if city_name_columns:
        info["cityNameColumns"] = city_name_columns
        info["cityContextColumn"] = city_context_column
    return matrix, info


def match_coordinate_pairs(latitudes: list[str], longitudes: list[str]) -> list[tuple[str, str]]:
    """Match every coordinate pair by its column-name context, not list order."""
    available = set(longitudes)
    pairs = []
    for latitude in latitudes:
        latitude_stem = coordinate_stem(latitude)
        same_context = [
            longitude for longitude in available
            if coordinate_stem(longitude) == latitude_stem
        ]
        candidates = same_context or sorted(available)
        if not candidates:
            break
        longitude = candidates[0]
        available.remove(longitude)
        pairs.append((latitude, longitude))
    return pairs


def coordinate_stem(column: str) -> str:
    tokens = [
        token for token in sg.tokenize(column)
        if token not in {"lat", "latitude", "lon", "lng", "long", "longitude"}
    ]
    return "_".join(tokens)


def combine_and_normalize(first: np.ndarray, second: np.ndarray, rows: int) -> np.ndarray:
    return combine_many_and_normalize([first, second], rows)


def combine_many_and_normalize(parts: list[np.ndarray], rows: int) -> np.ndarray:
    parts = [part for part in parts if part.size]
    matrix = np.hstack(parts) if parts else np.zeros((rows, 0), dtype=float)
    return sg.l2_normalize(np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0))


def feature_metadata(
    frame: pd.DataFrame,
    numeric_names: list[str],
    terms: list[str],
    text_matrix: np.ndarray,
) -> dict[str, Any]:
    return {
        "numeric_columns": numeric_names,
        "terms": terms,
        "text_matrix": text_matrix,
        "row_positions": {int(row_id): index for index, row_id in enumerate(frame["ID"].tolist())},
    }


def run_internal_clustering(
    matrix: np.ndarray,
    *,
    min_group_size: int | None,
) -> tuple[np.ndarray, np.ndarray, str, dict[str, Any]]:
    """Select K and algorithm from repeated-run evidence on this matrix.

    Every clustering decision below (which k, which algorithm) is made on the
    matrix's DISTINCT rows, not the full row-multiplicity matrix. Caught live
    on a duplicate-dense synthetic dataset (documented in ADAPTIVE_DECISION_
    POLICY.md): a numerically-dominant near-duplicate-dense majority distorts
    every diagnostic that depends on point density or repetition count --
    K-means' k-selection scoring (distinctiveness/balance measured across the
    full row population let thousands of identical points outweigh a smaller,
    genuinely distinct minority cluster) and DBSCAN's epsilon selection (many
    zero-distance duplicate pairs skew the k-neighbor-distance "knee" toward
    an artificially tiny eps, over-fragmenting everything). Deduplicating
    first fixes both: a data point repeated 400 times and a data point that
    appears once are structurally different information for "how many
    distinct kinds of rows exist", and only the shape of the distinct-row
    population should drive that decision. This is unconditional, not gated
    by a duplication-density threshold -- on a dataset with no duplicate rows
    it is a pure no-op (every row is already its own unique row), so it only
    changes behavior exactly where duplication is actually present. Labels
    are expanded back to one entry per original row before being returned, so
    every downstream consumer (groups_from_partition, row counts,
    min_group_size filtering) is completely unaffected by this and needs no
    changes of its own.
    """
    n_rows = len(matrix)
    unique_matrix, inverse_indices = np.unique(matrix, axis=0, return_inverse=True)
    inverse_indices = inverse_indices.ravel()
    unique_rows = unique_matrix.shape[0]
    k_values = agp.adaptive_k_candidates(n_rows, unique_rows, min_group_size)
    kmeans_records = []
    for k in k_values:
        if k < 2:
            continue
        unique_labels = sg.kmeans(unique_matrix, k, random_seed=42)
        unique_alternate = sg.kmeans(unique_matrix, k, random_seed=137)
        diagnostics = agp.partition_diagnostics(unique_matrix, unique_labels, unique_alternate)
        labels = unique_labels[inverse_indices]
        alternate = unique_alternate[inverse_indices]
        kmeans_records.append(partition_record("kmeans", k, labels, alternate, diagnostics))

    if not kmeans_records:
        labels = np.zeros(n_rows, dtype=int)
        diagnostics = {
            "kCandidates": k_values,
            "algorithmCandidates": [],
            "selection": {"reason": "fewer than two unique feature rows"},
        }
        return labels, labels.copy(), "Single group", diagnostics

    k_score_cutoff = agp.natural_break_threshold(
        record["diagnostics"].score for record in kmeans_records
    )
    competitive_k = [
        record for record in kmeans_records
        if k_score_cutoff is None or record["diagnostics"].score >= k_score_cutoff
    ]
    k_separation = agp.score_separation(
        record["diagnostics"].score for record in kmeans_records
    )
    if k_separation["separated"]:
        selected_kmeans = max(competitive_k, key=lambda record: record["diagnostics"].score)
    else:
        conservative_pool = competitive_k if len(kmeans_records) >= 3 else kmeans_records
        selected_kmeans = min(
            conservative_pool,
            key=lambda record: (record["k"], -record["diagnostics"].score),
        )

    selected_k = int(selected_kmeans["k"])
    algorithm_records = [selected_kmeans]
    perturbed_unique = adaptive_perturbation(unique_matrix)

    estimated_pairwise_bytes = unique_rows * unique_rows * np.dtype(float).itemsize
    if selected_k >= 2 and estimated_pairwise_bytes <= AGGLOMERATIVE_MEMORY_BUDGET_BYTES:
        unique_labels = AgglomerativeClustering(
            n_clusters=selected_k,
            metric="euclidean",
            linkage="average",
        ).fit_predict(unique_matrix)
        unique_alternate = AgglomerativeClustering(
            n_clusters=selected_k,
            metric="euclidean",
            linkage="average",
        ).fit_predict(perturbed_unique)
        diagnostics = agp.partition_diagnostics(unique_matrix, unique_labels, unique_alternate)
        labels = unique_labels[inverse_indices]
        alternate = unique_alternate[inverse_indices]
        algorithm_records.append(
            partition_record("agglomerative", selected_k, labels, alternate, diagnostics)
        )

    dbscan_record = adaptive_dbscan_record(
        unique_matrix, perturbed_unique, min_group_size, inverse_indices=inverse_indices,
    )
    if dbscan_record is not None:
        algorithm_records.append(dbscan_record)

    algorithm_separation = agp.score_separation(
        record["diagnostics"].score for record in algorithm_records
    )
    best_record = max(algorithm_records, key=lambda record: record["diagnostics"].score)
    if algorithm_separation["separated"]:
        selected = best_record
        selection_reason = "top candidate is naturally separated from the runner-up"
    else:
        selected = selected_kmeans
        selection_reason = "candidate scores overlap; retain the simpler deterministic K-means result"

    diagnostics = {
        "kCandidates": [
            serializable_partition_record(record) for record in kmeans_records
        ],
        "kScoreCutoff": k_score_cutoff,
        "kScoreSeparation": k_separation,
        "algorithmCandidates": [
            serializable_partition_record(record) for record in algorithm_records
        ],
        "algorithmScoreSeparation": algorithm_separation,
        "selection": {
            "algorithm": selected["algorithm"],
            "clusterCount": selected["diagnostics"].cluster_count,
            "reason": selection_reason,
        },
        "agglomerativeResourceGuard": {
            "estimatedPairwiseBytes": estimated_pairwise_bytes,
            "budgetBytes": AGGLOMERATIVE_MEMORY_BUDGET_BYTES,
            "eligible": estimated_pairwise_bytes <= AGGLOMERATIVE_MEMORY_BUDGET_BYTES,
        },
    }
    label = selected["algorithmLabel"]
    return selected["labels"], selected["alternate"], label, diagnostics


def partition_record(
    algorithm: str,
    k: int | None,
    labels: np.ndarray,
    alternate: np.ndarray,
    diagnostics: agp.PartitionDiagnostics,
    *,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if algorithm == "kmeans":
        algorithm_label = f"K-means (adaptive k={k})"
    elif algorithm == "agglomerative":
        algorithm_label = f"Agglomerative (adaptive k={k})"
    else:
        eps = (parameters or {}).get("eps")
        algorithm_label = f"DBSCAN (distance-knee eps={eps:.4g})"
    return {
        "algorithm": algorithm,
        "algorithmLabel": algorithm_label,
        "k": k,
        "labels": np.asarray(labels),
        "alternate": np.asarray(alternate),
        "diagnostics": diagnostics,
        "parameters": parameters or {},
    }


def serializable_partition_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "algorithm": record["algorithm"],
        "clusterCount": record["diagnostics"].cluster_count,
        "parameters": record["parameters"],
        **record["diagnostics"].to_dict(),
    }


def adaptive_dbscan_record(
    matrix: np.ndarray,
    perturbed: np.ndarray,
    min_group_size: int,
    *,
    inverse_indices: np.ndarray | None = None,
) -> dict[str, Any] | None:
    """matrix/perturbed are expected to already be deduplicated (see
    run_internal_clustering) -- DBSCAN's epsilon is chosen from k-nearest-
    neighbor distances, and duplicate rows contribute zero-distance pairs
    that skew that "knee" toward an artificially tiny eps. inverse_indices
    (from np.unique(..., return_inverse=True) on the original matrix) expands
    the resulting labels back to one entry per original row before they are
    returned; diagnostics are computed on the deduplicated labels, matching
    every other algorithm's diagnostics in run_internal_clustering.
    """
    n_rows = len(matrix)
    if n_rows < 3:
        return None
    min_samples = min(n_rows - 1, max(2, int(min_group_size)))
    neighbors = NearestNeighbors(
        n_neighbors=min_samples,
        metric="cosine",
        n_jobs=1,
    ).fit(matrix)
    distances, _indices = neighbors.kneighbors(matrix)
    eps = distance_knee(distances[:, -1])
    if eps is None or eps <= 0:
        return None
    unique_labels = DBSCAN(eps=eps, min_samples=min_samples, metric="cosine", n_jobs=1).fit_predict(matrix)
    unique_alternate = DBSCAN(eps=eps, min_samples=min_samples, metric="cosine", n_jobs=1).fit_predict(perturbed)
    diagnostics = agp.partition_diagnostics(matrix, unique_labels, unique_alternate)
    if diagnostics.cluster_count < 2:
        return None
    labels = unique_labels[inverse_indices] if inverse_indices is not None else unique_labels
    alternate = unique_alternate[inverse_indices] if inverse_indices is not None else unique_alternate
    return partition_record(
        "dbscan",
        None,
        labels,
        alternate,
        diagnostics,
        parameters={"eps": float(eps), "minSamples": int(min_samples)},
    )


def distance_knee(distances: np.ndarray) -> float | None:
    values = np.sort(agp.finite_values(distances))
    positive = values[values > 0]
    if positive.size == 0:
        return None
    if positive.size < 3 or positive[-1] == positive[0]:
        return float(np.median(positive))
    x = np.linspace(0.0, 1.0, len(positive))
    y = (positive - positive[0]) / (positive[-1] - positive[0])
    reference_line = x
    knee_index = int(np.argmax(reference_line - y))
    return float(positive[knee_index])


def deterministic_perturbation(matrix: np.ndarray) -> np.ndarray:
    """Compatibility name for the new data-scaled perturbation."""
    return adaptive_perturbation(matrix)


def adaptive_perturbation(matrix: np.ndarray) -> np.ndarray:
    rng = np.random.default_rng(20260717)
    if len(matrix) < 2:
        return matrix.copy()
    neighbors = NearestNeighbors(
        n_neighbors=min(2, len(matrix)),
        metric="euclidean",
        n_jobs=1,
    ).fit(matrix)
    distances, _indices = neighbors.kneighbors(matrix)
    local_distances = distances[:, -1]
    positive = local_distances[local_distances > 0]
    local_scale = float(np.median(positive)) if len(positive) else np.finfo(float).eps
    sigma = local_scale / math.sqrt(max(1, matrix.shape[1]))
    perturbed = matrix + rng.normal(0.0, sigma, matrix.shape)
    return sg.l2_normalize(perturbed)


def groups_from_partition(
    frame: pd.DataFrame,
    error_df: pd.DataFrame,
    *,
    view: str,
    columns: list[str],
    profile_map: dict[str, dict],
    matrix: np.ndarray,
    feature_info: dict,
    labels: np.ndarray,
    alternate_labels: np.ndarray,
    algorithm: str,
    baseline_error_rate: float,
    total_error_rows: int,
    min_group_size: int,
) -> list[MultiViewGroup]:
    groups = []
    # See generate_duplicate_candidates for why this is shared across every
    # make_group() call below instead of rebuilt per cluster label.
    baseline_cache: dict[str, Any] = {}
    for label in sorted(set(np.asarray(labels).tolist())):
        if label == -1:
            continue
        positions = np.flatnonzero(labels == label)
        if len(positions) < min_group_size:
            continue
        coverage = len(positions) / len(frame)
        if coverage >= 1.0:
            continue
        rows = frame.iloc[positions]
        stability = matched_group_jaccard(positions, alternate_labels)
        coherence = group_coherence(matrix, positions)
        distinctiveness = group_distinctiveness(matrix, labels, label, positions)
        highlights = describe_view_group(rows, frame, view, columns, profile_map, feature_info)
        representative_positions, contradictory_positions = select_group_example_positions(
            matrix,
            positions,
        )
        explainability = min(1.0, len(highlights) / max(1.0, math.sqrt(len(columns))))
        profile_confidence = mean_profile_confidence(columns, profile_map)
        group = make_group(
            rows,
            frame,
            error_df,
            view=view,
            group_name=f"cluster_{label}",
            algorithm=algorithm,
            columns=columns,
            profile_confidence=profile_confidence,
            stability=stability,
            coherence=coherence,
            distinctiveness=distinctiveness,
            explainability=explainability,
            feature_highlights=highlights,
            baseline_error_rate=baseline_error_rate,
            total_error_rows=total_error_rows,
            profile_map=profile_map,
            feature_info=feature_info,
            representative_positions=representative_positions,
            contradictory_positions=contradictory_positions,
            baseline_cache=baseline_cache,
        )
        groups.append(group)
    return groups


def generate_quality_candidates(
    frame: pd.DataFrame,
    error_df: pd.DataFrame,
    *,
    columns: list[str],
    profile_map: dict[str, dict],
    baseline_error_rate: float,
    total_error_rows: int,
    min_group_size: int | None,
) -> tuple[list[MultiViewGroup], dict]:
    signatures: dict[int, set[str]] = defaultdict(set)
    for record in error_df.itertuples(index=False):
        signatures[int(record.row_id)].add(f"{record.error_type} in {record.column_id}")
    for column in columns:
        missing = frame[column].map(sg.is_missing_value)
        for row_id in frame.loc[missing, "ID"].tolist():
            signatures[int(row_id)].add(f"missing in {column}")
    grouped: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for index, row_id in enumerate(frame["ID"].tolist()):
        signature = tuple(sorted(signatures.get(int(row_id), set())))
        if signature:
            grouped[signature].append(index)

    observed_sizes = [len(positions) for positions in grouped.values()]
    effective_min_group_size = (
        max(2, int(min_group_size))
        if min_group_size is not None
        else agp.adaptive_observed_group_support(observed_sizes, len(frame))
    )
    coverage_fence = agp.robust_upper_fence(
        len(positions) / len(frame) for positions in grouped.values()
    )
    groups = []
    for number, (signature, positions) in enumerate(
        sorted(grouped.items(), key=lambda item: len(item[1]), reverse=True)
    ):
        coverage = len(positions) / len(frame)
        if len(positions) < effective_min_group_size or coverage >= 1.0:
            continue
        if coverage_fence is not None and coverage > coverage_fence:
            continue
        rows = frame.iloc[positions]
        highlights = list(signature[:4])
        relevant_columns = sorted({item.rsplit(" in ", 1)[-1] for item in signature})
        groups.append(make_group(
            rows,
            frame,
            error_df,
            view="quality",
            group_name=f"quality_signature_{number}",
            algorithm="Exact quality signature",
            columns=relevant_columns,
            profile_confidence=mean_profile_confidence(relevant_columns, profile_map),
            stability=1.0,
            coherence=1.0,
            distinctiveness=1.0,
            explainability=1.0,
            feature_highlights=highlights,
            baseline_error_rate=baseline_error_rate,
            total_error_rows=total_error_rows,
            profile_map=profile_map,
            representative_positions=list(positions[:REPRESENTATIVE_EXAMPLE_CAP]),
        ))
    return groups, view_run(
        "quality",
        "ready" if groups else "no_useful_groups",
        "Exact quality signatures",
        len(groups),
        "" if groups else "No recurring quality signature met the data-derived support rule.",
        diagnostics={
            "effectiveMinGroupSize": effective_min_group_size,
            "supportSource": "natural break in observed quality-signature sizes",
            "coverageUpperFence": coverage_fence,
        },
    )


def generate_duplicate_candidates(
    frame: pd.DataFrame,
    error_df: pd.DataFrame,
    *,
    columns: list[str],
    profile_map: dict[str, dict],
    baseline_error_rate: float,
    total_error_rows: int,
) -> tuple[list[MultiViewGroup], dict]:
    if not columns:
        return [], view_run("duplicates", "unavailable", "none", 0, "No safe comparison columns remain after key exclusion.")
    signatures = normalized_duplicate_signatures(frame, columns, profile_map)
    grouped: dict[tuple, list[int]] = defaultdict(list)
    for position, signature in enumerate(signatures):
        if signature:
            grouped[signature].append(position)
    repeated_groups = sorted(
        (values for values in grouped.values() if len(values) >= 2),
        key=len,
        reverse=True,
    )
    coverage_fence = agp.robust_upper_fence(
        len(positions) / len(frame) for positions in repeated_groups
    )
    groups = []
    # Shared across every candidate below: the full-sample baseline for a given
    # column is identical regardless of which candidate is asking, so computing
    # it once here instead of once per make_group() call turns an O(candidates x
    # sample_rows) cost into O(sample_rows) -- see cached_full_frame_categorical_values.
    baseline_cache: dict[str, Any] = {}
    for number, positions in enumerate(repeated_groups):
        coverage = len(positions) / len(frame)
        if coverage >= 1.0:
            continue
        if coverage_fence is not None and coverage > coverage_fence:
            continue
        rows = frame.iloc[positions]
        examples = [column for column in columns if rows[column].astype(str).nunique(dropna=False) == 1][:4]
        highlights = (
            ["matching fields: " + ", ".join(examples)]
            if examples
            else [f"same normalized values across {len(columns)} compared columns"]
        )
        groups.append(make_group(
            rows,
            frame,
            error_df,
            view="duplicates",
            group_name=f"duplicate_signature_{number}",
            algorithm="Profiler-guided normalized signature",
            columns=columns,
            profile_confidence=mean_profile_confidence(columns, profile_map),
            stability=1.0,
            coherence=1.0,
            distinctiveness=1.0,
            explainability=1.0,
            feature_highlights=highlights,
            baseline_error_rate=baseline_error_rate,
            total_error_rows=total_error_rows,
            profile_map=profile_map,
            representative_positions=list(positions[:REPRESENTATIVE_EXAMPLE_CAP]),
            baseline_cache=baseline_cache,
        ))
    return groups, view_run(
        "duplicates",
        "ready" if groups else "no_useful_groups",
        "Normalized duplicate signatures",
        len(groups),
        "" if groups else "No repeated non-key signatures were found in the sample.",
        diagnostics={
            "coverageUpperFence": coverage_fence,
            "supportSource": "repeated signatures with robust coverage outlier removal",
        },
    )


def normalized_duplicate_signatures(
    frame: pd.DataFrame,
    columns: list[str],
    profile_map: dict[str, dict],
) -> list[tuple]:
    normalized_columns = []
    for column in columns:
        if profile_map[column]["family"] == "numeric":
            values = pd.to_numeric(frame[column], errors="coerce")
            scale = values.quantile(0.75) - values.quantile(0.25)
            scale = float(scale) if pd.notna(scale) and scale != 0 else float(values.std() or 1.0)
            standardized = (values - values.median()) / scale
            valid = standardized.dropna()
            if len(valid) > 1:
                standardized_iqr = valid.quantile(0.75) - valid.quantile(0.25)
                bin_width = (2.0 * standardized_iqr) / np.cbrt(len(valid))
            else:
                bin_width = math.nan
            if pd.isna(bin_width) or bin_width <= 0:
                normalized = standardized
            else:
                normalized = (standardized / bin_width).round() * bin_width
            normalized_columns.append(normalized.map(lambda value: None if pd.isna(value) else float(value)))
        else:
            normalized_columns.append(
                frame[column].map(lambda value: normalize_duplicate_value(value))
            )
    raw_signatures = [
        tuple(column.iloc[position] for column in normalized_columns)
        for position in range(len(frame))
    ]
    non_missing_counts = [
        sum(value not in {None, ""} for value in signature)
        for signature in raw_signatures
    ]
    support_cutoff = agp.natural_break_threshold(non_missing_counts)
    required_non_missing = (
        max(1, int(math.ceil(support_cutoff)))
        if support_cutoff is not None
        else 1
    )
    signatures = []
    for signature, non_missing in zip(raw_signatures, non_missing_counts):
        signatures.append(signature if non_missing >= required_non_missing else tuple())
    return signatures


def normalize_duplicate_value(value) -> str | None:
    if sg.is_missing_value(value):
        return None
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def select_group_example_positions(
    matrix: np.ndarray,
    positions: np.ndarray,
) -> tuple[list[int], list[int]]:
    """Choose centroid-nearest examples and genuinely different boundary rows."""
    positions = np.asarray(positions, dtype=int)
    if positions.size == 0:
        return [], []
    members = np.asarray(matrix[positions], dtype=float)
    centroid = members.mean(axis=0, keepdims=True)
    centroid = sg.l2_normalize(centroid)[0]
    similarities = np.asarray(members @ centroid, dtype=float).ravel()
    ranked = sorted(
        range(len(positions)),
        key=lambda index: (-similarities[index], int(positions[index])),
    )
    representative = [
        int(positions[index]) for index in ranked[:REPRESENTATIVE_EXAMPLE_CAP]
    ]

    # A uniform group has no honest contradictory example. In a varied group,
    # the farthest assigned rows reveal the cluster boundary without claiming
    # that those rows are errors or were misclustered.
    if similarities.size < 2 or float(np.ptp(similarities)) <= np.finfo(float).eps:
        return representative, []
    representative_set = set(representative)
    boundary_ranked = sorted(
        range(len(positions)),
        key=lambda index: (similarities[index], int(positions[index])),
    )
    contradictory = [
        int(positions[index])
        for index in boundary_ranked
        if int(positions[index]) not in representative_set
    ][:CONTRADICTORY_EXAMPLE_CAP]
    return representative, contradictory


def build_grounded_group_description(
    rows: pd.DataFrame,
    full_frame: pd.DataFrame,
    error_df: pd.DataFrame,
    *,
    view: str,
    columns: list[str],
    profile_map: dict[str, dict],
    feature_info: dict[str, Any],
    representative_positions: list[int] | None,
    contradictory_positions: list[int] | None,
    fallback_highlights: list[str],
    baseline_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe a group only from fields, values, and errors in this sample."""
    semantic_candidates = semantic_description_candidates(
        rows,
        full_frame,
        columns,
        profile_map,
        feature_info,
        baseline_cache,
    )
    quality_candidates = quality_description_candidates(
        rows,
        full_frame,
        error_df,
        feature_info,
    )
    duplicate_matches: list[dict[str, Any]] = []
    if view == "duplicates":
        # Near-duplicate groups are defined by which field values match exactly, not by
        # how a field drifts from the full-sample baseline (the effect-size framing every
        # other view uses). Naming the actual matched value per field is what makes each
        # group a distinct, specific description instead of a generic "same values" line.
        duplicate_matches = duplicate_match_candidates(rows, columns)
        semantic_candidates.extend(duplicate_matches)

    semantic_evidence = select_description_evidence(
        semantic_candidates,
        DESCRIPTION_SUPPORT_FIELD_CAP,
    )
    quality_evidence = select_description_evidence(quality_candidates, 2)

    if view == "duplicates" and duplicate_matches:
        semantic_cohort = duplicate_cohort_phrase(duplicate_matches, len(columns))
    elif semantic_evidence:
        phrases = unique_strings([
            str(item.get("cohortPhrase") or "") for item in semantic_evidence
        ])[:2]
        semantic_cohort = (
            "Rows with " + " and ".join(phrases)
            if phrases
            else NO_STANDOUT_FIELD_COHORT
        )
    elif fallback_highlights:
        semantic_cohort = f"Rows sharing this observed pattern: {fallback_highlights[0]}"
    else:
        semantic_cohort = NO_STANDOUT_FIELD_COHORT

    primary_quality = quality_evidence[0] if quality_evidence else None
    quality_is_informative = bool(primary_quality and primary_quality.get("enriched"))
    if quality_is_informative:
        quality_pattern = str(primary_quality["qualityPhrase"])
    else:
        quality_pattern = NO_QUALITY_SIGNAL_PHRASE

    description = (
        f"{semantic_cohort}, with {quality_pattern}."
        if quality_is_informative
        else f"{semantic_cohort}."
    )
    selected_support = [*semantic_evidence, *quality_evidence]
    supporting_fields = [
        public_description_evidence(item)
        for item in selected_support[:DESCRIPTION_SUPPORT_FIELD_CAP]
    ]
    example_columns = description_example_columns(selected_support, columns)
    if representative_positions is None:
        representative_positions = [int(index) for index in rows.index.tolist()]
    representative_examples = build_group_examples(
        full_frame,
        representative_positions[:REPRESENTATIVE_EXAMPLE_CAP],
        example_columns,
        reason="Closest to the group center; a typical example of this pattern.",
    )
    contradictory_examples = build_group_examples(
        full_frame,
        (contradictory_positions or [])[:CONTRADICTORY_EXAMPLE_CAP],
        example_columns,
        reason=(
            "Assigned to this group but farthest from its center; inspect this boundary "
            "example before treating the description as universal."
        ),
    )
    return {
        "description": description,
        "semanticCohort": semantic_cohort,
        "qualityPattern": quality_pattern,
        "hasQualitySignal": quality_is_informative,
        "supportingFields": supporting_fields,
        "representativeExamples": representative_examples,
        "contradictoryExamples": contradictory_examples,
    }


def semantic_description_candidates(
    rows: pd.DataFrame,
    full_frame: pd.DataFrame,
    columns: list[str],
    profile_map: dict[str, dict],
    feature_info: dict[str, Any],
    baseline_cache: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for column in columns:
        if column not in rows or column not in full_frame:
            continue
        profile = profile_map.get(column, {})
        role = str(profile.get("role") or "")
        family = str(profile.get("family") or "other")
        if family == "other":
            inferred_role, _confidence = fallback_profile(full_frame[column])
            role = inferred_role
            family = profile_role_family(inferred_role)

        if column in (feature_info.get("ordinalColumns") or []):
            # Takes priority over the role/family branches below: an ordinal
            # column (e.g. "YearsCoding") is still profiler-role categorical,
            # but genuine bucketed-numeric distance is a strictly better story
            # than either exact-match concentration or embedding cohesion here.
            candidate = ordinal_description_candidate(rows, full_frame, column, baseline_cache)
            if candidate:
                candidates.append(candidate)
            continue
        if column in (feature_info.get("geographyNameColumns") or []):
            # Same priority reasoning as ordinal above: real spherical
            # distance from a reference-table lookup is strictly better than
            # exact-match equality ("India" vs "Pakistan" treated as no more
            # different than "India" vs "Australia") for a column already
            # proven to resolve cleanly to real coordinates.
            candidate = geography_name_description_candidate(rows, full_frame, column, feature_info)
            if candidate:
                candidates.append(candidate)
            continue
        if role in TEMPORAL_ROLES or role == "datetime" or family == "temporal":
            candidate = temporal_description_candidate(rows, full_frame, column, baseline_cache)
            if candidate:
                candidates.append(candidate)
            continue
        if family == "numeric":
            candidate = numeric_description_candidate(rows, full_frame, column, baseline_cache)
            if candidate:
                candidates.append(candidate)
            continue
        if family == "text" or role in TEXT_ROLES:
            # Free-text columns have no exact-match equivalent to categorical_
            # description_candidate's fallback -- if this column was embedded
            # (see free_text_embedding_eligible_columns) and shows cohesion,
            # describe it; otherwise there is nothing else to say here, same
            # as before this column type could be embedded at all.
            if column in (feature_info.get("embeddingColumns") or []):
                embedding_candidate = embedding_semantic_description_candidate(rows, column, feature_info)
                if embedding_candidate:
                    candidates.append(embedding_candidate)
            continue
        if column in (feature_info.get("embeddingColumns") or []):
            embedding_candidate = embedding_semantic_description_candidate(rows, column, feature_info)
            if embedding_candidate:
                candidates.append(embedding_candidate)
                continue
        candidate = categorical_description_candidate(rows, full_frame, column, baseline_cache)
        if candidate:
            candidates.append(candidate)

    candidates.extend(geography_description_candidates(rows, full_frame, feature_info))
    candidates.extend(term_description_candidates(rows, columns, feature_info))
    return dedupe_description_candidates(candidates)


def cached_full_frame_numeric_values(
    full_frame: pd.DataFrame,
    column: str,
    baseline_cache: dict[str, Any] | None,
) -> pd.Series:
    """Parsed full-sample numeric values for one column, computed once per column.

    Same fix and same reason as cached_full_frame_categorical_values: this parse is
    identical for every group that shares a column, so it must not be redone once
    per candidate group.
    """
    cache = None if baseline_cache is None else baseline_cache.setdefault("numeric", {})
    if cache is not None and column in cache:
        return cache[column]
    full_values = pd.to_numeric(full_frame[column], errors="coerce").dropna()
    if cache is not None:
        cache[column] = full_values
    return full_values


def numeric_description_candidate(
    rows: pd.DataFrame,
    full_frame: pd.DataFrame,
    column: str,
    baseline_cache: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    group_values = pd.to_numeric(rows[column], errors="coerce").dropna()
    full_values = cached_full_frame_numeric_values(full_frame, column, baseline_cache)
    if group_values.empty or full_values.nunique() < 2:
        return None
    group_median = float(group_values.median())
    baseline_median = float(full_values.median())
    spread = float(full_values.quantile(0.75) - full_values.quantile(0.25))
    if not math.isfinite(spread) or spread <= 0:
        spread = float(full_values.std())
    if not math.isfinite(spread) or spread <= 0:
        return None
    effect = (group_median - baseline_median) / spread
    if abs(effect) <= np.finfo(float).eps:
        return None
    direction = "higher-than-typical" if effect > 0 else "lower-than-typical"
    friendly = sg.friendly_name(column)
    return {
        "_score": abs(effect),
        "kind": "numeric",
        "column": column,
        "sourceColumns": [column],
        "direction": direction,
        "groupValue": round(group_median, 6),
        "baselineValue": round(baseline_median, 6),
        "strength": round(abs(effect), 6),
        "cohortPhrase": f"{direction} {friendly}",
        "evidence": (
            f"Median {friendly} is {format_compact_number(group_median)} here versus "
            f"{format_compact_number(baseline_median)} across the sample."
        ),
    }


def cached_full_frame_ordinal_values(
    full_frame: pd.DataFrame,
    column: str,
    baseline_cache: dict[str, Any] | None,
) -> pd.Series:
    """Bucket-parsed full-sample ordinal values for one column, computed once.

    Same fix and same reason as cached_full_frame_categorical_values.
    """
    cache = None if baseline_cache is None else baseline_cache.setdefault("ordinal", {})
    if cache is not None and column in cache:
        return cache[column]
    full_values = full_frame[column].map(parse_ordinal_bucket_value).dropna()
    if cache is not None:
        cache[column] = full_values
    return full_values


def nearest_ordinal_label(full_frame: pd.DataFrame, column: str, target: float) -> str:
    """The original bucket label (e.g. "9-11 years") whose parsed value is
    closest to a target number, so descriptions read in the dataset's own
    vocabulary instead of a raw float like "10.5".
    """
    distinct_values = full_frame[column][~full_frame[column].map(sg.is_missing_value)].map(sg.format_group_value).unique()
    best_label, best_distance = None, math.inf
    for value in distinct_values:
        parsed = parse_ordinal_bucket_value(value)
        if parsed is None:
            continue
        distance = abs(parsed - target)
        if distance < best_distance:
            best_label, best_distance = str(value), distance
    return best_label if best_label is not None else format_compact_number(target)


def ordinal_description_candidate(
    rows: pd.DataFrame,
    full_frame: pd.DataFrame,
    column: str,
    baseline_cache: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Describe a group's position on a bucketed-numeric scale (see
    ordinal_eligible_columns / parse_ordinal_bucket_value), reusing the same
    robust-scaled effect-size scoring numeric_description_candidate uses, but
    displaying the group's position via the original bucket label instead of
    a raw parsed number -- "typically 9-11 years" reads naturally where
    "typically 10.5" would not.
    """
    group_values = rows[column].map(parse_ordinal_bucket_value).dropna()
    full_values = cached_full_frame_ordinal_values(full_frame, column, baseline_cache)
    if group_values.empty or full_values.nunique() < 2:
        return None
    group_median = float(group_values.median())
    baseline_median = float(full_values.median())
    spread = float(full_values.quantile(0.75) - full_values.quantile(0.25))
    if not math.isfinite(spread) or spread <= 0:
        spread = float(full_values.std())
    if not math.isfinite(spread) or spread <= 0:
        return None
    effect = (group_median - baseline_median) / spread
    if abs(effect) <= np.finfo(float).eps:
        return None
    direction = "higher-than-typical" if effect > 0 else "lower-than-typical"
    friendly = sg.friendly_name(column)
    group_label = nearest_ordinal_label(full_frame, column, group_median)
    baseline_label = nearest_ordinal_label(full_frame, column, baseline_median)
    return {
        "_score": abs(effect),
        "kind": "ordinal",
        "column": column,
        "sourceColumns": [column],
        "direction": direction,
        "groupValue": group_label,
        "baselineValue": baseline_label,
        "strength": round(abs(effect), 6),
        "cohortPhrase": f"{direction} {friendly}",
        "evidence": (
            f"{friendly} is typically {group_label} here versus {baseline_label} "
            "across the sample."
        ),
    }


def cached_full_frame_temporal_values(
    full_frame: pd.DataFrame,
    column: str,
    baseline_cache: dict[str, Any] | None,
) -> pd.Series:
    """Parsed full-sample datetime values for one column, computed once per column.

    Same fix and same reason as cached_full_frame_categorical_values.
    """
    cache = None if baseline_cache is None else baseline_cache.setdefault("temporal", {})
    if cache is not None and column in cache:
        return cache[column]
    full_values = pd.to_datetime(full_frame[column], errors="coerce", format="mixed", utc=True).dropna()
    if cache is not None:
        cache[column] = full_values
    return full_values


def temporal_description_candidate(
    rows: pd.DataFrame,
    full_frame: pd.DataFrame,
    column: str,
    baseline_cache: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    group_values = pd.to_datetime(rows[column], errors="coerce", format="mixed", utc=True).dropna()
    full_values = cached_full_frame_temporal_values(full_frame, column, baseline_cache)
    if group_values.empty or full_values.nunique() < 2:
        return None
    group_seconds = group_values.map(lambda value: value.timestamp())
    full_seconds = full_values.map(lambda value: value.timestamp())
    group_median = float(group_seconds.median())
    baseline_median = float(full_seconds.median())
    spread = float(full_seconds.quantile(0.75) - full_seconds.quantile(0.25))
    if not math.isfinite(spread) or spread <= 0:
        spread = float(full_seconds.std())
    if not math.isfinite(spread) or spread <= 0:
        return None
    effect = (group_median - baseline_median) / spread
    if abs(effect) <= np.finfo(float).eps:
        return None
    direction = "later-than-typical" if effect > 0 else "earlier-than-typical"
    group_display = pd.to_datetime(group_median, unit="s", utc=True).isoformat()
    baseline_display = pd.to_datetime(baseline_median, unit="s", utc=True).isoformat()
    friendly = sg.friendly_name(column)
    return {
        "_score": abs(effect),
        "kind": "temporal",
        "column": column,
        "sourceColumns": [column],
        "direction": direction,
        "groupValue": group_display,
        "baselineValue": baseline_display,
        "strength": round(abs(effect), 6),
        "cohortPhrase": f"{direction} {friendly}",
        "evidence": (
            f"Median {friendly} is {group_display} here versus {baseline_display} "
            "across the sample."
        ),
    }


# Formatting cutoff, not a modeling threshold -- same category as
# DESCRIPTION_VALUE_CHARACTER_CAP / DUPLICATE_COHORT_FIELD_CAP below, which are
# also fixed display caps rather than statistical decisions. Distinguishes
# short label-like embedded values (job titles, business categories) from
# full-sentence prose, so free-text headlines summarize shared language
# instead of quoting up to 3 full sentences verbatim.
EMBEDDING_PROSE_WORD_THRESHOLD = 6

# sg.STOP_WORDS is tuned for short category tokens (business/text column values),
# not natural-language prose -- it has no pronouns, modal/auxiliary verbs, or
# common prepositions, so real complaint narratives like "my calls about the
# balance" surface "about"/"my" as the "shared theme" instead of the actual
# content words. This supplement is scoped to shared_embedding_terms only; it
# does not touch sg.STOP_WORDS or any other tokenization path in this codebase.
PROSE_STOP_WORDS = {
    "i", "me", "my", "mine", "we", "us", "our", "ours", "you", "your", "yours",
    "he", "him", "his", "she", "her", "hers", "they", "them", "their", "theirs",
    "this", "that", "these", "those", "not", "no", "nor", "so", "than", "then",
    "too", "very", "can", "could", "will", "would", "shall", "should", "may",
    "might", "must", "do", "does", "did", "done", "have", "had", "having",
    "been", "being", "am", "if", "but", "about", "into", "onto", "over",
    "under", "again", "further", "once", "here", "there", "when", "where",
    "why", "how", "all", "any", "both", "each", "few", "more", "most", "other",
    "some", "such", "only", "own", "same", "just", "also",
}


def shared_embedding_terms(values: list[str], limit: int = 3) -> list[str]:
    """Deterministic, grounded keyword summary for a set of embedding-routed values.

    Not a generated summary -- no model call, no fabrication. Counts which
    tokens (sg.tokenize plus PROSE_STOP_WORDS filtering) actually recur across
    at least two of the group's distinct values, ranked by how many values
    contain them. Same "only report what is literally present" discipline
    every other description candidate in this file follows -- the cohesion
    score already proves the values are semantically close; this just names
    what they visibly share in common, in the group's own words.
    """
    token_value_counts: dict[str, int] = {}
    for value in values:
        tokens = {token for token in sg.tokenize(value) if token not in PROSE_STOP_WORDS}
        for token in tokens:
            token_value_counts[token] = token_value_counts.get(token, 0) + 1
    shared = sorted(
        (token for token, count in token_value_counts.items() if count >= 2),
        key=lambda token: (-token_value_counts[token], token),
    )
    return shared[:limit]


def embedding_semantic_description_candidate(
    rows: pd.DataFrame,
    column: str,
    feature_info: dict[str, Any],
) -> dict[str, Any] | None:
    """Describe a group whose cohesion in this column comes from meaning, not exact match.

    Only reachable for columns SBERT-embedded instead of exact-match tokenized (see
    embedding_eligible_columns). categorical_description_candidate can only reward one
    dominant repeated value -- it goes silent exactly when a group is held together by
    several *different* but semantically close values (e.g. "Back-end developer" /
    "Front-end developer" / "Full-stack developer"), which is the case embeddings exist
    to catch. Scored the same way every other candidate is: the group's effect (here,
    how much tighter its values sit in embedding space) relative to the baseline (how
    tight this column's full vocabulary sits), not a hardcoded similarity cutoff.
    """
    cache = (feature_info.get("embeddingValuesByColumn") or {}).get(column)
    if not cache:
        return None
    group_values = rows[column][~rows[column].map(sg.is_missing_value)].map(sg.format_group_value)
    if group_values.empty:
        return None
    counts = group_values.value_counts()
    distinct_values = [str(value) for value in counts.index if str(value) in cache]
    if len(distinct_values) < 2:
        return None

    group_vectors = np.array([cache[value] for value in distinct_values])
    centroid = group_vectors.mean(axis=0)
    centroid_norm = np.linalg.norm(centroid)
    if centroid_norm <= np.finfo(float).eps:
        return None
    group_cohesion = float(np.mean(group_vectors @ (centroid / centroid_norm)))

    all_values = list(cache.keys())
    if len(all_values) < 2:
        return None
    all_vectors = np.array([cache[value] for value in all_values])
    global_centroid = all_vectors.mean(axis=0)
    global_norm = np.linalg.norm(global_centroid)
    if global_norm <= np.finfo(float).eps:
        return None
    global_cohesion = float(np.mean(all_vectors @ (global_centroid / global_norm)))

    effect = group_cohesion - global_cohesion
    if effect <= np.finfo(float).eps:
        return None

    friendly = sg.friendly_name(column)
    average_word_count = sum(len(value.split()) for value in distinct_values) / len(distinct_values)
    is_prose = average_word_count > EMBEDDING_PROSE_WORD_THRESHOLD

    if is_prose:
        shared_terms = shared_embedding_terms(distinct_values)
        topic = ", ".join(shared_terms) if shared_terms else "no single recurring word"
        cohort_phrase = (
            f"{len(distinct_values)} {friendly} entries with similar meaning"
            + (f" (shared language: {topic})" if shared_terms else "")
        )
        group_value = topic
        evidence = (
            f"These {len(distinct_values)} distinct {friendly} entries sit close together in "
            f"meaning (similarity {group_cohesion:.2f} here vs {global_cohesion:.2f} across "
            "the sample) even though their exact wording differs."
        )
    else:
        shown_values = [truncate_description_value(value) for value in distinct_values[:3]]
        extra = len(distinct_values) - len(shown_values)
        value_list = join_with_and(shown_values)
        if extra > 0:
            value_list += f", and {extra} more"
        cohort_phrase = f"{friendly} values that mean the same thing, such as {value_list}"
        group_value = value_list
        evidence = (
            f"These {len(distinct_values)} distinct {friendly} values sit close together in "
            f"meaning (similarity {group_cohesion:.2f} here vs {global_cohesion:.2f} across "
            "the sample) even though they don't match exactly."
        )

    return {
        "_score": effect,
        "kind": "embedding_semantic",
        "column": column,
        "sourceColumns": [column],
        "groupValue": group_value,
        "groupCohesion": round(group_cohesion, 6),
        "baselineCohesion": round(global_cohesion, 6),
        "distinctValueCount": len(distinct_values),
        "strength": round(effect, 6),
        "cohortPhrase": cohort_phrase,
        "evidence": evidence,
    }


def cached_full_frame_categorical_values(
    full_frame: pd.DataFrame,
    column: str,
    baseline_cache: dict[str, Any] | None,
) -> pd.Series:
    """Present, formatted full-sample values for one column, computed once per column.

    Caught live profiling the Chicago Crime dataset: build_grounded_group_description
    runs once per candidate group (198 near-duplicate candidates before acceptance
    even trims them down), and this exact full_frame-sized missing/format pass was
    being recomputed from scratch every single time, identically, for every group --
    24.6M is_missing_value calls for a 10k-row sample. The baseline only depends on
    the column, never on which group is asking, so callers that process many groups
    against the same frame pass one shared dict to reuse it across all of them.
    """
    cache = None if baseline_cache is None else baseline_cache.setdefault("categorical", {})
    if cache is not None and column in cache:
        return cache[column]
    full_values = full_frame[column][~full_frame[column].map(sg.is_missing_value)].map(sg.format_group_value)
    if cache is not None:
        cache[column] = full_values
    return full_values


def categorical_description_candidate(
    rows: pd.DataFrame,
    full_frame: pd.DataFrame,
    column: str,
    baseline_cache: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    group_values = rows[column][~rows[column].map(sg.is_missing_value)].map(sg.format_group_value)
    full_values = cached_full_frame_categorical_values(full_frame, column, baseline_cache)
    if group_values.empty or full_values.empty:
        return None
    counts = group_values.value_counts()
    if counts.empty:
        return None
    value = str(counts.index[0])
    group_share = float(counts.iloc[0] / len(group_values))
    baseline_share = float((full_values == value).mean())
    concentration = group_share - baseline_share
    if concentration <= np.finfo(float).eps:
        return None
    friendly = sg.friendly_name(column)
    return {
        "_score": concentration,
        "kind": "categorical",
        "column": column,
        "sourceColumns": [column],
        "groupValue": truncate_description_value(value),
        "groupShare": round(group_share, 6),
        "baselineShare": round(baseline_share, 6),
        "strength": round(concentration, 6),
        "cohortPhrase": f"{friendly} usually {truncate_description_value(value)}",
        "evidence": (
            f"{truncate_description_value(value)} appears in {group_share:.0%} of present "
            f"{friendly} values here versus {baseline_share:.0%} across the sample."
        ),
    }


def term_description_candidates(
    rows: pd.DataFrame,
    columns: list[str],
    feature_info: dict[str, Any],
) -> list[dict[str, Any]]:
    text_matrix = feature_info.get("text_matrix")
    terms = list(feature_info.get("terms") or [])
    row_positions = feature_info.get("row_positions") or {}
    if text_matrix is None or not terms or getattr(text_matrix, "size", 0) == 0:
        return []
    positions = [row_positions.get(int(row_id)) for row_id in rows["ID"].tolist()]
    positions = [position for position in positions if position is not None]
    if not positions:
        return []
    cluster_mean = np.asarray(text_matrix[positions].mean(axis=0), dtype=float).ravel()
    global_mean = np.asarray(text_matrix.mean(axis=0), dtype=float).ravel()
    scores = cluster_mean - global_mean
    token_to_column = {column_token(column): column for column in columns}
    candidates = []
    for index in np.argsort(scores)[::-1]:
        score = float(scores[int(index)])
        if score <= np.finfo(float).eps:
            break
        term = str(terms[int(index)])
        if "__" not in term:
            continue
        prefix, value = term.split("__", 1)
        column = token_to_column.get(prefix)
        if not column or value == "missing":
            continue
        display_value = truncate_description_value(value.replace("_", " "))
        friendly = sg.friendly_name(column)
        candidates.append({
            "_score": score,
            "kind": "semantic_term",
            "column": column,
            "sourceColumns": [column],
            "groupValue": display_value,
            "groupWeight": round(float(cluster_mean[int(index)]), 6),
            "baselineWeight": round(float(global_mean[int(index)]), 6),
            "strength": round(score, 6),
            "cohortPhrase": f"shared {friendly} language such as {display_value}",
            "evidence": f"{display_value} is more prominent in {friendly} here than across the sample.",
        })
    return candidates


def central_angle_radians_vectorized(
    lat_a: np.ndarray, lon_a: np.ndarray, lat_b: float, lon_b: float,
) -> np.ndarray:
    lat_a_r = np.radians(lat_a)
    lon_a_r = np.radians(lon_a)
    lat_b_r = math.radians(lat_b)
    lon_b_r = math.radians(lon_b)
    cosine = (
        np.sin(lat_a_r) * math.sin(lat_b_r)
        + np.cos(lat_a_r) * math.cos(lat_b_r) * np.cos(lon_a_r - lon_b_r)
    )
    return np.arccos(np.clip(cosine, -1.0, 1.0))


def geography_description_candidates(
    rows: pd.DataFrame,
    full_frame: pd.DataFrame,
    feature_info: dict[str, Any],
) -> list[dict[str, Any]]:
    candidates = []
    for latitude, longitude in feature_info.get("coordinate_pairs", []):
        if latitude not in rows or longitude not in rows:
            continue
        group_lat = pd.to_numeric(rows[latitude], errors="coerce").median()
        group_lon = pd.to_numeric(rows[longitude], errors="coerce").median()
        full_lat_series = pd.to_numeric(full_frame[latitude], errors="coerce")
        full_lon_series = pd.to_numeric(full_frame[longitude], errors="coerce")
        valid = full_lat_series.notna() & full_lon_series.notna()
        full_lat = full_lat_series[valid].median()
        full_lon = full_lon_series[valid].median()
        if any(pd.isna(value) for value in (group_lat, group_lon, full_lat, full_lon)):
            continue
        angle = central_angle_radians(group_lat, group_lon, full_lat, full_lon)
        if angle <= np.finfo(float).eps:
            continue
        distance_km = angle * 6371.0088

        # Score this candidate the same way every other family scores itself: the group's
        # offset from the baseline relative to how spread out the full sample already is
        # around that same baseline. A raw angle/distance alone is on a different scale
        # than the IQR-normalized effect sizes used for numeric/categorical/temporal
        # candidates, so without this a real geographic split would look artificially weak
        # and lose out to unrelated fields in the natural-break evidence cutoff.
        sample_angles = central_angle_radians_vectorized(
            full_lat_series[valid].to_numpy(),
            full_lon_series[valid].to_numpy(),
            float(full_lat),
            float(full_lon),
        )
        spread = float(np.quantile(sample_angles, 0.75) - np.quantile(sample_angles, 0.25))
        if not math.isfinite(spread) or spread <= 0:
            spread = float(np.std(sample_angles))
        if not math.isfinite(spread) or spread <= 0:
            continue
        effect = angle / spread

        cohort_phrase = geography_cohort_phrase(full_lat, full_lon, group_lat, group_lon, distance_km)
        candidates.append({
            "_score": effect,
            "kind": "geography",
            "column": f"{latitude}, {longitude}",
            "sourceColumns": [latitude, longitude],
            "groupValue": f"{group_lat:.4f}, {group_lon:.4f}",
            "baselineValue": f"{full_lat:.4f}, {full_lon:.4f}",
            "strength": round(effect, 6),
            "cohortPhrase": cohort_phrase,
            "evidence": (
                f"The group center is near {group_lat:.4f}, {group_lon:.4f}, about "
                f"{distance_km:,.0f} km from the full-sample center."
            ),
        })
    return candidates


# Below this, a bearing is "near" rather than a directional claim — short distances make
# compass direction noisy and unhelpful ("3 km north" reads as false precision).
GEOGRAPHY_NEAR_CENTER_KM = 1.0
_COMPASS_POINTS = (
    "north", "north-northeast", "northeast", "east-northeast",
    "east", "east-southeast", "southeast", "south-southeast",
    "south", "south-southwest", "southwest", "west-southwest",
    "west", "west-northwest", "northwest", "north-northwest",
)


def compass_direction(lat_from: float, lon_from: float, lat_to: float, lon_to: float) -> str:
    """Compass direction of (lat_to, lon_to) as seen from (lat_from, lon_from)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (lat_from, lon_from, lat_to, lon_to))
    delta_lon = lon2 - lon1
    x = math.sin(delta_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    bearing_degrees = (math.degrees(math.atan2(x, y)) + 360.0) % 360.0
    index = int((bearing_degrees / 22.5) + 0.5) % 16
    return _COMPASS_POINTS[index]


def geography_cohort_phrase(
    full_lat: float,
    full_lon: float,
    group_lat: float,
    group_lon: float,
    distance_km: float,
) -> str:
    """A plain-language stand-in for raw coordinates, which most readers can't place mentally."""
    if distance_km < GEOGRAPHY_NEAR_CENTER_KM:
        return "a location near the sample's typical center"
    direction = compass_direction(full_lat, full_lon, group_lat, group_lon)
    return f"a location about {distance_km:,.0f} km {direction} of the sample's typical center"


def central_angle_radians(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    lat_a, lon_a, lat_b, lon_b = map(math.radians, (lat_a, lon_a, lat_b, lon_b))
    cosine = (
        math.sin(lat_a) * math.sin(lat_b)
        + math.cos(lat_a) * math.cos(lat_b) * math.cos(lon_a - lon_b)
    )
    return float(math.acos(max(-1.0, min(1.0, cosine))))


def nearest_geography_name_label(cache: dict[str, tuple[float, float]], target_lat: float, target_lon: float) -> str | None:
    """The original name (e.g. "France") whose looked-up centroid is closest
    to a target coordinate, so descriptions read in the dataset's own
    vocabulary instead of raw latitude/longitude.
    """
    best_label, best_distance = None, math.inf
    for value, (lat, lon) in cache.items():
        distance = central_angle_radians(target_lat, target_lon, lat, lon)
        if distance < best_distance:
            best_label, best_distance = value, distance
    return best_label


def geography_name_description_candidate(
    rows: pd.DataFrame,
    full_frame: pd.DataFrame,
    column: str,
    feature_info: dict[str, Any],
) -> dict[str, Any] | None:
    """Describe a group's position using real geographic distance for a
    location-*name* column (see geography_reference.py), reusing the same
    angle/spread effect-size scoring and compass phrasing
    geography_description_candidates already uses for explicit lat/long
    columns -- the only difference is where the coordinates come from (a
    reference-table lookup instead of raw numeric columns already on the row).
    """
    cache = (feature_info.get("geographyCentroidsByColumn") or {}).get(column)
    if not cache:
        return None

    def row_coordinates(series: pd.Series) -> tuple[np.ndarray, np.ndarray]:
        lats, lons = [], []
        for value in series:
            if sg.is_missing_value(value):
                continue
            centroid = cache.get(sg.format_group_value(value))
            if centroid is None:
                continue
            lats.append(centroid[0])
            lons.append(centroid[1])
        return np.asarray(lats, dtype=float), np.asarray(lons, dtype=float)

    group_lats, group_lons = row_coordinates(rows[column])
    full_lats, full_lons = row_coordinates(full_frame[column])
    if group_lats.size == 0 or full_lats.size < 2:
        return None

    group_lat, group_lon = float(np.median(group_lats)), float(np.median(group_lons))
    full_lat, full_lon = float(np.median(full_lats)), float(np.median(full_lons))
    angle = central_angle_radians(group_lat, group_lon, full_lat, full_lon)
    if angle <= np.finfo(float).eps:
        return None
    distance_km = angle * 6371.0088

    sample_angles = central_angle_radians_vectorized(full_lats, full_lons, full_lat, full_lon)
    spread = float(np.quantile(sample_angles, 0.75) - np.quantile(sample_angles, 0.25))
    if not math.isfinite(spread) or spread <= 0:
        spread = float(np.std(sample_angles))
    if not math.isfinite(spread) or spread <= 0:
        return None
    effect = angle / spread
    if effect <= np.finfo(float).eps:
        return None

    friendly = sg.friendly_name(column)
    cohort_phrase = geography_cohort_phrase(full_lat, full_lon, group_lat, group_lon, distance_km)
    group_label = nearest_geography_name_label(cache, group_lat, group_lon)
    return {
        "_score": effect,
        "kind": "geography_name",
        "column": column,
        "sourceColumns": [column],
        "groupValue": group_label or f"{group_lat:.4f}, {group_lon:.4f}",
        "baselineValue": f"{full_lat:.4f}, {full_lon:.4f}",
        "strength": round(effect, 6),
        "cohortPhrase": f"{friendly} typically {cohort_phrase}",
        "evidence": (
            f"The typical {friendly} here is near {group_label or f'{group_lat:.4f}, {group_lon:.4f}'}, "
            f"about {distance_km:,.0f} km from the full sample's typical {friendly}."
        ),
    }


def quality_description_candidates(
    rows: pd.DataFrame,
    full_frame: pd.DataFrame,
    error_df: pd.DataFrame,
    feature_info: dict[str, Any],
) -> list[dict[str, Any]]:
    row_positions = feature_info.get("row_positions") or {}
    quality_rows = feature_info.get("quality_row_tokens") or []
    group_tokens: Counter[str] = Counter()
    full_tokens: Counter[str] = Counter()
    if quality_rows:
        for tokens in quality_rows:
            full_tokens.update(set(tokens))
        for row_id in rows["ID"].tolist():
            position = row_positions.get(int(row_id))
            if position is not None and position < len(quality_rows):
                group_tokens.update(set(quality_rows[position]))
    elif not error_df.empty:
        group_ids = set(int(value) for value in rows["ID"].tolist())
        seen_by_row: dict[int, set[str]] = defaultdict(set)
        for record in error_df.itertuples(index=False):
            token = f"quality__{column_token(record.error_type)}__{column_token(record.column_id)}"
            seen_by_row[int(record.row_id)].add(token)
        for row_id, tokens in seen_by_row.items():
            full_tokens.update(tokens)
            if row_id in group_ids:
                group_tokens.update(tokens)
    if not group_tokens:
        return []

    token_to_column = {
        column_token(column): column
        for column in full_frame.columns
        if column not in sg.HELPER_COLUMNS and not column.startswith("_buckaroo_")
    }
    candidates = []
    for token, count in group_tokens.items():
        issue_token, column_token_value = parse_quality_token(token)
        column = token_to_column.get(column_token_value, column_token_value.replace("_", " "))

        # Tautology guard. A "rare value" / "incomplete" signal is a statement about how
        # uncommon a value is *in the whole dataset*. When the group shares one constant
        # value for that column (e.g. a near-duplicate group all with Country=Israel),
        # that rare value concentrates to 100% purely by construction — the group was
        # DEFINED by it. Reporting "unusually frequent rare Country values" there is
        # circular and misleading: the rows are not incomplete, their Country is simply
        # the uncommon value that defines the group. Such a signal carries no
        # within-cluster information, so it is dropped. (Missing / type-mismatch / anomaly
        # signals are about a value being absent or wrong, which stays a real finding even
        # when constant, so only the rarity family is guarded here.)
        issue_key = issue_token.strip().lower().replace(" ", "_")
        if issue_key in RARITY_ISSUE_TOKENS and column_is_constant_present_in_group(rows, column):
            continue

        group_rate = count / max(1, len(rows))
        baseline_rate = full_tokens[token] / max(1, len(full_frame))
        enrichment = group_rate - baseline_rate
        label = humanize_quality_issue(issue_token, column)
        enriched = bool(enrichment > np.finfo(float).eps)
        candidates.append({
            "_score": max(enrichment, np.finfo(float).eps) * group_rate,
            "kind": "quality",
            "column": column,
            "sourceColumns": [column] if column in full_frame else [],
            "issue": issue_token.replace("_", " "),
            "groupShare": round(group_rate, 6),
            "baselineShare": round(baseline_rate, 6),
            "strength": round(max(0.0, enrichment), 6),
            "enriched": enriched,
            "qualityPhrase": (
                f"unusually frequent {label}"
                if enriched
                else f"{label} without clear enrichment over the full sample"
            ),
            "evidence": (
                f"{label.capitalize()} affect {group_rate:.0%} of this group versus "
                f"{baseline_rate:.0%} of the full sample."
            ),
        })
    return candidates


# Issue families that are statements about a value's global rarity/uncommonness rather
# than the value being absent or malformed. Only these are tautological when the group is
# defined by a single constant value for the column (see quality_description_candidates).
RARITY_ISSUE_TOKENS = {"incomplete", "rare_value", "rare"}


def column_is_constant_present_in_group(rows: pd.DataFrame, column: str) -> bool:
    """True when every row in the group shares one present (non-missing) value for column.

    That makes the column part of the group's own definition rather than a dimension along
    which the group could exhibit a distinguishing quality pattern.
    """
    if column not in rows:
        return False
    series = rows[column]
    non_missing = series[~series.map(sg.is_missing_value)]
    return len(non_missing) == len(series) and int(non_missing.nunique(dropna=True)) == 1


def parse_quality_token(token: str) -> tuple[str, str]:
    parts = str(token).split("__", 2)
    if len(parts) == 3:
        return parts[1], parts[2]
    return "detected_issue", "unknown_column"


def humanize_quality_issue(issue: str, column: str) -> str:
    cleaned = issue.replace("_", " ").strip().lower()
    friendly = sg.friendly_name(column)
    if "missing" in cleaned:
        return f"missing values in {friendly}"
    if "datatype" in cleaned or "type mismatch" in cleaned:
        return f"type mismatches in {friendly}"
    if "anomal" in cleaned or "outlier" in cleaned:
        return f"unusual values in {friendly}"
    if "incomplete" in cleaned:
        # detectors/incomplete.py's own docstring: this detector no longer measures
        # incompleteness — it flags statistically rare categorical values, and kept the
        # "incomplete" error_type label only for backward compatibility with the DB error
        # schema and existing tests. Saying "incomplete" here would misrepresent a
        # frequency/concentration signal as missing data (caught live: a country value
        # present in 100% of a group but ~1% of the full sample was reported as
        # "incomplete values in Country", which reads as missing/blank data to anyone
        # who doesn't know the legacy label's history).
        return f"rare category values in {friendly}"
    return f"{cleaned or 'detected issues'} in {friendly}"


def duplicate_match_candidates(
    rows: pd.DataFrame,
    columns: list[str],
) -> list[dict[str, Any]]:
    """One candidate per column that is exactly constant within this near-duplicate group.

    This mirrors categorical_description_candidate's shape so it flows through the same
    natural-break selection and supporting-fields rendering as every other view, but the
    signal here is exact match within the group rather than a group-vs-baseline effect.
    """
    candidates = []
    for column in columns:
        if column not in rows:
            continue
        values = rows[column][~rows[column].map(sg.is_missing_value)].map(sg.format_group_value)
        if values.empty or values.nunique() != 1:
            continue
        value = truncate_description_value(str(values.iloc[0]))
        friendly = sg.friendly_name(column)
        candidates.append({
            "_score": 1.0,
            "kind": "duplicate_match",
            "column": column,
            "sourceColumns": [column],
            "groupValue": value,
            # The value is the whole point of a duplicate group: two groups that both
            # "match on Gender, Continent, Country" are entirely different cohorts if one
            # is US males and the other is UK females. Name the actual values, not just
            # the columns, so every group reads as a distinct, specific description.
            "matchPhrase": f"{friendly} is {value}",
            "strength": 1.0,
            "cohortPhrase": f"{friendly} is {value}",
            "evidence": f"Every row in this group shares the same {friendly}: {value}.",
        })
    return candidates


def join_with_and(values: list[str]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return ", ".join(values[:-1]) + f", and {values[-1]}"


# Beyond this many named field=value pairs the headline gets unwieldy; the rest are
# summarized as "and N more fields" and remain visible in the supporting-fields list.
DUPLICATE_COHORT_FIELD_CAP = 4


def duplicate_cohort_phrase(duplicate_matches: list[dict[str, Any]], total_columns: int) -> str:
    phrases = [str(item["matchPhrase"]) for item in duplicate_matches[:DUPLICATE_COHORT_FIELD_CAP]]
    extra = len(duplicate_matches) - len(phrases)
    if extra > 0:
        phrases.append(f"{extra} more matching field{'s' if extra != 1 else ''}")
    return f"Rows where {join_with_and(phrases)}"


def select_description_evidence(
    candidates: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    if not candidates or limit <= 0:
        return []
    ranked = sorted(
        candidates,
        key=lambda item: (-safe_float(item.get("_score"), 0.0), str(item.get("column", ""))),
    )
    cutoff = agp.natural_break_threshold(item.get("_score", 0.0) for item in ranked)
    stronger = [
        item for item in ranked
        if cutoff is None or safe_float(item.get("_score"), 0.0) >= cutoff
    ]
    return stronger[:limit]


def dedupe_description_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for candidate in sorted(candidates, key=lambda item: -safe_float(item.get("_score"), 0.0)):
        key = (
            candidate.get("kind"),
            candidate.get("column"),
            str(candidate.get("groupValue", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def public_description_evidence(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in candidate.items()
        if not key.startswith("_") and key not in {"cohortPhrase", "qualityPhrase"}
    }


def description_example_columns(
    evidence: list[dict[str, Any]],
    fallback_columns: list[str],
) -> list[str]:
    columns = unique_strings([
        column
        for item in evidence
        for column in item.get("sourceColumns", [])
    ])
    columns.extend(
        column for column in fallback_columns
        if column not in columns and column not in sg.HELPER_COLUMNS
    )
    return columns[:DESCRIPTION_EXAMPLE_FIELD_CAP]


def build_group_examples(
    full_frame: pd.DataFrame,
    positions: list[int],
    columns: list[str],
    *,
    reason: str,
) -> list[dict[str, Any]]:
    examples = []
    for position in positions:
        position = int(position)
        if position < 0 or position >= len(full_frame):
            continue
        row = full_frame.iloc[position]
        examples.append({
            "rowId": int(row["ID"]),
            "values": {
                column: display_example_value(row[column])
                for column in columns
                if column in full_frame
            },
            "reason": reason,
        })
    return examples


def display_example_value(value: Any) -> str:
    if sg.is_missing_value(value):
        return "missing"
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return truncate_description_value(str(value))


def truncate_description_value(value: str) -> str:
    value = " ".join(str(value).split())
    if len(value) <= DESCRIPTION_VALUE_CHARACTER_CAP:
        return value
    return value[: DESCRIPTION_VALUE_CHARACTER_CAP - 3].rstrip() + "..."


def format_compact_number(value: float) -> str:
    if not math.isfinite(value):
        return "unknown"
    return f"{value:,.3f}".rstrip("0").rstrip(".")


def make_group(
    rows: pd.DataFrame,
    full_frame: pd.DataFrame,
    error_df: pd.DataFrame,
    *,
    view: str,
    group_name: str,
    algorithm: str,
    columns: list[str],
    profile_confidence: float,
    stability: float,
    coherence: float,
    distinctiveness: float,
    explainability: float,
    feature_highlights: list[str],
    baseline_error_rate: float,
    total_error_rows: int,
    profile_map: dict[str, dict] | None = None,
    feature_info: dict[str, Any] | None = None,
    representative_positions: list[int] | None = None,
    contradictory_positions: list[int] | None = None,
    baseline_cache: dict[str, Any] | None = None,
) -> MultiViewGroup:
    row_ids = [int(value) for value in rows["ID"].tolist()]
    row_id_set = set(row_ids)
    group_errors = error_df[error_df["row_id"].isin(row_id_set)] if not error_df.empty else sg._empty_error_df()
    error_rows = int(rows["_buckaroo_has_error"].sum())
    error_rate = error_rows / len(rows) if len(rows) else 0.0
    lift = error_rate / baseline_error_rate if baseline_error_rate else 0.0
    error_coverage = error_rows / total_error_rows if total_error_rows else 0.0
    main_issue, main_columns = sg.summarize_errors(group_errors)
    coverage = len(rows) / len(full_frame)
    utility = utility_score(
        stability=stability,
        coherence=coherence,
        distinctiveness=distinctiveness,
        explainability=explainability,
        profile_confidence=profile_confidence,
        coverage=coverage,
        view=view,
    )
    highlights = unique_strings(feature_highlights)[:5]
    grounded = build_grounded_group_description(
        rows,
        full_frame,
        error_df,
        view=view,
        columns=columns,
        profile_map=profile_map or {},
        feature_info=feature_info or {},
        representative_positions=representative_positions,
        contradictory_positions=contradictory_positions,
        fallback_highlights=highlights,
        baseline_cache=baseline_cache,
    )
    caveats = []
    if view == "duplicates":
        caveats.append("This is a candidate duplicate group; confirm identity before deleting records.")
    definition = VIEW_DEFINITIONS[view]
    returned_ids = row_ids[:MAX_GROUP_ROW_IDS]
    return MultiViewGroup(
        id=f"{view}:{group_name}",
        view=view,
        viewLabel=definition["label"],
        groupType=view,
        algorithm=algorithm,
        description=grounded["description"],
        semanticCohort=grounded["semanticCohort"],
        qualityPattern=grounded["qualityPattern"],
        hasQualitySignal=grounded["hasQualitySignal"],
        supportingFields=grounded["supportingFields"],
        representativeExamples=grounded["representativeExamples"],
        contradictoryExamples=grounded["contradictoryExamples"],
        descriptionGrounded=True,
        whyUseful=definition["why"],
        rows=int(len(rows)),
        coverage=round(coverage, 6),
        utilityScore=round(utility, 6),
        semanticScore=0.0,  # assigned during semantic-first ranking across the merged list
        stability=round(float(stability), 6),
        coherence=round(float(coherence), 6),
        distinctiveness=round(float(distinctiveness), 6),
        explainability=round(float(explainability), 6),
        profileConfidence=round(float(profile_confidence), 6),
        errorRows=error_rows,
        errorRate=round(float(error_rate), 6),
        baselineErrorRate=round(float(baseline_error_rate), 6),
        lift=round(float(lift), 6),
        errorCoverage=round(float(error_coverage), 6),
        mainIssue=main_issue,
        mainErrorColumns=main_columns,
        columnsUsed=list(columns),
        rowIds=returned_ids,
        rowIdsTruncated=len(row_ids) > len(returned_ids),
        featureHighlights=highlights,
        caveats=caveats,
    )


def describe_view_group(
    rows: pd.DataFrame,
    full_frame: pd.DataFrame,
    view: str,
    columns: list[str],
    profile_map: dict[str, dict],
    feature_info: dict,
) -> list[str]:
    highlights = []
    numeric = [column for column in columns if profile_map[column]["family"] == "numeric"]
    categorical = [
        column for column in columns
        if column not in numeric and profile_map[column]["role"] not in TEMPORAL_ROLES
    ]
    for column, label in sg.strongest_numeric_descriptions(rows, full_frame, numeric):
        highlights.append(f"{label} {sg.friendly_name(column)} (average {sg.safe_mean(rows[column]):.1f})")
    for column, value, share in sg.strongest_text_descriptions(rows, full_frame, categorical):
        highlights.append(f"{sg.friendly_name(column)} mostly {value} ({share:.0%})")

    if view in {"lifecycle", "semantic_quality"}:
        for column, values in feature_info.get("parsed_dates", {}).items():
            positions = rows.index.to_numpy(dtype=int)
            selected = values.iloc[positions].dropna()
            if not selected.empty:
                month = selected.dt.strftime("%Y-%m").mode()
                if not month.empty:
                    share = float((selected.dt.strftime("%Y-%m") == month.iloc[0]).mean())
                    month_counts = selected.dt.strftime("%Y-%m").value_counts().tolist()
                    if agp.score_separation(month_counts)["separated"]:
                        highlights.append(f"{sg.friendly_name(column)} concentrated in {month.iloc[0]} ({share:.0%})")
        for first, second, duration in feature_info.get("durations", []):
            positions = rows.index.to_numpy(dtype=int)
            selected = duration.iloc[positions].dropna()
            if not selected.empty:
                highlights.append(
                    f"median {sg.friendly_name(first)} to {sg.friendly_name(second)}: {selected.median():.1f} days"
                )
    if view in {"geography", "semantic_quality"}:
        for latitude, longitude in feature_info.get("coordinate_pairs", []):
            lat = pd.to_numeric(rows[latitude], errors="coerce").median()
            lon = pd.to_numeric(rows[longitude], errors="coerce").median()
            if pd.notna(lat) and pd.notna(lon):
                highlights.append(f"centered near {lat:.3f}, {lon:.3f}")

    token_highlights = sg.strongest_token_descriptions(rows, feature_info)
    if token_highlights:
        readable = [term.replace("__", ": ").replace("_", " ") for term in token_highlights[:4]]
        highlights.append("shared terms: " + ", ".join(readable))

    if view == "semantic_quality":
        row_positions = feature_info.get("row_positions", {})
        row_tokens = feature_info.get("quality_row_tokens", [])
        counts = Counter()
        for row_id in rows["ID"].tolist():
            position = row_positions.get(int(row_id))
            if position is not None and position < len(row_tokens):
                counts.update(row_tokens[position])
        if counts:
            observed = list(counts.values())
            cutoff = agp.natural_break_threshold(observed)
            selected = [
                token for token, count in counts.most_common()
                if cutoff is None or count >= cutoff
            ][:2]
            if selected:
                readable = [
                    token.replace("quality__", "").replace("__", " in ").replace("_", " ")
                    for token in selected
                ]
                highlights.append("quality evidence: " + ", ".join(readable))
    return unique_strings(highlights)


def matched_group_jaccard(positions: np.ndarray, alternate_labels: np.ndarray) -> float:
    source = set(int(position) for position in positions.tolist())
    best = 0.0
    for label in set(np.asarray(alternate_labels).tolist()):
        if label == -1:
            continue
        candidate = set(np.flatnonzero(alternate_labels == label).tolist())
        union = source | candidate
        if union:
            best = max(best, len(source & candidate) / len(union))
    return float(best)


def group_coherence(matrix: np.ndarray, positions: np.ndarray) -> float:
    members = matrix[positions]
    if len(members) <= 1:
        return 1.0
    centroid = sg.l2_normalize(members.mean(axis=0, keepdims=True))[0]
    similarities = members @ centroid
    return float(np.clip(np.mean((similarities + 1.0) / 2.0), 0.0, 1.0))


def group_distinctiveness(
    matrix: np.ndarray,
    labels: np.ndarray,
    label: int,
    positions: np.ndarray,
) -> float:
    own = sg.l2_normalize(matrix[positions].mean(axis=0, keepdims=True))[0]
    other_centroids = []
    for other in set(np.asarray(labels).tolist()):
        if other in {-1, label}:
            continue
        other_positions = np.flatnonzero(labels == other)
        if len(other_positions):
            other_centroids.append(sg.l2_normalize(matrix[other_positions].mean(axis=0, keepdims=True))[0])
    if not other_centroids:
        return 0.0
    nearest_similarity = max(float(own @ centroid) for centroid in other_centroids)
    return float(np.clip(1.0 - ((nearest_similarity + 1.0) / 2.0), 0.0, 1.0))


def utility_score(
    *,
    stability: float,
    coherence: float,
    distinctiveness: float,
    explainability: float,
    profile_confidence: float,
    coverage: float,
    view: str,
) -> float:
    del view  # Views no longer receive fixed actionability priors.
    coverage_score = float(min(coverage, 1.0 - coverage))
    components = [
        stability,
        coherence,
        distinctiveness,
        explainability,
        profile_confidence,
        coverage_score,
    ]
    return float(np.clip(np.median(components), 0.0, 1.0))


def calibrate_candidate_utilities(groups: list[MultiViewGroup]) -> list[MultiViewGroup]:
    """Rank each signal within its view, then combine by median without weights."""
    if not groups:
        return []
    calibrated = []
    for view_groups in _groups_by_view(groups).values():
        calibrated.extend(calibrate_view_candidate_utilities(view_groups))
    return calibrated


def analyst_signal_strength(supporting_fields: list[dict[str, Any]]) -> float:
    """How much this group tells an analyst 'this segment has a real issue', not just
    'this segment is different' or 'this segment has errors' on their own.

    A clean semantic story with no quality signal, and a quality signal with no
    coherent semantic story, both score 0 here: neither is the actionable finding an
    analyst is looking for. The two must combine. This is one of several ranking
    components (see calibrate_view_candidate_utilities) — scoring 0 here never
    disqualifies a group, it just stops it from being favored over one that does
    combine meaning and a genuine issue.
    """
    semantic_strengths = sorted(
        (
            safe_float(field.get("strength"), 0.0)
            for field in supporting_fields
            if field.get("kind") != "quality"
        ),
        reverse=True,
    )
    if not semantic_strengths:
        return 0.0
    semantic_strength = float(np.mean(semantic_strengths[:2]))

    enriched_quality_strengths = [
        safe_float(field.get("strength"), 0.0)
        for field in supporting_fields
        if field.get("kind") == "quality" and field.get("enriched")
    ]
    if not enriched_quality_strengths:
        return 0.0
    quality_strength = max(enriched_quality_strengths)

    return float(math.sqrt(max(semantic_strength, 0.0) * max(quality_strength, 0.0)))


def calibrate_view_candidate_utilities(groups: list[MultiViewGroup]) -> list[MultiViewGroup]:
    component_values = {
        "stability": [group.stability for group in groups],
        "coherence": [group.coherence for group in groups],
        "distinctiveness": [group.distinctiveness for group in groups],
        "explainability": [group.explainability for group in groups],
        "profileConfidence": [group.profileConfidence for group in groups],
        "coverage": [min(group.coverage, 1.0 - group.coverage) for group in groups],
        "analystSignal": [analyst_signal_strength(group.supportingFields) for group in groups],
    }
    percentiles = {
        name: agp.empirical_percentile_scores(values)
        for name, values in component_values.items()
    }
    profile_cutoff = agp.natural_break_threshold(component_values["profileConfidence"])
    result = []
    for index, group in enumerate(groups):
        score = float(np.median([values[index] for values in percentiles.values()]))
        caveats = list(group.caveats)
        if profile_cutoff is not None and group.profileConfidence < profile_cutoff:
            caveats.append("Contributing columns fall in the lower observed profiler-confidence group.")
        result.append(replace(
            group,
            utilityScore=round(score, 6),
            caveats=unique_strings(caveats),
        ))
    return result


def select_useful_candidates(
    groups: list[MultiViewGroup],
) -> tuple[list[MultiViewGroup], dict[str, Any]]:
    calibrated = calibrate_candidate_utilities(groups)
    if not calibrated:
        return [], {
            "utilityCutoff": None,
            "stabilityCutoff": None,
            "coverageUpperFence": None,
            "duplicateCoherenceCutoff": None,
            "source": "no candidates",
        }

    accepted = []
    policies = {}
    for view, view_groups in _groups_by_view(calibrated).items():
        utility_cutoff = agp.natural_break_threshold(group.utilityScore for group in view_groups)
        stability_cutoff = (
            None
            if view in {"quality", "duplicates"}
            else agp.natural_break_threshold(group.stability for group in view_groups)
        )
        duplicate_cutoff = (
            agp.natural_break_threshold(group.coherence for group in view_groups)
            if view == "duplicates"
            else None
        )
        coverage_fence = agp.robust_upper_fence(group.coverage for group in view_groups)
        selected_for_view = []
        for group in view_groups:
            if group.coverage >= 1.0:
                continue
            if coverage_fence is not None and group.coverage > coverage_fence:
                continue
            if utility_cutoff is not None and group.utilityScore < utility_cutoff:
                continue
            if stability_cutoff is not None and group.stability < stability_cutoff:
                continue
            if duplicate_cutoff is not None and group.coherence < duplicate_cutoff:
                continue
            selected_for_view.append(group)
        if not selected_for_view and view_groups:
            selected_for_view = [max(view_groups, key=lambda group: group.utilityScore)]
        accepted.extend(selected_for_view)
        policies[view] = {
            "utilityCutoff": utility_cutoff,
            "stabilityCutoff": stability_cutoff,
            "coverageUpperFence": coverage_fence,
            "duplicateCoherenceCutoff": duplicate_cutoff,
            "candidateScoreSeparation": agp.score_separation(
                group.utilityScore for group in view_groups
            ),
            "candidates": len(view_groups),
            "accepted": len(selected_for_view),
        }
    return accepted, {
        "source": "natural breaks and robust fences within each semantic view",
        "views": policies,
    }


def dedupe_candidate_groups(
    groups: list[MultiViewGroup],
) -> tuple[list[MultiViewGroup], float | None]:
    overlaps = []
    for index, group in enumerate(groups):
        row_set = set(group.rowIds)
        for other in groups[index + 1:]:
            if other.view != group.view:
                continue
            other_set = set(other.rowIds)
            union = row_set | other_set
            overlap = len(row_set & other_set) / len(union) if union else 0.0
            if overlap > 0:
                overlaps.append(overlap)
    overlap_cutoff = agp.natural_break_threshold(overlaps)

    kept = []
    kept_sets: list[tuple[str, set[int]]] = []
    for group in sorted(groups, key=lambda item: item.utilityScore, reverse=True):
        row_set = set(group.rowIds)
        duplicate = False
        for existing_view, existing in kept_sets:
            # The same cohort can be useful for different reasons. For example,
            # a regional group may also share a business segment. Suppress only
            # repeated explanations produced inside the same semantic view.
            if existing_view != group.view:
                continue
            union = row_set | existing
            overlap = len(row_set & existing) / len(union) if union else 0.0
            if overlap_cutoff is not None and overlap >= overlap_cutoff:
                duplicate = True
                break
        if not duplicate:
            kept.append(group)
            kept_sets.append((group.view, row_set))
    return kept, overlap_cutoff


def group_semantic_specificity(group: MultiViewGroup) -> float:
    """How strongly the named semantic fields characterize this group.

    Uses the top two non-quality supporting-field strengths (a numeric effect size, a
    categorical concentration, an exact duplicate match, etc.). Different families live on
    different raw scales, which is fine: rank_groups_semantic_first percentile-normalizes
    across the whole merged list before comparing, so scale differences wash out.
    """
    strengths = sorted(
        (
            safe_float(field.get("strength"), 0.0)
            for field in group.supportingFields
            if field.get("kind") != "quality"
        ),
        reverse=True,
    )
    if not strengths:
        return 0.0
    return float(np.mean(strengths[:2]))


def rank_groups_semantic_first(
    groups: list[MultiViewGroup], *, limit: int
) -> list[MultiViewGroup]:
    """One merged, semantic-first ranking across every group regardless of view.

    Semantic meaningfulness dominates: the primary key is a percentile blend of how
    specific the description is, whether it pairs meaning with a real quality issue
    (analyst signal), and how distinct/explainable the cohort is. Cluster geometry
    (stability, coherence, coverage — the old utilityScore) only breaks ties. This is a
    lexicographic priority, not a hand-tuned weighted sum, so it keeps the project's
    "no arbitrary weights" stance while making semantics the star.
    """
    if not groups:
        return []
    specificity = agp.empirical_percentile_scores(
        [group_semantic_specificity(group) for group in groups]
    )
    analyst = agp.empirical_percentile_scores(
        [analyst_signal_strength(group.supportingFields) for group in groups]
    )
    distinct = agp.empirical_percentile_scores([group.distinctiveness for group in groups])
    explain = agp.empirical_percentile_scores([group.explainability for group in groups])
    semantic_scores = [
        float(np.median([specificity[index], analyst[index], distinct[index], explain[index]]))
        for index in range(len(groups))
    ]
    # Similarity outranks equality. Semantic-quality groups cluster rows that MEAN the same
    # thing (European rows with similar salaries land together via Continent + measures),
    # which is what a user exploring data quality wants first. Near-duplicate groups match
    # rows that are EXACTLY equal on their non-key fields — genuinely useful as a
    # record-linkage advisory, but they trivially score maximum specificity (every field is
    # an exact match), which would otherwise float small exact-match cohorts above large,
    # meaningful clusters. A hard tier keeps every semantic-quality cluster above every
    # near-duplicate group; scores only order within a tier.
    def view_tier(group: MultiViewGroup) -> int:
        return 0 if group.view == "duplicates" else 1

    order = sorted(
        range(len(groups)),
        key=lambda index: (
            view_tier(groups[index]),
            semantic_scores[index],
            groups[index].utilityScore,
        ),
        reverse=True,
    )
    ranked = []
    for index in order[:limit]:
        ranked.append(replace(groups[index], semanticScore=round(semantic_scores[index], 6)))
    return ranked


def _groups_by_view(groups: list[MultiViewGroup]) -> dict[str, list[MultiViewGroup]]:
    result: dict[str, list[MultiViewGroup]] = defaultdict(list)
    for group in groups:
        result[group.view].append(group)
    return result


def mean_profile_confidence(columns: list[str], profile_map: dict[str, dict]) -> float:
    values = [profile_map[column]["confidence"] for column in columns if column in profile_map]
    if values:
        return float(np.mean(values))
    observed = [
        profile["confidence"]
        for profile in profile_map.values()
        if math.isfinite(profile.get("confidence", math.nan))
    ]
    return float(np.median(observed)) if observed else 0.0


def column_token(column: str) -> str:
    tokens = sg.tokenize(column)
    return "_".join(tokens) if tokens else "column"


def safe_float(value, default: float) -> float:
    try:
        numeric = float(value)
        return numeric if math.isfinite(numeric) else default
    except (TypeError, ValueError):
        return default


def unique_strings(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        cleaned = str(value).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def view_run(
    view: str,
    status: str,
    algorithm: str,
    candidates: int,
    note: str,
    *,
    diagnostics: dict[str, Any] | None = None,
) -> dict:
    result = {
        "id": view,
        "status": status,
        "algorithm": algorithm,
        "candidates": int(candidates),
        "note": note,
    }
    if diagnostics:
        result["adaptiveDiagnostics"] = diagnostics
    return result


def empty_multiview_response(total_rows: int) -> dict[str, Any]:
    return {
        "strategy": "profiler_guided_semantic_quality",
        "effectiveStrategy": "profiler_guided_semantic_quality",
        "compatibilityStrategy": "profiler_guided_multi_view",
        "similarityTool": MULTI_VIEW_TOOL_NAME,
        "similarityDescription": "No usable rows were available for profiler-guided grouping.",
        "sampleRows": 0,
        "requestedSampleRows": 0,
        "totalRows": int(total_rows),
        "samplingMethod": "deterministic_random_without_replacement",
        "samplingSeed": MULTI_VIEW_SAMPLE_SEED,
        "baselineErrorRate": 0.0,
        "errorRows": 0,
        "groups": [],
        "views": [
            {
                "id": view,
                "label": definition["label"],
                "description": definition["description"],
                "status": "unavailable",
                "algorithm": "none",
                "columns": [],
                "candidatesGenerated": 0,
                "groupsShown": 0,
                "note": "No usable rows were available.",
            }
            for view, definition in (
                (view_id, VIEW_DEFINITIONS[view_id])
                for view_id in ("semantic_quality", "duplicates")
            )
        ],
        "representation": {
            "mode": "single_combined_semantic_quality_matrix",
            "activeBlocks": [],
            "inactiveBlocks": [*SEMANTIC_BLOCK_ORDER, "quality"],
            "blocks": [],
            "featureDimensions": 0,
            "semanticColumns": [],
            "semanticColumnAssignments": {},
            "qualityColumns": [],
            "qualitySignalRows": 0,
            "qualitySignalRate": 0.0,
            "qualitySignalTypes": [],
            "normalization": "row L2 within each evidence block, then row L2 after concatenation",
            "manualBlockWeights": False,
            "humanLabelsUsed": False,
            "routingPolicy": "mutually exclusive profiler-role routing with a value-driven generic fallback",
        },
        "profileSummary": {
            "columnsProfiled": 0,
            "roleCounts": {},
            "excludedIdentifierColumns": [],
            "excludedLowConfidenceColumns": [],
            "excludedStructuredTextColumns": [],
            "userOverridesApplied": [],
        },
    }
