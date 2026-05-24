from typing import Dict, Any, List

def map_to_pandas(operation: str, parameters: Dict[str, Any]) -> str:
    """
    Maps a wrangling operation and its parameters to equivalent Pandas code.
    """
    if operation == "delete":
        row_ids = parameters.get("row_ids", [])
        return f"df = df[~df['ID'].isin({row_ids})]"
    
    elif operation == "impute" or operation == "impute_x" or operation == "impute_y":
        col = parameters.get("col")
        row_ids = parameters.get("row_ids", [])
        if not col:
            return "# Impute operation missing column"
        
        # We need to know if it's numeric or categorical to decide between mean() and mode()
        # For the sake of the snippet, we can use a generic approach or assume column type
        # In Buckaroo, we handle both.
        return (
            f"if df['{col}'].dtype.kind in 'iufc':\n"
            f"    fill_val = df['{col}'].mean()\n"
            f"else:\n"
            f"    fill_val = df['{col}'].mode()[0] if not df['{col}'].mode().empty else None\n"
            f"df.loc[df['ID'].isin({row_ids}), '{col}'] = df.loc[df['ID'].isin({row_ids}), '{col}'].fillna(fill_val)"
        )
    
    elif operation == "delete-column":
        column = parameters.get("column")
        return f"df.drop(columns=['{column}'], inplace=True)"

    return f"# Unknown operation: {operation}"
