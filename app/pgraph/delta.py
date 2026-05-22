from typing import Dict, Any, List

class Delta:
    """
    Represents a single wrangling operation (a delta).
    """
    def __init__(self, operation: str, parameters: Dict[str, Any], pandas_code: str = ""):
        self.operation = operation
        self.parameters = parameters
        self.pandas_code = pandas_code

    def __json__(self):
        return {
            "operation": self.operation,
            "parameters": self.parameters,
            "pandas_code": self.pandas_code
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]):
        return Delta(
            operation=data.get("operation", "unknown"),
            parameters=data.get("parameters", {}),
            pandas_code=data.get("pandas_code", "")
        )
