from typing import Dict, Any

from app.pgraph.delta import Delta

def map_to_pandas(operation: str, parameters: Dict[str, Any]) -> str:
    """
    Maps a wrangling operation and its parameters to equivalent Pandas code.
    """
    return Delta(operation, parameters).pandas_code
