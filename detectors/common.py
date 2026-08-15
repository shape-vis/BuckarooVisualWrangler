"""Shared detector defaults and formatting helpers.

This module is intentionally small and centralized.  The individual detector
files import these helpers so that they all agree on:

- which text markers count as missing values,
- which threshold values should be used by default, and
- how detector outputs should be formatted for old and new callers.

Keeping those choices in one file makes the detector behavior easier to
explain, test, and tune.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


# Canonical string markers that should be treated the same as null/NaN.
#
# Real datasets often encode missingness as ordinary text rather than as an
# actual null value.  For example, one CSV may use "N/A", another may use "?",
# and another may use "unknown".  Normalizing those cases here prevents each
# detector from inventing its own missing-value definition.
#
# All markers are stored lowercase because is_missing_value() lowercases input
# before checking membership in this set.
MISSING_MARKERS = {
    "",
    "?",
    "-",
    "na",
    "n/a",
    "nan",
    "none",
    "null",
    "undefined",
    "unknown",
}


# Shared default tuning parameters for the detector suite.
#
# These values are deliberately collected in a single dictionary so experiments
# or UI controls can override detector behavior without rewriting each detector.
# For example, a stricter anomaly detector could lower "iqr_multiplier", while
# a more conservative rare-value detector could raise "rare_value_min_count".
DETECTOR_CONFIG = {
    # Default numeric anomaly method.  IQR is robust to skewed distributions and
    # outliers because it uses quartiles instead of mean and standard deviation.
    "anomaly_method": "iqr",

    # IQR rule multiplier.  A common outlier rule flags values below
    # Q1 - 1.5*IQR or above Q3 + 1.5*IQR.
    "iqr_multiplier": 1.5,

    # Median absolute deviation multiplier, kept as a configurable alternative
    # for distributions where median-based distance is preferable.
    "mad_multiplier": 3.5,

    # Z-score threshold, kept for comparison/backward compatibility with the
    # older anomaly approach.
    "zscore_threshold": 3.0,

    # If skew is above this threshold, detectors can choose log-aware handling.
    # This is useful for columns such as salary, population, or price.
    "log_skew_threshold": 2.0,

    # Minimum confidence needed before the type mismatch detector treats one
    # inferred type as the expected column type.
    "type_confidence_threshold": 0.9,

    # A category must appear fewer than this many times to be considered rare.
    # Example: if this is 3, then values appearing 1 or 2 times are rare, while
    # values appearing 3 or more times are treated as common enough.
    "rare_value_min_count": 3,

    # Rare-value detection only applies when the column has at most this many
    # unique values.  This prevents ID-like or free-text columns from producing
    # useless rare-value warnings, because those columns naturally have many
    # one-off values.
    "rare_value_max_unique": 80,

    # Rare-value detection only applies when the unique-value count is not too
    # large compared with the row count.  A ratio of 0.5 means that in a column
    # with 100 rows, rare-value detection is allowed only if there are 50 or
    # fewer unique values.
    "rare_value_max_cardinality_ratio": 0.5,

    # Rare-value detection only runs when there are at least this many
    # non-missing rows.  With tiny samples, a value appearing once may be normal
    # rather than suspicious, so the detector waits for enough evidence.
    "rare_value_min_rows": 20,
}


def merged_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return detector defaults with optional caller overrides applied.

    Detectors should call this instead of reading DETECTOR_CONFIG directly when
    they accept custom parameters.  The function copies DETECTOR_CONFIG first so
    caller overrides do not mutate the global defaults for later detector runs.

    Example:
        merged_config({"iqr_multiplier": 2.0})

    That keeps every default unchanged except "iqr_multiplier".
    """
    result = dict(DETECTOR_CONFIG)
    if config:
        result.update(config)
    return result


