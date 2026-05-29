from abc import ABC, abstractmethod
from typing import Any, Dict


class WrangleOperation(ABC):
    """Behavior that is specific to a wrangle operation."""

    @abstractmethod
    def pandas_code(self, parameters: Dict[str, Any]) -> str:
        pass

    @abstractmethod
    def create_view(self, conn, engine, source_table: str, target_view: str, parameters: Dict[str, Any]) -> bool:
        pass
