"""
Converts the current datastate data into JSON the view can use
"""

"""
Refactored to use jacobs new backend sql files March 11,2026 - db_functions_sql.py, execute_sql.py, filtering_sql.py 
"""
import time
from collections import Counter

import pandas as pd
from sqlalchemy import text

from app.db_utils.execute_sql import fetch_sql
from app.server_utils.service_helpers import _validate_identifier, is_categorical
from app.server_utils.dataset_processing_metadata import get_dataset_processing_metadata
from app.wrangle_operations.sql_utils import quote_identifier
from profiling.column_profiling import GEOGRAPHY_PROFILE_ROLES, profile_columns


PROFILE_SAMPLE_ROWS = 10000
PROFILE_REVIEW_COMPARISON_ROWS = 500
PROFILE_SAMPLE_SEED = 20260714
PROFILE_PROGRESSIVE_STEPS = (500, 1000, 5000, 10000)
PROFILE_BALANCED_MIN_AVG_CONFIDENCE = 0.86
PROFILE_BALANCED_MIN_COLUMN_CONFIDENCE = 0.80
PROFILE_BALANCED_MAX_UNCERTAIN_COLUMNS = 2


PROFILE_ROLE_LABELS = {
    "identifier": "primary-key candidate",
    "primary_key": "primary-key candidate",
    "quasi_identifier": "possible identifier",
    "datetime": "date/time field",
    "datetime_high_uniqueness": "high-uniqueness timestamp",
    "datetime_identifier": "timestamp-like identifier",
    "datetime_category": "date/time field",
    "numeric_measure": "numeric measure",
    "numeric_code_category": "numeric code category",
    "binary_category": "binary category",
    "categorical": "categorical field",
    "free_text": "free-text field",
    "vector_blob": "vector/blob text",
    "geographic_coordinate": "geographic coordinate",
    "geography_location": "geography/location field",
    "high_uniqueness_location_field": "high-uniqueness location field",
    "location_name": "location name",
    "postal_code": "postal code",
    "airport_code": "airport code",
    "country_code": "country code",
}

PROFILE_ROLE_FAMILIES = {
    "identifier": "identifier",
    "primary_key": "identifier",
    "quasi_identifier": "identifier",
    "datetime": "temporal",
    "datetime_high_uniqueness": "temporal",
    "datetime_identifier": "temporal",
    "datetime_category": "temporal",
    "numeric_measure": "numeric",
    "numeric_code_category": "categorical",
    "binary_category": "categorical",
    "categorical": "categorical",
    "free_text": "text",
    "vector_blob": "structured text",
    "geographic_coordinate": "geography",
    "geography_location": "geography",
    "high_uniqueness_location_field": "geography",
    "location_name": "geography",
    "postal_code": "geography",
    "airport_code": "geography",
    "country_code": "geography",
}

# These are deliberately limited to Buckaroo's explainable profile roles. A
# reviewer can correct a decision, but cannot store arbitrary display text as a
# role that later experiments would be unable to score consistently.
MANUAL_OVERRIDE_ROLE_OPTIONS = tuple(PROFILE_ROLE_LABELS.keys())

# A safeguard can influence classification without creating review work.
# Only roles that are inherently easy to confuse with row identity are always
# review-sensitive; ordinary country/latitude/longitude fields stay quiet.
PROFILE_ALWAYS_REVIEW_ROLES = frozenset({
    "high_uniqueness_location_field",
    "datetime_high_uniqueness",
    "datetime_identifier",
})


def resolve_detector_coverage(total_rows, processing_metadata):
    """Return detector coverage without mixing sampled and full denominators."""
    total_rows = max(0, int(total_rows or 0))
    if not processing_metadata:
        return total_rows, True, total_rows

    detector_is_complete = bool(processing_metadata.get("detector_is_complete"))
    raw_detector_rows = processing_metadata.get("detector_rows")
    detector_rows = total_rows if raw_detector_rows is None else max(0, int(raw_detector_rows))
    detector_rows = min(detector_rows, total_rows)
    if detector_is_complete:
        detector_rows = total_rows
    denominator = total_rows if detector_is_complete else detector_rows
    return detector_rows, detector_is_complete, denominator


