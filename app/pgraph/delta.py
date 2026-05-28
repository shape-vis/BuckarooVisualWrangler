from typing import Dict, Any

from app.wrangle_operations import get_operation

"""
Defines a delta object that represents a single wrangling operation (a delta).
"""

class Delta:

    def __init__(self, operation: str, parameters: Dict[str, Any], pandas_code: str = ""):
        """
        This is the definition method for the Delta class. It is used to create a new delta object.
        """
        self.operation = operation
        self.parameters = parameters
        self.pandas_code = pandas_code or self.to_pandas_code()

    def to_pandas_code(self) -> str:
        operation = get_operation(self.operation)
        if operation is None:
            return f"# Unknown operation: {self.operation}"
        return operation.pandas_code(self.parameters)

    def create_view(self, conn, engine, source_table: str, target_view: str) -> bool:
        operation = get_operation(self.operation)
        if operation is None:
            return False
        return operation.create_view(conn, engine, source_table, target_view, self.parameters)

    def __json__(self):
        """
        This is the json method for the Delta class. It is used to convert a delta object to a json object.
        """
        return {
            "operation": self.operation,
            "parameters": self.parameters,
            "pandas_code": self.pandas_code
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]):
        """
        This is the from_dict method for the Delta class. It is used to create a delta object from a dictionary.
        """
        return Delta(
            operation=data.get("operation", "unknown"),
            parameters=data.get("parameters", {}),
            pandas_code=data.get("pandas_code", "")
        )
