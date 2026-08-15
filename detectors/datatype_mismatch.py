import pandas as pd

from detectors.common import error_value, is_missing_value, merged_config


TRUE_VALUES = {"true", "t", "yes", "y"}
FALSE_VALUES = {"false", "f", "no", "n"}


def datatype_mismatch(data_frame, include_details=False, config=None):
    """
    Detect values that fail the inferred parse-based column type.

    Instead of comparing raw Python types from CSV-loaded values, this detector
    infers whether a non-missing column is mostly numeric, date-like, or boolean.
    It only flags failures when one parse type is dominant enough.
    """
    config = merged_config(config)
    threshold = float(config["type_confidence_threshold"])
    error_map = {}
    id_values = data_frame["ID"].to_numpy()

    for column in data_frame.columns[1:]:
        series = data_frame[column]
        non_missing_mask = ~series.map(is_missing_value)
        valid = series[non_missing_mask]
        if valid.empty:
            continue

        inferred = _infer_column_type(valid, threshold)
        if inferred is None:
            continue

        expected_type, confidence = inferred
        mismatch_mask = non_missing_mask & ~series.map(lambda value: _parses_as(value, expected_type))
        if mismatch_mask.any():
            error_map[column] = {
                int(row_id): error_value(
                    "type_mismatch",
                    include_details=include_details,
                    legacy_error_type="mismatch",
                    severity="error",
                    confidence="high" if confidence >= 0.95 else "medium",
                    reason=f"value does not parse as inferred {expected_type} column",
                    expected_type=expected_type,
                    column_type_confidence=round(float(confidence), 4),
                )
                for row_id in id_values[mismatch_mask.to_numpy()]
            }

    return error_map


def _infer_column_type(valid: pd.Series, threshold: float):
    candidates = {
        "numeric": valid.map(_is_numeric).mean(),
        "date": valid.map(_is_date_like).mean(),
        "boolean": valid.map(_is_boolean_like).mean(),
    }
    expected_type, confidence = max(candidates.items(), key=lambda item: item[1])
    if confidence < threshold:
        return None
    return expected_type, float(confidence)


def _parses_as(value, expected_type: str) -> bool:
    if is_missing_value(value):
        return True
    if expected_type == "numeric":
        return _is_numeric(value)
    if expected_type == "date":
        return _is_date_like(value)
    if expected_type == "boolean":
        return _is_boolean_like(value)
    return True


def _is_numeric(value) -> bool:
    try:
        return pd.notna(pd.to_numeric(value, errors="coerce"))
    except Exception:
        return False


def _is_boolean_like(value) -> bool:
    text = str(value).strip().lower()
    return text in TRUE_VALUES or text in FALSE_VALUES


def _is_date_like(value) -> bool:
    text = str(value).strip()
    if not any(separator in text for separator in ("-", "/", ":")):
        return False
    parsed = pd.to_datetime(pd.Series([value]), errors="coerce", format="mixed")
    return bool(parsed.notna().iloc[0])
