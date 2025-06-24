import pandas as pd
def incomplete(data_frame):
    """
    Flags cells which have a low occurrence (< 3)
    :return:
    """
    error_map = {}

    for column in data_frame.columns[1:]:
        numeric_mask = pd.to_numeric(data_frame[column], errors='coerce').notna()
        if numeric_mask.sum() > 10: continue
        if data_frame[column].dtype == 'object':
            value_counts = data_frame[column].value_counts()
            rare_values = value_counts[value_counts < 3].index
            mask = data_frame[column].isin(rare_values)
            rare_ids = data_frame.loc[mask, 'ID'].tolist()
            if len(rare_ids) > 0:
                if column not in error_map:
                    error_map[column] = {}
                for rare_id in rare_ids:
                    error_map[column][rare_id] = "incomplete"
    return error_map