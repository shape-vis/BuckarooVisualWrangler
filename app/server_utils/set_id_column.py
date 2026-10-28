"""
Set the ID column in a DataFrame, ensuring it is numeric and unique.
If an ID column already exists but is not numeric or unique, it will be renamed and a new ID column will be added.
If no ID column exists, a new numeric ID column will be created starting from 1.
If the ID column is already numeric and unique, it will be moved to the front of the DataFrame.
"""

import pandas as pd


def set_id_column(table: pd.DataFrame) -> pd.DataFrame:
    col_names = table.columns.tolist()
    has_id = "ID" in col_names

    if not has_id:
        # Add new numeric ID column starting from 1
        table = table.copy()
        table.insert(0, "ID", range(1, len(table) + 1))
        return table

    id_values = table["ID"]
    is_numeric = pd.to_numeric(id_values, errors='coerce').notnull().all()
    is_unique = id_values.is_unique

    if not is_numeric or not is_unique:
        # Rename existing ID column and add new numeric ID
        table = table.copy()
        table.rename(columns={"ID": "Original_ID"}, inplace=True)
        table.insert(0, "ID", range(1, len(table) + 1))
        return table

    # ID is good, move to front if not already
    if col_names[0] != "ID":
        reordered = ["ID"]
        for col_name in col_names:
            if col_name != "ID":
                reordered.append(col_name)
        return table[reordered]

    return table