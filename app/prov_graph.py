#March 2026 - Th

class ProvGraph:
    """
    The basic structure is a DAG, consisting of PNode objects connected by Edge Object
    """
    def __init__(self, root_table_name: str):
        self.root = None
        self.parent_nodes = []


