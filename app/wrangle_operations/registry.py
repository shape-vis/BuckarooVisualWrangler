from app.wrangle_operations.delete_column import DeleteColumnOperation
from app.wrangle_operations.delete_rows import DeleteRowsOperation
from app.wrangle_operations.impute import ImputeOperation


# Central dispatch table: Delta only stores an operation name, and this map
# gives that name the object that knows how to generate Pandas and SQL.
_OPERATIONS = {
    "delete": DeleteRowsOperation(),
    "impute": ImputeOperation(),
    "impute_x": ImputeOperation(),
    "impute_y": ImputeOperation(),
    "delete-column": DeleteColumnOperation(),
}


def get_operation(name: str):
    """Return the operation implementation for a stored operation name."""
    return _OPERATIONS.get(name)
