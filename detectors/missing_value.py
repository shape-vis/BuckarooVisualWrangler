from detectors.common import MISSING_MARKERS, error_value, is_missing_value


def missing_value(data_frame, include_details=False, missing_markers=None):
    """
    Detect missing cells using the shared Buckaroo missing-value definition.

    The default return shape preserves the legacy detector contract:
    {column: {row_id: "missing"}}. Set include_details=True to receive
    structured records with severity, confidence, and reason.
    """
    error_map = {}
    markers = missing_markers or MISSING_MARKERS
    id_values = data_frame["ID"].to_numpy()

    for column in data_frame.columns:
        if column == "ID":
            continue
        mask = data_frame[column].map(lambda value: is_missing_value(value, markers)).to_numpy()
        if mask.any():
            error_map[column] = {
                int(row_id): error_value(
                    "missing",
                    include_details=include_details,
                    severity="error",
                    confidence="high",
                    reason="value matches shared missing-value markers",
                )
                for row_id in id_values[mask]
            }

    return error_map
