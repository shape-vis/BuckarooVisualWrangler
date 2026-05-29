from app.wrangle_operations.delete_column import DeleteColumnOperation
from app.wrangle_operations.delete_rows import DeleteRowsOperation
from app.wrangle_operations.impute import ImputeOperation


_OPERATIONS = {
    "delete": DeleteRowsOperation(),
    "impute": ImputeOperation(),
    "impute_x": ImputeOperation(),
    "impute_y": ImputeOperation(),
    "delete-column": DeleteColumnOperation(),
}


def get_operation(name: str):
    return _OPERATIONS.get(name)
