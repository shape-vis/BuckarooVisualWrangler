from app.execute_sql import fetch_sql, execute_sql

"""
Manages detector and wrangler operations across a main dataset.
Subset class of DBOperations.
"""

class DetectorWranglerSQL:

    def __init__(self, engine, main_table_name, numeric_cols, pure_categorical, categorical_mixed):
        self.engine = engine
        self.main_table_name = main_table_name
        self.numeric_cols = numeric_cols.copy()
        self.numeric_cols.pop("ID")
        self.pure_categorical = pure_categorical
        self.categorical_mixed = categorical_mixed


    def anomaly_outliers(self, methods: list, p_threshold: list = None) -> str:
        """
        Creates the full SQL query to apply each selected anomaly type to each numeric column.

        :arg: methods     - a list of anomaly types to apply.
        :arg: p_threshold - a list of thresholds to apply for each anomaly type respectively.
                          - Null by default automatically populates reasonable threhsolds.
        :return: full SQL query to gather all anomaly values.
        """

        if len(methods) == 0 or len(self.numeric_cols) == 0:
            return []

        if p_threshold is None:
            p_threshold = [3, 1.5, 3]

        col_anomaly_queries = ["("]
        for col in self.numeric_cols:
            # Filter out null values.
            nonnull_col = self.cte_nonnull_col(col, "numeric")

            # Each nonnull col CTE is in anomaly query scope.
            anomaly_queries = ["(", nonnull_col]

            for method in methods:
                if method.tolower() == "mad":
                    anomaly_query = f"SELECT * FROM ({self.build_mad_query(p_threshold[0])}) AS mad"
                elif method.tolower() == "iqr":
                    anomaly_query = f"SELECT * FROM ({self.build_iqr_query(p_threshold[1])}) AS iqr"
                # Default to z-score if nothing else is applicable.
                else:
                    anomaly_query = f"SELECT * FROM ({self.build_zscore_query(p_threshold[2])}) AS zscore"

                anomaly_queries.append(anomaly_query)

            anomaly_queries.append(")")
            formatted_col_query = "".join(anomaly_queries)

            # Adds a formatted CTE of type (col, nonnull_col (anomaly method 1 UNION ALL method 2...))
            col_anomaly_queries.append(formatted_col_query)

        col_anomaly_queries.append(")")

        # Formats all the anomaly queries for each column.
        return "\nUNION ALL\n".join(col_anomaly_queries)


    def cte_nonnull_col(self, col: str, col_type: str) -> str:
        """
        Creates the CTE for all non-null values of a selected column.

        :arg: col      - the col to get all non-null values.
        :arg: col_type - the type of the column, e.g. "numeric" or "text"
        :return: CTE query for the non-null values of a chosen column.
        """

        return f'''WITH nonnull_col AS (
                   SELECT "ID"::int, "{col}"::{col_type} as current_col
                   FROM "{self.main_table_name}"
                   WHERE "{col}" IS NOT NULL)'''


    def build_mad_query(self, p_threshold):
        # Assumes nonnull_col already exists from earlier.
        if p_threshold is None:
            p_threshold = 3

        # Get the median value of the column.
        median_cte = f''',\n median_cte AS (
                         SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY current_col) AS median_val
                         FROM nonnull_col)'''

        # Gather the absolute deviations for each numeric value.
        absolute_deviations = f''',\n absolute_deviations AS (
                                SELECT ABS(current_col - median_val) AS abs_dev
                                FROM nonnull_col, median_cte)'''

        # Get the median of the absolute deviations, gets the median absolute deviation (MAD).
        mad_deviation = f''',\n mad_deviation AS (
                             SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY abs_dev) AS mad_dev
                             FROM absolute_deviations)'''

        # Get the anomalies which satisfy MAD.
        get_mad_errors = f'''\n SELECT "ID", current_col, 'mad_anomaly'
                                FROM nonnull_col, median_cte, mad_deviation
                                WHERE mad_dev IS NOT NULL
                                AND mad_dev > 0
                                AND ABS(0.6745 * (current_col - median_val) / mad_dev) > {p_threshold}'''

        return "".join([median_cte, absolute_deviations, mad_deviation, get_mad_errors])


    def build_iqr_query(self, p_threshold):
        if p_threshold is None:
            p_threshold = 1.5

        # get the 25% and 75% quartiles.
        quartiles = f''',\n quartiles AS (
                        SELECT PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY current_col) AS q1,
                               PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY current_col) AS q3)
                        FROM nonnull_col)'''


        # calculate the quartile fences to get outliers.
        quartile_fences = f''',\n quartile_fences AS (
                              SELECT 
                                (q3 - q1) AS iqr,
                                (q1 - ({p_threshold} * (q3 - q1))) AS lower_bound,
                                (q3 + ({p_threshold} * (q3 - q1))) AS upper_bound
                              FROM quartiles)'''

        # obtain outliers from quartile fence bounds.
        get_iqr_anomalies = f'''\n SELECT "ID", current_col, 'iqr_anomaly'
                                   FROM nonnull_col, quartile_fences
                                   WHERE iqr IS NOT NULL
                                   AND iqr > 0
                                   AND (nonnull_col < lower_bound OR nonnull_col > upper_bound)'''

        return "".join([quartiles, quartile_fences, get_iqr_anomalies])


    def build_zscore_query(self, p_threshold):
        if p_threshold is None:
            p_threshold = 3

        # Get the mean and standard deviation.
        stats = f''',\n stats AS (
                    SELECT AVG(current_col) AS mean_val, STDDEV_SAMP(current_col) AS std_val
                    FROM nonnull_col)'''

        # Gather zscore anomalies by checking how many standard deviations away from the mean a value is.
        gather_zscore_anomalies = f'''\n SELECT "ID", current_col, 'zscore_anomaly'
                                      FROM nonnull_col, stats
                                      WHERE std_val IS NOT NULL
                                      AND std_val > 0
                                      AND ABS((nonnull_col - mean_val) / std_val) > {p_threshold}'''

        return "".join([stats, gather_zscore_anomalies])




