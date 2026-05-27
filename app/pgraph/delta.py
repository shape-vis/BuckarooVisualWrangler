from typing import Dict, Any, List

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
        self.pandas_code = pandas_code

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
