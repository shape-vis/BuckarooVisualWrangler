import pandas as pd

from detectors.common import error_value, is_missing_value, merged_config


def incomplete(data_frame, numeric_cache=None, include_details=False, config=None):
    """
    Detect suspicious rare categorical values.

    Historically this detector returned "incomplete". The implementation now
    treats these as rare-value warnings because rare does not always mean wrong.
    The legacy error label is preserved by default for existing UI/app flows.
    """
    config = merged_config(config)
    error_map = {}
    id_values = data_frame["ID"].to_numpy()

    for column in data_frame.columns[1:]:
        series = data_frame[column]
        valid = series[~series.map(is_missing_value)]
        if not _should_check_rare_values(column, valid, numeric_cache, config):
            continue

        normalized = valid.astype(str).str.strip().str.lower()
        value_counts = normalized.value_counts(dropna=True)
        rare_values = set(
            value_counts[value_counts <= int(config["rare_value_min_count"])].index.tolist()
        )
        if not rare_values:
            continue

        mask = series.astype(str).str.strip().str.lower().isin(rare_values).to_numpy()
        if mask.any():
            error_map[column] = {
                int(row_id): error_value(
                    "rare_value",
                    include_details=include_details,
                    legacy_error_type="incomplete",
                    severity="warning",
                    confidence="low",
                    reason="value is uncommon in a low/medium-cardinality categorical column",
                    max_count=int(config["rare_value_min_count"]),
                )
                for row_id in id_values[mask]
            }

    return error_map


def _should_check_rare_values(column, valid, numeric_cache, config):
    if len(valid) < int(config["rare_value_min_rows"]):
        return False
    if valid.empty or valid.dtype != "object":
        return False

    numeric_ratio = _numeric_ratio(column, valid, numeric_cache)
    if numeric_ratio >= 0.8:
        return False

    unique_count = int(valid.astype(str).str.strip().str.lower().nunique(dropna=True))
    if unique_count <= 1:
        return False
    if unique_count > int(config["rare_value_max_unique"]):
        return False

    cardinality_ratio = unique_count / max(1, len(valid))
    return cardinality_ratio <= float(config["rare_value_max_cardinality_ratio"])


def _numeric_ratio(column, valid, numeric_cache):
    if numeric_cache is not None and column in numeric_cache:
        numeric = numeric_cache[column].loc[valid.index]
    else:
        numeric = pd.to_numeric(valid, errors="coerce")
    return float(numeric.notna().mean()) if len(valid) else 0.0
