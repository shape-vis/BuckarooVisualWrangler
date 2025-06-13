def datatype_mismatch(data_frame):
    """
    checks to see if a cell in the datatable has a different type than it's column majority type
    :return:
    """
    error_map = {}

    for column in data_frame.columns[1:]:
        value_counts = data_frame[column].value_counts()
        type_count = {}

        for key, value in value_counts.items():
            type_of_key = type(key).__name__
            if type_of_key in type_count:
                type_count[type_of_key] += value
            else:
                type_count[type_of_key] = value

        majority_type = None
        majority_count = 0

        for key, value in type_count.items():
            if value == majority_count and (key == "int" or key == "float"):
                majority_type = key
                majority_count = value
            elif value > majority_count:
                majority_count = value
                majority_type = key

        mismatched_categories = [key for key in value_counts.index if type(key).__name__ != majority_type]
        mask = data_frame[column].isin(mismatched_categories)
        mismatched_ids = data_frame.loc[mask, 'ID'].tolist()

        if len(mismatched_ids) > 0:
            if column not in error_map:
                error_map[column] = {}
            for mismatched_id in mismatched_ids:
                error_map[column][mismatched_id] = "mismatch"

    return error_map