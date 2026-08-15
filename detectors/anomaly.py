import numpy as np
import pandas as pd

from detectors.common import error_value, merged_config


def anomaly(data_frame, include_skipped=False, numeric_cache=None, include_details=False, config=None):
    """
    Detect numeric outliers using a robust method by default.

    :param numeric_cache: optional {column: numeric Series} mapping so callers
        that run several detectors can share a single pd.to_numeric pass over
        the data instead of recomputing it per detector.
    :param include_details: when true, return structured error records with
        severity, confidence, and reason. The default preserves the legacy
        {column: {row_id: "anomaly"}} contract used by the app.
    :param config: optional detector threshold overrides.
    :return:
    """
    # Pull the shared defaults from detectors.common, then layer any caller
    # overrides on top.  Keeping this as the first step means every threshold
    # read below has a defined value even when config=None.
    config = merged_config(config)

    # error_map preserves the legacy detector contract:
    #   {column_name: {row_id: error_label_or_metadata}}
    # The UI and downstream service helpers already understand this shape.
    error_map = {}

    # skipped_columns is only returned when include_skipped=True.  It is useful
    # for tests, profiling, and debugging because a column can be skipped for
    # several legitimate reasons instead of simply having no anomalies.
    skipped_columns = {}

    # Store row IDs once so we can map boolean masks back to Buckaroo's stable
    # row identifiers without repeatedly indexing the dataframe inside the loop.
    id_values = data_frame['ID'].to_numpy()

    # The first column is the Buckaroo ID column, so anomaly detection starts at
    # columns[1:].  Every remaining column is attempted as numeric because CSV
    # uploads often keep numeric-looking values as object/string dtype.
    for column in data_frame.columns[1:]:
        # Reuse a caller-provided numeric conversion when available.  run_detectors
        # builds this cache because anomaly and incomplete both need numeric
        # views of the same columns, and pd.to_numeric can be expensive on large
        # uploads.
        if numeric_cache is not None and column in numeric_cache:
            numeric_col = numeric_cache[column]
        else:
            # Non-numeric cells become NaN rather than raising.  This lets a
            # mostly-numeric column still be analyzed while ignoring text noise.
            numeric_col = pd.to_numeric(data_frame[column], errors='coerce')

        # Count valid numeric values after coercion.  This is the true sample
        # size for anomaly detection, not the raw dataframe row count.
        numeric_count = int(numeric_col.notna().sum())

        # A very small numeric sample makes quartiles, medians, standard
        # deviations, and skew unreliable.  Skipping under 10 values avoids
        # overconfident anomaly labels in tiny columns.
        if numeric_count < 10:
            skipped_columns[column] = {
                "reason": "fewer_than_10_numeric_values",
                "numeric_count": numeric_count,
            }
            continue

        # _outlier_mask chooses the configured method and may fall back to a
        # second robust method when the preferred one is mathematically unusable
        # for this column, for example when IQR or MAD is zero.
        mask, method, reason = _outlier_mask(numeric_col, config)

        # A None mask means every attempted method failed safely.  Common causes
        # are constant columns, nearly constant columns, or columns whose spread
        # statistic is missing.
        if mask is None:
            skipped_columns[column] = {
                "reason": reason,
                "numeric_count": numeric_count,
            }
            continue

        # Convert the pandas Series mask into a NumPy array so it can index the
        # cached id_values array positionally.
        anomaly_mask = mask.to_numpy()

        # Only include columns that actually have anomalies.  Columns with a
        # valid mask but no True values are clean and omitted from error_map.
        if anomaly_mask.any():
            error_map[column] = {
                int(row_id): error_value(
                    # New structured metadata calls this a numeric_outlier, but
                    # legacy callers still receive "anomaly" via legacy_error_type.
                    "numeric_outlier",
                    include_details=include_details,
                    legacy_error_type="anomaly",
                    severity="warning",
                    # IQR and MAD are distribution-resistant robust statistics,
                    # so their detections are reported with higher confidence
                    # than z-score detections, which are more sensitive to skew.
                    confidence="high" if method in {"iqr", "mad"} else "medium",
                    reason=reason,
                    method=method,
                )
                for row_id in id_values[anomaly_mask]
            }

    # include_skipped is intentionally opt-in so the production UI keeps the old
    # lightweight return shape, while tests/debug tooling can inspect why a
    # column did not produce anomaly labels.
    if include_skipped:
        return {
            "errors": error_map,
            "skipped": skipped_columns,
        }
    return error_map

