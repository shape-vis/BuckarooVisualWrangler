import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


DETECTOR_FUNCTIONS = {
    "detect_anomalies": """
    CREATE OR REPLACE FUNCTION detect_anomalies(
        p_table_name text,
        p_method text DEFAULT 'zscore',
        p_threshold numeric DEFAULT NULL
    )
    RETURNS TABLE (
        row_id integer,
        column_name text,
        error_type text,
        error_value text
    )
    LANGUAGE plpgsql
    AS $FUNC$
    DECLARE
        col RECORD;
        query_text text;
        tbl text;
        thresh numeric;
    BEGIN
        tbl := quote_ident(p_table_name);

        FOR col IN
            SELECT c.column_name
            FROM information_schema.columns c
            WHERE c.table_name = p_table_name
              AND c.data_type IN ('integer','bigint','numeric','real','double precision','smallint')
              AND c.column_name <> 'ID'
        LOOP
            IF lower(coalesce(p_method,'zscore')) = 'zscore' THEN
                thresh := COALESCE(p_threshold, 3);

                query_text := format($SQL$
                    WITH stats AS (
                        SELECT
                            AVG(%1$I)::numeric AS mean_val,
                            STDDEV_SAMP(%1$I)::numeric AS std_val
                        FROM %2$s
                        WHERE %1$I IS NOT NULL
                    )
                    SELECT
                        "ID"::int,
                        %3$L,
                        'zscore_anomaly',
                        %1$I::text
                    FROM %2$s, stats
                    WHERE %1$I IS NOT NULL
                      AND std_val IS NOT NULL
                      AND std_val > 0
                      AND ABS((%1$I::numeric - mean_val) / std_val) > %4$s
                $SQL$,
                    col.column_name,
                    tbl,
                    col.column_name,
                    thresh
                );

            ELSIF lower(p_method) = 'mad' THEN
                thresh := COALESCE(p_threshold, 3);

                query_text := format($SQL$
                    WITH stats AS (
                        SELECT
                            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY %1$I::numeric) AS median_val
                        FROM %2$s
                        WHERE %1$I IS NOT NULL
                    ),
                    deviations AS (
                        SELECT
                            ABS(%1$I::numeric - median_val) AS abs_dev
                        FROM %2$s, stats
                        WHERE %1$I IS NOT NULL
                    ),
                    mad_stats AS (
                        SELECT
                            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY abs_dev) AS mad_val
                        FROM deviations
                    )
                    SELECT
                        "ID"::int,
                        %3$L,
                        'mad_anomaly',
                        %1$I::text
                    FROM %2$s, stats, mad_stats
                    WHERE %1$I IS NOT NULL
                      AND mad_val IS NOT NULL
                      AND mad_val > 0
                      AND ABS(0.6745 * (%1$I::numeric - median_val) / mad_val) > %4$s
                $SQL$,
                    col.column_name,
                    tbl,
                    col.column_name,
                    thresh
                );

            ELSIF lower(p_method) = 'iqr' THEN
                thresh := COALESCE(p_threshold, 1.5);

                query_text := format($SQL$
                    WITH qs AS (
                        SELECT
                            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY %1$I::numeric) AS q1,
                            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY %1$I::numeric) AS q3
                        FROM %2$s
                        WHERE %1$I IS NOT NULL
                    ),
                    bounds AS (
                        SELECT
                            q1,
                            q3,
                            (q3 - q1) AS iqr,
                            (q1 - (%3$s * (q3 - q1))) AS lower_bound,
                            (q3 + (%3$s * (q3 - q1))) AS upper_bound
                        FROM qs
                    )
                    SELECT
                        "ID"::int,
                        %4$L,
                        'iqr_anomaly',
                        %1$I::text
                    FROM %2$s, bounds
                    WHERE %1$I IS NOT NULL
                      AND iqr IS NOT NULL
                      AND iqr > 0
                      AND (%1$I::numeric < lower_bound OR %1$I::numeric > upper_bound)
                $SQL$,
                    col.column_name,
                    tbl,
                    thresh,
                    col.column_name
                );

            ELSE
                thresh := COALESCE(p_threshold, 3);

                query_text := format($SQL$
                    WITH stats AS (
                        SELECT
                            AVG(%1$I)::numeric AS mean_val,
                            STDDEV_SAMP(%1$I)::numeric AS std_val
                        FROM %2$s
                        WHERE %1$I IS NOT NULL
                    )
                    SELECT
                        "ID"::int,
                        %3$L,
                        'zscore_anomaly',
                        %1$I::text
                    FROM %2$s, stats
                    WHERE %1$I IS NOT NULL
                      AND std_val IS NOT NULL
                      AND std_val > 0
                      AND ABS((%1$I::numeric - mean_val) / std_val) > %4$s
                $SQL$,
                    col.column_name,
                    tbl,
                    col.column_name,
                    thresh
                );
            END IF;

            RETURN QUERY EXECUTE query_text;
        END LOOP;

        RETURN;
    END;
    $FUNC$;
    """,
    "detect_rarity": """
    CREATE OR REPLACE FUNCTION detect_rarity(
        p_table_name text,
        p_threshold_pct numeric DEFAULT 0.01
    )
    RETURNS TABLE (
        row_id integer,
        column_name text,
        error_type text,
        error_value text,
        rarity_score numeric
    )
    LANGUAGE plpgsql
    AS $FUNC$
    DECLARE
        col RECORD;
        query_text text;
        tbl text;
        threshold_pct numeric;
    BEGIN
        tbl := quote_ident(p_table_name);
        threshold_pct := GREATEST(LEAST(COALESCE(p_threshold_pct, 0.01), 1), 0);

        FOR col IN
            SELECT c.column_name
            FROM information_schema.columns c
            WHERE c.table_name = p_table_name
              AND c.column_name <> 'ID'
              AND c.data_type IN ('character varying', 'character', 'text')
        LOOP
            query_text := format($SQL$
                WITH cleaned AS (
                    SELECT
                        "ID",
                        NULLIF(BTRIM(%1$I::text), '') AS normalized_value
                    FROM %2$s
                ),
                value_counts AS (
                    SELECT
                        normalized_value,
                        COUNT(*)::numeric AS value_count
                    FROM cleaned
                    WHERE normalized_value IS NOT NULL
                    GROUP BY normalized_value
                ),
                totals AS (
                    SELECT COALESCE(SUM(value_count), 0)::numeric AS total_count
                    FROM value_counts
                ),
                rare_values AS (
                    SELECT
                        vc.normalized_value,
                        CASE
                            WHEN t.total_count > 0 THEN vc.value_count / t.total_count
                            ELSE 0
                        END AS rarity_score
                    FROM value_counts vc
                    CROSS JOIN totals t
                    WHERE t.total_count > 0
                      AND (vc.value_count / t.total_count) <= %3$s
                )
                SELECT
                    c."ID"::int AS row_id,
                    %4$L AS column_name,
                    'incomplete'::text AS error_type,
                    c.normalized_value::text AS error_value,
                    rv.rarity_score::numeric AS rarity_score
                FROM cleaned c
                JOIN rare_values rv
                  ON c.normalized_value = rv.normalized_value
            $SQL$,
                col.column_name,
                tbl,
                threshold_pct,
                col.column_name
            );

            RETURN QUERY EXECUTE query_text;
        END LOOP;

        RETURN;
    END;
    $FUNC$;
    """,
    "detect_missing_values": """
    CREATE OR REPLACE FUNCTION detect_missing_values(
        p_table_name text
    )
    RETURNS TABLE (
        row_id integer,
        column_name text,
        error_type text,
        error_value text
    )
    LANGUAGE plpgsql
    AS $FUNC$
    DECLARE
        col RECORD;
        query_text text;
        tbl text;
    BEGIN
        tbl := quote_ident(p_table_name);

        FOR col IN
            SELECT c.column_name
            FROM information_schema.columns c
            WHERE c.table_name = p_table_name
              AND c.column_name <> 'ID'
        LOOP
            query_text := format($SQL$
                SELECT
                    "ID"::int AS row_id,
                    %1$L AS column_name,
                    'missing'::text AS error_type,
                    %2$I::text AS error_value
                FROM %3$s
                WHERE %2$I IS NULL
                   OR NULLIF(BTRIM(%2$I::text), '') IS NULL
                   OR LOWER(BTRIM(%2$I::text)) IN ('null', 'undefined')
            $SQL$,
                col.column_name,
                col.column_name,
                tbl
            );

            RETURN QUERY EXECUTE query_text;
        END LOOP;

        RETURN;
    END;
    $FUNC$;
    """,
    "detect_datatype_mismatch": r"""
    CREATE OR REPLACE FUNCTION detect_datatype_mismatch(
        p_table_name text
    )
    RETURNS TABLE (
        row_id integer,
        column_name text,
        error_type text,
        error_value text
    )
    LANGUAGE plpgsql
    AS $FUNC$
    DECLARE
        col RECORD;
        query_text text;
        tbl text;
    BEGIN
        tbl := quote_ident(p_table_name);

        FOR col IN
            SELECT c.column_name
            FROM information_schema.columns c
            WHERE c.table_name = p_table_name
              AND c.column_name <> 'ID'
        LOOP
            query_text := format($SQL$
                WITH classified AS (
                    SELECT
                        "ID"::int AS row_id,
                        %1$I::text AS error_value,
                        CASE
                            WHEN %1$I IS NULL THEN NULL
                            WHEN NULLIF(BTRIM(%1$I::text), '') IS NULL THEN NULL
                            WHEN LOWER(BTRIM(%1$I::text)) IN ('null', 'undefined') THEN NULL
                            WHEN BTRIM(%1$I::text) ~* '^[+-]?(\d+(\.\d+)?|\.\d+)$' THEN 'numeric'
                            WHEN BTRIM(%1$I::text) ~ '^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?$'
                              OR BTRIM(%1$I::text) ~ '^\d{1,2}/\d{1,2}/\d{4}$'
                              OR BTRIM(%1$I::text) ~ '^\d{4}/\d{1,2}/\d{1,2}$'
                            THEN 'datetime'
                            ELSE 'text'
                        END AS value_type
                    FROM %2$s
                ),
                type_counts AS (
                    SELECT
                        value_type,
                        COUNT(*)::int AS type_count,
                        CASE value_type
                            WHEN 'numeric' THEN 1
                            WHEN 'datetime' THEN 2
                            WHEN 'text' THEN 3
                            ELSE 4
                        END AS type_priority
                    FROM classified
                    WHERE value_type IS NOT NULL
                    GROUP BY value_type
                ),
                majority_type AS (
                    SELECT value_type
                    FROM type_counts
                    ORDER BY type_count DESC, type_priority ASC
                    LIMIT 1
                )
                SELECT
                    c.row_id,
                    %3$L AS column_name,
                    'mismatch'::text AS error_type,
                    c.error_value
                FROM classified c
                CROSS JOIN majority_type mt
                WHERE c.value_type IS NOT NULL
                  AND c.value_type <> mt.value_type
            $SQL$,
                col.column_name,
                tbl,
                col.column_name
            );

            RETURN QUERY EXECUTE query_text;
        END LOOP;

        RETURN;
    END;
    $FUNC$;
    """
}


def initialize_detector_functions(engine):
    # Create just the detector SQL functions.
    logger.info("Initializing detector database functions...")

    try:
        with engine.connect() as conn:
            trans = conn.begin()

            for func_name, func_sql in DETECTOR_FUNCTIONS.items():
                try:
                    logger.info(f"Creating detector function: {func_name}")
                    conn.execute(text(func_sql))
                except Exception:
                    trans.rollback()
                    raise

            trans.commit()
            logger.info("Detector database functions initialized successfully")

    except Exception as e:
        logger.error(f"Detector function initialization failed: {str(e)}")
        raise