def infer_detector_config(data_frame: pd.DataFrame, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Infer detector settings from broad dataset shape, then apply overrides.

    This is the adaptive caller layer for detector thresholds.  The goal is not
    to invent a different detector for every column; the individual detectors
    still contain their own column-level guards.  Instead, this function makes a
    few conservative dataset-level adjustments before detector execution.

    Current adaptation rules:

    - Very small datasets suppress rare-value detection because frequency is
      not reliable with little evidence.
    - Large datasets allow a slightly larger rare-value count cutoff because a
      value appearing only a handful of times in thousands of rows can still be
      suspicious.
    - Text-heavy/high-cardinality datasets make rare-value detection more
      conservative so IDs, names, and free-text fields do not dominate warnings.
    - Strongly skewed numeric datasets lower the log-skew trigger, encouraging
      robust log-aware anomaly handling.
    - Messy mixed-type datasets raise the type-confidence threshold so the type
      mismatch detector does not force a type onto ambiguous columns.

    Any explicit config values supplied by the caller are applied last.  That
    keeps user/experiment overrides in control.
    """
    result = merged_config()
    profile = _dataset_profile(data_frame)
    row_count = profile["row_count"]

    if row_count < 50:
        # With tiny samples, a value appearing once or twice may simply be a
        # normal consequence of small data.  Raising the minimum row requirement
        # above the current row count effectively disables rare-value warnings.
        result["rare_value_min_rows"] = max(int(result["rare_value_min_rows"]), row_count + 1)
    elif row_count >= 1000:
        # In larger datasets, an ultra-low-frequency category can be meaningful
        # even if it appears more than twice.  Cap the adaptive cutoff so it does
        # not become overly aggressive on very large uploads.
        adaptive_min_count = min(10, max(3, int(round(row_count * 0.002))))
        result["rare_value_min_count"] = max(int(result["rare_value_min_count"]), adaptive_min_count)

    if profile["text_column_count"] and profile["high_cardinality_text_fraction"] >= 0.5:
        # If many text columns look ID-like or free-form, rare-value warnings
        # should be harder to trigger globally.  The incomplete detector still
        # performs per-column checks after this.
        result["rare_value_max_unique"] = min(int(result["rare_value_max_unique"]), 50)
        result["rare_value_max_cardinality_ratio"] = min(
            float(result["rare_value_max_cardinality_ratio"]),
            0.35,
        )

    if profile["numeric_column_count"] and profile["skewed_numeric_fraction"] >= 0.5:
        # Keep IQR as the robust default, but let log-aware handling activate a
        # little earlier when skew is common across numeric columns.
        result["anomaly_method"] = "iqr"
        result["log_skew_threshold"] = min(float(result["log_skew_threshold"]), 1.5)

    if profile["typed_column_count"] and profile["weak_type_fraction"] >= 0.35:
        # If many columns have only a weak dominant parse type, be more
        # conservative before calling any minority value a type mismatch.
        result["type_confidence_threshold"] = max(float(result["type_confidence_threshold"]), 0.95)

    if config:
        result.update(config)
    return result


def _dataset_profile(data_frame: pd.DataFrame) -> dict[str, Any]:
    """Summarize dataset shape for adaptive detector configuration."""
    if data_frame is None or data_frame.empty:
        return {
            "row_count": 0,
            "numeric_column_count": 0,
            "skewed_numeric_fraction": 0.0,
            "text_column_count": 0,
            "high_cardinality_text_fraction": 0.0,
            "typed_column_count": 0,
            "weak_type_fraction": 0.0,
        }

    columns = [column for column in data_frame.columns if column != "ID"]
    row_count = int(len(data_frame))
    numeric_columns = 0
    skewed_numeric_columns = 0
    text_columns = 0
    high_cardinality_text_columns = 0
    typed_columns = 0
    weak_type_columns = 0

    for column in columns:
        series = data_frame[column]
        valid = series[~series.map(is_missing_value)]
        if valid.empty:
            continue

        numeric = pd.to_numeric(valid, errors="coerce")
        numeric_ratio = float(numeric.notna().mean()) if len(valid) else 0.0
        if numeric_ratio >= 0.8 and numeric.notna().sum() >= 10:
            numeric_columns += 1
            numeric_values = numeric.dropna().astype(float)
            if (
                not numeric_values.empty
                and numeric_values.nunique(dropna=True) >= 10
                and (numeric_values >= 0).all()
            ):
                skew = numeric_values.skew()
                if pd.notna(skew) and abs(float(skew)) >= float(DETECTOR_CONFIG["log_skew_threshold"]):
                    skewed_numeric_columns += 1
            continue

        if valid.dtype == "object":
            text_columns += 1
            normalized = valid.astype(str).str.strip().str.lower()
            unique_count = int(normalized.nunique(dropna=True))
            cardinality_ratio = unique_count / max(1, len(valid))
            if (
                unique_count > int(DETECTOR_CONFIG["rare_value_max_unique"])
                or cardinality_ratio > float(DETECTOR_CONFIG["rare_value_max_cardinality_ratio"])
            ):
                high_cardinality_text_columns += 1

            dominant_type_confidence = max(
                numeric_ratio,
                float(valid.map(_is_date_like).mean()),
                float(valid.map(_is_boolean_like).mean()),
            )
            if dominant_type_confidence > 0:
                typed_columns += 1
                if 0.5 <= dominant_type_confidence < float(DETECTOR_CONFIG["type_confidence_threshold"]):
                    weak_type_columns += 1

    return {
        "row_count": row_count,
        "numeric_column_count": numeric_columns,
        "skewed_numeric_fraction": _safe_fraction(skewed_numeric_columns, numeric_columns),
        "text_column_count": text_columns,
        "high_cardinality_text_fraction": _safe_fraction(high_cardinality_text_columns, text_columns),
        "typed_column_count": typed_columns,
        "weak_type_fraction": _safe_fraction(weak_type_columns, typed_columns),
    }


def _is_boolean_like(value: Any) -> bool:
    text = str(value).strip().lower()
    return text in {"true", "t", "yes", "y", "false", "f", "no", "n"}


def _is_date_like(value: Any) -> bool:
    text = str(value).strip()
    if not any(separator in text for separator in ("-", "/", ":")):
        return False
    parsed = pd.to_datetime(pd.Series([value]), errors="coerce", format="mixed")
    return bool(parsed.notna().iloc[0])


def _safe_fraction(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0


def is_missing_value(value: Any, missing_markers: set[str] | None = None) -> bool:
    """Return True when a value should be interpreted as missing.

    The check has two layers:

    1. pandas-level missingness, such as None, NaN, and pd.NA;
    2. string marker missingness, such as "", "?", "n/a", or "unknown".

    The optional missing_markers argument supports future user agency.  A caller
    can pass a custom marker set when the user decides that a dataset-specific
    value, such as "not supplied", should also count as missing.
    """
    # First handle true null-like values using pandas, which correctly catches
    # Python None, floating NaN, and pandas' own nullable scalar values.
    if pd.isna(value):
        return True

    # Then handle text encodings of missingness.  Whitespace and capitalization
    # should not matter, so " N/A ", "n/a", and "N/A" are treated identically.
    markers = missing_markers or MISSING_MARKERS
    return str(value).strip().lower() in markers


def error_value(
    error_type: str,
    *,
    include_details: bool = False,
    legacy_error_type: str | None = None,
    severity: str = "warning",
    confidence: str = "medium",
    reason: str = "",
    **extra,
):
    """Format one detector result as either a legacy label or rich metadata.

    The project has two output needs:

    - Existing UI/code paths expect simple string labels like "missing".
    - Newer clustering and explanation work benefits from richer metadata:
      severity, confidence, reason, thresholds, parsed types, and so on.

    include_details controls which format is returned.  This lets detectors add
    better metadata without breaking older call sites.
    """
    # Backward-compatible mode: return only the simple legacy string.  If a
    # specific legacy label is supplied, prefer it; otherwise use error_type.
    if not include_details:
        return legacy_error_type or error_type

    # Detailed mode: return a dictionary with a stable core schema.  Detectors
    # can add detector-specific fields through **extra below.
    result = {
        "error_type": error_type,
        "legacy_error_type": legacy_error_type or error_type,
        "severity": severity,
        "confidence": confidence,
        "reason": reason,
    }

    # Merge extra metadata last so detectors can attach contextual information
    # such as thresholds, observed values, expected types, or confidence scores.
    result.update(extra)
    return result
