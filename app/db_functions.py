# file to store all db functions the app will need to use

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Dictionary to store all the user's database functions
DB_FUNCTIONS = {
    "generate_one_d_histogram_with_errors": """
    -- Simplified unified version - single query path for numeric and categorical
    -- Fixed: Changed nested dollar-quote from $SQL$ to $QUERY$ to avoid parsing issues
    CREATE OR REPLACE FUNCTION generate_one_d_histogram_with_errors(
        main_table_name text,
        error_table_name text,
        axis_column text,
        bin_count integer DEFAULT 10,
        min_id integer DEFAULT NULL,
        max_id integer DEFAULT NULL
    ) RETURNS json
    LANGUAGE plpgsql
    AS $FUNC$
    DECLARE
        result json;
        is_numeric boolean;
    BEGIN
        -- Check if column is numeric
        SELECT data_type IN ('integer', 'bigint', 'numeric', 'real', 'double precision', 'smallint')
        INTO is_numeric
        FROM information_schema.columns
        WHERE table_name = main_table_name AND column_name = axis_column;

        -- Single unified query for both numeric and categorical
        EXECUTE format($QUERY$
            WITH
            -- Step 1: Get all data rows with optional ID filtering
            data_rows AS (
                SELECT
                    "ID",
                    %I as value
                FROM %I
                WHERE ($1 IS NULL OR "ID" >= $1)
                  AND ($2 IS NULL OR "ID" <= $2)
            ),
            -- Step 2: Assign bins (keep as text for both numeric and categorical)
            binned_data AS (
                SELECT
                    d."ID",
                    CASE
                        WHEN d.value IS NULL THEN 'null'  -- Handle NULL values first
                        WHEN $3 THEN  -- is_numeric
                            -- Try to convert to numeric, if fails treat as categorical
                            CASE
                                WHEN d.value::text ~ '^\s*-?\d+(\.\d+)?\s*$' THEN
                                    -- Clamp bin number to 0..(bin_count-1) range
                                    LEAST(
                                        GREATEST(
                                            COALESCE(
                                                width_bucket(
                                                    d.value::numeric,
                                                    (SELECT MIN(value::numeric) FROM data_rows WHERE value::text ~ '^\s*-?\d+(\.\d+)?\s*$'),
                                                    (SELECT MAX(value::numeric) FROM data_rows WHERE value::text ~ '^\s*-?\d+(\.\d+)?\s*$'),
                                                    $4
                                                ) - 1,
                                                0
                                            ),
                                            0
                                        ),
                                        $4 - 1
                                    )::text
                                ELSE
                                    d.value::text  -- Non-numeric value in numeric column
                            END
                        ELSE
                            COALESCE(d.value::text, 'null')
                    END as bin
                FROM data_rows d
            ),
            -- Step 3: Get error counts per bin
            errors_per_bin AS (
                SELECT
                    b.bin,
                    e.error_type,
                    COUNT(*) as error_count
                FROM binned_data b
                JOIN %I e ON b."ID" = e.row_id
                WHERE e.column_id = $5
                GROUP BY b.bin, e.error_type
            ),
            -- Step 4: Aggregate by bin
            histogram_bins AS (
                SELECT
                    b.bin,
                    COUNT(*) as total_items,
                    jsonb_object_agg(
                        e.error_type,
                        e.error_count
                    ) FILTER (WHERE e.error_type IS NOT NULL) as errors
                FROM binned_data b
                LEFT JOIN errors_per_bin e ON b.bin = e.bin
                GROUP BY b.bin
            ),
            -- Step 5: Build scale data for numeric columns (ALL bins, not just ones with data)
            numeric_scale_data AS (
                SELECT
                    n as bin_num,
                    CASE WHEN $3 THEN
                        (SELECT MIN(value::numeric) FROM data_rows) +
                        (n * ((SELECT MAX(value::numeric) FROM data_rows) - (SELECT MIN(value::numeric) FROM data_rows)) / $4::numeric)
                    ELSE NULL END as x0,
                    CASE WHEN $3 THEN
                        (SELECT MIN(value::numeric) FROM data_rows) +
                        ((n+1) * ((SELECT MAX(value::numeric) FROM data_rows) - (SELECT MIN(value::numeric) FROM data_rows)) / $4::numeric)
                    ELSE NULL END as x1
                FROM generate_series(0, $4-1) n
                WHERE $3
            )
            -- Step 6: Build final JSON (split into two subqueries to avoid type mismatch)
            SELECT json_build_object(
                'histograms',
                CASE WHEN $3 THEN
                    -- For numeric: handle mixed bins (numeric and "null") - keep bins as text
                    (SELECT COALESCE(json_agg(
                        json_build_object(
                            'xBin', bin,
                            'xType', CASE WHEN bin ~ '^\d+$' THEN 'numeric' ELSE 'categorical' END,
                            'count', COALESCE(errors, '{}'::jsonb) || jsonb_build_object('items', total_items)
                        ) ORDER BY CASE WHEN bin ~ '^\d+$' THEN lpad(bin, 10, '0') ELSE bin END
                    ), '[]'::json) FROM histogram_bins)
                ELSE
                    -- For categorical: keep bin as text
                    (SELECT COALESCE(json_agg(
                        json_build_object(
                            'xBin', bin,
                            'xType', 'categorical',
                            'count', COALESCE(errors, '{}'::jsonb) || jsonb_build_object('items', total_items)
                        ) ORDER BY bin
                    ), '[]'::json) FROM histogram_bins)
                END,
                'scaleX',
                json_build_object(
                    'numeric', CASE WHEN $3 THEN
                        (SELECT COALESCE(json_agg(json_build_object('x0', x0, 'x1', x1) ORDER BY bin_num), '[]'::json) FROM numeric_scale_data)
                    ELSE '[]'::json END,
                    'categorical', (
                        -- Always include categorical values (null and non-numeric values in numeric columns)
                        SELECT COALESCE(
                            json_agg(DISTINCT bin ORDER BY bin),
                            '[]'::json
                        )
                        FROM histogram_bins
                        WHERE NOT (bin ~ '^\d+$')  -- Only non-numeric bin labels
                    )
                )
            )
        $QUERY$,
            axis_column,              -- %I: column name in data_rows SELECT
            main_table_name,          -- %I: main table name
            error_table_name          -- %I: error table name
        )
        USING min_id, max_id, is_numeric, bin_count, axis_column
        INTO result;

        RETURN result;
    END;
    $FUNC$;
    """,
    "generate_two_d_histogram_with_errors": """
    -- Simplified unified version - single query path for all type combinations
    -- Follows the same pattern as 1D histogram
    CREATE OR REPLACE FUNCTION generate_two_d_histogram_with_errors(
        main_table_name text,
        error_table_name text,
        x_axis_column text,
        y_axis_column text,
        x_bin_count integer DEFAULT 10,
        y_bin_count integer DEFAULT 10,
        min_id integer DEFAULT NULL,
        max_id integer DEFAULT NULL
    ) RETURNS json
    LANGUAGE plpgsql
    AS $FUNC$
    DECLARE
        result json;
        x_is_numeric boolean;
        y_is_numeric boolean;
    BEGIN
        -- Check if columns are numeric
        SELECT data_type IN ('integer', 'bigint', 'numeric', 'real', 'double precision', 'smallint')
        INTO x_is_numeric
        FROM information_schema.columns
        WHERE table_name = main_table_name AND column_name = x_axis_column;

        SELECT data_type IN ('integer', 'bigint', 'numeric', 'real', 'double precision', 'smallint')
        INTO y_is_numeric
        FROM information_schema.columns
        WHERE table_name = main_table_name AND column_name = y_axis_column;

        -- Single unified query for all type combinations
        EXECUTE format($QUERY$
            WITH
            -- Step 1: Get all data rows with optional ID filtering
            data_rows AS (
                SELECT
                    "ID",
                    %I as x_value,
                    %I as y_value
                FROM %I
                WHERE ($1 IS NULL OR "ID" >= $1)
                  AND ($2 IS NULL OR "ID" <= $2)
            ),
            -- Step 2: Get min/max for numeric columns (for width_bucket)
            x_bounds AS (
                SELECT
                    COALESCE(MIN(x_value::numeric), 0) as min_val,
                    COALESCE(MAX(x_value::numeric), 1) as max_val
                FROM data_rows
                WHERE $3 AND x_value::text ~ '^\s*-?\d+(\.\d+)?\s*$'  -- only numeric values
            ),
            y_bounds AS (
                SELECT
                    COALESCE(MIN(y_value::numeric), 0) as min_val,
                    COALESCE(MAX(y_value::numeric), 1) as max_val
                FROM data_rows
                WHERE $4 AND y_value::text ~ '^\s*-?\d+(\.\d+)?\s*$'  -- only numeric values
            ),
            -- Step 3: Assign bins for both X and Y
            binned_data AS (
                SELECT
                    d."ID",
                    CASE
                        WHEN d.x_value IS NULL THEN 'null'
                        WHEN $3 THEN  -- x_is_numeric
                            CASE
                                WHEN d.x_value::text ~ '^\s*-?\d+(\.\d+)?\s*$' THEN
                                    LEAST(GREATEST(
                                        width_bucket(
                                            d.x_value::numeric,
                                            (SELECT min_val FROM x_bounds),
                                            (SELECT max_val FROM x_bounds),
                                            $5
                                        ) - 1,
                                        0
                                    ), $5 - 1)::text
                                ELSE
                                    d.x_value::text  -- Non-numeric value in numeric column
                            END
                        ELSE
                            COALESCE(d.x_value::text, 'null')
                    END as x_bin,
                    CASE
                        WHEN d.y_value IS NULL THEN 'null'
                        WHEN $4 THEN  -- y_is_numeric
                            CASE
                                WHEN d.y_value::text ~ '^\s*-?\d+(\.\d+)?\s*$' THEN
                                    LEAST(GREATEST(
                                        width_bucket(
                                            d.y_value::numeric,
                                            (SELECT min_val FROM y_bounds),
                                            (SELECT max_val FROM y_bounds),
                                            $6
                                        ) - 1,
                                        0
                                    ), $6 - 1)::text
                                ELSE
                                    d.y_value::text  -- Non-numeric value in numeric column
                            END
                        ELSE
                            COALESCE(d.y_value::text, 'null')
                    END as y_bin
                FROM data_rows d
            ),
            -- Step 5: Get error counts per (x_bin, y_bin) pair
            errors_per_bin AS (
                SELECT
                    b.x_bin,
                    b.y_bin,
                    e.error_type,
                    COUNT(*) as error_count
                FROM binned_data b
                JOIN %I e ON b."ID" = e.row_id
                WHERE e.column_id IN ($7, $8)
                GROUP BY b.x_bin, b.y_bin, e.error_type
            ),
            -- Step 6: Aggregate by bin
            histogram_bins AS (
                SELECT
                    b.x_bin,
                    b.y_bin,
                    COUNT(*) as total_items,
                    jsonb_object_agg(
                        e.error_type,
                        e.error_count
                    ) FILTER (WHERE e.error_type IS NOT NULL) as errors
                FROM binned_data b
                LEFT JOIN errors_per_bin e ON b.x_bin = e.x_bin AND b.y_bin = e.y_bin
                GROUP BY b.x_bin, b.y_bin
            ),
            -- Step 7: Build X scale data for numeric columns
            x_numeric_scale_data AS (
                SELECT
                    n as bin_num,
                    (SELECT min_val FROM x_bounds) +
                        (n * ((SELECT max_val FROM x_bounds) - (SELECT min_val FROM x_bounds)) / $5::numeric) as x0,
                    (SELECT min_val FROM x_bounds) +
                        ((n+1) * ((SELECT max_val FROM x_bounds) - (SELECT min_val FROM x_bounds)) / $5::numeric) as x1
                FROM generate_series(0, $5-1) n
                WHERE $3  -- only generate for numeric columns
            ),
            -- Step 8: Build Y scale data for numeric columns
            y_numeric_scale_data AS (
                SELECT
                    n as bin_num,
                    (SELECT min_val FROM y_bounds) +
                        (n * ((SELECT max_val FROM y_bounds) - (SELECT min_val FROM y_bounds)) / $6::numeric) as x0,
                    (SELECT min_val FROM y_bounds) +
                        ((n+1) * ((SELECT max_val FROM y_bounds) - (SELECT min_val FROM y_bounds)) / $6::numeric) as x1
                FROM generate_series(0, $6-1) n
                WHERE $4  -- only generate for numeric columns
            )
            -- Step 9: Build final JSON (split into 4 type combinations to avoid type mismatch)
            SELECT json_build_object(
                'histograms',
                CASE
                    WHEN $3 AND $4 THEN
                        -- Both numeric (but handle mixed bins) - keep bins as text
                        (SELECT COALESCE(json_agg(
                            json_build_object(
                                'xBin', x_bin,
                                'yBin', y_bin,
                                'xType', CASE WHEN x_bin ~ '^\d+$' THEN 'numeric' ELSE 'categorical' END,
                                'yType', CASE WHEN y_bin ~ '^\d+$' THEN 'numeric' ELSE 'categorical' END,
                                'count', COALESCE(errors, '{}'::jsonb) || jsonb_build_object('items', total_items)
                            ) ORDER BY CASE WHEN x_bin ~ '^\d+$' THEN lpad(x_bin, 10, '0') ELSE x_bin END,
                                      CASE WHEN y_bin ~ '^\d+$' THEN lpad(y_bin, 10, '0') ELSE y_bin END
                        ), '[]'::json) FROM histogram_bins)
                    WHEN $3 AND NOT $4 THEN
                        -- X numeric, Y categorical - keep bins as text
                        (SELECT COALESCE(json_agg(
                            json_build_object(
                                'xBin', x_bin,
                                'yBin', y_bin,
                                'xType', CASE WHEN x_bin ~ '^\d+$' THEN 'numeric' ELSE 'categorical' END,
                                'yType', 'categorical',
                                'count', COALESCE(errors, '{}'::jsonb) || jsonb_build_object('items', total_items)
                            ) ORDER BY CASE WHEN x_bin ~ '^\d+$' THEN lpad(x_bin, 10, '0') ELSE x_bin END, y_bin
                        ), '[]'::json) FROM histogram_bins)
                    WHEN NOT $3 AND $4 THEN
                        -- X categorical, Y numeric - keep bins as text
                        (SELECT COALESCE(json_agg(
                            json_build_object(
                                'xBin', x_bin,
                                'yBin', y_bin,
                                'xType', 'categorical',
                                'yType', CASE WHEN y_bin ~ '^\d+$' THEN 'numeric' ELSE 'categorical' END,
                                'count', COALESCE(errors, '{}'::jsonb) || jsonb_build_object('items', total_items)
                            ) ORDER BY x_bin, CASE WHEN y_bin ~ '^\d+$' THEN lpad(y_bin, 10, '0') ELSE y_bin END
                        ), '[]'::json) FROM histogram_bins)
                    ELSE
                        -- Both categorical
                        (SELECT COALESCE(json_agg(
                            json_build_object(
                                'xBin', x_bin,
                                'yBin', y_bin,
                                'xType', 'categorical',
                                'yType', 'categorical',
                                'count', COALESCE(errors, '{}'::jsonb) || jsonb_build_object('items', total_items)
                            ) ORDER BY x_bin, y_bin
                        ), '[]'::json) FROM histogram_bins)
                END,
                'scaleX', json_build_object(
                    'numeric', CASE WHEN $3 THEN
                        (SELECT COALESCE(json_agg(json_build_object('x0', x0, 'x1', x1) ORDER BY bin_num), '[]'::json) FROM x_numeric_scale_data)
                    ELSE '[]'::json END,
                    'categorical', (
                        -- Always include categorical values (null and non-numeric values in numeric columns)
                        SELECT COALESCE(
                            json_agg(DISTINCT x_bin ORDER BY x_bin),
                            '[]'::json
                        )
                        FROM histogram_bins
                        WHERE NOT (x_bin ~ '^\d+$')  -- Only non-numeric bin labels
                    )
                ),
                'scaleY', json_build_object(
                    'numeric', CASE WHEN $4 THEN
                        (SELECT COALESCE(json_agg(json_build_object('x0', x0, 'x1', x1) ORDER BY bin_num), '[]'::json) FROM y_numeric_scale_data)
                    ELSE '[]'::json END,
                    'categorical', (
                        -- Always include categorical values (null and non-numeric values in numeric columns)
                        SELECT COALESCE(
                            json_agg(DISTINCT y_bin ORDER BY y_bin),
                            '[]'::json
                        )
                        FROM histogram_bins
                        WHERE NOT (y_bin ~ '^\d+$')  -- Only non-numeric bin labels
                    )
                )
            )
        $QUERY$,
            x_axis_column,              -- %I: x column name
            y_axis_column,              -- %I: y column name
            main_table_name,            -- %I: main table name
            error_table_name            -- %I: error table name
        )
        USING min_id, max_id, x_is_numeric, y_is_numeric, x_bin_count, y_bin_count, x_axis_column, y_axis_column
        INTO result;

        RETURN result;
    END;
    $FUNC$;
    """,
    "generate_scatterplot_with_errors": """
    -- Generate scatterplot data with intelligent sampling
    -- Prioritizes rows with errors, then fills with random clean rows
    -- Simplified version: 4 CTEs instead of 10, fewer table scans
    CREATE OR REPLACE FUNCTION generate_scatterplot_with_errors(
        main_table_name text,
        error_table_name text,
        x_axis_column text,
        y_axis_column text,
        error_sample_size integer DEFAULT 30,
        total_sample_size integer DEFAULT 100,
        min_id integer DEFAULT NULL,
        max_id integer DEFAULT NULL
    ) RETURNS json
    LANGUAGE plpgsql
    AS $FUNC$
    DECLARE
        result json;
        x_is_numeric boolean;
        y_is_numeric boolean;
        x_is_mixed boolean;
        y_is_mixed boolean;
        x_has_numeric boolean;
        x_has_categorical boolean;
        y_has_numeric boolean;
        y_has_categorical boolean;
    BEGIN
        -- Check if columns are natively numeric types
        SELECT data_type IN ('integer', 'bigint', 'numeric', 'real', 'double precision', 'smallint')
        INTO x_is_numeric
        FROM information_schema.columns
        WHERE table_name = main_table_name AND column_name = x_axis_column;

        SELECT data_type IN ('integer', 'bigint', 'numeric', 'real', 'double precision', 'smallint')
        INTO y_is_numeric
        FROM information_schema.columns
        WHERE table_name = main_table_name AND column_name = y_axis_column;

        -- For TEXT columns, sample values to detect if they contain numeric strings
        IF NOT x_is_numeric THEN
            EXECUTE format($SAMPLE$
                SELECT
                    COUNT(*) FILTER (WHERE %I::text ~ '^\s*-?\d+(\.\d+)?\s*$') > 0,
                    COUNT(*) FILTER (WHERE NOT (%I::text ~ '^\s*-?\d+(\.\d+)?\s*$') AND %I IS NOT NULL) > 0
                FROM (SELECT %I FROM %I WHERE %I IS NOT NULL LIMIT 1000) sample
            $SAMPLE$, x_axis_column, x_axis_column, x_axis_column, x_axis_column, main_table_name, x_axis_column)
            INTO x_has_numeric, x_has_categorical;

            x_is_mixed := x_has_numeric AND x_has_categorical;
        ELSE
            x_is_mixed := FALSE;
        END IF;

        IF NOT y_is_numeric THEN
            EXECUTE format($SAMPLE$
                SELECT
                    COUNT(*) FILTER (WHERE %I::text ~ '^\s*-?\d+(\.\d+)?\s*$') > 0,
                    COUNT(*) FILTER (WHERE NOT (%I::text ~ '^\s*-?\d+(\.\d+)?\s*$') AND %I IS NOT NULL) > 0
                FROM (SELECT %I FROM %I WHERE %I IS NOT NULL LIMIT 1000) sample
            $SAMPLE$, y_axis_column, y_axis_column, y_axis_column, y_axis_column, main_table_name, y_axis_column)
            INTO y_has_numeric, y_has_categorical;

            y_is_mixed := y_has_numeric AND y_has_categorical;
        ELSE
            y_is_mixed := FALSE;
        END IF;

        -- Build scatterplot with intelligent sampling
        EXECUTE format($QUERY$
            WITH
            -- Step 1: Sample IDs (prioritize errors, then clean rows)
            all_sampled_ids AS (
                (
                    -- Sample error rows
                    SELECT e.row_id
                    FROM %I e
                    WHERE e.column_id IN ($1, $2)
                      AND ($3 IS NULL OR e.row_id >= $3)
                      AND ($4 IS NULL OR e.row_id <= $4)
                    ORDER BY RANDOM()
                    LIMIT $5
                )
                UNION ALL
                (
                    -- Sample clean rows to fill quota
                    SELECT "ID" as row_id
                    FROM %I
                    WHERE ($3 IS NULL OR "ID" >= $3)
                      AND ($4 IS NULL OR "ID" <= $4)
                      AND "ID" NOT IN (
                          SELECT DISTINCT row_id
                          FROM %I
                          WHERE column_id IN ($1, $2)
                            AND ($3 IS NULL OR row_id >= $3)
                            AND ($4 IS NULL OR row_id <= $4)
                      )
                    ORDER BY RANDOM()
                    LIMIT GREATEST($6 - $5, 0)
                )
            ),
            -- Step 2: Get data for sampled IDs with error aggregation
            sampled_data AS (
                SELECT
                    m."ID",
                    m.%I as x_value,
                    m.%I as y_value,
                    COALESCE(
                        json_agg(e.error_type) FILTER (WHERE e.error_type IS NOT NULL),
                        '[]'::json
                    ) as error_list
                FROM all_sampled_ids s
                JOIN %I m ON s.row_id = m."ID"
                LEFT JOIN %I e ON s.row_id = e.row_id AND e.column_id IN ($1, $2)
                GROUP BY m."ID", m.%I, m.%I
            ),
            -- Step 3: Pre-compute numeric bounds for X axis
            x_bounds AS (
                SELECT
                    MIN(x_value::numeric) as min_val,
                    MAX(x_value::numeric) as max_val
                FROM sampled_data
                WHERE $7  -- only for numeric columns
            ),
            -- Step 4: Pre-compute numeric bounds for Y axis
            y_bounds AS (
                SELECT
                    MIN(y_value::numeric) as min_val,
                    MAX(y_value::numeric) as max_val
                FROM sampled_data
                WHERE $8  -- only for numeric columns
            )
            -- Step 5: Build final result
            SELECT json_build_object(
                'data', (
                    SELECT COALESCE(json_agg(
                        json_build_object(
                            'ID', "ID",
                            'xType', CASE
                                WHEN x_value IS NULL THEN 'categorical'
                                WHEN $7 THEN 'numeric'
                                WHEN $9 AND (x_value::text ~ '^\s*-?\d+(\.\d+)?\s*$') THEN 'numeric'
                                ELSE 'categorical'
                            END,
                            'yType', CASE
                                WHEN y_value IS NULL THEN 'categorical'
                                WHEN $8 THEN 'numeric'
                                WHEN $10 AND (y_value::text ~ '^\s*-?\d+(\.\d+)?\s*$') THEN 'numeric'
                                ELSE 'categorical'
                            END,
                            'x', CASE
                                WHEN x_value IS NULL THEN to_json('null'::text)
                                WHEN $7 THEN to_json(x_value::numeric)
                                WHEN $9 AND (x_value::text ~ '^\s*-?\d+(\.\d+)?\s*$') THEN to_json(x_value::numeric)
                                ELSE to_json(x_value::text)
                            END,
                            'y', CASE
                                WHEN y_value IS NULL THEN to_json('null'::text)
                                WHEN $8 THEN to_json(y_value::numeric)
                                WHEN $10 AND (y_value::text ~ '^\s*-?\d+(\.\d+)?\s*$') THEN to_json(y_value::numeric)
                                ELSE to_json(y_value::text)
                            END,
                            'errors', error_list
                        )
                    ), '[]'::json)
                    FROM sampled_data
                ),
                'scaleX', json_build_object(
                    'numeric', CASE WHEN $7 OR $9 THEN
                        json_build_array(
                            (SELECT COALESCE(MIN(x_value::numeric), 0) FROM sampled_data
                             WHERE x_value::text ~ '^\s*-?\d+(\.\d+)?\s*$'),
                            (SELECT COALESCE(MAX(x_value::numeric), 1) + 1 FROM sampled_data
                             WHERE x_value::text ~ '^\s*-?\d+(\.\d+)?\s*$')
                        )
                    ELSE '[]'::json END,
                    'categorical', (
                        SELECT COALESCE(
                            json_agg(DISTINCT COALESCE(x_value::text, 'null') ORDER BY COALESCE(x_value::text, 'null')),
                            '["null"]'::json
                        ) FROM sampled_data
                        WHERE NOT (x_value::text ~ '^\s*-?\d+(\.\d+)?\s*$') OR x_value IS NULL
                    )
                ),
                'scaleY', json_build_object(
                    'numeric', CASE WHEN $8 OR $10 THEN
                        json_build_array(
                            (SELECT COALESCE(MIN(y_value::numeric), 0) FROM sampled_data
                             WHERE y_value::text ~ '^\s*-?\d+(\.\d+)?\s*$'),
                            (SELECT COALESCE(MAX(y_value::numeric), 1) + 1 FROM sampled_data
                             WHERE y_value::text ~ '^\s*-?\d+(\.\d+)?\s*$')
                        )
                    ELSE '[]'::json END,
                    'categorical', (
                        SELECT COALESCE(
                            json_agg(DISTINCT COALESCE(y_value::text, 'null') ORDER BY COALESCE(y_value::text, 'null')),
                            '["null"]'::json
                        ) FROM sampled_data
                        WHERE NOT (y_value::text ~ '^\s*-?\d+(\.\d+)?\s*$') OR y_value IS NULL
                    )
                )
            )
        $QUERY$,
            error_table_name,       -- %I: error table for sampling
            main_table_name,        -- %I: main table for clean sampling
            error_table_name,       -- %I: error table for NOT IN subquery
            x_axis_column,          -- %I: x column
            y_axis_column,          -- %I: y column
            main_table_name,        -- %I: main table for data join
            error_table_name,       -- %I: error table for error aggregation
            x_axis_column,          -- %I: x column in GROUP BY
            y_axis_column           -- %I: y column in GROUP BY
        )
        USING x_axis_column, y_axis_column, min_id, max_id, error_sample_size, total_sample_size, x_is_numeric, y_is_numeric, x_is_mixed, y_is_mixed
        INTO result;

        RETURN result;
    END;
    $FUNC$;
    """,
    # Add more functions here as needed
    # "another_function_name": """CREATE OR REPLACE FUNCTION...""",

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
                    -- fallback: treat unknown method as zscore
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
    """

}


def initialize_database_functions(engine):
    """
    Create all custom database functions on startup
    """
    logger.info("Initializing database functions...")

    try:
        with engine.connect() as conn:
            # Begin a transaction
            trans = conn.begin()

            for func_name, func_sql in DB_FUNCTIONS.items():
                try:
                    logger.info(f"Creating function: {func_name}")
                    conn.execute(text(func_sql))
                    logger.info(f"Successfully created function: {func_name}")
                except Exception as e:
                    logger.error(f"Failed to create function {func_name}: {str(e)}")
                    trans.rollback()
                    raise

            # Commit all functions
            trans.commit()
            logger.info("All database functions initialized successfully!")

    except Exception as e:
        logger.error(f"Database function initialization failed: {str(e)}")
        raise


##############################################################################################################
# DEPRECATED FUNCTIONS - KEPT FOR REFERENCE
##############################################################################################################

DEPRECATED_FUNCTIONS = {
    "generate_one_d_histogram_with_errors_ORIGINAL": """
    -- DEPRECATED: Original working version with separate IF/ELSE paths
    -- This is the proven working version - kept for rollback if needed

    CREATE OR REPLACE FUNCTION generate_one_d_histogram_with_errors_ORIGINAL(
        main_table_name text,
        error_table_name text,
        axis_column text,
        bin_count integer DEFAULT 10,
        min_id integer DEFAULT NULL,
        max_id integer DEFAULT NULL
    ) RETURNS json
    LANGUAGE plpgsql
    AS $FUNC$
    DECLARE
        result json;
        quoted_column text;
        column_type text;
        is_numeric boolean;
        id_filter text;
        error_id_filter text;
    BEGIN
        quoted_column := '"' || axis_column || '"';

        -- Build ID filter conditions
        IF min_id IS NOT NULL AND max_id IS NOT NULL THEN
            id_filter := format(' AND "ID" BETWEEN %s AND %s', min_id, max_id);
            error_id_filter := format(' AND m2."ID" BETWEEN %s AND %s', min_id, max_id);
        ELSIF min_id IS NOT NULL THEN
            id_filter := format(' AND "ID" >= %s', min_id);
            error_id_filter := format(' AND m2."ID" >= %s', min_id);
        ELSIF max_id IS NOT NULL THEN
            id_filter := format(' AND "ID" <= %s', max_id);
            error_id_filter := format(' AND m2."ID" <= %s', max_id);
        ELSE
            id_filter := '';
            error_id_filter := '';
        END IF;

        -- Determine if column is numeric
        EXECUTE format('
            SELECT data_type
            FROM information_schema.columns
            WHERE table_name = %L AND column_name = %L',
            main_table_name, axis_column
        ) INTO column_type;

        is_numeric := column_type IN ('integer', 'bigint', 'numeric', 'real', 'double precision', 'smallint');

        IF is_numeric THEN
            -- Numeric binning logic with errors and ID filtering
            EXECUTE format('
                WITH bin_ranges AS (
                    SELECT
                        generate_series(0, %s-1) as bin_num,
                        min_val + (generate_series(0, %s-1) * bin_width) as x0,
                        min_val + (generate_series(1, %s) * bin_width) as x1
                    FROM (
                        SELECT
                            MIN(%s::numeric) as min_val,
                            MAX(%s::numeric) as max_val,
                            (MAX(%s::numeric) - MIN(%s::numeric)) / %s::numeric as bin_width
                        FROM %I
                        WHERE %s IS NOT NULL%s
                    ) bounds
                ),
                data_with_bins AS (
                    SELECT
                        m."ID",
                        br.bin_num,
                        br.x0,
                        br.x1
                    FROM %I m
                    JOIN bin_ranges br ON m.%s::numeric >= br.x0 AND m.%s::numeric < br.x1
                    WHERE m.%s IS NOT NULL%s
                ),
                binned_counts AS (
                    SELECT
                        bin_num,
                        x0,
                        x1,
                        COUNT(*) as item_count
                    FROM data_with_bins
                    GROUP BY bin_num, x0, x1
                ),
                error_counts AS (
                    SELECT
                        dwb.bin_num,
                        e.error_type,
                        COUNT(*) as error_count
                    FROM data_with_bins dwb
                    JOIN %I e ON dwb."ID" = e.row_id
                    WHERE e.column_id = %L AND e.row_id IS NOT NULL
                    GROUP BY dwb.bin_num, e.error_type
                ),
                final_bins AS (
                    SELECT
                        bc.bin_num,
                        bc.x0,
                        bc.x1,
                        bc.item_count,
                        CASE
                            WHEN error_agg.error_json IS NULL THEN
                                json_build_object(''items'', bc.item_count)
                            ELSE
                                (error_agg.error_json::jsonb || json_build_object(''items'', bc.item_count)::jsonb)::json
                        END as count_obj
                    FROM binned_counts bc
                    LEFT JOIN (
                        SELECT
                            bin_num,
                            json_object_agg(error_type, error_count) as error_json
                        FROM error_counts
                        GROUP BY bin_num
                    ) error_agg ON bc.bin_num = error_agg.bin_num
                ),
                numeric_scale AS (
                    SELECT json_agg(
                        json_build_object(''x0'', x0, ''x1'', x1)
                    ) as numeric_bins
                    FROM bin_ranges
                )
                SELECT json_build_object(
                    ''histograms'', json_agg(
                        json_build_object(
                            ''count'', count_obj,
                            ''xBin'', bin_num,
                            ''xType'', ''numeric''
                        ) ORDER BY bin_num
                    ),
                    ''scaleX'', json_build_object(
                        ''categorical'', ''[]''::json,
                        ''numeric'', (SELECT numeric_bins FROM numeric_scale)
                    )
                )
                FROM final_bins',
                bin_count, bin_count, bin_count,
                quoted_column, quoted_column, quoted_column, quoted_column, bin_count,
                main_table_name, quoted_column, id_filter,
                main_table_name, quoted_column, quoted_column, quoted_column, id_filter,
                error_table_name, axis_column
            ) INTO result;
        ELSE
            -- Categorical logic with ID filtering
            EXECUTE format('
                SELECT json_build_object(
                    ''histograms'', json_agg(
                        json_build_object(
                            ''count'', count_obj,
                            ''xBin'', bin_value,
                            ''xType'', ''categorical''
                        )
                    ),
                    ''scaleX'', json_build_object(
                        ''categorical'', array_agg(DISTINCT bin_value),
                        ''numeric'', ''[]''::json
                    )
                )
                FROM (
                    SELECT
                        m.bin_value,
                        CASE
                            WHEN error_counts IS NULL THEN
                                json_build_object(''items'', item_count)
                            ELSE
                                (error_counts::jsonb || json_build_object(''items'', item_count)::jsonb)::json
                        END as count_obj
                    FROM (
                        SELECT %s as bin_value, COUNT(*) as item_count
                        FROM %I
                        WHERE %s IS NOT NULL%s
                        GROUP BY %s
                    ) m
                    LEFT JOIN (
                        SELECT
                            main_val,
                            json_object_agg(error_type, error_count)::json as error_counts
                        FROM (
                            SELECT
                                m2.%s as main_val,
                                e.error_type,
                                COUNT(*) as error_count
                            FROM %I m2
                            JOIN %I e ON m2."ID" = e.row_id
                            WHERE e.column_id = %L AND e.row_id IS NOT NULL%s
                            GROUP BY m2.%s, e.error_type
                        ) error_summary
                        GROUP BY main_val
                    ) errors ON m.bin_value = errors.main_val
                ) final_data',
                quoted_column, main_table_name, quoted_column, id_filter, quoted_column,
                quoted_column, main_table_name, error_table_name, axis_column, error_id_filter, quoted_column
            ) INTO result;
        END IF;

        RETURN result;
    END;
    $FUNC$;
    """,
    "generate_two_d_histogram_with_errors_ORIGINAL": """
    -- DEPRECATED: Original working version with separate IF/ELSE paths for each type combination
    -- This is the proven working version - kept for rollback if needed
    -- This version had 4 separate branches: numeric×numeric, numeric×categorical, categorical×numeric, categorical×categorical

     CREATE OR REPLACE FUNCTION generate_two_d_histogram_with_errors_ORIGINAL(
        main_table_name text,
        error_table_name text,
        x_axis_column text,
        y_axis_column text,
        x_bin_count integer DEFAULT 10,
        y_bin_count integer DEFAULT 10,
        min_id integer DEFAULT NULL,
        max_id integer DEFAULT NULL
    ) RETURNS json
    LANGUAGE plpgsql
    AS $FUNC$
    DECLARE
        result json;
        quoted_x_column text;
        quoted_y_column text;
        x_column_type text;
        y_column_type text;
        x_is_numeric boolean;
        y_is_numeric boolean;
        id_filter text;
        error_id_filter text;
    BEGIN
        quoted_x_column := '"' || x_axis_column || '"';
        quoted_y_column := '"' || y_axis_column || '"';

        -- Build ID filter conditions (same as 1D)
        IF min_id IS NOT NULL AND max_id IS NOT NULL THEN
            id_filter := format(' AND "ID" BETWEEN %s AND %s', min_id, max_id);
            error_id_filter := format(' AND m2."ID" BETWEEN %s AND %s', min_id, max_id);
        ELSIF min_id IS NOT NULL THEN
            id_filter := format(' AND "ID" >= %s', min_id);
            error_id_filter := format(' AND m2."ID" >= %s', min_id);
        ELSIF max_id IS NOT NULL THEN
            id_filter := format(' AND "ID" <= %s', max_id);
            error_id_filter := format(' AND m2."ID" <= %s', max_id);
        ELSE
            id_filter := '';
            error_id_filter := '';
        END IF;

        -- Determine column types (same as 1D)
        EXECUTE format('
            SELECT data_type
            FROM information_schema.columns
            WHERE table_name = %L AND column_name = %L',
            main_table_name, x_axis_column
        ) INTO x_column_type;

        EXECUTE format('
            SELECT data_type
            FROM information_schema.columns
            WHERE table_name = %L AND column_name = %L',
            main_table_name, y_axis_column
        ) INTO y_column_type;

        x_is_numeric := x_column_type IN ('integer', 'bigint', 'numeric', 'real', 'double precision', 'smallint');
        y_is_numeric := y_column_type IN ('integer', 'bigint', 'numeric', 'real', 'double precision', 'smallint');

        IF x_is_numeric AND y_is_numeric THEN
            -- Both numeric
            EXECUTE format('
                WITH x_bin_ranges AS (
                    SELECT
                        generate_series(0, %s-1) as x_bin_num,
                        min_val + (generate_series(0, %s-1) * bin_width) as x0,
                        min_val + (generate_series(1, %s) * bin_width) as x1
                    FROM (
                        SELECT
                            MIN(%s::numeric) as min_val,
                            MAX(%s::numeric) as max_val,
                            (MAX(%s::numeric) - MIN(%s::numeric)) / %s::numeric as bin_width
                        FROM %I
                        WHERE %s IS NOT NULL%s
                    ) bounds
                ),
                y_bin_ranges AS (
                    SELECT
                        generate_series(0, %s-1) as y_bin_num,
                        min_val + (generate_series(0, %s-1) * bin_width) as y0,
                        min_val + (generate_series(1, %s) * bin_width) as y1
                    FROM (
                        SELECT
                            MIN(%s::numeric) as min_val,
                            MAX(%s::numeric) as max_val,
                            (MAX(%s::numeric) - MIN(%s::numeric)) / %s::numeric as bin_width
                        FROM %I
                        WHERE %s IS NOT NULL%s
                    ) bounds
                ),
                all_bins AS (
                    SELECT
                        xbr.x_bin_num,
                        ybr.y_bin_num,
                        xbr.x0,
                        xbr.x1,
                        ybr.y0,
                        ybr.y1
                    FROM x_bin_ranges xbr
                    CROSS JOIN y_bin_ranges ybr
                ),
                data_with_bins AS (
                    SELECT
                        m."ID",
                        ab.x_bin_num,
                        ab.y_bin_num
                    FROM %I m
                    JOIN all_bins ab ON
                        m.%s::numeric >= ab.x0 AND m.%s::numeric < ab.x1 AND
                        m.%s::numeric >= ab.y0 AND m.%s::numeric < ab.y1
                    WHERE m.%s IS NOT NULL AND m.%s IS NOT NULL%s
                ),
                binned_counts AS (
                    SELECT
                        x_bin_num,
                        y_bin_num,
                        COUNT(*) as item_count
                    FROM data_with_bins
                    GROUP BY x_bin_num, y_bin_num
                ),
                error_counts AS (
                    SELECT
                        dwb.x_bin_num,
                        dwb.y_bin_num,
                        e.error_type,
                        COUNT(*) as error_count
                    FROM data_with_bins dwb
                    JOIN %I e ON dwb."ID" = e.row_id
                    WHERE (e.column_id = %L OR e.column_id = %L) AND e.row_id IS NOT NULL
                    GROUP BY dwb.x_bin_num, dwb.y_bin_num, e.error_type
                ),
                final_bins AS (
                    SELECT
                        bc.x_bin_num,
                        bc.y_bin_num,
                        bc.item_count,
                        CASE
                            WHEN error_agg.error_json IS NULL THEN
                                json_build_object(''items'', bc.item_count)
                            ELSE
                                (error_agg.error_json::jsonb || json_build_object(''items'', bc.item_count)::jsonb)::json
                        END as count_obj
                    FROM binned_counts bc
                    LEFT JOIN (
                        SELECT
                            x_bin_num,
                            y_bin_num,
                            json_object_agg(error_type, error_count) as error_json
                        FROM error_counts
                        GROUP BY x_bin_num, y_bin_num
                    ) error_agg ON bc.x_bin_num = error_agg.x_bin_num AND bc.y_bin_num = error_agg.y_bin_num
                ),
                x_scale AS (
                    SELECT json_agg(
                        json_build_object(''x0'', x0, ''x1'', x1) ORDER BY x_bin_num
                    ) as x_numeric_bins
                    FROM x_bin_ranges
                ),
                y_scale AS (
                    SELECT json_agg(
                        json_build_object(''x0'', y0, ''x1'', y1) ORDER BY y_bin_num
                    ) as y_numeric_bins
                    FROM y_bin_ranges
                )
                SELECT json_build_object(
                    ''histograms'', json_agg(
                        json_build_object(
                            ''count'', count_obj,
                            ''xBin'', x_bin_num,
                            ''yBin'', y_bin_num,
                            ''xType'', ''numeric'',
                            ''yType'', ''numeric''
                        ) ORDER BY x_bin_num, y_bin_num
                    ),
                    ''scaleX'', json_build_object(
                        ''categorical'', ''[]''::json,
                        ''numeric'', (SELECT x_numeric_bins FROM x_scale)
                    ),
                    ''scaleY'', json_build_object(
                        ''categorical'', ''[]''::json,
                        ''numeric'', (SELECT y_numeric_bins FROM y_scale)
                    )
                )
                FROM final_bins',
                x_bin_count, x_bin_count, x_bin_count,
                quoted_x_column, quoted_x_column, quoted_x_column, quoted_x_column, x_bin_count,
                main_table_name, quoted_x_column, id_filter,
                y_bin_count, y_bin_count, y_bin_count,
                quoted_y_column, quoted_y_column, quoted_y_column, quoted_y_column, y_bin_count,
                main_table_name, quoted_y_column, id_filter,
                main_table_name, quoted_x_column, quoted_x_column, quoted_y_column, quoted_y_column, quoted_x_column, quoted_y_column, id_filter,
                error_table_name, x_axis_column, y_axis_column
            ) INTO result;

        ELSIF x_is_numeric AND NOT y_is_numeric THEN
            -- X numeric, Y categorical
            EXECUTE format('
                WITH x_bin_ranges AS (
                    SELECT
                        generate_series(0, %s-1) as x_bin_num,
                        min_val + (generate_series(0, %s-1) * bin_width) as x0,
                        min_val + (generate_series(1, %s) * bin_width) as x1
                    FROM (
                        SELECT
                            MIN(%s::numeric) as min_val,
                            MAX(%s::numeric) as max_val,
                            (MAX(%s::numeric) - MIN(%s::numeric)) / %s::numeric as bin_width
                        FROM %I
                        WHERE %s IS NOT NULL%s
                    ) bounds
                ),
                y_categories AS (
                    SELECT DISTINCT %s as y_value
                    FROM %I
                    WHERE %s IS NOT NULL%s
                ),
                all_bins AS (
                    SELECT
                        xbr.x_bin_num,
                        yc.y_value,
                        xbr.x0,
                        xbr.x1
                    FROM x_bin_ranges xbr
                    CROSS JOIN y_categories yc
                ),
                data_with_bins AS (
                    SELECT
                        m."ID",
                        ab.x_bin_num,
                        ab.y_value
                    FROM %I m
                    JOIN all_bins ab ON
                        m.%s::numeric >= ab.x0 AND m.%s::numeric < ab.x1 AND
                        m.%s = ab.y_value
                    WHERE m.%s IS NOT NULL AND m.%s IS NOT NULL%s
                ),
                binned_counts AS (
                    SELECT
                        x_bin_num,
                        y_value,
                        COUNT(*) as item_count
                    FROM data_with_bins
                    GROUP BY x_bin_num, y_value
                ),
                error_counts AS (
                    SELECT
                        dwb.x_bin_num,
                        dwb.y_value,
                        e.error_type,
                        COUNT(*) as error_count
                    FROM data_with_bins dwb
                    JOIN %I e ON dwb."ID" = e.row_id
                    WHERE (e.column_id = %L OR e.column_id = %L) AND e.row_id IS NOT NULL
                    GROUP BY dwb.x_bin_num, dwb.y_value, e.error_type
                ),
                final_bins AS (
                    SELECT
                        bc.x_bin_num,
                        bc.y_value,
                        bc.item_count,
                        CASE
                            WHEN error_agg.error_json IS NULL THEN
                                json_build_object(''items'', bc.item_count)
                            ELSE
                                (error_agg.error_json::jsonb || json_build_object(''items'', bc.item_count)::jsonb)::json
                        END as count_obj
                    FROM binned_counts bc
                    LEFT JOIN (
                        SELECT
                            x_bin_num,
                            y_value,
                            json_object_agg(error_type, error_count) as error_json
                        FROM error_counts
                        GROUP BY x_bin_num, y_value
                    ) error_agg ON bc.x_bin_num = error_agg.x_bin_num AND bc.y_value = error_agg.y_value
                ),
                x_scale AS (
                    SELECT json_agg(
                        json_build_object(''x0'', x0, ''x1'', x1) ORDER BY x_bin_num
                    ) as x_numeric_bins
                    FROM x_bin_ranges
                )
                SELECT json_build_object(
                    ''histograms'', json_agg(
                        json_build_object(
                            ''count'', count_obj,
                            ''xBin'', x_bin_num,
                            ''yBin'', y_value,
                            ''xType'', ''numeric'',
                            ''yType'', ''categorical''
                        ) ORDER BY x_bin_num, y_value
                    ),
                    ''scaleX'', json_build_object(
                        ''categorical'', ''[]''::json,
                        ''numeric'', (SELECT x_numeric_bins FROM x_scale)
                    ),
                    ''scaleY'', json_build_object(
                        ''categorical'', array_agg(DISTINCT y_value ORDER BY y_value),
                        ''numeric'', ''[]''::json
                    )
                )
                FROM final_bins',
                x_bin_count, x_bin_count, x_bin_count,
                quoted_x_column, quoted_x_column, quoted_x_column, quoted_x_column, x_bin_count,
                main_table_name, quoted_x_column, id_filter,
                quoted_y_column, main_table_name, quoted_y_column, id_filter,
                main_table_name, quoted_x_column, quoted_x_column, quoted_y_column, quoted_x_column, quoted_y_column, id_filter,
                error_table_name, x_axis_column, y_axis_column
            ) INTO result;

        ELSIF NOT x_is_numeric AND y_is_numeric THEN
            -- X categorical, Y numeric
            EXECUTE format('
                WITH y_bin_ranges AS (
                    SELECT
                        generate_series(0, %s-1) as y_bin_num,
                        min_val + (generate_series(0, %s-1) * bin_width) as y0,
                        min_val + (generate_series(1, %s) * bin_width) as y1
                    FROM (
                        SELECT
                            MIN(%s::numeric) as min_val,
                            MAX(%s::numeric) as max_val,
                            (MAX(%s::numeric) - MIN(%s::numeric)) / %s::numeric as bin_width
                        FROM %I
                        WHERE %s IS NOT NULL%s
                    ) bounds
                ),
                x_categories AS (
                    SELECT DISTINCT %s as x_value
                    FROM %I
                    WHERE %s IS NOT NULL%s
                ),
                all_bins AS (
                    SELECT
                        xc.x_value,
                        ybr.y_bin_num,
                        ybr.y0,
                        ybr.y1
                    FROM x_categories xc
                    CROSS JOIN y_bin_ranges ybr
                ),
                data_with_bins AS (
                    SELECT
                        m."ID",
                        ab.x_value,
                        ab.y_bin_num
                    FROM %I m
                    JOIN all_bins ab ON
                        m.%s = ab.x_value AND
                        m.%s::numeric >= ab.y0 AND m.%s::numeric < ab.y1
                    WHERE m.%s IS NOT NULL AND m.%s IS NOT NULL%s
                ),
                binned_counts AS (
                    SELECT
                        x_value,
                        y_bin_num,
                        COUNT(*) as item_count
                    FROM data_with_bins
                    GROUP BY x_value, y_bin_num
                ),
                error_counts AS (
                    SELECT
                        dwb.x_value,
                        dwb.y_bin_num,
                        e.error_type,
                        COUNT(*) as error_count
                    FROM data_with_bins dwb
                    JOIN %I e ON dwb."ID" = e.row_id
                    WHERE (e.column_id = %L OR e.column_id = %L) AND e.row_id IS NOT NULL
                    GROUP BY dwb.x_value, dwb.y_bin_num, e.error_type
                ),
                final_bins AS (
                    SELECT
                        bc.x_value,
                        bc.y_bin_num,
                        bc.item_count,
                        CASE
                            WHEN error_agg.error_json IS NULL THEN
                                json_build_object(''items'', bc.item_count)
                            ELSE
                                (error_agg.error_json::jsonb || json_build_object(''items'', bc.item_count)::jsonb)::json
                        END as count_obj
                    FROM binned_counts bc
                    LEFT JOIN (
                        SELECT
                            x_value,
                            y_bin_num,
                            json_object_agg(error_type, error_count) as error_json
                        FROM error_counts
                        GROUP BY x_value, y_bin_num
                    ) error_agg ON bc.x_value = error_agg.x_value AND bc.y_bin_num = error_agg.y_bin_num
                ),
                y_scale AS (
                    SELECT json_agg(
                        json_build_object(''x0'', y0, ''x1'', y1) ORDER BY y_bin_num
                    ) as y_numeric_bins
                    FROM y_bin_ranges
                )
                SELECT json_build_object(
                    ''histograms'', json_agg(
                        json_build_object(
                            ''count'', count_obj,
                            ''xBin'', x_value,
                            ''yBin'', y_bin_num,
                            ''xType'', ''categorical'',
                            ''yType'', ''numeric''
                        ) ORDER BY x_value, y_bin_num
                    ),
                    ''scaleX'', json_build_object(
                        ''categorical'', array_agg(DISTINCT x_value ORDER BY x_value),
                        ''numeric'', ''[]''::json
                    ),
                    ''scaleY'', json_build_object(
                        ''categorical'', ''[]''::json,
                        ''numeric'', (SELECT y_numeric_bins FROM y_scale)
                    )
                )
                FROM final_bins',
                y_bin_count, y_bin_count, y_bin_count,
                quoted_y_column, quoted_y_column, quoted_y_column, quoted_y_column, y_bin_count,
                main_table_name, quoted_y_column, id_filter,
                quoted_x_column, main_table_name, quoted_x_column, id_filter,
                main_table_name, quoted_x_column, quoted_y_column, quoted_y_column, quoted_x_column, quoted_y_column, id_filter,
                error_table_name, x_axis_column, y_axis_column
            ) INTO result;

        ELSE
            -- Both categorical
            EXECUTE format('
                SELECT json_build_object(
                    ''histograms'', json_agg(
                        json_build_object(
                            ''count'', count_obj,
                            ''xBin'', x_value,
                            ''yBin'', y_value,
                            ''xType'', ''categorical'',
                            ''yType'', ''categorical''
                        ) ORDER BY x_value, y_value
                    ),
                    ''scaleX'', json_build_object(
                        ''categorical'', array_agg(DISTINCT x_value ORDER BY x_value),
                        ''numeric'', ''[]''::json
                    ),
                    ''scaleY'', json_build_object(
                        ''categorical'', array_agg(DISTINCT y_value ORDER BY y_value),
                        ''numeric'', ''[]''::json
                    )
                )
                FROM (
                    SELECT
                        m.x_value,
                        m.y_value,
                        CASE
                            WHEN error_counts IS NULL THEN
                                json_build_object(''items'', item_count)
                            ELSE
                                (error_counts::jsonb || json_build_object(''items'', item_count)::jsonb)::json
                        END as count_obj
                    FROM (
                        SELECT %s as x_value, %s as y_value, COUNT(*) as item_count
                        FROM %I
                        WHERE %s IS NOT NULL AND %s IS NOT NULL%s
                        GROUP BY %s, %s
                    ) m
                    LEFT JOIN (
                        SELECT
                            x_main_val,
                            y_main_val,
                            json_object_agg(error_type, error_count)::json as error_counts
                        FROM (
                            SELECT
                                m2.%s as x_main_val,
                                m2.%s as y_main_val,
                                e.error_type,
                                COUNT(*) as error_count
                            FROM %I m2
                            JOIN %I e ON m2."ID" = e.row_id
                            WHERE (e.column_id = %L OR e.column_id = %L) AND e.row_id IS NOT NULL%s
                            GROUP BY m2.%s, m2.%s, e.error_type
                        ) error_summary
                        GROUP BY x_main_val, y_main_val
                    ) errors ON m.x_value = errors.x_main_val AND m.y_value = errors.y_main_val
                ) final_data',
                quoted_x_column, quoted_y_column, main_table_name, quoted_x_column, quoted_y_column, id_filter, quoted_x_column, quoted_y_column,
                quoted_x_column, quoted_y_column, main_table_name, error_table_name, x_axis_column, y_axis_column, error_id_filter, quoted_x_column, quoted_y_column
            ) INTO result;
        END IF;

        RETURN result;
    END;
    $FUNC$;
    """
}
