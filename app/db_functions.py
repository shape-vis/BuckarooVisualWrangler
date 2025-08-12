# file to store all db functions the app will need to use

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Dictionary to store all the database functions
# Dictionary to store all your database functions
DB_FUNCTIONS = {
    "generate_one_d_histogram_with_errors": """
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
    "generate_two_d_histogram_with_errors": """
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
    """,

    # Add more functions here as needed
    # "another_function_name": """CREATE OR REPLACE FUNCTION...""",
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