def anomaly_sql(table_name: str, err_table_name: str) -> str:
    """
    determines whether a cell in a column of numeric values has a zscore > 2
    :return: the CTEs for the anomaly table.
    """

    query = f''''''


def _outlier_mask(numeric_col: pd.Series, config: dict):
    # Work only on numeric values that survived pd.to_numeric.  Missing and
    # non-numeric cells remain part of the original index but should not affect
    # distribution statistics.
    valid = numeric_col.dropna()

    # anomaly_method is intentionally configurable so experiments can compare
    # IQR, MAD, and z-score behavior without editing detector code.
    method = str(config.get("anomaly_method", "iqr")).lower()

    # Convert to float so log transforms and arithmetic use a predictable
    # numeric dtype even if pandas inferred integers or nullable numeric types.
    transformed = valid.astype(float)
    used_log = False

    # Skewed positive distributions, such as salary or population, can make raw
    # IQR/MAD thresholds too aggressive on the long tail.  A log1p transform
    # compresses that tail while preserving zero values.
    if method in {"iqr", "mad"} and _should_log_transform(transformed, config):
        transformed = np.log1p(transformed)
        used_log = True

    # z-score is kept as an explicit method for comparison/backward
    # compatibility.  It does not use the robust fallback chain because z-score
    # is the requested legacy-style behavior.
    if method == "zscore":
        return _zscore_mask(numeric_col, valid, transformed, config)

    # If MAD is requested, try MAD first.  When MAD is zero/missing, fall back to
    # IQR so a column with usable quartiles can still be analyzed.
    if method == "mad":
        mask, reason = _mad_mask(numeric_col, valid, transformed, config, used_log)
        if mask is not None:
            return mask, "mad", reason
        mask, reason = _iqr_mask(numeric_col, valid, transformed, config, used_log)
        return mask, "iqr", reason

    # Default path: use IQR first because it is intuitive, robust to skew, and
    # easy to explain in meetings.  If IQR is unusable, try MAD as a backup.
    mask, reason = _iqr_mask(numeric_col, valid, transformed, config, used_log)
    if mask is not None:
        return mask, "iqr", reason
    mask, reason = _mad_mask(numeric_col, valid, transformed, config, used_log)
    return mask, "mad", reason


def _iqr_mask(numeric_col, valid, transformed, config, used_log):
    # Q1 and Q3 define the middle 50% of values.  Using quartiles instead of
    # mean/std makes the rule resistant to extreme values already present in
    # the data.
    q1 = transformed.quantile(0.25)
    q3 = transformed.quantile(0.75)

    # IQR is the spread of the middle half of the distribution.
    iqr = q3 - q1

    # If IQR is zero or missing, the column is too flat for an IQR threshold:
    # Q1 and Q3 are identical, so every small deviation would look suspicious.
    if pd.isna(iqr) or iqr == 0:
        return None, "zero_or_missing_iqr"

    # Standard Tukey-style fences.  The default multiplier is 1.5, but keeping
    # it in config lets experiments tune detector aggressiveness.
    lower = q1 - float(config["iqr_multiplier"]) * iqr
    upper = q3 + float(config["iqr_multiplier"]) * iqr

    # Re-expand the transformed valid values onto the original dataframe index
    # so the returned mask lines up with the original rows, including NaNs.
    transformed_full = _align_transformed(numeric_col, valid, transformed)

    # Values outside the fence are anomalies; missing/non-numeric rows stay
    # False after fillna below.
    mask = (transformed_full < lower) | (transformed_full > upper)

    # Preserve whether this was raw-space IQR or log-space IQR so structured
    # detector details can explain the decision.
    reason = "outside log-IQR range" if used_log else "outside IQR range"
    return mask.fillna(False), reason