def get_profile_role_overrides(tablename, engine):
    """Return persisted human corrections for one uploaded dataset."""
    _validate_identifier(tablename)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS profile_role_overrides (
                table_name TEXT NOT NULL,
                column_name TEXT NOT NULL,
                role TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (table_name, column_name)
            )
        """))
        rows = connection.execute(
            text("""
                SELECT column_name, role, note
                FROM profile_role_overrides
                WHERE table_name = :table_name
            """),
            {"table_name": tablename},
        ).mappings().all()

    return {
        row["column_name"]: {
            "role": row["role"],
            "roleLabel": profile_role_label(row["role"]),
            "note": row["note"],
        }
        for row in rows
    }


def save_profile_role_override(tablename, column_name, role, note, engine):
    """Save one reviewer correction, replacing a prior correction if present."""
    _validate_identifier(tablename)
    cleaned_column = safe_string(column_name).strip()
    cleaned_role = safe_string(role).strip().lower()
    cleaned_note = safe_string(note).strip()

    if not cleaned_column:
        raise ValueError("A column name is required for a profile correction.")
    if cleaned_role not in MANUAL_OVERRIDE_ROLE_OPTIONS:
        raise ValueError("That correction is not a supported Buckaroo profile role.")
    if len(cleaned_note) > 1000:
        raise ValueError("Correction notes must be 1,000 characters or fewer.")

    available_columns = {item["name"] for item in get_table_columns_with_types(tablename, engine)}
    if cleaned_column not in available_columns:
        raise ValueError("The selected column does not belong to the active dataset.")

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS profile_role_overrides (
                table_name TEXT NOT NULL,
                column_name TEXT NOT NULL,
                role TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (table_name, column_name)
            )
        """))
        connection.execute(
            text("""
                INSERT INTO profile_role_overrides (table_name, column_name, role, note)
                VALUES (:table_name, :column_name, :role, :note)
                ON CONFLICT (table_name, column_name) DO UPDATE
                SET role = EXCLUDED.role,
                    note = EXCLUDED.note,
                    updated_at = CURRENT_TIMESTAMP
            """),
            {
                "table_name": tablename,
                "column_name": cleaned_column,
                "role": cleaned_role,
                "note": cleaned_note,
            },
        )

    return {"role": cleaned_role, "roleLabel": profile_role_label(cleaned_role), "note": cleaned_note}


