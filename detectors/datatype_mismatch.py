import re

def datatype_mismatch(data_frame):
    """
    checks to see if a cell in the datatable has a different type than it's column majority type
    :return:
    """
    error_map = {}

    def classify_value(value):
        if value is None:
            return None
        if hasattr(value, "strip"):
            stripped = value.strip()
            if stripped == "":
                return None
            lowered = stripped.lower()
            if lowered in {"null", "undefined"}:
                return None
            if re.fullmatch(r'^[+-]?(\d+(\.\d+)?|\.\d+)$', stripped):
                return "numeric"
            if re.fullmatch(r'^(true|false|t|f|yes|no|y|n)$', lowered):
                return "boolean"
            if (
                re.fullmatch(r'^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?$', stripped)
                or re.fullmatch(r'^\d{1,2}/\d{1,2}/\d{4}$', stripped)
                or re.fullmatch(r'^\d{4}/\d{1,2}/\d{1,2}$', stripped)
            ):
                return "datetime"
            return "text"
        return type(value).__name__

    type_priority = {"numeric": 1, "datetime": 2, "boolean": 3, "text": 4}

    for column in data_frame.columns[1:]:
        value_counts = data_frame[column].value_counts(dropna=False)
        type_count = {}
        type_key = {}

        for key, value in value_counts.items():
            type_of_key = classify_value(key)
            if type_of_key is None:
                continue
            if type_of_key in type_count:
                type_count[type_of_key] += value
                type_key[type_of_key].append(key)
            else:
                type_count[type_of_key] = value
                type_key[type_of_key] = [key]

        if not type_count:
            continue

        majority_type = sorted(
            type_count.items(),
            key=lambda item: (-item[1], type_priority.get(item[0], 99))
        )[0][0]

        mismatched_entries = []
        for category, values in type_key.items():
            if category != majority_type:
                mismatched_entries.extend(values)

        mask = data_frame[column].isin(mismatched_entries)
        mismatched_ids = data_frame.loc[mask, 'ID'].tolist()

        if len(mismatched_ids) > 0:
            if column not in error_map:
                error_map[column] = {}
            for mismatched_id in mismatched_ids:
                error_map[column][mismatched_id] = "mismatch"
    return error_map
