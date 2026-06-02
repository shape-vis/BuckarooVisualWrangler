from abc import ABC, abstractmethod
from typing import Any, Dict


class WrangleOperation(ABC):
    """
    Common interface for every wrangle operation.

    Each operation must know how to express itself in two worlds:
      - Pandas code, used by the export script.
      - SQL view creation, used by the live app and previews.
    Keeping those methods together makes it harder for the export behavior and
    database behavior to drift apart.
    """

    @abstractmethod
    def pandas_code(self, parameters: Dict[str, Any]) -> str:
        """Return Python code that performs this wrangle on a DataFrame named df."""
        pass

    @abstractmethod
    def create_view(self, conn, engine, source_table: str, target_view: str, parameters: Dict[str, Any]) -> bool:
        """Create a PostgreSQL view representing this wrangle."""
        pass

    def operation_result(self, engine, source_table: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Optional metadata for API responses after a wrangle (e.g. remaining column count)."""
        return {}