def delete_profile_role_override(tablename, column_name, engine):
    """Remove a reviewer correction and reveal Buckaroo's original role again."""
    _validate_identifier(tablename)
    cleaned_column = safe_string(column_name).strip()
    if not cleaned_column:
        raise ValueError("A column name is required for a profile correction.")

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS profile_role_overrides (
                table_name TEXT NOT NULL,
                column_name TEXT NOT NULL,
                role TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (table_name, column_name)
            )
        """))
        connection.execute(text("""
            DELETE FROM profile_role_overrides
            WHERE table_name = :table_name AND column_name = :column_name
        """), {"table_name": tablename, "column_name": cleaned_column})


def get_default_attributes_from_rankings(tablename, engine):
    """
    Fetch top 3 attributes from pre-computed rankings table.
    :param tablename: Name of the data table
    :param engine: SQLAlchemy engine
    :return: List of top 3 attribute names
    """
    try:
        _validate_identifier(tablename)
        query = f'SELECT attribute FROM "rankings_{tablename}" ORDER BY rank ASC LIMIT 3'
        rows = fetch_sql(query, False, engine)
        return [row[0] for row in rows] if rows else []
    except Exception as e:
        print(f"Error fetching rankings for table '{tablename}': {e}")
        return []



def generate_complete_json(tablename):
    """
    Generate a complete JSON representation of the current data state.

    This intentionally uses SQL aggregates instead of SELECT * + pandas so the
    first page load after a CSV upload does not pull the whole dataset back out
    of PostgreSQL.
    :param tablename: name of the table
    :return: JSON representation of the data state
    """
    from app import engine

    if not tablename:
        return {
            "columnErrors": {},
            "attributes": [],
            "attributeDistributions": {},
            "attributeProfiles": {},
            "defaultAttributes": [],
        }

    _validate_identifier(tablename)
    start = time.perf_counter()

    columns_with_types = get_table_columns_with_types(tablename, engine)
    attributes = [row["name"] for row in columns_with_types]
    total_rows = get_table_row_count(tablename, engine)
    processing_metadata = get_dataset_processing_metadata(engine, tablename)
    detector_rows, detector_is_complete, error_rate_denominator = resolve_detector_coverage(
        total_rows,
        processing_metadata,
    )
    column_errors = build_column_errors(tablename, error_rate_denominator, engine)
    default_attributes = get_default_attributes_from_rankings(tablename, engine)
    distribution_columns = choose_distribution_columns(
        attributes,
        column_errors,
        default_attributes,
    )
    sample_rows = 10000 if total_rows > 10000 else None
    attribute_distributions = build_attribute_distributions_sql(
        tablename,
        columns_with_types,
        engine,
        distribution_columns,
        sample_rows=sample_rows,
    )
    profile_sample_rows = PROFILE_SAMPLE_ROWS if total_rows > PROFILE_SAMPLE_ROWS else None
    attribute_profiles = build_attribute_profiles_sql(
        tablename,
        columns_with_types,
        engine,
        sample_rows=profile_sample_rows,
        total_rows=total_rows,
    )
    profile_overrides = get_profile_role_overrides(tablename, engine)
    for column_name, override in profile_overrides.items():
        if column_name not in attribute_profiles:
            continue
        attribute_profiles[column_name].update({
            "userOverrideRole": override["role"],
            "userOverrideLabel": override["roleLabel"],
            "userOverrideFamily": profile_role_family(override["role"]),
            "userOverrideNote": override["note"],
        })

    print(
        f"Generated attribute summaries for {tablename} in "
        f"{time.perf_counter() - start:.3f}s "
        f"({len(attribute_distributions)}/{len(attributes)} distributions"
        f"{f', sampled {sample_rows} rows' if sample_rows else ''}; "
        f"{len(attribute_profiles)}/{len(attributes)} profiles"
        f"{f', profiled {profile_sample_rows} rows' if profile_sample_rows else ''})"
    )

    return {
        "columnErrors": column_errors,
        "attributes": attributes,
        "attributeDistributions": attribute_distributions,
        "attributeProfiles": attribute_profiles,
        "defaultAttributes": default_attributes,
        "attributeDistributionsSampled": sample_rows is not None,
        "attributeDistributionSampleRows": sample_rows,
        "attributeProfilesSampled": profile_sample_rows is not None,
        "attributeProfileSampleRows": profile_sample_rows,
        "totalRows": total_rows,
        "detectorRows": detector_rows,
        "detectorIsComplete": detector_is_complete,
        "errorRatesSampled": not detector_is_complete,
        "errorRateDenominatorRows": error_rate_denominator,
        "detectorSamplingMethod": (
            processing_metadata.get("detector_sampling_method")
            if processing_metadata
            else "legacy_unknown"
        ),
    }


def get_table_columns_with_types(tablename, engine):
    rows = fetch_sql(
        f"""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = '{tablename}'
        ORDER BY ordinal_position
        """,
        False,
        engine,
    )
    return [{"name": row[0], "data_type": row[1]} for row in rows] if rows else []


def get_table_row_count(tablename, engine):
    rows = fetch_sql(f"SELECT COUNT(*) FROM {quote_identifier(tablename)}", False, engine)
    return int(rows[0][0]) if rows else 0


def build_column_errors(tablename, inspected_rows, engine):
    """Calculate error rates against rows actually inspected by detectors."""
    if inspected_rows <= 0:
        return {}

    rows = fetch_sql(
        f"""
        SELECT column_id, error_type, COUNT(*)::float / {int(inspected_rows)} AS pct
        FROM {quote_identifier("errors_" + tablename)}
        GROUP BY column_id, error_type
        """,
        False,
        engine,
    )

    result = {}
    for column_id, error_type, pct in rows or []:
        if pct and float(pct) > 0:
            result.setdefault(str(column_id).strip(), {})[str(error_type)] = float(pct)
    return result


def is_numeric_sql_type(data_type):
    return data_type in {
        "integer",
        "bigint",
        "numeric",
        "real",
        "double precision",
        "smallint",
    }


def choose_distribution_columns(attributes, column_errors, default_attributes, max_columns=8):
    prioritized = []

    def add_column(col):
        if col in attributes and col not in prioritized:
            prioritized.append(col)

    for col in default_attributes or []:
        add_column(col)

    by_error_count = sorted(
        attributes,
        key=lambda col: sum(column_errors.get(col, {}).values()),
        reverse=True,
    )
    for col in by_error_count:
        add_column(col)
        if len(prioritized) >= max_columns:
            break

    for col in attributes:
        add_column(col)
        if len(prioritized) >= max_columns:
            break

    return set(prioritized)


def build_attribute_distributions_sql(tablename, columns_with_types, engine, selected_columns=None, sample_rows=None):
    distributions = {}
    selected_columns = set(selected_columns or [column["name"] for column in columns_with_types])
    with engine.connect() as conn:
        for column in columns_with_types:
            col_name = column["name"]
            if col_name not in selected_columns:
                continue
            if is_numeric_sql_type(column["data_type"]):
                distributions[col_name] = get_numeric_stats_sql(conn, tablename, col_name, sample_rows)
            else:
                distributions[col_name] = get_categorical_stats_sql(conn, tablename, col_name, sample_rows)
    return distributions


def column_source_sql(tablename, column, sample_rows=None):
    column_sql = quote_identifier(column)
    table_sql = quote_identifier(tablename)
    if sample_rows:
        return (
            f"(SELECT {column_sql} FROM {table_sql} "
            f"ORDER BY md5(COALESCE({quote_identifier('ID')}::text, '') || '{PROFILE_SAMPLE_SEED}') "
            f"LIMIT {int(sample_rows)}) AS sample"
        )
    return table_sql


def get_categorical_stats_sql(conn, tablename, column, sample_rows=None):
    column_sql = quote_identifier(column)
    source_sql = column_source_sql(tablename, column, sample_rows)
    categories = conn.exec_driver_sql(
        f"SELECT COUNT(DISTINCT COALESCE({column_sql}::text, 'N/A')) FROM {source_sql}"
    ).scalar()
    mode = conn.exec_driver_sql(
        f"""
        SELECT COALESCE({column_sql}::text, 'N/A') AS value
        FROM {source_sql}
        GROUP BY value
        ORDER BY COUNT(*) DESC, value ASC
        LIMIT 1
        """
    ).scalar()
    return {
        "categorical": {
            "categories": int(categories or 0),
            "mode": mode if mode is not None else "N/A",
        }
    }


def get_numeric_stats_sql(conn, tablename, column, sample_rows=None):
    column_sql = quote_identifier(column)
    source_sql = column_source_sql(tablename, column, sample_rows)
    row = conn.exec_driver_sql(
        f"""
        SELECT
            AVG({column_sql}::double precision),
            MIN({column_sql}),
            MAX({column_sql})
        FROM {source_sql}
        WHERE {column_sql} IS NOT NULL
        """
    ).first()

    mean, min_value, max_value = row if row else (None, None, None)
    return {
        "numeric": {
            "mean": float(mean) if mean is not None else 0,
            "min": min_value if min_value is not None else 0,
            "max": max_value if max_value is not None else 0,
        }
    }


def build_attribute_profiles_sql(
        tablename,
        columns_with_types,
        engine,
        sample_rows=None,
        total_rows=None,
):
    column_names = [column["name"] for column in columns_with_types if column["name"] != "ID"]
    if not column_names:
        return {}

    column_sql = ", ".join(quote_identifier(column) for column in column_names)
    query = f"SELECT {column_sql} FROM {quote_identifier(tablename)}"
    query_params = None
    if sample_rows:
        available_columns = {column["name"] for column in columns_with_types}
        if "ID" in available_columns:
            query += (
                f" ORDER BY md5(COALESCE({quote_identifier('ID')}::text, '') || :sample_seed)"
                f" LIMIT {int(sample_rows)}"
            )
            query_params = {"sample_seed": str(PROFILE_SAMPLE_SEED)}
        else:
            query += f" ORDER BY random() LIMIT {int(sample_rows)}"

    try:
        frame = pd.read_sql_query(text(query), engine, params=query_params)
        return build_attribute_profiles(frame, total_rows=total_rows)
    except Exception as exc:
        raise RuntimeError(
            f"Unable to build profiler summaries for table '{tablename}'."
        ) from exc


def build_attribute_profiles(df, total_rows=None):
    """
    Build explainable profiler metadata for the attribute summary UI.

    The frontend uses this to show the role Buckaroo chose, the confidence,
    warnings, and the top alternate candidate roles for each column.
    """
    if df.empty and len(df.columns) == 0:
        return {}

    column_profile, selected_rows, profile_history = adaptive_profile_dataframe(df)
    available_rows = max(len(df), int(total_rows or 0))
    selected_df = df.iloc[:selected_rows].copy()
    initial_records = {}

    # A smaller initial pass lets the UI identify columns whose decision changed
    # after Buckaroo examined more available rows. It is a review signal, not a
    # claim that either pass is semantic ground truth.
    comparison_rows = min(PROFILE_REVIEW_COMPARISON_ROWS, selected_rows)
    if comparison_rows < selected_rows:
        initial_profile, _initial_roles = profile_columns(df.iloc[:comparison_rows].copy())
        initial_records = {
            str(initial_record.get("column")): initial_record
            for initial_record in initial_profile.to_dict("records")
            if initial_record.get("column")
        }

    profiles = {}
    for record in column_profile.to_dict("records"):
        column = record.get("column")
        if column:
            initial_record = initial_records.get(str(column))
            profile_role = safe_string(record.get("profile_role") or record.get("role"))
            chosen_candidate_role = safe_string(record.get("chosen_candidate_role"))
            initial_profile_role = safe_string(
                initial_record.get("profile_role") or initial_record.get("role")
            ) if initial_record else ""
            initial_candidate_role = safe_string(
                initial_record.get("chosen_candidate_role")
            ) if initial_record else ""
            changed_after_more_sampling = bool(
                initial_record
                and (
                    profile_role != initial_profile_role
                    or chosen_candidate_role != initial_candidate_role
                )
            )
            formatted = format_attribute_profile_record(record, selected_df[str(column)])
            confidence_score = formatted.get("confidenceScore")
            routine_geography = bool(
                formatted.get("roleFamily") == "geography"
                and not formatted.get("isSemanticallySensitive")
                and confidence_score is not None
                and confidence_score >= 0.80
            )
            if routine_geography:
                formatted["reviewReasons"] = []
            ambiguous = bool(
                (formatted.get("needsMoreSampling") and not routine_geography)
                or (
                    not routine_geography
                    and
                    formatted.get("candidateConfidenceGap") is not None
                    and formatted["candidateConfidenceGap"] < 0.08
                )
            )
            more_rows_available = selected_rows < available_rows
            profiled_all_rows = not more_rows_available

            if profiled_all_rows and ambiguous:
                full_data_state = "ambiguous_after_all_rows"
                full_data_state_label = "Ambiguous after examining all rows"
                sampling_action = "no_more_rows_available"
            elif profiled_all_rows:
                full_data_state = "stable_after_all_rows"
                full_data_state_label = "Stable after examining all rows"
                sampling_action = "no_more_sampling_needed"
            elif ambiguous:
                full_data_state = "provisional_more_rows_available"
                full_data_state_label = "Provisional; more rows are available"
                sampling_action = "sample_more"
            else:
                full_data_state = "stable_early_stop"
                full_data_state_label = "Stable enough to stop early"
                sampling_action = "stop_early"

            if profiled_all_rows and ambiguous:
                formatted["negativeEvidence"] = unique_evidence([
                    *(formatted.get("negativeEvidence") or []),
                    "All available rows were examined; remaining uncertainty is semantic, not a shortage of rows.",
                ], limit=6)

            formatted.update(
                {
                    "changedAfterMoreSampling": changed_after_more_sampling,
                    "initialProfileRole": initial_profile_role,
                    "initialRoleLabel": profile_role_label(initial_profile_role),
                    "initialProfileRows": comparison_rows if initial_record else None,
                    "currentProfileRows": selected_rows,
                    "availableProfileRows": available_rows,
                    "profileStoppedEarly": selected_rows < available_rows,
                    "profiledAllRows": profiled_all_rows,
                    "moreRowsAvailable": more_rows_available,
                    "classificationAmbiguous": ambiguous,
                    "samplingExhausted": profiled_all_rows and ambiguous,
                    "fullDataState": full_data_state,
                    "fullDataStateLabel": full_data_state_label,
                    "needsMoreSampling": ambiguous and more_rows_available,
                    "adaptiveSamplingAction": sampling_action,
                    "profileSamplingMethod": "deterministic_nested_random_prefix",
                    "profileSamplingHistory": profile_history,
                }
            )
            profiles[str(column)] = formatted
    return profiles


def adaptive_profile_dataframe(df):
    """Profile nested prefixes and stop when the balanced policy is defensible."""
    if df.empty:
        profile, _roles = profile_columns(df)
        return profile, len(df), []

    steps = sorted({min(len(df), step) for step in PROFILE_PROGRESSIVE_STEPS if step > 0})
    if len(df) not in steps:
        steps.append(len(df))

    history = []
    selected_profile = pd.DataFrame()
    selected_rows = len(df)
    for rows in steps:
        selected_profile, _roles = profile_columns(df.iloc[:rows].copy())
        confidence = (
            pd.to_numeric(selected_profile["confidence_score"], errors="coerce").fillna(0)
            if "confidence_score" in selected_profile
            else pd.Series(dtype="float64")
        )
        needs_more = (
            selected_profile["needs_more_sampling"]
            if "needs_more_sampling" in selected_profile
            else None
        )
        uncertain_count = (
            int(needs_more.fillna(True).astype(bool).sum())
            if needs_more is not None
            else len(selected_profile)
        )
        avg_confidence = float(confidence.mean()) if not confidence.empty else 0.0
        min_confidence = float(confidence.min()) if not confidence.empty else 0.0
        stop = bool(
            rows >= min(PROFILE_REVIEW_COMPARISON_ROWS, len(df))
            and avg_confidence >= PROFILE_BALANCED_MIN_AVG_CONFIDENCE
            and min_confidence >= PROFILE_BALANCED_MIN_COLUMN_CONFIDENCE
            and uncertain_count <= PROFILE_BALANCED_MAX_UNCERTAIN_COLUMNS
        )
        history.append(
            {
                "sampleRows": rows,
                "averageConfidence": round(avg_confidence, 3),
                "minimumConfidence": round(min_confidence, 3),
                "uncertainColumns": uncertain_count,
                "stopped": stop or rows >= len(df),
            }
        )
        selected_rows = rows
        if stop or rows >= len(df):
            break

    return selected_profile, selected_rows, history


def format_attribute_profile_record(record, values=None):
    profile_role = str(record.get("profile_role") or record.get("role") or "unknown")
    candidate_roles = record.get("candidate_roles")
    if not isinstance(candidate_roles, list):
        candidate_roles = []
    display_candidate_roles = candidate_roles[:4]
    chosen_candidate_role = safe_string(record.get("chosen_candidate_role"))
    if chosen_candidate_role and not any(
        isinstance(candidate, dict)
        and safe_string(candidate.get("role")) == chosen_candidate_role
        for candidate in display_candidate_roles
    ):
        chosen_candidate = next(
            (
                candidate for candidate in candidate_roles
                if isinstance(candidate, dict)
                and safe_string(candidate.get("role")) == chosen_candidate_role
            ),
            None,
        )
        if chosen_candidate:
            display_candidate_roles = [*display_candidate_roles[:3], chosen_candidate]

    formatted_candidates = [
        {
            "role": safe_string(candidate.get("role")),
            "label": profile_role_label(safe_string(candidate.get("role"))),
            "roleFamily": profile_role_family(safe_string(candidate.get("role"))),
            "roleFamilyLabel": profile_role_family(safe_string(candidate.get("role"))).title(),
            "confidence": safe_float(candidate.get("confidence")),
            "evidenceStrength": safe_float(candidate.get("evidence_strength")),
            "confidenceBasis": safe_string(candidate.get("confidence_basis")),
            "chosen": safe_bool(candidate.get("chosen")),
            "reason": safe_string(candidate.get("reason")),
        }
        for candidate in display_candidate_roles
        if isinstance(candidate, dict)
    ]
    supporting_examples, conflicting_examples = build_profile_examples(
        record,
        profile_role,
        values,
    )
    positive_evidence, negative_evidence = build_profile_evidence_lists(
        record,
        profile_role,
        candidate_roles,
    )
    semantic_review_required = profile_requires_semantic_review(record, profile_role)
    review_reasons = build_profile_review_reasons(
        record,
        profile_role,
        semantic_review_required,
    )

    return {
        "role": safe_string(record.get("role")),
        "profileRole": profile_role,
        "roleLabel": profile_role_label(profile_role),
        "roleFamily": profile_role_family(profile_role),
        "roleFamilyLabel": profile_role_family(profile_role).title(),
        "roleSubtype": profile_role,
        "roleSubtypeLabel": profile_role_label(profile_role),
        "confidence": safe_string(record.get("confidence")),
        "confidenceScore": safe_float(record.get("confidence_score")),
        # ``warning`` remains for existing experiment exports.  New UI code
        # must use dataWarning for actual quality problems and reviewReasons
        # for uncertainty or semantically sensitive-but-valid fields.
        "warning": safe_string(record.get("warning")),
        "adaptiveWarning": safe_string(record.get("adaptive_warning")),
        "dataWarning": safe_string(record.get("data_warning")),
        "reviewReasons": review_reasons,
        "isSemanticallySensitive": semantic_review_required,
        "semanticSafeguardApplied": (
            profile_role in GEOGRAPHY_PROFILE_ROLES
            or profile_role in {"datetime_high_uniqueness", "datetime_identifier"}
        ),
        "reason": safe_string(record.get("reason")),
        "sampleReliability": safe_string(record.get("sample_reliability")),
        "sampleUncertaintyMargin": safe_float(record.get("sample_uncertainty_margin")),
        "needsMoreSampling": safe_bool(record.get("needs_more_sampling")),
        "adaptiveSamplingAction": safe_string(record.get("adaptive_sampling_action")),
        "adaptiveSamplingReason": safe_string(record.get("adaptive_sampling_reason")),
        "topCandidateRole": safe_string(record.get("top_candidate_role")),
        "topCandidateConfidence": safe_float(record.get("top_candidate_confidence")),
        "secondCandidateRole": safe_string(record.get("second_candidate_role")),
        "secondCandidateConfidence": safe_float(record.get("second_candidate_confidence")),
        "chosenCandidateRole": chosen_candidate_role,
        "chosenCandidateConfidence": safe_float(record.get("chosen_candidate_confidence")),
        "candidateConfidenceGap": safe_float(record.get("candidate_confidence_gap")),
        "candidateRoles": formatted_candidates,
        "supportingExamples": supporting_examples,
        "conflictingExamples": conflicting_examples,
        "positiveEvidence": positive_evidence,
        "negativeEvidence": negative_evidence,
    }


def build_profile_evidence_lists(record, profile_role, candidate_roles):
    positive = []
    negative = []

    reason = safe_string(record.get("reason"))
    if reason:
        positive.append(reason)

    add_metric_evidence(positive, negative, record, profile_role)
    add_name_hint_evidence(positive, record, profile_role)
    add_candidate_evidence(positive, negative, candidate_roles, profile_role)

    data_warning = safe_string(record.get("data_warning"))
    if data_warning:
        for part in data_warning.split(";"):
            cleaned = part.strip()
            if cleaned:
                negative.append(cleaned)

    adaptive_reason = safe_string(record.get("adaptive_sampling_reason"))
    if safe_bool(record.get("needs_more_sampling")) and adaptive_reason:
        negative.append(adaptive_reason)

    if not positive:
        positive.append("Buckaroo found enough available values to make a provisional profile decision.")
    if not negative:
        negative.append("No strong conflicting evidence was found for this column.")

    return unique_evidence(positive, limit=6), unique_evidence(negative, limit=6)


def profile_requires_semantic_review(record, profile_role):
    """Return whether semantic meaning creates an actionable review case."""
    if profile_role in PROFILE_ALWAYS_REVIEW_ROLES:
        return True
    if profile_role not in GEOGRAPHY_PROFILE_ROLES:
        return False

    candidate_roles = record.get("candidate_roles")
    if not isinstance(candidate_roles, list):
        candidate_roles = []
    has_strong_key_evidence = any(
        isinstance(candidate, dict)
        and safe_string(candidate.get("role")) in {"identifier", "primary_key", "quasi_identifier"}
        and (safe_float(candidate.get("confidence")) or 0.0) >= 0.80
        for candidate in candidate_roles
    )
    return bool(has_strong_key_evidence)


def build_profile_review_reasons(record, profile_role, semantic_review_required=None):
    """Return non-error reasons a user may want to inspect a profile.

    This deliberately does not reuse ``data_warning``.  A location, timestamp,
    or low-margin result can need a human decision even when every data value is
    valid and internally consistent.
    """
    reasons = []
    if semantic_review_required is None:
        semantic_review_required = profile_requires_semantic_review(record, profile_role)

    if semantic_review_required and profile_role in GEOGRAPHY_PROFILE_ROLES:
        reasons.append(
            "This location field has identity-like evidence; review it before using it as a row or join key."
        )
    elif semantic_review_required and profile_role in {"datetime_high_uniqueness", "datetime_identifier"}:
        reasons.append(
            "High-uniqueness timestamps can be valid event data, but should be reviewed before being used as row identity."
        )

    if safe_bool(record.get("needs_more_sampling")):
        adaptive_warning = safe_string(record.get("adaptive_warning"))
        if adaptive_warning:
            reasons.extend(part.strip() for part in adaptive_warning.split(";") if part.strip())
        adaptive_reason = safe_string(record.get("adaptive_sampling_reason"))
        if adaptive_reason:
            reasons.append(adaptive_reason)

    return unique_evidence(reasons, limit=4)


def build_profile_examples(record, profile_role, values=None, limit=4):
    """Return actual values that support or challenge a profile decision.

    The UI keeps examples separate from rule prose.  A user can therefore check
    the data first, then read Buckaroo's explanation only when it is useful.
    """
    series = clean_profile_values(values)
    if series.empty:
        return [], []

    text = series.astype(str).str.strip()
    numeric = pd.to_numeric(series, errors="coerce")
    date_like = parse_date_like_values(text)

    if profile_role == "numeric_measure":
        return sample_display_values(series[numeric.notna()], limit), sample_display_values(series[numeric.isna()], limit)

    if profile_role in {"datetime_category", "datetime_high_uniqueness", "datetime_identifier"}:
        return sample_display_values(series[date_like], limit), sample_display_values(series[~date_like], limit)

    if profile_role in {"identifier", "quasi_identifier"}:
        duplicated = text.duplicated(keep=False)
        return sample_display_values(series[~duplicated], limit), sample_display_values(series[duplicated], limit)

    if profile_role in {"categorical", "binary_category", "numeric_code_category"}:
        counts = text.value_counts()
        repeated = text.map(counts).ge(2)
        rare = text.map(counts).eq(1)
        return sample_display_values(series[repeated], limit), sample_display_values(series[rare], limit)

    if profile_role == "free_text":
        long_values = text.str.split().str.len().ge(5)
        short_values = text.str.split().str.len().le(1)
        return sample_display_values(series[long_values], limit), sample_display_values(series[short_values], limit)

    if profile_role == "vector_blob":
        token_counts = text.str.split().str.len()
        vector_like = token_counts.ge(8)
        return sample_display_values(series[vector_like], limit), sample_display_values(series[~vector_like], limit)

    if profile_role in GEOGRAPHY_PROFILE_ROLES:
        return sample_display_values(series, limit), []

    return sample_display_values(series, limit), []


def clean_profile_values(values):
    if values is None:
        return pd.Series(dtype="object")

    try:
        series = pd.Series(values).dropna()
    except Exception:
        return pd.Series(dtype="object")

    return series[series.astype(str).str.strip().ne("")]


def parse_date_like_values(values):
    date_shaped = values.map(lambda value: any(symbol in str(value) for symbol in "-/:") )
    parsed = pd.to_datetime(values.where(date_shaped), errors="coerce", format="mixed", utc=True)
    return parsed.notna()


def sample_display_values(values, limit=4):
    if values is None:
        return []

    try:
        series = pd.Series(values).dropna()
    except Exception:
        return []

    examples = []
    counts = Counter()
    for value in series:
        text = safe_string(value).strip()
        if not text:
            continue
        if len(text) > 36:
            text = f"{text[:33]}..."
        counts[text] += 1

    for text, _count in counts.most_common(limit):
        examples.append(text)
    return examples


def add_metric_evidence(positive, negative, record, profile_role):
    numeric_ratio = safe_float(record.get("numeric_ratio"))
    date_ratio = safe_float(record.get("date_like_ratio"))
    cardinality = safe_float(record.get("decision_cardinality_ratio"))
    cardinality_lower = safe_float(record.get("cardinality_ratio_lower_bound"))
    sample_margin = safe_float(record.get("sample_uncertainty_margin"))

    if profile_role == "numeric_measure" and numeric_ratio is not None:
        positive.append(f"{percent_text(numeric_ratio)} of present values parse as numbers.")
        if numeric_ratio < 0.95:
            negative.append("Some values do not parse as numbers, so numeric confidence is reduced.")
    elif profile_role in {"datetime_category", "datetime_high_uniqueness", "datetime_identifier"} and date_ratio is not None:
        positive.append(f"{percent_text(date_ratio)} of present values parse as dates or timestamps.")
        if profile_role in {"datetime_high_uniqueness", "datetime_identifier"}:
            negative.append("Timestamps can be unique without being true row identifiers.")
    elif profile_role in GEOGRAPHY_PROFILE_ROLES:
        positive.append("Column name and value pattern look geographic or location-based.")
        negative.append("Location fields can look unique or categorical, but they describe places rather than row identity.")
    elif profile_role in {"identifier", "quasi_identifier"} and cardinality is not None:
        positive.append(f"{percent_text(cardinality)} of present values are distinct.")
        if cardinality_lower is not None and cardinality_lower < 0.9:
            negative.append("The lower confidence bound for uniqueness is weaker than the observed sample.")
    elif profile_role in {"categorical", "binary_category", "numeric_code_category"} and cardinality is not None:
        positive.append(f"Values repeat: distinctness is {percent_text(cardinality)}.")
        if profile_role == "numeric_code_category":
            negative.append("Values are numeric-looking, so Buckaroo treats them as codes rather than measurements.")
    elif profile_role == "free_text":
        avg_words = safe_float(record.get("avg_word_count"))
        if avg_words is not None:
            positive.append(f"Values average about {avg_words:.1f} words each.")
    elif profile_role == "vector_blob":
        token_fraction = safe_float(record.get("numeric_token_fraction"))
        if token_fraction is not None:
            positive.append(f"{percent_text(token_fraction)} of text tokens are numeric.")
            negative.append("Numeric text blobs are not natural-language text for semantic analysis.")

    if sample_margin is not None and sample_margin >= 0.10:
        negative.append("The confidence interval is wide, so more rows may change this decision.")


def add_name_hint_evidence(positive, record, profile_role):
    if safe_bool(record.get("id_name_hint")) and profile_role in {"identifier", "quasi_identifier"}:
        positive.append("Column name looks ID-like.")
    if safe_bool(record.get("measurement_name_hint")) and profile_role == "numeric_measure":
        positive.append("Column name looks like a measurement, amount, count, or price.")
    if safe_bool(record.get("categorical_name_hint")) and profile_role in {"categorical", "binary_category", "numeric_code_category"}:
        positive.append("Column name looks category-like.")
    if safe_bool(record.get("free_text_name_hint")) and profile_role == "free_text":
        positive.append("Column name looks like notes, description, text, or comments.")
    if safe_bool(record.get("geography_name_hint")) and profile_role in GEOGRAPHY_PROFILE_ROLES:
        positive.append("Column name contains a geography/location hint.")


def add_candidate_evidence(positive, negative, candidate_roles, profile_role):
    if not isinstance(candidate_roles, list) or not candidate_roles:
        return

    chosen = next((candidate for candidate in candidate_roles if isinstance(candidate, dict) and candidate.get("chosen")), None)
    if chosen:
        chosen_role = safe_string(chosen.get("role"))
        role = profile_role_label(chosen_role)
        confidence = safe_float(chosen.get("confidence"))
        if confidence is not None:
            chosen_family = profile_role_family(chosen_role)
            selected_family = profile_role_family(profile_role)
            if chosen_role != profile_role and chosen_family == selected_family:
                positive.append(
                    f"Role-family evidence for '{selected_family}' has "
                    f"{percent_text(confidence)} confidence; semantic rules select the more specific subtype."
                )
            else:
                positive.append(f"Chosen candidate '{role}' has {percent_text(confidence)} confidence.")

    alternatives = [
        candidate for candidate in candidate_roles
        if isinstance(candidate, dict)
        and not safe_bool(candidate.get("chosen"))
        and safe_float(candidate.get("confidence")) is not None
        and safe_float(candidate.get("confidence")) >= 0.35
    ]
    for candidate in alternatives[:2]:
        role = profile_role_label(safe_string(candidate.get("role")))
        confidence = safe_float(candidate.get("confidence"))
        reason = safe_string(candidate.get("reason"))
        suffix = f" because {reason}" if reason else ""
        negative.append(f"Also has {percent_text(confidence)} evidence for '{role}'{suffix}.")


def unique_evidence(items, limit=6):
    seen = set()
    result = []
    for item in items:
        cleaned = safe_string(item).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def percent_text(value):
    numeric = safe_float(value)
    if numeric is None:
        return "unknown"
    return f"{round(numeric * 100)}%"


def profile_role_label(profile_role):
    if not profile_role:
        return "unknown role"
    return PROFILE_ROLE_LABELS.get(str(profile_role), str(profile_role).replace("_", " "))


def profile_role_family(profile_role):
    if not profile_role:
        return "unknown"
    return PROFILE_ROLE_FAMILIES.get(str(profile_role), "other")


def safe_string(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def safe_float(value):
    if value is None:
        return None
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric_value):
        return None
    return round(numeric_value, 4)


def safe_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def get_attribute_stats(df, column):
    """
    Get statistics for a specific attribute in the DataFrame
    :param df: DataFrame containing the data
    :param column: name of the column to get statistics for
    :return: dictionary containing statistics for the column
    """
    if is_categorical(df[column]):
        return get_categorical_stats(df, column)
    return get_numeric_stats(df, column)

def build_attribute_distributions(main_df):
    """
    Build distributions for each attribute in the main DataFrame
    :param main_df: DataFrame containing the main data
    :return: dictionary containing distributions for each attribute
    """
    distributions = {}
    for col in main_df.columns:
        distributions[col] = get_attribute_stats(main_df, col)
    return distributions

def get_categorical_stats(df, column):
    """
    Get statistics for a categorical attribute in the DataFrame
    :param df: DataFrame containing the data
    :param column: name of the column to get statistics for
    :return: dictionary containing statistics for the categorical column
    """
    col_data = df[column].fillna('N/A')
    return {
        "categorical": {
            "categories": col_data.nunique(),
            "mode": col_data.mode().iloc[0]
        }
    }

def get_numeric_stats(df, column):
    """
    Get statistics for a numeric attribute in the DataFrame
    :param df: DataFrame containing the data
    :param column: name of the column to get statistics for
    :return: dictionary containing statistics for the numeric column
    """
    col_data = pd.to_numeric(df[column], errors='coerce').dropna()
    return {
        "numeric": {
            "mean": col_data.mean().item(),
            "min": col_data.min().item(),
            "max": col_data.max().item()
        }
    }

def convert_error_list_to_dict(error_list):
   """
   Convert the error list to a dictionary format
   :param error_list: list of error dictionaries
   :return: dictionary with a format like this (an example):
            "Age": {"incomplete": 0.75},
            "Country": {"missing": 2.25},
            "ConvertedSalary": {"incomplete": 2.5}
   """
   result = {}
   for row in error_list:
       if row != "error_type":
           error_type = row["error_type"]
           for col_key, percentage in row.items():
               if col_key != "error_type" and float(percentage) > 0:
                   col_name = col_key.strip()
                   if col_name not in result:
                       result[col_name] = {}
                   result[col_name][error_type] = float(percentage)
   return result




