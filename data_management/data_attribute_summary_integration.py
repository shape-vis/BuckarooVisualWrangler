"""
Build attribute-summary JSON directly from PostgreSQL tables.
"""
from sqlalchemy import text

from app.service_helpers import (
    clean_table_name,
    anomaly_methods_to_raw_error_types,
    _normalize_rarity_threshold,
)


NUMERIC_TYPES = {
    "smallint",
    "integer",
    "bigint",
    "numeric",
    "real",
    "double precision",
}


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def get_default_attributes_from_rankings(tablename, engine):
    """
    Fetch top 3 attributes from the pre-computed rankings table.
    """
    try:
        cleaned_tablename = clean_table_name(tablename)
        rankings_table = f"rankings{cleaned_tablename}"

        try:
            query = text(f'SELECT attribute FROM "{rankings_table}" ORDER BY rank ASC LIMIT 3')
            with engine.connect() as conn:
                return [row[0] for row in conn.execute(query).fetchall()]
        except Exception:
            base_pattern = cleaned_tablename.split('_version')[0] if '_version' in cleaned_tablename else cleaned_tablename
            pattern = f"rankings{base_pattern}%"

            with engine.connect() as conn:
                matching_tables = conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE tablename LIKE :pattern ORDER BY tablename DESC LIMIT 1"),
                    {"pattern": pattern}
                ).fetchall()

                if matching_tables:
                    found_table = matching_tables[0][0]
                    query = text(f'SELECT attribute FROM "{found_table}" ORDER BY rank ASC LIMIT 3')
                    return [row[0] for row in conn.execute(query).fetchall()]
                return []
    except Exception as e:
        print(f"Error fetching rankings for table '{tablename}': {e}")
        return []


def _get_table_columns(table_name: str, engine):
    query = text("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = :table_name
        ORDER BY ordinal_position
    """)
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(query, {"table_name": table_name}).fetchall()]


def _build_error_filter_clause(anomaly_methods, rarity_threshold):
    selected_raw_types = anomaly_methods_to_raw_error_types(anomaly_methods)
    threshold = _normalize_rarity_threshold(rarity_threshold)
    return """
        (
            e.error_type <> 'anomaly'
            OR e.raw_error_type = ANY(:selected_raw_types)
        )
        AND (
            e.error_type <> 'incomplete'
            OR e.rarity_score IS NULL
            OR e.rarity_score <= :rarity_threshold
        )
    """, {
        "selected_raw_types": selected_raw_types,
        "rarity_threshold": threshold,
    }


def _get_column_error_percentages(table_name, error_table_name, min_id, max_id, engine):
    query = text(f"""
        WITH total_rows AS (
            SELECT COUNT(*)::numeric AS total_count
            FROM "{table_name}"
            WHERE "ID" BETWEEN :min_id AND :max_id
        )
        SELECT
            e.column_id,
            e.error_type,
            COUNT(*)::numeric / NULLIF((SELECT total_count FROM total_rows), 0) AS error_pct
        FROM "{error_table_name}" e
        WHERE e.row_id BETWEEN :min_id AND :max_id
          AND e.column_id IS NOT NULL
          AND BTRIM(e.column_id) <> ''
        GROUP BY e.column_id, e.error_type
    """)

    params = {"min_id": min_id, "max_id": max_id}
    with engine.connect() as conn:
        rows = conn.execute(query, params).fetchall()

    result = {}
    for row in rows:
        mapping = row._mapping
        result.setdefault(mapping["column_id"], {})[mapping["error_type"]] = float(mapping["error_pct"] or 0)
    return result


def _get_numeric_stats(table_name: str, column_name: str, min_id: int, max_id: int, engine):
    quoted_column = _quote_identifier(column_name)
    query = text(f"""
        SELECT
            AVG({quoted_column}::double precision) AS mean_value,
            MIN({quoted_column}) AS min_value,
            MAX({quoted_column}) AS max_value
        FROM "{table_name}"
        WHERE "ID" BETWEEN :min_id AND :max_id
          AND {quoted_column} IS NOT NULL
    """)
    with engine.connect() as conn:
        row = conn.execute(query, {"min_id": min_id, "max_id": max_id}).first()

    if not row or row._mapping["mean_value"] is None:
        return {"numeric": {"mean": 0.0, "min": 0, "max": 0}}

    mapping = row._mapping
    return {
        "numeric": {
            "mean": float(mapping["mean_value"]),
            "min": mapping["min_value"],
            "max": mapping["max_value"],
        }
    }


def _get_categorical_stats(table_name: str, column_name: str, min_id: int, max_id: int, engine):
    quoted_column = _quote_identifier(column_name)
    distinct_query = text(f"""
        SELECT COUNT(DISTINCT COALESCE(NULLIF(BTRIM({quoted_column}::text), ''), 'N/A')) AS category_count
        FROM "{table_name}"
        WHERE "ID" BETWEEN :min_id AND :max_id
    """)
    mode_query = text(f"""
        SELECT COALESCE(NULLIF(BTRIM({quoted_column}::text), ''), 'N/A') AS mode_value
        FROM "{table_name}"
        WHERE "ID" BETWEEN :min_id AND :max_id
        GROUP BY COALESCE(NULLIF(BTRIM({quoted_column}::text), ''), 'N/A')
        ORDER BY COUNT(*) DESC, mode_value ASC
        LIMIT 1
    """)

    with engine.connect() as conn:
        category_count = conn.execute(distinct_query, {"min_id": min_id, "max_id": max_id}).scalar() or 0
        mode_value = conn.execute(mode_query, {"min_id": min_id, "max_id": max_id}).scalar() or "N/A"

    return {
        "categorical": {
            "categories": int(category_count),
            "mode": str(mode_value),
        }
    }


def _build_attribute_distributions(table_name: str, columns, min_id: int, max_id: int, engine):
    distributions = {}
    for column in columns:
        column_name = column["column_name"]
        data_type = column["data_type"]
        if data_type in NUMERIC_TYPES:
            distributions[column_name] = _get_numeric_stats(table_name, column_name, min_id, max_id, engine)
        else:
            distributions[column_name] = _get_categorical_stats(table_name, column_name, min_id, max_id, engine)
    return distributions


def generate_complete_json(
    min_id,
    max_id,
    tablename=None,
    anomaly_methods=None,
    rarity_threshold=0.01,
    error_table_name=None
):
    """
    Generate the attribute-summary payload directly from SQL tables.
    """
    from app import engine

    if not tablename:
        return {
            "columnErrors": {},
            "attributes": [],
            "attributeDistributions": {},
            "defaultAttributes": [],
        }

    cleaned_table_name = clean_table_name(tablename)
    effective_error_table = error_table_name or f"errors{cleaned_table_name}"
    columns = _get_table_columns(cleaned_table_name, engine)
    column_errors = _get_column_error_percentages(
        cleaned_table_name,
        effective_error_table,
        int(min_id),
        int(max_id),
        engine
    )
    attribute_distributions = _build_attribute_distributions(
        cleaned_table_name,
        columns,
        int(min_id),
        int(max_id),
        engine
    )
    default_attributes = get_default_attributes_from_rankings(cleaned_table_name, engine)

    return {
        "columnErrors": column_errors,
        "attributes": [column["column_name"] for column in columns],
        "attributeDistributions": attribute_distributions,
        "defaultAttributes": default_attributes,
    }
