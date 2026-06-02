from typing import Dict, Any

from app.pgraph.delta import Delta

def map_to_pandas(operation: str, parameters: Dict[str, Any]) -> str:
    """
    Maps a wrangling operation and its parameters to equivalent Pandas code.

    This is a small compatibility wrapper. The real mapping now lives on
    Delta, so tests and older callers can ask this helper for Pandas code while
    the app still uses the same Delta logic as the provenance graph.
    """
    return Delta(operation, parameters).pandas_code