def _mad_mask(numeric_col, valid, transformed, config, used_log):
    # MAD uses the median as the center, which is more robust than the mean when
    # the column already contains outliers.
    median = transformed.median()

    # Median absolute deviation is the median distance from the median.  It is
    # resistant to a small number of extreme values.
    mad = np.median(np.abs(transformed - median))

    # If every value is identical, or nearly identical after transformation,
    # MAD can be zero.  In that case modified z-scores would divide by zero.
    if pd.isna(mad) or mad == 0:
        return None, "zero_or_missing_mad"

    # 0.6745 rescales MAD so modified z-scores are comparable to standard
    # z-scores under a normal distribution.
    modified_z = 0.6745 * (transformed - median) / mad

    # Build a full-index Series of modified z-scores.  This preserves row
    # alignment with the original dataframe even though stats used only valid
    # numeric cells.
    transformed_full = pd.Series(index=numeric_col.index, dtype=float)
    transformed_full.loc[valid.index] = modified_z

    # Flag rows whose robust distance from the median exceeds the configured
    # threshold.  The default is intentionally less sensitive than raw z-score.
    mask = transformed_full.abs() > float(config["mad_multiplier"])
    reason = "outside log-MAD range" if used_log else "outside MAD range"
    return mask.fillna(False), reason


def _zscore_mask(numeric_col, valid, transformed, config):
    # z-score uses mean and standard deviation.  This is familiar but less
    # robust than IQR/MAD because the mean and std can be pulled by outliers.
    mean = transformed.mean()
    std = transformed.std()

    # A missing or zero standard deviation means the column has no measurable
    # spread, so z-score cannot produce meaningful distances.
    if pd.isna(std) or std == 0:
        return None, "zero_or_missing_standard_deviation", "zero_or_missing_standard_deviation"

    # Align transformed valid values back onto the original row index so the
    # mask returned to anomaly() can map directly to Buckaroo row IDs.
    transformed_full = _align_transformed(numeric_col, valid, transformed)

    # A row is anomalous when its absolute distance from the mean is greater
    # than threshold * standard deviation.
    mask = np.abs(transformed_full - mean) > float(config["zscore_threshold"]) * std
    return mask.fillna(False), "zscore", "outside z-score range"


def _align_transformed(numeric_col, valid, transformed):
    # Helper used by IQR and z-score paths.  The distribution statistics are
    # computed on valid numeric rows only, but the final boolean mask must have
    # the same index as the original column so row IDs are selected correctly.
    transformed_full = pd.Series(index=numeric_col.index, dtype=float)
    transformed_full.loc[valid.index] = transformed
    return transformed_full


def _should_log_transform(values: pd.Series, config: dict) -> bool:
    # log1p is only defined for values >= -1, and the interpretation for
    # negative values in arbitrary datasets is usually unclear.  To stay safe,
    # require all values to be non-negative before log-transforming.
    if values.empty or (values < 0).any():
        return False

    # Skew estimates and log-space fences are not reliable when a column has too
    # few distinct values.  This also avoids transforming low-cardinality codes.
    if values.nunique(dropna=True) < 10:
        return False

    # Use pandas skew to decide whether the distribution has a long tail.  The
    # absolute value catches both right-skew and left-skew, although log1p is
    # most useful for non-negative right-tailed values.
    skew = values.skew()

    # If skew is missing, do not transform.  Otherwise compare against the
    # shared configurable threshold from DETECTOR_CONFIG.
    return pd.notna(skew) and abs(float(skew)) >= float(config["log_skew_threshold"])

