from typing import Dict, Any

from app.wrangle_operations import get_operation
from app.wrangle_operations.sql_utils import drop_view, promote_errors_preview

"""
Delta storage for one wrangling step.

In the app, a user action such as "delete these rows" or "impute this
column" is stored as a Delta. The Delta keeps the operation name plus the
exact parameters needed to replay it later. That is what lets the app do
three related things from one source of truth:
  1. create the SQL preview/current table in PostgreSQL,
  2. export an equivalent Pandas script, and
  3. serialize the provenance graph for the UI.
"""

class Delta:

    def __init__(self, operation: str, parameters: Dict[str, Any], pandas_code: str = ""):
        """
        Create a new delta.

        operation is the wrangle type, for example "delete", "impute", or
        "delete-column". parameters stores the exact user selection, such as
        row IDs or a column name. If pandas_code is blank, we generate the
        export code from the operation registry.
        """
        self.operation = operation
        self.parameters = parameters
        self.pandas_code = pandas_code or self.to_pandas_code()

    def to_pandas_code(self) -> str:
        """Ask the operation registry for the Pandas version of this wrangle."""
        operation = get_operation(self.operation)
        if operation is None:
            return f"# Unknown operation: {self.operation}"
        return operation.pandas_code(self.parameters)

    def create_view(self, conn, engine, source_table: str, target_view: str) -> bool:
        """Ask the operation registry to build the SQL view for this wrangle."""
        operation = get_operation(self.operation)
        if operation is None:
            return False
        return operation.create_view(conn, engine, source_table, target_view, self.parameters)

    def operation_result(self, engine, source_table: str) -> Dict[str, Any]:
        """Return optional metadata, such as remaining column count."""
        operation = get_operation(self.operation)
        if operation is None:
            return {}
        return operation.operation_result(engine, source_table, self.parameters)

    def promote_from_preview(
        self,
        conn,
        engine,
        source_table: str,
        preview_table: str,
        target_table: str,
    ) -> bool:
        """
        Materialize the wrangle as target_table view from source_table, promote the
        errors preview table, and drop the temporary preview view.

        During preview, the UI shows temporary tables named like
        <table>_preview_delete. When the user clicks Execute, this method turns
        the chosen preview into the next permanent graph node.
        """
        view_created = self.create_view(conn, engine, source_table, target_table)
        if view_created:
            # The data table is a view, but the error table is a physical table
            # produced by Pandas detectors. It gets renamed to match the new
            # graph node.
            promote_errors_preview(conn, preview_table, target_table)
            drop_view(conn, preview_table)
        return view_created

    def __json__(self):
        """
        Convert this object to JSON-friendly data for the provenance graph.
        """
        return {
            "operation": self.operation,
            "parameters": self.parameters,
            "pandas_code": self.pandas_code
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]):
        """
        Rebuild a Delta from saved JSON.

        This matters when a graph is restored: we want the loaded node to keep
        the same operation, parameters, and export code it had before.
        """
        return Delta(
            operation=data.get("operation", "unknown"),
            parameters=data.get("parameters", {}),
            pandas_code=data.get("pandas_code", "")
        )
